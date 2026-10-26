"""Lint generated text against docs/02-writing-style-guide.md section 3 (banned words, phrases, structural tells).

lint(text, kind) -> list[Issue]; kind in {"resume", "email", "answer"}.
Hard issues block a draft until repaired; soft issues are shown to the person.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

HARD_WORDS = r"""leverage leveraged leveraging utilize utilized utilizing spearhead spearheaded champion championed orchestrate orchestrated
fostered foster empower empowered empowering elevate elevated streamline streamlined harness harnessed unlock unlocked
delve delved embark embarked bolster bolstered garner garnered underscore underscores showcase showcased showcasing
cutting-edge innovative robust seamless seamlessly passionate results-driven detail-oriented self-motivated proactive holistic impactful
delightful world-class best-in-class state-of-the-art groundbreaking transformative meticulous comprehensive vibrant pivotal crucial synergistic
synergy synergies dynamic honed hone tapestry realm paradigm value-add go-getter rockstar ninja wizard thrilled humbled truly genuinely incredibly""".split()
# context-dependent: flag softly (literal uses are fine, e.g. "service ecosystem", "user journeys", "Strategic Design and Management")
SOFT_WORDS = "landscape journey solutions deliverables strategic dynamic deeply optimize optimized drove".split()
# house rule 16: professional register (résumés and formal answers)
CASUAL = [r"\bmade\b", r"\bdid\b", r"\bworked on\b", r"\bhelped( with| to)?\b", r"\bgot\b", r"\bstuff\b", r"\bthings\b", r"\ba lot\b",
          r"\bmy own\b", r"\bbasically\b", r"\bpretty\b", r"\breally\b", r"\bspoke at\b", r"\bshared how\b", r"\btalked about\b",
          r"\bgave a talk\b", r"\bshare how\b",
          r"\bnamed (the|a|an|and|it)\b", r"\bthe name\b", r"\bnaming\b", r"\b(a|the) (bd |sales )?list\b"]
SMALL_TALK = [r"\bi (really )?love (that|how|the way)\b", r"\bi'?d love to\b", r"\bi would love to\b", r"\bhonestly\b", r"\bfun fact\b",
              r"\bsuper\b", r"\bpretty much\b", r"\ba lot of\b", r"\bsort of\b", r"\blol\b", r"\bhaha\b", r"!",
r"\bcan'?t wait\b", r"\bdream (job|company|role)\b", r"\bnerd\b", r"\bobsessed\b"]
VAGUE = re.compile(r"\bsomething (you|we|that|to|which)\b[^.]{0,60}\b(not|rather than)\b[^.]{0,40}\bsomething\b|"
                   r"\b(not|rather than) something (that )?(just )?(happens|exists|is)\b|, not (just|merely|simply) (a|an|the)?\s*\w+")
ALLOW = [r"Strategic Design and Management", r"user journeys?", r"service ecosystem", r"ecosystem map"]
PHRASES = ["i am writing to express", "to whom it may concern", "the best candidate", "very unique", "outside-the-box", "hope this email finds you", "hope this finds you", "i came across your", "would be a great fit",
           "proven track record", "think outside the box", "hit the ground running", "wear many hats", "at the intersection of",
           "fast-paced world", "it's important to note", "in conclusion", "look forward to hearing from you", "please don't hesitate",
           "a testament to", "serves as", "stands as", "plays a vital role", "a wide range of", "a diverse array of", "with a focus on",
           "in order to", "not only", "it's not about", "i'm excited to", "i am excited to", "key role", "best practices", "thought leadership",
           "team player", "drove results"]


@dataclass
class Issue:
    level: str   # hard | soft
    what: str
    where: str = ""


def _strip_allowed(text: str) -> str:
    for a in ALLOW:
        text = re.sub(a, " ", text, flags=re.I)
    return text


def lint(text: str, kind: str = "resume") -> list[Issue]:
    issues: list[Issue] = []
    t = _strip_allowed(text)
    low = t.lower()
    for w in HARD_WORDS:
        for m in re.finditer(rf"(?<![\w-]){re.escape(w)}(?![\w-])", low):
            issues.append(Issue("hard", f"banned word '{w}'", t[max(0, m.start()-40):m.end()+40].replace("\n", " ")))
    for w in SOFT_WORDS:
        if re.search(rf"(?<![\w-]){w}(?![\w-])", low):
            issues.append(Issue("soft", f"check '{w}' is literal, not filler"))
    try:
        from .learn import learned_bans
        extra = learned_bans()
    except Exception:
        extra = []
    for ph in PHRASES + extra:
        if ph in low:
            issues.append(Issue("hard", f"banned phrase '{ph}'"))
    if re.search(r"\b(designer|engineer|strategist|researcher|director|technologist|builder|creative|maker|person|someone|thinker|generalist|storyteller|problem-solver)s? (who|that|which)\b", low):
        issues.append(Issue("hard", "self-description with a relative clause ('designer who ...'); use a plain title or a plain statement"))
    if kind in ("resume", "answer"):   # not "why_us": those answers are meant to sound like a person
        for pat in CASUAL:
            m = re.search(pat, low)
            if m:
                issues.append(Issue("hard", f"casual wording '{m.group(0)}' (house rule 16: professional register)", t[max(0, m.start()-40):m.end()+40].replace("\n", " ")))
    if re.search(r"\bnot (just|merely) [^.]{1,60}\bbut\b", low):
        issues.append(Issue("hard", "'not just X but Y' construction"))
    dashes = text.count("—")
    if dashes > (1 if kind == "email" else 0 if kind in ("answer", "why_us") else 2):
        issues.append(Issue("hard", f"{dashes} em dashes"))
    if kind == "why_us":   # cover letters and why-us answers: no colons, no small talk; personality comes from substance
        colons = len(re.findall(r":(?!//)", text))
        if colons:
            issues.append(Issue("hard", f"{colons} colon(s); write full sentences instead"))
        m = VAGUE.search(low)   # an empty contrast ("as something you design for, not something that just happens")
        if m:
            issues.append(Issue("hard", f"vague contrast '{m.group(0)[:60]}'; name the concrete thing in precise words"))
        for pat in SMALL_TALK:
            m = re.search(pat, low)
            if m:
                issues.append(Issue("hard", f"small talk '{m.group(0)}'; show personality through what you did and how you think",
                                    t[max(0, m.start()-40):m.end()+40].replace("\n", " ")))
    if re.search(r"[☀-➿\U0001F300-\U0001FAFF]", text):
        issues.append(Issue("hard", "emoji"))
    sents = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if len(s.split()) > 2]
    if kind in ("email", "email_writeup", "answer") and len(sents) >= 4:
        lens = [len(s.split()) for s in sents]
        if max(lens) < 2 * min(lens):
            issues.append(Issue("soft", "sentences all similar length; vary them"))
    if kind in ("email", "email_writeup"):
        n = len(re.sub(r"\]\(https?://[^)]+\)", "]", text).split())   # link URLs don't count as words
        cap = 300 if kind == "email_writeup" else 160   # the employer asked for write-ups (what you built, how, what you'd change)
        if n > cap:
            issues.append(Issue("hard", f"email is {n} words (limit {cap})"))
        if "'" not in text and "’" not in text:
            issues.append(Issue("soft", "no contraction; reads stiff"))
    if kind == "resume":
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        starts = [l.split()[0].lower() for l in lines if len(l.split()) > 4]
        for w in set(starts):
            if starts.count(w) >= 4 and w not in ("designed",):
                issues.append(Issue("soft", f"{starts.count(w)} bullets start with '{w}'"))
    return issues


def resume_text(content: dict) -> str:
    parts = [content.get("headline", ""), content.get("summary", "")]
    for e in content.get("experience", []):
        parts += [b["text"] if isinstance(b, dict) else b.text for b in e.get("bullets", [])]
    parts += [p.get("blurb", "") for p in content.get("projects", [])]
    return "\n".join(parts)


def report(issues: list[Issue]) -> str:
    return "\n".join(f"[{i.level}] {i.what}" + (f" … {i.where} …" if i.where else "") for i in issues)


def lint_resume(content: dict, max_same_verb: int = 2) -> list[Issue]:
    """Page-level checks: no opening verb more than twice on one résumé (brief: vary verbs, use the field's verbs)."""
    from collections import Counter
    lines = [b["text"] for e in content.get("experience", []) for b in e.get("bullets", [])] + [p.get("blurb", "") for p in content.get("projects", [])]
    verbs = Counter(l.split()[0].lower().strip(",") for l in lines if l.split())
    out = [Issue("hard", f"'{v.title()}' opens {n} lines on this page; vary the verb") for v, n in verbs.items() if n > max_same_verb]
    concrete = [l for l in lines if re.search(r"\d", l)]
    if lines and len(concrete) < len(lines) / 2:   # recruiters look for numbers or concrete scope in at least half the lines
        out.append(Issue("soft", f"only {len(concrete)} of {len(lines)} lines carry a number or concrete scope"))
    out += [Issue("hard", f"over two lines ({len(l)} characters, max {MAX_BULLET}): {l[:60]}…") for l in lines if len(l) > MAX_BULLET]
    return out


MAX_BULLET = 200   # characters: two lines on the page, at the smallest scale the renderer uses
