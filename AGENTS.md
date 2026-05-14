# Agent guide — Staffing Agent

You are picking up a ticket from the Implementation Tasks database
(parent: Staffing Agent v2 Requirements Tracker, Notion).
This file is the rules of the road. Read it once at the start of every session.

## What this repo is

Slack bot that answers `@who_is_available` with staffing recommendations
(SO / SoE / WFM / SE pools) based on:

- Capacity v2 formula → `staffing_agent/decision/capacity.py`
- Live Notion People & Tags → `staffing_agent/exclusions.py`
- Databricks SQL (capacity + project staffing) → `sql/capacity.sql`,
  `sql/project_staffing.sql`
- LLM tier classification (Anthropic Opus) → `staffing_agent/extraction.py`

Audience of the bot's Slack output: Sales, Leadership, DPMs (non-engineers).
No raw JSON in Slack, no engineer jargon.

## Source of truth

1. **Requirements Tracker (Notion):**
   https://www.notion.so/34b49d06885681468dd6d79d2e16d332
   — describes what the bot must do (CR-1…CR-8, S1…S4).
2. **Implementation Tasks database (child of Tracker):**
   one row = one PR. Body of the row contains your brief.
3. **This file:** how to execute. Code conventions, test conventions,
   what's off-limits.

If a ticket conflicts with the Tracker — STOP and ask. Do not "fix the
Tracker to match the code" or vice versa without confirmation.

## Workflow per ticket

1. Read AGENTS.md (this file).
2. Read the ticket body in Notion. Note `Files to change` and `Out of scope`.
3. Read the linked CR-N section in Tracker — that is the spec.
4. Create a branch: `staffing/<ticket-slug>` (e.g. `staffing/cr-6-kill-mock-tier`).
5. Make the smallest diff that satisfies the Acceptance section.
6. Run `python -m pytest tests/ -q` — must be green before pushing.
7. Open a PR with body referencing the Notion ticket URL.
8. Stop. Do not pick up the next ticket on your own.

## Code rules

- Stay inside `Files to change`. Touching anything in `Out of scope` requires
  asking first.
- No speculative refactoring. Three similar lines are better than a premature
  abstraction. If a related cleanup is tempting — note it in PR description,
  do not include it in the diff.
- No new abstractions / config files / modules unless the ticket calls for one.
- No comments explaining what the code does. Comments only for non-obvious
  invariants (rare). No "removed X" / "added for Y flow" comments.
- No dead defensive code. Only validate at system boundaries (user input,
  external APIs). Trust internal code.
- Match existing style. If existing function uses `Mapping[str, Any]`, don't
  switch to `dict[str, Any]` just because.
- Type hints on new public functions. Not on every internal helper.

## Test rules

- Every behavior change has a test. Failing test first, then the fix —
  if the bug is reproducible at unit level.
- Tests live in `tests/test_<module>.py` matching the source file.
- Use the fixtures in `tests/conftest.py` — don't invent new ones if existing
  works.
- pytest must be green: `python -m pytest tests/ -q`. Don't merge red.
- If a test in `Out of scope` files starts failing — STOP. Don't "fix" it,
  ask. It means the change leaked.

## Slack output rules (when ticket touches user-visible reply)

- Never raw JSON in Slack. JSON only in stderr logs.
- Slack mrkdwn (asterisks for bold, backticks for code, `<url|label>`).
  Not Markdown.
- Each Slack message ≤ 12 000 chars. Split if longer.
- English, regardless of thread language (per CR-1 of Tracker).
- Compact, scannable. Section headers are bold. Max 2 levels of bullets.

## Git / PR conventions

- Branch: `staffing/<ticket-slug>`.
- Commit messages: imperative present tense, ≤72 chars subject line.
  Reference the ticket: `CR-6: kill mock-tier fallback`.
- PR title = commit subject. PR body links the Notion ticket URL and lists
  what changed in 3–5 bullet points.
- One ticket = one PR. Don't bundle.

## What you must NOT do

- Don't push to `main` / `master` / `claude/*` branches. Use your own
  `staffing/*` branch.
- Don't `--no-verify` commits, don't `--force` push.
- Don't update dependencies in `requirements.txt` unless the ticket asks for it.
- Don't add CI / GitHub Actions / Docker / Makefile entries unless the ticket
  asks for it.
- Don't change `.env.example`, `.env`, or any secret unless the ticket asks.
- Don't delete `sql/*.sql` files even if they look unused — Liuba uses them
  manually from the Databricks console.
- Don't add LICENSE / CONTRIBUTING.md / new README sections.

## Environment

- Python 3.11+
- `pip install -r requirements.txt` first time
- For tests Anthropic is mocked — `ANTHROPIC_API_KEY` not needed
- For local Slack run see README.md

## When something is ambiguous

Ask one specific question. Don't guess. Don't pick "the most common
interpretation". The ticket body should answer it; if not, that's the
ticket author's gap to fill, not yours to invent.
