"""Live exclusion data from Notion People & Tags (Staffing pool).

Replaces CSV Comment-regex exclusions. Queries Notion each staffing run with a TTL cache.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DOTENV_TRIED = False

NOTION_API_VERSION = "2026-03-11"
NOTION_DATA_SOURCE_ID = os.environ.get(
    "STAFFING_NOTION_PEOPLE_DS_ID", "73de0744-99bc-4ed9-a64a-ea35b5a15b94"
).strip()

STAFFING_POOL_ROLES = frozenset({"DPM", "SSOE+SOE", "WFM+WFC", "QC+QM", "SE"})

HARD_EXCLUDE_PHRASES = (
    "do not staff",
    "do not use",
    "unavailable",
    "onboarding",
)
HARD_EXCLUDE_TOKEN_RE = re.compile(r"\bDNS\b", re.IGNORECASE)

CACHE_TTL_SECONDS = 300  # 5 minutes

# Map People & Tags Role Tag → capacity `project_role` norms used in tier filters.
NOTION_TAG_TO_PROJECT_ROLES: dict[str, frozenset[str]] = {
    "DPM": frozenset({"dpm"}),
    "SSOE+SOE": frozenset({"soe"}),
    "WFM+WFC": frozenset({"wfm"}),
    "QC+QM": frozenset({"qm"}),
    "SE": frozenset({"se"}),
}


class ExclusionUnavailableError(RuntimeError):
    """No exclusion snapshot available (no token, first fetch failed, no cache)."""

    def __init__(self, message: str = "", *, slack_detail: str | None = None) -> None:
        super().__init__(message)
        self.slack_detail = slack_detail
@dataclass(frozen=True)
class ExcludedPerson:
    email: str  # lowercased
    name: str
    role_tag: str
    comment: str


@dataclass(frozen=True)
class ExclusionResult:
    excluded: tuple[ExcludedPerson, ...]
    fetched_at: float

    @property
    def excluded_emails(self) -> frozenset[str]:
        return frozenset(p.email for p in self.excluded)

    @property
    def reasons(self) -> dict[str, str]:
        return {p.email: p.comment for p in self.excluded}


def _maybe_load_repo_dotenv() -> None:
    """If `.env` next to repo root was never merged into os.environ, load it (does not override existing vars)."""
    global _DOTENV_TRIED
    if _DOTENV_TRIED:
        return
    _DOTENV_TRIED = True
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=False)


def notion_auth_token() -> str:
    """Bearer token for Notion API: prefer NOTION_API_KEY, then NOTION_TOKEN."""
    _maybe_load_repo_dotenv()
    return (
        (os.environ.get("NOTION_API_KEY") or os.environ.get("NOTION_TOKEN") or "").strip()
    )


def slack_exclusion_unavailable_message(*, title: str = "Staffing", detail: str | None = None) -> str:
    mins = max(1, (CACHE_TTL_SECONDS + 59) // 60)
    body = (
        f"*{title}*\n"
        f"⚠️ Exclusion data unavailable. Try in {mins} min or ping @operations."
    )
    if detail:
        body += "\n" + detail
    return body


def project_roles_for_notion_tag(tag: str) -> frozenset[str]:
    raw = (tag or "").strip()
    if not raw:
        return frozenset()
    out: set[str] = set()
    for part in re.split(r"[,;/]", raw):
        p = part.strip()
        if p in NOTION_TAG_TO_PROJECT_ROLES:
            out |= NOTION_TAG_TO_PROJECT_ROLES[p]
    return frozenset(out)


def role_tag_in_staffing_pool(role_tag: str) -> bool:
    raw = (role_tag or "").strip()
    if not raw:
        return False
    parts = [x.strip() for x in re.split(r"[,;/]", raw) if x.strip()]
    if not parts:
        parts = [raw]
    return any(p in STAFFING_POOL_ROLES for p in parts)


def format_excluded_comment_block(
    result: ExclusionResult,
    required_project_roles: frozenset[str],
    *,
    start_dates: dict[str, date] | None = None,
    max_lines: int = 12,
) -> str:
    """Slack mrkdwn footer: onboarding exclusions (People & Tags) overlapping Tier/capacity roles."""
    if not required_project_roles:
        return ""
    hits = [
        p
        for p in result.excluded
        if "onboarding" in (p.comment or "").lower()
        and project_roles_for_notion_tag(p.role_tag) & required_project_roles
    ]
    if not hits:
        return ""
    today = date.today()

    def _sort_key(p: ExcludedPerson) -> tuple[int, int, str]:
        if start_dates:
            sd = start_dates.get(p.email)
        else:
            sd = None
        if sd is None:
            return (1, 0, p.name.casefold())
        days = max(0, (today - sd).days)
        return (0, days, p.name.casefold())

    hits.sort(key=_sort_key)
    lines: list[str] = ["_Onboarding (excluded from picks):_"]
    shown = hits[:max_lines]
    for p in shown:
        if start_dates:
            sd = start_dates.get(p.email)
        else:
            sd = None
        if sd is None:
            tail = "(start date unknown)"
        else:
            tail = f"({max(0, (today - sd).days)} days)"
        lines.append(f"• {p.name} — onboarding {tail}")
    if len(hits) > max_lines:
        lines.append(f"_…and {len(hits) - max_lines} more._")
    return "\n".join(lines)


def check_notion_exclusions_connection() -> None:
    """One live query (uses cache afterwards). Raises on failure."""
    reset_exclusion_store()
    get_exclusion_store().get()


_store: Optional["ExclusionStore"] = None


def reset_exclusion_store() -> None:
    global _store
    _store = None


def get_exclusion_store() -> ExclusionStore:
    global _store
    if _store is None:
        _store = ExclusionStore()
    return _store


def match_hard_exclude(comment: str) -> Optional[str]:
    """Return matched phrase / token label if comment triggers hard-exclude, else None."""
    if not (comment or "").strip():
        return None
    lowered = comment.lower()
    for phrase in HARD_EXCLUDE_PHRASES:
        if phrase in lowered:
            return phrase
    if HARD_EXCLUDE_TOKEN_RE.search(comment):
        return "DNS"
    return None


class ExclusionStore:
    """TTL cache around live Notion exclusion rows."""

    _match_hard_exclude = staticmethod(match_hard_exclude)

    def __init__(self) -> None:
        self._cached: Optional[ExclusionResult] = None

    def get(self) -> ExclusionResult:
        now = time.time()
        if self._cached is not None and (now - self._cached.fetched_at) < CACHE_TTL_SECONDS:
            return self._cached
        token = notion_auth_token()
        if not token:
            raise ExclusionUnavailableError(
                "NOTION_API_KEY or NOTION_TOKEN must be set for live People & Tags exclusions.",
                slack_detail=(
                    "_The bot process has no Notion token._ Add `NOTION_API_KEY=…` (or `NOTION_TOKEN`) to `.env` "
                    "at the **repo root** (next to `staffing_agent/`), restart the bot, then run "
                    "`python3 -m staffing_agent --check`._"
                ),
            )
        try:
            fresh = self._fetch_live(token)
            self._cached = fresh
            return fresh
        except Exception as exc:
            logger.warning("Notion exclusion fetch failed: %s", exc)
            if self._cached is not None:
                logger.warning(
                    "Falling back to stale exclusion cache (age %ds)",
                    int(now - self._cached.fetched_at),
                )
                return self._cached
            raise ExclusionUnavailableError(
                "Exclusion data unavailable — Notion fetch failed and no cache.",
                slack_detail=(
                    "_Notion request failed (see bot stderr for HTTP/body snippet)._ "
                    "Check the integration has access to **Staffing — People & Tags**, "
                    "the token is valid, then retry after a few minutes if Notion had an outage._"
                ),
            ) from exc

    def _fetch_live(self, token: str) -> ExclusionResult:
        pages = self._query_paginated(token)
        excluded: list[ExcludedPerson] = []
        for page in pages:
            props_ci = _properties_ci(page)
            email_prop = _pick_prop(props_ci, "email")
            name_prop = _pick_prop(props_ci, "name")
            role_prop = _pick_prop(props_ci, "role tag")
            comment_prop = _pick_prop(props_ci, "comment")

            email = _plain_email(email_prop).strip().lower()
            comment = _plain_text(comment_prop).strip()
            role_tag = _plain_select(role_prop).strip()
            name = (
                _plain_title(name_prop).strip()
                or _plain_text(name_prop).strip()
                or email.split("@")[0]
            )

            if not email or "@" not in email:
                continue
            if not comment:
                continue
            if match_hard_exclude(comment) is None:
                continue
            excluded.append(
                ExcludedPerson(email=email, name=name, role_tag=role_tag, comment=comment)
            )

        return ExclusionResult(excluded=tuple(excluded), fetched_at=time.time())

    def _query_paginated(self, token: str) -> list[dict[str, Any]]:
        ds_id = NOTION_DATA_SOURCE_ID.replace("-", "")
        if len(ds_id) == 32:
            ds_fmt = f"{ds_id[0:8]}-{ds_id[8:12]}-{ds_id[12:16]}-{ds_id[16:20]}-{ds_id[20:32]}"
        else:
            ds_fmt = NOTION_DATA_SOURCE_ID

        props_q = "&".join(
            "filter_properties=" + urllib.parse.quote(p)
            for p in ("Email", "Name", "Role Tag", "Comment")
        )
        base_path = f"/data_sources/{ds_fmt}/query"
        url_base = f"https://api.notion.com/v1{base_path}?{props_q}"

        out: list[dict[str, Any]] = []
        cursor: Optional[str] = None
        while True:
            body: dict[str, Any] = {"page_size": 100, "result_type": "page"}
            if cursor:
                body["start_cursor"] = cursor
            raw = _notion_post(token, url_base, body)
            results = raw.get("results") or []
            for item in results:
                if isinstance(item, dict) and item.get("object") == "page":
                    out.append(item)
            if not raw.get("has_more"):
                break
            cursor = raw.get("next_cursor")
            if not cursor:
                break
        return out


def _properties_ci(page: dict[str, Any]) -> dict[str, Any]:
    props = page.get("properties") or {}
    return {(str(k).strip().lower()): v for k, v in props.items()}


def _pick_prop(props_ci: dict[str, Any], *names: str) -> Any:
    for n in names:
        k = n.lower().strip()
        if k in props_ci:
            return props_ci[k]
    return None


def _plain_title(prop: Any) -> str:
    if not isinstance(prop, dict):
        return ""
    if prop.get("type") != "title":
        return ""
    inner = prop.get("title") or []
    return "".join(str(x.get("plain_text", "")) for x in inner if isinstance(x, dict))


def _plain_text(prop: Any) -> str:
    if not isinstance(prop, dict):
        return ""
    t = prop.get("type")
    if t == "rich_text":
        inner = prop.get("rich_text") or []
        return "".join(str(x.get("plain_text", "")) for x in inner if isinstance(x, dict))
    if t == "title":
        return _plain_title(prop)
    return ""


def _plain_email(prop: Any) -> str:
    if not isinstance(prop, dict) or prop.get("type") != "email":
        return ""
    inner = prop.get("email")
    return str(inner if isinstance(inner, str) else inner or "")


def _plain_select(prop: Any) -> str:
    if not isinstance(prop, dict):
        return ""
    t = prop.get("type")
    if t == "select":
        sel = prop.get("select")
        if isinstance(sel, dict):
            return str(sel.get("name") or "").strip()
        return ""
    if t == "multi_select":
        inner = prop.get("multi_select") or []
        return ", ".join(
            str(x.get("name", "")).strip() for x in inner if isinstance(x, dict) and x.get("name")
        )
    if t == "status":
        st = prop.get("status")
        if isinstance(st, dict):
            return str(st.get("name") or "").strip()
        return ""
    return ""


def _notion_post(token: str, url: str, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_API_VERSION,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:800]
        except Exception:
            detail = str(e)
        raise RuntimeError(f"Notion HTTP {e.code}: {detail}") from e
