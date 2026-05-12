# STATE — Wave 46 tick#4 (永遠ループ) audiences cost-saving PR

Status: PROPOSED · Generated: 2026-05-12 · Branch:
`feat/jpcite_2026_05_12_wave46_audiences_cost_saving`

PR#: pending (open after admin merge of tick#3 #151 already landed; this is
the next consumer of the canonical doc `docs/canonical/cost_saving_examples.md`).

## 1. Scope (3 audience pages)

Wave 46 tick#3 landed pricing + compare cost-saving framing on 2026-05-12
(PR #151). tick#4 extends the same "純 LLM vs jpcite ¥3/req" framing to the 3
highest-traffic audience pages so the saving figures users see on each
audience landing match the canonical doc.

Pages touched (3 files):

- `site/audiences/ma_advisor.html`
- `site/audiences/cpa_firm.html`
- `site/audiences/shindanshi.html`

Out of scope (deliberate): the other 14 audience pages
(`construction.html` / `tax-advisor.html` / `shihoshoshi.html` / `vc.html`
/ `journalist.html` / `manufacturing.html` / `real_estate.html`
/ `shinkin.html` / `shokokai.html` / `smb.html`
/ `subsidy-consultant.html` / `dev.html`
/ `admin-scrivener.html` / `index.html`) keep the existing baseline
framing for now and will be cleaned in subsequent ticks of this loop.
Reason: dual-CLI lane atomicity (mkdir guard) + smaller verified diff.

## 2. Per-page saving table

Headline cost-saving figures advertised on each audience landing
(consistent with `docs/canonical/cost_saving_examples.md` token-cost
model: 純 LLM token 単価 ¥300/1M, jpcite ¥3/req tax-excluded).

| audience | unit | 純 LLM コスト | jpcite ¥3/req | 節約 / unit | rough off |
|----------|------|---------------|---------------|-------------|-----------|
| ma_advisor (M&A advisor) | 1 deal × 50 req | ¥15,000/deal | ¥150/deal | **¥14,850/deal** | ~99% |
| cpa_firm (公認会計士事務所) | 月次 100 社 × 5 req = 500 req/月 | ¥150,000/月 | ¥1,500/月 | **¥148,500/月** | ~99% |
| shindanshi (中小企業診断士) | 月次 30 顧問 × 10 req = 300 req/月 | ¥90,000/月 | ¥900/月 | **¥89,100/月** | ~99% |

### 2.1 Per-page task breakdown (top of the new Cost saving calculator table)

`ma_advisor.html` (1 deal × 50 req, sums to ¥150 jpcite / ¥15,000 LLM):

| # | task | 純 LLM ≈ | jpcite | 節約 |
|---|------|----------|--------|------|
| 1 | 法人 360° (対象会社 surface) | ¥4,500/deal | 15 req ¥45 | ¥4,455/deal |
| 2 | DD deck 作成 | ¥2,700/deal | 9 req ¥27 | ¥2,673/deal |
| 3 | 補助金返還義務 chain | ¥3,000/deal | 10 req ¥30 | ¥2,970/deal |
| 4 | 業法 fence 検証 | ¥2,400/deal | 8 req ¥24 | ¥2,376/deal |
| 5 | 事業承継 制度 mapping | ¥2,400/deal | 8 req ¥24 | ¥2,376/deal |
| Σ | (1 deal × 50 req) | ¥15,000/deal | ¥150/deal | **¥14,850/deal (~99% off)** |

`cpa_firm.html` (月次 100 社 × 5 req = 500 req/月):

| # | task | 純 LLM ≈ | jpcite | 節約 |
|---|------|----------|--------|------|
| 1 | 措置法 42-4 lookup | ¥30,000/月 | 100 req ¥300 | ¥29,700/月 |
| 2 | IT 導入補助金 会計処理 dual check | ¥40,000/月 | 100 req ¥300 | ¥39,700/月 |
| 3 | 被監査会社 DD question deck | ¥35,000/月 | 100 req ¥300 | ¥34,700/月 |
| 4 | 行政処分歴 filter | ¥30,000/月 | 100 req ¥300 | ¥29,700/月 |
| 5 | 監査調書 template scaffold | ¥15,000/月 | 100 req ¥300 | ¥14,700/月 |
| Σ | (月次 100 社 × 5 req) | ¥150,000/月 | ¥1,500/月 | **¥148,500/月 (~99% off)** |

`shindanshi.html` (月次 30 顧問 × 10 req = 300 req/月):

| # | task | 純 LLM ≈ | jpcite | 節約 |
|---|------|----------|--------|------|
| 1 | 月次 saved search (30 顧問) | ¥24,000/月 | 90 req ¥270 | ¥23,730/月 |
| 2 | eligibility chain | ¥18,000/月 | 60 req ¥180 | ¥17,820/月 |
| 3 | renewal forecast | ¥24,000/月 | 60 req ¥180 | ¥23,820/月 |
| 4 | 補完制度 探索 | ¥12,000/月 | 45 req ¥135 | ¥11,865/月 |
| 5 | 申請 kit scaffold | ¥12,000/月 | 45 req ¥135 | ¥11,865/月 |
| Σ | (月次 30 顧問 × 10 req) | ¥90,000/月 | ¥900/月 | **¥89,100/月 (~99% off)** |

## 3. Replaced surface text (audit log)

For each page, the following 4 elements were replaced consistently:

- `<meta name="description">` — old ROI / delta framing → "節約 ¥… (約 99% off)"
- `<meta property="og:description">` — same swap
- JSON-LD FAQ "コストは?" answer — same swap, new saving line + 99% off note
- Main `<section class="features" aria-labelledby="roi-title">` → renamed
  `aria-labelledby="cost-saving-title"`. The `<h2>` heading is now
  "Cost saving calculator (... 純 LLM vs jpcite ¥3/req)". The 5-task table
  columns become `task / 純 LLM コスト (baseline) / jpcite ¥3/req / 節約 ¥/...`.
  The trailing footnote replaces ROI multiplier language with the
  ¥300/1M token unit-price assumption and the "削減保証ではない" disclaimer.

Out of scope on these pages (preserved untouched):

- hero / breadcrumb / fence section
- MCP install snippet (Claude Desktop config)
- CTA buttons (`?src=audiences_*` query params remain)
- legal-note footer (業法 fence 文言 unchanged)
- JSON-LD Service / Offer / FAQPage other Q&A nodes (only the cost answer
  was edited)
- common JSON-LD `@graph` org + price block

## 4. Tests

New: `tests/test_audiences_cost_saving.py` — 10 tests, all PASS locally
(`/Users/shigetoumeda/jpcite/.venv/bin/pytest`, Python 3.13.12):

1. `test_canonical_doc_exists`
2. `test_no_roi_arr_yarn_framing` (ROI / ARR / 射程 0-grep gate on 3 pages)
3. `test_each_page_has_cost_saving_section`
4. `test_each_page_saving_amount_present_and_in_doc`
5. `test_each_page_links_to_canonical_doc`
6. `test_brand_consistency` (legacy 税務会計AI / AutonoMath / zeimu-kaikei.ai 0)
7. `test_unit_price_constant` (¥3 + 従量 wording present)
8. `test_structural_anchors_intact` (hero/fence/cost-saving/install/cta)
9. `test_html_parses_clean` (stdlib html.parser, 0 errors per file)
10. `test_each_page_h2_count_preserved` (exactly 4 h2 per page)

Result: `10 passed in 0.94s`.

## 5. Verify gates (バグなし)

- `grep -cE "(ROI|ARR|射程|roi-title)" site/audiences/{ma_advisor,cpa_firm,shindanshi}.html`
  → 3 × 0 (no leak)
- `grep -cE "(zeimu-kaikei|税務会計AI|AutonoMath|autonomath\.ai)" site/audiences/{ma_advisor,cpa_firm,shindanshi}.html`
  → 3 × 0 (no legacy brand leak)
- stdlib `html.parser` on all 3 files → 0 errors, h2 = 4 each, h3 = 0
- `pytest tests/test_audiences_cost_saving.py` → 10/10 PASS

## 6. Files in this PR

- `site/audiences/ma_advisor.html` (modified)
- `site/audiences/cpa_firm.html` (modified)
- `site/audiences/shindanshi.html` (modified)
- `tests/test_audiences_cost_saving.py` (new, ~220 LOC)
- `docs/research/wave46/STATE_w46_tick_audiences_pr.md` (this file, new)

No file rm/mv (破壊なき整理整頓ルール 遵守). No main worktree usage
(dual-CLI lane atomic via `mkdir /tmp/jpcite-w46-audiences-cost.lane`).
No LLM API import added.

## 7. Loop continuation

The remaining audience pages (14 files) can be cleaned in subsequent ticks
of this loop, each chunk ≤ 3 files to keep PR diff reviewable and lane
atomicity intact. Priority order suggested for the next tick:

1. `tax-advisor.html` (税理士) — case 1 base = ¥15,300/月 already canonical
2. `subsidy-consultant.html` (補助金コンサル) — case 6 base = ¥8,160/月
3. `shihoshoshi.html` (司法書士) — derive from case 6 + 法務 weighting

After all 17 audience pages, follow up with `industry/*.html` and `roles/*.html`
sweeps if those exist.
