"""
Team capacity: who is free by role (Occupation + People & Tags) and a simplified estimate of
parallel projects by tier.

Assumptions: one row per person in occupation output; for Tier 2 a “project” = 1 SO (SoE/DPM with SO in the table); Tier 1 scoping = one DPM + WFM pair.
"""

from __future__ import annotations

import sys
from typing import Any, Mapping, Optional

from staffing_agent.config_loader import load_decision_config
from staffing_agent.databricks_cli import databricks_profile
from staffing_agent.decision import classify_availability
from staffing_agent.decision.enums import AvailabilityLabel
from staffing_agent.node3_row_utils import email_value, name_value, occupation_value, project_role_norm
from staffing_agent.node3_occupation import (
    MIN_OCCUPATION_SQL_LEN,
    _run_query_json_first,
    _sql_executable_text,
    _try_parse_query_json,
    occupation_sql_path,
)
from staffing_agent.project_staffing_gates import (
    active_project_rows_for_person,
    gate_reason_label,
    project_staffing_gate_reason,
)
from staffing_agent.staffing_csv import (
    StaffingRecord,
    comment_blocks_staffing,
    is_so_or_can_be_so,
    load_staffing_records,
    load_staffing_table_config,
)


def _staffing_stderr(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _classify_label(row: dict[str, Any], decision_cfg: Mapping[str, Any]) -> AvailabilityLabel:
    occ = occupation_value(row)
    if occ is None:
        t = 1.0
    else:
        t = max(0.0, min(1.0, float(occ)))
    apc = 0 if t == 0.0 else 1
    return classify_availability(t, active_project_count=apc, decision_cfg=decision_cfg).label


def _is_freeish(label: AvailabilityLabel) -> bool:
    return label in (
        AvailabilityLabel.FREE,
        AvailabilityLabel.PARTIAL,
    )


def _row_usable(
    row: dict[str, Any],
    staffing: dict[str, StaffingRecord],
    st_cfg: Mapping[str, Any],
) -> bool:
    em = email_value(row)
    rec = staffing.get(em) if em else None
    if rec and comment_blocks_staffing(rec.comment, st_cfg):
        return False
    return True


def _fmt_person(row: dict[str, Any], label: AvailabilityLabel) -> str:
    occ = occupation_value(row)
    pct = f"{float(occ) * 100:.0f}%" if occ is not None else "n/a"
    return f"{name_value(row)} — {pct} → `{label.value}`"


def _dedupe_pairs(pairs: list[tuple[dict[str, Any], AvailabilityLabel]]) -> list[tuple[dict[str, Any], AvailabilityLabel]]:
    seen: set[str] = set()
    out: list[tuple[dict[str, Any], AvailabilityLabel]] = []
    for r, lb in pairs:
        em = email_value(r) or name_value(r)
        if em in seen:
            continue
        seen.add(em)
        out.append((r, lb))
    return out


def _snapshot_gate_outcome(
    ps_rows: list[dict[str, Any]] | None,
    row: dict[str, Any],
    gate_tier: int,
    decision_cfg: Mapping[str, Any],
) -> tuple[bool, str | None]:
    """
    Same staffing snapshot rules as Node 4.

    Returns (eligible_for_main_bullet, reason_code_or_none).
    If eligible and reason is ``ps_scoping_discovery_only``, show footnote; if not eligible, list under *Hold*.
    """
    if not ps_rows:
        return True, None
    sub = active_project_rows_for_person(ps_rows, name_value(row))
    if not sub:
        return True, None
    reason = project_staffing_gate_reason(
        sub,
        tier=gate_tier,
        decision_cfg=decision_cfg,
    )
    if reason is None:
        return True, None
    if reason == "ps_scoping_discovery_only":
        return True, reason
    return False, reason


def build_team_capacity_markdown(
    rows: list[dict[str, Any]],
    *,
    decision_cfg: Optional[Mapping[str, Any]] = None,
    project_staffing_rows: Optional[list[dict[str, Any]]] = None,
) -> str:
    """
    Breakdown SO / SoE / DPM / WFM+WFC and a “how many projects we can take” block.
    """
    cfg = decision_cfg or load_decision_config()
    st_cfg = load_staffing_table_config()
    staffing = load_staffing_records()
    csv_loaded = bool(staffing)

    usable = [r for r in rows if _row_usable(r, staffing, st_cfg)]
    if not usable:
        return (
            "*Team capacity*\n"
            "_No Occupation rows after CSV filter — check `sql/occupation.sql` and People & Tags._"
        )

    # SO = SoE/DPM with SO / can be SO in the table (same as recommendation)
    so_rows: list[tuple[dict[str, Any], AvailabilityLabel]] = []
    soe_rows: list[tuple[dict[str, Any], AvailabilityLabel]] = []
    dpm_rows: list[tuple[dict[str, Any], AvailabilityLabel]] = []
    wfm_rows: list[tuple[dict[str, Any], AvailabilityLabel]] = []
    qm_rows: list[tuple[dict[str, Any], AvailabilityLabel]] = []

    for r in usable:
        pr = project_role_norm(r)
        lb = _classify_label(r, cfg)
        em = email_value(r)
        rec = staffing.get(em) if em else None
        pair = (r, lb)

        if pr == "soe":
            soe_rows.append(pair)
        elif pr == "dpm":
            dpm_rows.append(pair)
        elif pr == "wfm":
            wfm_rows.append(pair)
        elif pr == "qm":
            qm_rows.append(pair)

        if pr in ("soe", "dpm"):
            if not csv_loaded:
                so_rows.append(pair)
            elif rec and is_so_or_can_be_so(rec.so_status):
                so_rows.append(pair)

    def sort_key(it: tuple[dict[str, Any], AvailabilityLabel]) -> float:
        o = occupation_value(it[0])
        return o if o is not None else 1.0

    ps = project_staffing_rows

    def fmt_section(
        title: str,
        pairs: list[tuple[dict[str, Any], AvailabilityLabel]],
        *,
        subtitle: str = "",
        gate_tier: int = 2,
    ) -> list[str]:
        sec: list[str] = [f"*{title}*"]
        if subtitle:
            sec.append(subtitle)
        if ps:
            sec.append(f"_Snapshot gates: `tier={gate_tier}` (aligned with Node 4)._")
        free_pairs = [p for p in pairs if _is_freeish(p[1])]
        free_pairs = sorted(free_pairs, key=sort_key)
        if not free_pairs:
            sec.append("_No one in FREE/PARTIAL in this slice._")
            return sec
        main: list[str] = []
        hold: list[str] = []
        for r, lb in free_pairs[:40]:
            ok, rcode = _snapshot_gate_outcome(ps, r, gate_tier, cfg)
            line = _fmt_person(r, lb)
            if ok:
                if rcode == "ps_scoping_discovery_only":
                    main.append(f"• {line} _({gate_reason_label(rcode)})_")
                else:
                    main.append(f"• {line}")
            else:
                hold.append(f"• {line} — _{gate_reason_label(rcode)}_")
        sec.extend(main)
        if len(free_pairs) > 40:
            sec.append(f"… _{len(free_pairs) - 40} more people_")
        if hold:
            sec.append("_Hold (snapshot — not for full staffing line):_")
            sec.extend(hold[:15])
            if len(hold) > 15:
                sec.append(f"… _{len(hold) - 15} more on hold_")
        return sec

    lines: list[str] = [
        "*Team capacity* _(Occupation + People & Tags; free = FREE or PARTIAL)_",
    ]
    if ps:
        lines.append(
            "_`project_staffing.sql` snapshot loaded — same order-level gates as recommendations "
            "(per-role tier below)._"
        )
    else:
        lines.append(
            "_No project staffing snapshot — order-level gates (building/stab caps, etc.) are not applied here._"
        )
    if not csv_loaded:
        lines.append("_People & Tags CSV not found — SO block is not filtered by SO Status._")

    lines.append("")
    lines.extend(
        fmt_section(
            "SO (SoE/DPM with SO / can be SO in the table)",
            _dedupe_pairs(so_rows),
            subtitle="_Who can be accountable SO per the table._",
            gate_tier=2,
        )
    )
    lines.append("")
    lines.extend(
        fmt_section(
            "SoE / SSoE (`project_role` = soe)",
            _dedupe_pairs(soe_rows),
            gate_tier=3,
        )
    )
    lines.append("")
    lines.extend(
        fmt_section(
            "DPM",
            _dedupe_pairs(dpm_rows),
            gate_tier=1,
        )
    )
    lines.append("")
    lines.extend(
        fmt_section(
            "WFM / WFC (`project_role` = wfm)",
            _dedupe_pairs(wfm_rows),
            gate_tier=1,
        )
    )
    lines.append("")
    lines.extend(
        fmt_section(
            "QM (for Tier 1 scoping/building per Node 2)",
            _dedupe_pairs(qm_rows),
            gate_tier=1,
        )
    )

    # --- slot estimates (FREE only, conservative) — same snapshot gates per tier ---
    def free_and_snapshot_ok(
        r: dict[str, Any],
        lb: AvailabilityLabel,
        gate_tier: int,
    ) -> bool:
        if lb != AvailabilityLabel.FREE:
            return False
        ok, _rcode = _snapshot_gate_outcome(ps, r, gate_tier, cfg)
        return ok

    d_pairs = _dedupe_pairs(dpm_rows)
    w_pairs = _dedupe_pairs(wfm_rows)
    q_pairs = _dedupe_pairs(qm_rows)
    so_pairs = _dedupe_pairs(so_rows)
    soe_pairs = _dedupe_pairs(soe_rows)

    dpm_f = sum(1 for r, lb in d_pairs if free_and_snapshot_ok(r, lb, 1))
    wfm_t1 = sum(1 for r, lb in w_pairs if free_and_snapshot_ok(r, lb, 1))
    wfm_t3 = sum(1 for r, lb in w_pairs if free_and_snapshot_ok(r, lb, 3))
    qm_f = sum(1 for r, lb in q_pairs if free_and_snapshot_ok(r, lb, 1))
    so_free = sum(1 for r, lb in so_pairs if free_and_snapshot_ok(r, lb, 2))
    soe_f = sum(1 for r, lb in soe_pairs if free_and_snapshot_ok(r, lb, 3))
    dpm_t4 = sum(1 for r, lb in d_pairs if free_and_snapshot_ok(r, lb, 4))
    soe_t4 = sum(1 for r, lb in soe_pairs if free_and_snapshot_ok(r, lb, 4))
    wfm_t4 = sum(1 for r, lb in w_pairs if free_and_snapshot_ok(r, lb, 4))

    t1_scoping = min(dpm_f, wfm_t1)
    t1_full = min(dpm_f, wfm_t1, qm_f) if qm_f > 0 else min(dpm_f, wfm_t1)
    t2_slots = so_free
    t3_slots = min(soe_f, wfm_t3)
    t4_slots = (
        min(dpm_t4, soe_t4, wfm_t4)
        if dpm_t4 and soe_t4 and wfm_t4
        else min(so_free, wfm_t1)
    )

    lines.append("")
    lines.append("*How many projects we can take now (estimate, FREE only)*")
    lines.append(
        "_Simplification: Tier 2 = 1 SO per project; Tier 1 scoping = need DPM and WFM at the same time; "
        "Tier 3+ — no domain match in this model; Tier 4 — no Commercial in Occupation — lower bound._"
    )
    if ps:
        lines.append(
            "_Slot counts use the same snapshot gate tier as recommendations (Tier 1 roles → tier 1; "
            "SO → tier 2; SoE / WFM for Tier 3 pair → tier 3; Tier 4 row → tier 4)._"
        )
    lines.append(f"• *Tier 1 — scoping* (DPM + WFM): up to **{t1_scoping}** parallel tracks.")
    lines.append(
        f"• *Tier 1 — full loop* (+ QM in Node 2): up to **{t1_full}** when QM is in FREE."
    )
    lines.append(
        f"• *Tier 2 — full project* (1 SO SoE/DPM with SO in the table): up to **{t2_slots}** parallel projects."
    )
    lines.append(
        f"• *Tier 3* (SoE + WFM, no domain): up to **{t3_slots}** SoE+WFM pairs in FREE."
    )
    lines.append(
        f"• *Tier 4* (conservative, no Commercial): **≤ {t4_slots}** — confirm manually with Commercial."
    )

    return "\n".join(lines)


def fetch_occupation_rows(timeout_sec: int = 300) -> tuple[bool, list[dict[str, Any]], str]:
    """Load JSON rows from Databricks occupation.sql."""
    if not databricks_profile():
        return False, [], "no_profile"
    path = occupation_sql_path()
    sql_text = _sql_executable_text(path)
    if len(sql_text) < MIN_OCCUPATION_SQL_LEN:
        return False, [], "no_sql"
    _staffing_stderr("[staffing] Team capacity: running sql/occupation.sql …")
    ok, out = _run_query_json_first(sql_text, timeout_sec=timeout_sec)
    if not ok:
        return False, [], out[:2000]
    rows = _try_parse_query_json(out) or []
    return True, rows, ""


def build_team_capacity_slack_reply(messages: list[dict[str, Any]]) -> str:
    """Full Slack message for team-capacity intent."""
    from staffing_agent.node3_project_staffing import fetch_project_staffing_rows

    ok, rows, err = fetch_occupation_rows()
    header = ""
    if not ok:
        if err == "no_profile":
            body = "*Team capacity*\n_Set `DATABRICKS_PROFILE` and place the query in `sql/occupation.sql`._"
        elif err == "no_sql":
            body = "*Team capacity*\n_`sql/occupation.sql` is empty or too short._"
        else:
            body = f"*Team capacity*\n_Occupation query failed:_\n```{err[:1200]}```"
        return header + body

    cfg = load_decision_config()
    ps_rows = fetch_project_staffing_rows(timeout_sec=180)
    body = build_team_capacity_markdown(rows, decision_cfg=cfg, project_staffing_rows=ps_rows or None)
    return header + body
