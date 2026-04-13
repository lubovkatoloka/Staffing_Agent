"""Slack copy for Node 3 checklist + Node 4 / 4.5 / 5 (Decision Logic v1.0) — next-step guidance."""

from __future__ import annotations

from typing import Optional

NOTION_DL = "https://www.notion.so/toloka-ai/Staffing-Agent-Decision-Logic-v1-0-32749d0688568183af3bf80ff6aedfd4"


def node3_checklist_intro() -> str:
    return (
        "*Node 3 — что делаем (по спеке)*\n"
        "1. *Occupation SQL* — коэффициенты по матрице, суммарная загрузка по ролям на проектах.\n"
        "2. *PTO SQL* — кто в отпуске / out today (отдельный запрос ниже).\n"
        "3. В финальной таблице уже есть `project_occupation`, `pto` и итог `occupation` "
        "(как в Notion: total = project + PTO-коэффициент).\n"
        "4. Полосы *FREE / PARTIAL / BUSY / …* — из `config/decision_logic.yaml`; "
        "*UNVERIFIED* при 0% без подтверждённой занятости — по спеке, не FREE.\n"
        "5. *Tier из Phase B (Node 1)* задаёт, *кого стафим*; таблица Occupation ниже при известном Tier "
        "показывает только роли из Node 2 (например Tier 2 → SoE/DPM).\n"
        f"_Полная спека:_ <{NOTION_DL}|Decision Logic v1.0>\n"
    )


def node4_section_markdown(tier: Optional[int]) -> str:
    tier_hint = ""
    if tier == 2:
        tier_hint = (
            "_Ваш Tier 2: минимальная команда = *SO (SoE или DPM)*; "
            "WFM/QM в составе Tier 2 по умолчанию не требуются для «есть ли матч»._\n"
        )
    lines = [
        "*Node 4 — Is there a match?*",
        "*Целевой состав по Tier (из спеки):*",
        "• Tier 1 — SO (DPM или WFM) + WFM + QM",
        "• Tier 2 — SO (SoE или DPM в роли SO)",
        "• Tier 3 — SO (SSoE или DPM) + SoE + WFM",
        "• Tier 4 — SO (DPM) + SSoE + SoE + WFM + Commercial",
        "",
        "*Match* = по каждой *требуемой* роли есть хотя бы один кандидат *FREE* или *SOFT*.",
        "*Если YES* — предложить состав; *если NO* — какие роли не закрыты → Node 5.",
        "",
        "*Ранжирование (Tier 1–2, domain не обязателен):* availability → SO status → seniority.",
        "*Ранжирование (Tier 3–4):* сначала *domain / tag overlap*, затем availability → SO status → seniority.",
        tier_hint,
        f"_Детали:_ <{NOTION_DL}|Decision Logic — Node 4>",
    ]
    return "\n".join(lines)


def node4_5_section_markdown() -> str:
    return (
        "*Node 4.5 — Freeing up soon*\n"
        "_Люди, которые сейчас заняты, но освобождаются в горизонте ~8 недель — для планирования заранее._\n"
        f"_Спека:_ <{NOTION_DL}|Node 4.5>"
    )


def node5_section_markdown() -> str:
    return (
        "*Node 5 — Can we rebalance?*\n"
        "Если нет полного матча: можно ли *освободить* кого-то с SOFT/BUSY (доноры: дедлайн на неделе, "
        "discovery/scoping как доноры, статус AT_RISK/BEHIND блокирует и т.д.).\n"
        "*Если NO* — эскалация Directors / Delivery Leads.\n"
        f"_Спека:_ <{NOTION_DL}|Node 5>"
    )


def node3_checklist_intro_compact() -> str:
    """Один абзац вместо длинного чеклиста Node 3."""
    return (
        "_Загрузка: Occupation SQL + PTO в Databricks; полосы FREE/PARTIAL из `config/decision_logic.yaml`; "
        f"Tier из Phase B задаёт фильтр ролей. Спека: <{NOTION_DL}|Decision Logic v1.0>._"
    )


def followup_decision_nodes_compact(tier: Optional[int]) -> str:
    """Node 4–5 без таблиц — только ссылки и одна строка по матчу."""
    th = ""
    if tier == 2:
        th = "_Tier 2: достаточно одного SO (SoE или DPM)._ "
    return (
        "*Дальше по Decision Logic*\n"
        f"{th}"
        "• Node 4 — матч состава / ранжирование — "
        f"<{NOTION_DL}|спека>\n"
        f"• Node 4.5 — freeing up soon — <{NOTION_DL}|спека>\n"
        f"• Node 5 — rebalance — <{NOTION_DL}|спека>\n"
        "_Полные таблицы и выгрузки — в Databricks / Notion, не в этом сообщении._"
    )
