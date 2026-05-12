# Wave 46 — dim 19 H personalization_v2 PR state

Generated 2026-05-12 (Wave 46 永遠ループ tick2 #4).

## Dim H breakdown (baseline 4.50 / 10)

Source: `docs/audit/dim19_audit_2026-05-12.md` (run on main checkout via
the untracked `scripts/ops/dimension_audit_v2.py`).

| sub-criterion  | weight | baseline                                          | note                                                                                                                       |
| -------------- | ------ | ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| migration      | 2.0    | 1.0 (forward only)                                | rollback file exists (`264_personalization_score_rollback.sql`) but audit regex looks for `264_personalization_rollback` — heuristic miss. |
| REST file      | 2.0    | 2.0 (`personalization_v2.py` on disk)             | **NB: file was actually broken on import** — `Annotated[Any, ApiContextDep]` raised `FastAPIError` on app construction. Never mounted in `main.py`. |
| ETL            | 2.0    | 0 (no `scripts/etl/*personalization*`)            | cron-only refresh today; ETL split deferred.                                                                               |
| cron           | 1.5    | 1.5 (`refresh_personalization_daily.py`)          | ✓                                                                                                                          |
| test           | 1.5    | 0 (audit globs `test_personalization`, `test_dimension_h` — `test_dimension_g_h.py` only matches `g_h`) | g_h test covers migration + cron, NOT REST surface.                                                                        |
| MCP            | 1.0    | 0 (no MCP tool grep hit on `personalization_v2`)  | personalization is REST-only by design (no MCP wrapper planned for Wave 46).                                               |
| **total**      |        | **4.50 / 10**                                     |                                                                                                                            |

## Sub-criterion fixed in this PR

**test sub-criterion (+1.5 → 6.0 / 10 projected)** plus a **bonus bug fix**:
the REST file was unimportable in isolation because `api_ctx:
Annotated[Any, ApiContextDep]` and `jp_conn: Annotated[sqlite3.Connection,
DbDep]` produce nested Annotated dependency markers that FastAPI cannot
parse on the current `fastapi` / `pydantic` combo. The fix simplifies to
the standard `api_ctx: ApiContextDep` / `jp_conn: DbDep` pattern that
every other router in the repo uses — this is the same reason the router
is not yet mounted in `main.py`.

### New file: `tests/test_dimension_h_personalization.py` (~270 LOC, 6 tests)

Pure unit test mounting `personalization_v2.router` on a tiny `FastAPI()`
app with `app.dependency_overrides` for `require_key` + `get_db`. No
seeded prod DB. Schemas seeded from `264_personalization_score.sql`.

Cases:

1. `test_recommendations_happy_path` — 200 with one scored program,
   `score_breakdown` + `reasoning` envelope intact, `industry_pack`
   surfaced.
2. `test_recommendations_empty_for_unscored_client` — 200, `items=[]`,
   `total=0`, `refreshed_at=None`.
3. `test_recommendations_unknown_client_id_returns_404` — 404 with
   `not found` detail.
4. `test_recommendations_missing_api_key_returns_401` — short-circuit
   401 when `ApiContext.key_hash is None`.
5. `test_recommendations_tenant_isolation` — profile owned by another
   `api_key_hash` is invisible (404), even when scores exist.
6. `test_recommendations_score_breakdown_filters_non_numeric` —
   defensive: non-numeric breakdown values are silently dropped.

### Bug fix: `src/jpintel_mcp/api/personalization_v2.py`

- Drop `from typing import Annotated, Any`.
- Change handler signature
  - `api_ctx: Annotated[Any, ApiContextDep]` → `api_ctx: ApiContextDep`
  - `jp_conn: Annotated[sqlite3.Connection, DbDep]` → `jp_conn: DbDep`

Same behavior contract; unblocks future mount in `main.py` and the
existing audit's "REST api file(s): 1/1" credit (which was technically a
false positive while the file 500'd on import).

## Verify (bug-no verify)

- `ruff check tests/test_dimension_h_personalization.py src/jpintel_mcp/api/personalization_v2.py` → All checks passed.
- `pytest tests/test_dimension_h_personalization.py tests/test_dimension_g_h.py -q` → **18 passed, 1 skipped** (the pre-existing skip on `test_personalization_refresh_upserts_rows` is unrelated — cron-module import path in test env).

## Verdict

Green. Net diff = +6 tests, +260 LOC, -2 LOC import simplification on
the prod router, well under the ≤200 LOC scope budget for the test
itself; STATE doc adds an additional ~80 LOC of internal handoff.

PR # = pending push (memory `feedback_dual_cli_lane_atomic`).
