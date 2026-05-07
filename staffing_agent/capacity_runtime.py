"""Glue: Capacity SQL rows → per-person CapacityRow lists + CapacityVerdict."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from staffing_agent.decision import CapacityRow, CapacityVerdict, assess
from staffing_agent.node3_row_utils import email_value
from staffing_agent.staffing_csv import StaffingRecord, comment_blocks_staffing, load_staffing_table_config


def _row_int_like(row: Mapping[str, Any], key: str) -> int:
    lower = {k.lower(): v for k, v in row.items()}
    raw = lower.get(key.lower())
    if raw is None:
        return 0
    if isinstance(raw, bool):
        return 1 if raw else 0
    s = str(raw).strip().lower()
    if s in ("1", "true", "yes"):
        return 1
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 0


def _row_get_ci(row: Mapping[str, Any], *keys: str) -> Any:
    lower = {k.lower(): v for k, v in row.items()}
    for k in keys:
        if k.lower() in lower:
            return lower[k.lower()]
    return None


def _looks_capacity_fanout(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return False
    for r in rows:
        if _row_get_ci(r, "user_id", "USER_ID"):
            return True
    return False


def _truthy_pto_upcoming(row: dict[str, Any]) -> bool:
    return _row_int_like(row, "on_pto_upcoming") != 0


def capacity_rows_from_sql_group(group: list[dict[str, Any]]) -> list[CapacityRow]:
    """Build deduped CapacityRow list from rows sharing one user_id."""
    seen: set[str] = set()
    out: list[CapacityRow] = []
    for r in group:
        pid = str(_row_get_ci(r, "project_id", "PROJECT_ID") or "").strip()
        if not pid or pid.lower() == "null":
            continue
        if pid in seen:
            continue
        seen.add(pid)
        pname = str(_row_get_ci(r, "project_name", "name", "NAME") or "").strip() or pid
        tier = str(_row_get_ci(r, "tier", "TIER") or "").strip()
        stage = str(_row_get_ci(r, "stage", "STAGE") or "").strip()
        status = str(_row_get_ci(r, "status", "STATUS") or "").strip()
        out.append(
            CapacityRow(
                project_id=pid,
                project_name=pname,
                tier=tier,
                stage=stage,
                status=status,
            )
        )
    return out


def _pto_today_end_from_group(group: list[dict[str, Any]]) -> Optional[str]:
    for r in group:
        if _row_int_like(r, "on_pto_today") == 0:
            continue
        end = _row_get_ci(r, "pto_today_end", "PTO_TODAY_END")
        if end:
            return str(end).strip()[:10]
    return None


def _pto_flags_from_group(group: list[dict[str, Any]]) -> tuple[bool, Optional[tuple[str, str]]]:
    on_today = any(_row_int_like(r, "on_pto_today") != 0 for r in group)
    upcoming: Optional[tuple[str, str]] = None
    for r in group:
        if not _truthy_pto_upcoming(r):
            continue
        s = str(_row_get_ci(r, "pto_upcoming_start", "PTO_UPCOMING_START") or "").strip()
        e = str(_row_get_ci(r, "pto_upcoming_end", "PTO_UPCOMING_END") or "").strip()
        if s and e:
            upcoming = (s[:10], e[:10])
            break
    return on_today, upcoming


def verdict_for_person_rows(
    group: list[dict[str, Any]],
    *,
    decision_cfg: Mapping[str, Any],
    new_project_weight: float,
    staffing: Mapping[str, StaffingRecord],
    in_hard_exclude_override: Optional[bool] = None,
) -> tuple[CapacityVerdict, tuple[CapacityRow, ...]]:
    """Single person's SQL fan-out rows → verdict + project rows."""
    cr = capacity_rows_from_sql_group(group)
    on_pto, pto_up = _pto_flags_from_group(group)

    em = str(_row_get_ci(group[0], "user_email", "email") or "").strip().lower()
    rec = staffing.get(em) if em else None
    st_cfg = load_staffing_table_config()
    hard_ex = in_hard_exclude_override
    if hard_ex is None:
        hard_ex = bool(rec and comment_blocks_staffing(rec.comment, st_cfg))

    v = assess(
        cr,
        on_pto_today=on_pto,
        pto_upcoming=pto_up,
        in_hard_exclude=hard_ex,
        new_project_weight=new_project_weight,
        cfg=decision_cfg,
    )
    return v, tuple(cr)


def collapse_capacity_sql_rows(
    rows: list[dict[str, Any]],
    *,
    decision_cfg: Mapping[str, Any],
    new_project_weight: float,
    staffing: Mapping[str, StaffingRecord],
) -> list[dict[str, Any]]:
    """One dict per user_id with canonical Node 3/4 fields + verdict."""
    from collections import defaultdict

    by_uid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        uid = str(_row_get_ci(r, "user_id", "USER_ID") or "").strip()
        if uid:
            by_uid[uid].append(r)

    out: list[dict[str, Any]] = []
    for uid, group in by_uid.items():
        base = dict(group[0])
        base["user_id"] = uid
        verdict, crs = verdict_for_person_rows(
            group,
            decision_cfg=decision_cfg,
            new_project_weight=new_project_weight,
            staffing=staffing,
        )
        rg = str(_row_get_ci(base, "role_group", "ROLE_GROUP") or "").strip()
        base["project_role"] = role_group_to_project_role(rg)
        base["_capacity_verdict"] = verdict
        base["_capacity_rows"] = crs
        base["_pto_today_end"] = _pto_today_end_from_group(group)
        out.append(base)
    return out


def merge_explicit_verdict_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """When rows already carry `_capacity_verdict`, optionally attach project_role from role_group."""
    out: list[dict[str, Any]] = []
    for r in rows:
        cp = dict(r)
        rg = str(_row_get_ci(cp, "role_group", "ROLE_GROUP") or "").strip()
        if rg and not str(cp.get("project_role") or "").strip():
            cp["project_role"] = role_group_to_project_role(rg)
        out.append(cp)
    return out


def prepare_rows_for_recommendation(
    rows: list[dict[str, Any]],
    *,
    decision_cfg: Mapping[str, Any],
    new_project_weight: float,
    staffing: Mapping[str, StaffingRecord],
) -> list[dict[str, Any]]:
    """Normalize raw SQL or test rows to one row per person with `_capacity_verdict`."""
    if not rows:
        return []
    if all(r.get("_capacity_verdict") is not None for r in rows):
        return merge_explicit_verdict_rows(rows)
    if _looks_capacity_fanout(rows):
        return collapse_capacity_sql_rows(
            rows,
            decision_cfg=decision_cfg,
            new_project_weight=new_project_weight,
            staffing=staffing,
        )
    st_cfg = load_staffing_table_config()
    synthetic: list[dict[str, Any]] = []
    for r in rows:
        cp = dict(r)
        if cp.get("_capacity_verdict") is None:
            em = email_value(cp)
            rec = staffing.get(em) if em else None
            hard_ex = bool(rec and comment_blocks_staffing(rec.comment, st_cfg))
            cp["_capacity_verdict"] = assess(
                [],
                on_pto_today=False,
                pto_upcoming=None,
                in_hard_exclude=hard_ex,
                new_project_weight=new_project_weight,
                cfg=decision_cfg,
            )
            cp.setdefault("_capacity_rows", tuple())
        synthetic.append(cp)
    return merge_explicit_verdict_rows(synthetic)


def role_group_to_project_role(role_group: str) -> str:
    g = (role_group or "").strip().upper()
    if "SOE" in g or "SSOE" in g:
        return "soe"
    if g == "DPM":
        return "dpm"
    if "WFM" in g or "WFC" in g:
        return "wfm"
    if "QM" in g or "QC" in g:
        return "qm"
    if g == "SE":
        return "se"
    return (role_group or "").strip().lower() or "?"


def format_capacity_projects_line(rows: tuple[CapacityRow, ...]) -> str:
    """`name (T/stage/status)` entries separated by ` | `."""
    parts: list[str] = []
    for r in rows:
        tier_short = (r.tier or "").replace("Tier ", "T").strip() or "?"
        st = (r.stage or "").strip().replace("_", " ")
        stat = (r.status or "").strip()
        nm = (r.project_name or r.project_id or "?").strip()
        parts.append(f"{nm} ({tier_short}/{st}/{stat})")
    return " | ".join(parts) if parts else "(no active projects in snapshot)"


def default_new_project_weight(decision_cfg: Mapping[str, Any], tier: Optional[int]) -> float:
    """Tier weight for overload check when staffing a tier-N project (building / ON_TRACK proxy)."""
    if tier is None or tier not in (1, 2, 3, 4):
        return 0.0
    tw = decision_cfg.get("tier_weights") or {}
    key = f"Tier {tier}"
    raw = tw.get(key)
    try:
        return float(raw) if raw is not None else 1.0
    except (TypeError, ValueError):
        return 1.0
