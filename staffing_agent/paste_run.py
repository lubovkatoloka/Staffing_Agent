"""CLI: run Phase A + B + C on pasted thread text (same logic as @mention, without Socket Mode)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from staffing_agent.extraction import extract_request_spec
from staffing_agent.intent import is_team_capacity_query, single_role_focus_from_thread
from staffing_agent.models.request_spec import RequestSpec
from staffing_agent.node3_occupation import node3_slack_markdown
from staffing_agent.reply_template import reply_style
from staffing_agent.slack_phase_c import build_phase_c_section
from staffing_agent.team_capacity import build_live_capacity_markdown
from staffing_agent.thread_context import (
    build_context_reply,
    format_thread_preview,
    gather_google_doc_previews,
    gather_notion_previews,
    phase_b_excerpt_for_llm,
)

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env", override=True)


def _src_label(src: str) -> str:
    return {
        "mock": "mock (set ANTHROPIC_API_KEY; unset STAFFING_AGENT_MOCK_LLM)",
        "anthropic": "Anthropic Opus",
        "anthropic_fallback": "Anthropic failed — deal-feed heuristic summary",
        "anthropic_rescue": "Anthropic/JSON failed — tier recovered from thread text",
        "error": "error",
    }.get(src, src)


def _node3_markdown_when_no_tier() -> str:
    """Phase B has no tier and thread did not match capacity / single-role heuristics."""
    return (
        "*Staffing — нужен контекст*\n"
        "_Не удалось распознать сценарий: снимок загрузки команды, узкий запрос по роли, или проект с tier._\n\n"
        "*Примеры:*\n"
        "• `Team capacity` @who_is_available — кто свободен по ролям (primary + alternates)\n"
        "• `Need 1 SoE tier 3 …` — кандидаты под роль и полная команда при заданном tier\n"
        "• Тред с описанием сделки + tier — подбор всех ролей под проект\n"
    )


def _public_spec_lede(spec: RequestSpec) -> str:
    """Short Slack-visible preamble: tier+judge line, else first line of summary only."""
    th = spec.tier_slack_header_mrkdwn()
    if th:
        return th
    summ = (spec.summary or "").strip()
    if not summ:
        return ""
    first_line = summ.split("\n", 1)[0].strip()
    if len(first_line) > 280:
        return first_line[:277] + "…"
    return first_line


def _resolve_node3_parts(
    spec: RequestSpec,
    *,
    thread_plain: str,
    trigger_message_text: str | None,
) -> list[str]:
    if is_team_capacity_query(thread_plain, trigger_message_text=trigger_message_text):
        return build_live_capacity_markdown()
    role = single_role_focus_from_thread(thread_plain)
    if role and spec.tier is None:
        return build_live_capacity_markdown(only_role=role)
    if spec.tier is None:
        return [_node3_markdown_when_no_tier()]
    return [
        node3_slack_markdown(
            tier=spec.tier,
            project_type_tags=spec.project_type_tags,
            summary=spec.summary,
            sese_path=spec.sese_path,
        )
    ]


def build_slack_mention_reply(
    messages: list[dict[str, Any]],
    previews: list[dict[str, Any]],
    spec: RequestSpec,
    *,
    extraction_src_label: str,
    google_previews: list[dict[str, Any]] | None = None,
    thread_plain: str | None = None,
    trigger_message_text: str | None = None,
) -> list[str]:
    """
    Socket Mode + paste: shape depends on STAFFING_AGENT_REPLY_STYLE.

    Returns one or more Slack ``text`` payloads (team capacity: overview + one or more detail chunks).
    """
    tp = (thread_plain or "").strip() or format_thread_preview(messages)
    trig = trigger_message_text

    n3_list = _resolve_node3_parts(spec, thread_plain=tp, trigger_message_text=trig)
    lede = _public_spec_lede(spec)
    rs = reply_style()

    def _merge_lede_first(chunk: str) -> str:
        parts = [p for p in (lede, chunk) if p]
        return "\n\n".join(parts)

    phase_c = build_phase_c_section()

    if rs == "minimal" or rs == "compact":
        if len(n3_list) == 1:
            return [_merge_lede_first(n3_list[0])]
        merged_first = _merge_lede_first(n3_list[0])
        return [merged_first] + list(n3_list[1:])

    prefix = (
        build_context_reply(messages, previews=previews, google_previews=google_previews)
        + f"\n\n*Phase B — extraction (Node 1)* _(source: {extraction_src_label})_\n"
        + spec.to_slack_block()
        + "\n\n"
    )
    if len(n3_list) == 1:
        body = _merge_lede_first(n3_list[0])
        full = prefix + body + "\n\n" + phase_c
        return [full]
    first = _merge_lede_first(n3_list[0])
    rest = list(n3_list[1:])
    rest[-1] = rest[-1] + "\n\n" + phase_c
    return [prefix + first] + rest


def build_reply_from_paste(thread_text: str, *, notion_excerpt_override: str = "") -> tuple[str, str]:
    """
    Build the same mrkdwn body the bot would post for a thread whose text is `thread_text`.
    Returns (reply_text, extraction_source). Multiple bot messages are joined with a divider line.
    """
    text = (thread_text or "").strip()
    messages: list[dict[str, Any]] = [{"user": "paste", "text": text}]
    previews = gather_notion_previews(messages)
    google_previews = gather_google_doc_previews(messages)
    notion_ex = (notion_excerpt_override or "").strip() or phase_b_excerpt_for_llm(
        messages,
        notion_previews=previews,
        google_previews=google_previews,
    )
    thread_plain = format_thread_preview(messages)
    spec, src = extract_request_spec(thread_plain, notion_ex)
    parts = build_slack_mention_reply(
        messages,
        previews,
        spec,
        extraction_src_label=_src_label(src),
        google_previews=google_previews,
    )
    reply = "\n\n────────\n\n".join(parts)
    return reply, src


def post_reply_to_slack(channel: str, text: str) -> None:
    """Post one or more messages as the bot (needs SLACK_BOT_TOKEN; bot must be in the channel)."""
    from slack_sdk import WebClient

    token = (os.environ.get("SLACK_BOT_TOKEN") or "").strip()
    if not token:
        raise ValueError("SLACK_BOT_TOKEN is not set")
    client = WebClient(token=token)
    parts = text.split("\n\n────────\n\n")
    for chunk in parts:
        resp = client.chat_postMessage(channel=channel.strip(), text=chunk)
        if not resp.get("ok"):
            raise RuntimeError(resp)
