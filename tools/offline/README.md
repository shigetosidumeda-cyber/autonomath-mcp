# tools/offline/

Operator-only offline scripts. **Not part of the production runtime.**

## Rules

- Scripts here are run **manually by the operator** on a workstation, never
  invoked from production code paths (`src/`, `scripts/cron/`, `scripts/etl/`).
- These scripts **MAY use external APIs** (LLM providers, paid third-party
  data sources, etc.) but **only with explicit operator authorization**
  (e.g. an `ANTHROPIC_API_KEY` exported in the operator's local shell).
- Production code MUST NOT import from this directory. The CI guard at
  `tests/test_no_llm_in_production.py` enforces that no LLM SDK
  (`anthropic`, `openai`, `google.generativeai`, `claude_agent_sdk`) and
  no LLM API-key env vars (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  `GEMINI_API_KEY`, `GOOGLE_API_KEY`) leak into `src/`, `scripts/`, or
  `tests/`.
- CI **does not** test, lint, or import these scripts. They are excluded
  from the deployable artifact (Fly.io image, PyPI sdist, MCP bundle).

## Why isolate?

Per `feedback_autonomath_no_api_use` (operator memory) and the
`No-LLM` invariant in the launch plan: AutonoMath bills ¥3/request fully
metered. Any per-request LLM call would bankrupt the unit economics.
The runtime must remain pure SQLite + deterministic Python.

Offline ETL backfills (e.g. precomputing English aliases for the corpus)
are charged to the operator's developer-budget API key once and written
to the database as static reference data. The runtime then JOINs them
as plain rows.

## Current contents

This directory now holds several kinds of operator-only material:

- `INFO_COLLECTOR_*.md` — prompts and loop specifications for large external
  information-collection runs. These are versionable because they define the
  repeatable research protocol.
- `run_*_batch.py`, `*_batch.py`, and `dispatch_*.sh` — local batch jobs that
  precompute or ingest data under explicit operator control.
- `ingest_*`, `extract_*`, `embed_*`, and `iter_*` scripts — one-off or
  repeatable offline ETL helpers.
- `_runner_common.py` — shared helper code for offline runners only.
- `_inbox/`, `_outbox/`, `_quarantine/`, and `_done/` — run artifacts and
  raw captures. These are ignored by git and should be summarized into source
  tables, migration notes, or `docs/_internal/` reports instead of committed
  wholesale.

## Adding a new offline script

1. Put repeatable operator prompts or local-only runners in `tools/offline/`.
2. Put deployable cron jobs in `scripts/cron/`, reusable ETL in `scripts/etl/`,
   and operational checks in `scripts/ops/`.
3. Add a top-of-file header to executable offline scripts:
   ```
   # OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, or scripts/etl/.
   ```
4. Confirm `tests/test_no_llm_in_production.py` still passes when the script
   uses LLM or paid API dependencies.
5. Do NOT add imports of this script anywhere under `src/` or deployable
   `scripts/` modules.
6. Keep bulky run output in the ignored artifact roots above. Commit only the
   prompt/spec, compact rollup, migration, test, or deterministic source table.
