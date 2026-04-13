"""
Who can take the project — ranked recommendation from Occupation rows + People & Tags CSV (email join).
"""

from __future__ import annotations

from typing import Any, Literal, Mapping, Optional

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


def _staffing_full_scored(
    rows: list[dict[str, Any]],
    *,
    tier: Optional[int],
    decision_cfg: Mapping[str, Any],
    project_type_tags: list[str],
    summary: str,
    staffing: dict[str, StaffingRecord],
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
        scored.append((r, av, rec, sk, reason))

    def sort_key(
        it: tuple[dict[str, Any], Any, StaffingRecord | None, int, str | None],
    ) -> tuple[int, int, float, int]:
        r, av, _rec, sk, reason = it
        eligible = reason is None
        occ = occupation_value(r) if occupation_value(r) is not None else 1.0
        bucket = 0 if eligible else 1
        return (bucket, -sk, _label_rank(av.label), occ)

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
    return av.label in good_labels and reason is None


def pickable_recommendation_rows(
    rows: list[dict[str, Any]],
    *,
    tier: Optional[int],
    decision_cfg: Mapping[str, Any],
    project_type_tags: Optional[list[str]] = None,
    summary: str = "",
    staffing_by_email: Optional[dict[str, StaffingRecord]] = None,
    limit: int = 4,
) -> list[dict[str, Any]]:
    """Occupation rows for top recommended people (same order as Slack list)."""
    tags = project_type_tags or []
    staffing = staffing_by_email if staffing_by_email is not None else load_staffing_records()
    scored = _staffing_full_scored(
        rows,
        tier=tier,
        decision_cfg=decision_cfg,
        project_type_tags=tags,
        summary=summary,
        staffing=staffing,
    )
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
) -> str:
    """
    Primary + backup with People & Tags CSV (email), Comment / SO Status / Skills.

    *minimal* — только топ-кандидаты и короткое обоснование; без списков исключений и UNVERIFIED.
    """
    tags = project_type_tags or []
    staffing = staffing_by_email if staffing_by_email is not None else load_staffing_records()
    minimal = detail == "minimal"

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

    scored = _staffing_full_scored(
        rows,
        tier=tier,
        decision_cfg=decision_cfg,
        project_type_tags=tags,
        summary=summary,
        staffing=staffing,
    )
    pickable = [it for it in scored if _is_pickable_tuple(it)]

    unverified = [(r, av) for r, av, _, _, reas in scored if av.label == AvailabilityLabel.UNVERIFIED and reas is None]

    if minimal:
        lines = [
            "*Рекомендация*",
            "_Почему:_ занятость из сводки Occupation (Databricks), роль SoE/DPM под этот Tier, "
            "в People & Tags — статус SO / can be SO и близость skills к тегам запроса. "
            "Перед слотом сверьте календарь и актуальные заказы в SCM — Node 3–5 в спеке это проверочные шаги._",
        ]
    else:
        lines = [
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
            if not minimal and (rec.comment or "").strip():
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
        if minimal:
            lines.append(
                "_Нет кандидатов FREE/PARTIAL/SOFT с подтверждённым SO в таблице — проверьте CSV (email), Tier или эскалация._"
            )
        else:
            lines.append(
                "_Нет кандидатов FREE/PARTIAL/SOFT без блокировок CSV — см. исключения ниже или Node 5._"
            )

    # Exclusion sections (not in minimal — ответ только с топ-кандидатами)
    if minimal:
        return "\n".join(lines)

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
