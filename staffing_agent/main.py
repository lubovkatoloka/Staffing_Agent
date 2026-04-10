"""CLI entry: `python -m staffing_agent` from repo root."""

import argparse
import sys

from staffing_agent.anthropic_llm import check_anthropic_connection
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
    args = parser.parse_args()
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
    run_socket_mode()


if __name__ == "__main__":
    main()
