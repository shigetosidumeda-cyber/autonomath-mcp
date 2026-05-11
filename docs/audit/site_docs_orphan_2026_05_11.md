# site/ + docs/ orphan / broken-link / duplicate audit (2026-05-11)

Scope: `/Users/shigetoumeda/jpcite/site/` (22,581 .html + sitemap*.xml + _redirects) and `/Users/shigetoumeda/jpcite/docs/` (390 .md) + `mkdocs.yml` exclude_docs / nav.

Probe: ripgrep `href="…"` link index across all .html, sitemap*.xml `<loc>` parse, mkdocs.yml nav + exclude_docs literal parse. Snapshot only — no rename/delete performed.

## 5 axis summary

| axis | what | color | count |
|---|---|---|---|
| A | orphan page (0 inbound link + not in sitemap + not redirect target) | **yellow** | 25 |
| B | broken internal link | **red** | 12739 |
| C | duplicate-content page (small-dir scope) | **green** | 1 groups |
| D | sitemap drift (missing file + file not in sitemap) | **red** | 120 (5 sitemap→missing / 115 file→absent-from-sitemap) |
| E | mkdocs nav vs docs/ + exclude_docs phantom | **yellow** | 19 (0 nav→missing / 0 md→not-in-nav / 19 exclude phantom) |

Color legend: **green** ≈ within tolerance, **yellow** ≈ within fixable backlog, **red** ≈ structural drift requiring rebuild step.

## Axis A · orphan page candidates (top-20)

Total orphan candidates: **25**

Method: file under `site/` not in `PUBLIC_KEEP` allowlist, **0 inbound `href="…"` references** from any other html, **not** listed in any `sitemap*.xml`, and **not** the target of any `_redirects` rule. Auto-gen tree (programs/, laws/, qa/, cases/, enforcement/, cross/, prefectures/, audiences/<pref>/, cities/, intel/) is fully included — orphans there are the ones to investigate.

| # | file (relative to site/) | dir |
|---|---|---|
| 1 | `assets/demo-terminal.html` | `assets/` |
| 2 | `audiences/shihoshoshi.html` | `audiences/` |
| 3 | `dashboard/analytics.html` | `dashboard/` |
| 4 | `docs/404.html` | `docs/` |
| 5 | `en/widget/success.html` | `en/widget/` |
| 6 | `practitioner-eval/ai_dev.html` | `practitioner-eval/` |
| 7 | `practitioner-eval/foreign_fdi_compliance.html` | `practitioner-eval/` |
| 8 | `practitioner-eval/foreign_fdi_investor.html` | `practitioner-eval/` |
| 9 | `practitioner-eval/industry_pack_construction.html` | `practitioner-eval/` |
| 10 | `practitioner-eval/industry_pack_real_estate.html` | `practitioner-eval/` |
| 11 | `practitioner-eval/kaikeishi.html` | `practitioner-eval/` |
| 12 | `practitioner-eval/kaikeishi_audit.html` | `practitioner-eval/` |
| 13 | `practitioner-eval/kokusai_zeimu.html` | `practitioner-eval/` |
| 14 | `practitioner-eval/ma_analyst.html` | `practitioner-eval/` |
| 15 | `practitioner-eval/ma_valuation.html` | `practitioner-eval/` |
| 16 | `practitioner-eval/monitoring_pic.html` | `practitioner-eval/` |
| 17 | `practitioner-eval/shinkin_shokokai.html` | `practitioner-eval/` |
| 18 | `practitioner-eval/subsidy_consultant.html` | `practitioner-eval/` |
| 19 | `practitioner-eval/template.html` | `practitioner-eval/` |
| 20 | `practitioner-eval/zeirishi.html` | `practitioner-eval/` |

Total orphan candidates per top-level dir (showing top 15):

| dir | count |
|---|---|
| `practitioner-eval/` | 16 |
| `transparency/` | 2 |
| `assets/` | 1 |
| `audiences/` | 1 |
| `dashboard/` | 1 |
| `docs/` | 1 |
| `en/` | 1 |
| `status/` | 1 |
| `widget/` | 1 |

## Axis B · broken internal link (top-20 by target frequency)

Total broken link occurrences: **12739** (across 9994 source files, pointing at 139 unique missing targets)

Method: every `href="…"` resolved against either site/ absolute root or source-relative directory. A target is broken if the resolved path is neither an existing file nor an existing directory with an `index.html`.

Top-20 missing targets (most-linked):

| # | missing target | references | example source |
|---|---|---|---|
| 1 | `laws/index.html` | 6493 | `laws/abura-mataha-yugai.html` |
| 2 | `cases/index.html` | 2286 | `cases/mirasapo_case_118.html` |
| 3 | `laws/LAW-c0aea8612e` | 709 | `enforcement/case-jbaudit_r03_2021-r03-0046-0_1.html` |
| 4 | `laws/LAW-0b8fd53008` | 709 | `enforcement/case-jbaudit_r03_2021-r03-0046-0_1.html` |
| 5 | `laws/LAW-1c1831a72e` | 709 | `enforcement/case-jbaudit_r03_2021-r03-0046-0_1.html` |
| 6 | `laws/LAW-23cf80a32f` | 476 | `enforcement/case-mhlw_fraud_20220603_9caa3fbf07.html` |
| 7 | `programs/UNI-ext-89fe514f02` | 246 | `enforcement/case-mhlw_fraud_20220722_61292055ba.html` |
| 8 | `programs/UNI-ext-859b801d1d` | 246 | `enforcement/case-mhlw_fraud_20220722_61292055ba.html` |
| 9 | `programs/UNI-eef45f3263` | 246 | `enforcement/case-mhlw_fraud_20220722_61292055ba.html` |
| 10 | `programs/UNI-ext-c4e5feedb7` | 246 | `enforcement/case-mhlw_fraud_20220722_61292055ba.html` |
| 11 | `programs/UNI-ext-e43f1013ec` | 14 | `enforcement/case-jbaudit_r05_2023-r05-0065-0_16.html` |
| 12 | `programs/UNI-pref-628fc4b54d` | 14 | `enforcement/case-jbaudit_r05_2023-r05-0065-0_16.html` |
| 13 | `programs/UNI-ext-32793db272` | 14 | `enforcement/case-jbaudit_r05_2023-r05-0065-0_16.html` |
| 14 | `programs/UNI-pref-e9c09ec419` | 14 | `enforcement/case-jbaudit_r05_2023-r05-0065-0_16.html` |
| 15 | `programs/UNI-39eb69c459` | 14 | `enforcement/case-mhlw_fraud_20240213_0fbf7a3d9c.html` |
| 16 | `programs/UNI-458ded82af` | 14 | `enforcement/case-mhlw_fraud_20240213_0fbf7a3d9c.html` |
| 17 | `programs/UNI-36200730f2` | 14 | `enforcement/case-mhlw_fraud_20240213_0fbf7a3d9c.html` |
| 18 | `programs/UNI-0e164be8f8` | 14 | `enforcement/case-mhlw_fraud_20240213_0fbf7a3d9c.html` |
| 19 | `programs/UNI-ext-87195d565a` | 13 | `enforcement/case-jbaudit_r03_2021-r03-0358-0_246.html` |
| 20 | `programs/UNI-ext-7d53de2a75` | 13 | `enforcement/case-jbaudit_r03_2021-r03-0304-0_229.html` |

Top-10 source files emitting the most broken links:

| # | source | broken hrefs |
|---|---|---|
| 1 | `index.html` | 10 |
| 2 | `enforcement/case-jbaudit_r05_2023-r05-0065-0_27.html` | 7 |
| 3 | `enforcement/case-jbaudit_r05_2023-r05-0065-0_18.html` | 7 |
| 4 | `enforcement/case-jbaudit_r05_2023-r05-0065-0_26.html` | 7 |
| 5 | `enforcement/case-jbaudit_r05_2023-r05-0368-0_230.html` | 7 |
| 6 | `enforcement/case-jbaudit_r03_2021-r03-0221-0_208.html` | 7 |
| 7 | `enforcement/case-jbaudit_r05_2023-r05-0350-0_217.html` | 7 |
| 8 | `enforcement/case-jbaudit_r03_2021-r03-0286-0_222.html` | 7 |
| 9 | `enforcement/case-jbaudit_r04_2022-r04-0281-1_216.html` | 7 |
| 10 | `enforcement/case-jbaudit_r03_2021-r03-0304-0_229.html` | 7 |

## Axis C · duplicate page candidates (top-10)

Total duplicate-content groups (scope = top-level + small dirs, excluding programs/laws/qa/cases/enforcement/cross/prefectures/cities/intel/per-prefecture audiences): **1**

Method: sha256 of the first 4 KB of each html outside the high-cardinality auto-gen trees. Files sharing a hash are emitted together — manual confirmation needed before treating any as redundant.

| # | members | sample (truncated) |
|---|---|---|
| 1 | 16 | `practitioner-eval/zeirishi.html`, `practitioner-eval/zeirishi_kessan.html`, `practitioner-eval/monitoring_pic.html`, `practitioner-eval/ma_valuation.html`, … (+12 more) |

## Axis D · sitemap drift

- `<loc>` entries in `sitemap*.xml` with **no corresponding file** under `site/`: **5**
- files present under `site/` but **not referenced from any sitemap**: **115**

Method: parse every `sitemap-*.xml` + `sitemap.xml` + `sitemap-index.xml`, normalize `<loc>` to relative path (`/foo` → `foo.html`, `/foo/` → `foo/index.html`), then cross with the file index.

Sitemap → missing file (top 10):

| # | sitemap URL (normalized) |
|---|---|
| 1 | `docs/api-reference.html` |
| 2 | `docs/exclusions.html` |
| 3 | `docs/faq.html` |
| 4 | `docs/getting-started.html` |
| 5 | `docs/mcp-tools.html` |

File → absent-from-sitemap (top dirs):

| dir | count |
|---|---|
| `docs/` | 38 |
| `en/` | 30 |
| `practitioner-eval/` | 17 |
| `security/` | 4 |
| `connect/` | 4 |
| `transparency/` | 3 |
| `compare/` | 3 |
| `dashboard/` | 2 |
| `trust/` | 2 |
| `widget/` | 2 |
| `audiences/` | 1 |
| `benchmark/` | 1 |
| `blog/` | 1 |
| `intel/` | 1 |
| `calculator/` | 1 |

## Axis E · mkdocs nav + exclude_docs integrity

- nav entries pointing at **nonexistent .md**: **0**
- `.md` files **not in nav and not excluded**: **0**
- `exclude_docs:` patterns with **no matching file**: **19**

`exclude_docs:` phantom patterns (top 15):

| # | pattern |
|---|---|
| 1 | `compliance/electronic_bookkeeping.md` |
| 2 | `cs_templates.md` |
| 3 | `disaster_recovery.md` |
| 4 | `monitoring.md` |
| 5 | `observability.md` |
| 6 | `solo_ops_handoff.md` |
| 7 | `assets/*.jsonld` |
| 8 | `overrides/` |
| 9 | `monitoring.md` |
| 10 | `observability.md` |
| 11 | `disaster_recovery.md` |
| 12 | `solo_ops_handoff.md` |
| 13 | `hiring_decision_gate.md` |
| 14 | `bench/` |
| 15 | `go_no_go_gate.md` |

## Method footnote

- HTML link regex: `href="([^"#?]+?)(?:[?#][^"]*)?"` (case-insensitive).
- External hosts (non-jpcite.com) are skipped from broken-link audit by design.
- `_templates/` `_assets/` `_data/` `og/` `static/` directories are excluded from orphan checks (they are not navigable pages).
- Auto-gen tree (programs/, laws/, qa/, cases/, enforcement/, cross/, prefectures/, cities/, intel/) is **fully included** in axis A/B/D; **excluded** from axis C (would generate noise rather than signal).
- Sitemap normalization: trailing `/` → `index.html`; bare paths get `.html` appended for resolution. URLs ending in `.xml/.txt/.json/.mcpb` checked literally.
- This is a **snapshot**, not a diff against the previous run.
- Per repo policy (`feedback_destruction_free_organization`): no files are renamed or deleted from this audit; remediation lands as a banner + index follow-up.
