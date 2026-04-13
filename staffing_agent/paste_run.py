"""CLI: run Phase A + B + C on pasted thread text (same logic as @mention, without Socket Mode)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from staffing_agent.decision.node2_rules import node2_slack_markdown
from staffing_agent.extraction import extract_request_spec
from staffing_agent.node3_occupation import node3_slack_markdown
from staffing_agent.slack_phase_c import build_phase_c_section
from staffing_agent.thread_context import (
    build_context_reply,
    format_thread_preview,
    gather_notion_previews,
    notion_excerpt_for_llm,
)

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env", override=True)


def _src_label(src: str) -> str:
    return {
        "mock": "mock (set ANTHROPIC_API_KEY; unset STAFFING_AGENT_MOCK_LLM)",
        "anthropic": "Anthropic Opus",
        "error": "error",
    }.get(src, src)


def build_reply_from_paste(thread_text: str, *, notion_excerpt_override: str = "") -> tuple[str, str]:
    """
    Build the same mrkdwn body the bot would post for a thread whose text is `thread_text`.
    Returns (reply_text, extraction_source).
    """
    text = (thread_text or "").strip()
    messages: list[dict[str, Any]] = [{"user": "paste", "text": text}]
    previews = gather_notion_previews(messages)
    ctx = build_context_reply(messages, previews=previews)
    notion_ex = (notion_excerpt_override or "").strip() or notion_excerpt_for_llm(
        messages, previews=previews
    )
    thread_plain = format_thread_preview(messages)
    spec, src = extract_request_spec(thread_plain, notion_ex)
    reply = (
        ctx
        + f"\n\n*Phase B — extraction (Node 1)* _(source: {_src_label(src)})_\n"
        + spec.to_slack_block()
        + "\n\n"
        + node2_slack_markdown(spec.tier, spec.project_type_tags)
        + "\n\n"
        + node3_slack_markdown(
            tier=spec.tier,
            project_type_tags=spec.project_type_tags,
            summary=spec.summary,
        )
        + "\n\n"
        + build_phase_c_section()
    )
    if len(reply) > 12000:
        reply = reply[:11900] + "\n```\n… (truncated)"
    return reply, src


def post_reply_to_slack(channel: str, text: str) -> None:
    """Post a message as the bot (needs SLACK_BOT_TOKEN; bot must be in the channel)."""
    from slack_sdk import WebClient

    token = (os.environ.get("SLACK_BOT_TOKEN") or "").strip()
    if not token:
        raise ValueError("SLACK_BOT_TOKEN is not set")
    client = WebClient(token=token)
    resp = client.chat_postMessage(channel=channel.strip(), text=text)
    if not resp.get("ok"):
        raise RuntimeError(resp)
