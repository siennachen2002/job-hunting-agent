"""First run, and the Setup page: what is done, what is left, and the settings the page may write to .env.

    python -m agent.run init     a fresh profile/ (your storybook, empty) and .env, once
    python -m agent.run setup    the same checklist the dashboard's Setup page shows
"""
from __future__ import annotations
import os
import re
import shutil
from . import config

# what the Setup page may write; secrets are never sent back to the page, only whether they are set
KEYS = ["JHA_MODEL", "JHA_DRAFT_MODEL", "ANTHROPIC_API_KEY", "JHA_OPENAI_BASE_URL", "JHA_OPENAI_API_KEY", "OLLAMA_BASE_URL",
        "JHA_MAIL_ADDRESS", "JHA_MAIL_APP_PASSWORD", "TYPESAFE_API_KEY", "JHA_ACCESS_KEY", "JHA_HOST"]
SECRET = {"ANTHROPIC_API_KEY", "JHA_OPENAI_API_KEY", "JHA_MAIL_APP_PASSWORD", "TYPESAFE_API_KEY", "JHA_ACCESS_KEY"}
KEY_NAMES = {"TYPESAFE_API_KEY": "Jev (TypeSafe)", "ANTHROPIC_API_KEY": "Anthropic", "JHA_OPENAI_API_KEY": "OpenAI-compatible server",
             "JHA_MAIL_APP_PASSWORD": "Mailbox app password"}   # every secret the Setup page's API keys step saves
LINE = re.compile(r"^- .+\[[a-z_, ]+\]\s*$", re.M)   # a résumé-ready storybook line


def init() -> list[str]:
    """Create what a new person needs, without overwriting anything: profile/ from the example's templates (not its
    fictional person), and .env from .env.example. Returns what was created."""
    made = []
    env, example = config.ROOT / ".env", config.ROOT / ".env.example"
    if not env.exists() and example.exists():
        shutil.copy(example, env); made.append(".env")
    if not (config.ROOT / "profile").exists():
        new_profile(config.ROOT / "profile"); made.append("profile/")
    return made


def new_profile(prof, demo: bool = False) -> None:
    """An empty profile folder: the example's templates (role lenses, watchlist, preferences, guides), no person in it."""
    src = config.ROOT / "profile.example"
    (prof / "master").mkdir(parents=True)
    for f in ("preferences.yaml", "roles.yaml", "companies.yaml"):
        shutil.copy(src / f, prof / f)
    for f in ("00-README.md", "06-roles.md", "07-voice.md"):
        shutil.copy(src / "master" / f, prof / "master" / f)
    (prof / "master" / "02-experience.md").write_text("# Experience\n", encoding="utf-8")
    (prof / "master" / "03-projects.md").write_text("# Projects\n", encoding="utf-8")
    (prof / "profile.yaml").write_text("# About you. Your name and contact details come from the standing answers.\n"
                                       + ("demo: true   # a demo account: fills real forms up to Submit, never sends anything\n" if demo else "")
                                       + "summary_for_ranker: \"\"   # one line the ranker reads, e.g. 'Product designer, 4 years in climate'\n",
                                       encoding="utf-8")


def write_env(values: dict) -> list[str]:
    """Set keys in .env (and in this process). A blank secret means 'leave it as it is'; a blank model clears it."""
    path = config.ROOT / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    changed = []
    for k, v in values.items():
        if k not in KEYS:
            continue
        v = (v or "").strip()
        if k in SECRET and not v:
            continue
        val = f'"{v}"' if re.search(r"[\s#'\"]", v) and not v.startswith('"') else v
        for i, l in enumerate(lines):
            if re.match(rf"\s*#?\s*{k}\s*=", l):
                lines[i] = f"{k}={val}"; break
        else:
            lines.append(f"{k}={val}")
        if v:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)
        changed.append(k)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def status() -> dict:
    """The checklist. Required steps gate the agent; the rest make it better."""
    from . import providers, setup_answers, mailbox, jev
    from .apply import browser
    m = providers.describe()
    sa = setup_answers.load()
    left = setup_answers.missing(sa)
    lines = sum(len(LINE.findall(p.read_text(encoding="utf-8"))) for p in config.MASTER_DIR.glob("0[23]-*.md")) if config.MASTER_DIR.exists() else 0
    mb = mailbox.settings()
    signed = (browser.PROFILE / "Default" / "Cookies").exists()
    steps = [
        dict(id="model", title="Connect a model", required=True, done=bool(m["model"]["label"]) and not m["model"]["missing"],
             detail=(m["model"]["missing"] or f"Model: {m['model']['label']} · Draft model: {m['draft']['label'] or 'none, the model does everything'}")),
        dict(id="standing", title="Answer the standing questions", required=True, done=not left,
             detail="All answered." if not left else f"{len(left)} left: {', '.join(left[:4])}{'…' if len(left) > 4 else ''}"),
        dict(id="storybook", title="Tell it everything", required=True, done=lines > 0,
             detail=f"{lines} résumé lines in your storybook." if lines else "Your storybook is empty: drop your old résumés, or just talk."),
        dict(id="mailbox", title="Connect your application mailbox", required=False, done=mailbox.configured(),
             detail=("A demo account has no mailbox: nothing is sent, and there are no replies to read." if config.is_demo() else
                     f"Reading replies at {mb['address']} (read-only)." if mailbox.configured() else
                     "So it can tell you who wrote back, and send the emails you approve.")),
        dict(id="browser", title="Sign in where you keep job accounts", required=False, done=signed,
             detail="Only for sites that need an account, like a company's Workday. Greenhouse, Lever and Ashby need none."),
        dict(id="phone", title="Use it on your phone", required=False,
             done=bool(os.getenv("JHA_ACCESS_KEY")) and os.getenv("JHA_HOST", "127.0.0.1") != "127.0.0.1",
             detail="Review and approve from your phone, anywhere, through Tailscale (a private link between your own devices)."),
        dict(id="keys", title="API keys", required=False, done=jev.available(),
             detail="Saved: " + (", ".join(n for k, n in KEY_NAMES.items() if os.getenv(k)) or "none yet")
                    + ("" if jev.available() else " · Jev isn't connected, so Claude Code rates postings (no API)")),
    ]
    return {"steps": steps, "ready": all(s["done"] for s in steps if s["required"]), "models": m, "demo": config.is_demo(),
            "mailbox": {"address": mb["address"], "configured": mailbox.configured(), "gmail": mb["gmail"]},
            "browser": {"chrome": bool(browser.chrome())}, "providers": providers.PROVIDERS}


def report() -> str:
    s = status()
    out = []
    for i, st in enumerate(s["steps"], 1):
        mark = "✓" if st["done"] else ("·" if not st["required"] else "✗")
        out.append(f" {mark} {i}. {st['title']}{'' if st['required'] else ' (optional)'}\n      {st['detail']}")
    out.append("\nReady: the agent can work." if s["ready"] else "\nNot ready yet: finish the steps marked ✗ (the dashboard's Setup page walks you through them).")
    return "\n".join(out)
