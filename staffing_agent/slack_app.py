"""Slack Bolt app: Socket Mode, thread context, stub reply."""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient

from staffing_agent.decision.node2_rules import node2_slack_markdown
from staffing_agent.extraction import extract_request_spec, mock_llm_reason, uses_mock_llm
from staffing_agent.node3_occupation import node3_slack_markdown
from staffing_agent.slack_phase_c import build_phase_c_section
from staffing_agent.thread_context import (
    build_context_reply,
    exclude_bot_user_messages,
    format_thread_preview,
    gather_notion_previews,
    notion_excerpt_for_llm,
)

# Load `.env` from repo root (parent of `staffing_agent/`), not from shell cwd.
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH, override=True)

logger = logging.getLogger(__name__)

REQUIRED = ("SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "SLACK_APP_TOKEN")

# Cached Slack bot user id (auth.test) — exclude our own replies from thread text for LLM
_CACHED_BOT_USER_ID: str | None = None


def _get_bot_user_id(client: Any) -> str:
    global _CACHED_BOT_USER_ID
    if _CACHED_BOT_USER_ID is None:
        r = client.auth_test()
        uid = r.get("user_id")
        if not uid:
            raise RuntimeError("Slack auth.test did not return user_id")
        _CACHED_BOT_USER_ID = str(uid)
        logger.info("bot user_id=%s (our replies excluded from Phase B context)", _CACHED_BOT_USER_ID)
    return _CACHED_BOT_USER_ID


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


def check_slack_connection() -> None:
    """Quick test: tokens valid and API reachable (exits fast)."""
    _check_env()
    print("Calling Slack auth.test…", flush=True)
    client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
    resp = client.auth_test()
    if not resp.get("ok"):
        raise RuntimeError(resp)
    print(
        f"OK: bot user={resp.get('user')} team={resp.get('team')} url={resp.get('url')}",
        flush=True,
    )


def create_app() -> App:
    _check_env()
    app = App(
        token=os.environ["SLACK_BOT_TOKEN"],
        signing_secret=os.environ["SLACK_SIGNING_SECRET"],
    )

    @app.middleware
    def log_request(logger: logging.Logger, body: dict[str, Any], next: Any) -> Any:
        """See which events reach the app (debug: set STAFFING_AGENT_DEBUG=1)."""
        if os.environ.get("STAFFING_AGENT_DEBUG") == "1":
            ev = body.get("event") or {}
            logger.info(
                "incoming event type=%s subtype=%s channel=%s",
                ev.get("type"),
                ev.get("subtype"),
                ev.get("channel"),
            )
        return next()

    @app.error
    def global_error(error: Exception, body: dict[str, Any], logger: logging.Logger) -> None:
        logger.exception("Bolt error: %s body_keys=%s", error, list(body.keys()) if body else [])

    @app.event("app_mention")
    def on_mention(event: dict[str, Any], client: Any, logger: logging.Logger) -> None:
        logger.info(
            "app_mention received channel=%s thread/root_ts=%s",
            event.get("channel"),
            _thread_ts(event),
        )
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

        bot_uid = _get_bot_user_id(client)
        messages = exclude_bot_user_messages(messages, bot_uid)

        thread_plain = format_thread_preview(messages)
        print(
            "[staffing] Notion: fetching page previews for links in thread (if any; may take a few seconds)…",
            file=sys.stderr,
            flush=True,
        )
        previews = gather_notion_previews(messages)
        notion_ex = notion_excerpt_for_llm(messages, previews=previews)
        print(
            f"[staffing] Phase B: extraction starting (thread={len(thread_plain)} chars, "
            f"notion_excerpt={len(notion_ex)} chars). Anthropic can take 15–40s — not frozen.\n",
            file=sys.stderr,
            flush=True,
        )
        t0 = time.perf_counter()
        spec, src = extract_request_spec(thread_plain, notion_ex)
        elapsed = time.perf_counter() - t0
        print(
            f"[staffing] Phase B: extraction done in {elapsed:.1f}s (source={src})\n",
            file=sys.stderr,
            flush=True,
        )
        logger.info("extraction finished in %.1fs source=%s", elapsed, src)
        src_label = {
            "mock": "mock (set ANTHROPIC_API_KEY; unset STAFFING_AGENT_MOCK_LLM)",
            "anthropic": "Anthropic Opus",
            "error": "error",
        }.get(src, src)

        print(
            "[staffing] Node 2–3: building pool text + optional Databricks occupation query…",
            file=sys.stderr,
            flush=True,
        )
        reply = (
            build_context_reply(messages, previews=previews)
            + f"\n\n*Phase B — extraction (Node 1)* _(source: {src_label})_\n"
            + spec.to_slack_block()
            + "\n\n"
            + node2_slack_markdown(spec.tier, spec.project_type_tags)
            + "\n\n"
            + node3_slack_markdown(
                tier=spec.tier,
                project_type_tags=spec.project_type_tags,
                summary=spec.summary,
            )
            + "\n\n"
            + build_phase_c_section()
        )
        if len(reply) > 12000:
            reply = reply[:11900] + "\n```\n… (truncated)"

        try:
            client.chat_postMessage(channel=channel, thread_ts=root_ts, text=reply)
        except Exception as e:
            logger.exception("chat_postMessage failed: %s", e)
            raise

    return app


def run_socket_mode() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )
    print("[1/4] Staffing Agent: loading env and checking tokens…", flush=True, file=sys.stderr)
    print(
        "\n=== Staffing Agent (local) ===\n"
        "After step [4/4] this terminal will show no shell prompt until Ctrl+C — that is normal.\n"
        "Leave it running, @mention the bot in Slack; logs appear on stderr.\n",
        flush=True,
        file=sys.stderr,
    )
    print("[2/4] Building Bolt app (calls auth.test)…", flush=True, file=sys.stderr)
    app = create_app()
    if uses_mock_llm():
        print(
            f"[staffing] LLM: MOCK — {mock_llm_reason()} "
            "(fix .env, then restart the bot — env is read only at process start).",
            flush=True,
            file=sys.stderr,
        )
    else:
        print(
            "[staffing] LLM: LIVE (Anthropic API via ANTHROPIC_* / LiteLLM).",
            flush=True,
            file=sys.stderr,
        )
    print("[3/4] Starting Socket Mode handler…", flush=True, file=sys.stderr)
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    logging.getLogger(__name__).info("Socket Mode handler starting (Ctrl+C to stop)…")
    print(
        "[4/4] Connected — waiting for Slack events. Try @your_bot in a channel.\n",
        flush=True,
        file=sys.stderr,
    )
    try:
        handler.start()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True, file=sys.stderr)
