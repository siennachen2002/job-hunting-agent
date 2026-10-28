"""The code half of ranking: the model scores each dimension with a quote, code checks the quotes and adds them up.

The model (agent/llm.py · score_job) returns 1-5 per dimension of preferences.yaml → scoring, each with one sentence and
words copied from the posting. Here, with no model: a quote that isn't in the posting turns its dimension to unknown, the
weighted total is computed, the seniority guard caps it, and every score records what produced it (the model and the
versions of the preferences, storybook and prompt), so your Good and Nope verdicts can later be read against them.
"""
from __future__ import annotations
import hashlib
import html
import json
import re
from . import config, db

DEFAULT_DIMENSIONS = [   # the same as profile.example/preferences.yaml, for a profile that has no scoring block
    {"key": "role", "name": "Role fit", "weight": 35,
     "rubric": "5: the daily work is one of the role families at its core. 3: half design, research or strategy work, half something else. 1: not design, research or strategy work at all."},
    {"key": "level", "name": "Level", "weight": 25,
     "rubric": "5: entry or mid level, 0-3 years asked, or a portfolio counts more than years. 3: 3-5 years, or senior in a small team. 1: staff, principal, director, 6+ years, or managing people."},
    {"key": "background", "name": "Background match", "weight": 25,
     "rubric": "5: the core requirements (tools, methods, domain) all appear in the storybook. 3: about half of them. 1: core requirements the storybook lacks (a degree, a license, a tech stack)."},
    {"key": "sector", "name": "Sector", "weight": 15,
     "rubric": "5: AI-native product, climate, or a design or innovation agency. 4: a creative studio. 3: other tech. 1: a sector in avoid_keywords."},
]
UNKNOWN = 3        # a dimension the posting says nothing about counts as the middle
GUARD_CAP = 50     # a role family's seniority guard (roles.yaml) caps the total, and the job is a 'maybe'


def dimensions() -> list[dict]:
    return (config.preferences().get("scoring") or {}).get("dimensions") or DEFAULT_DIMENSIONS


def rubric_text(dims: list[dict] | None = None) -> str:
    return "\n".join(f"- {d['key']} ({d['name']}): {d['rubric']}" for d in dims or dimensions())


def plain(text: str | None) -> str:
    """Posting text without HTML tags or entities."""
    t = html.unescape(text or "")
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d)>", "\n", t)
    return html.unescape(re.sub(r"<[^>]+>", " ", t))


def posting_text(job: dict, limit: int | None = None) -> str:
    """The posting exactly as the model reads it; the quote check reads the same text, uncut."""
    d = plain(job.get("description"))
    return (f"Company: {job.get('company')}\nTitle: {job.get('title')}\nLocation: {job.get('location')}\n"
            f"Remote: {'yes' if job.get('remote') else 'not stated'}\n\n{d[:limit] if limit else d}")


def quote_form(s: str) -> str:
    """Lowercase, straight quotes and dashes, single spaces: a quote the model copied still matches."""
    s = s.lower().translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                                           "–": "-", "—": "-", " ": " "}))
    return re.sub(r"\s+", " ", s).strip()


def quote_found(quote: str, text_form: str) -> bool:
    """Every piece of the quote (pieces joined by '...') is in the posting."""
    parts = [p.strip(" \"'.,;:") for p in re.split(r"\.\.\.|…", quote_form(quote))]
    parts = [p for p in parts if p]
    return bool(parts) and all(p in text_form for p in parts)


def total(scores: dict[str, int | None], dims: list[dict]) -> int:
    """0-100: each dimension's 1-5 mapped to 0-100, averaged by weight; unknown counts as UNKNOWN."""
    w = sum(d["weight"] for d in dims) or 1
    return round(100 * sum(d["weight"] * ((scores.get(d["key"]) or UNKNOWN) - 1) / 4 for d in dims) / w)


def _hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]


def versions(con=None) -> dict:
    """Short hashes of what the score depends on. With a connection, each new version is kept (first seen, and its
    content for preferences and the prompt), so a later change can be told apart and read back."""
    from . import llm, prompts as P
    prefs = json.dumps({"scoring": config.preferences().get("scoring"), "targets": config.preferences().get("targets"),
                        "roles": config.roles()}, ensure_ascii=False, sort_keys=True)
    prompt = P.RANK + json.dumps(llm.JobScore.model_json_schema(), sort_keys=True)
    v = {"preferences": _hash(prefs), "storybook": _hash(config.master_text()), "prompt": _hash(prompt)}
    if con is not None:
        for kind, content in (("preferences", prefs), ("storybook", None), ("prompt", prompt)):
            con.execute("INSERT OR IGNORE INTO versions(kind, hash, first_at, content) VALUES (?,?,?,?)", (kind, v[kind], db.now(), content))
    return v


def finalize(con, job: dict, raw: dict, model: str, v: dict | None = None) -> tuple[int, str, dict]:
    """The model's dimension scores → (total, jobs.status, the score_json payload)."""
    dims = dimensions()
    text = quote_form(posting_text(job))
    given = {d.get("key"): d for d in raw.get("dims") or []}
    out, failed = [], []
    for d in dims:
        g = given.get(d["key"]) or {}
        sc = g.get("score") if g.get("score") in (1, 2, 3, 4, 5) else None
        ev = (g.get("evidence") or "").strip()
        row = {"key": d["key"], "name": d["name"], "weight": d["weight"], "score": sc, "reason": g.get("reason") or "", "evidence": ev}
        if sc is not None and not quote_found(ev, text):
            row.update(score=None, note="quote not found in the posting" if ev else "no quote given", claimed=sc)
            failed.append(d["key"])
        out.append(row)
    t = total({r["key"]: r["score"] for r in out}, dims)
    guard = bool(raw.get("guard"))
    if guard:
        t = min(t, GUARD_CAP)
    auto = config.preferences().get("automation", {})
    blockers = raw.get("hard_blockers") or []
    action = ("skip" if blockers or t < auto.get("min_score_to_queue", 50)
              else "maybe" if guard or t < auto.get("min_score_to_apply", 70) else "apply")
    payload = {**raw, "dims": out, "score": t, "action": action, "evidence_failed": failed,
               "model": model, "versions": v or versions(con), "scored_at": db.now()}
    return t, ("skipped" if action == "skip" else "queued"), payload


# ---------------------------------------------------------------- your verdicts
def set_verdict(con, job_id: int, verdict: str | None, reason: str | None = None) -> dict:
    """Good or Nope on a job, with the score it had then. Nope also takes it off To do; clearing a Nope puts it back."""
    row = con.execute("SELECT status, score, score_json FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise ValueError(f"no job {job_id}")
    old = con.execute("SELECT * FROM verdicts WHERE job_id=?", (job_id,)).fetchone()
    if old and old["verdict"] == "nope" and verdict != "nope" and row["status"] == "skipped" and old["prev_status"]:
        con.execute("UPDATE jobs SET status=? WHERE id=?", (old["prev_status"], job_id))
    if verdict is None:
        con.execute("DELETE FROM verdicts WHERE job_id=?", (job_id,))
        return {"verdict": None}
    if verdict not in ("good", "nope"):
        raise ValueError("verdict is good or nope")
    prev = old["prev_status"] if old and old["prev_status"] else row["status"]
    con.execute("INSERT OR REPLACE INTO verdicts(job_id, verdict, reason, at, score, score_json, prev_status) VALUES (?,?,?,?,?,?,?)",
                (job_id, verdict, reason, db.now(), row["score"], row["score_json"], prev))
    if verdict == "nope" and row["status"] in ("queued", "new"):
        con.execute("UPDATE jobs SET status='skipped' WHERE id=?", (job_id,))
    from .audit import log
    log(con, "review", f"verdict-{verdict}", reason or "", job_id=job_id)
    return {"verdict": verdict, "reason": reason}
