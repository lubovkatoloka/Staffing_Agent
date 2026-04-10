"""Entry for `python -m staffing_agent` — boot logging before heavy imports."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_LOG = _REPO / ".staffing_agent_debug.log"


def _boot_log(msg: str) -> None:
    line = f"{msg}\n"
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
    try:
        print(msg, file=sys.stderr, flush=True)
    except OSError:
        pass


_boot_log("---")
_boot_log("staffing_agent: __main__ starting (if your terminal is blank, open .staffing_agent_debug.log in the repo root)")

try:
    from staffing_agent.main import main

    main()
except SystemExit:
    raise
except BaseException as e:
    _boot_log(f"FATAL: {e!r}")
    traceback.print_exc(file=sys.stderr)
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            traceback.print_exc(file=f)
    except OSError:
        pass
    raise
