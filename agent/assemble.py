"""Assemble a résumé from the playbook's tagged résumé lines, with no model call.

Lines in profile/master/02-experience.md and 03-projects.md end with [lens, lens]. For a lens we take the entries with
the most matching lines, keep the best 3-4 lines each, and order entries reverse-chronologically. Wording is the
playbook's own, so it already follows the brief.
"""
from __future__ import annotations
import re
from . import config

def _p():
    return config.profile()


LINE_RE = re.compile(r"^- (.+?) \[([a-z_, ]+)\]\s*$")


def _sections(path, keep: set | None = None) -> dict[str, list[tuple[str, set[str]]]]:
    out, cur = {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            name = line[3:].split(" · ")[0].strip()
            cur = name if "[fill" not in line or (keep and name in keep) else None
            out.setdefault(cur, []) if cur else None
            continue
        m = LINE_RE.match(line)
        if cur and m:
            out[cur].append((m.group(1).strip(), {t.strip() for t in m.group(2).split(",")}))
    return {k: v for k, v in out.items() if v}


YEAR_RE = re.compile(r"\b(?:(\d{1,2})/)?((?:19|20)\d\d)\b")


def _headings(path) -> dict[str, dict]:
    """'## Org · Title · Location · MM/YYYY - MM/YYYY' → that entry's role, location and dates. A new profile's
    profile.yaml lists no entries; its storybook headings (written by Tell it everything) are the record."""
    out = {}
    for line in (path.read_text(encoding="utf-8").splitlines() if path.exists() else []):
        if not line.startswith("## ") or "[fill" in line:
            continue
        parts = [x.strip() for x in line[3:].split(" · ")]
        dates = next((x for x in parts[1:] if YEAR_RE.search(x)), "")
        rest = [x for x in parts[1:] if x != dates]
        m = YEAR_RE.search(dates)
        out[parts[0]] = {"role": rest[0] if rest else "", "location": rest[1] if len(rest) > 1 else "", "dates": dates, "link": "",
                         "start": f"{m.group(2)}-{int(m.group(1) or 1):02d}" if m else "0000",
                         "pinned": bool(re.search(r"present|now|current", dates, re.I))}
    return out


def _linkify(text: str) -> tuple[str, str]:
    for name, url in (_p().get("project_links") or {}).items():
        if name in text:
            return name, url
    return "", ""


_STOP = set("the and for with that this from your you our are will have has into across about their they them what when where which while who how its it's not but all can more most one two own any each".split())


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z\-]{3,}", (text or "").lower()) if w not in _STOP}


def assemble(lens: str, sector: str | None = None, n_entries: int = 4, n_projects: int = 4, posting_text: str = "", posting_title: str = "") -> dict:
    prof = _p(); PROJECT_LINKS = prof.get("project_links", {})
    ENTRIES = {**_headings(config.MASTER_DIR / "02-experience.md"), **prof.get("entries", {})}
    PINNED = [n for n, m in ENTRIES.items() if m.get("pinned")]
    exp = _sections(config.MASTER_DIR / "02-experience.md", set(ENTRIES))
    proj = _sections(config.MASTER_DIR / "03-projects.md")
    want = {lens} | ({"climate"} if sector == "climate" else set())

    def rank(lines):
        return sum(2 if t & want else 0 for _, t in lines) + 0.1 * len(lines)

    names = [n for n in exp if n in ENTRIES]
    pinned = [n for n in PINNED if n in names]   # the most recent role always appears
    chosen = pinned + sorted([n for n in names if n not in pinned], key=lambda n: -rank(exp[n]))[:n_entries - len(pinned)]
    chosen.sort(key=lambda n: ENTRIES[n]["start"], reverse=True)
    from collections import Counter
    verbs: Counter = Counter()
    post_words = _words(posting_text)
    covered: set = set()   # posting words the two most recent roles already show

    def pick(cands, k, cover=False):
        """Lens-matching lines that speak to the posting first; skip a line whose opening verb is already used twice.
        cover=True (the two most recent roles) prefers lines that add posting words not yet on the page, so those
        roles show every core requirement on their own."""
        out, pool = [], list(cands)
        while pool and len(out) < k:
            def score(x):
                w = _words(x[0]) & post_words
                return (2 if x[1] & want else 0) + 0.35 * min(len(w - covered if cover else w), 8) - 0.5 * verbs[x[0].split()[0]]
            pool.sort(key=score, reverse=True)
            text, tags = pool.pop(0)
            if verbs[text.split()[0]] >= 2 and len(pool) >= k - len(out):
                continue
            out.append((text, tags)); verbs[text.split()[0]] += 1
            if cover:
                covered.update(_words(text) & post_words)
        return out

    experience = []
    for i, n in enumerate(chosen):
        lines = pick(exp[n], 4, cover=True) if i < 2 else pick(exp[n], 3)
        bullets = []
        for text, _ in lines:
            lt, url = _linkify(text)
            bullets.append({"text": text, "provenance": "master", "link_text": lt, "link": url})
        m = ENTRIES[n]
        experience.append({"org": n, "org_link": m["link"], "role": m["role"], "dates": m["dates"], "location": m["location"], "bullets": bullets})
    used = " ".join(b["text"] for e in experience for b in e["bullets"])
    # Projects: lens tags first, then what the posting itself talks about (so a climate-data SaaS role
    # doesn't get a game just because the game has one product-design line).
    also = set()
    if re.search(r"\b(AI|LLM|agents?|machine learning|ML)\b", posting_text):
        also.add("ai_product")
    if re.search(r"climate|sustainab|carbon|decarboni|ESG|energy", posting_text, re.I):
        also.add("climate")
    also -= want
    from .links import CREATIVE_FAMILIES, CREATIVE_SECTORS
    creative_only = set(prof.get("creative_only_projects") or [])
    creative_role = lens in CREATIVE_FAMILIES or sector in CREATIVE_SECTORS or bool(
        re.search(r"creative|game|art director|motion|technologist|illustrat|visual|brand|graphic|interactive|3d", posting_title or posting_text[:60], re.I))

    priority = set(prof.get("creative_priority_projects") or []) if creative_role else set()

    def relevance(lines):
        tags = sum(2 if t & want else (1 if t & also else 0) for _, t in lines)
        overlap = len(post_words & _words(" ".join(x for x, _ in lines)))
        return tags + 0.35 * min(overlap, 12)

    projects = []
    for name, lines in sorted(proj.items(), key=lambda kv: (kv[0] not in priority, -relevance(kv[1]))):
        if name.startswith("Talks") or name in used or not any(t & (want | also) for _, t in lines):
            continue
        if name in creative_only and not creative_role:
            continue  # game-design projects go only on creative résumés
        if any(name in a for a in prof.get("awards") or []):
            continue  # already on the page under Awards
        matching = [(t, tags) for t, tags in lines if tags & want] or [(t, tags) for t, tags in lines if tags & also]
        text = sorted(matching, key=lambda x: verbs[x[0].split()[0]])[0][0]
        verbs[text.split()[0]] += 1
        projects.append({"name": name, "blurb": text, "link": PROJECT_LINKS.get(name, ""), "provenance": "master"})
        if len(projects) >= n_projects:
            break
    who = config.person()
    return {"name": who["name"], "headline": "", "email": who["email"], "phone": who["phone"],
            "location": who["location"], "links": [], "summary": "",
            "experience": experience, "projects": projects, "education": who["education"],
            "skills": skills_for(lens, posting_text), "diy_ratio": 0.0, "diy_notes": [], "tailoring_notes": [f"assembled from playbook lines for lens {lens}"]}


GENERATIVE_RE = r"generative|creative coding|digital art|shader|particle|webgl artist|installation"


def skills_for(lens: str, posting_text: str = "") -> list[dict]:
    """Techniques (particle systems, SDF) appear only when the posting asks for generative / digital-art work."""
    import copy
    prof = _p(); groups_def = prof.get("skill_groups", {})
    keys = prof.get("skills_by_lens", {}).get(lens) or prof.get("skills_by_lens", {}).get("product_design", [])
    groups = [copy.deepcopy(groups_def[k]) for k in keys if k in groups_def]
    if re.search(GENERATIVE_RE, posting_text or "", re.I):
        for g in groups:
            if g["label"] == "Creative coding":
                g["items"] += prof.get("generative_extra", [])
    return groups
