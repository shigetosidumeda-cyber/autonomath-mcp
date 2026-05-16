# CSV-derived Output Catalog by User Type Deep Dive

作成日: 2026-05-15  
担当: CSV-derived output catalog by user type  
Status: pre-implementation planning only. 実装コードは触らない。  
保存先: `docs/_internal/csv_output_catalog_by_user_type_deepdive_2026-05-15.md`

## 0. 結論

会計CSVから作るP0価値は、税務判断・会計処理判断ではなく、AIエージェントがエンドユーザーへ安全に渡せる次の3種類に限定する。

1. CSV由来の派生事実: 期間、列、行数、科目語彙、月次活動密度、業種シグナル、レビュー条件。
2. 確認リスト: 顧客・専門家・社内担当者・窓口へ聞くべき不足情報や入力品質の確認項目。
3. 公的情報join候補: 法人番号、インボイス、補助金、調達、EDINET、gBizINFO、e-Stat等への接続候補。ただしCSVだけで同一主体や適格性を断定しない。

P0で採用する成果物は、全ユーザー共通の `CSV Coverage Receipt`, `CSV Review Queue Packet`, `Evidence-safe Advisor Brief`, `Account Vocabulary Map`, `Public Join Candidate Sheet` を土台にし、ユーザー種類ごとの文脈に合わせた短いブリーフへ展開する。後回しにするのは、税額・税区分からの申告判断、仕訳正誤判定、融資可否、採択可否、監査結論、与信結論、個別取引の再構成につながる成果物である。

## 1. 出力境界

| 境界 | P0で許可 | 禁止 / 後回し |
|---|---|---|
| 会計CSV | raw行を保存せず、列・期間・件数・集計・レビュー条件だけを出す | 摘要、取引先、伝票番号、作成者名、少数セルから個別取引が読める出力 |
| 税務・会計 | 「確認が必要な入力条件」「税額列の有無」「税区分列の存在」を出す | 消費税・法人税・所得税の判断、仕訳の正誤、申告上の有利不利 |
| 公的source join | 法人番号/T番号/会社名+所在地/制度名/業種語彙から候補を出す | 名称だけで同一法人断定、no_hitを不存在証明として扱うこと |
| AIエージェント | 次に渡す成果物、質問、確認順、cost previewを返す | 専門家判断、融資判断、採択保証、監査意見、リスクなし宣言 |
| 課金 | 成功したpacket、resolved subject、source receipt set等の明示単位 | validation reject、cap不足、unsupported final judgment、gap-only no usable packet |

## 2. 共通入力列と正規化hint

### 2.1 会計CSVの最小入力列

| normalized field | freee例 | MF例 | 弥生例 | 用途 |
|---|---|---|---|---|
| `entry_date` | `取引日` | `取引日` | `取引日付` | 期間、月次活動、未来日付確認 |
| `voucher_id` | `伝票番号` | `取引No` | `伝票No` / `伝票No.` | 内部ハッシュID材料。出力しない |
| `debit_account` | `借方勘定科目` | `借方勘定科目` | `借方勘定科目` | 科目語彙、軽分類、業種シグナル |
| `credit_account` | `貸方勘定科目` | `貸方勘定科目` | `貸方勘定科目` | 科目語彙、軽分類、業種シグナル |
| `debit_amount` | `借方金額` | `借方金額(円)` | `借方金額` | 集計。個別明細は出さない |
| `credit_amount` | `貸方金額` | `貸方金額(円)` | `貸方金額` | 集計。個別明細は出さない |
| `tax_amount` | `借方税額`等 | 税額列があれば採用 | `借方税金額`等 | 税額列の存在・集計のみ。税判断禁止 |
| `department_or_item_presence` | 部門、品目、タグ | 部門、タグ | 部門、付箋 | 詳細管理の存在フラグ |
| `vendor_meta_presence` | メモタグ等 | `決算整理仕訳`, 作成更新メタ | `決算`, `調整`, `付箋` | レビュー条件 |
| `memo_presence` | `摘要` | `摘要` / `仕訳メモ` | `摘要` / `仕訳メモ` | 存在フラグのみ。本文は出さない |

### 2.2 公的source join用の任意hint

会計CSV単体では法人同定に必要な列が不足しやすい。P0では、会計CSVから直接抽出する値と、アップロード時プロフィールや別CSVから追加される値を分けて扱う。

| hint | 入手元 | join先 | 出力上の扱い |
|---|---|---|---|
| `houjin_bangou` | ユーザープロフィール、顧客台帳CSV | 国税庁法人番号、EDINET JCN、gBizINFO | exact join可能。source receipt付きfact |
| `invoice_registration_number` | 請求書台帳、顧客台帳、ユーザー入力 | 国税庁インボイス | exact join可能。個人事業者T番号は法人番号化しない |
| `company_name` | ユーザー入力、顧客台帳、CSVファイル名由来の手入力 | 法人番号候補、gBizINFO候補 | candidate生成。単独では断定しない |
| `address_hint` | ユーザー入力、顧客台帳 | 法人番号候補、e-Stat地域 | tie-breaker。候補表示に留める |
| `industry_hint` | 科目語彙、ユーザー選択 | jGrants、e-Stat、業種別制度 | 適合断定ではなく候補理由 |
| `program_name` | 補助金関連科目、ユーザー入力 | jGrants、e-Gov、自治体制度 | 制度候補。公募要領確認が必要 |
| `counterparty_name_raw` | 取引先列 | 原則P0出力禁止 | raw名は出さず、hash/deduped countまたは「別途確認」へ |

## 3. 共通成果物

| artifact | P0判断 | 入力列 | 出力 | source join | known_gaps | 課金単位 |
|---|---|---|---|---|---|---|
| `csv_coverage_receipt` | P0採用 | file bytes、列名、日付列、金額列、科目列 | ベンダー推定、行数、列数、期間、列プロファイル、raw保存なし宣言 | なし。CSV receiptのみ | encoding unknown、必須列欠落、期間不明、ベンダーunknown | `packet` 1件 |
| `csv_review_queue_packet` | P0採用 | 日付、金額、科目、税額、vendor meta | 未来日付、貸借差額、パース不能、ID fallback、少数セル抑制理由 | なし。CSV品質確認 | 正誤判断不可、原因未特定、raw確認が必要 | `packet` 1件 |
| `account_vocabulary_map` | P0採用 | 借方/貸方科目、補助科目presence、部門presence | 科目別件数、軽分類、業種シグナル、review_required | 業種hintからjGrants/e-Stat候補へ派生可 | 科目名ゆれ、ベンダー差、分類confidence低 | `packet` 1件 |
| `period_activity_packet` | P1後回し | 日付、金額、科目 | 月別活動密度、空白月、月次合計、distinct account | e-Stat地域/産業cohortと組合せ可能 | 少数セル、季節性の意味判断不可 | `packet` 1件 |
| `evidence_safe_advisor_brief` | P0採用 | coverage、review_queue、vocabulary、任意profile | 専門家/顧客に渡せる短いブリーフ、確認質問 | 法人番号/T番号があればpublic baseline候補 | raw CSV未確認、専門判断未実施 | `packet` 1件 |
| `public_join_candidate_sheet` | P0採用 | 法人番号、T番号、会社名、所在地、業種hint、制度名 | join候補、confidence、必要追加情報、no_hit receipt | NTA法人番号、NTAインボイス、jGrants、EDINET、gBizINFO、e-Stat | name-only match、同名法人、source未接続、snapshot lag | `source_receipt_set` `ceil(unique_receipts/25)` |
| `csv_to_agent_route_card` | P0採用 | coverage + user type + goal | AIエージェント向け推奨artifact、cap見積、禁止回答 | join候補の有無だけ参照 | user goal不足、final judgment request | `free_control` 0円 |

## 4. ユーザー種類別カタログ

### 4.1 税理士

税理士向けの価値は、顧問先へ追加確認を依頼する前の「CSV構造・要確認点・公的登録確認候補」の整理である。税額や税区分を使って納税額・控除可否・申告方針を示さない。

| artifact | P0判断 | 入力列 | 出力 | source join | known_gaps | 課金単位 |
|---|---|---|---|---|---|---|
| `tax_client_csv_intake_brief` | P0採用 | `entry_date`, 科目, 金額, 税額列presence, vendor meta | 顧問先CSVの期間、列、レビュー条件、顧問先への確認文 | 顧問先の法人番号/T番号があればNTA/インボイス確認候補 | 税務判断未実施、raw摘要非表示、税区分解釈なし | `packet` 1件 |
| `month_end_question_list` | P0採用 | 月別行数、空白月、未来日付、決算整理/調整presence | 月次面談で聞く質問。例: 期間外日付、未入力月、補助科目不足 | 決算月profileがあればwatch候補 | 質問は必要性候補であり処理誤りではない | `packet` 1件 |
| `invoice_registration_check_candidates` | P0採用 | T番号、法人番号、会社名profile、取引先列presence | インボイス確認の対象候補と不足情報 | NTAインボイス、NTA法人番号 | 取引先raw名は出さない、個人T番号は法人番号化不可 | `subject` resolved件数 |
| `tax_return_risk_score` | 後回し/禁止 | 税額、税区分、科目、金額 | 出さない | なし | 専門判断・申告判断に該当 | なし |

P0採用理由:

- 税理士はCSVを受け取った直後の顧客コミュニケーションに価値を感じる。
- 出力を「確認依頼」と「公的登録候補」に留めると、税務助言の境界を守れる。

後回し理由:

- 税額・税区分からの消費税判定、科目別の税務取扱い、申告書作成支援は専門判断に直結するためP0から外す。

### 4.2 会計士

会計士向けの価値は、監査・レビュー・DD前の公開情報証跡と、CSV入力品質の確認範囲を分けることである。監査意見、虚偽表示判定、内部統制評価を出さない。

| artifact | P0判断 | 入力列 | 出力 | source join | known_gaps | 課金単位 |
|---|---|---|---|---|---|---|
| `audit_pbc_csv_evidence_index` | P0採用 | file profile、日付、科目、金額、vendor meta | PBC受領CSVの範囲表、列プロファイル、要レビュー条件 | 会社法人番号があればpublic baselineへ接続 | CSVの完全性未保証、証憑照合なし、監査手続未実施 | `packet` 1件 |
| `public_identity_reconciliation_sheet` | P0採用 | 法人番号/T番号/会社名/所在地profile | CSV対象会社と公的identityの突合候補 | NTA法人番号、NTAインボイス、EDINET JCN、gBizINFO | name-only候補、旧商号未追跡、関連会社未確認 | `subject` resolved件数 |
| `audit_review_queue_packet` | P0採用 | 未来日付、貸借差額、決算整理、調整、付箋、更新メタ | 監査チーム向けの確認キュー。入力品質・範囲の質問だけ | なし | 重要性判断なし、誤謬断定なし、raw明細非表示 | `packet` 1件 |
| `misstatement_or_fraud_indicator` | 後回し/禁止 | 金額、科目、時系列 | 出さない | なし | 監査判断に該当 | なし |

P0採用理由:

- 会計士は「何を受領し、どこまで公的に確認したか」をsource receipt付きで残す価値が高い。
- CSVレビューは入力品質・範囲確認に限定すれば、監査結論を代替しない。

後回し理由:

- 異常検知を「虚偽表示」「不正兆候」と命名すると専門判断に見える。P0では `review_required` と `human_question` に留める。

### 4.3 補助金コンサル

補助金コンサル向けの価値は、会計CSVから投資・人件費・業種・補助金関連科目の「候補理由」を作り、公募要領・公的制度への確認順へ変換することである。採択可能性や対象経費該当性を断定しない。

| artifact | P0判断 | 入力列 | 出力 | source join | known_gaps | 課金単位 |
|---|---|---|---|---|---|---|
| `subsidy_readiness_question_list` | P0採用 | 科目語彙、月次活動、固定資産/外注/人件費/補助金like科目 | 申請前ヒアリング質問、必要情報リスト、確認優先順 | jGrants制度候補、e-Gov根拠法令候補 | 対象経費判断なし、事業計画未確認、募集時点未確認 | `packet` 1件 |
| `eligible_expense_vocabulary_map` | P0採用 | 勘定科目、補助科目presence、部門presence | 設備・外注・人件費・広告・研究開発等の語彙候補 | jGrantsキーワード、行政事業レビュー/公募PDFはP1 | 勘定科目名と対象経費は一致しない、証憑未確認 | `packet` 1件 |
| `grant_public_join_candidate_sheet` | P0採用 | 法人番号、所在地、業種hint、制度名hint、期間 | 会社属性と制度候補のjoin候補、確認すべき公募要領 | NTA法人番号、jGrants、gBizINFO補助金/認定、e-Stat地域 | 自治体制度未接続、Jグランツ非掲載制度、締切stale | `source_receipt_set` |
| `adoption_probability_score` | 後回し/禁止 | 業績、費目、制度 | 出さない | なし | 採択保証・審査判断に該当 | なし |

P0採用理由:

- 補助金支援では、最初の価値は「聞くべきことを減らす」ことにある。
- CSV由来の科目語彙は候補理由として有用だが、公募要領の要件判定とは分離できる。

後回し理由:

- 採択確率、対象経費該当、補助率適用、加点判断は制度本文・証憑・事業計画が必要で、CSV派生事実だけでは危険。

### 4.4 信金

信金向けの価値は、借り手との面談・稟議前に、会計CSV由来の事業活動シグナルと公的情報join候補を整理することである。融資可否、信用力、返済能力を判定しない。

| artifact | P0判断 | 入力列 | 出力 | source join | known_gaps | 課金単位 |
|---|---|---|---|---|---|---|
| `borrower_csv_onboarding_brief` | P0採用 | 期間、行数、科目語彙、月次活動、review_queue | 借り手から受け取ったCSVの範囲、追加資料依頼、面談質問 | 法人番号profileからpublic baseline | 財務分析なし、返済能力判断なし、証憑未確認 | `packet` 1件 |
| `funding_use_signal_brief` | P0採用 | 固定資産、借入金、支払利息、外注、補助金like科目 | 資金使途・投資予定の確認質問候補 | jGrants、調達、gBizINFO、e-Stat地域 | 資金使途断定なし、融資適格性未確認 | `packet` 1件 |
| `portfolio_public_join_candidates` | P0採用 | 顧客台帳CSVの法人番号/T番号、会社名、所在地 | 顧客ごとの公的情報join候補、known gaps | NTA、インボイス、EDINET、p-portal/JETRO、gBizINFO | name-only rows、同名法人、未接続source、no_hit_not_absence | `billable_subject` resolved件数 |
| `credit_decision_or_risk_grade` | 後回し/禁止 | 金額、科目、時系列 | 出さない | なし | 与信判断・融資判断に該当 | なし |

P0採用理由:

- 信金では稟議前の材料整理、追加資料依頼、制度候補の提示が現実的なfirst-hopになる。
- `borrower_csv_onboarding_brief` は借り手にも支店担当者にも転記しやすい。

後回し理由:

- CSVから信用格付や融資可否を出すと、会計CSVの範囲を超え、金融判断に見える。

### 4.5 商工会

商工会向けの価値は、会員から受け取った会計CSVを、専門家相談・補助金案内・記帳支援のどこへ回すべきかを整理すること。個別税務・申請可否・経営診断の結論は出さない。

| artifact | P0判断 | 入力列 | 出力 | source join | known_gaps | 課金単位 |
|---|---|---|---|---|---|---|
| `member_support_triage_sheet` | P0採用 | coverage、review_queue、業種シグナル、owner_related科目presence | 会員相談の振り分け、必要資料、担当者への確認質問 | 会員法人番号があればNTA/gBizINFO | 会員属性不足、個人事業者の公開情報不足、相談目的未確定 | `packet` 1件 |
| `program_outreach_candidate_list` | P0採用 | 業種hint、所在地、設備/人件費/販促科目presence | 案内候補制度と確認すべき条件リスト | jGrants、自治体制度はP1、e-Stat地域 | Jグランツ非掲載、自治体制度未収録、適合未判定 | `source_receipt_set` |
| `bookkeeping_hygiene_report` | P0採用 | 列欠落、空白月、未来日付、ID fallback、諸口比率 | 記帳支援前のデータ品質レポート | なし | 正誤判断なし、詳細明細の確認は別途必要 | `packet` 1件 |
| `management_diagnosis_score` | 後回し/禁止 | 科目、金額、期間 | 出さない | なし | 経営診断・収益性判断に該当 | なし |

P0採用理由:

- 商工会の実務は、多様な会員相談を適切な窓口・専門家・制度へつなぐことが中心。
- CSV由来成果物は「案内前の確認リスト」にすると、過剰な判断を避けられる。

後回し理由:

- 収益性、資金繰り、経営改善の結論は、会計CSV以外のヒアリングと専門判断が必要。

### 4.6 中小企業

中小企業向けの価値は、自社の会計CSVから「専門家へ渡す前の整理」と「AIエージェントが次に何を聞くべきか」を返すことである。経営者向けには専門用語を減らし、確認タスクに変換する。

| artifact | P0判断 | 入力列 | 出力 | source join | known_gaps | 課金単位 |
|---|---|---|---|---|---|---|
| `owner_action_checklist` | P0採用 | coverage、review_queue、account_vocabulary | 経営者向けの次アクション、専門家に聞く質問、追加で用意する資料 | 法人番号/T番号があれば登録確認候補 | 税務・融資・補助金の結論なし、CSV期間外は未確認 | `packet` 1件 |
| `advisor_handoff_brief` | P0採用 | 期間、行数、科目グループ、review_required | 税理士/会計士/支援機関へ渡す短いブリーフ | public baseline候補、invoice候補 | raw CSVを共有しないため詳細判断不可 | `packet` 1件 |
| `public_opportunity_candidate_sheet` | P0採用 | 業種hint、所在地、法人番号、設備/外注/人件費科目 | 補助金・公的支援・調達等の確認候補 | jGrants、gBizINFO、p-portal/JETRO、e-Stat | 適合未判定、締切stale、自治体制度未収録 | `source_receipt_set` |
| `tax_saving_or_loan_recommendation` | 後回し/禁止 | 税額、金額、科目 | 出さない | なし | 税務・融資判断に該当 | なし |

P0採用理由:

- 中小企業にとっては、専門家に丸投げする前の整理が最もわかりやすい価値。
- 出力を「質問」「資料」「候補」に限定すればAIエージェントが安全に案内できる。

後回し理由:

- 節税提案、融資提案、補助金申請可否は、事業計画・証憑・専門家確認が必要。

### 4.7 業務SaaS

業務SaaS向けの価値は、プロダクト内でAIエージェントやワークフローが使える小さなartifact APIとして返すこと。SaaSが最終判断をUIに出すのではなく、ユーザー確認タスク・source receipt・cost previewを組み込める形にする。

| artifact | P0判断 | 入力列 | 出力 | source join | known_gaps | 課金単位 |
|---|---|---|---|---|---|---|
| `csv_health_api_packet` | P0採用 | file profile、列名、日付、金額、科目 | SaaS内表示用のCSV健全性、review_required、修正依頼文 | なし | ベンダーunknown、列mapping失敗、raw保存なし | `packet` 1件 |
| `agent_ready_csv_artifact_bundle` | P0採用 | coverage、review_queue、vocabulary、public join candidates | AIエージェントに渡すsections/claims/source_receipts/known_gaps | NTA、インボイス、jGrants等の候補receipt | unsupported final judgment、source blocked、name-only | `packet` 1件 + `source_receipt_set` |
| `integration_gap_telemetry` | P0採用 | vendor_family、列profile hash、mapping failure、review codes | SaaS側の取り込み改善に使う匿名化集計 | なし | tenant横断利用は同意/匿名化が必要 | `record` または free internal telemetry |
| `embedded_tax_or_credit_advice` | 後回し/禁止 | 科目、税額、金額 | 出さない | なし | SaaS内で専門判断に見える | なし |

P0採用理由:

- SaaSはCSV ingestionの摩擦を下げるだけでも明確な価値がある。
- Agent bundleをpacket envelopeに合わせると、外部LLMやSaaS UIがsource/gap/costをそのまま扱える。

後回し理由:

- SaaSのUIに税務・融資・監査・採択判断を埋め込むと、境界と責任分界が曖昧になる。

## 5. P0採用マトリクス

| user type | P0採用artifact | 採用理由 | 主要入力 | 課金単位 |
|---|---|---|---|---|
| 税理士 | `tax_client_csv_intake_brief`, `month_end_question_list`, `invoice_registration_check_candidates` | 顧客確認依頼へ直結し、税務判断を避けられる | CSV profile、日付、科目、税額presence、T番号/法人番号 | `packet`, `subject` |
| 会計士 | `audit_pbc_csv_evidence_index`, `public_identity_reconciliation_sheet`, `audit_review_queue_packet` | 受領範囲と公的identityの証跡を残せる | CSV profile、vendor meta、法人番号/T番号 | `packet`, `subject` |
| 補助金コンサル | `subsidy_readiness_question_list`, `eligible_expense_vocabulary_map`, `grant_public_join_candidate_sheet` | 申請前ヒアリングと制度候補の確認順に使える | 科目語彙、業種hint、所在地、制度名 | `packet`, `source_receipt_set` |
| 信金 | `borrower_csv_onboarding_brief`, `funding_use_signal_brief`, `portfolio_public_join_candidates` | 面談質問、追加資料依頼、公的情報確認に使える | CSV profile、資金使途語彙、顧客台帳 | `packet`, `billable_subject` |
| 商工会 | `member_support_triage_sheet`, `program_outreach_candidate_list`, `bookkeeping_hygiene_report` | 会員相談の振り分けと案内前確認に使える | coverage、業種hint、所在地、review codes | `packet`, `source_receipt_set` |
| 中小企業 | `owner_action_checklist`, `advisor_handoff_brief`, `public_opportunity_candidate_sheet` | 経営者が専門家に渡す前の整理になる | CSV profile、科目語彙、法人番号/T番号 | `packet`, `source_receipt_set` |
| 業務SaaS | `csv_health_api_packet`, `agent_ready_csv_artifact_bundle`, `integration_gap_telemetry` | プロダクト内の取り込み改善とAI agent routeに使える | file profile、mapping result、review codes | `packet`, `record/free_control` |

## 6. 後回し / 禁止マトリクス

| output | 判断 | 理由 | 代替P0 |
|---|---|---|---|
| 税額・税区分からの納税額/控除可否判断 | 禁止 | 税務判断に該当 | 税額列presenceと確認質問 |
| 仕訳正誤判定 | 禁止 | 会計処理判断に該当 | `csv_review_queue_packet` のreview_required |
| 採択確率/対象経費該当判定 | 禁止 | 補助金審査・制度適合判断に該当 | `subsidy_readiness_question_list` |
| 融資可否/信用格付 | 禁止 | 金融判断に該当 | `borrower_csv_onboarding_brief` |
| 監査意見/不正兆候断定 | 禁止 | 監査判断に該当 | `audit_review_queue_packet` |
| 個別取引一覧の再出力 | 禁止 | raw CSV・機微情報再配布に該当 | 集計、少数セル抑制、presence flag |
| 取引先名の公的source一括照合 | P1/P2 | raw取引先名の扱いと誤結合リスクが高い | 取引先列presence、別途同意付きcounterparty CSV |
| 経営診断スコア | 後回し | 会計CSVだけでは根拠不足 | `owner_action_checklist` |

## 7. Artifact共通スキーマ要件

P0成果物は、既存のpacket envelope方針に合わせて次のフィールドを持つ。

| field | 必須性 | 内容 |
|---|---:|---|
| `packet.type` | required | 上記artifact ID |
| `input_echo.user_type` | required | `tax_accountant`, `cpa`, `subsidy_consultant`, `shinkin`, `chamber`, `sme`, `business_saas` |
| `csv_intake_profile` | required | vendor family、列profile、期間、行数、raw retention none |
| `sections` | required | ユーザー種類別のブリーフ、質問、候補 |
| `claims` | required | CSV派生事実とpublic source factを分ける |
| `source_receipts` | required | `private_csv_derived` と `positive_source/no_hit_check` を分ける |
| `known_gaps` | required | 未確認範囲、source未接続、name-only、少数セル抑制 |
| `fence` | required | tax/accounting/audit/credit/grant final judgmentではない旨 |
| `billing_metadata` | required | unit price、unit type、billable units、external cost excluded |

### 7.1 known_gapsの標準タグ

| tag | 使う場面 |
|---|---|
| `raw_csv_not_retained` | raw行、摘要、取引先、伝票番号を保存/出力しない |
| `tax_accounting_opinion_not_provided` | 税務・会計判断に見える要求を境界内へ戻す |
| `source_not_connected` | 自治体制度、処分source、PDF抽出等が未接続 |
| `identifier_missing` | 法人番号/T番号がなく名称候補だけ |
| `name_only_match` | 会社名だけの公的source候補 |
| `same_name_entity_risk` | 同名法人が複数ありうる |
| `snapshot_lag` | 公的sourceの基準日が古い |
| `small_cell_suppressed` | 個別取引再識別を避けるため金額等を丸める |
| `no_hit_not_absence` | no_hitが不存在証明ではない |
| `human_review_required` | 専門家/顧客/社内担当者の確認が必要 |

## 8. 課金設計

P0ではユーザーに「ファイル単位」と「成果物単位」が混同されないよう、previewで次を表示する。

```text
uploaded_files -> accepted_files -> requested_artifacts -> source_join_subjects -> predicted_units -> cap check -> execution -> billed_units
```

| unit type | 適用 | formula |
|---|---|---|
| `packet` | coverage、review queue、brief、question list、vocabulary map | 成功した成果物1件 = 1 unit |
| `subject` | 法人番号/T番号等でresolvedした会社・登録番号 | resolved subject数。重複はdedupe |
| `billable_subject` | 信金/商工会/SaaS等の顧客台帳・会員台帳 | accepted_resolved subject数 |
| `source_receipt_set` | public join candidate sheet、ledger | `ceil(unique_source_receipts / 25)`, min 1 |
| `record` | SaaS telemetry等の匿名化集計 | 実装時に明示。P0では課金外も可 |
| `free_control` | route card、cost preview | 0円。匿名quotaとは分離可 |

課金しないケース:

- 必須列欠落で成果物を生成できないvalidation reject。
- identityが曖昧で、ユーザーがambiguity packetを明示要求していない場合。
- final judgment要求を境界違反として拒否した場合。
- no_hitだけでusable packetがない場合。
- cost cap不足、API key不足、認可失敗。

## 9. AIエージェント向け推薦ルール

| 条件 | 推薦artifact | 避ける回答 |
|---|---|---|
| 初回CSVアップロード | `csv_coverage_receipt` -> `csv_review_queue_packet` | いきなり税務/融資/採択判断 |
| `review_required=true` | ユーザー種類別の確認リスト | 正誤断定 |
| 法人番号/T番号あり | `public_join_candidate_sheet` | no_hitを不存在証明にする |
| 科目語彙に業種シグナルあり | 補助金/支援制度の候補確認 | 適合・採択・対象経費の断定 |
| raw取引先照合を求められた | 別途同意付きcounterparty CSVとsource boundaryを要求 | 取引先名を成果物へ再出力 |
| ユーザー種類がSaaS | `agent_ready_csv_artifact_bundle` | SaaS UI内の専門判断文 |

## 10. P0実装順

1. 共通 `csv_coverage_receipt` と `csv_review_queue_packet` を先に固定する。
2. `account_vocabulary_map` と `evidence_safe_advisor_brief` を追加する。
3. 任意profileから `public_join_candidate_sheet` を作る。ただし名称のみはcandidate表示に限定する。
4. 税理士・中小企業・業務SaaS向けの3 personaを先に公開候補にする。
5. 会計士・補助金コンサル・信金・商工会は、P0の共通artifactをpersona copyに展開する。
6. P1で `period_activity_packet`、自治体制度join、counterparty同意付き照合、watch差分へ広げる。

## 11. 受け入れ条件

| gate | 合格条件 |
|---|---|
| Boundary gate | 税務・会計・監査・融資・採択・経営診断の結論を含まない |
| Privacy gate | raw行、摘要、取引先、伝票番号、作成者名を出さない |
| Source gate | public factはsource receipt、CSV派生factはprivate CSV receiptに分ける |
| Gap gate | no_hit、未接続、同名法人、stale、少数セル抑制をknown_gapsへ出す |
| Persona gate | 同じCSVでも税理士/会計士/補助金コンサル/信金/商工会/中小企業/SaaSで異なる成果物名と確認質問になる |
| Billing gate | cost previewでunit type、predicted units、cap required、external costs excludedを表示する |
| Agent gate | AIエージェントが次に使うartifactと禁止回答を判断できる |

