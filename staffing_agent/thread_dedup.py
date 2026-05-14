"""Within-thread @mention dedup (CR-2): short window, same context vs new context."""

from __future__ import annotations

import hashlib
import os
import time
from typing import Literal

_STATE: dict[tuple[str, str], tuple[float, str]] = {}

DedupOutcome = Literal["fresh", "duplicate", "updated"]


def mention_dedup_seconds() -> float:
    raw = (os.environ.get("STAFFING_MENTION_DEDUP_SECONDS") or "60").strip()
    try:
        v = float(raw)
    except ValueError:
        return 60.0
    return max(0.0, v)


def _fingerprint(thread_plain: str) -> str:
    t = (thread_plain or "").encode("utf-8", errors="replace")
    return hashlib.sha256(t).hexdigest()[:24]


def classify_mention_dedup(
    channel_id: str,
    thread_root_ts: str,
    thread_plain: str,
) -> DedupOutcome:
    if mention_dedup_seconds() <= 0:
        return "fresh"
    key = (channel_id, thread_root_ts)
    now = time.time()
    fp = _fingerprint(thread_plain)
    prev = _STATE.get(key)
    if prev is None:
        _STATE[key] = (now, fp)
        return "fresh"
    prev_t, prev_fp = prev
    if now - prev_t > mention_dedup_seconds():
        _STATE[key] = (now, fp)
        return "fresh"
    if fp == prev_fp:
        return "duplicate"
    _STATE[key] = (now, fp)
    return "updated"


def reset_mention_dedup_for_tests() -> None:
    _STATE.clear()
