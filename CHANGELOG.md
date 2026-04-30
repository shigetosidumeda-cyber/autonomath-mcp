# Changelog

All notable changes to **autonomath-mcp** are documented here.

Format: [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).
See [`docs/versioning.md`](docs/versioning.md) for what counts as breaking.

## [Unreleased]

### Changed

- **Brand rename — `税務会計AI` → `jpcite` (2026-04-30)** — primary
  user-facing brand renamed to **jpcite**; `税務会計AI` is retained as
  `alternateName` only. Apex/API domains migrated:
  `zeimu-kaikei.ai` → `jpcite.com`, `api.zeimu-kaikei.ai` →
  `api.jpcite.com`. The PyPI package name `autonomath-mcp` and the
  legacy import path `jpintel_mcp` are **unchanged** to preserve
  consumer compatibility. Historical CHANGELOG entries below intentionally
  retain the old URL strings as a migration trail; new entries
  going forward use the jpcite.com domains.

### Documentation

- **I1 — production-state numeric drift fix (2026-04-25)** — synced
  `CLAUDE.md`, `README.md`, `pyproject.toml`, `mcp-server.json`,
  `dxt/manifest.json`, `smithery.yaml` to the v15 production snapshot:
  programs `11,547 → 13,578`, autonomath `am_entities 416,375 →
  424,054`. Court decisions (2,065) + bids (362) lifted from "schema
  pre-built, post-launch" to live counts. Added a pre-V4 / post-V4
  numeric-versioning note in `CLAUDE.md` so the manifests can lag the
  in-repo state until the v0.3.0 bump CLI runs. V4 absorption details
  (migrations 046–049, +4 universal tools, post-V4 row growth) are
  documented in `CLAUDE.md` "V4 absorption" section by the absorption
  CLI; this CHANGELOG entry only covers the README / manifest sync.

### Added

- **D-series wave (2026-04-25)** — npm SDK distribution, gated cohort
  scaffolding, EN llms-full surface, infra hardening, SLA + Tokushoho
  copy. No MCP tool count change at launch (still 55); gated cohorts
  add +6 healthcare and +5 real-estate tools when env flags flip.
  - **D2 — npm SDK published**: `@autonomath/sdk@0.2.0` on npm
    (TypeScript / JavaScript), dual ESM + CJS, `.d.ts` bundled,
    `import` from `@autonomath/sdk` for REST and `@autonomath/sdk/mcp`
    for MCP. Zero runtime dependencies (platform `fetch`). Source at
    `sdk/typescript/`.
  - **D4 — Healthcare V3 cohort scaffolded** (T+90d 2026-08-04): +6
    MCP tools (`search_medical_institutions`, `get_medical_institution`,
    `search_care_subsidies`, `get_care_subsidy`,
    `eligible_care_for_profile`, `medical_compliance_pack`) gated on
    `HEALTHCARE_ENABLED=true`. Schema: migration 039
    (`medical_institutions` + `care_subsidies`).
  - **D5 — Real Estate V5 cohort scaffolded** (T+200d): +5 MCP tools
    (`search_real_estate_programs`, `get_real_estate_program`,
    `search_zoning_overlays`, `re_eligible_for_parcel`,
    `re_compliance_pack`) gated on `REAL_ESTATE_ENABLED=true`. Schema:
    migration 042 (`real_estate_programs` + `zoning_overlays`).
  - **D6 — `site/llms-full.en.txt`** new surface — EN-translated full
    spec for AI-agent discovery (companion to existing JA
    `llms-full.txt`, plus `llms.txt` / `llms.en.txt` short forms).
  - **D8 — Migration 045**: 18 new `pc_*` precompute tables added
    (industry-pref-program top-N, deadline calendar, combo pairs,
    industry adjacency, JSIC alias map, etc.). Brings pc_* count from
    33 → **51**. Read-only from API; populated by nightly cron.
  - **D9 — Rate-limit middleware + Cloudflare WAF**: token-bucket
    middleware in `src/jpintel_mcp/api/middleware/ratelimit.py` (per-IP
    + per-API-key buckets, JST monthly reset for anonymous, UTC daily
    for authenticated). Cloudflare WAF in front via
    `cloudflare-rules.yaml` (managed ruleset + custom rules for
    aggregator-style scraping). Adds no new REST paths; affects every
    request transparently.
  - **D10 — SLA 99.5% + Tokushoho**: SLA target raised from 99.0% to
    **99.5%** monthly uptime ([`docs/sla.md`](docs/sla.md));
    Tokushoho disclosure ([`site/tokushoho.html`](site/tokushoho.html))
    finalized for 特定商取引法 compliance at launch.
- **B/C-series wave (2026-04-25)** — pre-launch dashboard / alerts / stats /
  testimonials surface, customer-controlled cap, healthcare + real-estate
  schema scaffold, L4 cache + 14 pre-compute tables. No MCP tool count
  change (still 55); REST surface grew 17 → **30+** new `/v1/me/*` +
  `/v1/stats/*` + `/v1/testimonials` + `/v1/admin/testimonials/*` paths.
  - **Migrations applied** (`scripts/migrations/`):
    - `037_customer_self_cap.sql` — `api_keys.monthly_cap_yen` column
      (NULL = unlimited; non-null hard-stops billing at the cap, no
      Stripe usage record on rejection).
    - `038_alert_subscriptions.sql` — `alert_subscriptions` table for
      Tier 3 amendment alerts (filter_type ∈ tool/law_id/program_id/
      industry_jsic/all, min_severity ∈ critical/important/info,
      HTTPS-only webhook + optional email fallback).
    - `039_healthcare_schema.sql` — `medical_institutions` +
      `care_subsidies` (Healthcare V3 cohort prep, T+90d 2026-08-04).
    - `040_english_alias.sql` — DEFERRED (collection-CLI territory; not
      yet applied).
    - `041_testimonials.sql` — public testimonial collection +
      moderation queue (5 audience buckets: 税理士/行政書士/SMB/VC/Dev,
      `approved_at` flips NULL→ISO 8601 on admin approval).
    - `042_real_estate_schema.sql` — `real_estate_programs` +
      `zoning_overlays` (Real Estate V5 cohort prep, T+200d).
    - `043_l4_cache.sql` — `l4_query_cache` table (sha256-keyed, per-row
      TTL, LRU eviction via `last_hit_at`; populated organically + nightly
      Zipf seed). Empty at launch, target 60% hit rate at T+30d.
    - `044_precompute_tables.sql` — 14 new `pc_*` tables (industry/pref
      top-N, law⇄program adjacency, acceptance stats, combo pairs,
      seasonal calendar, JSIC aliases, authority adjacency, recent
      amendments, enforcement by industry, loan by collateral, cert by
      subject, starter-pack per audience). Read-only from API; nightly
      cron populates. Brings pc_* count from 19 → 33 (T+30d target).
  - **New REST endpoints** (`docs/openapi/v1.json`):
    - **Cap**: `POST /v1/me/cap` (set/clear customer-controlled monthly
      cap; ¥3/req unit price unchanged).
    - **Dashboard**: `GET /v1/me/dashboard`, `GET /v1/me/usage_by_tool`,
      `GET /v1/me/billing_history`, `GET /v1/me/tool_recommendation`.
    - **Alerts** (Tier 3 amendment subscriptions):
      `POST /v1/me/alerts/subscribe`,
      `GET /v1/me/alerts/subscriptions`,
      `DELETE /v1/me/alerts/subscriptions/{sub_id}`.
    - **Testimonials** (public submit + moderate):
      `POST /v1/me/testimonials`,
      `DELETE /v1/me/testimonials/{testimonial_id}`,
      `GET /v1/testimonials` (approved-only public list),
      `POST /v1/admin/testimonials/{id}/approve`,
      `POST /v1/admin/testimonials/{id}/unapprove`.
    - **Stats** (transparency surface):
      `GET /v1/stats/coverage`, `GET /v1/stats/freshness`,
      `GET /v1/stats/usage`. (Confidence endpoint deferred — not in this
      wave.)
  - **Aggregator cleanup** — programs `excluded=0 AND tier IN (S,A,B,C)`:
    11,559 → **11,547** (-12 net; aggregator/dead-link quarantine reset
    `tier='X'`). Total `programs` rows in DB unchanged at 12,753; the
    -12 is solely from `tier` reclassification.
  - **autonomath.db count refresh** (canonical doc-time snapshot
    aligned with task spec; live DB may be ahead due to concurrent
    ingest) — entities now **416,375** (+13,607 vs v0.2.0 baseline);
    facts ~**5.26M** (within rounding); aliases now **335,605**
    (+22,854 vs v0.2.0 baseline); `am_law_article` 0 → **28,048**;
    `am_enforcement_detail` 0 → **7,989**. Relations stable at 23,805.

- **`list_tax_sunset_alerts`** (new autonomath MCP tool): list tax
  incentives whose `am_tax_rule.effective_until` expires within N days
  (default 365). Tax-cliff alerting for 大綱-driven sunsets (年度末
  3/31 / 年末 12/31). Total MCP tool count: 54 → **55** (38 core + 17
  autonomath).

- **`subsidy_roadmap_3yr`** (new one-shot MCP tool): industry (JSIC) +
  prefecture + company_size + funding_purpose → 3-year (default 36-month)
  timeline of plausibly-applicable subsidy / loan / tax `application_window`
  entries, bucketed into JST fiscal-year quarters (Apr-Jun=Q1, Jul-Sep=Q2,
  Oct-Dec=Q3, Jan-Mar=Q4 of the prior FY). Returns `timeline` (sorted
  ascending by `opens_at`, `application_deadline` tiebreak) + `by_quarter_count`
  + `total_ceiling_yen` (sum over `max_amount_yen`). Past `from_date` is
  clamped to today JST with a hint; `cycle=annual` past `start_date` is
  projected forward year-by-year (Feb 29 → Feb 28 fallback) until it lies
  in the horizon; rolling/non-annual past windows are dropped. Empty result
  surfaces a nested `{error: {code, message, hint}}` envelope. Eliminates
  the 「いつ何を申請するか」planning round-trip.
- **`regulatory_prep_pack`** (new one-shot MCP tool): industry (JSIC) +
  prefecture (+ optional company_size) → applicable laws (current
  revision) + certifications (programs.program_kind LIKE 'certification%'
  fallback while a dedicated certifications table is pending) + tax
  rulesets (effective_until-aware, `include_expired` toggle) + 5 most
  recent same-industry enforcement cases. Eliminates the 4-5 round-trips
  (search_laws → programs(certification) → search_tax_rules →
  search_enforcement_cases) a user/agent makes to assemble the regulatory
  context for a new business / new prefecture. Empty all-sections result
  surfaces a nested `{error: {code, message, hint}}` envelope; partial
  emptiness adds a `hint` string instead of erroring.
- **`dd_profile_am`** (new one-shot MCP tool): 法人番号 → entity + adoptions +
  invoice registration + enforcement history, collapses a 5-call due-diligence
  chain into one. Honesty gates: invoice mirror delta-only flagged explicitly,
  `enforcement.found=False` does NOT claim "clean record".
- **`similar_cases`** (new MCP tool): case-study-led discovery. Given a
  `case_id` or a free-text `description`, returns 10 similar 採択事例 ranked by
  weighted Jaccard (industry ×2 + prefecture ×1 + shared `programs_used` ×3),
  each annotated with `supporting_programs` resolved from `case_studies.programs_used`
  names to actual `programs` rows. Empty seed → envelope `code=empty_input`.
- **Typo-detection gate** on prefecture input across 8 search tools
  (`search_programs`, `search_enforcement_cases`, `search_case_studies`,
  `prescreen_programs`, `upcoming_deadlines`, `subsidy_combo_finder`,
  `deadline_calendar`, `smb_starter_pack`). Unknown prefecture strings surface
  an `input_warnings` envelope instead of silently filtering on garbage (0 rows).
- **Empty-hit hints** on `list_exclusion_rules(program_id=...)` and
  `search_acceptance_stats_am`: structured `hint` with `filters_applied` +
  `suggestions` when a query matches nothing.
- **Katakana keyword expansion** (50+ pairs): `モノづくり`↔`ものづくり`,
  `DX`↔`デジタルトランスフォーメーション`, `インボイス`↔`適格請求書`, etc.
  Expands additively inside FTS `OR` so both forms now hit the same rows.
- **`tests/test_autonomath_tools.py`** (46 tests, covers all 16 autonomath
  tools against the real 7.3 GB DB — happy path + bad input per tool).

### Changed

- `PRAGMA synchronous=NORMAL` + `PRAGMA busy_timeout=5000` added to
  `jpintel.db` connection helper (matches `autonomath.db` tuning).
- Program count updated across docs/server.py to **11,547** (was the
  v0.1.0 baseline); laws **9,484** (was the early-launch baseline); tool
  total **55** (was 47 at v0.2.0 release): 38 core + 17 autonomath;
  includes 7 one-shot discovery tools: smb_starter_pack /
  subsidy_combo_finder / deadline_calendar / dd_profile_am /
  similar_cases / regulatory_prep_pack / subsidy_roadmap_3yr; and the
  autonomath sunset-alert tool list_tax_sunset_alerts).
- `get_program` / `batch_get_programs` bad-input contract: returns structured
  `{"error": {...}}` envelope instead of raising `ValueError` (MCP over
  JSON-RPC loses raise information to -32603 Internal Error).

### Fixed

- `search_acceptance_stats_am` WHERE clause bug: was filtering
  `record_kind='program'` against rows that are actually stored as
  `record_kind IN ('adoption','statistic')`. Tool silently returned
  total=0 for every query. Fixed; now returns real 採択統計 rows with
  applicants/accepted/acceptance_rate fields populated.
- Circular-import crash on `scripts/export_openapi.py` (and any
  consumer importing `jpintel_mcp.api.main`): `server.py` had a
  module-scope `from autonomath_tools.tools import …` that fired
  while `tools.py` was still mid-initialization on the
  api.main → api.autonomath → autonomath_tools → server.py path.
  Moved the import inside the `search_acceptance_stats` function
  body; both import paths now work.
- `__version__` in `src/jpintel_mcp/__init__.py` was pinned to
  `0.1.0` while `pyproject.toml` advertised `0.2.0`, so the FastAPI
  OpenAPI `info.version` field was leaking the stale value. Bumped.
- Prefecture typo gate added to `subsidy_roadmap_3yr` and
  `regulatory_prep_pack`: unknown values like `'Tokio'` / `'東京府'`
  now surface a structured `input_warnings` entry (matches the
  existing 8-tool BUG-2 pattern) instead of either silently
  filtering to 0 rows (`subsidy_roadmap_3yr` was) or silently
  dropping the filter without telling the caller
  (`regulatory_prep_pack` was). +2 tests, 531 passing.

## [0.3.1] — 2026-04-29 — Wave 30 disclaimer hardening + launch-blocker batch

### Added

- **Three new disclaimer settings** in `src/jpintel_mcp/config.py`: gates for sensitive-tool envelope hardening + anonymous quota warning body injection.
- **§52 disclaimer hardening** across **11 sensitive-tool branches** in `src/jpintel_mcp/mcp/autonomath_tools/envelope_wrapper.py` (`SENSITIVE_TOOLS` frozenset extended; tax surfaces — `search_tax_incentives`, `get_am_tax_rule`, `list_tax_sunset_alerts` — explicitly carry 税理士法 §52 fence; existing 7 sensitive tools tightened).
- **Tax surface §52 disclaimers** added to REST envelopes in `src/jpintel_mcp/api/tax_rulesets.py` and `src/jpintel_mcp/api/autonomath.py`.
- **Anonymous quota warning body injection** in `src/jpintel_mcp/api/middleware/anon_quota_header.py` (warns user before they hit the 50/month JST cap, not after).
- **4 broken-tool gates** wired in `snapshot_tool.py` + `tools.py`:
  `AUTONOMATH_SNAPSHOT_ENABLED` (`query_at_snapshot`, migration 067 missing),
  `AUTONOMATH_REASONING_ENABLED` (`intent_of` + `reason_answer`, package missing),
  `AUTONOMATH_GRAPH_ENABLED` (`related_programs`, `am_node` table missing).
  Flipping all 3 ON restores the 72-tool surface (broken tools still error until the underlying schema / package lands).

### Changed

- **Tool count surface 72 → 68 at default gates** (4 broken tools gated off pending fix; `mcp-server.json` `tool_count` updated; `dxt/manifest.json` `long_description` updated).
- **Brand rename** completed across user-facing manifest + description copy: jpintel internal package path retained (`src/jpintel_mcp/`), but every user-visible string now reads AutonoMath / Bookyou株式会社. Internal file paths intentionally untouched per CLAUDE.md "Never rename `src/jpintel_mcp/`" rule.
- **Homepage CRO + phantom-moat copy fix**: marketing copy realigned to honest counts (10,790 searchable / full table 13,578 incl. tier X quarantine; am_amount_condition 35,713 row count moved out of public-facing surfaces because 76% of rows are template-default values from a single broken ETL pass).
- `pyproject.toml` `[project.urls]` block — dead URL fix + Repository / Issues pointed at the live `shigetosidumeda-cyber/jpintel-mcp` repo until the AutonoMath GitHub org is claimed.
- `server.json` + `mcp-server.json` + `dxt/manifest.json` description URLs realigned with the live homepage `https://zeimu-kaikei.ai`.

### Fixed

- Stale `dist/` artifacts (`dist/autonomath_mcp-0.3.0-py3-none-any.whl` / sdist / `.mcpb` were built **before** the §52 disclaimer hardening + brand rename + quota header changes landed). Rebuilt at v0.3.1 — site/downloads/autonomath-mcp.mcpb now points at the v0.3.1 bundle.

### Notes

- v0.3.0 `dist/` artifacts are **retained** in-repo (not deleted) so any pinned downstream consumer can still install `autonomath-mcp==0.3.0`. The v0.3.1 artifacts are the publish target.
- `@autonomath/sdk` (npm) is on a **separate version track** (currently 0.3.2) per `feedback_no_priority_question` memory note; it is not bumped by this batch.
- Smithery pulls from the GitHub repo directly; this version bump only requires a git tag once the launch CLI advances.

## [0.3.0] - 2026-04-25 (Phase A absorption)

### Added

- +7 MCP tools: list_static_resources_am, get_static_resource_am, list_example_profiles_am, get_example_profile_am, render_36_kyotei_am, get_36_kyotei_metadata_am, deep_health_am
- +7 REST endpoints under /v1/am/* including health_router 分離 (AnonIpLimitDep bypass)
- 8 静的タクソノミ + 5 example profiles in data/autonomath_static/
- 4 utility modules (wareki, jp_money, jp_constants, saburoku_kyotei template)
- models/premium_response.py (PremiumResponse, ProvenanceBadge, AdoptionScore, AuditLogEntry)
- L 系列 fixes: P0-1 models shadow / P0-2 envelope wiring / P0-3 exclusion_rules dual-key / P0-4 strict_query / P0-6 get_meta dynamic / P0-7 request_id / P0-10 Tier=X
- migration 050 (Tier=X quarantine fix), 051 (exclusion_rules unified_id keys)
- target_db marker scheme for migrations
- response_model annotations 32 endpoints
- _error_envelope.py global error handler
- strict_query middleware (87% silent drop fix)
- charge.refunded webhook handler

### Changed

- Tool count: 55 → 66 (38 jpintel + 24 autonomath: 17 V1 + 4 V4 + 7 Phase A)
- autonomath.db: am_entities 416,375 → 503,930 / facts 6.12M / annotations 16,474 (V4 absorption)
- exclusion_rules: name-keyed → unified_id keyed (dual-key)

## [0.2.0] — 2026-04-25 — AutonoMath canonical DB landing

### Added

- **`autonomath.db`** companion SQLite file (7.3 GB, read-only): entity-fact
  EAV schema with **416,375 am_entities**, **5.26M am_entity_facts**,
  **23,805 am_relation** edges, **335,605 am_alias** rows, plus 14 am_*
  support tables (authority / region / tax_rule / subsidy_rule /
  application_round / loan_product / insurance_mutual / enforcement_detail /
  amendment_snapshot / industry_jsic / target_profile / peer_cache / law /
  entity_tag). FTS5 (trigram + unicode61) + sqlite-vec (6 tiered vector
  indexes). Separate file from `data/jpintel.db` — no ATTACH, no cross-DB
  JOIN per Option C strategy.
- **16 new MCP tools** (autonomath_tools subpackage):
  - tools.py (10): `search_tax_incentives`, `search_certifications`,
    `list_open_programs`, `enum_values_am`, `search_by_law`,
    `active_programs_at`, `related_programs`, `search_acceptance_stats_am`,
    `intent_of`, `reason_answer`
  - autonomath_wrappers.py (5): `search_gx_programs_am`, `search_loans_am`,
    `check_enforcement_am`, `search_mutual_plans_am`, `get_law_article_am`
  - tax_rule_tool.py (1): `get_am_tax_rule`
  - Total MCP tool count: 31 → **47**.
- **REST router** `src/jpintel_mcp/api/autonomath.py` (16 endpoints at
  `/v1/am/*`) — file on disk but intentionally NOT mounted at v0.2.0 per
  parallel-CLI merge plan. One-line activation when ready.
- **Feature flag** `AUTONOMATH_ENABLED` (default `True`) gating the
  autonomath_tools import in `server.py:4220` — rollback path to 31-tool
  baseline if autonomath.db becomes unavailable.
- **Config fields** `settings.autonomath_db_path` (default
  `./autonomath.db` dev / `/data/autonomath.db` prod) and
  `settings.autonomath_enabled`.
- **Fly.toml** `[env]` block now includes `AUTONOMATH_DB_PATH` +
  `AUTONOMATH_ENABLED`; `[[vm]]` bumped 1→2 CPU, 512→2048 MiB to cover
  7.3 GB DB mmap + headroom.
- `AUTONOMATH_DB_MANIFEST.md` at repo root documenting the DB lineage,
  18+ am_* table inventory, and "read-only primary source as of 2026-04-24
  23:26" invariant.

### Changed

- `server.json` / `pyproject.toml` description updated to reflect 47-tool
  surface and autonomath dataset breadth (416,375 entities, 5.26M facts,
  23,805 relations).
- `CLAUDE.md` architecture section split into two-DB layout with
  per-DB table inventory.

### Deferred to v0.3.x

- REST mount for `/v1/am/*` — router file on disk, `include_router`
  call not yet added. Per parallel-CLI merge plan §6.2: "10 new tools do
  not expose REST routes at launch (deferred)".
- Embedding-powered `reason_answer` semantic search — skeleton present
  (am_entities_vec + tiered vec tables) but `sentence-transformers` +
  `sqlite-vec` deps not yet pinned in pyproject.toml.
- Learning middleware + proactive push tools (Phase D/E of rollout plan).

### Unreleased (non-0.2.0 items kept below this divider)

- JP-localized 429 rate-limit error body (`detail` + `detail_en`) and
  JP-localized 422 validation errors (`msg_ja` + `detail_summary_ja`).
- `/v1/meta` endpoint (previously `/meta`; old path kept as 308 redirect).
- `/v1/openapi.json` endpoint (previously `/openapi.json`; old path kept
  as 308 redirect).
- `site/404.html` branded 404 page.
- `site/programs/index.html` — `/programs/` landing for BreadcrumbList
  navigation.
- `site/_redirects` for Cloudflare Pages URL hygiene.
- `site/rss.xml` — 20 latest programs feed.
- `scripts/refresh_sources.py` — nightly URL liveness scan with per-host
  rate limit, robots.txt compliance, and 3-strike quarantine.
- `.github/workflows/refresh-sources.yml` — daily 03:17 JST cron.
- `CLAUDE.md` at repo root for future LLM-assisted sessions.

### Changed

- MCP tool docstrings (all 13) rewritten per Anthropic mcp-builder
  pattern: 1-sentence purpose + concrete scope numbers (11,547 / 2,286 /
  108 / 1,185 / 181) + 2–3 natural Japanese example queries per tool.
  Removed negative framing ("do not use for X") per 2026 ArXiv 2602.14878
  finding that negative prompts in tool descriptions are ignored.
- `server.json` description: updated from 6,658 programs to full
  multi-source framing (11,547 programs + 2,286 採択事例 + 108 三軸分解
  融資 + 1,185 行政処分 + 181 exclusion/prerequisite rules) with
  primary-source lineage differentiation.
- `pyproject.toml` description mirrors the new multi-source framing.
- MCP server `serverInfo.version` now reports `0.1.0` (autonomath-mcp)
  instead of MCP SDK version.
- Program page template: replaced generic "所管官公庁" fallback with
  URL-host-derived JA agency name.
- Program page template: `target_types` enum values (`corporation`,
  `sole_proprietor`, etc.) now render as JA labels (法人, 個人事業主).
- Program page JSON-LD: `MonetaryGrant.funder` is now
  `GovernmentOrganization` with the actual issuing authority, not
  AutonoMath.
- Program page copy: "最終更新" label replaced with "出典取得" +
  disclaimer, reflecting that AutonoMath records when it fetched the
  source, not when the source was updated.
- Dashboard: removed retired `tier-badge` / "Free tier" markup. Copy
  reflects the current metered ¥3/req model (税込 ¥3.30).
- Dashboard: quota-reset copy now accurately states "月初 00:00 JST
  (認証済み: 00:00 UTC)".
- Stripe checkout: removed `consent_collection.terms_of_service=required`
  (caused live-mode 500). Replaced with `custom_text.submit.message`
  containing ToS + Privacy links.
- Stripe webhook: `invoice.payment_failed` now demotes the customer
  quota; `invoice.paid` re-promotes on recovery.
- README: quickstart curl uses `/v1/programs/search` (was `/v1/search`
  which 404'd); added REST API + SDKs section.
- Trust footer (`運営: Bookyou株式会社 (T8010001213708) ·
  info@bookyou.net`) now present on every public page.

### Fixed

- 509 polluted DB rows quarantined: 5 aggregator URLs, 298 MAFF `g_biki`
  dead pages, 8 fake `12345.pdf` placeholder URLs, 198 bare MAFF section
  roots.
- 360 stale HTML program pages deleted, sitemap rebuilt to 4,817
  entries.
- FTS search: `ORDER BY rank` path now also respects tier priority.
- FTS search: `tier='X'` rows no longer leak into results (432
  pre-existing + 509 new quarantined).
- FTS search: phrase-match used for 2+ character kanji queries to
  suppress trigram false-positives (e.g., `税額控除` no longer returns
  "ふるさと納税").
- FTS search: kana query expansion (`のうぎょう` → `農業`) for top-50
  common terms.
- LIKE fallback (q<3) now searches `aliases_json` and `enriched_text`.
- Duplicate program dedup via GROUP BY primary_name.
- `pricing.html` paid CTA is a POST to `/v1/billing/checkout` (was a
  broken GET link returning 405).
- `pricing.html` contact email: `info@bookyou.net` (was dead alias
  `hello@autonomath.ai`).
- `index.html` hero-tag: "AutonoMath" (was leftover "jpintel").
- `status.html`: added full footer (previously had none before
  `</body>`).
- `server.py` module docstring: binary name `autonomath-mcp` (was
  "AutonoMath").

## [0.1.0] - 2026-05-06 (planned)

First public release of the `autonomath-mcp` API, MCP server, and the
Python / TypeScript SDKs. Bundles all three artifacts at the same
initial version to simplify the launch; subsequent SDK releases will
cut independently (see `docs/_internal/sdk_release.md`).

### Added

**REST API (`https://api.autonomath.ai`, path-versioned under `/v1/*`):**

- `GET  /v1/programs/search` — structured + free-text search with
  `tier`, `prefecture`, `authority_level`, `funding_purpose`,
  `target_type`, `amount_min` / `amount_max`, `include_excluded`,
  `limit`, `offset`, `fields` (`minimal` / `default` / `full`).
- `GET  /v1/programs/{unified_id}` — program detail with optional
  enriched A–J blocks and source_mentions lineage.
- `POST /v1/programs/batch` — batch detail lookup (up to 100 ids).
- `GET  /v1/exclusions/rules` — list the exclusion-rule catalog.
- `POST /v1/exclusions/check` — evaluate a candidate program set against
  all exclusion rules; returns hits grouped by severity.
- `POST /v1/feedback` — user feedback submission (auth optional).
- `POST /v1/billing/checkout` / `/portal` / `/keys/from-checkout` /
  `/webhook` — Stripe-backed billing flow.
- `GET  /v1/meta` — aggregate stats (total_programs, tier_counts,
  last_updated).
- `GET  /healthz` — liveness probe.
- `GET  /v1/ping` — authenticated echo (useful for SDK smoke tests).

**MCP server (stdio, FastMCP, protocol `2025-06-18`):** exposes six
tools — `search_programs`, `get_program`, `batch_get_programs`,
`list_exclusion_rules`, `check_exclusions`, `get_meta`. Tool shapes
mirror the REST responses 1:1.

**Python SDK (`jpintel` on PyPI):** `Client` + `AsyncClient` with typed
Pydantic models and a typed error hierarchy (`JpintelError`,
`AuthError`, `NotFoundError`, `RateLimitError`, `ServerError`). Retries
429 / 5xx with `Retry-After` support. Requires Python 3.11+.

**TypeScript SDK (`@autonomath/client` on npm):** zero-runtime-deps
`Client` using the platform `fetch` (Node 18+, Deno, Bun, browsers).
Dual ESM + CJS output with bundled `.d.ts`. Exponential backoff on
429 / 5xx.

### Notes

- **Semver and pre-1.0 caveat.** While we are at `0.x.y`, *minor* bumps
  may still contain breaking changes — we will call them out explicitly
  with a `BREAKING:` prefix. `1.0.0` is targeted for GA (not before
  2026-09); post-1.0, breaking changes require a major bump plus a
  6-month deprecation window. See [`docs/versioning.md`](docs/versioning.md).
- **Rate limits at launch.** Anonymous: 50 req/month per IP (IPv4 /32,
  IPv6 /64), JST-first-of-month 00:00 reset. Authenticated: metered at
  ¥3/req 税別 (税込 ¥3.30) via Stripe usage billing, `lookup_key =
  per_request_v2`.
- **Data coverage disclaimer.** The `programs` catalog covers Japan's
  national, prefectural, municipal, and financial-public-corp (公庫)
  subsidy / loan / tax-incentive landscape. Coverage is **not
  exhaustive** and the Tier distribution is skewed toward agriculture
  and manufacturing at launch. Callers should treat absence of a
  program as "we may not have it yet", not "it doesn't exist". See
  [`docs/exclusions.md`](docs/exclusions.md) and
  [`docs/data_integrity.md`](docs/data_integrity.md).
- **SLA.** 99.0% monthly uptime target on `api.autonomath.ai` during
  beta, "fair-warning" SLA (no service credits). See
  [`docs/sla.md`](docs/sla.md).

---

[Unreleased]: {{REPO_URL}}/compare/v0.1.0...HEAD
[0.1.0]: {{REPO_URL}}/releases/tag/v0.1.0

© 2026 Bookyou株式会社 (T8010001213708).
