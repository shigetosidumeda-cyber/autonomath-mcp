---
submission_form: https://clau.de/plugin-directory-submission
target_channel: Claude Desktop Extensions directory
prepared: 2026-04-23
status: DRAFT — submit post PyPI publish (#74)
---

# Anthropic External Plugins Directory — Submission Package

**BLOCKER**: submit only after `autonomath-mcp` v0.3.2 is live on PyPI (task #74). The
directory verifies `pip show` / `uvx` resolves before listing goes live.

## Form fields (copy-paste ready)

| Field | Value |
|-------|-------|
| Plugin name | `AutonoMath — 日本の制度 MCP` |
| Plugin slug | `autonomath-mcp` |
| Short description (< 80 chars) | `日本の制度 API — 11,684 searchable programs / 採択事例 / 融資 / 行政処分` |
| Tagline (EN, < 80 chars) | `Japanese public-program MCP — 11,684 searchable programs + 93 tools` |
| Long description | 下記テンプレ参照 |
| Category | Data / Government / Japan (primary: **Data**) |
| Publisher display name | `Bookyou 株式会社 (AutonoMath)` |
| Publisher website | `https://jpcite.com/` |
| Publisher contact email | `info@bookyou.net` |
| Public GitHub URL | `https://github.com/shigetosidumeda-cyber/autonomath-mcp` |
| Homepage URL | `https://jpcite.com/` |
| Docs URL | `https://jpcite.com/docs/` |
| Privacy policy URL | `https://jpcite.com/privacy.html` |
| Terms of service URL | `https://jpcite.com/tos.html` |
| 特商法表示 URL | `https://jpcite.com/tokushoho.html` |
| Invoice-registration number | `T8010001213708` |
| License | MIT |
| Supported clients | Claude Desktop (primary), Cursor, ChatGPT (MCP), Gemini |
| MCP protocol version | `2025-06-18` |
| Install command | `uvx autonomath-mcp` |
| Pricing model | Free tier 3 req/day per IP (JST next-day reset), ¥3/req tax-exclusive (¥3.30 tax-inclusive) metered beyond |
| Icon (256×256 PNG) | `https://jpcite.com/assets/mcp_preview_1.png` (fallback: favicon) |
| Tile image (1200×630) | `https://jpcite.com/assets/mcp_preview_1.png` |
| Wide tile (1600×900) | `https://jpcite.com/assets/mcp_preview_2.png` |
| .mcpb bundle | `https://jpcite.com/downloads/autonomath-mcp.mcpb` (2,296 bytes) |
| Data-collection disclosure | No PII; only server-side request logs (IP hash, latency, status) |
| Age rating | General |

## Long description (日本語)

AutonoMath は、日本の公的制度データ (補助金・融資・税制・認定) 検索対象 11,684 件
(総件数 14,472) + 採択事例 2,286 件 + 融資 108 件 + 行政処分 1,185 件 を横断検索できる
MCP サーバです。FastMCP (protocol 2025-06-18) の stdio で動作し、Claude Desktop
などの MCP クライアントから 93 tools (search / get × 4 データセット、
batch_get、181 件の排他/前提条件ルール、meta) を直接呼び出せます。

特徴:

- **4 データセット横断**: `search_programs`, `search_case_studies`,
  `search_loan_programs`, `search_enforcement_cases` を 1 サーバで提供
- **融資の三軸分解**: 担保 / 個人保証人 / 第三者保証人 を独立 enum 化し、
  「無担保・無保証」求人を JP prose parsing なしで抽出可能
- **181 排他/前提条件ルール**: `check_exclusions(program_ids=[...])`
  で併給不可・前提条件の違反ペアを返す
- **一次資料 lineage**: 全行に `source_url` + `fetched_at`。MAFF / METI /
  日本政策金融公庫 / 47 都道府県公報 / 会計検査院 を primary source
  とし、aggregator URL は banned
- **無料枠 3 req/day per IP (登録不要、JST 翌日リセット)**、¥3/req 税別 / ¥3.30 税込 従量 (Stripe 従量請求)

## Long description (English)

AutonoMath is an MCP server for querying Japanese public-program data:
11,684 searchable programs (14,472 total; subsidies / loans / tax incentives / certifications),
2,286 case studies (採択事例), 108 loan programs with three-axis risk
decomposition (collateral / personal guarantor / third-party guarantor),
and 1,185 enforcement cases (会計検査院 findings). A 181-rule
exclusion / prerequisite checker (22 agri + 13 non-agri) resolves
co-application conflicts. Every row carries primary-source URL + fetched_at;
aggregators are banned.

93 tools over MCP protocol `2025-06-18`, FastMCP stdio. Anonymous 3 req/day
per IP free (JST next-day reset); ¥3/req tax-exclusive (¥3.30
tax-inclusive) metered thereafter. Self-serve — no sales, no tiers.

Evidence Pre-fetch / precomputed intelligence means source URLs, fetched timestamps,
exclusion-rule checks, and cross-dataset joins are prepared for retrieval. It is
evidence packaging, not model-cost savings.

## Representative Tools

1. `search_programs` — 11,684 searchable 制度の横断検索 (14,472 total; q, prefecture, target_types, program_kind, min_amount)
2. `get_program` — `unified_id` で詳細取得
3. `batch_get_programs` — 最大 50 件 `unified_id` を 1 call で resolve
4. `search_case_studies` — 2,286 採択事例検索
5. `get_case_study` — 採択事例詳細
6. `search_loan_programs` — 108 融資検索 (三軸フィルタ)
7. `get_loan_program` — 融資詳細
8. `search_enforcement_cases` — 1,185 行政処分検索
9. `get_enforcement_case` — 行政処分詳細
10. `list_exclusion_rules` — 181 併給不可 / 前提条件ルール
11. `check_exclusions` — `program_ids` から違反ペア・前提条件を返す
12. `get_meta` — 件数 / 最終更新 / tier カバレッジ

## Pre-submission checklist (human)

- [ ] `autonomath-mcp` v0.3.2 を PyPI に publish (`python -m build && twine upload`)
- [ ] `uvx autonomath-mcp --version` が別マシンで動くことを確認
- [ ] GitHub repo `shigetosidumeda-cyber/autonomath-mcp` が public (LICENSE / README / CHANGELOG 揃う)
- [ ] `/downloads/autonomath-mcp.mcpb` が Cloudflare Pages で HTTP 200
- [ ] `https://jpcite.com/privacy.html` / `/tos.html` / `/tokushoho.html` が reachable
- [ ] `https://api.jpcite.com/v1/meta` が 200 で新しい件数を返す
- [ ] Claude Desktop で .mcpb を double-click → 93 tools 認識 (スクリーンショット取得)
- [ ] 上記スクリーンショットを form の動作確認欄に添付

## Expected review

- Review: Anthropic review, typically **2-4 週間** per `docs/_internal/mcp_registry_submissions/README.md`
- Post-acceptance: listing appears at `clau.de/directory` (or equivalent) + badge eligible
- Rejection risks:
  - PyPI package name mismatch → fix by `python -m build` from a clean tree
  - `.mcpb` bundle expired → rebuild via `scripts/build_mcpb.sh`
  - Privacy policy missing APPI 26/28 language → already addressed in task #70

## Assets generated

- `/dxt/manifest.json` — DXT 0.1 manifest, 93 tools, version 0.3.2
- `/site/downloads/autonomath-mcp.mcpb` — 2,296 byte zip (manifest.json only; uvx-based reference install)
- `/scripts/build_mcpb.sh` — rebuilder; version-matches pyproject/server/manifest before zipping
- `/site/assets/mcp_preview_1.png` — 1200×630 tile (terminal-style search + exclusion demo)
- `/site/assets/mcp_preview_2.png` — 1600×900 wide tile

## Submission URL

`https://clau.de/plugin-directory-submission` (human fills form; copy-paste fields above)
