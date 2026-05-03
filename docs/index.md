# jpcite API Docs

このドキュメントは、jpcite の **REST API** と **MCP server** を組み込む開発者・AI エージェント設定者向けの入口です。

jpcite は回答文を生成するサービスではありません。制度候補、出典 URL、取得時刻、content hash、併用ルール、根拠パケットを返します。アプリや AI クライアントは、その返却値を使って最終回答を作ります。LLM 側のトークン量や検索回数への影響は使い方に依存します。現在の公開料金と匿名枠は [Pricing](./pricing.md) に掲載しています。

GPT / Claude / Cursor に長い PDF や公式ページを直接渡す前に、Evidence Packet を取得すると、短い出典付き JSON を回答生成の入力にできます。元の入力トークン数を把握している場合は `source_tokens_basis=token_count&source_token_count=<tokens>` を渡すことで、返却パケットとの文脈サイズ比較も確認できます。これは入力文脈の見積もりであり、LLM 事業者の請求額削減を保証するものではありません。

## 最初に読むもの

| 目的 | ページ |
|---|---|
| 5 分で API を試す | [Getting started](./getting-started.md) |
| エンドポイント一覧を見る | [API reference](./api-reference.md) |
| Claude / Cursor などのMCPクライアント、ChatGPT Custom GPT から使う | [MCP tools](./mcp-tools.md) / [API reference](./api-reference.md) |
| 調査コンテキストを小さくできる条件を見る | [MCP tools](./mcp-tools.md#evidence-packet) / [API reference](./api-reference.md) |
| 返却形式とエラー処理を合わせる | [Response envelope](./api-reference/response_envelope.md) / [Error handling](./error_handling.md) |
| 出典・根拠・除外ルールを確認する | [Exclusions](./exclusions.md) / [Honest capabilities](./honest_capabilities.md) |
| 料金と無料枠を確認する | [Pricing](./pricing.md) |

## 使える形

- **REST API**: `https://api.jpcite.com/v1/*`
- **OpenAPI**: [openapi/v1.json](./openapi/v1.json)
- **MCP server**: Claude Desktop / Cursor / Cline などの MCP クライアントで利用できます。ChatGPT Custom GPT では OpenAPI Actions 経由で同等の REST endpoint を呼び出します。
- **配布 package**: 互換性のため package 名は `autonomath-mcp` を維持しています。表示名とサービス名は jpcite です。

## 代表的な使い方

1. `GET /v1/programs/search` で制度候補を検索する
2. `GET /v1/programs/{id}` で制度詳細と出典 URL を取る
3. `POST /v1/exclusions/check` で併用不可・前提条件を確認する
4. `GET /v1/source_manifest/{program_id}` または Evidence Packet 系 endpoint で根拠 chain を確認する
5. AI クライアント側では `source_url` と取得時刻を添えて回答する

## データ収録

| データ種別 | 検索対象 件数 |
|---|---:|
| 補助金 / 助成金 / 認定 | 11,684 |
| 採択事例 | 2,286 |
| 融資 | 108 |
| 行政処分 | 1,185 |
| 法令本文 | 154 |
| 法令メタデータ | 9,484 |
| 判例 | 2,065 |
| 税制ルールセット | 50 |
| 適格請求書発行事業者 | 13,801 |
| 排他 / 前提ルール | 181 |

品質ラベルは、出典・構造化・説明材料の充足度を表す目安です。重要な判断では、返却される `source_url` / `source_fetched_at` を確認し、必要に応じて一次資料も参照してください。
