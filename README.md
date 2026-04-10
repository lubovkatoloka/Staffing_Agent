# Staffing Agent

Slack-based assistant for staffing decisions. Product logic is defined in Notion:

- [Staffing Agent — Decision Logic v1.0](https://www.notion.so/toloka-ai/Staffing-Agent-Decision-Logic-v1-0-32749d0688568183af3bf80ff6aedfd4)

Track work in [GitHub Issues](https://github.com/lubovkatoloka/Staffing_Agent/issues).

## Local development

### 1. Python 3.11+

```bash
cd "/Users/liubakarpova/Documents/Staffing Agent"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Slack app (Socket Mode — no public URL)

1. Create an app at [api.slack.com/apps](https://api.slack.com/apps) (from scratch or manifest).
2. **Socket Mode** → turn **On**.
3. **Basic Information** → **App-Level Tokens** → generate token with scope `connections:write` → this is `SLACK_APP_TOKEN` (`xapp-…`).
4. **OAuth & Permissions** → **Bot Token Scopes** (minimum for this stub):
   - `app_mentions:read`
   - `chat:write`
   - `channels:history` (read thread in public channels)
   - For private channels add `groups:history`.
5. **Install to workspace** → copy **Bot User OAuth Token** → `SLACK_BOT_TOKEN` (`xoxb-…`).
6. **Basic Information** → **Signing Secret** → `SLACK_SIGNING_SECRET`.
7. **Event Subscriptions** (required, or the bot never sees `@mentions`):
   - Turn **Enable Events** **ON**.
   - Under **Subscribe to bot events**, add **`app_mention`** (and click **Save Changes**).
   - Without this, Socket Mode connects but nothing triggers your handler.

### 3. Environment

```bash
cp .env.example .env
# edit .env with the three values above
```

If the bot still says the token is wrong but you pasted full values: your shell may have old `SLACK_*` exports. Run `unset SLACK_BOT_TOKEN SLACK_SIGNING_SECRET SLACK_APP_TOKEN` and try again. The app loads `.env` with **override** so file values take precedence.

### 4. Run

**Always run from the project root** (the folder that contains `staffing_agent/`). If you start the terminal elsewhere, `python -m staffing_agent` will not find the package.

```bash
cd "/Users/liubakarpova/Documents/Staffing Agent"
source .venv/bin/activate
python -m staffing_agent --check   # fast: only tests tokens (optional)
python -m staffing_agent           # long-running: Socket Mode
```

If the terminal seems to print nothing:

1. Run **`python -m staffing_agent --check`** — should finish in ~1s.
2. Open **`Staffing Agent/.staffing_agent_debug.log`** in the repo (the app appends lines here on every start, even if the terminal hides stderr).
3. Use **Terminal.app** instead of the IDE terminal, or run: `python -u -m staffing_agent`.

Logs from the bot go to **stderr**; you should see steps `[1/4]` … `[4/4]` when the full bot starts.

Or from any directory:

```bash
"/Users/liubakarpova/Documents/Staffing Agent/run_local.sh"
```

Invite the bot: `/invite @YourBotName` in the channel. In Slack you must **@mention the bot** in the message (e.g. `@who_is_available hello`) — plain text without `@` does not fire `app_mention`.

The bot replies **in the same thread** with a **stub** that lists collected thread text. If nothing happens, check the terminal: you should see `app_mention received`. If you see no log line, fix **Event Subscriptions → `app_mention`** above. For more detail run with `STAFFING_AGENT_DEBUG=1 python -m staffing_agent`.

**Note:** After `Bolt app is running!` the terminal **does not return a new prompt** — the process waits for Slack. That is expected. Use another terminal tab for other commands. Stop the bot with **Ctrl+C**.

## Layout

- `staffing_agent/slack_app.py` — Bolt app, thread fetch, placeholder reply.
- `.env` — secrets (never committed).
