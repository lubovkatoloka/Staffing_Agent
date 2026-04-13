"""
Slack reply shape for @mention pipeline (paste_run + socket).

**Цель:** не засыпать пользователя сырыми таблицами; держать «ответ бота» читаемым.

## Шаблон ответа (порядок секций)

1. **Phase A — context** — кратко: число сообщений, URL, текст треда (preview).
2. **Phase B — extraction (Node 1)** — JSON `RequestSpec` (tier, теги, summary).
3. **Node 2** — правила пула по Tier (коротко).
4. **Node 3 — availability** (Databricks):
   - **compact (по умолчанию):** сначала *Рекомендация: кто может взять проект*, затем короткая сводка загрузки
     (первые N строк Occupation по Tier-фильтру), PTO и Active projects — только счётчики/имена, без простыней.
   - **full:** длинный чеклист спеки, до 15 строк таблицы, ведра по ролям, полные выборки optional SQL.
5. **Decision Logic — follow-up** — в compact: одна строка + ссылки на Notion; в full: развёрнутые Node 4 / 4.5 / 5.
6. **Похожие проекты** — опционально из CSV «Projects & Offers Classification» (`config/projects_classification.yaml`) по тегам Phase B.
7. **Phase C** — демо полос + подсказка DBX (коротко).

Переключение: env `STAFFING_AGENT_REPLY_STYLE` = `minimal` | `compact` | `full` (default: minimal).

- **minimal** — краткое саммари запроса + рекомендация и короткое «почему» (без JSON, без списков исключений, без PTO/похожих проектов/Phase C).
- **compact** — саммари + Node 2–3 с превью Occupation; без PTO/active/follow-up/похожих/Phase C.
- **full** — полный вывод (как раньше).
"""

from __future__ import annotations

import os
from typing import Literal

ReplyStyle = Literal["minimal", "compact", "full"]


def reply_style() -> ReplyStyle:
    v = (os.environ.get("STAFFING_AGENT_REPLY_STYLE") or "minimal").strip().lower()
    if v == "full":
        return "full"
    if v == "compact":
        return "compact"
    return "minimal"


# Лимиты для compact-режима
COMPACT_OCCUPATION_PREVIEW_ROWS = 5
FULL_OCCUPATION_PREVIEW_ROWS = 15
COMPACT_PTO_NAME_SAMPLES = 5
