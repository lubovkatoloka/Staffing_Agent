"""
Group Capacity snapshot rows into SO / SOE·SSoE / DPM / WFM buckets for Slack (Capacity v2).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from staffing_agent.capacity_runtime import format_capacity_projects_line
from staffing_agent.decision import CapacityVerdict
from staffing_agent.decision.enums import Band
from staffing_agent.node3_row_utils import name_value, project_role_norm


def _get_ci(row: dict[str, Any], *candidates: str) -> Any:
    lower_map = {k.lower(): v for k, v in row.items()}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    return None


def _user_role_norm(row: dict[str, Any]) -> str:
    v = _get_ci(row, "user_role", "rolename", "USER_ROLE")
    return (str(v) if v is not None else "").strip().lower()


def _verdict(row: dict[str, Any]) -> CapacityVerdict:
    v = row.get("_capacity_verdict")
    if not isinstance(v, CapacityVerdict):
        raise ValueError("Row missing `_capacity_verdict` — prepare snapshot rows first.")
    return v


def _row_label(row: dict[str, Any]) -> str:
    return _verdict(row).band.value


def _line_for_row(row: dict[str, Any]) -> str:
    name = name_value(row)
    verdict = _verdict(row)
    label = verdict.band.value
    cu = verdict.capacity_used
    soft = ""
    if verdict.is_soft and verdict.soft_reasons:
        soft = " `[SOFT: " + ", ".join(s.value for s in verdict.soft_reasons) + "]`"
    projs = format_capacity_projects_line(tuple(row.get("_capacity_rows") or ()))
    return f"• {name} — capacity *{cu:.2f}* → `{label}`{soft} — _{projs}_"


def _take_bucket(
    rows: list[dict[str, Any]],
    pred,
    *,
    max_n: int,
) -> list[dict[str, Any]]:
    cand = [r for r in rows if pred(r)]
    cand.sort(key=lambda r: float(_verdict(r).capacity_used))
    non_busy = [r for r in cand if _verdict(r).band != Band.AT_CAP]
    use = non_busy if non_busy else cand
    return use[:max_n]


def format_role_bucket_section(
    rows: list[dict[str, Any]],
    *,
    decision_cfg: Mapping[str, Any],
    max_per_bucket: int = 6,
    tier: Optional[int] = None,
) -> str:
    """
    Slack block: SO / SOE·SSoE / DPM / WFM/WFC with freest people per bucket.

    For Tier 2 (Node 2), only SO-relevant buckets are shown — WFM is omitted (not in minimum team).
    """
    _ = decision_cfg
    if not rows:
        return ""

    hide_wfm = tier == 2

    def is_soe(r: dict[str, Any]) -> bool:
        return project_role_norm(r) == "soe"

    def is_dpm(r: dict[str, Any]) -> bool:
        return project_role_norm(r) == "dpm"

    def is_wfm(r: dict[str, Any]) -> bool:
        pr = project_role_norm(r)
        ur = _user_role_norm(r)
        return pr == "wfm" or "workforce" in ur

    def is_so_pool(r: dict[str, Any]) -> bool:
        return is_soe(r) or is_dpm(r)

    if hide_wfm:
        lines: list[str] = [
            "*By role — candidates for Node 2 (Tier 2)*",
            "_Only *SO* (SoE or DPM). WFM/QM are not in the Tier 2 minimum team — WFM block hidden._",
        ]
    else:
        lines = [
            "*By role — who to look at first (from Capacity snapshot)*",
            "_SO in spec = SoE or DPM; buckets use `project_role` / `role_group` from SQL._",
        ]

    so_pool = _take_bucket(rows, is_so_pool, max_n=max_per_bucket)
    lines.append("*SO (SoE + DPM pool, lowest capacity first):*")
    if so_pool:
        for r in so_pool:
            lines.append(_line_for_row(r))
    else:
        lines.append("_no SoE/DPM in sample_")

    soe = _take_bucket(rows, is_soe, max_n=max_per_bucket)
    lines.append("*SOE / SSoE:*")
    if soe:
        for r in soe:
            lines.append(_line_for_row(r))
    else:
        lines.append("_none_")

    dpm = _take_bucket(rows, is_dpm, max_n=max_per_bucket)
    lines.append("*DPM:*")
    if dpm:
        for r in dpm:
            lines.append(_line_for_row(r))
    else:
        lines.append("_none_")

    if not hide_wfm:
        wfm = _take_bucket(rows, is_wfm, max_n=max_per_bucket)
        lines.append("*WFM / WFC:*")
        if wfm:
            for r in wfm:
                lines.append(_line_for_row(r))
        else:
            lines.append("_none_")

    fb = float((decision_cfg.get("availability_bands") or {}).get("free_below", 1.0))
    pb = float((decision_cfg.get("availability_bands") or {}).get("partial_below", 2.0))
    lines.append(
        f"_Bands (capacity units): FREE below {fb:.2f}, PARTIAL below {pb:.2f}, else AT_CAP (`config/decision_logic.yaml`)._"
    )
    return "\n".join(lines)


def format_role_bucket_fallback(reason: str, *, tier: Optional[int] = None) -> str:
    """When SQL is unavailable — template + reason."""
    hide_wfm = tier == 2
    head = (
        "*By role — candidates for Node 2 (Tier 2)*\n"
        if hide_wfm
        else "*By role — who to look at (Databricks data needed)*\n"
    )
    wfm_line = (
        ""
        if hide_wfm
        else "*WFM / WFC:* _—_\n"
    )
    wfm_note = (
        "_WFM are not in the Tier 2 minimum team — block omitted._\n"
        if hide_wfm
        else ""
    )
    return (
        f"{head}"
        f"_{reason}_\n"
        "*SO (SoE + DPM):* _—_\n"
        "*SOE / SSoE:* _—_\n"
        "*DPM:* _—_\n"
        f"{wfm_line}"
        f"{wfm_note}"
        "_After a successful `sql/capacity.sql`, people appear here by staffing role._"
    )

