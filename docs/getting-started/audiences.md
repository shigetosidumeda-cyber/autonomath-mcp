# 利用者別の始め方

jpcite は、AI が回答を書く前に日本の公的情報を取りに行くための Evidence Pre-fetch Layer です。ここでは、利用者ごとに最初に試す endpoint と、課金利用へ移る時の使い方だけを整理します。

| まずやること | 使い方 | 課金への移り方 |
| --- | --- | --- |
| 匿名で確認 | 登録不要で 3 API/MCP 呼び出し/日まで無料。`GET /v1/usage` と `POST /v1/cost/preview` は確認用で、匿名 3 回枠を消費しません。 | 反復利用する場合は API キーを発行します。 |
| トライアル | メール認証だけで 14 日 / 200 req。カード不要。 | 期間後または上限到達後、同じ workflow を有料キーで継続します。 |
| 業務利用 | 通常 1 API/MCP 呼び出し = 1 billable unit = 税込 ¥3.30。 | `X-Client-Tag` と `X-Cost-Cap-JPY` で顧客・案件別に原価管理します。 |

## AI agent / BPO チーム

最初は `GET /v1/usage` で残り回数を確認し、`POST /v1/cost/preview` で想定費用を確認します。実行は `POST /v1/evidence/packets/query` または `POST /v1/artifacts/company_public_baseline` から始めるのが安全です。

継続利用では `X-API-Key` または `Authorization: Bearer` を付け、案件単位で `X-Client-Tag` を固定します。POST の再試行には `Idempotency-Key`、広い batch / fanout には `X-Cost-Cap-JPY` を付けます。

## 税理士・会計士・行政書士

顧問先や相談者の会社フォルダを作る場合は、法人番号が分かるなら `POST /v1/artifacts/company_public_baseline` から始めます。制度候補の一次スクリーニングは `POST /v1/programs/prescreen`、根拠付きの回答素材は `POST /v1/evidence/packets/query` を使います。

jpcite の出力は最終判断ではありません。`source_url`、`source_fetched_at`、`known_gaps`、`human_review_required` を残したまま、専門家レビューや顧客ヒアリングに渡してください。

## 補助金・融資・BPO コンサル

制度候補を広く拾うだけなら `GET /v1/programs/search`、会社・事業プロフィールから候補を絞るなら `POST /v1/programs/prescreen` を使います。併用可否や組み合わせ確認は `POST /v1/funding_stack/check` を使います。

制度名だけで断定せず、返却された `match_reasons`、`caveats`、`eligibility_gaps`、`source_url` を提案書や確認リストに移してください。

## 会社管理・監査・DD

取引先、投資先、顧問先、監査対象の初期確認では `POST /v1/artifacts/company_public_baseline` を first-hop にします。必要に応じて `POST /v1/artifacts/company_public_audit_pack` で、source receipts、mismatch flags、review controls をまとめます。

公的情報で確認できない点は `known_gaps` として扱います。空欄を「リスクなし」と解釈しないでください。

## 関連ページ

- [Getting Started](../getting-started.md)
- [REST API reference](../api-reference.md)
- [Pricing](../pricing.md)
- [Audience landing pages](https://jpcite.com/audiences/)
