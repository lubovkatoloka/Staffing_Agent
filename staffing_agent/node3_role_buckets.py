"""
Group occupation rows into SO / SOE·SSoE / DPM / WFM buckets for Slack (Decision Logic–aligned labels).

Uses `project_role` from occupation SQL (dpm, soe, wfm, …) and `user_role` when present.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from staffing_agent.decision import classify_availability
from staffing_agent.node3_row_utils import name_value, occupation_value, project_role_norm


def _get_ci(row: dict[str, Any], *candidates: str) -> Any:
    lower_map = {k.lower(): v for k, v in row.items()}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    return None


def _user_role_norm(row: dict[str, Any]) -> str:
    v = _get_ci(row, "user_role", "rolename", "USER_ROLE")
    return (str(v) if v is not None else "").strip().lower()


def _row_label(
    row: dict[str, Any],
    *,
    decision_cfg: Mapping[str, Any],
) -> str:
    occ = occupation_value(row)
    if occ is None:
        return "?"
    t = max(0.0, min(1.0, float(occ)))
    apc = 0 if t == 0.0 else 1
    av = classify_availability(t, active_project_count=apc, decision_cfg=decision_cfg)
    return av.label.value


def _line_for_row(
    row: dict[str, Any],
    *,
    decision_cfg: Mapping[str, Any],
) -> str:
    name = name_value(row)
    label = _row_label(row, decision_cfg=decision_cfg)
    occ = occupation_value(row)
    pct = f"{occ * 100:.0f}%" if occ is not None else "n/a"
    return f"• {name} — load {pct} → `{label}`"


def _take_bucket(
    rows: list[dict[str, Any]],
    pred,
    *,
    decision_cfg: Mapping[str, Any],
    max_n: int,
) -> list[dict[str, Any]]:
    cand = [r for r in rows if pred(r)]
    cand.sort(key=lambda r: occupation_value(r) if occupation_value(r) is not None else 1.0)
    non_busy = [r for r in cand if _row_label(r, decision_cfg=decision_cfg) != "BUSY"]
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
            "*By role — who to look at first (from Node 3 load)*",
            "_SO in spec = SoE or DPM; below — buckets by `project_role` from SQL._",
        ]

    so_pool = _take_bucket(rows, is_so_pool, decision_cfg=decision_cfg, max_n=max_per_bucket)
    lines.append("*SO (SoE + DPM pool, freest first):*")
    if so_pool:
        for r in so_pool:
            lines.append(_line_for_row(r, decision_cfg=decision_cfg))
    else:
        lines.append("_no SoE/DPM in sample_")

    soe = _take_bucket(rows, is_soe, decision_cfg=decision_cfg, max_n=max_per_bucket)
    lines.append("*SOE / SSoE:*")
    if soe:
        for r in soe:
            lines.append(_line_for_row(r, decision_cfg=decision_cfg))
    else:
        lines.append("_none_")

    dpm = _take_bucket(rows, is_dpm, decision_cfg=decision_cfg, max_n=max_per_bucket)
    lines.append("*DPM:*")
    if dpm:
        for r in dpm:
            lines.append(_line_for_row(r, decision_cfg=decision_cfg))
    else:
        lines.append("_none_")

    if not hide_wfm:
        wfm = _take_bucket(rows, is_wfm, decision_cfg=decision_cfg, max_n=max_per_bucket)
        lines.append("*WFM / WFC:*")
        if wfm:
            for r in wfm:
                lines.append(_line_for_row(r, decision_cfg=decision_cfg))
        else:
            lines.append("_none_")

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
        "_After a successful `sql/occupation.sql`, people appear here by `project_role`._"
    )
