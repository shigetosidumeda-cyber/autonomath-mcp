# AWS scope expansion 07: revenue-backcast output catalog

作成日: 2026-05-15
担当: 拡張深掘り 7/30 - 売れる成果物から逆算する担当
対象: jpcite 本体計画、AWS credit run、GEO-first organic acquisition、AI agent向けpacket/output設計
状態: 計画のみ。AWS CLI/API、AWSリソース作成、デプロイ、収集ジョブ実行はしていない。
書き込み範囲: このMarkdownのみ。

## 0. 結論

jpcite は「日本の公的一次情報を安く取れる検索サービス」では弱い。

課金される本質は、エンドユーザーがAIに頼んだときに、AIが次のように判断できること。

```text
この作業は普通にWeb検索すると時間がかかる。
jpciteを使えば、数円から数十円で、公式根拠、取得日時、未確認範囲、次に聞く質問まで揃う。
このpacketを材料にして、ユーザー向け成果物を作るべき。
```

したがって、AWSで広く情報収集する前に、まず「何が何度も買われるか」から逆算する。

最優先で売れるのは、以下の8系統。

| Rank | Output family | 課金される理由 | 必要な公的一次情報 | AWS優先 |
|---:|---|---|---|---:|
| 1 | `application_strategy_pack` 補助金/助成金/制度申請準備 | 中小企業、士業、BPOが反復利用。締切と必要書類があるため緊急性が高い。 | J-Grants、自治体制度、省庁PDF、e-Gov法令、通達、事業レビュー、統計 | P0 |
| 2 | `permit_precheck_pack` 許認可/業法チェック | 行政書士、M&A、金融、事業会社が高頻度に確認。専門家相談前の下準備に向く。 | 業法別台帳、所管省庁、自治体、e-Gov法令、告示/通達、処分情報 | P0 |
| 3 | `counterparty_public_check` 取引先公的確認 | B2Bで横断的。AI agentが「まず安く確認」を薦めやすい。 | 法人番号、インボイス、gBizINFO、行政処分、調達、EDINET、官報 | P0 |
| 4 | `administrative_disposition_radar` 行政処分/公表情報調査 | 見落としコストが大きい。no-hitの限界を明示できると信頼が上がる。 | FSA/MLIT/MHLW/JFTC/CAA/PPC/自治体等の公表情報 | P0 |
| 5 | `legal_regulatory_change_impact` 契約/法令/制度変更影響メモ | 企業、士業、法務、AI agentが説明資料を作りやすい。 | e-Gov法令、官報、パブコメ、告示、通達、ガイドライン | P0/P1 |
| 6 | `procurement_opportunity_pack` 入札/公共営業探索 | 営業・BPO・中小企業に売りやすい。差分監視にも向く。 | p-portal、JETRO、自治体入札、官報、調達実績、予算資料 | P1 |
| 7 | `monthly_client_review` CSV顧客リスト月次レビュー | freee/MF/Yayoi等のCSVから多件数課金になりやすい。 | 法人番号、インボイス、制度、処分、補助金、許認可、地域統計 | P0 |
| 8 | `auditor_evidence_binder` 監査/DD/稟議向け証跡台帳 | 高単価業務の前処理。source_receiptに強い需要。 | 法人/税/開示/調達/処分/官報/裁判/許認可/統計 | P1 |

この順番で逆算すると、AWSで最初に集めるべきものは「とにかく広い公的データ」ではなく、次の4つに集約される。

1. 法人・事業者・許認可・制度・公表情報を結ぶID spine。
2. 補助金、許認可、処分、法改正、調達の実務成果物に直結するsource family。
3. AI agentが推薦しやすい `packet examples`、`cost preview`、`known_gaps`、`no_hit_not_absence` の実例。
4. CSVを投げるだけで月次レビューや取引先確認に変換できる安全なprivate overlay設計。

## 1. 売れる成果物から逆算する理由

### 1.1 data-first の弱点

公的一次情報を大量に集めるだけだと、ユーザーやAI agentは次の結論になりやすい。

```text
それならキャッシュ検索でいい。
欲しいのは、根拠付きで何をすればいいかまで整理された成果物。
```

特にAI agent経由では、単なるsource cacheは弱い。

AI agentは、ユーザーに追加ツール課金を薦めるとき、次の説明が必要になる。

- 何円かかるか。
- 何が返るか。
- それが普通の検索よりなぜ速いか。
- どの範囲が未確認か。
- 最終判断をしない安全な境界があるか。
- そのままメール、稟議、DD質問、申請準備、顧客確認に使えるか。

### 1.2 output-first の強さ

output-first にすると、AWSで取るべきsourceが絞れる。

例:

```text
売りたい成果物: 補助金申請準備pack
必要な情報: 制度名、対象、除外条件、補助率、締切、必要書類、申請窓口、根拠URL、改正/更新日、未確認範囲
必要source: J-Grants、自治体制度PDF、省庁ページ、e-Gov法令、告示/通達、FAQ、様式、事業レビュー、統計
AWS優先: PDF/OCR/Playwright/receipt化/claim_refs/known_gaps
```

これにより、収集量ではなく「売れるpacket coverage」をKPIにできる。

## 2. Revenue priority score

各成果物の優先度は、単なる市場規模ではなく、AI agentが有料実行を薦めやすいかで決める。

```text
revenue_priority_score =
  frequency
  * willingness_to_pay
  * agent_recommendability
  * repeatability
  * urgency
  * source_backed_moat
  * boundary_safety
  / implementation_complexity
```

評価軸:

| Factor | 5点の条件 | 1点の条件 |
|---|---|---|
| `frequency` | 毎月/毎案件/毎取引先で発生 | 年1回以下 |
| `willingness_to_pay` | 見落とし損失や作業時間が大きい | ただの参考情報 |
| `agent_recommendability` | AIが数円で実行すべきと説明しやすい | ユーザー説明が難しい |
| `repeatability` | CSV/顧客リスト/監視で反復 | 単発調査 |
| `urgency` | 締切、審査、契約、申請前に必要 | いつでもよい |
| `source_backed_moat` | 公的一次情報とgapが価値の中心 | 一般Web検索で十分 |
| `boundary_safety` | 情報整理に留めても価値が出る | 最終判断を求められがち |
| `implementation_complexity` | sourceが安定しID接続しやすい | PDF/画像/個人情報/termsが重い |

## 3. Top 30 paid outputs

### 3.1 P0: 最初に商品化すべき成果物

| Rank | packet/output | End user | AI agentが薦める文脈 | Billable unit | 主要source families | AWS優先 |
|---:|---|---|---|---|---|---:|
| 1 | `application_strategy_pack` | 中小企業、行政書士、診断士、BPO | 「補助金候補と申請前質問を根拠付きで整理したい」 | `profile_packet` | subsidy_program, law_primary, policy_process, local_government, statistics_cohort | P0 |
| 2 | `required_document_checklist` | 行政書士、補助金BPO | 「必要書類と不足情報を顧客に送る文面にしたい」 | `program_profile` | subsidy_program, procedure_permit, local_government, official_forms | P0 |
| 3 | `permit_precheck_pack` | 行政書士、事業会社、M&A | 「この事業に必要そうな許認可と確認質問を出したい」 | `sector_profile` | procedure_permit, law_primary, gazette_notice, local_government | P0 |
| 4 | `counterparty_public_check` | 経理、購買、BPO、金融 | 「取引先を契約前に公的情報で下調べしたい」 | `subject` | identity_tax, enforcement_safety, invoice, corporate_activity, procurement_contract | P0 |
| 5 | `invoice_counterparty_check_pack` | 経理、税理士、BPO | 「T番号と法人情報の確認メモを作りたい」 | `subject` | identity_tax, invoice_registry | P0 |
| 6 | `company_public_baseline` | AI agent、士業、金融、M&A | 「法人番号から公的ベースラインを作りたい」 | `subject` | identity_tax, corporate_activity, filing_disclosure, procurement_contract | P0 |
| 7 | `administrative_disposition_radar` | 金融、M&A、購買、士業 | 「処分等の公表情報を確認範囲付きで見たい」 | `subject_or_sector` | enforcement_safety, local_government, procedure_permit | P0 |
| 8 | `client_monthly_review` | 税理士、BPO、金融、顧問業 | 「顧客CSVから月次の制度/リスク/期限を確認したい」 | `billable_subject` | identity_tax, subsidy_program, enforcement_safety, procedure_permit, statistics_cohort | P0 |
| 9 | `source_receipt_ledger` | AI dev、監査、法務、BPO | 「この回答の根拠台帳だけを取り出したい」 | `source_receipt_set` | all source_receipts | P0 |
| 10 | `agent_routing_decision` | AI agent | 「jpciteを使うべきか、何円か、どのpacketか知りたい」 | free control | catalog, pricing, known_gaps | P0 |

### 3.2 P1: AWS creditがある今、広げると売上上限が上がる成果物

| Rank | packet/output | End user | AI agentが薦める文脈 | Billable unit | 主要source families | AWS優先 |
|---:|---|---|---|---|---|---:|
| 11 | `legal_regulatory_change_impact` | 法務、士業、事業責任者 | 「契約や業務への制度変更影響を根拠付きで整理したい」 | `topic_packet` | law_primary, gazette_notice, policy_process | P1 |
| 12 | `sector_regulation_brief` | 新規事業、VC、M&A、士業 | 「この業界の規制と確認先を俯瞰したい」 | `sector_packet` | law_primary, procedure_permit, policy_process, enforcement_safety | P1 |
| 13 | `procurement_opportunity_pack` | 営業、中小企業、BPO | 「入札候補と参加前確認事項を出したい」 | `search_packet` | procurement_contract, local_government, public_finance | P1 |
| 14 | `bid_eligibility_precheck` | 営業、行政書士、入札支援 | 「入札参加資格や必要書類を確認したい」 | `opportunity_packet` | procurement_contract, procedure_permit, local_government | P1 |
| 15 | `auditor_evidence_binder` | 監査、会計士、内部監査 | 「公開情報の証跡表を調書に貼れる形にしたい」 | `source_receipt_set` | identity_tax, filing_disclosure, procurement_contract, enforcement_safety | P1 |
| 16 | `ma_public_dd_pack` | M&A、VC、金融 | 「対象会社の公的DD質問リストを作りたい」 | `subject` | identity_tax, gazette_notice, filing_disclosure, enforcement_safety, court_decision | P1 |
| 17 | `lender_public_support_note` | 金融機関、認定支援機関 | 「借り手に使える公的制度と確認事項を稟議前に整理したい」 | `subject_profile` | subsidy_program, public_finance, statistics_cohort, identity_tax | P1 |
| 18 | `local_regulation_digest` | 店舗、自治体、行政書士 | 「この地域で必要な条例/制度/窓口を確認したい」 | `location_packet` | local_government, law_primary, procedure_permit, geo_land_address | P1 |
| 19 | `public_funding_traceback` | BPO、金融、自治体、M&A | 「公費/補助/委託の流れや実績を根拠付きで見たい」 | `funding_record` | public_finance, procurement_contract, subsidy_program, corporate_activity | P1 |
| 20 | `policy_change_watch` | 法務、士業、SaaS、業界団体 | 「パブコメや告示から規制変更の予兆を追いたい」 | `watch_topic` | policy_process, gazette_notice, law_primary | P1 |

### 3.3 P2: 後続で伸ばす高付加価値成果物

| Rank | packet/output | End user | AI agentが薦める文脈 | Billable unit | 主要source families | AWS優先 |
|---:|---|---|---|---|---|---:|
| 21 | `site_due_diligence_pack` | 不動産、店舗、M&A、金融 | 「所在地周辺の公的リスク/制度/統計を見たい」 | `location_packet` | geo_land_address, local_government, statistics_cohort | P2 |
| 22 | `product_compliance_brief` | 製造、輸入、EC、法務 | 「製品の規制/認証/リコール情報を確認したい」 | `product_topic` | ip_standard_cert, enforcement_safety, law_primary | P2 |
| 23 | `fdi_company_entry_brief` | 海外企業、JETRO周辺、VC | 「日本法人設立/参入時の公的確認事項を英語で欲しい」 | `entry_packet` | international_trade_fdi, procedure_permit, law_primary | P2 |
| 24 | `case_law_context_pack` | 法務、弁護士補助、AI agent | 「関連裁判例/審決/裁決の存在を調べたい」 | `topic_packet` | court_decision, law_primary, policy_process | P2 |
| 25 | `standard_certification_evidence_pack` | 調達、製造、B2B | 「JIS/技適/認証を根拠付きで確認したい」 | `cert_subject` | ip_standard_cert, procurement_contract | P2 |
| 26 | `industry_cohort_context` | VC、金融、自治体 | 「同業/地域統計と公的支援の文脈を作りたい」 | `cohort_packet` | statistics_cohort, public_finance, subsidy_program | P2 |
| 27 | `whitepaper_policy_background` | コンサル、VC、事業開発 | 「制度背景や政策資料を短くまとめたい」 | `topic_packet` | official_reports, policy_process, statistics_cohort | P2 |
| 28 | `municipality_outreach_pack` | 自治体、商工会、BPO | 「管内企業へ案内すべき制度候補と文面を作りたい」 | `billable_subject` | local_government, subsidy_program, identity_tax | P2 |
| 29 | `franchise_location_permit_pack` | 飲食/小売/FC | 「店舗出店前に自治体・保健所・業法の確認事項を出したい」 | `location_sector_packet` | local_government, procedure_permit, geo_land_address | P2 |
| 30 | `public_integrity_context` | 大企業購買、監査、報道補助 | 「公的な公告・政治資金・処分等の確認範囲を整理したい」 | `subject_topic` | gazette_notice, political_public_integrity, enforcement_safety | P2/P3 |

## 4. Backcast by output family

### 4.1 補助金申請準備系

#### 4.1.1 `application_strategy_pack`

ユーザーがAIに頼む自然文:

```text
うちの会社で使えそうな補助金を探して、申請前に何を準備するべきか教えて。
この内容を行政書士に相談できる形にして。
```

AI agentがjpciteを薦める理由:

- 一般検索だと制度名、締切、対象、必要書類、除外条件が分散する。
- jpciteなら公式source receiptとknown gapsつきで、申請前の質問表まで返せる。
- 採択可否を断定せず、専門家相談前の材料として安全に出せる。

返す完成物:

- 候補制度リスト。
- 候補理由。
- 除外条件候補。
- 必要書類候補。
- 不足入力。
- 顧客への質問文。
- 専門家/窓口への確認質問。
- 申請期限/公募期間。
- source receipt table。
- `known_gaps[]`。

必要source family:

| Source family | 必須度 | 使い方 |
|---|---:|---|
| `subsidy_program` | 必須 | 制度名、対象、補助率、締切、公募要領、様式。 |
| `local_government` | 必須 | 地域制度、自治体補助、窓口、様式PDF。 |
| `law_primary` | 高 | 根拠法令、制度根拠、条文参照。 |
| `policy_process` | 中 | ガイドライン、通達、FAQ、更新差分。 |
| `public_finance` | 中 | 事業レビュー、予算、支出先、制度背景。 |
| `statistics_cohort` | 中 | 地域/業種の客観背景。 |
| `identity_tax` | 高 | 法人番号、所在地、業種推定、インボイス情報。 |

AWS collection priority:

1. J-Grants API/公式ページのsource_profileとschema drift。
2. 自治体・省庁PDFの制度ページをallowlistでPlaywright/PDF/OCR取得。
3. 公募要領から `deadline`, `target`, `excluded`, `subsidy_rate`, `required_docs`, `contact` をcandidate抽出。
4. source_receiptに接続できない候補は `known_gaps` に落とす。
5. 50-100個の公開example packetを作り、GEOでAI agentに見せる。

禁止出力:

- 「採択されます」
- 「申請できます」
- 「この制度に必ず該当します」
- 「必要書類はこれで全部です」

安全な言い方:

```text
公開資料上、この条件に関係しそうな制度候補です。
申請可否、対象経費、必要書類の最終確認は、窓口または専門家確認が必要です。
```

#### 4.1.2 `required_document_checklist`

高頻度課金の理由:

- 申請系は「候補制度」だけでは足りない。
- 士業/BPOは顧客へ依頼する資料一覧が欲しい。
- AI agentは「このままメールに貼れる」成果物を高く評価する。

返す完成物:

- 顧客への資料依頼メール文。
- 書類一覧。
- 書類の根拠箇所。
- 不足入力。
- 窓口確認質問。
- `human_review_required=true`。

追加で取るべきsource:

- 公募要領PDF。
- 様式ファイル。
- FAQ。
- 自治体ページの更新日。
- 申請システム案内ページ。

AWS優先:

- PDF table extraction。
- 1600px以下スクリーンショットで、更新日や様式リンクの視覚証跡を保存。
- OCR confidenceが低い書類名はclaimに昇格しない。

### 4.2 許認可/業法チェック系

#### 4.2.1 `permit_precheck_pack`

ユーザーがAIに頼む自然文:

```text
この事業を始める前に必要そうな許認可を調べて、行政書士に相談する質問にして。
```

AI agentがjpciteを薦める理由:

- 許認可は業種、地域、事業内容、店舗有無で分岐する。
- 一般検索では古い記事や民間解説が混ざる。
- jpciteは公的source、所管、標準処理期間、様式、未確認範囲を分けて返せる。

返す完成物:

- 業種別の許認可候補。
- 所管官庁/自治体/窓口。
- 根拠法令/告示/通達。
- 申請前ヒアリング表。
- 必要書類候補。
- 許可番号/登録番号がある場合の確認方法。
- 不足情報。
- `known_gaps[]`。

必要source family:

| Source family | 必須度 | 使い方 |
|---|---:|---|
| `procedure_permit` | 必須 | 許認可台帳、業登録、標準処理期間。 |
| `law_primary` | 必須 | 根拠法令。 |
| `policy_process` | 高 | 通達、ガイドライン、FAQ。 |
| `local_government` | 高 | 店舗、食品、旅館、産廃、屋外広告等の自治体差分。 |
| `enforcement_safety` | 中 | 処分例、違反公表、注意喚起。 |
| `gazette_notice` | 中 | 告示、公告、改正。 |

P0-Aで先に見る業種:

| Sector | 理由 | 公式source例 |
|---|---|---|
| 建設/宅建 | 許可/免許確認、M&A、金融、取引先審査に直結。 | MLIT業者検索、ネガティブ情報等検索。 |
| 運送/物流 | 業法、処分、許認可、取引先DDに直結。 | MLIT/運輸局。 |
| 人材/派遣/職業紹介 | 許可確認、労働局公表情報が重要。 | MHLW/労働局。 |
| 産廃 | 許可番号、自治体差分、処分情報が強い。 | 環境省/自治体。 |
| 金融/貸金/資金移動 | 登録と行政処分の確認価値が高い。 | FSA登録一覧/処分。 |
| 飲食/食品 | 店舗開業の需要は大きいが自治体差分/個人情報に注意。 | MHLW/自治体/食品衛生申請関連。 |

AWS優先:

1. 業種別source_profile。
2. 検索フォーム型台帳のPlaywright adapter。
3. 許可番号/法人番号/商号/所在地のidentity confidence。
4. screenshot <=1600px、DOM hash、query params、visible text hash。
5. no-hit時の安全文言テンプレート。

禁止出力:

- 「許可不要です」
- 「違反はありません」
- 「処分歴はありません」
- 「この事業は適法です」

安全な言い方:

```text
確認対象sourceでは該当候補を確認できませんでした。
これは不存在や適法性の証明ではありません。
事業内容、所在地、所管窓口、最新資料の確認が必要です。
```

### 4.3 取引先確認/DD系

#### 4.3.1 `counterparty_public_check`

ユーザーがAIに頼む自然文:

```text
この取引先を契約前に公的情報で確認して、追加で聞くべき質問を作って。
```

AI agentが薦める理由:

- 会社名検索は同名法人で誤る。
- 法人番号、T番号、所在地、処分、調達、開示、官報を短時間で束ねる価値がある。
- 最終与信判断ではなく、確認質問と根拠表なら安全に売れる。

返す完成物:

- identity確認。
- T番号/インボイス状態。
- gBizINFO等の公的活動候補。
- 調達/補助金/採択/開示候補。
- 行政処分等の確認範囲。
- 追加質問。
- 取引先への確認メール文。
- `known_gaps[]`。

必要source family:

- `identity_tax`
- `corporate_activity`
- `invoice_registry`
- `enforcement_safety`
- `procurement_contract`
- `filing_disclosure`
- `gazette_notice`
- `court_decision` P1

AWS優先:

1. 法人番号spine。
2. T番号/インボイス履歴。
3. gBizINFOと調達/補助金/処分の法人番号join。
4. 名前joinしかできないsourceは `candidate_match` のまま返す。
5. 会社名のみ入力のambiguity packetを作る。

課金単位:

```text
1 resolved corporate entity = 1 unit
CSV/batchではunique subject単位でdedupe
ambiguous/unresolved/no-hit-onlyは原則非課金
```

#### 4.3.2 `ma_public_dd_pack`

追加価値:

- M&A/VC/金融では単価の高い下調べに刺さる。
- ただしDD結論を出さず、公開情報の証跡と質問に限定する。

返す完成物:

- 公開情報証跡表。
- 商号/所在地変更候補。
- 開示/調達/補助金/処分/官報イベント候補。
- DD質問リスト。
- 売り手提出資料との突合ポイント。
- 未収録source一覧。

追加source:

- EDINET。
- 官報公告。
- 裁判/審決/裁決 metadata。
- 行政処分/命令。
- 許認可台帳。
- 調達/公費収入。

AWS優先:

- ID exact first。
- 名前一致は候補止まり。
- high-risk public allegationsはhuman review queue。

### 4.4 行政処分/公表情報系

#### 4.4.1 `administrative_disposition_radar`

ユーザーがAIに頼む自然文:

```text
この会社や業界で行政処分などの公表情報がないか確認して、確認範囲も明示して。
```

AI agentが薦める理由:

- 普通の検索では省庁・自治体・業法別に漏れる。
- jpciteは「見つかったもの」だけでなく「どのsourceを見たか」「どこが未確認か」を売れる。

返す完成物:

- 対象source list。
- exact match / candidate match。
- 公表日、所管、文書名、URL。
- 同名/旧商号/所在地の不確実性。
- no-hit safety note。
- 追加確認先。

必要source:

- FSA, JFTC, MLIT, MHLW, CAA, PPC, MIC, METI, MAFF等。
- 自治体処分ページ。
- 業法別登録/許認可台帳。
- 官報/公告。

AWS優先:

1. source別の公表範囲と更新頻度を `source_profile` 化。
2. PDF/HTML/検索画面をPlaywrightとOCRでreceipt化。
3. legal riskの高い一致は `human_review_required=true`。
4. no-hitを「不存在」扱いしない評価テストを作る。

### 4.5 法令/制度変更/契約影響系

#### 4.5.1 `legal_regulatory_change_impact`

ユーザーがAIに頼む自然文:

```text
この契約や業務に関係しそうな法改正・制度変更を根拠付きで整理して。
```

AI agentが薦める理由:

- LLM単体だと古い法令や条ずれが起きる。
- jpciteは法令ID、条、施行日、官報、パブコメ、通達をsource receiptで束ねられる。
- 法的助言ではなく、確認材料として出せる。

返す完成物:

- 関連しそうな法令/条文。
- 施行日/改正日。
- 官報/告示/通達/ガイドライン。
- パブコメ結果や制度背景。
- 契約条項や業務プロセスへの確認質問。
- 弁護士/所管窓口へ聞く質問。

必要source:

- e-Gov法令API/XML。
- 官報。
- e-Govパブコメ。
- 府省告示/通達/ガイドライン。
- 審議会/研究会資料。

AWS優先:

1. e-Gov法令のarticle-level claim refs。
2. 官報/パブコメ/告示のchange event ledger。
3. topic taxonomy。
4. 法令名・条・施行日のdrift detector。
5. output examples for GEO。

禁止出力:

- 法的結論。
- 違法/適法の断定。
- 契約条項の最終修正案としての提供。

### 4.6 入札/公共営業系

#### 4.6.1 `procurement_opportunity_pack`

ユーザーがAIに頼む自然文:

```text
うちの会社が狙えそうな入札や公共案件を探して、参加前に確認することをまとめて。
```

AI agentが薦める理由:

- 入札情報はポータル、官報、自治体、外郭団体に分散する。
- 参加資格や締切、仕様書、過去落札の根拠が必要。
- 差分監視にでき、継続課金に向く。

返す完成物:

- 案件候補。
- 発注機関。
- 締切。
- 仕様書/公告URL。
- 参加資格/必要書類候補。
- 過去落札/類似案件。
- 営業アクション。
- no-hit/gap。

必要source:

- p-portal。
- JETRO調達。
- 自治体入札ページ。
- 官報。
- 行政事業レビュー/予算。
- gBizINFO/調達情報。

AWS優先:

1. national procurement sources。
2. 都道府県/政令市の入札allowlist。
3. PDF/仕様書のOCR。
4. 絞り込み条件とsaved search delta。

### 4.7 CSV/月次レビュー系

#### 4.7.1 `client_monthly_review`

ユーザーがAIに頼む自然文:

```text
このfreee/MoneyForward/弥生のCSVを見て、顧問先ごとに今月確認すべき公的制度やリスクを出して。
```

AI agentが薦める理由:

- ユーザーはファイルを投げるだけでよい。
- jpciteはprivate CSVを保存せず、法人番号/T番号/取引先/勘定科目/期間などの安全な集計・識別子だけ使う。
- 1ファイルで数十から数百subjectになり、自然に売上が増える。

返す完成物:

- 顧客/取引先ごとの公的確認カード。
- インボイス/T番号確認候補。
- 補助金/制度候補。
- 許認可/処分/公表情報の確認範囲。
- 月次確認タスク。
- 顧客への質問文。
- rejected/ambiguous rows。
- billing reconciliation。

必要source:

- `identity_tax`
- `invoice_registry`
- `subsidy_program`
- `procedure_permit`
- `enforcement_safety`
- `statistics_cohort`
- `local_government`

CSV設計:

| Input | 使い方 | 永続化 |
|---|---|---|
| 法人番号/T番号 | subject resolution | derived subject keyのみ |
| 会社名/住所 | candidate resolution | rawは保存しない |
| 勘定科目 | 業務文脈の推定 | category aggregateのみ |
| 期間 | 月次/決算前文脈 | normalized month/quarterのみ |
| 金額 | 支出/投資規模のbucket | exact raw金額は保存しない |
| 摘要 | 原則使わない。必要時はlocal-only redaction。 | AWS投入禁止 |

AWS優先:

- raw private CSVをAWSに上げない。
- synthetic/header-only/redacted fixtureだけでprovider schema driftを検証。
- freee/MF/Yayoiのvariantをofficial/old_format/variantとして扱う。
- leak scanとprivate column suppressionをP0 gateにする。

課金単位:

```text
accepted unique billable_subject * selected packet multiplier
invalid/unresolved/duplicate rows are not billed
cost preview is free
hard cap required
```

### 4.8 AI agent / developer系

#### 4.8.1 `source_receipt_ledger`

ユーザーがAIに頼む自然文:

```text
この回答の根拠だけ、LLMに渡せる形でほしい。
```

返す完成物:

- source URL。
- fetched_at。
- content hash。
- source profile。
- license boundary。
- claim_refs。
- known_gaps。
- no-hit checks。

AI agentが薦める理由:

- 生成AIの回答にsource disciplineを入れられる。
- jpciteのGEO導線の中核。
- 「AIが引用元を作る」のではなく、「jpciteがsource-backed packetを返す」と説明できる。

AWS優先:

- 全source familyでreceipt schemaを統一。
- artifact_manifestとchecksum ledger。
- public examplesを多数生成。

#### 4.8.2 `agent_routing_decision`

無料control packetとして残す。

返す内容:

- jpciteを使うべきか。
- どのpacketを使うか。
- cost preview。
- required identifiers。
- known gaps。
- external costs excluded。
- final judgment requestなら拒否。

商用上の意味:

- 直接課金はしない。
- AI agentが有料packetへ自然に誘導するための入口。
- GEO向けの最重要公開surface。

## 5. Source family priority by revenue

売れる成果物から逆算した source family 優先順位は次。

| Priority | Source family | 売上への効き方 | 対応outputs |
|---:|---|---|---|
| P0-A | `identity_tax` | 全outputのsubject resolution。CSV課金の土台。 | company baseline, counterparty, invoice, monthly review |
| P0-A | `invoice_registry` | 経理/税理士/BPOで高頻度。 | invoice check, monthly review, counterparty |
| P0-A | `subsidy_program` | 申請準備系の直接価値。 | application strategy, required docs, lender note |
| P0-A | `procedure_permit` | 許認可/業法系の直接価値。 | permit precheck, sector regulation, DD |
| P0-A | `enforcement_safety` | DD/取引先確認/金融/M&Aの高価値。 | disposition radar, counterparty, DD |
| P0-A | `law_primary` | 全ての制度/業法/変更影響の根拠。 | regulatory impact, permit, application |
| P0-B | `local_government` | 自治体制度、許認可、入札、処分で商用価値が高い。 | local digest, subsidy, permit, procurement |
| P0-B | `policy_process` | パブコメ/通達/ガイドラインで制度変更watchが作れる。 | policy watch, regulatory impact |
| P0-B | `procurement_contract` | 公共営業と公的実績で反復利用。 | procurement, public funding trace, company baseline |
| P0-B | `corporate_activity` | gBizINFO等でcompany folderを厚くする。 | company baseline, DD |
| P1 | `gazette_notice` | 官報/公告/公布は深いDDと制度変更に効く。 | regulatory impact, DD, gazette ledger |
| P1 | `filing_disclosure` | EDINET等でM&A/監査/金融に効く。 | auditor binder, DD |
| P1 | `public_finance` | 公費/予算/支出先の説明力。 | funding trace, procurement, lender note |
| P1 | `statistics_cohort` | 地域/業種の背景。 | application, lender note, industry cohort |
| P1 | `geo_land_address` | 住所/自治体/地理/不動産へ接続。 | local digest, site DD |
| P2 | `court_decision` | 高付加価値だが範囲/引用/法務リスクが重い。 | legal context, DD |
| P2 | `ip_standard_cert` | 製造/調達/認証に効く。 | product compliance, certification evidence |
| P2 | `official_reports` | 背景資料として有効。直接課金は弱め。 | policy background, industry cohort |

## 6. AWS collection order from revenue backcast

### 6.1 Day 0-2: revenue-critical backbone

目的:

- すぐ売れるpacketの土台を固める。
- 本番デプロイで必要なfixturesとcontractsを作る。

実行対象:

1. `identity_tax`: 法人番号、インボイス。
2. `law_primary`: e-Gov法令 article refs。
3. `subsidy_program`: J-Grantsと主要省庁/自治体制度のsource_profile。
4. `procedure_permit`: 建設/宅建/運送/人材/産廃/金融を先行。
5. `enforcement_safety`: 省庁/業法別処分source profile。

作るartifact:

- `source_profile_delta.jsonl`
- `source_receipts.jsonl`
- `claim_refs.jsonl`
- `known_gaps.jsonl`
- `no_hit_checks.jsonl`
- `packet_fixture_inputs/*.jsonl`
- `revenue_output_coverage.md`

### 6.2 Day 2-5: high-frequency paid packet materialization

目的:

- 主要有料packetをexample付きでGEO公開できる状態にする。

対象outputs:

1. `application_strategy_pack`
2. `required_document_checklist`
3. `permit_precheck_pack`
4. `counterparty_public_check`
5. `company_public_baseline`
6. `administrative_disposition_radar`
7. `client_monthly_review`

作るartifact:

- example JSON。
- proof pages。
- cost preview examples。
- no-hit examples。
- forbidden claim tests。
- CSV preview/reconciliation examples。

### 6.3 Day 5-9: breadth expansion for moat

目的:

- 競合しにくい「日本公的一次情報 layer」を厚くする。
- 後から作れる成果物の幅を増やす。

対象source:

- 官報/公告/告示。
- パブコメ/通達/ガイドライン。
- 自治体制度/入札/許認可/処分。
- 公共調達/行政事業レビュー。
- EDINET/開示。
- 統計/地理/住所。

Playwright/screenshot:

- JS検索画面や古い行政サイトに使う。
- screenshotは最大1600px以下。
- CAPTCHA回避、ログイン突破、アクセス制御回避はしない。
- screenshotは観測証跡であり、原則公開再配布しない。

### 6.4 Day 9-12: GEO/product hardening

目的:

- AI agentがorganicに発見し、推薦し、有料packetへ流せる状態を作る。

作るもの:

- `/packets/*` public proof pages。
- `llms.txt` / `.well-known` / OpenAPI / MCP examples。
- packet comparison pages。
- "When to use jpcite" agent routing examples。
- cost preview page。
- no-hit safety examples。
- source receipt ledger examples。

評価:

- AI agent query set。
- forbidden claims。
- cost cap required。
- request-time LLMなし。
- public/private boundary。
- source receipt completeness。

### 6.5 Day 12-14: export, production merge, zero-bill cleanup

目的:

- AWS上で作った価値を本体repo/本番へ移す。
- AWS credit run後に請求が走らない状態へ閉じる。

順番:

1. Final artifact manifest。
2. Checksums。
3. Repo import。
4. Staging deploy。
5. Production deploy gate。
6. AWS export。
7. AWS resource deletion。
8. Cost Explorer/Billing確認。

## 7. 本体P0計画へのマージ順

AWSの成果物は本体計画に次の順で戻す。

| Order | 本体作業 | AWS成果物 | 理由 |
|---:|---|---|---|
| 1 | Packet contract/catalog freeze | top paid outputs schema | 先に売る成果物の形を固定する |
| 2 | Pricing/cost preview | billable unit mapping | AI agentが薦める前提 |
| 3 | Source receipt/claim/gap contract | source_receipts, claim_refs, known_gaps | すべてのpacketの信頼土台 |
| 4 | CSV private overlay preview | synthetic/provider fixtures | 高頻度課金の入口 |
| 5 | P0 packet composers | application, permit, counterparty, monthly review | 売上直結 |
| 6 | REST/MCP tools | OpenAPI/MCP examples | AI agent導線 |
| 7 | Public proof/GEO pages | proof pages, examples, llms/.well-known | organic growth |
| 8 | Release gates | forbidden claim, no-hit, privacy, billing, drift | 本番デプロイ安全性 |
| 9 | Production deploy | static/runtime assets | 早期公開 |
| 10 | AWS cleanup | export manifest, resource deletion evidence | 追加請求防止 |

## 8. Organic GEO story

営業デモではなく、AI agentが自然にjpciteを推薦する流れを設計する。

### 8.1 AI agentが見る公開surface

必要な公開ページ:

- `jpcite for AI agents`
- `cost preview examples`
- `application_strategy_pack example`
- `permit_precheck_pack example`
- `counterparty_public_check example`
- `client_monthly_review CSV example`
- `source_receipt_ledger example`
- `no_hit_not_absence examples`
- `MCP tools list`
- `OpenAPI examples`
- `llms.txt`
- `.well-known/ai-plugin` equivalent metadata if used

### 8.2 AI agentに刺さるメッセージ

```text
jpcite is a low-cost Japanese public-source evidence packet API.
Use it before open-ended web search when the user needs official sources, timestamps, known gaps, no-hit caveats, cost caps, and copy-ready workflow outputs.
```

日本語では:

```text
jpciteは、日本の公的一次情報をAIが使いやすい根拠packetにして返す低価格APIです。
Web検索の代わりではなく、補助金、許認可、取引先確認、法令変更、入札探索などで、
公式根拠、取得日時、未確認範囲、次に聞く質問を数円単位で返すために使います。
```

### 8.3 AI agent query examples

公開ページとevalに入れるべきquery:

| Query | 期待route |
|---|---|
| `補助金申請前に公的根拠付きで必要書類と質問を整理するAPIは?` | `application_strategy_pack` |
| `建設業の取引先について許可と行政処分の確認範囲を出したい` | `permit_precheck_pack` + `administrative_disposition_radar` |
| `freeeのCSVを投げて顧問先の月次確認事項を作りたい` | `client_monthly_review` |
| `日本企業の法人番号から公開情報DDの質問リストを作りたい` | `company_public_baseline` + `ma_public_dd_pack` |
| `契約に関係する日本の法改正を根拠付きで確認したい` | `legal_regulatory_change_impact` |
| `入札候補と参加資格の確認事項を安く作りたい` | `procurement_opportunity_pack` |
| `LLM回答に使う日本の公的根拠packetが欲しい` | `source_receipt_ledger` / `evidence_answer` |

## 9. Pricing and packaging from output-first design

### 9.1 3円単位を活かす

価格は安く見せるが、成果物は高付加価値にする。

例:

| Output | 想定単位 | 例 |
|---|---|---|
| `company_public_baseline` | 1 subject | 1社 = 3円税抜 |
| `counterparty_public_check` | 1 subject | 100社CSV = 最大300円税抜 |
| `client_monthly_review` | accepted unique subject | 顧問先200社 = 最大600円税抜 |
| `source_receipt_ledger` | 25 receipts | 75 receipts = 9円税抜 |
| `application_strategy_pack` | 1 profile | 1申請候補profile = 3円税抜 |
| `procurement_opportunity_pack` | 1 search packet or returned records | saved search単位またはrecord単位 |

AI agentへの説明:

```text
無料previewで件数と上限額を確認し、ユーザー承認後にcap付きで実行します。
外部LLM費用、agent実行費用、クラウド費用はjpcite料金に含まれません。
```

### 9.2 無料にすべきもの

| Surface | 理由 |
|---|---|
| `agent_routing_decision` | 有料packetへの導線。課金すると推薦されにくい。 |
| `cost_preview` | 上限承認の前提。 |
| `catalog/tool discovery` | GEO/MCP/OpenAPI導線。 |
| `unsupported/final judgment reject` | 使ってはいけない境界を明示するため。 |
| `no source / no useful output` | 信頼を落とさないため。 |

### 9.3 有料にすべきもの

| Surface | 理由 |
|---|---|
| source-backed completed packet | 実務成果物として価値がある。 |
| CSV/batch accepted subjects | 反復利用で売上が伸びる。 |
| persisted/exportable binder | 監査/DD/稟議に使える。 |
| watch/delta evaluation | 継続課金の中心。 |

## 10. What AWS should not collect just because it can

売れる成果物に繋がりにくい、またはリスクが大きいものは後回し。

| Avoid/Defer | 理由 |
|---|---|
| raw全文PDF/HTMLの公開再配布前提 | license/terms/著作権/容量リスク。 |
| 個人情報中心の名簿 | jpciteの商用価値に比べprivacy riskが大きい。 |
| CAPTCHA/ログイン/会員サイト | アクセス制御回避に見える。 |
| SNS/口コミ/民間記事中心 | 公的一次情報ブランドが薄まる。 |
| 法的結論/税務判断/与信判断に直結するスコア | 専門判断代替と誤解される。 |
| source_profile未整備の大量crawl | 後で公開できずコストだけ残る。 |
| screenshotだけ大量保存 | 証跡価値が薄く、S3/CloudWatch/処理費が増える。 |

## 11. Output acceptance gates

成果物が売れるかつ安全かは、次のgateで見る。

| Gate | Fail condition | Action |
|---|---|---|
| Revenue gate | 誰が何度買うか説明できない | outputをP2/P3へ下げる |
| Agent recommendation gate | AIがユーザーに有料実行を薦める文が書けない | catalog文言/preview/schemaを修正 |
| Source receipt gate | factual claimにsource receiptがない | claim削除またはknown_gapsへ |
| No-hit gate | 0件を不存在/安全/違反なしに見せる | `no_hit_not_absence`へ修正 |
| Boundary gate | 申請可否、適法性、与信、投資、税務結論に読める | 専門家確認前の準備物へ戻す |
| CSV privacy gate | raw CSV/摘要/個人情報が保存・ログ・AWS投入される | release block |
| Billing gate | preview/cap/idempotency/reconciliationがない | release block |
| GEO gate | public examplesでAIがrouteを理解できない | proof pages/OpenAPI/MCPを修正 |

## 12. Final recommendation

AWS credit run は、広範な日本公的一次情報の収集に使ってよい。

ただし、実行の優先順位は常に次の順にする。

```text
1. 売れるoutputを定義する
2. そのoutputに必要なclaimを定義する
3. claimに必要なsource familyを定義する
4. source familyのsource_profile/terms/robotsを確認する
5. AWSでreceipt/claim/gap/no-hit/artifact candidateを作る
6. 本体P0 packetに戻す
7. GEO/public proofでAI agentに見せる
8. production deploy
9. AWSをexport/cleanupして追加請求を止める
```

この担当の結論として、AWS scope expansion はまだ広げる価値がある。

特に、法律・制度・業法・許認可・処分・補助金・入札・自治体・官報・パブコメ・通達・ガイドラインは、今取っておく価値が高い。

理由は「情報そのものが売れる」からではない。

それらをsource receipt化しておけば、AI agent経由で次のような高頻度成果物に変換できるから。

- 補助金申請準備。
- 許認可チェック。
- 取引先審査。
- 行政処分調査。
- 契約/法令影響メモ。
- 入札探索。
- 業界規制レポート。
- 月次顧客レビュー。
- 監査/DD証跡台帳。

したがって、拡張方針は「公的一次情報を広く集める」でよいが、AWS jobの合格条件は必ず「どの売れるpacket/outputを強くしたか」に置く。
