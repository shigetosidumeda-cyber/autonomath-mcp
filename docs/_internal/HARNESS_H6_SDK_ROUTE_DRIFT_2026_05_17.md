# Harness H6 — SDK Agent Route Drift Fix (2026-05-17)

**Status: LANDED**
**Scope:** Bring `sdk/agents/src/` REST paths back into the FastAPI route subset.
**Contract:** `SDK ⊆ FastAPI` — every path the SDK can call must exist on the server.

## Why this mattered

The reference-agent SDK shipped under `sdk/agents/` carried REST paths
that were canonical at Wave 22/24 but had since been migrated by the
houjin / wave24 / ma_dd / audit_workpaper / amendment_alerts routers. Six
agent surfaces (Houjin 360, recommend, adoption stats, exclusion check,
invoice registrant lookup, amendment feed) and three composition
surfaces (DD question matcher, jurisdiction cross-check, kessan
briefing) all 404'd against current production. Customers who took the
SDK at face value would see hard fetch errors on first run.

Harness P0.7 (this work) brought the SDK back to parity and added a
regex-based parity test that catches future drift without booting the
FastAPI app (which would pull the 9 GB autonomath.db).

## Route drift map (Old SDK → New FastAPI)

| # | Old SDK path | New FastAPI path | Source file |
|---|---|---|---|
| 1 | `GET  /v1/am/houjin/{id}/snapshot` | `GET  /v1/houjin/{bangou}/360` | `houjin_360.py` |
| 2 | `GET  /v1/am/recommend/{id}` | `POST /v1/am/recommend` (body) | `wave24_endpoints.py` |
| 3 | `GET  /v1/am/program/{id}/adoption_stats` | `GET  /v1/am/programs/{id}/adoption_stats` | `wave24_endpoints.py` |
| 4 | `GET  /v1/exclusion/check?…` | `POST /v1/exclusions/check` (body) | `exclusions.py` |
| 5 | `GET  /v1/am/amendments/recent` | `GET  /v1/me/amendment_alerts/feed` (auth) | `amendment_alerts.py` |
| 6 | `GET  /v1/am/invoice_registrants/{id}` | `GET  /v1/houjin/{bangou}/invoice_status` | `houjin.py` |
| 7 | `GET  /v1/am/houjin/{id}/jurisdiction_check` + `POST /v1/am/dd/match_questions` | `POST /v1/am/dd_batch` (composed) | `ma_dd.py` |
| 8 | `POST /v1/am/kessan/prepare_briefing` | `POST /v1/audit/workpaper` | `audit_workpaper_v2.py` |

**Drift count:** 8 (6 jpcite_client method calls + 2 composition routes
rebased into existing batch/workpaper composers).

## Files touched

- `sdk/agents/src/lib/jpcite_client.ts`
  - 6 method bodies updated to the new paths.
  - 3 doc comments updated to reference the canonical surfaces.
- `sdk/agents/src/agents/subsidy_match.ts`
  - Pipeline header doc updated to reflect the new 4-step pipeline.
- `sdk/agents/src/agents/due_diligence.ts`
  - `Step 2 — jurisdiction_check` + `Step 3 — match_questions` consolidated
    into one `POST /v1/am/dd_batch` call. The agent now unpacks the
    composed envelope back into the existing `cross` / `matched` shape so
    the surrounding code is unchanged.
- `sdk/agents/src/agents/kessan_brief.ts`
  - `prepare_kessan_briefing` swapped for `POST /v1/audit/workpaper`.
    Note the field name change: `houjin_bangou` → `client_houjin_bangou`.
- `tests/sdk_route_parity_check.py` (NEW)
  - Regex-based parity check; runs in CI without booting the FastAPI app.
- `docs/_internal/HARNESS_H6_SDK_ROUTE_DRIFT_2026_05_17.md` (this file)

## How the parity test works

The test does NOT import `main.py` — startup pulls the 9 GB
`autonomath.db` and would make CI unusable on this hot path. Instead, it
statically walks `src/jpintel_mcp/api/*.py` for `APIRouter(prefix=…)`
declarations and `@*_router.{get,post,…}` decorators, then compares to
the path literals it finds in `sdk/agents/src/*.ts`. The same approach
backs the OpenAPI exporter.

Doc-comment references to legacy paths (e.g. inside the migration
explanation block) are filtered out via a "skip-pure-comment-lines"
heuristic — only lines that look like actual `fetch(...)` or
``const path = `…`` ` calls are considered.

The test produces 1 case per SDK call site, so a future regression
points at exactly the file/path that drifted.

## Verification

```bash
# 1. Route parity (the SDK ⊆ FastAPI invariant)
.venv/bin/pytest tests/sdk_route_parity_check.py -v

# 2. TypeScript compile (no emit; just type-check)
cd sdk/agents && npm run typecheck

# 3. mypy strict for the test file (it is pure Python)
mypy --strict tests/sdk_route_parity_check.py
```

## Constraints honoured

- NO LLM — pure static analysis on both sides of the parity contract.
- mypy --strict for the Python test file.
- `tsc --noEmit` clean (TypeScript side).
- Conventional commit with `[lane:solo]` + `Co-Authored-By: Claude
  Opus 4.7` trailer.

## See also

- `docs/_internal/AGENT_HARNESS_REMEDIATION_PLAN_2026_05_17.md` —
  parent plan that flagged the SDK drift.
- `src/jpintel_mcp/api/houjin_360.py`, `wave24_endpoints.py`,
  `exclusions.py`, `houjin.py`, `amendment_alerts.py`, `ma_dd.py`,
  `audit_workpaper_v2.py` — the FastAPI route owners.
- `tests/sdk_route_parity_check.py` — the gate that keeps the SOT honest.
