# 「AI に読ませるレイヤー」教育資料 (2026-05-11)

> 対象: 梅田茂利 (Bookyou株式会社 代表 / jpcite 発明者)
> 目的: AI agent が jpcite を「発見・理解・推奨」するための公開層 (= GEO layer) を
> 仕様レベルで噛み砕き、jpcite の現状対応度と次に学ぶ/改善するべき項目を一望する。
> 構成: A 概念 → B 必須 6 layer + 現状 mapping → C 新興 spec → D 改善 roadmap → E 学習リソース。

---

## A. 「AI に読ませるレイヤー」とは何か

### A-1. 3 段構造: 人 → AI agent → jpcite

伝統的な Web は「人がブラウザでサイトを読む」前提で作られています。HTML、CSS、JavaScript は
人の網膜と脳に最適化された層です。

2023 年以降、間に **AI agent** という新しい読者が割り込みました。

```
┌──────────┐    質問     ┌────────────────┐   crawl/API   ┌──────────┐
│   人     │ ──────────▶ │   AI agent     │ ────────────▶ │  jpcite  │
│ (発注者) │             │ ChatGPT/Claude │               │ (一次源) │
│          │ ◀────────── │ Cursor/Codex   │ ◀──────────── │          │
└──────────┘    答案     │ Gemini/Perplex │   evidence    └──────────┘
                         └────────────────┘
```

人は AI agent に「日本の補助金で X が使えるか」と尋ね、AI agent が裏で jpcite を呼びます。
人は jpcite の存在を知らなくても、AI agent が知っていれば良い。
これが **GEO (Generative Engine Optimization)** の世界観です。

### A-2. SEO と GEO の違い

| | **SEO** | **GEO** |
|---|---|---|
| 読者 | Google/Bing の crawler | ChatGPT/Claude/Perplexity 等の AI agent |
| 評価軸 | rank position (1-10位) | 引用回数 + 引用時の出典扱い |
| ranking signal | バックリンク・CTR・滞在時間 | 構造化された fact、source_url、機械可読 manifest |
| 失敗時 | 検索結果 10 位以下に沈む | AI 回答に登場しない (= 存在しないのと同じ) |
| 配信形態 | HTML | HTML + JSON-LD + llms.txt + openapi.json + MCP |

GEO の最大の罠は **「人には見えない」** こと。順位や CTR が無いので、
何が効いているかを直接測れません。だから「仕様準拠」が唯一の安全ベットになります。

### A-3. 「発見 → 理解 → 推奨」3 phase

AI agent が jpcite を回答に組み込むまでには 3 段階あります。

1. **発見 (Discovery)** — AI agent が `https://jpcite.com/llms.txt` や `/.well-known/mcp.json`
   を読み、「日本の公的制度の一次資料を返す API がある」と知る。
2. **理解 (Comprehension)** — openapi.agent.json + agents.json + Schema.org Dataset を読み、
   どの endpoint を、どんな引数で、どの順番で呼ぶか把握する。
3. **推奨 (Recommendation)** — 人が「日本の補助金…」と聞いた時、訓練データ + RAG +
   tool catalog の中から jpcite を選んで実行する。

3 phase 全てに対応する公開物が必要であり、jpcite は既に主要な 6 layer をカバーしています。

---

## B. 必須 6 layer 解説 + jpcite 現状 mapping

### B-1. AI bot welcome (robots.txt の UA Allow 列挙)

**目的**: AI bot は `User-agent: *` の Default rule を信用しません。
仕様上 (RFC 9309) **最も具体的な UA グループだけ** が適用され、Default group は無視されます。
個別 UA を明示 Allow しないと、控えめな bot は遠慮して立ち去ります。

**主要 AI bot UA (2026 年時点、jpcite の robots.txt は赤字を全て列挙済み)**:

| Provider | UA token | 用途 |
|---|---|---|
| OpenAI | `GPTBot` | ChatGPT 訓練 |
| OpenAI | `ChatGPT-User` | ChatGPT user 起点 fetch (回答中の参照) |
| OpenAI | `OAI-SearchBot` | SearchGPT インデックス |
| Anthropic | `ClaudeBot` | Claude 訓練 |
| Anthropic | `Claude-User` | Claude user 起点 fetch |
| Anthropic | `Claude-SearchBot` | Claude search 用 |
| Anthropic | `anthropic-ai` | レガシー UA |
| Google | `Google-Extended` | Gemini 訓練 opt-out gate |
| Google | `GoogleOther` | 内部研究 crawl |
| Google | `Google-CloudVertexBot` | Vertex AI Agent 訓練 |
| Perplexity | `PerplexityBot` | 回答 + crawl |
| Common Crawl | `CCBot` | 公開 corpus (LLM 訓練の上流) |
| Apple | `Applebot` / `Applebot-Extended` | Siri / Apple Intelligence |
| Meta | `Meta-ExternalAgent` | Llama / Meta AI |
| Amazon | `Amazonbot` | Alexa / Amazon AI |
| ByteDance | `Bytespider` | Doubao 訓練 |
| DuckDuckGo | `DuckAssistBot` | DuckAssist 回答 |
| Mistral | `MistralAI-User` | Le Chat |

**jpcite 現状**: 16 UA を Allow リストに列挙済み (DuckDuckBot / Bingbot 含む)。
低価値 crawler (AhrefsBot / SemrushBot / MJ12bot / DotBot / PetalBot / YandexBot) は明示 Disallow。
**追加候補**: `OAI-SearchBot`, `Claude-SearchBot` は既に追加済み。`MistralAI-User`,
`DuckAssistBot`, `Google-CloudVertexBot`, `GoogleOther` の追加余地あり。

### B-2. Discovery file 4 種 (一次入口)

AI agent が「初めてこのサイトを見た」時に最初に取りに来るのが、以下 4 種類です。

#### B-2-1. `/llms.txt` (Jeremy Howard / Answer.AI 提案、Markdown spec)

**仕様**: ルートに `/llms.txt` を置き、AI agent が context window に貼り付けやすい
Markdown 形式で「サイトとは何か / どこを読めば良いか」を箇条書きにする。

```
# サイト名 (H1, 必須)
> 1 行サマリ (Blockquote, 推奨)

任意の本文 (heading 除く)

## セクション (H2)
- [リソース名](URL): 説明
- [API spec](https://example.com/openapi.json): OpenAPI 3.1

## Optional (H2)
- [低優先リソース](URL)
```

**重要 point**:
- HTML ではなく Markdown を使う理由 = LLM の token 効率が圧倒的に良い (HTML タグはノイズ)。
- `llms-full.txt` という拡張版もあり、サイト全体の本文を 1 ファイルにまとめる慣習が広がりつつある。
- 採用例: Stripe, Anthropic docs, Cloudflare, FastHTML, nbdev。

**jpcite 現状**: `/llms.txt` (47KB) + `/llms.en.txt` (22KB) + `/llms-full.txt` (2.2MB) +
`/llms-full.en.txt` (4.4MB) を配信中。`llms-full` は 90 ページ相当の本文を 1 ファイル化、
Claude/GPT が 1 fetch で全体把握できる構造。

#### B-2-2. `/.well-known/mcp.json` (MCP discovery、AI engineering 業界デファクト)

**役割**: 「ここに MCP server があるよ、認証はこう、料金はこう、推奨 workflow はこう」を機械可読で宣言。
RFC 8615 の `.well-known` 慣習に則った場所。

**jpcite 現状**: 253 行の精緻な manifest を配信。schema_version, llms ペア (ja/en/full),
mcp サーバ install コマンド (`uvx autonomath-mcp`), auth (`X-API-Key`, `jc_` prefix),
pricing (¥3/req 完全従量), 3 つの `recurring_agent_workflows` (company_folder_intake /
monthly_client_review / counterparty_dd_and_audit_prep), `recommend_when` /
`do_not_recommend_when`, `evidence_to_expert_handoff` (7 業法フェンス含む) を網羅。

#### B-2-3. `/.well-known/agents.json` (agents.json draft、複数の MCP/REST 配信先を集約)

**役割**: 1 つの operator が複数の AI 入口 (MCP / REST OpenAPI / agent-safe OpenAPI / GPT30 slim
OpenAPI) を出している時、それらを 1 manifest で束ねる。

**jpcite 現状**: `agents.json/draft-01` schema で 22 行のスリムな manifest。
mcp_endpoint, rest_openapi, agent_openapi, llms_txt, glossary, facts_registry,
fence_md, pricing, geo_eligibility (Japan-only via Stripe billing_address_country),
data_licenses (PDL_v1.0 + CC-BY-4.0 + 政府標準利用規約v2.0) を宣言。

#### B-2-4. `/.well-known/ai-plugin.json` (OpenAI Custom GPT Actions、legacy ChatGPT plugin)

**役割**: ChatGPT の Custom GPT (旧 plugin) が自動で API を組み込むための manifest。
schema_version, name_for_human, name_for_model, description_for_model, auth, api.url を含む。

**重要 point**: OpenAI plugin 自体は 2024 年に Custom GPT Actions に統合されましたが、
`ai-plugin.json` 形式は引き続き Custom GPT が読み込めるフォーマットとして残っています。
更に Claude Code / Cursor 等が「Custom GPT Action discovery を真似る」ので価値は残存。

**jpcite 現状**: schema_version=v1, name_for_model=jpcite,
description_for_model に「7 業法フェンス + 匿名 3 req/日 + jc_ プレフィックス + Stripe Checkout」
を組み込み、api.url=https://jpcite.com/openapi.agent.gpt30.json を指す。

### B-3. MCP server (server.json + uvx 配信)

**MCP (Model Context Protocol) 2025-06-18 仕様** (Anthropic + OpenAI + Google 共同で進化中):

- **Transport**: stdio / HTTP / SSE。jpcite は stdio (`uvx autonomath-mcp`) + HTTPS (`https://api.jpcite.com/mcp`)
- **3 つの primary capability**:
  - **Tools** — AI agent が呼べる関数 (jpcite は 139 tools)
  - **Resources** — AI agent が読み取れる文書/ファイル (jpcite は facts_registry + fence.md)
  - **Prompts** — Templated prompt workflow (jpcite は未配信)
- **Client → Server 方向の 3 capability**:
  - Sampling (server が client の LLM を呼び返す)
  - Roots (URI/filesystem の境界宣言)
  - Elicitation (server が user に追加質問を出す)
- **JSON-RPC 2.0 + stateful connection + capability negotiation**

**`server.json`** は MCP Registry (mcp.so / Smithery / VS Code 等) に投稿する manifest。
distribution channel (pypi/npm), version, transport, publisher 情報を機械可読で宣言。

**jpcite 現状**:
- `server.json` (v0.3.4): pypi package `autonomath-mcp`, stdio transport,
  `tool_count=139`, `resource_count=28`, recurring_workflows 3 種を `_meta` に格納。
- `mcp-server.json` (172KB): tool 1 件 1 件の `inputSchema` を完全展開した tool catalog。
- MCP Registry: 既に publish 済み。`uvx autonomath-mcp` で 1 行 install。

### B-4. OpenAPI 3 layer (full / agent-safe / GPT30)

**なぜ 3 つ必要か**: AI agent ごとに context window と inputSchema 解釈能力が違います。

| Layer | サイズ | 対象読者 | 用途 |
|---|---|---|---|
| **full** (`/v1/openapi.json`) | 数 MB | 開発者 (人) + 高性能 LLM | 完全な reference、自動 SDK 生成 |
| **agent-safe** (`/openapi.agent.json`) | 約 544 KB | Claude / Cursor / Cline | 内部 admin/dashboard を除いた agent 向け |
| **GPT30** (`/openapi.agent.gpt30.json`) | 約 379 KB | ChatGPT Custom GPT (30 endpoint 制限) | GPT Actions の 30 endpoint 上限に収めた slim |

**ChatGPT Custom GPT には 30 endpoint の hard limit があります** (2026 年現在も継続)。
これを超えると Custom GPT が manifest を拒否するため、GPT 専用に厳選 endpoint の slim を出すのが業界慣習。

**jpcite 現状**: 3 layer 全て配信中。`scripts/export_openapi.py --profile gpt30` で
自動生成。`agents.json` の `agent_openapi_slim_gpt30` field でも宣言済み。

### B-5. Schema.org structured data (JSON-LD)

**目的**: HTML 内に JSON-LD ブロックを埋め込むと、Google / AI agent が
「これは Dataset」「これは Service」「これは FAQ」と機械的に判別できる。

**主な type**:

#### B-5-1. `Dataset` (jpcite の corpus 全体を 1 つの Dataset として宣言)

```json
{
  "@context": "https://schema.org",
  "@type": "Dataset",
  "name": "jpcite 日本公的制度コーパス",
  "description": "補助金 11,601 + 採択 2,286 + 融資 108 + 行政処分 1,185 + 法令 9,484 ...",
  "license": "https://creativecommons.org/licenses/by/4.0/",
  "creator": { "@type": "Organization", "name": "Bookyou株式会社" },
  "distribution": [
    { "@type": "DataDownload", "encodingFormat": "application/json",
      "contentUrl": "https://api.jpcite.com/v1/openapi.json" }
  ],
  "keywords": ["補助金", "適格請求書", "法人番号", "e-Gov", "MCP"],
  "temporalCoverage": "2018-01-01/..",
  "spatialCoverage": { "@type": "Country", "name": "Japan" }
}
```

これが Google Dataset Search にも掲載され、AI agent が「Japan public program dataset」を
検索した時に jpcite が候補に上がる。

#### B-5-2. `Service` (jpcite を「Japan public-record data service」として宣言)

`provider`, `serviceType`, `areaServed=Japan`, `offers` (¥3/req), `termsOfService` を網羅。

#### B-5-3. `FAQPage` (`mainEntity` に `Question`/`Answer` のペア)

AI agent と voice search (Alexa / Siri / Google Assistant) は FAQPage を特に好む。
`speakable` プロパティを付けると、音声読み上げ最適化セクションを宣言できる。

#### B-5-4. `SearchAction` (AI agent から site search を起動可能に)

```json
{
  "@type": "WebSite",
  "potentialAction": {
    "@type": "SearchAction",
    "target": { "@type": "EntryPoint",
      "urlTemplate": "https://jpcite.com/search?q={search_term}" },
    "query-input": "required name=search_term"
  }
}
```

これで AI agent は「jpcite で X を検索」を URL template から自動構築できる。

**jpcite 現状**: `index.html` + 主要 page に JSON-LD 注入済み (要再 audit)。
全 page への Dataset 注入と SearchAction 注入は未確認。

### B-6. AI 専用 sitemap (sitemap-llms.xml)

**従来の sitemap.xml** は Google crawler に「全 URL を網羅で渡す」のが目的。
jpcite は既に 17 個の sitemap shard (programs / prefectures / industries / cities / qa /
audiences / cross / pages / enforcement / cases / laws / laws-en / 等) を配信中。

**sitemap-llms.xml** は新しい慣習で、「AI agent が読むべき URL だけ」を抽出した sitemap。
全 URL ではなく、`llms.txt` / `llms-full.txt` / `openapi.*.json` / 重要 docs / FAQ 等の
**「AI 向け黄金ルート」** のみ列挙する。AI agent 側で URL discovery のショートカット。

**jpcite 現状**: 未配信 (改善候補)。

---

## C. 新興 spec / 未対応 (今後学ぶ価値)

### C-1. LLMs.txt v2 (草案、未確定)

現行 spec はあくまで Markdown ベースの discovery file。
コミュニティでは以下の拡張が議論中:

- **多言語の `.md` companion files の標準化** (各 HTML ページに `index.html.md` を併置)
- **`/llms-meta.json`** (machine-readable index of llms.txt itself)
- **token-budget hint** (各セクションの size 宣言)

jpcite は既に `llms.en.txt` + `llms-full.*.txt` の 4 variant を持つので、
companion `.md` 方式に移行する場合の準備は整っている。

### C-2. MCP protocol 2026 (次バージョン)

2025-06-18 仕様の次に予定される機能:
- **Streamable HTTP transport の正式化** (現状はまだ optional)
- **Multi-tenant authentication patterns の標準化**
- **Tool annotations の trust boundary 強化** (tool description の untrusted 扱い)
- **Elicitation の対話的フロー強化**

jpcite は既に stdio + HTTPS の 2 transport をサポートしているので、
spec の変更を追随しやすい。

### C-3. Schema.org Action / SearchAction の本格活用

`SearchAction` 以外にも `BuyAction`, `OrderAction`, `CommunicateAction`, `ReserveAction`
等の Action サブ types があり、AI agent が「次にこれを実行する」を構造化できる。

jpcite は Stripe Checkout や `/v1/billing/portal` を `BuyAction` で宣言する余地あり。

### C-4. IndexNow (Bing + Yandex + Seznam + Naver の即時 indexing)

**仕様**: ルートに 8-128 hex 文字の key ファイル (`{key}.txt`) を配置し、
URL 更新時に `https://<searchengine>/indexnow?url=URL&key=KEY` (GET) または
`POST` で bulk 10,000 件まで通知すると、参加 search engine が即時 crawl。

- 200 = 成功 / 202 = key 検証中 / 403 = key 無効 / 422 = host/key 不一致 / 429 = rate limit
- 参加: Bing, Yandex, Seznam, Naver (+ 通知後に全参加エンジンに共有される)
- Google は不参加 (Google Search Console の通常ルートを使う必要あり)

**jpcite 現状**: `scripts/cron/index_now_ping.py` + `.github/workflows/index-now-cron.yml`
は既に存在。key 配置と日次 ping 動作の確認余地あり。

### C-5. Common Crawl 取り込み

Common Crawl (`CCBot`) は世界最大の公開 web corpus を 1-2 ヶ月ごとに更新し、
殆どの LLM の訓練データの上流になる。Common Crawl に取り込まれることは
「次世代 LLM の訓練データに乗る」を意味する。

**現状**: jpcite は `CCBot` を Allow 済みなので、自動的に取り込み対象。
Common Crawl Index (`https://index.commoncrawl.org`) で jpcite.com の捕捉率を確認可能。
明示的な submit ルートは無く、CCBot が定期 crawl で拾うのを待つ pull model。

### C-6. AI agent crawl analytics (Cloudflare AI UA 統計)

Cloudflare Pages の dashboard では、UA 別の request count を可視化できる。
`GPTBot`, `ClaudeBot`, `PerplexityBot`, `Bytespider` 等の AI bot の visit を観測すれば、
GEO 投資の ROI を粗くだが追跡可能。

CF の `AI Audit` 機能 (2024-2025 公開) で AI UA に絞ったログ抽出も可能。

**jpcite 現状**: CF Pages を使用中。AI Audit + Bot Management の活用余地あり。

### C-7. Google-Extended / Google-CloudVertexBot の二段制御

Google は「検索 indexing 用 (Googlebot)」と「Gemini 訓練用 (Google-Extended)」と
「Vertex AI 用 (Google-CloudVertexBot)」を **分離可能** にした。

- `Googlebot` を Allow し続ければ Google 検索順位は保持
- `Google-Extended` を Allow すると Gemini 回答に登場する確率が上がる
- `Google-CloudVertexBot` を Allow すると Vertex AI Agent の訓練に乗る

**jpcite 現状**: `Google-Extended` は Allow 済み。`Google-CloudVertexBot` と
`GoogleOther` の明示は未対応 (`*` default では拾われない bot)。

### C-8. agents.json の上位 spec (Anthropic / OpenAI 主導の標準化)

現状の `agents.json` は draft-01 (jpcite 独自進化版)。
Anthropic と OpenAI が共同で「agent capability discovery の業界標準」を進めており、
2026 後半に正式 draft が出る可能性あり。

---

## D. jpcite 改善 roadmap (1 line per item、Claude 側で着手可能)

> memory `feedback_no_user_operation_assumption` に従い、Claude 側で着手可能な項目は
> 「user に頼む」ではなく「Claude が PR 化」と読む。

1. `sitemap-llms.xml` 新設 (AI agent 向け黄金 URL list を抽出)
2. `robots.txt` に `MistralAI-User`, `DuckAssistBot`, `Google-CloudVertexBot`, `GoogleOther` を Allow 追加
3. `agents.json` を draft-01 → 上位 spec 追随用に schema_version field 拡張
4. `mcp.json` の `recurring_agent_workflows` を 3 → 6 (将来 cohort の追加分)
5. Schema.org `Dataset` JSON-LD を全 program page に inject (現状 index.html のみ)
6. Schema.org `SearchAction` を root の HTML に inject (`urlTemplate` で programs/search を露出)
7. Schema.org `FAQPage` + `speakable` を FAQ section に inject (音声検索対応)
8. `/llms-meta.json` (llms.txt 自身の machine-readable index) を試作 (v2 spec 想定)
9. `index-now-cron.yml` の動作確認と key file 配置 verify (Bing + Yandex への即時 ping)
10. CF Pages AI Audit を有効化、AI UA 別 visit 統計を `analytics/` に dump
11. `mcp-server.json` に Prompts capability を追加 (3 primary capability の最後の 1 つ)
12. `openapi.agent.gpt30.json` の slim 内訳を facts.html に可視化 (どの 30 endpoint が GPT 用か)
13. `Common Crawl Index` での jpcite.com 捕捉率を定期 audit (monthly cron)
14. `llms-full.txt` のセクション header に anchor link 付与 (AI agent が部分 fetch しやすく)
15. `Google-Extended` 観測用に Search Console の coverage report を `analytics/` に export

---

## E. 学びに行く organic リソース

> memory `feedback_organic_only_no_ads` に従い、有償講座は除外。全て公開 doc + blog。

### E-1. 一次仕様

| リソース | URL | カバー範囲 |
|---|---|---|
| llmstxt.org | https://llmstxt.org/ | LLMs.txt 提案者 Jeremy Howard 公式 |
| MCP spec | https://modelcontextprotocol.io/specification/2025-06-18 | MCP 最新仕様 |
| Schema.org | https://schema.org/ | Dataset / Service / FAQPage / Action |
| IndexNow | https://www.indexnow.org/documentation | 即時 indexing |
| Google crawler doc | https://developers.google.com/search/docs/crawling-indexing/google-common-crawlers | Google bot UA 一覧 |
| OpenAPI 3.1 | https://spec.openapis.org/oas/v3.1.0 | API spec の標準 |
| Known Agents | https://knownagents.com/agents | AI bot UA レジストリ (旧 darkvisitors.com) |

### E-2. blog / cookbook (実装例)

| リソース | 価値 |
|---|---|
| Anthropic Engineering blog | https://www.anthropic.com/news (MCP / Claude best practices) |
| Anthropic Cookbook | https://github.com/anthropics/anthropic-cookbook |
| OpenAI Platform docs | https://platform.openai.com/docs (Custom GPT Actions, file_search) |
| OpenAI Cookbook | https://cookbook.openai.com/ |
| Cursor docs | https://docs.cursor.com/ (MCP integration 実装側) |
| Cline docs | https://docs.cline.bot/ (autonomous coding agent の MCP 消費例) |
| Claude Code docs | https://docs.claude.com/en/docs/claude-code (Skill / sub-agent / MCP) |
| Smithery | https://smithery.ai/ (MCP server コミュニティ + 配信) |
| mcp.so | https://mcp.so/ (MCP server registry + 検索) |
| Cloudflare AI Gateway | https://developers.cloudflare.com/ai-gateway/ (AI traffic の中継・analytics) |
| Stripe LLMs.txt | https://docs.stripe.com/llms.txt (LLMs.txt 採用先進例) |
| Vercel AI SDK | https://sdk.vercel.ai/ (agent UI + tool calling) |

### E-3. コミュニティ

- **MCP Discord** (modelcontextprotocol.io から参加 link)
- **Anthropic Discord** (Claude / MCP の実装相談)
- **r/LocalLLaMA** (オープン LLM + AI engineering の最大コミュニティ)
- **Hacker News** (`llms.txt` / `MCP` キーワードで定期 hit、コメント欄が一次情報源化)

---

## 付録: jpcite 公開層 file map (2026-05-11 snapshot)

```
site/
├── robots.txt                            # AI bot UA 16+ Allow + sitemap declaration
├── sitemap-index.xml                     # 17 sitemap shard を集約
├── sitemap-{programs,prefectures,...}.xml
├── llms.txt                              # 47KB, ja
├── llms.en.txt                           # 22KB, en
├── llms-full.txt                         # 2.2MB, 90 ページ相当 ja
├── llms-full.en.txt                      # 4.4MB, 90 ページ相当 en
├── openapi.agent.json                    # 544KB, agent-safe
├── openapi.agent.gpt30.json              # 379KB, GPT Custom GPT 30 endpoint slim
├── mcp-server.json                       # 172KB, tool catalog
├── server.json                           # MCP Registry manifest (v0.3.4)
├── manifest.webmanifest                  # PWA manifest
└── .well-known/
    ├── mcp.json                          # 253 行、AI discovery の主役
    ├── agents.json                       # 22 行、4 manifest を束ねる
    ├── ai-plugin.json                    # OpenAI Custom GPT 用
    ├── trust.json                        # operator + product 信頼情報
    ├── security.txt                      # 脆弱性報告窓口
    └── sbom.json                         # SBOM (CycloneDX)
```

---

## 結論

jpcite は既に **B-1〜B-5 の 5 layer + B-6 の sitemap 一般版** をカバーし、
GEO 観点での「発見・理解」までは業界先進水準にあります。

次に学ぶべきは:
1. **MCP の Prompts capability** (3 つの primary capability の最後)
2. **Schema.org Action 系** (`SearchAction` + `BuyAction` で AI agent から jpcite を起動可能に)
3. **AI bot 観測** (CF Pages AI Audit で「誰が読んでいるか」を可視化)

改善 roadmap (D 章 15 項目) は全て Claude 側で PR 化可能。
user 操作必須項目は **CF Pages dashboard での AI Audit 有効化** のみで、これは既存
analytics 設定の延長線上にあり、最終承認のみで通せる。

— end of document —
