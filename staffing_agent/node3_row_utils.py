"""Shared helpers for parsing Capacity / legacy SQL rows (avoid import cycles)."""

from __future__ import annotations

from typing import Any


def _row_get_ci(row: dict[str, Any], *candidates: str) -> Any:
    lower_map = {k.lower(): v for k, v in row.items()}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    return None


def project_role_norm(row: dict[str, Any]) -> str:
    """Normalized `project_role` from Capacity SQL or legacy rows (dpm, soe, wfm, …)."""
    v = _row_get_ci(row, "project_role", "PROJECT_ROLE")
    if v is not None and str(v).strip():
        return str(v).strip().lower()
    rg = _row_get_ci(row, "role_group", "ROLE_GROUP")
    if rg is None:
        return ""
    g = str(rg).strip().upper()
    if "SOE" in g or "SSOE" in g:
        return "soe"
    if g == "DPM":
        return "dpm"
    if "WFM" in g or "WFC" in g:
        return "wfm"
    if "QM" in g or "QC" in g:
        return "qm"
    if g == "SE":
        return "se"
    return str(rg).strip().lower()


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
