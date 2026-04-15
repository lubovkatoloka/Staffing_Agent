"""Phase B: LLM extraction → RequestSpec (Anthropic Opus or mock)."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from staffing_agent.config_loader import load_decision_config, load_tier_classification_prompt
from staffing_agent.intent import is_likely_deal_notification_thread
from staffing_agent.models.request_spec import RequestSpec

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env", override=True)

logger = logging.getLogger(__name__)


def mock_llm_reason() -> str:
    """Why mock mode is active; empty string if live LLM should run."""
    if os.environ.get("STAFFING_AGENT_MOCK_LLM", "").strip() == "1":
        return "STAFFING_AGENT_MOCK_LLM=1"
    if not (os.environ.get("ANTHROPIC_API_KEY") or "").strip():
        return "ANTHROPIC_API_KEY is empty"
    return ""


def uses_mock_llm() -> bool:
    return bool(mock_llm_reason())


def forced_tier_from_env() -> int | None:
    """
    Optional override for Phase B: set ``STAFFING_FORCE_TIER`` to ``1``–``4`` to always use that tier
    for Node 2–3 (e.g. force Tier 3 team layout + project_staffing snapshot) regardless of LLM output.
    """
    raw = (os.environ.get("STAFFING_FORCE_TIER") or "").strip()
    if not raw:
        return None
    try:
        v = int(raw)
    except ValueError:
        logger.warning("STAFFING_FORCE_TIER ignored (not an integer): %r", raw)
        return None
    if 1 <= v <= 4:
        return v
    logger.warning("STAFFING_FORCE_TIER ignored (must be 1–4): %r", raw)
    return None


def _thread_brief_for_fallback(thread_text: str, max_chars: int = 480) -> str:
    """One-line preview when LLM output cannot be parsed (deal-feed fallback)."""
    t = (thread_text or "").replace("\r", "\n")
    lines: list[str] = []
    for line in t.split("\n"):
        line = re.sub(r"^<@[^>]+>:\s*", "", line.strip())
        if line and not line.startswith("_[no extractable text"):
            lines.append(line)
    out = " ".join(lines)
    out = re.sub(r"\s+", " ", out).strip()
    if len(out) > max_chars:
        out = out[: max_chars - 1] + "…"
    return out or "CRM / deal thread (no extractable preview)."


def _normalize_llm_spec_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Best-effort coercion so minor model mistakes still validate."""
    out = dict(data)
    tk = out.get("thread_kind")
    if tk is not None and tk not in (
        "deal_notification",
        "staffing_request",
        "capacity_question",
        "unclear",
    ):
        out["thread_kind"] = None
    tr = out.get("tier")
    if isinstance(tr, str) and tr.strip().isdigit():
        out["tier"] = int(tr.strip())
    elif isinstance(tr, float) and tr == int(tr) and 1 <= int(tr) <= 4:
        out["tier"] = int(tr)
    conf = out.get("confidence")
    if isinstance(conf, str):
        try:
            out["confidence"] = float(conf)
        except ValueError:
            out["confidence"] = 0.0
    cc = out.get("complexity_class")
    if cc is not None and cc not in ("S", "M", "L"):
        out["complexity_class"] = None
    return out


def _deal_feed_fallback_spec(thread_text: str, exc: BaseException) -> RequestSpec:
    """When Phase B fails but the thread looks like Attio/CRM — avoid generic 'unclear'."""
    brief = _thread_brief_for_fallback(thread_text)
    err_note = f"Heuristic fallback (Phase B error: {type(exc).__name__}: {str(exc)[:350]})"
    return RequestSpec(
        thread_kind="deal_notification",
        tier=None,
        complexity_class=None,
        tier_rationale="",
        project_type_tags=[],
        summary=brief,
        confidence=0.35,
        notes=err_note[:2000],
    )


def apply_forced_tier(spec: RequestSpec) -> RequestSpec:
    ft = forced_tier_from_env()
    if ft is None:
        return spec
    prev = spec.tier
    tr = (spec.tier_rationale or "").strip()
    if tr:
        tr = f"{tr}\n_STAFFING_FORCE_TIER={ft} (was tier {prev!r})_"
    else:
        tr = f"_STAFFING_FORCE_TIER={ft} (was tier {prev!r})_"
    notes = (spec.notes or "").strip()
    if prev != ft:
        extra = f"tier overridden {prev!r} → {ft}"
        notes = f"{notes}; {extra}" if notes else extra
    # Tier 3 ownership row uses complexity M — align when forcing tier 3.
    cc = "M" if ft == 3 else spec.complexity_class
    logger.info("STAFFING_FORCE_TIER: applying tier %s (previous %s)", ft, prev)
    return spec.model_copy(
        update={
            "tier": ft,
            "complexity_class": cc,
            "tier_rationale": tr,
            "notes": notes[:2000],
        }
    )


def _mock_spec() -> RequestSpec:
    th = load_decision_config()
    ver = th.get("spec_version", "?")
    return RequestSpec(
        thread_kind="unclear",
        tier=2,
        complexity_class="S",
        tier_rationale="Mock: default Tier 2 placeholder.",
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

    `notion_excerpt` may include Notion + Google Docs text (same field as before; name kept for compatibility).
    """
    if uses_mock_llm():
        logger.warning("using mock LLM: %s", mock_llm_reason())
        return apply_forced_tier(_mock_spec()), "mock"

    from staffing_agent.anthropic_llm import complete_json

    schema = RequestSpec.model_json_schema()
    th = load_decision_config()
    tc = load_tier_classification_prompt()
    rules = (tc.get("classification_rules") or "").strip()
    fa = (tc.get("framework_alignment") or "").strip()
    out_req = (tc.get("output_requirements") or "").strip()
    fw = (tc.get("framework_url") or "").strip()
    boundary = (tc.get("system_boundary") or "").strip()
    boundary_block = f"### System boundary (enforced)\n{boundary}\n\n" if boundary else ""
    fa_block = f"{fa}\n\n" if fa else ""

    system = (
        "You are a staffing assistant implementing Node 1 (project classification) for Toloka Staffing Agent. "
        f"Decision-logic spec_version: {th.get('spec_version', 'unknown')}. "
        f"Project Classification Framework (canonical reference): {fw}\n\n"
        "### Tier & complexity rules (must follow)\n"
        f"{rules}\n\n"
        f"{fa_block}"
        "When the thread describes an RL-gym / multi-app pilot with domain-heavy delivery and a scale path, "
        "use **Tier 3** and complexity **M**, not Tier 2 — unless the scope is clearly a simple standard pipeline only.\n\n"
        "### Output discipline\n"
        f"{out_req}\n\n"
        f"{boundary_block}"
        "Read the Slack thread and optional Notion excerpts. "
        "If the thread is pasted proposal copy, FAQ, or 'better phrasing' without a staffing ask, set tier to null — do not assign Tier 1–4 from product description alone. "
        "When tier is set and unclear, still extract product signals (evals, languages, call, etc.); "
        "Node 3 lists people by role from Databricks when SQL is configured. "
        "Extract project type tags only when they help staffing (short labels: e.g. Evals, TTS, multilingual); omit or minimize tags when tier is null. "
        "Output a single JSON object matching this JSON Schema (no markdown, no commentary):\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )
    user = (
        "### Slack thread\n"
        f"{thread_text}\n\n"
        "### Linked pages (Notion + Google Docs; may be empty)\n"
        f"{notion_excerpt or '(none)'}\n"
    )
    try:
        data = complete_json(system=system, user=user, max_tokens=4096)
        data = _normalize_llm_spec_dict(data)
        spec = RequestSpec.model_validate(data)
        return apply_forced_tier(spec), "anthropic"
    except Exception as e:
        logger.exception("extraction failed: %s", e)
        if is_likely_deal_notification_thread(thread_text):
            logger.warning("using deal-feed RequestSpec fallback after Phase B failure")
            return apply_forced_tier(_deal_feed_fallback_spec(thread_text, e)), "anthropic_fallback"
        return (
            apply_forced_tier(
                RequestSpec(
                    thread_kind="unclear",
                    tier=None,
                    summary="Extraction failed; see notes.",
                    confidence=0.0,
                    notes=str(e)[:500],
                )
            ),
            "error",
        )
