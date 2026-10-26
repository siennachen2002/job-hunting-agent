"""All Claude calls live here: scoring, résumé tailoring, email/proposal drafting.

Design rules (from the user):
- Content must come from the master documents. Anything not traceable to them is
  "DIY" and the share of DIY content must stay <= 15% (preferences.diy_max).
- Voice must not read as machine-written. docs/02-writing-style-guide.md is loaded
  into the system prompt when present and is the authority on voice.
"""
from __future__ import annotations
import json
import re
from typing import Literal
from pydantic import BaseModel, Field
from . import config
from . import prompts as P         # every prompt, in one file
from .providers import structured  # the model (and the optional draft model), see agent/providers.py


def _brief() -> str:
    return (config.DOCS_DIR / "00-house-rules.md").read_text(encoding="utf-8").replace("{name}", config.first_name())


def _system(task: str = "") -> list[dict]:
    """Stable, cached prefix: the writing brief, preferences, the master documents. Then a short task line."""
    prefs = json.dumps(config.preferences(), ensure_ascii=False)
    blocks = [{"type": "text", "text": _brief() + "\n\n## Preferences\n" + prefs + "\n\n## Master documents\n" + config.master_text(),
               "cache_control": {"type": "ephemeral"}}]
    if task:
        blocks.append({"type": "text", "text": "## Task\n" + task})
    return blocks


# ---------------------------------------------------------------- scoring
class JobScore(BaseModel):
    score: int = Field(description="0-100 relevance of this posting to the person, considering role fit, sector priority, seniority and location/visa constraints")
    role_family: str = Field(description="which of the person's role families this maps to, or 'none'")
    sector: Literal["climate", "ai", "design_agency", "creative", "tech", "other"]
    fit_reasons: list[str] = Field(description="3-5 concrete overlaps between the posting and the person's record")
    gaps: list[str] = Field(description="requirements the person does not clearly meet")
    hard_blockers: list[str] = Field(description="dealbreakers: wrong country without visa, clearance, >N years gap, etc. Empty if none")
    action: Literal["apply", "maybe", "skip"]
    one_line: str = Field(description="one plain sentence to the person about this job, addressing them as 'you'; no pronouns like she/he")


def score_job(job: dict, tier: str = "draft") -> JobScore:
    roles = config.roles()
    posting = (f"Company: {job.get('company')}\nTitle: {job.get('title')}\nLocation: {job.get('location')}\n"
               f"Remote: {job.get('remote')}\nURL: {job.get('url')}\n\n{(job.get('description') or '')[:12000]}")
    task = P.RANK.format(first_name=config.first_name(), roles=json.dumps(roles, ensure_ascii=False))
    return structured(_system(task), posting, JobScore, effort="low", max_tokens=2000, tier=tier)   # every posting: the draft model


class ScoredJob(JobScore):
    job_id: int = Field(description="the id given with the posting")


class JobScores(BaseModel):
    items: list[ScoredJob] = Field(description="one entry per posting, same ids as given")


def score_jobs_claude_code(jobs: list[dict]) -> dict[int, JobScore]:
    """Without Jev: Claude Code (your login, no API) rates a handful of postings in one call."""
    roles = config.roles()
    task = P.RANK.format(first_name=config.first_name(), roles=json.dumps(roles, ensure_ascii=False)) + " Rate every posting below, each on its own."
    postings = "\n\n".join(f"### Posting id {j['id']}\nCompany: {j.get('company')}\nTitle: {j.get('title')}\nLocation: {j.get('location')}\n"
                           f"Remote: {j.get('remote')}\n\n{(j.get('description') or '')[:3500]}" for j in jobs)
    out = structured(_system(task), postings, JobScores, effort="low", max_tokens=8000, tier="claude-code")
    want = {j["id"] for j in jobs}
    return {s.job_id: JobScore(**s.model_dump(exclude={"job_id"})) for s in out.items if s.job_id in want}


# ---------------------------------------------------------------- résumé
class Bullet(BaseModel):
    text: str
    link_text: str = Field(default="", description="exact substring of text to make clickable, usually a project name like 'Cocut'; '' if none")
    link: str = Field(default="", description="URL for link_text, copied from the master documents; '' if none")
    provenance: Literal["master", "adapted", "new"] = Field(description="master = copied/condensed from the documents; adapted = reworded but same facts; new = not in the documents (counts as DIY)")


class Experience(BaseModel):
    org: str
    org_link: str = Field(default="", description="URL for the org or project name if the master documents give one, else ''")
    role: str
    dates: str
    location: str = ""
    bullets: list[Bullet]


class Project(BaseModel):
    name: str
    blurb: str
    link: str = ""
    provenance: Literal["master", "adapted", "new"] = "master"


class Education(BaseModel):
    school: str
    degree: str
    dates: str
    note: str = ""


class SkillGroup(BaseModel):
    label: str
    items: list[str]


class ResumeContent(BaseModel):
    name: str
    headline: str = Field(description="ignored: the headline is set in code to a plain job title")
    email: str
    phone: str = ""
    location: str = ""
    links: list[str] = Field(description="portfolio, LinkedIn, GitHub - as bare domains/paths")
    summary: str = Field(description="2-3 sentences max, specific, in the person's own phrasing. May be empty if the documents suggest they don't use one")
    experience: list[Experience]
    projects: list[Project] = []
    education: list[Education]
    skills: list[SkillGroup]
    diy_ratio: float = Field(description="fraction of bullets/blurbs with provenance 'new' (0-1)")
    diy_notes: list[str] = Field(description="every 'new' item and why it was needed")
    tailoring_notes: list[str] = Field(description="what was emphasised or dropped for this posting, 3-6 items")


def tailor_resume(job: dict, score: JobScore | None = None) -> ResumeContent:
    diy_max = config.preferences().get("automation", {}).get("diy_max", 0.15)
    task = P.TAILOR.format(diy_max=f"{diy_max:.0%}")
    posting = (f"Company: {job.get('company')}\nTitle: {job.get('title')}\nLocation: {job.get('location')}\n\n{(job.get('description') or '')[:12000]}")
    if score:
        posting += "\n\n## SCORING NOTES\n" + score.model_dump_json(indent=1)
    return structured(_system(task), "Build the one-page résumé content for this posting.\n\n" + posting, ResumeContent, effort="high", max_tokens=16000)


class AlignedEntry(BaseModel):
    org: str
    bullets: list[str]


class AlignedProject(BaseModel):
    name: str
    blurb: str


class Aligned(BaseModel):
    requirements: list[str] = Field(description="the posting's core requirements, in its own words")
    experience: list[AlignedEntry]
    projects: list[AlignedProject] = []
    gaps: list[str] = Field(description="requirements the record doesn't support; left uncovered")


def align_resume(job: dict, content: dict) -> tuple[dict, list[str]]:
    """Reword the picked lines in the posting's vocabulary and order them by its requirements; facts unchanged.
    Returns the content and notes (requirements covered, gaps)."""
    import copy
    cur = {"experience": [{"org": e["org"], "role": e.get("role"), "bullets": [b["text"] for b in e.get("bullets", [])]} for e in content.get("experience", [])],
           "projects": [{"name": p["name"], "blurb": p["blurb"]} for p in content.get("projects", [])]}
    body = (f"## POSTING\nCompany: {job.get('company')}\nTitle: {job.get('title')}\n\n{(job.get('description') or '')[:9000]}\n\n"
            f"## RÉSUMÉ LINES\n{json.dumps(cur, ensure_ascii=False, indent=1)}")
    out = structured(_system(P.ALIGN), body, Aligned, effort="high", max_tokens=8000)
    new = copy.deepcopy(content)
    by_org = {e.org: e.bullets for e in out.experience}
    NUMW = r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|dozens?|hundreds?|thousands?)\b"
    nums = lambda t: set(re.findall(r"\d[\d,.]*\+?%?", t)) | {w.lower() for w in re.findall(NUMW, t, re.I)}
    CLAIMS = r"\b(deployed|adopted|adoption|rolled out|in production|alongside|scaled to)\b"
    claims = lambda t: {w.lower() for w in re.findall(CLAIMS, t, re.I)}
    for e in new.get("experience", []):
        b = by_org.get(e["org"])
        if not b:
            continue
        old_nums = nums(" ".join(x["text"] for x in e["bullets"]))
        old_text = " ".join(x["text"] for x in e["bullets"])
        if not nums(" ".join(b)) <= old_nums or not claims(" ".join(b)) <= claims(old_text):
            continue   # a number or an outcome the record doesn't have: keep the original lines for this entry
        e["bullets"] = [{"text": t, "provenance": "adapted", "link_text": "", "link": ""} for t in b]
    blurbs = {p.name: p.blurb for p in out.projects}
    for p in new.get("projects", []):
        if blurbs.get(p["name"]) and nums(blurbs[p["name"]]) <= nums(p["blurb"]) and claims(blurbs[p["name"]]) <= claims(p["blurb"]):
            p["blurb"] = blurbs[p["name"]]; p["provenance"] = "adapted"
    return new, ["requirements: " + "; ".join(out.requirements)] + (["not covered: " + "; ".join(out.gaps)] if out.gaps else [])


def revise_resume(job: dict, current: dict, instruction: str) -> ResumeContent:
    """The person's note on one résumé ("lead with the climate work", "shorter bullets"), applied to that résumé only.
    Same rules as tailoring: facts come from the master documents, nothing is invented."""
    task = P.REVISE
    body = (f"## THE PERSON'S NOTE\n{instruction}\n\n## CURRENT RÉSUMÉ\n{json.dumps(current, ensure_ascii=False)[:20000]}\n\n"
            f"## POSTING\nCompany: {job.get('company')}\nTitle: {job.get('title')}\n\n{(job.get('description') or '')[:8000]}")
    return structured(_system(task), body, ResumeContent, effort="high", max_tokens=16000)


# ---------------------------------------------------------------- answers
class FormAnswer(BaseModel):
    question: str
    answer: str
    provenance: Literal["master", "adapted", "new", "skipped"]
    note: str = ""


class FormAnswers(BaseModel):
    answers: list[FormAnswer]
    diy_ratio: float
    needs_human: list[str] = Field(description="questions we must not answer on the person's behalf (salary, visa, legal attestations, EEO) or could not answer")


WHY_US = re.compile(r"\bwhy\b.*\b(us|join|interest|company|here)|interested in|excit|what (draws|attracts)|most interesting aspects|motivat", re.I)
WHY_US_RULE = P.WHY_US


def answer_form(job: dict, questions: list[dict]) -> FormAnswers:
    """questions: [{label, required, type, options?}] extracted from the ATS form."""
    task = P.ANSWERS.format(first_name=config.first_name())
    body = (f"Company: {job.get('company')}\nTitle: {job.get('title')}\n\n## QUESTIONS\n" +
            json.dumps(questions, ensure_ascii=False, indent=1) + "\n\n## POSTING\n" + (job.get('description') or '')[:8000])
    if any(WHY_US.search(q.get("label") or "") for q in questions):
        from . import db as _db
        from .mission import mission
        with _db.tx() as con:
            m = mission(con, job.get("company") or "", job.get("description") or "")
        body += ("\n\n## COMPANY MISSION (their own words)\n" + ("\n".join(f"- {x}" for x in m) if m else
                 "- none found: open with what the company says it is building, never invent a mission"))
        task += " " + WHY_US_RULE
    fa = structured(_system(task), body, FormAnswers, effort="medium", max_tokens=8000)
    from .apply.identity import identity_answer
    from .apply.standing import standing_answer
    opts = {q.get("label"): q.get("options") for q in questions}
    have = {a.question for a in fa.answers}
    from .apply.standing import SKIP_NEED
    fa.needs_human = list(dict.fromkeys(re.sub(r"\s*select\.{3}\s*$", "", q, flags=re.I) for q in fa.needs_human if not SKIP_NEED.search(q)))
    labels = [q.get("label") or "" for q in questions]
    def exact(need: str) -> str:   # the form's own full question, not the model's shortened retelling of it
        if need in labels:
            return need
        w = set(re.findall(r"[a-z]{3,}", need.lower()))
        best = max(labels, key=lambda l: len(w & set(re.findall(r"[a-z]{3,}", l.lower()))), default="")
        return best if best and len(w & set(re.findall(r"[a-z]{3,}", best.lower()))) >= 2 else need
    fa.needs_human = list(dict.fromkeys(exact(q) for q in fa.needs_human))
    req = {q.get("label"): q.get("required") for q in questions}
    for q in list(fa.needs_human):
        base = re.sub(r"\s*\([a-z ]+\)$", "", q)   # "Name (text)" → "Name"
        v = standing_answer(q, opts.get(q))
        if v is None:   # name, email and phone come from the standing answers too
            v = identity_answer(base) or None
        if v is None and not req.get(base, req.get(q, True)) and re.search(r"linkedin|github|website|portfolio", q, re.I):
            fa.needs_human.remove(q); continue   # an optional link the standing answers leave empty stays empty
        if v is not None:
            fa.needs_human.remove(q)
            if q not in have:
                fa.answers.append(FormAnswer(question=q, answer=v, provenance="master", note="standing answer"))
    from .apply.standing import LEGAL
    for a in list(fa.answers):   # legal declarations stay with the person, however sure the model is
        if LEGAL.search(a.question) and a.note != "standing answer":
            fa.answers.remove(a)
            if a.question not in fa.needs_human:
                fa.needs_human.append(a.question)
    from .answer_bank import lookup
    for q in list(fa.needs_human):   # asked before and answered by the person: never asked again
        v = lookup(q, job.get("company") or "")
        if v is not None:
            fa.needs_human.remove(q)
            if q not in have:
                fa.answers.append(FormAnswer(question=q, answer=v, provenance="master", note="saved answer"))
    for a in fa.answers:
        v = standing_answer(a.question, opts.get(a.question))
        if v is not None:
            a.answer, a.provenance, a.note = v, "master", "standing answer"
            continue
        v = identity_answer(a.question)
        if v is not None:
            a.answer, a.provenance, a.note = v, "master", "identity rule: legal name first"
    return fa


# ---------------------------------------------------------------- email / proposal
class EmailDraft(BaseModel):
    to_guess: str = Field(description="best guess at recipient (name/role), or '' if unknown. Never invent an email address")
    subject: str
    body: str = Field(description="plain text, <= 160 words for applications, <= 260 for proposals; ends with a specific ask")
    diy_ratio: float
    diy_notes: list[str]
    why_them: str = Field(description="one sentence: the specific thing about this company this email hinges on")


def draft_email(kind: Literal["application", "proposal", "social_mention"], company: str, context: str,
                problem_statement: str = "") -> EmailDraft:
    task = P.EMAIL.format(kind=kind.replace("_", " "), first_name=config.first_name())
    body = f"Company: {company}\n\n## CONTEXT (posting / post / article)\n{context[:10000]}"
    if problem_statement:
        body += f"\n\n## THEIR STATED PROBLEM\n{problem_statement}\n\n{P.EMAIL_PROBLEM}"
    return structured(_system(task), body, EmailDraft, effort="high", max_tokens=4000)


# ---------------------------------------------------------------- voice repair
class Repaired(BaseModel):
    text: str = Field(description="the rewritten text, same facts, same length or shorter")


def repair_text(text: str, problems: str, kind: str = "resume") -> str:
    """Rewrite one bullet / answer / email so it passes the style guide's bans. Facts must not change."""
    return structured(_system(P.REPAIR), f"Kind: {kind}\nProblems:\n{problems}\n\nText:\n{text}", Repaired, effort="low", max_tokens=4000).text


def clean_resume(content: "ResumeContent") -> list[str]:
    """Lint every bullet and blurb; repair hard issues in place; return remaining issue notes."""
    from .voicecheck import lint, report
    left = []
    def fix(s: str) -> str:
        iss = [i for i in lint(s, "resume") if i.level == "hard"]
        if not iss:
            return s
        s2 = repair_text(s, report(iss), "resume bullet")
        rest = [i for i in lint(s2, "resume") if i.level == "hard"]
        if rest:
            left.append(f"still flagged after repair: {s2} :: {report(rest)}")
        return s2
    content.summary = fix(content.summary)
    for e in content.experience:
        for b in e.bullets:
            b.text = fix(b.text)
    for p in content.projects:
        p.blurb = fix(p.blurb)
    left += [f"[soft] {i.what}" for i in lint("\n".join([content.summary] + [b.text for e in content.experience for b in e.bullets]), "resume") if i.level == "soft"]
    return left


def clean_text(text: str, kind: str) -> tuple[str, list[str]]:
    from .voicecheck import lint, report
    hard = [i for i in lint(text, kind) if i.level == "hard"]
    if hard:
        text = repair_text(text, report(hard), kind)
    rest = lint(text, kind)
    return text, [f"[{i.level}] {i.what}" for i in rest]
