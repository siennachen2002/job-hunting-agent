"""The learning loop on made-up posts, in a throwaway profile and database: no model, no network, nothing of yours touched.

    python3 tests/improve_test.py
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
tmp = Path(tempfile.mkdtemp())
shutil.copytree(ROOT / "profile.example", tmp / "profile")
os.environ.update(JHA_PROFILE=str(tmp / "profile"), JHA_DB=str(tmp / "t.sqlite"))
sys.path.insert(0, str(ROOT))
from agent import config, db, improve, learn, scoring  # noqa: E402

assert str(config.DB_PATH).startswith(str(tmp)) and str(config.PROFILE_DIR).startswith(str(tmp))


def check(name, got, want):
    if got != want:
        raise SystemExit(f"FAIL {name}: got {got!r}, want {want!r}")


con = db.connect(); learn.init(con)
dims = scoring.dimensions()   # role 35, level 25, background 25, sector 15


def post(i, title, company, verdict, role, level, background, sector, at="2026-10-01T00:00:00+00:00"):
    raw = {"dims": [{"key": k, "score": v} for k, v in zip(("role", "level", "background", "sector"), (role, level, background, sector))]}
    total, status, sc = scoring.finalize(None, {"title": title, "company": company, "description": ""}, raw, "test", {"preferences": "x"})
    for d in sc["dims"]:   # the made-up scores have no quotes: keep them as given
        d["score"] = dict(zip(("role", "level", "background", "sector"), (role, level, background, sector)))[d["key"]]
    total = scoring.total({d["key"]: d["score"] for d in sc["dims"]}, dims)
    sc.update(score=total, scored_at=at)
    con.execute("INSERT INTO jobs(id, source, company, title, status, score, score_json) VALUES (?,?,?,?,?,?,?)",
                (i, "greenhouse", company, title, status, total, json.dumps(sc)))
    if verdict:
        con.execute("INSERT INTO verdicts(job_id, verdict, reason, at, score, score_json) VALUES (?,?,?,?,?,?)",
                    (i, verdict, "", at, total, json.dumps(sc)))


# You like junior roles in any sector and say Nope to senior roles in your favourite sectors: Level matters more than
# the weights say, Sector less.
post(1, "Junior Product Designer", "A", "good", 3, 5, 3, 2)
post(2, "Associate Designer", "B", "good", 3, 5, 3, 1)
post(3, "Product Designer", "C", "good", 3, 4, 3, 2)
post(4, "Senior Staff Designer", "D", "nope", 5, 1, 3, 5)
post(5, "Senior Staff Product Designer", "E", "nope", 5, 2, 3, 5)
post(6, "Lead Designer", "F", "nope", 4, 2, 3, 5)
con.commit()

rows = improve.judged(con)
now = improve.agreement_of(rows)
w, then = improve.best_weights(rows, dims)
check("today's weights rank them badly", now < 50, True)
check("weights help", then - now >= improve.CLEAR and w["level"] > 25, True)
check("weights sum to 100", sum(w.values()), 100)
check("nope-only words", {"senior", "staff", "senior staff"} <= {x for x, _ in improve.nope_only_words(rows)}, True)

# a watched company whose postings never pass the prefilter
co = config.companies()[0]["name"]
for i in range(100, 100 + improve.MIN_SEEN):
    con.execute("INSERT INTO jobs(id, source, company, title, status, score_reason) VALUES (?,?,?,?,?,?)",
                (i, "greenhouse", co, "Backend Engineer", "skipped", "prefilter: no role title word"))
con.commit()
check("quiet source", [y["source"] for y in improve.quiet_sources(improve.source_yield(con))], [co])

made = improve.suggest(con)
kinds = sorted(r["kind"] for r in con.execute("SELECT kind FROM proposals WHERE status='pending'"))
check("suggestions", kinds, ["drop_titles", "source_off", "weights"])
check("never twice", improve.suggest(con), 0)

# apply the weights: preferences change in place, waiting posts get new totals, the outcome waits for new verdicts
pid = con.execute("SELECT id FROM proposals WHERE kind='weights'").fetchone()[0]
post(7, "Designer", "G", None, 4, 5, 3, 1); con.commit()
before7 = con.execute("SELECT score FROM jobs WHERE id=7").fetchone()[0]
learn.apply(con, pid)
check("weights written", {d["key"]: d["weight"] for d in scoring.dimensions()}, w)
check("waiting post re-totalled", con.execute("SELECT score FROM jobs WHERE id=7").fetchone()[0] > before7, True)
check("too early", improve.outcomes(con)[0]["verdict"], "too_early")
# three more judged after the change, ranked right: agreement after is read
for i, (v, lv, sec) in enumerate([("good", 5, 1), ("nope", 1, 5), ("good", 4, 2)], start=8):
    post(i, "Designer", "H", v, 3, lv, 3, sec, at="2099-01-01T00:00:00+00:00")
con.commit()
o = improve.outcomes(con)[0]
check("outcome read", (o["metric"], o["judged_after"], o["after"]), ("agreement", 3, 100))
learn.revert(con, pid)
check("weights reverted", {d["key"]: d["weight"] for d in scoring.dimensions()}, {d["key"]: d["weight"] for d in dims})

# switching a board off, and on again
sid = con.execute("SELECT id FROM proposals WHERE kind='source_off'").fetchone()[0]
learn.apply(con, sid)
check("board off", next(c for c in config.companies() if c["name"] == co).get("paused"), True)
learn.revert(con, sid)
check("board on", next(c for c in config.companies() if c["name"] == co).get("paused"), None)

shutil.rmtree(tmp)
print("improve: all checks pass")
