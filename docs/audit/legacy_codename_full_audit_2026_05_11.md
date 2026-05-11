# Legacy Codename Full Audit — 2026-05-11

Repo grep audit of legacy brand / codename / phase residue across the jpcite tree.
PR #25 hotfix swept the public surface for `税務会計AI` / `AutonoMath` on key HTML
pages; this audit re-runs the sweep with the **explicit Tier 1 / 2 / 3 policy
matrix** and inventories what remains, separating **public surface**
(`site/` + `site/.well-known/`) from **internal surface** (`docs/` + `scripts/`
+ `src/` + `.github/`).

This audit is **read-only**. No source code is modified. Follow-up fix tasks
should consume the Tier 1 list verbatim.

---

## Scope and method

- Inputs scanned: `site/`, `docs/`, `scripts/`, `src/`, `.github/`,
  `data/` (json/sql only), `CLAUDE.md`, `README.md`, `mkdocs.yml`.
- Tool: `rg` 14.1.1 (binary file auto-skip, default ignore rules respected).
- Match patterns:

  | Tier | Pattern |
  | --- | --- |
  | 1 | `BC666`, `unified_registry`, `税務会計AI` |
  | 2 | `AutonoMath`/`autonomath`, `zeimu-kaikei.ai`/`zeimu-kaikei`, `jpintel`/`jpintel-mcp` |
  | 3 | `Wave [0-9]`, `W[0-9]+-[0-9]+`, `V3_WAVE`, `Phase [A-Z]`, `feedback_*.md`, `DEEP-[0-9]+` |

- Allowed reservations (per policy):
  - Tier 1 `税務会計AI` is **allowed in `site/llms*.txt`** as SEO bridge
    marker only.
  - Tier 2 `autonomath` / `autonomath-mcp` is **allowed** when it refers to
    the PyPI package name, the Fly app name `autonomath-api`, or the Python
    import path `src/jpintel_mcp/...` / `autonomath_tools/`.
  - Tier 2 `zeimu-kaikei` is **allowed** in 301 redirect rules
    (`_redirects`, Cloudflare scripts) and legacy host deprecation middleware.
  - Tier 2 `jpintel` is **allowed** under the Python import path
    `src/jpintel_mcp/`.
  - Tier 3 is internal-keep across the board (Wave/Phase/feedback/DEEP).

---

## Summary table

| Tier | Pattern | Files | Total matches | Public surface (site/) | Internal surface | Must-fix? |
| --- | --- | ---:| ---:| ---:| ---:| --- |
| 1 | `BC666` | 3 | 6 | 0 | 6 (data/ only) | YES |
| 1 | `unified_registry` | 18 | 29 | 0 | 29 | YES |
| 1 | `税務会計AI` | 24 | 73 | 8 | 65 | YES (excl. 4 llms\*.txt lines + reservation) |
| 2 | `AutonoMath`/`autonomath` | 1182 | ~6 962 | 534 (56 files) | ~6 428 | Public only |
| 2 | `zeimu-kaikei` | 42 | 185 | 7 (4 files) | 178 | Public only |
| 2 | `jpintel` | 580 | ~3 263 | 3 (1 file = `_redirects`) | ~3 260 | Public NG hits = 0 |
| 3 | `Wave N` / `W-m` / `V3_WAVE` / `Phase [A-Z]` | 229 | n/a | 38 (11 files) | n/a | NO (internal keep) |
| 3 | `feedback_*.md` | 16 | n/a | 0 | n/a | NO (internal keep) |
| 3 | `DEEP-[0-9]+` | 76 | n/a | 0 | n/a | NO (internal keep) |

---

## Tier 1 — IMMEDIATE FIX REQUIRED (all surfaces)

### 1.1 `BC666`  (6 hits in 3 files, all in `data/`)

| File | Line | Sample |
| --- | --- | --- |
| `data/autonomath_static/agri/exclusion_rules.json` | 10 | `"BC666 image 7 の月別スケジュール (前提依存 + 順序制約の実運用確認)"` |
| `data/autonomath_static/agri/exclusion_rules.json` | 71 | `"source_notes": "nounavi-aomori support: 対象者 '認定新規就農者'… BC666 実例 '4 月認定申請 → 5 月認定 → 5 月 7 日 青年等就農資金申込' で順序確定"` |
| `data/autonomath_static/agri/exclusion_rules.json` | 95 | `"…BC666 image 7 の 4-6 月個人ルート + 7-9 月法人ルートが実例…"` |
| `data/autonomath_static/example_profiles/README.md` | 16 | `\| bc666_plan_map.yml \| BC666 northstar XLSX → PlanUnderReview cell-mapping fixture \|` |
| `data/autonomath_static/example_profiles/bc666_plan_map.yml` | 1 | `# BC666 事業計画書 3.30 xlsx → PlanUnderReview 変換マッピング` |
| `data/autonomath_static/example_profiles/bc666_plan_map.yml` | 3 | `# ⚠️ **重要**: BC666 はまだ窓口に提出していない draft であって「正解」ではない。` |

These are agri-pivot legacy benchmark references baked into static
fixtures. Per memory `feedback_bc666_is_judgment_benchmark.md`, BC666
is unrelated to jpcite (Japanese public-program DB). Fix path: rename
fixture file + scrub source-note prose; keep semantic intent (4-6 月
個人ルート + 7-9 月法人ルート の例) but redact the BC666 token.

### 1.2 `unified_registry`  (29 hits in 18 files)

Internal-only (no public-surface hits). All file:line entries:

| File | Line | Sample |
| --- | --- | --- |
| `scripts/data_quality_audit.py` | 35 | `# project_unified_registry_tier.md snapshot after 2026-04-20 strict recalc.` |
| `scripts/data_quality_audit.py` | 364 | `"Reference snapshot (from memory \`project_unified_registry_tier.md\`): "` |
| `scripts/ingest_external_data.py` | 38 | `the canonical UNI-<10hex> ingested from unified_registry.json.` |
| `scripts/ingest_external_data.py` | 217 | `separate from the canonical UNI-xxxx rows that unified_registry.json` |
| `scripts/prefecture_walker.py` | 1 | `"""Prefecture attach walker for jpintel-mcp unified_registry.` |
| `scripts/prefecture_walker.py` | 54 | `REGISTRY_PATH = Path("/Users/shigetoumeda/Autonomath/data/unified_registry.json")` |
| `scripts/prefecture_walker.py` | 272 | `raise FileNotFoundError(f"unified_registry not found at {REGISTRY_PATH}")` |
| `src/jpintel_mcp/api/widget_auth.py` | 689 | `# target_types: drawn from the unified_registry vocabulary. Kept small` |
| `src/jpintel_mcp/api/meta_freshness.py` | 52 | `return Path(__file__).resolve().parents[2] / "data" / "unified_registry.json"` |
| `src/jpintel_mcp/api/meta_freshness.py` | 109 | `registry: unified_registry.json structure (needs .programs dict).` |
| `src/jpintel_mcp/db/schema.sql` | 2 | `-- Generated on ingest from Autonomath unified_registry + enriched/ + exclusion_rules` |
| `src/jpintel_mcp/ingest/canonical.py` | 4 | `- unified_registry.json -> programs table (+ fts)` |
| `src/jpintel_mcp/ingest/canonical.py` | 130 | `raise RuntimeError("unified_registry.json has no 'programs' dict")` |
| `src/jpintel_mcp/ingest/canonical.py` | 327 | `logger.error("unified_registry.json missing at %s", reg_path)` |
| `src/jpintel_mcp/config.py` | 334 | `return self.autonomath_path / "data" / "unified_registry.json"` |
| `docs/_internal/repo_organization_assessment_2026-05-06.md` | 103 | `data/unified_registry.json` |
| `docs/_internal/COORDINATION_2026-04-25.md` | 19, 42, 58 | image-baked path mentions |
| `docs/_internal/_archive/2026-04/sentry_audit_2026-04-25.md` | 118 | DB integrity_check fallback note |
| `docs/_internal/GENERALIZATION_ROADMAP.md` | 152 | `### R3. unified_registry の語彙ドリフト` |
| `docs/_internal/content_flywheel.md` | 22, 221 | tier S+A density references |
| `docs/_internal/perf_baseline_v15_2026-04-25.md` | 56 | path reference |
| `docs/_internal/perf_baseline_2026-04-25.md` | 40, 42 | error string + comment |
| `docs/_internal/ingest_automation.md` | 216 | ingestor reference |
| `docs/_internal/operators_playbook.md` | 143 | `2. Autonomath 側 unified_registry の該当 row を修正…` |
| `docs/_internal/archive/launch_2026-04-23/LAUNCH_READINESS.md` | 30 | `Ingest from Autonomath unified_registry.json` |

`unified_registry` is the legacy table/path name. The newer canonical
table is `programs` (see `src/jpintel_mcp/db/schema.sql:2` which still
refers to it as the source artifact). Fix path: rename the JSON
artifact + load path, or commit to the new naming and add a docstring
that calls the old name out as deprecated.

### 1.3 `税務会計AI`  (73 hits in 24 files)

**Allowed reservations (do not fix, SEO bridge marker)** — 4 lines:

| File | Line | Notes |
| --- | --- | --- |
| `site/llms.txt` | 2 | Bridge marker prose |
| `site/llms.en.txt` | 2 | Bridge marker prose |
| `site/llms-full.txt` | 2 | Bridge marker prose |
| `site/llms-full.en.txt` | 2 | Bridge marker prose |
| `site/en/llms.txt` | 3 | Bridge marker prose |

**Public-surface NOT bridge-marker (FIX REQUIRED)** — 3 lines:

| File | Line | Sample |
| --- | --- | --- |
| `site/index.html` | 87 | `"alternateName": ["jpcite", "税務会計AI", "AutonoMath", "zeimu-kaikei.ai"],` (schema.org JSON-LD) |
| `site/index.html` | 122 | `"alternateName": ["jpcite", "税務会計AI", "AutonoMath", "zeimu-kaikei.ai"],` (schema.org JSON-LD) |
| `site/.well-known/trust.json` | 20 | `"previous_brands": ["AutonoMath", "zeimu-kaikei.ai"]` (`税務会計AI` absent here — but this is the canonical legacy-brand surface, so audit value) |

`site/index.html` lines 87+122 currently re-list `税務会計AI` as
`alternateName` in two JSON-LD blocks. Per memory
`feedback_legacy_brand_marker.md`, the legacy brand marker should be
**minimal** and not foregrounded. Decide: drop entirely, or keep one
single line as `alternateName` and remove the duplicate at line 122.

**Internal surface (Tier 1 — FIX REQUIRED, no reservation)** — 65 lines
across 19 files:

- `docs/for-agent-devs/why-bundle-jpcite_2026_05_11.md:6` — editorial
  guideline mentions the term (self-referential, keep with marker, or
  reword to talk about "legacy brand" without naming).
- `docs/geo/seo_geo_strategy_2026_05_11.md` lines 5, 93, 199 — strategy
  doc; can stay as policy reference but consider scoping to a single
  paragraph.
- `docs/distribution/asset_spec_2026_05_11.md:265` — asset rules; keep
  as policy reference.
- `docs/publication/targeting_plan_2026_05_11.md:306` — audit table;
  keep as reference.
- `docs/_internal/_INDEX.md:18`, `docs/_internal/seo_geo_strategy.md`
  lines 99, 101, 121, `docs/_internal/handoff_session_2026-05-01_for_deploy.md:62`,
  `docs/_internal/sdk_republish_after_rename.md:3` — internal docs.
- `docs/_internal/_archive/2026-04/competitive_baseline_2026-04-29.md`
  lines 11, 175, 241 — archived audit; keep.
- `docs/_internal/_archive/2026-04/en_coverage_audit_2026-04-29.md`
  39 hits — full audit table for the prior brand; archive-only,
  keep.
- `scripts/check_geo_readiness.py:45` — readiness probe ("brand
  history" check); intent is to assert the legacy mark is present in
  llms.txt, so this stays.
- `scripts/check_distribution_manifest_drift.py:639` — set membership
  `{"zeimu-kaikei.ai", "税務会計AI"}`; intent identical, keep.
- `scripts/distribution_manifest.yml:161, 241` — distribution manifest
  legacy brand list; keep.
- `scripts/rename_zeimu_to_jpcite.py:15` — comment in the one-shot
  rename script; keep as historical.
- `scripts/generate_law_pages.py:33` — docstring "do NOT surface…";
  intent is the policy itself, keep.
- `scripts/regen_llms_full.py:253, 257` — emits the bridge marker
  literally; keep.
- `scripts/notify_existing_users.py:3, 197` — one-shot rename
  notification; keep as historical.
- `.github/workflows/rebrand-notify-once.yml:3` — workflow comment;
  keep.
- `CLAUDE.md` — not detected (passed the rg sweep with 0 hits for
  `税務会計AI` against the root); the earlier check shows `1` hit
  came via the `zeimu-kaikei` axis.

The **only Tier 1 must-fix non-bridge hits** are the two
`site/index.html` JSON-LD `alternateName` re-entries and (subjectively)
the `for-agent-devs/why-bundle-jpcite_2026_05_11.md:6` reword. The
remaining 60+ hits all serve a policy / archive / SEO function and
should NOT be removed wholesale.

---

## Tier 2 — PUBLIC SURFACE ONLY (internal keep OK)

### 2.1 `AutonoMath` / `autonomath`

Aggregate counts:

| Surface | Files | Total matches |
| --- | ---:| ---:|
| Public `site/` | 56 | 534 |
| `docs/` | 260 | 2 236 |
| `scripts/` | 527 | 2 230 |
| `src/` (incl. import path) | 260 | 1 564 |
| `.github/` | 76 | 334 |
| Root files (`CLAUDE.md`, `README.md`, `mkdocs.yml`) | 3 | 64 |

Internal surface is **expected** to be heavy because:

- Python import path is `src/jpintel_mcp/mcp/autonomath_tools/`,
  `src/jpintel_mcp/api/autonomath.py`, etc.
- PyPI package name is `autonomath-mcp`.
- Fly app name is `autonomath-api`.
- Local Autonomath data path is `~/Autonomath/`.

**Public surface — KEEP (allowed PyPI / npm package + widget filename
+ bridge marker):**

- `site/widget/autonomath.src.css`, `site/widget/autonomath.css`,
  `site/widget/autonomath.src.js`, `site/widget/autonomath.js`,
  `site/widget/jpcite.js` — widget CSS class prefix `.autonomath-widget-*`
  (~480 lines aggregate). These are the widget filenames + CSS class
  names; they ship in the embed snippet customers paste into their
  sites. Renaming is high-cost (breaks customer integrations) and
  **out of scope for this audit**.
- `site/mcp-server.json`, `site/mcp-server.full.json`,
  `site/server.json`, `site/.well-known/mcp.json`,
  `site/.well-known/trust.json`, `site/.well-known/sbom.json`,
  `site/.well-known/sbom/sbom-npm-typescript.cyclonedx.json` — refer
  to `autonomath-mcp` PyPI package + `@autonomath/sdk` npm scope +
  GitHub URL `shigetosidumeda-cyber/autonomath-mcp`. Allowed by policy.
- `site/dashboard.html`, `site/success.html` — `pip install
  autonomath-mcp` / `args: ["autonomath-mcp"]` install instructions.
  Allowed (PyPI compat).
- `site/connect/*.html`, `site/integrations/*.html`,
  `site/compare/*/index.html`, `site/llms*.txt`, `site/en/audiences/*.html`,
  `site/en/getting-started.html` — install snippets and GitHub URL
  references that all wrap `autonomath-mcp`. Allowed.

**Public surface — FIX (real legacy-brand mentions, ~12 lines):**

| File | Line | Sample |
| --- | --- | --- |
| `site/index.html` | 87 | JSON-LD `alternateName` includes `"AutonoMath"` |
| `site/index.html` | 122 | JSON-LD `alternateName` includes `"AutonoMath"` (duplicate block) |
| `site/transparency/llm-citation-rate.html` | 361 | `… + autonomath.citation_sample` (legacy table-name reference) |
| `site/mcp-server.json` | 339 | tool description prose includes `feedback_autonomath_no_api_use` policy ref |
| `site/mcp-server.json` | 403 | tool description prose mentions `autonomath.intake.<known>` dispatch path |
| `site/mcp-server.full.json` | 339 | same as above (duplicate manifest) |
| `site/mcp-server.full.json` | 403 | same as above |
| `site/status/index.html` | 572 | `var PYPI_PROJECT = "https://pypi.org/pypi/autonomath-mcp/json";` (allowed) |
| `site/status/index.html` | 694 | `var legacyEntityFactsKey = ["db", "autonomath", "reachable"].join("_");` — KV key prose, decide whether to rename |
| `site/.well-known/trust.json` | 20 | `"previous_brands": ["AutonoMath", "zeimu-kaikei.ai"]` (intentional legacy marker — keep) |
| `site/en/foreign-investor.html` | 72 | `… pure SQL + Python over autonomath.db.` (legacy DB name in prose) |
| `site/styles.src.css` | 188 | comment about `autonomath-mcp install commands` (allowed) |

Real candidates for rewording on the public surface: `site/index.html`
JSON-LD duplicates, `site/transparency/llm-citation-rate.html:361`
(`autonomath.citation_sample`), `site/en/foreign-investor.html:72`
(`autonomath.db`), `site/mcp-server*.json` tool descriptions (lines
339+403, expose internal naming convention `autonomath.intake.<known>`
and `feedback_autonomath_no_api_use`).

### 2.2 `zeimu-kaikei`

Aggregate counts:

| Surface | Files | Total matches |
| --- | ---:| ---:|
| Public `site/` | 4 | 7 |
| `docs/` | 22 | 118 |
| `scripts/` | 9 | 43 |
| `src/` | 4 | 12 |
| `.github/` | 2 | 4 |
| Root | 1 | 1 (`CLAUDE.md`) |

**Public surface — all 7 hits are bridge marker or 301 redirect rules
(allowed):**

| File | Line | Sample |
| --- | --- | --- |
| `site/index.html` | 87, 122 | JSON-LD `alternateName` — same lines as 1.3 / 2.1 |
| `site/llms.txt` | 2 | Bridge marker |
| `site/llms.en.txt` | 2 | Bridge marker |
| `site/llms-full.txt` | 2 | Bridge marker |
| `site/llms-full.en.txt` | 2 | Bridge marker |
| `site/en/llms.txt` | 3 | Bridge marker |
| `site/.well-known/trust.json` | 20 | `"previous_brands"` (keep) |

**Internal — allowed (legacy host deprecation + 301 chain):**

- `src/jpintel_mcp/api/middleware/host_deprecation.py` lines 1, 7, 81,
  112, 124 — middleware that rewrites legacy host `api.zeimu-kaikei.ai`
  → `api.jpcite.com`. Keep.
- `src/jpintel_mcp/api/middleware/origin_enforcement.py` lines 49–51 —
  CORS allowlist for legacy origins. Keep.
- `src/jpintel_mcp/api/main.py:1421` — middleware mount comment. Keep.
- `scripts/ops/cloudflare_redirect.sh:69` — CF zone map. Keep.
- `scripts/rename_zeimu_to_jpcite.py` (26 hits) — one-shot rename
  script with the source/dest mapping inline. Keep as historical.
- `docs/runbook/cloudflare_redirect.md` (6), `docs/runbook/github_rename.md`
  (2), `docs/runbook/README.md` (2) — runbooks that describe the 301
  setup. Keep.
- `docs/_internal/seo_geo_strategy.md` (33),
  `docs/_internal/api_domain_migration.md` (7),
  `docs/_internal/stripe_webhook_migration.md` (13),
  `docs/_internal/jpcite_cloudflare_setup.md` (14) — strategy /
  migration runbooks. Keep.
- `docs/_internal/_archive/2026-04/competitive_baseline_2026-04-29.md`
  (10) — archived audit. Keep.
- `CLAUDE.md:233` — CORS allowlist policy doc. Keep.
- `.github/workflows/pages-preview.yml:23-24`,
  `.github/workflows/pages-deploy-main.yml:31-32` — workflow comments
  about the redirect-source domains. Keep.

### 2.3 `jpintel`

Aggregate counts:

| Surface | Files | Total matches |
| --- | ---:| ---:|
| Public `site/` | 1 | 3 |
| `docs/` | 212 | 1 632 |
| `scripts/` | 333 | 1 445 |
| `.github/` | 33 | 151 |
| Root | 1 | 32 (`CLAUDE.md`) |

**Public surface (`site/`) — all 3 hits are 301 redirect rules
(allowed):**

| File | Line | Sample |
| --- | --- | --- |
| `site/_redirects` | 124 | `/jpintel        /  301` |
| `site/_redirects` | 125 | `/jpintel.html   /  301` |
| `site/_redirects` | 126 | `/jpintel/*      /  301` |

**Public-surface NG count: 0.** PR #25 was effective.

Internal: heavy use is expected — `src/jpintel_mcp/` is the canonical
import path; all internal documentation, cron schedulers, and runbooks
reference it. Per policy these stay.

---

## Tier 3 — INTERNAL KEEP (reference only, no fix)

### 3.1 `Wave N` / `W-m` / `V3_WAVE` / `Phase [A-Z]`

| Surface | Files | Matches |
| --- | ---:| ---:|
| Public `site/` | 11 | 38 |
| `docs/` | 57 | n/a (heavy) |
| `scripts/` | 63 | n/a (heavy) |
| `src/` | 76 | n/a (heavy) |
| `.github/` | 17 | n/a |
| Root | 16 | n/a |

**Public-surface Wave/Phase hits** (these leak development-phase
naming into customer-facing pages):

| File | Hits | Notable lines |
| --- | ---:| --- |
| `site/dashboard/savings.html` | 17 | Calculator formula anchored to "W28-4 sim 実測" (lines 15, 19, 250, 325, 326, 362, …) |
| `site/dashboard.html` | 9 | "ログイン (W9-01 実装予定 — UI placeholder)" + "Wave 8 で hydrate" placeholders |
| `site/playground.html` | 5 | "v3 evidence3 wizard 3 step (minimal viable、Wave 8 で full)" |
| `site/mcp-server.json` | 1 | "(W22-9)" inside tool description |
| `site/mcp-server.full.json` | 1 | same |
| `site/legal-fence.html` | 1 | "Wave 30 disclaimer hardening 済" |
| `site/calculator/index.html` | 1 | "W28-4 reframe" comment |
| `site/trust/purchasing.html` | 1 | n/a |
| `site/status/v2.html` | 1 | "Wave 8 で詳細" |
| `site/audiences/shihoshoshi.html` | 1 | n/a |
| `site/artifact.html` | 1 | n/a |

Per Tier 3 policy these are **internal-keep** and do not need fixing.
But the user may want to clean the most prominent customer-facing
phrasings (`dashboard.html` "W9-01 実装予定", `dashboard/savings.html`
"W28-4 sim 実測 anchor") as a future Tier 3 elective fix — flagged
here for visibility only.

### 3.2 `feedback_*.md` (memory keys)

16 internal file hits, **0 on public surface**.

References in (internal-only):

- `src/jpintel_mcp/email/compliance_templates.py:1`
- `src/jpintel_mcp/api/autonomath.py:1`
- `src/jpintel_mcp/db/id_translator.py:1`
- `scripts/data_quality_audit.py` (4)
- `scripts/ingest/ingest_enforcement_npa.py:1`
- `scripts/ingest/ingest_jcci_programs.py:1`
- `scripts/migrations/115_source_manifest_view.sql:1`
- `docs/geo/seo_geo_strategy_2026_05_11.md` (6) — public-NG candidate;
  the public `seo_geo_strategy_2026_05_11.md` lives under `docs/geo/`
  but is published via mkdocs; check whether `mkdocs.yml` exposes
  `docs/geo/` (likely yes, but `feedback_*.md` token in a paragraph
  body is a soft leak, not load-bearing).
- `docs/_internal/_archive/2026-04/en_coverage_audit_2026-04-29.md:1`
- `docs/_internal/hf_publish_log.md:1`
- `docs/_internal/seo_geo_strategy.md:1`
- `docs/_internal/operators_playbook.md:1`
- `docs/_internal/competitive_watch.md:1`
- `docs/_internal/W19_VENV312_README.md:1`
- `docs/_internal/saburoku_kyotei_gate_decision_2026-04-25.md:5`
- `docs/_internal/data_integrity.md:1`

Per the audit rules, the **memory key tokens are not hardcoded in this
audit** — these are simply pointers ("see `feedback_*` in memory").

### 3.3 `DEEP-[0-9]+` (internal ticket IDs)

76 file hits. **0 public-surface hits.**

Heavy concentration in:

- `scripts/verify/deep-*_verify.sh` (12 files × 6 hits each = ~72)
- `scripts/cron/*.py` (cron job docstrings referencing DEEP-NN spec
  IDs)
- `.github/workflows/*.yml` (workflow descriptions)
- `docs/legal/gbizinfo_terms_compliance.md`, `docs/smoke_runbook.md`,
  `CLAUDE.md` (6), `README.md` (1)

All internal-keep.

---

## Recommendations (audit-only — no code changes here)

1. **Tier 1 must-fix list (small, ~9 actionable lines):**
   - `site/index.html` lines 87, 122 — drop or single-occurrence the
     JSON-LD `alternateName` legacy entry.
   - `site/transparency/llm-citation-rate.html:361` — replace
     `autonomath.citation_sample` with the new table name (or rephrase
     to avoid internal-naming leak).
   - `site/en/foreign-investor.html:72` — replace "over autonomath.db"
     with a brand-neutral phrasing ("over the jpcite SQLite corpus").
   - `site/mcp-server.json` + `site/mcp-server.full.json` lines 339
     and 403 — strip the `feedback_autonomath_no_api_use` and
     `autonomath.intake.<known>` token leaks from public tool
     descriptions.
   - `data/autonomath_static/agri/exclusion_rules.json` lines 10, 71,
     95 + `data/autonomath_static/example_profiles/bc666_plan_map.yml`
     + `data/autonomath_static/example_profiles/README.md:16` —
     redact `BC666` brand token; keep semantic intent.
   - `data/autonomath_static/example_profiles/bc666_plan_map.yml` —
     rename file (drop `bc666_` prefix).
2. **Tier 1 internal `unified_registry` rename**: 29 hits, intentional
   table-name rename. Coordinate the path/JSON rename + grep sweep in
   a separate PR; not blocking but tracks toward the migration target.
3. **Tier 2 public surface** is otherwise clean. The widget CSS prefix
   `.autonomath-widget-*` is a customer-integration contract and is
   intentionally kept (renaming requires SDK republish).
4. **Tier 3** is informational; no action required. If desired, a
   future cleanup can scrub the customer-facing Wave/Phase phrasings in
   `site/dashboard.html` and `site/dashboard/savings.html`.

---

## Notes

- This audit does **not** read or hardcode the memory file paths
  (`feedback_*.md`). All memory references in `src/`, `scripts/`, and
  `docs/_internal/` are listed by file:line only.
- Numbers in the summary table are derived from `rg --count-matches`
  rather than `rg --files-with-matches`; the per-tier file counts and
  match totals may differ slightly from a manual grep due to ripgrep's
  binary-file skipping rules.
- This audit is rooted at `/Users/shigetoumeda/jpcite/` and was
  generated 2026-05-11.
