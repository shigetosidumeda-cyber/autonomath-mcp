# MOAT: jpcite Stage 3 Application — Products A1 + A2 (2026-05-17)

> Internal design + moat docs for the first 2 paid Stage 3 products that land on top of the moat lane substrate (HE-2 + N3 + N4 + N6 + N7 + N8). All numbers are F4 tier-D pricing band. NO LLM. Scaffold-only. §52 / §47条の2 disclaimer everywhere.

## TL;DR

| product | tool_name | tier | price | value_proxy LLM cost | composed lanes |
| --- | --- | --- | --- | --- | --- |
| A1 — 税理士月次決算 Pack | `product_tax_monthly_closing_pack` | D | ¥1,000/req or ¥100/houjin/月 | ¥3,000-15,000 | HE-2 + N3 + N4 + N6 + N8 |
| A2 — 会計士監査調書 Pack | `product_audit_workpaper_pack` | D | ¥200/req | ¥5,000-15,000 | HE-2 + N3 + N7 |

* 18 tests PASS (`tests/test_product_a1_a2.py`).
* mypy strict 0 errors on product modules.
* ruff 0 errors on product modules.
* `tests/test_no_llm_in_production.py` still 10/10 PASS (CI guard for `anthropic` / `openai` / `google.generativeai`).

## Why "Application products"?

Stage 1 / 2 of the jpcite moat surface (cohort revenue model 8 cohorts + 21 moat lanes M1-M11 + N1-N9) shipped **retrieval primitives**. Each ¥3/req call returns 1 lane's worth of data. Stage 3 begins the **composition layer**: a single MCP call that wraps multiple lanes into a **completed artifact draft** (workpaper / packet / pack) priced by output, not by retrieval depth.

The composition layer is the moat. The retrieval primitives are commodities; the way we wire them, fan out concurrently, deduplicate citations, attach the right §-disclaimer, and price the bundle deterministically — that is what an LLM-only competitor cannot replicate at the same cost / latency / legal-safety triple.

## Tier-D pricing band (F4 design)

Tier-D is the "complete artifact draft" band:

* **Tier S** = ¥3/req (retrieval primitives, M1-M11 + N1-N9). This is the canonical baseline.
* **Tier A** = ¥30-60/req (HE-1 / HE-2 / HE-3 / HE-4 composition endpoints — 1 artifact-flavored payload).
* **Tier D** = ¥100-1,000/req (full product packs — 月次決算 / 監査調書 / 補助金 ロードマップ etc.).

Pricing intuition for A1:

* HE-2 single call (¥30-60 tier A) returns a generic workpaper scaffold.
* A1 = HE-2 + N3 + N4 + N6 + N8 wrapped + deterministic 月次決算-specific composition + warnings + next_actions + recipe summary + dual-disclaimer envelope. The added value is the **complete 月次決算 substrate** + Tier-D pricing reflects the bundle.
* ¥100/houjin/月 = subscription discount path so 顧問先 20 法人 × ¥100 = ¥2,000/月 makes the math work for a solo tax accountant.

Pricing intuition for A2:

* 監査調書は per-houjin の頻度が低い (年 1-4 回) ので subscription envelope は出さず per-call only.
* ¥200/req は 1 法人 1 監査期の調書 skeleton を 60 sample + 4 区分 + 5 軸 + 3 リスク + 業界 benchmark で構成するための minimum sustainable price.

## Composition graph

```
A1 (product_tax_monthly_closing_pack)
├── HE-2 prepare_implementation_workpaper(artifact_type='gessji_shiwake')
│   └── (internally fans out N1 + N2 + N3 + N4 + N6 + N9)
├── N3 walk_reasoning_chain(category='corporate_tax|consumption_tax')
├── N4 find_filing_window(kind='tax_office')
├── N6 am_amendment_alert_impact (horizon=90d)
└── N8 recipe_tax_monthly_closing.yaml (read-only file load)

A2 (product_audit_workpaper_pack)
├── HE-2 prepare_implementation_workpaper(artifact_type='kansa_chosho')
├── N3 walk_reasoning_chain(category='corporate_tax|commerce|labor')
└── N7 get_segment_view(JSIC × size_band × prefecture) — auto-resolved from houjin facts
```

Both products use `asyncio.gather` to fan out lane fetches in parallel — the cold-path latency is dominated by the slowest single-lane DB query, not by the sum of all lane queries.

## Why this is a moat (not just a thin wrapper)

1. **§52 / §47条の2 boundary** — the disclaimer envelope is jurisprudence-aware. It mentions the specific 業務独占 article + the specific 監査基準 / 通達 / 一次資料 anchor list. An LLM-only competitor would either generate disclaimer text (hallucination risk) or omit it (legal liability).
2. **Deterministic skeleton** — the 13 PL accounts (A1) / 4 workpaper sections (A2) / 5 J-SOX axes / 4 opinion buckets / 3 risk axes / sampling table values are **fixed by 監査基準**. There is no LLM judgment involved; the legal accuracy is mechanical.
3. **N6 alert × N7 segment cross-join** — the alert impact_score + segment_view popularity_rank surfaces are precomputed in `data/autonomath.db` (~9.4 GB). No LLM can rebuild this corpus per-call.
4. **¥100/houjin/月 subscription envelope** — 顧問先 fan-out at zero marginal LLM cost. Each rerun within month is free. An LLM-only competitor pays the token cost every rerun.
5. **N8 recipe traceability** — the `recipe_tax_monthly_closing.yaml` 13-step machine-readable plan is surfaced in the response so the agent can replay every step independently if any single lane fails. This is **process moat** on top of data moat.

## Cost saving math (per-case, not ARR)

### A1 case 1 — 中小企業 1 法人 / 月

| approach | cost / 月 | annual |
| --- | --- | --- |
| Claude Opus 4.7 only (1-pass, 1.5M input + 50K output tokens × $15/$75 per MTok) | ~¥4,000 / month | ¥48,000 / year |
| Claude Opus 4.7 + 3-pass review | ~¥12,000 / month | ¥144,000 / year |
| jpcite A1 per-call | ¥1,000 / month | ¥12,000 / year |
| jpcite A1 subscription (¥100/houjin/月) | ¥100 / month | ¥1,200 / year |

Saving against the low-LLM-cost baseline: **67-91%** (per-call vs subscription).

### A2 case 1 — 公認会計士 1 法人 1 監査期

| approach | cost / engagement |
| --- | --- |
| Claude Opus 4.7 1-pass (2.5M input + 80K output tokens) | ~¥5,000 |
| Claude Opus 4.7 + 3-pass review | ~¥15,000 |
| jpcite A2 | ¥200 |

Saving: **96-98.7%**.

> Note: per memory `feedback_cost_saving_per_case_not_roi`, we express saving as per-case vs. pure LLM cost, never as ROI / ARR / TAM. The numbers above are the canonical surface for sales copy.

## File map

| path | role |
| --- | --- |
| `/Users/shigetoumeda/jpcite/src/jpintel_mcp/mcp/products/__init__.py` | Submodule registry + auto-import. |
| `/Users/shigetoumeda/jpcite/src/jpintel_mcp/mcp/products/product_a1_tax_monthly.py` | A1 implementation. |
| `/Users/shigetoumeda/jpcite/src/jpintel_mcp/mcp/products/product_a2_audit_workpaper.py` | A2 implementation. |
| `/Users/shigetoumeda/jpcite/tests/test_product_a1_a2.py` | 18 tests (8 A1 + 7 A2 + 3 boundary). |
| `/Users/shigetoumeda/jpcite/docs/products/A1_zeirishi_monthly_pack.md` | Sales-grade A1 docs. |
| `/Users/shigetoumeda/jpcite/docs/products/A2_kaikeishi_audit_pack.md` | Sales-grade A2 docs. |

## Server.py wiring

`src/jpintel_mcp/mcp/server.py` line ~9685 imports the products package alongside `autonomath_tools` and `moat_lane_tools`. The 2 new MCP tools register on import via the `@mcp.tool` decorator. No manifest bump in this commit — verify with `len(await mcp.list_tools())` post-deploy and bump in the next intentional release.

## Future products (Stage 3 roadmap)

* **A3** — 補助金 ロードマップ 3 年 (`product_subsidy_roadmap_pack`) — Tier-D ¥500/req. composed_lanes = HE-2 + N2 + N6 + recipe_subsidy_application_draft.
* **A4** — 36協定 / 就業規則 pack (`product_shuugyou_kisoku_pack`) — gated behind `AUTONOMATH_36_KYOTEI_ENABLED` per launch gate decision.
* **A5** — 設立登記 pack — 司法書士 cohort.
* **A6** — DD pack — M&A cohort.

Each new Stage 3 product = 1 new file in `src/jpintel_mcp/mcp/products/` + 1 new test file + 1 new sales-grade doc + entry in the products `__init__.py` registry.

## Anti-patterns avoided

* Never imported `anthropic` / `openai` / `google.generativeai` (CI guard `tests/test_no_llm_in_production.py` enforces).
* Never reused the `tier-badge` / "Pro plan" / "Starter plan" UI strings (CLAUDE.md non-negotiable).
* Never claimed the draft is a finished filing — every disclaimer + every `next_actions` step references 士業 verification.
* Never bypassed `--no-verify` / `--no-gpg-sign` — `safe_commit.sh` wrapper used.
* Never bumped manifests prematurely — runtime tool count drifts naturally; intentional bump deferred to next release.

last_updated: 2026-05-17
