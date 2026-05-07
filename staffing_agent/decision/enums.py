"""Bands and reason codes for Capacity v2."""

from __future__ import annotations

from enum import Enum


class Band(str, Enum):
    FREE = "FREE"
    PARTIAL = "PARTIAL"
    AT_CAP = "AT_CAP"


class IneligibleReason(str, Enum):
    OK = ""
    ON_PTO_TODAY = "on_pto_today"
    IN_HARD_EXCLUDE = "in_hard_exclude"
    MAX_PROJECTS_CAP = "max_projects_cap"
    CAPACITY_OVERFLOW = "capacity_overflow"


class SoftReason(str, Enum):
    ALL_SCOPING_OR_DISCOVERY = "all_scoping_or_discovery"
    ALL_CLOSE_OUT_ON_TRACK = "all_close_out_on_track"
    # ENDING_SOON deferred — see Known Gaps in Notion v2 page
