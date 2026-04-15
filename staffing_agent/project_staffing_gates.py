"""
Project staffing snapshot (Databricks) — extra gates before recommending someone.

Rules are config-driven (`staffing_ps_gates` in decision_logic.yaml); product will iterate.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Optional


def _stage(row: dict[str, Any]) -> str:
    return str(row.get("stage") or "").strip()


def _status(row: dict[str, Any]) -> str:
    return str(row.get("status") or "").strip()


def _norm_stage(s: str) -> str:
    return s.strip().lower().replace(" ", "_").replace("-", "_")


def _is_blocked_status(status: str, blocked_token: str) -> bool:
    return (status or "").strip().upper() == (blocked_token or "BLOCKED_CLIENT").upper()


def _parse_deadline(val: Any) -> Optional[date]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _in_same_iso_week(d: date, ref: date) -> bool:
    return d.isocalendar()[:2] == ref.isocalendar()[:2]


def active_project_rows_for_person(
    ps_rows: list[dict[str, Any]],
    person_name: str,
) -> list[dict[str, Any]]:
    """Active (non-terminal) orders where this display name appears in any role column."""
    # Local import avoids circular import (node3_project_staffing ↔ node4_recommendation).
    from staffing_agent.node3_project_staffing import _roles_hitting_name, _row_status_active

    if not ps_rows or not (person_name or "").strip():
        return []
    out: list[dict[str, Any]] = []
    for r in ps_rows:
        if not _row_status_active(r):
            continue
        if _roles_hitting_name(r, person_name):
            out.append(r)
    return out


def _is_heavy_stage(stage_raw: str, heavy: frozenset[str]) -> bool:
    s = _norm_stage(stage_raw)
    if s in heavy:
        return True
    if "stabilisation" in s or "stabilization" in s:
        return True
    return False


def _is_light_stage(stage_raw: str, cfg: Mapping[str, Any]) -> bool:
    s = _norm_stage(stage_raw)
    if s == "discovery":
        return True
    for p in cfg.get("light_stage_prefixes") or ("scoping",):
        if s.startswith(str(p).lower()) or p.lower() in s:
            return True
    return False


def project_staffing_gate_reason(
    person_rows: list[dict[str, Any]],
    *,
    tier: Optional[int],
    decision_cfg: Mapping[str, Any],
) -> Optional[str]:
    """
    Return None if no extra block; otherwise a machine reason (CSV / Node 4).

    Special: ``ps_scoping_discovery_only`` — still listable with a footnote (scoping/discovery only).
    """
    g = (decision_cfg or {}).get("staffing_ps_gates") or {}
    if not g.get("enabled", True) or not person_rows:
        return None

    blocked_tok = str(g.get("blocked_status") or "BLOCKED_CLIENT")
    heavy_set = frozenset(str(x).lower() for x in (g.get("heavy_stages") or ("building", "stabilisation_delivery")))
    min_heavy = int(g.get("min_heavy_projects_to_block", 3))
    tier_lt = int(g.get("heavy_block_tier_lt", 3))
    tier_n = int(tier) if tier is not None else 0

    only_light_override = g.get("only_light_overrides_all", True)
    if only_light_override and all(_is_light_stage(_stage(r), g) for r in person_rows):
        return None

    if g.get("deadline_this_week_overrides", True):
        today = date.today()
        for r in person_rows:
            dl = _parse_deadline(r.get("deadline"))
            if dl and _in_same_iso_week(dl, today):
                return None

    has_blocked = any(_is_blocked_status(_status(r), blocked_tok) for r in person_rows)
    n_orders = len(person_rows)

    heavy_rows = [r for r in person_rows if _is_heavy_stage(_stage(r), heavy_set)]
    n_heavy = len(heavy_rows)

    # 1) Delivery overload (building / stabilisation) must run *before* the “3 orders + 1 blocked → scoping”
    #    exception — otherwise someone with 3+ stab projects + any blocked row stayed pickable as scoping-only.
    if n_heavy >= min_heavy:
        if tier_n < tier_lt:
            return "ps_three_plus_heavy_low_tier"
        if g.get("block_three_heavy_for_tier_gte_threshold", True):
            return "ps_three_plus_heavy"

    if g.get("block_any_building_non_blocked", True):
        for r in person_rows:
            stg = _norm_stage(_stage(r))
            if stg == "building" and not _is_blocked_status(_status(r), blocked_tok):
                return "ps_active_building"

    # 2) Narrow exception: ≥3 active orders, at least one blocked-by-client, but *not* already excluded above
    #    (e.g. mixed scoping + light load) → still listable with scoping/discovery footnote only.
    if g.get("three_plus_one_blocked_scoping_only", True) and n_orders >= 3 and has_blocked:
        return "ps_scoping_discovery_only"

    return None


def gate_reason_label(reason: str) -> str:
    """Short human label for Slack (internal footnote)."""
    return {
        "ps_scoping_discovery_only": "snapshot: scoping/discovery only (3+ orders incl. blocked)",
        "ps_three_plus_heavy_low_tier": "snapshot: 3+ building/stabilisation orders — hold for Tier < 3",
        "ps_three_plus_heavy": "snapshot: 3+ building/stabilisation orders",
        "ps_active_building": "snapshot: active building (non blocked-by-client)",
    }.get(reason, reason)
