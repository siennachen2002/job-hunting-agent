"""Standing answers for recurring form questions, decided in code (node 05 · Write and 07 · Apply).

Values come from the person's standing answers (agent/setup_answers.py, filled once in the dashboard) and,
for anything extra, from preferences.yaml eligibility.simple_answers (regex -> answer). Nothing is assumed:
an unanswered item stays a question for the person. "Prefer not to say" makes the agent pick the decline option.

Works on a question label, or on one option label when an ATS renders each checkbox as its own field ("Male", "White").
"""
from __future__ import annotations
import re
from .. import config
from .. import setup_answers

DECLINE = setup_answers.DECLINE
SKIP_NEED = re.compile(r"\boptional\b|opt-?in|text messages?|sms|marketing|newsletter|pronounce|pronoun|cover letter|"
                       r"\(file upload|upload handled|handled outside|additional file|^attach\b|legal name|if the form adds", re.I)
_DECL_OPT = r"decline|prefer not|don.?t wish|do not wish|choose not|not to (say|answer|disclose)"


def _sa() -> dict:
    """Standing answers, with older preference keys as a fallback for profiles set up before the form existed."""
    v = dict(setup_answers.load())
    old = (config.preferences().get("eligibility") or {}).get("self_id") or {}
    g = {"female": "Woman", "male": "Man"}.get(str(old.get("gender", "")).lower(), old.get("gender"))
    for k, val in (("gender", g), ("race", old.get("race")), ("race_detail", old.get("race_detail")),
                   ("hispanic_latino", old.get("hispanic_latino")), ("veteran", old.get("veteran")), ("relocate", old.get("relocate"))):
        if val and not v.get(k):
            v[k] = val
    return {k: (str(x).strip() if x is not None else "") for k, x in v.items()}


def _pick(options: list[str] | None, *wants: str) -> str | None:
    """First option whose text matches one of `wants` (in order), else None."""
    for w in wants:
        for o in options or []:
            if w and re.search(w, o, re.I):
                return o
    return None


def _is(value: str | None, text: str) -> bool:
    return bool(value) and re.sub(r"\W+", " ", value.lower()).strip() == re.sub(r"\W+", " ", text.lower()).strip()


def _norm_opt(o: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z -]", "", (o or "").lower())).strip()


def _declined(v: str) -> bool:
    return _is(v, DECLINE)


def _gender_words(g: str) -> tuple[str, ...]:
    return {"woman": ("female", "woman", "women"), "man": ("male", "man", "men"), "non-binary": ("non-binary", "nonbinary", "non binary")}.get(g.lower(), (g.lower(),))


SELF_ID = re.compile(r"veteran|disabilit|gender|\brace\b|ethnic|hispanic|latin[oax]|pronoun|sexual orientation|transgender", re.I)
LEGAL = re.compile(r"arbitrat|certify|attest|export control|export[- ]control|bound by|background check|criminal|perjury|true and (complete|correct)", re.I)


def _sponsor(l: str, s: dict) -> str | None:
    """Sponsorship, by what the question asks: 'now or in the future' together is Yes if either is; 'future' alone is the
    future answer; 'now' alone the present one (OPT counts as now)."""
    now, fut = s.get("sponsorship_now"), s.get("sponsorship_future")
    if not (now or fut):
        return None
    either = "Yes" if "Yes" in (now, fut) else "No"
    if re.search(r"\bopt\b|\bcpt\b|\bf-?1\b", l, re.I):
        return now or either
    has_now = re.search(r"\bnow\b|current(ly)?|\btoday\b|at this time|to start", l, re.I)
    has_fut = re.search(r"future|\bever\b|at any (point|time)|later", l, re.I)
    if has_fut and not has_now:
        return fut or either
    if has_now and not has_fut:
        return now or either
    return either


def simple_answer(label: str) -> str | None:
    """Plain questions answered from the standing answers, then preferences.yaml simple_answers."""
    s, l = _sa(), (label or "")
    if re.search(r"password", l, re.I) and not re.search(r"include (a |the |any )?password|password(s)? (if|when|where)", l, re.I):
        return None   # "Website Password" is not the website ("Website (include password if needed)" still is)
    if LEGAL.search(l) and not SELF_ID.search(l):
        return None   # arbitration, certifications, export control, background checks: always the person's own decision
    rules = [
        (r"undergrad(uate)? gpa|bachelor.*gpa", s.get("undergrad_gpa")),
        (r"countr(y|ies) (where )?you (anticipate|plan|expect|intend|will|would)( to)? (be )?work|which countr(y|ies) (will|would) you (be )?work",
         re.split(r"[;,/]", s.get("authorized_in") or "")[0].strip() or None),   # where the work happens: the home country
        (r"(graduate|master'?s?|ms) gpa", s.get("grad_gpa")),
        (r"exercise|work sample|portfolio( url| link)?|shared url|link to (your )?(work|portfolio)|personal website|^website", s.get("website")),
        (r"linkedin", s.get("linkedin")),
        (r"github", s.get("github")),
        (r"how did you (hear|find|learn)", s.get("how_heard") or "Company website"),
        (r"opt[- ]?in.*(whatsapp|sms|text message|marketing|newsletter)|(whatsapp|sms|text) (messages|updates)", "No"),   # marketing opt-ins: no
        (r"^\s*(current )?location( \(city\))?\s*\*?\s*$|where are you (currently )?(located|based)|city of residence", s.get("city")),
        (r"(currently )?(based|located|live) in the (nyc|new york( city)?) (metro|area|metropolitan)",
         None if not s.get("city") else ("Yes" if re.search(r"new york|\bny\b|brooklyn|queens|bronx|jersey city|hoboken|newark|\bnj\b", s["city"], re.I) else "No")),
        (r"(expected )?graduation date|when (do|will) you graduate|currently enrolled.*graduat", s.get("grad_date")),
        (r"earliest (you could|you can|date you could|start)|when (can|could) you start|available to start|start date", s.get("earliest_start")),
        (r"(come|commute) (in)?to the office|in[- ]office|in an office|from (the|an|our) office|on-?site|in[- ]person|days (a|per) week|hybrid",
         None if not s.get("onsite") else ("No" if s["onsite"].startswith("Remote") else "Yes")),
        (r"\b(stem )?opt\b|\bcpt\b|\bf-?1\b", _sponsor(l, s)),   # OPT counts as needing support now
        (r"require (visa )?sponsorship|need sponsorship|sponsorship for (an )?(immigration|employment)|visa sponsorship|sponsorship",
         _sponsor(l, s)),
        (r"^\s*i agree\b|^\s*i acknowledge\b|consent to the processing|\bi consent to\b|(review and )?acknowledge .*(agreement|policy|notice|terms)",
         "Yes" if re.match(r"\s*(tick|i agree|yes)", s.get("consent", ""), re.I) else None),
    ]
    for pat, val in rules:
        if val and re.search(pat, l, re.I):
            return val
    if re.search(r"legally authori[sz]ed to work|authori[sz]ed to work (lawfully )?in|eligible to work in", l, re.I) and s.get("authorized_in"):
        countries = [c.strip().lower() for c in re.split(r"[;,/]", s["authorized_in"]) if c.strip()]
        named = re.search(r"in (the )?(united states|u\.?s\.?a?|canada|united kingdom|uk|[A-Z][a-z]+)\b", l)
        if named and not re.search(r"country in which you are applying", l, re.I):
            n = named.group(2).lower().replace(".", "")
            n = "united states" if n in ("us", "usa", "u s a") else n
            return "Yes" if any(n in c or c in n for c in countries) else "No"
        return "Yes"
    table = (config.preferences().get("eligibility") or {}).get("simple_answers") or {}
    for pat, val in table.items():
        if re.search(pat, l, re.I):
            return str(val).replace("{website}", s.get("website") or (config.profile().get("links") or {}).get("website", ""))
    return None


def standing_answer(label: str, options: list[str] | None = None, as_option: bool = False) -> str | None:
    """as_option=True: `label` is one choice of a checkbox/radio group, so only the per-option demographic rules apply;
    question rules (relocation, sponsorship, simple answers) must never tick an option because it shares a word."""
    s, l = _sa(), (label or "").strip().lower()
    if not l:
        return None
    if not as_option:
        v = simple_answer(label)
        if v is not None:
            if not options:
                return v
            hit = _pick(options, "^" + re.escape(v))
            if not hit and v == "Yes":   # "I acknowledge…" / "I agree…" or the form's only choice
                hit = _pick(options, r"^i (acknowledge|agree|consent|confirm|certify)") or (options[0] if len(options) == 1 else None)
            if not hit and v in ("Yes", "No") and re.search(r"office|location|on-?site|commut|hybrid|in[- ]person", l, re.I):
                # "which office would you work from?": the option nearest home (Jersey City → New York), or none of them
                home = (s.get("city") or "").lower()
                metro = r"new york|nyc|\bny\b" if re.search(r"new york|nyc|brooklyn|queens|jersey city|hoboken|newark|\bnj\b|\bny\b", home) else re.escape(home.split(",")[0])
                hit = _pick(options, metro) if v == "Yes" else _pick(options, r"not be able|neither|none|remote")
            return hit or v
    o = re.sub(r"\s*\(.*?\)", "", l).strip()   # "White (Not Hispanic or Latino)" -> "white"
    demo = [s.get(k, "") for k in ("gender", "race", "hispanic_latino", "veteran", "disability")]
    # ---- one checkbox per option: Yes for the person's own value, No for the rest
    if re.search(_DECL_OPT, o):
        # a lone "Decline" box can't say which group it belongs to: tick it only if every answer given is a decline
        given = [x for x in demo if x]
        return None if not given else ("Yes" if as_option and all(_declined(x) for x in given) else "No")
    if s.get("gender") and re.fullmatch(r"(fe)?male|wom[ae]n|men|man|non-?binary|.*gender.*(identity|non|fluid).*", o) and len(o) < 40:
        return "No" if _declined(s["gender"]) else ("Yes" if o in _gender_words(s["gender"]) else "No")
    if s.get("race") and re.fullmatch(r"(east |south |southeast )?asian|white|black.*|native.*|american indian.*|hispanic or latino|two or more.*|middle eastern.*", o):
        if o == "hispanic or latino":
            return "Yes" if _is(s.get("hispanic_latino"), "yes") else "No"
        if _declined(s["race"]):
            return "No"
        return "Yes" if (s["race"].lower().startswith(o) or o.startswith(s["race"].lower()) or _is(s.get("race_detail"), o)) else "No"
    if s.get("veteran") and re.search(r"identify as one or more of the classifications of protected veteran|i am a (protected )?veteran", l):
        return "Yes" if _is(s["veteran"], "I am a protected veteran") else "No"
    if s.get("veteran") and re.search(r"i am not a (protected )?veteran", l):
        return "Yes" if re.search(r"\bnot\b", s["veteran"], re.I) else "No"
    if s.get("disability") and re.search(r"^(yes|no),? i (do not |don.?t )?have a disability|^i (do not |don.?t )?have a disability", o):
        mine = "no" if s["disability"].lower().startswith("no") else "yes" if s["disability"].lower().startswith("yes") else ""
        theirs = "no" if re.search(r"\b(no|not|don.?t)\b", o) else "yes"
        return "Yes" if mine and mine == theirs else "No"
    if as_option:
        return None
    # ---- whole questions
    if s.get("relocate") and re.search(r"address|where .*work from|city", l) and re.search(r"relocat", l):
        return "Relocating" if _is(s["relocate"], "yes") else None
    if s.get("relocate") and re.search(r"relocat|willing to (move|be based)", l):
        return _pick(options, "^" + re.escape(s["relocate"])) or s["relocate"]
    if s.get("disability") and re.search(r"disabilit|chronic condition", l):
        if _declined(s["disability"]):
            return _pick(options, _DECL_OPT) or "I don't wish to answer"
        no = s["disability"].lower().startswith("no")
        return _pick(options, r"^no\b|don.?t have|do not have" if no else r"^yes\b|i have") or ("No" if no else "Yes")
    if s.get("gender") and re.search(r"\bgender\b|\bsex\b", l):
        if options and not _declined(s["gender"]):
            hit = next((o for o in options if _norm_opt(o) in _gender_words(s["gender"])), None)
            if hit:
                return hit
        if _declined(s["gender"]):
            return _pick(options, _DECL_OPT) or "Decline to self-identify"
        w = _gender_words(s["gender"])
        return _pick(options, *[f"^{x}$" for x in w], *w) or {"woman": "Female", "man": "Male"}.get(s["gender"].lower(), s["gender"])
    if s.get("hispanic_latino") and (re.search(r"hispanic|latin[oax]", l) or
                                     (re.search(r"ethnicity", l) and any(re.search(r"hispanic|latin", o, re.I) for o in options or []))):
        if _declined(s["hispanic_latino"]):
            return _pick(options, _DECL_OPT) or "Decline to self-identify"
        return (_pick(options, r"^no\b", r"not hispanic") if _is(s["hispanic_latino"], "no") else _pick(options, r"^yes\b")) or s["hispanic_latino"]
    if s.get("race") and re.search(r"\brace\b|ethnic", l):
        if _declined(s["race"]):
            return _pick(options, _DECL_OPT) or "Decline to self-identify"
        detail = f' ({s["race_detail"]})' if s.get("race_detail") else ""
        return _pick(options, *(re.escape(x) for x in (s.get("race_detail"), s["race"]) if x)) or s["race"] + detail
    if s.get("veteran") and re.search(r"veteran", l):
        if _declined(s["veteran"]):
            return _pick(options, _DECL_OPT) or "I don't wish to answer"
        mine_not = bool(re.search(r"\bnot\b", s["veteran"], re.I))
        return _pick(options, re.escape(s["veteran"]), r"not a (protected )?veteran|^no\b" if mine_not else r"^yes|i identify as") or s["veteran"]
    if re.search(r"self-?identification|eeo", l) and not re.search(r"disab", l) and all(s.get(k) for k in ("gender", "race", "veteran")):
        return (f'Gender: {s["gender"]}; race: {s["race"]}' + (f' ({s["race_detail"]})' if s.get("race_detail") else "") +
                (f'; Hispanic or Latino: {s["hispanic_latino"]}' if s.get("hispanic_latino") else "") + f'; veteran: {s["veteran"]}')
    return None
