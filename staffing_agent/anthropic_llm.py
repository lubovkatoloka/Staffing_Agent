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


def get_api_key() -> str:
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        raise ValueError(
            "ANTHROPIC_API_KEY is not set. Add it to .env (see .env.example)."
        )
    return key


def complete_text(
    *,
    system: str,
    user: str,
    max_tokens: int = 4096,
    temperature: float = 0.2,
) -> str:
    """Single-turn completion; returns assistant text."""
    import anthropic

    client = anthropic.Anthropic(api_key=get_api_key())
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
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[: raw.rfind("```")].strip()
    return json.loads(raw)


def check_anthropic_connection() -> None:
    """One token completion to verify key + model name."""
    import anthropic

    model = anthropic_model_name()
    print(f"Using model: {model}", flush=True)
    client = anthropic.Anthropic(api_key=get_api_key())
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
