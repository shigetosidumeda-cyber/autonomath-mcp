# TODO / Stub / Placeholder Audit — 2026-05-11

Comprehensive scan of incomplete code markers across the jpcite repo.

**Scope**: `src/jpintel_mcp/`, `scripts/`, `tests/`, `site/`, `docs/`,
`.github/workflows/`, `sdk/` (Python + TypeScript + plugins).

**Method**: `rg` for `TODO`, `FIXME`, `XXX`, `HACK`, `NotImplementedError`,
`HTTP_501_NOT_IMPLEMENTED`, `not_implemented`, `@pytest.mark.skip`,
`pytest.skip()`, `scaffolding`, `coming soon`, `準備中`, `T+90d` / `T+200d`
schedule sentinels, `placeholder`, `(β)`, `// TODO`, `<!-- TODO -->`,
`# TODO` in YAML.

**Exclusions from false-positives**:
- `XXX` patterns that are example tokens (`cus_XXX`, `prog_XXX`, `ch_3PXXX`,
  `S100XXXX`, `9XXX`, `aXXXX.pdf`, etc.) used as redaction placeholders in
  customer-support templates / docstrings / regex examples.
- `準備中` strings inside ingested government source titles
  (`site/programs/*.html`, `site/rss/prefecture/*.xml` — these are upstream
  ministry / 都道府県 program names, not our incompleteness).
- `XXXX.pdf` glob filename patterns in NTA / 国交省 PDF-walk regexes
  (`scripts/ingest/ingest_enforcement_*.py`).
- `placeholders = ",".join("?" for _ in ...)` SQL parameterization
  (Python sqlite3 idiom, not a marker).
- `Beta(α, β)` mathematical notation in `analytics/bayesian.py`.
- `_archive/` directories (dead code retained for historical reference).
- `site/docs/assets/javascripts/bundle.*.min.js` (mkdocs-material vendored
  third-party bundle).

---

## 1. Summary

| Category                                  | Hit count |
|-------------------------------------------|-----------|
| Production stubs returning sentinel envelope (T+90d / T+200d) | 11 funcs |
| REST `HTTP_501_NOT_IMPLEMENTED` endpoints                     | 2 routes |
| Active source TODO comments (src/)                            | 5         |
| Active source TODO comments (scripts/)                        | 21        |
| Test TODO comments                                             | 4         |
| SDK / pyproject TODO (org-claim rename)                        | 3         |
| GHA workflow TODO (rebrand)                                    | 2         |
| `@pytest.mark.skip` (hard-disabled tests)                      | 3         |
| `pytest.skip()` runtime gates (env / data / build skip)        | ~180      |
| Self-improve loops marked "scaffolding only"                   | 9 loops   |
| i18n English V4 scaffolding module                              | 1 pkg     |
| Operator playbook `TODO owner-fills` (CS contact list)         | 7         |
| Honest "scaffolding" / "WIP" markers                            | 5         |
| Reasoning broken-tool gates (default-off until fix)            | 3 tools   |
| **GRAND TOTAL — meaningful markers**                            | **~250**  |

### High-priority hits: **9**

Surfaces visible in production (`/v1/*` API / MCP tools / public site / CS runbook):

1. `src/jpintel_mcp/api/legal.py:64` — `/v1/legal/{law}/{article}` returns 501 (ETA 2026-05-27).
2. `src/jpintel_mcp/api/accounting.py:76` — `/v1/accounting/validate_invoice` returns 501 (ETA 2026-06-10).
3. `src/jpintel_mcp/mcp/healthcare_tools/tools.py` — 6 MCP tools return `{"status": "not_implemented_until_T+90d"}` sentinel until 2026-08-04.
4. `src/jpintel_mcp/mcp/real_estate_tools/tools.py` — 5 MCP tools return `{"status": "not_implemented_until_T+200d"}` sentinel until 2026-11-22.
5. `src/jpintel_mcp/mcp/autonomath_tools/snapshot_tool.py:83` — `query_at_snapshot` broken, gated off pending migration 067.
6. `src/jpintel_mcp/mcp/autonomath_tools/tools.py:3030` — `intent_of` broken, gated off pending reasoning package.
7. `src/jpintel_mcp/mcp/autonomath_tools/tools.py:3156` — `reason_answer` broken, gated off (same root cause as #6).
8. `docs/_internal/operators_playbook.md` — 7+ `TODO owner-fills` for CS contact info (lawyer / 税理士 / Sentry URL / etc.); production CS runbook depends on these.
9. `.github/workflows/tls-check.yml:26` + `nightly-backup.yml:21` — rebrand TODO (final production hostname / Fly app name still references `jpintel-mcp`).

### Most-deferred top-5 files

1. **`scripts/ingest_tier.py`** — 11 distinct `TODO(owner=@shigeto)` markers; the entire fetcher harness is a skeleton with per-authority stubs (jgrants / chusho.meti / maff / 厚労省 / JFC / 47 都道府県 / ~500 muni netlocs / INSERT mirroring / UPDATE+FTS).
2. **`src/jpintel_mcp/mcp/healthcare_tools/tools.py`** — 6 tools × `not_implemented_until_T+90d` sentinel envelope; real SQL lands W4 (2026-08-04). Each tool has a docstring `**実装予定: T+90d (2026-08-04)、現在は scaffolding。**` and an inline T+90d FTS5 plan comment.
3. **`src/jpintel_mcp/mcp/real_estate_tools/tools.py`** — 5 tools × `not_implemented_until_T+200d` sentinel envelope; real SQL lands T+200d (2026-11-22).
4. **`src/jpintel_mcp/self_improve/`** — 9 loop modules (`loop_a..j_*`), all marked `Method (T+30d, ...)` / `Implementation status: scaffolding only (T+30d for real ML wiring)`.
5. **`docs/_internal/operators_playbook.md`** — 7+ `TODO owner-fills` (lawyer / 税理士 / 司法書士 / 弁理士 / Sentry org URL / UptimeRobot dashboard URL / 広報 contact); Appendix B explicitly tracks "未実装".

---

## 2. Production stubs (HIGH priority)

### 2.1 REST endpoints returning HTTP 501

| File:line                                              | Path                                       | ETA         |
|---------------------------------------------------------|--------------------------------------------|-------------|
| `src/jpintel_mcp/api/legal.py:64`                       | `GET /v1/legal/{law}/{article}`            | 2026-05-27  |
| `src/jpintel_mcp/api/accounting.py:76`                  | `POST /v1/accounting/validate_invoice`     | 2026-06-10  |

Both routes raise `HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)`
with `detail.eta` set; OpenAPI schema correctly declares the 501 response.

### 2.2 MCP tools returning `not_implemented` sentinel envelope

**Healthcare V3 (6 tools)** — `src/jpintel_mcp/mcp/healthcare_tools/tools.py`:

- `tools.py:42` defines `_NOT_IMPLEMENTED_BODY = {"status": "not_implemented_until_T+90d", "results": []}`.
- 6 tool functions return this envelope. Each carries inline docstring
  `**実装予定: T+90d (2026-08-04)、現在は scaffolding。**` and a T+90d FTS5 SQL plan comment.
- Gated by `AUTONOMATH_HEALTHCARE_ENABLED` (default off per launch CLI plan).

**Real-estate V5 (5 tools)** — `src/jpintel_mcp/mcp/real_estate_tools/tools.py`:

- `tools.py:32` defines `_NOT_IMPLEMENTED_STATUS = "not_implemented_until_T+200d"`.
- 5 tool functions return the envelope at lines 50 / 127 / 200 / 343 / 417.
- Real query implementations land **right before** T+200d (2026-11-22).
- Gated by `AUTONOMATH_REAL_ESTATE_ENABLED` (default off).

**Broken-tool gates (3 tools, default-off pending fix)**:

- `src/jpintel_mcp/mcp/autonomath_tools/snapshot_tool.py:83`
  `# TODO(2026-04-29): query_at_snapshot is currently broken — migration 067` (missing).
  Gate: `AUTONOMATH_SNAPSHOT_ENABLED`.
- `src/jpintel_mcp/mcp/autonomath_tools/tools.py:3030`
  `# TODO(2026-04-29): intent_of is currently broken — _reasoning_import()` (missing).
  Gate: `AUTONOMATH_REASONING_ENABLED`.
- `src/jpintel_mcp/mcp/autonomath_tools/tools.py:3156`
  `# TODO(2026-04-29): reason_answer is currently broken — same root cause` (as #2).
  Gate: `AUTONOMATH_REASONING_ENABLED`.

### 2.3 ETL / cron job returning `not_implemented`

- `scripts/etl/plan_jgrants_fact_upsert.py:1066` — emits
  `{"status": "not_implemented", ...}` for unhandled fact-type branch.
- `scripts/acceptance/run.js:16` — acceptance harness defaults
  `{ evidence: null, error: 'not_implemented_yet' }` when a criterion has no
  evidence collector wired yet.

---

## 3. Active TODO / FIXME / HACK comments

### 3.1 `src/jpintel_mcp/` — 5 hits

| File:line                                                  | Priority | Context |
|-------------------------------------------------------------|----------|---------|
| `mcp/autonomath_tools/snapshot_tool.py:83`                  | high     | `query_at_snapshot` broken, gated off |
| `mcp/autonomath_tools/tools.py:3030`                        | high     | `intent_of` broken, gated off |
| `mcp/autonomath_tools/tools.py:3156`                        | high     | `reason_answer` broken, gated off |
| `ingest/_gbiz_rate_limiter.py:55`                           | medium   | `# TODO: add 'ratelimit>=2.2.1,<3.0' to pyproject.toml core deps per` |
| `ingest/_gbiz_rate_limiter.py:65`                           | medium   | `# TODO: add 'diskcache>=5.6,<6.0' to pyproject.toml core deps per` |
| `email/templates/README.md:11`                              | low      | `check (TODO, post-launch) could diff them. For now the alignment is` |

### 3.2 `scripts/` — 21 hits

| File:line                                                  | Priority | Context |
|-------------------------------------------------------------|----------|---------|
| `ingest_tier.py:284`                                       | medium   | `# TODO(owner=@shigeto): implement via jgrants OpenAPI (digital.go.jp)` |
| `ingest_tier.py:292`                                       | medium   | `# TODO(owner=@shigeto): HTML walk of www.chusho.meti.go.jp/koukai.` |
| `ingest_tier.py:298`                                       | medium   | `# TODO(owner=@shigeto): weekly walk of www.maff.go.jp. 800+ rows.` |
| `ingest_tier.py:304`                                       | medium   | `# TODO(owner=@shigeto): 雇用調整助成金系 index walk.` |
| `ingest_tier.py:309`                                       | medium   | `# TODO(owner=@shigeto): JFC site search shortcut already proven` |
| `ingest_tier.py:316`                                       | medium   | `# TODO(owner=@shigeto): walk the 47 *.pref.*.lg.jp / *.pref.*.jp roots` |
| `ingest_tier.py:323`                                       | medium   | `# TODO(owner=@shigeto): pick ~25% of the ~500 muni netlocs per slot.` |
| `ingest_tier.py:382-392`                                   | medium   | full INSERT + UPDATE+FTS row rebuild are stubs |
| `ingest/ingest_court_decisions.py:51, 58, 336, 366, 543, 1187` | medium | 6 TODOs (out-of-scope reconciliation, override heuristic, pdfplumber extras, form field types, PENDING law_name backfill) |
| `ingest/ingest_invoice_registrants.py:725, 760`             | medium   | `TODO(verify): confirm root/element names against the real download.` |
| `ingest/ingest_bids_geps.py:136, 156`                      | medium   | 落札日 label variance, 調達ポータル classification code |
| `ingest/ingest_laws.py:217, 442, 455`                      | medium   | partial-metadata fallback, pagination shape confirm |
| `generate_program_pages.py:840`                            | low      | `# TODO populate when LinkedIn / GitHub / X (Twitter) / Crunchbase` (sameAs JSON-LD) |
| `generate_geo_citation_pages.py:3747`                      | low      | same sameAs TODO |
| `generate_prefecture_pages.py:452`                         | low      | same sameAs TODO |
| `generate_industry_program_pages.py:934`                   | low      | same sameAs TODO |
| `migrations/089_audit_seal_table.sql:57`                    | low      | `TODO: scripts/cron/audit_seal_purge.py` — purge cron not yet implemented |
| `seed_advisors.py:95`                                      | low      | structured stubs marked with TODO for advisor seed batch |

### 3.3 `tests/` — 4 hits

| File:line                                                  | Priority | Context |
|-------------------------------------------------------------|----------|---------|
| `test_prescreen.py:48`                                     | low      | `(TODO: tighten when seed pinned)` — surface OR-instead-of-AND gate |
| `eval/tier_a_seed.yaml:78`                                 | low      | `TODO(user manual curate, P2.3.2): TA003-TA004, TA007-TA029 = 25 more.` |
| `eval/tier_c_adversarial.yaml:37`                          | low      | `TODO(user manual curate, P2.3.2): TC_M003 .. TC_M030 (28 more).` |
| `eval/tier_b_template.py:85`                               | low      | `── Stubs (TODO: P2.3.x implementer wires SQL + tool args) ──` |

### 3.4 `sdk/` + `pyproject.toml` — 3 hits

| File:line                                                  | Priority | Context |
|-------------------------------------------------------------|----------|---------|
| `sdk/python/pyproject.toml:33`                              | low      | `# TODO(org-claim): switch back to github.com/AutonoMath/autonomath-mcp once the AutonoMath GitHub org is claimed.` |
| `sdk/starter/README.md:7`                                   | low      | starter-repo URL rename pending org claim |
| `sdk/starter/README.md:100`                                 | low      | starter-repo issues URL rename pending org claim |

### 3.5 `.github/workflows/` — 2 hits

| File:line                                                  | Priority | Context |
|-------------------------------------------------------------|----------|---------|
| `tls-check.yml:26`                                          | high     | `# TODO(rebrand): replace with final production hostname once the` rebrand settles |
| `nightly-backup.yml:21`                                     | high     | `# TODO (operator — manual Fly.io steps required if the Fly app is still named jpintel-mcp)` |

---

## 4. Disabled tests (`@pytest.mark.skip`)

Three test files carry a hard `@pytest.mark.skip` at module / function level
(beyond the ~180 conditional `pytest.skip()` data-presence gates):

| File:line                                                  | Priority | Reason |
|-------------------------------------------------------------|----------|--------|
| `tests/test_revoke_cascade.py:189`                          | medium   | "billing-rewire blocker (R8 round 3, 2026-05-07): `billing.keys.revoke_child_by_id` does NOT spawn the daemon notify thread the test expects (SubscriptionItem.modify ...)" |
| `tests/test_redirect_zeimu_kaikei.py:173`                   | low      | "Live HTTP probe — opt-in only. Requires the operator to have applied `cloudflare-rules.yaml` to the zeimu-kaikei.ai zone." |
| `tests/test_offline_inbox_workflow.py:14`                   | medium   | "data-fix gate (R8 round 3, 2026-05-07): the 598-row source-profile JSONL backlog at `tools/offline/_inbox/public_source_foundation/` fails Pydantic schema validation on rows missing required fields." |

Conditional `pytest.skip(...)` runtime gates (~180 occurrences across
`tests/`) are intentional and expected — they guard against missing optional
dependencies (`bs4`, `WeasyPrint`, `pykakasi`, `icalendar`, `docx`,
`scipy`), missing data fixtures (autonomath.db unmounted in CI, empty
seed tables), and prod-only invariants. Not flagged as defects.

---

## 5. Scaffolding-only modules (T+30d / T+90d / T+200d)

### 5.1 Self-improve loops — 9 modules under `src/jpintel_mcp/self_improve/`

All carry `Method (T+30d, ...)` docstring and currently emit candidate rows
without ML wiring:

- `loop_a_hallucination_guard.py` — DBSCAN-on-feedback wiring lands T+30d once `query_log_v2` has enough rows; rule-based for now.
- `loop_b_testimonial_seo.py` — plain rules-based, NO LLM rewrite.
- `loop_c_personalized_cache.py` — T+30d.
- `loop_d_forecast_accuracy.py` — T+30d.
- `loop_e_alias_expansion.py` — plain rules-based; redacted-log feeder lands T+30d.
- `loop_f_channel_roi.py` — plain rules-based, NO LLM.
- `loop_g_invariant_expansion.py` — plain SQL rules-based.
- `loop_h_cache_warming.py` — plain SQL + internal compute.
- `loop_j_gold_expansion.py` — post-launch orchestrator integration pending.

`__init__.py:28`: `Implementation status: scaffolding only (T+30d for real ML wiring).`

### 5.2 English V4 (i18n) — `src/jpintel_mcp/i18n/__init__.py`

`P6-E (English V4) scaffolding — landed 2026-04-25 ahead of the T+150d ...`
Catalog scope is currently small; English query layer expands later.

### 5.3 MCP tool scaffolding (counted in §2.2 above)

- Healthcare V3 — `mcp/healthcare_tools/` (T+90d).
- Real estate V5 — `mcp/real_estate_tools/` (T+200d).

---

## 6. `XXX` redaction placeholders (CS / docs templates) — informational

Pattern `XXX` / `XXXX` appears 80+ times across CS templates / docs / sample
SQL — these are intentional redaction tokens (`cus_XXXX`, `ch_3PXXXX`,
`prog_XXX`, `evt_XXXXXXXX`, `ratecut_XXX`, etc.) used to indicate where the
operator fills in a real ID. Not defects, but worth noting:

- `docs/_internal/cs_templates.md` — ~25 redaction tokens across customer-support reply templates.
- `docs/_internal/operators_playbook.md` — ~12 `cus_XXXX` examples + 7 `TODO owner-fills` (real CS contacts pending — see §1 high-priority #8).
- `docs/_internal/monitoring.md`, `stripe_webhook_rotation_runbook.md`,
  `breach_notification_sop.md`, `slo_log.md` — additional redaction tokens.
- `scripts/url_integrity_scan.py:77` — `PLACEHOLDER_TOKENS = ("TODO", "FIXME", "XXXX", "...", "…")` is the **detector** for placeholder leaks in `source_url` strings (not a leak itself; this is the guard).

These contribute to total token counts but are not work items.

---

## 7. `準備中` markers — informational

Three places use `準備中` in non-ingested code/content:

1. `src/jpintel_mcp/mcp/autonomath_tools/tools.py:3355` — sanitizer rewrites `<<<precompute gap: ...>>>` to `(集計準備中)` when fact missing. Intentional fail-safe.
2. `src/jpintel_mcp/mcp/server.py:353` — "入札データは本格ロード post-launch です (schema ready, 0 rows — GEPS/自治体 bulk 準備中)" — honest disclosure string for bids tools.
3. `site/notifications.html:228` — `<p class="price">準備中</p>` — public site declares LINE notification pricing pending; consistent with `src/jpintel_mcp/line/config.py:63` `back to a "coming soon" note so we don't ship a dead link.`

(Many `準備中` hits in `site/programs/*.html`, `site/audiences/*/index.html`,
`site/rss/prefecture/*.xml` are ingested government program names — upstream
ministry wording, not our incompleteness.)

---

## 8. Beta-quality public surface

| File:line                                                  | Note |
|-------------------------------------------------------------|------|
| `site/calculator/index.html:16` / `:223` / `:226`           | `ROI 試算 (β)` — calculator page explicitly tagged beta in `<title>`, breadcrumb, and `<h1>`. Honest disclosure. |

---

## 9. Operator playbook outstanding fills

`docs/_internal/operators_playbook.md` — Appendix B "TODO (未実装)" tracks
the inventory. Notable items:

- §8 contact list: lawyer / 税理士 / 司法書士 / 弁理士 phone+email (`TODO owner-fills`).
- Stripe Support JP phone (`TODO owner-fills 最終電話番号`).
- Sentry org URL + UptimeRobot dashboard URL (`TODO owner-fills`).
- 広報 contact for media inquiries (`TODO owner-fills`).
- `scripts/revoke_key.sh` does not yet exist — inline SQL procedure documented as fallback (TODO owner=umeda).
- Admin UI revoke endpoint not confirmed (`src/jpintel_mcp/api/admin.py` not yet verified — `TODO: admin UI 経由化`).

These are high-priority because they appear in the CS operations runbook
that the operator runs against in production.

---

## 10. Launch compliance checklist

`docs/_internal/launch_compliance_checklist.md` carries explicit launch-gate TODOs:

- L96 `TODO by 2026-05-01` — bank verification / identity / T-号 申請 / webhook endpoint / Radar baseline / `[要確定]` tos.html / lawyer 1h review.
- L97 `TODO by 2026-05-05` — Stripe CLI test / PDF sample / MX/SPF/DKIM/DMARC / `tls-check.yml` DOMAIN replacement / kill-switch dry-run.

Both lists pre-date the brand rename. Per memory `project_jpcite_2026_05_07_state.md`,
the production deploy landed on 2026-05-07 b1de8b2; many items on the
launch compliance list are stale but the file itself retains them as
historical-state markers — `# TODO by 2026-05-01` strings remain
literally present in the file.

---

## 11. Audit hygiene note (pre-existing)

`docs/_internal/W28_DATA_QUALITY_DEEP_AUDIT.md:185-186` recorded a prior
placeholder scan with `TODO|FIXME|placeholder|PLACEHOLDER: **0**`. That
scan was scoped to data-row text, not source code; this 2026-05-11 audit
is the first full-tree source-code scan and captures source comments,
test markers, and scaffolding modules that the data-row scan
intentionally excluded.

---

## 12. Stretch items observed but not work-tracked

- `src/jpintel_mcp/api/main.py:946` — regex rewrites the string `post-launch monthly bulk refresh` to `scheduled source refresh` in user-visible copy; the regex is a hygiene guard, not an incomplete code path.
- `src/jpintel_mcp/email/postmark.py:20` — `password-reset` template is a "placeholder for the future passwordless dashboard"; postmark.py routing already accepts the template name but no caller currently emits it.
- `src/jpintel_mcp/api/meta.py:216` — "deploy points the API at an empty placeholder DB"; this is the **detector** for misconfigured deploy targets, not a leak.
- `src/jpintel_mcp/db/session.py:21+41+60+94` — autonomath.db's `programs` table is `intentionally an empty placeholder` so guarded reads fail hard; design-by-contract, not a TODO.
- `src/jpintel_mcp/mcp/autonomath_tools/time_machine_tools.py:27` — references "broken ETL pass placeholder ¥500K/¥2M" am_amount_condition rows; CLAUDE.md tracks this as a known data-quality re-validation item.

---

**Audit end.** Path: `/Users/shigetoumeda/jpcite/docs/audit/todo_stub_audit_2026_05_11.md`.
