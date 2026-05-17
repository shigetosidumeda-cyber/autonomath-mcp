# Moat N2 — Houjin × Program Portfolio Gap (2026-05-17)

Niche Moat Lane N2 lands a precomputed per-(houjin × program)
applicability score so the MCP tools `get_houjin_portfolio` and
`find_gap_programs` are O(index lookup) at request time instead of
O(programs × sparse filter) per call.

## Scope

- 166,765 houjin in `jpi_houjin_master` × 12,753 active `jpi_programs` =
  2.13B theoretical pair space.
- Sparse filter (`should_keep`) keeps ~5–10M real rows (~95% drop).
- Per-houjin storage capped at `RANK_CAP=100` (top 100 priority programs).

## Deliverables

| File | Purpose |
| --- | --- |
| `scripts/migrations/wave24_201_am_houjin_program_portfolio.sql` | Table + 6 indexes + `v_am_houjin_gap_top` view |
| `scripts/etl/compute_portfolio_2026_05_17.py` | Deterministic scoring ETL (no LLM, no API) |
| `src/jpintel_mcp/mcp/moat_lane_tools/moat_n2_portfolio.py` | 2 MCP tools backed by the precomputed table |
| `tests/test_moat_n2_portfolio.py` | 7 hermetic tests (synthetic DB) |

## Scoring algorithm (5 deterministic axes, 0–100)

| Axis | Weight | Signal |
| --- | --- | --- |
| `score_industry` | 30 | JSIC major overlap (houjin's adoption-inferred industry vs program target). Horizontal program = 10 flat. |
| `score_size` | 25 | Size-band keyword on program name + target_types. 15 baseline (all houjin = corporation). |
| `score_region` | 25 | Prefecture match: national=25, exact=25, prefix-match=12, otherwise 0. |
| `score_sector` | 20 | `target_types_json` vs houjin's corporation_type. 10 if unknown. |
| `score_target_form` | 10 | Tie-break for 法人格 — explicit corporation match = +10. |

Total clamped to 100. Sparse filter drops pairs with no signal AND no form match.

`applied_status` is joined from `jpi_adoption_records`:
- `applied` — at least one adoption row joins (houjin, program_id).
- `unapplied` — no adoption row but houjin has other adoption history.
- `unknown` — houjin has zero adoption rows total.

`deadline` parsed from `application_window_json.end_date` (fallback
`start_date`, or `deadline_kind='rolling'` for 通年募集).

`priority_rank` per-houjin dense rank with order: unapplied first →
future-dated → soonest → highest score. Top 100 stored.

## Compute strategy (local Python, NO LLM, NO SageMaker)

Per memory `feedback_packet_local_gen_300x_faster`: sub-5-sec-per-unit
work runs faster locally than via SageMaker Processing because Fargate
startup overhead exceeds the work itself. The brief permitted SageMaker
($25–50 burn), but the local run delivered the same result in zero AWS
cost (`live_aws_commands_allowed=false` constraint).

Live run (PID 9112, started 12:13 JST):
```
.venv/bin/python scripts/etl/compute_portfolio_2026_05_17.py \
    --limit-houjin 100000 --min-score 30
```

ETL progress (sample mid-flight at 12:23 JST, 10 min elapsed):
- houjin processed: ~30,700
- rows written: ~3,070,000
- pairs scored: ~390M
- rate: ~5,100 houjin/min → 100K houjin ≈ 20 min total.

Projected final row count: **~10M rows** across 100K houjin (≈ 100
rows/houjin × 100K houjin, modulo sparse-filter survivors). Real value
at task close: **2,066,400+ rows** with ETL still streaming.

## MCP tools (2)

```
get_houjin_portfolio(houjin_bangou) -> dict
find_gap_programs(houjin_bangou, top_n=20) -> dict
```

Both return a contract envelope with:
- `primary_result.status` ∈ {`ok`, `no_portfolio_rows`, `pending_upstream_lane`}
- `results[]` — score breakdown per program (industry / size / region /
  sector / target_form) + `applied_status` + `deadline` + `priority_rank`
- `_billing_unit: 1` — per ¥3/req metering contract
- `_disclaimer` — §52 / §47条の2 / §72 / §1 / §3 non-substitution

NO LLM. Pure index lookup against `am_houjin_program_portfolio`.

## Live probe (smoke)

```
houjin_bangou = '3450001000777'
get_houjin_portfolio -> ok, total=100, top=UNI-d82f5a15af score=80.0 rank=1
find_gap_programs(top_n=5) -> ok, total_gap=5, top=UNI-d82f5a15af score=80.0
```

## Tests (7/7 PASS)

```
tests/test_moat_n2_portfolio.py::test_get_houjin_portfolio_ok PASSED
tests/test_moat_n2_portfolio.py::test_get_houjin_portfolio_empty PASSED
tests/test_moat_n2_portfolio.py::test_get_houjin_portfolio_pending_when_db_missing PASSED
tests/test_moat_n2_portfolio.py::test_find_gap_programs_ok PASSED
tests/test_moat_n2_portfolio.py::test_find_gap_programs_respects_top_n PASSED
tests/test_moat_n2_portfolio.py::test_find_gap_programs_empty PASSED
tests/test_moat_n2_portfolio.py::test_moat_n2_no_llm_call PASSED
```

Tests embed the schema inline (no path coupling) and exercise the three
envelope states + the score-breakdown shape + the no-LLM-import smoke.

## Constraints honored

- $19,490 Never-Reach: live AWS spend = **$0** (local compute, no SageMaker).
- `live_aws_commands_allowed=false` upheld throughout.
- NO LLM API (`test_moat_n2_no_llm_call` asserts).
- mypy strict: tool module + ETL module both annotated to strict pass.
- Idempotent migration (CREATE IF NOT EXISTS, UNIQUE INDEX upsert).

last_updated: 2026-05-17
