"""
Team capacity: who is free by role (Capacity v2 + People & Tags) and a simplified estimate of
parallel projects by tier.

Assumes prepared rows (one per person) with `_capacity_verdict` from `prepare_rows_for_recommendation`.
"""

from __future__ import annotations

import sys
from typing import Any, Mapping, Optional

from staffing_agent.capacity_runtime import prepare_rows_for_recommendation
from staffing_agent.config_loader import load_decision_config
from staffing_agent.databricks_cli import databricks_profile
from staffing_agent.decision import CapacityVerdict
from staffing_agent.decision.enums import Band
from staffing_agent.node3_occupation import (
    MIN_CAPACITY_SQL_LEN,
    _run_query_json_first,
    _sql_executable_text,
    _try_parse_query_json,
    capacity_sql_path,
)
from staffing_agent.node3_row_utils import email_value, name_value, project_role_norm
from staffing_agent.project_staffing_gates import (
    active_project_rows_for_person,
    gate_reason_label,
    project_staffing_gate_reason,
)
from staffing_agent.exclusions import (
    ExclusionUnavailableError,
    format_excluded_comment_block,
    get_exclusion_store,
    slack_exclusion_unavailable_message,
)
from staffing_agent.staffing_csv import (
    StaffingRecord,
    is_so_or_can_be_so,
    load_staffing_records,
)


def _staffing_stderr(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _team_capacity_required_roles(only_role: Optional[str]) -> frozenset[str]:
    orl = (only_role or "").strip().lower()
    if orl == "so":
        return frozenset({"soe", "dpm"})
    if orl in ("soe", "dpm", "wfm", "qm", "se"):
        return frozenset({orl})
    return frozenset({"soe", "dpm", "wfm", "qm", "se"})


def _verdict(row: dict[str, Any]) -> CapacityVerdict:
    v = row.get("_capacity_verdict")
    if not isinstance(v, CapacityVerdict):
        raise ValueError("expected `_capacity_verdict` on row — run prepare_rows_for_recommendation")
    return v


def _classify_label(row: dict[str, Any]) -> Band:
    return _verdict(row).band


def _row_is_freeish(row: dict[str, Any]) -> bool:
    v = _verdict(row)
    if v.on_pto_today:
        return False
    return v.band in (Band.FREE, Band.PARTIAL)


def _row_usable(
    row: dict[str, Any],
    staffing: dict[str, StaffingRecord],
    excluded_emails: frozenset[str],
) -> bool:
    em = (email_value(row) or "").strip().lower()
    if em and em in excluded_emails:
        return False
    return True


def _fmt_person(row: dict[str, Any], band: Band) -> str:
    v = _verdict(row)
    cu = v.capacity_used
    pto_marker = ""
    up = v.pto_upcoming_dates
    if up is not None:
        pto_marker = f" ⚠️ PTO {up[0]}"
    return f"{name_value(row)} — capacity *{cu:.2f}* → `{band.value}`{pto_marker}"


def _dedupe_pairs(pairs: list[tuple[dict[str, Any], Band]]) -> list[tuple[dict[str, Any], Band]]:
    seen: set[str] = set()
    out: list[tuple[dict[str, Any], Band]] = []
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


def _bullets_primary_alternates(bullets: list[str], *, max_alternates: int = 3) -> list[str]:
    if not bullets:
        return []
    out: list[str] = []
    for i, b in enumerate(bullets):
        raw = b.strip()
        body = raw[1:].strip() if raw.startswith("•") else raw
        if i == 0:
            out.append(f"• *Primary:* {body}")
        elif i <= max_alternates:
            out.append(f"• *Alternate:* {body}")
        else:
            out.append(f"• {body}")
    return out


def build_team_capacity_markdown(
    rows: list[dict[str, Any]],
    *,
    decision_cfg: Optional[Mapping[str, Any]] = None,
    project_staffing_rows: Optional[list[dict[str, Any]]] = None,
    only_role: Optional[str] = None,
) -> str:
    """
    Breakdown SO / SoE / DPM / WFM+WFC and a “how many projects we can take” block.

    ``only_role`` — if set to ``so``/``soe``/``dpm``/``wfm``/``qm``, return only that slice (primary + alternates).
    """
    cfg = decision_cfg or load_decision_config()
    staffing = load_staffing_records()
    csv_loaded = bool(staffing)

    try:
        exr = get_exclusion_store().get()
    except ExclusionUnavailableError:
        return slack_exclusion_unavailable_message(title="Team capacity")

    npw = 0.0
    prepared = prepare_rows_for_recommendation(
        rows,
        decision_cfg=cfg,
        new_project_weight=npw,
        staffing=staffing,
        excluded_emails=exr.excluded_emails,
    )

    usable = [r for r in prepared if _row_usable(r, staffing, exr.excluded_emails)]
    if not usable:
        return (
            "*Team capacity*\n"
            "_No Capacity rows after CSV filter — check `sql/capacity.sql` and People & Tags._"
        )

    so_rows: list[tuple[dict[str, Any], Band]] = []
    soe_rows: list[tuple[dict[str, Any], Band]] = []
    dpm_rows: list[tuple[dict[str, Any], Band]] = []
    wfm_rows: list[tuple[dict[str, Any], Band]] = []
    qm_rows: list[tuple[dict[str, Any], Band]] = []

    for r in usable:
        pr = project_role_norm(r)
        lb = _classify_label(r)
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

    def sort_key(it: tuple[dict[str, Any], Band]) -> float:
        return float(_verdict(it[0]).capacity_used)

    ps = project_staffing_rows

    def fmt_section(
        title: str,
        pairs: list[tuple[dict[str, Any], Band]],
        *,
        subtitle: str = "",
        gate_tier: int = 2,
        max_alternates: int = 3,
    ) -> list[str]:
        sec: list[str] = [f"*{title}*"]
        if subtitle:
            sec.append(subtitle)
        if ps:
            sec.append(f"_Snapshot gates: `tier={gate_tier}` (aligned with Node 4)._")
        free_pairs = [p for p in pairs if _row_is_freeish(p[0])]
        free_pairs = sorted(free_pairs, key=sort_key)
        on_pto_count = sum(1 for r, _lb in pairs if _verdict(r).on_pto_today)
        if on_pto_count:
            sec[0] = sec[0] + f" _([PTO today: {on_pto_count}])_"
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
        sec.extend(_bullets_primary_alternates(main, max_alternates=max_alternates))
        if len(free_pairs) > 40:
            sec.append(f"… _{len(free_pairs) - 40} more people_")
        if hold:
            sec.append("_Hold (snapshot — not for full staffing line):_")
            sec.extend(hold[:15])
            if len(hold) > 15:
                sec.append(f"… _{len(hold) - 15} more on hold_")
        return sec

    orl = (only_role or "").strip().lower()
    if orl in ("so", "soe", "dpm", "wfm", "qm"):
        role_map: dict[str, tuple[list[tuple[dict[str, Any], Band]], int, str, str]] = {
            "so": (
                _dedupe_pairs(so_rows),
                2,
                "SO (SoE/DPM with SO / can be SO in the table)",
                "_Accountable SO pool._",
            ),
            "soe": (
                _dedupe_pairs(soe_rows),
                3,
                "SoE / SSoE (`project_role` = soe)",
                "_SoE-shaped staffing ask._",
            ),
            "dpm": (_dedupe_pairs(dpm_rows), 1, "DPM", "_DPM-only snapshot._"),
            "wfm": (
                _dedupe_pairs(wfm_rows),
                1,
                "WFM / WFC (`project_role` = wfm)",
                "_WFM-only snapshot._",
            ),
            "qm": (_dedupe_pairs(qm_rows), 1, "QM (for Tier 1 scoping/building per Node 2)", "_QM-only snapshot._"),
        }
        pairs, gt, title, sub = role_map[orl]
        intro = [
            "*Staffing — role shortlist*",
            "_Narrow ask (no project tier in Phase B). For a full team layout, add tier + scope or ask for *team capacity*._",
            "",
        ]
        body_lines = intro + fmt_section(title, pairs, subtitle=sub, gate_tier=gt, max_alternates=5)
        foot = format_excluded_comment_block(exr, _team_capacity_required_roles(only_role))
        if foot:
            body_lines.append("")
            body_lines.append(foot)
        return "\n".join(body_lines)

    lines: list[str] = [
        "*Team capacity* _(Capacity v2 + People & Tags; free = FREE or PARTIAL)_",
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

    def free_and_snapshot_ok(
        r: dict[str, Any],
        band: Band,
        gate_tier: int,
    ) -> bool:
        if band != Band.FREE:
            return False
        if _verdict(r).on_pto_today:
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
    lines.append("*How many projects we can take now (estimate, FREE band only)*")
    lines.append(
        "_Simplification: Tier 2 = 1 SO per project; Tier 1 scoping = need DPM and WFM at the same time; "
        "Tier 3+ — no domain match in this model; Tier 4 — no Commercial in Capacity — lower bound._"
    )
    if ps:
        lines.append(
            "_Slot counts use the same snapshot gate tier as recommendations (Tier 1 roles → tier 1; "
            "SO → tier 2; SoE / WFM for Tier 3 pair → tier 3; Tier 4 row → tier 4)._"
        )
    lines.append(f"• *Tier 1 — scoping* (DPM + WFM): up to *{t1_scoping}* parallel tracks.")
    lines.append(
        f"• *Tier 1 — full loop* (+ QM in Node 2): up to *{t1_full}* when QM is in FREE."
    )
    lines.append(
        f"• *Tier 2 — full project* (1 SO SoE/DPM with SO in the table): up to *{t2_slots}* parallel projects."
    )
    lines.append(
        f"• *Tier 3* (SoE + WFM, no domain): up to *{t3_slots}* SoE+WFM pairs in FREE."
    )
    lines.append(
        f"• *Tier 4* (conservative, no Commercial): ≤ {t4_slots} — confirm manually with Commercial."
    )

    foot = format_excluded_comment_block(exr, _team_capacity_required_roles(only_role))
    if foot:
        lines.append("")
        lines.append(foot)

    return "\n".join(lines)


def fetch_capacity_rows(timeout_sec: int = 300) -> tuple[bool, list[dict[str, Any]], str]:
    """Load JSON rows from Databricks capacity.sql."""
    if not databricks_profile():
        return False, [], "no_profile"
    path = capacity_sql_path()
    sql_text = _sql_executable_text(path)
    if len(sql_text) < MIN_CAPACITY_SQL_LEN:
        return False, [], "no_sql"
    _staffing_stderr("[staffing] Team capacity: running sql/capacity.sql …")
    ok, out = _run_query_json_first(sql_text, timeout_sec=timeout_sec)
    if not ok:
        return False, [], out[:2000]
    rows = _try_parse_query_json(out) or []
    return True, rows, ""


def build_live_capacity_markdown(
    *,
    only_role: Optional[str] = None,
    timeout_sec: int = 300,
) -> str:
    """Fetch Capacity + optional project_staffing, return capacity or single-role markdown."""
    from staffing_agent.node3_project_staffing import fetch_project_staffing_rows

    ok, rows, err = fetch_capacity_rows(timeout_sec=timeout_sec)
    if not ok:
        if err == "no_profile":
            return "*Team capacity*\n_Set `DATABRICKS_PROFILE` and place the query in `sql/capacity.sql`._"
        if err == "no_sql":
            return "*Team capacity*\n_`sql/capacity.sql` is empty or too short._"
        return f"*Team capacity*\n_Capacity query failed:_\n```{err[:1200]}```"

    cfg = load_decision_config()
    ps_rows = fetch_project_staffing_rows(timeout_sec=min(timeout_sec, 180))
    return build_team_capacity_markdown(
        rows,
        decision_cfg=cfg,
        project_staffing_rows=ps_rows or None,
        only_role=only_role,
    )


def build_team_capacity_slack_reply(messages: list[dict[str, Any]], *, only_role: Optional[str] = None) -> str:
    """Full Slack message for team-capacity intent (``messages`` reserved for future context)."""
    _ = messages
    return build_live_capacity_markdown(only_role=only_role)

