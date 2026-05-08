# 価格・需要戦略メモ 2026-05-08

## 結論

`¥3/billable unit` は据え置く。10万 units/day は単発検索の自然需要ではなく、AI agent / BPO / 士業システム / 監査・DD / 営業支援の自動ワークフローに組み込まれた時の到達KPIとして扱う。

## なぜ値上げを先にしないか

- `¥3/unit` は、AI agent が回答前に first-hop evidence call を実行しやすい心理的単価。
- 一律値上げは、高頻度のBPO・AI開発・広域スクリーニング用途を鈍らせる。
- jpcite は「安い検索API」ではなく、source URL、取得時刻、known gaps、互換/排他ルール、監査ログを返す Evidence layer として評価されるべき。
- 高単価化する場合は base unit ではなく、audit/DD pack、company baseline batch、watch digest、hosted connector、private ingest、SLA など成果物・運用価値側で行う。

## 10万/day の現実的な発生条件

- 人間の手動検索ではなく、会社・顧問先・案件ごとの反復処理。
- 例: 50 組込先 × 2,000 units/day、または 500 組織 × 200 units/day。
- 主要導線は `previewCost -> paid evidence/artifact call -> client_tag付き継続利用 -> dashboard/capで管理`。

## 値上げ判断前の観測指標

- `daily_billable_units = SUM(quantity) WHERE metered=1 AND status<400`
- `paid_key_7d_retention`
- `first_billable` 到達率
- `previewCost -> paid evidence call` 転換率
- `client_tag` 付き units 比率
- `scheduled job / webhook / batch / connector` 経由 units 比率
- paid key あたり 7日 units と上位顧客集中度
- `X-Cost-Cap-JPY` / monthly cap 設定率

## 公開文面の原則

- 「外部LLM料金を削減保証」と言わない。
- 「10万/day需要がある」と断定しない。
- 「人間が毎日10万回使う」と見える表現を避ける。
- 「自動化ワークフローでの運用KPI」「実行前見積もり」「月次上限」「顧客別原価管理」として説明する。
