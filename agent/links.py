"""Hard link rules. Not left to the model.

1. Every link in a résumé, form answer or email is shown as a word (Website, LinkedIn, GitHub, Instagram, a project name)
   with the URL embedded. Raw URLs are never printed.
2. Header links are built here from preferences.yaml, not by the model: the website as its bare address, LinkedIn, GitHub always;
   Instagram for creative roles (CREATIVE_FAMILIES or creative sectors).
"""
from __future__ import annotations
import re
from . import config

LABELS = {"website": "Website", "linkedin": "LinkedIn", "github": "GitHub", "instagram": "Instagram"}
ORDER = ["website", "linkedin", "github", "instagram"]
CREATIVE_FAMILIES = {"art_director", "motion", "brand_strategy"}
CREATIVE_SECTORS = {"design_agency", "creative"}


def header_links(role_family: str | None = None, sector: str | None = None) -> list[dict]:
    links = config.person()["links"] or (config.preferences().get("identity", {}) or {}).get("links", {}) or {}
    creative = (role_family in CREATIVE_FAMILIES) or (sector in CREATIVE_SECTORS)
    out = []
    for k in ORDER:
        if k == "instagram" and not creative:
            continue
        if links.get(k):   # the website shows as its address (siennachen.com): readable on paper and by applicant-tracking systems
            label = re.sub(r"^https?://(www\.)?", "", links[k]).rstrip("/") if k == "website" else LABELS[k]
            out.append({"label": label, "url": links[k]})
    return out


URL_CORE = r"(?:https?://)?(?:www\.)?(?:[a-z0-9-]+\.)+(?:com|dev|io|ai|org|net|app|co|design)(?:/[^\s)\]]*)?"
URL_RE = re.compile(r"\b(" + URL_CORE + r")", re.I)
NAMED_RE = re.compile(r"([A-Z][\w.+-]*(?: [A-Z][\w.+-]*){0,4}) \((" + URL_CORE + r")\)", re.I)


def label_for(url: str) -> str:
    u = url.lower()
    if "linkedin.com" in u: return "LinkedIn"
    if "instagram.com" in u: return "Instagram"
    if "github.com" in u:
        parts = [x for x in re.sub(r"^https?://", "", u).split("/") if x]
        return parts[2].replace("-", " ").title() if len(parts) >= 3 else "GitHub"
    prof = config.profile(); site = re.sub(r"^https?://(www\.)?", "", config.person()["links"].get("website", "")).rstrip("/")
    if site and re.sub(r"^https?://(www\.)?", "", u).rstrip("/") == site.lower(): return "Website"
    m = re.search(prof.get("case_study_pattern") or r"$^", u)
    if m: return m.group(1).replace("-", " ").title() + " case study"
    return "link"


def to_markdown_links(text: str) -> str:
    """Turn bare URLs in a text into [label](url). "Name (url)" becomes [Name](url). Existing markdown links are kept."""
    def full(u): return u if u.startswith("http") else "https://" + u
    # "CodeCut (github.com/...)" -> "[CodeCut](https://github.com/...)"
    text = NAMED_RE.sub(lambda m: f"[{m.group(1)}]({full(m.group(2))})", text)
    out, last = [], 0
    for m in URL_RE.finditer(text):
        if text[max(0, m.start() - 2):m.start()] == "](" or text[max(0, m.start() - 1):m.start()] in ("[",):
            continue
        out.append(text[last:m.start()]); out.append(f"[{label_for(full(m.group(1)))}]({full(m.group(1))})"); last = m.end()
    out.append(text[last:])
    return "".join(out)


def markdown_to_html(text: str) -> str:
    import html as _h
    esc = _h.escape(text)
    esc = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', esc)
    return "<br>".join(esc.splitlines())


def has_raw_url(text: str) -> bool:
    stripped = re.sub(r"\[[^\]]*\]\([^)]+\)", "", text)
    return bool(URL_RE.search(stripped))
