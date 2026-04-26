# MCP Registry Submissions — 提出チェックリスト

Launch 2026-05-06。本ディレクトリは各 registry への提出 draft を格納する。
**実送信は行わない**。rebrand 確定 → `scripts/rebrand_mcp_entries.sh --apply` →
本人が手動でボタンを押す。

---

## 対象 registry (8 候補 → viable 6 + 断念 2)

| # | Registry | Method | Status | ファイル |
|---|----------|--------|--------|---------|
| 1 | **Official MCP Registry** | `mcp-publisher` CLI | ACTIVE | `official_registry_submission.md` |
| 2 | **glama.ai** | GitHub auto-crawl | ACTIVE | `glama_submission.md` |
| 3 | **modelcontextprotocol/servers** (GitHub) | ~~PR~~ → **第三者提出は廃止** | DEAD for us | `modelcontextprotocol_pr.md` (経緯のみ) |
| 4 | **Smithery** | `smithery.yaml` + claim | ACTIVE | `smithery_submission.md` |
| 5 | **Claude Desktop Extensions** | .mcpb bundle + `clau.de/plugin-directory-submission` | ACTIVE (高バリア) | `anthropic_external_plugins.md` |
| 6 | **Cursor Directory** | `cursor.directory/plugins` Submit | ACTIVE | `cursor_windsurf_submission.md` |
| 6b | **Windsurf (Codeium)** | no directory — Official Registry 経由 + community post | PROPAGATE | `cursor_windsurf_submission.md` |
| 7 | **Continue Hub** | `hub.continue.dev` (submission 経路不明瞭) | **要 2026-04 再確認** | 下記参照 |
| 8 | **Cline** | install-via-config のみ、registry なし | NO REGISTRY | README install 節で対応 |
| + | **mcphub.tools** | (Cloudflare Registrar parked page) | DEAD | `mcphub_tools_submission.md` |

**Task #29 の非重複 registry** (`scripts/mcp_registries.md`): PulseMCP、Awesome
MCP Servers PR、MCP Market、MCP Hunt、MCP Server Finder、mcp.so、mcpservers.org。

## Rebrand 前にできる / できない

**できない (rebrand blocked)**: placeholder 置換・PyPI/npm 公開・GitHub 本稼働 URL 公開・Glama 自動 index。

**できる (今)**: draft review・LICENSE 追加・demo.svg 最適化・CI workflow draft・弁理士 商標 調査 (`project_jpintel_trademark_intel_risk`)。

rebrand 確定後: `scripts/rebrand_mcp_entries.sh --apply --vars=scripts/rebrand_vars.env`。

---

## 提出順 (launch plan)

**Easy wins first** (user's memory: 成功確率を上げる方向だけ)。

### D-7 (準備)
- 弁理士 確認完了 → rebrand variables 確定 → `rebrand_vars.env` 作成
- `scripts/rebrand_mcp_entries.sh --apply` で一括置換
- LICENSE、最終 README 確認、`v0.1.0` tag 準備

### D-0 (2026-05-06, 当日): Easy / Auto
1. **Glama** — repo public にするだけ。form 無し。~24h で index。
2. **Official MCP Registry** — `mcp-publisher login github` → `mcp-publisher publish`。即時。
3. **PulseMCP** — #2 が propagate する。何もしない。7日待機。
4. **mcp.so** — GitHub issue template 提出、5分。
5. **mcpservers.org** — 5 field form 提出、free tier only ($39 premium は**不可**)、5分。
6. **MCP Hunt** (mcphunt.com) — form + upvote 調整。15分。

### D+3: Manual form
7. **MCP Market** — form (name / repo / description / category)、10分。
8. **Cursor Directory** — `cursor.directory/plugins` Submit 経由。10分。
9. **MCP Server Finder** — email 提出 to `info@mcpserverfinder.com`、5分。

### D+7: PR-based / heavier
10. **Awesome MCP Servers PR** — `punkpeye/awesome-mcp-servers` Finance 節に 1 行追加 PR (emoji 🤖🤖🤖 で agent fast track)。20分。
11. **Smithery** — claim flow、`smithery.ai/new` で repo URL 貼付。10分 + 1-3 業務日 review。
12. **Claude Desktop Extensions** — interest form 提出 + .mcpb bundle 準備 (`dxt` CLI で package 作成)。review は 数週間。
13. **Continue Hub** — 2026-04 時点で public submission 経路が不明瞭。`hub.continue.dev` 再確認、submission 経路があれば提出、無ければ skip。

### ToS / 有料 placement (**全部拒否**)
- mcpservers.org $39 premium: **skip**
- Smithery Hosted (managed cloud exec): **skip**
- 排他契約 / revenue share を要求する registry: **skip + 本 doc に追記**

---

## Registry 別 content must-haves

| Registry | Description 制限 | Screenshot | Logo | その他 |
|----------|-----------------|-----------|------|--------|
| Official Registry | 説明は JSON 内 free、`_meta` publisher-provided ≤ 4 KB | 任意 | 任意 | namespace `io.github.*` 必須 |
| Glama | README から抽出、200-500 字推奨 | `site/assets/demo.svg` 埋込 | `site/assets/mark.svg` | tools 表の h2/h3 headings 必須 |
| Smithery | metadata.description ≤ 280 字 | metadata.icon URL | SVG 可 | configSchema 型正当性 |
| Cursor Directory | < 200 字 | 推奨 PNG 1200×630 | icon 256×256 | カテゴリ必須 |
| Awesome MCP Servers | 1 行 < 160 字 | 不要 | 不要 | emoji legend 遵守 |
| MCP Market | 300-500 字 | 推奨 | 推奨 | tag は自由記述 |
| Claude Desktop Ext. | manifest.json (DXT 規格) | 不要 (icon で代替) | PNG 256×256 必須 | .mcpb bundle |

既存素材:
- `site/assets/demo.svg` (6.4 KB 動画 SVG、15s loop)
- `site/assets/mark.svg` (SVG logo)
- `site/assets/favicon.svg`, `apple-touch-icon.png`, `og.png`
- `site/assets/mcp_preview_1.png` (1200×630、72 KB、OG/Glama tile 用) — 2026-04-23 生成
- `site/assets/mcp_preview_2.png` (1600×900、94 KB、Cursor / Smithery tile 用) — 2026-04-23 生成

**画像 alt-text / caption** (登録フォームで貼る文言、コピペ用):

| 画像 | Alt | Caption (EN) | Caption (JA) |
|------|-----|--------------|--------------|
| mcp_preview_1.png | Terminal-style preview of jpintel-mcp: curl request to /v1/programs/search returning a Tier-S 経営開始資金 result, followed by /v1/exclusions/check detecting a keiei-kaishi-shikin × koyo-shuno-shikin conflict. | jpintel-mcp cross-authority search + exclusion-check demo | jpintel-mcp の横断検索と排他チェックのデモ |
| mcp_preview_2.png | Same content at 1600×900 landscape for registry tile displays. | jpintel-mcp wide-tile preview | jpintel-mcp ワイドタイル用プレビュー |
| demo.svg | 15-second animated terminal showing curl + JSON response for the 12 MCP tools. | AutonoMath 15s animated demo | AutonoMath 15秒アニメデモ |

再生成: Playwright headless `width ≤ 1880px` (memory `feedback_playwright_screenshots`)、demo.svg を HTML inline して terminal chrome で囲む。

---

## Review 時間 (per registry)

| Registry | Review | Indexing lag |
|----------|--------|-------------|
| Official Registry | 自動 (秒) | 即時 |
| Glama | 自動 daily crawl | 24-48h |
| PulseMCP | 自動 (Official Registry 経由) | ~7日 |
| mcp.so | manual, maintainer queue | 2-5日 |
| mcpservers.org | manual | 3-7日 (free tier) |
| MCP Hunt | community upvote | 日次 |
| MCP Market | manual | 3-7日 |
| Cursor Directory | manual | 3-10日 |
| Awesome MCP Servers | maintainer PR review | 2-14日 |
| Smithery | claim manual | 1-3業務日 |
| Claude Desktop Ext. | Anthropic review | **2-4週間** |
| Continue Hub | 要確認 | — |

**全 8 候補 indexed まで現実的見積**: D+3 に 4-5 箇所、D+14 に 7-8 箇所。

---

## 成功指標 (W2 末)

6 registry 以上 listed、Glama badge 生存、PulseMCP propagation 確認、Desktop Ext. interest form 受理、MCP Hunt 10+ upvote。失敗 = 4 未満 → rebrand / namespace 再検査。

---

## 禁止事項 (memory 由来)

- 有料 placement 購入 禁止 (`feedback_no_cheapskate` ではなく **成功確率** 視点でも、広告枠は怪しい signal)
- データ 数字 の 水増 禁止 (tools 12、programs 13,578、case_studies 2,286、loan_programs 108、enforcement_cases 1,185、exclusion_rules 35 — 盛らない)
- 幻覚 registry 提出 禁止 (未確認の registry に submit して 404 コピー貼るのは論外)
- ToS 未読 承諾 禁止 (必ず D-7 までに読む)

---

## 関連ファイル

- `/Users/shigetoumeda/jpintel-mcp/mcp-server.json` — canonical manifest
- `/Users/shigetoumeda/jpintel-mcp/smithery.yaml` — Smithery 用
- `/Users/shigetoumeda/jpintel-mcp/scripts/rebrand_mcp_entries.sh` — 置換 script
- `/Users/shigetoumeda/jpintel-mcp/scripts/mcp_registries.md` — Task #29 research
- `/Users/shigetoumeda/jpintel-mcp/scripts/mcp_registries_submission.json` — Task #29 structured data
- `/Users/shigetoumeda/jpintel-mcp/src/jpintel_mcp/mcp/server.py` — protocol 実装 (MCP 2025-06-18)

---

最終更新: 2026-04-23
