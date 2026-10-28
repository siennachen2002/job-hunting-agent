"""Central settings. Everything path-related lives here."""
from __future__ import annotations
import os
import re
from pathlib import Path
from dotenv import load_dotenv
import yaml

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "out"
RESUME_OUT = OUT_DIR / "resumes"
# One storybook per story you want to tell: JHA_PROFILE=profiles/design-engineer python -m agent.run daily
PROFILE_DIR = Path(os.getenv("JHA_PROFILE")).expanduser() if os.getenv("JHA_PROFILE") else (
    ROOT / "profile" if (ROOT / "profile").exists() else ROOT / "profile.example")
if not PROFILE_DIR.is_absolute():
    PROFILE_DIR = ROOT / PROFILE_DIR
MASTER_DIR = PROFILE_DIR / "master"
DOCS_DIR = ROOT / "docs"
# Accounts (agent/accounts.py): profile/ is the main one; profiles/<name>/ each get their own database and browser profile
ACCOUNT = "" if PROFILE_DIR.resolve() == (ROOT / "profile").resolve() else re.sub(r"\W+", "-", PROFILE_DIR.name).strip("-")
DB_PATH = Path(os.getenv("JHA_DB", str(DATA_DIR / (f"{ACCOUNT}.sqlite" if ACCOUNT else "jobs.sqlite"))))
BROWSER_DIR = DATA_DIR / (f"browser-{ACCOUNT}" if ACCOUNT else "browser")
REFRESHED = DATA_DIR / (f"last_refresh-{ACCOUNT}.json" if ACCOUNT else "last_refresh.json")   # this account's last Refresh
SCREENS = OUT_DIR / "screens" / ACCOUNT if ACCOUNT else OUT_DIR / "screens"   # form screenshots, named by application id

for d in (DATA_DIR, RESUME_OUT, OUT_DIR / "emails"):
    d.mkdir(parents=True, exist_ok=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")   # which model runs each step: agent/providers.py
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")

USER_AGENT = "job-hunting-agent/0.1 (personal, low-volume)"


def _load_yaml(path: Path, default):
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or default


def preferences() -> dict:
    return _load_yaml(PROFILE_DIR / "preferences.yaml", {})


def roles() -> dict:
    return _load_yaml(PROFILE_DIR / "roles.yaml", {})


def companies() -> list[dict]:
    return _load_yaml(PROFILE_DIR / "companies.yaml", {}).get("companies", [])


def boards() -> list[dict]:
    """Job boards that list many companies (agent/sources/boards.py): companies.yaml → boards."""
    return _load_yaml(PROFILE_DIR / "companies.yaml", {}).get("boards", [])


def master_text() -> str:
    """Concatenate every markdown/text file in profile/master, in filename order.
    PDFs/DOCX should be converted to .md first (see docs/01)."""
    parts = []
    for p in sorted(MASTER_DIR.glob("*")):
        if p.suffix.lower() in {".md", ".txt"}:
            parts.append(f"\n\n<!-- file: {p.name} -->\n" + p.read_text(encoding="utf-8"))
    return "".join(parts).strip()


def profile() -> dict:
    """Person-specific data (profile/profile.yaml). Code never hard-codes a person."""
    return _load_yaml(PROFILE_DIR / "profile.yaml", {})


def is_demo() -> bool:
    """A demo account (profile.yaml: demo: true) fills real forms up to Submit and never sends anything:
    no submitting, no résumé uploads to real sites, no email, no mailbox."""
    return bool(profile().get("demo"))


def _name() -> str:
    """profile.yaml's name, else the standing answers (a new profile keeps the name only there)."""
    n = profile().get("name")
    if not n:
        from .setup_answers import load
        sa = load()
        n = " ".join(x for x in (sa.get("preferred_name") or sa.get("legal_first"), sa.get("legal_last")) if x)
    return n or ""


def person() -> dict:
    """Who the résumé is about: profile.yaml where it says so, else the standing answers (a new profile keeps the
    name, contact details, links and degree only there)."""
    from .setup_answers import load
    p, sa = profile(), load()
    links = dict(p.get("links") or {})
    for k in ("website", "linkedin", "github"):
        links[k] = links.get(k) or sa.get(k) or ""
    edu = p.get("education") or ([{"school": sa["school"], "degree": sa.get("degree", ""), "dates": sa.get("grad_date", ""), "note": ""}]
                                 if sa.get("school") else [])
    return {"name": _name(), "email": p.get("email") or sa.get("email", ""), "phone": str(p.get("phone") or sa.get("phone", "")),
            "location": p.get("location") or sa.get("city", ""), "links": {k: v for k, v in links.items() if v}, "education": edu}


def first_name() -> str:
    return (_name() or "the candidate").split()[0]


def file_stem() -> str:
    return re.sub(r"\W+", "_", _name() or "Candidate").strip("_")
