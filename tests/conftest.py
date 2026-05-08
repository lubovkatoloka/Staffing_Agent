"""Shared pytest fixtures."""

from __future__ import annotations

import time

import pytest

from staffing_agent.exclusions import ExclusionResult, ExclusionStore, reset_exclusion_store


@pytest.fixture(autouse=True)
def _default_live_exclusions(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Stub Notion exclusion fetch so tests never require live NOTION_TOKEN."""
    if request.node.get_closest_marker("no_fake_exclusions"):
        yield
        return
    reset_exclusion_store()
    monkeypatch.setenv("NOTION_TOKEN", "test-token-unused")

    def empty_fetch(self: ExclusionStore, token: str) -> ExclusionResult:
        return ExclusionResult(excluded=tuple(), fetched_at=time.time())

    monkeypatch.setattr(ExclusionStore, "_fetch_live", empty_fetch)
    yield
    reset_exclusion_store()
