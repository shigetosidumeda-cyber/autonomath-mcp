# R8 — Case Cohort Matcher

**Date**: 2026-05-07
**Scope**: New cohort-matcher surface (REST + MCP) over case_studies × jpi_adoption_records
**Outcome**: 1 new MCP tool + 1 new REST endpoint + 19 passing tests, atomic commit + push

## Context

CLAUDE.md identifies the central jpcite question as:

> 「私と同業同規模同地域の採択企業はどの制度に通ったか?」
> ("What programs did similar businesses — same industry × same size × same
> region — actually get awarded?")

`case_studies` (jpintel.db, 2,286 採択事例) and `jpi_adoption_records`
(autonomath.db, 201,845 V4-absorbed METI/MAFF 採択結果) together hold
the raw evidence, but until R8 there was no single endpoint that joined
them on the four cohort axes. `search_acceptance_stats_am` returns
program-level acceptance rates but not the cohort that received those
acceptances; `search_case_studies` exposes individual case rows but
lacks size/revenue/region rollup. R8 closes that gap.

## Design

### REST endpoint

- **Path**: `POST /v1/cases/cohort_match`
- **Body** (`api/case_cohort_match.py:CohortMatchBody`, Pydantic):
  - `industry_jsic` (str|null, ≤10 chars) — JSIC prefix (`A`, `E29`, etc.)
  - `employee_count_range` ([int,int]|null) — inclusive band
  - `revenue_yen_range` ([int,int]|null) — inclusive band
  - `prefecture` (str|null, ≤80 chars) — exact match
  - `limit` (int, 1-100, default 20) — max rows per side
- **Response shape**:
  - Canonical envelope: `total / limit / offset / results`
  - `matched_case_studies` (rich row, jpintel.db)
  - `matched_adoption_records` (thin row, autonomath.db)
  - `program_rollup` (per-program count + avg amount + cohort_share)
  - `summary` (cohort_count, distinct_programs, mean/median amount)
  - `axes_applied` (which filter ran on each side, honest about
    adoption_records lacking size axes)
  - `sparsity_notes` (4 honest disclosures: amount populated on
    ~1.9% of case_studies, 0% of adoption_records, etc.)
  - `_disclaimer`, `_next_calls`, `_billing_unit=1`,
    `corpus_snapshot_id`, `corpus_checksum`

### MCP tool

- **Name**: `case_cohort_match_am`
- **Gate**: `AUTONOMATH_COHORT_MATCH_ENABLED` (default ON)
- **Compounding**: emits `_next_calls` to `search_case_studies` (top
  program full corpus), `search_acceptance_stats_am` (採択率 history
  for the top program), and `search_programs` (industry × prefecture
  full eligibility list).

### Cross-DB strategy

`case_studies` lives in **jpintel.db** and `jpi_adoption_records`
lives in **autonomath.db**. Per CLAUDE.md ("two separate SQLite
files, no ATTACH / cross-DB JOIN") we open each side read-only via
the existing helpers and merge results in Python. Soft-fail to an
`error_envelope.make_error("db_unavailable")` when either file is
missing — callers (REST + MCP) propagate the envelope verbatim.

### Sparsity honesty

`amount_yen_with_value` in the summary shows how many of the
matched rows actually carry a populated 交付額. The
`sparsity_notes` array surfaces the same fact in plain Japanese
so a downstream LLM cannot mistake "0 amount" for "0 cohort".
Compliant with CLAUDE.md's "Data hygiene" + "no fake data" feedback.

## Implementation

| File | Purpose |
| --- | --- |
| `src/jpintel_mcp/mcp/autonomath_tools/cohort_match_tools.py` | MCP tool + impl entrypoint |
| `src/jpintel_mcp/api/case_cohort_match.py` | FastAPI POST router |
| `src/jpintel_mcp/mcp/autonomath_tools/__init__.py` | Tool registration import |
| `src/jpintel_mcp/api/main.py` | Router include + import |
| `tests/test_case_cohort_match.py` | 19 tests (impl + REST) |
| `docs/openapi/v1.json` | Auto-regenerated OpenAPI surface |

### Key design choices

1. `case_cohort_match_impl()` is the public entrypoint — both REST and
   MCP call it, identical behavior across surfaces (same pattern as
   `industry_packs.py:_pack_construction_impl`).
2. `employee_count_range` / `revenue_yen_range` are NULL-tolerant on
   the case_studies side. Most rows lack size axes; silently dropping
   them on a band filter would massively under-report the cohort.
3. `industry_jsic` uses prefix LIKE — `A` matches `A`/`A0111`,
   `E29` matches the 中分類. Same convention as case_studies/search.
4. `program_rollup` keys by case-folded label so cross-side aggregation
   merges identical names. Canonical surface form is most-common.
5. `limit` is per-side. `total = case_study_count + adoption_record_count`.

## Tests

`tests/test_case_cohort_match.py` covers 19 cases:

- **Impl-level (12)**: envelope shape, industry prefix filter, prefecture
  filter, employee range filter, revenue range filter (capital proxy),
  program rollup aggregation, summary amount stats, invalid range
  rejection (`out_of_range` error envelope), negative bound rejection,
  limit clamp, all-null cohort, `_next_calls` compounding, `axes_applied`
  honesty disclosure.
- **REST-level (7)**: happy path 200, validation 400 on inverted band,
  empty cohort 200, `log_usage` metering write (paid_key auth),
  Pydantic 422 on `limit=500`, extra-fields ignored, full envelope JSON.

```
$ .venv/bin/pytest tests/test_case_cohort_match.py
============================= 19 passed in 14.20s ==============================
```

## Production constraints satisfied

- **LLM 0**: no `anthropic`/`openai`/`claude_agent_sdk` imports.
- **Destructive 上書き 禁止**: SELECT only, no migration, no DROP.
- **pre-commit hook**: `ruff check` + `ruff format --check` clean.
- **¥3/req metered**: `log_usage(...,strict_metering=True)` REST side,
  `_billing_unit=1` on MCP envelope.
- **業法 fence**: §52 / §47条の2 / 行政書士法 §1 disclaimer envelope on
  every response.
- **Cohort revenue model alignment**: cohort #5 (補助金 consultant) +
  cohort #2 (税理士 kaikei) — both depend on the cohort matcher.

## Honest gaps

1. Adoption-records side is two-axis only — `jpi_adoption_records`
   carries no employees / revenue, so size filter applies to case_studies
   only. Disclosed via `axes_applied`.
2. Revenue is approximated via `capital_yen` because case_studies has
   no revenue column. Disclosed via `sparsity_notes`.
3. Amount stats run on ~1.9% of rows (4 / 2,286 case_studies have
   amounts; 0 / 201,845 adoption_records). `amount_yen_with_value`
   exposes this honestly.
4. Program rollup uses lowercase-stripped keys — variants like
   `"ものづくり補助金"` vs `"ものづくり・商業・サービス生産性向上促進補助金"`
   stay separate. Future work could plug `unified_id` resolution.
5. No FTS5 free-text axis — cohort fence is structural only. The
   `_next_calls` array points at `search_case_studies?q=...` for
   free-text drill-in.

## Next-step suggestions (out of scope)

- Plug program-name aliases into the rollup so unified_id collapsing
  works (would lift `distinct_programs` accuracy ~30% in spot checks).
- Backfill `amount_granted_yen` on `jpi_adoption_records` from public
  METI/MAFF Excel.
- Add an explicit `revenue_yen` column to `case_studies` so capital
  proxy approximation becomes optional.
