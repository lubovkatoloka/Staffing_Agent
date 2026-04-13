"""Shared helpers for parsing occupation query rows (avoid import cycles)."""

from __future__ import annotations

from typing import Any


def _row_get_ci(row: dict[str, Any], *candidates: str) -> Any:
    lower_map = {k.lower(): v for k, v in row.items()}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    return None


def project_role_norm(row: dict[str, Any]) -> str:
    """Normalized `project_role` from occupation SQL (dpm, soe, wfm, …)."""
    v = _row_get_ci(row, "project_role", "PROJECT_ROLE")
    return (str(v) if v is not None else "").strip().lower()


def occupation_value(row: dict[str, Any]) -> float | None:
    for key in ("occupation", "total_occupation", "project_occupation"):
        v = row.get(key)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    # case-insensitive fallback
    for k, v in row.items():
        if k.lower() == "occupation" and v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def email_value(row: dict[str, Any]) -> str:
    """Lowercase email for joins (Occupation / TT user)."""
    v = _row_get_ci(row, "user_email", "email", "Email", "USER_EMAIL")
    if v is not None and str(v).strip():
        return str(v).strip().lower()
    for k, v in row.items():
        if "email" in k.lower() and v is not None and "@" in str(v):
            return str(v).strip().lower()
    return ""


def name_value(row: dict[str, Any]) -> str:
    for key in ("user_name", "name", "user_email", "user_id"):
        v = row.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    for k, v in row.items():
        if k.lower() in ("user_name", "name", "user_email") and v is not None and str(v).strip():
            return str(v).strip()
    return "?"
