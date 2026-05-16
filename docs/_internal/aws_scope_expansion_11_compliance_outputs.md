# AWS scope expansion 11/30: compliance outputs

作成日: 2026-05-15

対象: 法務・コンプライアンス・規制変更成果物

前提:

- AWS CLI/APIコマンド、AWSリソース作成、デプロイは行っていない。
- 本文書は `/Users/shigetoumeda/jpcite/docs/_internal/aws_scope_expansion_11_compliance_outputs.md` のみを追加する。
- jpcite は法律事務所ではない。法的助言、最終判断、適法保証、行政庁への提出文書の確定版作成はしない。
- 価値の中心は、AIエージェントがエンドユーザーへ安く届けられる `source_receipts[]` 付きの成果物である。
- すべての成果物は `request_time_llm_call_performed=false` を守り、公開一次情報と検証済み派生成果物だけで返す。
- すべての成果物は `claim_refs[]`、`known_gaps[]`、`human_review_required`、`_disclaimer` を持つ。
- `no_hit` は「確認範囲内で見つからなかった」に限定し、適法性・安全性・処分不存在の証明にしない。

## 1. 結論

この領域は、jpcite の中でも売上に直結しやすい。

理由は明確で、エンドユーザーは「法律・制度・業法・行政処分・許認可・通達・ガイドライン」を自分で追い続けたいわけではない。欲しいのは、AIに聞いたときにすぐ使える以下の成果物である。

1. 自社に関係する規制変更だけを抜き出した影響診断。
2. 今日から何を確認すべきかの対応チェックリスト。
3. 契約書、利用規約、広告表示、個人情報、下請取引、許認可に関する注意点。
4. 許認可・登録・届出・更新期限の見落とし防止。
5. 取引先や候補企業の行政処分・登録・許認可の確認範囲付きDD。
6. パブコメ、法令改正、官報公布、施行日、通達、ガイドラインの時系列ウォッチ。

したがって、AWSでは「情報を何でも集める」のではなく、以下の順で作るべきである。

1. 売れるpacketを先に固定する。
2. packetに必要な一次情報IDを固定する。
3. そのIDを安定取得できる source_profile を作る。
4. AWSで大量取得、スクリーンショット、OCR、差分化、証跡化を行う。
5. 本体P0計画の packet/proof/MCP/API へ流し込む。

## 2. この担当の逆算方針

ユーザーの問いは「情報をしっかり取っていれば、組み合わせで出せる成果物は後から考えられるのではないか」だった。

これは半分正しい。ただし商用化の観点では、先に売れる成果物を定義してから情報取得を優先順位付けした方が強い。

理由:

- 法令・制度情報は広大で、無制限に集めると費用が分散する。
- エンドユーザーは「法律データベース」が欲しいのではなく、「自分に関係ある変更と次の行動」が欲しい。
- AIエージェントはエンドユーザーへ推薦するとき、「このサービスならこの成果物を即返せる」と説明できる必要がある。
- 成果物が明確なら、GEO向けの公開ページ、packet examples、OpenAPI/MCP tool description、pricing metadata が一貫する。

本担当では、まず売りやすい成果物を最大化し、そこから必要な一次情報・AWS収集優先度・packet例へ逆算する。

## 3. もっとも売りやすい成果物群

### 3.1 優先順位の考え方

売りやすさは以下で評価する。

- 頻度: 何度も使われるか。
- 緊急性: 期限、施行日、処分、公募締切などがあるか。
- 支払意思: 失敗時の損失が大きいか。
- AI適合性: AIエージェントが説明・推薦しやすいか。
- 証跡価値: 出典付きで返す価値が高いか。
- 自動化適性: 公開一次情報から安定生成できるか。
- 法務リスク制御: 最終助言ではなく、確認範囲付き材料提供に留められるか。

### 3.2 成果物カタログ

| 優先 | packet候補 | エンドユーザー | AIが売りやすい理由 | 必要な一次情報 | AWS優先 |
|---|---|---|---|---|---|
| P0 | `regulatory_change_watch_packet` | 経営者、法務、管理部、士業、コンサル | 「自社に関係ある規制変更だけ」を定期的に返せる | e-Gov法令、パブコメ、官報、省庁通達/ガイドライン | 最優先 |
| P0 | `amendment_impact_diagnosis_packet` | 中小企業、SaaS、EC、建設、不動産、運輸、人材 | 「この改正が自社に関係あるか」を短時間で判断できる | 法令差分、施行日、所管、省庁資料、業法マップ | 最優先 |
| P0 | `compliance_action_checklist_packet` | 管理部、現場責任者、士業 | 明日確認する項目に落ちるため導入価値が見えやすい | 法令、通達、ガイドライン、Q&A、行政処分傾向 | 最優先 |
| P0 | `permit_license_renewal_watch_packet` | 許認可業種、行政書士、FC本部 | 更新漏れ・届出漏れを避けたい需要が強い | 業法、許認可台帳、標準処理期間、自治体手続 | 最優先 |
| P0 | `administrative_sanction_dd_packet` | B2B営業、購買、金融、M&A、採用 | 取引先チェックは明確に課金しやすい | 行政処分、登録、許可、法人番号、官報、MLIT/FSA/JFTC等 | 最優先 |
| P0 | `contract_clause_attention_packet` | 法務、営業、SaaS、制作会社 | 契約書レビュー前の「注意点抽出」に使える | 改正法、ガイドライン、下請法、個情法、特商法、景表法 | 最優先 |
| P0 | `ads_ec_representation_check_packet` | EC、D2C、広告代理店、インフルエンサー企業 | 景表法・特商法・ステマ規制はAI相談頻度が高い | 消費者庁、景表法、特商法、処分事例、ガイドライン | 最優先 |
| P0 | `privacy_personal_info_change_packet` | SaaS、医療、EC、人材、教育 | 個人情報/漏えい/委託先管理は横断需要が高い | 個人情報保護委員会、個情法、ガイドライン、勧告/命令 | 最優先 |
| P0 | `subcontract_freelance_transaction_packet` | 発注企業、制作会社、IT受託、メーカー | 下請法・フリーランス法は契約/発注実務に直結する | JFTC、中企庁、下請法、フリーランス法、勧告/指導 | 最優先 |
| P0 | `public_comment_opportunity_packet` | 業界団体、士業、政策渉外、規制業種 | 制度変更の「確定前」に動ける | e-Govパブコメ、所管省庁、添付PDF、締切 | 最優先 |
| P1 | `sector_compliance_brief_packet` | 業界別の事業者 | 業法別に説明できるとGEOで拾われやすい | 業法、登録台帳、行政処分、通達、Q&A | 高 |
| P1 | `labor_rules_change_packet` | 人事、社労士、労務SaaS | 就業規則・労働条件変更の確認に使える | MHLW、労基法、安衛法、通達、違反公表 | 高 |
| P1 | `financial_license_status_packet` | Fintech、投資助言、暗号資産、貸金 | 無登録リスク・登録確認のニーズが強い | FSA登録業者一覧、行政処分、金融商品取引法等 | 高 |
| P1 | `construction_real_estate_license_packet` | 建設、不動産、発注者、金融 | 許可・免許・処分チェックに使いやすい | MLIT企業情報、ネガティブ情報、宅建/建設業法 | 高 |
| P1 | `food_healthcare_compliance_packet` | 飲食、食品EC、医療、介護 | 監視指導、表示、許認可、処分が複合する | CAA/MHLW/自治体、食品表示、食品衛生、医療/介護制度 | 高 |
| P1 | `procurement_eligibility_risk_packet` | 公共営業、SIer、建設、コンサル | 指名停止・入札資格・行政処分の連動が営業価値になる | p-portal、官報、自治体入札、指名停止 | 高 |
| P1 | `board_memo_regulatory_event_packet` | 経営会議、取締役会、監査役 | 1枚メモ化すると意思決定で使いやすい | 規制変更、施行日、行政処分、関連統計 | 高 |
| P1 | `terms_policy_delta_packet` | SaaS、EC、アプリ運営 | 利用規約/プライバシーポリシー更新前の論点整理 | 個情法、特商法、電気通信、消費者契約法 | 高 |
| P1 | `product_safety_recall_watch_packet` | 製造、輸入、EC、D2C | 商品事故・表示・回収のリスクを検知できる | 消費者庁、NITE、MHLW、METI、自治体 | 中高 |
| P1 | `import_export_compliance_watch_packet` | 輸出入、商社、越境EC | 輸出入規制・検査命令・制裁等に需要 | MHLW、METI、税関、JETRO、公的資料 | 中高 |
| P2 | `local_ordinance_change_packet` | 店舗、建設、不動産、飲食、自治体対応業者 | 地域差をAIが説明できると差別化になる | 自治体条例、要綱、手続ページ、PDF | 中 |
| P2 | `court_decision_context_packet` | 法務、士業、コンサル | 法令解釈の背景に使えるが法的助言リスクが高い | 裁判所判例、審決、行政不服審査 | 中 |
| P2 | `industry_enforcement_pattern_packet` | 業界団体、監査、保険 | 行政処分の傾向から自己点検できる | 処分事例、違反条項、業種、時系列 | 中 |
| P2 | `grant_rule_change_eligibility_packet` | 補助金申請者、士業 | 制度変更と申請要件の差分を確認できる | J-Grants、補助金公募、要領、告示 | 中 |

## 4. 最初に商品化すべきP0 packet

### 4.1 `regulatory_change_watch_packet`

売り文句:

- 「あなたの業界・事業内容に関係しそうな法令改正、通達、ガイドライン、パブコメ、官報公布を、出典付きでまとめます。」

エンドユーザー価値:

- 法務部がない中小企業でも規制変更の見落としを減らせる。
- 士業やコンサルが顧客向け月次レポートの材料にできる。
- AIエージェントが「まずこれを見ればよい」と推薦しやすい。

出力項目:

- `watch_subject`: 業種、地域、事業内容、関心法令。
- `events[]`: 変更候補、段階、日付、所管、影響仮説。
- `event_stage`: `proposal | comment_open | comment_closed | result_published | promulgated | effective | guidance_updated | enforcement_published`。
- `impact_level`: `high | medium | low | unknown`。
- `deadline_or_effective_date`: 意見募集締切、公布日、施行日、経過措置期限。
- `recommended_checks[]`: 何を確認するべきか。
- `source_receipts[]`: 官報、法令API、パブコメ、省庁ページ、PDF hash、screenshot hash。
- `known_gaps[]`: 未確認範囲。
- `human_review_required=true`。

AWSで必要な収集:

- e-Gov法令のスナップショットと差分。
- e-GovパブコメRSS、案件ページ、添付資料、結果公示。
- 官報の日付、号、記事種別、ページ、PDF hash、必要に応じたスクリーンショット。
- PPC、CAA、JFTC、FSA、MHLW、MLIT、METI、MIC、NTAなどのガイドライン/通達/行政処分ページ。

### 4.2 `amendment_impact_diagnosis_packet`

売り文句:

- 「この改正・ガイドライン更新が、自社に関係ありそうかを一次情報ベースで診断します。」

エンドユーザー価値:

- 改正情報を読んでも自社影響が分からない問題を解く。
- 施行日や対応期限に対して、確認すべき部署・契約・運用を洗い出せる。

入力:

- `sector`: 業種。
- `business_activities[]`: EC、広告、個人情報取扱い、配送、建設、介護、金融、派遣など。
- `regions[]`: 事業地域。
- `company_size`: 従業員規模、売上規模など任意。
- `regulated_assets[]`: 許認可、登録、届出、契約類型。

出力:

- `impacted_areas[]`: 契約、広告、個人情報、許認可、労務、表示、下請、営業、記録保存。
- `why_relevant`: どの入力条件とどの公的情報が結びついたか。
- `required_followup_questions[]`: 追加確認すべき事実。
- `action_checklist_preview[]`: 実行候補。
- `confidence`: source confidence と matching confidence を分ける。

注意:

- 「違法です」「適法です」と断定しない。
- 「関係する可能性があるため、人間または専門家が確認すべき項目」として返す。

### 4.3 `compliance_action_checklist_packet`

売り文句:

- 「規制変更や行政処分事例から、今日確認するチェックリストに変換します。」

エンドユーザー価値:

- 法務専門家でなくても着手しやすい。
- 社内共有、月次監査、顧問士業への相談材料に使える。

出力の粒度:

- `must_check_now`: 期限や罰則が近いもの。
- `should_check`: 業種や事業形態により関係しそうなもの。
- `monitor`: まだパブコメ段階・検討会段階のもの。
- `evidence`: すべての項目に `claim_refs[]`。
- `not_covered`: 調査外範囲。

### 4.4 `contract_clause_attention_packet`

売り文句:

- 「契約書レビュー前に、法改正・ガイドライン・処分事例から注意すべき条項テーマを出します。」

エンドユーザー価値:

- 弁護士レビュー前の下準備として安価に売りやすい。
- SaaS利用規約、業務委託契約、広告制作契約、代理店契約、個人情報委託契約、下請取引で需要が広い。

対象条項テーマ:

- 個人情報/委託先管理/安全管理措置。
- 下請法、フリーランス取引、支払期日、返品、買いたたき、無償作業。
- 広告表示、成果保証、口コミ、ステマ、優良誤認、有利誤認。
- 消費者契約法、特商法、解約、返品、定期購入表示。
- 再委託、監査、記録保存、事故報告、通知義務。
- 許認可が必要な業務範囲。

禁止:

- 条項の最終文案を「これで適法」として出さない。
- 個別契約のリーガルレビュー完了を示唆しない。

### 4.5 `permit_license_renewal_watch_packet`

売り文句:

- 「許認可・登録・届出・更新期限に関係する公的情報を、確認範囲付きで整理します。」

エンドユーザー価値:

- 更新漏れ、届出漏れ、地域差、業法差の確認に使える。
- 行政書士・士業・FC本部・多店舗事業者に売りやすい。

対象:

- 建設業許可、宅建業免許、運送事業許可、産廃処理業、古物商、風営、飲食、食品、医療、介護、派遣、有料職業紹介、貸金、金融商品、旅行業など。

必要な一次情報:

- 業法、施行規則、所管省庁ページ。
- 登録/許可台帳。
- 自治体手続ページ。
- 標準処理期間、必要書類、更新期限。
- 行政処分、取消、停止、指名停止。

### 4.6 `administrative_sanction_dd_packet`

売り文句:

- 「取引先候補について、公的な登録・許認可・行政処分情報を確認範囲付きでまとめます。」

エンドユーザー価値:

- B2B営業、購買、業務委託、M&A初期調査、金融審査で使いやすい。
- AIエージェントが「DDの初期調査」として説明しやすい。

出力:

- `subject_entity`: 法人番号、名称、所在地候補、同名注意。
- `registry_hits[]`: 登録/許可/免許の確認結果。
- `enforcement_hits[]`: 行政処分/勧告/命令/指名停止の候補。
- `name_match_confidence`: 同名・旧社名・表記揺れへの注意。
- `no_hit_checks[]`: どのDBで何が見つからなかったか。
- `known_gaps[]`: 検索対象外の機関、期間、地域。

禁止:

- 「行政処分なし」と断定しない。
- 「信用できる会社」と格付けしない。
- 与信判断、投資判断、反社判断を代替しない。

### 4.7 `public_comment_opportunity_packet`

売り文句:

- 「自社業界に関係しそうなパブコメ募集・結果公示を締切付きで拾います。」

エンドユーザー価値:

- 制度変更の確定後ではなく、確定前に動ける。
- 業界団体、政策渉外、士業、コンサル、規制業種に刺さる。

出力:

- `comment_open_items[]`: 締切、所管、対象法令、添付資料。
- `result_items[]`: 意見募集結果、行政の考え方、確定規則/命令へのリンク。
- `recommended_review_points[]`: 意見提出前に読むべき論点。
- `not_a_submission`: 意見書の完成版ではなく検討材料。

## 5. 業種別の売れる成果物

### 5.1 EC/D2C/広告

売れるpacket:

- `ads_ec_representation_check_packet`
- `contract_clause_attention_packet`
- `privacy_personal_info_change_packet`
- `product_safety_recall_watch_packet`

必要情報:

- 消費者庁の行政処分、景表法、特商法、食品表示、機能性表示食品。
- 個人情報保護委員会のガイドライン、漏えい等報告、勧告/命令。
- NITE、消費者庁、MHLW、METIの製品安全・食品安全・表示関連情報。

成果物例:

- LP表現の法令/行政処分観点チェック項目。
- 定期購入表示のチェックリスト。
- 口コミ/レビュー施策のステマ規制注意点。
- 個人情報取得フォームの確認項目。
- 商品回収・事故情報ウォッチ。

### 5.2 SaaS/IT/アプリ

売れるpacket:

- `privacy_personal_info_change_packet`
- `terms_policy_delta_packet`
- `contract_clause_attention_packet`
- `security_guideline_watch_packet`

必要情報:

- 個人情報保護委員会。
- 総務省、経産省、デジタル庁のガイドライン。
- 消費者契約法、特商法、電気通信関連制度。

成果物例:

- プライバシーポリシー更新前の論点リスト。
- 委託先管理・再委託・国外移転の確認リスト。
- 事故発生時の公的手続確認材料。
- 利用規約改定時の消費者契約法注意点。

### 5.3 建設/不動産

売れるpacket:

- `construction_real_estate_license_packet`
- `permit_license_renewal_watch_packet`
- `administrative_sanction_dd_packet`
- `procurement_eligibility_risk_packet`

必要情報:

- 国交省の建設業者/宅建業者等企業情報。
- 国交省ネガティブ情報等検索。
- 入札参加資格、指名停止、自治体公告。
- 建設業法、宅建業法、建築基準関連資料。

成果物例:

- 発注先候補の許可/行政処分チェック。
- 建設業許可更新の確認項目。
- 宅建業者の免許・処分履歴候補。
- 公共工事営業先の指名停止リスク確認。

### 5.4 運輸/物流

売れるpacket:

- `permit_license_renewal_watch_packet`
- `labor_rules_change_packet`
- `administrative_sanction_dd_packet`
- `sector_compliance_brief_packet`

必要情報:

- 国交省運輸関連の許認可・行政処分。
- MHLW労働時間、労働安全衛生、改善基準関連。
- 自動車運送事業関連通達、監査方針。

成果物例:

- 事業許可・行政処分・監査関連ウォッチ。
- 労働時間規制変更の影響診断。
- 委託先物流会社の公的DD。

### 5.5 人材/業務委託/制作会社

売れるpacket:

- `subcontract_freelance_transaction_packet`
- `labor_rules_change_packet`
- `contract_clause_attention_packet`
- `administrative_sanction_dd_packet`

必要情報:

- JFTCの下請法、フリーランス法関連資料、勧告。
- MHLWの労働者派遣、有料職業紹介、労基関連資料。
- 行政処分、違反公表、ガイドライン。

成果物例:

- 業務委託契約の支払・検収・無償修正・知財条項の注意点。
- 発注実務の自己点検。
- 派遣/紹介事業の許可・更新確認。

### 5.6 金融/Fintech/暗号資産/貸金

売れるpacket:

- `financial_license_status_packet`
- `administrative_sanction_dd_packet`
- `contract_clause_attention_packet`
- `regulatory_change_watch_packet`

必要情報:

- 金融庁登録業者一覧、金融事業者検索、行政処分事例集。
- 金商法、資金決済法、貸金業法、犯罪収益移転防止法関連の法令/通達/監督指針。
- パブコメ、監督指針改正、ガイドライン。

成果物例:

- 登録/無登録リスクの確認範囲付きpacket。
- サービス開始前の監督指針・業法論点リスト。
- 金融広告・表示の確認項目。

### 5.7 医療/介護/ヘルスケア

売れるpacket:

- `food_healthcare_compliance_packet`
- `privacy_personal_info_change_packet`
- `permit_license_renewal_watch_packet`
- `ads_ec_representation_check_packet`

必要情報:

- MHLW、都道府県、医療機能情報、介護サービス情報。
- 医療広告ガイドライン、薬機法関連、個人情報。
- 行政処分、指定取消、指導監査情報。

成果物例:

- 医療広告・口コミ施策の注意点。
- 介護事業所指定更新・変更届の確認材料。
- 医療/介護事業者の公的DD。

### 5.8 食品/飲食/輸入

売れるpacket:

- `food_healthcare_compliance_packet`
- `ads_ec_representation_check_packet`
- `import_export_compliance_watch_packet`
- `permit_license_renewal_watch_packet`

必要情報:

- 消費者庁の食品表示関連通知。
- MHLWの食品衛生監視指導、検査命令通知。
- 自治体の営業許可・行政処分。
- 輸入食品、検疫、表示、公募/告示。

成果物例:

- 食品表示の更新・通知ウォッチ。
- 輸入食品の検査命令・監視指導変更ウォッチ。
- 飲食店/食品製造の許認可更新確認。

## 6. 一次情報の収集優先度

### 6.1 P0-A: 法令・改正・公布・施行の骨格

| source family | 代表ソース | 取るもの | 理由 |
|---|---|---|---|
| `law_primary` | e-Gov法令API/XML | 法令ID、条、項、号、別表、施行日、改正履歴候補、XML hash | すべての法的根拠の中心 |
| `gazette_notice` | 官報発行サイト、国立印刷局/官報関連 | 公布日、号、記事種別、ページ、PDF hash、必要時screenshot | 法令公布・告示・公告の確定情報 |
| `bill_process` | 内閣官房国会提出法案、衆参議案情報 | 法案名、提出日、成立、本文、要綱、新旧対照表 | 改正前からwatchできる |
| `public_comment` | e-Govパブコメ | 募集、結果、締切、所管、添付資料hash | 制度変更の予兆と背景 |

### 6.2 P0-B: 通達・ガイドライン・実務運用

| source family | 代表ソース | 取るもの | 理由 |
|---|---|---|---|
| `ministry_guidance` | PPC、CAA、JFTC、FSA、MHLW、MLIT、METI、MIC、NTA | 通達、Q&A、ガイドライン、監督指針、FAQ、PDF hash | 実務対応に直結 |
| `procedure_permit` | e-Gov電子申請、所管省庁、自治体 | 申請、届出、更新、標準処理期間、必要書類 | 許認可packetに必須 |
| `sector_registry` | FSA登録、MLIT台帳、MHLW/自治体台帳 | 登録番号、許可番号、業種、所在地、期限候補 | DDと更新watchに必須 |

### 6.3 P0-C: 行政処分・勧告・命令・指名停止

| source family | 代表ソース | 取るもの | 理由 |
|---|---|---|---|
| `enforcement_fsa` | 金融庁 | 行政処分、登録取消、業務改善命令、無登録警告 | 金融DDで高価値 |
| `enforcement_caa` | 消費者庁 | 特商法、景表法、食品表示等の処分 | EC/広告/食品で高頻度 |
| `enforcement_jftc` | 公正取引委員会 | 排除措置命令、課徴金納付命令、下請法勧告、警告 | 下請/取引/広告で重要 |
| `enforcement_mlit` | 国交省ネガティブ情報等検索 | 建設、宅建、運輸等の処分 | 建設/不動産/物流DDで重要 |
| `enforcement_ppc` | 個人情報保護委員会 | 勧告、命令、注意喚起、ガイドライン | SaaS/個情で重要 |
| `enforcement_mhlw_local` | MHLW/労働局/自治体 | 労基違反公表、食品衛生、医療/介護処分 | 労務/食品/医療で重要 |

### 6.4 P1: 自治体・地方制度

取得対象:

- 条例、規則、要綱、補助金、許認可、飲食/食品/風営/古物/産廃/建築/福祉の手続。
- 都道府県・政令市・中核市を優先し、市区町村は業種別に拡張。

理由:

- 許認可・店舗・建設・食品・福祉は地域差が強い。
- ただし取得難度とページ形式差が大きいため、P0の中央省庁source_profileを安定させてから拡張する。

### 6.5 P2: 裁判例・審決・白書・審議会

取得対象:

- 裁判所判例、審決、審議会資料、白書、行政事業レビュー、統計。

使い道:

- 背景説明、影響度推定、業界傾向。

注意:

- 法的助言リスクが上がるため、P0では「根拠」ではなく「補助情報」に留める。

## 7. AWS収集ジョブ設計

この担当では `COMP-*` ジョブとして定義する。既存の J01-J24、拡張J25-J40と競合しないよう、法務・コンプライアンス成果物専用の論理ジョブ名にする。

### 7.1 COMP-01 source_profile freeze

目的:

- 法務・コンプライアンス領域の公式ソースを source_profile 化する。

出力:

- `source_profiles/compliance/*.json`
- `terms_robots_ledger/compliance_sources.jsonl`

必須項目:

- `source_id`
- `authority`
- `official_url`
- `fetch_mode`: `api | bulk | html | pdf | playwright | screenshot | manual_review`
- `allowed_use`
- `redistribution_boundary`
- `rate_limit_policy`
- `capture_required`
- `screenshot_max_width=1600`
- `private_data_allowed=false`

### 7.2 COMP-02 e-Gov law snapshot and article graph

目的:

- e-Gov法令API/XMLから法令・条文単位の安定IDを作る。

出力:

- `law_snapshot_manifest.json`
- `law_article_nodes.jsonl`
- `law_article_hashes.jsonl`
- `law_to_sector_candidates.jsonl`

### 7.3 COMP-03 amendment diff and effective-date extraction

目的:

- スナップショット差分から改正候補、施行日、経過措置、条文変更を抽出する。

出力:

- `legal_change_events.jsonl`
- `effective_date_candidates.jsonl`
- `article_diff_receipts.jsonl`

注意:

- e-Govから直接「過去全履歴」が常に完全に取れるとは限らないため、jpcite側で日次/週次snapshotを作り、差分を蓄積する。

### 7.4 COMP-04 public comment pipeline

目的:

- e-Govパブコメの募集・結果公示・添付資料を収集する。

出力:

- `public_comment_items.jsonl`
- `public_comment_attachments_manifest.jsonl`
- `public_comment_timeline.jsonl`

重要:

- 募集と結果公示を同一案件として結合する。
- 締切、所管、命令等題名、関連法令、添付PDF hashを取る。

### 7.5 COMP-05 gazette legal notice pipeline

目的:

- 官報の法令公布・告示・公告・政府調達・行政関連noticeをmetadata中心で取得する。

出力:

- `gazette_issue_manifest.jsonl`
- `gazette_article_candidates.jsonl`
- `gazette_pdf_hashes.jsonl`
- `gazette_screenshot_receipts.jsonl`

注意:

- 全文再配布はしない。
- 個人公告は公開packetに出さない。
- 正確性確認は公式官報ページへのdeep linkとhashで行う。

### 7.6 COMP-06 ministry guidance crawler

目的:

- 通達、ガイドライン、Q&A、監督指針、FAQ、制度説明ページを取得する。

対象優先:

1. 個人情報保護委員会。
2. 消費者庁。
3. 公正取引委員会。
4. 金融庁。
5. 厚生労働省。
6. 国土交通省。
7. 経済産業省。
8. 総務省。
9. 国税庁。
10. デジタル庁。

出力:

- `guidance_documents.jsonl`
- `guidance_versions.jsonl`
- `guidance_pdf_hashes.jsonl`
- `guidance_screenshot_receipts.jsonl`

### 7.7 COMP-07 enforcement event normalizer

目的:

- 行政処分、勧告、命令、課徴金、取消、指名停止、違反公表を統一schemaにする。

出力:

- `enforcement_events.jsonl`
- `enforcement_subject_candidates.jsonl`
- `enforcement_law_refs.jsonl`

schema要点:

- `agency`
- `action_type`
- `legal_basis`
- `subject_name`
- `corporation_number_candidate`
- `license_number_candidate`
- `date`
- `source_receipt_refs`
- `name_match_confidence`
- `public_output_allowed`

### 7.8 COMP-08 permit and registry bridge

目的:

- 許認可・登録・届出台帳をDD/更新watchに使える形へ変換する。

対象:

- 金融庁登録業者。
- 国交省建設/宅建/運輸。
- 医療/介護/食品/職業紹介/派遣などの所管別台帳。
- 自治体許認可台帳はP1として段階投入。

出力:

- `sector_registries/*.jsonl`
- `license_key_candidates.jsonl`
- `license_update_rule_candidates.jsonl`

### 7.9 COMP-09 Playwright capture for difficult pages

目的:

- API/通常fetchで取りにくい公開ページを、PlaywrightでDOM、スクリーンショット、PDF link、HAR、console logを証跡化する。

制約:

- screenshot widthは1600px以下。
- CAPTCHA突破、ログイン回避、有料サービス回避、アクセス制限回避はしない。
- 表示内容の再配布ではなく、hash・metadata・短い派生fact・deep linkを基本にする。

出力:

- `playwright_capture_manifest.jsonl`
- `screenshots/{source_id}/{date}/{hash}.png`
- `dom_snapshots/{source_id}/{date}/{hash}.html.gz`
- `capture_failures.jsonl`

### 7.10 COMP-10 OCR and table extraction

目的:

- PDF/画像中心の通達、処分、公告から、packetに必要な短い事実を抽出する。

処理:

- PDF text layer抽出。
- table extraction。
- OCRは必要時のみ。
- confidenceが低い場合は `human_review_required=true` を強制。

出力:

- `extracted_tables.jsonl`
- `ocr_text_candidates.jsonl`
- `low_confidence_review_queue.jsonl`

### 7.11 COMP-11 obligation candidate graph

目的:

- 法令、通達、ガイドライン、処分事例から「義務・期限・対象者・届出・記録保存・禁止行為」の候補を作る。

出力:

- `obligation_candidates.jsonl`
- `deadline_candidates.jsonl`
- `prohibited_action_candidates.jsonl`
- `required_record_candidates.jsonl`

注意:

- 候補であり、確定義務とは表現しない。

### 7.12 COMP-12 sector mapping and relevance scoring

目的:

- 成果物生成のため、法令/通達/処分を業種・事業活動・地域・許認可に結びつける。

出力:

- `sector_source_map.json`
- `business_activity_taxonomy.json`
- `law_sector_relevance_scores.jsonl`

### 7.13 COMP-13 packet fixture materialization

目的:

- 上記データからP0 packet examplesを大量生成する。

出力:

- `packet_examples/regulatory_change_watch/*.json`
- `packet_examples/amendment_impact_diagnosis/*.json`
- `packet_examples/compliance_action_checklist/*.json`
- `packet_examples/contract_clause_attention/*.json`
- `packet_examples/permit_license_renewal_watch/*.json`
- `packet_examples/administrative_sanction_dd/*.json`

### 7.14 COMP-14 GEO proof page generation

目的:

- AIエージェント/answer engineが読みやすい公開proof pageを生成する。

出力:

- `proof_pages/compliance/*.md`
- `llms_compliance_index.md`
- `well_known/compliance_packet_catalog.json`

### 7.15 COMP-15 privacy/legal leak scan

目的:

- 個人情報、全文再配布、法的助言、断定表現、no-hit誤表現を検出する。

検査:

- 官報個人公告が公開packetへ出ていない。
- 行政処分DDで「処分なし」と断定していない。
- 契約条項packetで「適法」と断定していない。
- 法令本文やPDF全文の過剰再配布がない。
- `known_gaps[]` が空でも確認範囲を持つ。

### 7.16 COMP-16 deployment handoff

目的:

- AWS成果物を本体P0計画のREST/MCP/API/公開ページへ安全に渡す。

出力:

- `repo_import_manifest_compliance.json`
- `compliance_release_blockers.json`
- `compliance_packet_catalog_patch.json`

## 8. データモデル

### 8.1 `ComplianceEvent`

```json
{
  "event_id": "comp_evt_...",
  "event_type": "law_amendment | public_comment | gazette_notice | guidance_update | enforcement_action | registry_update | permit_rule_change",
  "stage": "proposal | comment_open | comment_closed | result_published | promulgated | effective | guidance_updated | enforcement_published",
  "title": "string",
  "agency": "string",
  "jurisdiction": "JP | prefecture | municipality",
  "sector_tags": ["ec", "personal_information", "subcontracting"],
  "business_activity_tags": ["advertising", "outsourcing", "consumer_sales"],
  "key_dates": {
    "published_date": "YYYY-MM-DD",
    "comment_deadline": "YYYY-MM-DD",
    "promulgation_date": "YYYY-MM-DD",
    "effective_date": "YYYY-MM-DD"
  },
  "source_receipt_refs": ["sr_..."],
  "claim_refs": ["claim_..."],
  "known_gaps": ["string"],
  "public_output_allowed": true
}
```

### 8.2 `ObligationCandidate`

```json
{
  "obligation_id": "obl_...",
  "candidate_status": "candidate_not_legal_advice",
  "subject_conditions": ["personal_information_handler", "specified_commercial_transaction"],
  "action_type": "notify | record_keep | disclose | report | update_contract | renew_license | file_application | avoid_representation",
  "deadline": "YYYY-MM-DD or null",
  "legal_basis_refs": ["law_article_ref_..."],
  "guidance_refs": ["guidance_ref_..."],
  "source_receipt_refs": ["sr_..."],
  "confidence": {
    "source_confidence": 0.0,
    "extraction_confidence": 0.0,
    "applicability_confidence": 0.0
  },
  "human_review_required": true
}
```

### 8.3 `EnforcementEvent`

```json
{
  "enforcement_id": "enf_...",
  "agency": "Consumer Affairs Agency",
  "action_type": "order | recommendation | warning | administrative_disposition | surcharge | registration_cancelled | suspension | public_notice",
  "subject_name": "string",
  "subject_identifiers": {
    "corporation_number": null,
    "license_number": null,
    "address": null
  },
  "legal_basis": ["string"],
  "violation_summary_derived": "short derived fact, not full reproduction",
  "date": "YYYY-MM-DD",
  "source_receipt_refs": ["sr_..."],
  "name_match_confidence": "high | medium | low",
  "known_gaps": ["同名法人の可能性がある場合は人間確認が必要"]
}
```

## 9. スコアリング

### 9.1 規制変更の関係度

目的:

- エンドユーザー入力と公的イベントの関係を機械的に並べる。
- 最終判断ではなく、確認優先度を出す。

式:

```text
relevance_score =
  0.25 * sector_match
+ 0.20 * business_activity_match
+ 0.15 * regulated_asset_match
+ 0.10 * region_match
+ 0.10 * entity_size_match
+ 0.10 * enforcement_history_signal
+ 0.10 * source_authority_weight
```

各要素:

- `sector_match`: 業種タグ一致。
- `business_activity_match`: 広告、個人情報、委託、運送、食品、金融などの活動一致。
- `regulated_asset_match`: 許可番号、登録、届出、契約類型との一致。
- `region_match`: 国、都道府県、市区町村。
- `entity_size_match`: 中小企業要件、従業員数、売上規模など。
- `enforcement_history_signal`: 同業界の行政処分・勧告・命令が増えているか。
- `source_authority_weight`: 官報/e-Gov/所管省庁/自治体の信頼重み。

### 9.2 緊急度

```text
urgency_score =
  0.35 * deadline_proximity
+ 0.25 * effective_date_proximity
+ 0.15 * penalty_or_disposition_signal
+ 0.15 * comment_deadline_signal
+ 0.10 * operational_complexity
```

注意:

- 期限不明の場合は `unknown` として `known_gaps[]` に出す。
- 緊急度が高くても、法的助言ではなく確認優先度として表示する。

### 9.3 売上優先度

AWSの処理順は、収集価値だけでなく商品化しやすさで決める。

```text
commercial_priority =
  0.25 * buyer_pain
+ 0.20 * repeat_usage
+ 0.15 * willingness_to_pay
+ 0.15 * ai_agent_recommendability
+ 0.15 * source_backed_differentiation
+ 0.10 * automation_reliability
```

P0は以下を満たすもの:

- AIが一言で価値を説明できる。
- 出典付きで安く返せる。
- 1回限りでなく継続利用される。
- 法務・コンプラ・許認可・DDのいずれかの高痛点に直結する。

## 10. packet examples

### 10.1 `regulatory_change_watch_packet`

```json
{
  "packet_type": "regulatory_change_watch",
  "request_time_llm_call_performed": false,
  "watch_subject": {
    "sector": "EC/D2C",
    "business_activities": ["consumer_sales", "online_advertising", "personal_information_collection"],
    "regions": ["JP"]
  },
  "events": [
    {
      "event_id": "comp_evt_public_comment_...",
      "stage": "comment_open",
      "headline": "消費者向け表示に関係する可能性がある意見募集",
      "impact_level": "medium",
      "deadline_or_effective_date": "YYYY-MM-DD",
      "why_relevant": [
        {
          "claim": "online_advertising と consumer_sales の活動タグに関連する可能性がある",
          "claim_refs": ["claim_001"]
        }
      ],
      "recommended_checks": [
        "対象商品・LP・広告運用が案件の対象範囲に含まれるか確認する",
        "意見募集締切前に所管資料と添付PDFを確認する"
      ],
      "source_receipt_refs": ["sr_egov_public_comment_..."]
    }
  ],
  "known_gaps": [
    "個別商品の表示内容はこのpacketでは確認していない",
    "自治体独自の指導情報は対象外"
  ],
  "human_review_required": true,
  "_disclaimer": "公的情報に基づく確認材料であり、法的助言や適法性の保証ではありません。"
}
```

### 10.2 `amendment_impact_diagnosis_packet`

```json
{
  "packet_type": "amendment_impact_diagnosis",
  "request_time_llm_call_performed": false,
  "subject": {
    "sector": "SaaS",
    "business_activities": ["personal_information_processing", "outsourcing", "consumer_terms"]
  },
  "diagnosis": [
    {
      "area": "privacy_policy_and_outsourcing",
      "impact_level": "high",
      "reasoning_type": "source_backed_matching",
      "matched_conditions": ["personal_information_processing", "outsourcing"],
      "claims": [
        {
          "claim": "個人情報取扱い・委託先管理に関する確認が必要な可能性がある",
          "claim_refs": ["claim_101"]
        }
      ],
      "recommended_followup_questions": [
        "個人情報の国外移転があるか",
        "再委託先を利用しているか",
        "漏えい等発生時の社内手順があるか"
      ],
      "source_receipt_refs": ["sr_ppc_guideline_..."]
    }
  ],
  "known_gaps": [
    "実際のプライバシーポリシー本文は確認していない"
  ],
  "human_review_required": true
}
```

### 10.3 `contract_clause_attention_packet`

```json
{
  "packet_type": "contract_clause_attention",
  "request_time_llm_call_performed": false,
  "contract_context": {
    "contract_type": "業務委託契約",
    "sector": "IT制作",
    "relationship": "発注者 -> 個人フリーランス"
  },
  "attention_topics": [
    {
      "topic": "支払期日・検収・一方的なやり直し",
      "attention_level": "high",
      "why": "フリーランス取引・下請取引の確認対象になり得る",
      "check_items": [
        "支払期日が明確か",
        "検収基準が一方的でないか",
        "無償修正の範囲が無限定でないか"
      ],
      "source_receipt_refs": ["sr_jftc_guidance_..."],
      "claim_refs": ["claim_201"]
    }
  ],
  "known_gaps": [
    "契約書全文は確認していない",
    "当事者の資本金・取引規模は確認していない"
  ],
  "human_review_required": true,
  "_disclaimer": "条項の最終文案や適法性判断ではなく、専門家確認前の論点整理です。"
}
```

### 10.4 `permit_license_renewal_watch_packet`

```json
{
  "packet_type": "permit_license_renewal_watch",
  "request_time_llm_call_performed": false,
  "subject": {
    "sector": "construction",
    "license_identifiers": ["許可番号候補"],
    "regions": ["Tokyo"]
  },
  "registry_checks": [
    {
      "registry": "MLIT construction/real estate registry family",
      "hit_status": "candidate_hit",
      "name_match_confidence": "medium",
      "fields_found": ["business_name", "license_number_candidate", "jurisdiction"],
      "source_receipt_refs": ["sr_mlit_registry_..."]
    }
  ],
  "renewal_risk_items": [
    {
      "item": "更新期限・変更届の確認",
      "status": "needs_human_confirmation",
      "reason": "公開台帳だけでは期限が確定しない可能性がある"
    }
  ],
  "known_gaps": [
    "自治体独自手続は未確認",
    "提出済み書類や社内保管書類は確認していない"
  ],
  "human_review_required": true
}
```

### 10.5 `administrative_sanction_dd_packet`

```json
{
  "packet_type": "administrative_sanction_dd",
  "request_time_llm_call_performed": false,
  "subject_entity": {
    "name": "株式会社サンプル",
    "corporation_number": "optional",
    "name_match_policy": "strict_with_alias_review"
  },
  "checks": [
    {
      "source": "FSA registered business list",
      "result": "no_hit_in_checked_scope",
      "checked_at": "YYYY-MM-DD",
      "source_receipt_refs": ["sr_fsa_registry_..."],
      "no_hit_statement": "確認したFSA登録業者一覧の範囲では該当候補を確認できませんでした。登録不要または未登録を意味するものではありません。"
    },
    {
      "source": "MLIT negative information",
      "result": "candidate_hit",
      "name_match_confidence": "low",
      "source_receipt_refs": ["sr_mlit_negative_..."],
      "requires_review": "同名/類似名の可能性があるため法人番号・所在地で確認が必要"
    }
  ],
  "known_gaps": [
    "すべての自治体処分情報は確認していない",
    "過去の社名変更・合併情報は未結合"
  ],
  "human_review_required": true
}
```

### 10.6 `public_comment_opportunity_packet`

```json
{
  "packet_type": "public_comment_opportunity",
  "request_time_llm_call_performed": false,
  "subject": {
    "sector": "financial_services",
    "interest": ["funds_transfer", "consumer_protection", "outsourcing"]
  },
  "open_items": [
    {
      "public_comment_id": "egov_pcm_...",
      "title": "制度改正案に関する意見募集",
      "agency": "string",
      "deadline": "YYYY-MM-DD",
      "why_relevant": "funds_transfer / consumer_protection tags matched",
      "read_first": [
        "意見募集要領",
        "新旧対照表",
        "概要資料"
      ],
      "source_receipt_refs": ["sr_public_comment_..."]
    }
  ],
  "known_gaps": [
    "意見書の作成・提出代理は行わない"
  ],
  "human_review_required": true
}
```

## 11. 本体計画へのマージ順

### 11.1 実装前に固定するもの

1. `packet_type` 名称。
2. 共通schema。
3. source_profile形式。
4. `known_gaps[]` 表現。
5. no-hit文言。
6. `_disclaimer`。
7. legal/compliance forbidden claims。
8. AWS artifact manifest。

### 11.2 本体P0との順番

1. P0-E1 Packet contract and catalog に、法務・コンプライアンスpacketを追加する。
2. P0-E2 Source receipts / claim_refs / known_gaps に、法令・通達・官報・パブコメ・行政処分向けのreceipt subtypeを追加する。
3. P0-E3 Pricing/cost preview に、`compliance_packet` の価格階層を追加する。
4. P0-E5 Packet composers に、まず6種類だけ実装する。
5. P0-E6 REST facade に `/packets/compliance/*` の読み取りAPIを追加する。
6. P0-E7 MCP tools に、AI agent向け tool description を追加する。
7. P0-E8 Public proof/discovery に、GEO向け成果物ページを追加する。
8. P0-E9 Drift/privacy/billing/release gates に、法務禁止表現と出典欠落のrelease blockerを追加する。

### 11.3 先に出すべき6 packet

最初の本番投入は以下に絞る。

1. `regulatory_change_watch_packet`
2. `amendment_impact_diagnosis_packet`
3. `compliance_action_checklist_packet`
4. `contract_clause_attention_packet`
5. `permit_license_renewal_watch_packet`
6. `administrative_sanction_dd_packet`

理由:

- 横断業種で使える。
- AIエージェントが推薦しやすい。
- source-backedの差別化が強い。
- 継続課金と従量課金の両方に向く。
- 法的助言ではなく「確認材料」に落としやすい。

## 12. AWS実行順

### Phase C11-0: 安全条件

実行前に必ず満たす:

- `bookyou-recovery` / account `993693061769` / `us-east-1` のみを使う。
- Cost guardrailは本体AWS計画の `17,000 / 18,300 / 18,900 / 19,300` を使用する。
- Budgetsはhard capではないため、Budget Actions、tag policy、operator stopline、kill switchを併用する。
- private CSV、顧客契約書、顧客個人情報はAWSへ送らない。
- Playwrightは公開ページのみ、CAPTCHA/ログイン/有料回避なし。

### Phase C11-1: P0 source foundation

実行:

1. COMP-01 source_profile freeze。
2. COMP-02 e-Gov law snapshot。
3. COMP-04 public comment pipeline。
4. COMP-05 gazette metadata pipeline。
5. COMP-06 ministry guidance crawler。

成果:

- 法令・パブコメ・官報・ガイドラインの最小source_receiptが揃う。
- これだけで `regulatory_change_watch_packet` の初期版が作れる。

### Phase C11-2: enforcement and registry

実行:

1. COMP-07 enforcement event normalizer。
2. COMP-08 permit and registry bridge。
3. COMP-10 OCR/table extraction。

成果:

- `administrative_sanction_dd_packet` と `permit_license_renewal_watch_packet` の初期版が作れる。

### Phase C11-3: obligation graph and sector mapping

実行:

1. COMP-03 amendment diff。
2. COMP-11 obligation candidate graph。
3. COMP-12 sector mapping。

成果:

- `amendment_impact_diagnosis_packet` と `compliance_action_checklist_packet` の質が上がる。

### Phase C11-4: Playwright expansion

実行:

1. COMP-09 Playwright capture。
2. 1600px以下screenshot。
3. DOM/PDF/HAR/console log manifest。
4. 失敗キューとretry。

成果:

- fetch困難な省庁/自治体/検索ページも証跡化できる。
- ただし公開packetには画像を原則出さず、hash/deep link/短い派生factを使う。

### Phase C11-5: packet/proof/GEO

実行:

1. COMP-13 packet fixture materialization。
2. COMP-14 GEO proof page generation。
3. COMP-15 privacy/legal leak scan。
4. COMP-16 deployment handoff。

成果:

- 本体P0のAPI/MCP/公開ページへ投入できる。
- AIエージェントが見に来た時に「このpacketが買える」と理解できる。

## 13. 収集対象を広げる順番

### 13.1 最初の7日でやる範囲

1. e-Gov法令。
2. e-Govパブコメ。
3. 官報metadata。
4. PPC、CAA、JFTC、FSA、MHLW、MLITのP0ページ。
5. FSA登録業者、MLITネガティブ情報、JFTC報道発表、CAA行政処分。
6. Playwright canaryを10-20 sourceで実施。
7. P0 packet examplesを最低100-300件生成。

### 13.2 2週目で広げる範囲

1. METI、MIC、NTA、Digital Agency。
2. 医療、介護、食品、労務、運輸、建設、不動産、人材、金融の個別台帳。
3. 都道府県・政令市の許認可/行政処分/条例。
4. パブコメ結果と官報公布の結合。
5. 行政処分から業界別チェックリストの自動生成。
6. proof pageとMCP tool descriptionを拡充。

### 13.3 今回やりすぎない範囲

- 全自治体の完全網羅。
- 有料官報情報検索サービスの内容再配布。
- 裁判例を使った法的結論生成。
- 契約書全文レビューの自動最終判断。
- 個人公告、破産公告など個人情報性が高い官報記事の公開packet化。
- CAPTCHA、ログイン、アクセス制限の回避。

## 14. 禁止表現

法務・コンプライアンスpacketでは、以下を禁止する。

- 「適法です」
- 「違法です」
- 「処分はありません」
- 「行政処分歴なし」
- 「許可は有効です」
- 「この契約書で問題ありません」
- 「弁護士確認は不要です」
- 「必ず申請できます」
- 「必ず補助金対象です」
- 「規制対象外です」
- 「安全な取引先です」
- 「反社ではありません」
- 「与信上問題ありません」
- 「この表示は景表法違反ではありません」

安全な表現:

- 「確認した公的情報の範囲では、該当候補を確認できませんでした」
- 「このpacketでは未確認の範囲があります」
- 「関係する可能性があるため、人間または専門家による確認が必要です」
- 「出典A/B/Cに基づく確認材料です」
- 「法的助言や適法性保証ではありません」

## 15. release blockers

以下が1つでもあれば、本番公開しない。

1. `claim_refs[]` のない主張がある。
2. `source_receipts[]` が空のpacketがある。
3. `known_gaps[]` が欠けている。
4. no-hitを不存在証明として表現している。
5. 法的助言・適法保証・処分なし断定が含まれる。
6. 官報個人公告など個人情報性の高い情報が公開packetに混入している。
7. 法令本文/PDF全文の過剰再配布がある。
8. Playwright screenshotが1600pxを超える、またはCAPTCHA/ログイン回避に見えるcaptureがある。
9. 行政処分DDで同名法人の注意が欠けている。
10. 契約条項packetが条項確定版として読める。
11. 出典の利用規約/robots/再配布境界が未確認。
12. human review required がfalseになっている法務packetがある。

## 16. 価格・課金動線の考え方

法務・コンプライアンス領域は、無料検索と有料packetの差を明確にしやすい。

無料で見せる:

- packet catalog。
- どんな公的sourceを確認するか。
- サンプルpacket。
- no-hitの正しい意味。
- 価格の概算。
- AIエージェント向けtool description。

有料にする:

- 個別業種/事業活動に合わせた `amendment_impact_diagnosis_packet`。
- 取引先名や法人番号を入れた `administrative_sanction_dd_packet`。
- 許認可/登録/更新対象を入れた `permit_license_renewal_watch_packet`。
- 継続的な `regulatory_change_watch_packet`。
- 大量対象のbatch DD。
- 証跡ledger付きexport。

売り方:

- AIエージェントが「法務相談の前に、まず公的根拠付きの確認材料を取る」と推薦する。
- エンドユーザーは安価に一次情報の束を取得し、必要なら弁護士・行政書士・社労士・税理士へ持ち込む。
- jpciteは専門家を代替せず、専門家確認の前処理として位置づける。

## 17. GEO向け公開ページ案

公開ページはSEO記事ではなく、AIエージェントが読みやすい構造化ページにする。

ページ例:

1. `/jp/packets/regulatory-change-watch`
2. `/jp/packets/amendment-impact-diagnosis`
3. `/jp/packets/compliance-action-checklist`
4. `/jp/packets/contract-clause-attention`
5. `/jp/packets/permit-license-renewal-watch`
6. `/jp/packets/administrative-sanction-dd`
7. `/jp/sources/egov-law`
8. `/jp/sources/public-comment`
9. `/jp/sources/kanpo`
10. `/jp/sources/administrative-sanctions`

各ページに置くもの:

- `what_agents_can_do`
- `input_schema`
- `output_schema`
- `source_families_checked`
- `known_gaps_policy`
- `no_hit_policy`
- `pricing_metadata`
- `mcp_tool_name`
- `api_endpoint`
- `sample_packet`
- `forbidden_claims`

## 18. 公式ソース起点

以下はsource_profile候補の公式起点である。実際のAWS実行前に、利用規約、robots、取得間隔、再配布境界を再確認する。

### 18.1 法令・行政手続・パブコメ

- e-Gov APIカタログ 法令API: https://api-catalog.e-gov.go.jp/info/ja/apicatalog/view/44
- e-Gov法令API docs: https://laws.e-gov.go.jp/docs/law-data-basic/8529371-law-api-v1/
- e-Gov法令 XML一括ダウンロード: https://laws.e-gov.go.jp/bulkdownload/
- e-Govパブリックコメント RSS一覧: https://public-comment.e-gov.go.jp/contents/help/guide/rss.html
- e-Govパブリックコメント RSSフィードについて: https://public-comment.e-gov.go.jp/contents/service-policy/rssfeed.html
- e-Gov APIカタログ利用規約: https://api-catalog.e-gov.go.jp/info/terms
- e-Gov Developer: https://developer.e-gov.go.jp/contents/specification

### 18.2 官報・法案

- 官報発行サイト: https://www.kanpo.go.jp/
- 国立印刷局 官報: https://www.npb.go.jp/product_service/books/index.html
- 官報情報検索サービス利用規約: https://search.npb.go.jp/guide/kiyaku.html
- 内閣官房 国会提出法案: https://www.cas.go.jp/jp/houan/index.html
- 参議院 議案情報: https://www.sangiin.go.jp/japanese/joho1/kousei/gian/

### 18.3 主要コンプライアンス領域

- 個人情報保護委員会 法令・ガイドライン: https://www.ppc.go.jp/personalinfo/legal/
- 消費者庁 行政処分: https://www.caa.go.jp/business/disposal/
- 消費者庁 食品表示関連通知: https://www.caa.go.jp/policies/policy/food_labeling/information/notice/
- 公正取引委員会 報道発表資料: https://www.jftc.go.jp/houdou/pressrelease
- 公正取引委員会 下請法報道発表資料: https://www.jftc.go.jp/shitauke/houdou/index.html
- 金融庁 金融機関情報: https://www.fsa.go.jp/status/index.html
- 金融庁 免許・許可・登録等を受けている事業者一覧: https://www.fsa.go.jp/menkyo/menkyo.html
- 国土交通省 ネガティブ情報等検索サイト: https://www.mlit.go.jp/nega-inf/index.html
- 厚生労働省 食品衛生監視指導関連通知例: https://www.mhlw.go.jp/stf/newpage_56303.html

## 19. 最終判断

この領域は、AWSクレジットを使って広げる価値が十分にある。

ただし、単に大量の法令・PDF・スクリーンショットを集めるだけでは弱い。売上につながる形にするには、以下を守る必要がある。

1. 先にP0 packetを6種類に絞る。
2. 各packetに必要な一次情報だけを優先取得する。
3. 法務助言ではなく、出典付き確認材料に徹する。
4. no-hitの誤表現を絶対に避ける。
5. 行政処分DDは同名・旧社名・法人番号・許可番号の不確実性を明示する。
6. 通達・ガイドライン・パブコメ・官報・行政処分を時系列で結ぶ。
7. Playwright/1600px以下スクリーンショットは「取得困難ページの証跡化」に限定する。
8. GEOページとMCP/APIは、AIエージェントが推薦しやすいpacket単位で公開する。

これにより、jpciteは「日本の公的一次情報を検索するサービス」ではなく、「AIエージェントがエンドユーザーへ安く売れる法務・コンプライアンス成果物を、出典付きで返すサービス」として説明できる。
