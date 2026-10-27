"""Fill an ATS application form in a real browser and stop before Submit.

fill(url, answers, resume_pdf, shot_path, submit=False, headed=False)
- answers: {label substring (lowercase ok): value}
- Never solves CAPTCHAs. If submit=True and a challenge appears, it waits for the person (headed mode) and reports it.
"""
from __future__ import annotations
import re
from pathlib import Path
from playwright.sync_api import sync_playwright
from .inspect_form import JS as FIELDS_JS
from .identity import identity_answer
from .standing import standing_answer


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _lookup(answers: dict, lab: str):
    """The answer whose question best fits this label: exact first, else the longest question contained in it,
    and only if it covers most of the label (so 'Country' never answers '...authorized to work in the country...')."""
    best = None
    for k, v in answers.items():
        nk = _norm(k)
        if nk and (nk == lab or (nk in lab and len(nk) >= 0.6 * len(lab)) or (lab in nk and len(lab) >= 0.6 * len(nk))):
            if best is None or len(nk) > best[0]:
                best = (len(nk), v)
    return best[1] if best else None


def best_option(val: str, options: list[str]) -> str | None:
    """Map a free-text answer onto a dropdown's options: exact or contained text first, then dates to
    terms ("06/2027" -> "Spring 2027"), New York-area places to an NYC option, yes/no."""
    v = _norm(val); opts = [o for o in options if o.strip()]
    if re.match(r"\s*(ms|msc|ma|mfa|mba|master)", val, re.I):
        v = "master s degree" if not re.match(r"\s*mba", val, re.I) else v
    elif re.match(r"\s*(ba|bs|bsc|bfa|bachelor)", val, re.I):
        v = "bachelor s degree"
    for o in opts:
        if _norm(o) == v:
            return o
    neg = lambda t: bool(re.search(r"\b(not|no|don ?t|do not|decline)\b", t))
    for o in opts:   # contained text, but never flip a "not" ("I am not a veteran" is not "I am a veteran and …")
        if v and (v in _norm(o) or _norm(o) in v) and len(_norm(o)) > 2 and neg(v) == neg(_norm(o)):
            return o
    m = re.search(r"\b(\d{1,2})[/-](20\d\d)\b|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+(20\d\d)", val, re.I)
    if m:
        month = int(m.group(1)) if m.group(1) else ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"].index(m.group(3).lower()[:3]) + 1
        year = m.group(2) or m.group(4); term = "spring" if month <= 6 else "fall"
        hit = next((o for o in opts if term in o.lower() and year in o), None) or next((o for o in opts if year in o), None)
        if hit:
            return hit
    if re.fullmatch(r"\s*(united states( of america)?|usa|u\.s\.a?\.?|us)\s*", val, re.I):   # the country, however the form words it
        hit = next((o for o in opts if re.fullmatch(r"\s*(united states( of america)?|usa|u\.s\.a?\.?|us)( \(.*\))?\s*", o, re.I)), None)
        if hit:
            return hit
    if re.search(r"new york|\bnyc\b|brooklyn|queens|hoboken|\bnj\b|\bny\b", val, re.I):
        hit = next((o for o in opts if re.search(r"\bnyc\b|new york", o, re.I)), None)
        if hit:
            return hit
    if v in ("yes", "no"):
        return (next((o for o in opts if _norm(o).startswith(v)), None) or
                (next((o for o in opts if re.match(r"\s*i (acknowledge|agree|consent|confirm)", o, re.I)), None) if v == "yes" else None) or
                (opts[0] if v == "yes" and len(opts) == 1 else None))
    if re.search(r"company (website|site)|careers? (site|page)", val, re.I):
        hit = next((o for o in opts if re.search(r"careers? (site|page)|company (website|site)|website", o, re.I)), None)
        if hit:
            return hit
    if "veteran" in v and neg(v):   # "not a protected veteran": the plain "not a veteran" option, never "I am a veteran and …"
        hit = next((o for o in opts if re.search(r"\bnot a (protected )?veteran\b|^\s*no\b", o, re.I)), None)
        if hit:
            return hit
    words = {w for w in v.split() if len(w) > 3}
    scored = sorted(((len(words & {w for w in _norm(o).split() if len(w) > 3}), o) for o in opts
                     if neg(v) == bool(re.search(r"\b(not|no|don ?t|do not|decline)\b", _norm(o)))), reverse=True)
    if scored and scored[0][0] >= 2 or (scored and scored[0][0] == 1 and len(words) == 1):
        return scored[0][1]
    return None


def _search_terms(val: str) -> list[str]:
    parts = [re.sub(r"^\s*the\s+", "", x, flags=re.I).strip() for x in re.split(r"[,;]", re.sub(r"\(.*?\)", "", val))]
    parts = [x for x in parts if len(x) > 3][:3]
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'&.-]+", parts[0] if parts else val) if len(w) > 3 and w.lower() not in ("school", "university", "college", "design")]
    return list(dict.fromkeys(parts + words[:2]))


def fill(url: str, answers: dict[str, str], resume_pdf: str | None, shot_path: str, submit: bool = False,
         headed: bool = False) -> dict:
    log = []
    from .. import config
    demo = config.is_demo()
    if demo:
        submit = False            # a demo account fills right up to Submit and stops there
    with sync_playwright() as p:
        from .browser import open_page   # the agent's own browser profile, with any sign-ins you made there
        pg, close = open_page(p, headless=not headed, viewport={"width": 1280, "height": 1600})
        pg.goto(url, wait_until="networkidle", timeout=60000); pg.wait_for_timeout(1500)
        if "not found" in pg.inner_text("body")[:300].lower():
            close(); return {"ok": False, "error": "posting closed", "log": log}
        fields = pg.evaluate(FIELDS_JS)
        for _ in range(30):   # the form can render seconds after the page: wait for it (up to ~15 s)
            if fields:
                break
            pg.wait_for_timeout(500); fields = pg.evaluate(FIELDS_JS)
        # files first: some ATSs (Ashby) parse an uploaded résumé and reset the form state, wiping earlier typing
        fields.sort(key=lambda f: 0 if f["type"] == "file" else 1)
        uploaded = False
        typed = []   # (selector, value, label) of plain text fills, re-checked before Submit
        ticked = []  # (selector, label) of choices ticked, re-clicked if the form says they are missing
        radios = {}  # radio group → {label, required, ticked}: a required group with nothing chosen is unfilled
        for f in fields:
            if uploaded is True and f["type"] != "file":
                pg.wait_for_timeout(4000); uploaded = "done"
                try:   # the résumé parse can take longer: let it finish before typing
                    pg.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
            sel = f'[id="{f["id"]}"]' if f["id"] else (f"[name=\"{f['name']}\"]" if f["name"] else
                  (f'[data-field-path="{f["path"]}"] {f["tag"]}' if f.get("path") else None))
            if not sel or "recaptcha" in (f["label"] + f["name"]).lower():
                continue
            lab = _norm(f["label"])
            if f["type"] == "file" and demo and not url.startswith("file:"):
                log.append(f"demo account: no file uploaded to {url.split('/')[2]} → {f['label'][:40]}")   # many forms upload on selection
                continue
            if f["type"] == "file" and re.search(r"transcript", lab) and re.search(r"\bgraduate\b", lab) and not re.search(r"undergrad", lab):
                if f["required"]: log.append(f"UNFILLED required: {f['label']} (only an undergraduate transcript is on file)")
                continue
            if f["type"] == "file" and re.search(r"transcript", lab):
                from ..setup_answers import load as _sa
                tp = (_sa().get("transcript_file") or "").strip()
                if tp and Path(tp).exists():
                    pg.set_input_files(sel, tp); log.append(f"attached transcript → {f['label'][:40]}"); uploaded = uploaded or True
                elif f["required"]:
                    log.append(f"UNFILLED required: {f['label']} (add a transcript file in Standing answers)")
                continue
            if f["type"] == "file":
                key = lab + " " + _norm(f.get("id", "")) + " " + _norm(f.get("name", ""))
                if resume_pdf and re.search(r"\bresume\b|\bcv\b", key) and "cover" not in key:
                    pg.set_input_files(sel, resume_pdf); log.append(f"attached résumé → {f['label']}"); uploaded = uploaded or True
                continue
            if f["type"] == "checkbox" and pg.locator(sel).first.locator("xpath=..").locator("button[data-option]").count():
                # Ashby yes/no: two buttons next to a hidden checkbox
                ans = _lookup(answers, lab) or standing_answer(f["label"])
                if ans is not None:
                    choice = "yes" if str(ans).strip().lower() in ("yes", "on", "true", "y") else "no"
                    try:
                        pg.locator(sel).first.locator("xpath=..").locator(f'button[data-option="{choice}"]').click(timeout=5000)
                        log.append(f"chose {choice} → {f['label'][:50]}")
                    except Exception as e:
                        log.append(f"could not choose {f['label'][:40]}: {e.__class__.__name__}")
                elif f["required"]:
                    log.append(f"UNFILLED required: {f['label']}")
                continue
            if f["type"] in ("radio", "checkbox"):
                # one element per option: tick it when the group's answer names this option,
                # or when the option itself is a standing answer (a demographic choice or a "not a veteran" line)
                opt = (f.get("options") or [""])[0]
                group_opts = [x.get("options", [""])[0] for x in fields if x["type"] == f["type"] and (x.get("name") or x["label"]) == (f.get("name") or f["label"])]
                if f["type"] == "radio" or len(group_opts) > 1:   # a choice among options: a required one left empty is caught below
                    g = radios.setdefault(f.get("name") or f["label"], {"label": f["label"], "required": f["required"], "ticked": False})
                    g["required"] = g["required"] or f["required"]
                grp = _lookup(answers, lab) or standing_answer(f["label"])
                if f["type"] == "radio" and grp:   # a yes/no answer to a question whose options are places or choices
                    if not any(_norm(o) in ("yes", "no") for o in group_opts):
                        grp = standing_answer(f["label"], group_opts) or grp
                own = standing_answer(opt, as_option=True)
                if _norm(opt) in ("", "on", "true", "yes", "1"):   # a lone checkbox for the whole question: tick it when the answer is yes
                    tick = bool(grp) and _norm(grp).startswith("yes")
                else:
                    tick = (own == "Yes") if own in ("Yes", "No") else bool(grp and _norm(opt) and (_norm(opt) == _norm(grp) or _norm(opt) in _norm(grp)))
                    if not tick and grp and len(group_opts) > 1 and not any(_norm(o) in ("yes", "no") for o in group_opts):
                        tick = best_option(str(grp), group_opts) == opt   # "United States" ticks "US"
                if tick and (f.get("name") or f["label"]) in radios:
                    radios[f.get("name") or f["label"]]["ticked"] = True
                if tick:
                    try:
                        pg.check(sel, force=True, timeout=5000); log.append(f"ticked {opt[:60] or f['label'][:60]}")
                        ticked.append((sel, f["label"]))
                    except Exception:
                        try:   # custom checkboxes: click the label or the wrapper instead of the hidden input
                            target = pg.locator(f'label[for="{f["id"]}"]').first if f["id"] else None
                            if target is None or not target.count():
                                target = pg.locator(sel).first.locator("xpath=..")
                            target.click(timeout=5000)
                            ok = pg.locator(sel).first.is_checked()
                            log.append(f"ticked {opt[:60] or f['label'][:60]}" if ok else f"could not tick {f['label'][:40]}")
                        except Exception as e:
                            log.append(f"could not tick {f['label'][:40]}: {e.__class__.__name__}")
                continue
            val = identity_answer(f["label"])          # legal name first; preferred name only in its own field
            if val is None:
                val = standing_answer(f["label"], f.get("options"))
            if val is None:
                val = _lookup(answers, lab)
            if val is None:
                if f["required"]: log.append(f"UNFILLED required: {f['label']}")
                continue
            if f["tag"] in ("input", "textarea") and f["type"] not in ("radio", "checkbox"):
                if f["type"] == "search" or not pg.locator(sel).first.is_visible():
                    continue   # hidden helpers (country pickers, comboboxes) are not answers
                try:
                    loc = pg.locator(sel).first
                    if loc.get_attribute("role") == "combobox" or loc.get_attribute("aria-autocomplete"):
                        # custom dropdowns (Greenhouse react-select): type, then pick the matching option
                        loc.click(timeout=5000); loc.fill(val, timeout=5000); pg.wait_for_timeout(500)
                        opt = pg.get_by_role("option", name=re.compile(r"^\s*" + re.escape(val).replace("/", r"\/"), re.I)).first
                        if not opt.count() and "," in val:   # "Brooklyn, NY" vs "Brooklyn, New York, United States"
                            loc.fill(val.split(",")[0], timeout=5000); pg.wait_for_timeout(1200)
                            opt = pg.get_by_role("option", name=re.compile(re.escape(val.split(",")[0]).replace("/", r"\/"), re.I)).first
                        if not opt.count():   # fixed list: read every option and map the answer onto one
                            read = lambda: [o.inner_text().strip() for o in pg.get_by_role("option").all()]
                            loc.press("Meta+A"); loc.press("Backspace"); pg.wait_for_timeout(600)
                            names = read()
                            if not names:
                                loc.click(timeout=3000); pg.wait_for_timeout(600); names = read()
                            again = standing_answer(f["label"], names) if names else None   # the standing rules, with the form's real options
                            pick = again if again in names else best_option(val, names)
                            if not pick and names and again:
                                pick = best_option(again, names)
                            for term in ([] if pick else _search_terms(val)):   # long lists load as you type
                                loc.fill(term, timeout=3000)
                                for _ in range(12):   # search results arrive at network speed: wait until they do (up to ~5 s)
                                    pg.wait_for_timeout(400)
                                    if read():
                                        break
                                pick = best_option(val, read())
                                if pick:
                                    break
                            if pick:
                                pg.get_by_role("option", name=pick, exact=True).first.click(timeout=3000)
                                log.append(f"chose {pick[:30]} → {f['label'][:50]}")
                            else:
                                pg.keyboard.press("Escape")   # an optional field with no fitting option is left empty; only a required one blocks Submit
                                log.append(f"UNFILLED (no matching option for '{val[:30]}'): {f['label']}" if f["required"] else f"left empty, no fitting option for '{val[:30]}': {f['label']}")
                            continue
                        opt.click(timeout=3000)
                        log.append(f"chose {val[:30]} → {f['label'][:50]}")
                    else:
                        pg.fill(sel, val, timeout=5000); loc.press("Tab"); log.append(f"filled {f['label'][:60]}")
                        typed.append((sel, val, f["label"]))
                except Exception as e:
                    log.append(f"could not fill {f['label'][:40]}: {e.__class__.__name__}: {str(e).splitlines()[0][:160]}")
            elif f["tag"] == "select":
                pick = next((o for o in f.get("options") or [] if _norm(o) == _norm(val)), None) or next((o for o in f.get("options") or [] if _norm(val) and _norm(val) in _norm(o)), None)
                if pick:
                    try:
                        pg.select_option(sel, label=pick, timeout=5000); log.append(f"selected {pick[:40]} → {f['label'][:40]}")
                    except Exception as e:
                        log.append(f"could not select {f['label'][:40]}: {e.__class__.__name__}")
        for g in radios.values():   # a required choice left empty: never submitted that way, asked of the person instead
            if g["required"] and not g["ticked"]:
                log.append(f"UNFILLED required: {g['label']}")
        pg.wait_for_timeout(1500)
        try:   # the filled form itself, not the job description above it
            # the biggest form on the page (Ashby puts a small "autofill from resume" form above the real one)
            idx = pg.evaluate("""() => { const c = [...document.querySelectorAll('form, #application-form, [class*=application-form], [class*=ApplicationForm]')];
                let best = -1, area = 0; c.forEach((el, i) => { const r = el.getBoundingClientRect(); if (r.width * r.height > area) { area = r.width * r.height; best = i; } });
                return area > 200000 ? best : -1; }""")
            if idx < 0:
                raise ValueError("no form big enough")
            form = pg.locator("form, #application-form, [class*=application-form], [class*=ApplicationForm]").nth(idx)
            form.scroll_into_view_if_needed(timeout=3000); form.screenshot(path=shot_path, timeout=10000)
        except Exception:
            pg.screenshot(path=shot_path, full_page=True)
        result = {"ok": True, "log": log, "screenshot": shot_path, "submitted": False}
        if submit:
            def refill_cleared():
                for s_, v_, l_ in typed:
                    try:
                        if not pg.locator(s_).first.input_value(timeout=2000).strip():
                            pg.fill(s_, v_, timeout=5000); pg.locator(s_).first.press("Tab"); log.append(f"refilled {l_[:50]}")
                    except Exception:
                        pass
            def reenter(named):
                """Type a rejected text field again key by key, and click a rejected choice off and on, so the form's own state takes it."""
                hit = lambda l_: any(n and (n in _norm(l_) or _norm(l_) in n) for n in named)
                for s_, v_, l_ in typed:
                    if hit(l_):
                        try:
                            loc_ = pg.locator(s_).first; loc_.fill("", timeout=3000); loc_.press_sequentially(v_, delay=5, timeout=60000)
                            loc_.press("Tab"); log.append(f"re-entered {l_[:50]}")
                        except Exception:
                            pass
                for s_, l_ in ticked:
                    if hit(l_):
                        try:
                            el = pg.locator(s_).first; nm = el.get_attribute("name")
                            other = pg.locator(f'input[type=radio][name="{nm}"]:not({s_})').first if nm else None
                            if other is not None and other.count():
                                other.check(force=True, timeout=3000)
                            lab_ = pg.locator(f'label[for="{el.get_attribute("id")}"]').first
                            (lab_.click(timeout=3000) if lab_.count() else el.check(force=True, timeout=3000))
                            log.append(f"re-ticked {l_[:50]}")
                        except Exception:
                            pass
            refill_cleared()
            empty =[l.split(": ", 1)[1] for l in log if l.startswith(("UNFILLED required: ", "UNFILLED (no matching option"))]
            if empty:   # never press Submit on a form we know is incomplete: it only comes back rejected
                result["needs_person"] = "not submitted: required fields still empty"
                result["unfilled"] = empty
                return result
            try:
                btn = pg.get_by_role("button", name=re.compile(r"submit", re.I)).first
                btn.click(); result["clicked"] = True; pg.wait_for_timeout(5000)
                body = pg.inner_text("body").lower()
                for _ in range(2):   # the form lost a value it still shows (Ashby resets its state after parsing the résumé)
                    if not (re.search(r"missing entry for required field|needs corrections", body) and not any(w in body for w in ("thank", "successfully submitted"))):
                        break
                    refill_cleared()
                    named = [_norm(x) for x in re.findall(r"missing entry for required field:?\s*([^\n]+)", body)]
                    reenter(named)
                    btn.click(); pg.wait_for_timeout(5000)
                    body = pg.inner_text("body").lower()
                m = re.search(r"(missing entry for required field[^\n]*|needs corrections[^\n]*|this field is required[^\n]*)", body)
                if m and not any(w in body for w in ("thank", "received", "submitted")):
                    try:   # which fields the form rejected, by their question text
                        bad = pg.evaluate("""() => [...document.querySelectorAll('[aria-invalid="true"], .field-error, [class*=error] input, [class*=Error] input')]
                            .map(el => { const f = el.closest('.field, fieldset, [class*=field], [class*=Field], label') || el.parentElement;
                                         const l = f && (f.querySelector('label, legend') || f); return (l ? l.innerText : '').trim().split('\\n')[0].slice(0, 90); })
                            .filter(Boolean)""")
                    except Exception:
                        bad = []
                    bad = list(dict.fromkeys(bad))[:4]
                    result["needs_person"] = "form rejected" + (": fix " + "; ".join(bad) if bad else ": " + m.group(1)[:200])
                elif re.search(r"security code|verification code|enter the code", body) and not any(w in body for w in ("thank you for applying", "successfully submitted")):
                    # Greenhouse emails a one-time code for automated-looking submissions. It is a human check:
                    # the person types it into this window and clicks Submit; we only wait and watch.
                    result["needs_person"] = "Greenhouse emailed you a security code: type it into the open window and click Submit"
                elif pg.evaluate("""() => [...document.querySelectorAll('iframe')].some(f => /bframe|hcaptcha|challenge/i.test(f.src + f.title)
                            && f.getBoundingClientRect().height > 100 && getComputedStyle(f.closest('div') || f).visibility !== 'hidden')"""):
                    result["needs_person"] = "CAPTCHA shown: finish it in the open window"
                done = lambda b: re.search(r"thank(s| you) for (applying|your application)|application (has been|was) (successfully )?(submitted|received)|"
                                           r"successfully submitted|we('ve| have) received your application|your application is in", b)
                if headed and not done(body):
                    # whatever is left (a code, a CAPTCHA, a field the form still rejects, or nothing visible): the window comes to
                    # the front, scrolled to the spot, with a banner saying what to do; then we wait for the confirmation
                    from .browser import call_person
                    need = result.get("needs_person") or ""
                    if "security code" in need:
                        call_person(pg, "type the security code from your email below, then click Submit.", 'input[id*="security" i], input[name*="code" i]')
                    elif "CAPTCHA" in need:
                        call_person(pg, "finish the 'I'm not a robot' check on this page, then click Submit.", 'iframe[src*="recaptcha"], iframe[src*="hcaptcha"]')
                    elif need.startswith("form rejected"):
                        call_person(pg, "the form says something is missing (see the red box). Fix it, then click Submit.", '[class*=error i], [aria-invalid="true"]')
                    else:
                        call_person(pg, "this application isn't confirmed yet. Check the page, then click Submit.", 'button[type=submit], button:has-text("Submit")')
                    for _ in range(60):   # up to 10 minutes; closing the window ends it
                        pg.wait_for_timeout(10000)
                        body = pg.inner_text("body").lower()
                        if done(body):
                            result.pop("needs_person", None)
                            break
                # a real confirmation: one of these phrases AND the Submit button is gone (the form text itself says "submit")
                confirmed = re.search(r"thank(s| you) for (applying|your application)|application (has been|was) (successfully )?(submitted|received)|"
                                      r"successfully submitted|we('ve| have) received your application|your application is in", body)
                try:
                    still_form = pg.get_by_role("button", name=re.compile(r"^\s*submit", re.I)).first.is_visible(timeout=1000)
                except Exception:
                    still_form = False
                result["submitted"] = bool(confirmed) and not still_form
                pg.screenshot(path=shot_path.replace(".png", "-after.png"), full_page=True)
            except Exception as e:   # the window closed (you closed it, or the site moved on): after Submit it counts as sent
                if "closed" not in str(e).lower():
                    raise
                result["closed"] = True
                result["submitted"] = bool(result.get("clicked"))
                if result["submitted"]:
                    log.append("window closed after Submit was clicked: counted as sent; the confirmation email confirms it")
                try:
                    close()
                except Exception:
                    pass
                return result
        close()
    return result
