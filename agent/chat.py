"""The Storybook chat box's history: what the person said and what the agent did about it, one file per account.

<profile>/chat.json, newest last. Private like the rest of profile/.
"""
from __future__ import annotations
import json
from . import config, db


def _path():
    return config.PROFILE_DIR / "chat.json"


def load() -> list[dict]:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except Exception:
        return []


def add(role: str, text: str, files: list[str] | None = None) -> dict:
    """role: 'you' or 'agent'."""
    msgs = load()
    m = {"role": role, "text": text, "at": db.now(), **({"files": files} if files else {})}
    msgs.append(m)
    _path().write_text(json.dumps(msgs[-200:], ensure_ascii=False, indent=1), encoding="utf-8")
    return m


def clear() -> None:
    _path().write_text("[]", encoding="utf-8")
