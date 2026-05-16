# jpcite install/setup friction audit — 2026-05-11

AI-agent dev 視点の install path 監査。「30 秒で 'これは使える' と感じる体験」になっているかを 5 系統 × 6 axis = 30 cell で評価し、即修正候補と one-command demo を出す。

Scope: AI agent (Claude Code / Cursor / Codex / Custom GPT / SDK 直叩き) が install する path のみ。人間 user が web UI で設定する path は除外 (memory `feedback_autonomath_no_ui`)。

Probe time: 2026-05-11 12:20 JST。本番 https://api.jpcite.com + https://jpcite.com に対する 1 IP 匿名 quota 消化済み (3/3 used → 残り 0)。

---

## サマリ: 30 秒目標達成状況

| Path | 達成 (≤30s) | 推定 time-to-first-success | 致命 pinch |
|---|---|---|---|
| 1. MCP server (Claude Code / Cursor / Codex) | ❌ | **90-180s** | uvx 未導入 user は +30-120s、stdio起動 cold 5-15s、PyPI 名 `autonomath-mcp` がブランド `jpcite` と乖離 |
| 2. REST API (curl) | ❌ | **15-45s + fail loop** | README/connect-page 掲載 curl が **HTTP 400 を返す** (URL 内 utf-8 unencoded 文字を CF が拒絶) |
| 3. ChatGPT Custom GPT | ❌ | **300-600s** | **`openapi.agent.gpt30.json` が 404** (jpcite.com 上にデプロイされていない)。Custom GPT Builder 5+ クリック手動。AI agent で自動化不可 |
| 4. SDK (Python `autonomath` / TS `@autonomath/sdk`) | ❌ | **install 不可** | **両方 unpublished** (README に "Currently unpublished" / "Pre-release — npm publish pending"。実体無し) |
| 5. Playground (browser-only) | N/A | (除外 — human UI) | memory `feedback_autonomath_no_ui` により audit 対象外 |

**30 秒目標達成 path 数: 0/5。** path 2 が一番近いが docs の curl がそのまま動かない致命。path 1 は最速。

`/connect/*` 4 ページ全て **CF Pages 上で 404** (`HTTP=404` × 4 確認)。ローカルファイル `site/connect/*.html` は存在するが本番未配信 → SEO 流入から到達した AI agent は SOT 文書に辿り着けない。

---

## 30 cell grid (5 path × 6 axis)

凡例: ✓=合格 / △=微妙 / ✗=致命 / N/A=該当せず。

### Path 1: MCP server (Claude Code / Cursor / Codex via uvx)

| Axis | 状況 | 詳細 |
|---|---|---|
| 1. time-to-first-success | △ 90-180s | uvx 既導入なら 30-45s。未導入なら +30-120s (`curl -LsSf astral.sh/uv` + shell restart) |
| 2. step 数 | ✗ 5 step | uvx install → register (`claude mcp add ...`) → restart → verify → first prompt。Cursor は更に「Settings → MCP 緑 dot 待ち」が UI 介在 |
| 3. error 経路 | △ | `claude mcp add` 失敗時に「uvx が PATH に無い」を CLI が指摘しない、user 自力で `which uvx` 必要 |
| 4. 依存物 | ✗ | uv + Python 3.11+ + Claude Code CLI 最新 + ~150MB PyPI download (autonomath-mcp wheel 1.5MB だが依存 transitive で fastmcp/httpx/sqlalchemy 等) |
| 5. first call 質 | ✓ | `search_programs` が source_url + fetched_at + tier 付きで返る。155 tools tool list の説得力高 |
| 6. discoverability after install | △ | `mcp.json` `resources` に `facts_registry` + `fence.md` 2 件のみ。`recurring_agent_workflows` JSON は存在するが MCP `resources` から exposeされていない (`mcp://jpcite/workflows.json` 未登録) |

**pinch point**:
- `site/connect/claude-code.html:185` の PyPI 名 `autonomath-mcp` がブランド `jpcite` と乖離 → AI agent が `uvx jpcite-mcp` と推測して `error: package not found`
- HTTP fallback 切替時に DB 同梱無しの旨を warn する copy が `README.md:99-103` には書いてあるが connect/*.html には書かれていない → user は遠回し warn を読まずに「local DB 0」のエラーで困惑

---

### Path 2: REST API (curl)

| Axis | 状況 | 詳細 |
|---|---|---|
| 1. time-to-first-success | ✗ **fail loop** | 公式 README/connect-page 掲載 curl: `curl "https://api.jpcite.com/v1/programs/search?q=設備投資&prefecture=東京都"` → **HTTP 400 "Invalid HTTP request received"** (CF/Fly の URL parser が utf-8 unescaped を reject) |
| 2. step 数 | △ 1 step (但し fail) | curl 1 本コピペ → 400 → 「percent-encode が必要」と気付き調整 → ようやく success |
| 3. error 経路 | ✗ | 400 のレスポンスが `"Invalid HTTP request received"` 30byte のみで `code/documentation/next_step` 無し → docs に書いた error_handling URL に到達不能 |
| 4. 依存物 | ✓ | curl のみ |
| 5. first call 質 | ✓ (encode 後) | 200 response が tier + source_url 付き、Evidence Packet が満足度高 |
| 6. discoverability after install | △ | response の `_next_calls` envelope は wave22 系のみ。検索 endpoint は素のリスト返却で「次に何を呼ぶか」hint 無し |

**pinch point** (再現性 100%):
- `README.md:138-144` の curl 例 (utf-8 unencoded) → CF/Fly 400 reject
- 同じく `site/connect/*.html` 内 verification snippet (例 `claude-code.html:212` `claude mcp list | grep jpcite` は OK だが `chatgpt.html:209` には `補助金 ものづくり 東京都の最新公募を、jpcite から…` という日本語 user query があり、これは curl 例ではないが README の curl 例と一連の混同を生む)
- 匿名 quota 消化後の 429 response が `upgrade_url` を返すのは良いが、`X-API-Key` ヘッダー名が pages 間で `X-API-Key` vs `Authorization: Bearer` で揺れている (`README.md:138-144` に "Primary X-API-Key" + "Also supported Bearer" と書いてあるが Cursor/Claude HTML は X-API-Key only)

---

### Path 3: ChatGPT Custom GPT

| Axis | 状況 | 詳細 |
|---|---|---|
| 1. time-to-first-success | ✗ **install 不能** | `https://jpcite.com/openapi.agent.gpt30.json` → **HTTP 404** (CF Pages にファイル未配信、ローカル `site/openapi.agent.gpt30.json` 512KB は存在) |
| 2. step 数 | ✗ 5+ step (全て human UI) | Explore GPTs → Create → Configure → Actions → Import from URL → Authentication → Instructions → Save → Publish。AI agent が自動化不可、純 human flow |
| 3. error 経路 | ✗ | URL 404 を Custom GPT Builder が「Invalid OpenAPI URL」と汎用文言で返し、jpcite側で原因究明不能 |
| 4. 依存物 | ✗ | ChatGPT Plus/Team/Enterprise 課金 + GPT Builder 操作スキル |
| 5. first call 質 | N/A (install 不能) | - |
| 6. discoverability after install | N/A | - |

**pinch point**:
- `site/.well-known/ai-plugin.json:13` `"url": "https://jpcite.com/openapi.agent.gpt30.json"` の参照先が 404 → ai-plugin 規格に従う AI agent (Bing Chat 等) も到達不能
- `api.jpcite.com/v1/openapi.agent.json` (no `gpt30` suffix) は 200 を返すが 325KB と巨大、Custom GPT の 30 path 制限超過 → 名前/path 設計の SOT 不整合

**memory `feedback_autonomath_no_ui` に従えば Path 3 は本質的に AI dev 視点 audit 対象外**。Custom GPT は human が UI で組む。但し ai-plugin.json と openapi.agent.gpt30.json は AI 自動 discovery 経路でもあるため、最低限 URL を 200 にする必要がある。

---

### Path 4: SDK (Python `autonomath` / TypeScript `@autonomath/sdk`)

| Axis | 状況 | 詳細 |
|---|---|---|
| 1. time-to-first-success | ✗ **install 不能** | `pip install autonomath` → PyPI 上に存在しない (autonomath-mcp は別 package、SDK は未公開)。`npm install @autonomath/sdk` → unpublished |
| 2. step 数 | ✗ N/A | install そのものが失敗 |
| 3. error 経路 | ✗ | `pip install autonomath` が `ERROR: No matching distribution` を返すのみ。README:13 に「Currently unpublished」と書かれているが install 試行前に気付くには README 読破が必要 |
| 4. 依存物 | △ | Python 3.10+ or Node 20+ |
| 5. first call 質 | N/A (install 不能) | - |
| 6. discoverability after install | N/A | - |

**pinch point**:
- `sdk/python/README.md:12-13` 「Currently unpublished; install locally with `pip install -e path/to/sdk/python`」→ そもそも repo を clone してパスを指定する flow は AI agent が SDK を使う動機を破壊する
- `sdk/typescript/README.md:20-23` 「Pre-release — npm publish pending」+ 「Public npm release is pending. Until then, call the REST API directly」→ 公開 install path を諦めさせる copy。SDK 自体の存在意義が薄い (REST + MCP で十分)

**判定**: AI agent dev は Path 1 (MCP) か Path 2 (REST curl) を直接使うべき。SDK は launch 後 publish までは存在しないものとして扱い、README 冒頭で「現状は MCP/REST 直叩きを推奨」と redirect する方が誠実。

---

### Path 5: Playground (browser)

memory `feedback_autonomath_no_ui` により AI dev install path から **除外**。但し AI agent が「人間 user に playground を見せて理解させる」 onboarding path として有効なので、AI agent の出力 (recommend) に load される URL は最低限 200 にする必要がある (playground.html は 200 OK 確認済)。

---

## 即修正 top-5 (実装可能、半日内)

### 1. **CF Pages デプロイ漏れ修復 (Path 1/2/3 全 blocker)**

**現象**: `/connect/{claude-code,cursor,chatgpt,codex}` 全 404、`/openapi.agent.gpt30.json` 404。ローカル `site/` 配下には全てあり、CF Pages デプロイが反映されていない。

**修正**: 既存 memory `project_jpcite_2026_05_07_state` 「CF Pages wrangler 4th retry 1734/13010 (13%)」が原因。デプロイ完走させる、または `_redirects` に static で 200 を返す entry を追加。

具体 diff (`site/_redirects` 末尾追加):
```
/connect/claude-code /connect/claude-code.html 200
/connect/cursor /connect/cursor.html 200
/connect/chatgpt /connect/chatgpt.html 200
/connect/codex /connect/codex.html 200
```

検証: `curl -sL -w "%{http_code}\n" https://jpcite.com/connect/claude-code` が 200 返るまで再 deploy。

### 2. **README/connect-page curl 例を percent-encoded 版に書き換え (Path 2 致命)**

**現象**: docs の curl が utf-8 unescaped 文字を含み 400 reject。

**修正**: `README.md:138-144` + 各 connect page の curl 例を ASCII-safe に。

Before:
```bash
curl "https://api.jpcite.com/v1/programs/search?q=設備投資&prefecture=東京都" \
  -H "X-API-Key: jc_xxx"
```

After:
```bash
# 推奨: ASCII クエリ (AI agent からの自動化に強い)
curl "https://api.jpcite.com/v1/programs/search?q=energy&limit=3"

# 日本語クエリは percent-encode 必須:
curl --get "https://api.jpcite.com/v1/programs/search" \
  --data-urlencode "q=設備投資" \
  --data-urlencode "prefecture=東京都" \
  --data-urlencode "limit=3"
```

`curl --data-urlencode` が GET でも encode してくれる、コピペ 1 行で必ず 200 を返す形にする。

### 3. **HTTP 400 error response を統一 envelope に (Path 2 自己回復力)**

**現象**: `Invalid HTTP request received` 30byte のみ、`code/documentation/user_message` 無し → 自動修復不能。

**修正**: Fly/FastAPI middleware の 400 catch を追加し、429/404 と同じ structured error envelope を返す。

期待 response:
```json
{
  "code": "invalid_query_encoding",
  "user_message": "URL に utf-8 unencoded 文字が含まれています。`curl --data-urlencode` または percent-encoding をお試しください。",
  "documentation": "https://jpcite.com/docs/error_handling#invalid_query_encoding",
  "example": "curl --get https://api.jpcite.com/v1/programs/search --data-urlencode 'q=設備投資'"
}
```

修正対象は CF Worker / Fly proxy のいずれかで HTTP layer の 400 を catch (FastAPI に届く前に reject されているため)。優先度高、AI agent の自己修復経路が確立する。

### 4. **PyPI 名 `autonomath-mcp` ↔ ブランド `jpcite` 二重表記の SOT 明文化 (Path 1)**

**現象**: connect-page で「PyPI 名は legacy 維持で `autonomath-mcp`、ブランドは jpcite」と複数箇所に重複説明。AI agent が `jpcite-mcp` と推測して `package not found` で死ぬ。

**修正**: `site/connect/*.html` hero 直下に固定 callout を追加。

```html
<div class="callout-warn">
<strong>命名注意</strong>: PyPI package 名は <code>autonomath-mcp</code> (legacy 維持)、ブランド表示は <code>jpcite</code>。
<code>uvx jpcite-mcp</code> は存在しません。常に <code>uvx autonomath-mcp</code>。
</div>
```

加えて mcp.json `mcp.package.install` の `"install": "uvx autonomath-mcp"` field を AI agent が必ず読むよう、`mcp.json:18-20` に `"correct_command": "uvx autonomath-mcp"` + `"do_not_use": ["uvx jpcite-mcp", "uvx jpcite", "pip install jpcite"]` を追加。

### 5. **API key prefix `sk_` / `am_` / `jc_` 三系混在の整理 (Path 1/2 認証 friction)**

**現象**:
- `ai-plugin.json:6,9` → `jc_...` (新規発行 prefix)
- `connect/cursor.html:188,201` → `sk_...`
- `connect/claude-code.html:187,201` → `sk_...`
- `README.md:114` → `jc_xxx`
- `playground.html:815` → `jc_...`

これは memory `reference_secrets_store` の secrets sync 漏れ。

**修正**: 全 surface で正式に `jc_` prefix を default 表記とし、`sk_` / `am_` は「legacy backward-compat 対応で valid」と注釈する。AI agent が key 例を見て「prefix が違うから自分のは無効」と誤判定するのを防ぐ。

具体: 5 file に `replace_all`:
- `connect/cursor.html`: `sk_xxxxx` → `jc_xxxxx`、説明文 `sk_...` → `jc_... (legacy sk_/am_ も valid)`
- `connect/claude-code.html`: 同上
- `README.md:114`: `jc_xxx` → `jc_xxx`
- `playground.html:815`: `jc_...` → `jc_...`

---

## one-command demo 提案

現状: 「30 秒で動く 1 行」が無い。AI agent / user 双方が「とにかく動かしたい」入口を求めている。

### 提案 A: curl 1 本 (anonymous, 0 install)

```bash
curl -s "https://api.jpcite.com/v1/programs/search?q=energy&limit=3" | head -c 800
```

- 依存: curl のみ
- time: ~600ms (実測 0.7s)
- output: tier S/A 補助金 3 件 + source_url + tier + fetched_at
- 匿名 3 req/IP/日 free、API key 不要

これを `README.md` 冒頭 / `site/index.html` hero 直下 / 全 connect pages 共通に「30 秒で確認」box として固定配置する。

### 提案 B: uvx 1 行 (MCP, claude-code 専用)

```bash
claude mcp add jpcite -- uvx autonomath-mcp && claude mcp list | grep jpcite
```

- 依存: claude CLI + uvx
- time: 既導入なら ~10s、未導入なら +60s (uv install)
- output: `jpcite: uvx autonomath-mcp - ✓ Connected`

既に connect/claude-code.html に書かれているが、複数 step に分かれていて 1 行で完結する印象が弱い。1 行版を hero に固定。

### 提案 C: docker 1 行 (REST 自前 host、advanced)

(将来) `docker run -p 8080:8080 ghcr.io/jpcite/api:latest` で REST endpoint をローカル起動。現状未提供だが「30 秒目標」の最後の選択肢として有効。

---

## 6 axis 全 path 横断の系統的 gap

1. **CF Pages デプロイの drift** (今日時点で 4 connect-page + openapi.agent.gpt30 全 404) → SOT 文書がそもそも届かない。最優先で修復。
2. **utf-8 URL の curl 例** → 全 docs で「コピペで動く」前提が崩れる。
3. **SDK の存在主張 vs 実体不在** → README で SDK を案内するが PyPI/npm 上に物が無い。AI agent 視点では「読んだ通りに動かない」最大の信頼破壊。`feedback_keep_it_simple` に従い SDK セクションは削除し「MCP/REST 直叩き推奨、SDK は launch 後検討」に reframe。
4. **API key prefix 三系混在** → key 生成側を `jc_` に統一済みのはずなのに docs が追従していない。secrets store sync 漏れ。
5. **`_next_calls` / `recurring_agent_workflows` resource の非露出** → MCP `resources` array に並ぶのは facts_registry + fence.md の 2 件のみ。`mcp://jpcite/workflows.json` を追加すれば AI agent が install 直後に「3 連続 call の典型」を自己 discover できる。

---

## 結論

5 path 全てが 30 秒目標を未達。最大要因は **CF Pages デプロイ反映遅延** (今日時点で connect/* + openapi.agent.gpt30.json 全 404) と **公式 curl 例が 400 を返す utf-8 問題**。即修正 top-5 を 0.5 day で実装すれば Path 1 (MCP) と Path 2 (curl) が 30 秒以内に到達可能になり、Path 3/4 は scope outside (Custom GPT は human UI / SDK は未公開) として整理。

`feedback_keep_it_simple` + `feedback_no_priority_question` に従い、phase 分けや工数試算は提示しない。yes/no 二択で実行判断のこと。
