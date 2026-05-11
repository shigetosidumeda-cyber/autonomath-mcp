# tools/offline/

> ⚠️ **WARNING — OPERATOR ONLY. NOT PART OF PRODUCTION.**
>
> Scripts under this directory may import LLM SDKs (`anthropic`, `openai`,
> `google.generativeai`, `claude_agent_sdk`) and may read LLM provider API
> keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`,
> `GOOGLE_API_KEY`). **Nothing under `src/`, `scripts/cron/`, `scripts/etl/`,
> or `tests/` may import from here, depend on these tools, or replicate
> their behavior at request time.** Violating this isolation bankrupts the
> ¥3/req unit economics (see operator memory `feedback_no_operator_llm_api`
> and `feedback_autonomath_no_api_use`).

## Why this directory exists

Per the operator-LLM invariant (operator memory `feedback_no_operator_llm_api`,
ratified after a 5,000円 loss on 2026-04-24) and the No-LLM constraint in
CLAUDE.md §"What NOT to do":

- The jpcite runtime bills **¥3/req fully metered** (税込 ¥3.30, with
  anonymous 3 req/day free). One internal LLM round-trip costs ¥0.5–¥5 of
  Anthropic API spend per call. A single LLM-touching request would erase
  the gross margin and a sustained pattern would post negative gross.
- Therefore **every request-path code path must be deterministic SQLite +
  Python**. No LLM call. No SDK import. No API key read.
- Bulk offline ETL (alias generation, narrative extraction, batch
  translation, etc.) is paid for **once** out of the operator's developer
  budget and the output is written to the database as static rows. The
  runtime then JOINs the precomputed columns at zero marginal LLM cost.
- This directory is the **only** legitimate home for code that imports an
  LLM SDK or reads an LLM API-key env var.

## Hard rules

1. **No production import path may reach this directory.** The CI guard
   at `tests/test_no_llm_in_production.py::test_offline_dir_is_not_imported_from_production`
   enforces this with an AST walk over `src/`, `scripts/cron/`,
   `scripts/etl/`, and `tests/`. Any `from tools.offline import ...` or
   `import tools.offline.foo` is a hard fail.
2. **No production code may import any LLM SDK.** The CI guard at
   `tests/test_no_llm_in_production.py::test_no_llm_imports_in_production`
   AST-walks `import anthropic` / `from anthropic import ...` /
   `openai` / `google.generativeai` / `claude_agent_sdk` across the same
   four trees. `tools/offline/` is the only directory excluded.
3. **No production code may read an LLM API-key env var on a real code
   line.** Same test, env-var axis: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
   `GEMINI_API_KEY`, `GOOGLE_API_KEY` are forbidden on non-comment,
   non-docstring lines of `.py` files. Comments and docstrings that name
   the env vars in an "NO `ANTHROPIC_API_KEY`" enforcement context are
   tolerated by the AST-span heuristic.
4. **No hardcoded provider secrets anywhere.** The CI guard also scans
   for `sk-ant-...`, `sk-...`, and `AIzaSy...` literal patterns. Real
   secrets live in `.env.local` (chmod 600, git-ignored, see operator
   memory `reference_secrets_store`) and Fly secrets, never the repo.
5. **`# noqa` does not unlock this guard in production.** The test allows
   a `# noqa: F401  # LLM_IMPORT_TOLERATED` marker only on files under
   `tools/offline/` itself. Adding the same marker to a `src/` or
   `scripts/cron/` file fails CI by design.
6. **No CI workflow may execute an LLM SDK on a runner.** The
   `test_no_llm_in_workflow_inline_python` test scans inline-python
   regions (`python -c "..."`, `python <<'PY' ... PY` heredocs) inside
   `.github/workflows/*.yml` for the same forbidden surface. GHA runners
   are part of production CI/CD; nothing they execute may touch an LLM.

## Operator runtime expectations

- Run scripts **manually** from a workstation, not from cron, not from
  GHA, not from Fly. There is no production process that should ever
  invoke a script in `tools/offline/`.
- Authorize each LLM-touching run **explicitly** by exporting the key in
  your local shell (e.g. `export ANTHROPIC_API_KEY=$(...)`), running the
  script, then unsetting the variable. Do not bake keys into shell
  profiles or `.env.local` lines that production code might read.
- Treat artifact directories (`_inbox/`, `_outbox/`, `_quarantine/`,
  `_done/`) as **scratch space**. Summarize useful output into a
  migration, source table, or `docs/_internal/` report and commit only
  the deterministic distilled output, never the raw run.
- Cost-of-run discipline: bill the developer-budget API key, not the
  ¥3/req production billing pipeline. If a batch is too expensive,
  rate-limit at the script level and pause until a fresh budget window.

## Currently-present material

This directory holds operator-only prompts, batch runners, and ETL
helpers under explicit operator control. The exact roster drifts with
each Wave; the README intentionally does not enumerate filenames to
avoid drift-prone documentation. Inspect the directory contents with
`ls tools/offline/` to see what is currently checked in.

Three categories you may find:

- **Prompt / loop specifications** — markdown files (often
  `INFO_COLLECTOR_*.md` shape) that describe a repeatable research
  protocol. Versionable.
- **Batch runners and ETL helpers** — Python entrypoints and shell
  dispatchers that read source artifacts and write deterministic output
  back to the database. May import LLM SDKs.
- **Scratch / quarantine artifacts** — git-ignored captures from in-flight
  runs. Summarize and discard; do not commit.

## Adding a new offline script

1. Place repeatable operator prompts, batch runners, or ETL helpers in
   `tools/offline/`. Anything that imports an LLM SDK or reads an LLM
   API-key env var must live here.
2. Production cron jobs go in `scripts/cron/`, reusable production ETL
   in `scripts/etl/`, operational checks in `scripts/ops/`. None of
   those may import LLM SDKs or read LLM API keys.
3. Add a top-of-file banner to executable offline scripts:
   ```
   # OPERATOR ONLY: Run manually from tools/offline/. Never imported from
   # src/, scripts/cron/, scripts/etl/, or tests/. May import LLM SDKs.
   ```
4. Run `pytest tests/test_no_llm_in_production.py -v` locally before
   committing. All five axes must stay green.
5. Do **NOT** add `from tools.offline import ...` or
   `import tools.offline.foo` anywhere outside this directory.
6. Keep bulky run output in the ignored artifact roots. Commit only
   prompt specs, compact rollups, migrations, tests, or deterministic
   source tables — not raw run dumps.

## Internal-path-only history note

The legacy import path `src/jpintel_mcp/` is retained for distribution
backward compatibility (the PyPI package is `autonomath-mcp` but the
source module is the historical `jpintel_mcp`). The user-facing brand
is **jpcite**; do not surface internal path names in any operator-
facing copy emitted from scripts under this directory.
