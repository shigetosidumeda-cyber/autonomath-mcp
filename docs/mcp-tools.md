<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "headline": "jpcite MCP Tools",
  "description": "jpcite の MCP ツールは、日本の公的制度・法令・税務公開資料・法人情報を AI クライアントから検索するための出典付きデータ取得レイヤーです。",
  "datePublished": "2026-04-01",
  "dateModified": "2026-05-13",
  "inLanguage": "ja",
  "author": {
    "@type": "Organization",
    "name": "jpcite",
    "url": "https://jpcite.com/"
  },
  "publisher": {
    "@type": "Organization",
    "name": "jpcite",
    "logo": {
      "@type": "ImageObject",
      "url": "https://jpcite.com/og/default.png"
    }
  },
  "mainEntityOfPage": {
    "@type": "WebPage",
    "@id": "https://jpcite.com/docs/mcp-tools/"
  }
}
</script>

# MCP Tools

jpcite は、AI クライアントから日本の公的制度・法人・法令データを検索するための **139 個の MCP ツール**を提供します。補助金・助成金・融資・税制・法令・判例・採択事例・行政処分・入札・適格請求書発行事業者などを、一次資料 URL 付きで取得できます。

ChatGPT / Claude / Cursor では、jpcite を回答生成前の evidence retrieval / provenance pre-fetch / GEO source レイヤーとして使います。各ツールは制度名、対象地域、金額、締切、併用ルール、`source_url`、`source_fetched_at` などを構造化して返し、AI クライアントが引用可能な根拠を持って説明できるようにします。

jpcite サーバーは外部 LLM API を呼びません。生成、要約、翻訳、推論は利用中の AI クライアント側で行われます。AI クライアント側の送信・保持の扱いは、各サービスの設定と規約に従います。

AI agent の first call は、OpenAPI / REST では広い制度質問なら `GET /v1/intelligence/precomputed/query`、根拠 record・known gaps・caller-baseline の入力文脈比較が必要なら `POST /v1/evidence/packets/query` です。MCP だけで使う場合は、該当する検索ツールで実在 ID を取り、`get_evidence_packet` で source-linked packet を作ります。日本企業の会社フォルダ、取引先確認、監査/DD、営業先調査では、一般 Web 検索の前に OpenAPI / REST の `createCompanyPublicBaseline` / `/v1/artifacts/company_public_baseline` を使い、`identity_confidence`、`source_url`、`source_fetched_at`、`known_gaps` を回答まで保持してください。法務・税務・補助金申請・融資・監査など専門判断が必要な場合は evidence brief を作ってから `GET /v1/advisors/match` を候補 reviewer 検索として使い、最終意見・保証・紹介完了として扱わないでください。

## 料金

MCP ツールの呼び出しは REST API と同じ課金単位です。匿名枠は 1 IP あたり 3 req/日 (JST 翌日 00:00 リセット)、通常の検索・詳細取得は ¥3/billable unit (税込 ¥3.30) です。これは jpcite API/MCP の料金であり、外部 LLM の token/search/cache/tool 料金や削減額は jpcite では保証しません。月次上限の考え方は [pricing.md](./pricing.md) を参照してください。

## セットアップ

現在の配布パッケージ名は互換性のため `autonomath-mcp` です。MCP サーバー名は `jpcite` として設定できます。

```bash
uvx autonomath-mcp
```

Claude Desktop 拡張として入れる場合は、公開バンドル `https://jpcite.com/downloads/autonomath-mcp.mcpb` を使えます。MCP サーバー manifest は `https://jpcite.com/mcp-server.json` です。配布パッケージの既定 transport は `stdio` で、公開 manifest には HTTP 対応クライアント向けに `sse` と `streamable_http` の endpoint metadata も載せています。

Claude Desktop などの MCP クライアントでは、次のように登録します。

```json
{
  "mcpServers": {
    "jpcite": {
      "command": "uvx",
      "args": ["autonomath-mcp"]
    }
  }
}
```

## よく使うツール

| ツール | 使いどころ |
|---|---|
| `search_programs` | 補助金・助成金・融資・税制・認定制度を横断検索する |
| `get_program` | 検索結果の 1 件を詳しく見る |
| `batch_get_programs` | 複数制度をまとめて比較する |
| `list_open_programs` | 募集中・利用可能な候補を探す |
| `check_exclusions` | 複数制度を併用するときの注意点を確認する |
| `list_exclusion_rules` | 登録済みの併用チェックルールを見る |
| `get_evidence_packet` | 一次資料・provenance・ルール判定を AI に渡しやすい資料パケットにする |
| `search_case_studies` | 採択事例・利用事例を探す |
| `search_enforcement_cases` | 行政処分・返還命令などの公開事例を探す |
| `search_loan_programs` | 融資制度を担保・保証人などの条件で探す |
| `search_laws` | 法令名・条文・関連語で法令を探す |
| `find_saiketsu` | 国税不服審判所の公表裁決事例を探す |
| `cite_tsutatsu` | 国税庁通達への参照を探す |
| `find_shitsugi` | 国税庁の質疑応答事例を探す |
| `search_invoice_registrants` | 適格請求書発行事業者を確認する |

## 基本フロー

### 1. 制度を探す

```python
await client.call_tool("search_programs", {
    "q": "設備投資 補助金",
    "prefecture": "東京都",
    "limit": 5
})
```

### 2. 詳細を取得する

```python
await client.call_tool("get_program", {
    "unified_id": "<search_programs の results[].unified_id>",
    "fields": "full"
})
```

### 3. 複数候補を比較する

```python
await client.call_tool("batch_get_programs", {
    "unified_ids": [
        "<search_programs の results[0].unified_id>",
        "<search_programs の results[1].unified_id>"
    ]
})
```

### 4. 併用リスクを確認する

```python
await client.call_tool("check_exclusions", {
    "program_ids": [
        "<search_programs の results[0].unified_id>",
        "<search_programs の results[1].unified_id>"
    ]
})
```

## 用途別の選び方

| ユーザーの質問 | 最初に使うツール |
|---|---|
| 「東京都の設備投資補助金を探して」 | `search_programs` |
| 「この制度の対象者と締切を見て」 | `get_program` |
| 「候補 5 件を比較して」 | `batch_get_programs` |
| 「この 2 つは併用できる？」 | `check_exclusions` |
| 「この補助金の採択事例は？」 | `search_case_studies` |
| 「不正受給や返還命令の例は？」 | `search_enforcement_cases` |
| 「根拠法令を探して」 | `search_laws` |
| 「税務上の公開裁決を探して」 | `find_saiketsu` |
| 「適格請求書発行事業者か確認して」 | `search_invoice_registrants` |

## 出力の読み方

多くのツールは、次のような出典情報を返します。

| フィールド | 意味 |
|---|---|
| `source_url` / `source_urls` | 根拠となる一次資料 URL |
| `source_fetched_at` | jpcite が資料を取得した時刻 |
| `corpus_snapshot_id` | どのデータスナップショットに基づくか |
| `unified_id` | jpcite 内で制度や資料を参照するための ID |
| `decision_insights` | Evidence Packet の AI 向け補助。`why_review`、`next_checks`、`evidence_gaps` を判断材料・次の確認・根拠不足として使う |
| `next_questions` | `match_due_diligence_questions` の AI 向け補助。顧客へ聞く不足情報を、ヒアリング項目として使う |
| `eligibility_gaps` | `match_due_diligence_questions` の AI 向け補助。要件未解消、unknown 条件、追加確認が必要な前提を、申請前チェックに使う |
| `document_readiness` | `match_due_diligence_questions` の AI 向け補助。必要書類の準備状態、未収集書類、最新版確認先を、書類収集リストに使う |
| `decision_support` | `portfolio_optimize_am`、`get_houjin_360_am` などの AI 向け補助。主案 bundle の理由、decision signals、次アクション、法人DD・与信前確認・監視提案を回答骨子に使う |
| `next_actions` | funding stack/compat などの AI 向け補助。pair verdict や conflict edge を、確認行動、窓口質問、再実行条件に変換して使う |
| `_disclaimer` | 税務・法律・士業領域に関する注意書き |

AI への回答生成では、`source_url` と `source_fetched_at` を一緒に引用することを推奨します。

## Evidence Packet

`get_evidence_packet` は、制度・法人などの対象について、一次資料 URL、取得時刻、provenance、関連するルール判定を 1 つのパケットにまとめます。

これは回答文ではなく、監査可能な入力パケットです。AI クライアントには `source_url`、`source_fetched_at`、`source_checksum`、`corpus_snapshot_id`、`license`、`quality.known_gaps[]` をそのまま渡し、回答側では URL と取得時刻を併記してください。

Evidence prefetch は、回答生成の前に構造化済みの根拠を AI クライアントへ渡すための機能です。トークン量、外部 LLM API 料金、追加検索回数への影響は、モデル、プロンプト、質問内容、検索設定、キャッシュ状態によって変わります。

REST の Evidence Packet endpoint では、`include_compression=true&source_tokens_basis=token_count&source_token_count=<tokens>` を渡すと、ユーザー側で測った元トークン数と jpcite の返却パケット推定トークン数を比較できます。PDFページ数しか分からない場合は `source_tokens_basis=pdf_pages&source_pdf_pages=<N>` も使えます。AI クライアントには、これらを caller baseline に基づく input-context estimates として渡し、`source_url`、`source_fetched_at`、`quality.known_gaps[]` と並べて回答根拠の説明に使ってください。

返却される `agent_recommendation` は、根拠確認としての推薦 (`recommend_for_evidence`) と、コスト削減としての推薦 (`recommend_for_cost_savings`) を分けています。AI agent は `cost_savings_decision=supported_by_caller_baseline` のときだけ、渡された baseline 条件内で input context を抑えられる可能性がある、と説明してください。`recommend_to_user` が返る古いクライアントでは summary field として扱い、二軸の判定を優先してください。

JSON Evidence Packet の `decision_insights` は、`records`、`quality`、`verification`、`evidence_value` から作る回答補助です。AI クライアントは `why_review`、`next_checks`、`evidence_gaps` を、回答前に見る判断材料、確認手順、根拠不足として扱ってください。

## bundle/optimal decision support

`portfolio_optimize_am` / REST `/v1/intelligence/precomputed/query` の `decision_support` は、選ばれた bundle を説明するための補助です。AI クライアントは `why_this_matters`、`decision_insights`、`next_actions` を、主案の理由、runner-up との比較、次の確認事項として回答に使ってください。

## DD actionable fields

`match_due_diligence_questions` / REST `/v1/intelligence/precomputed/query` の `next_questions`、`eligibility_gaps`、`document_readiness` は、候補制度の一覧を「次に何を聞き、何を確認し、何を集めるか」へ変換するための補助です。

AI クライアントは、`next_questions` を顧客ヒアリング、`eligibility_gaps` を要件確認、`document_readiness` を書類収集と最新版確認に使ってください。これらは公開情報と入力 profile に基づく申請前チェックであり、採択可否や書類完備の保証として表示しないでください。

## houjin/full decision support

`get_houjin_360_am` / REST `/v1/artifacts/company_public_baseline` の `decision_support` は、法人360のレスポンスを法人DD、与信前確認、監視提案へ変換するための補助です。AI クライアントは、公的リスクの見るべき点、追加DD質問、インボイス・行政処分・採択/調達などの照合メモ、監視対象を短く示す回答骨子として使ってください。

公的リスクが見つからない場合も、取引安全や融資可否の断定には使わず、確認済み範囲と `known_gaps` を並べて説明してください。

## funding stack/compat next actions

funding stack/compat の `next_actions` は、併用/排他表、申請前チェック、代替 bundle 提案のための確認行動です。AI クライアントは、pair verdict、conflict edge、`runner_up_bundles[]`、`exclude_program_ids` での再実行条件を、同一経費の切り分け、窓口確認、既申請制度の確認、代替案比較に変換してください。

`allow` や `block` は、根拠付きの現在の判定として扱います。併用安全性、採択、受給を保証する表現にはせず、unknown や根拠不足は次の確認事項として残してください。

## 併用チェック

`check_exclusions` は、複数制度を同時に検討するときの注意点を返します。`hits` が空のときは「確認できた排他・前提ルールは見つからない」と扱い、AI クライアントでは一次資料・募集要項・担当窓口での最終確認につなげてください。詳しくは [exclusions.md](./exclusions.md) を参照してください。

## 注意事項

- jpcite は申請代行、税務助言、法律相談を行いません。
- 出力は公開資料に基づく構造化情報です。申請前の最終確認は一次資料・担当窓口・専門家で行ってください。
- MCP クライアント側の会話履歴やデータ送信は、利用しているクライアントの設定に従います。
- ツール名や出力フィールドは後方互換を保つよう管理していますが、新しいフィールドが追加されることがあります。

## REST API との関係

MCP ツールは、REST API と同じデータを AI クライアントから使いやすくした入口です。UI や自社システムに組み込む場合は [api-reference.md](./api-reference.md) を利用してください。
