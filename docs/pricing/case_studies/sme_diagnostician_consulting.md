# 中小企業診断士 — 経営診断 1 件

- snapshot_at: 2026-05-11
- 単価: ¥3 / billable unit (税込 ¥3.30)
- 想定読者: 中小企業診断士 (登録診断士)、ないし認定支援機関業務を扱う事務所で AI agent (Claude / GPT / Cursor 等) を運用するオペレータ

## 業務シナリオ

中小企業診断士が経営診断 1 件を着手する際、対象企業について「公開情報ベースの経営環境 DD パック」を 1 セッションで揃える:

- 法人 identity + 業種コード (JSIC major) 確定
- 業種コホート統計 (am_industry_jsic 37 行 — JSIC majors A-T カバー)
- 採択事例コホート (case_studies 2,286 行 + jpi_adoption_records 201,845 行) で業種別補助金採択動向
- 業種別税制特例 (tax_rulesets 50 行) で研究開発税制・IT 導入会計処理・GX 投資減税の適用可否
- 採択後カレンダー (program_post_award_calendar、migration 098) で「採択後 monitoring 義務」の把握
- 行政処分履歴 (enforcement_cases 1,185 行) で当該企業 / 同業他社の処分動向
- DD 質問デッキ (Wave 22 `match_due_diligence_questions`、`dd_question_templates` 60 seed × 業種別マッチ)

## 利用量と課金 (実数)

| 項目 | 値 |
|---|---|
| 1 案件 req 数 | 47 (mcp.json `cost_examples.M&A DD 1社` = 47 req、経営診断 1 件はこれに準じる) |
| 単価 | ¥3.30/unit (税込) |
| **1 案件 jpcite 課金** | **¥155.10** |

DD-style の深掘り 1 件で 47 req。pricing.html の「申請戦略パック: 受付案件 200 件を 3 call で一次整理」(600 units = ¥1,980) のような bulk triage ではなく、1 件で深く掘る構成。

## 業務単価との比較

| 項目 | 値 |
|---|---|
| 経営診断料 (業界実勢) | ¥10-30 万/件 |
| 認定支援機関業務 (経営改善計画策定支援) | ¥15-30 万/件 (補助金交付対象案件) |
| jpcite 課金 / 診断料 | **0.052 - 0.155%** |

## ROI 倍率 — 取りこぼし 1 件で何が起きるか

中小企業診断士の経営診断で見落とすと痛い典型:

- **事業再構築補助金・ものづくり補助金の適用可能性を見落とし** — 補助上限 ¥1,500 万 - ¥1 億の機会損失
- **研究開発税制 (試験研究費総額型) を見落とし** — 試験研究費 ¥5,000 万なら税額控除 ¥500 万級
- **GX 投資減税 / 中小企業経営強化税制を見落とし** — 設備投資 1 億で税控除 ¥1,000 万級
- **業種別 cohort 統計を取らず汎用的な診断を出した結果、顧客から「相場感覚が無い」と評価され継続契約落ち** — 認定支援機関業務の年間継続 ¥50-200 万のロス

¥155.10/件 を払うことで、1 件で補助金 ¥1,500 万級の取りこぼしを回避できれば **ROI 倍率は 10 万倍級**。継続契約 1 件のロス回避ベースでも **600-1,900 倍**。

## なぜ web search や anonymous 枠で代替できないか

- **web search**: tax_rulesets の研究開発税制 措置法 42-4・IT 導入補助金会計処理は条文 + 通達 + 国税庁 saiketsu の組み合わせで決まる。web search だと国税庁ページ / 経産省ページ / aggregator がバラバラに返り、組み合わせを 人手で復元する負荷が高い
- **anonymous 3 req/日**: 1 案件 47 req のため 16 日かかる計算。経営診断のタイムボックス (1 週間 - 1 ヶ月) に乗らない
- **汎用 RAG**: 業種コホート統計や採択事例 cohort matching は curated DB が無いと不可能。複数 DB JOIN の `pack_construction` / `pack_manufacturing` / `pack_real_estate` 相当の表現は汎用 RAG が日本公的領域では届かない

## jpcite を使った場合の構造的優位

- `pack_construction` / `pack_manufacturing` / `pack_real_estate` (Wave 23) で業種別 top 10 programs + saiketsu + 通達 を 1 セットで返却
- `match_due_diligence_questions` (Wave 22) で 業種 × 規模 × 与信 risk 別の DD 質問 30-60 を 1 req で生成 (dd_question_templates 60 seed × 7 categories)
- `forecast_program_renewal` (Wave 22) で 制度の翌 FY 更新確率 + window を 4 signal 加重平均で予測
- 中小企業診断士登録規則 fence で「個別経営診断書発行」は出さない構造制約
- `audit_seal` (migration 089) で月次サマリの PDF 化が認定支援機関業務のドキュメント化に直結

## 反論への先回り

- 「経営診断書を出さないなら何のための tool か?」 → 経営診断書のドラフトを作るための **根拠集約 (Evidence Packet)** + 質問デッキ + 業種コホート統計を提供する。診断書そのものは診断士本人が書く。診断士が 1 から手作業で集めると 1 件 4-10 時間かかる作業が、jpcite + AI agent で 30 分 - 1 時間に圧縮できる
- 「47 req は多いのでは?」 → 業種統計 (3-5 req) + 採択事例 cohort (5-10 req) + 税制特例適用可否 (5-8 req) + DD 質問デッキ (1-3 req) + 行政処分照合 (2-3 req) + 排他ルール (3-5 req) + Evidence Packet 引照 (8-12 req) で 1 案件 47 req は典型的な分布

## 関連 endpoint / 設定

- `pack_manufacturing` / `pack_construction` / `pack_real_estate` — JSIC major 別の業種 pack (Wave 23)
- `match_due_diligence_questions` — DD 質問デッキ (Wave 22)
- `prepare_kessan_briefing` — 月次 / 四半期 制度改正サマリ (Wave 22)
- `forecast_program_renewal` — 制度更新確率 + window (Wave 22)
- `search_acceptance_stats_am` — 採択統計
- `simulate_application_am` — 申請シミュレーション (Wave 21)
- `find_complementary_programs_am` — 補完制度発見 (Wave 21)
- `previewCost` — 実行前見積もり

## まとめ

経営診断 1 件で ¥155.10 (税込)。診断料比 0.05-0.16%、補助金 ¥1,500 万級の取りこぼし回避で ROI 倍率 10 万倍級、継続契約ベースでも 600-1,900 倍。中小企業診断士登録規則 fence により「個別経営診断書発行」は出さず、診断士の補助線として組み込み安全。
