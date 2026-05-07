# R8: am_compat_matrix full-surface (2026-05-07)

Status: shipped to source on 2026-05-07.

## Summary

`am_compat_matrix` (43,966 rows; 4,300 sourced + 39,666 heuristic
inferences flagged via `inferred_only=1`) was previously exposed only via
`find_complementary_programs_am` (1-seed → portfolio neighbours) and
indirectly through `intel_conflict` / `intel_portfolio_heatmap`. Both
surfaces leaked the matrix's "ポートフォリオ最適化" + "重複/排他 risk
check" axes into adjacent intelligence flows, never as a first-class
program × program contract.

This packet promotes the matrix to a public, stable surface:

- **POST `/v1/programs/portfolio_optimize`**
  Multi-program portfolio optimizer. Body
  `{candidate_program_ids: [...], target_axes: ["coverage", "amount", "risk"]}`.
  Returns the recommended portfolio (greedy max-IS), `duplicate_risk` (pairs
  flagged via empirical / legal / matrix), `axis_scores` (per-axis [0,1]
  for the primary portfolio), `recommended_mix` (top-3 bundles ranked by
  axis-weighted score) and `data_quality` (missing-table flags +
  authoritative-share caveat).
- **GET `/v1/programs/{a}/compatibility/{b}`**
  4-bucket pair verdict: `compatible | mutually_exclusive | unknown |
  sequential`. The 4th bucket (`sequential`) is new and surfaces temporal
  precedence edges in `am_relation`
  (`requires_before` / `precedes` / `follows` / `superseded_by`) so
  customer LLMs can reason about 段階申請 cases that the legacy 3-bucket
  vocabulary collapses into "compatible".
- 2 MCP tools mirror the REST contract: `portfolio_optimize_am` and
  `program_compatibility_pair_am`. Both are gated by
  `AUTONOMATH_COMPATIBILITY_TOOLS_ENABLED` (default ON).

NO LLM call inside any of the four entry points. Pure SQLite + Python
greedy walk; ¥3 / call billing per the standard surface contract.

## File map

| Path | Purpose |
| --- | --- |
| `src/jpintel_mcp/api/compatibility.py` | REST surface (router with both endpoints) |
| `src/jpintel_mcp/mcp/autonomath_tools/compatibility_tools.py` | MCP impls + tool registration |
| `src/jpintel_mcp/api/main.py` (≈line 1893) | Router wiring under `programs_router` neighbourhood |
| `src/jpintel_mcp/mcp/autonomath_tools/__init__.py` (`compatibility_tools`) | MCP package import + tool register |
| `tests/test_compatibility.py` | 15 tests covering REST + MCP + graceful degradation |
| `docs/openapi/v1.json` | regenerated, both new paths land at the top of the programs cohort |

## Resolution stack

The pair-verdict resolver hits four sources in priority order:

1. **am_program_eligibility_predicate** (legal) — operator
   `NOT_IN | != | CONTAINS` whose `value_text` references the
   counterparty → `mutually_exclusive`.
2. **am_funding_stack_empirical** (実証 stack co-occurrence) — `conflict_flag=1` on
   the (lo, hi) ordered pair → `mutually_exclusive`.
3. **am_compat_matrix.compat_status** —
   `incompatible` → `mutually_exclusive`,
   `compatible` → `compatible`,
   `case_by_case` → `compatible` (with conditions caveat),
   `unknown` → `unknown`.
4. **am_relation** — temporal precedence edges
   (`requires_before` / `precedes` / `follows` / `sequential` / `superseded_by`)
   → `sequential` when no incompatibility from sources 1-3 fired.

`evidence` always carries every source row that was consulted, not only
the deciding source, so customer LLMs get the full picture in a single
RPC.

## Portfolio scoring

`recommended_mix` runs four greedy seeds and dedupes by sorted-bundle
key:

- `max_amount_compatible_subset` — sort by descending `programs.amount_max_man_yen × 10000`, drop conflicts.
- `alt_without_<top>` — drop the top-amount program, re-run.
- `tier_safest_subset` — sort by ascending `_TIER_RISK[tier]` (S=10..X=90).
- `max_coverage_subset` — bias programs that carry a `program_kind` first.

Each bundle reports:
- `score` — equal-weighted average of per-axis scores in [0, 1].
- `axis_scores` — `{coverage, amount, risk}` mapping (saturates at
  ¥1B / 5 distinct kinds / `1 - mean(tier_risk)/100`).
- `expected_total_amount` — yen sum across bundle.
- `rationale` — which seed produced it.

Bundles are ranked by `(-score, sorted(bundle))`, returned top-3.

## Graceful degradation

Each backing-table miss is recorded in `data_quality.missing_tables`
without raising. Tested under a bare autonomath.db with only a `meta`
table — the pair endpoint returns `compatibility="unknown"` with all 4
sources listed missing; the portfolio endpoint returns the input set as
the portfolio and an empty `duplicate_risk`.

## Sensitive-surface envelope

Every response body carries the standard `_disclaimer` string fencing
税理士法 §52 / 行政書士法 §1 / 弁護士法 §72. `inferred_only` is surfaced
on the pair endpoint and on every `duplicate_risk` row so the customer
LLM can downweight heuristic edges before relaying to an end user.

## Tests

`tests/test_compatibility.py` — 15 tests.

- Pair verdicts: matrix-compatible / legal-predicate / empirical /
  sequential / unknown / 422 same-program / 422 invalid id.
- Portfolio: max-amount subset / axis-score normalization / 422
  insufficient candidates / unknown-axes-default-to-amount / graceful
  bare DB.
- MCP impls: 4-bucket coverage + recommended_mix shape + invalid_input
  on a == b.

`pytest tests/test_compatibility.py -x` → **15 passed in 29.30s**.

## OpenAPI

`scripts/export_openapi.py --out docs/openapi/v1.json` regenerated.
Stable path count moved from 216 → **218** (the 2 preview surfaces are
unchanged). Verify:

```
$ grep -c '"/v1/programs/portfolio_optimize"\|"/v1/programs/{a}/compatibility/{b}"' \
    docs/openapi/v1.json
2
```

## Manifest accounting

This packet adds:
- 2 REST paths (already counted in the regenerated `docs/openapi/v1.json`).
- 2 MCP tools (`portfolio_optimize_am`, `program_compatibility_pair_am`)
  behind a default-ON gate (`AUTONOMATH_COMPATIBILITY_TOOLS_ENABLED`).

Per CLAUDE.md "Do not bump manifest tool_count without intentional
release." — `pyproject.toml` / `server.json` / `dxt/manifest.json` /
`smithery.yaml` / `mcp-server.json` stay at 139 until the next planned
manifest bump. Verify on next bump with
`len(await mcp.list_tools())`.

## Hard constraints honoured

- LLM 0: no `anthropic` / `openai` / `claude_agent_sdk` import in the new
  files. CI guard `tests/test_no_llm_in_production.py` continues to pass.
- ¥3/req metered: every entry point sets `_billing_unit = 1` and routes
  through `log_usage(..., strict_metering=True)`.
- `attach_seal_to_body` + `attach_corpus_snapshot` wired so audit-seal
  consumers see the new endpoints alongside existing intel surfaces.
- pre-commit: ruff + ruff-format clean; pre-existing pre-commit drift
  unrelated to this packet (other agents' files such as `succession.py`
  Pydantic boundary issues remain to be resolved by their owners).
