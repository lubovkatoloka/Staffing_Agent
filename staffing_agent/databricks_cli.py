"""Optional: run SQL via local `databricks` CLI (OAuth profile from DATABRICKS_PROFILE)."""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

from dotenv import load_dotenv

from staffing_agent.sql_sanitize import sanitize_sql_for_cli

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env", override=True)


def databricks_profile() -> str | None:
    p = (os.environ.get("DATABRICKS_PROFILE") or "").strip()
    return p or None


def cli_available() -> bool:
    return shutil.which("databricks") is not None


def run_sql_query(
    sql: str,
    *,
    timeout_sec: int = 120,
    extra_args: list[str] | None = None,
) -> tuple[bool, str]:
    """
    Execute SQL using `databricks experimental aitools tools query` (see Databricks skill).
    Returns (ok, message) where message is stdout or error text.
    """
    profile = databricks_profile()
    if not profile:
        return False, "DATABRICKS_PROFILE is not set in .env"
    if not cli_available():
        return False, "databricks CLI not found in PATH (install: brew install databricks)"

    sql = sanitize_sql_for_cli(sql)
    if not sql:
        return False, "SQL is empty after stripping Notion/markdown (paste raw SQL starting with WITH or SELECT)."
    sql_one_line = sql
    cmd = [
        "databricks",
        "experimental",
        "aitools",
        "tools",
        "query",
        sql_one_line,
    ]
    if extra_args:
        cmd.extend(extra_args)
    cmd.extend(["--profile", profile])
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode != 0:
            return False, err or out or f"exit {proc.returncode}"
        return True, out or "(empty stdout)"
    except subprocess.TimeoutExpired:
        return False, f"timeout after {timeout_sec}s"
    except Exception as e:
        return False, str(e)


def check_databricks_sql() -> None:
    """Print result of SELECT 1 for `python -m staffing_agent --check-dbx` (same flags as Node 3)."""
    print("Databricks SQL smoke (SELECT 1)…", flush=True)
    ok, msg = run_sql_query(
        "SELECT 1 AS ok",
        extra_args=["--output", "json"],
    )
    if not ok:
        ok, msg = run_sql_query("SELECT 1 AS ok")
    if not ok:
        raise RuntimeError(msg)
    print(textwrap.shorten(f"OK: {msg}", width=800, placeholder="…"), flush=True)


def smoke_sql_text() -> str:
    p = _ROOT / "sql" / "smoke.sql"
    if p.is_file():
        lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if not ln.strip().startswith("--")]
        return "\n".join(lines).strip() or "SELECT 1 AS ok"
    return "SELECT 1 AS ok"
