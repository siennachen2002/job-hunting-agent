"""Standing answers: the questions almost every application form asks, answered once by the person.

They are a required part of the storybook. Until every required one is answered, the agent prepares and
submits nothing (agent/run.py checks `missing()`). The dashboard renders this same list as the
"Standing answers" form, so the questions live in one place: QUESTIONS below.

Answers are stored in <profile>/standing.yaml, which stays on the person's machine (profile/ is git-ignored).
"Prefer not to say" is always an answer: the agent then picks the form's decline option.
"""
from __future__ import annotations
import yaml
from pydantic import BaseModel, Field
from . import config

DECLINE = "Prefer not to say"
YES_NO = ["Yes", "No"]

# (section, key, label, kind, options, required, hint)
QUESTIONS = [
    ("Name and contact", "legal_first", "Legal first name", "text", None, True, "As on your passport or ID. Forms get this first."),
    ("Name and contact", "legal_last", "Legal last name", "text", None, True, ""),
    ("Name and contact", "preferred_name", "Preferred first name", "text", None, False, "Only used where a form asks for a preferred name."),
    ("Name and contact", "email", "Email", "text", None, True, ""),
    ("Name and contact", "phone", "Phone", "text", None, True, ""),
    ("Name and contact", "city", "Where you live (City, State/Region)", "text", None, True, "e.g. Brooklyn, NY"),
    ("Name and contact", "website", "Portfolio or website", "text", None, False, "Also the answer to 'link to your work' questions."),
    ("Name and contact", "linkedin", "LinkedIn URL", "text", None, False, ""),
    ("Name and contact", "github", "GitHub URL", "text", None, False, ""),

    ("Work eligibility", "authorized_in", "Countries where you are authorized to work", "text", None, True, "e.g. United States; Canada"),
    ("Work eligibility", "sponsorship_now", "Do you need visa sponsorship now?", "select", YES_NO, True, ""),
    ("Work eligibility", "sponsorship_future", "Will you need visa sponsorship in the future?", "select", YES_NO, True, ""),
    ("Work eligibility", "relocate", "Are you willing to relocate?", "select", YES_NO, True, ""),
    ("Work eligibility", "relocate_where", "If yes, where?", "select",
     ["Anywhere (my country and abroad)", "Within my country", "Abroad only", "Only the places below"], False, ""),
    ("Work eligibility", "relocate_places", "Places you would move to (optional)", "text", None, False, "e.g. New York, London"),
    ("Work eligibility", "onsite", "How do you want to work?", "select", ["In office or hybrid, either is fine", "Hybrid only", "Remote only"], True,
     "Answers 'can you come into the office N days a week?'"),
    ("Work eligibility", "earliest_start", "Earliest start date", "text", None, False, "e.g. June 2027, or 'two weeks after an offer'"),

    ("Education", "degree", "Highest degree (finished or in progress)", "text", None, True, "e.g. MS Strategic Design and Management"),
    ("Education", "school", "School", "text", None, True, ""),
    ("Education", "grad_date", "Graduation date (MM/YYYY)", "text", None, True, "Expected, if you are still studying."),
    ("Education", "undergrad_gpa", "Undergraduate GPA", "text", None, False, "Leave empty to have forms ask you."),
    ("Education", "grad_gpa", "Graduate GPA", "text", None, False, ""),
    ("Education", "transcript_file", "Transcript file on this computer (optional)", "text", None, False,
     "Full path to a PDF. Attached when a form asks for a transcript."),

    ("Voluntary self-identification", "gender", "Gender", "select", ["Woman", "Man", "Non-binary", DECLINE], True,
     "US forms ask these voluntarily. 'Prefer not to say' is always fine."),
    ("Voluntary self-identification", "pronouns", "Pronouns (optional)", "text", None, False, ""),
    ("Voluntary self-identification", "race", "Race", "select",
     ["Asian", "Black or African American", "Native American or Alaska Native", "Native Hawaiian or Other Pacific Islander",
      "White", "Two or more races", DECLINE], True, ""),
    ("Voluntary self-identification", "race_detail", "More specific (optional)", "text", None, False, "e.g. Korean, Mexican, Nigerian"),
    ("Voluntary self-identification", "hispanic_latino", "Hispanic or Latino?", "select", ["Yes", "No", DECLINE], True, ""),
    ("Voluntary self-identification", "veteran", "Protected veteran status", "select",
     ["I am not a protected veteran", "I am a protected veteran", DECLINE], True, ""),
    ("Voluntary self-identification", "disability", "Disability status", "select",
     ["No, I don't have a disability", "Yes, I have a disability", DECLINE], True, ""),

    ("Form defaults", "how_heard", "Answer to 'How did you hear about this job?'", "text", None, False, "Default: Company website"),
    ("Form defaults", "consent", "Required consent boxes ('I agree', privacy notice)", "select",
     ["Tick them; they are only sent after I approve", "Ask me each time"], True, ""),
]
REQUIRED = [q[1] for q in QUESTIONS if q[5]]


def path():
    return config.PROFILE_DIR / "standing.yaml"


def load() -> dict:
    p = path()
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def save(values: dict) -> dict:
    keys = {q[1] for q in QUESTIONS}
    data = {k: (str(v).strip() if v is not None else "") for k, v in values.items() if k in keys}
    path().write_text("# Standing answers (filled in the dashboard). Private: never published.\n" +
                      yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return data


def missing(values: dict | None = None) -> list[str]:
    v = load() if values is None else values
    return [q[2] for q in QUESTIONS if q[5] and not str(v.get(q[1]) or "").strip()]


class _Answer(BaseModel):
    key: str
    value: str


class _Answers(BaseModel):
    items: list[_Answer] = Field(description="only the questions the person's words clearly answer")


def fill_from(text: str) -> dict[str, str]:
    """The chat box on the Standing answers page: what the person said (or a résumé they dropped) → answers.
    Only what the words support; a select gets one of its own options. Saves and returns what changed."""
    from .providers import structured
    qs = "\n".join(f"- {k}: {label}" + (f" (one of: {' | '.join(opts)})" if opts else "") + (f" [{hint}]" if hint else "")
                   for _, k, label, _kind, opts, _req, hint in QUESTIONS)
    task = ("Fill a job applicant's standing answers from what they wrote. Use only what the text clearly says; never guess "
            "or infer demographics. For a question with options, reply with exactly one option. Keep their own spelling of names, "
            f"emails and links. If they decline a self-identification question, answer '{DECLINE}'.\n\nQuestions (key: label):\n{qs}")
    out = structured([{"type": "text", "text": task}], text, _Answers, effort="low", max_tokens=3000)
    opts = {q[1]: q[4] for q in QUESTIONS}
    cur = load(); changed = {}
    for a in out.items:
        v = a.value.strip()
        if a.key not in opts or not v:
            continue
        if opts[a.key]:
            v = next((o for o in opts[a.key] if o.lower() == v.lower()), None)
            if v is None:
                continue
        if a.key in ("website", "linkedin", "github") and not v.startswith(("http://", "https://")):
            v = "https://" + v   # forms want a full URL
        if str(cur.get(a.key) or "") != v:
            changed[a.key] = v
    if changed:
        save({**cur, **changed})
    return changed


def require() -> None:
    """Stop the pipeline until the standing answers are complete."""
    m = missing()
    if m:
        raise SystemExit("Standing answers are incomplete (" + ", ".join(m[:4]) + ("…" if len(m) > 4 else "") +
                         "). Fill them in the dashboard: Storybook → Standing answers.")
