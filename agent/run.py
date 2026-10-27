"""CLI entry point.

  python -m agent.run discover            # pull new postings from every configured source
  python -m agent.run score [--limit N]   # score unscored postings
  python -m agent.run tailor JOB_ID       # build résumé + draft for one job -> application row
  python -m agent.run probe SLUG          # find a company's ATS board token
  python -m agent.run status              # counts
  python -m agent.run daily               # discover + score + tailor top matches (what the scheduler runs)
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from . import config, db
from .sources import ats, hn_hiring


def discover(con) -> dict:
    from .audit import log
    counts = {}
    for entry in config.companies():
        try:
            jobs = ats.fetch_company(entry)
        except Exception as e:  # network hiccups should not kill the run
            print(f"  ! {entry.get('name')}: {e}", file=sys.stderr)
            continue
        new = sum(db.upsert_job(con, j)[1] for j in jobs)
        con.commit()   # one company at a time, so nothing else waits on the whole refresh
        counts[entry["name"]] = (len(jobs), new)
    try:
        kws = [k for fam in config.roles().get("families", []) for k in fam.get("keywords", [])]
        hn = hn_hiring.fetch(keywords=kws or None)
        counts["HN who is hiring"] = (len(hn), sum(db.upsert_job(con, j)[1] for j in hn))
    except Exception as e:
        print(f"  ! hn: {e}", file=sys.stderr)
    log(con, "discover", "run", json.dumps({k: v[1] for k, v in counts.items()}))
    return counts


def _patterns() -> tuple[list[str], list[str]]:
    fams = config.roles().get("families", [])
    titles = [t.lower() for f in fams for t in f.get("titles", [])]
    kws = [k.lower() for f in fams for k in f.get("keywords", [])]
    return titles, kws


def prefilter(con) -> tuple[int, int]:
    """Cheap keyword gate before any model call. A posting passes if its title contains a family title word,
    or its description mentions >= 2 family keywords. Also drops avoid_keywords / avoid_companies."""
    titles, kws = _patterns()
    prefs = config.preferences().get("targets", {})
    avoid_k = [a.lower() for a in prefs.get("avoid_keywords", [])]
    avoid_c = [a.lower() for a in prefs.get("avoid_companies", [])]
    title_words = {w for t in titles for w in t.replace("(", " ").replace(")", " ").replace(",", " ").split() if len(w) > 3 and w not in {"only", "focused"}}
    kept = dropped = 0
    for row in db.jobs_by_status(con, "new", 100000):
        t = (row["title"] or "").lower(); d = (row["description"] or "").lower(); c = (row["company"] or "").lower()
        bad = any(a in t or a in d for a in avoid_k) or any(a in c for a in avoid_c)
        hit_title = any(w in t for w in title_words)
        hit_kw = sum(1 for k in kws if k in d) >= 2
        if bad or not (hit_title or hit_kw):
            con.execute("UPDATE jobs SET status='skipped', score_reason='prefilter' WHERE id=?", (row["id"],)); dropped += 1
        else:
            kept += 1
            import re as _re
            exact = any(tt in t for tt in titles)
            kw = (0.6 if exact else 0.35 if hit_title else 0.0) + min(0.3, 0.03 * sum(1 for k in kws if k in d))
            if _re.search(r"\b(staff|principal|director|head of|vp|vice president|manager|lead)\b", t): kw -= 0.4
            elif _re.search(r"\bsenior|\bsr\.?\b", t): kw -= 0.2
            if not exact and _re.search(r"\b(software|backend|infrastructure|data|security|sales|account|recruit|finance|legal|mechanical|electrical|hardware|technician)\b", t): kw -= 0.5
            if _re.search(r"\b(intern|associate|junior|jr\.?)\b", t): kw += 0.1
            loc = (row["location"] or "").lower()
            us_or_remote = bool(row["remote"]) or _re.search(r"\b(united states|usa|us\b|new york|nyc|ny\b|new jersey|brooklyn|san francisco|sf\b|seattle|los angeles|boston|chicago|austin|remote|north america|americas)", loc)
            if loc and not us_or_remote: kw -= 0.35   # until eligibility in 01-bio.md says otherwise
            kw = max(0.0, min(1.0, kw))
            sector_w = config.preferences().get("targets", {}).get("sector_weights", {}).get(row["sector"] or "other", 0.5)
            con.execute("UPDATE jobs SET kw_score=? WHERE id=?", (round(kw * (0.5 + 0.5 * sector_w), 3), row["id"]))
    con.commit()
    return kept, dropped


def jev_pass(con, limit: int = 5000) -> tuple[int, int]:
    """First pass: Jev P(apply) for every unscored posting. Postings under jev_min are skipped without a Claude call."""
    from . import jev
    if not jev.available():
        print("  (no TYPESAFE_API_KEY: skipping the Jev pass, Claude scores everything)")
        return 0, 0
    jev_min = config.preferences().get("automation", {}).get("jev_min", 0.35)
    rows = [dict(r) for r in con.execute("SELECT * FROM jobs WHERE status='new' AND jev_p IS NULL LIMIT ?", (limit,)).fetchall()]
    ps = jev.score_batch(rows)
    dropped = 0
    for j, pr in zip(rows, ps):
        if pr is None:
            continue
        con.execute("UPDATE jobs SET jev_p=? WHERE id=?", (pr, j["id"]))
        if pr < jev_min:
            con.execute("UPDATE jobs SET status='skipped', score_reason=? WHERE id=?", (f"jev {pr:.2f} < {jev_min}", j["id"]))
            dropped += 1
    con.commit()
    return len(rows), dropped


def score(con, limit: int = 200) -> int:
    """Model scores for unscored postings. Without Jev, Claude Code (your login, never an API key) scores them, 8 per call."""
    from . import llm, jev
    prefs = config.preferences().get("automation", {})
    q_min = prefs.get("min_score_to_queue", 55)
    n = 0
    rows = [dict(r) for r in con.execute("SELECT * FROM jobs WHERE status='new' ORDER BY COALESCE(jev_p, kw_score, 0) DESC, discovered_at DESC LIMIT ?", (limit,)).fetchall()]
    cc = {}
    if not jev.available():
        for i in range(0, len(rows), 8):
            try:
                cc.update(llm.score_jobs_claude_code(rows[i:i + 8]))
            except Exception as e:   # a batch that came back malformed: those postings one by one, still Claude Code
                print(f"  claude code batch failed ({str(e)[:80]}); scoring its postings one by one")
                for r in rows[i:i + 8]:
                    try:
                        cc[r["id"]] = llm.score_job(r, tier="claude-code")
                    except Exception as e2:
                        print(f"  could not score {r['company']} - {r['title']}: {str(e2)[:80]}")
        rows = [r for r in rows if r["id"] in cc]
    for job in rows:
        s = cc.get(job["id"]) or llm.score_job(job)
        status = "queued" if (s.score >= q_min and s.action != "skip" and not s.hard_blockers) else "skipped"
        db.set_score(con, job["id"], s.score, s.one_line, s.model_dump(), status)
        from .audit import log
        log(con, "rank", status, f"{s.score} {s.role_family}: {s.one_line}", job_id=job["id"])
        con.execute("UPDATE jobs SET sector=COALESCE(sector, ?) WHERE id=?", (s.sector, job["id"]))
        con.commit()
        n += 1
        print(f"  {s.score:3d} {status:8s} {job['company']} - {job['title']}")
    return n


def self_update() -> dict:
    """Pull the newest version of the app (fast-forward only: local changes are never overwritten; personal data is not in git).
    Returns {"updated": commits pulled, "restart": True when Python code changed, "update_error": why it couldn't}."""
    import subprocess
    git = lambda *x: subprocess.run(["git", *x], cwd=config.ROOT, capture_output=True, text=True, timeout=90)
    try:
        if git("rev-parse", "--is-inside-work-tree").returncode != 0 or not git("remote").stdout.strip():
            return {"updated": 0}
        before = git("rev-parse", "HEAD").stdout.strip()
        r = git("pull", "--ff-only", "--quiet")
        if r.returncode != 0:
            print("update skipped:", (r.stderr or r.stdout).strip()[:300])
            return {"updated": 0, "update_error": "couldn't update: local changes or no network"}
        after = git("rev-parse", "HEAD").stdout.strip()
        if before == after:
            return {"updated": 0}
        n = int(git("rev-list", "--count", f"{before}..{after}").stdout.strip() or 0)
        changed = git("diff", "--name-only", before, after).stdout.split()
        print(f"updated: {n} commit(s)")
        return {"updated": n, "restart": any(f.endswith(".py") for f in changed)}
    except Exception as e:
        return {"updated": 0, "update_error": str(e)[:200]}


def revise(con, app_id: int, instruction: str) -> str:
    """Rewrite one application's résumé from the person's note and re-render it in place. Returns the PDF path."""
    from pathlib import Path
    from . import llm
    from .resume.render import render_one_page
    a = dict(con.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone())
    job = dict(con.execute("SELECT * FROM jobs WHERE id=?", (a["job_id"],)).fetchone())
    sc = llm.JobScore(**json.loads(job["score_json"])) if job.get("score_json") else None
    content = llm.revise_resume(job, json.loads(a["resume_json"] or "{}"), instruction)
    notes = llm.clean_resume(content)
    from .voicecheck import lint_resume
    notes += [f"[page] {i.what}" for i in lint_resume(content.model_dump())]
    pdf, rendered, scale = render_one_page(content.model_dump(), Path(a["resume_pdf"]).stem,
                                           role_family=sc.role_family if sc else None, sector=job.get("sector") or (sc.sector if sc else None),
                                           posting_title=job.get("title"))
    db.update_application(con, app_id, resume_pdf=str(pdf), resume_json=json.dumps(rendered, ensure_ascii=False),
                          diy_notes=(a.get("diy_notes") or "") + f"\n-- revised: {instruction}\n" + "\n".join(content.tailoring_notes + notes))
    from .audit import log
    log(con, "compose", "resume-revised", instruction[:200], job_id=a["job_id"], app_id=app_id)
    con.commit()
    return str(pdf)


def tailor(con, job_id: int) -> int:
    from . import llm
    from .resume.render import render_one_page
    row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise SystemExit(f"no job {job_id}")
    job = dict(row)
    sc = llm.JobScore(**json.loads(job["score_json"])) if job.get("score_json") else None
    content = llm.tailor_resume(job, sc)
    voice_notes = llm.clean_resume(content)
    from .voicecheck import lint_resume
    voice_notes += [f"[page] {i.what}" for i in lint_resume(content.model_dump())]
    pdf, rendered, scale = render_one_page(content.model_dump(), f"{config.file_stem()}_{job['company']}_{job_id}",
                                           role_family=sc.role_family if sc else None, sector=job.get("sector") or (sc.sector if sc else None),
                                           posting_title=job.get("title"))
    prefs = config.preferences().get("automation", {})
    kind = "ats_web" if job["source"] in ("greenhouse", "lever", "ashby") else "manual"
    needs_approval = kind not in prefs.get("auto_approve_kinds", []) or content.diy_ratio > prefs.get("diy_max", 0.15)
    app_id = db.create_application(
        con, job_id=job_id, kind=kind, status="pending_approval", needs_approval=int(needs_approval),
        resume_pdf=str(pdf), resume_json=json.dumps(rendered, ensure_ascii=False),
        diy_ratio=content.diy_ratio, diy_notes="\n".join(content.diy_notes + ["--"] + content.tailoring_notes + (["-- voice check"] + voice_notes if voice_notes else [])),
    )
    con.execute("UPDATE jobs SET status='applied_draft' WHERE id=?", (job_id,))
    from .audit import log
    log(con, "compose", "resume", f"lens {sc.role_family if sc else '?'}, diy {content.diy_ratio:.0%}", job_id=job_id, app_id=app_id)
    con.commit()
    print(f"  application {app_id}: {pdf} (scale {scale}, diy {content.diy_ratio:.0%}, approval {'needed' if needs_approval else 'auto'})")
    return app_id


def submit_approved(con, headed: bool = True, app_id: int | None = None) -> None:
    if config.is_demo():
        print("demo account: nothing is ever submitted"); return
    from .setup_answers import require
    require()
    """Submit every approved ats_web application: re-check the posting, refill, click Submit in a visible browser.
    CAPTCHAs are left to the person in that window."""
    from .apply.fill import fill
    from .apply.live import still_open
    q = "SELECT * FROM applications WHERE status='approved' AND kind='ats_web'" + (" AND id=?" if app_id else "")
    for a in con.execute(q, (app_id,) if app_id else ()).fetchall():
        a = dict(a); j = dict(con.execute("SELECT * FROM jobs WHERE id=?", (a["job_id"],)).fetchone())
        aj = json.loads(a["answers_json"] or "{}")
        if re.search(r"\[YOUR ANSWER", json.dumps(aj) + (a.get("email_body") or "") + (a.get("cover_text") or ""), re.I):
            print(f"  app {a['id']} {j['company']}: still has a [YOUR ANSWER] blank, skipped"); continue
        if aj.get("needs_human"):
            print(f"  app {a['id']} {j['company']}: still has unanswered questions, skipped"); continue
        if not still_open(j):
            db.update_application(con, a["id"], status="failed", error="posting closed"); con.commit(); continue
        config.SCREENS.mkdir(parents=True, exist_ok=True); shot = str(config.SCREENS / f"app{a['id']}-submit.png")
        ans = {x["question"]: x["answer"] for x in aj.get("answers", []) if x.get("answer")}
        try:
            r = fill(j["apply_url"], ans, a["resume_pdf"], shot, submit=True, headed=headed)
        except Exception as e:   # the window was closed or the browser crashed: say so, never leave it "approved"
            r = {"log": [f"{e.__class__.__name__}: {str(e)[:200]}"], "error": "the submit window closed before it finished; try again"}
        if r.get("unfilled"):   # incomplete form: back to review with those fields as questions, nothing pressed
            aj["needs_human"] = list(dict.fromkeys((aj.get("needs_human") or []) + r["unfilled"]))
            db.update_application(con, a["id"], status="pending_approval", answers_json=json.dumps(aj, ensure_ascii=False),
                                  error="not submitted: " + "; ".join(x[:60] for x in r["unfilled"][:3]))
            con.commit(); print(f"  app {a['id']} {j['company']}: back to review, {len(r['unfilled'])} required field(s) empty"); continue
        status = "sent" if r.get("submitted") else "failed"
        db.update_application(con, a["id"], status=status, sent_at=db.now() if status == "sent" else None,
                              sent_log=(a["sent_log"] or "") + "\n--- submit ---\n" + "\n".join(r.get("log", [])) + f"\nscreenshot: {shot}",
                              error=r.get("needs_person") or r.get("error"))
        if status == "sent":
            con.execute("UPDATE jobs SET status='applied' WHERE id=?", (j["id"],))
        con.commit()
        from .audit import log
        log(con, "apply", "submit-" + status, r.get("needs_person") or "", job_id=j["id"], app_id=a["id"])
        print(f"  app {a['id']} {j['company']}: {status} {r.get('needs_person') or ''}")


EMAIL_RE = __import__("re").compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


PRE: dict = {}   # job_id -> (questions, FormAnswers) drafted while the résumé was being written (compose_job)


def prepare(con, limit: int = 10, app_id: int | None = None) -> list[str]:
    """Bring drafted applications to 'ready for your approval':
    ATS posting -> read the live form, draft answers, fill it in a headless browser (never submits), screenshot.
    HN / email-only posting -> draft the email to the address the posting itself gives."""
    from .setup_answers import require
    require()
    from . import llm
    from .apply.inspect_form import inspect
    from .apply.fill import fill
    from .apply.live import still_open
    done = []
    rows = con.execute("SELECT a.* FROM applications a WHERE a.status IN ('draft','pending_approval') AND a.answers_json IS NULL "
                       "AND a.kind IN ('ats_web','manual')" + (" AND a.id=?" if app_id else "") + " ORDER BY a.id DESC LIMIT ?",
                       ((app_id, limit) if app_id else (limit,))).fetchall()
    for a in rows:
        a = dict(a); j = dict(con.execute("SELECT * FROM jobs WHERE id=?", (a["job_id"],)).fetchone())
        if not still_open(j):
            db.update_application(con, a["id"], status="withdrawn", error="posting closed"); con.execute("UPDATE jobs SET status='closed' WHERE id=?", (j["id"],)); con.commit(); continue
        if j["source"] in ("greenhouse", "lever", "ashby") and j.get("apply_url"):
            if j["id"] in PRE:
                qs, fa = PRE.pop(j["id"])
            else:
                fields = [f for f in inspect(j["apply_url"]) if "recaptcha" not in (f["label"] + f["name"]).lower() and f["label"]]
                qs = [{"label": f["label"], "required": f["required"], "type": f["type"], "options": f["options"]} for f in fields]
                fa = llm.answer_form(j, qs)
            fa.needs_human = [q for q in fa.needs_human if not __import__("re").search(r"\b(resume|cv)\b.*(upload|file)|^(resume|cv)\b", q, __import__("re").I)]
            for x in fa.answers:
                if x.answer and len(x.answer.split()) > 25:
                    x.answer, _ = llm.clean_text(x.answer, "why_us" if llm.WHY_US.search(x.question) else "answer")
            config.SCREENS.mkdir(parents=True, exist_ok=True); shot = str(config.SCREENS / f"app{a['id']}.png")
            _step(5, "Filling in the form")
            r = fill(j["apply_url"], {x.question: x.answer for x in fa.answers if x.answer}, a["resume_pdf"], shot)
            dump = fa.model_dump()
            for line in r.get("log", []):   # a required field the form couldn't fill is a question for the person, always
                m = re.match(r"UNFILLED (?:required|\(no matching option[^)]*\)): (.+)", line)
                if m and m.group(1).strip() not in dump["needs_human"]:
                    dump["needs_human"].append(m.group(1).strip())
            opts = {q["label"]: q["options"] for q in qs if q.get("options")}
            dump["needs_options"] = {n: opts[n] for n in fa.needs_human if n in opts}   # shown as a dropdown in "Questions for you"
            from .doctor import fill_version, _init as _doc_init
            _doc_init(con)
            db.update_application(con, a["id"], kind="ats_web", status="pending_approval", answers_json=json.dumps(dump, ensure_ascii=False), fill_version=fill_version(),
                                  sent_log="\n".join(r.get("log", [])) + f"\nscreenshot: {shot}", error=r.get("error"))
            done.append(f"{j['company']} · {j['title']}: form filled, {len(fa.needs_human)} question(s) for you")
        else:
            emails = [e for e in EMAIL_RE.findall(j.get("description") or "") if not e.lower().endswith((".png", ".jpg"))]
            if not emails:
                db.update_application(con, a["id"], kind="manual", status="pending_approval", answers_json="{}",
                                      error="no form or email found in the posting; apply by hand from the link"); con.commit(); continue
            d = llm.draft_email("application", j["company"], (j.get("description") or "") + "\n\nFollow any application instructions in the posting exactly.")
            asks = re.search(r"what you'?ve built|things you'?ve built|tell us (about|how)|how it works|what you'?d change|write[- ]?up", j.get("description") or "", re.I)
            body, vnotes = llm.clean_text(d.body, "email_writeup" if asks else "email")
            body = llm.check_changes(body, j)   # an invented "what I'd change" becomes a question for you
            from .links import to_markdown_links
            db.update_application(con, a["id"], kind="email", status="pending_approval", answers_json="{}", email_to=emails[0],
                                  email_subject=d.subject, email_body=to_markdown_links(body),
                                  diy_notes=(a["diy_notes"] or "") + "\n-- email\n" + "\n".join(d.diy_notes + vnotes))
            done.append(f"{j['company']} · {j['title']}: email drafted to {emails[0]}")
        con.commit()
    return done


def outbox(con) -> list[dict]:
    """Approved email / proposal rows, ready for the Claude session to send through the Gmail connector.
    Blocks anything with a placeholder or a raw URL left in the body."""
    from .links import to_markdown_links, markdown_to_html, has_raw_url
    out = []
    for a in con.execute("SELECT * FROM applications WHERE status='approved' AND kind IN ('email','proposal','social_mention')").fetchall():
        a = dict(a); body = to_markdown_links(a["email_body"] or "")
        problems = []
        if "[YOUR ANSWER" in body or "[fill" in body: problems.append("placeholder left in body")
        if has_raw_url(body): problems.append("raw URL in body")
        if not a["email_to"] or "@" not in a["email_to"]: problems.append("no verified recipient")
        if problems:
            db.update_application(con, a["id"], status="pending_approval", error="; ".join(problems)); con.commit(); continue
        plain = __import__("re").sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", body)
        out.append({"id": a["id"], "to": [a["email_to"]], "subject": a["email_subject"], "htmlBody": markdown_to_html(body),
                    "body": plain, "attachment": a["resume_pdf"]})
    return out


def mark_sent(con, app_id: int, message_id: str) -> None:
    db.update_application(con, app_id, status="sent", sent_at=db.now(), sent_log=f"gmail message {message_id}")
    from .audit import log
    log(con, "apply", "email-sent", message_id, app_id=app_id)
    con.execute("UPDATE jobs SET status='applied' WHERE id=(SELECT job_id FROM applications WHERE id=?)", (app_id,)); con.commit()


POOL = re.compile(r"join our (network|talent)|talent (community|pool|network)|general application|future opportunit|"
                  r"don'?t see|open application|expression of interest", re.I)


def find_jobs(con, n: int = 1, boards: int = 12) -> list[int]:
    """Started by the person from the Storybook chat once the storybook is ready: prepare the n best-fitting jobs.
    A demo account reads its demo boards first; your own account picks from postings already found and ranked."""
    if config.is_demo():
        return [a for a in [demo_one(con, boards)] + [demo_next(con) for _ in range(n - 1)] if a]
    made = []
    rows = con.execute("SELECT id, title, COALESCE(jev_p*100, score, kw_score*100) m FROM jobs WHERE status IN ('queued','new') "
                       "AND source IN ('greenhouse','lever','ashby') ORDER BY m DESC LIMIT ?", (n * 4,)).fetchall()
    for r in rows:
        if len(made) >= n:
            break
        if POOL.search(r["title"] or "") or (r["m"] is not None and r["m"] < 50):
            continue
        try:
            made.append(compose_job(con, r["id"]))
        except SystemExit:
            continue
    return made


def demo_next(con) -> int | None:
    """The next best posting already read and ranked in this demo account."""
    top = con.execute("SELECT id FROM jobs WHERE status='new' AND source IN ('greenhouse','lever','ashby') "
                      "ORDER BY COALESCE(jev_p, -1) DESC, kw_score DESC LIMIT 1").fetchone()
    return compose_job(con, top["id"]) if top else None


def demo_one(con, boards: int = 12) -> int | None:
    """The live demo: find ONE job that fits and prepare it. A handful of boards, read in parallel; Jev (or keywords)
    ranks; the best real posting (no talent pools) gets a résumé and a filled form."""
    import concurrent.futures as cf
    from . import setup_answers
    if config.is_demo() and setup_answers.missing():   # the fictional applicant's blanks come from the sample answers
        import yaml
        sample = yaml.safe_load((config.ROOT / "demo" / "standing.yaml").read_text(encoding="utf-8")) or {}
        cur = setup_answers.load()
        filled = {k: v for k, v in sample.items() if v and not str(cur.get(k) or "").strip()}
        setup_answers.save({**cur, **filled})
        print("sample answers for:", ", ".join(filled))
    import yaml
    demo_boards = config.ROOT / "demo" / "companies.yaml"
    src = (yaml.safe_load(demo_boards.read_text(encoding="utf-8")) or {}).get("companies", []) if config.is_demo() and demo_boards.exists() else config.companies()
    ents = [e for e in src if e.get("ats") in ("greenhouse", "lever", "ashby")][:boards]
    def get(e):
        try:
            return ats.fetch_company(e)
        except Exception:
            return []
    ex = cf.ThreadPoolExecutor(len(ents) or 1)
    futs = [ex.submit(get, e) for e in ents]
    try:
        for f in cf.as_completed(futs, timeout=8):   # a slow board is skipped, not waited for
            for j in f.result():
                db.upsert_job(con, j)
    except cf.TimeoutError:
        pass
    ex.shutdown(wait=False, cancel_futures=True)
    con.commit()
    prefilter(con)
    for r in con.execute("SELECT id, title FROM jobs WHERE status='new'").fetchall():
        if POOL.search(r["title"] or ""):
            con.execute("UPDATE jobs SET status='skipped', score_reason='talent pool, not a job' WHERE id=?", (r["id"],))
    con.commit()
    jev_pass(con, 400)
    top = con.execute("SELECT id FROM jobs WHERE status='new' AND source IN ('greenhouse','lever','ashby') "
                      "ORDER BY COALESCE(jev_p, -1) DESC, kw_score DESC LIMIT 1").fetchone()
    return compose_job(con, top["id"]) if top else None


def _step(n: int, label: str) -> None:
    """A progress line the dashboard reads from the prepare log: the red bar under the job's card."""
    print(f"STEP {n}/5 {label}", flush=True)


def compose_job(con, job_id: int) -> int:
    """Not started → Waiting for review: résumé from storybook lines (no model), then fill the form or draft the email."""
    from .setup_answers import require
    require()
    dup = db.applied_role(con, dict(con.execute("SELECT company, title FROM jobs WHERE id=?", (job_id,)).fetchone()))
    if dup:   # the same role in another city already has an application
        con.execute("UPDATE jobs SET status='skipped', score_reason=? WHERE id=?", (f"same role as application #{dup}", job_id)); con.commit()
        raise SystemExit(f"same role as application #{dup}: not preparing it twice")
    from .assemble import assemble
    from .resume.render import render_one_page
    from .audit import log
    job = dict(con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
    m = job["jev_p"] * 100 if job.get("jev_p") is not None else (job["score"] if job.get("score") is not None else
                                                                  (job["kw_score"] * 100 if job.get("kw_score") is not None else None))
    if m is not None and m < 50:
        raise SystemExit(f"match {m:.0f}% is below 50%: not applying (your rule)")
    sc = json.loads(job["score_json"]) if job.get("score_json") else {}
    lens = sc.get("role_family") or "product_design"
    _step(1, "Reading the posting and its form")
    content = assemble(lens, job.get("sector"), posting_text=(job.get("title") or "") + " " + (job.get("description") or ""), posting_title=job.get("title") or "")
    from . import llm
    import concurrent.futures as cf
    def draft_form():   # independent of the résumé: read the live form and draft its answers meanwhile
        from .apply.inspect_form import inspect
        if job["source"] not in ("greenhouse", "lever", "ashby") or not job.get("apply_url"):
            return None
        fields = [f for f in inspect(job["apply_url"]) if "recaptcha" not in (f["label"] + f["name"]).lower() and f["label"]]
        qs = [{"label": f["label"], "required": f["required"], "type": f["type"], "options": f["options"]} for f in fields]
        return qs, llm.answer_form(job, qs)
    pool = cf.ThreadPoolExecutor(1); form_future = pool.submit(draft_form)
    align_notes = []
    _step(2, "Tailoring the résumé")
    try:   # the storybook's lines, reworded in the posting's vocabulary and ordered by its requirements; facts unchanged
        content, align_notes = llm.align_resume(job, content)
        from .voicecheck import lint_resume
        align_notes += [f"[page] {i.what}" for i in lint_resume(content)]
    except Exception as e:
        align_notes = [f"alignment skipped: {str(e)[:120]}"]
        try:
            llm.shorten_long(content)   # two lines per bullet, even without the alignment
        except Exception:
            pass
    _step(3, "Writing the summary")
    try:
        content["summary"] = llm.write_summary(job, content)   # the story, for this posting; empty if it can't be kept true
    except Exception:
        pass
    pdf, rendered, scale = render_one_page(content, f"{config.file_stem()}_{job['company']}_{job_id}", role_family=lens,
                                           sector=job.get("sector"), posting_title=job.get("title"))
    app_id = db.create_application(con, job_id=job_id, kind="ats_web" if job["source"] in ("greenhouse", "lever", "ashby") else "manual",
                                   status="draft", needs_approval=1, resume_pdf=str(pdf), resume_json=json.dumps(rendered, ensure_ascii=False),
                                   diy_ratio=0.0, diy_notes=f"assembled from storybook lines; lens {lens}\n-- aligned to the posting\n" + "\n".join(align_notes))
    con.execute("UPDATE jobs SET status='applied_draft' WHERE id=?", (job_id,)); con.commit()
    log(con, "compose", "resume", f"lens {lens}", job_id=job_id, app_id=app_id)
    _step(4, "Answering the form's questions")
    try:
        pre = form_future.result()
        if pre:
            PRE[job_id] = pre
    except Exception:
        pass   # prepare reads the form itself
    pool.shutdown(wait=False)
    try:
        prepare(con, 1, app_id=app_id)
    except BaseException:   # a half-made application shows nowhere: take it back, so the job is in Not started again
        con.execute("DELETE FROM applications WHERE id=? AND status='draft'", (app_id,))
        con.execute("UPDATE jobs SET status=? WHERE id=?", (job.get("status") or "new", job_id)); con.commit()
        raise
    return app_id


def status(con):
    for t in ("jobs", "applications"):
        rows = con.execute(f"SELECT status, COUNT(*) c FROM {t} GROUP BY status").fetchall()
        print(t + ":", ", ".join(f"{r['status']}={r['c']}" for r in rows) or "empty")


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover")
    sub.add_parser("refresh")
    sub.add_parser("init")       # first run: a fresh profile/ and .env
    sub.add_parser("setup")      # the Setup checklist, in the terminal
    md = sub.add_parser("models"); md.add_argument("--test", action="store_true")   # which model runs what; --test calls them
    br = sub.add_parser("browser"); br.add_argument("url", nargs="?", default="")   # the agent's browser, for you to sign in
    sub.add_parser("mail-test")
    mc = sub.add_parser("mail-check"); mc.add_argument("--days", type=int, default=3)
    ms2 = sub.add_parser("mail-send"); ms2.add_argument("--app", type=int)
    sub.add_parser("prefilter")
    s = sub.add_parser("score"); s.add_argument("--limit", type=int, default=200)
    sub.add_parser("jev")
    t = sub.add_parser("tailor"); t.add_argument("job_id", type=int)
    p = sub.add_parser("probe"); p.add_argument("slug")
    sub.add_parser("status")
    sb = sub.add_parser("submit"); sb.add_argument("--app", type=int)
    sub.add_parser("outbox")
    sub.add_parser("intake")
    cj = sub.add_parser("compose"); cj.add_argument("job_id", type=int)
    sub.add_parser("demo-one")   # the live demo: one fitting job, résumé and filled form
    fj = sub.add_parser("find-jobs"); fj.add_argument("--n", type=int, default=1)   # started from the Storybook chat
    sub.add_parser("doctor")   # the self-check: every waiting application brought up to today's rules
    sub.add_parser("learn")
    rq = sub.add_parser("replies-query"); rq.add_argument("--days", type=int, default=3)
    ri = sub.add_parser("replies-ingest"); ri.add_argument("file")
    cv = sub.add_parser("cover"); cv.add_argument("job_id", type=int)
    pr = sub.add_parser("prepare"); pr.add_argument("--limit", type=int, default=10)
    ms = sub.add_parser("mark-sent"); ms.add_argument("app_id", type=int); ms.add_argument("message_id")
    d = sub.add_parser("daily"); d.add_argument("--max-tailor", type=int, default=10)
    a = ap.parse_args(argv)

    if a.cmd == "probe":
        print(ats.probe_company(a.slug) or "nothing found; try another slug (company domain name, no spaces)")
        return
    with db.tx() as con:
        if a.cmd == "discover":
            for k, (tot, new) in discover(con).items():
                print(f"  {k}: {tot} postings, {new} new")
        elif a.cmd == "init":
            from .setup import init
            made = init()
            print("created: " + ", ".join(made) if made else "nothing to create: profile/ and .env already exist")
            print("next: start the dashboard (python -m dashboard.app, or the app) and follow the Setup page")
        elif a.cmd == "setup":
            from .setup import report
            print(report())
        elif a.cmd == "models":
            from .providers import describe, check
            d = describe()
            print(f"model        {d['model']['label'] or '(not set)'}  {d['model']['missing']}")
            print(f"draft model  {d['draft']['label'] or '(none: the model does everything)'}  {d['draft']['missing']}")
            if a.test:
                for tier in ("model", "draft"):
                    r = check(tier)
                    print(f"test {tier:5s}  " + (f"ok in {r['ms']} ms ({r['model']})" if r["ok"] else r.get("error", "failed")))
        elif a.cmd == "browser":
            from .apply.browser import open_for_signing_in
            print("opened the agent's browser (" + open_for_signing_in(a.url) + "): sign in, then close the window")
        elif a.cmd == "mail-test":
            from .mailbox import test
            print(test())
        elif a.cmd == "mail-check":   # read-only: match recent mail to submitted applications
            from .mailbox import fetch, configured
            from .replies import ingest
            if not configured():
                raise SystemExit("mailbox not configured: add JHA_MAIL_APP_PASSWORD to .env")
            counts = ingest(con, fetch(a.days))
            print(json.dumps(counts) if counts else "no new replies about your applications")
        elif a.cmd == "mail-send":   # approved emails only (outbox blocks placeholders, raw URLs, missing recipients)
            from .mailbox import send, configured
            if not configured():
                raise SystemExit("mailbox not configured: add JHA_MAIL_APP_PASSWORD to .env")
            for item in outbox(con):
                if a.app and item["id"] != a.app:
                    continue
                mid = send(item["to"], item["subject"], item["body"], item["htmlBody"], item["attachment"])
                mark_sent(con, item["id"], mid); print(f"sent {item['id']} to {', '.join(item['to'])}")
        elif a.cmd == "refresh":   # Refresh jobs & replies: the job boards and the inbox (the app's own update is a separate button)
            update = {}
            counts = discover(con); prefilter(con)
            new = sum(v[1] for v in counts.values())
            from . import jev
            if jev.available():
                jev_pass(con)
            else:   # no Jev: Claude Code ranks the new postings, never the API
                print(f"claude code scored {score(con, config.preferences().get('automation', {}).get('daily_score_limit', 60))}")
            replies = 0
            from .mailbox import configured
            if configured():
                try:
                    from .mailbox import fetch
                    from .replies import ingest
                    got = ingest(con, fetch(3)); replies = sum(got.values()) if got else 0
                    print("replies:", got or "none new")
                except Exception as e:
                    print("mail check failed:", e)
            try:   # the self-check: bugs fixed in code are fixed in every waiting application too
                from .doctor import run as doctor_run
                doc = doctor_run(con); print("self-check:", json.dumps(doc, ensure_ascii=False))
            except Exception as e:
                doc = {"fixed": [], "error": str(e)[:200]}; print("self-check failed:", e)
            config.REFRESHED.write_text(json.dumps({"at": db.now(), "new": new, "replies": replies, "fixed": len(doc.get("fixed", [])),
                                                    "blanks": len(doc.get("blanks", [])), **update}))
            print(f"{new} new postings")
        elif a.cmd == "prefilter":
            k, d = prefilter(con); print(f"kept {k}, dropped {d}")
        elif a.cmd == "score":
            prefilter(con)
            seen, dropped = jev_pass(con)
            print(f"jev: {seen} rated, {dropped} skipped")
            print(f"scored {score(con, a.limit)}")
        elif a.cmd == "jev":
            prefilter(con)
            seen, dropped = jev_pass(con)
            print(f"jev: {seen} rated, {dropped} skipped")
        elif a.cmd == "tailor":
            tailor(con, a.job_id)
        elif a.cmd == "status":
            status(con)
        elif a.cmd == "submit":
            submit_approved(con, app_id=a.app)
        elif a.cmd == "prepare":
            print("\n".join(prepare(con, a.limit)) or "nothing to prepare")
        elif a.cmd == "doctor":
            from .doctor import run as doctor_run
            rep = doctor_run(con)
            print(json.dumps(rep, ensure_ascii=False, indent=1))
        elif a.cmd == "find-jobs":
            print("applications", find_jobs(con, max(1, min(5, a.n))))
        elif a.cmd == "demo-one":
            print("application", demo_one(con))
        elif a.cmd == "compose":
            print("application", compose_job(con, a.job_id))
        elif a.cmd == "replies-query":
            from .replies import gmail_query, tracked
            print(json.dumps({"query": gmail_query(con, a.days), "tracked": [{k: t[k] for k in ("id", "company", "title", "sent_at", "stage")} for t in tracked(con)]}, ensure_ascii=False, indent=1))
        elif a.cmd == "replies-ingest":
            from .replies import ingest
            counts = ingest(con, json.load(open(a.file, encoding="utf-8")))
            print(json.dumps(counts) if counts else "no new replies about your applications")
        elif a.cmd == "learn":
            from .learn import propose
            print(f"{propose(con)} patch(es) proposed; review them on the dashboard's Learn page")
        elif a.cmd == "intake":
            from .intake import run as intake_run
            out = intake_run(); print(out or "inbox/ is empty")
        elif a.cmd == "cover":
            from .cover import draft
            j = dict(con.execute("SELECT * FROM jobs WHERE id=?", (a.job_id,)).fetchone()); d = draft(j)
            print(d.model_dump_json(indent=1))
        elif a.cmd == "outbox":
            print(json.dumps(outbox(con), ensure_ascii=False, indent=1))
        elif a.cmd == "mark-sent":
            mark_sent(con, a.app_id, a.message_id)
        elif a.cmd == "daily":
            run_id = con.execute("INSERT INTO runs(started_at) VALUES(?)", (db.now(),)).lastrowid
            found = discover(con); con.commit()
            kept, dropped = prefilter(con)
            jev_seen, jev_dropped = jev_pass(con)
            n = score(con, config.preferences().get("automation", {}).get("daily_score_limit", 60))
            prefs = config.preferences().get("automation", {})
            top = con.execute("SELECT id FROM jobs WHERE status='queued' AND score>=? ORDER BY score DESC LIMIT ?",
                              (prefs.get("min_score_to_apply", 70), a.max_tailor)).fetchall()
            made = [tailor(con, r["id"]) for r in top]
            prepared = prepare(con, len(made) + 5)
            try:
                from .doctor import run as doctor_run
                doctor_run(con)
            except Exception as e:
                print("self-check failed:", e)
            try:
                from .learn import propose
                learned = propose(con)
            except Exception as e:
                learned = f"learn failed: {e}"
            summary = {"discovered": found, "prefilter": {"kept": kept, "dropped": dropped}, "jev": {"rated": jev_seen, "skipped": jev_dropped}, "scored": n, "applications_drafted": made, "prepared": prepared, "learn_proposals": learned}
            con.execute("UPDATE runs SET finished_at=?, summary=? WHERE id=?", (db.now(), json.dumps(summary), run_id))
            print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
