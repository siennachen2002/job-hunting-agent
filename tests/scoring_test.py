"""The code half of ranking, on a made-up posting and a throwaway database: no model, no network.

    python3 tests/scoring_test.py
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import db, llm, scoring  # noqa: E402

DIMS = [{"key": "role", "name": "Role fit", "weight": 40, "rubric": ""},
        {"key": "level", "name": "Level", "weight": 30, "rubric": ""},
        {"key": "sector", "name": "Sector", "weight": 30, "rubric": ""}]
scoring.dimensions = lambda: DIMS
JOB = {"company": "Acme", "title": "Product Designer", "location": "New York", "remote": 0,
       "description": "<p>Acme&#8217;s mission is to make climate data usable.</p><p>You have 2+ years of product design &amp; Figma.</p>"}


def raw(*dims, guard=False, blockers=()):
    return llm.JobScore(role_family="product_design", sector="climate", guard=guard, gaps=[], hard_blockers=list(blockers),
                        one_line="", dims=[{"key": k, "score": s, "reason": "", "evidence": e} for k, s, e in dims]).model_dump()


def check(name, got, want):
    if got != want:
        raise SystemExit(f"FAIL {name}: got {got!r}, want {want!r}")


V = {"preferences": "test"}

# quotes: curly apostrophes, entities, '...' between pieces, case and spacing all still match
text = scoring.quote_form(scoring.posting_text(JOB))
check("curly quote", scoring.quote_found("Acme's mission is to make climate data usable", text), True)
check("entity", scoring.quote_found("product design & figma", text), True)
check("pieces", scoring.quote_found("Acme's mission ... 2+ years of product design", text), True)
check("header line", scoring.quote_found("Title: Product Designer", text), True)
check("made up", scoring.quote_found("10+ years leading teams", text), False)
check("empty", scoring.quote_found("  ", text), False)

# totals: 1-5 → 0-100 by weight; unknown and an unfound quote count as 3
t, st, p = scoring.finalize(None, JOB, raw(("role", 5, "Product Designer"), ("level", 5, "2+ years"), ("sector", 5, "climate data")), "m", V)
check("all 5", (t, st, p["action"]), (100, "queued", "apply"))
t, st, p = scoring.finalize(None, JOB, raw(("role", 5, "Product Designer"), ("level", 1, "made-up words"), ("sector", "unknown", "")), "m", V)
check("unfound quote → unknown", ([d["score"] for d in p["dims"]], p["evidence_failed"], p["dims"][1]["claimed"]), ([5, None, None], ["level"], 1))
check("total with unknowns", t, round(40 * 1 + 30 * .5 + 30 * .5))
t, st, p = scoring.finalize(None, JOB, raw(("role", 5, "Product Designer"), ("level", 5, "2+ years"), ("sector", 5, "climate"), guard=True), "m", V)
check("guard caps at 50", (t, p["action"]), (50, "maybe"))
t, st, p = scoring.finalize(None, JOB, raw(("role", 5, "Product Designer"), blockers=["clearance"]), "m", V)
check("blocker skips", (st, p["action"]), ("skipped", "skip"))
check("records model and versions", (p["model"], p["versions"]), ("m", V))

# verdicts: Nope takes a job off To do, clearing it puts it back; the score is kept as it was
con = sqlite3.connect(":memory:"); con.row_factory = sqlite3.Row; con.executescript(db.SCHEMA)
con.execute("INSERT INTO jobs(id, source, title, status, score, score_json) VALUES (1, 't', 'x', 'queued', 74, '{\"score\": 74}')")
scoring.set_verdict(con, 1, "nope", "Level")
check("nope skips", con.execute("SELECT status FROM jobs").fetchone()[0], "skipped")
check("nope kept", tuple(con.execute("SELECT verdict, reason, score, prev_status FROM verdicts").fetchone()), ("nope", "Level", 74.0, "queued"))
scoring.set_verdict(con, 1, "good")
check("good restores", con.execute("SELECT status FROM jobs").fetchone()[0], "queued")
scoring.set_verdict(con, 1, None)
check("cleared", con.execute("SELECT count(*) FROM verdicts").fetchone()[0], 0)

print("scoring: all checks pass")
