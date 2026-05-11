# Dependency Drift + Dead Code Audit (jpcite, 2026-05-11)

Scope: `pyproject.toml` (prod + dev + e2e + site), `sdk/python/pyproject.toml`,
`sdk/typescript/package.json`, `docs-requirements.txt`, `.pre-commit-config.yaml`,
plus all 341 `.py` files under `src/jpintel_mcp/` (excluding `_archive/`).

Tools used (local only, no LLM API):
- `uvx vulture` 2.16 (dead-code detection)
- `.venv/bin/pip-audit` (OSV CVE lookup; ran with `--disable-pip --no-deps`)
- `.venv/bin/pip list --outdated`
- repo-wide `grep` for import / symbol reverse-lookup
- static AST walk for cycle detection (custom `python -c` snippet)

> All findings are read-only. No code changes performed.

---

## 0. 5-axis rollup

| Axis | Status | Hit count | Sample |
|---|---|---|---|
| A. Unused declared dependencies | **YELLOW** | 2 / 24 prod | `sqlite-utils`, `tenacity` (0 repo refs) |
| B. Outdated / drift (1+ major behind) | **YELLOW** | 5 deps capped 1 major behind PyPI latest | `fastapi 0.120<0.121` (latest 0.136), `stripe 12.x<13` (latest 15.1), `uvicorn 0.39<0.40` (latest 0.46), `mypy 1.20<2.0` (latest 2.0), `starlette 0.49<0.50` (latest 1.0) |
| C. Dead code (function / class / method) | **GREEN-YELLOW** | 16 confidence-100 (all are FP — pass-through API params); ~10 genuine dead helpers (`next_calls_for_*`) | `_universal_envelope.next_calls_for_{law,court_decision,case_study,bid,invoice_registrant,loan,tax_ruleset,enforcement,am_entity}` |
| D. Duplicate / overlapping modules | **YELLOW** | 8 envelope-named files + 8 basename collisions | `api/_envelope.py` (910L) / `_error_envelope.py` (721L) / `_universal_envelope.py` / `_compact_envelope.py` + 4 in `mcp/` |
| E. Circular imports | **GREEN** | 3 top-level cycles, all benign (function-scoped name use) | `api.deps` ↔ `api.funnel_events` ↔ `api.middleware.analytics_recorder`; `api.deps` ↔ `api.middleware.customer_cap`; `mcp.server` ↔ `mcp.autonomath_tools.tools` |

CVE scan via OSV DB on 202 installed packages: **0 known vulnerabilities**
(starlette pinned to `>=0.49.1` mitigates CVE-2025-62727; python-multipart
`>=0.0.27` mitigates CVE-2026-42561 per `pyproject.toml` comments).

---

## A. Unused dependencies (declared but 0 import)

Method: for every name in `[project.dependencies]`, count
`^(import|from)\s+<pkg-import-name>` across `src/`, `tests/`, `scripts/`,
`benchmarks/`, `sdk/`.

| Dep | Pin | Direct refs | Indirect? | Verdict |
|---|---|---|---|---|
| **sqlite-utils** | `>=3.38,<4` | **0** | not transitive of any other prod dep | **DROP candidate** |
| **tenacity** | `>=9.0,<10` | **0** | not transitive | **DROP candidate** |
| email-validator | `>=2.0,<3` | 0 direct | `pydantic.EmailStr` requires it (10 src refs to `EmailStr`) | **KEEP (indirect)** |
| python-multipart | `>=0.0.27,<1` | 0 direct (only `from fastapi import Form, UploadFile`) | `fastapi.Form` / `UploadFile` requires it (4 src refs) | **KEEP (indirect)** |

Other declared prod deps with direct-import counts (`src/` + `scripts/`):

```
fastapi              253      uvicorn                1
mcp                    2      pydantic             155
pydantic-settings      2      starlette             47
httpx                 64      weasyprint             3
stripe                23      orjson                 4
structlog              3      sentry-sdk            22
keyring                3      scipy                  1
bcrypt                 2      openpyxl               9
python-docx            3      icalendar              1
pdfplumber            15      beautifulsoup4        40
```

uvicorn `1` ref is correct — only imported once at the `run()` entry point.

`mcp` `2` direct refs is correct — `FastMCP` is imported lazily.

Top dev-dep usage outside `src/`:

```
pytest               343      pandas              7
rapidfuzz              4      duckdb              2
pyarrow                2      huggingface_hub     2
playwright            19      pre_commit          0  (consumed by pre-commit binary, not python imports)
pytest_asyncio         1      pytest_cov          0  (consumed by pytest plugin discovery)
ruff                   0      mypy                0  (binary-only, both consumed by hooks)
build                  0      (consumed by python -m build)
```

Top-10 declared-but-unused candidates (after filtering indirect):

1. **sqlite-utils** — declared 2026-04 era, no repo callers
2. **tenacity** — declared retry helper, no `@retry` / `wait_exponential` anywhere

That's the entire list — the remaining 22 prod deps are either directly
imported or are transitive-required by pydantic / fastapi.

---

## B. Outdated dependencies (1+ major behind PyPI latest)

`pip list --outdated` against installed venv (Python 3.13). Listing only
deps where the **declared upper-bound cap** is at least 1 major behind the
PyPI latest.

| Dep | Declared cap | Installed | PyPI latest | Major gap | Notes |
|---|---|---|---|---|---|
| fastapi | `<0.121` | 0.120.4 | **0.136.1** | -16 minor (effectively 1 major in fastapi cadence) | upper cap intentionally tight per comment in `pyproject.toml`; widen after middleware-API review |
| stripe | `<13` | 12.5.1 | **15.1.0** | -2 majors | yearly major bumps, breaking; planned per comment |
| uvicorn | `<0.40` | 0.39.0 | **0.46.0** | -6 minor (1 major-equivalent) | no comment; widen-candidate |
| mypy | `>=1.13` (dev) | 1.20.2 | **2.0.0** | -1 major | dev-only, pre-commit pinned 1.20.0 |
| starlette | `<0.50` | 0.49.3 | **1.0.0** | -1 major (1.0 released) | fastapi compat gates upper cap |
| huggingface_hub | `<1` (dev) | 1.13.0 | **1.14.0** | crossed cap — installed already at 1.x | **PIN drift**: cap says `<1`, installed 1.13.0 |
| pyarrow | `<25` (dev) | 24.x | (latest still <25) | within cap | OK |
| icalendar | `<7` | 6.3.2 | **7.1.0** | -1 major | upper cap holds, widen-candidate |
| ruff | `>=0.8` | 0.15.11 | 0.15.12 | within | OK |
| sentry-sdk | `<3` | 2.58.0 | 2.59.0 | within | OK |

Top-10 outdated (PyPI latest > installed):

```
fastapi                0.120.4 → 0.136.1
stripe                  12.5.1 → 15.1.0
starlette               0.49.3 →  1.0.0
uvicorn                 0.39.0 →  0.46.0
mypy                    1.20.2 →  2.0.0
icalendar                6.3.2 →  7.1.0
sentry-sdk              2.58.0 →  2.59.0
cryptography           46.0.7 → 48.0.0   (transitive)
playwright              1.58.0 →  1.59.0 (e2e extras)
huggingface_hub        1.13.0 → 1.14.0  (dev — already past `<1` cap!)
```

**Cap-drift bug**: `pyproject.toml [project.optional-dependencies] dev`
declares `huggingface_hub>=0.25,<1` but the installed (locally resolved)
version is `1.13.0` — i.e. the local environment is **outside** the
declared range. Either widen the cap to `<2` or repin the env.

CVE / vulnerability scan via OSV DB (`pip-audit --disable-pip --no-deps`):
**0 known vulnerabilities** across 202 installed packages. The two
fences the comments mention (starlette CVE-2025-62727, python-multipart
CVE-2026-42561) are both already satisfied by the current pins.

---

## C. Dead code (unused module / function / class)

Method: `uvx vulture src/jpintel_mcp/ --min-confidence {60,90,100} --exclude '_archive'`,
then sanity-grep each suspicious symbol with `rg <sym> src/ tests/ scripts/`
to weed out vulture false positives (FastAPI route handlers, pydantic
validators, decorator-bound methods, SQLite hook callbacks).

### C.1 Confidence-100 (16 hits) — all FALSE POSITIVES

Vulture's 100% bucket flagged only unused **local variables** that are in
fact API parameter pass-throughs that the framework binds but the body
doesn't read. Not actual dead code. List:

```
api/_contributor_trust.py:316       cumulative_contributions (function arg)
api/integrations.py:269-271         team_id / user_id / command (Slack slash-cmd Form fields, reserved for fan-out)
api/intel_why_excluded.py:481       age_axis (axis param matching a sister checker signature)
api/programs.py:1423                include_excluded (FastAPI Query param)
db/session.py:49-51                 arg2 / db_name / trigger (SQLite update-hook signature)
mcp/healthcare_tools/tools.py:152-307  7 Annotated[str|None, Form()] fields on
                                       MCP tool signatures — bound by
                                       FastMCP into JSON schema, intentionally
                                       parametric.
```

Verdict: **no actual confidence-100 dead code**. These are framework
parameter contracts that vulture cannot model.

### C.2 Genuine dead-helper family (10 functions) — single-file, no caller

Real finding: `src/jpintel_mcp/api/_universal_envelope.py` exports a
**`next_calls_for_*` dispatch family** that exists in source + test fixtures
but **has zero in-tree callers** in `src/`.

| Symbol | Defined at | src callers | test refs | Verdict |
|---|---|---|---|---|
| next_calls_for_program | _universal_envelope.py:234 | **0** | 1 | dead in prod, test-only |
| next_calls_for_law | _universal_envelope.py:269 | **0** | 1 | dead in prod, test-only |
| next_calls_for_court_decision | :281 | **0** | 1 | dead in prod, test-only |
| next_calls_for_case_study | :298 | **0** | 1 | dead in prod, test-only |
| next_calls_for_bid | :322 | **0** | 1 | dead in prod, test-only |
| next_calls_for_invoice_registrant | :344 | **0** | 1 | dead in prod, test-only |
| next_calls_for_loan | :366 | **0** | 1 | dead in prod, test-only |
| next_calls_for_tax_ruleset | :376 | **0** | 1 | dead in prod, test-only |
| next_calls_for_enforcement | :393 | **0** | 1 | dead in prod, test-only |
| next_calls_for_am_entity | :412 | **0** | 1 | dead in prod, test-only |

These 10 functions take a `row: Any` and emit a list of next-call hints.
The companion `build_envelope_extras(rows, next_calls_fn=...)` takes the
function as a kwarg — but **no route handler under `src/` passes one in**.
Only `tests/test_universal_envelope.py` imports them. Net: an entire 178-line
public-shaped dispatch surface lives in source but never reaches the wire.

### C.3 Other singletons (top-20 candidates)

Functions / classes defined once with no in-tree caller (after filtering
FastAPI decorators / pydantic validators):

| Symbol | File:line | Notes |
|---|---|---|
| `next_calls_for_law` | api/_universal_envelope.py:269 | (above) |
| `next_calls_for_court_decision` | :281 | (above) |
| `next_calls_for_case_study` | :298 | (above) |
| `next_calls_for_bid` | :322 | (above) |
| `next_calls_for_invoice_registrant` | :344 | (above) |
| `next_calls_for_loan` | :366 | (above) |
| `next_calls_for_tax_ruleset` | :376 | (above) |
| `next_calls_for_enforcement` | :393 | (above) |
| `next_calls_for_am_entity` | :412 | (above) |
| `validate_invoice` | api/accounting.py:74 | defined once, only this one ref; suspicious; could be route handler — verify |
| `_kakasi_converter` | api/_business_law_detector.py:184 | 2 refs total (def + 1) — likely lazy-init helper |
| `KpiSeverity` | api/admin_kpi.py:85 | Pydantic enum, 1 ref = definition only |
| `ClientTagBreakdownResponse` | api/billing_breakdown.py:132 | Pydantic response model, 1 ref = definition only |
| `UsageByChildResponse` | api/me.py:353 | Pydantic response model, 1 ref = definition only |
| `cluster_spillover` | api/_contributor_trust.py:200 | 7 refs (incl. tests) — actually used |
| `default_user_message_for` | api/_envelope.py:298 | 6 refs (incl. tests) — actually used |
| `parse_license_filter` | api/_universal_envelope.py:135 | 8 refs (incl. tests) — actually used |
| `filter_rows_by_license` | api/_universal_envelope.py:152 | 2 refs — possibly dead in src too |
| `build_envelope_extras` | api/_universal_envelope.py:430 | 7 refs (incl. tests) — actually used |
| `_reset_corpus_snapshot_cache_for_tests` | api/_audit_seal.py:452 | 27 refs (test-only helper, intentional) |

Vulture-60 totals: 548 unused functions, 56 unused methods, 3 unused
classes, 868 unused variables, 80 unused attributes, 0 unused imports.
**The 548 / 56 / 3 numbers are dominated by FastAPI routes (`@router.get`),
Pydantic `@field_validator` / `@model_validator`, MCP `@mcp.tool`
decorators, and FastAPI / Starlette `dispatch(...)` middleware overrides** —
not real dead code. The genuine signal is the **10-function
`next_calls_for_*` family + 3 response-model classes** above.

---

## D. Duplicate / overlapping modules

### D.1 Envelope sprawl (8 files, 4400 lines combined)

8 separate "envelope" modules wrap response shaping across `api/` and `mcp/`:

| Path | Lines | Purpose (per file) |
|---|---|---|
| api/_envelope.py | 910 | Pydantic models + factory methods for success / error envelopes |
| api/_error_envelope.py | 721 | Error envelope variants (overlap with `_envelope.py`) |
| api/_universal_envelope.py | 457 | `next_calls_for_*` + `parse_license_filter` + `build_envelope_extras` |
| api/_compact_envelope.py | 475 | "Compact" response shape |
| api/middleware/envelope_adapter.py | (small) | middleware bridge |
| mcp/_envelope.py | 137 | MCP-side envelope |
| mcp/autonomath_tools/envelope_wrapper.py | 1307 | per-tool envelope wrapper (largest of the 8) |
| mcp/autonomath_tools/error_envelope.py | 299 | autonomath-tools error variant |
| mcp/autonomath_tools/tools_envelope.py | 94 | tiny extra |

Top-5 duplicate-functionality clusters:

1. **api/_envelope.py vs api/_error_envelope.py** (910 + 721 lines) — both
   define error envelope shapes; the `_error_envelope.py` file likely
   superseded `_envelope.py`'s error helpers but the old methods are still
   kept (which is why vulture flagged `rate_limited` / `unauthorized` /
   `forbidden` / `bad_request` / `license_gate_blocked` / `integrity_error`
   in `_envelope.py`).
2. **api/_envelope.py vs api/_compact_envelope.py vs api/_universal_envelope.py**
   — three success-envelope shapers in the same dir.
3. **api/_envelope.py vs mcp/_envelope.py** — separate models in separate
   dirs, basename collision.
4. **mcp/autonomath_tools/{envelope_wrapper,error_envelope,tools_envelope}.py**
   — three envelope helpers in the same package; `envelope_wrapper.py` at
   1307 lines is the largest envelope file in the repo.
5. **api/middleware/envelope_adapter.py** — bridges middleware to one of
   the above; adds a fifth top-level envelope-related file under `api/`.

### D.2 Basename collisions (cross-dir same name)

Vulture-orthogonal scan via `find ... -name '*.py' | basename | sort | uniq -c`:

| Basename | Paths | Verdict |
|---|---|---|
| `tools.py` | mcp/real_estate_tools/, mcp/autonomath_tools/, mcp/healthcare_tools/ | intentional package convention |
| `public_source_foundation.py` | ingest/normalizers/, ingest/schemas/ | **different contents** — normalizer vs schema, OK |
| `evidence_batch.py` | api/, mcp/autonomath_tools/ | **review needed** — could be API wrapper vs MCP wrapper |
| `english_wedge.py` | api/, mcp/autonomath_tools/ | same — likely intentional thin wrapper pair |
| `eligibility_predicate.py` | api/, ingest/schemas/ | **different content** — runtime vs schema |
| `discover.py` | api/, mcp/autonomath_tools/ | likely API + MCP pair |
| `config.py` | top-level `config.py`, `line/config.py` | line-bot subdir config, OK |
| `_envelope.py` | api/, mcp/ | covered in D.1 |

---

## E. Circular imports

Static AST walk across `src/jpintel_mcp/`:

**3 top-level cycles** detected. All benign — Python tolerates them because
the imported name is only **used inside function bodies**, never at module-
import time. Verified via `python -c "import jpintel_mcp.api.deps; import
jpintel_mcp.api.funnel_events; print('imports ok')"` → succeeds.

| Cycle (top-level) | Risk | Why benign |
|---|---|---|
| `api.deps` → `api.funnel_events` → `api.middleware.analytics_recorder` → `api.deps` | LOW | `analytics_recorder` imports `hash_api_key` from `deps`; `deps` re-imports `_classify_src` from `analytics_recorder`. Both names are used only inside function bodies, so the second-pass import resolves against the partially-initialized module. |
| `api.deps` → `api.middleware.customer_cap` → `api.deps` | LOW | same pattern |
| `mcp.server` → `mcp.autonomath_tools.tools` → `mcp.server` | LOW | `tools.py` imports `mcp` from `server.py` to register `@mcp.tool` — only attribute access; safe |

**7 additional cycles** detected but classified as **not cycles** on second
inspection — the `formats/*` modules import from `_format_dispatch` at top
level, but `_format_dispatch.py` imports from `formats/*` only inside
function bodies (lazy lookup). Vulture-style AST walk over-reports these.

| Pseudo-cycle | Real type |
|---|---|
| `api._format_dispatch` ↔ `api.formats.md` | lazy-import (line 272 of `_format_dispatch`) |
| `api._format_dispatch` ↔ `api.formats.accounting_csv` | lazy (line 284) |
| `api._format_dispatch` ↔ `api.formats.xlsx` | lazy (line 268) |
| `api._format_dispatch` ↔ `api.formats.docx_application` | lazy (line 280) |
| `api._format_dispatch` ↔ `api.formats.ics` | lazy (line 276) |
| `api._format_dispatch` ↔ `api.formats.csv` | lazy (line 264) |

Top-level imports from `_format_dispatch.py` to `formats.*`: **0** (verified
by AST). So these are safe by design.

---

## Top-10 unused declared deps (deduplicated)

1. `sqlite-utils` — 0 repo refs, drop candidate
2. `tenacity` — 0 repo refs, drop candidate
3. (no further candidates — the other 22 prod deps all have ≥1 direct
   or indirect via pydantic/fastapi requirement)

## Top-10 outdated deps (PyPI latest > declared cap)

1. `fastapi 0.120.4 < 0.121` cap vs PyPI **0.136.1**
2. `stripe 12.5.1 < 13` cap vs PyPI **15.1.0** (2 majors behind)
3. `starlette 0.49.3 < 0.50` cap vs PyPI **1.0.0**
4. `uvicorn 0.39.0 < 0.40` cap vs PyPI **0.46.0**
5. `mypy 1.20.2` (dev) vs PyPI **2.0.0**
6. `icalendar 6.3.2 < 7` cap vs PyPI **7.1.0**
7. `huggingface_hub 1.13.0` (dev, **already past cap `<1`**) vs PyPI 1.14.0
8. `sentry-sdk 2.58.0 < 3` cap vs PyPI 2.59.0
9. `playwright 1.58.0` (e2e) vs PyPI 1.59.0
10. `pdfminer.six 20251230` (transitive, via pdfplumber) vs 20260107

## Top-20 dead code candidates

1-10: `next_calls_for_{program,law,court_decision,case_study,bid,invoice_registrant,loan,tax_ruleset,enforcement,am_entity}` in `api/_universal_envelope.py` — test-imported, never wired into any route handler. Removing the 10 funcs (and the test that imports them) would shed ~170 lines.

11. `validate_invoice` — `api/accounting.py:74` (1 ref) — needs route-decorator audit; if it's just defined but no `@router.post`, this is a stranded helper.
12. `_kakasi_converter` — `api/_business_law_detector.py:184` (2 refs) — single-call lazy init or genuinely dead.
13. `KpiSeverity` — `api/admin_kpi.py:85` Pydantic enum, defined-only.
14. `ClientTagBreakdownResponse` — `api/billing_breakdown.py:132` defined-only.
15. `UsageByChildResponse` — `api/me.py:353` defined-only.
16. `filter_rows_by_license` — `api/_universal_envelope.py:152` (2 refs) — borderline.
17. 6 unused `_envelope.py` factory methods (`rate_limited` / `unauthorized` / `forbidden` / `bad_request` / `license_gate_blocked` / `integrity_error`) — superseded by `_error_envelope.py`. Confidence ~60% (vulture). Would shed ~150 lines if confirmed.
18. `cluster_spillover` constants (`CLUSTER_SPILLOVER_ALPHA` / `DIRECT_VERIFY_ALPHA` / `PRIOR_CLUSTER_BUMP` / `PRIOR_CLUSTER_BUMP_CAP`) — 4 module-level constants flagged 60%, need usage verification.
19. `_reset_corpus_snapshot_cache_for_tests` (27 refs) — test-only helper, **intentional** (vulture flagged it but it is heavily used in `tests/`).
20. ~530 other vulture-60 flags — overwhelmingly FastAPI route handlers
   (`@router.get(...)`), Pydantic `@field_validator` decorators, MCP
   `@mcp.tool` registrations, and `dispatch(...)` middleware overrides
   that vulture cannot resolve. **Treat as noise unless individually
   verified.**

## Top-5 duplicate / overlapping modules

1. **Envelope sprawl across `api/` + `mcp/`** — 8 files, 4400 lines combined.
   Top-3 culprits: `api/_envelope.py` (910L) / `api/_error_envelope.py`
   (721L) / `mcp/autonomath_tools/envelope_wrapper.py` (1307L).
2. **Error envelope methods in `api/_envelope.py`** vs sibling
   `api/_error_envelope.py` — 6 factory methods in `_envelope.py` (`rate_limited`,
   `unauthorized`, `forbidden`, `bad_request`, `license_gate_blocked`,
   `integrity_error`) appear to be superseded by `_error_envelope.py` but
   neither file is the unambiguous successor; both stay live.
3. **`mcp/autonomath_tools/{envelope_wrapper, error_envelope, tools_envelope}.py`**
   — three envelope helpers in one package; the 1307-line `envelope_wrapper`
   could likely subsume the 94-line `tools_envelope`.
4. **`ingest/normalizers/public_source_foundation.py` vs
   `ingest/schemas/public_source_foundation.py`** — different contents
   (normalizer / schema split is intentional) but the basename collision
   is a footgun for `from jpintel_mcp.ingest.public_source_foundation import ...`
   misimports.
5. **`api/{evidence_batch,english_wedge,discover}.py` vs
   `mcp/autonomath_tools/{evidence_batch,english_wedge,discover}.py`** —
   3 basename pairs across api ↔ mcp. Likely intentional (REST wrapper
   ⇄ MCP tool pair), but a brief audit would confirm whether either side
   is now a passthrough.

---

## Recommended next steps (read-only — no code modifications were performed)

The audit is informational. If a follow-up cleanup pass is approved, the
highest-signal actions are:

- Drop `sqlite-utils` and `tenacity` from `pyproject.toml` `[project.dependencies]`
  (0 in-repo references, no transitive requirement found).
- Consider removing the 10 `next_calls_for_*` functions in
  `api/_universal_envelope.py` (test-only callers) — ~170 LOC.
- Audit envelope sprawl (D.1) for a future single-source consolidation.
- Bump caps on `fastapi` / `stripe` / `uvicorn` / `starlette` / `icalendar`
  / `mypy` after a breaking-change review per their changelogs.
- Fix cap drift on `huggingface_hub` (declared `<1`, installed `1.13.0`).

**Did not perform** any module / function removal, dep removal, or cap
bump. This file is the only artifact.
