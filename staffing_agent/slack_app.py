"""Slack Bolt app: Socket Mode, thread context, stub reply."""

from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# `.env` must win over stale exports in the shell (dotenv default is override=False).
load_dotenv(override=True)

logger = logging.getLogger(__name__)

REQUIRED = ("SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "SLACK_APP_TOKEN")


def _check_env() -> None:
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        raise SystemExit(
            f"Missing env vars: {', '.join(missing)}. Copy .env.example → .env and fill values."
        )
    bot = os.environ["SLACK_BOT_TOKEN"].strip()
    secret = os.environ["SLACK_SIGNING_SECRET"].strip()
    app_tok = os.environ["SLACK_APP_TOKEN"].strip()
    if not bot.startswith("xoxb-") or len(bot) < 40:
        raise SystemExit(
            "SLACK_BOT_TOKEN looks wrong: paste the full Bot User OAuth Token from "
            "OAuth & Permissions (after Install to Workspace), not the placeholder xoxb-...\n"
            "If .env is correct, run: unset SLACK_BOT_TOKEN SLACK_SIGNING_SECRET SLACK_APP_TOKEN"
        )
    if len(secret) < 16:
        raise SystemExit(
            "SLACK_SIGNING_SECRET looks too short: copy the full Signing Secret from Basic Information."
        )
    if not app_tok.startswith("xapp-") or len(app_tok) < 40:
        raise SystemExit(
            "SLACK_APP_TOKEN looks wrong: create an App-Level Token with scope connections:write "
            "(Basic Information → App-Level Tokens)."
        )


def _thread_ts(event: dict[str, Any]) -> str:
    return event.get("thread_ts") or event["ts"]


def _collect_thread_messages(client: Any, channel: str, root_ts: str) -> list[dict[str, Any]]:
    """Fetch all messages in a thread (root + replies)."""
    out: list[dict[str, Any]] = []
    cursor = None
    while True:
        kwargs: dict[str, Any] = {"channel": channel, "ts": root_ts, "limit": 200}
        if cursor:
            kwargs["cursor"] = cursor
        resp = client.conversations_replies(**kwargs)
        messages = resp.get("messages") or []
        out.extend(messages)
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    out.sort(key=lambda m: float(m.get("ts", "0")))
    return out


def _format_thread_preview(messages: list[dict[str, Any]], max_chars: int = 3500) -> str:
    lines: list[str] = []
    total = 0
    for m in messages:
        uid = m.get("user") or "?"
        text = (m.get("text") or "").strip()
        if not text:
            continue
        line = f"<@{uid}>: {text}"
        if total + len(line) + 1 > max_chars:
            lines.append("… (truncated)")
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines) if lines else "(empty thread)"


def create_app() -> App:
    _check_env()
    app = App(
        token=os.environ["SLACK_BOT_TOKEN"],
        signing_secret=os.environ["SLACK_SIGNING_SECRET"],
    )

    @app.event("app_mention")
    def on_mention(event: dict[str, Any], client: Any, logger: logging.Logger) -> None:
        channel = event["channel"]
        root_ts = _thread_ts(event)

        try:
            messages = _collect_thread_messages(client, channel, root_ts)
        except Exception as e:
            logger.exception("conversations.replies failed: %s", e)
            client.chat_postMessage(
                channel=channel,
                thread_ts=root_ts,
                text=f"Could not load thread: `{e}`",
            )
            return

        preview = _format_thread_preview(messages)
        # Stub: later plug Decision Logic + Databricks here
        reply = (
            "*Staffing Agent (local stub)*\n"
            f"_Messages in thread:_ {len(messages)}\n"
            "```\n"
            f"{preview}\n"
            "```"
        )
        client.chat_postMessage(channel=channel, thread_ts=root_ts, text=reply)

    return app


def run_socket_mode() -> None:
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    logging.getLogger(__name__).info("Socket Mode handler starting (Ctrl+C to stop)…")
    handler.start()
