"""Saved answers: what the person typed into "Questions for you", kept so the same question is never asked twice.

<profile>/saved-answers.yaml, shown in the Storybook. A question is reused only when it is the same kind of question:
a known topic (start date, interviewed here before, how did you hear…) or nearly the same words. Answers that belong to
one application are never saved: why-this-company, salary, essays, legal attestations and agreements, policy confirmations.
A question that names the company is reused only for that company ("Have you interviewed at Anthropic before?").
"""
from __future__ import annotations
import re
import yaml
from . import config, db

NEVER = re.compile(r"\bwhy\b|interest|excit|motivat|cover letter|tell us|describe|a time when|project|salary|compensation|\bpay\b|"
                   r"arbitrat|attest|certif|acknowledg|\bagree|confirm|policy|export control|read the|signature|essay|words\)|"
                   r"additional information|anything else|radio #|field label", re.I)
TOPICS = {   # same topic = same question, however it is worded
    "start": r"\b(earliest|when)\b.*\bstart|start date|available to start|availability to start",
    "timeline": r"deadline|timeline consideration|other offers|competing offer",
    "interviewed_before": r"(interviewed|applied) (at|with|to)\b.*\bbefore|previously (interviewed|applied)",
    "worked_before": r"(worked|employed) (at|for)\b.*\bbefore|previously (worked|been employed)|former employee",
    "heard": r"how did you (hear|find|learn)|where did you (hear|find)",
    "referral": r"\breferr",
    "notice": r"notice period",
    "located": r"(currently )?(based|located|live) in|reside in",
    "relocate": r"relocat",
    "pronouns": r"pronoun",
    "orientation": r"sexual orientation",
    "transgender": r"transgender",
    "disability": r"disabilit|chronic condition",
    "veteran": r"veteran",
    "age": r"18 years|over the age|at least 18",
}


def _path():
    return config.PROFILE_DIR / "saved-answers.yaml"


def load() -> list[dict]:
    p = _path()
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or []) if p.exists() else []


def _save(items: list[dict]) -> None:
    _path().write_text("# Answers you gave in 'Questions for you', reused on later applications. Private.\n" +
                       yaml.safe_dump(items, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _core(q: str) -> str:
    """'Have you ever interviewed at Anthropic before?* (both instances) — personal note' → the question itself."""
    q = re.split(r"\s+[—–]\s+|:\s+(?=you |your |Sienna|confirm|field)", q)[0]
    return re.sub(r"\((both instances|yes/no|text|[a-z ]+)\)|\*", "", q, flags=re.I).strip()


def _topic(q: str) -> str | None:
    return next((t for t, rx in TOPICS.items() if re.search(rx, q, re.I)), None)


def _words(q: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", q.lower()) if w not in {"the", "you", "your", "are", "and", "with", "for", "have", "ever", "this"}}


def _scope(q: str, company: str) -> str | None:
    """None: not reusable. 'any': every application. Otherwise the company it is limited to."""
    if NEVER.search(q) and not _topic(q):   # a known topic ("how would you describe your sexual orientation") is always reusable
        return None
    name = (company or "").split()[0].lower() if company else ""
    return company if name and len(name) > 2 and name in q.lower() else "any"


def _same(a: dict, q: str, company: str) -> bool:
    if a.get("scope") not in ("any", company):
        return False
    t = _topic(q)
    if t or a.get("topic"):
        return t == a.get("topic")
    wa, wq = _words(a["question"]), _words(q)
    return bool(wa and wq) and len(wa & wq) / len(wa | wq) >= 0.75


def lookup(question: str, company: str) -> str | None:
    q = _core(question)
    if _scope(q, company) is None:
        return None
    return next((a["answer"] for a in load() if _same(a, q, company)), None)


def remember(question: str, answer: str, company: str) -> bool:
    """Keep a reusable answer (replacing an older one to the same question). Returns whether it was kept."""
    q = _core(question); answer = (answer or "").strip()
    scope = _scope(q, company)
    if scope is None or not answer:
        return False
    items = [a for a in load() if not _same(a, q, company)]
    items.append({"question": q, "answer": answer, "topic": _topic(q), "scope": scope, "from": company, "saved": db.now()[:10]})
    _save(items)
    return True


def forget(i: int) -> None:
    items = load()
    if 0 <= i < len(items):
        items.pop(i); _save(items)


def fill_pending(con, skip_app: int | None = None) -> int:
    """Answer open questions on applications waiting for review from the saved answers. Returns how many were filled."""
    import json
    n = 0
    for r in con.execute("SELECT a.id, a.answers_json, j.company FROM applications a JOIN jobs j ON j.id=a.job_id "
                         "WHERE a.status='pending_approval' AND a.answers_json IS NOT NULL").fetchall():
        if r["id"] == skip_app:
            continue
        aj = json.loads(r["answers_json"] or "{}"); left = []
        for q in aj.get("needs_human") or []:
            v = lookup(q, r["company"])
            if v is None:
                left.append(q); continue
            aj.setdefault("answers", []).append({"question": _core(q), "answer": v, "provenance": "you", "note": "saved answer"})
            n += 1
        if len(left) != len(aj.get("needs_human") or []):
            aj["needs_human"] = left
            con.execute("UPDATE applications SET answers_json=? WHERE id=?", (json.dumps(aj, ensure_ascii=False), r["id"]))
    con.commit()
    return n
