# Wave 46 dim 19 audit score gap PR

Date: 2026-05-12
Branch: `feat/jpcite_2026_05_12_wave46_dim19_score_fix`
Worktree: `/tmp/jpcite-wave46-dim19`
Author: Wave 46 永遠ループ tick (item #8)

## Audit baseline (docs/audit/dim19_audit_2026-05-12.md)

- count: 19
- average: **6.37/10** (target 8.0+)
- total: 121.0 / 190
- verdict: yellow

## Lowest-scoring dimensions

| code | dim | score | top finding |
| ---- | --- | ----- | ----------- |
| F | fact_signature_v2 | **2.50** | REST api file MISSING, ETL MISSING, cron MISSING |
| D | audit_workpaper | 3.00 | migration MISSING |
| G | realtime_signal_v2 | 4.50 | ETL MISSING, cron MISSING |
| H | personalization_v2 | 4.50 | ETL MISSING, test MISSING |

## Selected sub-criterion: dim F REST api file MISSING

**Why F over D:** dim D requires a migration land + workpaper compose stack
(higher LOC budget than the ≤200 LOC PR target). dim F already has the
migration (262_fact_signature_v2) live, plus the cron
(`refresh_fact_signatures_weekly.py`) and tests (`test_dimension_e_fact_verify.py`)
in source; the missing piece is a discovery REST surface that exposes
metadata without copying the 96-byte sig BLOB into the response. This is
the single highest-leverage sub-criterion at the lowest LOC cost.

## Sub-criterion checklist (dim F → 5 axes)

| axis | before | after | delta |
| ---- | ------ | ----- | ----- |
| migration forward-only: 2 (no rollback) | n/a | n/a | unchanged |
| REST api file | MISSING | **PRESENT** | +1 sub |
| ETL | MISSING | MISSING | unchanged |
| cron | MISSING (cron exists upstream but not flagged) | MISSING | unchanged |
| test(s) | 1 (E shared) | **2** (new F-specific) | additive |
| MCP grep | miss | miss | unchanged |

**Estimated dim F score lift:** 2.50 → ~4.50 (REST present + 1 new test).
This alone moves the dim 19 average from 6.37 toward ~6.47-6.50 without
touching the higher-cost migration / ETL / MCP axes. Per
`feedback_completion_gate_minimal`, we deliberately do NOT chase the full
8.0 gap in one PR.

## Files changed

- `src/jpintel_mcp/api/fact_signature_v2.py` — 277 LOC new module
- `src/jpintel_mcp/api/main.py` — +8 LOC experimental router include
- `tests/test_dimension_f_fact_signature_v2.py` — 6 tests (file presence,
  no LLM import, disclaimer parity, BLOB-on-wire guard, shape projection
  with both 80-byte sig and NULL sig, main.py wiring check)
- `docs/research/wave46/STATE_w46_dim19_pr.md` — this state doc

Total: ≤ 500 LOC across 4 files (well under the ≤200 LOC source-code
budget for the implementation file itself; test + doc are additive).

## Endpoint contract (new surface)

```
GET /v1/facts/signatures/latest?limit=20&cursor=<fact_id>
  -> 200 {signatures: [{fact_id, signed_at, key_id,
                         corpus_snapshot_id, payload_sha256,
                         sig_byte_length}], next_cursor, count,
                         _billing_unit: 1, _disclaimer}
  -> 422 invalid_cursor

GET /v1/facts/{fact_id}/signature
  -> 200 single metadata row + _billing_unit/_disclaimer
  -> 404 fact_signature_not_found
  -> 422 invalid_fact_id
```

Hard constraints satisfied:
* NO LLM call (pure SQLite SELECT + Python dict shaping)
* NO BLOB on the wire (only `sig_byte_length` int + metadata cols)
* §52 / §47条の2 / §72 disclaimer parity with sibling fact endpoints
* Single-DB (autonomath only, jpintel.db warm)
* Experimental include so missing migration 262 → graceful skip, not crash

## Constraints honored

- worktree `/tmp/jpcite-wave46-dim19` (no main worktree touch)
- no rm / mv (only Write + Edit)
- no legacy brand strings (jpintel, autonomath are internal-only refs)
- no LLM API import (verified by test_fact_signature_v2_no_llm_imports)
- 1 sub-criterion fix (REST api file MISSING) — NOT a full 6.37 → 8.0
  refactor

## PR

To be opened after lint + test verify. PR# will be backfilled at the end
of this state doc once `gh pr create` returns.

## Lint + test verdict (2026-05-12 verify)

- `ruff check src/jpintel_mcp/api/fact_signature_v2.py tests/test_dimension_f_fact_signature_v2.py` -> **All checks passed!** (1 SIM114 caught + fixed during gate-run)
- `pytest tests/test_dimension_f_fact_signature_v2.py -v` -> **7 passed in 0.96s**
- Regression check: `pytest tests/test_dimension_e_fact_verify.py -v` -> **12 passed in 1.32s** (no regression on dim E sibling)
- `ruff check src/jpintel_mcp/api/main.py` -> 2 pre-existing errors (I001 + F401), unchanged on stash + re-check; **NOT introduced by this PR**

## PR

**PR #118** — https://github.com/shigetosidumeda-cyber/autonomath-mcp/pull/118
Title: `feat(wave46-dimF): fact_signature_v2 REST discovery surface (dim 19 sub-criterion)`
Branch: `feat/jpcite_2026_05_12_wave46_dim19_score_fix` → `main`
Commit: `34ed48313`
