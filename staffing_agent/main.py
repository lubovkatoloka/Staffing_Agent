"""CLI entry: `python -m staffing_agent` from repo root."""

import argparse
import sys
from pathlib import Path

from staffing_agent.anthropic_llm import check_anthropic_connection
from staffing_agent.databricks_cli import check_databricks_sql
from staffing_agent.paste_run import build_reply_from_paste, post_reply_to_slack
from staffing_agent.slack_app import check_slack_connection, run_socket_mode


def main() -> None:
    parser = argparse.ArgumentParser(description="Staffing Agent Slack bot (local Socket Mode)")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only verify .env + Slack auth.test (no long-running process)",
    )
    parser.add_argument(
        "--check-llm",
        action="store_true",
        help="Verify ANTHROPIC_API_KEY + Opus model (one short API call)",
    )
    parser.add_argument(
        "--check-dbx",
        action="store_true",
        help="Run SELECT 1 via local databricks CLI (needs DATABRICKS_PROFILE)",
    )
    parser.add_argument(
        "--process-paste",
        metavar="FILE",
        help="Run Phase A/B/C on thread text (use - for stdin). Prints reply; add --post-slack-channel to post as the bot.",
    )
    parser.add_argument(
        "--notion-excerpt-file",
        metavar="FILE",
        help="Optional Notion excerpt text for Phase B (instead of auto-fetch from URLs)",
    )
    parser.add_argument(
        "--post-slack-channel",
        metavar="CHANNEL_ID",
        help="With --process-paste: post result to this channel (e.g. C0123ABC); bot must be /invite'd",
    )
    parser.add_argument(
        "--fetch-google-doc",
        metavar="URL_OR_DOC_ID",
        help="Print plain text of a Google Doc (API; needs service account JSON in .env). URL or raw document id.",
    )
    args = parser.parse_args()
    if args.fetch_google_doc:
        from staffing_agent.google_docs_fetch import fetch_google_doc, fetch_google_doc_from_url

        raw = args.fetch_google_doc.strip()
        info = fetch_google_doc_from_url(raw) if raw.startswith("http") else fetch_google_doc(raw)
        if info.get("error"):
            print(f"FETCH_GOOGLE_DOC FAILED: {info['error']}", file=sys.stderr, flush=True)
            raise SystemExit(1)
        title = info.get("title") or ""
        text = info.get("text") or ""
        print(f"# {title}\n\n{text}")
        raise SystemExit(0)
    if args.check:
        try:
            check_slack_connection()
        except Exception as e:
            print(f"CHECK FAILED: {e}", file=sys.stderr, flush=True)
            raise SystemExit(1) from e
        raise SystemExit(0)
    if args.check_llm:
        try:
            check_anthropic_connection()
        except Exception as e:
            print(f"CHECK_LLM FAILED: {e}", file=sys.stderr, flush=True)
            raise SystemExit(1) from e
        raise SystemExit(0)
    if args.check_dbx:
        try:
            check_databricks_sql()
        except Exception as e:
            print(f"CHECK_DBX FAILED: {e}", file=sys.stderr, flush=True)
            raise SystemExit(1) from e
        raise SystemExit(0)
    if args.process_paste:
        path = args.process_paste
        raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
        notion_ex = ""
        if args.notion_excerpt_file:
            notion_ex = Path(args.notion_excerpt_file).read_text(encoding="utf-8")
        try:
            reply, _src = build_reply_from_paste(raw, notion_excerpt_override=notion_ex)
        except Exception as e:
            print(f"PROCESS_PASTE FAILED: {e}", file=sys.stderr, flush=True)
            raise SystemExit(1) from e
        if args.post_slack_channel:
            try:
                post_reply_to_slack(args.post_slack_channel, reply)
            except Exception as e:
                print(f"POST_SLACK FAILED: {e}", file=sys.stderr, flush=True)
                raise SystemExit(1) from e
            print("Posted to Slack.", flush=True)
        else:
            print(reply)
        raise SystemExit(0)
    run_socket_mode()


if __name__ == "__main__":
    main()
