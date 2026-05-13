# Databricks MCP в Cursor: пошаговый гайд

Этот гайд настраивает доступ агента Cursor к **управляемому MCP-серверу Databricks** через **`uc-mcp-proxy`** и авторизацию **Databricks CLI**. В репозитории есть `.cursor/mcp.json` и скрипт `.cursor/run-databricks-mcp.sh`, который **читает `DATABRICKS_MCP_URL` из `.env`** (подстановка `${env:...}` в `args` у Cursor не берёт значения из `envFile`, из‑за этого URL мог оказаться пустым и падал прокси с `UnsupportedProtocol`).

Официальная схема: [Connect non-Databricks clients to Databricks MCP servers](https://learn.microsoft.com/azure/databricks/generative-ai/mcp/connect-external-services) (раздел Cursor / Databricks CLI + `uc-mcp-proxy`).

---

## Что понадобится

- Учётная запись в Databricks и URL воркспейса (например `https://dbc-xxxxxxxx.cloud.databricks.com`).
- Установленный **Databricks CLI** и выполненный вход (`databricks auth login`).
- Установленный **uv** (даёт команду `uvx` для запуска прокси без отдельного venv).
- Локальный файл **`.env`** в корне проекта Staffing Agent (не коммитится; шаблон — `.env.example`).

---

## Шаг 1. Установить uv (если ещё нет)

В терминале:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Перезапустите терминал (или откройте новую вкладку). Проверка:

```bash
uvx --version
```

Ожидаемый путь к `uvx` на macOS после скрипта: `~/.local/bin/uvx`. Скрипт `.cursor/run-databricks-mcp.sh` вызывает **`${HOME}/.local/bin/uvx`** — при другом расположении `uvx` отредактируйте путь в этом скрипте.

---

## Шаг 2. Установить и настроить Databricks CLI

Если CLI ещё нет (пример для macOS с Homebrew):

```bash
brew install databricks-cli
```

Войдите в нужный воркспейс и сохраните профиль (имя примера — `toloka`, можно любое):

```bash
databricks auth login --profile toloka
```

Следуйте подсказкам браузера. Убедитесь, что команда завершается без ошибки.

Проверка (опционально):

```bash
databricks workspace ls --profile toloka
```

---

## Шаг 3. Собрать URL для MCP

Для управляемого endpoint формат такой:

```text
https://<хост-вашего-воркспейса>/api/2.0/mcp/functions/system/ai
```

**`<хост>`** — то же самое, что в адресной строке воркспейса: например `dbc-abc123.cloud.databricks.com` **без** `/` в конце; в переменной указывается полный URL с `https://`.

Пример:

```text
https://dbc-abc123.cloud.databricks.com/api/2.0/mcp/functions/system/ai
```

Если воркспейс использует другой регион/хост — подставьте свой из URL Databricks.

---

## Шаг 4. Заполнить `.env` в корне проекта

В каталоге репозитория Staffing Agent создайте или отредактируйте файл **`.env`** (он в `.gitignore`).

Добавьте (подставьте свои значения):

```env
DATABRICKS_MCP_URL=https://<ваш-хост>/api/2.0/mcp/functions/system/ai
DATABRICKS_PROFILE=toloka
```

`DATABRICKS_PROFILE` **должен совпадать** с именем профиля, который вы использовали в `databricks auth login --profile ...`.

Сохраните файл.

---

## Шаг 5. Проверить `.cursor/mcp.json` и скрипт

Должны быть:

- **`.cursor/mcp.json`** — запускает `/bin/bash` с аргументом `${workspaceFolder}/.cursor/run-databricks-mcp.sh` (Cursor подставляет путь к проекту).
- **`.cursor/run-databricks-mcp.sh`** — исполняемый (`chmod +x`); читает **`.env`** и вызывает `uvx uc-mcp-proxy` с `--url` и `--profile` из файла.

Менять нужно только если:

- **`uvx` не в `~/.local/bin`** — правьте путь в **`run-databricks-mcp.sh`**;
- нужен **SQL warehouse** — добавьте в **`run-databricks-mcp.sh`** в конец вызова `exec ... uvx uc-mcp-proxy` аргументы: `--meta` `warehouse_id=<идентификатор-warehouse>`;
- скрипт не запускается из Cursor — в терминале: `chmod +x .cursor/run-databricks-mcp.sh`.

---

## Шаг 6. Перезапустить Cursor

Полностью закройте приложение Cursor и откройте снова, затем откройте **именно этот проект** (папку Staffing Agent), чтобы подтянулся `.cursor/mcp.json` уровня проекта.

---

## Шаг 7. Включить MCP и проверить логи

1. **Cursor Settings** → **Features** → **Model Context Protocol** (или аналог в вашей версии).
2. Убедитесь, что сервер **`databricks`** включён.
3. При проблемах: **View** → **Output** → в списке выберите **MCP Logs** и прочитайте текст ошибки (часто это неверный URL, профиль или отсутствие `uvx` в пути).

В чате с агентом можно попросить выполнить простое действие через Databricks MCP и убедиться, что инструменты доступны.

---

## Типичные проблемы

| Симптом | Что проверить |
|--------|----------------|
| «command not found» / не стартует `uvx` | В **`run-databricks-mcp.sh`** должен быть верный путь к `uvx` (по умолчанию `~/.local/bin/uvx`). |
| Ошибка авторизации | Снова `databricks auth login --profile <имя>`, совпадение `DATABRICKS_PROFILE` в `.env`. |
| 403 / 404 по URL | Точный хост воркспейса и полный путь `/api/2.0/mcp/functions/system/ai`; фича MCP на воркспейсе может быть в preview — см. доку Databricks для вашего облака. |
| `UnsupportedProtocol` / URL без `https://` | Часто **`DATABRICKS_MCP_URL` не попадал в `--url`**, если задавали его только в `.env`, а в `mcp.json` использовали `${env:...}` — Cursor не подставляет эти значения из `envFile`. Используйте текущий **`run-databricks-mcp.sh`** или пропишите URL прямо в конфиге. |
| Переменные «пустые» | Файл `.env` в **корне** открытого в Cursor воркспейса; после правок `.env` — перезапуск Cursor. |

---

## Связь с ботом Staffing Agent

Переменные `DATABRICKS_PROFILE` и проверка `python -m staffing_agent --check` описаны в `.env.example` отдельно от MCP: бот и Cursor MCP используют один и тот же профиль CLI, если вы задаёте одно и то же имя профиля в `.env`.

После правок кода, `.env` или `.cursor/mcp.json` перезапускайте Cursor; для Slack-бота — по правилам проекта отдельно перезапускайте `python -m staffing_agent`.
