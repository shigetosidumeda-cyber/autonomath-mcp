# Changelog

All notable changes to **autonomath-mcp** are documented here.

Format: [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).
See [`docs/versioning.md`](docs/versioning.md) for what counts as breaking.

## [Unreleased]

### Added (post-manifest landing 2026-05-07 — manifests held at 139 pending operator decision)

- **7 post-manifest MCP tools landed 2026-05-07** — DEEP-22 / DEEP-30 / DEEP-39 /
  DEEP-44 / DEEP-45 spec batch lands as additive cohort over the 139-tool
  default-gate surface. Manifest counts (`pyproject.toml` /
  `mcp-server.json` / `dxt/manifest.json` / `smithery.yaml` /
  `site/mcp-server.json` / `server.json`) intentionally **held at 139**
  pending operator decision per `R8_MANIFEST_BUMP_EVAL_2026-05-07.md`
  Option B recommendation; runtime `tools/list` will surface **146** once
  the underlying gates flip ON (139 default-gate + 7 post-manifest). Cohort audit:
  `R8_MCP_FULL_COHORT_2026-05-07.md`. NO LLM call inside any of the 7
  tools — pure SQLite + Python.
  - **`query_at_snapshot_v2`** (DEEP-22) — point-in-time snapshot query
    over `am_amendment_snapshot` v2 surface; supersedes the
    `query_at_snapshot` (v1) tool that remains gated off pending the
    migration 067 substrate. v2 reads the 144 dated rows directly and
    returns honest `effective_from` / `eligibility_hash` envelopes for
    those, falling back to a structured `unknown_temporal` hint for the
    remaining ~14,452 rows where the time-series is acknowledged-fake.
    NOT 業法 sensitive.
  - **`query_program_evolution`** (DEEP-30) — program lineage walker over
    `am_amendment_diff` (12,116 rows, cron-live since 2026-05-02). Given
    a `program_unified_id`, returns the eligibility / amount / deadline
    diff timeline with `corpus_snapshot_id` + `corpus_checksum` for
    auditor reproducibility. Empty timeline surfaces a structured
    `{error: {code: empty_evolution, hint}}` envelope. NOT 業法
    sensitive.
  - **`shihoshoshi_dd_pack_am`** (DEEP-39) — 司法書士法 §3 fence,
    NON-CREATING DD pack assembly: 法人番号 → 法務局 jurisdiction
    cross-check + 不動産登記 reference scaffold + 商業登記 amendment
    history index. Output is a **read-only** assembly of first-party
    references with explicit `_disclaimer` declaring the pack is a
    pre-司法書士-review checklist, NOT a 登記申請 draft. Sensitive
    (司法書士法 §3 — assembly only, no 登記申請 creation).
  - **`search_kokkai_utterance`** (DEEP-44) — 国会会議録 utterance search
    over the post-manifest kokkai corpus shard. Filters on speaker /
    party / committee / session date range with FTS5 trigram +
    unicode61 fallback. Each hit carries primary-source `source_url`
    (kokkai.ndl.go.jp) + speaker attribution. NOT 業法 sensitive but
    carries a `_disclaimer` declaring utterances are pre-法案 commentary,
    NOT enacted law.
  - **`search_shingikai_minutes`** (DEEP-45) — 審議会 議事録 search over
    the cabinet-office / agency 審議会 minutes shard. Filters on
    審議会 name / agenda topic / committee member / meeting date range.
    Returns extracted reasoning paragraphs with `corpus_snapshot_id` for
    reproducibility. NOT 業法 sensitive but carries a `_disclaimer`
    that 議事録 are pre-policy deliberation, NOT enacted regulation.
  - **`search_municipality_subsidies`** (DEEP-44 companion) —
    municipality-level subsidy surface beyond the 政令市 20 hub
    coverage. Filters on `municipality_code` (5-digit) + funding_purpose
    + amount range. Honest-coverage gate: returns `{warning:
    coverage_gap_municipality}` envelope when the requested municipality
    has zero indexed programs (vs silently returning 0 rows). NOT 業法
    sensitive.
  - **`get_pubcomment_status`** (DEEP-45 companion) — パブリックコメント
    status probe over `e-gov.go.jp` パブコメ surface. Given a
    `pubcomment_id`, returns the consultation window (open/close) +
    submission count + post-consultation outcome reference (when the
    結果概要 has been issued) + first-party `source_url`. Surfaces a
    structured `{status: in_consultation | closed | result_published |
    unknown}` enum. NOT 業法 sensitive.

### Notes (post-manifest landing 2026-05-07)

- **Manifest hold rationale (Option B)** — per
  `R8_MANIFEST_BUMP_EVAL_2026-05-07.md`, the 7 post-manifest tools are
  **NOT** auto-published to the MCP registry. Manifests stay at 139 until
  the operator explicitly approves a v0.3.5 bump. Rationale: the 3
  post-manifest tools that touch sensitive surfaces
  (`shihoshoshi_dd_pack_am` 司法書士法 §3 / `search_kokkai_utterance`
  utterance disclaimer scaffold / `search_shingikai_minutes` 議事録
  disclaimer scaffold) need a final §52 / §3 disclaimer audit walk
  before public registry exposure. The 4 non-sensitive tools
  (`query_at_snapshot_v2` / `query_program_evolution` /
  `search_municipality_subsidies` / `get_pubcomment_status`) could ship
  today, but bundling avoids two registry republish cycles in one week.
- **Audit references**:
  - `R8_MANIFEST_BUMP_EVAL_2026-05-07.md` — Option A vs Option B
    comparison + Option B (manifest hold + CHANGELOG entry only)
    recommendation.
  - `R8_MCP_FULL_COHORT_2026-05-07.md` — full 146-tool cohort inventory
    with per-tool gate state + sensitivity classification + landing date
    (139 default-gate + 7 post-manifest = 146 latent surface).
- **Internal hypothesis framing retained** — manifest bump is an
  operator decision, NOT an automatic publish trigger. The tag-push
  →PyPI →MCP-registry chain (`release.yml` + `mcp-registry-publish.yml`)
  remains gated on a manual `pyproject.toml` bump; no auto-bump
  workflow has been added in this landing.

## [v0.3.3] — 2026-05-04 — Release wave (DYM middleware + child API keys + 政令市 hubs + manifest shortform)

### Added

- **`did_you_mean` middleware on 422 unknown_query_parameter** — the FastAPI
  validation pipeline now wires a one-shot suggester that catches `unknown
  query parameter` 422 responses and inserts a `did_you_mean` array of the
  3 closest known field names (Levenshtein-trimmed, score>=0.7) into the
  error envelope. Eliminates silent typos like `?pref=...` (correct: `prefecture`)
  / `?industry=...` (correct: `target_industry`).
- **`/v1/me/keys/children` REST endpoint** (POST/GET/DELETE) — sub-API-key
  fan-out surface for the 税理士 顧問先 cohort. Parent key holders can
  mint child keys (1 parent → N children, mig 086) with per-child
  `monthly_cap_yen`, suspend/revoke independently. Each child carries its
  own usage quota counter so 顧問先 attribution is clean. Companion test:
  `tests/test_child_api_keys.py`.
- **政令市 20 hub pages + 5 trust pages + 12 cookbook recipes** —
  `site/cities/{city}.html` x 20 (Sapporo / Sendai / Saitama / Chiba /
  Yokohama / Kawasaki / Sagamihara / Niigata / Shizuoka / Hamamatsu /
  Nagoya / Kyoto / Osaka / Sakai / Kobe / Okayama / Hiroshima / Kitakyushu /
  Fukuoka / Kumamoto), `site/trust/*.html` x 5 (corporate procurement
  reviewer surface), `site/cookbook/*.html` x 12 (W2-6 outline of runnable
  dev-first recipes). Sitemap regenerated, canonical URLs aligned.
- **Saved-search digests fanned out per `client_profiles.profile_ids`** —
  `scripts/cron/run_saved_searches.py` now reads `saved_searches.profile_ids`
  (mig 097) and emits one digest per linked client profile instead of one
  digest per saved_search. The 税理士 / 補助金 consultant cohorts can now
  run N顧問先 saved searches as one cron with per-顧問先 envelope splits.
- **`dispatch_webhooks` filtered by `houjin_watch.watch_kind`** — the M&A
  cohort cron `scripts/cron/dispatch_webhooks.py` (mig 088) now respects
  `watch_kind` (e.g. `amendment` / `enforcement` / `adoption`) so subscribers
  receive only the event categories they actually opted into. Eliminates
  noisy fan-out where a watcher subscribed for `amendment` was also
  receiving `adoption` events.

### Changed

- **MCP manifest descriptions front-load generic keywords** —
  `server.json::description` compressed 287 → **94 chars** to satisfy the
  MCP registry's 100-char hard cap (variant D from the A1-RETRY audit:
  `Japan public-program MCP — subsidies, loans, tax, law, invoice, corp.
  93 tools, ¥3/req metered`). `mcp-server.json` / `dxt/manifest.json` /
  `smithery.yaml` / `site/mcp-server.json` retain the longer marketing copy
  (no 100-char cap on those surfaces). `_meta.publisher-provided` trimmed
  4654 → 1707 bytes (well under the 4 KB registry cap) by dropping
  resources arrays that are runtime-discoverable via `resources/list`.
- **Stripe Checkout display name** — `client_reference_id` now sets the
  jpcite display name (was AutonoMath); aligns checkout UI with the
  2026-04-30 brand rename.
- **`site/structured/` JSON-LD shards retired** — replaced by inline
  JSON-LD on the parent HTML pages. Surface size dropped 22,896 → **12,016
  site files** (-47%) and the canonical .html drift from the dual surfaces
  (shard vs. inline) is gone. Sitemap regenerated.

### Fixed

- **Skip PRAGMA quick_check on autonomath profile** — the schema_guard
  boot-sequence was running a full `PRAGMA quick_check` against the 9.4 GB
  `autonomath.db` on every container start, which exceeded the Fly release
  machine grace period (3 min hard ceiling) and hung deploys. Now skipped
  for the autonomath profile (the integrity check still runs nightly via
  `weekly-backup-autonomath.yml`). Boot grace period restored.
- **`distribution_manifest` route_count drift 212 → 215** — bumped to match
  the runtime probe after the new `/v1/me/keys/children` endpoint group
  added 3 routes.

### Notes

- semver bump to **v0.3.3** applied across `pyproject.toml` /
  `src/jpintel_mcp/__init__.py` / `server.json` / `mcp-server.json` /
  `dxt/manifest.json` / `smithery.yaml` / `site/mcp-server.json` /
  `scripts/distribution_manifest.yml::pyproject_version` /
  `scripts/mcp_registries_submission.json`. `@autonomath/sdk` (npm)
  remains on its independent version track per `feedback_no_priority_question`
  memory note.
- PyPI publish + MCP registry republish happen automatically on tag push:
  `release.yml` triggers on `v*` tags → test → build → PyPI publish via
  `secrets.PYPI_API_TOKEN`. After PyPI 0.3.3 is live (~2-5 min), the
  `mcp-registry-publish.yml` workflow_dispatch fires (OIDC auth, no PAT
  needed) and the registry mirrors the new 94-char description.

### Changed (carryover from Unreleased)

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

## [v0.3.2] - 2026-05-01

### Added

- **`am_amendment_diff` cron live** —改正イベント feed の基盤として
  `am_amendment_diff` populator が production cron で稼働開始。
  `am_amendment_snapshot` の v1/v2 ペアを scan し eligibility / amount /
  deadline 軸の差分を materialize する。Tier 3 alert subscription
  surface (migration 038) と直結し、launch 後の amendment alert を
  empty-feed でなく実データで起動可能にする。
- **`programs.aliases_json` + prefecture/municipality backfill tools** —
  `aliases_json` non-empty 行が **82 → 9,996** へ伸長 (法令 alias
  抽出 + JSIC 同義語 + 既存 alias_table merge)。新スクリプト
  `scripts/etl/backfill_program_aliases.py` +
  `scripts/etl/extract_prefecture_municipality.py`。後者は
  `programs.prefecture` / `programs.municipality` を `source_url`
  ホスト + 本文 N-gram から抽出し、検索 facet の精度を底上げ。
- **HF dataset cards (4 データセット)** — `hf/datasets/` 配下に
  `programs` / `case_studies` / `enforcement_cases` / `loan_programs`
  の README + LICENSE review queue を追加。`docs/_internal/hf_publish_plan.md`
  にライセンス互換チェック手順を記録 (PDL v1.0 / CC-BY 4.0 / 政府標準
  利用規約 を個別レビュー)。launch 直後ではなく review queue が
  green になったタイミングで HF publish CLI を別タスクで実行する。
- **5 untested critical files にテスト追加** — 14 件の新規テストを
  `tests/test_search_ranking.py` / `tests/test_amendment_diff.py` /
  `tests/test_aliases_backfill.py` / `tests/test_prefecture_extractor.py` /
  `tests/test_content_hash_verifier.py` に分散。これまで coverage
  ゼロだった 5 ファイル (search ranking helpers / amendment diff
  populator / aliases backfill / prefecture extractor / content hash
  verifier) を最低 happy-path + bad-input でカバー。

### Changed

- **検索 ranking 改善** — `search_programs` の bm25 ranker で
  `primary_name` matchを **5×** weight、tokenize miss 時の
  LIKE fallback を `primary_name` / `aliases_json` / `enriched_text`
  に拡大。tier prior を再 calibration (S=1.0 / A=0.85 / B=0.55 /
  C=0.30, 旧 0.25 / 0.20 / 0.15 / 0.10) し、Tier S/A の体感ヒット率を
  改善。FTS 結果が 0 件でも LIKE fallback で 1 件以上返る確率が
  上昇 (regression risk → 既存 ranking テスト 12 件の baseline は
  全て pass)。
- **価値命題の書き直し** — README / homepage / pricing 系コピーで
  「token cost shield」フレーミングを廃止し「evidence-first context
  layer」に統一。ユーザーが LLM agent に渡す前に primary-source
  citation 付きで context を組み立てる layer、という positioning。
  旧フレーミング (token cost を削るだけ) は AutoNoMath EC SaaS と
  混同を招くため撤去。
- **anon rate limit `50 req/月` → `3 req/日`** — 匿名ユーザの quota
  reset 単位を月初 JST → 翌日 00:00 JST に変更 (DAU 目的の daily 化、
  AutoNoMath 本体ビジネスモデル v4 と整合)。
  `src/jpintel_mcp/api/middleware/ratelimit.py` の anon bucket と
  `anon_quota_header.py` の警告本文も更新。月初 reset 系コピーは
  `dashboard.html` / `pricing.html` / `docs/ratelimit.md` 全てで
  日次 reset 表記に置換。
- **brand: AutonoMath → jpcite** — user-facing surfaces (site copy /
  README headlines / OG metadata) の `AutonoMath` を `jpcite` に
  rename。PyPI package `autonomath-mcp` と import path
  `jpintel_mcp` は consumer 互換性のため不変。`zeimu-kaikei.ai`
  apex は 301 redirect で SEO 認証を引き継ぐ。

### Fixed

- **`am_source.content_hash` NULL 281 → 0** — 補完 + last_verified
  検証器を追加 (`scripts/etl/fill_content_hash.py` +
  `scripts/cron/verify_last_verified.py`)。content_hash が NULL の
  281 行を実 fetch + sha256 で埋め、`last_verified` の改ざん検出
  cron が 1 日 1 回 sample をかける運用に。
- **`programs.aliases_json` non-empty 82 → 9,996** — 上記 backfill
  ETL の Fixed 効果。検索 query が alias hit に依存していた採択事例
  / 法令交差 query で recall が改善。

### Removed

- **99 GB の DB rollback バックアップ削除** — `data/jpintel.db.bak.*`
  系列のうち 30 日以上経過した snapshot を整理し、バックアップ
  ストレージを **113 GB → 12 GB** に縮小。直近 7 日の snapshot は
  保持 (R2 weekly backup + 直近 daily の二段構え)。
- **token cost shield フレーミング撤去** — 上記 Changed と対応。
  「LLM token cost を削減する layer」という旧 pitch を README /
  homepage / pricing から完全に除去。

### Notes

- 内部メモは [`docs/_internal/`](docs/_internal/) 配下を参照
  (HF publish plan / SEO GEO strategy / brand migration log 等)。
- semver bump (`pyproject.toml` / `server.json` / `mcp-server.json` /
  `dxt/manifest.json` / `smithery.yaml`) は version-bump CLI が
  別タスクで実行する。本エントリは CHANGELOG のみ。

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

[Unreleased]: {{REPO_URL}}/compare/v0.3.3...HEAD
[v0.3.3]: {{REPO_URL}}/compare/v0.3.2...v0.3.3
[v0.3.2]: {{REPO_URL}}/compare/v0.3.1...v0.3.2
[0.3.1]: {{REPO_URL}}/compare/v0.3.0...v0.3.1
[0.3.0]: {{REPO_URL}}/compare/v0.2.0...v0.3.0
[0.2.0]: {{REPO_URL}}/compare/v0.1.0...v0.2.0
[0.1.0]: {{REPO_URL}}/releases/tag/v0.1.0

© 2026 Bookyou株式会社 (T8010001213708).
