"""Optional Notion API: page title + short text preview (integration token in NOTION_TOKEN)."""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

NOTION_VERSION = "2022-06-28"


def notion_page_id_from_url(url: str) -> str | None:
    """Extract Notion page UUID (32 hex) from a notion.so / notion.site URL."""
    if "notion.so" not in url and "notion.site" not in url:
        return None
    path = urlparse(url).path
    for part in path.split("/"):
        cand = re.sub(r"[^0-9a-fA-F]", "", part).lower()
        if len(cand) >= 32:
            return cand[-32:]
    hex_only = "".join(re.findall(r"[0-9a-fA-F]", path))
    if len(hex_only) >= 32:
        return hex_only[-32:]
    return None


def format_uuid(page_id: str) -> str:
    p = page_id.replace("-", "").lower()
    if len(p) != 32:
        return page_id
    return f"{p[0:8]}-{p[8:12]}-{p[12:16]}-{p[16:20]}-{p[20:32]}"


def _notion_get(path: str, token: str) -> dict[str, Any]:
    req = urllib.request.Request(
        f"https://api.notion.com/v1{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _plain_from_rich(rich: list[dict[str, Any]]) -> str:
    return "".join(p.get("plain_text", "") for p in rich)


def _text_from_block(block: dict[str, Any]) -> str:
    btype = block.get("type")
    if not btype:
        return ""
    inner = block.get(btype) or {}
    rich = inner.get("rich_text") or []
    if rich:
        return _plain_from_rich(rich)
    if btype == "child_page":
        return inner.get("title") or ""
    return ""


def fetch_page_preview(token: str, page_id: str, max_chars: int = 1200) -> dict[str, Any]:
    """
    Returns {"title": str, "preview": str, "error": None | str}.
    """
    pid = format_uuid(page_id)
    out: dict[str, Any] = {"title": "", "preview": "", "error": None}
    try:
        page = _notion_get(f"/pages/{pid}", token)
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = str(e)
        out["error"] = f"HTTP {e.code}: {body[:200]}"
        logger.warning("Notion page fetch failed: %s", out["error"])
        return out
    except Exception as e:
        out["error"] = str(e)
        logger.exception("Notion fetch error")
        return out

    props = page.get("properties") or {}
    title = ""
    for _k, pv in props.items():
        if pv.get("type") == "title":
            title = _plain_from_rich(pv.get("title") or [])
            break
    out["title"] = title or "(untitled)"

    preview_parts: list[str] = []
    try:
        children = _notion_get(f"/blocks/{pid}/children?page_size=50", token)
        for block in children.get("results") or []:
            t = _text_from_block(block)
            if t.strip():
                preview_parts.append(t.strip())
            if sum(len(p) for p in preview_parts) >= max_chars:
                break
    except Exception as e:
        logger.info("Notion blocks fetch skipped/failed: %s", e)

    out["preview"] = "\n".join(preview_parts)[:max_chars]
    return out
