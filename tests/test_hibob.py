"""HiBob Databricks helpers."""

from __future__ import annotations

from unittest.mock import patch

from staffing_agent import hibob


def test_fetch_start_dates_empty_emails_no_sql_call() -> None:
    with patch.object(hibob, "run_sql_query") as rq:
        assert hibob.fetch_start_dates(set()) == {}
        assert hibob.fetch_start_dates({""}) == {}
        rq.assert_not_called()


def test_fetch_start_dates_sql_failure_returns_empty(monkeypatch) -> None:
    monkeypatch.setenv("DATABRICKS_PROFILE", "test-profile")
    with patch.object(hibob, "run_sql_query", return_value=(False, "CLI error")):
        assert hibob.fetch_start_dates({"a@b.com"}) == {}

