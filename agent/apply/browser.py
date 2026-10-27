"""The agent's own browser: a separate profile in data/browser, never your everyday Chrome.

Where you keep an account (a company's Workday, a careers site that wants you signed in), you sign in yourself, once,
in this browser: dashboard → Setup → Open the agent's browser, or `python -m agent.run browser`. The session stays in
the profile, so the filler is signed in when it fills that site's forms. The agent never sees, types or stores a
password. It uses Google Chrome when installed (sites trust it more than a bare test browser), else Playwright's Chromium.
LinkedIn and Indeed are never automated, signed in or not.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
from pathlib import Path
from .. import config

PROFILE = config.BROWSER_DIR                       # one per account: a demo account never sees your sign-ins
START = config.DATA_DIR / "browser-start.html"


def chrome() -> str | None:
    """Google Chrome's executable on this computer, if any."""
    for c in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
              os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
              os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe")):
        if c and os.path.exists(c):
            return c
    return shutil.which("google-chrome") or shutil.which("google-chrome-stable") or shutil.which("chromium")


def open_page(p, headless: bool = True, viewport: dict | None = None):
    """A page in the agent's browser profile, and a function that closes it. If the profile is busy (its window is open
    for signing in, or another run has it), a fresh profile is used instead: the fill works, without your sign-ins."""
    PROFILE.mkdir(parents=True, exist_ok=True)
    # a window you watch takes the screen's size, so it scrolls like any page; only a hidden one draws a tall page for screenshots
    kw = dict(headless=headless, viewport=viewport or {"width": 1280, "height": 1600}) if headless else \
        dict(headless=False, no_viewport=True, args=["--start-maximized"])
    for channel in (["chrome"] if chrome() else []) + [None]:
        try:
            ctx = p.chromium.launch_persistent_context(str(PROFILE), **({**kw, "channel": channel} if channel else kw))
            return ctx.new_page(), ctx.close
        except Exception as e:
            last = e
    print(f"  the agent's browser profile is busy ({last.__class__.__name__}); using a fresh one for this run")
    b = p.chromium.launch(headless=headless, args=kw.get("args") or [])
    return (b.new_page(viewport=kw["viewport"]) if headless else b.new_page(no_viewport=True)), b.close


def call_person(pg, message: str, target: str | None = None) -> None:
    """Put the submit window in front of the person, scrolled to what needs them, with a banner saying what to do."""
    try:
        if target and pg.locator(target).count():
            pg.locator(target).first.scroll_into_view_if_needed(timeout=3000)
        pg.evaluate("""m => { let b = document.getElementById('jha-banner'); if (!b) { b = document.createElement('div'); b.id = 'jha-banner';
            b.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;background:#B91C1C;color:#fff;font:600 16px/1.4 -apple-system,sans-serif;padding:14px 20px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.25)';
            document.body.appendChild(b); } b.textContent = 'Job Hunter Agent: ' + m; }""", message)
        pg.bring_to_front()
    except Exception:
        pass
    if sys.platform == "darwin":   # raise this browser's own window, not your everyday Chrome
        try:
            pid = subprocess.run(["pgrep", "-o", "-f", "Chrom.*" + str(PROFILE if PROFILE.exists() else "ms-playwright")],
                                 capture_output=True, text=True).stdout.split()
            if pid:
                subprocess.run(["osascript", "-e", f'tell application "System Events" to set frontmost of (first process whose unix id is {pid[0]}) to true'],
                               capture_output=True)
        except Exception:
            pass
        subprocess.run(["osascript", "-e", f'display notification "{message[:120]}" with title "Job Hunter Agent" sound name "Glass"'], capture_output=True)


START_PAGE = """<!doctype html><meta charset="utf-8"><title>The agent's browser</title>
<body style="font:16px/1.55 -apple-system,Segoe UI,sans-serif;max-width:620px;margin:64px auto;padding:0 24px;color:#1C1917;background:#FAF8F5">
<h1 style="font-size:28px;letter-spacing:-.02em">This is the agent's browser</h1>
<p>It is separate from your everyday browser. Sign in here, yourself, to the sites where you keep a job account, such as a
company's Workday page. The agent reuses the session when it fills that site's forms. It never sees, types or keeps your password.</p>
<p><b>You don't need to sign in to anything else.</b> Greenhouse, Lever and Ashby applications need no account, and
LinkedIn and Indeed are never automated, so there is no reason to sign in to them here.</p>
<p>When you're done, close this window. Keep it closed while the agent fills forms.</p></body>"""


def open_for_signing_in(url: str = "") -> str:
    """Open the agent's browser for you to sign in (a normal window, not automated). Returns what was opened."""
    PROFILE.mkdir(parents=True, exist_ok=True)
    START.write_text(START_PAGE, encoding="utf-8")
    target = url or START.as_uri()
    c = chrome()
    if c:
        flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {"start_new_session": True}
        subprocess.Popen([c, f"--user-data-dir={PROFILE}", "--no-first-run", "--no-default-browser-check", target],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flags)
        return "Google Chrome"
    from playwright.sync_api import sync_playwright   # no Chrome: Playwright's Chromium, until you close it
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(PROFILE), headless=False, viewport=None)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(target)
        page.wait_for_event("close", timeout=0)
        ctx.close()
    return "Chromium"
