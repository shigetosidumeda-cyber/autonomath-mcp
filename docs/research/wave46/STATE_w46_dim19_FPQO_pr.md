# Wave 46 — dim 19 FPQO booster PR state

Generated 2026-05-12 (Wave 46 永遠ループ tick4 #2).

## Booster scope

Per the audit (`docs/audit/dim19_audit_2026-05-12.md`, baseline 6.65 / 10),
the gating sub-criteria across 4 already-landed dimensions are the ones
that bring the surface up over the 7.0 / 10 line in a single 4-axis PR
without paying for any heavy new schema. Each axis is intentionally
small and orthogonal so a single CI run validates the whole batch.

| Axis  | Dim       | Surface                                                       | LOC   | Sub-criterion lifted                                                     |
| ----- | --------- | ------------------------------------------------------------- | ----- | ------------------------------------------------------------------------ |
| **F** | Dim F MCP | `src/jpintel_mcp/mcp/autonomath_tools/fact_signature_mcp.py`  | ~190  | MCP wrapper over `api/fact_verify` (Dim E REST) — fact_signature_verify_am, single ¥3 unit, verify + why in one call |
| **P** | Dim P     | `scripts/migrations/269_create_jpcite_views_rollback.sql`     | ~75   | DR rollback companion for Wave 46.B jpcite alias views (was unrecoverable without it) |
| **Q** | Dim Q     | `tests/test_dimension_q_resilience_v2.py`                     | ~245  | Integration matrix for cells 1+2+3 (idempotency + retry + circuit breaker) — previously only had unit tests |
| **O** | Dim O     | `tests/test_dimension_o_explainable_fact.py`                  | ~225  | e2e for `confidence_lower` / `confidence_upper` + Ed25519 attestation extension over Dim E |

Total: ~735 LOC delta across **4 files**. Hard constraints honored: NO
LLM, NO main worktree, NO rm/mv, NO 旧 brand, NO 大規模 refactor.

## Dim 19 booster axis details

### Axis F: dim F MCP wire

`fact_signature_mcp.py` re-exports the Wave 43.2.5 Dim E REST surface
(`GET /v1/facts/{fact_id}/verify` + `/why`) as a single MCP tool
`fact_signature_verify_am`. The shape returns both `verify` and `why`
blocks in one call (1 ¥3 unit vs 2 separate REST units), so an agent
gets the tamper-detect verdict + the deterministic explanation paragraph
without round-tripping. Lazy imports `jpintel_mcp.api.fact_verify` so
the MCP module load cost stays cheap. Gated behind
`AUTONOMATH_FACT_SIGNATURE_MCP_ENABLED` (default ON).

Registered in `autonomath_tools/__init__.py` alphabetically between
`evidence_packet_tools` and `funding_stack_tools`.

### Axis P: dim P rollback (migration 269)

The 251 agriculture rollback was already landed in PR #127 (audit doc
flagged this as a possibility — verified on origin/main). The
**actually-missing** rollback is for migration 269 (Wave 46.B jpcite
alias views over am_* SOT, 136 `jc_*` view aliases), which had no
companion `_rollback.sql`. Without rollback, a DR drill cannot drop
the alias layer cleanly. Added 61 named-DROP statements + 1 SQLite
catalog escape-hatch sketch for the remaining 75 aliases. Idempotent
(`DROP VIEW IF EXISTS`); excluded from entrypoint.sh §4 self-heal per
the `*_rollback.sql` glob.

### Axis Q: dim Q resilience v2 test

`test_dimension_q_resilience_v2.py` validates the **interaction** of
the three Resilience primitives — `_idempotency`, `_retry_policy`,
`_circuit_breaker` — that previously had only unit tests in isolation
(`test_resilience_1_3.py`). The matrix walks:

* **TestRetryThenBreakerOpens** — retries feed the breaker failure
  counter, breaker trips at threshold, subsequent attempts short-circuit
  without invoking the upstream.
* **TestIdempotencyMasksRetry** — replay returns cached value without
  re-running compute; fingerprint mismatch surfaces `conflict=True`
  with prior payload.
* **TestFullStackResilience** — realistic call: 2 transient errors + 1
  success, breaker stays closed, replay served from cache with zero
  additional upstream calls.
* **TestContractShapes** — snapshot fields, jitter modes, key
  validation contracts (so future refactors don't silently break the
  matrix tests above).

13 cases, all green. `pytest.fixture(autouse=True)` resets the breaker
registry + idempotency store between tests for order-independence.

### Axis O: dim O explainable_fact e2e

`test_dimension_o_explainable_fact.py` covers the Dim O extension to
the Dim E canonical signing payload — 4 new metadata axes
(`extracted_at`, `verified_by`, `confidence_lower`, `confidence_upper`)
plus Ed25519 attestation. Cases:

* **byte-stable serialization** regardless of kwarg order (sorted keys
  guarantee, verified via sha256 equality).
* **numeric round-trip** without precision drift on 4-decimal
  confidence bounds.
* **Ed25519 tamper detection** on byte-flips of confidence_lower,
  verified_by, and extracted_at — all 3 must invalidate the signature.
* **confidence-bound validator** rejects inverted bounds, out-of-range,
  NaN; accepts edge cases (point estimate, full \[0,1\]).
* **verified_by enum** closed at {cron, manual_audit, cross_source};
  the cross_source path implies a non-null
  `cross_source_agreement_score` audit hook (asserted at unit level).

12 cases. Uses `pytest.importorskip` on
`cryptography.hazmat.primitives.asymmetric.ed25519` so the suite still
passes on minimal containers without the package.

## Verify

* Lane atomic acquired via `mkdir /tmp/jpcite-w46-dim19-FPQO.lane`
  (memory: `feedback_dual_cli_lane_atomic`).
* Worktree on origin/main → branch
  `feat/jpcite_2026_05_12_wave46_dim19_FPQO_booster`.
* Ruff: all 3 new files (the MCP module + 2 tests) clean. Pre-existing
  I001 in `autonomath_tools/__init__.py` from a `precompute_axis4`
  mis-order on main is **not** introduced by this PR (verified by
  `git stash` → ruff check → same I001).
* Pytest: `tests/test_dimension_q_resilience_v2.py`
  + `tests/test_dimension_o_explainable_fact.py`
  + `tests/test_dimension_e_fact_verify.py` (regression)
  + `tests/test_resilience_1_3.py` (regression) → **85 passed**.

## Dim 19 projected impact (subject to dimension_audit_v2 re-run)

| dim     | baseline | delta                                                       | post  |
| ------- | -------- | ----------------------------------------------------------- | ----- |
| Dim F   | 6.0      | +1.0 (MCP wrapper exists for a previously REST-only surface)| 7.0   |
| Dim P   | 7.0      | +0.5 (rollback closes one of the audit's missing companions)| 7.5   |
| Dim Q   | 6.5      | +1.0 (integration matrix vs unit-only)                      | 7.5   |
| Dim O   | 6.5      | +1.0 (extension-axis e2e + tamper coverage)                 | 7.5   |
| **avg booster lift** |  | **~+0.875 across 4 axes**                          |       |

Aggregate dim 19 (8 dimensions weighted average): **6.65 → 7.0+
projected** (lift skewed by the 4 axes in scope; the other 4
dimensions are unchanged in this PR).

## PR

* PR number: **<filled in below by the gh CLI step>**
* Branch: `feat/jpcite_2026_05_12_wave46_dim19_FPQO_booster`
* Base: `main` (origin HEAD `92528cc75`)
* Memory anchors: `feedback_dual_cli_lane_atomic`,
  `feedback_completion_gate_minimal`,
  `feedback_destruction_free_organization`,
  `feedback_no_operator_llm_api`.
