"""
Optional Databricks query: project staffing snapshot (sql/project_staffing.sql).

Current SQL shape: one row per project_id with pivoted role columns (responsible, dpm, …).
Recommended people are matched by name substring in those columns (no per-row email in the result set).
"""

from __future__ import annotations

import os
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
        if _roles_hitting_name(r, person_name):
            out.append(r)
        if len(out) >= max_projects:
            break
    return out


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

    lines: list[str] = [
        "*Сейчас на проектах (staffing, Databricks)*",
        "_Снимок из `sql/project_staffing.sql`: проекты, где имя из Occupation встречается в списках ролей "
        "(подстрока по имени; при расхождении написания проверьте вручную)._",
    ]
    for display_name in recommended_names:
        matches = _projects_for_person(
            ps_rows,
            display_name,
            max_projects=max_projects_per_person,
        )
        if not matches:
            lines.append(
                f"• *{display_name}* — _нет проектов в выдаче, где имя совпало с полями ролей._"
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
        total_hits = sum(1 for r in ps_rows if bool(_roles_hitting_name(r, display_name)))
        if total_hits > max_projects_per_person:
            extra = f" _+{total_hits - max_projects_per_person} ещё_"
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
) -> str:
    """
    Run project_staffing.sql and return markdown for recommended people only.
    Empty string if profile missing, SQL missing, query fails, or no overlap.
    """
    from staffing_agent.node3_occupation import (
        MIN_OPTIONAL_SQL_LEN,
        _run_query_json_first,
        _sql_executable_text,
        _try_parse_query_json,
    )
    from staffing_agent.node3_row_utils import name_value

    if not databricks_profile():
        return ""
    path = project_staffing_sql_path()
    sql_text = _sql_executable_text(path)
    if len(sql_text) < MIN_OPTIONAL_SQL_LEN:
        return ""

    pick_rows = pickable_recommendation_rows(
        occupation_rows,
        tier=tier,
        decision_cfg=decision_cfg,
        project_type_tags=project_type_tags or [],
        summary=summary or "",
        limit=4,
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

    ok, out = _run_query_json_first(sql_text, timeout_sec=min(timeout_sec, 180))
    if not ok:
        return ""
    ps_rows = _try_parse_query_json(out) or []
    return format_project_staffing_markdown(ps_rows, names_ordered)
