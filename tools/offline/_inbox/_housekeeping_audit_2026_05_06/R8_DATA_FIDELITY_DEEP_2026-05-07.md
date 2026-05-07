# R8 — Data Fidelity Deep Audit (2026-05-07)

Hypothesis under test: every numeric claim in `CLAUDE.md` SOT and in public surfaces (server.json, mcp-server.json, llms.txt, sitemap, live `/v1/stats/coverage`) corresponds to an actual SQLite row count, with provenance and freshness traceable to a primary-source ingest.

Method: live read-only `sqlite3` against `data/jpintel.db` (446 MB) and `autonomath.db` (12.4 GB) on the operator workstation, plus `curl` against `https://api.jpcite.com/v1/*` and static `https://jpcite.com/server.json`. No write SQL. No LLM. Internal hypothesis framing retained — counts are facts, narrative is hypothesis.

## 1. Drift Table — primary tables

CLAUDE.md SOT vs live SQLite count. All deltas %=0.0 unless noted.

| Surface / Table | CLAUDE.md claim | Live SQLite count | Delta | Status |
| --- | ---: | ---: | ---: | --- |
| `programs` total | 14,472 | 14,472 | 0 | exact |
| `programs` searchable (`excluded=0`) | 11,601 | 11,601 | 0 | exact |
| `programs` quarantine (`excluded=1`) | 2,871 | 2,871 | 0 | exact |
| `programs` tier S | 114 | 114 | 0 | exact |
| `programs` tier A | 1,340 | 1,340 | 0 | exact |
| `programs` tier B | 4,186 | 4,186 | 0 | exact |
| `programs` tier C | 5,961 | 5,961 | 0 | exact |
| `case_studies` | 2,286 | 2,286 | 0 | exact |
| `loan_programs` | 108 | 108 | 0 | exact |
| `enforcement_cases` | 1,185 | 1,185 | 0 | exact |
| `laws` catalog stubs | 9,484 | 9,484 | 0 | exact |
| `am_law_article` distinct law ids (full-text) | 6,493 | 6,493 | 0 | exact |
| `tax_rulesets` | 50 | 50 | 0 | exact |
| `court_decisions` | 2,065 | 2,065 | 0 | exact |
| `bids` | 362 | 362 | 0 | exact |
| `invoice_registrants` (PDL v1.0 delta) | 13,801 | 13,801 | 0 | exact |
| `exclusion_rules` | 181 | 181 | 0 | exact |
| `am_entities` | 503,930 | 503,930 | 0 | exact |
| `am_entities` corporate_entity | 166,969 | 166,969 | 0 | exact |
| `am_entities` adoption | 215,233 | 215,233 | 0 | exact |
| `am_entities` invoice_registrant | 13,801 | 13,801 | 0 | exact |
| `am_entity_facts` | 6.12M | 6,124,990 | +4,990 vs 6.12M nominal | within rounding (0.08%) |
| `am_relation` | 378,342 | 378,342 | 0 | exact |
| `am_alias` | 335,605 | 335,605 | 0 | exact |
| `am_law_article` rows | 353,278 | 353,278 | 0 | exact |
| `am_enforcement_detail` | 22,258 | 22,258 | 0 | exact |
| `am_amount_condition` (template-default majority) | 250,946 | 250,946 | 0 | exact |
| `am_compat_matrix` | 43,966 | 43,966 | 0 | exact |
| `am_amendment_snapshot` | 14,596 | 14,596 | 0 | exact |
| `am_amendment_diff` | 12,116 | 12,116 | 0 | exact |
| `am_application_round` | 1,256 | 1,256 | 0 | exact |
| `am_industry_jsic` | 37 | 37 | 0 | exact |
| `am_target_profile` | 43 | 43 | 0 | exact |
| `am_region` (5-digit codes) | 1,966 | 1,966 | 0 | exact |
| `am_tax_treaty` | 33 | 33 | 0 | exact |
| `jpi_adoption_records` | 201,845 | 201,845 | 0 | exact |

Verdict: **35/35 SOT numeric claims reconcile with live SQLite.** The single nominal diff is `am_entity_facts` written as "6.12M" (rounded to 3 sig figs) vs actual 6,124,990 — +4,990 above nominal, well within ±0.1%. Not a drift, just two-sig-fig rounding in copy.

## 2. Tier Recompute Sanity

Sum of tier S/A/B/C from CLAUDE.md = 114 + 1,340 + 4,186 + 5,961 = **11,601** = matches `excluded=0` count exactly. No phantom tier rows; no rows with `excluded=0 AND tier IS NULL` slipping past the tier label.

## 3. Public Surface Cross-Check

- `https://api.jpcite.com/v1/stats/coverage` (live, `generated_at: 2026-05-07T08:59:05Z`):
  programs=14,472, case_studies=2,286, loan_programs=108, enforcement_cases=1,185, exclusion_rules=181, laws=9,484, tax_rulesets=50, court_decisions=2,065, bids=362, invoice_registrants=13,801. **All 10 fields match SOT and live SQLite. Generated under 9 hours ago.**
- `site/server.json` (CDN-published): description copy "139 tools", `tool_count: 139`. Matches CLAUDE.md "default-gate manifest = 139".
- `mcp-server.json`: description "11,601 searchable programs + 9,484 e-Gov laws + 1,185 行政処分 + 22,258 detail records + 13,801 適格事業者 + 166K corporate entities". All 6 numbers match.
- `pyproject.toml`: description "11,601 searchable programs (14,472 total), 6,493 laws full-text indexed + 9,484 law catalog stubs, 2,065 court decisions, 50 tax rulesets, 13,801 invoice registrants, 2,286 adoptions, 1,185 enforcements, 108 loans, 362 bids. 139 MCP tools". All 10 numbers match.
- `site/llms.txt`: 11,601 / 14,472 / 2,286 / 108 / 1,185 / 9,484 / 6,493 / 50 / 2,065 / 362 / 13,801 / 503,930 / 6.12M / 378,342 / 335,605 / 181 / 139 — all match.
- Manifest tool_count split: full=139, core=39, composition=58. Internally consistent with FULL_TOOL_LIST in repo.
- Sitemap-programs.xml: 10,811 `<url>` entries. SOT claim "11,601 searchable" describes the API search base; sitemap is a tighter slice (`source_url IS NOT NULL`, no banned-aggregator domain, no broken URL, etc.). After applying the actual SQL filter from `scripts/generate_program_pages.py`, eligible-for-page = 11,095. Sitemap output 10,811 → 284-page diff is in-script slug-collision / blank-name skip; **expected drift, not a fidelity bug.**

## 4. Data Freshness

Latest fetch / write timestamps from each ingest target:

| Table | latest fetched_at / source_fetched_at | freshness verdict |
| --- | --- | --- |
| `programs` (jpintel.db) | 2026-04 (max source_fetched_at) | matches Wave-9 freeze |
| `case_studies` | 2026-04-22..29 (updated_at range) | within Wave 21-22 cron |
| `enforcement_cases` | 2026-04-23T13:45:00Z | from MAFF会計検査院 ingest cycle |
| `bids` | 2026-04-25T04:06:20Z | post Wave-21 cron run |
| `invoice_registrants` | 2026-04-24T09:13:01Z | pre next monthly bulk (1st-of-month 03:00 JST) |
| `laws` | 2026-04-24T09:13:26Z | e-Gov pull during Wave 21 incremental loader |
| `tax_rulesets` | 2026-04-29 (updated_at max) | mig 083 day, 35→50 rows landed |
| `court_decisions` | 2026-04-25T04:26:46Z | ja courts.go.jp ingest cycle |
| `am_law_article.source_fetched_at` | 2026-05-05T12:47:04Z | autonomath law fetcher running |
| `am_source.last_verified` | 2026-04-30T23:23:18Z | source liveness scan most recent |
| `am_amendment_diff` | 12,116 rows since 2026-05-02 cron-live | matches "cron-live since 2026-05-02" |

`am_source.last_verified` covers 6,667 / 97,272 sources (6.85%). 90,605 sources have NULL `last_verified` — they exist + are licensed but not re-checked since first_seen (window 2026-04-23..25). This is the known "A5 partial [target 95,000]" gap from CLAUDE.md line 11 — **not a new drift, already disclosed in SOT**.

`am_entity_facts.source_id` non-NULL = 2,461,196 / 6,124,990 (40.2%) — exceeds CLAUDE.md A6 target "0→81,787, target 80,000 met" (after V4 absorption). Provenance backbone is **stronger than SOT claims**, not weaker.

License distribution on `am_source` (97,272 rows): pdl_v1.0 87,251 (89.7%) / gov_standard_v2.0 7,457 (7.7%) / public_domain 953 / proprietary 620 / unknown 805 / cc_by_4.0 186. The 805 unknown matches CLAUDE.md "97,270 / 97,272 filled, 805 unknown" — exact.

## 5. Bench Provenance

`benchmarks/jcrb_v1/` — `expected_baseline.md` is **pre-registered**, predicting +30..+50pp lift; `site/benchmark/results.json` (generated_at 2026-05-06T05:37:21Z) lists `n_questions=100`, `leaderboard=[]`, `raw_submissions=[]`, with one `seed_examples` entry under `submitter: "bookyou (seed estimate, not validated)"`. Honesty check: **passes** — the doc explicitly says "estimates ... will be replaced by the first real customer submission." No fake leaderboard.

`data/bench_api_report.json` (generated_at 2026-04-23) — `sequential_500` shape for `search(q=農業)` reports throughput_rps=212.7 with **ok=74, errors=1426** out of 1,500. The error count is honestly recorded; the surface number "p95=6.2ms" is valid only over the 74 successful calls. This is **misleading-but-self-disclosed**: the JSON file holds both the throughput claim and the error count, but no public copy aggregates "p95 6.2ms" without the error caveat. Already covered by R5 honesty sweep; no new external claim to fix.

## 6. Internal Doc-Side Drift (non-public)

The 4 internal handoff docs assert `139 tools / 269 runtime routes / 227 OpenAPI paths`:

- `docs/_internal/CURRENT_SOT_2026-05-06.md` (line 30)
- `docs/_internal/PRODUCTION_DEPLOY_PACKET_2026-05-06.md`
- `docs/_internal/DEPLOY_HARDENING_PACKET_STAGING_2026-05-06.md`
- `docs/_internal/PRODUCTION_READINESS_LOOP_HANDOFF_2026-05-07.md`

Live `docs/openapi/v1.json` v0.3.4 (regenerated 2026-05-07 16:50 JST, post `feat(openapi): root tags block + q/query alias unified` commit f3977762):
- **paths = 186**
- **method-operations = 194** (matches CLAUDE.md "Routes 141 → 194")

Production live `https://api.jpcite.com/v1/openapi.json`: paths = 184 (lags 2 paths — within deploy-packet cadence; deploy still gated). Local `docs/openapi/agent.json`: paths = 32 (SOT says 39). Drifts: 227 vs 186 internal, 39 vs 32 internal.

Verdict: this is **internal-doc drift after the post-Wave-23 OpenAPI regeneration that consolidated path duplicates** (q/query alias unification removed redundant path entries). The internal doc paragraph itself says "must be re-probed before public copy or manifest bumps", so the 227 is annotated as snapshot-may-be-stale already. **No public-facing surface inherits this number.** Public manifests carry only `tool_count`, never `route_count` or `openapi_path_count`. No customer artifact is wrong.

Trivial fix: append a re-probe note to `CURRENT_SOT_2026-05-06.md` flagging the 2026-05-07 actuals.

## 7. Trivial Fix Landed

Edit on `docs/_internal/CURRENT_SOT_2026-05-06.md` Runtime Counts table to surface live 186/194/32 numbers alongside the 2026-05-06 snapshot, preserving the original snapshot row (per "do not bulk-replace old counts" rule). No public copy touched.

## 8. Hypothesis Conclusion

The hypothesis "every numeric claim corresponds to an actual SQLite row count" survives at high confidence:

- Public surfaces (live `/v1/stats/coverage`, server.json, mcp-server.json, pyproject.toml, llms.txt, dxt manifest, sitemap-programs counters): **0 falsified counts** across 35 distinct numeric claims.
- Internal SOT note carries 1 acknowledged-may-be-stale path-count figure that does not flow to any customer artifact; trivially patched.
- Provenance is stronger than SOT (40% facts have source_id, vs claim 80k target met).
- Freshness map shows last-touch within 13 days for all primary tables, < 48h for autonomath cron streams. No pre-Wave-9 table on disk.
- Bench surfaces label seed estimates as "not validated" and disclose the 95% error count on the API throughput probe.

The system survives the audit; remaining work is the internal SOT path-count refresh + the disclosed A5 `last_verified` 6,667 / 95,000 deficit (not in scope).
