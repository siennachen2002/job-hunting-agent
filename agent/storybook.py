"""Storybook versions, "tell it everything" and "learn from a résumé you like".

- snapshot(reason): saves the storybook before any change (manual save, applied fix, style learning).
- restore_previous(): puts back the most recent snapshot ("Back to previous version"). Press again to go further back.
- add_from(files, note): reads whatever the person drops in (old résumés, reference letters, papers, notes) plus what
  they typed or said, and adds the facts about them as résumé lines. Material about someone else adds nothing; a
  single résumé of someone else is treated as a style reference instead.
- learn_from(file, prompt): reads a résumé you admire and rewrites your storybook's résumé lines in that style, using
  only your own facts. Runs line block by line block and reports progress, so the page can show it changing.
"""
from __future__ import annotations
import datetime, json, re, shutil, threading
from pathlib import Path
from pydantic import BaseModel, Field
from . import config

STATUS: dict = {"state": "idle"}


def _vdir() -> Path:
    d = config.PROFILE_DIR / ".versions"; d.mkdir(exist_ok=True); return d


def snapshot(reason: str) -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    d = _vdir() / ts; d.mkdir()
    for f in config.MASTER_DIR.glob("*.md"):
        shutil.copy2(f, d / f.name)
    (d / "_meta.json").write_text(json.dumps({"reason": reason, "at": ts}), encoding="utf-8")
    return ts


def versions() -> list[dict]:
    out = []
    for d in sorted(_vdir().iterdir(), reverse=True):
        if d.is_dir():
            m = json.loads((d / "_meta.json").read_text()) if (d / "_meta.json").exists() else {}
            out.append({"id": d.name, "reason": m.get("reason", ""), "at": d.name[:15]})
    return out


def restore_previous() -> str | None:
    vs = [d for d in sorted(_vdir().iterdir(), reverse=True) if d.is_dir()]
    if not vs:
        return None
    d = vs[0]
    for f in d.glob("*.md"):
        shutil.copy2(f, config.MASTER_DIR / f.name)
    reason = json.loads((d / "_meta.json").read_text()).get("reason", "") if (d / "_meta.json").exists() else ""
    shutil.rmtree(d)
    return reason


class Edit(BaseModel):
    before: str = Field(description="an existing résumé line, copied exactly (without its [tags])")
    after: str = Field(description="the same facts rewritten in the admired style; no new facts, numbers, tools or claims")
    why: str = Field(description="what was borrowed from the reference, in a few words")


class Edits(BaseModel):
    edits: list[Edit]


LINE_RE = re.compile(r"^- (.+?) (\[[a-z_, ]+\])\s*$")


def _sections(text: str) -> list[tuple[str, list[str]]]:
    out, cur = [], None
    for line in text.splitlines():
        if line.startswith("## "):
            cur = (line[3:].split(" · ")[0], []); out.append(cur)
        elif cur and LINE_RE.match(line):
            cur[1].append(LINE_RE.match(line).group(1))
    return [s for s in out if s[1]]


def learn_from(reference_text: str, reference_name: str, prompt: str) -> None:
    """Background job. Updates STATUS as it goes."""
    from .llm import _system
    from .providers import structured
    files = [config.MASTER_DIR / n for n in ("02-experience.md", "03-projects.md") if (config.MASTER_DIR / n).exists()]
    blocks = [(f, name, lines) for f in files for name, lines in _sections(f.read_text(encoding="utf-8"))]
    STATUS.clear(); STATUS.update(state="running", reference=reference_name, prompt=prompt, total=len(blocks), done=0, changes=[], current="")
    snapshot(f"before learning from {reference_name}")
    from .prompts import STORYBOOK_STYLE as task
    try:
        for f, name, lines in blocks:
            STATUS["current"] = name
            body = (f"## Instruction\n{prompt}\n\n## Reference résumé ({reference_name})\n{reference_text[:12000]}\n\n"
                    f"## Lines for '{name}'\n" + "\n".join(f"- {l}" for l in lines))
            res = structured(_system(task), body, Edits, effort="medium", max_tokens=4000)
            text = f.read_text(encoding="utf-8")
            for e in res.edits:
                if e.before in text and e.after and e.after != e.before:
                    text = text.replace(e.before, e.after, 1)
                    STATUS["changes"].append({"where": name, "before": e.before, "after": e.after, "why": e.why})
            f.write_text(text, encoding="utf-8")
            STATUS["done"] += 1
        STATUS["state"] = "done"
    except Exception as ex:  # keep what was done; the snapshot can undo it
        STATUS.update(state="error", error=str(ex)[:300])


class Addition(BaseModel):
    file: str = Field(description="02-experience.md for jobs, 03-projects.md for projects, papers, talks, teaching")
    entry: str = Field(description="heading of an existing entry copied exactly, or a new heading in the same format "
                                   "('Org · Title · Location · MM/YYYY - MM/YYYY' or 'Name · venue or link · year'), leaving "
                                   "out any part the material doesn't state")
    context: str = Field(description="one plain sentence for a new entry; '' when adding to an existing one")
    line: str = Field(description="one résumé-ready line stating only what the material says")
    lenses: list[str] = Field(description="lens tags from 06-roles.md")
    source: str = Field(description="file name the fact came from, or 'your note'")


class Additions(BaseModel):
    additions: list[Addition]
    about_someone_else: list[str] = Field(description="file names that describe a different person (e.g. a résumé they admire)")


def _lenses() -> set[str]:
    f = config.MASTER_DIR / "06-roles.md"
    return set(re.findall(r"\(`([a-z_]+)`\)", f.read_text(encoding="utf-8"))) if f.exists() else set()


def _add_line(path: Path, entry: str, context: str, line: str) -> bool:
    text = path.read_text(encoding="utf-8") if path.exists() else f"# {path.stem.split('-', 1)[-1].title()}\n"
    if line.split(" [")[0] in text:
        return False
    lines = text.splitlines()
    key = entry.split(" · ")[0].strip().lower()
    at = next((i for i, l in enumerate(lines) if l.startswith("## ") and l[3:].split(" · ")[0].strip().lower() == key), None)
    if at is None:
        text = text.rstrip() + f"\n\n## {entry}\n\n" + (f"**Context.** {context}\n\n" if context else "") + f"**Résumé lines**\n- {line}\n"
    else:
        end = next((i for i in range(at + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        last = max((i for i in range(at, end) if LINE_RE.match(lines[i])), default=None)
        if last is None:
            lines[end:end] = ["**Résumé lines**", f"- {line}", ""]
        else:
            lines.insert(last + 1, f"- {line}")
        text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8")
    return True


def _stated(entry: str, said: str) -> str:
    """A heading keeps only the years the material gives: 'Plugin · Figma · 2026' → 'Plugin · Figma' when no 2026 was said."""
    parts = entry.split(" · ")
    return " · ".join(p for i, p in enumerate(parts) if not i or all(y in said for y in re.findall(r"\b(?:19|20)\d\d\b", p)))


def add_from(files: list[tuple[str, str]], note: str, person: str = "") -> None:
    """Background job: add what the dropped files and the note say about the person. Updates STATUS as it goes."""
    from .llm import _system
    from .providers import structured
    names = [n for n, _ in files]
    STATUS.clear(); STATUS.update(state="running", mode="add", reference=" · ".join(names + (["your note"] if note.strip() else [])),
                                  prompt=note, total=len(files) + 1, done=0, changes=[], current="")
    snapshot(f"before adding from {', '.join(names) or 'your note'}")
    pending = config.PROFILE_DIR / ".adding.json"   # survives a restart: the dashboard picks the job up again on start
    pending.write_text(json.dumps({"files": files, "note": note, "person": person}, ensure_ascii=False), encoding="utf-8")
    from .prompts import STORYBOOK_ADD as task
    try:
        corpus = []
        for name, text in files:
            STATUS["current"] = f"Reading {name}"
            corpus.append(f"<<<FILE {name}>>>\n{text[:30000]}")
            STATUS["done"] += 1
        STATUS["current"] = "Writing your story"
        book = "\n\n".join(f"<<<{f.name}>>>\n{f.read_text(encoding='utf-8')}" for f in sorted(config.MASTER_DIR.glob("0[23]-*.md")))
        body = (f"## The person\n{person or '(name not given)'}\n\n## Their note\n{note or '(none)'}\n\n"
                f"## Their storybook now\n{book}\n\n## Material\n" + "\n\n".join(corpus))
        res = structured(_system(task), body, Additions, effort="medium", max_tokens=6000)
        ok = _lenses()
        for a in res.additions:
            f = config.MASTER_DIR / ("03-projects.md" if a.file.startswith("03") else "02-experience.md")
            tags = [t for t in a.lenses if t in ok or t == "climate"]
            entry = _stated(a.entry.strip(), note + " ".join(t for _, t in files))
            if a.line.strip() and _add_line(f, entry, a.context.strip(), a.line.strip() + (f" [{', '.join(tags)}]" if tags else "")):
                STATUS["changes"].append({"where": a.entry.split(" · ")[0], "before": "", "after": a.line.strip(), "why": f"from {a.source}"})
        STATUS["done"] += 1
        pending.unlink(missing_ok=True)
        others = [t for n, t in files if n in res.about_someone_else]
        if not STATUS["changes"] and len(others) == 1:   # one résumé they like and nothing about them: learn its style
            restore_previous()
            return learn_from(others[0], res.about_someone_else[0], note)
        STATUS["state"] = "done"
    except Exception as ex:  # .adding.json stays, so "Try again" can run the same files again
        STATUS.update(state="error", error=str(ex)[:300])


def resume_add() -> bool:
    """An addition cut off by a restart (Update app, account switch) starts again from the same files."""
    p = config.PROFILE_DIR / ".adding.json"
    if not p.exists() or STATUS.get("state") == "running":
        return False
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        p.unlink(missing_ok=True); return False
    restore_previous()   # back to the storybook as it was before the cut-off run, so nothing is added twice
    return start_add_from([tuple(x) for x in d["files"]], d.get("note", ""), d.get("person", ""))


def start_add_from(files: list[tuple[str, str]], note: str, person: str = "") -> bool:
    if STATUS.get("state") == "running":
        return False
    threading.Thread(target=add_from, args=(files, note, person), daemon=True).start()
    return True


def start_learn_from(reference_text: str, reference_name: str, prompt: str) -> bool:
    if STATUS.get("state") == "running":
        return False
    threading.Thread(target=learn_from, args=(reference_text, reference_name, prompt), daemon=True).start()
    return True
