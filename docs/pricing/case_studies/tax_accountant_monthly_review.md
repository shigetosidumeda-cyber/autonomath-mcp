# 税理士 — 100 顧問先 月次制度レビュー

- snapshot_at: 2026-05-11
- 単価: ¥3 / billable unit (税込 ¥3.30)
- 想定読者: 税理士事務所の所長 or 担当者、ないしその事務所で AI agent (Claude / GPT / Cursor 等) を運用するオペレータ

## 業務シナリオ

税理士 1 人が 100 顧問先を抱え、毎月の月次レビューで「先月以降に新設・改正された補助金 / 融資 / 税制特例のうち、当該顧問先に compatibility のある制度」を 1 件以上ピックアップして顧問先に共有する。

- 各顧問先 1 req: `queryEvidencePacket` 経由で houjin_bangou + 業種 + 規模 + 地域を渡し、Evidence Packet (source_url + fetched_at + known_gaps 入り) を取得
- `X-Client-Tag` で顧問先別に課金を分離 (migration 085 で `usage_events.client_tag` 着地済)
- 必要に応じて `prescreenPrograms` (recurring_agent_workflows.monthly_client_review シーケンス) を追加 call

## 利用量と課金 (実数)

| 項目 | 値 |
|---|---|
| 顧問先数 | 100 社 |
| 月次 req 数 | 100 (顧問先 1 件 1 req) |
| 単価 | ¥3.30/unit (税込) |
| **月次 jpcite 課金** | **¥330** |
| 年間 jpcite 課金 | ¥3,960 |

`previewCost` で実行前見積もり、月額上限を ¥1,000 / ¥5,000 等で設定可能 (実行量より十分高い水準で十分)。

## 業務単価との比較

| 項目 | 値 |
|---|---|
| 顧問契約 1 件 単価 (業界実勢) | ¥3-10 万/月 |
| 100 顧問先 月次レビューの jpcite 課金 | ¥330/月 |
| 顧問契約 1 件あたりの jpcite 課金 | ¥3.30/月 (税込) |

## 費用対効果の前提 — 取りこぼし 1 件回避で何が起きるか

仮に jpcite を入れず、IT 導入補助金 (通常枠、上限 ¥150 万) を 1 顧問先で取りこぼしたとする:

- 顧問先損害: ¥150 万級 (補助金機会損失) + 投資意思決定の歪み
- 顧問契約解除 (¥3-10 万/月) に発展: 年間 ¥36-120 万のロス
- 解除リスクが他顧問先にも波及 (口コミ) → 隠れた upside loss

jpcite 年間課金は **¥3,960**。この支出で、100 顧問先に対して毎月 1 req ずつ evidence packet を取得し、補助金・融資・税制特例の候補を確認する。顧問契約解除や機会損失の金額は顧問先ごとに異なるため、ここでは保証値ではなく確認漏れを減らすための固定費として扱う。

## なぜ web search や anonymous 枠で代替できないか

- **web search**: 100 顧問先分を毎月手で検索する工数が破綻する。aggregator (noukaweb / hojyokin-portal) 由来の旧版要件を骨格にすると、滝のように下流で誤判定が連鎖
- **anonymous 3 req/日**: 100 顧問先 1 ヶ月のレビューに 34 日かかる計算。業務に物理的に間に合わない
- **一般 AI / 長文資料投入**: 自治体補助金・公庫融資・税制特例の網羅性が著しく薄い + 税理士法 §52 fence なし

## jpcite を使った場合の構造的優位

- `source_url` が一次資料に直リンク (aggregator ban)
- `source_fetched_at` で「いつ取った情報か」が常に分かる
- `known_gaps` を Evidence Packet が明示
- 税理士法 §52 fence が出力に常に差し込まれる (個別税務助言は出さない / 申告は税理士に確認、と response が自分で言う)
- `X-Client-Tag` で顧問先別の利用集計 → 顧問料に付加価値費として透明に転嫁可能

## 反論への先回り

- 「100 req は少なすぎないか?」 → 月次レビューに必要な reach であって、書面化・申請補助で追加 req を呼ぶ場合は `prescreenPrograms` / `bundle_application_kit` / `audit_seal` 等を別途追加。それでも 1 顧問先で年間 ¥100 オーダー以下に収まる
- 「LLM API は別途かかるのでは?」 → jpcite 側で LLM API は呼ばない。AI agent (Claude Code / Cursor / GPT 等) は顧客側の契約 (ChatGPT Team / Claude Pro / Cursor Pro 等の月額 ¥3,000 級) で動かし、jpcite は evidence prefetch 専用なので単価が固定

## 関連 endpoint / 設定

- `queryEvidencePacket` — 月次レビューの一次 call
- `prescreenPrograms` — 候補制度の事前 screen
- `X-Client-Tag` — 顧問先別課金分離 (migration 085)
- `previewCost` — 実行前見積もり
- `audit_seal` — 月次 audit-seal pack PDF + RSS (migration 089)
- `client_profiles` — 顧問先 master table (migration 096)
- `saved_searches.profile_ids` — 顧問先別 fan-out saved search (migration 097)
- `run_saved_searches.py` cron — 顧問先別 saved search を cron 化

## まとめ

100 顧問先月次レビュー、月額 ¥330 (顧問契約 1 件あたり ¥3.30/月)。月 100 req、年 1,200 req の固定的な公開情報チェックとして運用できる。anonymous 枠・web search・長文資料を毎回 AI に渡す運用では物理的・構造的に達成不能。
