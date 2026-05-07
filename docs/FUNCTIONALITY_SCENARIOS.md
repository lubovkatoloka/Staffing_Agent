# Staffing Agent — функциональность и сценарии проверки

Документ для регрессии: что делает бот, из чего состоит ответ, как проверять по сценариям. Корень репозитория — папка с каталогом `staffing_agent/`.

---

## 1. Назначение

Slack-бот (Socket Mode): по `@mention` в треде собирает **контекст**, прогоняет **классификацию (LLM)**, при необходимости дергает **Databricks** (Occupation, опционально project staffing), формирует ответ с **правилами Decision Logic** и **рекомендациями по ролям**.

---

## 2. Поток обработки (высокоуровнево)

| Этап | Что делает | Где в коде |
|------|------------|------------|
| Сбор треда | `conversations.replies`, исключение сообщений бота | `slack_app.py` |
| Phase A | Превью треда, ссылки Notion/Google Docs, вытягивание текста по ссылкам | `thread_context.py` |
| Phase B (Node 1) | JSON `RequestSpec`: `thread_kind`, `tier`, теги, summary, rationale | `extraction.py` + промпт из `config/tier_classification.yaml` |
| Маршрут Node 3 | По тексту треда: **team capacity** / **узкая роль** / **проект с tier** | `paste_run.py` + `intent.py` |
| Node 2 | Текстовые правила пула по tier (или пояснение для capacity/role-focus) | `decision/node2_rules.py`, `paste_run.py` |
| Node 3 | Occupation SQL, PTO/active projects (в зависимости от стиля), рекомендации | `node3_occupation.py`, `node4_recommendation.py` |
| Team capacity | Отдельный снимок по ролям (SO, SoE, DPM, WFM, QM) + слоты + gates | `team_capacity.py` |
| Phase C / прочее | Демо-полосы, подсказки DBX (в `full`) | `slack_phase_c.py`, `spec_nodes_slack.py` |

---

## 2.1. Ожидаемый результат (expected) на каждом шаге — общий поток

Условие: успешный `@mention`, валидные токены Slack, для сценариев с Databricks — рабочий `DATABRICKS_PROFILE`. Ниже «в ответе» = итоговое сообщение бота в треде.

| № | Шаг | Действие | Expected result (успех) | Expected result (сбой / край) |
|---|-----|----------|---------------------------|-------------------------------|
| 0 | Slack | Событие `app_mention` | В логах stderr: `app_mention received`, известны `channel`, `thread_ts` | Нет события → в Slack App включён `app_mention`, бот в канале |
| 1 | Сбор треда | `conversations.replies` | `messages` ≥ 1 после фильтра бота; `thread_plain` — склеенный текст | `Could not load thread` в Slack |
| 2 | Phase A | Notion / Google превью | К `phase_b_excerpt_for_llm` добавлен текст по ссылкам (или пустой блок `(none)`). **full:** в ответе есть блок контекста с перечнем ссылок/превью | 403 Notion / нет credentials Google → ссылка без текста, excerpt короче |
| 3 | Phase B | `extract_request_spec` | Валидный `RequestSpec`: хотя бы `summary` или `tier_rationale`; `thread_kind` из допустимых; `confidence` 0..1. В **full:** в ответе JSON-блок Phase B. **minimal:** краткий brief (tier line + summary), без JSON | `Extraction failed` в summary; `notes` с текстом ошибки; возможен `anthropic_rescue` / `anthropic_fallback` (см. S6) |
| 4 | Источник Phase B | Метка в ответе | **full:** строка `_(source: …)_` — `Anthropic Opus` / `mock` / `anthropic_rescue` / … | `error` — смотреть `notes` |
| 5 | Маршрут Node 3 | `build_slack_mention_reply` | Ровно одна ветка: **capacity** ИЛИ **only_role** ИЛИ **node3_slack (tier)** ИЛИ **заглушка контекст** | Две ветки одновременно недопустимы: сначала capacity, иначе role при `tier is None`, иначе tier |
| 6 | Node 2 | Текст правил пула | **capacity:** «tier не обязателен… Occupation». **role-focus:** узкий список. **tier:** «Node 2 — … Tier N» с FTE/пулом | При `tier=null` и не capacity/не role — «Set tier…» в классическом Node 2 (через `node2_slack_markdown`) |
| 7a | Тело: team capacity | `build_live_capacity_markdown` | 1–2 запроса Databricks: `occupation.sql`, `project_staffing.sql`. В ответе: `*Team capacity*`, секции ролей, `*Primary:*` / `*Alternate:*`, слоты Tier 1–4, опц. Hold | `Occupation query failed` + текст CLI; `no_profile` / `no_sql` — короткое сообщение без таблиц |
| 7b | Тело: role shortlist | `build_live_capacity_markdown(only_role=…)` | Как 7a, но одна роль + заголовок `role shortlist` | Та же ошибка DBX |
| 7c | Тело: проект с tier | `node3_slack_markdown` + Node 4 | Databricks: occupation (+ опц. PTO/active по стилю). В ответе: `*Node 3*`, превью ролей, **Recommendation** / bullets с primary/alternates для Tier 3 | Тот же `Occupation query failed` |
| 7d | Тело: нет сценария | Заглушка | Текст «нужен контекст» + примеры фраз | — |
| 8 | Phase C / хвост | `build_phase_c_section` и др. | **full:** секции Phase C, похожие проекты (если CSV). **minimal:** обычно без Phase C | — |
| 9 | Постинг | `chat_postMessage` | Одно сообщение в треде, длина ≤ ~12k (усечение с пометкой) | Ошибка Slack API в логах |

### Ожидаемое содержимое ответа по `STAFFING_AGENT_REPLY_STYLE`

| Режим | Обязательно присутствует (expected) | Обычно отсутствует |
|-------|--------------------------------------|---------------------|
| **minimal** | Краткий Phase B brief (tier/tags/summary в тексте); Node 2; основной блок (capacity ИЛИ Node 3 ИЛИ заглушка) | JSON Phase A/B, Phase C, длинные таблицы |
| **compact** | Как minimal + чуть больше Node 3-структуры при tier | Phase C, часть follow-up |
| **full** | Phase A контекст; JSON Phase B; Node 2; Node 3/capacity; Phase C; при настройке — similar projects | — |

### Expected по сценариям — покомпонентно

**S1 Team capacity**

| Шаг | Expected |
|-----|----------|
| Phase B | Часто `tier=null`, `thread_kind` может быть `capacity_question` или другое — на маршрут не опираться |
| Маршрут | `is_team_capacity_query` = true |
| Node 2 | Текст про «tier не обязателен», Occupation |
| Тело | `Team capacity`, все роли, Primary/Alternate, слоты, при наличии snapshot — строки про `project_staffing` / Hold |
| Не expected | Долгая лекция «задайте tier» вместо таблиц |

**S2 Single role**

| Шаг | Expected |
|-----|----------|
| Phase B | Может быть `tier` set или null; при **непустом tier** маршрут уйдёт в S3, не в S2 |
| Маршрут | `single_role_focus_from_thread` ≠ None и `tier is None` и не S1 |
| Тело | `role shortlist`, одна роль, Primary/Alternate |
| Не expected | Полный пяти-ролевой capacity-блок |

**S3 Проект с tier**

| Шаг | Expected |
|-----|----------|
| Phase B | `tier` ∈ {1,2,3,4}, желательно `complexity_class` |
| Маршрут | Не capacity, не only_role (при наличии tier) |
| Тело | `Node 3`, фильтр ролей по tier, Recommendation (Tier 3+: SO/SoE/WFM с alternates) |
| Не expected | Только team capacity без Node 3 |

**S4 Deal FYI**

| Шаг | Expected |
|-----|----------|
| Phase B | `deal_notification`, `tier=null` типично |
| Маршрут | Не S1/S2, нет tier |
| Тело | Brief + заглушка «нужен контекст» |
| Не expected | Полный Occupation без запроса |

**S5 Deal + availability**

| Шаг | Expected |
|-----|----------|
| Phase B | tier может быть выставлен гипотезой ИЛИ остаться null при явном только capacity-слове |
| Маршрут | Если есть «team capacity» / who is available в допустимой форме → S1; иначе возможен tier hint |
| Тело | Либо capacity (как S1), либо проектный путь с tier (как S3) |
| Не expected | Пустой tier + только заглушка при явном S1-триггере |

**S6 Ошибка LLM**

| Шаг | Expected |
|-----|----------|
| Phase B | `src` = `error` / `anthropic_fallback` / `anthropic_rescue` |
| Тело | При rescue: непустой tier из текста; при fallback deal: краткий summary; при error: `Extraction failed` + notes |
| Проверка | Лог stderr: `extraction failed` |

---

## 3. Режимы ответа (`STAFFING_AGENT_REPLY_STYLE`)

| Значение | Поведение |
|----------|-----------|
| `minimal` (по умолчанию) | Краткий brief Phase B + Node 2/3 без JSON, без Phase C в полном виде |
| `compact` | Больше секций Node 2–3, без части хвоста |
| `full` | Phase A + JSON Phase B + Node 2–3 + Phase C + похожие проекты (если настроено) |

Переменная читается при каждом ответе (перезапуск не обязателен при смене, если процесс перечитает env — для надёжности после смены `.env` лучше перезапустить бота).

---

## 4. Сценарии Slack (главная матрица)

Ниже: **что написать в треде** → **ожидаемое поведение** → **как проверить**.

### S1 — Снимок загрузки команды (без tier)

| Поле | Значение |
|------|----------|
| **Триггер** | Фразы вроде `Team capacity`, `who is available`, `кто свободен`, `загрузка команды`; bare `@bot` в треде **без** deal-feed эвристики |
| **Логика** | `is_team_capacity_query` → `build_live_capacity_markdown()` |
| **Ожидание** | Блок **Team capacity**: роли SO / SoE / DPM / WFM / QM; у каждой секции **Primary** и **Alternate**; оценка слотов Tier 1–4; при наличии SQL — **project_staffing** gates по tier на роль |
| **Не ожидать** | Сообщение «Tier required» / «нужен tier» для этого запроса |
| **Проверка** | Databricks профиль валиден; `sql/occupation.sql` не пустой; в ответе есть `Team capacity` и `Primary` |

### S2 — Узкий запрос по одной роли (tier в Phase B может быть null)

| Поле | Значение |
|------|----------|
| **Триггер** | Явные need/want/hire/… + **SoE / DPM / WFM / QM** (и т.п.), **без** фраз team capacity; пример: `need 1 SOE tier 3 …` |
| **Логика** | `single_role_focus_from_thread` → `build_live_capacity_markdown(only_role=…)` |
| **Ожидание** | Заголовок **role shortlist**, одна роль, Primary + Alternates, snapshot gates для соответствующего tier gate |
| **Проверка** | В ответе нет полного списка всех ролей capacity; есть только выбранная роль |

### S3 — Проект с tier (подбор команды)

| Поле | Значение |
|------|----------|
| **Триггер** | Phase B выставляет `tier` 1–4 (явный staffing / deal + availability / хинты из промпта) |
| **Логика** | `node3_slack_markdown` + рекомендации Node 4 (в т.ч. Tier 3: SO / SoE / WFM, primary + alternates) |
| **Ожидание** | Occupation превью по tier-ролям, блок **Recommendation** с кандидатами |
| **Проверка** | В brief есть `Tier N`; в теле — Node 3 и рекомендации, не только capacity-таблица |

### S4 — Deal-feed (Attio) без staffing

| Поле | Значение |
|------|----------|
| **Триггер** | Тред с `Attio`, `deal value`, `deals-new` и т.д., **без** явного team capacity / без tier |
| **Логика** | Phase B часто `deal_notification`, `tier=null`; Node 3 — заглушка «нужен контекст» **если** нет team capacity и нет single-role |
| **Ожидание** | Краткое описание сделки; без Occupation, если нет S1/S2/S3 |
| **Проверка** | Нет ложного полного capacity на чистом FYI |

### S5 — Deal-feed + availability ping

| Поле | Значение |
|------|----------|
| **Триггер** | Deal контекст + `who_is_available` / team capacity / русские аналоги |
| **Логика** | Промпт + `apply_deal_feed_availability_tier_hint` могут выставить гипотезу tier; либо capacity если сработал S1 |
| **Ожидание** | Не застревать в «tier null» только из-за отсутствия слова «staff»; при явном capacity — см. S1 |
| **Проверка** | Тред из продуктовых примеров (Shopify + @who) даёт либо tier/gипотезу, либо capacity |

### S6 — Ошибка Phase B (LLM / JSON)

| Поле | Значение |
|------|----------|
| **Триггер** | Сбой API, невалидный JSON, validation |
| **Логика** | `anthropic_fallback` (deal), `anthropic_rescue` (явный tier в тексте + staffing), иначе `error` с notes |
| **Ожидание** | В Slack source видно rescue/fallback; при явном `tier 3` в тексте — не пустой tier |
| **Проверка** | Юнит-тесты `tests/test_extraction.py` |

---

## 5. Databricks и SQL

| Ресурс | Назначение | Переменные / файлы |
|--------|------------|---------------------|
| Occupation | Загрузка %, роли, рекомендации | `DATABRICKS_PROFILE`, `sql/occupation.sql`, опц. `STAFFING_OCCUPATION_SQL_PATH` |
| Project staffing | Активные заказы, gates (building/stab, …) | `sql/project_staffing.sql`, опц. `STAFFING_PROJECT_STAFFING_SQL_PATH` |
| PTO / Active | Опциональные секции в full/compact | `sql/pto.sql`, `sql/active_projects.sql` |

CLI: `databricks experimental aitools tools query` с `--profile`.

Проверки перед запуском бота:

```bash
python3 -m staffing_agent --check      # Slack + DBX SELECT 1 при профиле
python3 -m staffing_agent --check-dbx # только Databricks
```

---

## 6. People & Tags (CSV)

| Файл | Назначение |
|------|------------|
| `config/staffing_csv.yaml` | Путь к CSV, паттерны `do not staff` в Comment |
| `config/notion_export/staffing_people_tags*.csv` | SO status, skills, комментарии блокировки |

Сопоставление с Occupation по **email**. Блокировка по Comment не даёт попасть в рекомендации/capacity.

---

## 7. Конфиг логики

| Файл | Содержимое |
|------|------------|
| `config/decision_logic.yaml` | Полосы занятости, `staffing_ps_gates`, tier3_recommendation, … |
| `config/tier_classification.yaml` | Правила Phase B для LLM, `framework_alignment`, deal + availability |

---

## 8. Переменные окружения (основные)

| Переменная | Назначение |
|------------|------------|
| `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_SIGNING_SECRET` | Slack |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `LITELLM_BASE_URL` | LLM |
| `STAFFING_AGENT_MOCK_LLM=1` | Мок без Anthropic |
| `DATABRICKS_PROFILE` | Профиль CLI Databricks |
| `STAFFING_AGENT_REPLY_STYLE` | `minimal` / `compact` / `full` |
| `STAFFING_FORCE_TIER` | Принудительно tier 1–4 (отладка) |
| `STAFFING_DEAL_AVAILABILITY_TIER_HINT=0` | Отключить пост-хинт tier для deal+who_is_available |
| `NOTION_TOKEN` | Опционально: превью Notion |
| `STAFFING_GOOGLE_APPLICATION_CREDENTIALS` | Опционально: Google Docs |

---

## 9. CLI (кроме бота)

| Команда | Назначение |
|---------|------------|
| `python3 -m staffing_agent --check` | Slack + DBX smoke |
| `python3 -m staffing_agent --check-llm` | Проверка модели |
| `python3 -m staffing_agent --check-dbx` | Только DBX |
| `python3 -m staffing_agent --process-paste FILE` | Прогон Phase A–C на файле |
| `python3 -m pytest tests/ -q` | Тесты |

---

## 10. Автотесты по областям

| Папка / файл | Что покрывает |
|----------------|----------------|
| `tests/test_intent.py` | Team capacity, deal-feed, single-role hint |
| `tests/test_extraction.py` | Phase B, rescue, normalize, deal hint |
| `tests/test_team_capacity.py` | Capacity markdown, gates, only_role |
| `tests/test_project_staffing_gates.py` | Порядок gates |
| `tests/test_node4_recommendation.py` | Рекомендации, pickable |
| `tests/test_paste_run.py` | Маршрут capacity vs tier |

---

## 11. Перезапуск бота после изменений кода

Код подхватывается только после перезапуска процесса:

```bash
cd "/Users/liubakarpova/Documents/Staffing Agent"
source .venv/bin/activate
python3 -m staffing_agent --check
python3 -m staffing_agent
```

(Путь `cd` заменить на свой корень репозитория.)

---

## 12. Чек-лист быстрой регрессии (ручной)

1. **S1:** `Team capacity @who_is_available` → полный capacity, Primary/Alternate, без «нужен tier».
2. **S2:** `need 1 SOE tier 3, coding @bot` → role shortlist SoE (при `tier=null` в Phase B) или полный Node 3 при извлечённом tier.
3. **S3:** Тред с явным проектом и tier → Recommendation + роли.
4. **DBX:** `--check` зелёный; при ошибке refresh token — `databricks auth login --profile <profile>`.
5. **CSV:** человек с `do not staff` в Comment не в списках.

---

*Версия документа: по состоянию репозитория; при смене поведения обновляйте таблицы сценариев, раздел 2.1 и раздел 10.*
