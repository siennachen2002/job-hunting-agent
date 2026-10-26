"""Render ResumeContent -> HTML -> one-page PDF. Shrinks type, then trims bullets, until it fits."""
from __future__ import annotations
import copy
import re
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape
from playwright.sync_api import sync_playwright
from pypdf import PdfReader
from ..config import RESUME_OUT

HERE = Path(__file__).parent
env = Environment(loader=FileSystemLoader(HERE), autoescape=select_autoescape(["html"]))


def _href(url: str) -> str:
    url = (url or "").strip()
    return url if url.startswith(("http://", "https://", "mailto:")) else "https://" + url


def _linkify(text: str, link_text: str, link: str) -> Markup:
    """Escape the bullet, then turn the first occurrence of link_text into an anchor."""
    safe = str(escape(text))
    if link and link_text and link_text in text:
        lt = str(escape(link_text))
        safe = safe.replace(lt, f'<a href="{escape(_href(link))}">{lt}</a>', 1)
    return Markup(safe)


env.filters["href"] = _href
env.globals["linkify"] = _linkify


def _html(content: dict, scale: float) -> str:
    return env.get_template("template.html").render(r=content, scale=f"{scale:.3f}")


def _pages(pdf_path: Path) -> int:
    return len(PdfReader(str(pdf_path)).pages)


def _trim(content: dict) -> bool:
    """Remove a bullet from the oldest entry that can spare one (or the last project). Returns False if nothing left to trim.
    Recent roles must carry the posting's core requirements on their own, so they keep their bullets longest:
    older entries go down to 2 bullets first, then to 1, before the two most recent lose any."""
    exps = content.get("experience", [])
    order = list(reversed(exps[2:])) + list(reversed(exps[:2]))
    cand = next((e for e in order if len(e.get("bullets", [])) > 2), None) or \
        next((e for e in order if len(e.get("bullets", [])) > 1), None)
    if cand:
        cand["bullets"].pop()
        return True
    if content.get("projects"):
        content["projects"].pop()
        return True
    return False


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")[:60]


def render_one_page(content: dict, basename: str, role_family: str | None = None, sector: str | None = None,
                    posting_title: str | None = None) -> tuple[Path, dict, float]:
    """Returns (pdf_path, content_actually_rendered, scale). Header links and headline come from code, never from the model."""
    from ..links import header_links
    from ..headline import headline, strip_role_fragment, fix_entry_titles
    content = copy.deepcopy(content)
    fix_entry_titles(content, role_family)
    content["summary"] = strip_role_fragment(content.get("summary", ""))
    content["header_links"] = header_links(role_family, sector)
    content["headline"] = headline(role_family, posting_title)
    from .. import config as _config
    content["awards"] = list(_config.profile().get("awards") or [])   # on every résumé, never trimmed
    content["projects"] = [p for p in content.get("projects", []) if not any(p.get("name", "") in a for a in content["awards"])]
    out = RESUME_OUT / f"{safe_name(basename)}.pdf"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            while True:
                for scale in (1.0, 0.96, 0.92, 0.88, 0.85):
                    page.set_content(_html(content, scale), wait_until="load")
                    page.pdf(path=str(out), format="Letter", print_background=True, prefer_css_page_size=True)
                    if _pages(out) == 1:
                        page.set_viewport_size({"width": 816, "height": 1056})
                        page.screenshot(path=str(out.with_suffix(".png")), clip={"x": 0, "y": 0, "width": 816, "height": 1056})
                        return out, content, scale
                if not _trim(content):
                    raise RuntimeError("could not fit résumé on one page even after trimming")
        finally:
            browser.close()


if __name__ == "__main__":  # smoke test with dummy content
    demo = {
        "name": "Ada Example", "headline": "Product designer who ships code", "email": "ada@example.com", "phone": "",
        "location": "Berlin", "links": ["ada.design", "github.com/ada"],
        "summary": "Six years designing and building tools for energy and logistics teams. Most recent work: a dispatch console used by 400 field technicians.",
        "experience": [{"org": "Gridwork", "role": "Senior Product Designer", "dates": "2022 - 2025", "location": "Berlin",
                        "bullets": [{"text": "Redesigned the dispatch console; median task time fell from 4.1 to 2.3 minutes across 400 technicians.", "provenance": "master"},
                                    {"text": "Built Editor X, an open-source tool where people and agents share one timeline.", "provenance": "master", "link_text": "Editor X", "link": "github.com/example/editor-x"}]}] * 3,
        "projects": [{"name": "Solar siting map", "blurb": "Weekend tool that overlays grid capacity on rooftop data; 2k users.", "link": "ada.design/solar"}],
        "education": [{"school": "TU Delft", "degree": "MSc Design for Interaction", "dates": "2017 - 2019"}],
        "skills": [{"label": "Design", "items": ["Figma", "prototyping", "research"]}, {"label": "Code", "items": ["TypeScript", "React", "Python"]}],
    }
    path, c, s = render_one_page(demo, "demo")
    links = [a["/A"]["/URI"] for pg in PdfReader(str(path)).pages for a in (pg.get("/Annots") or []) if a.get_object().get("/A")]
    print("wrote", path, "scale", s, "pages", _pages(path), "links", links)
