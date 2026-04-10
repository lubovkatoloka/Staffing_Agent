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


def collect_urls_from_messages(messages: list[dict[str, Any]]) -> list[str]:
    seen: dict[str, None] = {}
    for m in messages:
        t = m.get("text") or ""
        for u in extract_urls_from_text(t):
            seen[u] = None
    return list(seen.keys())


def format_thread_preview(messages: list[dict[str, Any]], max_chars: int = 3500) -> str:
    lines: list[str] = []
    total = 0
    for m in messages:
        uid = m.get("user") or "?"
        text = (m.get("text") or "").strip()
        if not text:
            continue
        line = f"<@{uid}>: {text}"
        if total + len(line) + 1 > max_chars:
            lines.append("… (truncated)")
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines) if lines else "(empty thread)"


def build_context_reply(messages: list[dict[str, Any]]) -> str:
    """Full mrkdwn reply for Phase A (context only)."""
    preview = format_thread_preview(messages)
    urls = collect_urls_from_messages(messages)
    notion_token = (os.environ.get("NOTION_TOKEN") or "").strip()

    lines: list[str] = [
        "*Staffing Agent — context (phase A)*",
        f"_Messages in thread:_ {len(messages)}",
        f"_URLs detected:_ {len(urls)}",
    ]

    notion_sections: list[str] = []
    notion_ids_seen: set[str] = set()
    for u in urls:
        nid = notion_page_id_from_url(u)
        if nid and nid not in notion_ids_seen:
            notion_ids_seen.add(nid)

    if notion_ids_seen:
        if not notion_token:
            notion_sections.append(
                "_Notion:_ links found, but `NOTION_TOKEN` is not set — add integration token to `.env` to fetch page previews."
            )
        else:
            for nid in notion_ids_seen:
                info = fetch_page_preview(notion_token, nid)
                if info.get("error"):
                    notion_sections.append(f"• Notion `{nid[:8]}…`: _{info['error']}_")
                else:
                    title = info.get("title") or "(untitled)"
                    prv = (info.get("preview") or "").strip()
                    if prv:
                        clip = prv[:800] + ("…" if len(prv) > 800 else "")
                        notion_sections.append(f"• *{title}*\n```{clip}```")
                    else:
                        notion_sections.append(f"• *{title}* _(no block text fetched)_")

    if urls and not notion_sections:
        lines.append("_No Notion page IDs parsed from URLs (only notion.so / notion.site links are supported)._")

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
