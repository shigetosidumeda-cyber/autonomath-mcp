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

- `batch_translate_corpus.py` — Offline JP→EN alias backfill into
  `am_alias.language='en'`. Manual operator execution only.

## Adding a new offline script

1. Drop it in `tools/offline/`.
2. Add a top-of-file header:
   ```
   # OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, or scripts/etl/.
   ```
3. Confirm `tests/test_no_llm_in_production.py` still passes.
4. Do NOT add imports of this script anywhere under `src/` or `scripts/`.
