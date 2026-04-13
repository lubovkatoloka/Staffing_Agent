"""Load YAML config from repo `config/`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _ROOT / "config"


def load_decision_config() -> dict[str, Any]:
    """Full Decision Logic snapshot (`config/decision_logic.yaml`)."""
    path = _CONFIG_DIR / "decision_logic.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_thresholds() -> dict[str, Any]:
    """Backward-compatible name: same document (spec_version + occupation + …)."""
    return load_decision_config()


def load_tier_classification_prompt() -> dict[str, Any]:
    """Node 1 tier rules for LLM (`config/tier_classification.yaml`)."""
    path = _CONFIG_DIR / "tier_classification.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
