"""
Optional Databricks query: project staffing snapshot (sql/project_staffing.sql).

Current SQL shape: one row per project_id with pivoted role columns (responsible, dpm, …).
Recommended people are matched by name substring in those columns (no per-row email in the result set).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Optional

from staffing_agent.databricks_cli import databricks_profile
from staffing_agent.node4_recommendation import pickable_recommendation_rows

_ROOT = Path(__file__).resolve().parent.parent

# Pivoted columns from project_staffing.sql (lowercase keys from JSON)
_ROLE_KEYS = (
    "responsible",
    "director",
    "bizdev",
    "dpm",
    "soe",
    "wfm",
    "qm",
    "other",
)

# Keep in sync with sql/project_staffing.sql (orders) and capacity.sql — hide terminal statuses.
_EXCLUDED_ORDER_STATUSES = frozenset(
    {
        "archived",
        "completed",
        "canceled",
        "cancelled",
        "archieved",  # typo in source data
    }
)


def _row_status_active(row: dict[str, Any]) -> bool:
    """True if the order is not in a final status (omit from staffing block)."""
    lower_map = {k.lower(): v for k, v in row.items()}
    raw = lower_map.get("status")
    if raw is None:
        return True
    s = str(raw).strip().lower()
    return s not in _EXCLUDED_ORDER_STATUSES


def project_staffing_sql_path() -> Path:
    override = (os.environ.get("STAFFING_PROJECT_STAFFING_SQL_PATH") or "").strip()
    if override:
        return Path(override).expanduser()
    return _ROOT / "sql" / "project_staffing.sql"


def _roles_hitting_name(row: dict[str, Any], person_name: str) -> list[str]:
    n = (person_name or "").strip().lower()
    if len(n) < 2:
        return []
    lower_map = {k.lower(): v for k, v in row.items()}
    hit: list[str] = []
    for k in _ROLE_KEYS:
        v = lower_map.get(k)
        if v is None:
            continue
        if n in str(v).lower():
            hit.append(k)
    return hit


def _projects_for_person(
    ps_rows: list[dict[str, Any]],
    person_name: str,
    *,
    max_projects: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in ps_rows:
        if not _row_status_active(r):
            continue
        if _roles_hitting_name(r, person_name):
            out.append(r)
        if len(out) >= max_projects:
            break
    return out


def count_active_orders_for_person(
    ps_rows: list[dict[str, Any]],
    person_name: str,
) -> int:
    """How many active (non-terminal) orders mention this display name in any role column."""
    if not ps_rows or not (person_name or "").strip():
        return 0
    active_rows = [r for r in ps_rows if _row_status_active(r)]
    n = 0
    for r in active_rows:
        if _roles_hitting_name(r, person_name):
            n += 1
    return n


def inline_active_orders_markdown(
    ps_rows: list[dict[str, Any]],
    display_name: str,
    *,
    max_projects: int = 4,
) -> str:
    """
    One line for Tier 3 bullets: where the person appears on active orders (project_staffing snapshot).
    Empty string if no snapshot rows, no active rows, or name does not match any role field.
    """
    if not ps_rows or not (display_name or "").strip():
        return ""
    active_rows = [r for r in ps_rows if _row_status_active(r)]
    matches = _projects_for_person(
        active_rows,
        display_name,
        max_projects=max_projects,
    )
    if not matches:
        return ""
    parts: list[str] = []
    for r in matches:
        pname = (r.get("name") or r.get("project_name") or "?").strip()
        client = (r.get("client_name") or "").strip()
        st = (r.get("stage") or "").strip()
        stat = (r.get("status") or "").strip()
        roles_hit = _roles_hitting_name(r, display_name)
        rh = ", ".join(roles_hit) if roles_hit else "?"
        meta = " · ".join(x for x in (client, f"{st}/{stat}" if st or stat else "") if x)
        if meta:
            parts.append(f"`{pname}` ({rh}; {meta})")
        else:
            parts.append(f"`{pname}` ({rh})")
    extra = ""
    total_hits = sum(1 for r in active_rows if _roles_hitting_name(r, display_name))
    if total_hits > max_projects:
        extra = f" _+{total_hits - max_projects} more_"
    return "_On active orders:_ " + "; ".join(parts) + extra


def fetch_project_staffing_rows(*, timeout_sec: int = 180) -> list[dict[str, Any]]:
    """
    Run sql/project_staffing.sql once; return JSON rows or [] if profile/SQL/query missing or failed.
    """
    from staffing_agent.node3_occupation import (
        MIN_OPTIONAL_SQL_LEN,
        _run_query_json_first,
        _sql_executable_text,
        _try_parse_query_json,
    )

    if not databricks_profile():
        return []
    path = project_staffing_sql_path()
    sql_text = _sql_executable_text(path)
    if len(sql_text) < MIN_OPTIONAL_SQL_LEN:
        return []
    print(
        "[staffing] Databricks: running sql/project_staffing.sql …",
        file=sys.stderr,
        flush=True,
    )
    t0 = time.perf_counter()
    ok, out = _run_query_json_first(sql_text, timeout_sec=min(timeout_sec, 180))
    print(
        f"[staffing] Databricks: project_staffing.sql finished in {time.perf_counter() - t0:.1f}s "
        f"(ok={ok}, ~{len(out)} chars raw output)",
        file=sys.stderr,
        flush=True,
    )
    if not ok:
        return []
    return _try_parse_query_json(out) or []


def format_project_staffing_markdown(
    ps_rows: list[dict[str, Any]],
    recommended_names: list[str],
    *,
    max_projects_per_person: int = 8,
) -> str:
    """
    One bullet per recommended person; projects where their name appears in any role column.
    `recommended_names` — display order, deduped by caller.
    """
    if not ps_rows or not recommended_names:
        return ""

    active_rows = [r for r in ps_rows if _row_status_active(r)]
    if not active_rows:
        return ""

    lines: list[str] = [
        "*Currently on projects (staffing, Databricks)*",
        "_Only orders whose status is not in (ARCHIVED, COMPLETED, CANCELED). "
        "Name matches as substring in role fields; load in the recommendation above is from Capacity summary — different slices._",
    ]
    for display_name in recommended_names:
        matches = _projects_for_person(
            active_rows,
            display_name,
            max_projects=max_projects_per_person,
        )
        if not matches:
            lines.append(
                f"• *{display_name}* — _no active orders where the name matched role fields._"
            )
            continue
        parts: list[str] = []
        for r in matches:
            pname = (r.get("name") or r.get("project_name") or "?").strip()
            client = (r.get("client_name") or "").strip()
            st = (r.get("stage") or "").strip()
            stat = (r.get("status") or "").strip()
            roles_hit = _roles_hitting_name(r, display_name)
            rh = ", ".join(roles_hit) if roles_hit else "?"
            meta = " · ".join(x for x in (client, f"{st}/{stat}" if st or stat else "") if x)
            if meta:
                parts.append(f"`{pname}` ({rh}; {meta})")
            else:
                parts.append(f"`{pname}` ({rh})")
        extra = ""
        total_hits = sum(1 for r in active_rows if _roles_hitting_name(r, display_name))
        if total_hits > max_projects_per_person:
            extra = f" _+{total_hits - max_projects_per_person} more_"
        lines.append(f"• *{display_name}* — " + "; ".join(parts) + extra)

    return "\n".join(lines)


def fetch_project_staffing_addon(
    occupation_rows: list[dict[str, Any]],
    *,
    tier: Optional[int],
    decision_cfg: Mapping[str, Any],
    project_type_tags: Optional[list[str]],
    summary: str,
    timeout_sec: int = 120,
    preloaded_ps_rows: Optional[list[dict[str, Any]]] = None,
) -> str:
    """
    Run project_staffing.sql and return markdown for recommended people only.
    Empty string if profile missing, SQL missing, query fails, or no overlap.

    If ``preloaded_ps_rows`` is set (e.g. Tier 3 already fetched for inline lines), SQL is not run again.
    """
    from staffing_agent.node3_occupation import MIN_OPTIONAL_SQL_LEN, _sql_executable_text
    from staffing_agent.node3_row_utils import name_value

    if preloaded_ps_rows is not None:
        ps_rows = preloaded_ps_rows
    else:
        if not databricks_profile():
            return ""
        path = project_staffing_sql_path()
        sql_text = _sql_executable_text(path)
        if len(sql_text) < MIN_OPTIONAL_SQL_LEN:
            return ""
        ps_rows = fetch_project_staffing_rows(timeout_sec=min(timeout_sec, 180))
        if not ps_rows:
            return ""

    pick_rows = pickable_recommendation_rows(
        occupation_rows,
        tier=tier,
        decision_cfg=decision_cfg,
        project_type_tags=project_type_tags or [],
        summary=summary or "",
        limit=4,
        project_staffing_rows=ps_rows if tier == 3 else None,
    )
    seen: set[str] = set()
    names_ordered: list[str] = []
    for r in pick_rows:
        nm = (name_value(r) or "").strip()
        if not nm or nm == "?":
            continue
        key = nm.lower()
        if key not in seen:
            seen.add(key)
            names_ordered.append(nm)
    if not names_ordered:
        return ""

    return format_project_staffing_markdown(ps_rows, names_ordered)
