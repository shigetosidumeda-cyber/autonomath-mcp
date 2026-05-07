# R8 — Industry Benchmark Surface (cohort average + outliers)

**Date**: 2026-05-07
**Scope**: New benchmark + outlier surface (REST + MCP) over case_studies × jpi_adoption_records
**Outcome**: 1 new MCP tool + 2 new REST endpoints + 15 passing tests, idempotent inject + push

## Context

The cohort matcher (R8 case_cohort_match) returns the row-set of the
caller's cohort. The next layer the user demanded is the **benchmark +
取りこぼし** lens:

> 「私 (業種X 中小Y 都道府県Z) の 業界平均 vs 私の活用度」
> ＝ 使える制度 取りこぼし 検知

Existing tools answered cohort *who* and per-program *acceptance rate*
(`search_acceptance_stats_am`) but no single endpoint returned **average
採択額 + 採択件数 + 制度hit数 + outlier 法人 (top 10%)** for a 3-axis
JSIC × size × prefecture cohort, nor did any endpoint surface the
caller's own usage_events against that cohort baseline. R8 closes both.

## Design

### REST endpoints

#### 1. POST /v1/benchmark/cohort_average

- **Path**: `POST /v1/benchmark/cohort_average`
- **Body** (`api/benchmark.py:CohortAverageBody`, Pydantic):
  - `industry_jsic` (str|null, ≤10 chars) — JSIC prefix (`D`, `E29`, etc.)
  - `size_band` (str|null) — `'small'` (≤¥50M capital) / `'medium'` (¥50M–¥300M) / `'large'` (>¥300M) / `'all'`
  - `prefecture` (str|null, ≤80 chars) — exact match
- **Response shape**:
  - `cohort_size` / `case_study_count` / `adoption_record_count`
  - `distinct_programs` (sorted str list) + `distinct_program_count`
  - `accept_rate_proxy` (directional, NOT real 採択率)
  - `amount_summary` (count + mean / median / min / max / total in yen)
  - `outlier_top_decile` (top 10% rows by amount_yen DESC, ceiling 1)
  - `axes_applied` (size_band capital_yen bounds disclosed)
  - `sparsity_notes` (4 honest disclosures)
  - `_disclaimer`, `_next_calls`, `_billing_unit=1`

#### 2. GET /v1/me/benchmark_vs_industry

- **Path**: `GET /v1/me/benchmark_vs_industry`
- **Auth**: X-API-Key / Bearer required (401 otherwise)
- **Query**: `industry_jsic`, `size_band`, `prefecture`, `window_days` (1..365, default 90)
- **Response shape**:
  - `cohort` — same shape as POST endpoint, summary fields
  - `me` — `total_program_touches`, `endpoint_hits` (per-program-touch endpoint), `my_program_touches_known=False`, `reach_pct`
  - `leakage_programs` — cohort distinct programs the caller hasn't touched yet (= 取りこぼし候補)
  - `axes_applied`, `sparsity_notes`, `_disclaimer`

### MCP tool

- **Name**: `benchmark_cohort_average_am`
- **Gate**: `AUTONOMATH_BENCHMARK_ENABLED` (default ON)
- **Compounding**: emits `_next_calls` to `case_cohort_match_am`
  (full cohort rows for the same axes) and `search_acceptance_stats_am`
  (replace directional accept_rate_proxy with a real one for the top
  program).

The "me vs industry" lens is intentionally REST-only because it needs
an authenticated request scope to read `usage_events`. The MCP tool
exposes the public cohort baseline only.

### Cross-DB strategy

Same as R8 case_cohort_match: `case_studies` lives in **jpintel.db**
and `jpi_adoption_records` in **autonomath.db**. Per CLAUDE.md ("two
separate SQLite files, no ATTACH / cross-DB JOIN") we open each side
read-only and merge results in Python. Soft-fail to an empty list when
the autonomath side is unavailable.

The **me_vs_industry** lens reads `usage_events` (jpintel.db) scoped
to the caller's parent/child key tree (migration 086 semantics, mirrored
from `api/me.py::_resolve_tree_key_hashes`). No PII leak — the caller
only ever sees their own rows.

### Honesty surface

- **`my_program_touches_known=False`**: usage_events stores
  `params_digest` (hashed) — there's no per-program touch column. The
  endpoint does NOT pretend to know which programs the caller actually
  searched for; `leakage_programs` defaults to the full cohort
  distinct-program set as a precaution.
- **`accept_rate_proxy`**: case_studies + jpi_adoption_records are both
  positive (採択) rows, no applicant denominator. The proxy is
  directional, called out in sparsity_notes, NOT a real 採択率.
- **`outlier_top_decile`**: amount-driven, ceiling 1. Rows missing
  amount are excluded from outlier ranking but counted in cohort_size.

## Implementation

| File | Purpose |
| --- | --- |
| `src/jpintel_mcp/mcp/autonomath_tools/benchmark_tools.py` | MCP tool + impl entrypoints (`benchmark_cohort_average_impl`, `benchmark_me_vs_industry_impl`) |
| `src/jpintel_mcp/api/benchmark.py` | FastAPI POST + GET routers |
| `src/jpintel_mcp/mcp/autonomath_tools/__init__.py` | Tool registration import |
| `src/jpintel_mcp/api/main.py` | Router include + import |
| `tests/test_benchmark_cohort_average.py` | 15 tests (10 impl + 5 REST) |
| `docs/openapi/v1.json` | Regenerated — 218 → 219 paths |

## Constraints upheld

- **NO LLM**: zero `anthropic` / `openai` imports anywhere in the new
  files. CI guard `tests/test_no_llm_in_production.py` passes.
- **Pure read-only**: every DB connection opened via
  `?mode=ro` URI (jpintel.db) and `connect_autonomath()`
  (autonomath.db). No DDL, no migration, no destructive write.
- **Disclaimer envelope**: `_DISCLAIMER_BENCHMARK` covers 税理士法 §52
  / 公認会計士法 §47条の2 / 行政書士法 §1 / 経営判断 simultaneously,
  on every 2xx body.
- **Single ¥3/req billing unit**: `_billing_unit=1` on every body;
  `log_usage(strict_metering=True)` on both REST handlers.
- **¥3/req only**: no tier badge, no Pro feature gate, no seat counter.

## Verification

- `pytest tests/test_benchmark_cohort_average.py`: **15/15 PASS**
- `pytest tests/test_benchmark_cohort_average.py tests/test_case_cohort_match.py`: **34/34 PASS** (no fixture cross-pollination)
- `pytest tests/test_endpoint_smoke.py tests/test_no_llm_in_production.py`: **83/83 PASS**
- `ruff check src/jpintel_mcp/api/benchmark.py src/jpintel_mcp/mcp/autonomath_tools/benchmark_tools.py tests/test_benchmark_cohort_average.py`: **clean**
- `ruff format` applied.
- `mypy src/jpintel_mcp/api/benchmark.py src/jpintel_mcp/mcp/autonomath_tools/benchmark_tools.py`: **clean** (no new errors).
- OpenAPI regenerated: `docs/openapi/v1.json` 218 → 219 paths; both new paths present.

## Live cohort smoke (example)

```
benchmark_cohort_average_impl(industry_jsic="D", size_band="small", prefecture="東京都")
→ cohort_size=878, distinct_program_count=11, amount_yen_with_value=0
```

Cohort 数 is healthy; jpi_adoption_records.amount_granted_yen still 0/201,845
populated, so amount_summary is sparse for any cohort that filters down to
adoption_records-only. case_studies side is the only contributor to amount —
called out in sparsity_notes verbatim.

## Honest gap

`my_program_touches_known=False` is the headline weakness: until
`usage_events` carries a per-row program_id (or a deterministic
`programs_touched` column), the leakage_programs list is the full
cohort distinct-program set, not a real diff. A future migration that
adds `usage_events.program_id` (NULL when not applicable) would let
the endpoint compute a real `reach_pct` and `leakage_programs` =
cohort − me. That's a follow-up, not blocking this surface.
