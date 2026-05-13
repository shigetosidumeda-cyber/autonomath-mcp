# M&A advisor — 1 案件 DD

- snapshot_at: 2026-05-11
- 単価: ¥3 / billable unit (税込 ¥3.30)
- 想定読者: ミドル M&A の advisor / FA、ないし PE / VC の deal team で AI agent (Claude / GPT / Cursor 等) を運用するオペレータ

## 業務シナリオ

M&A advisor が 1 案件 (中小企業 sell side / buy side / 事業承継) の DD を着手する際、対象企業について「公開情報ベースの DD パック」を 1 セッションで揃える:

- 法人 identity 確定 (corporate_number / JCT registration)
- 登記情報照合 (houjin_master + houjin_360 3-axis scoring、Wave 23)
- 商号 / 所在地 / 役員変遷 (am_amendment_diff 12,116 行、cron-live 2026-05-02)
- 行政処分履歴 (enforcement_cases 1,185 行 + am_enforcement_detail 22,258 行 — grant_refund 1,498 / subsidy_exclude 476 / fine 26 carry amount_yen)
- 適格事業者照合 (invoice_registrants 13,801 行 delta + 月次 4M 行 bulk)
- 採択補助金履歴 (jpi_adoption_records 201,845 行)
- 国税 saiketsu (140+ 行) と通達 (3,221 行) で税務争点の有無
- 事業承継 制度マッチング (api/succession.py、R8 grow)
- M&A 関連の助成金 / 補助金 (事業承継・引継ぎ補助金、中小 M&A 支援措置等)
- 監査済 audit_pack の assembly (createCompanyPublicAuditPack、counterparty_dd_and_audit_prep シーケンス)

## 利用量と課金 (実数)

| 項目 | 値 |
|---|---|
| 1 案件 req 数 | 47 (mcp.json `cost_examples.M&A DD 1社` = 47 req) |
| 単価 | ¥3.30/unit (税込) |
| **1 案件 jpcite 課金** | **¥155.10** |

`createCompanyPublicBaseline` → `createCompanyPublicAuditPack` → `match_advisors_v1_advisors_match_get` の counterparty_dd_and_audit_prep シーケンス (mcp.json `recurring_agent_workflows`) で実行。`previewCost` で実行前見積もり。

## 業務単価との比較

| 項目 | 値 |
|---|---|
| ミドル M&A DD 料 (財務 / 税務 / 法務 / 商業) | ¥100-500 万/件 |
| 事業承継 advisor 報酬 | ¥30-200 万/件 |
| Lead 段階の case 評価に使う初期調査工数 | 10-30 時間 × ¥10,000-30,000/h = ¥10-90 万/件 |
| jpcite 課金 / DD 料 | **0.003 - 0.016%** |

## 費用対効果の前提 — 取りこぼし 1 件で何が起きるか

M&A DD で公開情報の見落としが致命傷になる典型:

- **行政処分・指名停止履歴の見落とし** — クロージング後に発覚して契約解除 / 損害賠償。advisor 側に説明責任が及ぶ
- **過去の補助金交付決定取消 (grant_refund、enforcement 1,498 行が amount_yen 持ち)** — 返還義務が買い手に承継、deal economics 崩壊
- **適格事業者番号の登録漏れ・取消し** — 取引先からの仕入税額控除不能で買収後の P/L が崩れる
- **役員変遷・商号変遷の追跡漏れ** — 反社チェックの基準データを誤認 → 銀行 / LBO ファイナンス停止
- **税務争点 (saiketsu) の見落とし** — 過去類似事例で否認されたスキームを継承 → クロージング後の追徴課税

DD 失敗 1 件では re-do コスト、報酬返金、顧客説明、専門家再レビュー、信用毀損などが発生しうる。金額は契約規模・責任分界・保険条件に依存するため、ここでは損害額を保証せず、公開情報 DD の確認漏れを減らすためのコストとして扱う。

明示的な利用前提では、1 案件 47 req、税込 **¥155.10/件**。100 案件を初期評価しても **¥15,510** で、法人 identity・行政処分・適格事業者・採択履歴・税務争点の公開情報チェックを同じ手順で回せる。

## なぜ web search や anonymous 枠で代替できないか

- **web search**: 行政処分公示 (国交省 / 経産省 / 都道府県・市区町村) と国税 saiketsu (国税不服審判所) は完全に分散。手で全部当たって整合性を取る作業に 1 案件 10-30 時間
- **anonymous 3 req/日**: 1 案件 47 req のため 16 日かかる計算。Deal team の DD タイムボックス (1-4 週間) に乗らない上、IP 共有のため複数 advisor で quota が枯渇
- **汎用 RAG**: 適格事業者照合・行政処分照合・採択履歴照合は curated DB が無いと不可能。corporate_entity 166,969 行 / am_enforcement_detail 22,258 行 / invoice_registrants 13,801 行 delta + 月次 4M 行 bulk は jpcite 固有

## jpcite を使った場合の構造的優位

- `createCompanyPublicBaseline` で法人 identity + 公的情報を一括取得
- `houjin_360` (3-axis scoring) で 法人 unified スコア
- `am_amendment_diff` (12,116 行 cron-live) で 商号 / 所在地 / 役員 の変遷を時系列で参照
- `track_amendment_lineage_am` (Wave 21) で制度 / 法人改正の lineage 追跡
- `cross_check_jurisdiction` (Wave 22) で 登記 / 適格事業者 / 採択地域 の不一致検出
- `createCompanyPublicAuditPack` で audit-ready のパック化
- 弁護士法 §72 + 公認会計士法 §47の2 fence により「個別法律相談」「監査意見の表明」は出さない構造制約。advisor の意思決定責任の領域を侵さない

## 反論への先回り

- 「DD は弁護士・会計士の領域では?」 → jpcite は DD の **公開情報部分 (Public-Info DD)** を集約するだけで、専門判断は弁護士・会計士に handoff する設計。`evidence_to_expert_handoff` (mcp.json) が明示しているように、jpcite output は「専門家レビュー前の bounded evidence brief」であって、final professional answer ではない
- 「機密性の高い DD で外部 API を叩いて大丈夫か?」 → jpcite が扱うのは 公開情報のみ (登記 / 適格事業者 / 行政処分 / 採択補助金 / 国税 saiketsu / 通達)。target 企業の非公開財務情報を入力する API ではない。Stripe + Fly Tokyo の通常 SaaS セキュリティ水準で問題ない
- 「47 req は M&A DD としては少なすぎないか?」 → 1 案件で 47 req は最初の reach。継続調査・複数 target 比較・複数 round の進捗で 100-500 req/案件まで膨らんでも、それでも ¥330 - ¥1,650 (税込) で DD 料 0.01-0.165%

## 関連 endpoint / 設定

- `createCompanyPublicBaseline` — 1 案件の最初の paid call
- `createCompanyPublicAuditPack` — audit-ready packet assembly
- `match_advisors_v1_advisors_match_get` — advisor handoff
- `houjin_360` — 法人 3-axis scoring (R8)
- `cross_check_jurisdiction` — 登記 / 適格事業者 / 採択地域の不一致検出 (Wave 22)
- `track_amendment_lineage_am` — 制度・法人改正 lineage (Wave 21)
- `houjin_watch` — リアルタイム法人改正 webhook (migration 088、継続監視の中核)
- `dispatch_webhooks.py` cron — webhook 配信
- `previewCost` — 実行前見積もり

## まとめ

M&A 1 案件 DD で ¥155.10 (税込)。DD 料比 0.003-0.016%。公開情報の確認漏れを減らすため、法人 identity・行政処分・適格事業者・採択履歴・税務争点を低い案件単価で揃える。弁護士法 §72 + CPA 法 §47の2 fence により専門判断領域は犯さず、advisor の意思決定の **下地 (Public-Info DD)** として組み込み安全。`houjin_watch` + webhook で継続監視も可能。
