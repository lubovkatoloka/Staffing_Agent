"""
Who can take the project — ranked recommendation from Occupation rows + People & Tags CSV (email join).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from staffing_agent.decision import classify_availability
from staffing_agent.decision.enums import AvailabilityLabel
from staffing_agent.node3_row_utils import email_value, name_value, occupation_value, project_role_norm
from staffing_agent.node3_tier_preview import occupation_preview_roles
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
    """SO / responsible по таблице — только для SoE/DPM."""
    return (project_role or "").strip().lower() in ("soe", "dpm")


def build_project_recommendation_markdown(
    rows: list[dict[str, Any]],
    *,
    tier: Optional[int],
    decision_cfg: Mapping[str, Any],
    project_type_tags: Optional[list[str]] = None,
    summary: str = "",
    staffing_by_email: Optional[dict[str, StaffingRecord]] = None,
) -> str:
    """
    Primary + backup with People & Tags CSV (email), Comment / SO Status / Skills.
    """
    tags = project_type_tags or []
    st_cfg = load_staffing_table_config()
    staffing = staffing_by_email if staffing_by_email is not None else load_staffing_records()

    if not rows:
        return ""

    if tier is None:
        return (
            "*Рекомендация: кто может взять проект*\n"
            "_Задайте Tier в Phase B (Node 1) — без Tier автоматический отбор по ролям Node 2 не применяется._"
        )

    if tier not in (1, 2, 3, 4):
        return (
            f"*Рекомендация: кто может взять проект*\n"
            f"_Tier {tier} вне диапазона 1–4 — уточните классификацию в Phase B._"
        )

    role_filter = occupation_preview_roles(tier)
    if role_filter is None:
        return ""

    candidates = [r for r in rows if project_role_norm(r) in role_filter]
    if not candidates:
        return (
            "*Рекомендация: кто может взять проект*\n"
            "_Нет строк с подходящими ролями для этого Tier в выдаче Occupation — проверьте SQL или данные._"
        )

    csv_loaded = bool(staffing)

    scored: list[tuple[dict[str, Any], Any, StaffingRecord | None, int, str | None]] = []
    # tuple: row, availability, staffing_record|None, skill_score, exclude_reason or None
    # exclude_reason: "blocked_comment" | "not_so" | "no_csv" (no_csv only blocks primary tier for SO roles)
    for r in candidates:
        av = _classify_row(r, decision_cfg)
        em = email_value(r)
        rec = staffing.get(em) if em else None
        sk = skill_match_score(rec, tags, summary) if rec else 0
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
        scored.append((r, av, rec, sk, reason))

    def sort_key(
        it: tuple[dict[str, Any], Any, StaffingRecord | None, int, str | None],
    ) -> tuple[int, int, float, int]:
        r, av, _rec, sk, reason = it
        # eligible for primary: no blocking reason
        eligible = reason is None
        occ = occupation_value(r) if occupation_value(r) is not None else 1.0
        # non-eligible last within same availability
        bucket = 0 if eligible else 1
        return (
            bucket,
            -sk,
            _label_rank(av.label),
            occ,
        )

    scored.sort(key=sort_key)

    good_labels = frozenset(
        {
            AvailabilityLabel.FREE,
            AvailabilityLabel.PARTIAL,
            AvailabilityLabel.SOFT,
        }
    )

    def is_pickable(it: tuple) -> bool:
        r, av, _rec, _sk, reason = it
        return av.label in good_labels and reason is None

    pickable = [it for it in scored if is_pickable(it)]

    unverified = [(r, av) for r, av, _, _, reas in scored if av.label == AvailabilityLabel.UNVERIFIED and reas is None]

    lines: list[str] = [
        "*Рекомендация: кто может взять проект* _(Tier + Occupation + People & Tags CSV по email)_",
    ]
    if csv_loaded:
        lines.append("_Таблица People & Tags загружена; Comment / SO Status / Skills учтены._")
    else:
        lines.append(
            "_Файл CSV не найден (`config/staffing_csv.yaml` / `STAFFING_PEOPLE_CSV_PATH`) — только загрузка из Databricks._"
        )

    def _fmt(r: dict[str, Any], av: Any, rec: StaffingRecord | None) -> str:
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
            if (rec.comment or "").strip():
                extra += f" _Comment: {(rec.comment.strip())[:120]}{'…' if len(rec.comment.strip()) > 120 else ''}_"
            return base + extra
        return base

    def _line(r: dict[str, Any], av: Any, rec: StaffingRecord | None) -> str:
        return f"• *{name_value(r)}* — {_fmt(r, av, rec)}"

    if pickable:
        it0 = pickable[0]
        r0, av0 = it0[0], it0[1]
        rec0 = it0[2]
        lines.append(f"• *Первый выбор:* *{name_value(r0)}* — {_fmt(r0, av0, rec0)}")
        rest = [x for x in pickable[1:4]]
        if rest:
            lines.append("*Запас:*")
            for it in rest:
                lines.append(_line(it[0], it[1], it[2]))
    else:
        lines.append(
            "_Нет кандидатов FREE/PARTIAL/SOFT без блокировок CSV — см. исключения ниже или Node 5._"
        )

    # Exclusion sections
    blocked_names = [(name_value(r), rec.comment[:80] if rec else "") for r, av, rec, _, reas in scored if reas == "blocked_comment"]
    if blocked_names:
        lines.append("*Исключены по Comment (не стаффить):*")
        for nm, c in blocked_names[:15]:
            lines.append(f"• *{nm}* — `…{c}…`" if c else f"• *{nm}*")

    not_so_names = [name_value(r) for r, av, rec, _, reas in scored if reas == "not_so"]
    if not_so_names:
        lines.append("*Не подходят как SO / responsible (в таблице не SO / not can be SO):*")
        for nm in not_so_names[:20]:
            lines.append(f"• {nm}")
        if len(not_so_names) > 20:
            lines.append(f"… _ещё {len(not_so_names) - 20}_")

    no_csv_names = [name_value(r) for r, av, rec, _, reas in scored if reas == "no_csv"]
    if no_csv_names:
        lines.append("*Нет строки в CSV по email — SO для SoE/DPM не подтверждён:*")
        for nm in no_csv_names[:20]:
            lines.append(f"• {nm}")

    if unverified:
        lines.append("*UNVERIFIED (загрузка 0% — после менеджера; CSV не отменяет UNVERIFIED):*")
        for r, av in unverified[:MAX_UNVERIFIED_LINES]:
            em = email_value(r)
            rec_uv = staffing.get(em) if em else None
            lines.append(_line(r, av, rec_uv))
        if len(unverified) > MAX_UNVERIFIED_LINES:
            lines.append(
                f"… _и ещё {len(unverified) - MAX_UNVERIFIED_LINES} в UNVERIFIED (см. Databricks)._"
            )

    busy_only = [r for r, av, _, _, reas in scored if av.label == AvailabilityLabel.BUSY and reas is None]
    if not pickable and busy_only and not unverified:
        lines.append("_Все кандидаты в статусе BUSY — эскалация / Node 5._")

    lines.append(
        "_Итог: Occupation + PTO; CSV — правила стаффинга; сверьте с календарём._"
    )
    return "\n".join(lines)
