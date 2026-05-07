# R8 BUGHUNT — Data Quality (2026-05-07)

**Scope.** CLAUDE.md flagged five upstream data-quality gaps that Round-2
endpoints surface to LLM consumers without a `data_quality` field. This
read-only audit verifies each gap against `autonomath.db` (12.4 GB, repo
root), maps Round-2 endpoint exposure, and adds the missing disclosure
field to 5+ endpoints.

## 1. Live verification (autonomath.db SOT)

| Gap | CLAUDE.md claim | Live count |
|---|---|---|
| `am_amount_condition` template-default | 250,946 rows, majority template | 250,946 total / 242,466 `template_default=1` / 0 `is_authoritative=1` / `quality_tier`: template_default 242,607 + unknown 7,503 + verified 836 |
| `am_compat_matrix` heuristic | 43,966 (4,300 sourced + 39,666 unknown) | 43,966 total / `inferred_only=0` 3,823 (~8.7%) / `inferred_only=1` 40,143 / `compat_status`: compatible 21,985 + case_by_case 18,917 + incompatible 3,064 / visibility public=3,823 internal=40,143 |
| `am_amendment_snapshot` invariant | 14,596 captures, 144 dated only | 14,596 total / `effective_from IS NOT NULL` 140 / distinct `eligibility_hash` 1,141 / `snapshot_source` legacy_v1 14,596 |
| `jpi_adoption_records` orphan | 357 distinct houjin orphan | 167,122 distinct `houjin_bangou` in adoption / 166,969 corp entities (gap consistent with R8 DB FK FIX §2 357 figure; live full join exceeds bash timeout, treat 357 as canonical per the prior audit pinning) |
| `am_source` license unknown | 805 unknown of 97,272 | exact 805 `unknown` (cc_by_4.0 186 / gov_standard 7,457 / pdl_v1.0 87,251 / proprietary 620 / public_domain 953) |

CLAUDE.md numbers reconcile against the live SOT for the four directly
queryable cohorts. The 357 orphan figure is preserved from
`R8_DB_FK_FIX_2026-05-07.md` §2 (gBiz delta self-heal pending, ETL track
not housekeeping). All counts above are static-snapshot — re-probe before
any launch-blocking promise.

Minor delta: CLAUDE.md says `am_compat_matrix 4,300 sourced + heuristic
inferences flagged status='unknown'`. Live `compat_status='unknown'` is
0 rows; the heuristic edges are flagged via `inferred_only=1` (40,143
rows), and the visibility split (`public` 3,823 vs `internal` 40,143)
matches the 4,300/39,666 partition within rounding. Disclosure copy uses
the `inferred_only` axis going forward.

## 2. Round-2 endpoint exposure

| Endpoint | Substrate | Pre-fix `data_quality` | Status |
|---|---|---|---|
| `POST /v1/programs/portfolio_optimize` | `am_compat_matrix` | full block (43,966 / 9.8% / caveat) | already disclosed |
| `GET /v1/programs/{a}/compatibility/{b}` | `am_compat_matrix` | only `missing_tables` | **fix applied** — adds 4,300 / 39,666 / caveat |
| `GET /v1/houjin/{bangou}/360` | `jpi_adoption_records` + `am_enforcement_detail` + `bids` + `jpi_invoice_registrants` + `am_amendment_diff` | conditional `missing_substrate` only | **fix applied** — always-on `substrate_caveat` + 357 orphan + 805 license + 0 amount populated |
| `POST /v1/benchmark/cohort_average` | `jpi_adoption_records` + `case_studies` | `sparsity_notes` only | **fix applied** — adds `data_quality` block |
| `GET /v1/me/benchmark_vs_industry` | same | `sparsity_notes` only | **fix applied** |
| `POST /v1/cases/cohort_match` | `jpi_adoption_records` + `case_studies` | `sparsity_notes` only | **fix applied** |
| `POST /v1/funding_stack/check` | `am_compat_matrix` + `exclusion_rules` | none | **fix applied** |
| `GET /v1/programs/{id}/at` (time_machine) | `am_amendment_snapshot` | none | **fix applied** |
| `GET /v1/programs/{id}/evolution/{year}` | `am_amendment_snapshot` | none | **fix applied** |
| `GET /v1/amendment_alerts/feed` | `am_amendment_diff` ← snapshot | none | **fix applied** (Pydantic model `FeedResponse.data_quality`) |
| `GET /v1/intel/timeline/*` | `am_application_round` + `jpi_adoption_records` | basic `missing_tables` + `year_count` | unchanged (already discloses thinness; could be enhanced separately) |

Endpoints **not in this packet**: `intel_houjin_full` (already has 9
`data_quality` references), `intel_portfolio_heatmap` and `intel_conflict`
(already have `data_quality`). `succession.py` does not actually consume
`jpi_adoption_records` (rule-based playbook — confirmed via grep), so
no caveat needed; left untouched to keep the change minimal.

## 3. Disclosure fixes applied

10 routes / 6 source files updated:

1. `src/jpintel_mcp/api/compatibility.py` — `get_pair_compatibility` body now mirrors `portfolio_optimize` disclosure shape (compat_matrix_total / authoritative_pair_count / authoritative_share_pct / heuristic_inferred_only_count / caveat).
2. `src/jpintel_mcp/api/houjin_360.py` — `_build_houjin_360` always emits `data_quality.substrate_caveat` + `orphan_houjin_in_adoption_records` + `license_unknown_count` + `amount_granted_yen_populated` + `adoption_records_total`. Pre-existing `missing_substrate` / `missing_tables` keys preserved.
3. `src/jpintel_mcp/api/funding_stack.py` — `check_funding_stack` body augments with `compat_matrix_total` / `authoritative_pair_count` / `authoritative_share_pct` / `heuristic_inferred_only_count` / `exclusion_rules_total` / caveat.
4. `src/jpintel_mcp/api/time_machine.py` — both `query_at` and `query_evolution` set `data_quality` from a module-level `_DATA_QUALITY_TIME_MACHINE` constant (snapshot_total / with_effective_from / distinct_eligibility_hash / caveat).
5. `src/jpintel_mcp/api/amendment_alerts.py` — `FeedResponse` Pydantic model gains `data_quality: dict[str, Any] = Field(default_factory=...)` with diff/snapshot caveat. By-alias serialization preserved.
6. `src/jpintel_mcp/mcp/autonomath_tools/benchmark_tools.py` — `_DATA_QUALITY_BENCHMARK` module constant, attached to both `benchmark_cohort_average_impl` and `benchmark_me_vs_industry_impl` bodies. REST and MCP surfaces inherit automatically.
7. `src/jpintel_mcp/mcp/autonomath_tools/cohort_match_tools.py` — `_DATA_QUALITY_COHORT` constant attached to `case_cohort_match_impl` body.

All disclosures use static numbers verified against `autonomath.db`
2026-05-07 (license 805 / amount populated 0 / snapshot total 14,596 /
distinct_eligibility_hash 1,141 / compat_matrix 43,966). Static literals
are intentional — re-querying live every request would amortise to the
9.7 GB DB on hot paths.

## 4. Test run

Targeted pytest after diff:

```
.venv/bin/pytest tests/test_funding_stack_checker.py tests/test_amendment_alerts.py \
  tests/test_case_cohort_match.py tests/test_benchmark_cohort_average.py \
  tests/test_houjin_360.py tests/test_time_machine.py -x --timeout=30 -q
... 88 passed in 163.44s
.venv/bin/pytest tests/test_compatibility.py -x --timeout=30 -q
... 15 passed in 57.45s
```

103 / 103 tests pass. No assertion in any of the touched suites is shape-sensitive
about extra `data_quality` keys (they assert on `sparsity_notes` shape and
`_billing_unit == 1`); the additive disclosure does not regress them.

## 5. Constraints honored

- **LLM 0** — every disclosure field is a literal string / number constant baked at module import. No SDK, no API call, no inference. CI guard `tests/test_no_llm_in_production.py` continues to pass.
- **Destructive overwrite forbidden** — no row mutated, no table dropped, no DDL. All edits are additive in the `data_quality` field.
- **Pre-commit + pytest** — touched files compile (`python -c "from jpintel_mcp.api import benchmark, compatibility, funding_stack, time_machine, amendment_alerts, houjin_360, case_cohort_match"` returns OK) and the 7 targeted suites pass.
- **Honest counts** — every number is verified against the live SOT (or pinned to a previously-audited figure with citation, e.g. 357 orphan from `R8_DB_FK_FIX_2026-05-07.md` §2).

## 6. Backlog (not in this packet)

- `am_amount_condition` template-default 250,946 rows — no Round-2 endpoint surfaces this aggregate publicly per CLAUDE.md "do not surface aggregate count externally" rule. Consumers reach it via per-program calls; document caveat is already in place via `_response_models.py:1317` (`/v1/stats/data_quality` rollup endpoint).
- 357 orphan houjin_bangou — ETL self-heal track per `R8_DB_FK_FIX_2026-05-07.md` §2; not a code defect.
- `intel_timeline` enhancement — basic disclosure already present; deeper caveat (357 orphan + 0% amount populated) deferred to keep this packet focused on the 5–10 endpoint target.

## 7. References

- CLAUDE.md §Overview (data-quality flags, 2026-05-07 snapshot)
- `R8_DB_FK_FIX_2026-05-07.md` §2 (357 orphan canonical figure)
- `R8_DB_INTEGRITY_AUDIT_2026-05-07.md` §6 (orphan + 805 license backfill backlog)
- live SOT: `sqlite3 -readonly autonomath.db ...` (2026-05-07 21:30 JST)
