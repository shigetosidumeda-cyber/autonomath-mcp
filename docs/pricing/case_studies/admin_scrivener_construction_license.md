# 行政書士 — 建設業許可 1 件 DD

- snapshot_at: 2026-05-11
- 単価: ¥3 / billable unit (税込 ¥3.30)
- 想定読者: 建設業許可・更新・業種追加を扱う行政書士、ないしその事務所で AI agent (Claude / GPT / Cursor 等) を運用するオペレータ

## 業務シナリオ

行政書士が新規申請 / 更新 / 業種追加を 1 件着手する際、対象法人について「公開情報ベースの DD パック」を 1 回で揃える。具体的には:

- houjin_bangou による法人 identity 確定
- 商号 / 所在地 / 役員構成の登記情報照合 (houjin_master)
- 建設業に紐づく行政処分・指名停止履歴 (enforcement_cases 1,185 行)
- 適格事業者 (NTA invoice_registrants 13,801 行 delta + 月次 4M 行 bulk)
- 業種コード × 過去採択事例 (case_studies 2,286 行 / am_industry_jsic 37 行)
- 業法上の要件 (建設業法 + 業種別追加要件) を法令本文 (6,493 法令本文 indexed) で根拠付け
- compatibility / 排他ルール (181 exclusion rules) で「申請してはいけない条件」の事前検出

## 利用量と課金 (実数)

| 項目 | 値 |
|---|---|
| 1 案件 req 数 | 18 (mcp.json `cost_examples.1社フォルダ作成パック` = 18 req) |
| 単価 | ¥3.30/unit (税込) |
| **1 案件 jpcite 課金** | **¥59.40** |

`createCompanyPublicBaseline` → `createCompanyFolderBrief` → `queryEvidencePacket` の company_folder_intake シーケンス (mcp.json `recurring_agent_workflows`) で実行。前に `previewCost` を 1 回呼んで合計予測を確認可能。

## 業務単価との比較

| 項目 | 値 |
|---|---|
| 建設業許可申請報酬 (新規) | 約 ¥15-30 万/件 (業界実勢) |
| 建設業許可更新報酬 | 約 ¥10-15 万/件 |
| 業種追加報酬 | 約 ¥5-15 万/件 |
| jpcite 課金 / 報酬 | **0.020 - 0.059%** |

## 費用対効果の前提 — 取りこぼし 1 件で何が起きるか

行政書士の建設業許可 DD で取りこぼしが起きる典型は:

- **役員に過去 5 年以内の建設業法違反処分歴あり** — 許可要件不適合で申請却下、行政書士の事務所に責任が及ぶ
- **指名停止履歴あり** — 結果として許可は通っても、自治体入札参加で別途引っかかる
- **業種別の追加要件 (専任技術者・財産的基礎) を見落とし** — 申請差し戻し、顧客から信頼喪失 + 報酬返金 + 賠償リスク
- **適格事業者番号の不一致** — 元請からの取引で信用毀損

申請差し戻し or 賠償案件 1 件で、再確認・顧客説明・返金・専門家相談などの追加コストが発生する。金額は案件内容と契約条件に依存するため、ここでは定量保証せず、発生しうるコスト項目として扱う。

明示的な利用前提を置くと、月 10 件なら jpcite 課金は 10 件 × 12 ヶ月 × ¥59.40 = **¥7,128/年**。この支出で、建設業法要件・行政処分・適格事業者番号・排他条件の確認漏れを減らすための evidence pack を案件ごとに揃える、という位置づけ。

## なぜ web search や anonymous 枠で代替できないか

- **web search**: 建設業法違反の行政処分情報は単独データベースに無い (国交省 + 自治体に分散)。手作業で 1 件 30-60 分かかり、案件単価を圧迫
- **anonymous 3 req/日**: 1 案件 18 req のため、anonymous では 1 件で 6 日かかる計算。実用不能
- **一般 AI / 長文資料投入**: enforcement_cases (1,185 行) や invoice_registrants (13,801 行 delta + 月次 4M bulk) は curated DB が無いと網羅不能。aggregator 経由は信頼性が業務水準に届かない

## jpcite を使った場合の構造的優位

- `createCompanyPublicBaseline` で法人 identity + 公的情報を一括取得
- `enforcement_cases` (1,185 行) + `am_enforcement_detail` (22,258 行) で行政処分履歴を 1 unit で照会
- `invoice_registrants` (13,801 行 delta + 月次 4M 行 bulk 自動 ingest) で適格事業者照合
- 行政書士法 §19 fence が出力に常に差し込まれる (申請書面の代理作成は出さない / 申請は行政書士に確認、と response が自分で言う)
- `bundle_application_kit` で必要書類チェックリストの assembly が可能 (申請書面そのものは作らない)

## 反論への先回り

- 「行政書士法 §19 で申請代理は行政書士独占だが jpcite はその領域を犯さないか?」 → 8 業法 fence の design 原則で犯さない。jpcite は「公開要件の構造化」「事前要件チェイン」のみで、申請書面の作成・提出代行は構造的に出さない (`data/fence_registry.json` の `administrative_scrivener.do_not` 参照)
- 「DD パック 18 req は多すぎないか?」 → 同一案件で実 query 18 件は妥当。entity baseline (1 req) + houjin_master (1 req) + enforcement 照合 (2-3 req) + invoice 照合 (1 req) + 業種別要件 (3-5 req) + 排他ルール / 採択事例 / 法令本文 引照で 7-10 req。実数として 18 req は中庸

## 関連 endpoint / 設定

- `createCompanyPublicBaseline` — 1 案件の最初の paid call
- `createCompanyFolderBrief` — 法人サマリ + 引照付きフォルダ assembly
- `queryEvidencePacket` — 法令本文 + 排他ルール照合
- `prerequisite_chain` — 事前要件チェイン (Wave 21 composition)
- `bundle_application_kit` — 必要書類チェックリスト assembly (Wave 22 composition、行政書士法 §1の2・§19 fence 付き)
- `cross_check_jurisdiction` — 登記 / 適格事業者 / 採択地域の不一致検出 (Wave 22)
- `previewCost` — 実行前見積もり

## まとめ

建設業許可 1 案件 DD、¥59.40 (税込)。報酬比 0.02-0.06%。申請差し戻し・顧客説明・返金リスクにつながる確認漏れを減らすため、公開情報の evidence pack を低い案件単価で揃える。行政書士法 §19 fence により申請代理領域は犯さず、行政書士事務所の補助線として使う。専門判断・申請代理の代替ではなく、公開情報の確認下地としてレビューしてください。
