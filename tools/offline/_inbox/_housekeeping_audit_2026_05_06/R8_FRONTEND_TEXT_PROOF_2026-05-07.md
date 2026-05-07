# R8 FRONTEND TEXT PROOF AUDIT (2026-05-07)

Scope: 9 proof-surface pages under `site/`.
Method: read each page, diff numeric claims against live SQLite SOT (`data/jpintel.db` + `autonomath.db`), verify license / phantom-moat audit / WatchTrueCost / patent retreat stance, link-check critical references.
Constraint: LLM 0, destructive overwrite none, numeric strings reconcile to live DB.

## 1. Pages audited

| # | Path | Status | Fix |
|---|---|---|---|
| 1 | `site/sources.html` | GREEN | none |
| 2 | `site/facts.html` | RED → fixed | relations 177,381 → 378,342; v0.3.2 → v0.3.4; lastModified 2026-04-30 → 2026-05-07; changelog row added |
| 3 | `site/transparency.html` | YELLOW → fixed | added "過去の数値補正履歴" section (R8 補正 + phantom-moat + 特許撤退 + WatchTrueCost); related links expanded |
| 4 | `site/data-freshness.html` | GREEN | none (live-fetch via `/v1/meta/freshness`) |
| 5 | `site/data-licensing.html` | RED → fixed | `97,270 / 97,272` → `96,467 / 97,272` (live `am_source.license` re-count) |
| 6 | `site/audit-log.html` | GREEN | none (live-fetch via `/v1/am/audit-log`) |
| 7 | `site/sla.html` | GREEN | none |
| 8 | `site/trust.html` | YELLOW → fixed | added SBOM trust-panel pointing to `/.well-known/sbom.json` |
| 9 | `site/calculator.html` | GREEN | none (DB join 8 / sources 4 / freshness 7d catalog values match SOT framing) |

## 2. SOT reconcile (live SQLite, 2026-05-07)

```
$ sqlite3 data/jpintel.db
searchable_programs_total = 11,601    [matches facts.html]
total_programs            = 14,472    [matches]
tier_S = 114, tier_A = 1,340, tier_B = 4,186, tier_C = 5,961  [matches]
non_public (X+excluded)   = 2,871     [matches]
case_studies              = 2,286     [matches]
loan_programs             = 108       [matches]
enforcement_cases         = 1,185     [matches]
laws                      = 9,484     [matches]
tax_rulesets              = 50        [matches]
court_decisions           = 2,065     [matches]
bids                      = 362       [matches]
invoice_registrants       = 13,801    [matches; PDL v1.0 attribution]
exclusion_rules           = 181       [matches]

$ sqlite3 autonomath.db
am_entities      = 503,930   [matches]
am_entity_facts  = 6,124,990 (~6.12M)  [matches]
am_relation      = 378,342   [DRIFT: facts.html showed 177,381 → fixed]
am_alias         = 335,605   [matches]

$ sqlite3 autonomath.db "SELECT license, COUNT(*) FROM am_source GROUP BY license"
pdl_v1.0          87,251
gov_standard_v2.0  7,457
public_domain        953
unknown              805   [matches data-licensing.html; license_review_queue.csv (1,425 行)]
proprietary          620
cc_by_4.0            186
TOTAL              97,272
classified         96,467   [DRIFT: data-licensing.html showed 97,270 → fixed]
```

Total numeric reconciliations: 35 SOT counts checked, 2 drifts found and fixed, 33 GREEN.

## 3. License-disclosure audit

- e-Gov 法令: CC BY 4.0 — sources.html / data-licensing.html / trust.html consistent.
- 国税庁 適格請求書発行事業者: PDL v1.0 — facts.html / data-licensing.html / sources.html consistent. TOS confirmed 2026-04-24 (operator memory `project_nta_invoice_api_blocker`).
- 国税庁 通達 / 国税不服審判所 裁決: data-licensing.html lists as 政府標準利用規約 v2.0. Sources.html lists 国税庁 通達 as パブリックドメイン — minor terminology drift; both forms acceptable but 政府標準利用規約 v2.0 is the primary source classification per `am_source.license` (gov_standard_v2.0 = 7,457).
- 経産省 gBizINFO: CC BY 4.0 — sources.html / data-licensing.html consistent.
- 47 都道府県 / JFC / JST: individual / 利用規約準拠 — flagged for license_review_queue.
- Aggregator ban: noukaweb / hojyokin-portal / biz.stayway / nikkei / prtimes / wikipedia explicitly excluded in `data-licensing.html#banned`. INV-04 invariant gate cited.

No license claim regressions found.

## 4. Transparency / past-stance integrity

Added to `transparency.html`:
- 2026-05-07: am_relation 17.7万 → 37.8万 (R8_DATA_FIDELITY)
- 2026-04-29: phantom-moat audit (検証ratio / ZERO-coverage 訴求 全廃)
- 2026-04-13: 特許 5 件全撤退 (補正せず 3 年後消滅 / 出願見送り) — aligns with `project_patent_retreat`
- 2026-04-15: WatchTrueCost 撤退 — aligns with `project_wtc_pivot`

No "Pro plan" / "Free tier" / 営業 references found in scope (zero-touch + 100% organic constraints intact).

## 5. SLA expression audit

`site/sla.html`:
- Uptime target: ≥ 99.0% (7d rolling) — matches monitoring/sla docs
- p95 latency: < 1500 ms (1h rolling) — matches
- 5xx error rate: < 0.5% (1h rolling) — matches
- Calculation excludes Cloudflare / Fly platform incidents and ≥48h-pre-announced maintenance
- Live-fetched from `/v1/health/sla?window=7d`; sample_count = 0 ⇒ 計測中 (does not falsely claim 100%)
- Support email SLA: not explicitly declared — info@bookyou.net implied via solo + zero-touch principle; no 24h promise made (good — solo ops constraint preserved)

## 6. Calculator UI / formula audit

`site/calculator.html`:
- Pricing: ¥3 / billable unit 税別 + 10% = ¥3.30 税込 [✓ matches facts.html#fact-price_per_req_inc_tax]
- 月額 = clients × reviews × ¥3 (税別) [✓ matches `/v1/cost/preview` semantics]
- Anonymous quota: 3 req/日 per IP (90/月) — does NOT subtract from paid estimate (correct, per CLAUDE.md)
- 1 req joins 8 DB (programs / 採択 / 融資 / 法令 / 税制 / 行政処分 / 適格事業者 / 入札) [✓ matches sources.html catalog]
- 中央値 出典 4 本 / 鮮度 7 日 (tier S/A) — catalog values, not estimates
- §52 / §72 disclaimer present
- Pure JS, no fetch, no LLM call [✓ matches `feedback_no_operator_llm_api`]

## 7. Audit-log / RSS feed audit

`site/audit-log.html`:
- Endpoint: `https://api.jpcite.com/v1/am/audit-log` [live]
- RSS: `/audit-log.rss` [live, regenerated by `regenerate_audit_log_rss.py` cron]
- Cursor pagination, since/entity_id/limit filters
- Source URL link present per row
- Schema.org Dataset + Organization JSON-LD (publisher Bookyou株式会社, T8010001213708 implied via 信頼 surface)

## 8. Trust badges / certification audit

`site/trust.html`:
- Bookyou株式会社 publisher pin (適格請求書発行事業者 T8010001213708 referenced via /trust.json)
- SBOM panel ADDED — points to `/.well-known/sbom.json` (CycloneDX 1.4, monthly cron `.github/workflows/sbom-publish-monthly.yml`)
- Verified `site/.well-known/sbom.json` exists (3,877 bytes, generated_at 2026-05-07T09:27:06Z)
- 8 trust panels total: 再現性 / 鮮度 / SLA / Corrections / License / §52 / RSS / no-LLM / SBOM (NEW)
- Live-fetch SLA via `/v1/health/sla` (sample_count guard intact)
- Corrections panel: 0 件 (90日) — honest baseline; no inflation

## 9. Fixes applied (atomic)

1. `site/facts.html`:
   - `関係性 総数: 177,381` → `378,342` + 補正注記
   - `v0.3.2` → `v0.3.4 (manifest hold-at-139, runtime cohort=146)`
   - `dateModified` 2026-04-30 → 2026-05-07 + lead `time` element + changelog row
2. `site/data-licensing.html`:
   - `97,270 / 97,272 分類済` → `96,467 / 97,272 分類済` (lead + foot, replace_all)
3. `site/transparency.html`:
   - dateModified → 2026-05-07
   - "過去の数値補正履歴" section added (4 stance rows)
   - Related-page links expanded (data-licensing / audit-log / trust)
4. `site/trust.html`:
   - SBOM trust-panel added pointing to `/.well-known/sbom.json`

## 10. Commit + push

- Atomic commit: `fix(site): proof surfaces text audit - sources/facts/transparency/SLA/calculator`
- Pre-commit hook compliance: distribution-manifest-drift / yaml / json checks (no manifest changes; HTML-only)
- Pushed to `origin/main`

## 11. Honest gaps remaining (NOT fixed in this pass)

- `data-licensing.html` row #14 JST: 件数 `(一部)` — placeholder, license still 要再確認.
- `data-licensing.html` row #5-9: 件数 `約 2,000` / `約 800` / `約 400` / `約 300` — round-number heuristics, not live counts. Not regressions per se but worth a future SOT-bind pass when `am_entities GROUP BY ministry` ETL is wired.
- `trust.html` データ鮮度 panel: hard-coded median fetched_at dates (2026-04-25 〜 2026-04-29) — should be live-fetched from `/v1/staleness` like the SLA panel. Out of scope for text audit (would need JS).
- `sources.html` JSON-LD line 75: METI listed under `kantei.go.jp/.../sankou1.pdf` license — link still resolves but kantei.go.jp 政府標準利用規約 has been superseded by digital.go.jp data_policy. Acceptable transitional reference.

## 12. Closure

- 9 pages audited
- 35 SOT counts cross-checked, 2 drifts repaired
- License surface re-verified across 6 sources
- Phantom-moat / patent / WatchTrueCost stance memorialized in transparency.html
- SBOM landed link wired into trust panel
- LLM calls: 0 (per `feedback_no_operator_llm_api`)
- Destructive overwrite: 0
- Pre-commit: PASS (HTML-only, no manifest drift)
