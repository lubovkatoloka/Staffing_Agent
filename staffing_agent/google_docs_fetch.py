"""Google Docs API: fetch document title + plain text (service account JSON)."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# https://developers.google.com/docs/api/reference/rest/v1/documents
DOCS_READONLY = "https://www.googleapis.com/auth/documents.readonly"

DOC_URL_RE = re.compile(
    r"https?://docs\.google\.com/document/d/([a-zA-Z0-9_-]+)",
    re.IGNORECASE,
)


def google_doc_id_from_url(url: str) -> str | None:
    """Extract document ID from a docs.google.com/document/d/... URL."""
    m = DOC_URL_RE.search(url or "")
    return m.group(1) if m else None


def _credentials_path() -> Path | None:
    for key in (
        "STAFFING_GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_APPLICATION_CREDENTIALS",
    ):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            p = Path(raw).expanduser()
            if p.is_file():
                return p
    return None


def credentials_configured() -> bool:
    return _credentials_path() is not None


def _elements_to_plain(elements: list[dict[str, Any]] | None) -> str:
    if not elements:
        return ""
    parts: list[str] = []
    for el in elements:
        if "paragraph" in el:
            for pe in el["paragraph"].get("elements", []):
                tr = pe.get("textRun")
                if tr and isinstance(tr.get("content"), str):
                    parts.append(tr["content"])
            parts.append("\n")
        elif "table" in el:
            for row in el["table"].get("tableRows", []):
                for cell in row.get("tableCells", []):
                    parts.append(_elements_to_plain(cell.get("content")))
                    parts.append("\t")
                parts.append("\n")
            parts.append("\n")
        elif "sectionBreak" in el:
            parts.append("\n")
        elif "tableOfContents" in el:
            toc = el["tableOfContents"]
            for pe in toc.get("content", []):
                parts.append(_elements_to_plain([pe]))
    return "".join(parts)


def plain_text_from_document_resource(doc: dict[str, Any]) -> str:
    """Turn a Documents API `documents.get` JSON body into plain text."""
    body = doc.get("body") or {}
    content = body.get("content")
    if not isinstance(content, list):
        return ""
    return _elements_to_plain(content).strip()


def fetch_google_doc(
    doc_id: str,
    *,
    max_chars: int = 12000,
) -> dict[str, Any]:
    """
    Returns {"doc_id", "title", "text", "error": None | str}.
    Requires STAFFING_GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_APPLICATION_CREDENTIALS
    pointing to a service account JSON with Docs API enabled; the doc must be shared
    with that service account (Viewer), or be readable by it via Workspace domain-wide delegation (advanced).
    """
    doc_id = (doc_id or "").strip()
    out: dict[str, Any] = {"doc_id": doc_id, "title": "", "text": "", "error": None}
    if not doc_id:
        out["error"] = "empty document id"
        return out

    path = _credentials_path()
    if not path:
        out["error"] = "Google credentials not set (STAFFING_GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_APPLICATION_CREDENTIALS)"
        return out

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as e:
        out["error"] = f"google-api-python-client not installed: {e}"
        return out

    try:
        creds = service_account.Credentials.from_service_account_file(
            str(path),
            scopes=[DOCS_READONLY],
        )
        service = build("docs", "v1", credentials=creds, cache_discovery=False)
        doc = service.documents().get(documentId=doc_id).execute()
    except Exception as e:
        logger.exception("Google Docs API error: %s", e)
        out["error"] = str(e)[:500]
        return out

    out["title"] = (doc.get("title") or "").strip() or "(untitled)"
    text = plain_text_from_document_resource(doc)
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    out["text"] = text
    return out


def fetch_google_doc_from_url(url: str, *, max_chars: int = 12000) -> dict[str, Any]:
    did = google_doc_id_from_url(url)
    if not did:
        return {
            "doc_id": "",
            "title": "",
            "text": "",
            "error": "not a Google Docs URL",
        }
    return fetch_google_doc(did, max_chars=max_chars)
