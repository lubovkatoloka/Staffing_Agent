"""Phase B: LLM extraction → RequestSpec (Anthropic Opus or mock)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from staffing_agent.config_loader import load_thresholds
from staffing_agent.models.request_spec import RequestSpec

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env", override=True)

logger = logging.getLogger(__name__)


def uses_mock_llm() -> bool:
    if os.environ.get("STAFFING_AGENT_MOCK_LLM", "").strip() == "1":
        return True
    if not (os.environ.get("ANTHROPIC_API_KEY") or "").strip():
        return True
    return False


def _mock_spec() -> RequestSpec:
    th = load_thresholds()
    ver = th.get("spec_version", "?")
    return RequestSpec(
        tier=2,
        project_type_tags=[],
        summary=(
            f"Mock extraction (no Anthropic call). Decision-logic config v{ver}. "
            "Set ANTHROPIC_API_KEY and ensure STAFFING_AGENT_MOCK_LLM is not 1 for real Opus."
        ),
        confidence=0.0,
        notes="mock_llm",
    )


def extract_request_spec(thread_text: str, notion_excerpt: str = "") -> tuple[RequestSpec, str]:
    """
    Returns (RequestSpec, source) where source is 'mock' or 'anthropic'.
    """
    if uses_mock_llm():
        return _mock_spec(), "mock"

    from staffing_agent.anthropic_llm import complete_json

    schema = RequestSpec.model_json_schema()
    th = load_thresholds()
    system = (
        "You are a staffing assistant. Read the Slack thread (and optional Notion excerpts). "
        "Infer project tier (1–4) only if the text supports it; otherwise use null. "
        "Extract project type tags if mentioned. "
        f"Decision-logic spec_version from config: {th.get('spec_version', 'unknown')}. "
        "Output a single JSON object matching this JSON Schema (no markdown, no commentary):\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )
    user = (
        "### Slack thread\n"
        f"{thread_text}\n\n"
        "### Notion excerpts (may be empty)\n"
        f"{notion_excerpt or '(none)'}\n"
    )
    try:
        data = complete_json(system=system, user=user, max_tokens=2048)
        spec = RequestSpec.model_validate(data)
        return spec, "anthropic"
    except Exception as e:
        logger.exception("extraction failed: %s", e)
        return (
            RequestSpec(
                tier=None,
                summary="Extraction failed; see notes.",
                confidence=0.0,
                notes=str(e)[:500],
            ),
            "error",
        )
