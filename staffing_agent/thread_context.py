"""Build Slack reply text: thread text + URLs + optional Notion previews."""

from __future__ import annotations

import os
import re
from typing import Any

from staffing_agent.google_docs_fetch import (
    credentials_configured as google_credentials_configured,
    fetch_google_doc,
    google_doc_id_from_url,
)
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


def default_thread_preview_max_chars() -> int:
    """Env STAFFING_THREAD_PREVIEW_MAX_CHARS (default 50000) caps Phase B thread text; raise for long deal threads."""
    raw = (os.environ.get("STAFFING_THREAD_PREVIEW_MAX_CHARS") or "50000").strip()
    try:
        return max(2000, min(int(raw), 500_000))
    except ValueError:
        return 50000


def format_thread_preview(messages: list[dict[str, Any]], max_chars: int | None = None) -> str:
    if max_chars is None:
        max_chars = default_thread_preview_max_chars()
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


def gather_google_doc_previews(
    messages: list[dict[str, Any]],
    *,
    max_chars_per_doc: int = 12000,
) -> list[dict[str, Any]]:
    """
    Fetch Google Docs plain text for docs.google.com URLs in thread (deduped by document id).
    Each item: {doc_id, title, preview, error?}
    Requires service account JSON (see .env.example); each doc must be shared with that account (Viewer).
    """
    urls = collect_urls_from_messages(messages)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for u in urls:
        did = google_doc_id_from_url(u)
        if not did or did in seen:
            continue
        seen.add(did)
        if not google_credentials_configured():
            out.append(
                {
                    "doc_id": did,
                    "title": "",
                    "preview": "",
                    "error": "Google credentials not set",
                }
            )
            continue
        info = fetch_google_doc(did, max_chars=max_chars_per_doc)
        out.append(
            {
                "doc_id": did,
                "title": (info.get("title") or "").strip(),
                "preview": (info.get("text") or "").strip(),
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


def google_docs_excerpt_for_llm(
    messages: list[dict[str, Any]],
    *,
    previews: list[dict[str, Any]] | None = None,
    max_chars: int = 6000,
) -> str:
    """Plain text from Google Docs for Anthropic. Pass `previews` to avoid a second API fetch."""
    rows = previews if previews is not None else gather_google_doc_previews(messages)
    parts: list[str] = []
    total = 0
    for row in rows:
        if row.get("error"):
            block = f"[Google Doc {row['doc_id'][:8]}… error: {row['error']}]\n"
        else:
            title = row.get("title") or "(untitled)"
            prv = (row.get("preview") or "")[:3000]
            block = f"## Google Doc: {title}\n{prv}\n"
        if total + len(block) > max_chars:
            parts.append("… (google doc excerpt truncated)")
            break
        parts.append(block)
        total += len(block)
    return "\n".join(parts).strip()


def phase_b_excerpt_for_llm(
    messages: list[dict[str, Any]],
    *,
    notion_previews: list[dict[str, Any]] | None = None,
    google_previews: list[dict[str, Any]] | None = None,
    max_chars: int = 8000,
) -> str:
    """Notion + Google Docs text for Phase B extraction (split budget when both present)."""
    half = max(2000, max_chars // 2)
    n = notion_excerpt_for_llm(messages, previews=notion_previews, max_chars=half)
    g = google_docs_excerpt_for_llm(messages, previews=google_previews, max_chars=half)
    return "\n\n".join(x for x in (n, g) if x).strip()


def build_context_minimal_line(messages: list[dict[str, Any]]) -> str:
    """One line for minimal Slack mode — no full thread dump."""
    n = len(messages)
    return f"_Context: {n} message(s) in thread._"


def build_context_reply(
    messages: list[dict[str, Any]],
    *,
    previews: list[dict[str, Any]] | None = None,
    google_previews: list[dict[str, Any]] | None = None,
) -> str:
    """Full mrkdwn reply for Phase A (context only). Pass `previews` / `google_previews` to reuse fetches."""
    preview = format_thread_preview(messages)
    urls = collect_urls_from_messages(messages)
    rows = previews if previews is not None else gather_notion_previews(messages)
    g_rows = google_previews if google_previews is not None else gather_google_doc_previews(messages)

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

    google_sections: list[str] = []
    g_cred_missing_shown = False
    for row in g_rows:
        did = row["doc_id"]
        if row.get("error") == "Google credentials not set":
            if not g_cred_missing_shown:
                google_sections.append(
                    "_Google Docs:_ links found, but `STAFFING_GOOGLE_APPLICATION_CREDENTIALS` or "
                    "`GOOGLE_APPLICATION_CREDENTIALS` is not set — add a service account JSON path (see `.env.example`)."
                )
                g_cred_missing_shown = True
            continue
        if row.get("error"):
            google_sections.append(f"• Google Doc `{did[:8]}…`: _{row['error']}_")
        else:
            title = row.get("title") or "(untitled)"
            prv = (row.get("preview") or "").strip()
            if prv:
                clip = prv[:800] + ("…" if len(prv) > 800 else "")
                google_sections.append(f"• *{title}* _(Google Doc)_\n```{clip}```")
            else:
                google_sections.append(f"• *{title}* _(Google Doc, empty body)_")

    if google_sections:
        lines.append("*Google Docs previews*")
        lines.extend(google_sections)

    lines.append("*Thread*")
    lines.append("```")
    lines.append(preview)
    lines.append("```")

    reply = "\n".join(lines)
    if len(reply) > 12000:
        reply = reply[:11900] + "\n```\n… (truncated)"
    return reply
