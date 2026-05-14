"""Within-thread mention dedup (CR-2)."""

from __future__ import annotations

import pytest

from staffing_agent.thread_dedup import (
    classify_mention_dedup,
    mention_dedup_seconds,
    reset_mention_dedup_for_tests,
)


@pytest.fixture(autouse=True)
def _clear_dedup() -> None:
    reset_mention_dedup_for_tests()
    yield
    reset_mention_dedup_for_tests()


def test_classify_fresh_then_duplicate_same_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAFFING_MENTION_DEDUP_SECONDS", "60")
    assert classify_mention_dedup("C1", "1.0", "hello\n") == "fresh"
    assert classify_mention_dedup("C1", "1.0", "hello\n") == "duplicate"


def test_classify_updated_when_text_changes_within_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAFFING_MENTION_DEDUP_SECONDS", "60")
    assert classify_mention_dedup("C1", "1.0", "v1") == "fresh"
    assert classify_mention_dedup("C1", "1.0", "v2") == "updated"
    assert classify_mention_dedup("C1", "1.0", "v2") == "duplicate"


def test_zero_seconds_disables_dedup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAFFING_MENTION_DEDUP_SECONDS", "0")
    assert mention_dedup_seconds() == 0.0
    assert classify_mention_dedup("C1", "1.0", "a") == "fresh"
    assert classify_mention_dedup("C1", "1.0", "a") == "fresh"


def test_different_threads_in_same_channel_are_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAFFING_MENTION_DEDUP_SECONDS", "60")
    assert classify_mention_dedup("C1", "1.1", "same body") == "fresh"
    assert classify_mention_dedup("C1", "1.2", "same body") == "fresh"
