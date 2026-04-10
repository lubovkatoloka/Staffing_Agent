"""Labels from Decision Logic v1.0 availability table (+ UNVERIFIED, PTO)."""

from __future__ import annotations

from enum import Enum


class AvailabilityLabel(str, Enum):
    FREE = "FREE"
    PARTIAL = "PARTIAL"
    SOFT = "SOFT"
    BUSY = "BUSY"
    PTO = "PTO"
    UNVERIFIED = "UNVERIFIED"
