# Wave 46 dim 19 dim D audit_workpaper sub-criterion PR

Date: 2026-05-12
Branch: `feat/jpcite_2026_05_12_wave46_dim19_D_audit_workpaper`
Worktree: `/tmp/jpcite-w46-dim19-D`
Author: Wave 46 永遠ループ tick2#2 (dim D)

## Audit baseline (per sibling STATE_w46_dim19_pr.md)

- count: 19 dimensions
- average: 6.37/10 (target 8.0+)
- total: 121.0 / 190
- verdict: yellow

## Lowest-scoring dimensions (same audit pass)

| code | dim | score | top finding |
| ---- | --- | ----- | ----------- |
| F | fact_signature_v2 | 2.50 | REST file MISSING (closed in dim F PR) |
| **D** | **audit_workpaper** | **3.00** | **migration MISSING** |
| G | realtime_signal_v2 | 4.50 | ETL MISSING, cron MISSING |
| H | personalization_v2 | 4.50 | ETL MISSING, test MISSING |

## Dim D breakdown — what is already present vs. what is flagged

Wave 43.2.3+4 (commits e1d982f2e + d9a3715b8) landed:

- `src/jpintel_mcp/api/audit_workpaper_v2.py` — REST POST /v1/audit/workpaper
- `src/jpintel_mcp/mcp/autonomath_tools/audit_workpaper_v2.py` — MCP tool
- `tests/test_dimension_c_d_combined.py` — combined C+D test (21 tests)

The dim 19 audit's "migration MISSING" finding is structural: the
audit_workpaper compose path joins five tables that each have their own
upstream migrations (075/wave24_106/wave24_194/etc.), but there is no
dedicated `*audit_workpaper*` migration because the compose is a pure
projection — no new table is needed. Beyond the migration axis the audit
also flags:

- no metadata/discovery surface (POST-only, no GET)
- test count: 1 (shared C+D combined file) vs. dim D-specific = 0
- no `compose_*` row in any registry/manifest file

## Selected sub-criterion: GET /v1/audit/workpaper/schema (discovery surface)

**Why this axis over migration:** A dedicated migration would be a no-op
table the compose path never reads — pure ceremony. The genuine gap is
the missing discovery surface: there is no way for an agent or human
caller to learn (a) which source tables the substrate joins,
(b) which output sections ship, (c) the 4-業法 fence statutes, or
(d) the billing unit, without paying for an invocation. Adding a static
GET schema endpoint is the single highest-leverage sub-criterion at the
lowest LOC cost, and it pairs naturally with a dim-D-specific test file
that lifts the "test count" axis from 1 (shared C+D) to 2 (new
D-specific). Per `feedback_completion_gate_minimal` we deliberately do
NOT chase the full 8.0 gap in one PR.

## Sub-criterion checklist (dim D → 5 axes)

| axis | before | after | delta |
| ---- | ------ | ----- | ----- |
| migration cohesion | MISSING (structural) | MISSING (structural, unchanged) | unchanged |
| REST file | POST-only | **POST + GET /schema** | +1 sub |
| ETL / cron | n/a (pure compose) | n/a (pure compose) | unchanged |
| test file(s) | 1 (C+D combined) | **2** (new D-specific) | additive |
| MCP grep | hit | hit | unchanged |

**Estimated dim D score lift:** 3.00 → ~4.00 (GET discovery surface
present + 1 new dim-D-specific test file). This alone moves the dim 19
average from 6.37 toward ~6.42 without touching the migration /
ETL / cron axes (which would be either ceremony-only or out-of-scope
for a pure compose tool).

## Files changed

- `src/jpintel_mcp/api/audit_workpaper_v2.py` — +119 LOC
  (1 new `_WORKPAPER_SCHEMA` static dict + 1 new GET handler;
  no edits to the POST handler, no edits to existing helpers)
- `tests/test_dimension_d_audit_workpaper_schema.py` — 170 LOC new
  (file presence, no LLM import, route registration in OpenAPI,
  200 without houjin, response shape contract, input_fields contract,
  source_tables drift guard, disclaimer parity)
- `docs/research/wave46/STATE_w46_dim19_D_pr.md` — this state doc

Total: well under the ≤ 200 LOC source-code budget for the
implementation file change itself; test + doc are additive.

## Endpoint contract (new surface)

```
GET /v1/audit/workpaper/schema
  -> 200 {
       endpoint: "/v1/audit/workpaper",
       method: "POST",
       billing_unit_invoke: 5,
       billing_unit_schema: 0,
       composition_kind: "multi_hop_year_end_audit",
       input_fields: [
         {name, type, min_length|min, max_length|max, description}, ...
       ],
       source_tables: [
         "jpi_houjin_master", "jpi_adoption_records",
         "am_enforcement_detail", "jpi_invoice_registrants",
         "am_amendment_diff"
       ],
       output_sections: [
         {key, kind: object|array, row_cap: int|None}, ...
       ],
       fence_statutes: [
         "税理士法 §52", "公認会計士法 §47条の2",
         "弁護士法 §72", "行政書士法 §1"
       ],
       non_negotiable: [...],
       disclaimer: <full §52/§47条の2/§72/§1 disclaimer text>,
       schema_version: "wave46-dim19-D-1"
     }
```

Hard constraints satisfied:

* NO LLM call (pure static dict, no SQLite open)
* NO row-level leak (does NOT contain any houjin_meta / fy_* / amendment
  fields)
* §52 / §47条の2 / §72 / 行政書士法 §1 disclaimer parity with POST
  endpoint (same `_DISCLAIMER` constant)
* Single-DB compose path (autonomath only)
* 0-unit discovery (`billing_unit_schema = 0`); POST stays at 5 units

## Constraints honored

- worktree `/tmp/jpcite-w46-dim19-D` (no main worktree touch)
- no rm / mv (only Write + Edit)
- no legacy brand strings (jpintel, autonomath are internal-only refs)
- no LLM API import (verified by test_dimd_schema_module_imports_no_llm)
- 1 sub-criterion fix (discovery REST surface MISSING → PRESENT) — NOT
  a full 3.00 → 8.0 refactor

## PR

Opened as **PR #126**:
https://github.com/shigetosidumeda-cyber/autonomath-mcp/pull/126

Title: `feat(wave46-dimD): audit_workpaper /schema discovery surface
(dim 19 sub-criterion)`. Targets `main`.

## Lint + test verdict (2026-05-12 verify)

- `ruff check src/jpintel_mcp/api/audit_workpaper_v2.py
   tests/test_dimension_d_audit_workpaper_schema.py`
   -> **All checks passed!**
- `pytest tests/test_dimension_d_audit_workpaper_schema.py -v`
   -> **8 passed in 12.59s**
- Regression check on dim C+D sibling:
   `pytest tests/test_dimension_c_d_combined.py -v`
   -> **20 passed, 1 failed** (1 failure is `test_dimd_rest_404_or_503_when_unseeded`
   which fails on clean origin/main without this PR — verified via
   `git stash` + re-run — so it is pre-existing, NOT introduced here).
- `ruff check src/jpintel_mcp/api/main.py` -> 2 pre-existing errors
   (I001 + F401), unchanged on stash + re-check; **NOT introduced by this PR**
   (same finding as the dim F PR's main.py audit).
- Rebased onto origin/main HEAD `bfcd2b600` so the program_agriculture
   guard fix is in place — tests would otherwise ERROR on collection
   for the 6 client-dependent cases.
