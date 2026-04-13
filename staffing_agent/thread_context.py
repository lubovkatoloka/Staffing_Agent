"""Build Slack reply text: thread text + URLs + optional Notion previews."""

from __future__ import annotations

import os
import re
from typing import Any

from staffing_agent.notion_fetch import fetch_page_preview, notion_page_id_from_url

URL_RE = re.compile(r"https?://[^\s<>\]]+", re.IGNORECASE)


def extract_urls_from_text(text: str) -> list[str]:
    raw = URL_RE.findall(text or "")
    out: list[str] = []
    for u in raw:
        u = u.rstrip(").,;\"'")
        if u not in out:
            out.append(u)
    return out


def exclude_bot_user_messages(
    messages: list[dict[str, Any]],
    bot_user_id: str,
) -> list[dict[str, Any]]:
    """
    Drop messages posted by our Slack app bot so Phase B does not re-ingest
    prior bot replies (large JSON, duplicate Phase A text).
    """
    if not (bot_user_id or "").strip():
        return messages
    bid = bot_user_id.strip()
    return [m for m in messages if (m.get("user") or "") != bid]


def slack_message_plain_text(m: dict[str, Any]) -> str:
    """
    Top-level `text` plus text nested in Block Kit `blocks` / attachments.
    Slack often sends empty `text` when the body lives only in blocks.
    """
    t = (m.get("text") or "").strip()
    if t:
        return t
    parts: list[str] = []
    _collect_text_from_blocks(m.get("blocks"), parts)
    if parts:
        return "\n".join(parts).strip()
    for att in m.get("attachments") or []:
        if not isinstance(att, dict):
            continue
        for key in ("text", "pretext", "fallback"):
            v = att.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    for f in m.get("files") or []:
        if not isinstance(f, dict):
            continue
        title = f.get("title") or f.get("name")
        if title:
            return f"[shared file: {title}]"
    return ""


def _collect_text_from_blocks(obj: Any, out: list[str]) -> None:
    """Shallow-deep: collect string values for keys named 'text' under blocks."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "text" and isinstance(v, str) and v.strip():
                out.append(v.strip())
            else:
                _collect_text_from_blocks(v, out)
    elif isinstance(obj, list):
        for x in obj:
            _collect_text_from_blocks(x, out)


def collect_urls_from_messages(messages: list[dict[str, Any]]) -> list[str]:
    seen: dict[str, None] = {}
    for m in messages:
        t = slack_message_plain_text(m)
        for u in extract_urls_from_text(t):
            seen[u] = None
    return list(seen.keys())


def format_thread_preview(messages: list[dict[str, Any]], max_chars: int = 3500) -> str:
    lines: list[str] = []
    total = 0
    for m in messages:
        uid = m.get("user") or "?"
        text = slack_message_plain_text(m)
        if not text:
            text = "_[no extractable text — file-only or unsupported payload]_"
        line = f"<@{uid}>: {text}"
        if total + len(line) + 1 > max_chars:
            lines.append("… (truncated)")
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines) if lines else "(empty thread)"


def gather_notion_previews(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Fetch Notion page previews for notion.so URLs in thread (deduped).
    Each item: {page_id, title, preview, error?}
    """
    urls = collect_urls_from_messages(messages)
    notion_token = (os.environ.get("NOTION_TOKEN") or "").strip()
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for u in urls:
        nid = notion_page_id_from_url(u)
        if not nid or nid in seen:
            continue
        seen.add(nid)
        if not notion_token:
            out.append(
                {
                    "page_id": nid,
                    "title": "",
                    "preview": "",
                    "error": "NOTION_TOKEN not set",
                }
            )
            continue
        info = fetch_page_preview(notion_token, nid)
        out.append(
            {
                "page_id": nid,
                "title": info.get("title") or "",
                "preview": (info.get("preview") or "").strip(),
                "error": info.get("error"),
            }
        )
    return out


def notion_excerpt_for_llm(
    messages: list[dict[str, Any]],
    *,
    previews: list[dict[str, Any]] | None = None,
    max_chars: int = 6000,
) -> str:
    """Plain text blob for Anthropic (titles + previews). Pass `previews` to avoid a second Notion fetch."""
    rows = previews if previews is not None else gather_notion_previews(messages)
    parts: list[str] = []
    total = 0
    for row in rows:
        if row.get("error"):
            block = f"[Notion {row['page_id'][:8]}… error: {row['error']}]\n"
        else:
            title = row.get("title") or "(untitled)"
            prv = (row.get("preview") or "")[:3000]
            block = f"## {title}\n{prv}\n"
        if total + len(block) > max_chars:
            parts.append("… (notion excerpt truncated)")
            break
        parts.append(block)
        total += len(block)
    return "\n".join(parts).strip()


def build_context_reply(
    messages: list[dict[str, Any]],
    *,
    previews: list[dict[str, Any]] | None = None,
) -> str:
    """Full mrkdwn reply for Phase A (context only). Pass `previews` to reuse a single Notion fetch."""
    preview = format_thread_preview(messages)
    urls = collect_urls_from_messages(messages)
    rows = previews if previews is not None else gather_notion_previews(messages)

    lines: list[str] = [
        "*Staffing Agent — context (phase A)*",
        f"_Messages in thread:_ {len(messages)}",
        f"_URLs detected:_ {len(urls)}",
    ]

    notion_sections: list[str] = []
    token_missing_shown = False
    for row in rows:
        nid = row["page_id"]
        if row.get("error") == "NOTION_TOKEN not set":
            if not token_missing_shown:
                notion_sections.append(
                    "_Notion:_ links found, but `NOTION_TOKEN` is not set — add integration token to `.env` to fetch page previews."
                )
                token_missing_shown = True
            continue
        if row.get("error"):
            notion_sections.append(f"• Notion `{nid[:8]}…`: _{row['error']}_")
        else:
            title = row.get("title") or "(untitled)"
            prv = (row.get("preview") or "").strip()
            if prv:
                clip = prv[:800] + ("…" if len(prv) > 800 else "")
                notion_sections.append(f"• *{title}*\n```{clip}```")
            else:
                notion_sections.append(f"• *{title}* _(no block text fetched)_")

    if urls and not notion_sections:
        lines.append(
            "_No Notion page IDs parsed from URLs (only notion.so / notion.site links are supported)._"
        )

    if notion_sections:
        lines.append("*Notion previews*")
        lines.extend(notion_sections)

    lines.append("*Thread*")
    lines.append("```")
    lines.append(preview)
    lines.append("```")

    reply = "\n".join(lines)
    if len(reply) > 12000:
        reply = reply[:11900] + "\n```\n… (truncated)"
    return reply
