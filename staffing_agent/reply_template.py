"""
Slack reply shape for @mention pipeline (paste_run + socket).

**Goal:** avoid dumping raw tables; keep the bot reply readable.

## Reply template (section order)

1. **Phase A — context** — briefly: message count, URLs, thread text (preview).
2. **Phase B — extraction (Node 1)** — JSON `RequestSpec` (tier, tags, summary).
3. **Node 2** — Tier pool rules (short).
4. **Node 3 — availability** (Databricks):
   - **compact:** first *Recommendation: who can take the project*, then a short load summary
     (first N Occupation rows with Tier filter), PTO and Active projects — counts/names only, no walls of text.
   - **full:** long spec checklist, up to 15 table rows, role buckets, full optional SQL pulls.
5. **Decision Logic — follow-up** — in compact: one line + Notion links; in full: expanded Node 4 / 4.5 / 5.
6. **Similar projects** — optional from CSV “Projects & Offers Classification” (`config/projects_classification.yaml`) by Phase B tags.
7. **Phase C** — demo bands + short DBX hint.

Switch: env `STAFFING_AGENT_REPLY_STYLE` = `minimal` | `compact` | `full` (default: minimal).

- **minimal** — short request summary + recommendation and short “why” (no JSON, no exclusion lists, no PTO/similar/Phase C).
- **compact** — summary + Nodes 2–3 with Occupation preview; no PTO/active/follow-up/similar/Phase C.
- **full** — full output (as before).
"""

from __future__ import annotations

import os
from typing import Literal

ReplyStyle = Literal["minimal", "compact", "full"]


def reply_style() -> ReplyStyle:
    v = (os.environ.get("STAFFING_AGENT_REPLY_STYLE") or "minimal").strip().lower()
    if v == "full":
        return "full"
    if v == "compact":
        return "compact"
    return "minimal"


# Limits for compact mode
COMPACT_OCCUPATION_PREVIEW_ROWS = 5
FULL_OCCUPATION_PREVIEW_ROWS = 15
COMPACT_PTO_NAME_SAMPLES = 5
