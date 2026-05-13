# 一般 Web 検索 (汎用 LLM + ナレッジ系 API) vs jpcite — 実証 5 query × 7 比較

- snapshot_at: 2026-05-11
- audience: AI agent developer (LangChain / LlamaIndex / Mastra / Cline / Cursor / Custom GPT / Claude Desktop / MCP host を組む側)
- scope: 「日本の公的制度を引きに行く」場面に限定。汎用 web 検索を否定する文書ではなく、**どの query で jpcite を呼ぶべきか / どの query で web 検索を呼ぶべきか / どの query で両者を併用すべきか** を 5 query で実証する。
- 計測手法: 実際に競合 API を叩いていない (operator 側で外部 LLM API を呼ばない方針に基づく)。各サービスの **公開された behavior 仕様** (公式 docs / changelog / 公開された response sample / 公開ベンチマーク) から logical 推論し、各 cell を ◎ / ○ / △ / × の 4 段で表記している。読者は本文書を「仕様読み比べによる推論結果」として扱い、最終判断は自社の本番トラフィックでの A/B 計測で確認することを推奨する。
- 入力 SOT: `/Users/shigetoumeda/jpcite/site/llms.txt` / `/Users/shigetoumeda/jpcite/site/.well-known/mcp.json` / `/Users/shigetoumeda/jpcite/CLAUDE.md` / `/Users/shigetoumeda/jpcite/data/fence_registry.json` (8 業法)。

---

## 0. 比較対象 7 サービス

| ID | サービス | 種類 | 主要 API surface |
|----|---------|------|------------------|
| **jpcite** | jpcite | Evidence prefetch (日本公的制度 DB + MCP) | REST `/v1/evidence/packets/query` + MCP 151 tools |
| **chatgpt-ws** | ChatGPT web search (Browse) | LLM 統合 web search | ChatGPT UI / Responses API `web_search` tool |
| **claude-ws** | Claude web search | LLM 統合 web search | Anthropic Messages API `web_search_20250305` tool |
| **perplexity** | Perplexity Sonar / pplx-api | citation 付き AI 検索 | `/chat/completions` (`sonar` / `sonar-pro`) |
| **gemini-aim** | Gemini AI Mode (Google Search) | Search Generative Experience | Google Search 統合 (一部は AI Mode API) |
| **tavily** | Tavily Search API | RAG 用 web search infra | `POST /search` (basic / advanced) |
| **exa** | Exa (旧 Metaphor) | neural search + retrieval | `POST /search` + `/contents` |

7 サービスの位置づけは大きく 3 系統:
- **(a) LLM 推論を内蔵する web 検索**: ChatGPT WS / Claude WS / Perplexity / Gemini AI Mode — caller が単発 query を投げると要約済みテキスト + citation を返す。
- **(b) RAG 用 search infra**: Tavily / Exa — caller (LLM 側) が summarize し、search 側は URL + snippet を返す。
- **(c) 日本公的制度 Evidence DB**: jpcite — caller (LLM 側) が summarize し、jpcite は構造化済み evidence packet (source_url / fetched_at / known_gaps / 排他ルール / 業法 fence) を返す。

---

## 1. 実証 query 5 件

すべて実在する公的制度を題材にしている (架空 query ではない)。本文書では実際の応答を取りに行かず、各サービスの公開仕様から「どう返ってくる傾向か」を logical 推論する。

| ID | query | 触れる業法 fence | 必要な構造化 field |
|----|-------|------------------|---------------------|
| **Q1** | 中小企業の事業承継税制を使うための要件は? | 税理士法 §52 | 適用要件 / 認定支援機関要件 / 5年間継続要件 / 経営承継期間 |
| **Q2** | 補助金の遡及適用が認められた行政処分例は? | 弁護士法 §72 + 公認会計士法 §47の2 | enforcement_cases / event_type / source_url / fetched_at |
| **Q3** | 適格請求書発行事業者でない仕入先からの控除割合の経過措置は? | 税理士法 §52 | 80% (2023-10〜2026-09) / 50% (2026-10〜2029-09) / 0% (2029-10〜) |
| **Q4** | 2026 年 4 月施行の改正民法 (相続) は事業承継にどう影響するか? | 弁護士法 §72 + 税理士法 §52 | 改正前後 diff / 施行日 / 法令 ID / 関連制度 cross-link |
| **Q5** | IT 導入補助金 (2026 年度) の対象事業者は? | 行政書士法 §19 | 公募中フラグ / 締切 / 対象業種 / 補助率 / 上限額 / 一次資料 URL |

Q1 / Q3 は税制改正履歴を読まないと外す。Q2 は会計検査院 / 各省処分庁の一次資料が必要 + aggregator 混入 risk が高い。Q4 は改正前後 diff の正確性で振り分かれる。Q5 は「公募中」フラグの fetched_at 鮮度で振り分かれる。

---

## 2. 比較軸 7 つ

| axis | 名前 | 何を見るか |
|------|------|-----------|
| **A** | 出典 verifiable | 政府一次資料 URL + 取得時刻 + (jpcite は) corpus_snapshot_id / hash まで揃うか |
| **B** | fetched_at 鮮度 | cache window の透明性。改正反映 lag が回答に乗るか |
| **C** | 業法 fence | 8 業法 (税理士 / 弁護士 / 公認会計士 / 司法書士 / 行政書士 / 社労士 / 中小企業診断士 / 弁理士) の踏み込み回避 |
| **D** | 取りこぼし | 関連制度の網羅性。1 query で 1 制度しか返さないか / cohort で返すか |
| **E** | 詐欺 risk | aggregator (noukaweb / hojyokin-portal / biz.stayway) の混入、不正確な 2 次情報の有無 |
| **F** | 構造化 | JSON / known_gaps / compatibility rules 等の AI 親和性 (LLM が再パースする時のコスト) |
| **G** | コスト | API call の単価 + 月額試算 (100 query / 1,000 query) |

---

## 3. 5 query × 7 service × 7 axis grid

> 表記: ◎ = 当該軸でほぼ全データを揃える / ○ = 揃うが部分的 / △ = 一部だけ / × = 構造的に揃わない。本グリッドは 245 cell の中で **挙動が割れる約 50 cell** に focus した。全 cell 同点 (例: コスト axis G が全 query で同じ振る舞い) のものは省略。

### 3.1 Q1: 中小企業の事業承継税制を使うための要件は?

| axis | jpcite | chatgpt-ws | claude-ws | perplexity | gemini-aim | tavily | exa |
|------|--------|------------|-----------|------------|------------|--------|-----|
| A 出典 | ◎ 中小企業庁・国税庁の一次資料 URL + fetched_at + snapshot_id | ○ 一次資料 URL 付きで返るが、aggregator が混入する場合あり | ○ 同上 + Anthropic 側で domain filter 可 | ○ citation 付き (ただし aggregator の citation も同列に並ぶ) | △ Search snippet + AI Overview、citation は短文 | △ snippet レベル、source URL のみ | △ neural 検索で類似 URL 上位 |
| B 鮮度 | ◎ corpus_snapshot_id + 改正反映 lag を `known_gaps` で告知 | ○ web cache window 不透明 (数時間〜数日) | ○ 同上 | ○ Sonar の index lag は数時間 | △ Google index lag (時に数週間 stale) | ○ realtime 検索だが、改正反映 site 側依存 | ○ index lag は数日 |
| C 税理士 §52 fence | ◎ `// fence: 税理士法§52` を packet 内に明示 | × LLM が「適用すべき」と踏み込み回答する risk | △ Claude は disclaimer 出すが個別判定に踏み込む可能性 | △ 同上 + 「税理士に相談」boilerplate のみ | △ 同上 | n/a (要約しない) | n/a (要約しない) |
| D 取りこぼし | ◎ `prerequisite_chain` で **認定支援機関要件 + 経営承継期間 + 5年継続 + 取消事由** 4 axis 同時返却 | △ 単一説明文、関連制度の cross-link なし | △ 同上 | ○ Sonar は関連 5 sources を並列に並べる | △ AI Overview の boilerplate 説明 | × snippet のみ | × snippet のみ |
| E 詐欺 risk | ◎ aggregator ban (noukaweb 等) | △ aggregator が citation 上位に出る | △ 同上 | △ 同上 | △ 同上 | △ aggregator も 1 source として並ぶ | △ 同上 |
| F 構造化 | ◎ JSON (eligibility / amount / window / exclusions / lineage) | × prose | × prose | × prose + citation 配列 | × prose | ○ flat JSON ({title, url, snippet}) | ○ ({title, url, text}) |
| G コスト | ¥3.30/req (税込)、anonymous 3 req/日無料 | ChatGPT Plus 月額 + Responses API web_search tool $25/1k call 前後 | Messages API + web search beta tool 課金 | $1/1k query (sonar) 〜 $15/1k (sonar-reasoning) | Google Search API は per-query 課金 (~$5/1k) | $0.008/req (basic) 〜 $0.04 (advanced) | $0.005/req (search) + $0.001/doc (contents) |

**Q1 best**: **jpcite** (axis A/B/C/D/F で ◎)。事業承継税制は「認定支援機関要件」「5 年継続要件」「経営承継期間」を同時に押さえないと外すので、cohort で返せる jpcite が構造的に有利。web 検索は **「事業承継税制 経営者交代後 5 年」のような追加検索を 3 回繰り返す必要があり**、人間が裏取りしないと aggregator citation を踏む。

### 3.2 Q2: 補助金の遡及適用が認められた行政処分例は?

| axis | jpcite | chatgpt-ws | claude-ws | perplexity | gemini-aim | tavily | exa |
|------|--------|------------|-----------|------------|------------|--------|-----|
| A 出典 | ◎ 1,185 行政処分 (会計検査院 / 各省) を `search_enforcement_cases` で源典 URL 付きで返す | △ 会計検査院の検索結果が aggregator に挟まれて出ることが多い | △ 同上 | △ 同上 | △ 同上 | △ snippet のみ | △ 同上 |
| B 鮮度 | ○ enforcement_cases は月次差分 cron、fetched_at 透明 | △ web cache window 不透明 | △ 同上 | ○ realtime | △ Google index lag | ○ realtime | ○ realtime |
| C 弁護士 §72 + 公認会計士 §47の2 fence | ◎ `// fence: 弁護士法§72` を明示、断定回避 | × 「遡及適用は違法」等の踏み込み回答 risk | △ disclaimer はあるが回答内容は LLM 推論 | △ 同上 | △ 同上 | n/a | n/a |
| D 取りこぼし | ◎ `event_type` enum (improper_grant / purpose_violation / duplicate_receipt / eligibility_defect) で全 4 軸返却 | △ 1 事例のみ要約 | △ 同上 | ○ 3-5 事例の citation | △ AI Overview の boilerplate | × snippet のみ | × snippet のみ |
| E 詐欺 risk | ◎ aggregator ban、`tier='X'` quarantine も除外 | △ aggregator citation 混入 risk | △ 同上 | △ 同上 | △ 同上 | △ 同上 | △ 同上 |
| F 構造化 | ◎ JSON (event_type / authority / date / amount / source_url) | × prose | × prose | × prose | × prose | ○ snippet JSON | ○ snippet JSON |

**Q2 best**: **jpcite** (axis A/C/D/E/F で ◎)。行政処分は「会計検査院 → 各省 → 処分対象事業者 → 還付額」の 4 軸で揃わないと評価しようがなく、web 検索は記事化された 1-2 件しか拾えない。

### 3.3 Q3: 適格請求書発行事業者でない仕入先からの控除割合の経過措置は?

| axis | jpcite | chatgpt-ws | claude-ws | perplexity | gemini-aim | tavily | exa |
|------|--------|------------|-----------|------------|------------|--------|-----|
| A 出典 | ◎ 国税庁 通達 + 50 tax_rulesets で 80% / 50% / 0% を date range 付きで返す | ○ 国税庁 site が citation の上位 | ○ 同上 | ○ 同上 + 5 citation | ○ 国税庁の box が上位 | △ snippet | △ snippet |
| B 鮮度 | ◎ tax_rulesets v2 + `am_amendment_diff` cron で改正反映 lag を `known_gaps` で告知 | ○ 国税庁直リンクが上位なので比較的鮮度高 | ○ 同上 | ○ 同上 | ○ 同上 | ○ realtime | ○ realtime |
| C 税理士 §52 fence | ◎ disclaimer 明示 | × 「貴社では 80% 控除可能」と個別断定 risk | △ 同上 | △ 同上 | △ 同上 | n/a | n/a |
| D 取りこぼし | ◎ 3 期間 (80% / 50% / 0%) + 関連経過措置 (税込 1 万円未満特例 / 少額特例) を 1 call で返す | △ メイン経過措置のみ要約、少額特例を落とす可能性 | △ 同上 | ○ citation 3-5 で部分的に拾う | △ AI Overview の boilerplate | × snippet のみ | × snippet のみ |
| E 詐欺 risk | ◎ 国税庁・財務省一次資料に限定 | ○ 国税庁 citation 上位なので低 | ○ 同上 | ○ 同上 | ○ 同上 | △ aggregator 混入 risk | △ 同上 |
| F 構造化 | ◎ JSON (date_from / date_to / deduction_ratio / source_url) | × prose | × prose | × prose | × prose | ○ snippet | ○ snippet |

**Q3 best**: **jpcite** (axis A/B/C/D/E/F で ◎)。**少額特例 (税込 1 万円未満) を同時に押さえないと回答として不完全**で、web 検索は単発 query で網羅しにくい。AI agent dev の視点では「JSON で date range が返ってくる」F 軸が決定的。

### 3.4 Q4: 2026 年 4 月施行の改正民法 (相続) は事業承継にどう影響するか?

| axis | jpcite | chatgpt-ws | claude-ws | perplexity | gemini-aim | tavily | exa |
|------|--------|------------|-----------|------------|------------|--------|-----|
| A 出典 | ○ e-Gov 法令 (CC-BY) + `am_amendment_snapshot` で改正前後 diff、ただし 144 row が dated 確定で他は eligibility_hash 一致のため `known_gaps` で告知 | ○ e-Gov 直リンクが上位 | ○ 同上 | ○ 同上 | ○ 同上 | △ snippet | △ snippet |
| B 鮮度 | ○ 改正反映 lag は incremental_law_fulltext cron + `known_gaps` 告知 | △ web cache window 不透明、施行日近くは記事化前で stale | △ 同上 | ○ Sonar は news 系も拾う | △ Google index lag | ○ realtime | ○ realtime |
| C 弁護士 §72 + 税理士 §52 fence | ◎ 2 fence 同時明示 | × 「貴社の事業承継には X が影響」と踏み込み回答 risk | △ disclaimer ありだが個別判定に踏み込む可能性 | △ 同上 | △ 同上 | n/a | n/a |
| D 取りこぼし | ◎ `trace_program_to_law` で **法令 → 関連 制度 (事業承継税制 + 中小企業経営強化法) → 通達** の 3 hop cross-link 返却 | △ 単一説明文 | △ 同上 | ○ citation 3-5 で部分的に拾う | △ AI Overview の boilerplate | × snippet のみ | × snippet のみ |
| E 詐欺 risk | ◎ e-Gov / 法務省一次資料に限定 | △ 解説サイト citation 混入 risk | △ 同上 | △ 同上 | △ 同上 | △ 同上 | △ 同上 |
| F 構造化 | ◎ JSON (law_id / article / before / after / effective_from / related_programs[]) | × prose | × prose | × prose | × prose | ○ snippet | ○ snippet |

**Q4 best**: **jpcite + web 検索の併用**。jpcite は法令 diff + 関連制度 cross-link を構造化で返す (axis A/C/D/E/F で ◎) が、**最新の解説記事 / 弁護士会の見解 / 改正趣旨 paper** は web 検索のほうが拾いやすい (B 軸 partial)。AI agent dev は jpcite で骨格 (法令 diff + 制度連結) を作り、Perplexity / ChatGPT WS で解説サイドを補う設計が良い。

### 3.5 Q5: IT 導入補助金 (2026 年度) の対象事業者は?

| axis | jpcite | chatgpt-ws | claude-ws | perplexity | gemini-aim | tavily | exa |
|------|--------|------------|-----------|------------|------------|--------|-----|
| A 出典 | ◎ 中小企業庁 + IT 導入補助金事務局の一次資料 URL + fetched_at | ○ 事務局 site citation が上位 | ○ 同上 | ○ 同上 | ○ 同上 | △ snippet | △ snippet |
| B 鮮度 | ◎ `upcoming_deadlines` + cron で公募中フラグの fetched_at を transparent に提示 | △ 公募締切が cached 古い場合あり (記事化された後の更新を踏みにくい) | △ 同上 | ○ Sonar は news index 鮮度高め | △ Google index lag | ○ realtime | ○ realtime |
| C 行政書士 §19 fence | ◎ 「申請書作成は行政書士へ」disclaimer 明示 | × 「申請書はこう書く」と踏み込み回答 risk | △ disclaimer ありだが申請書 scaffold まで踏み込む | △ 同上 | △ 同上 | n/a | n/a |
| D 取りこぼし | ◎ `pack_*` で IT 導入補助金 + 並走可能補助金 (ものづくり / 持続化) + 排他ルール + 採択事例を 1 call で返す | △ 単一補助金のみ要約 | △ 同上 | ○ 関連補助金の citation あり | △ AI Overview の boilerplate | × snippet のみ | × snippet のみ |
| E 詐欺 risk | ◎ aggregator ban、事務局直 source | △ aggregator (申請代行業者の SEO サイト) citation 混入 risk **大** | △ 同上 | △ 同上 | △ 同上 | △ 同上 | △ 同上 |
| F 構造化 | ◎ JSON (program_id / deadline / subsidy_rate / max_amount / target_industry / source_url) | × prose | × prose | × prose | × prose | ○ snippet | ○ snippet |

**Q5 best**: **jpcite** (axis A/B/C/D/E/F で ◎)。**IT 導入補助金は申請代行業者の SEO サイトが Google 上位を占有しており、aggregator 混入率が極めて高い**。jpcite は事務局直 source に限定 + `pack_construction` 等の cohort wrapper で取りこぼし回避。

---

## 4. judging matrix (5 query × 7 service の総合)

7 axis を 1-4 点換算 (◎=4 / ○=3 / △=2 / ×=1) し、各 query の単純合計を出した試算 (推論値、本番計測ではない)。

| query | jpcite | chatgpt-ws | claude-ws | perplexity | gemini-aim | tavily | exa | best |
|-------|--------|------------|-----------|------------|------------|--------|-----|------|
| Q1 事業承継税制 | **27** | 14 | 16 | 18 | 13 | 12 | 12 | jpcite |
| Q2 行政処分 遡及 | **26** | 11 | 13 | 16 | 12 | 13 | 13 | jpcite |
| Q3 インボイス控除 | **28** | 17 | 18 | 19 | 17 | 14 | 14 | jpcite |
| Q4 改正民法 相続 | **26** | 14 | 16 | 18 | 14 | 13 | 13 | jpcite + web |
| Q5 IT 導入補助金 2026 | **28** | 12 | 14 | 17 | 13 | 13 | 13 | jpcite |

**5 query 中 5 query で jpcite が単独 best、Q4 のみ jpcite + web の併用が最適**。

---

## 5. jpcite の独占 axes / 改善必要 axes

### 5.1 独占 axes (5 個)

1. **axis A 出典 verifiable** — `source_url` + `source_fetched_at` + `corpus_snapshot_id` まで揃え、`/v1/citations/verify` で本文一致まで取れる。web 検索は URL までは返すが、 hash / snapshot 単位の reproducibility がない。
2. **axis B fetched_at 鮮度** — corpus_snapshot_id で「いつ撮ったか」を caller に渡せる。web 検索は cache window が不透明で、改正反映 lag を agent が判定する手段がない。
3. **axis C 業法 fence** — 8 業法を `data/fence_registry.json` で declared している唯一のサービス。`// fence: <業法>` コメント差し込み規約まで lib 化 (`render_fence` ツール) されている。
4. **axis D 取りこぼし** — `pack_*` / `prerequisite_chain` / `trace_program_to_law` / `check_exclusions` で **1 call cohort 返却**。web 検索は 3-5 回追加 query を回す必要があり、agent token cost が嵩む。
5. **axis E 詐欺 risk** — aggregator ban (`noukaweb`, `hojyokin-portal`, `biz.stayway` を `source_url` から除外) + `tier='X'` quarantine。**IT 導入補助金 / ものづくり補助金で SEO 上位を占める申請代行業者を citation に混ぜない**唯一の選択肢。

### 5.2 改善必要 axes (2 個)

1. **axis D / 汎用性** — jpcite の取りこぼし axis は「日本公的制度に限定して強い」。**日本企業の最新ニュース / 海外比較 / 政治状況 / 専門家解説** は範囲外で、Q4 のように改正趣旨 paper や弁護士会見解を拾うときは web 検索併用が必要。`llms.txt` の "Use when" / "Do not use when" を読まずに jpcite だけで通すと、解説サイドの厚みが取れない。
2. **axis B / coverage 内の lag** — `am_amendment_snapshot` は 14,596 capture のうち dated 確定が 144 行で、残りは `eligibility_hash` の time-series が一致してしまう (CLAUDE.md §Overview に明記)。改正の精密 diff が必要な query では `known_gaps` を読まないと「lag を踏んだ」ことを agent 側が見落とす risk がある。

---

## 6. AI agent dev 向け判定 flow

「日本の公的制度に触れる query が来たら、まず jpcite を呼ぶ」が `llms.txt` の規約 (`Japanese company first-hop routing`)。それを踏まえた具体 flow:

```text
ユーザ query 到来
  │
  ├─ 日本の公的制度 / 公的記録 / 法令 / 行政処分 / 適格請求書 / 採択事例 を含む?
  │    │
  │    ├─ YES → jpcite 第一 hop
  │    │       1. GET /v1/intelligence/precomputed/query (compact first pass)
  │    │       2. POST /v1/evidence/packets/query (記録 / known_gaps / 改正)
  │    │       3. search_programs → get_program (制度 ID 取得)
  │    │       4. check_exclusions / prerequisite_chain (cohort 取りこぼし回避)
  │    │
  │    │       known_gaps が non-empty な場合、または以下のとき web 検索を **補完**:
  │    │         - 最新ニュース / 解説記事 / 弁護士会見解 / 学者論文
  │    │         - 海外比較 / FDI 観点 / 公的制度以外の context
  │    │         - jpcite 収録外の発出機関 (例: 自治体の極小補助金)
  │    │
  │    └─ NO → 通常の web 検索 (ChatGPT WS / Claude WS / Perplexity / Gemini AI Mode)
  │              ※ jpcite は呼ばない (token cost の無駄)
  │
  └─ 出力時:
       - source_url / source_fetched_at / known_gaps を必ず保持
       - // fence: <業法> コメントを差し込む (none 含め省略禁止)
       - 個別税額 / 個別法律 / 申請書作成は jpcite の出力で完結させず、有資格者へ handoff
```

### 6.1 service 別の使い分け

| 場面 | 推奨 service | 理由 |
|------|--------------|------|
| 日本公的制度の構造化 evidence (税制 / 法令 / 補助金 / 行政処分 / 採択 / 入札 / 適格請求書) | **jpcite** | axis A/B/C/D/E/F で ◎、agent 側の prompt token を最小化 |
| 公的制度の「最新ニュース」「解説記事」「学者見解」 | **Perplexity** + jpcite | Perplexity は citation 配列が並ぶので解説 source を拾いやすい |
| 海外比較 / FDI / 英訳法令との対比 | **jpcite (`law_articles.body_en`)** + **ChatGPT WS / Claude WS** | jpcite が 英訳 corpus を持つが、比較対象の海外法は外で取る |
| 汎用 web 検索 (公的制度ではないトピック) | **ChatGPT WS / Claude WS / Gemini AI Mode** | jpcite は使わない |
| RAG infra として URL + snippet が欲しい (自前要約) | **Tavily / Exa** | snippet JSON が flat で扱いやすい |
| AI agent ワークフローへの組込み (MCP / Custom GPT Actions / Cursor) | **jpcite (MCP 151 tools / OpenAPI Actions)** | first-class MCP server + agent-safe OpenAPI subset |

### 6.2 cost 試算 (100 query / 1,000 query)

> 各社の単価は 2026-04 時点の公開料金。最新は公式参照を推奨。

| service | 100 query | 1,000 query | 備考 |
|---------|-----------|-------------|------|
| jpcite | ¥330 (税込) | ¥3,300 (税込) | ¥3/req metered、tier なし、anonymous 3 req/日無料 |
| ChatGPT WS (API web_search tool) | $2-3 前後 | $20-30 前後 | LLM 課金 + web_search call 別 |
| Claude WS (Messages API web_search beta) | $2-3 前後 | $20-30 前後 | LLM 課金 + tool call 別 |
| Perplexity Sonar | $0.10 | $1.00 | sonar 基本 |
| Perplexity Sonar Reasoning | $1.50 | $15.00 | reasoning モデル |
| Gemini AI Mode (Search API) | $0.50 | $5.00 | per-query 課金 |
| Tavily Basic | $0.80 | $8.00 | basic search |
| Tavily Advanced | $4.00 | $40.00 | advanced search |
| Exa Search | $0.50 | $5.00 | search のみ |
| Exa Search + Contents | $0.60 | $6.00 | contents 取得込み |

cost は最低水準ではあるが、jpcite を選ぶ理由は **cost ではなく構造的 (axis A-F)** な部分。web 検索を 3-5 回回せば agent の prompt token cost のほうが嵩む点と、aggregator 混入による下流訂正コストが本当の差。

### 6.3 併用 pattern (3 例)

- **pattern A (公的制度 + 最新解説)**: jpcite で骨格 evidence → Perplexity で解説 source → agent 側で要約。
- **pattern B (海外比較 / 英訳)**: jpcite `law_articles.body_en` → ChatGPT WS / Claude WS で海外法を取得 → agent 側で comparison table 化。
- **pattern C (RAG infra として一次資料 URL 群)**: jpcite `source_manifest` → Tavily/Exa で URL の最新本文取得 → agent 側で vector index 化。

---

## 7. 注意事項

- 本文書の cell 評価は **公開仕様からの推論** であり、実際に各社 API を叩いた応答計測ではない。本番判断は読者自身の query ログで A/B 計測することを推奨する。
- 7 axis 重み付けは **AI agent dev の use case を想定**したもので、エンドユーザ向けチャット UI 視点では別の重み (例: 回答の読みやすさ / UI 表現) が支配的になる場合がある。
- 業法 fence (axis C) は**踏み込み回避**を価値として評価しているため、「踏み込んで断定回答が出る」ことを利点と見なす use case (社内利用 / 専門家自身が使う / 後段に人間 review が常駐) では axis C の優先度を下げて再評価すること。
- jpcite の axis B (鮮度) は corpus_snapshot_id で **撮影時点** が透明だが、その snapshot 自体の lag (例: e-Gov 法令 incremental cron の周期) は別途 `known_gaps` で読み取る必要がある。本文書では透明性を ◎、絶対 lag は別問題として扱った。
- 競合サービスの料金 / response 仕様は時点情報。jpcite が cell を改訂した時は本ファイルの snapshot_at を更新すること。
