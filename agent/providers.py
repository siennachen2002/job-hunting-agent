"""Models. Every step that needs a model makes one call:

    structured(system_blocks, user_text, Schema, tier="model" | "draft", effort="medium", max_tokens=8000) -> Schema

Two settings in .env (or on the dashboard's Setup page):

  JHA_MODEL         the model. Everything that goes out under your name or decides what is true about you:
                    the résumé, form answers, emails, revisions, what gets added to your storybook.
  JHA_DRAFT_MODEL   optional, a faster or cheaper model for first passes over the many: ranking every posting,
                    proposing fixes from your notes, the intake draft you edit by hand. Leave it empty and the
                    model does everything. (Which step uses which is listed in agent/pipeline.py.)

Each is written provider:name

  anthropic:claude-opus-5-5   Claude through the API                  ANTHROPIC_API_KEY
  claude-code                 your Claude Code login, no API key      (claude-code:<model> picks a model)
  ollama:qwen3:32b            an open-source model on your computer   OLLAMA_BASE_URL (default http://localhost:11434/v1)
  openai:<name>               any OpenAI-compatible server: vLLM, LM Studio, llama.cpp, OpenRouter, Together…
                                                                      JHA_OPENAI_BASE_URL, JHA_OPENAI_API_KEY

Older settings still work when JHA_MODEL is empty: LLM_PROVIDER (anthropic | openai_compat | claude_code),
MODEL_TAILOR, MODEL_SCORE (becomes the draft model when it differs), LLM_MODEL, LLM_BASE_URL, LLM_API_KEY.
Relevance ranking also uses Jev (TypeSafe) when TYPESAFE_API_KEY is set; see agent/jev.py.
"""
from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
import time
from typing import Type, TypeVar
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)
PROVIDERS = {"anthropic": "Claude API", "claude-code": "Claude Code login", "ollama": "Ollama (open-source, on this computer)",
             "openai": "OpenAI-compatible server"}


# ---------------------------------------------------------------- which model
def _parse(text: str) -> dict | None:
    text = (text or "").strip()
    if not text:
        return None
    provider, _, name = text.partition(":")
    provider = provider.strip().lower().replace("_", "-")
    if provider not in PROVIDERS:          # a bare model name: Claude through the API
        provider, name = "anthropic", text
    return {"provider": provider, "name": name.strip()}


def _legacy(tier: str) -> dict | None:
    p = os.getenv("LLM_PROVIDER", "").strip()
    if not p:
        return None
    if p == "claude_code":
        return {"provider": "claude-code", "name": ""} if tier == "model" else None
    if p == "openai_compat":
        return {"provider": "openai", "name": os.getenv("LLM_MODEL", ""), "legacy_url": True} if tier == "model" else None
    tailor, score = os.getenv("MODEL_TAILOR", "claude-opus-5-5"), os.getenv("MODEL_SCORE", "")
    if tier == "model":
        return {"provider": "anthropic", "name": tailor}
    return {"provider": "anthropic", "name": score} if score and score != tailor else None


def spec(tier: str = "model") -> dict | None:
    """The model a tier runs on, or None (draft: the model does it; model: not set up yet)."""
    if tier == "draft":
        return _parse(os.getenv("JHA_DRAFT_MODEL", "")) or (_legacy("draft") if not os.getenv("JHA_MODEL") else None)
    s = _parse(os.getenv("JHA_MODEL", "")) or _legacy("model")
    if s:
        return s
    if os.getenv("ANTHROPIC_API_KEY"):
        return {"provider": "anthropic", "name": "claude-opus-5-5"}
    if shutil.which("claude"):
        return {"provider": "claude-code", "name": ""}
    return None


def label(s: dict | None) -> str:
    if not s:
        return ""
    return f"{s['provider']}:{s['name']}" if s.get("name") else s["provider"]


def missing(s: dict | None) -> str:
    """What this model still needs before it can run, in plain words ('' when nothing)."""
    if not s:
        return "Choose a model."
    p = s["provider"]
    if p == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
        return "Add your Anthropic API key."
    if p == "claude-code" and not shutil.which("claude"):
        return "Install Claude Code and sign in (the `claude` command)."
    if p in ("ollama", "openai") and not s.get("name"):
        return "Write the model's name."
    if p == "openai" and not (os.getenv("JHA_OPENAI_BASE_URL") or os.getenv("LLM_BASE_URL")):
        return "Add the server's address (JHA_OPENAI_BASE_URL)."
    return ""


def describe() -> dict:
    """For the Setup page and `agent.run models`: no keys, only what is chosen and what is missing."""
    m, d = spec("model"), spec("draft")
    return {"model": {"label": label(m), "provider": (m or {}).get("provider", ""), "name": (m or {}).get("name", ""), "missing": missing(m)},
            "draft": {"label": label(d), "provider": (d or {}).get("provider", ""), "name": (d or {}).get("name", ""), "missing": missing(d) if d else ""},
            "keys": {k: bool(os.getenv(k)) for k in ("ANTHROPIC_API_KEY", "JHA_OPENAI_API_KEY", "TYPESAFE_API_KEY", "JHA_MAIL_APP_PASSWORD")},
            "openai_base_url": os.getenv("JHA_OPENAI_BASE_URL", ""), "ollama_base_url": os.getenv("OLLAMA_BASE_URL", "")}


# ---------------------------------------------------------------- calling it
def _flatten(system_blocks: list[dict]) -> str:
    return "\n\n".join(b["text"] for b in system_blocks)


def _extract_json(text: str) -> str:
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        return m.group(1)
    a, b = text.find("{"), text.rfind("}")
    return text[a:b + 1] if a >= 0 else text


def _anthropic(system_blocks, user, schema: Type[T], effort, max_tokens, s) -> T:
    import anthropic
    client = anthropic.Anthropic()
    kw = dict(model=s["name"] or "claude-opus-5-5", max_tokens=max_tokens, output_config={"effort": effort},
              system=system_blocks, messages=[{"role": "user", "content": user}], output_format=schema)
    if max_tokens > 8000:
        with client.messages.stream(**kw) as st:
            return st.get_final_message().parsed_output
    return client.messages.parse(**kw).parsed_output


def _openai_compat(system_blocks, user, schema: Type[T], effort, max_tokens, s) -> T:
    import httpx
    if s["provider"] == "ollama":
        base, key = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"), "ollama"
    else:
        base = os.getenv("JHA_OPENAI_BASE_URL") or os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
        key = os.getenv("JHA_OPENAI_API_KEY") or os.getenv("LLM_API_KEY", "none")
    body = {"model": s["name"], "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": _flatten(system_blocks)}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()}}}
    last = None
    for _ in range(2):
        r = httpx.post(f"{base.rstrip('/')}/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"}, timeout=600)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        try:
            return schema.model_validate_json(_extract_json(text))
        except ValidationError as e:
            last = e
            body["messages"] += [{"role": "assistant", "content": text},
                                 {"role": "user", "content": f"That JSON did not match the schema: {e}. Reply with corrected JSON only."}]
    raise last


def _claude_code(system_blocks, user, schema: Type[T], effort, max_tokens, s) -> T:
    prompt = user + "\n\nReply with one JSON object only, matching this JSON schema:\n" + json.dumps(schema.model_json_schema())
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--append-system-prompt", _flatten(system_blocks)]
    if s.get("name"):
        cmd += ["--model", s["name"]]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    if out.returncode != 0:
        raise RuntimeError(out.stderr[-2000:])
    return schema.model_validate_json(_extract_json(json.loads(out.stdout).get("result", "")))


CALL = {"anthropic": _anthropic, "claude-code": _claude_code, "ollama": _openai_compat, "openai": _openai_compat}


def structured(system_blocks: list[dict], user: str, schema: Type[T], effort: str = "medium",
               max_tokens: int = 8000, tier: str = "model") -> T:
    from . import config  # loads .env
    # tier "claude-code": your Claude Code login, never an API key (ranking when Jev isn't connected)
    s = {"provider": "claude-code", "name": ""} if tier == "claude-code" else (spec("draft") if tier == "draft" else None) or spec("model")
    if not s or missing(s):
        raise RuntimeError("No model is set up yet: open the dashboard's Setup page, or set JHA_MODEL in .env. " + missing(s))
    return CALL[s["provider"]](system_blocks, user, schema, effort, max_tokens, s)


class _Ping(BaseModel):
    ok: bool
    said: str


def check(tier: str = "model") -> dict:
    """One tiny call, to prove a model answers with structured output. {ok, ms, model, error}"""
    from . import config  # noqa: F401  (loads .env)
    s = spec(tier)
    if not s:
        return {"ok": False, "model": "", "error": "Not set: the model does this step." if tier == "draft" else "Choose a model first."}
    if missing(s):
        return {"ok": False, "model": label(s), "error": missing(s)}
    t = time.time()
    try:
        r = CALL[s["provider"]]([{"type": "text", "text": "You are a connection test."}], "Reply with ok=true and said='ready'.", _Ping, "low", 200, s)
        return {"ok": bool(r.ok), "model": label(s), "ms": int((time.time() - t) * 1000)}
    except Exception as e:
        return {"ok": False, "model": label(s), "error": f"{e.__class__.__name__}: {str(e)[:300]}"}
