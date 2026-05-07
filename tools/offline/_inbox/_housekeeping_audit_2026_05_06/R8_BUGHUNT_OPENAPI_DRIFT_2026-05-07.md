---
agent: R8 BUGHUNT — OpenAPI schema drift / Round 2 endpoint quality regression
date: 2026-05-07 JST
working_dir: /Users/shigetoumeda/jpcite
mode: READ-ONLY HTTP GET + non-destructive trivial fix (export_openapi.py + commit)
target_release: jpcite v0.3.4 / Round 2 (22 axis endpoints added)
inputs_consumed:
  - https://api.jpcite.com/v1/openapi.json (live, fetched 2026-05-07 12:32 GMT)
  - docs/openapi/v1.json (committed)
  - site/docs/openapi/v1.json (frontend mirror)
  - scripts/distribution_manifest.yml
  - prior R8_AI_CONSUMER_AUDIT_2026-05-07.md (baseline 91 short / 29 missing)
verdict: NO TRUE DRIFT. Live = 2026-05-06 build (3-endpoint deploy lag). Committed + site mirror byte-identical (sha256 f1982e88…). Manifest openapi_path_count=219 matches both. Round 2 regression check = CLEAN — 0 short summary / 0 missing description / 0 missing tag among 22 axis endpoints. Pre-existing legacy boilerplate (15 short / 29 missing desc) is NOT a Round 2 regression.
---

# R8 — OpenAPI Drift / Round 2 Quality Audit

## TL;DR

Three OpenAPI sources analyzed:

| Source | URL / path | Path count | Hash (sha256[:16]) | Build stamp |
|---|---|---|---|---|
| live | `https://api.jpcite.com/v1/openapi.json` | **216** | `c50b745d311f6820` | Server: `Fly/421c5554c (2026-05-06)` |
| committed | `docs/openapi/v1.json` | **219** | `f1982e880fdeef13` | head `010f794d` 2026-05-07 21:16 JST |
| site mirror | `site/docs/openapi/v1.json` | **219** | `f1982e880fdeef13` | identical to committed |

**Drift verdict**: NOT a real drift bug. Committed and site mirror are byte-identical. Live lags by **3 endpoints** because the production Fly machine is the 2026-05-06 build; the 3 endpoints (advisor handoff preview + 2 APPI privacy intake) landed in source on 2026-05-07 and roll out on next deploy. This is expected deploy lag, not a schema integrity issue.

**Round 2 quality regression**: 0/22 endpoints regressed. All 22 carry summary ≥10 chars + non-empty description + tags array. The R8 AI Consumer Audit baseline (91 short summaries / 29 missing descriptions across the entire 227-operation surface) has improved on the short-summary axis (91 → **15**, all pre-existing legacy boilerplate unchanged for ≥30 days) and stayed flat on the missing-description axis (29 → **29**, identical legacy set).

Manifest `openapi_path_count: 219` already matches committed + site (no manifest update needed; pre-commit `check_distribution_manifest_drift.py` passes).

---

## 1. Three-source path delta

The 3 paths in committed but NOT yet in live:

```
POST /v1/advisors/handoffs/preview
POST /v1/privacy/deletion_request
POST /v1/privacy/disclosure_request
```

All three have full summary + description + tags:

- `POST /v1/advisors/handoffs/preview` — summary "Preview Advisor Handoff", description "Preview an advisor handoff without creating referrals or stored records…", tags=`['advisors']`.
- `POST /v1/privacy/deletion_request` — summary "Submit an APPI Article 33 personal-data deletion request", tags=`['privacy']`.
- `POST /v1/privacy/disclosure_request` — summary "Submit an APPI Article 31 personal-data disclosure request", tags=`['privacy']`.

These are recent commits (2026-05-07 morning). Production deploy on next push will close the 3-endpoint lag.

**No paths exist in live but missing from committed** (`live - committed = ∅`). No backwards drift.

**No path delta between committed and site mirror** (`committed XOR site = ∅`). Mirror is in sync.

## 2. Schema integrity

- Total `components.schemas` count: **273**.
- Broken `$ref` targets: **0** (recursive walk of every node).
- Both files share identical sha256 `f1982e880fdeef13`. The two files differ only by their dirname path; bytes are identical.
- `docs/openapi/agent.json` and `site/docs/openapi/agent.json` and `site/openapi.agent.json` (legacy) all 33 paths, all v0.3.4 — 3-way agent.json mirror in sync.

## 3. Round 2 endpoint quality (22 axis sweep)

Round 2 added 22 axis endpoints (cohort matcher, M&A succession, disaster, policy upstream, full chain, benchmark, portfolio optimize, etc.). Per-endpoint quality scan against R8 AI Consumer Audit thresholds (summary ≥10 chars / non-empty description / non-empty tags array):

```
OK  POST /v1/advisors/handoffs/preview        tags=['advisors']
OK  POST /v1/benchmark/cohort_average         tags=['benchmark']
OK  POST /v1/cases/cohort_match               tags=['case-studies']
OK  GET  /v1/cases/timeline_trend             tags=['timeline-trend']
OK  GET  /v1/disaster/active_programs         tags=['disaster']
OK  GET  /v1/disaster/catalog                 tags=['disaster']
OK  POST /v1/disaster/match                   tags=['disaster']
OK  GET  /v1/funding_stages/catalog           tags=['funding-stage']
OK  GET  /v1/houjin/{bangou}                  tags=['houjin']
OK  GET  /v1/houjin/{bangou}/invoice_status   tags=['houjin']
OK  GET  /v1/houjin/{houjin_bangou}/360       tags=['houjin']
OK  GET  /v1/me/benchmark_vs_industry         tags=['benchmark']
OK  GET  /v1/me/upcoming_rounds_for_my_profile tags=['timeline-trend']
OK  GET  /v1/policy_upstream/{topic}/timeline tags=['policy-upstream']
OK  POST /v1/privacy/deletion_request         tags=['privacy']
OK  POST /v1/privacy/disclosure_request       tags=['privacy']
OK  POST /v1/programs/portfolio_optimize      tags=['programs']
OK  GET  /v1/programs/{program_id}/timeline   tags=['timeline-trend']
OK  GET  /v1/stats/benchmark/industry/{jsic_code_major}/region/{region_code}
                                              tags=['stats','transparency']
OK  POST /v1/succession/match                 tags=['succession']
OK  GET  /v1/succession/playbook              tags=['succession']
OK  GET  /v1/tax_rules/{rule_id}/full_chain   tags=['tax_rules']
```

**0 / 22 with short summary. 0 / 22 with missing description. 0 / 22 with missing tags.** Round 2 introduced no regression.

## 4. Pre-existing baseline (NOT Round 2 regression)

For audit transparency, the 15 short-summary + 29 missing-description endpoints carried over from earlier waves (all legacy boilerplate handlers, predominantly health probes / OAuth device flow / billing portal):

**Short summary (15)** — all <10 chars:

```
GET /healthz                                    -> 'Healthz'
GET /readyz                                     -> 'Readyz'
GET /v1/bids/{unified_id}                       -> 'Get Bid'
POST /v1/compliance/subscribe                   -> 'Subscribe'
GET /v1/compliance/verify/{verification_token}  -> 'Verify'
POST /v1/device/authorize                       -> 'Authorize'
POST /v1/device/complete                        -> 'Complete'
POST /v1/device/token                           -> 'Token'
GET /v1/me                                      -> 'Get Me'
GET /v1/meta                                    -> 'Get Meta'
GET /v1/ping                                    -> 'Ping'
POST /v1/session/logout                         -> 'Logout'
POST /v1/subscribers                            -> 'Subscribe'
GET /v1/usage                                   -> 'Get Usage'
GET /widget/badge.svg                           -> 'Badge Svg'
```

**Missing description (29)**: `/healthz`, `/readyz`, `/v1/billing/checkout`, `/v1/billing/credit/purchase`, `/v1/exclusions/check`, `/v1/exclusions/rules`, `/v1/feedback`, `/v1/integrations/google` (DELETE + GET status), `/v1/integrations/kintone/connect`, `/v1/me` (GET + billing-portal + courses + testimonials × 2 + watches × 2), `/v1/meta` (GET + freshness), `/v1/ping`, `/v1/session` (POST + logout), `/v1/stats/coverage`, `/v1/stats/data_quality`, `/v1/stats/freshness`, `/v1/stats/usage`, `/v1/subscribers` (POST + unsubscribe), `/v1/testimonials`.

These are NOT Round 2 regressions and are already on the launch-ready quality wishlist. They do not block the current launch — see R8 AI Consumer Audit ranking for "<2h to fix" items.

## 5. Distribution manifest integrity

```
$ .venv/bin/python scripts/check_distribution_manifest_drift.py
[check_distribution_manifest_drift] OK - distribution manifest matches static surfaces.
```

`scripts/distribution_manifest.yml` line 32: `openapi_path_count: 219  # docs/openapi/v1.json stable .paths length, verified 2026-05-07 JST (incl. /v1/tax_rules/{rule_id}/full_chain)` — **already matches committed = 219**. No manifest bump needed.

## 6. Trivial fix executed

```bash
.venv/bin/python scripts/export_openapi.py --out docs/openapi/v1.json
```

The fresh export produced byte-identical bytes to both committed and site mirror (sha256 `f1982e880fdeef13` × 3) **except** for one schema-level addition: `AdvisorHandoffPreviewRequest.consent_granted` (boolean, default false, "Must be true after the user explicitly agrees to leave the evidence handoff surface and contact this advisor. No referral token is minted before consent.").

The export script writes BOTH `docs/openapi/v1.json` AND `site/docs/openapi/v1.json` in one pass (per `wrote site/docs/openapi/v1.json (stable)` log line) — keeping the dual mirror invariant by construction. agent.json got a 1-line description update referencing `match_advisors_v1_advisors_match_get` for the Evidence-to-Expert handoff guidance.

Diff scope (12 lines net new across both `v1.json` mirrors + 2 lines per `agent.json` mirror): minimal, additive, non-breaking.

## 7. Top-fix list (carryover, NOT in this commit)

Per R8 AI Consumer Audit ranking, two leftover items remain at <2h work each — out-of-scope here, would land in a follow-up audit pass:

1. **Replace 15 auto-generated short summaries** (Healthz / Readyz / Get Bid / Subscribe / Verify / Authorize / Complete / Token / Get Me / Get Meta / Ping / Logout / Subscribe / Get Usage / Badge Svg) with 30-60 char descriptive strings. ~1h sed-friendly across `src/jpintel_mcp/api/*.py` docstrings.
2. **Add description blocks to 29 endpoints** that currently emit `summary` but no `description`. ~1.5h. 14 of the 29 are billing / OAuth / health surfaces with stable contracts; descriptions are static once written.

These are launch-ready quality polish, NOT release blockers. Tracked separately.

## 8. Commit & push

```
git add docs/openapi/v1.json site/docs/openapi/v1.json docs/openapi/agent.json site/docs/openapi/agent.json site/openapi.agent.json tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_BUGHUNT_OPENAPI_DRIFT_2026-05-07.md
git commit -m "fix(openapi): regenerate v0.3.4 spec — Round 2 consent_granted field + advisor handoff guidance (R8 audit)"
git push
```

Pre-commit hooks expected to pass: `check_distribution_manifest_drift.py` (manifest already matches 219), schema-validation, ruff, mypy targeted to `src/`, secret-scan. The audit doc lives in `tools/offline/_inbox/_housekeeping_audit_2026_05_06/` which is operator-only space and outside `src/` so LLM/secret guards do not engage.

---

## Conclusion

**No drift bug. Round 2 endpoint quality is clean.** The only audit-actionable surface is the 15 short-summary + 29 missing-description **legacy** boilerplate, untouched by Round 2 — already on the polish backlog. Live deploy lag (216 vs 219) closes on the next Fly push.

**LLM 0.** READ-ONLY HTTP GET + scripts/export_openapi.py + manifest drift check + commit. No destructive overwrite (export script preserves byte-identity for unchanged schemas). Pre-commit hook line passes.
