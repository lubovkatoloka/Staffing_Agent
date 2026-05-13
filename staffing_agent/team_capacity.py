"""
Team capacity: who is free by role (Capacity v2 + People & Tags) and possible team allocations.

Assumes prepared rows (one per person) with `_capacity_verdict` from `prepare_rows_for_recommendation`.
"""

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
import sys
from typing import Any, Callable, Mapping, Optional

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
    project_roles_for_notion_tag,
    slack_exclusion_unavailable_message,
)
from staffing_agent.format_utils import (
    band_label_for_slack,
    compress_slash,
    project_status_word,
    risk_breakdown_summary,
    truncate_at_word_boundary,
    truncate_overcap_projects,
)
from staffing_agent.hibob import fetch_start_dates
from staffing_agent.staffing_csv import (
    StaffingRecord,
    is_so,
    is_so_eligible_for_tier,
    load_staffing_records,
)

_SHOW_LOAD = os.environ.get("STAFFING_AGENT_SHOW_LOAD", "").strip().lower() in (
    "1",
    "true",
    "yes",
)

# Slack mrkdwn (bold). Socket handler also caps each post at ~12k unless overridden.
TEAM_CAPACITY_TITLE_OVERVIEW_MRKDWN = "*TEAM CAPACITY — OVERVIEW*"
TEAM_CAPACITY_TITLE_BY_ROLE_MRKDWN = "*TEAM CAPACITY — BY ROLE*"


def _team_capacity_detail_chunk_chars() -> int:
    raw = (os.environ.get("STAFFING_TEAM_CAPACITY_CHUNK_CHARS") or "").strip()
    if raw.isdigit():
        # Floor keeps tests (small limits) and pathological tiny chunks out of prod defaults.
        return max(400, min(int(raw), 39_000))
    return 11_000


def _split_detail_block_lines(block: str, max_chars: int) -> list[str]:
    """Split one markdown block on lines so each piece is at most ``max_chars``."""
    if max_chars < 80:
        max_chars = 80
    lines = block.split("\n")
    expanded: list[str] = []
    for line in lines:
        if len(line) <= max_chars:
            expanded.append(line)
        else:
            for i in range(0, len(line), max_chars):
                expanded.append(line[i : i + max_chars])

    out: list[str] = []
    buf: list[str] = []
    n = 0
    for line in expanded:
        add = len(line) + (1 if buf else 0)
        if n + add > max_chars and buf:
            out.append("\n".join(buf))
            buf = [line]
            n = len(line)
        else:
            buf.append(line)
            n += add
    if buf:
        out.append("\n".join(buf))
    return out if out else [block[:max_chars]]


def _pack_team_capacity_detail_chunks(section_blocks: list[str], *, max_chars: int) -> list[str]:
    """Pack role/onboarding sections into 1..N Slack messages under the BY ROLE title."""
    inner_limit = max(200, max_chars - 100)
    pieces: list[str] = []
    for b in section_blocks:
        if not (b or "").strip():
            continue
        pieces.extend(_split_detail_block_lines(b.strip(), inner_limit))

    cont = "_… continued below._"
    if not pieces:
        return [TEAM_CAPACITY_TITLE_BY_ROLE_MRKDWN]

    out: list[str] = []
    cur = f"{TEAM_CAPACITY_TITLE_BY_ROLE_MRKDWN}\n\n{pieces[0]}"
    for p in pieces[1:]:
        addition = "\n\n" + p
        if len(cur) + len(addition) <= max_chars:
            cur += addition
        else:
            out.append(cur)
            cur = f"{cont}\n\n{p}"
    out.append(cur)
    return out


@dataclass(frozen=True)
class TeamCapacityState:
    """Team-capacity render: Message 1 overview + one or more Message-2 detail chunks + name sets."""

    messages: list[str]
    names_in_message1: frozenset[str]
    names_in_message2: frozenset[str]


_STG_SHORT: dict[str, str] = {
    "building": "build",
    "stabilisation_delivery": "stab",
    "scoping_solution_design": "scoping",
    "discovery": "disc",
    "close_out_retrospective": "close-out",
}


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


def _stage_short(raw: str) -> str:
    key = (raw or "").strip().lower().replace(" ", "_")
    return _STG_SHORT.get(key, key.replace("_", "-")[:12])


def _truncate_name(name: str, max_len: int = 30) -> str:
    return truncate_at_word_boundary(name or "?", max_len)


def _risk_and_pto_headline(row: dict[str, Any]) -> str:
    warnings: list[str] = []
    v = _verdict(row)
    crs = tuple(row.get("_capacity_rows") or ())
    for cr in crs:
        stat_word = project_status_word(cr.status or "")
        if stat_word:
            warnings.append(f"{stat_word} {_stage_short(cr.stage or '')}")
            break
    if v.pto_upcoming_dates is not None:
        warnings.append(f"PTO {v.pto_upcoming_dates[0]}")
    return (" " + " ".join(warnings)) if warnings else ""


def _projects_detail_line(row: dict[str, Any]) -> str:
    crs = tuple(row.get("_capacity_rows") or ())
    n = len(crs)
    if n == 0:
        return "└ 0 active"
    parts: list[str] = []
    for cr in crs[:12]:
        pname = _truncate_name(cr.project_name or cr.project_id or "?", 48)
        tier_bit = (cr.tier or "").replace("Tier ", "T").strip() or "T?"
        st = _stage_short(cr.stage or "")
        stat_word = project_status_word(cr.status or "")
        stat_seg = f", {stat_word}" if stat_word else ""
        parts.append(f"{pname} ({tier_bit} {st}{stat_seg})")
    tail = "; ".join(parts)
    if n > 12:
        tail += "; _…+{0} more_".format(n - 12)
    return f"└ {n} active: {tail}"


def _two_line_entry(row: dict[str, Any], band: Band) -> tuple[str, str]:
    nm = name_value(row)
    v = _verdict(row)
    bl = band_label_for_slack(band)
    head = f"{nm} — `{bl}`{_risk_and_pto_headline(row)}"
    if _SHOW_LOAD:
        head += f" _[load: {v.capacity_used:.2f}]_"
    return head, _projects_detail_line(row)


def _active_project_count(row: dict[str, Any]) -> int:
    return len(row.get("_capacity_rows") or ())


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


_POOL_GATE_TIER: dict[str, int] = {
    "so": 2,
    "soe": 3,
    "dpm": 1,
    "wfm": 1,
    "qm": 1,
    "se": 4,
}

_POOL_DISPLAY: list[tuple[str, str]] = [
    ("so", "SO"),
    ("soe", "SoE"),
    ("dpm", "DPM"),
    ("wfm", "WFM"),
    ("qm", "QM"),
    ("se", "SE"),
]

_ROLE_SLUG_DISPLAY: dict[str, str] = {
    "so": "SO",
    "soe": "SoE",
    "dpm": "DPM",
    "wfm": "WFM",
    "qm": "QM",
    "se": "SE",
}


def _bottleneck_labels_for_role(
    key: str,
    *,
    n_t1s: int,
    n_t1f: int,
    n_t2: int,
    n_t3: int,
    n_t4: int,
) -> list[str]:
    z1s = n_t1s == 0
    z1f = n_t1f == 0
    z2 = n_t2 == 0
    z3 = n_t3 == 0
    z4 = n_t4 == 0
    out: list[str] = []
    if key == "so":
        if z2:
            out.append("T2")
        if z3:
            out.append("T3")
        if z4:
            out.append("T4")
    elif key == "soe":
        if z3:
            out.append("T3")
        if z4:
            out.append("T4")
    elif key == "dpm":
        if z1s or z1f:
            out.append("T1")
    elif key == "wfm":
        if z1s or z1f:
            out.append("T1")
        if z3:
            out.append("T3")
        if z4:
            out.append("T4")
    elif key == "qm":
        if z1f:
            out.append("T1 full")
    elif key == "se":
        if z4:
            out.append("T4")
    return list(dict.fromkeys(out))


def _fmt_bottleneck_arrow_suffix(labels: list[str]) -> str:
    if not labels:
        return ""
    pure = [x for x in labels if len(x) == 2 and x.startswith("T") and x[1].isdigit()]
    special = [x for x in labels if x not in pure]
    parts: list[str] = []
    if pure:
        parts.append(compress_slash(pure))
    parts.extend(special)
    return "/".join(parts)


def _non_hold_freeish_pool_pairs(
    pairs: list[tuple[dict[str, Any], Band]],
    gate_tier: int,
    ps_rows: list[dict[str, Any]] | None,
    cfg: Mapping[str, Any],
) -> list[tuple[dict[str, Any], Band]]:
    """FREE/PARTIAL people in the staffing line (excludes Hold / failed snapshot gate)."""
    out: list[tuple[dict[str, Any], Band]] = []
    for r, lb in pairs:
        if not _row_is_freeish(r):
            continue
        ok, rcode = _snapshot_gate_outcome(ps_rows, r, gate_tier, cfg)
        if not ok and rcode != "ps_scoping_discovery_only":
            continue
        out.append((r, lb))
    return out


def _pool_free_partial_counts(
    pairs: list[tuple[dict[str, Any], Band]],
    gate_tier: int,
    ps_rows: list[dict[str, Any]] | None,
    cfg: Mapping[str, Any],
) -> tuple[int, int]:
    nh = _non_hold_freeish_pool_pairs(pairs, gate_tier, ps_rows, cfg)
    fr = sum(1 for _r, lb in nh if lb == Band.FREE)
    pr = sum(1 for _r, lb in nh if lb == Band.PARTIAL)
    return fr, pr


def _primary_risk_suffix(row: dict[str, Any]) -> str:
    for cr in row.get("_capacity_rows") or ():
        w = project_status_word(cr.status or "")
        if w and w in ("BEHIND", "AT_RISK"):
            return f" {w}"
        if w and w.startswith("BLOCKED"):
            return f" {w}"
    return ""


def _best_alt_for_blocker(
    pairs: list[tuple[dict[str, Any], Band]],
    gate_tier: int,
    ps_rows: list[dict[str, Any]] | None,
    cfg: Mapping[str, Any],
    *,
    strict_free_ok: Callable[[dict[str, Any], Band], bool],
) -> tuple[str, str, str] | None:
    """Pick a person on the same non-Hold staffing line as Message 2, not counting as strict FREE."""
    nh = _non_hold_freeish_pool_pairs(pairs, gate_tier, ps_rows, cfg)
    scored: list[tuple[int, int, str, str, str]] = []
    for r, lb in nh:
        if strict_free_ok(r, lb):
            continue
        brank = 0 if lb == Band.PARTIAL else (1 if lb == Band.FREE else 2)
        ap = _active_project_count(r)
        nm = name_value(r)
        risk = _primary_risk_suffix(r)
        scored.append((brank, ap, nm.lower(), nm, risk))
    if not scored:
        return None
    scored.sort(key=lambda t: (t[0], t[1], t[2]))
    _br, _ap, _lk, nm, risk = scored[0]
    lb_row = next(lb for (r2, lb) in pairs if name_value(r2) == nm)
    return (nm, band_label_for_slack(lb_row), risk)


def _fmt_blocker_alt(alt: tuple[str, str, str] | None) -> str:
    if alt is None:
        return "(pool is empty)"
    nm, bl, risk = alt
    return f"({nm} is {bl}{risk})."


def _pool_table_and_arrows(
    *,
    so_d: list[tuple[dict[str, Any], Band]],
    soe_d: list[tuple[dict[str, Any], Band]],
    dpm_d: list[tuple[dict[str, Any], Band]],
    wfm_d: list[tuple[dict[str, Any], Band]],
    qm_d: list[tuple[dict[str, Any], Band]],
    se_d: list[tuple[dict[str, Any], Band]],
    n_t1s: int,
    n_t1f: int,
    n_t2: int,
    n_t3: int,
    n_t4: int,
    ps_rows: list[dict[str, Any]] | None,
    cfg: Mapping[str, Any],
) -> list[str]:
    buckets: dict[str, list[tuple[dict[str, Any], Band]]] = {
        "so": so_d,
        "soe": soe_d,
        "dpm": dpm_d,
        "wfm": wfm_d,
        "qm": qm_d,
        "se": se_d,
    }
    lines = ["*Pool right now (FREE / PARTIAL):*"]
    for key, label in _POOL_DISPLAY:
        gt = _POOL_GATE_TIER[key]
        pairs = buckets[key]
        fr, pr = _pool_free_partial_counts(pairs, gt, ps_rows, cfg)
        base = f"   {label:<6} {fr} / {pr}"
        arrow = ""
        if fr == 0:
            bl = _bottleneck_labels_for_role(
                key,
                n_t1s=n_t1s,
                n_t1f=n_t1f,
                n_t2=n_t2,
                n_t3=n_t3,
                n_t4=n_t4,
            )
            disp = _fmt_bottleneck_arrow_suffix(bl)
            if disp:
                arrow = f"      ← bottleneck for {disp}"
        lines.append(base + arrow)
    return lines


def _most_free_right_now_lines(
    *,
    so_d: list[tuple[dict[str, Any], Band]],
    soe_d: list[tuple[dict[str, Any], Band]],
    dpm_d: list[tuple[dict[str, Any], Band]],
    wfm_d: list[tuple[dict[str, Any], Band]],
    qm_d: list[tuple[dict[str, Any], Band]],
    se_d: list[tuple[dict[str, Any], Band]],
    ps_rows: list[dict[str, Any]] | None,
    cfg: Mapping[str, Any],
) -> tuple[list[str], frozenset[str]]:
    """Same buckets as Message 2: FREE only, non-Hold. Top 5 by (active asc, name asc)."""
    pr_short = {"soe": "SoE", "dpm": "DPM", "wfm": "WFM", "qm": "QM", "se": "SE", "so": "SO"}
    buckets: list[tuple[str, list[tuple[dict[str, Any], Band]]]] = [
        ("so", so_d),
        ("soe", soe_d),
        ("dpm", dpm_d),
        ("wfm", wfm_d),
        ("qm", qm_d),
        ("se", se_d),
    ]
    candidates: list[tuple[int, str, str, str]] = []
    for pr, pairs in buckets:
        gt = _POOL_GATE_TIER[pr]
        for r, lb in _non_hold_freeish_pool_pairs(pairs, gt, ps_rows, cfg):
            if lb != Band.FREE:
                continue
            n = _active_project_count(r)
            nm = name_value(r)
            candidates.append((n, nm.lower(), nm, pr_short.get(pr, pr)))
    candidates.sort(key=lambda t: (t[0], t[1]))
    lines = ["*Most free right now:*"]
    for n, _lk, nm, prs in candidates[:5]:
        lines.append(f"- {nm} ({prs}) — {n} active")
    if len(lines) == 1:
        return [], frozenset()
    names = frozenset(t[2] for t in candidates[:5])
    return lines, names


def _onboarding_overview_line(exr, req_roles: frozenset[str]) -> str:
    from staffing_agent.exclusions import project_roles_for_notion_tag

    hits = [
        p
        for p in exr.excluded
        if "onboarding" in (p.comment or "").lower()
        and project_roles_for_notion_tag(p.role_tag) & req_roles
    ]
    if not hits:
        return ""
    return f"*Onboarding:* {len(hits)} people"


def _restriction_phrase(rec: StaffingRecord | None) -> str | None:
    """People & Tags Comment indicates conditional staffing (PR-6 Restricted sub-band)."""
    if rec is None:
        return None
    c = (rec.comment or "").strip()
    if not c:
        return None
    low = c.lower()
    markers = (
        "only ots",
        "only agentic",
        "only ",
        "not for general",
        "conditional",
        "restrict",
        "stripe only",
        "exclude from",
        "agents only",
    )
    if not any(m in low for m in markers):
        return None
    return truncate_at_word_boundary(c, 100)


def _classify_detail_subband(
    r: dict[str, Any],
    lb: Band,
    gate_tier: int,
    ps_rows: list[dict[str, Any]] | None,
    cfg: Mapping[str, Any],
    rec: StaffingRecord | None,
) -> str:
    v = _verdict(r)
    if v.on_pto_today:
        return "pto"
    if _restriction_phrase(rec):
        return "restricted"
    if lb == Band.AT_CAP:
        return "over_cap"
    if _row_is_freeish(r):
        ok, rcode = _snapshot_gate_outcome(ps_rows, r, gate_tier, cfg)
        if not ok and rcode != "ps_scoping_discovery_only":
            return "hold"
        if lb == Band.FREE:
            return "free"
        return "partial"
    return "over_cap"


def _projects_detail_line_full(row: dict[str, Any]) -> str:
    """All active projects (PR-6 FREE/PARTIAL/Hold/Restricted)."""
    crs = tuple(row.get("_capacity_rows") or ())
    n = len(crs)
    if n == 0:
        return "└ 0 active"
    parts: list[str] = []
    for cr in crs:
        pname = _truncate_name(cr.project_name or cr.project_id or "?", 48)
        tier_bit = (cr.tier or "").replace("Tier ", "T").strip() or "T?"
        st = _stage_short(cr.stage or "")
        stat_word = project_status_word(cr.status or "")
        stat_seg = f", {stat_word}" if stat_word else ""
        parts.append(f"{pname} ({tier_bit} {st}{stat_seg})")
    return f"└ {n} active: {'; '.join(parts)}"


def _overcap_second_line(row: dict[str, Any]) -> str:
    crs = tuple(row.get("_capacity_rows") or ())
    n = len(crs)
    if n == 0:
        return "└ 0 active"
    summary = risk_breakdown_summary(crs)
    frag, more = truncate_overcap_projects(crs, top_n=3)
    mid = f" — {summary}" if summary else ""
    if frag:
        body = f"└ {n} active{mid}: {frag}"
    else:
        body = f"└ {n} active{mid}"
    if more:
        body += f" _(+{more} more)_"
    return body


def _onboarding_message2_footer(
    exr,
    req_roles: frozenset[str],
    start_dates: Optional[dict[str, date]] = None,
) -> str:
    from datetime import date

    from staffing_agent.exclusions import project_roles_for_notion_tag

    hits = [
        p
        for p in exr.excluded
        if "onboarding" in (p.comment or "").lower()
        and project_roles_for_notion_tag(p.role_tag) & req_roles
    ]
    if not hits:
        return ""
    today = date.today()

    def _sort_key(p) -> tuple[int, int, str]:
        if start_dates:
            sd = start_dates.get(p.email)
        else:
            sd = None
        if sd is None:
            return (1, 0, p.name.casefold())
        days = max(0, (today - sd).days)
        return (0, days, p.name.casefold())

    hits.sort(key=_sort_key)
    lines: list[str] = ["*Onboarding*"]
    for p in hits:
        if start_dates:
            sd = start_dates.get(p.email)
        else:
            sd = None
        if sd is None:
            tail = "(start date unknown)"
        else:
            tail = f"({max(0, (today - sd).days)} days)"
        lines.append(f"• {p.name} — onboarding {tail}")
    return "\n".join(lines)


def build_team_capacity_markdown(
    rows: list[dict[str, Any]],
    *,
    decision_cfg: Optional[Mapping[str, Any]] = None,
    project_staffing_rows: Optional[list[dict[str, Any]]] = None,
    only_role: Optional[str] = None,
    _consistency_sink: Optional[list[tuple[frozenset[str], frozenset[str]]]] = None,
) -> list[str]:
    """
    Breakdown SO / SoE / DPM / WFM / QM / SE + named possible teams (strict FREE).

    Full team capacity returns ``[overview, *detail_chunks]`` (one or more detail messages if long).

    ``only_role`` — if set to ``so``/``soe``/``dpm``/``wfm``/``qm``/``se``, return only that slice.

    ``_consistency_sink`` — optional list used by :func:`build_team_capacity_state` to capture
    name sets for Message 1 vs role-bucket (Message 2) regression tests; not for production callers.

    Set ``STAFFING_TEAM_CAPACITY_CHUNK_CHARS`` (default 11000, clamped 400–39000) to tune detail splitting vs Slack limits."""
    cfg = decision_cfg or load_decision_config()
    staffing = load_staffing_records()
    csv_loaded = bool(staffing)

    try:
        exr = get_exclusion_store().get()
    except ExclusionUnavailableError as e:
        return [slack_exclusion_unavailable_message(title="Team capacity", detail=e.slack_detail)]

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
        return [
            "*Team capacity*\n"
            "_No Capacity rows after CSV filter — check `sql/capacity.sql` and People & Tags._"
        ]

    so_rows: list[tuple[dict[str, Any], Band]] = []
    soe_rows: list[tuple[dict[str, Any], Band]] = []
    dpm_rows: list[tuple[dict[str, Any], Band]] = []
    wfm_rows: list[tuple[dict[str, Any], Band]] = []
    qm_rows: list[tuple[dict[str, Any], Band]] = []
    se_rows: list[tuple[dict[str, Any], Band]] = []

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
        elif pr == "se":
            se_rows.append(pair)

        if pr in ("soe", "dpm"):
            if not csv_loaded:
                so_rows.append(pair)
            elif rec and is_so(rec.so_status):
                so_rows.append(pair)

    ps = project_staffing_rows

    def fmt_section(
        title: str,
        pairs: list[tuple[dict[str, Any], Band]],
        *,
        subtitle: str = "",
        gate_tier: int = 2,
        max_listed: int = 40,
    ) -> list[str]:
        from staffing_agent.decision.team_template import (
            TEAM_CAPACITY_SUBBAND_HEADER,
            TEAM_CAPACITY_SUBBAND_ORDER,
        )

        _ = max_listed
        sec: list[str] = [f"*{title}*"]
        if subtitle:
            sec.append(subtitle)
        if not pairs:
            sec.append("_No people in this slice._")
            return sec

        pto_n = sum(1 for r, _lb in pairs if _verdict(r).on_pto_today)
        if pto_n:
            sec[0] = sec[0] + f" _([PTO today: {pto_n}])_"

        buckets: dict[str, list[tuple[dict[str, Any], Band]]] = {k: [] for k in TEAM_CAPACITY_SUBBAND_ORDER}
        for r, lb in pairs:
            em = (email_value(r) or "").strip().lower()
            rec = staffing.get(em) if em else None
            sk = _classify_detail_subband(r, lb, gate_tier, ps, cfg, rec)
            buckets[sk].append((r, lb))

        def sort_in_bucket(items: list[tuple[dict[str, Any], Band]]) -> list[tuple[dict[str, Any], Band]]:
            return sorted(
                items,
                key=lambda it: (_active_project_count(it[0]), name_value(it[0]).lower()),
            )

        for key in TEAM_CAPACITY_SUBBAND_ORDER:
            group = buckets[key]
            if not group:
                continue
            hdr = TEAM_CAPACITY_SUBBAND_HEADER.get(key)
            if hdr:
                sec.append(hdr)
            for r, lb in sort_in_bucket(group):
                em = (email_value(r) or "").strip().lower()
                rec2 = staffing.get(em) if em else None
                if key == "pto":
                    sec.append(f"• {name_value(r)} — _PTO today_")
                elif key == "restricted":
                    phrase = _restriction_phrase(rec2) or "conditional staffing"
                    bl = band_label_for_slack(lb)
                    load_s = ""
                    if _SHOW_LOAD:
                        vu = _verdict(r)
                        load_s = f" _[load: {vu.capacity_used:.2f}]_"
                    sec.append(
                        f"• {name_value(r)} — `{bl}` — _{phrase}_{_risk_and_pto_headline(r)}{load_s}"
                    )
                    sec.append(f"   {_projects_detail_line_full(r)}")
                elif key == "over_cap":
                    h, _d = _two_line_entry(r, lb)
                    sec.append(f"• {h}")
                    sec.append(f"   {_overcap_second_line(r)}")
                elif key == "hold":
                    _ok, rcode = _snapshot_gate_outcome(ps, r, gate_tier, cfg)
                    h, _d = _two_line_entry(r, lb)
                    reason = gate_reason_label(rcode) or "?"
                    sec.append(f"• {h} — _{reason}_")
                    sec.append(f"   {_projects_detail_line_full(r)}")
                else:
                    ok, rcode = _snapshot_gate_outcome(ps, r, gate_tier, cfg)
                    h, _d = _two_line_entry(r, lb)
                    suf = ""
                    if ok and rcode == "ps_scoping_discovery_only":
                        suf = f" _({gate_reason_label(rcode)})_"
                    sec.append(f"• {h}{suf}")
                    sec.append(f"   {_projects_detail_line_full(r)}")
        return sec

    orl = (only_role or "").strip().lower()
    if orl in ("so", "soe", "dpm", "wfm", "qm", "se"):
        role_map: dict[str, tuple[list[tuple[dict[str, Any], Band]], int, str, str]] = {
            "so": (
                _dedupe_pairs(so_rows),
                2,
                "SO (SoE/DPM with confirmed SO status)",
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
            "se": (_dedupe_pairs(se_rows), 4, "SE / Software Engineer", "_SE snapshot._"),
        }
        pairs, gt, title, sub = role_map[orl]
        intro = [
            "*Staffing — role shortlist*",
            "_Narrow ask (no project tier in Phase B). For a full team layout, add tier + scope or ask for *team capacity*._",
            "",
        ]
        body_lines = intro + fmt_section(title, pairs, subtitle=sub, gate_tier=gt, max_listed=40)
        req_roles = _team_capacity_required_roles(only_role)
        onboarding_emails = {
            p.email
            for p in exr.excluded
            if "onboarding" in (p.comment or "").lower()
            and project_roles_for_notion_tag(p.role_tag) & req_roles
        }
        start_dates = fetch_start_dates(onboarding_emails) if onboarding_emails else None
        foot = format_excluded_comment_block(exr, req_roles, start_dates=start_dates)
        if foot:
            body_lines.append("")
            body_lines.append(foot)
        return ["\n".join(body_lines)]

    def free_strict_ok(
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
    se_pairs = _dedupe_pairs(se_rows)

    def _em(r: dict[str, Any]) -> str:
        return (email_value(r) or "").strip().lower()

    def _rec(r: dict[str, Any]) -> StaffingRecord | None:
        e = _em(r)
        return staffing.get(e) if e else None

    d_free = [(r, lb) for r, lb in d_pairs if free_strict_ok(r, lb, 1)]
    w_free_t1 = [(r, lb) for r, lb in w_pairs if free_strict_ok(r, lb, 1)]
    q_free = [(r, lb) for r, lb in q_pairs if free_strict_ok(r, lb, 1)]
    w_free_t3 = [(r, lb) for r, lb in w_pairs if free_strict_ok(r, lb, 3)]
    w_free_t4 = [(r, lb) for r, lb in w_pairs if free_strict_ok(r, lb, 4)]
    se_free = [(r, lb) for r, lb in se_pairs if free_strict_ok(r, lb, 4)]

    so_t2 = [
        (r, lb)
        for r, lb in so_pairs
        if free_strict_ok(r, lb, 2)
        and (rec := _rec(r)) is not None
        and is_so_eligible_for_tier(rec, 2)
    ]
    so_t3 = [
        (r, lb)
        for r, lb in so_pairs
        if free_strict_ok(r, lb, 3)
        and (rec := _rec(r)) is not None
        and is_so_eligible_for_tier(rec, 3)
    ]
    so_t4 = [
        (r, lb)
        for r, lb in so_pairs
        if free_strict_ok(r, lb, 4)
        and (rec := _rec(r)) is not None
        and is_so_eligible_for_tier(rec, 4)
    ]
    soe_t3 = [(r, lb) for r, lb in soe_pairs if free_strict_ok(r, lb, 3)]
    soe_t4 = [(r, lb) for r, lb in soe_pairs if free_strict_ok(r, lb, 4)]

    def _greedy_pairs(
        a: list[tuple[dict[str, Any], Band]],
        b: list[tuple[dict[str, Any], Band]],
    ) -> list[tuple[str, str]]:
        used: set[str] = set()
        teams: list[tuple[str, str]] = []
        for r1, _ in a:
            e1 = _em(r1)
            if not e1 or e1 in used:
                continue
            for r2, _ in b:
                e2 = _em(r2)
                if not e2 or e2 in used or e2 == e1:
                    continue
                teams.append((name_value(r1), name_value(r2)))
                used.add(e1)
                used.add(e2)
                break
        return teams

    def _greedy_triples(
        xs: list[tuple[dict[str, Any], Band]],
        ys: list[tuple[dict[str, Any], Band]],
        zs: list[tuple[dict[str, Any], Band]],
    ) -> list[tuple[str, str, str]]:
        used: set[str] = set()
        out: list[tuple[str, str, str]] = []
        for r1, _ in xs:
            e1 = _em(r1)
            if not e1 or e1 in used:
                continue
            for r2, _ in ys:
                e2 = _em(r2)
                if not e2 or e2 in used or e2 == e1:
                    continue
                for r3, _ in zs:
                    e3 = _em(r3)
                    if not e3 or e3 in used or e3 in {e1, e2}:
                        continue
                    out.append((name_value(r1), name_value(r2), name_value(r3)))
                    used.update({e1, e2, e3})
                    break
                else:
                    continue
                break
        return out

    def _greedy_quads(
        a: list[tuple[dict[str, Any], Band]],
        b: list[tuple[dict[str, Any], Band]],
        c: list[tuple[dict[str, Any], Band]],
        d: list[tuple[dict[str, Any], Band]],
    ) -> list[tuple[str, str, str, str]]:
        used: set[str] = set()
        out: list[tuple[str, str, str, str]] = []
        for r1, _ in a:
            e1 = _em(r1)
            if not e1 or e1 in used:
                continue
            for r2, _ in b:
                e2 = _em(r2)
                if not e2 or e2 in used or e2 == e1:
                    continue
                for r3, _ in c:
                    e3 = _em(r3)
                    if not e3 or e3 in used or e3 in {e1, e2}:
                        continue
                    for r4, _ in d:
                        e4 = _em(r4)
                        if not e4 or e4 in used or e4 in {e1, e2, e3}:
                            continue
                        out.append(
                            (name_value(r1), name_value(r2), name_value(r3), name_value(r4))
                        )
                        used.update({e1, e2, e3, e4})
                        break
                    else:
                        continue
                    break
                else:
                    continue
                break
        return out

    t1_scoping_teams = _greedy_pairs(d_free, w_free_t1)
    t1_full_teams = _greedy_triples(d_free, w_free_t1, q_free)
    t3_teams = _greedy_triples(so_t3, soe_t3, w_free_t3)
    t4_teams = _greedy_quads(so_t4, soe_t4, w_free_t4, se_free)

    n_t1s = len(t1_scoping_teams)
    n_t1f = len(t1_full_teams)
    n_t2 = len(so_t2)
    n_t3 = len(t3_teams)
    n_t4 = len(t4_teams)

    allocations: list[tuple[str, str, tuple[str, ...]]] = []
    for i, (na, nb) in enumerate(t1_scoping_teams[:12], 1):
        allocations.append(("T1-scoping", f"Team {i}", (na, nb)))
    for i, (na, nb, nc) in enumerate(t1_full_teams[:12], 1):
        allocations.append(("T1-full", f"Team {i}", (na, nb, nc)))
    for i, (r, _lb) in enumerate(so_t2[:20], 1):
        allocations.append(("T2", f"SO-{i}", (name_value(r),)))
    for i, (na, nb, nc) in enumerate(t3_teams[:12], 1):
        allocations.append(("T3", f"Team {i}", (na, nb, nc)))
    for i, quad in enumerate(t4_teams[:12], 1):
        allocations.append(("T4", f"Team {i}", quad))

    name_to_tiers: dict[str, set[str]] = defaultdict(set)
    for tier_lbl, _team_lbl, names in allocations:
        for n in names:
            name_to_tiers[n].add(tier_lbl)
    conflicts = sorted(n for n, tis in name_to_tiers.items() if len(tis) > 1)

    so_d = _dedupe_pairs(so_rows)
    soe_d = _dedupe_pairs(soe_rows)
    dpm_d = _dedupe_pairs(dpm_rows)
    wfm_d = _dedupe_pairs(wfm_rows)
    qm_d = _dedupe_pairs(qm_rows)
    se_d = _dedupe_pairs(se_rows)

    bucket_names = frozenset(
        name_value(r) for pairs in (so_d, soe_d, dpm_d, wfm_d, qm_d, se_d) for r, _ in pairs
    )
    overview_person_names: set[str] = set()

    def _so_strict_free_for_alt(r: dict[str, Any], lb: Band) -> bool:
        if not free_strict_ok(r, lb, 2):
            return False
        rec = _rec(r)
        return rec is not None and is_so_eligible_for_tier(rec, 2)

    f_so, _p_so = _pool_free_partial_counts(so_d, 2, ps, cfg)
    f_soe, _p_soe = _pool_free_partial_counts(soe_d, 3, ps, cfg)
    f_dpm, _p_dpm = _pool_free_partial_counts(dpm_d, 1, ps, cfg)
    f_wfm, _p_wfm = _pool_free_partial_counts(wfm_d, 1, ps, cfg)
    f_qm, _p_qm = _pool_free_partial_counts(qm_d, 1, ps, cfg)
    f_se, _p_se = _pool_free_partial_counts(se_d, 4, ps, cfg)

    overview: list[str] = [
        TEAM_CAPACITY_TITLE_OVERVIEW_MRKDWN,
        "_Capacity v2 + People & Tags._",
    ]
    if ps:
        overview.append(
            "_Project staffing snapshot is loaded; per-role listing uses the same order-level "
            "rules as recommendations._"
        )
    else:
        overview.append("_No project staffing snapshot loaded._")
    if not csv_loaded:
        overview.append("_People & Tags CSV not found — SO bucket is not filtered by SO status._")

    overview.append("")
    overview.extend(
        _pool_table_and_arrows(
            so_d=so_d,
            soe_d=soe_d,
            dpm_d=dpm_d,
            wfm_d=wfm_d,
            qm_d=qm_d,
            se_d=se_d,
            n_t1s=n_t1s,
            n_t1f=n_t1f,
            n_t2=n_t2,
            n_t3=n_t3,
            n_t4=n_t4,
            ps_rows=ps,
            cfg=cfg,
        )
    )
    overview.append("")

    all_zero = n_t1s == 0 and n_t1f == 0 and n_t2 == 0 and n_t3 == 0 and n_t4 == 0
    if all_zero:
        overview.append("*Possible teams NOW:* 0 at every tier.")
        blines: list[str] = []
        if (n_t1s == 0 or n_t1f == 0) and f_dpm == 0:
            alt = _best_alt_for_blocker(
                dpm_d, 1, ps, cfg, strict_free_ok=lambda r, lb: free_strict_ok(r, lb, 1)
            )
            if alt:
                overview_person_names.add(alt[0])
            blines.append(f"   T1 blocked: 0 FREE DPM {_fmt_blocker_alt(alt)}")
        if n_t1s == 0 and f_dpm > 0 and len(w_free_t1) == 0:
            alt = _best_alt_for_blocker(
                wfm_d, 1, ps, cfg, strict_free_ok=lambda r, lb: free_strict_ok(r, lb, 1)
            )
            if alt:
                overview_person_names.add(alt[0])
            blines.append(f"   T1 scoping blocked: 0 FREE WFM {_fmt_blocker_alt(alt)}")
        if n_t1f == 0 and f_qm == 0 and len(d_free) > 0 and len(w_free_t1) > 0:
            alt = _best_alt_for_blocker(
                qm_d, 1, ps, cfg, strict_free_ok=lambda r, lb: free_strict_ok(r, lb, 1)
            )
            if alt:
                overview_person_names.add(alt[0])
            blines.append(f"   T1 full blocked: 0 FREE QM {_fmt_blocker_alt(alt)}")
        if (n_t2 == 0 or n_t3 == 0 or n_t4 == 0) and f_so == 0:
            alt = _best_alt_for_blocker(
                so_d, 2, ps, cfg, strict_free_ok=_so_strict_free_for_alt
            )
            if alt:
                overview_person_names.add(alt[0])
            zs: list[str] = []
            if n_t2 == 0:
                zs.append("T2")
            if n_t3 == 0:
                zs.append("T3")
            if n_t4 == 0:
                zs.append("T4")
            tl = compress_slash(zs)
            blines.append(f"   {tl} blocked: 0 FREE SO {_fmt_blocker_alt(alt)}")
        if n_t3 == 0 and f_soe == 0 and f_so > 0:
            alt = _best_alt_for_blocker(
                soe_d, 3, ps, cfg, strict_free_ok=lambda r, lb: free_strict_ok(r, lb, 3)
            )
            if alt:
                overview_person_names.add(alt[0])
            blines.append(f"   T3 blocked: 0 FREE SoE {_fmt_blocker_alt(alt)}")
        if n_t3 == 0 and f_so > 0 and f_soe > 0 and len(w_free_t3) == 0:
            alt = _best_alt_for_blocker(
                wfm_d, 3, ps, cfg, strict_free_ok=lambda r, lb: free_strict_ok(r, lb, 3)
            )
            if alt:
                overview_person_names.add(alt[0])
            blines.append(f"   T3 blocked: 0 FREE WFM {_fmt_blocker_alt(alt)}")
        if n_t4 == 0 and f_se == 0:
            alt = _best_alt_for_blocker(
                se_d, 4, ps, cfg, strict_free_ok=lambda r, lb: free_strict_ok(r, lb, 4)
            )
            if alt:
                overview_person_names.add(alt[0])
            blines.append(f"   T4 blocked: 0 FREE SE {_fmt_blocker_alt(alt)}")
        dedup: list[str] = []
        seen_b: set[str] = set()
        for b in blines:
            if b not in seen_b:
                seen_b.add(b)
                dedup.append(b)
        overview.extend(dedup[:4])
        if len(dedup) > 4:
            overview.append(f"   _(+ {len(dedup) - 4} more blockers)_")
    else:
        head_bits: list[str] = []
        if n_t1s:
            head_bits.append(f"{n_t1s} at T1 scoping")
        if n_t1f:
            head_bits.append(f"{n_t1f} at T1 full")
        if n_t2:
            head_bits.append(f"{n_t2} at T2")
        if n_t3:
            head_bits.append(f"{n_t3} at T3")
        if n_t4:
            head_bits.append(f"{n_t4} at T4")
        overview.append("*Possible teams NOW:* " + " · ".join(head_bits))
        if t1_scoping_teams:
            pairs_s = " · ".join(f"{a} + {b}" for a, b in t1_scoping_teams[:8])
            overview.append(f"   T1 scoping: {pairs_s}")
            overview_person_names.update(n for ab in t1_scoping_teams[:8] for n in ab)
        if t1_full_teams:
            pairs_f = " · ".join(f"{a} + {b} + {c}" for a, b, c in t1_full_teams[:8])
            overview.append(f"   T1 full: {pairs_f}")
            overview_person_names.update(n for t in t1_full_teams[:8] for n in t)
        if so_t2:
            names = " · ".join(name_value(r) for r, _lb in so_t2[:16])
            overview.append(f"   T2: {names}")
            overview_person_names.update(name_value(r) for r, _lb in so_t2[:16])
        if t3_teams:
            trip = " · ".join(f"{a} + {b} + {c}" for a, b, c in t3_teams[:8])
            overview.append(f"   T3: {trip}")
            overview_person_names.update(n for t in t3_teams[:8] for n in t)
        if t4_teams:
            qu = " · ".join(f"{a} + {b} + {c} + {d}" for a, b, c, d in t4_teams[:8])
            overview.append(f"   T4: {qu}")
            overview_person_names.update(n for t in t4_teams[:8] for n in t)

    if conflicts:
        overview.append(
            f"_Cross-tier name overlap:_ {', '.join(conflicts)} — same person in multiple greedy scenarios."
        )
        overview_person_names.update(conflicts)

    overview.append("")
    mf_lines, mf_nm = _most_free_right_now_lines(
        so_d=so_d,
        soe_d=soe_d,
        dpm_d=dpm_d,
        wfm_d=wfm_d,
        qm_d=qm_d,
        se_d=se_d,
        ps_rows=ps,
        cfg=cfg,
    )
    overview_person_names |= mf_nm
    if mf_lines:
        overview.extend(mf_lines)
        overview.append("")

    req_roles = _team_capacity_required_roles(only_role)
    ob = _onboarding_overview_line(exr, req_roles)
    if ob:
        overview.append(ob)
        overview.append("")

    section_blocks: list[str] = []
    section_blocks.append("\n".join(fmt_section(
        "SO (SoE/DPM with confirmed SO status)",
        so_d,
        subtitle="_Accountable SO pool (exact SO status in People & Tags, not “can be SO”)._",
        gate_tier=2,
    )))
    section_blocks.append("\n".join(fmt_section(
        "SoE / SSoE (`project_role` = soe)",
        soe_d,
        gate_tier=3,
    )))
    section_blocks.append("\n".join(fmt_section("DPM", dpm_d, gate_tier=1)))
    section_blocks.append("\n".join(fmt_section(
        "WFM / WFC (`project_role` = wfm)",
        wfm_d,
        gate_tier=1,
    )))
    section_blocks.append("\n".join(fmt_section(
        "QM (for Tier 1 scoping/building per Node 2)",
        qm_d,
        gate_tier=1,
    )))
    section_blocks.append("\n".join(fmt_section(
        "SE / Software Engineer",
        se_d,
        gate_tier=4,
    )))

    req_roles_ob = _team_capacity_required_roles(None)
    onboarding_emails2 = {
        p.email
        for p in exr.excluded
        if "onboarding" in (p.comment or "").lower()
        and project_roles_for_notion_tag(p.role_tag) & req_roles_ob
    }
    start_dates2 = fetch_start_dates(onboarding_emails2) if onboarding_emails2 else None
    ob_tail = _onboarding_message2_footer(exr, req_roles_ob, start_dates2)
    if ob_tail:
        section_blocks.append(ob_tail)

    detail_chunks = _pack_team_capacity_detail_chunks(
        section_blocks,
        max_chars=_team_capacity_detail_chunk_chars(),
    )

    if _consistency_sink is not None:
        _consistency_sink.append((frozenset(overview_person_names), bucket_names))
    return ["\n".join(overview), *detail_chunks]


def build_team_capacity_state(
    rows: list[dict[str, Any]],
    *,
    decision_cfg: Optional[Mapping[str, Any]] = None,
    project_staffing_rows: Optional[list[dict[str, Any]]] = None,
    only_role: Optional[str] = None,
) -> TeamCapacityState:
    """Same render as :func:`build_team_capacity_markdown`, plus name sets for cross-message checks."""
    sink: list[tuple[frozenset[str], frozenset[str]]] = []
    messages = build_team_capacity_markdown(
        rows,
        decision_cfg=decision_cfg,
        project_staffing_rows=project_staffing_rows,
        only_role=only_role,
        _consistency_sink=sink,
    )
    if sink:
        m1, m2 = sink[0]
        return TeamCapacityState(messages, m1, m2)
    return TeamCapacityState(messages, frozenset(), frozenset())


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
) -> list[str]:
    """Fetch Capacity + optional project_staffing; returns 1+ Slack mrkdwn messages (overview + detail chunks)."""
    from staffing_agent.node3_project_staffing import fetch_project_staffing_rows

    ok, rows, err = fetch_capacity_rows(timeout_sec=timeout_sec)
    if not ok:
        if err == "no_profile":
            return ["*Team capacity*\n_Set `DATABRICKS_PROFILE` and place the query in `sql/capacity.sql`._"]
        if err == "no_sql":
            return ["*Team capacity*\n_`sql/capacity.sql` is empty or too short._"]
        return [f"*Team capacity*\n_Capacity query failed:_\n```{err[:1200]}```"]

    cfg = load_decision_config()
    ps_rows = fetch_project_staffing_rows(timeout_sec=min(timeout_sec, 180))
    return build_team_capacity_markdown(
        rows,
        decision_cfg=cfg,
        project_staffing_rows=ps_rows or None,
        only_role=only_role,
    )


def build_team_capacity_slack_reply(messages: list[dict[str, Any]], *, only_role: Optional[str] = None) -> list[str]:
    """Full Slack payload for team-capacity intent (``messages`` reserved for future context)."""
    _ = messages
    return build_live_capacity_markdown(only_role=only_role)
