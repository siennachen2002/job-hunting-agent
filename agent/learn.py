"""Node 08 · Learn (self-improvement, with you in charge).

Inputs: your notes on applications, the reasons you rejected drafts, and edits you made in the dashboard.
Output: proposed patches, each small and reviewable:
  - brief_example   add or sharpen one Weak → Strong row in docs/00-house-rules.md (the brief stays one page)
  - storybook_line  replace one line in the storybook with a better-worded one (same facts)
  - ban_phrase      add a phrase to the writing check (profile/learned_patterns.yaml; code is never edited)
  - preference      change one line of the application strategy in profile/preferences.yaml (a rubric line included)
From your Good and Nope verdicts, by code (agent/improve.py): weights, drop_titles (prefilter) and source_off.
Nothing is applied until you approve it on the dashboard's Learn page. Every applied patch keeps its before/after,
so it can be reverted.
"""
from __future__ import annotations
import json
import re
from pydantic import BaseModel, Field
from . import config, db

SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY, at TEXT, app_id INTEGER, job_id INTEGER, text TEXT, used INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS proposals (id INTEGER PRIMARY KEY, at TEXT, kind TEXT, target TEXT, before TEXT, after TEXT,
  reason TEXT, source TEXT, status TEXT DEFAULT 'pending', decided_at TEXT);
"""
PATTERNS = lambda: config.PROFILE_DIR / "learned_patterns.yaml"


def init(con):
    con.executescript(SCHEMA)


def add_feedback(con, text: str, app_id: int | None = None, job_id: int | None = None):
    init(con)
    con.execute("INSERT INTO feedback(at, app_id, job_id, text) VALUES (?,?,?,?)", (db.now(), app_id, job_id, text.strip()))
    con.commit()


class Patch(BaseModel):
    kind: str = Field(description="brief_example | storybook_line | ban_phrase | preference")
    target: str = Field(description="file the patch applies to: docs/00-house-rules.md, profile/master/<file>.md, learned_patterns, or profile/preferences.yaml")
    before: str = Field(description="exact existing text to replace; '' when adding a brief example row or a ban phrase")
    after: str = Field(description="new text: a full table row '| Weak | Strong | Why |', a replacement storybook line, or a phrase")
    reason: str = Field(description="one sentence linking the patch to the note it came from")
    source: str = Field(description="the note or edit that prompted it, quoted briefly")


class Patches(BaseModel):
    patches: list[Patch]


def propose(con) -> int:
    """Turn unused feedback into pending proposals. Returns how many were proposed."""
    init(con)
    notes = [dict(r) for r in con.execute("SELECT * FROM feedback WHERE used=0").fetchall()]
    rejected = [dict(r) for r in con.execute("SELECT id, error FROM applications WHERE status='withdrawn' AND error IS NOT NULL AND error!=''").fetchall()]
    verdicts = _disagreements(con)   # new Good/Nope since the last time: where the scores and you disagree
    if not notes and not rejected and not verdicts:
        return 0
    from .llm import _system
    from .providers import structured
    body = ("## Notes from the person\n" + "\n".join(f"- (app {n['app_id']}) {n['text']}" for n in notes) +
            "\n\n## Reasons given when rejecting drafts\n" + "\n".join(f"- (app {r['id']}) {r['error']}" for r in rejected) +
            "\n\n## Current brief\n" + (config.DOCS_DIR / "00-house-rules.md").read_text(encoding="utf-8"))
    from .prompts import LEARN as task
    if verdicts:
        body += "\n\n## Your Good and Nope where the scores disagree\n" + verdicts
    body += "\n\n## Track record\n" + _track_record(con)
    body += "\n\n## Current preferences.yaml\n" + (config.PROFILE_DIR / "preferences.yaml").read_text(encoding="utf-8")
    res = structured(_system(task), body, Patches, effort="high", max_tokens=6000, tier="draft")   # you apply each one
    for p in res.patches:
        con.execute("INSERT INTO proposals(at, kind, target, before, after, reason, source) VALUES (?,?,?,?,?,?,?)",
                    (db.now(), p.kind, p.target, p.before, p.after, p.reason, p.source))
    con.execute("UPDATE feedback SET used=1 WHERE used=0")
    db.set_setting(con, "learn_verdicts_at", db.now())
    con.commit()
    return len(res.patches)


def _disagreements(con, n: int = 6) -> str:
    """The Good posts that scored lowest and the Nope posts that scored highest, with each dimension's score and reason;
    only when there are verdicts newer than the last suggestions."""
    from .improve import judged, MIN_EACH
    rows = judged(con)
    since = db.get_setting(con, "learn_verdicts_at") or ""
    if not any(r["at"] > since for r in rows) or sum(r["verdict"] == "good" for r in rows) + sum(r["verdict"] == "nope" for r in rows) < MIN_EACH:
        return ""
    good = sorted((r for r in rows if r["verdict"] == "good"), key=lambda r: r["score"])[:n]
    nope = sorted((r for r in rows if r["verdict"] == "nope"), key=lambda r: -r["score"])[:n]
    line = lambda r: (f"- {r['verdict'].upper()} ({r['reason'] or 'no reason given'}), scored {r['score']:.0f}: {r['company']} · {r['title']}\n"
                      + "\n".join(f"    {d['name']}: {d.get('score') or 'unknown'} · {d.get('reason', '')}" for d in r["dims"]))
    return "\n".join(map(line, good + nope))


def _track_record(con) -> str:
    """Changes already applied (with what they did) and suggestions dismissed: the next suggestions build on them."""
    from .improve import outcomes
    done = [f"- applied {o['kind']}: {(o['after'] or '')[:120]} → {o['text']}" for o in outcomes(con)[:10]]
    no = [f"- dismissed {r['kind']}: {(r['after'] or '')[:120]}" for r in
          con.execute("SELECT kind, after FROM proposals WHERE status='rejected' ORDER BY decided_at DESC LIMIT 10").fetchall()]
    return "\n".join(done + no) or "(nothing applied or dismissed yet)"


def apply(con, pid: int) -> str:
    """Apply one approved proposal. Returns a short description; raises if the target text is not found."""
    init(con)
    p = dict(con.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone())
    if p["kind"] == "storybook_line":
        from .storybook import snapshot
        snapshot("before applying a fix from your notes")
    if p["kind"] == "brief_example":
        path = config.DOCS_DIR / "00-house-rules.md"; s = path.read_text(encoding="utf-8")
        anchor = "| I am excited to apply…"
        if p["before"] and p["before"] in s:
            s = s.replace(p["before"], p["after"], 1)
        else:
            s = s.replace(anchor, p["after"].strip() + "\n" + anchor, 1)
        path.write_text(s, encoding="utf-8")
    elif p["kind"] == "storybook_line":
        hits = [f for f in config.MASTER_DIR.glob("*.md") if p["before"] and p["before"] in f.read_text(encoding="utf-8")]
        if not hits:
            raise ValueError("the line to replace was not found in the storybook")
        f = hits[0]; f.write_text(f.read_text(encoding="utf-8").replace(p["before"], p["after"], 1), encoding="utf-8")
    elif p["kind"] == "preference":
        import yaml
        path = config.PROFILE_DIR / "preferences.yaml"; s = path.read_text(encoding="utf-8")
        if not p["before"] or p["before"] not in s:
            raise ValueError("the preference line to change was not found")
        s = s.replace(p["before"], p["after"], 1); yaml.safe_load(s)  # refuse to write broken YAML
        path.write_text(s, encoding="utf-8")
    elif p["kind"] == "weights":
        from .improve import set_weights, retotal
        path = config.PROFILE_DIR / "preferences.yaml"
        path.write_text(set_weights(path.read_text(encoding="utf-8"), json.loads(p["after"])), encoding="utf-8")
        retotal(con)
    elif p["kind"] == "drop_titles":
        path = config.PROFILE_DIR / "preferences.yaml"
        path.write_text(_drop_titles(path.read_text(encoding="utf-8"), add=json.loads(p["after"])), encoding="utf-8")
    elif p["kind"] == "source_off":
        path = config.PROFILE_DIR / "companies.yaml"
        path.write_text(_source_off(path.read_text(encoding="utf-8"), p["after"], True), encoding="utf-8")
    elif p["kind"] == "ban_phrase":
        import yaml
        path = PATTERNS(); data = yaml.safe_load(path.read_text()) if path.exists() else {}
        data = data or {}; data.setdefault("ban_phrases", [])
        if p["after"].lower() not in data["ban_phrases"]:
            data["ban_phrases"].append(p["after"].lower())
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    con.execute("UPDATE proposals SET status='applied', decided_at=? WHERE id=?", (db.now(), pid)); con.commit()
    from .audit import log
    log(con, "learn", "patch-applied", f"{p['kind']}: {p['after'][:200]}")
    return f"{p['kind']} applied"


def revert(con, pid: int) -> str:
    p = dict(con.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone())
    if p["kind"] == "brief_example":
        path = config.DOCS_DIR / "00-house-rules.md"; s = path.read_text(encoding="utf-8")
        s = s.replace(p["after"], p["before"], 1) if p["before"] else s.replace(p["after"].strip() + "\n", "", 1)
        path.write_text(s, encoding="utf-8")
    elif p["kind"] == "storybook_line":
        for f in config.MASTER_DIR.glob("*.md"):
            t = f.read_text(encoding="utf-8")
            if p["after"] in t:
                f.write_text(t.replace(p["after"], p["before"], 1), encoding="utf-8"); break
    elif p["kind"] == "preference":
        path = config.PROFILE_DIR / "preferences.yaml"
        path.write_text(path.read_text(encoding="utf-8").replace(p["after"], p["before"], 1), encoding="utf-8")
    elif p["kind"] == "weights":
        from .improve import set_weights, retotal
        path = config.PROFILE_DIR / "preferences.yaml"
        path.write_text(set_weights(path.read_text(encoding="utf-8"), json.loads(p["before"])), encoding="utf-8")
        retotal(con)
    elif p["kind"] == "drop_titles":
        path = config.PROFILE_DIR / "preferences.yaml"
        path.write_text(_drop_titles(path.read_text(encoding="utf-8"), remove=json.loads(p["after"])), encoding="utf-8")
    elif p["kind"] == "source_off":
        path = config.PROFILE_DIR / "companies.yaml"
        path.write_text(_source_off(path.read_text(encoding="utf-8"), p["after"], False), encoding="utf-8")
    elif p["kind"] == "ban_phrase":
        import yaml
        path = PATTERNS(); data = yaml.safe_load(path.read_text()) or {}
        data["ban_phrases"] = [x for x in data.get("ban_phrases", []) if x != p["after"].lower()]
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    con.execute("UPDATE proposals SET status='reverted', decided_at=? WHERE id=?", (db.now(), pid)); con.commit()
    from .audit import log
    log(con, "learn", "patch-reverted", p["after"][:200])
    return "reverted"


def _drop_titles(text: str, add: list[str] = (), remove: list[str] = ()) -> str:
    """preferences.yaml with prefilter → drop_titles changed in place (comments kept)."""
    import yaml
    m = re.search(r"^([ \t]+drop_titles:[ \t]*)(\[.*?\])", text, re.M)
    if not m:
        raise ValueError("prefilter → drop_titles was not found in preferences.yaml (as a [list] on one line)")
    cur = yaml.safe_load(m.group(2)) or []
    new = [x for x in cur if x not in remove] + [x for x in add if x not in cur]
    text = text[:m.start(2)] + json.dumps(new) + text[m.end(2):]
    yaml.safe_load(text)
    return text


def _source_off(text: str, name: str, off: bool) -> str:
    """companies.yaml with one watched company switched off (or on again), in place."""
    import yaml
    m = re.search(r"^([ \t]*- \{name: " + re.escape(name) + r",)( paused: true,)?", text, re.M)
    if not m:
        raise ValueError(f"{name} was not found in companies.yaml")
    text = text[:m.end(1)] + (" paused: true," if off else "") + text[m.end():]
    yaml.safe_load(text)
    return text


def learned_bans() -> list[str]:
    import yaml
    path = PATTERNS()
    return (yaml.safe_load(path.read_text()) or {}).get("ban_phrases", []) if path.exists() else []
