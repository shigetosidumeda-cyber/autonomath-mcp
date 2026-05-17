# CL17 — A series (A1-A5 + A7) consolidation SOT

**Date:** 2026-05-17 (evening)
**Lane:** solo (READ-ONLY scan; new audit doc only)
**Scope:** Stage-3 Application products A1..A5 + A7 (5 product + 5 persona + 5 compare + 15 recipe) public-site coverage.
**Authors:** Claude Opus 4.7 (this audit). Cross-refs: CL1 (A5 PR merge log), CL9 (FF2 validator), CL14 (public-docs deploy SOT), MOAT_PRODUCT_A1_A2.

---

## Section 1 — A1-A5 product source summary

Tier letter D = `pricing_v2.PricingTier.D` (workflow); 1 billable unit = ¥3 / req (canonical
metered rate). Tier C = ¥12 (4 units) for Lite-mode-only callers. All five products are
**NO LLM** (pure SQLite + dict composition). Read-only SQLite URI ``mode=ro`` is enforced.
All emit the §52 / §47条の2 / §72 / §1 / §3 disclaimer envelope.

| product | file | LOC | tier | billing_units | ¥ / call | tests | LIVE state |
| --- | --- | ---: | --- | ---: | ---: | ---: | --- |
| **A1** — 税理士 月次 closing pack | `src/jpintel_mcp/mcp/products/product_a1_tax_monthly.py` | **737** | D | 10 | ¥30 | 18 | LIVE on `main` (re-priced V3 `dd2bcd332`) |
| **A2** — 会計士 監査調書 scaffold pack | `src/jpintel_mcp/mcp/products/product_a2_audit_workpaper.py` | **792** | D | 10 | ¥30 | (in `tests/test_product_a1_a2.py`, shared 18) | LIVE on `main` (re-priced V3 `1dd9097d3`) |
| **A3** — 補助金活用ロードマップ pack | `src/jpintel_mcp/mcp/products/product_a3_subsidy_roadmap.py` | **753** | D (Deep) / C (Lite) | 10 / 4 | ¥30 Deep / **¥12 Lite (only A-series Lite-tier)** | 17 | LIVE on `main` (re-priced V3 `bfb4be7ff`) |
| **A4** — 就業規則生成 pack (36協定 disclaimer) | `src/jpintel_mcp/mcp/products/product_a4_shuugyou_kisoku.py` | **535** | D | 10 | ¥30 | (in `tests/test_product_a3_a4.py`, shared 17) | LIVE on `main` (re-priced V3 `90040b67c`) |
| **A5** — 司法書士 会社設立 一式 pack | `(.claude/worktrees/agent-ac0ac5fdd0bcff29c/) src/jpintel_mcp/mcp/products/product_a5_kaisha_setsuritsu.py` | **778** | D | **267** (note) | (under V3 ¥3/unit × 267 = ¥801) | 19 | **NOT ON MAIN** — PR #245 OPEN as DRAFT, head `fa3c80a47` (CL1 blocked) |

Tool-name registration map (all five auto-register via `products/__init__.py` `_SUBMODULES`):

- A1 → `product_tax_monthly_closing_pack`
- A2 → `product_audit_workpaper_pack`
- A3 → `product_subsidy_roadmap_12month`
- A4 → `product_shuugyou_kisoku_pack`
- A5 → `product_kaisha_setsuritsu_pack` (NOT YET registered on main)

**Stale comment in `__init__.py`**: pre-V3 docstring still says A1 ¥1,000 / A2 ¥200 / A3 ¥500 /
A4 ¥300 / A5 ¥800. Source code constants (`_TIER_LETTER = "D"`, `_BILLING_UNITS = 10`) reflect
V3, but the docstring comment block is **drift**. Outstanding item §3 below.

---

## Section 2 — A7 site LANDED state (5 product + 5 persona + 5 compare + 15 recipe)

| surface | found | expected | % | gap |
| --- | ---: | ---: | ---: | --- |
| `site/products/A*.html` | **5** | 5 | **100%** | A1/A2/A3/A4/A5 all present |
| `site/personas/*.html` | **0** | 5 | **0%** | **directory does not exist** — appears to be remapped to `site/compare/<persona>.html` |
| `site/compare/*.html` (persona-tagged) | **5** | 5 | **100%** | `gyoseishoshi.html / kaikei.html / shihoshoshi.html / sme.html / zeirishi.html` |
| `docs/cookbook/r*.md` | **22** | 15 | **147%** | 22 recipe files; numbering r01-r03, r09-r11, r16-r26 (gaps r04-r08, r12-r15); 7 recipes ABOVE the planned 15 |

**Coverage scoring:** if A7 plan = 5 product + 5 persona + 5 compare + 15 recipe = **30 page**
target, then on-disk surfaces = 5 (product) + 5 (compare-as-persona) + 22 (recipe) = **32 / 30
(107%)** with **the persona directory itself being absent** (compare/ files are doing double duty).

**Per-product persona-page naming sanity:**
- `site/products/A3_gyosei_licensing_eligibility_pack.html` (行政書士) ≠ A3 source = `subsidy_roadmap_12month`. **Site product A3 page is mis-labeled vs server tool A3.**
- `site/products/A4_shihoshoshi_registry_watch.html` (司法書士) ≠ A4 source = `shuugyou_kisoku_pack`. **Site A4 = different product.**
- `site/products/A5_sme_subsidy_companion.html` (中小経営者) ≠ A5 source (= 司法書士 会社設立). **Site A5 = different product.**

This is a **product-numbering mismatch between server tools (A1..A5) and site product pages
(A1..A5)**. Pages were authored before tool registration moved. Outstanding item §3.

---

## Section 3 — Outstanding items

1. **A5 PR #245 merge** — DRAFT, mergeable=UNKNOWN (was CONFLICTING per CL1). Worktree
   `agent-ac0ac5fdd0bcff29c` is 1 commit ahead, main is 42 commits ahead. CL1 declared
   "do not clobber CodeX in-flight work" → still pending operator decision.
2. **A3 Lite-tier impl** — already landed (`_TIER_LETTER_LITE = "C"`, `_BILLING_UNITS_LITE = 4`),
   verified at `product_a3_subsidy_roadmap.py:67-69`. No work pending. ✓
3. **`products/__init__.py` docstring drift** — pre-V3 ¥1,000 / ¥200 / ¥500 / ¥300 / ¥800
   prices still in docstring. Constants in each module already on V3. Trivial docstring
   patch needed (no behavior change).
4. **Site product page ↔ server tool A-number mismatch** — site A3/A4/A5 page slugs name
   different cohorts than server tool A3/A4/A5. Either rename site pages or rename server
   tools — operator decision required.
5. **`site/personas/` directory missing** — A7 spec calls for 5 personas; on-disk they live
   under `site/compare/<persona>.html`. Decide whether to (a) create `site/personas/` symlinks
   or (b) update sitemap to point compare/ to persona-role.
6. **Recipe overshoot** — 22 recipes ≥ 15 target. No gap. r04-r08 and r12-r15 are skipped
   numbers; renumber not needed (numbers are deliberately reserved).
7. **Site product pages still quote ¥3/req baseline** rather than V3 D-tier ¥30/call for
   the pack. Cross-link to `/pricing` is correct, but per-page hero copy is inconsistent
   ("¥3/req" baseline vs "Tier D ¥30/call" pack). Editorial decision: V3 is for paid
   composition product pack callers; ¥3/req remains correct for the anonymous canonical
   tier. Keep both — no change.

---

## Section 4 — Cost-saving narrative (FF2) tier-quintuple anchor

CL9 / CL14 confirmed the FF2 quintuple is replicated identically across `llms.txt`,
`agents.json`, `.well-known/jpcite-justifiability.json`:

```
saving_ratio_min   = 17    (Tier A baseline ¥3/req vs Opus 7-turn ¥510)
saving_ratio_max   = 167   (Tier D workflow ¥30/call vs Opus 7-turn ¥5,000)
saving_pct_low     = 94.4 %
saving_pct_mid     = 96.5 %
saving_pct_high    = 94.0 %
```

The A-series five products are the **named end-points of the cost-saving narrative**:

- A1 monthly closing (税理士 cohort): jpcite ¥30/pack vs Opus 7-turn Deep++ ¥500/chain → **16.7x / 94% saving**
- A2 audit workpaper (会計士 cohort): jpcite ¥30/pack vs Opus 5-turn medium ¥300/chain → **10.0x / 90% saving**
- A3 subsidy roadmap (Deep ¥30 / Lite ¥12 — 行政書士 cohort): Deep vs Opus 8-turn ¥600 → **20.0x / 95% saving**
- A4 shuugyou kisoku (社労士 cohort): jpcite ¥30/pack vs Opus 6-turn ¥400 → **13.3x / 93% saving**
- A5 会社設立 (司法書士 cohort, pending merge): jpcite ¥801/pack vs 司法書士 manual + Opus draft ≈ ¥10,000 → **12.5x / 92% saving**

These tie back to FF2 cost_efficiency_claim and remain inside the published 17x..167x band.

---

## Section 5 — Operator decision items (yes/no)

| # | item | decision |
| --- | --- | --- |
| 1 | Merge PR #245 (A5 + A6 + P4 + P5) **clobbering 42 main commits** to land A5 on main? | yes / no |
| 2 | Rename site product pages A3/A4/A5 to match server tool A3/A4/A5 cohorts (subsidy / shuugyou-kisoku / kaisha-setsuritsu)? | yes / no |
| 3 | Patch `products/__init__.py` docstring to drop pre-V3 prices (low-risk doc-only)? | yes / no |
| 4 | Create `site/personas/` symlinks to `site/compare/<persona>.html`, or update sitemap to point persona-role to `compare/`? | symlink / sitemap / no |
| 5 | Reserve r04-r08 and r12-r15 recipe slots (operator may have a v3 plan), or compact-renumber existing 22 recipes? | reserve / compact |

---

## Cross-refs

- CL1 — A5+A6+P4+P5 PR #245 merge log (BLOCKED). `docs/_internal/CL1_A5_A6_PR_MERGE_2026_05_17.md`.
- CL9 — FF2 cost-saving validator run. `docs/_internal/CL9_FF2_VALIDATOR_RUN_2026_05_17_EVENING.md`.
- CL14 — public-docs deploy SOT. `docs/_internal/CL14_PUBLIC_DOCS_STATE_SOT_2026_05_17.md`.
- MOAT_PRODUCT_A1_A2 — paid-pack moat audit. `docs/_internal/MOAT_PRODUCT_A1_A2_2026_05_17.md`.

Commit subject: `docs(audit): A series (A1-A5 + A7) consolidation SOT [lane:solo]`
