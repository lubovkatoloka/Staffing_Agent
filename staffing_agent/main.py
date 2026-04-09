"""CLI entry: `python -m staffing_agent` from repo root."""

from staffing_agent.slack_app import run_socket_mode


def main() -> None:
    run_socket_mode()


if __name__ == "__main__":
    main()
