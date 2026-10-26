"""Local review dashboard.  python -m dashboard.app  ->  http://127.0.0.1:8765"""
from __future__ import annotations
import json
import os
import re
from pathlib import Path


def _account_from_switcher() -> None:
    """The app's account switcher (agent/accounts.py) leaves its choice in data/account.json. Use it unless this server
    was started for a given profile (JHA_PROFILE set by hand); what the server starts (Refresh, Prepare) inherits it."""
    if os.environ.get("JHA_PROFILE") and os.environ.get("JHA_ACCOUNT_SWITCHER") != "1":
        return
    f = Path(__file__).resolve().parent.parent / "data" / "account.json"
    try:
        a = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        a = {}
    os.environ.pop("JHA_PROFILE", None); os.environ.pop("JHA_DB", None)
    if a.get("profile"):
        os.environ.update(JHA_PROFILE=a["profile"], JHA_ACCOUNT_SWITCHER="1")


_account_from_switcher()
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from agent import db

HERE = Path(__file__).parent
app = FastAPI(title="Job Hunter Agent")


# ---- phone: this Mac opens freely; any other device (your phone over Tailscale) needs your private link once ----------
from fastapi import Request
from fastapi.responses import RedirectResponse, PlainTextResponse
LOCAL = {"127.0.0.1", "::1", "localhost"}


@app.middleware("http")
async def phone_key(request: Request, call_next):
    if (request.client.host if request.client else "") in LOCAL:
        return await call_next(request)
    key = os.getenv("JHA_ACCESS_KEY", "")
    given = request.query_params.get("key")
    if key and given == key:   # the private link: remember this phone, then drop the key from the address bar
        r = RedirectResponse(request.url.path or "/", status_code=303)
        r.set_cookie("jha_key", key, max_age=400 * 86400, httponly=True, samesite="lax")
        return r
    if key and request.cookies.get("jha_key") == key:
        return await call_next(request)
    return PlainTextResponse("Open this with your private phone link (Setup → Use it on your phone, on your Mac).", status_code=403)


def _tailscale_ip() -> str:
    import shutil, subprocess
    for exe in (shutil.which("tailscale"), "/Applications/Tailscale.app/Contents/MacOS/Tailscale"):
        if exe and Path(exe).exists():
            try:
                out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=5).stdout.split()
                if out:
                    return out[0]
            except Exception:
                pass
    return ""


@app.get("/api/phone")
def phone():
    """What the Setup page's phone step shows: is Tailscale up, is the server reachable, the private link."""
    ip = _tailscale_ip()
    listening = os.getenv("JHA_HOST", "127.0.0.1") != "127.0.0.1"
    key = os.getenv("JHA_ACCESS_KEY", "")
    port = int(os.getenv("JHA_PORT", "8765"))
    return {"tailscale": bool(ip), "listening": listening, "has_key": bool(key),
            "link": f"http://{ip}:{port}/?key={key}" if ip and key and listening else ""}


@app.get("/manifest.webmanifest")
def manifest(request: Request):
    """Add to Home Screen: opens full screen like an app. A home-screen app keeps its own cookies on iPhone,
    so its start address carries the private key (only devices already let in ever see this)."""
    key = os.getenv("JHA_ACCESS_KEY", "")
    local = (request.client.host if request.client else "") in LOCAL
    return JSONResponse({"name": "Job Hunter Agent", "short_name": "Job Hunter", "display": "standalone",
                         "start_url": "/" if local or not key else f"/?key={key}", "scope": "/",
                         "background_color": "#FAF9F7", "theme_color": "#FAF9F7",
                         "icons": [{"src": "/static/icon.png", "sizes": "256x256", "type": "image/png"},
                                   {"src": "/static/icon.svg", "sizes": "any", "type": "image/svg+xml"}]},
                        media_type="application/manifest+json")


@app.post("/api/phone/enable")
def phone_enable():
    """Make a private key, listen beyond this Mac (behind the key), then restart this server."""
    import secrets
    from agent.setup import write_env
    write_env({"JHA_ACCESS_KEY": os.getenv("JHA_ACCESS_KEY") or secrets.token_urlsafe(18), "JHA_HOST": "0.0.0.0"})
    _restart_soon()
    return {"ok": True, "restarting": True}


def rows(q, *args):
    with db.tx() as con:
        return [dict(r) for r in con.execute(q, args).fetchall()]


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html", headers={"Cache-Control": "no-cache"})   # an update shows at once


@app.get("/api/stats")
def stats():
    with db.tx() as con:
        jobs = {r["status"]: r["c"] for r in con.execute("SELECT status, COUNT(*) c FROM jobs GROUP BY status")}
        apps = {r["status"]: r["c"] for r in con.execute("SELECT status, COUNT(*) c FROM applications GROUP BY status")}
        last = con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    return {"jobs": jobs, "applications": apps, "last_run": dict(last) if last else None}


@app.get("/api/jobs")
def jobs(status: str | None = None, min_score: float = 0, limit: int = 300):
    q = "SELECT id, source, company, title, location, remote, url, sector, status, score, score_reason, discovered_at, posted_at FROM jobs WHERE score IS NOT NULL AND score>=?"
    args: list = [min_score]
    if status:
        q += " AND status=?"; args.append(status)
    q += " ORDER BY score DESC, discovered_at DESC LIMIT ?"; args.append(limit)
    return rows(q, *args)


@app.get("/api/jobs/{job_id}")
def job(job_id: int):
    r = rows("SELECT * FROM jobs WHERE id=?", job_id)
    if not r:
        raise HTTPException(404)
    j = r[0]
    j["score_json"] = json.loads(j["score_json"]) if j.get("score_json") else None
    return j


@app.get("/api/applications")
def applications(status: str | None = None):
    q = """SELECT a.*, j.company AS job_company, j.title AS job_title, j.url AS job_url, j.score AS job_score,
                  c.name AS company_name
           FROM applications a LEFT JOIN jobs j ON j.id=a.job_id LEFT JOIN companies c ON c.id=a.company_id"""
    args: list = []
    if status:
        q += " WHERE a.status=?"; args.append(status)
    q += " ORDER BY a.id DESC"
    out = rows(q, *args)
    for a in out:
        for k in ("resume_json", "answers_json"):
            if a.get(k):
                try:
                    a[k] = json.loads(a[k])
                except Exception:
                    pass
    return out


class Decision(BaseModel):
    note: str = ""


REFRESH = {}


@app.post("/api/update-app")
def update_app():
    """Update app: the newest version from GitHub when there is one, then this server starts again on the code on disk,
    so every change shows. Jobs and replies are not touched (that is Refresh jobs & replies)."""
    from agent.run import self_update
    r = self_update()
    _restart_soon()
    return {"ok": True, **r}


@app.post("/api/refresh")
def refresh_start():
    import subprocess, sys
    p = REFRESH.get("proc")
    if not (p and p.poll() is None):
        REFRESH["proc"] = subprocess.Popen([sys.executable, "-m", "agent.run", "refresh"], cwd=str(HERE.parent),
                                           stdout=open(HERE.parent / "data" / "refresh.log", "w"), stderr=subprocess.STDOUT)
    return {"ok": True}


@app.get("/api/refresh")
def refresh_status():
    from agent import config
    p = REFRESH.get("proc"); f = config.REFRESHED
    last = json.loads(f.read_text()) if f.exists() else {}
    running = bool(p and p.poll() is None)
    restarting = False
    if not running and p and last.get("restart") and REFRESH.get("restarted_for") != last.get("at"):
        # the update changed the app's code: start this server again on it, a moment after answering
        import os, sys, threading
        REFRESH["restarted_for"] = last.get("at"); restarting = True
        threading.Timer(.6, lambda: os.execv(sys.executable, [sys.executable, "-m", "dashboard.app"])).start()
    return {"running": running, "failed": bool(p and p.poll() not in (None, 0)), "restarting": restarting, **last}


class Stage(BaseModel):
    stage: str


@app.post("/api/applications/{app_id}/stage")
def set_stage(app_id: int, s: Stage):
    from agent.replies import advance, STAGES
    if s.stage not in STAGES + ["rejected"]:
        raise HTTPException(400)
    with db.tx() as con:
        advance(con, app_id, s.stage, "set in the dashboard", by_person=True); con.commit()
    return {"ok": True}


class Standing(BaseModel):
    values: dict


@app.get("/api/standing")
def standing_get():
    from agent import setup_answers as sa
    v = sa.load()
    return {"questions": [{"section": q[0], "key": q[1], "label": q[2], "kind": q[3], "options": q[4], "required": q[5], "hint": q[6]}
                          for q in sa.QUESTIONS], "values": v, "missing": sa.missing(v)}


@app.put("/api/standing")
def standing_put(s: Standing):
    from agent import setup_answers as sa
    from agent.audit import log
    v = sa.save(s.values)
    with db.tx() as con:
        log(con, "intake", "standing-answers", f"saved; {len(sa.missing(v))} required left")
    return {"ok": True, "missing": sa.missing(v)}


BLANK = re.compile(r"\[YOUR ANSWER", re.I)


def _blanks(a: dict) -> list[str]:
    """Where an application still has a [YOUR ANSWER …] placeholder: it can't be approved until each one is filled."""
    aj = json.loads(a.get("answers_json") or "{}") if (a.get("answers_json") or "").startswith("{") else {}
    where = []
    if BLANK.search((a.get("email_body") or "") + (a.get("email_subject") or "")):
        where.append("the email")
    if BLANK.search(a.get("cover_text") or ""):
        where.append("the cover letter")
    where += [f"'{x['question'][:60]}'" for x in aj.get("answers", []) if BLANK.search(x.get("answer") or "")]
    return where


@app.post("/api/applications/{app_id}/approve")
def approve(app_id: int, d: Decision | None = None):
    with db.tx() as con:   # a [YOUR ANSWER] placeholder must never reach an employer
        row = con.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
        blanks = _blanks(dict(row)) if row else []
    if blanks:
        return {"ok": False, "msg": "Fill in the [YOUR ANSWER] blank in " + ", ".join(blanks) + " before approving."}
    from agent.audit import log
    from agent.setup_answers import missing
    if missing():
        return {"ok": False, "msg": "Finish your standing answers first (Storybook → Standing answers)."}
    with db.tx() as con:
        a = con.execute("SELECT kind, answers_json FROM applications WHERE id=?", (app_id,)).fetchone()
        if a and (json.loads(a["answers_json"] or "{}").get("needs_human")):
            return {"ok": False, "msg": "Answer the open questions first."}
        from agent import config
        if config.is_demo():
            db.update_application(con, app_id, status="approved", approved_at=db.now(), error="demo account: not sent")
            log(con, "review", "approved (demo, not sent)", d.note if d else "", app_id=app_id)
            return {"ok": True, "msg": "Demo account: nothing was sent. In your own account, Approve submits this exact form."}
        db.update_application(con, app_id, status="approved", approved_at=db.now())
        log(con, "review", "approved", d.note if d else "", app_id=app_id)
    if a and a["kind"] == "ats_web":
        import subprocess, sys
        subprocess.Popen([sys.executable, "-m", "agent.run", "submit", "--app", str(app_id)], cwd=str(HERE.parent),
                         stdout=open(HERE.parent / "data" / f"submit-{app_id}.log", "w"), stderr=subprocess.STDOUT)
        return {"ok": True, "msg": "Submitting in a browser window. If a CAPTCHA appears, finish it there."}
    from agent.mailbox import configured
    if a and a["kind"] in ("email", "proposal") and configured():
        import subprocess, sys
        subprocess.Popen([sys.executable, "-m", "agent.run", "mail-send", "--app", str(app_id)], cwd=str(HERE.parent),
                         stdout=open(HERE.parent / "data" / f"send-{app_id}.log", "w"), stderr=subprocess.STDOUT)
        return {"ok": True, "msg": "Sending from your application address now."}
    return {"ok": True, "msg": "Approved. The email goes out with the next daily run."}


@app.post("/api/applications/{app_id}/reject")
def reject(app_id: int, d: Decision | None = None):
    from agent.audit import log
    from agent.learn import add_feedback
    with db.tx() as con:
        db.update_application(con, app_id, status="withdrawn", error=(d.note if d else None))
        log(con, "review", "rejected", d.note if d else "", app_id=app_id)
        if d and d.note:
            add_feedback(con, "Rejected because: " + d.note, app_id)
    return {"ok": True}


@app.get("/api/applications/{app_id}/checklist")
def app_checklist(app_id: int):
    from agent.audit import checklist
    a = rows("SELECT * FROM applications WHERE id=?", app_id)
    if not a:
        raise HTTPException(404)
    j = rows("SELECT * FROM jobs WHERE id=?", a[0]["job_id"]) if a[0].get("job_id") else []
    return checklist(a[0], j[0] if j else None)


class Note(BaseModel):
    text: str
    app_id: int | None = None


@app.post("/api/feedback")
def feedback(n: Note):
    from agent.learn import add_feedback
    from agent.audit import log
    with db.tx() as con:
        add_feedback(con, n.text, n.app_id)
        log(con, "review", "note", n.text[:200], app_id=n.app_id)
    return {"ok": True}


@app.get("/api/proposals")
def proposals():
    from agent.learn import init
    with db.tx() as con:
        init(con)
        return [dict(r) for r in con.execute("SELECT * FROM proposals ORDER BY id DESC LIMIT 200").fetchall()]


@app.post("/api/proposals/{pid}/{action}")
def proposal_action(pid: int, action: str):
    from agent import learn
    with db.tx() as con:
        learn.init(con)
        if action == "approve":
            try:
                return {"ok": True, "msg": learn.apply(con, pid)}
            except Exception as e:
                return {"ok": False, "msg": str(e)}
        if action == "reject":
            con.execute("UPDATE proposals SET status='rejected', decided_at=? WHERE id=?", (db.now(), pid)); return {"ok": True}
        if action == "revert":
            return {"ok": True, "msg": learn.revert(con, pid)}
    raise HTTPException(400)


@app.get("/api/events")
def events(limit: int = 200):
    from agent.audit import recent
    with db.tx() as con:
        return recent(con, limit)


class EmailEdit(BaseModel):
    email_to: str | None = None
    email_subject: str | None = None
    email_body: str | None = None
    cover_text: str | None = None


@app.post("/api/applications/{app_id}/edit")
def edit(app_id: int, e: EmailEdit):
    fields = {k: v for k, v in e.model_dump().items() if v is not None}
    if not fields:
        return {"ok": False}
    with db.tx() as con:
        db.update_application(con, app_id, **fields)
    return {"ok": True}


# ---- setup: the checklist a new person follows; settings go to .env, secrets never come back to the page -------
@app.get("/api/setup")
def setup_status():
    from agent.setup import status
    return status()


class EnvValues(BaseModel):
    values: dict


@app.post("/api/setup/env")
def setup_env(e: EnvValues):
    from agent.setup import write_env, status
    return {"ok": True, "changed": write_env(e.values), **status()}


class SetupTest(BaseModel):
    what: str


@app.post("/api/setup/test")
def setup_test(t: SetupTest):
    if t.what in ("model", "draft"):
        from agent.providers import check
        return check(t.what)
    if t.what == "mail":
        from agent.mailbox import test
        try:
            msg = test()
            return {"ok": msg.startswith("ok"), "msg": msg}
        except Exception as e:
            return {"ok": False, "msg": f"{e.__class__.__name__}: {str(e)[:200]}. Check the address and the app password."}
    if t.what == "jev":
        from agent.jev import score_batch
        try:
            p = score_batch([{"company": "Example", "title": "Product Designer", "location": "New York", "description": "Design product."}])[0]
            return {"ok": p is not None, "msg": "Jev answered." if p is not None else "No key set."}
        except Exception as e:
            return {"ok": False, "msg": f"{e.__class__.__name__}: {str(e)[:200]}"}
    return {"ok": False, "msg": "unknown test"}


@app.post("/api/setup/browser")
def setup_browser():
    import subprocess, sys
    subprocess.Popen([sys.executable, "-m", "agent.run", "browser"], cwd=str(HERE.parent),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True}


# ---- accounts: yours, other stories, demo accounts; switching restarts this server on the chosen one -------------
@app.get("/api/accounts")
def accounts_list():
    from agent import accounts, config
    return {"accounts": accounts.listing(), "demo": config.is_demo()}


class AccountPick(BaseModel):
    id: str = ""


def _restart_soon():
    import sys, threading
    threading.Timer(.5, lambda: os.execv(sys.executable, [sys.executable, "-m", "dashboard.app"])).start()


@app.post("/api/accounts/switch")
def accounts_switch(p: AccountPick):
    from agent import accounts
    try:
        accounts.switch(p.id)
    except ValueError as e:
        return {"ok": False, "msg": str(e)}
    _restart_soon()
    return {"ok": True, "restarting": True}


@app.post("/api/accounts/demo")
def accounts_new_demo():
    from agent import accounts
    accounts.switch(accounts.create_demo())
    _restart_soon()
    return {"ok": True, "restarting": True}


@app.post("/api/accounts/remove")
def accounts_remove(p: AccountPick):
    from agent import accounts
    try:
        accounts.remove_demo(p.id)
    except PermissionError as e:
        return {"ok": False, "msg": str(e)}
    return {"ok": True}


@app.post("/api/demo/answers")
def demo_answers():
    from agent import accounts
    try:
        return {"ok": True, "filled": accounts.demo_answers()}
    except PermissionError as e:
        return {"ok": False, "msg": str(e)}


@app.post("/api/demo/materials")
def demo_materials():
    """Show the sample material (demo/materials) in Finder or Explorer, ready to drag onto Drop anything."""
    import subprocess, sys
    from agent.accounts import DEMO_DIR
    folder = str(DEMO_DIR / "materials")
    cmd = ["open", folder] if sys.platform == "darwin" else ["explorer", folder] if os.name == "nt" else ["xdg-open", folder]
    subprocess.Popen(cmd)
    return {"ok": True}


class Revise(BaseModel):
    text: str


REVISE: dict[int, dict] = {}


@app.post("/api/applications/{app_id}/revise")
def revise_resume(app_id: int, r: Revise):
    """The person's note on this résumé ("lead with the climate work"): rewritten and re-rendered in the background."""
    import threading, time
    if not r.text.strip():
        return {"ok": False, "msg": "Say what to change first."}
    if REVISE.get(app_id, {}).get("state") == "running":
        return {"ok": False, "msg": "Already revising this résumé."}
    REVISE[app_id] = {"state": "running", "since": time.time()}

    def work():
        from agent.run import revise
        try:
            with db.tx() as con:
                revise(con, app_id, r.text.strip())
            REVISE[app_id] = {"state": "done", "at": time.time()}
        except Exception as e:
            REVISE[app_id] = {"state": "error", "error": str(e)[:300]}
    threading.Thread(target=work, daemon=True).start()
    return {"ok": True}


@app.get("/api/applications/{app_id}/revise-status")
def revise_status(app_id: int):
    return REVISE.get(app_id, {"state": "idle"})


FRESH = {"Cache-Control": "no-cache"}   # /screen/1 is a different file in each account, and changes when a résumé is revised


@app.get("/screen/{app_id}")
def screen(app_id: int):
    r = rows("SELECT sent_log FROM applications WHERE id=?", app_id)
    import re as _r
    m = _r.search(r"screenshot: (.+?\.png)", (r[0]["sent_log"] or "") if r else "")
    if not m or not Path(m.group(1)).exists():
        raise HTTPException(404)
    return FileResponse(m.group(1), media_type="image/png", headers=FRESH)


@app.get("/resume/{app_id}")
def resume(app_id: int):
    r = rows("SELECT resume_pdf FROM applications WHERE id=?", app_id)
    if not r or not r[0]["resume_pdf"] or not Path(r[0]["resume_pdf"]).exists():
        raise HTTPException(404)
    return FileResponse(r[0]["resume_pdf"], media_type="application/pdf", headers=FRESH)


# ---- playbook (profile/master) -------------------------------------------
from agent.config import MASTER_DIR
import re as _re


def _safe(name: str) -> Path:
    if not _re.fullmatch(r"[A-Za-z0-9._-]+\.(md|txt)", name):
        raise HTTPException(400, "bad name")
    return MASTER_DIR / name


@app.get("/api/playbook")
def playbook_list():
    out = []
    for f in sorted(MASTER_DIR.glob("*")):
        if f.suffix in (".md", ".txt"):
            txt = f.read_text(encoding="utf-8")
            out.append({"name": f.name, "words": len(txt.split()), "fill": txt.count("[fill"), "confirm": txt.count("[confirm"),
                        "mtime": f.stat().st_mtime})
    return out


@app.get("/api/playbook/{name}")
def playbook_get(name: str):
    f = _safe(name)
    if not f.exists():
        raise HTTPException(404)
    return {"name": name, "text": f.read_text(encoding="utf-8")}


class Text(BaseModel):
    text: str


@app.put("/api/playbook/{name}")
def playbook_put(name: str, t: Text):
    f = _safe(name)
    if f.exists() and f.read_text(encoding="utf-8") != t.text:
        from agent.storybook import snapshot
        snapshot(f"before your edit to {name}")
    f.write_text(t.text, encoding="utf-8")
    return {"ok": True, "words": len(t.text.split())}


# ---- simple board: Waiting for review / Not started / Applied ------------------
import threading as _th
PREP: dict = {}


MIN_MATCH = 50  # your rule: never apply below a 50% match


def _match(j):
    if j.get("jev_p") is not None:
        return round(j["jev_p"] * 100), "Jev"
    if j.get("score") is not None:
        return round(j["score"]), "model"
    return (round(j["kw_score"] * 100) if j.get("kw_score") is not None else None), "keyword"


_MONEY = re.compile(r"(?:US)?\$\s?\d[\d,.]*\s?[kK]?(?:\s?(?:-|–|—|to)\s?(?:US)?\$?\s?\d[\d,.]*\s?[kK]?)?(?:\s?(?:/|per\s)(?:hour|hr|year|yr))?")
_DATEISH = re.compile(r"\b(19|20)\d\d\b|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|\b(spring|summer|fall|autumn|winter|immediately|asap|q[1-4])\b|\d{1,2}/\d{1,2}", re.I)
_START = re.compile(r"(?:start(?:ing)?\s+date|start(?:s|ing)?\s+(?:in|on|by)|available\s+to\s+start)[:\s]+([^.\n<]{3,40})", re.I)


def _facts(j):
    """Salary and start date as the posting states them; None when it doesn't say."""
    raw = json.loads(j.get("raw") or "{}") if (j.get("raw") or "").startswith("{") else {}
    comp = raw.get("compensation") or {}
    salary = comp.get("scrapeableCompensationSalarySummary") or comp.get("compensationTierSummary")
    import html as _h
    text = _h.unescape(re.sub(r"<[^>]+>", " ", _h.unescape(j.get("description") or "")))
    if not salary:
        hits = [m.group(0).strip() for m in _MONEY.finditer(text) if any(x in m.group(0) for x in "-–—to") or "/" in m.group(0)]
        salary = hits[0] if hits else None
    m = next((x for x in _START.finditer(text) if _DATEISH.search(x.group(1))), None)   # "starts in June 2027", not "starts by an LLM"
    return {"salary": salary, "start": m.group(1).strip() if m else None}


def _title(t):
    t = t or ""
    return t.split("|")[1].strip() if "|" in t else t


@app.get("/api/config")
def ui_config():
    import os
    return {"jev": bool(os.getenv("TYPESAFE_API_KEY"))}


def _submitting(app_id: int) -> bool:
    """A submit window for this application is open right now."""
    import subprocess
    out = subprocess.run(["pgrep", "-f", f"agent.run submit --app {app_id}$"], capture_output=True, text=True).stdout
    return bool(out.strip())


@app.get("/api/board")
def board(tab: str = "review"):
    out = []
    with db.tx() as con:
        if tab == "todo":
            busy = [k for k in list(PREP) if _prep_state(k) == "running"]
            rows_ = [con.execute("SELECT * FROM jobs WHERE id=?", (k,)).fetchone() for k in busy]
            rows_ += con.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY COALESCE(jev_p*100, score) DESC LIMIT 200").fetchall()
            rows_ += con.execute("SELECT * FROM jobs WHERE status='new' AND (jev_p IS NOT NULL OR kw_score >= 0.6) "
                                 "ORDER BY COALESCE(jev_p, -1) DESC, kw_score DESC LIMIT 60").fetchall()
            seen = set()
            for j in rows_:
                if j is None or j["id"] in seen:
                    continue
                seen.add(j["id"]); j = dict(j); m, src = _match(j)
                if m is not None and m < MIN_MATCH and _prep_state(j["id"]) != "running":
                    continue  # below 50: not worth applying, never listed
                out.append({**_facts(j), "apply_url": j.get("apply_url"), "job_id": j["id"], "company": j["company"], "title": _title(j["title"]), "url": j["url"], "match": m, "match_src": src, "location": j.get("location") or "",
                            "why": j.get("score_reason") or "", "preparing": _prep_state(j["id"])})
            out.sort(key=lambda c: (c["preparing"] != "running", -(c["match"] if c["match"] is not None else -1)))
            return out
        from agent.replies import init as _ri
        _ri(con)
        statuses = ("pending_approval",) if tab == "review" else ("approved", "sent", "failed")
        q = f"SELECT a.*, j.company, j.title jt, j.url, j.apply_url, j.location, j.remote, j.score, j.jev_p, j.kw_score, j.raw, j.description FROM applications a JOIN jobs j ON j.id=a.job_id WHERE a.status IN ({','.join('?'*len(statuses))}) ORDER BY a.id DESC"
        for a in con.execute(q, statuses).fetchall():
            a = dict(a); m, src = _match(a)
            aj = json.loads(a["answers_json"]) if a.get("answers_json") else {}
            fields = [{"q": x["question"], "a": x["answer"]} for x in aj.get("answers", []) if x.get("answer")]
            out.append({**_facts(a), "apply_url": a.get("apply_url"), "location": (a.get("location") or "") + (" · Remote" if a.get("remote") and not re.search("remote|hybrid", (a.get("location") or ""), re.I) else ""),
                        "app_id": a["id"], "job_id": a["job_id"], "company": a["company"], "title": _title(a["jt"]), "url": a["url"],
                        "kind": a["kind"], "status": a["status"], "match": m, "match_src": src, "fields": fields,
                        "stage": a.get("stage") or "applied", "stage_at": a.get("stage_at"),
                        "replies": [dict(x) for x in con.execute("SELECT kind, at, sender, subject, snippet, view_url FROM replies WHERE app_id=? ORDER BY at DESC", (a["id"],)).fetchall()] if tab == "applied" else [],
                        "needs": aj.get("needs_human") or [], "needs_options": aj.get("needs_options") or {}, "has_shot": "screenshot:" in (a.get("sent_log") or ""),
                        "email_to": a.get("email_to"), "email_subject": a.get("email_subject"), "email_body": a.get("email_body"),
                        "sent_at": a.get("sent_at") or a.get("approved_at"), "error": a.get("error") or "", "blanks": _blanks(a),
                        "submitting": _submitting(a["id"])})
    if tab == "review":
        out.sort(key=lambda c: -(c["match"] if c["match"] is not None else -1))
    if tab == "applied":   # what needs you first: offers, interviews, next steps; rejections last
        order = {"offer": 0, "interview": 1, "next_step": 2, "confirmation": 3, "applied": 4, "rejected": 5}
        out.sort(key=lambda c: (order.get(c.get("stage") or "applied", 4), -(len(c.get("sent_at") or "") and 1), c.get("sent_at") or ""), reverse=False)
    return out


@app.get("/api/jobs/{job_id}/description")
def job_description(job_id: int):
    """The full posting as readable text, for the dashboard's View window."""
    import html as _h
    with db.tx() as con:
        j = con.execute("SELECT company, title, location, url, description FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not j:
        raise HTTPException(404)
    t = _h.unescape(j["description"] or "")
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d)>", "\n", t); t = re.sub(r"(?i)<li[^>]*>", "• ", t)
    t = _h.unescape(re.sub(r"<[^>]+>", "", t)); t = re.sub(r"\n\s*\n\s*\n+", "\n\n", t).strip()
    return {"company": j["company"], "title": _title(j["title"]), "location": j["location"], "url": j["url"], "text": t}


@app.post("/api/jobs/{job_id}/prepare")
def prepare_job(job_id: int):
    """Runs `python -m agent.run compose <id>` in its own process (browser automation and model CLIs stay out of the web server)."""
    import subprocess, sys
    from agent.setup_answers import missing
    if missing():
        return {"ok": False, "msg": "Finish your standing answers first (Storybook → Standing answers)."}
    j = rows("SELECT * FROM jobs WHERE id=?", job_id)
    m = _match(dict(j[0]))[0] if j else None
    if m is not None and m < MIN_MATCH:
        return {"ok": False, "msg": f"Match {m}% is below {MIN_MATCH}%; jobs under that are not applied to."}
    proc = PREP.get(job_id)
    if isinstance(proc, subprocess.Popen) and proc.poll() is None:
        return {"ok": True}
    log = HERE.parent / "data" / f"prepare-{job_id}.log"
    PREP[job_id] = subprocess.Popen([sys.executable, "-m", "agent.run", "compose", str(job_id)], cwd=str(HERE.parent),
                                    stdout=open(log, "w"), stderr=subprocess.STDOUT)
    return {"ok": True}


class _Queued:
    """A job picked for a batch prepare that hasn't started yet: shows as preparing."""
    def poll(self):
        return None


class PrepareMany(BaseModel):
    job_ids: list[int]


@app.post("/api/jobs/prepare-many")
def prepare_many(body: PrepareMany):
    """Prepare several jobs one after another (never in parallel: two browsers on one profile crash)."""
    import subprocess, sys
    from agent.setup_answers import missing
    if missing():
        return {"ok": False, "msg": "Finish your standing answers first (Storybook → Standing answers)."}
    ids, skipped = [], []
    for jid in body.job_ids:
        j = rows("SELECT * FROM jobs WHERE id=?", jid)
        m = _match(dict(j[0]))[0] if j else None
        if not j or (m is not None and m < MIN_MATCH) or _prep_state(jid) == "running":
            skipped.append(jid); continue
        PREP[jid] = _Queued(); ids.append(jid)

    def run():
        for jid in ids:
            log = HERE.parent / "data" / f"prepare-{jid}.log"
            PREP[jid] = subprocess.Popen([sys.executable, "-m", "agent.run", "compose", str(jid)], cwd=str(HERE.parent),
                                         stdout=open(log, "w"), stderr=subprocess.STDOUT)
            PREP[jid].wait()
    _th.Thread(target=run, daemon=True).start()
    return {"ok": True, "started": len(ids), "skipped": len(skipped)}


def _prep_state(job_id):
    proc = PREP.get(job_id)
    if proc is None or not hasattr(proc, "poll"):
        return None
    rc = proc.poll()
    return "running" if rc is None else ("done" if rc == 0 else f"error: see data/prepare-{job_id}.log")


@app.post("/api/jobs/{job_id}/skip")
def skip_job(job_id: int):
    from agent.audit import log
    with db.tx() as con:
        con.execute("UPDATE jobs SET status='skipped', score_reason=COALESCE(score_reason,'')||' (skipped by you)' WHERE id=?", (job_id,))
        log(con, "review", "skipped", "", job_id=job_id)
    return {"ok": True}


class Answers(BaseModel):
    answers: list[dict]


@app.post("/api/applications/{app_id}/answers")
def save_answers(app_id: int, body: Answers):
    with db.tx() as con:
        a = dict(con.execute("SELECT answers_json FROM applications WHERE id=?", (app_id,)).fetchone())
        aj = json.loads(a["answers_json"] or "{}")
        new = {x["q"]: x["a"] for x in body.answers}
        for x in aj.get("answers", []):
            if x["question"] in new:
                x["answer"] = new.pop(x["question"]); x["provenance"] = "you"
        # questions the agent left for you: answering one moves it out of "needs you"
        for q, ans in new.items():
            if ans.strip() and q in (aj.get("needs_human") or []):
                aj.setdefault("answers", []).append({"question": q, "answer": ans, "provenance": "you"})
        answered = {x["question"] for x in aj.get("answers", []) if (x.get("answer") or "").strip()}
        from agent import answer_bank
        company = con.execute("SELECT j.company FROM applications a JOIN jobs j ON j.id=a.job_id WHERE a.id=?", (app_id,)).fetchone()[0]
        saved = [q for q in (aj.get("needs_human") or []) if q in answered and answer_bank.remember(q, {x["q"]: x["a"] for x in body.answers}.get(q, ""), company)]
        aj["needs_human"] = [q for q in (aj.get("needs_human") or []) if q not in answered]
        db.update_application(con, app_id, answers_json=json.dumps(aj, ensure_ascii=False))
        con.commit()
        elsewhere = answer_bank.fill_pending(con, skip_app=app_id) if saved else 0   # the same question on other applications
    return {"ok": True, "saved": len(saved), "elsewhere": elsewhere}


@app.get("/api/saved-answers")
def saved_answers():
    from agent import answer_bank
    return answer_bank.load()


@app.delete("/api/saved-answers/{i}")
def forget_answer(i: int):
    from agent import answer_bank
    answer_bank.forget(i)
    return {"ok": True}


@app.get("/resume-png/{app_id}")
def resume_png(app_id: int):
    r = rows("SELECT resume_pdf FROM applications WHERE id=?", app_id)
    png = Path(r[0]["resume_pdf"]).with_suffix(".png") if r and r[0]["resume_pdf"] else None
    if not png or not png.exists():
        raise HTTPException(404)
    return FileResponse(png, media_type="image/png", headers=FRESH)


# ---- storybook: versions and learning from a résumé you like -------------------
class Reference(BaseModel):
    name: str
    data_b64: str
    prompt: str


@app.post("/api/storybook/learn-from")
def learn_from(ref: Reference):
    import base64, re as _r
    from agent.storybook import start_learn_from
    from agent.intake import read_any
    folder = Path("inbox/reference"); folder.mkdir(parents=True, exist_ok=True)
    path = folder / _r.sub(r"[^A-Za-z0-9._-]+", "_", ref.name)[:80]
    path.write_bytes(base64.b64decode(ref.data_b64.split(",")[-1]))
    text = read_any(path)
    if not text.strip():
        return {"ok": False, "msg": "Couldn't read text from that file. Try a PDF, DOCX or text file."}
    return {"ok": start_learn_from(text, path.name, ref.prompt), "msg": "started"}


class Upload(BaseModel):
    name: str
    data_b64: str


class Tell(BaseModel):
    text: str = ""
    name: str = ""
    data_b64: str = ""
    files: list[Upload] = []


TELL = {}
STYLE_ASK = re.compile(r"\b(style|tone|formatting|how my résumé is written|write like|written like|like \w+ (does|do|did|writes|wrote))\b", re.I)


CHAT: dict = {}   # what the chat box is still working on: {"fill": thread, "add": True, "learn": True}


def _fill_standing(text: str) -> None:
    """Background: turn what was said or dropped into standing answers, then say what was filled and what is still blank."""
    from agent import setup_answers as sa, chat
    labels = {q[1]: q[2] for q in sa.QUESTIONS}
    try:
        changed = sa.fill_from(text)
        left = sa.missing()
        msg = (f"Filled {len(changed)} standing answer{'s' if len(changed) != 1 else ''}: {', '.join(labels[k] for k in changed)}." if changed
               else "Nothing in that answers a standing question.")
        msg += (f" Still blank: {', '.join(left)}. Tell me those, or fill them in below." if left else " All required ones are done.")
        chat.add("agent", msg)
    except Exception as e:
        chat.add("agent", f"I couldn't fill the standing answers: {str(e)[:160]}")
    CHAT.pop("fill", None)


@app.post("/api/agent/tell")
def tell(t: Tell):
    """The Storybook chat box. Everything said or dropped also fills the standing answers (in the background).
    With files: one file plus a style request rewrites the storybook in its style; anything else (old résumés, reference
    letters, papers, notes) is read and its facts added to the storybook. Without files: save the note and propose patches
    in a separate process; they come back as suggested changes to approve."""
    import base64, subprocess, sys, threading
    from agent import chat
    files = t.files or ([Upload(name=t.name or "reference.txt", data_b64=t.data_b64)] if t.data_b64 else [])
    if not t.text.strip() and not files:
        return {"ok": False, "msg": "Write something first."}
    chat.add("you", t.text.strip(), [u.name for u in files])
    if len(files) == 1 and STYLE_ASK.search(t.text):
        chat.add("agent", f"Rewriting your storybook in the style of {files[0].name}. Progress shows below.")
        CHAT["add"] = True
        return learn_from(Reference(name=files[0].name, data_b64=files[0].data_b64, prompt=t.text))
    texts = []
    if files:
        from agent import config
        from agent.intake import read_any
        folder = config.PROFILE_DIR / "uploads"; folder.mkdir(exist_ok=True)
        for u in files:
            path = folder / re.sub(r"[^A-Za-z0-9._-]+", "_", u.name)[:80]
            path.write_bytes(base64.b64decode(u.data_b64.split(",")[-1]))
            texts.append((u.name, read_any(path)))
        if not any(x.strip() for _, x in texts):
            chat.add("agent", "I couldn't read text from those files. Try PDF, DOCX, text or audio.")
            return {"ok": False, "msg": "Couldn't read text from those files. Try PDF, DOCX, text or audio."}
    said = "\n\n".join([t.text] + [f"--- {n} ---\n{x[:8000]}" for n, x in texts if x.strip()])
    if "fill" not in CHAT:
        CHAT["fill"] = threading.Thread(target=_fill_standing, args=(said,), daemon=True); CHAT["fill"].start()
    if files:
        from agent import setup_answers
        from agent.storybook import start_add_from
        sa = setup_answers.load()
        person = " ".join(x for x in (sa.get("legal_first"), sa.get("legal_last")) if x)
        if sa.get("preferred_name"):
            person += f" (goes by {sa['preferred_name']})"
        ok = start_add_from([x for x in texts if x[1].strip()], t.text, person)
        chat.add("agent", f"Reading {files[0].name if len(files) == 1 else f'{len(files)} files'}: adding what's in {'it' if len(files) == 1 else 'them'} to your storybook, and filling your standing answers.")
        CHAT["add"] = True
        return {"ok": ok, "msg": "started"}
    from agent.learn import add_feedback
    with db.tx() as con:
        add_feedback(con, t.text)
    proc = TELL.get("proc")
    if not (proc and proc.poll() is None):
        TELL["proc"] = subprocess.Popen([sys.executable, "-m", "agent.run", "learn"], cwd=str(HERE.parent),
                                        stdout=open(HERE.parent / "data" / "learn.log", "w"), stderr=subprocess.STDOUT)
    chat.add("agent", "Got it. Filling any standing answers that covers, and thinking about what else to change; suggestions show below.")
    CHAT["learn"] = True
    return {"ok": True, "msg": "thinking"}


@app.get("/api/chat")
def chat_history():
    """The chat box's history. Reports work that finished since (storybook additions, suggestions) as agent messages."""
    from agent import chat
    from agent.storybook import STATUS
    if CHAT.get("add") and STATUS.get("state") != "running":
        CHAT.pop("add")
        n = len(STATUS.get("changes") or [])
        chat.add("agent", f"Storybook updated: {n} change{'s' if n != 1 else ''}." if STATUS.get("state") == "done" else
                 f"Stopped adding to your storybook{': ' + str(STATUS.get('error'))[:160] if STATUS.get('error') else '.'}")
        if STATUS.get("state") == "done" and n:   # the next step is the person's: how many matching jobs to look for
            chat.add("agent", "Your storybook is ready. Want me to look for matching jobs now? Choose how many and start.", action="find_jobs")
    d = CHAT.get("find")
    if d is not None and hasattr(d, "poll") and d.poll() is not None:
        CHAT.pop("find"); before = CHAT.pop("find_after", 0)
        made = rows("SELECT a.id app_id, j.company, j.title FROM applications a JOIN jobs j ON j.id=a.job_id WHERE a.id > ? ORDER BY a.id", before)
        if made:   # not a message: a button per application that opens it for review
            chat.add("agent", "", action="review", apps=made)
        else:
            chat.add("agent", "Couldn't find a job above a 50% match this time; see data/find-jobs.log.")
    proc = TELL.get("proc")
    if CHAT.get("learn") and not (proc and proc.poll() is None):
        CHAT.pop("learn")
        n = len(rows("SELECT id FROM proposals WHERE status='pending'")) if rows("SELECT name FROM sqlite_master WHERE name='proposals'") else 0
        if n:
            chat.add("agent", f"{n} suggested change{'s' if n != 1 else ''} below: apply or dismiss each.")
    return {"messages": chat.load(), "working": any(k != "find_after" for k in CHAT)}


class FindJobs(BaseModel):
    n: int = 1


@app.post("/api/find-jobs")
def find_jobs(body: FindJobs):
    """The person starts the search from the chat: n matching jobs, each with a résumé and a filled form."""
    import subprocess, sys
    from agent import chat
    if "find" in CHAT:
        return {"ok": False, "msg": "Already looking."}
    n = max(1, min(5, body.n))
    CHAT["find_after"] = (rows("SELECT MAX(id) m FROM applications") or [{"m": 0}])[0]["m"] or 0
    CHAT["find"] = subprocess.Popen([sys.executable, "-m", "agent.run", "find-jobs", "--n", str(n)], cwd=str(HERE.parent),
                                    stdout=open(HERE.parent / "data" / "find-jobs.log", "w"), stderr=subprocess.STDOUT)
    chat.add("you", f"Find {n} matching job{'s' if n > 1 else ''}.")
    chat.add("agent", ("Looking for the job that fits best, then writing its résumé and filling its form. About a minute." if n == 1 else
                       f"Looking for the {n} jobs that fit best, then preparing them one by one, best first: résumé, then the form. "
                       f"About {n} minutes."))
    return {"ok": True}


@app.post("/api/chat/clear")
def chat_clear():
    from agent import chat
    chat.clear()
    return {"ok": True}


@app.get("/api/agent/tell-status")
def tell_status():
    proc = TELL.get("proc")
    return {"thinking": bool(proc and proc.poll() is None)}


@app.get("/api/storybook/learn-status")
def learn_status():
    from agent.storybook import STATUS
    return STATUS


@app.get("/api/storybook/versions")
def sb_versions():
    from agent.storybook import versions
    return versions()


@app.post("/api/storybook/back")
def sb_back():
    from agent.storybook import restore_previous
    from agent.audit import log
    r = restore_previous()
    with db.tx() as con:
        log(con, "storybook", "restored", r or "")
    return {"ok": r is not None, "restored": r}


app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

if __name__ == "__main__":
    import uvicorn
    import os
    uvicorn.run("dashboard.app:app", host=os.getenv("JHA_HOST", "127.0.0.1"), port=int(os.getenv("JHA_PORT", "8765")), reload=False)
