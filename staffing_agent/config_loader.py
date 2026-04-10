"""Load YAML config from repo `config/`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _ROOT / "config"


def load_thresholds() -> dict[str, Any]:
    path = _CONFIG_DIR / "thresholds.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
