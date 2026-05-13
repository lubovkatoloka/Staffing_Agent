"""HiBob-derived fields from Databricks (Airbyte raw tables)."""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime
from pathlib import Path

from staffing_agent.databricks_cli import databricks_profile, run_sql_query

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
MIN_HIBOB_SQL_LEN = 40


def hibob_start_dates_sql_path() -> Path:
    """Default `sql/hibob_start_dates.sql` or `STAFFING_HIBOB_START_DATES_SQL_PATH` (absolute/expanduser)."""
    override = (os.environ.get("STAFFING_HIBOB_START_DATES_SQL_PATH") or "").strip()
    if override:
        return Path(override).expanduser()
    return _ROOT / "sql" / "hibob_start_dates.sql"


def _sql_executable_text(path: Path) -> str:
    if not path.is_file():
        return ""
    raw = path.read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if not ln.strip().startswith("--")]
    return "\n".join(lines).strip()


def _escape_sql_literal(value: str) -> str:
    return value.replace("'", "''")


_ISO_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _parse_start_date(raw: str | None) -> date | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    m = _ISO_DATE_RE.match(s)
    if m:
        s = m.group(1)
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def fetch_start_dates(emails: set[str], *, timeout_sec: int = 60) -> dict[str, date]:
    """Return ``email.lower()`` → first known work start date from HiBob SQL; never raises."""
    if not emails:
        return {}
    cleaned = {e.strip().lower() for e in emails if (e or "").strip()}
    if not cleaned:
        return {}
    if not databricks_profile():
        logger.warning("HiBob start dates: DATABRICKS_PROFILE not set; skipping fetch")
        return {}
    path = hibob_start_dates_sql_path()
    base = _sql_executable_text(path)
    if len(base) < MIN_HIBOB_SQL_LEN:
        logger.warning("HiBob start dates: SQL missing or too short (%s)", path)
        return {}
    in_list = ", ".join(f"'{_escape_sql_literal(e)}'" for e in sorted(cleaned))
    sql = f"{base}\nWHERE email IN ({in_list})"
    ok, out = run_sql_query(sql, timeout_sec=timeout_sec, extra_args=["--output", "json"])
    if not ok:
        ok, out = run_sql_query(sql, timeout_sec=timeout_sec)
    if not ok:
        logger.warning(
            "HiBob start dates query failed: %s",
            (out or "")[:800],
        )
        return {}
    from staffing_agent.node3_occupation import _try_parse_query_json

    rows = _try_parse_query_json(out)
    if not rows:
        logger.warning("HiBob start dates: could not parse CLI JSON output")
        return {}
    out_map: dict[str, date] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        rd = {str(k).lower(): v for k, v in row.items()}
        em = rd.get("email")
        if not em:
            continue
        em = str(em).strip().lower()
        raw_date = rd.get("start_date_raw")
        sd = _parse_start_date(str(raw_date) if raw_date is not None else None)
        if sd is not None:
            out_map[em] = sd
    return out_map
