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

### 3. Environment

```bash
cp .env.example .env
# edit .env with the three values above
```

### 4. Run

**Always run from the project root** (the folder that contains `staffing_agent/`). If you start the terminal elsewhere, `python -m staffing_agent` will not find the package.

```bash
cd "/Users/liubakarpova/Documents/Staffing Agent"
source .venv/bin/activate
python -m staffing_agent
```

Or from any directory:

```bash
"/Users/liubakarpova/Documents/Staffing Agent/run_local.sh"
```

Invite the bot to a channel, then mention it in a thread. It replies in the thread with a **stub** that lists collected thread text (later: Decision Logic + Databricks).

Press **Ctrl+C** to stop.

## Layout

- `staffing_agent/slack_app.py` — Bolt app, thread fetch, placeholder reply.
- `.env` — secrets (never committed).
