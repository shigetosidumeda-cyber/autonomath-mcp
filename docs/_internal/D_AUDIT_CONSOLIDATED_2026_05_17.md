# D-Series Audit Consolidation (D1-D5) — 2026-05-17

- Author: Claude Opus 4.7
- Lane: `lane:solo`
- Scope: READ-ONLY consolidation of D1 (integration map), D2 (migration drift), D3 (MCP registry), D4 (E2E user journey), D5 (production gate root cause). No source artifact modified. CodeX collision avoidance: new doc only.
- Status of pending task list (`task #312`, `#313`, `#318`, `#319`) updated to reflect real on-disk state captured at this SHA.
- Inputs walked:
  - `docs/_internal/MOAT_INTEGRATION_MAP_2026_05_17.md` (D1)
  - `docs/_internal/CL7_MIGRATION_APPLY_5_AUDIT_2026_05_17.md` (D2)
  - `docs/_internal/MOAT_MCP_REGISTRY_AUDIT_2026_05_17.md` (D3)
  - `docs/_internal/MOAT_E2E_JOURNEY_2026_05_17.md` (D4)
  - `docs/_internal/CL6_PRODUCTION_GATE_4_FAIL_AUDIT_2026_05_17.md` (D5 ref, commit `c3b45f215`)
- Live verification (this session):
  - `runtime_tools = 231` via `mcp.list_tools()` (jpintel_mcp.mcp.server)
  - `mcp-server.json _meta.tool_count = 184` (drift +47)
  - `site/releases/rc1-p0-bootstrap/preflight_scorecard.json` → `state=AWS_CANARY_READY`, `live_aws_commands_allowed=true`, unlocked 2026-05-17T03:11:48Z
  - sqlite probe on `autonomath.db`: 6 tables NOT_EXIST (`am_outcome_chunk_map`, `am_outcome_cohort_variant`, `am_nta_qa`, `am_chihouzei_tsutatsu`, `am_pdf_watch_log`, `am_municipality_subsidy`); `am_placeholder_mapping` already EXIST 207 rows
  - boot manifests sync: both `autonomath_boot_manifest.txt` + `jpcite_boot_manifest.txt` carry 168 / 168 entries, byte-identical (494 lines each incl. comments) — none of the 6 missing tables are listed

---

## Section 1 — D1-D5 one-line summary

| ID | Audit | Source doc | Headline finding | Status today |
| --- | --- | --- | --- | --- |
| D1 | 21-lane × 5-dim integration map (M1-M11 + N1-N10) | `MOAT_INTEGRATION_MAP_2026_05_17.md` | 1 CRITICAL: missing `wave24_206_am_placeholder_mapping.sql` referenced by `moat_n9_placeholder.py:4`; 0 migration-ID collision; 7 latent name shadows in `autonomath_tools/`; 0 active MCP collision | LANDED (audit doc); CRITICAL still open (file absent on disk, but table exists in `autonomath.db` 207 rows — out-of-band hydrate, no migration file ever shipped) |
| D2 | 5-of-6 migration boot-manifest drift | `CL7_MIGRATION_APPLY_5_AUDIT_2026_05_17.md` | 6 SQL files landed under `scripts/migrations/wave24_2*` but 0 of them in either manifest, 0 of them applied to live `autonomath.db` | LANDED (audit doc); 6/6 unapplied confirmed at this SHA |
| D3 | FastMCP registry audit | `MOAT_MCP_REGISTRY_AUDIT_2026_05_17.md` | runtime=216 at audit time → **now 231 (live probe)**; manifests still pinned at 184 (47-tool drift); 0 active collisions; 3 orphan source dup definitions (`get_recipe` / `list_recipes` / `resolve_placeholder`) | LANDED (audit doc); manifest drift unresolved — see D5 Fail 3 |
| D4 | E2E 5-segment user journey simulation | `MOAT_E2E_JOURNEY_2026_05_17.md` | 5/5 PASS, 26 MCP calls / ¥78 total, 0.97s wall, mypy 0 / ruff 0; 6 integration gaps catalogued (G1-G6) with in-test mitigations | LANDED (audit + tests); pass status reproducible via `JPINTEL_E2E=1 pytest tests/e2e/test_user_journey_*.py -v` |
| D5 | Production deploy readiness gate 4/7 FAIL root cause | `CL6_PRODUCTION_GATE_4_FAIL_AUDIT_2026_05_17.md` (`c3b45f215`) | 4 fails: `release_capsule_validator` + `aws_blocked_preflight_state` share 1 signal (scorecard unlock); `openapi_drift` (4 stale exports + 4 discovery hash mismatches); `mcp_drift` (runtime 231 vs manifest 184) | LANDED (audit doc); 4 fails still unresolved at this SHA |

---

## Section 2 — Current pass/fail state per audit

### D1 — Integration map (CRITICAL: 1 / latent: 7 / 0 active)

| Item | State | Evidence |
| --- | --- | --- |
| 21 lanes catalogued (M1-M11 + N1-N10) | DONE | `MOAT_INTEGRATION_MAP_2026_05_17.md §1` |
| LIVE lane count | 10 (M10 + N1-N9) | unchanged today |
| PENDING lane count | 11 (M1-M9, M11) | unchanged today |
| Migration-ID collision | 0 | wave24_195/198/200-205 each owned by exactly one lane |
| MCP tool-name collision in moat roster | 0 | 32 unique names across moat_lane_tools/ |
| MCP tool-name collision vs 184 baseline | 0 active | diff sort verified |
| **CRITICAL** — `wave24_206_am_placeholder_mapping.sql` | **MISSING ON DISK / live table EXIST 207 rows** | confirms out-of-band loader (`scripts/cron/load_placeholder_mappings_2026_05_17.py`) populated the table without a versioned migration ever landing. Risk: any prod boot on a fresh autonomath.db cannot reproduce the table. |
| Duplicate file shadows in `src/jpintel_mcp/mcp/autonomath_tools/` | 5 files / 7 latent collision events | inactive (no import); flips active the moment `autonomath_tools/__init__.py` adds the import |

### D2 — Migration drift (6 unapplied, 6 unregistered)

| Migration | target_db | Idempotent? | In manifest? | Applied to autonomath.db? |
| --- | --- | --- | --- | --- |
| `wave24_212_am_nta_qa.sql` | autonomath | yes (CREATE IF NOT EXISTS + FTS5) | NO | NO |
| `wave24_213_am_chihouzei_tsutatsu.sql` | autonomath | yes | NO | NO |
| `wave24_216_am_pdf_watch_log.sql` | autonomath | yes (scaffold-only) | NO | NO |
| `wave24_217_am_municipality_subsidy.sql` | autonomath | yes | NO | NO |
| `wave24_220_am_outcome_chunk_map.sql` | autonomath | yes (PK outcome_id+rank) | NO | NO |
| `wave24_221_am_outcome_cohort_variant.sql` | autonomath | yes (UNIQ outcome_id+cohort) | NO | NO |
| `wave24_206_am_placeholder_mapping.sql` (D1 CRITICAL) | autonomath (intended) | n/a — file absent | NO | table exists 207 rows (out-of-band) |

Per `entrypoint.sh §4` (`AUTONOMATH_BOOT_MIGRATION_MODE=manifest` default), the self-heal loop skips any filename not in the manifest. **All 6 D2 migrations are dormant on every prod boot.**

Both manifests are byte-identical (494 lines / 168 entries each) — dual-read alias invariant holds.

"0 production-ready" reading: the audit's interpretation is that none of the 6 candidates are production-deployable today because (a) not in manifest, (b) post-apply populate scripts depend on out-of-scope ETL state (NTA crawl URL repair, municipality OCR, M5/M6 cohort outputs, etc.). The migrations themselves are pure additive DDL and would each apply in milliseconds; only the post-apply data flow is gated.

### D3 — MCP registry (231 live / 184 manifest / 47 drift)

| Surface | tool_count today | Source |
| --- | --- | --- |
| Runtime (`mcp.list_tools()`) | **231** | live probe this session |
| `mcp-server.json _meta.tool_count` | 184 | grep result this session |
| `mcp-server.full.json` | 184 | same drift per D5 Fail 3 tail |
| `site/mcp-server.json` / `site/mcp-server.full.json` | 184 | same drift |
| `server.json` / `site/server.json` | 184 | same drift |
| `check_mcp_drift.py` hard range | `[130, 200]` | runtime 231 exceeds upper bound → FAIL |

47-tool delta consists of the Wave 89-94 outcome catalog expansion (M&A / talent / brand / safety / real_estate / insurance) plus 11 explicit cohort tools (`agent_briefing_pack` + 10 `agent_cohort_(deep|ultra)_*`).

Naming convention: 0 violations; orphan dup definitions: 3 (dead code, runtime impact zero). All moat lane tools are LIVE and each appears exactly once in the runtime registry.

### D4 — E2E user journey (5/5 PASS)

| Scenario | Test file | MCP calls | Cost | Status |
| --- | --- | --- | --- | --- |
| 1. 税理士 月次決算 | `tests/e2e/test_user_journey_zeirishi.py` | 4 | ¥12 | PASS |
| 2. 会計士 監査調書 | `tests/e2e/test_user_journey_kaikeishi.py` | 5 | ¥15 | PASS |
| 3. 行政書士 補助金申請 | `tests/e2e/test_user_journey_gyouseishoshi.py` | 9 | ¥27 | PASS |
| 4. 司法書士 会社設立登記 | `tests/e2e/test_user_journey_shihoshoshi.py` | 3 | ¥9 | PASS |
| 5. 社労士 就業規則 | `tests/e2e/test_user_journey_sharoushi.py` | 5 | ¥15 | PASS |
| Total | 5 / 5 | 26 | **¥78** | PASS |

Average ¥15.6 / artifact, well under the ¥300-¥900 outcome-justifiable-cost band. Default-skip via `--run-e2e` / `JPINTEL_E2E=1`. mypy strict 0 / ruff 0 on 6 new files.

Integration gaps the simulation exposed (G1-G6): G1 M9 PENDING chunk corpus (substitute N4 in 行政書士 path), G2 36協定 gated tool surface (use elaws.e-gov.go.jp 一次URL), **G3 `am_placeholder_mapping` migration absent (matches D1 CRITICAL + D2 manifest gap)**, G4 single-window match for 文京区 fixture, G5 会計士 監査調書 chain topic_id not in seed, G6 `_am` suffix discipline keeps REST vs MCP variants disjoint.

### D5 — Production deploy readiness gate (4/7 FAIL, single-shot path)

| # | Check | Result | Root cause |
| --- | --- | --- | --- |
| 1 | functions_typecheck | PASS | — |
| 2 | release_capsule_validator | FAIL | scorecard `live_aws_commands_allowed=true` (operator unlock 2026-05-17T03:11:48Z) |
| 3 | agent_runtime_contracts | PASS | — |
| 4 | openapi_drift | FAIL | 4 stale exports + 4 discovery hash mismatches (ensure_ascii flag drift) |
| 5 | mcp_drift | FAIL | runtime 231 vs manifest 184; drift range `[130,200]` exceeded |
| 6 | release_capsule_route | PASS | — |
| 7 | aws_blocked_preflight_state | FAIL | same single signal as #2 (scorecard unlock) |

`#2` + `#7` collapse to **one** scorecard flag flip. `#4` + `#5` are independent artifact-regeneration tasks.

---

## Section 3 — Cross-dependency map

Edges = "fixing A unblocks / impacts B".

```
D1.CRITICAL (wave24_206 missing file)
   ├── matches → D2 (manifest gap row for placeholder_mapping)
   └── matches → D4.G3 (test-only schema seed mitigation)
       └── prod-rollout blocker for N9 `resolve_placeholder`

D2 (6 unapplied)                          D3 (manifest 184 vs runtime 231)
   ├── prod boot can't restore tables      ├── breaks D5 Fail 5 (mcp_drift)
   └── post-apply populate scripts gated   └── 47-tool delta = Wave 89-94 catalog
                                              + 11 cohort/briefing surfaces

D4 (E2E 5/5 PASS)
   └── reads through 32 moat lane tools (D1 catalogue) →
       any tool name drift in D3 would invalidate D4 stability →
       today: 0 collision so D4 holds

D5 (master gate, 4 FAIL)
   ├── Fail 2 + Fail 7 = scorecard unlock (1 JSON edit fixes both)
   ├── Fail 4 = openapi exporter regenerate (independent)
   └── Fail 5 = D3 manifest drift (CodeX must re-emit 6 manifests +
       bump check_mcp_drift.py upper bound; operator decision on
       public/private gating for 11 cohort/briefing tools)
```

Master gate is D5. D1 CRITICAL + D2 do not block D5 directly today (production gate doesn't check `autonomath.db` migration state), but they will block the next prod boot recovery on a fresh DB.

---

## Section 4 — Priority fix queue

Prescription from D5 Section "Aggregated fix plan" (CodeX-owned, Step 7 already shipped in `c3b45f215`):

| Order | Fix | Source audit | Effort | Owner | Precondition |
| --- | --- | --- | --- | --- | --- |
| 1 | Re-lock `preflight_scorecard.json` → `live_aws_commands_allowed=false` (Option A) **after** AWS canary burn completes | D5 Fail 2 + 7 | small (1-line JSON + re-sign) | CodeX | Operator confirms canary done |
| 2 | Re-run OpenAPI exporter, commit regenerated `site/openapi/v1.json` / `site/openapi.agent.json` / `site/openapi/agent.json` / `site/openapi.agent.gpt30.json` + `site/docs/openapi/*` mirrors; refresh `site/.well-known/openapi-discovery.json`; pin `ensure_ascii` policy in exporter | D5 Fail 4 | medium | CodeX | Exporter target identified (`scripts/check_openapi_drift.py` writes to `/tmp/jpcite-openapi-drift-*/` — canonical generator) |
| 3 | Re-emit `mcp-server.json` / `mcp-server.full.json` / `site/server.json` / `server.json` (+ site mirrors) at `_meta.tool_count=231`; bump `check_mcp_drift.py` upper bound 200 → 250 OR gate 11 cohort/briefing tools out of public manifest | D5 Fail 5 + D3 | medium | CodeX | Operator decides public-vs-private gating for the 11 (`agent_briefing_pack` + 10 `agent_cohort_*`) |
| 4 | Author `wave24_206_am_placeholder_mapping.sql` from live schema (207-row table already exists) + append to both boot manifests | D1 CRITICAL + D4.G3 | small (introspect schema, emit DDL, manifest append in 2 files) | CodeX | None — purely additive |
| 5 | For each of the 6 D2 migrations: DRY_RUN parse-only → cp -a autonomath.db backup → executescript → append to both boot manifests | D2 | small per file (mechanical) | CodeX | Per-migration: post-apply populate prerequisites (NTA crawl URLs / municipality OCR / GG4/GG7 cohort artifacts) tracked separately |
| 6 | Cleanup 5 dormant duplicate files in `src/jpintel_mcp/mcp/autonomath_tools/` shadowing moat_lane_tools | D1 + D3 | small (git rm 5 files, no import change) | CodeX | Confirm no import / no fixture loads them |
| 7 | Re-run `production_deploy_readiness_gate.py`; expect 7/7 PASS once fixes 1+2+3 land | D5 | exec only | CodeX | Fixes 1+2+3 committed |

---

## Section 5 — Operator decision items

| # | Decision | Audit | Options | Impact if deferred |
| --- | --- | --- | --- | --- |
| 1 | After-canary scorecard policy | D5 Fail 2 + 7 | (A) re-lock `live_aws_commands_allowed=false` post-canary [recommended]; (B) split flag into `aws_burn_mode` vs `production_deploy_allowed` (schema bump + 2 validator edits) | Production deploy gate stays 3/7 PASS; cannot greenlight Fly prod deploy |
| 2 | 11 cohort/briefing tools public/private gating | D3 + D5 Fail 5 | (A) keep on public manifest (re-emit at 231 + bump drift ceiling to 250); (B) gate to `core` only (drop from `mcp-server.json` to keep 184-ish public ceiling) | mcp_drift remains FAIL; manifest cannot honestly advertise the registry |
| 3 | `wave24_206_am_placeholder_mapping.sql` authoring | D1 CRITICAL + D4.G3 | (A) introspect live table schema and emit DDL [recommended — table exists 207 rows]; (B) drop table + define from-scratch DDL + re-load 207 rows | New prod boot on fresh autonomath.db loses 207 placeholder mappings; N9 `resolve_placeholder` degrades on cold start |
| 4 | D2 post-apply populate scope | D2 | (A) apply DDL now, hydrate later as ETL prerequisites land; (B) wait until each populate pipeline is green before applying DDL | (A) leaves 6 empty tables in `autonomath.db` (read-safe); (B) keeps schema gap until upstream ETL clears |
| 5 | D1 latent shadow cleanup priority | D1 + D3 | (A) immediate `git rm` of 5 files [recommended — they cannot become active without an explicit import]; (B) defer to next major cleanup wave | Risk window: any future PR adding `from . import moat_n8_recipe` to `autonomath_tools/__init__.py` bricks FastMCP boot |

---

## Section 6 — Constraints honoured

- READ-ONLY scan. No source artifact / scorecard / manifest / SQL / test file modified.
- CodeX collision avoidance: only `docs/_internal/D_AUDIT_CONSOLIDATED_2026_05_17.md` created.
- Commit via `scripts/safe_commit.sh`, NO `--no-verify`.
- Co-Authored-By: Claude Opus 4.7.
- Lane tag `[lane:solo]` retained.

last_updated: 2026-05-17 (evening)
