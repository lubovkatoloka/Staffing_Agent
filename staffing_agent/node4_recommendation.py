"""
Who can take the project — ranked recommendation from Capacity v2 rows + People & Tags (email join).
"""

from __future__ import annotations

import re
from typing import Any, Literal, Mapping, NamedTuple, Optional, Tuple

from staffing_agent.capacity_runtime import (
    default_new_project_weight,
    prepare_rows_for_recommendation,
)
from staffing_agent.decision import CapacityRow, CapacityVerdict
from staffing_agent.decision.enums import Band, IneligibleReason
from staffing_agent.decision.team_template import SLOT_TO_SECTION_HEADER, team_template_for
from staffing_agent.node3_row_utils import email_value, name_value, project_role_norm
from staffing_agent.node3_tier_preview import occupation_preview_roles
from staffing_agent.project_staffing_gates import (
    active_project_rows_for_person,
    project_staffing_gate_reason,
)
from staffing_agent.exclusions import (
    ExclusionResult,
    format_excluded_comment_block,
    get_exclusion_store,
    project_roles_for_notion_tag,
)
from staffing_agent.hibob import fetch_start_dates
from staffing_agent.staffing_csv import (
    StaffingRecord,
    is_so,
    is_so_eligible_for_tier,
    load_staffing_records,
    skill_match_score,
)


class Tier3RoleBuckets(NamedTuple):
    """Primary + pickable alternates + stretch (gated) alternates for one template slot."""

    primary: list[tuple[dict[str, Any], CapacityVerdict, StaffingRecord | None, int, str | None]]
    alternate: list[tuple[dict[str, Any], CapacityVerdict, StaffingRecord | None, int, str | None]]
    stretch_alternates: tuple[tuple[dict[str, Any], CapacityVerdict, StaffingRecord | None, int, str | None], ...]


# Minimum alternates per section whenever a primary exists (pickable first, then gated rows).
RECOMMENDATION_MIN_ALTERNATES = 2

ScoredTuple = Tuple[dict[str, Any], CapacityVerdict, Optional[StaffingRecord], int, Optional[str]]


_STAGE_SHORT = {
    "building": "build",
    "stabilisation_delivery": "stab",
    "scoping_solution_design": "scoping",
    "discovery": "disc",
    "close_out_retrospective": "close-out",
}


def _verdict(row: dict[str, Any]) -> CapacityVerdict:
    v = row.get("_capacity_verdict")
    if not isinstance(v, CapacityVerdict):
        raise ValueError("row missing CapacityVerdict — call prepare_rows_for_recommendation first")
    return v


def _band_rank(band: Band) -> int:
    return {Band.FREE: 0, Band.PARTIAL: 1, Band.AT_CAP: 2}.get(band, 9)


def _so_rank(rec: StaffingRecord | None, *, needs_so: bool) -> int:
    if not needs_so:
        return 0
    if rec and is_so(rec.so_status):
        return 0
    return 1


def _so_slot_tuple(
    it: tuple[dict[str, Any], CapacityVerdict, StaffingRecord | None, int, str | None],
    tier: int,
) -> bool:
    _r, _v, rec, _sk, _reason = it
    return rec is not None and is_so_eligible_for_tier(rec, tier)


def _needs_so_table_filter(project_role: str) -> bool:
    return (project_role or "").strip().lower() in ("soe", "dpm")


def _staffing_full_scored(
    rows: list[dict[str, Any]],
    *,
    tier: Optional[int],
    decision_cfg: Mapping[str, Any],
    project_type_tags: list[str],
    summary: str,
    staffing: dict[str, StaffingRecord],
    project_staffing_rows: Optional[list[dict[str, Any]]] = None,
    new_project_weight: float,
    excluded_emails: frozenset[str],
) -> list[tuple[dict[str, Any], CapacityVerdict, StaffingRecord | None, int, str | None]]:
    """All role-filtered candidates with CSV reasons — same sort as recommendation."""
    if not rows or tier is None or tier not in (1, 2, 3, 4):
        return []

    role_filter = occupation_preview_roles(tier)
    if role_filter is None:
        return []

    candidates = [r for r in rows if project_role_norm(r) in role_filter]
    if not candidates:
        return []

    scored: list[tuple[dict[str, Any], CapacityVerdict, StaffingRecord | None, int, str | None]] = []
    for r in candidates:
        verdict = _verdict(r)
        em = email_value(r)
        rec = staffing.get(em) if em else None
        sk = skill_match_score(rec, project_type_tags, summary) if rec else 0
        pr = project_role_norm(r)
        reason: str | None = None
        needs_so = _needs_so_table_filter(pr)
        if em and em in excluded_emails:
            reason = "blocked_comment"
        elif rec:
            if needs_so and not is_so(rec.so_status):
                # Tier 2–4: template has a dedicated *SoE* bench slot after *SO* (SoE/DPM in SO pool only via
                # `_so_slot_tuple`). SoE-shaped people without People & Tags "SO" stay recommendable for SoE.
                if pr != "soe" or tier not in (2, 3, 4):
                    reason = "not_so"
        else:
            if needs_so:
                reason = "no_csv"
        if reason is None and project_staffing_rows:
            pname = name_value(r)
            ps_sub = active_project_rows_for_person(project_staffing_rows, pname)
            if ps_sub:
                reason = project_staffing_gate_reason(
                    ps_sub,
                    tier=tier,
                    decision_cfg=decision_cfg,
                )
        scored.append((r, verdict, rec, sk, reason))

    def sort_key(
        it: tuple[dict[str, Any], CapacityVerdict, StaffingRecord | None, int, str | None],
    ) -> tuple[int, int, int, float, int, int]:
        r, verdict, rec, sk, reason = it
        pr = project_role_norm(r)
        needs_so = _needs_so_table_filter(pr)
        if reason is None:
            bucket, ps_rank = 0, 0
        elif reason == "ps_scoping_discovery_only":
            bucket, ps_rank = 0, 1
        else:
            bucket, ps_rank = 1, 0
        return (
            bucket,
            ps_rank,
            _band_rank(verdict.band),
            float(verdict.capacity_used),
            _so_rank(rec, needs_so=needs_so),
            -sk,
        )

    scored.sort(key=sort_key)
    return scored


def _is_pickable_tuple(
    it: tuple[dict[str, Any], CapacityVerdict, StaffingRecord | None, int, str | None],
) -> bool:
    _r, verdict, _rec, _sk, reason = it
    if not verdict.eligible_for_new:
        return False
    if verdict.band == Band.AT_CAP:
        return False
    if verdict.ineligible_reason != IneligibleReason.OK:
        return False
    good_band = verdict.band in (Band.FREE, Band.PARTIAL)
    if not good_band:
        return False
    if reason is None:
        return True
    if reason == "ps_scoping_discovery_only":
        return True
    return False


def _email_norm_tuple(it: ScoredTuple) -> str:
    return (email_value(it[0]) or "").strip().lower()


def _stretch_ok_nonpickable(it: ScoredTuple) -> bool:
    """Non-pickable row we may still list as a stretch alternate (e.g. project_staffing gate)."""
    if _is_pickable_tuple(it):
        return False
    _r, v, _rec, _sk, reason = it
    if reason == "blocked_comment":
        return False
    if v.on_pto_today:
        return False
    if v.band not in (Band.FREE, Band.PARTIAL):
        return False
    if v.ineligible_reason != IneligibleReason.OK:
        return False
    if not v.eligible_for_new:
        return False
    return True


def _fill_slot_alternates(
    ordered: list[ScoredTuple],
    *,
    primary: list[ScoredTuple],
    min_alternates: int = RECOMMENDATION_MIN_ALTERNATES,
    extra_used: frozenset[str] = frozenset(),
) -> tuple[list[ScoredTuple], tuple[ScoredTuple, ...]]:
    """Up to ``min_alternates`` names: pickable first in sort order, then gated/stretch."""
    used: set[str] = set(extra_used) | {_email_norm_tuple(x) for x in primary if _email_norm_tuple(x)}
    pick_alts: list[ScoredTuple] = []
    for it in ordered:
        em = _email_norm_tuple(it)
        if not em or em in used:
            continue
        if len(pick_alts) >= min_alternates:
            break
        if _is_pickable_tuple(it):
            pick_alts.append(it)
            used.add(em)
    stretch: list[ScoredTuple] = []
    if len(pick_alts) < min_alternates:
        for it in ordered:
            em = _email_norm_tuple(it)
            if not em or em in used:
                continue
            if len(pick_alts) + len(stretch) >= min_alternates:
                break
            if _stretch_ok_nonpickable(it):
                stretch.append(it)
                used.add(em)
    return pick_alts, tuple(stretch)


def _scored_tuple_sort_key(
    it: tuple[dict[str, Any], CapacityVerdict, StaffingRecord | None, int, str | None],
) -> tuple[int, int, int, float, int, int]:
    r, verdict, rec, sk, reason = it
    pr = project_role_norm(r)
    needs_so = _needs_so_table_filter(pr)
    if reason is None:
        bucket, ps_rank = 0, 0
    elif reason == "ps_scoping_discovery_only":
        bucket, ps_rank = 0, 1
    else:
        bucket, ps_rank = 1, 0
    return (
        bucket,
        ps_rank,
        _band_rank(verdict.band),
        float(verdict.capacity_used),
        _so_rank(rec, needs_so=needs_so),
        -sk,
    )


def _tier3_int_setting(decision_cfg: Mapping[str, Any], key: str, *, default: int) -> int:
    t3 = (decision_cfg or {}).get("tier3_recommendation") or {}
    raw = t3.get(key, default)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = default
    return max(0, n)


def _tier3_team_slices(
    scored: list[tuple[dict[str, Any], CapacityVerdict, StaffingRecord | None, int, str | None]],
    *,
    project_staffing_rows: list[dict[str, Any]] | None,
    decision_cfg: Mapping[str, Any],
) -> tuple[Tier3RoleBuckets, Tier3RoleBuckets, Tier3RoleBuckets]:
    from staffing_agent.node3_project_staffing import count_active_orders_for_person

    cfg: Mapping[str, Any] = decision_cfg or {}
    ps = project_staffing_rows or []
    has_ps = bool(project_staffing_rows)

    so_cap = _tier3_int_setting(cfg, "exclude_so_if_active_orders_gte", default=3)
    soe_cap = _tier3_int_setting(cfg, "exclude_soe_if_active_orders_gte", default=3)
    wfm_cap = _tier3_int_setting(cfg, "exclude_wfm_if_active_orders_gte", default=0)

    def _orders(nm: str) -> int:
        return count_active_orders_for_person(ps, nm)

    def _pass_cap(nm: str, cap: int) -> bool:
        if not has_ps or cap <= 0:
            return True
        return _orders(nm) < cap

    so_ordered = sorted(
        [
            it
            for it in scored
            if project_role_norm(it[0]) in frozenset({"dpm", "soe"})
            and _so_slot_tuple(it, 3)
            and _pass_cap(name_value(it[0]), so_cap)
        ],
        key=_scored_tuple_sort_key,
    )
    so_primary: list[ScoredTuple] = []
    for it in so_ordered:
        if _is_pickable_tuple(it):
            so_primary = [it]
            break
    so_pick_alts, so_stretch = _fill_slot_alternates(so_ordered, primary=so_primary)

    so_emails_primary = {
        email_value(it[0]).strip().lower()
        for it in so_primary
        if (email_value(it[0]) or "").strip()
    }

    soe_ordered = sorted(
        [
            it
            for it in scored
            if project_role_norm(it[0]) == "soe"
            and _pass_cap(name_value(it[0]), soe_cap)
        ],
        key=_scored_tuple_sort_key,
    )
    soe_primary: list[ScoredTuple] = []
    for it in soe_ordered:
        em = _email_norm_tuple(it)
        if em in so_emails_primary:
            continue
        if _is_pickable_tuple(it):
            soe_primary = [it]
            break
    soe_pick_alts, soe_stretch = _fill_slot_alternates(
        soe_ordered,
        primary=soe_primary,
        extra_used=frozenset(so_emails_primary),
    )

    wfm_ordered = sorted(
        [
            it
            for it in scored
            if project_role_norm(it[0]) == "wfm"
            and _pass_cap(name_value(it[0]), wfm_cap)
        ],
        key=_scored_tuple_sort_key,
    )
    wfm_primary: list[ScoredTuple] = []
    for it in wfm_ordered:
        if _is_pickable_tuple(it):
            wfm_primary = [it]
            break
    wfm_pick_alts, wfm_stretch = _fill_slot_alternates(wfm_ordered, primary=wfm_primary)

    return (
        Tier3RoleBuckets(so_primary, so_pick_alts, so_stretch),
        Tier3RoleBuckets(soe_primary, soe_pick_alts, soe_stretch),
        Tier3RoleBuckets(wfm_primary, wfm_pick_alts, wfm_stretch),
    )


def _tier4_team_slices(
    scored: list[tuple[dict[str, Any], CapacityVerdict, StaffingRecord | None, int, str | None]],
    *,
    project_staffing_rows: list[dict[str, Any]] | None,
    decision_cfg: Mapping[str, Any],
) -> tuple[Tier3RoleBuckets, Tier3RoleBuckets, Tier3RoleBuckets, Tier3RoleBuckets]:
    from staffing_agent.node3_project_staffing import count_active_orders_for_person

    cfg: Mapping[str, Any] = decision_cfg or {}
    ps = project_staffing_rows or []
    has_ps = bool(project_staffing_rows)

    so_cap = _tier3_int_setting(cfg, "exclude_so_if_active_orders_gte", default=3)
    soe_cap = _tier3_int_setting(cfg, "exclude_soe_if_active_orders_gte", default=3)
    wfm_cap = _tier3_int_setting(cfg, "exclude_wfm_if_active_orders_gte", default=0)
    se_cap = _tier3_int_setting(cfg, "exclude_se_if_active_orders_gte", default=0)

    def _orders(nm: str) -> int:
        return count_active_orders_for_person(ps, nm)

    def _pass_cap(nm: str, cap: int) -> bool:
        if not has_ps or cap <= 0:
            return True
        return _orders(nm) < cap

    so_ordered = sorted(
        [
            it
            for it in scored
            if project_role_norm(it[0]) in frozenset({"dpm", "soe"})
            and _so_slot_tuple(it, 4)
            and _pass_cap(name_value(it[0]), so_cap)
        ],
        key=_scored_tuple_sort_key,
    )
    so_primary: list[ScoredTuple] = []
    for it in so_ordered:
        if _is_pickable_tuple(it):
            so_primary = [it]
            break
    so_pick_alts, so_stretch = _fill_slot_alternates(so_ordered, primary=so_primary)

    so_emails_primary = {
        email_value(it[0]).strip().lower()
        for it in so_primary
        if (email_value(it[0]) or "").strip()
    }

    soe_ordered = sorted(
        [
            it
            for it in scored
            if project_role_norm(it[0]) == "soe"
            and _pass_cap(name_value(it[0]), soe_cap)
        ],
        key=_scored_tuple_sort_key,
    )
    soe_primary = []
    for it in soe_ordered:
        em = _email_norm_tuple(it)
        if em in so_emails_primary:
            continue
        if _is_pickable_tuple(it):
            soe_primary = [it]
            break
    soe_pick_alts, soe_stretch = _fill_slot_alternates(
        soe_ordered,
        primary=soe_primary,
        extra_used=frozenset(so_emails_primary),
    )

    wfm_ordered = sorted(
        [
            it
            for it in scored
            if project_role_norm(it[0]) == "wfm"
            and _pass_cap(name_value(it[0]), wfm_cap)
        ],
        key=_scored_tuple_sort_key,
    )
    wfm_primary = []
    for it in wfm_ordered:
        if _is_pickable_tuple(it):
            wfm_primary = [it]
            break
    wfm_pick_alts, wfm_stretch = _fill_slot_alternates(wfm_ordered, primary=wfm_primary)

    se_ordered = sorted(
        [
            it
            for it in scored
            if project_role_norm(it[0]) == "se"
            and _pass_cap(name_value(it[0]), se_cap)
        ],
        key=_scored_tuple_sort_key,
    )
    se_primary = []
    for it in se_ordered:
        if _is_pickable_tuple(it):
            se_primary = [it]
            break
    se_pick_alts, se_stretch = _fill_slot_alternates(se_ordered, primary=se_primary)

    return (
        Tier3RoleBuckets(so_primary, so_pick_alts, so_stretch),
        Tier3RoleBuckets(soe_primary, soe_pick_alts, soe_stretch),
        Tier3RoleBuckets(wfm_primary, wfm_pick_alts, wfm_stretch),
        Tier3RoleBuckets(se_primary, se_pick_alts, se_stretch),
    )


def _tier1_team_slices(
    scored: list[tuple[dict[str, Any], CapacityVerdict, StaffingRecord | None, int, str | None]],
) -> tuple[Tier3RoleBuckets, Tier3RoleBuckets]:
    so_ordered = sorted(
        [
            it
            for it in scored
            if project_role_norm(it[0]) in frozenset({"dpm", "wfm"})
            and _so_slot_tuple(it, 1)
        ],
        key=_scored_tuple_sort_key,
    )
    so_primary: list[ScoredTuple] = []
    for it in so_ordered:
        if _is_pickable_tuple(it):
            so_primary = [it]
            break
    so_pick_alts, so_stretch = _fill_slot_alternates(so_ordered, primary=so_primary)

    wfm_ordered = sorted(
        [it for it in scored if project_role_norm(it[0]) == "wfm"],
        key=_scored_tuple_sort_key,
    )
    wfm_primary: list[ScoredTuple] = []
    for it in wfm_ordered:
        if _is_pickable_tuple(it):
            wfm_primary = [it]
            break
    wfm_pick_alts, wfm_stretch = _fill_slot_alternates(wfm_ordered, primary=wfm_primary)

    return (
        Tier3RoleBuckets(so_primary, so_pick_alts, so_stretch),
        Tier3RoleBuckets(wfm_primary, wfm_pick_alts, wfm_stretch),
    )


def _tier2_full_team_slices(
    scored: list[tuple[dict[str, Any], CapacityVerdict, StaffingRecord | None, int, str | None]],
) -> tuple[Tier3RoleBuckets, Tier3RoleBuckets, Tier3RoleBuckets]:
    """Tier 2 full template: SoE/DPM (SO) + SoE bench + WFM (no parallel-order caps)."""
    so_ordered = sorted(
        [
            it
            for it in scored
            if project_role_norm(it[0]) in frozenset({"dpm", "soe"})
            and _so_slot_tuple(it, 2)
        ],
        key=_scored_tuple_sort_key,
    )
    so_primary: list[ScoredTuple] = []
    for it in so_ordered:
        if _is_pickable_tuple(it):
            so_primary = [it]
            break
    so_pick_alts, so_stretch = _fill_slot_alternates(so_ordered, primary=so_primary)

    so_emails_primary = {
        email_value(it[0]).strip().lower()
        for it in so_primary
        if (email_value(it[0]) or "").strip()
    }

    soe_ordered = sorted(
        [it for it in scored if project_role_norm(it[0]) == "soe"],
        key=_scored_tuple_sort_key,
    )
    soe_primary: list[ScoredTuple] = []
    for it in soe_ordered:
        em = _email_norm_tuple(it)
        if em in so_emails_primary:
            continue
        if _is_pickable_tuple(it):
            soe_primary = [it]
            break
    soe_pick_alts, soe_stretch = _fill_slot_alternates(
        soe_ordered,
        primary=soe_primary,
        extra_used=frozenset(so_emails_primary),
    )

    wfm_ordered = sorted(
        [it for it in scored if project_role_norm(it[0]) == "wfm"],
        key=_scored_tuple_sort_key,
    )
    wfm_primary: list[ScoredTuple] = []
    for it in wfm_ordered:
        if _is_pickable_tuple(it):
            wfm_primary = [it]
            break
    wfm_pick_alts, wfm_stretch = _fill_slot_alternates(wfm_ordered, primary=wfm_primary)

    return (
        Tier3RoleBuckets(so_primary, so_pick_alts, so_stretch),
        Tier3RoleBuckets(soe_primary, soe_pick_alts, soe_stretch),
        Tier3RoleBuckets(wfm_primary, wfm_pick_alts, wfm_stretch),
    )


def _tier2_bucket_map(
    scored: list[tuple[dict[str, Any], CapacityVerdict, StaffingRecord | None, int, str | None]],
    *,
    sese_path: bool,
) -> dict[str, Tier3RoleBuckets]:
    if sese_path:
        so_ordered = sorted(
            [
                it
                for it in scored
                if project_role_norm(it[0]) in frozenset({"dpm", "soe"})
                and _so_slot_tuple(it, 2)
            ],
            key=_scored_tuple_sort_key,
        )
        so_primary: list[ScoredTuple] = []
        for it in so_ordered:
            if _is_pickable_tuple(it):
                so_primary = [it]
                break
        so_pick_alts, so_stretch = _fill_slot_alternates(so_ordered, primary=so_primary)
        return {"SoE/DPM (SO)": Tier3RoleBuckets(so_primary, so_pick_alts, so_stretch)}
    so_b, soe_b, wfm_b = _tier2_full_team_slices(scored)
    return {
        "SoE/DPM (SO)": so_b,
        "SoE": soe_b,
        "WFM": wfm_b,
    }


def _stage_short(raw: str) -> str:
    key = (raw or "").strip().lower().replace(" ", "_")
    return _STAGE_SHORT.get(key, key.replace("_", "-"))


def _truncate_project_name(name: str, max_len: int = 25) -> str:
    base = name.strip()
    for frag in ("Studio", "Data Collection", "Orchestration Agents"):
        base = base.replace(frag, "")
    base = " ".join(base.split()).strip() or "?"
    if len(base) <= max_len:
        return base
    return base[: max_len - 1].rstrip() + "…"


def _risk_and_pto_inline(verdict: CapacityVerdict, crs: tuple[CapacityRow, ...]) -> str:
    """BEHIND/AT_RISK project marker + upcoming PTO (Rule 8b); cap at 2, then +N more."""
    warnings: list[str] = []
    risk_marker = _risk_inline(crs).strip()
    if risk_marker:
        warnings.append(risk_marker)
    if verdict.pto_upcoming_dates is not None:
        pto_start, _ = verdict.pto_upcoming_dates
        warnings.append(f"⚠️ PTO {pto_start}")
    if len(warnings) > 2:
        return " " + " ".join(warnings[:2]) + f" ⚠️ +{len(warnings) - 2} more issues"
    if warnings:
        return " " + " ".join(warnings)
    return ""


def _risk_inline(crs: tuple[CapacityRow, ...]) -> str:
    worst: CapacityRow | None = None
    worst_rank = 99
    for cr in crs:
        stat = (cr.status or "").strip().upper()
        if stat not in {"BEHIND", "AT_RISK"}:
            continue
        rk = 0 if stat == "BEHIND" else 1
        if rk < worst_rank:
            worst_rank = rk
            worst = cr
    if worst is None:
        return ""
    st = (worst.status or "").strip().upper()
    return f" ⚠️ {st} {_stage_short(worst.stage)}"


def _role_short_label(pr: str) -> str:
    pl = (pr or "").strip().lower()
    return {
        "dpm": "DPM",
        "soe": "SoE",
        "wfm": "WFM",
        "qm": "QM",
        "se": "SE",
    }.get(pl, pl.upper() or "?")


def _display_name_parts(row: dict[str, Any], rec: StaffingRecord | None) -> tuple[str, str]:
    nm_row = name_value(row)
    src = (rec.name if rec and rec.name.strip() else nm_row) or nm_row
    if re.search(r"\(external\)\s*$", src, flags=re.I):
        base = re.sub(r"\s*\(external\)\s*$", "", src, flags=re.I).strip()
        return base or nm_row, " (ext)"
    return nm_row, ""


def _compact_projects_tail(crs: tuple[CapacityRow, ...]) -> str:
    if not crs:
        return ""
    parts: list[str] = []
    for cr in crs[:3]:
        pname = _truncate_project_name(cr.project_name or cr.project_id or "?")
        tier_bit = (cr.tier or "").replace("Tier ", "T").strip() or "T?"
        st_short = _stage_short(cr.stage or "")
        stat_u = (cr.status or "").strip().upper()
        suffix = ""
        if stat_u and stat_u != "ON_TRACK":
            suffix = f", {stat_u}"
        parts.append(f"{pname} ({tier_bit} {st_short}{suffix})")
    return " · ".join(parts)


def _person_lines_slim(
    it: tuple[dict[str, Any], CapacityVerdict, StaffingRecord | None, int, str | None],
    *,
    new_pw: float,
    stretch_candidate: bool = False,
) -> list[str]:
    r, verdict, rec, _sk, _gate_reason = it
    cu = verdict.capacity_used
    after = cu + new_pw if new_pw > 0 else cu
    pr = project_role_norm(r) or "?"
    role_label = _role_short_label(pr)
    base_name, ext_suf = _display_name_parts(r, rec)
    soft = " [SOFT]" if verdict.is_soft else ""
    crs = tuple(r.get("_capacity_rows") or ())
    risk_inline = _risk_and_pto_inline(verdict, crs)
    band = verdict.band.value
    body = f"• *{base_name}{ext_suf}* · {role_label} · `{cu:.2f} → {after:.2f}` · {band}{soft}{risk_inline}"
    if stretch_candidate:
        body += " _[gated — verify snapshot / People & Tags]_"
    out = [body]
    compact = _compact_projects_tail(crs)
    if compact:
        out.append(f"   _{compact}_")
    return out


def _slot_section_md(
    slot_label: str,
    bucket: Tier3RoleBuckets,
    *,
    new_pw: float,
) -> tuple[str, list[str]]:
    header_key = SLOT_TO_SECTION_HEADER.get(slot_label, slot_label)
    risks: list[str] = []
    lines: list[str] = [f"*{header_key}*"]
    if bucket.primary:
        lines.extend(_person_lines_slim(bucket.primary[0], new_pw=new_pw))
    else:
        lines.append("_None available — see Risks below._")
        risks.append(f"No pickable candidate for *{header_key}*.")
    if bucket.primary:
        lines.append("")
        lines.append("_Alternates:_")
        for it in bucket.alternate:
            lines.extend(_person_lines_slim(it, new_pw=new_pw))
        for it in bucket.stretch_alternates:
            lines.extend(_person_lines_slim(it, new_pw=new_pw, stretch_candidate=True))
        if not bucket.alternate and not bucket.stretch_alternates:
            lines.append("_No other people in this tier’s snapshot._")
    elif bucket.alternate or bucket.stretch_alternates:
        lines.append("")
        lines.append("_Alternates:_")
        for it in bucket.alternate:
            lines.extend(_person_lines_slim(it, new_pw=new_pw))
        for it in bucket.stretch_alternates:
            lines.extend(_person_lines_slim(it, new_pw=new_pw, stretch_candidate=True))
    return "\n".join(lines), risks


def _bucket_map_for_tier(
    tier: int,
    *,
    sese_path: bool,
    scored: list[tuple[dict[str, Any], CapacityVerdict, StaffingRecord | None, int, str | None]],
    project_staffing_rows: list[dict[str, Any]] | None,
    decision_cfg: Mapping[str, Any],
) -> dict[str, Tier3RoleBuckets]:
    if tier == 1:
        so_b, wfm_b = _tier1_team_slices(scored)
        return {"DPM/WFM (SO)": so_b, "WFM": wfm_b}
    if tier == 2:
        return _tier2_bucket_map(scored, sese_path=sese_path)
    if tier == 3:
        so_b, soe_b, wfm_b = _tier3_team_slices(
            scored,
            project_staffing_rows=project_staffing_rows,
            decision_cfg=decision_cfg,
        )
        return {"SSoE/DPM (SO)": so_b, "SoE": soe_b, "WFM": wfm_b}
    so_b, soe_b, wfm_b, se_b = _tier4_team_slices(
        scored,
        project_staffing_rows=project_staffing_rows,
        decision_cfg=decision_cfg,
    )
    return {"SSoE/DPM (SO)": so_b, "SoE": soe_b, "WFM": wfm_b, "SE": se_b}


def _build_grouped_recommendation_md(
    *,
    tier: int,
    sese_path: bool,
    scored: list[tuple[dict[str, Any], CapacityVerdict, StaffingRecord | None, int, str | None]],
    decision_cfg: Mapping[str, Any],
    project_staffing_rows: Optional[list[dict[str, Any]]],
    new_pw: float,
) -> str:
    slots = team_template_for(tier, sese_path=sese_path)
    bucket_map = _bucket_map_for_tier(
        tier,
        sese_path=sese_path,
        scored=scored,
        project_staffing_rows=project_staffing_rows,
        decision_cfg=decision_cfg,
    )
    sections: list[str] = []
    risks: list[str] = []
    for slot in slots:
        sec_md, rs = _slot_section_md(slot, bucket_map[slot], new_pw=new_pw)
        sections.append(sec_md)
        risks.extend(rs)
    body = "\n\n".join(sections)
    if risks:
        body += "\n\n*Risks / open questions*\n" + "\n".join(f"• {r}" for r in risks)
    return body


def pickable_recommendation_rows(
    rows: list[dict[str, Any]],
    *,
    tier: Optional[int],
    decision_cfg: Mapping[str, Any],
    project_type_tags: Optional[list[str]] = None,
    summary: str = "",
    staffing_by_email: Optional[dict[str, StaffingRecord]] = None,
    limit: int = 4,
    project_staffing_rows: Optional[list[dict[str, Any]]] = None,
    sese_path: bool = False,
) -> list[dict[str, Any]]:
    """Capacity rows for top recommended people (same order as Slack sections)."""
    tags = project_type_tags or []
    staffing = staffing_by_email if staffing_by_email is not None else load_staffing_records()
    npw = default_new_project_weight(decision_cfg, tier)
    exr = get_exclusion_store().get()
    prepared = prepare_rows_for_recommendation(
        rows,
        decision_cfg=decision_cfg,
        new_project_weight=npw,
        staffing=staffing,
        excluded_emails=exr.excluded_emails,
    )
    scored = _staffing_full_scored(
        prepared,
        tier=tier,
        decision_cfg=decision_cfg,
        project_type_tags=tags,
        summary=summary,
        staffing=staffing,
        project_staffing_rows=project_staffing_rows,
        new_project_weight=npw,
        excluded_emails=exr.excluded_emails,
    )
    if tier not in (1, 2, 3, 4):
        pickable = [it for it in scored if _is_pickable_tuple(it)]
        return [it[0] for it in pickable[:limit]]

    bucket_map = _bucket_map_for_tier(
        tier,
        sese_path=sese_path,
        scored=scored,
        project_staffing_rows=project_staffing_rows,
        decision_cfg=decision_cfg,
    )
    slots = team_template_for(tier, sese_path=sese_path)
    ordered_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for slot in slots:
        b = bucket_map[slot]
        for it in b.primary + b.alternate:
            em = (email_value(it[0]) or "").strip().lower()
            if em:
                if em in seen:
                    continue
                seen.add(em)
            ordered_rows.append(it[0])
    return ordered_rows[:limit]


def build_project_recommendation_markdown(
    rows: list[dict[str, Any]],
    *,
    tier: Optional[int],
    decision_cfg: Mapping[str, Any],
    project_type_tags: Optional[list[str]] = None,
    summary: str = "",
    staffing_by_email: Optional[dict[str, StaffingRecord]] = None,
    detail: Literal["minimal", "standard", "full"] = "standard",
    project_staffing_rows: Optional[list[dict[str, Any]]] = None,
    sese_path: bool = False,
    exclusion_result: Optional[ExclusionResult] = None,
) -> str:
    """
    Role-grouped primary + alternates (Capacity v2 + People & Tags ranking).

    ``detail`` is kept for API compatibility; rendering is always the slim grouped layout.
    ``project_staffing_rows`` feeds tier 3/4 parallel-order caps only (not duplicate Slack tables).
    """
    _ = detail
    tags = project_type_tags or []
    staffing = staffing_by_email if staffing_by_email is not None else load_staffing_records()
    npw = default_new_project_weight(decision_cfg, tier)
    exr = exclusion_result or get_exclusion_store().get()

    if not rows:
        return ""

    prepared = prepare_rows_for_recommendation(
        rows,
        decision_cfg=decision_cfg,
        new_project_weight=npw,
        staffing=staffing,
        excluded_emails=exr.excluded_emails,
    )

    if tier is None:
        return (
            "*Recommendation: who can take the project*\n"
            "_Set Tier in Phase B (Node 1) — without Tier, automatic role filtering does not apply._"
        )

    if tier not in (1, 2, 3, 4):
        return (
            "*Recommendation: who can take the project*\n"
            f"_Tier {tier} is outside 1–4 — fix the classification in Phase B._"
        )

    role_filter = occupation_preview_roles(tier)
    if role_filter is None:
        return ""

    candidates = [r for r in prepared if project_role_norm(r) in role_filter]
    if not candidates:
        return (
            "*Recommendation: who can take the project*\n"
            "_No rows with matching roles for this Tier in Capacity snapshot — check SQL or data._"
        )

    scored = _staffing_full_scored(
        prepared,
        tier=tier,
        decision_cfg=decision_cfg,
        project_type_tags=tags,
        summary=summary,
        staffing=staffing,
        project_staffing_rows=project_staffing_rows,
        new_project_weight=npw,
        excluded_emails=exr.excluded_emails,
    )
    body = _build_grouped_recommendation_md(
        tier=tier,
        sese_path=sese_path,
        scored=scored,
        decision_cfg=decision_cfg,
        project_staffing_rows=project_staffing_rows,
        new_pw=npw,
    )
    role_filter = occupation_preview_roles(tier) or frozenset()
    onboarding_emails = {
        p.email
        for p in exr.excluded
        if "onboarding" in (p.comment or "").lower()
        and project_roles_for_notion_tag(p.role_tag) & role_filter
    }
    start_dates = fetch_start_dates(onboarding_emails) if onboarding_emails else None
    footer = format_excluded_comment_block(exr, role_filter, start_dates=start_dates)
    if footer:
        body += "\n\n" + footer
    return body
