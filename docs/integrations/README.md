# jpcite Integrations Index

更新日: 2026-05-05  
目的: AI agent / API / UI が jpcite を「検索結果」ではなく、根拠付きの業務完成物として扱うための integration docs 索引。

この索引の対象は、価格変更ではありません。焦点は次の4点です。

1. 無料3回/日は通常品質のアウトプットを返す。
2. ユーザー満足度は候補一覧ではなく、顧問先メモ、申請キット、DDパック、稟議シート、監視ダイジェストなどの完成物で作る。
3. 派生データで順位、勝ち筋、不足情報、差分、確認範囲を出せるようにする。
4. Evidence Packet 後は、文脈に合う完成物 CTA へつなげる。

## Primary Docs

| File | Role | Use When |
|---|---|---|
| [`deep-paid-output-and-data-foundation-plan.md`](./deep-paid-output-and-data-foundation-plan.md) | 成果物設計、データ基盤、無料3回、完成物CTA、派生レイヤーの全体方針 | どの方向に実装を寄せるか、artifact中心の判断を確認する |
| [`output-satisfaction-spec.md`](./output-satisfaction-spec.md) | 無料3回/通常利用で共通する出力品質標準 | API response、UI表示、agent wrapper の最低品質を決める |
| [`artifact-catalog.md`](./artifact-catalog.md) | artifact type 別の入力、出力セクション、必要データ、品質ゲート | 顧問先メモ、申請キット、法人DDなどの完成物を実装する |
| [`derived-data-layer-spec.md`](./derived-data-layer-spec.md) | 深い回答を支える派生データレイヤー仕様 | DB/view/service 層で ranking、risk、source quality、document requirement、delta を作る |
| [`agent-routing-and-cta-spec.md`](./agent-routing-and-cta-spec.md) | AI agent の use/skip 判断、無料枠表示、429、完成物CTA、0件時文言 | README、llms.txt、OpenAPI、MCP、Actions、Cursor/Claude/Codex 向け文言を揃える |
| [`ai-agent-recommendation-plan.md`](./ai-agent-recommendation-plan.md) | AI agent に jpcite を推薦させるための配布・説明計画 | Claude / ChatGPT / Cursor などに向けた positioning、manifest、cookbook を整える |

## Implementation Reading Order

1. [`output-satisfaction-spec.md`](./output-satisfaction-spec.md) で、無料3回でも落とさない通常品質の response contract を確認する。
2. [`artifact-catalog.md`](./artifact-catalog.md) で、ユーザー文脈ごとの完成物と品質ゲートを選ぶ。
3. [`derived-data-layer-spec.md`](./derived-data-layer-spec.md) で、完成物に必要な派生データと `known_gaps` の出し方を実装へ落とす。
4. [`agent-routing-and-cta-spec.md`](./agent-routing-and-cta-spec.md) で、agent がいつ jpcite を呼ぶか、Evidence Packet 後に何を提示するかを揃える。
5. [`deep-paid-output-and-data-foundation-plan.md`](./deep-paid-output-and-data-foundation-plan.md) と [`ai-agent-recommendation-plan.md`](./ai-agent-recommendation-plan.md) で、全体方針と外部 agent 向け配布文言に矛盾がないか確認する。

## Shared Contract

新規 integration 実装は、次の contract を満たす。

| Area | Required Direction |
|---|---|
| Free 3/day | 匿名無料枠でも通常品質を返す。根拠URL、取得日時、候補名、known_gaps を隠さない |
| Output shape | `source_url`, `source_fetched_at`, `known_gaps`, `_disclaimer`, `quality_tier` 相当を落とさない |
| Completion | 検索結果だけで終えず、文脈に合う artifact CTA を提示する |
| Derived data | ranking、risk、document requirement、source quality、monitoring delta を派生レイヤーで作る |
| Zero result | 「存在しない」と断定せず、収録範囲、条件拡張、一次確認先を返す |
| Judgment boundary | 税務、法務、申請可否、融資可否の最終判断を出さない |

## Wave 2 Focus

Wave 2 の実装対象は、価格表や unit 単価の変更ではなく、次のユーザー体験を形にすること。

| Focus | Implementation Target |
|---|---|
| アウトプット満足度 | 候補一覧を、結論サマリ、次アクション、根拠カード、確認範囲、顧客向け文面に変換する |
| 無料3回通常品質 | 3 req/day の範囲でも同じ response contract を返し、回数と継続CTAだけで差をつける |
| 派生データ | `program_decision_layer`, `corporate_risk_layer`, `source_quality_layer`, `document_requirement_layer`, `monitoring_delta_layer` を実装候補にする |
| CTA | Evidence Packet 後に `顧問先メモにする`, `申請前チェックリストを作る`, `法人DDパックを作る`, `月次監視に追加` などを返す |
