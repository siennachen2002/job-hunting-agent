"""The self-check: every application waiting for you is brought up to today's rules, so a bug fixed in code is fixed in
every application it already touched. Runs with Refresh jobs & replies and in the daily run; never submits anything.

    python -m agent.run doctor

What it checks, and what it does about each:
  duplicate roles        the same role (any city) twice → the later application is withdrawn
  outdated answers       saved answers re-checked against today's standing rules: a stale one is dropped, a legal
                         declaration goes back to the person
  stale or failed forms  the form-filling code changed since this form was filled, or a submit was rejected → the form is
                         filled again with the saved answers (code only, no model, never submitted); a required field it
                         still can't fill becomes a question for the person
  résumés                over two lines, repeated opening verbs, the person's summary missing → fixed and re-rendered on
                         today's template (links, countries)
  cover letters          the agent's own letters that break the writing checks are repaired; the person's own text is
                         never touched
  blanks                 [YOUR ANSWER] placeholders are listed (approval is already blocked)
"""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from . import config, db

FILL_CODE = ["apply/fill.py", "apply/inspect_form.py", "apply/standing.py", "apply/identity.py"]
COVER = re.compile(r"\bwhy\b.*\b(us|join|work|company|here|this|apply|role)\b|interesting aspects|cover letter|interested in", re.I)


def fill_version() -> str:
    """A fingerprint of the form-filling code: when it changes, forms filled before need filling again."""
    h = hashlib.sha1()
    for f in FILL_CODE:
        p = Path(__file__).parent / f
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


def _init(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(applications)")}
    if "fill_version" not in cols:
        con.execute("ALTER TABLE applications ADD COLUMN fill_version TEXT")
    con.commit()


def _clean_answers(aj: dict) -> list[str]:
    """Today's rules on yesterday's answers: drop what a standing rule no longer gives, hand legal declarations back."""
    from .apply.standing import standing_answer, LEGAL, SELF_ID
    notes, keep = [], []
    for x in aj.get("answers", []):
        q = x.get("question") or ""
        if LEGAL.search(q) and not SELF_ID.search(q) and x.get("provenance") != "you":
            aj.setdefault("needs_human", []).append(q); notes.append(f"legal declaration handed back: {q[:50]}"); continue
        if x.get("note") == "standing answer" and standing_answer(q) is None:
            notes.append(f"stale answer dropped: {q[:50]}"); continue
        keep.append(x)
    aj["answers"] = keep
    aj["needs_human"] = list(dict.fromkeys(aj.get("needs_human") or []))
    return notes


MINE = ("status", "answers_json", "resume_json", "resume_pdf", "fill_version", "email_body")


def _fresh(con, a: dict) -> bool:
    """Re-read what you can change on an application (it may be minutes since the list was read): False when it is no
    longer waiting for review, so the self-check leaves it alone."""
    r = con.execute(f"SELECT {', '.join(MINE)} FROM applications WHERE id=?", (a["id"],)).fetchone()
    if not r or r["status"] not in ("pending_approval", "failed"):
        return False
    a.update(dict(r))
    return True


def _unchanged(con, a: dict) -> bool:
    """Nobody changed it while the self-check worked on it (you answered, revised, approved or sent it meanwhile)."""
    r = con.execute(f"SELECT {', '.join(MINE)} FROM applications WHERE id=?", (a["id"],)).fetchone()
    return bool(r) and all(r[k] == a.get(k) for k in MINE)


def _write(con, a: dict, **fields) -> bool:
    """Write the self-check's change only if the application is as it read it; keep its own copy current."""
    if not _unchanged(con, a):
        return False
    db.update_application(con, a["id"], **fields); con.commit()
    a.update(fields)
    return True


def run(con, refill: bool = True) -> dict:
    from .apply.fill import fill
    from .resume.render import render_one_page
    from .voicecheck import lint, lint_resume, report
    from . import llm
    _init(con)
    version, rep = fill_version(), {"checked": 0, "fixed": [], "blanks": []}
    apps = [dict(r) for r in con.execute(
        "SELECT a.*, j.company, j.title, j.apply_url, j.source, j.sector, j.score_json FROM applications a JOIN jobs j ON j.id=a.job_id "
        "WHERE a.status IN ('pending_approval','failed') ORDER BY a.id").fetchall()]
    # duplicate roles: the one with your own answers keeps the role, else the earliest
    seen = {}
    for a in sorted(apps, key=lambda a: ('"provenance": "you"' not in (a.get("answers_json") or ""), a["id"])):
        k = db.role_key(a["company"], a["title"])
        if k in seen:
            db.update_application(con, a["id"], status="withdrawn", error=f"same role as application #{seen[k]}")
            rep["fixed"].append(f"#{a['id']} {a['company']}: duplicate of #{seen[k]}, withdrawn"); a["_gone"] = True
        else:
            seen[k] = a["id"]
    con.commit()
    for a in apps:
        if a.get("_gone") or not _fresh(con, a):
            continue
        rep["checked"] += 1
        tag = f"#{a['id']} {a['company']} · {a['title']}"
        aj = json.loads(a["answers_json"]) if (a.get("answers_json") or "").startswith("{") else {}
        # answers and form
        if a["kind"] == "ats_web" and a.get("apply_url") and aj:
            notes = _clean_answers(aj)
            stale = a.get("fill_version") != version
            failed = a["status"] == "failed"
            if refill and (stale or failed or notes):
                config.SCREENS.mkdir(parents=True, exist_ok=True); shot = str(config.SCREENS / f"app{a['id']}.png")
                try:
                    r = fill(a["apply_url"], {x["question"]: x["answer"] for x in aj["answers"] if x.get("answer")}, a["resume_pdf"], shot)
                    empty = [l.split(": ", 1)[1] for l in r.get("log", []) if l.startswith("UNFILLED required: ")]
                    answered = {x["question"] for x in aj["answers"]}
                    aj["needs_human"] = list(dict.fromkeys((aj.get("needs_human") or []) + [e for e in empty if e not in answered]))
                    if not _write(con, a, answers_json=json.dumps(aj, ensure_ascii=False), fill_version=version,
                                  sent_log="\n".join(r.get("log", [])) + f"\nscreenshot: {shot}",
                                  **({"status": "pending_approval", "error": None} if failed else {})):
                        rep["fixed"].append(f"{tag}: left alone, you changed it while its form was being refilled"); continue
                    why = "submit had failed" if failed else "form-filling rules changed" if stale else "answers updated"
                    rep["fixed"].append(f"{tag}: form refilled ({why})" + (f", {len(empty)} field(s) for you" if empty else "") +
                                        ("; " + "; ".join(notes) if notes else ""))
                except Exception as e:
                    rep["fixed"].append(f"{tag}: refill failed ({str(e)[:80]})")
        # cover letters the agent wrote
        changed = False
        for x in aj.get("answers", []):
            if x.get("provenance") == "you" or len(x.get("answer") or "") < 120 or not COVER.search(x.get("question") or ""):
                continue
            hard = [i for i in lint(x["answer"], "why_us") if i.level == "hard"]
            if hard:
                try:
                    x["answer"] = llm.repair_text(x["answer"], report(hard), "why_us"); changed = True
                    rep["fixed"].append(f"{tag}: cover letter repaired ({hard[0].what[:50]})")
                except Exception:
                    pass
        if changed and not _write(con, a, answers_json=json.dumps(aj, ensure_ascii=False)):
            continue
        # résumé on today's template
        if a.get("resume_json") and _unchanged(con, a):   # re-rendered at the same path: never over a résumé you just revised
            c = json.loads(a["resume_json"]); before = json.dumps(c, sort_keys=True)
            if any(i.level == "hard" and "two lines" in i.what for i in lint_resume(c)):
                llm.shorten_long(c)
            own = (config.profile().get("summary") or "").strip()
            if own and c.get("summary") != own:
                c["summary"] = own
            sc = json.loads(a.get("score_json") or "{}")
            pdf, r2, _ = render_one_page(c, Path(a["resume_pdf"]).stem, role_family=sc.get("role_family"),
                                         sector=a.get("sector") or sc.get("sector"), posting_title=a.get("title"))
            if json.dumps(r2, sort_keys=True) != before and _write(con, a, resume_pdf=str(pdf), resume_json=json.dumps(r2, ensure_ascii=False)):
                rep["fixed"].append(f"{tag}: résumé brought up to date")
        # blanks
        if re.search(r"\[YOUR ANSWER", json.dumps(aj) + (a.get("email_body") or ""), re.I):
            rep["blanks"].append(tag)
        con.commit()
    from .audit import log
    log(con, "doctor", "run", f"{rep['checked']} checked, {len(rep['fixed'])} fixed, {len(rep['blanks'])} with blanks")
    return rep
