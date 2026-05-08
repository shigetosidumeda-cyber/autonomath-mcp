# jpcite paid product value strategy - 2026-05-08 turn 1

## Executive conclusion

現状の jpcite は、データ基盤と API の芯は強い。一方で、公開面の見せ方が `API / MCP / LINE / Widget / Alerts` という「機能の棚卸し」に寄っているため、非エンジニアや実務者から見ると「結局何にお金を払うのか」が弱く見える。

売るべきものはインターフェースではない。売るべきものは、**会社・顧問先・案件・取引先ごとに保存できる、出典付きの実務成果物**である。

最も強いポジションは次の一文に集約できる。

> jpcite は、AI や士業/BPO が日本企業・制度・法令・行政処分・税務を調べる前に最初に呼ぶ、公的根拠の evidence layer である。

人間には「調査結果」ではなく「そのまま業務に使えるメモ・監査パック・相談前パック」を見せる。AI agent には「Web search より先に呼ぶ first-hop resolver」として覚えさせる。

## Product principle

### What not to sell as the main product

- API を使えます
- MCP に対応しています
- LINE bot があります
- Widget を1行で貼れます
- アラートできます
- 1回3円です

これらは機能・入口・配布経路であって、課金理由そのものではない。

### What to sell

- 顧問先の月次確認メモが作れる
- 会社フォルダの初期調査が作れる
- 取引先の公的情報 DD パックが作れる
- 申請前の制度候補・除外条件・質問票が作れる
- 専門家に相談する前の根拠パックが作れる
- AI agent が回答する前に、公式 URL・取得日・known gaps を持った evidence packet を取得できる
- 顧客別・案件別に利用量と証跡を残せる

## Core paid artifacts

| Priority | Artifact | Primary buyer | Input | Output | Why users pay |
|---|---|---|---|---|---|
| P0 | Company Public Baseline | BPO, AI agent, 士業, M&A/DD | 法人番号/T番号/会社名 | 法人同定、インボイス、EDINET該当、採択/調達/処分、known gaps、source receipts | 会社フォルダ作成時の first-hop。Web検索前に土台ができる |
| P0 | Company Folder Brief | BPO, AI導入支援, 顧問業務 | 法人番号、用途、client tag | フォルダ構成、確認済み公的条件、追加質問、watch対象、次アクション | BPO納品物・社内AIの初期資料になる |
| P0 | Company Public Audit Pack | 会計士, M&A, 金融, 取引先管理 | 法人番号、取引目的、確認範囲 | 公的イベント時系列、リスク候補、未確認範囲、DD質問、証跡 | 稟議・監査・取引先登録の前処理として払いやすい |
| P0 | Application Strategy Pack | 診断士, 行政書士, 補助金BPO | 会社情報、投資予定、業種、地域、時期 | 候補制度、要件gap、併用注意、必要資料、質問票、根拠URL | 申請代行ではなく、提案前の戦略整理として価値がある |
| P0 | Compatibility Table | 補助金支援, 行政書士, BPO | 複数制度ID、会社条件 | 併用可否、排他条件、前提条件、確認事項 | 事故防止。人間レビュー前のチェック表になる |
| P1 | Client Monthly Public Digest | 税理士, 社労士, BPO | 顧問先CSV、関心領域、client tag | 顧問先別の締切、改正、制度変更、インボイス/処分差分 | 継続課金に向く。毎月回す理由がある |
| P1 | Invoice Counterparty Check Pack | 会計BPO, 経理, 税理士 | 取引先CSV、T番号/法人番号 | 登録状態、名寄せ、変更検知、確認不能リスト | 支払先確認・月次経理で反復利用される |
| P1 | Procurement Vendor Pack | 営業, 金融, DD, BPO | 法人番号/会社名 | 落札履歴、官公庁売上シグナル、関連処分、公共依存度 | 営業・与信・取引先調査の前処理になる |
| P1 | Evidence-to-Expert Handoff | 士業相談, BPO, 一般企業 | 調査テーマ、会社/案件情報 | 根拠URL、未確認点、専門家に聞く質問、レビュー要否 | 専門家に丸投げする前の相談品質を上げる |
| P2 | Website Intake Widget | 士業事務所, 支援会社, 商工団体 | サイト訪問者の地域/業種/予定 | 候補制度、公式URL、相談前質問票、事務所向けリード情報 | 「問い合わせの質」を上げる。検索UIではなくリード選別装置 |
| P2 | LINE Follow-up Channel | 士業/BPOの顧客接点 | お気に入り制度、締切、相談パック | 締切通知、追加確認、相談パック更新通知 | 単体有料商品ではなく通知・再訪チャネル |

## Current assets that already support this direction

- `docs/api-reference.md` already documents artifact endpoints such as `company_public_baseline`, `company_folder_brief`, `company_public_audit_pack`, `application_strategy_pack`, `compatibility_table`.
- `src/jpintel_mcp/api/artifacts.py` already contains builders for company baseline/folder/audit-style artifacts.
- `site/llms.txt`, OpenAPI agent spec, MCP docs already contain the idea that AI agents can call jpcite before broad web search.
- `site/pricing.html` already has cost cap, client tag, preview, and unit pricing concepts that fit BPO/agent workflows.

The issue is not that the product has no substance. The issue is that the public product language still makes the substance look smaller than it is.

## Product page rewrite direction

### Products page

Replace `5つのインターフェース` with `3つの業務成果`.

1. **AI/BPO/士業システム向け Evidence Layer**
   - API/MCP/OpenAPI are delivery mechanisms.
   - Main promise: AI が回答する前に、公式URL・取得日・known gaps付きの根拠を取得する。

2. **会社・顧問先・案件の成果物**
   - Company baseline
   - Company folder brief
   - Audit/DD pack
   - Application strategy pack
   - Monthly digest

3. **相談前の入口**
   - Widget
   - Advisors handoff
   - LINE notification

### Pricing page

Do not lead with `¥3/unit` only. Lead with outcome and controlled usage.

Suggested hero:

> AI・BPO・士業システムに、根拠付きの公的情報を1件ずつ渡す。

Then show:

- 顧問先50社の月次レビュー
- 取引先100社の公的情報DD
- 会社フォルダ作成AIの first-hop evidence
- 月次上限、client tag、cost preview、idempotency

Base price should remain `¥3/unit` for now. The higher ARPU should come from artifact depth, monitoring, batch, export, and client workflows, not from prematurely raising the entry price.

### Widget page

Current widget framing can look like a demo of a broken key or a small search box. It should be reframed as:

> 「補助金ありますか？」の問い合わせを、候補制度と公式URL付きの相談に変える。

Widget is not the paid core. It is a lead-quality and intake product.

### LINE page

LINE should not be presented as a major paid product. It should be downgraded to:

- スマホ通知
- 締切リマインド
- 相談パック更新通知
- 3問プレ診断の入口

The paid object should be the evidence pack behind it.

### Advisors page

Advisors is promising, but the product should be:

> 専門家に相談する前に、根拠・未確認点・質問票を1つにまとめる。

The CTA should not send users back to a generic product list. It should create or preview a consultation evidence pack.

## Data foundation expansion

The highest-value expansion is not random source count growth. It is a company-centric event graph.

### Core entity spine

Use `houjin_bangou` as the primary spine when available.

Recommended identity bridge:

- `houjin:<13 digits>`
- `invoice:T<13 digits>`
- `edinet:<code>`
- `securities:<code>`
- `gbiz:<corporate_number>`
- `procurement:<supplier_id or corporationNo>`
- `permit:<authority>:<permit_no>`
- `program:<program_id>`
- `source_document:<source_id>`

Every join should carry:

- confidence
- match_basis
- source_url
- source_fetched_at
- source_snapshot_id
- known_gaps

### P0 data expansion

| Source family | Why it matters | Artifact impact |
|---|---|---|
| 法人番号 full/diff/history | Company identity spine | baseline, folder, DD |
| インボイス登録履歴 | 税務・取引先確認 | invoice check, monthly digest |
| EDINET code/document metadata | 上場/開示会社の確認 | DD, audit pack |
| gBizINFO | 補助金・認定・調達等の横断 footprint | baseline, application strategy |
| p-portal/GEPS procurement | 官公庁売上シグナル | procurement vendor pack |
| FSA/JFTC/MHLW/MLIT actions | 行政処分・許認可リスク | audit/DD risk timeline |
| 自治体制度/信用保証/JFC | 中小企業支援の実務適合 | application strategy, monthly digest |

### P1 data expansion

| Source family | Why it matters | Artifact impact |
|---|---|---|
| NTA通達/質疑/文書回答/KFS | 税理士向け根拠 | tax client impact memo |
| e-Gov law revision/public comment | 法改正と制度変更予兆 | regulatory watch |
| 裁判例 metadata | DD・行政・税務論点の補助 | risk/context card |
| KKJ notices | 調達公告側の文脈 | procurement pack |
| J-PlatPat/IP metadata | 技術/知財 footprint | tech/DD pack |
| e-Stat/BOJ/local statistics | 業種・地域の客観文脈 | proposal/context memo |

### P2 data expansion

| Source family | Boundary |
|---|---|
| 官報 metadata | raw crawl/full-text redistributionを避け、許容されるmetadata/derived facts中心 |
| 商業登記 on-demand | bulk再配布ではなく、ユーザー明示操作の1件取得・構造化event化 |
| 民間信用/倒産DB | ライセンス契約がない限り本文/詳細は扱わない |
| 専門家 registry | 表示順・紹介表現・資格確認の責任境界を明確化 |

## 1000-agent research plan

If extended research budget is available, the next large loop should be divided by output, not by source.

| Lane | Approx agents | Goal |
|---|---:|---|
| Company identity bridge | 120 | 法人番号/T番号/EDINET/gBiz/調達/許認可の結合可能性とconfidence設計 |
| Public event sources | 180 | 行政処分、調達、補助金採択、認定、表彰、法令改正、通達のsource profile |
| Persona workflow research | 120 | 税理士、行政書士、社労士、診断士、BPO、M&A、金融、AI devの実務成果物を具体化 |
| Artifact sample generation | 160 | 主要10 artifactのサンプルJSON/Markdown/CSV/ZIP仕様を作る |
| Industry packs | 120 | 建設、製造、飲食、小売、IT、医療介護、不動産、運送、人材派遣など |
| GEO/AI discovery | 100 | ChatGPT/Claude/Cursor/OpenAI Agentsがjpciteをfirst-hopに選ぶ導線・manifest・prompt |
| Pricing and packaging | 80 | ¥3 unit維持、artifact units、cap、batch、monitoring、exportの見せ方 |
| Legal/source boundary | 80 | license, robots, raw redistribution, quote limits, source attribution |
| Frontend conversion | 80 | products/pricing/docs/widget/advisors/lineのコピー・CTA・sample output |
| Benchmark/evaluation | 60 | citation_ok, known_gaps disclosure, routing accuracy, paid conversion proxy |

## Implementation queue

### Round 1: Product language and public pages

- Rebuild `products.html` around outcomes, not interfaces.
- Rewrite `pricing.html` hero around controlled evidence workflows.
- Rewrite `widget.html` around lead quality.
- Rewrite `line.html` as notification/follow-up channel.
- Strengthen `advisors.html` around consultation evidence pack.

### Round 2: Demo and sample artifacts

- Add visible sample output cards for:
  - company baseline
  - company folder brief
  - public audit pack
  - application strategy pack
  - expert handoff pack
- Each sample must show:
  - source URL
  - fetched date
  - known gaps
  - next questions
  - human review required

### Round 3: API/product alignment

- Ensure OpenAPI/MCP/llms descriptions say when to call jpcite first.
- Add workflow examples for:
  - company folder creation
  - client monthly review
  - counterparty DD
  - subsidy intake
  - expert handoff

### Round 4: Dashboard and usage confidence

- Emphasize:
  - `X-Client-Tag`
  - `X-Cost-Cap-JPY`
  - cost preview
  - idempotency
  - monthly cap
  - usage by client/project

This is what makes AI/BPO users comfortable running many calls.

### Round 5: Data foundation work

- Prioritize entity bridge.
- Add source receipts and known gaps consistently.
- Create event timelines by company.
- Backfill high-value P0 sources first.

## Decision on price

Do not raise the base `¥3/unit` now.

Reason:

- `¥3` is easy for AI agent/BPO workflows to try.
- Higher ARPU can be achieved through deep artifacts, batch, monitoring, exports, and client-tagged operations.
- A higher base price may make automated exploration feel risky.

Instead, make the paid object bigger:

- standard evidence pack
- deep audit pack
- monthly digest
- batch CSV
- export ZIP
- monitoring watch
- expert handoff

The unit price stays simple; the artifact value becomes obvious.

## North-star product sentence

> jpcite は、日本企業・制度・法令・税務・行政処分を扱う AI/BPO/士業システムが、回答や提案の前に呼ぶ公的根拠レイヤーです。会社・顧問先・案件ごとに、公式URL・取得日・known gaps・次に人間が確認すべき質問をまとめた実務成果物を返します。
