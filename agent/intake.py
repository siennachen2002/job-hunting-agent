"""Node 1 · Intake → Storybook.

Put anything about the person in inbox/: old résumés (PDF, DOCX), portfolio text, LinkedIn exports, voice-memo
transcripts, chat notes. This node reads them all and drafts storybook entries in the brief's style:
facts with sources, résumé lines tagged by lens, open questions. It writes profile/master/_intake-draft-<date>.md
for the person to review and merge. It never edits the storybook directly.
"""
from __future__ import annotations
import datetime
import re
import zipfile
from pathlib import Path
from pydantic import BaseModel, Field
from . import config
from .providers import structured

INBOX = config.ROOT / "inbox"


def read_any(path: Path) -> str:
    suf = path.suffix.lower()
    if suf == ".pdf":
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    if suf == ".docx":
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        return re.sub(r"<[^>]+>", " ", xml.replace("</w:p>", "\n"))
    if suf in (".m4a", ".mp3", ".wav", ".mp4", ".mov", ".webm"):
        return transcribe(path)
    if suf in (".md", ".txt", ".vtt", ".srt", ".json", ".csv", ".html"):
        return path.read_text(encoding="utf-8", errors="ignore")
    return ""


def transcribe(path: Path) -> str:
    """Voice notes: talk through a job, a project, what you want next. Uses local whisper if installed."""
    import hashlib
    cached = path.with_suffix(path.suffix + ".txt")
    by_content = config.DATA_DIR / "transcripts" / (hashlib.sha1(path.read_bytes()).hexdigest() + ".txt")   # the same recording, never twice
    for c in (cached, by_content):
        if c.exists():
            return c.read_text(encoding="utf-8")
    try:
        from faster_whisper import WhisperModel
        segs, _ = WhisperModel("small", compute_type="int8").transcribe(str(path))
        text = " ".join(s.text.strip() for s in segs)
    except ImportError:
        try:
            import whisper
            text = whisper.load_model("small").transcribe(str(path))["text"]
        except ImportError:
            print(f"  ! {path.name}: install faster-whisper (pip install faster-whisper) or drop a transcript next to it")
            return ""
    cached.write_text(text, encoding="utf-8")
    by_content.parent.mkdir(parents=True, exist_ok=True); by_content.write_text(text, encoding="utf-8")
    return text


class Line(BaseModel):
    text: str = Field(description="one résumé-ready line written to the brief")
    lenses: list[str] = Field(description="lens tags from 06-roles.md")
    source: str = Field(description="file name the fact came from")


class Entry(BaseModel):
    kind: str = Field(description="experience | project | education | skill | voice")
    name: str
    header: str = Field(description="e.g. 'Org · Title · Location · MM/YYYY - MM/YYYY'")
    context: str
    lines: list[Line]
    open_questions: list[str]


class Storybook(BaseModel):
    entries: list[Entry]
    conflicts: list[str] = Field(description="facts that disagree between sources, with both versions")
    voice_samples: list[str] = Field(description="passages the person clearly wrote themselves, verbatim")


def run() -> Path | None:
    files = [p for p in sorted(INBOX.glob("**/*")) if p.is_file() and not p.name.startswith(".")
             and not (p.suffix == ".txt" and p.with_suffix("").suffix in (".m4a", ".mp3", ".wav", ".mp4", ".mov", ".webm"))]
    if not files:
        return None
    corpus = "\n\n".join(f"<<<FILE {p.name}>>>\n{read_any(p)[:40000]}" for p in files)
    from .llm import _system
    from .prompts import INTAKE
    sb = structured(_system(INTAKE), corpus, Storybook, effort="high", max_tokens=32000, tier="draft")   # a draft you edit
    out = config.MASTER_DIR / f"_intake-draft-{datetime.date.today()}.md"
    md = ["# Intake draft (review, then move what you want into the storybook files)\n"]
    for e in sb.entries:
        md += [f"## [{e.kind}] {e.header}", e.context, "", "**Résumé lines**"]
        md += [f"- {l.text} [{', '.join(l.lenses)}]  <!-- {l.source} -->" for l in e.lines]
        md += ["", "**Open**: " + " · ".join(e.open_questions), "", "---", ""]
    md += ["## Conflicts", *[f"- {c}" for c in sb.conflicts], "", "## Voice samples", *[f"> {v}\n" for v in sb.voice_samples]]
    out.write_text("\n".join(md), encoding="utf-8")
    return out
