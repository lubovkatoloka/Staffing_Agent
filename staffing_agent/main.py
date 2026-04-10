"""CLI entry: `python -m staffing_agent` from repo root."""

import argparse
import sys

from staffing_agent.slack_app import check_slack_connection, run_socket_mode


def main() -> None:
    parser = argparse.ArgumentParser(description="Staffing Agent Slack bot (local Socket Mode)")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only verify .env + Slack auth.test (no long-running process)",
    )
    args = parser.parse_args()
    if args.check:
        try:
            check_slack_connection()
        except Exception as e:
            print(f"CHECK FAILED: {e}", file=sys.stderr, flush=True)
            raise SystemExit(1) from e
        raise SystemExit(0)
    run_socket_mode()


if __name__ == "__main__":
    main()
