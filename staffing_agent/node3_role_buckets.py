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
            "*По ролям — кандидаты под Node 2 (Tier 2)*",
            "_Только *SO* (SoE или DPM). WFM/QM в минимальный состав Tier 2 не входят — блок WFM не показываем._",
        ]
    else:
        lines = [
            "*По ролям — кого смотреть первым (по загрузке из Node 3)*",
            "_SO в спеке = SoE или DPM; ниже — ведра по `project_role` из SQL._",
        ]

    so_pool = _take_bucket(rows, is_so_pool, decision_cfg=decision_cfg, max_n=max_per_bucket)
    lines.append("*SO (пул SoE + DPM, самые свободные):*")
    if so_pool:
        for r in so_pool:
            lines.append(_line_for_row(r, decision_cfg=decision_cfg))
    else:
        lines.append("_нет SoE/DPM в выборке_")

    soe = _take_bucket(rows, is_soe, decision_cfg=decision_cfg, max_n=max_per_bucket)
    lines.append("*SOE / SSoE:*")
    if soe:
        for r in soe:
            lines.append(_line_for_row(r, decision_cfg=decision_cfg))
    else:
        lines.append("_нет_")

    dpm = _take_bucket(rows, is_dpm, decision_cfg=decision_cfg, max_n=max_per_bucket)
    lines.append("*DPM:*")
    if dpm:
        for r in dpm:
            lines.append(_line_for_row(r, decision_cfg=decision_cfg))
    else:
        lines.append("_нет_")

    if not hide_wfm:
        wfm = _take_bucket(rows, is_wfm, decision_cfg=decision_cfg, max_n=max_per_bucket)
        lines.append("*WFM / WFC:*")
        if wfm:
            for r in wfm:
                lines.append(_line_for_row(r, decision_cfg=decision_cfg))
        else:
            lines.append("_нет_")

    return "\n".join(lines)


def format_role_bucket_fallback(reason: str, *, tier: Optional[int] = None) -> str:
    """When SQL недоступен — шаблон + причина."""
    hide_wfm = tier == 2
    head = (
        "*По ролям — кандидаты под Node 2 (Tier 2)*\n"
        if hide_wfm
        else "*По ролям — кого смотреть (нужны данные Databricks)*\n"
    )
    wfm_line = (
        ""
        if hide_wfm
        else "*WFM / WFC:* _—_\n"
    )
    wfm_note = (
        "_WFM не входят в минимальный состав Tier 2 — блок не показывается._\n"
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
        "_После успешного `sql/occupation.sql` здесь появятся люди по `project_role`._"
    )
