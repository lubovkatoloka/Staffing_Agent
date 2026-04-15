"""Anthropic Messages API — default model: Claude Opus (override via ANTHROPIC_MODEL)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env", override=True)

# Default: Opus. Override if Anthropic renames IDs — see https://docs.anthropic.com/en/docs/about-claude/models
DEFAULT_OPUS_MODEL = "claude-opus-4-6"


def anthropic_model_name() -> str:
    return (os.environ.get("ANTHROPIC_MODEL") or DEFAULT_OPUS_MODEL).strip()


def anthropic_base_url() -> str | None:
    """
    Optional proxy (e.g. internal LiteLLM). If set, requests go here instead of api.anthropic.com.
    Use ANTHROPIC_BASE_URL or LITELLM_BASE_URL (same meaning).
    """
    u = (
        os.environ.get("ANTHROPIC_BASE_URL")
        or os.environ.get("LITELLM_BASE_URL")
        or ""
    ).strip()
    return u or None


def get_api_key() -> str:
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        raise ValueError(
            "ANTHROPIC_API_KEY is not set. Add it to .env (see .env.example)."
        )
    return key


def _anthropic_client() -> Any:
    import anthropic

    kwargs: dict[str, Any] = {"api_key": get_api_key()}
    base = anthropic_base_url()
    if base:
        kwargs["base_url"] = base
    return anthropic.Anthropic(**kwargs)


def complete_text(
    *,
    system: str,
    user: str,
    max_tokens: int = 4096,
    temperature: float = 0.2,
) -> str:
    """Single-turn completion; returns assistant text."""
    client = _anthropic_client()
    msg = client.messages.create(
        model=anthropic_model_name(),
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    parts: list[str] = []
    for block in msg.content:
        if hasattr(block, "text") and block.text:
            parts.append(block.text)
    return "".join(parts).strip()


def _parse_json_object(raw: str) -> dict[str, Any]:
    """Parse model output: strict JSON, or first balanced `{...}` object (handles extra prose / truncation)."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[: text.rfind("```")].strip()
        elif "```" in text:
            text = text[: text.rfind("```")].strip()
    try:
        out = json.loads(text)
        if isinstance(out, dict):
            return out
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object in model output")
    decoder = json.JSONDecoder()
    try:
        obj, _end = decoder.raw_decode(text[start:])
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    end = text.rfind("}")
    if end > start:
        out = json.loads(text[start : end + 1])
        if isinstance(out, dict):
            return out
    raise ValueError("Could not parse JSON object from model output")


def complete_json(
    *,
    system: str,
    user: str,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """Ask for JSON only; parse result (best-effort)."""
    raw = complete_text(
        system=system + "\nRespond with valid JSON only, no markdown fences.",
        user=user,
        max_tokens=max_tokens,
        temperature=0.1,
    )
    return _parse_json_object(raw)


def check_anthropic_connection() -> None:
    """One token completion to verify key + model name."""
    model = anthropic_model_name()
    print(f"Using model: {model}", flush=True)
    base = anthropic_base_url()
    if base:
        print(f"Using API base URL (proxy): {base}", flush=True)
    client = _anthropic_client()
    msg = client.messages.create(
        model=model,
        max_tokens=32,
        messages=[{"role": "user", "content": 'Reply with exactly: ok'}],
    )
    text = ""
    for block in msg.content:
        if hasattr(block, "text"):
            text += block.text or ""
    print(f"OK: Anthropic replied ({len(text.strip())} chars)", flush=True)
