# jpcite API Docs

このドキュメントは、jpcite の **REST API** と **MCP server** を組み込む開発者・AI エージェント設定者向けの入口です。

jpcite は、日本の制度・法人・法令・税制・行政処分データを AI が使いやすい根拠パケットとして返す evidence prefetch layer です。制度候補、出典 URL、取得時刻、content hash、併用ルール、known gaps、decision insights を短い JSON で取得できます。アプリや AI クライアントは、その返却値を使って最終回答を作ります。

GPT / Claude / Cursor に長い PDF や公式ページを直接渡す前に、Evidence Packet を取得すると、出典付きの構造化 JSON を回答生成の入力にできます。元の入力トークン数を把握している場合は `source_tokens_basis=token_count&source_token_count=<tokens>` を渡すことで、返却パケットとの文脈サイズ比較も確認できます。現在の公開料金と匿名枠は [Pricing](./pricing.md) に掲載しています。

## 最初に読むもの

| 目的 | ページ |
|---|---|
| 5 分で API を試す | [Getting started](./getting-started.md) |
| エンドポイント一覧を見る | [API reference](./api-reference.md) |
| Claude / Cursor などのMCPクライアント、ChatGPT Custom GPT から使う | [MCP tools](./mcp-tools.md) / [API reference](./api-reference.md) |
| 5-15 行 runnable レシピ集 (12 本) | [Cookbook](./cookbook/index.md) |
| 調査コンテキストを小さくできる条件を見る | [MCP tools](./mcp-tools.md#evidence-packet) / [API reference](./api-reference.md) |
| 返却形式とエラー処理を合わせる | [Response envelope](./api-reference/response_envelope.md) / [Error handling](./error_handling.md) |
| 出典・根拠・除外ルールを確認する | [Exclusions](./exclusions.md) / [Honest capabilities](./honest_capabilities.md) |
| 料金と無料枠を確認する | [Pricing](./pricing.md) |

## 使える形

- **REST API**: `https://api.jpcite.com/v1/*`
- **Agent-safe OpenAPI**: [openapi/agent.json](./openapi/agent.json) / `https://api.jpcite.com/v1/openapi.agent.json` (ChatGPT Custom GPT Actions や AI tool import 向け)
- **Full OpenAPI**: [openapi/v1.json](./openapi/v1.json) / `https://api.jpcite.com/v1/openapi.json` (SDK 生成・完全リファレンス向け)
- **MCP server**: Claude Desktop / Cursor / Cline などの MCP クライアントで利用できます。ChatGPT Custom GPT では OpenAPI Actions 経由で同等の REST endpoint を呼び出します。
- **配布 package**: 互換性のため package 名は `autonomath-mcp` を維持しています。表示名とサービス名は jpcite です。

## AI agent 向け first call

1. 広い制度質問は `GET /v1/intelligence/precomputed/query?include_facts=false&include_compression=true`
2. 根拠 record、known gaps、文脈サイズ比較が必要なら `POST /v1/evidence/packets/query`
3. 実在 ID が必要な場合だけ `GET /v1/programs/search`
4. 詳細・併用確認は `GET /v1/programs/{unified_id}` / `POST /v1/exclusions/check`
5. AI クライアント側では `source_url` と `source_fetched_at` を添え、known gaps も明示する

## データ収録

| データ種別 | 検索対象 件数 |
|---|---:|
| 補助金 / 助成金 / 認定 | 11,601 |
| 採択事例 | 2,286 |
| 融資 | 108 |
| 行政処分 | 1,185 |
| 法令本文索引 | 6,493 |
| 法令メタデータ | 9,484 |
| 判例 | 2,065 |
| 税制ルールセット | 50 |
| 適格請求書発行事業者 | 13,801 |
| 排他 / 前提ルール | 181 |

品質ラベルは、出典・構造化・説明材料の充足度を表す目安です。重要な判断では、返却される `source_url` / `source_fetched_at` を確認し、必要に応じて一次資料も参照してください。
