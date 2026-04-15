"""
Who can take the project — ranked recommendation from Occupation rows + People & Tags CSV (email join).
"""

from __future__ import annotations

from typing import Any, Literal, Mapping, NamedTuple, Optional

from staffing_agent.decision import classify_availability
from staffing_agent.decision.enums import AvailabilityLabel
from staffing_agent.node3_row_utils import email_value, name_value, occupation_value, project_role_norm
from staffing_agent.node3_tier_preview import occupation_preview_roles
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
    skill_match_score,
)

# Max names in UNVERIFIED block (Slack message size); full set remains in Databricks.
MAX_UNVERIFIED_LINES = 20

# Short public line: ownership shape by tier + skills (tags or summary excerpt).
_TIER_TEAM_LABEL: dict[int, str] = {
    1: "DPM, WFM, QM",
    2: "SoE or DPM (SO), WFM, QM",
    3: "SSoE or DPM (SO), SoE, WFM/WFC",
    4: "SoE or DPM (SO), SoE, WFM, SE",
}


def _minimal_team_skills_why(tier: int, tags: list[str], summary: str) -> str:
    """Single `_Why:_` line: expected roles + skill focus — no Databricks/SCM boilerplate."""
    team = _TIER_TEAM_LABEL.get(tier, f"Tier {tier} ownership roles")
    if tags:
        sk = ", ".join(tags[:12])
        if len(tags) > 12:
            sk += "…"
        return f"_Why:_ *Team:* {team}. *Skills:* {sk}_"
    s = " ".join((summary or "").split())
    if s:
        if len(s) > 140:
            s = s[:137] + "…"
        return f"_Why:_ *Team:* {team}. *Skills:* _{s}_"
    return f"_Why:_ *Team:* {team}. *Skills:* _add tags or a short summary in Phase B for a tighter match._"


class Tier3RoleBuckets(NamedTuple):
    """Primary shortlist (top 3) + alternates (next N by rank) for one Tier 3 role line."""

    primary: list[tuple[dict[str, Any], Any, StaffingRecord | None, int, str | None]]
    alternate: list[tuple[dict[str, Any], Any, StaffingRecord | None, int, str | None]]


def _label_rank(label: AvailabilityLabel) -> int:
    return {
        AvailabilityLabel.FREE: 0,
        AvailabilityLabel.PARTIAL: 1,
        AvailabilityLabel.SOFT: 2,
        AvailabilityLabel.UNVERIFIED: 3,
        AvailabilityLabel.BUSY: 4,
        AvailabilityLabel.PTO: 5,
    }.get(label, 9)


def _classify_row(row: dict[str, Any], decision_cfg: Mapping[str, Any]):
    occ = occupation_value(row)
    if occ is None:
        t = 1.0
    else:
        t = max(0.0, min(1.0, float(occ)))
    apc = 0 if t == 0.0 else 1
    return classify_availability(t, active_project_count=apc, decision_cfg=decision_cfg)


def _needs_so_table_filter(project_role: str) -> bool:
    """SO / responsible per table — only for SoE/DPM."""
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
) -> list[tuple[dict[str, Any], Any, StaffingRecord | None, int, str | None]]:
    """All role-filtered candidates with CSV reasons — same sort as recommendation."""
    if not rows or tier is None or tier not in (1, 2, 3, 4):
        return []

    role_filter = occupation_preview_roles(tier)
    if role_filter is None:
        return []

    candidates = [r for r in rows if project_role_norm(r) in role_filter]
    if not candidates:
        return []

    st_cfg = load_staffing_table_config()
    scored: list[tuple[dict[str, Any], Any, StaffingRecord | None, int, str | None]] = []
    for r in candidates:
        av = _classify_row(r, decision_cfg)
        em = email_value(r)
        rec = staffing.get(em) if em else None
        sk = skill_match_score(rec, project_type_tags, summary) if rec else 0
        pr = project_role_norm(r)
        reason: str | None = None
        if rec:
            if comment_blocks_staffing(rec.comment, st_cfg):
                reason = "blocked_comment"
            elif _needs_so_table_filter(pr) and not is_so_or_can_be_so(rec.so_status):
                reason = "not_so"
        else:
            if _needs_so_table_filter(pr):
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
        scored.append((r, av, rec, sk, reason))

    def sort_key(
        it: tuple[dict[str, Any], Any, StaffingRecord | None, int, str | None],
    ) -> tuple[int, int, int, float, int]:
        r, av, _rec, sk, reason = it
        if reason is None:
            bucket, ps_rank = 0, 0
        elif reason == "ps_scoping_discovery_only":
            bucket, ps_rank = 0, 1  # after clean picks, still above hard-excluded
        else:
            bucket, ps_rank = 1, 0
        occ = occupation_value(r) if occupation_value(r) is not None else 1.0
        return (bucket, ps_rank, -sk, _label_rank(av.label), occ)

    scored.sort(key=sort_key)
    return scored


def _is_pickable_tuple(
    it: tuple[dict[str, Any], Any, StaffingRecord | None, int, str | None],
) -> bool:
    r, av, _rec, _sk, reason = it
    good_labels = frozenset(
        {
            AvailabilityLabel.FREE,
            AvailabilityLabel.PARTIAL,
            AvailabilityLabel.SOFT,
        }
    )
    if av.label not in good_labels:
        return False
    if reason is None:
        return True
    # Listed with a footnote — ok for scoping/discovery proposals only.
    if reason == "ps_scoping_discovery_only":
        return True
    return False


def _scored_tuple_sort_key(
    it: tuple[dict[str, Any], Any, StaffingRecord | None, int, str | None],
) -> tuple[int, int, int, float, int]:
    r, av, _rec, sk, reason = it
    if reason is None:
        bucket, ps_rank = 0, 0
    elif reason == "ps_scoping_discovery_only":
        bucket, ps_rank = 0, 1
    else:
        bucket, ps_rank = 1, 0
    occ = occupation_value(r) if occupation_value(r) is not None else 1.0
    return (bucket, ps_rank, -sk, _label_rank(av.label), occ)


def _short_why_so_line(
    r: dict[str, Any],
    av: Any,
    rec: StaffingRecord | None,
    sk: int,
) -> str:
    occ = occupation_value(r)
    pct = f"{float(occ) * 100:.0f}%" if occ is not None else "n/a"
    pr = project_role_norm(r) or "?"
    bits = [
        f"current load *{pct}* → `{av.label.value}`",
        f"role `{pr}` in Occupation",
    ]
    if sk:
        bits.append(f"tag/summary match ≈ {sk}")
    if rec:
        so = (rec.so_status or "—").strip() or "—"
        bits.append(f"People & Tags SO status: *{so}*")
    bits.append("fits SO accountability (SSoE or DPM) per Tier 3 ownership model")
    return "_Why:_ " + "; ".join(bits) + "_"


def _short_why_role_line(
    r: dict[str, Any],
    av: Any,
    rec: StaffingRecord | None,
    sk: int,
    role_label: str,
) -> str:
    occ = occupation_value(r)
    pct = f"{float(occ) * 100:.0f}%" if occ is not None else "n/a"
    bits = [
        f"current load *{pct}* → `{av.label.value}`",
        f"role `{project_role_norm(r) or '?'}` in Occupation",
    ]
    if sk:
        bits.append(f"tag/summary match ≈ {sk}")
    bits.append(f"strong fit for *{role_label}* slot on the team")
    return "_Why:_ " + "; ".join(bits) + "_"


def _format_tier3_person_line(
    it: tuple[dict[str, Any], Any, StaffingRecord | None, int, str | None],
    *,
    why_fn,
    project_staffing_rows: list[dict[str, Any]] | None = None,
) -> list[str]:
    r, av, rec, sk, gate_reason = it
    nm = name_value(r)
    out = [f"• *{nm}*"]
    out.append(f"  {why_fn(r, av, rec, sk)}")
    if gate_reason == "ps_scoping_discovery_only":
        out.append(f"  _({gate_reason_label(gate_reason)})_")
    if project_staffing_rows:
        from staffing_agent.node3_project_staffing import inline_active_orders_markdown

        busy = inline_active_orders_markdown(project_staffing_rows, nm)
        if busy:
            out.append(f"  {busy}")
    return out


def _tier3_int_setting(decision_cfg: Mapping[str, Any], key: str, *, default: int) -> int:
    t3 = (decision_cfg or {}).get("tier3_recommendation") or {}
    raw = t3.get(key, default)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = default
    return max(0, n)


def _tier3_team_slices(
    scored: list[tuple[dict[str, Any], Any, StaffingRecord | None, int, str | None]],
    *,
    project_staffing_rows: list[dict[str, Any]] | None,
    decision_cfg: Mapping[str, Any],
) -> tuple[Tier3RoleBuckets, Tier3RoleBuckets, Tier3RoleBuckets]:
    """
    Tier 3: SO / SoE / WFM each as primary (top 3) + alternates (next N by rank).
    Order-count gates from config apply per role when project_staffing snapshot exists.
    SoE list excludes anyone in the SO *primary* shortlist (distinct seats).
    """
    from staffing_agent.node3_project_staffing import count_active_orders_for_person

    pickable_scored = [it for it in scored if _is_pickable_tuple(it)]
    cfg: Mapping[str, Any] = decision_cfg or {}
    ps = project_staffing_rows or []
    has_ps = bool(project_staffing_rows)

    so_cap = _tier3_int_setting(cfg, "exclude_so_if_active_orders_gte", default=3)
    soe_cap = _tier3_int_setting(cfg, "exclude_soe_if_active_orders_gte", default=3)
    wfm_cap = _tier3_int_setting(cfg, "exclude_wfm_if_active_orders_gte", default=0)
    alt_n = _tier3_int_setting(cfg, "alternate_slots_per_role", default=3)
    alt_n = min(alt_n, 10)

    def _orders(nm: str) -> int:
        return count_active_orders_for_person(ps, nm)

    def _pass_cap(nm: str, cap: int) -> bool:
        if not has_ps or cap <= 0:
            return True
        return _orders(nm) < cap

    so_pool_raw = [it for it in pickable_scored if project_role_norm(it[0]) in frozenset({"dpm", "soe"})]
    so_pool_raw = [it for it in so_pool_raw if _pass_cap(name_value(it[0]), so_cap)]

    so_pool = sorted(so_pool_raw, key=_scored_tuple_sort_key)
    so_primary = so_pool[:3]
    so_alternate = so_pool[3 : 3 + alt_n]

    so_emails_primary = {
        email_value(it[0]).strip().lower()
        for it in so_primary
        if (email_value(it[0]) or "").strip()
    }

    soe_pool_raw = [it for it in pickable_scored if project_role_norm(it[0]) == "soe"]
    soe_pool_raw = [it for it in soe_pool_raw if _pass_cap(name_value(it[0]), soe_cap)]
    soe_pool = sorted(soe_pool_raw, key=_scored_tuple_sort_key)
    soe_for_team = [
        it for it in soe_pool if email_value(it[0]).strip().lower() not in so_emails_primary
    ]
    soe_primary = soe_for_team[:3]
    soe_alternate = soe_for_team[3 : 3 + alt_n]

    wfm_pool_raw = [it for it in pickable_scored if project_role_norm(it[0]) == "wfm"]
    wfm_pool_raw = [it for it in wfm_pool_raw if _pass_cap(name_value(it[0]), wfm_cap)]
    wfm_pool = sorted(wfm_pool_raw, key=_scored_tuple_sort_key)
    wfm_primary = wfm_pool[:3]
    wfm_alternate = wfm_pool[3 : 3 + alt_n]

    return (
        Tier3RoleBuckets(so_primary, so_alternate),
        Tier3RoleBuckets(soe_primary, soe_alternate),
        Tier3RoleBuckets(wfm_primary, wfm_alternate),
    )


def _format_tier3_alternate_bullets(
    items: list[tuple[dict[str, Any], Any, StaffingRecord | None, int, str | None]],
    *,
    project_staffing_rows: list[dict[str, Any]] | None,
) -> list[str]:
    """Compact lines for alternate shortlist (still ranked; same data rules)."""
    from staffing_agent.node3_project_staffing import count_active_orders_for_person

    out: list[str] = []
    for it in items:
        r, av, _rec, _sk, _reason = it
        nm = name_value(r)
        occ = occupation_value(r)
        pct = f"{float(occ) * 100:.0f}%" if occ is not None else "n/a"
        n_ord = (
            count_active_orders_for_person(project_staffing_rows or [], nm)
            if project_staffing_rows
            else None
        )
        ord_s = f"{n_ord} active orders" if n_ord is not None else "orders n/a"
        out.append(f"• *{nm}* — load *{pct}* → `{av.label.value}`; _{ord_s} (snapshot)_")
    return out


def _build_tier3_team_markdown(
    scored: list[tuple[dict[str, Any], Any, StaffingRecord | None, int, str | None]],
    *,
    minimal: bool,
    csv_loaded: bool,
    project_staffing_rows: list[dict[str, Any]] | None = None,
    decision_cfg: Mapping[str, Any] | None = None,
    project_type_tags: Optional[list[str]] = None,
    summary: str = "",
) -> str:
    """
    Tier 3 ownership: SO = SSoE or DPM; + SoE + WFM(WFC) — separate sections with load + why.

    Node 4 rules: (1) nobody appears in both SO and SoE primary lists; (2) per-role concurrent-order
    caps from config when project_staffing exists; (3) alternates = next in rank (not a manual blocklist).
    """
    cfg: Mapping[str, Any] = decision_cfg or {}
    has_ps = bool(project_staffing_rows)
    so_cap = _tier3_int_setting(cfg, "exclude_so_if_active_orders_gte", default=3)
    soe_cap = _tier3_int_setting(cfg, "exclude_soe_if_active_orders_gte", default=3)
    wfm_cap = _tier3_int_setting(cfg, "exclude_wfm_if_active_orders_gte", default=0)
    gate_any = has_ps and (so_cap > 0 or soe_cap > 0 or wfm_cap > 0)
    tags = list(project_type_tags or [])

    if minimal:
        lines = [
            "*Recommendation — Tier 3 team*",
            _minimal_team_skills_why(3, tags, summary),
        ]
    else:
        lines = [
            "*Recommendation — Tier 3 team (Decision Logic)*",
            "_Model: SO (SSoE or DPM) + SoE + WFM/WFC · target ~1.7 FTE; Occupation + People & Tags; verify calendar/SCM before slot._",
        ]
        if csv_loaded:
            lines.append("_People & Tags loaded._")
        else:
            lines.append("_CSV not loaded — SO checks limited._")

    if not minimal and gate_any:
        cap_parts: list[str] = []
        if so_cap > 0:
            cap_parts.append(f"SO: skip if ≥{so_cap} parallel orders in snapshot")
        if soe_cap > 0:
            cap_parts.append(f"SoE: skip if ≥{soe_cap} parallel orders in snapshot")
        if wfm_cap > 0:
            cap_parts.append(f"WFM: skip if ≥{wfm_cap} parallel orders in snapshot")
        cap_line = "; ".join(cap_parts)
        lines.append(
            "_Node 4: SoE primary excludes anyone in the SO primary shortlist (distinct seats). "
            f"{cap_line}. "
            "Alternates = next in rank after the same rules (not manual name blocks). "
            "Tune caps in decision_logic.yaml (tier3_recommendation)._"
        )
    elif not minimal:
        lines.append(
            "_Node 4: SoE primary excludes SO primary shortlist. "
            "Parallel-order caps apply when `project_staffing` snapshot is available._"
        )

    so_b, soe_b, wfm_b = _tier3_team_slices(
        scored,
        project_staffing_rows=project_staffing_rows,
        decision_cfg=cfg,
    )

    lines.append("")
    lines.append("*SO (SSoE or DPM)*")
    if so_b.primary:
        for it in so_b.primary:
            lines.extend(
                _format_tier3_person_line(
                    it,
                    why_fn=lambda r, av, rec, sk: _short_why_so_line(r, av, rec, sk),
                    project_staffing_rows=project_staffing_rows,
                )
            )
    else:
        lines.append("• _No pickable SO candidates (DPM/SoE) with current rules — check CSV SO status or escalate._")
    if so_b.alternate:
        lines.append("_Alternates (next in rank):_")
        lines.extend(_format_tier3_alternate_bullets(so_b.alternate, project_staffing_rows=project_staffing_rows))

    lines.append("")
    lines.append("*SoE*")
    if soe_b.primary:
        for it in soe_b.primary:
            lines.extend(
                _format_tier3_person_line(
                    it,
                    why_fn=lambda r, av, rec, sk: _short_why_role_line(r, av, rec, sk, "SoE"),
                    project_staffing_rows=project_staffing_rows,
                )
            )
    else:
        lines.append("• _No pickable SoE rows in this slice._")
    if soe_b.alternate:
        lines.append("_Alternates (next in rank):_")
        lines.extend(_format_tier3_alternate_bullets(soe_b.alternate, project_staffing_rows=project_staffing_rows))

    lines.append("")
    lines.append("*WFM / WFC*")
    if wfm_b.primary:
        for it in wfm_b.primary:
            lines.extend(
                _format_tier3_person_line(
                    it,
                    why_fn=lambda r, av, rec, sk: _short_why_role_line(r, av, rec, sk, "WFM/WFC"),
                    project_staffing_rows=project_staffing_rows,
                )
            )
    else:
        lines.append("• _No pickable WFM/WFC rows in this slice._")
    if wfm_b.alternate:
        lines.append("_Alternates (next in rank):_")
        lines.extend(_format_tier3_alternate_bullets(wfm_b.alternate, project_staffing_rows=project_staffing_rows))

    return "\n".join(lines)


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
) -> list[dict[str, Any]]:
    """Occupation rows for top recommended people (same order as Slack list / Tier 3 team blocks)."""
    tags = project_type_tags or []
    staffing = staffing_by_email if staffing_by_email is not None else load_staffing_records()
    scored = _staffing_full_scored(
        rows,
        tier=tier,
        decision_cfg=decision_cfg,
        project_type_tags=tags,
        summary=summary,
        staffing=staffing,
        project_staffing_rows=project_staffing_rows,
    )
    if tier == 3:
        so_b, soe_b, wfm_b = _tier3_team_slices(
            scored,
            project_staffing_rows=project_staffing_rows,
            decision_cfg=decision_cfg,
        )
        ordered_rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for it in (
            so_b.primary
            + soe_b.primary
            + wfm_b.primary
            + so_b.alternate
            + soe_b.alternate
            + wfm_b.alternate
        ):
            em = (email_value(it[0]) or "").strip().lower()
            if em:
                if em in seen:
                    continue
                seen.add(em)
            ordered_rows.append(it[0])
        return ordered_rows[:limit]

    pickable = [it for it in scored if _is_pickable_tuple(it)]
    return [it[0] for it in pickable[:limit]]


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
) -> str:
    """
    Primary + backup with People & Tags CSV (email), Comment / SO Status / Skills.

    *minimal* — top candidates and a short rationale only; no exclusion lists or UNVERIFIED.

    *project_staffing_rows* — optional snapshot from ``sql/project_staffing.sql`` (Databricks). For Tier 3,
    each candidate line can include *_On active orders:* with matching projects.
    """
    tags = project_type_tags or []
    staffing = staffing_by_email if staffing_by_email is not None else load_staffing_records()
    minimal = detail == "minimal"

    if not rows:
        return ""

    if tier is None:
        return (
            "*Recommendation: who can take the project*\n"
            "_Set Tier in Phase B (Node 1) — without Tier, automatic Node 2 role filtering does not apply._"
        )

    if tier not in (1, 2, 3, 4):
        return (
            f"*Recommendation: who can take the project*\n"
            f"_Tier {tier} is outside 1–4 — fix the classification in Phase B._"
        )

    role_filter = occupation_preview_roles(tier)
    if role_filter is None:
        return ""

    candidates = [r for r in rows if project_role_norm(r) in role_filter]
    if not candidates:
        return (
            "*Recommendation: who can take the project*\n"
            "_No rows with matching roles for this Tier in Occupation — check SQL or data._"
        )

    csv_loaded = bool(staffing)

    scored = _staffing_full_scored(
        rows,
        tier=tier,
        decision_cfg=decision_cfg,
        project_type_tags=tags,
        summary=summary,
        staffing=staffing,
        project_staffing_rows=project_staffing_rows,
    )
    pickable = [it for it in scored if _is_pickable_tuple(it)]

    unverified = [(r, av) for r, av, _, _, reas in scored if av.label == AvailabilityLabel.UNVERIFIED and reas is None]

    def _fmt(
        r: dict[str, Any],
        av: Any,
        rec: StaffingRecord | None,
        ps_reason: str | None = None,
    ) -> str:
        occ = occupation_value(r)
        pct = f"{float(occ) * 100:.0f}%" if occ is not None else "n/a"
        pr = project_role_norm(r) or "?"
        base = f"*`{pr}`*, {pct} → `{av.label.value}`"
        if rec:
            so = (rec.so_status or "—").strip() or "—"
            sm = skill_match_score(rec, tags, summary)
            sk_hint = f"skills match ≈ {sm}" if (tags or summary) and sm else ""
            extra = f" _SO Status: {so}_"
            if sk_hint:
                extra += f" _{sk_hint}_"
            if not minimal and (rec.comment or "").strip():
                extra += f" _Comment: {(rec.comment.strip())[:120]}{'…' if len(rec.comment.strip()) > 120 else ''}_"
            base = base + extra
        if ps_reason == "ps_scoping_discovery_only":
            base += f" _({gate_reason_label(ps_reason)})_"
        return base

    def _line(
        r: dict[str, Any],
        av: Any,
        rec: StaffingRecord | None,
        ps_reason: str | None = None,
    ) -> str:
        return f"• *{name_value(r)}* — {_fmt(r, av, rec, ps_reason)}"

    if tier == 3:
        body = _build_tier3_team_markdown(
            scored,
            minimal=minimal,
            csv_loaded=csv_loaded,
            project_staffing_rows=project_staffing_rows,
            decision_cfg=decision_cfg,
            project_type_tags=tags,
            summary=summary,
        )
        if minimal:
            return body
        lines = [body]
    else:
        if minimal:
            lines = [
                "*Recommendation*",
                _minimal_team_skills_why(tier, tags, summary),
            ]
        else:
            lines = [
                "*Recommendation: who can take the project* _(Tier + Occupation + People & Tags CSV by email)_",
            ]
            if csv_loaded:
                lines.append("_People & Tags table loaded; Comment / SO Status / Skills applied._")
            else:
                lines.append(
                    "_CSV file not found (`config/staffing_csv.yaml` / `STAFFING_PEOPLE_CSV_PATH`) — Databricks load only._"
                )

        if pickable:
            it0 = pickable[0]
            r0, av0, rec0, _, ps0 = it0[0], it0[1], it0[2], it0[3], it0[4]
            lines.append(
                f"• *First pick:* *{name_value(r0)}* — {_fmt(r0, av0, rec0, ps0)}"
            )
            rest = [x for x in pickable[1:4]]
            if rest:
                lines.append("*Alternates:*")
                for it in rest:
                    lines.append(_line(it[0], it[1], it[2], it[4]))
        else:
            if minimal:
                lines.append(
                    "_No FREE/PARTIAL/SOFT candidates with confirmed SO in the table — check CSV (email), Tier, or escalate._"
                )
            else:
                lines.append(
                    "_No FREE/PARTIAL/SOFT candidates without CSV blocks — see exclusions below or Node 5._"
                )

        if minimal:
            return "\n".join(lines)

    # Exclusion sections (full mode only)

    blocked_names = [(name_value(r), rec.comment[:80] if rec else "") for r, av, rec, _, reas in scored if reas == "blocked_comment"]
    if blocked_names:
        lines.append("*Excluded by Comment (do not staff):*")
        for nm, c in blocked_names[:15]:
            lines.append(f"• *{nm}* — `…{c}…`" if c else f"• *{nm}*")

    not_so_names = [name_value(r) for r, av, rec, _, reas in scored if reas == "not_so"]
    if not_so_names:
        lines.append("*Not suitable as SO / responsible (not SO / not can be SO in table):*")
        for nm in not_so_names[:20]:
            lines.append(f"• {nm}")
        if len(not_so_names) > 20:
            lines.append(f"… _{len(not_so_names) - 20} more_")

    no_csv_names = [name_value(r) for r, av, rec, _, reas in scored if reas == "no_csv"]
    if no_csv_names:
        lines.append("*No CSV row for email — SO for SoE/DPM not confirmed:*")
        for nm in no_csv_names[:20]:
            lines.append(f"• {nm}")

    ps_gates = [
        (name_value(r), reas)
        for r, av, rec, _, reas in scored
        if reas and str(reas).startswith("ps_") and reas != "ps_scoping_discovery_only"
    ]
    if ps_gates:
        lines.append("*Project snapshot staffing gates (excluded from picks):*")
        for nm, reas in ps_gates[:25]:
            lines.append(f"• *{nm}* — _{gate_reason_label(reas)}_")
        if len(ps_gates) > 25:
            lines.append(f"… _{len(ps_gates) - 25} more_")

    if unverified:
        lines.append("*UNVERIFIED (0% load — after manager; CSV does not override UNVERIFIED):*")
        for r, av in unverified[:MAX_UNVERIFIED_LINES]:
            em = email_value(r)
            rec_uv = staffing.get(em) if em else None
            lines.append(_line(r, av, rec_uv, None))
        if len(unverified) > MAX_UNVERIFIED_LINES:
            lines.append(
                f"… _{len(unverified) - MAX_UNVERIFIED_LINES} more in UNVERIFIED (see Databricks)._"
            )

    busy_only = [r for r, av, _, _, reas in scored if av.label == AvailabilityLabel.BUSY and reas is None]
    if not pickable and busy_only and not unverified:
        lines.append("_All candidates are BUSY — escalate / Node 5._")

    lines.append(
        "_Summary: Occupation + PTO; CSV — staffing rules; cross-check with calendar._"
    )
    return "\n".join(lines)
