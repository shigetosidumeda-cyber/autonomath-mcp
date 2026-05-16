# AWS scope expansion 27/30: packet taxonomy and成果物 catalog

作成日: 2026-05-15  
担当: 拡張深掘り 27/30 / 成果物カタログ・packet taxonomy  
対象: jpcite 本体計画、AWS credit run、GEO-first organic acquisition、MCP/API課金導線  
状態: 計画文書のみ。AWS CLI/API実行、AWSリソース作成、デプロイ、既存コード変更は行わない。  
出力制約: このMarkdownだけを追加する。  

## 0. 結論

jpcite の商品は「検索」ではなく、AIエージェントがエンドユーザーに安く薦められる **公的一次情報ベースの成果物packet** である。

packet taxonomy は次の順で設計する。

1. エンドユーザーがAIに頼む成果物を先に定義する。
2. AIエージェントが「有料packetを買うべき」と説明できる条件を定義する。
3. そのpacketに必要な入力、公的一次情報source family、アルゴリズム、価格、無料preview、known gapsを定義する。
4. 同じ定義から MCP tool、OpenAPI route、GEO proof page、pricing page、`llms.txt` の説明を生成する。
5. AWS credit run は、このpacket catalogを満たすためのsource receipt、fixture、proof example、eval dataを作る。

最初に商品化すべきP0は、次の15 packetである。

| Priority | Packet | 主要な売上理由 |
|---:|---|---|
| P0-01 | `agent_routing_decision` | AIがjpciteを使うべきかを無料で判断する入口。 |
| P0-02 | `cost_preview_quote` | 課金前に価格、cap、必要入力、known gapsを示す。 |
| P0-03 | `source_receipt_ledger` | 回答・監査・DDに再利用できる証跡台帳。 |
| P0-04 | `evidence_answer` | 一般質問に対する根拠付き素材packet。 |
| P0-05 | `company_public_baseline` | 法人番号から公的ベースラインを作る高頻度packet。 |
| P0-06 | `invoice_vendor_public_check` | 経理・税理士・BPOが繰り返し使える安価packet。 |
| P0-07 | `counterparty_public_dd_packet` | 取引先確認の高頻度・高説明力packet。 |
| P0-08 | `vendor_public_risk_attention_packet` | リスク断定ではなく公的注意情報を整理するpacket。 |
| P0-09 | `administrative_disposition_radar_packet` | 行政処分・公表情報の確認範囲を可視化するpacket。 |
| P0-10 | `grant_candidate_shortlist_packet` | 補助金・助成金候補を公的根拠付きで短縮するpacket。 |
| P0-11 | `application_readiness_checklist_packet` | 申請前の必要書類・不足入力・質問表を作るpacket。 |
| P0-12 | `permit_scope_checklist_packet` | 許認可・業法の確認事項を三値論理で返すpacket。 |
| P0-13 | `regulation_change_impact_packet` | 法令・制度差分から影響候補と確認事項を返すpacket。 |
| P0-14 | `csv_monthly_public_review_packet` | 会計CSV由来の派生factsと公的情報を重ねる月次packet。 |
| P0-15 | `tax_labor_event_radar_packet` | 税・社保・労務イベント候補を公的カレンダーで返すpacket。 |

P1は業界別・業務別に広げて単価と継続性を上げる。P2は地理、標準、製品規制、裁判例、海外参入など高付加価値だがsource整備が重い領域に置く。

## 1. Taxonomyの非交渉ルール

| Area | Rule |
|---|---|
| GEO-first | packet説明は人間LPだけでなく、AIエージェントが推薦文として使える形で公開する。 |
| Catalog SOT | packet catalogを唯一の正本にし、MCP/OpenAPI/proof/pricing/llmsを生成またはdrift testする。 |
| Request-time LLM | 有料packetの主張生成にrequest-time LLMを使わない。`request_time_llm_call_performed=false` を返す。 |
| Evidence contract | すべての有料packetは `source_receipts[]`, `claim_refs[]`, `known_gaps[]`, `billing_metadata`, `human_review_required`, `_disclaimer` を持つ。 |
| No-hit | no-hitは常に `no_hit_not_absence`。不存在、安全、適格、問題なしの証明にしない。 |
| Professional fence | 法務・税務・会計・投資・与信・安全の最終判断をしない。候補、証跡、確認事項、質問表に留める。 |
| CSV privacy | raw CSVは保存、ログ、echo、AWS投入しない。保存可能なのは集計・派生facts・safe identifierのみ。 |
| Pricing | 正本は3円税抜/unit。packet価格はunit数の表示であり、別の価格ロジックを持たない。 |
| Free preview | 無料previewは必ず課金前に使える。full source_receiptsや高価値hitを漏らさない。 |
| Cap | 有料実行はAPI key、cap、idempotency keyを要求する。 |

## 2. Source family正規化

packet定義では、個別サイト名ではなくsource familyを使う。AWS側の収集計画はsource family単位でsource_profile、receipt schema、terms/robots、drift testを持つ。

| Source family | 内容 | 代表例 | 主なpacket |
|---|---|---|---|
| `identity_tax` | 法人・事業者の同定情報 | 国税庁法人番号、商号、所在地、変更履歴 | `company_public_baseline`, `counterparty_public_dd_packet` |
| `invoice_registry` | 適格請求書発行事業者情報 | インボイス公表サイト/API | `invoice_vendor_public_check` |
| `corporate_activity` | 事業者活動の公的情報 | gBizINFO、補助金採択、表彰、届出系公開情報 | `company_public_baseline`, `vendor_public_risk_attention_packet` |
| `filing_disclosure` | 開示・提出書類 | EDINET、有価証券報告書、公告系 | `ma_public_dd_pack`, `auditor_evidence_binder` |
| `law_primary` | 法律・政省令・条文 | e-Gov法令、法令XML、一括DL、改正履歴 | `permit_scope_checklist_packet`, `regulation_change_impact_packet` |
| `policy_process` | 告示、通達、ガイドライン、FAQ、パブコメ | e-Govパブコメ、省庁ページ、審議会資料 | `regulation_change_impact_packet`, `sector_regulation_brief` |
| `gazette_notice` | 官報、公告、公示 | 官報、公告、破産/合併/許認可公告等 | `public_integrity_context`, `ma_public_dd_pack` |
| `procedure_permit` | 許認可、登録、届出、処分、標準処理期間 | 国交省、厚労省、金融庁、自治体台帳 | `permit_scope_checklist_packet`, `construction_license_scope_packet` |
| `enforcement_safety` | 行政処分、注意喚起、リコール、公表 | 消費者庁、公取委、金融庁、国交省、PPC、NITE | `administrative_disposition_radar_packet` |
| `subsidy_program` | 補助金、助成金、制度公募 | J-Grants、ミラサポplus、厚労省助成金、自治体制度 | `grant_candidate_shortlist_packet` |
| `procurement_contract` | 入札、落札、契約、公共営業 | 調達ポータル、自治体入札、JETRO、官報 | `procurement_opportunity_radar` |
| `public_finance` | 予算、行政事業レビュー、支出 | 行政事業レビュー、予算資料、自治体決算 | `public_funding_traceback` |
| `local_government` | 自治体制度、条例、窓口、地域手続 | 自治体サイト、標準オープンデータセット | `local_regulation_digest`, `franchise_location_permit_pack` |
| `statistics_geo` | 統計、地域、地理、ハザード | e-Stat、国土地理院、国土数値情報、不動産情報ライブラリ | `site_due_diligence_pack`, `industry_cohort_context` |
| `courts_disputes` | 裁判例、審決、裁決、不服審査 | 裁判所、公取委審決、中労委、行政不服審査DB | `case_law_context_pack` |
| `standards_certifications` | 標準、認証、技適、製品規制 | JISC、技適、PSE/PSC、PMDA、JAS/HACCP | `product_compliance_brief` |
| `tax_labor_social` | 税、社保、労務、最低賃金、雇用助成 | 国税庁、eLTAX、日本年金機構、厚労省 | `tax_labor_event_radar_packet` |
| `csv_private_derived` | raw CSVから生成した安全な派生facts | freee/MF/Yayoi/generic CSVの集計・勘定科目・取引先候補 | `csv_monthly_public_review_packet` |
| `official_forms` | 様式、添付書類、申請手引き | 申請様式PDF、FAQ、手引き、記載例 | `application_readiness_checklist_packet` |
| `international_trade_fdi` | 輸出入、海外企業参入、外為、JETRO | JETRO、経産省、安全保障貿易管理 | `trade_control_source_navigation_packet` |

## 3. Algorithm primitives

packetはLLM自由生成ではなく、以下のアルゴリズムprimitiveを組み合わせて作る。

| Primitive | 役割 | 出力 |
|---|---|---|
| `entity_resolution` | 法人番号、T番号、会社名、所在地、CSV取引先名を同定する。 | `subject_candidates[]`, `match_confidence`, `disambiguation_questions[]` |
| `source_profile_match` | 対象packetに必要なsource familyと公式source_profileを選ぶ。 | `selected_sources[]`, `excluded_sources[]` |
| `receipt_builder` | 取得URL、取得日時、checksum、screenshot/PDF/DOM/OCR由来をreceipt化する。 | `source_receipts[]` |
| `claim_ref_builder` | packet内の各主張をsource_receiptの該当範囲へ結びつける。 | `claim_refs[]` |
| `no_hit_ledger` | 検索したが該当がなかった範囲を記録し、断定を防ぐ。 | `no_hit_checks[]`, `no_hit_policy` |
| `coverage_gap_analyzer` | 入力不足、source未対応、地域未対応、schema driftを整理する。 | `known_gaps[]`, `missing_inputs[]` |
| `rule_graph_triage` | 法令・許認可・制度条件を決定表/三値論理で評価する。 | `condition_results[]`, `needs_review[]` |
| `eligibility_candidate_scoring` | 補助金/制度候補を「該当断定」ではなく候補順位で並べる。 | `ranked_candidates[]`, `score_components[]` |
| `reg_change_diff` | 法令XML、告示、通達、パブコメ、官報の差分を正規化する。 | `change_events[]`, `impact_candidates[]` |
| `public_evidence_attention_score` | 与信・安全断定ではなく、公的情報上の注意度を出す。 | `attention_score`, `evidence_quality_score`, `coverage_gap_score` |
| `csv_derived_fact_overlay` | raw CSVを保存せず、期間、金額帯、勘定科目、取引先候補などの派生factsを作る。 | `derived_facts[]`, `suppressed_fields[]` |
| `geo_join` | 所在地・自治体・区域・統計・ハザード・条例を結合する。 | `location_context[]` |
| `playwright_capture_receipt` | fetch困難な公式ページをDOM/PDF/HAR/1600px以下screenshotで証跡化する。 | `capture_receipts[]` |

## 4. Price tier正本

packetの表示価格は、3円税抜/unitの見せ方である。

| Tier | Units | 税抜 | 税込 | 使いどころ |
|---|---:|---:|---:|---|
| Free preview | 0 | 0円 | 0円 | route、価格見積、必要入力、known gaps preview |
| Nano receipt | 10 | 30円 | 33円 | 単一source receipt、引用anchor |
| Micro check | 30 | 90円 | 99円 | 1件の正確lookup |
| Starter packet | 100 | 300円 | 330円 | 1対象のbaseline、小さなchecklist |
| Standard packet | 300 | 900円 | 990円 | 複数sourceの1成果物 |
| Professional packet | 1,000 | 3,000円 | 3,300円 | 許認可、補助金、DD、法令変更 |
| Heavy packet | 3,000 | 9,000円 | 9,900円 | CSV/portfolio/広域調査 |
| Custom capped run | user cap | cap連動 | cap連動 | 大量MCP/API/batch。cap必須 |

## 5. P0 packet taxonomy

### P0-01 `agent_routing_decision`

| Field | Definition |
|---|---|
| End-user output | AIエージェントが「jpciteを使うべきか」を説明するための無料route判断。 |
| Inputs | `user_task`, `jurisdiction=JP`, `desired_output`, 任意で `subject_type`, `industry`, `has_csv`, `location` |
| Required source families | `catalog`, `pricing`, `source_profile_registry` |
| Algorithm | `intent_classifier` + `source_profile_match` + `coverage_gap_analyzer`。実source検索はしない。 |
| Price | Free preview / 0 units |
| Preview | packet候補、必要入力、価格帯、使ってはいけない場面、agent推薦文。 |
| Known gaps | task曖昧、対象国が日本でない、最終専門判断を求めている、必要ID不足。 |
| GEO proof page | `/proof/packets/agent-routing-decision` |
| MCP tool | `jpcite_route` |

### P0-02 `cost_preview_quote`

| Field | Definition |
|---|---|
| End-user output | 課金前に、packet価格、cap、想定unit、必要入力、no-charge条件を示す見積。 |
| Inputs | `packet_type`, `subject_count`, `source_scope`, `batch_size`, 任意で `csv_profile_summary` |
| Required source families | `catalog`, `pricing`, `source_profile_registry` |
| Algorithm | `unit_estimator` + `cap_validator` + `known_gap_preview` + `idempotency_plan` |
| Price | Free preview / 0 units |
| Preview | 税抜/税込価格、max cap、free preview範囲、paid実行条件、外部費用別の明記。 |
| Known gaps | unit見積不能、CSV列不明、対象数不明、source familyが未整備。 |
| GEO proof page | `/proof/packets/cost-preview-quote` |
| MCP tool | `jpcite_preview_cost` |

### P0-03 `source_receipt_ledger`

| Field | Definition |
|---|---|
| End-user output | 回答・稟議・監査・DDに使えるsource receipt台帳。 |
| Inputs | `receipt_ids[]` または `packet_run_id` または `source_query` |
| Required source families | 任意の有効source family。ただしreceipt schema対応済みのみ。 |
| Algorithm | `receipt_builder` + `claim_ref_builder` + `checksum_verifier` + `license_boundary_check` |
| Price | Nano receiptからStarter packet / 10-100 units |
| Preview | 何件のreceiptが返るか、含まれるsource family、証跡種別、未対応source。 |
| Known gaps | source未対応、スクショのみでDOM claim位置なし、terms未確認、checksum不一致。 |
| GEO proof page | `/proof/packets/source-receipt-ledger` |
| MCP tool | `jpcite_source_receipts` |

### P0-04 `evidence_answer`

| Field | Definition |
|---|---|
| End-user output | 日本の公的一次情報に基づく短い根拠付き回答素材。最終判断ではない。 |
| Inputs | `question`, 任意で `subject`, `industry`, `location`, `time_range`, `source_scope` |
| Required source families | `law_primary`, `identity_tax`, `subsidy_program`, `procedure_permit`, `enforcement_safety` からrouteで選択 |
| Algorithm | `intent_classifier` + `source_profile_match` + `receipt_builder` + `claim_ref_builder` + `coverage_gap_analyzer` |
| Price | StarterからStandard / 100-300 units |
| Preview | 使うsource family、返せる主張種別、禁止断定、価格。 |
| Known gaps | 質問が専門判断、sourceが未収集、期間指定不足、地域不足、対象同定不足。 |
| GEO proof page | `/proof/packets/evidence-answer` |
| MCP tool | `jpcite_evidence_answer` |

### P0-05 `company_public_baseline`

| Field | Definition |
|---|---|
| End-user output | 法人番号等から会社の公的ベースライン、変更履歴、主要公的リンクを作る。 |
| Inputs | `corporate_number` または `company_name` + `address_hint`; 任意で `t_number` |
| Required source families | `identity_tax`, `invoice_registry`, `corporate_activity`, `filing_disclosure` |
| Algorithm | `entity_resolution` + `receipt_builder` + `claim_ref_builder` + `no_hit_ledger` |
| Price | Starter / 100 units / 330円税込 |
| Preview | 同定候補、必要ID、取得source、EDINET/gBizINFO有無の確認範囲。 |
| Known gaps | 同名法人複数、所在地不一致、非上場で開示sourceなし、古い商号変更。 |
| GEO proof page | `/proof/packets/company-public-baseline` |
| MCP tool | `jpcite_company_baseline` |

### P0-06 `invoice_vendor_public_check`

| Field | Definition |
|---|---|
| End-user output | T番号/法人番号/会社名からインボイスと法人情報の確認メモを返す。 |
| Inputs | `t_number` または `corporate_number` または `vendor_name` + `address_hint` |
| Required source families | `invoice_registry`, `identity_tax` |
| Algorithm | `entity_resolution` + `registry_status_lookup` + `receipt_builder` + `no_hit_ledger` |
| Price | Starter / 100 units / 330円税込。単独T番号だけならMicro checkも可能。 |
| Preview | 確認できる項目、同定に必要な情報、no-hitの限界。 |
| Known gaps | T番号未入力、法人/個人事業主の同定不能、登録日/失効日の解釈要確認。 |
| GEO proof page | `/proof/packets/invoice-vendor-public-check` |
| MCP tool | `jpcite_invoice_vendor_check` |

### P0-07 `counterparty_public_dd_packet`

| Field | Definition |
|---|---|
| End-user output | 取引先について、公的source上の基本情報、登録、開示、処分、調達等を整理するDD lite。 |
| Inputs | `corporate_number` 推奨。代替で `company_name`, `address_hint`, `industry_hint` |
| Required source families | `identity_tax`, `invoice_registry`, `corporate_activity`, `filing_disclosure`, `enforcement_safety`, `procedure_permit`, `procurement_contract`, `gazette_notice` |
| Algorithm | `entity_resolution` + `source_profile_match` + `receipt_builder` + `no_hit_ledger` + `coverage_gap_analyzer` |
| Price | Standard / 300 units / 990円税込 |
| Preview | 確認source一覧、同定confidence、処分sourceの確認範囲、価格、注意文。 |
| Known gaps | 業種不明で許認可source未選択、自治体source未対応、同名法人、非公開情報は扱わない。 |
| GEO proof page | `/proof/packets/counterparty-public-dd` |
| MCP tool | `jpcite_counterparty_dd` |

### P0-08 `vendor_public_risk_attention_packet`

| Field | Definition |
|---|---|
| End-user output | 取引先の「公的情報上の注意点」を整理する。信用・安全の断定はしない。 |
| Inputs | `corporate_number`, 任意で `industry_hint`, `permit_type`, `region` |
| Required source families | `identity_tax`, `enforcement_safety`, `procedure_permit`, `filing_disclosure`, `courts_disputes`, `gazette_notice` |
| Algorithm | `public_evidence_attention_score` + `evidence_quality_score` + `coverage_gap_score` + `no_hit_ledger` |
| Price | Standard / 300 units / 990円税込 |
| Preview | 注意情報source、riskではなくattentionである説明、未確認領域。 |
| Known gaps | no-hitは安全証明ではない、個人情報/非公開審査不可、裁判例網羅不可、自治体差。 |
| GEO proof page | `/proof/packets/vendor-public-risk-attention` |
| MCP tool | `jpcite_vendor_attention` |

### P0-09 `administrative_disposition_radar_packet`

| Field | Definition |
|---|---|
| End-user output | 行政処分・注意喚起・公表情報のhit/no-hitと確認範囲を返す。 |
| Inputs | `subject` または `industry` または `permit_type`; 任意で `region`, `time_range` |
| Required source families | `enforcement_safety`, `procedure_permit`, `local_government`, `courts_disputes` |
| Algorithm | `source_profile_match` + `entity_resolution` + `no_hit_ledger` + `receipt_builder` |
| Price | Standard / 300 units / 990円税込 |
| Preview | 対象省庁/自治体/source family、期間、名称揺れ条件、known gaps。 |
| Known gaps | source未網羅、掲載終了、PDF画像のみ、同名誤爆、処分と勧告の区別が必要。 |
| GEO proof page | `/proof/packets/administrative-disposition-radar` |
| MCP tool | `jpcite_disposition_radar` |

### P0-10 `grant_candidate_shortlist_packet`

| Field | Definition |
|---|---|
| End-user output | 企業/地域/業種/目的から補助金・助成金候補を根拠付きで短縮する。 |
| Inputs | `business_profile`, `location`, `industry`, `purpose`, 任意で `employee_count`, `revenue_band`, `csv_derived_facts` |
| Required source families | `subsidy_program`, `local_government`, `policy_process`, `law_primary`, `public_finance`, `statistics_geo` |
| Algorithm | `eligibility_candidate_scoring` + `rule_graph_triage` + `coverage_gap_analyzer` + `receipt_builder` |
| Price | Professional / 1,000 units / 3,300円税込 |
| Preview | 候補を出せるsource、必要入力、不足入力、価格、最終採択断定不可の説明。 |
| Known gaps | 公募終了/未開始、自治体未対応、売上/従業員等の入力不足、対象経費の最終判断不可。 |
| GEO proof page | `/proof/packets/grant-candidate-shortlist` |
| MCP tool | `jpcite_grant_shortlist` |

### P0-11 `application_readiness_checklist_packet`

| Field | Definition |
|---|---|
| End-user output | 申請候補ごとに必要書類、不足入力、窓口質問、専門家引継ぎメモを返す。 |
| Inputs | `program_id` または `program_url`; `business_profile`; 任意で `csv_derived_facts` |
| Required source families | `subsidy_program`, `official_forms`, `local_government`, `policy_process`, `law_primary` |
| Algorithm | `document_requirement_extractor` + `rule_graph_triage` + `missing_input_generator` + `claim_ref_builder` |
| Price | StandardからProfessional / 300-1,000 units |
| Preview | 必要になりそうな入力、対象制度、様式/FAQ有無、価格。 |
| Known gaps | 様式がPDF画像、窓口裁量、更新直後、添付書類の最終確認不可。 |
| GEO proof page | `/proof/packets/application-readiness-checklist` |
| MCP tool | `jpcite_application_checklist` |

### P0-12 `permit_scope_checklist_packet`

| Field | Definition |
|---|---|
| End-user output | 業種/地域/行為/規模から、関係しそうな許認可・業法確認事項を返す。 |
| Inputs | `industry`, `activity`, `location`, 任意で `scale`, `facility`, `staffing`, `qualification`, `past_disposition` |
| Required source families | `law_primary`, `procedure_permit`, `policy_process`, `local_government`, `enforcement_safety`, `official_forms` |
| Algorithm | `rule_graph_triage` + `three_valued_logic` + `constraint_check` + `missing_question_generator` |
| Price | Professional / 1,000 units / 3,300円税込 |
| Preview | 必要入力、対象source、最終法務判断不可、地域差、価格。 |
| Known gaps | 地方条例未整備、行為定義曖昧、規模/設備/資格不足、専門家確認必須。 |
| GEO proof page | `/proof/packets/permit-scope-checklist` |
| MCP tool | `jpcite_permit_checklist` |

### P0-13 `regulation_change_impact_packet`

| Field | Definition |
|---|---|
| End-user output | 法令・告示・通達・パブコメ・官報の差分から影響候補、期限候補、確認事項を返す。 |
| Inputs | `topic` または `law_id` または `industry`; 任意で `date_range`, `business_activity` |
| Required source families | `law_primary`, `policy_process`, `gazette_notice`, `procedure_permit` |
| Algorithm | `reg_change_diff` + `topic_classifier` + `impact_candidate_mapper` + `claim_ref_builder` |
| Price | StandardからProfessional / 300-1,000 units |
| Preview | 追えるsource、差分期間、業界mappingの限界、価格。 |
| Known gaps | 告示/通達の網羅不足、施行日解釈、実務影響は断定不可、古いPDF。 |
| GEO proof page | `/proof/packets/regulation-change-impact` |
| MCP tool | `jpcite_reg_change_impact` |

### P0-14 `csv_monthly_public_review_packet`

| Field | Definition |
|---|---|
| End-user output | 会計CSVから派生factsを作り、取引先、公的制度、税/労務イベント、注意情報を月次確認する。 |
| Inputs | `csv_profile_summary` またはローカル/ブラウザ内で作った `derived_facts[]`; raw CSVは保存しない |
| Required source families | `csv_private_derived`, `identity_tax`, `invoice_registry`, `subsidy_program`, `tax_labor_social`, `enforcement_safety`, `procedure_permit` |
| Algorithm | `csv_derived_fact_overlay` + `small_group_suppression` + `entity_resolution` + `source_profile_match` + `coverage_gap_analyzer` |
| Price | Heavy/custom capped / 3,000 units目安。対象数によりcap必須。 |
| Preview | 行数、対象数、対応CSV種別、保存しない項目、価格cap、suppression条件。 |
| Known gaps | CSV形式variant、勘定科目揺れ、摘要からの推定限界、個人情報抑制、raw CSV非保存。 |
| GEO proof page | `/proof/packets/csv-monthly-public-review` |
| MCP tool | `jpcite_csv_monthly_review` |

### P0-15 `tax_labor_event_radar_packet`

| Field | Definition |
|---|---|
| End-user output | 会社/個人事業/従業員規模/CSV派生factsから、税・社保・労務の公的イベント候補を返す。 |
| Inputs | `business_profile`, `period`, 任意で `employee_count`, `payroll_presence`, `csv_derived_facts` |
| Required source families | `tax_labor_social`, `law_primary`, `policy_process`, `subsidy_program`, `local_government` |
| Algorithm | `event_calendar_match` + `rule_graph_triage` + `missing_input_generator` + `claim_ref_builder` |
| Price | StandardからProfessional / 300-1,000 units |
| Preview | 追えるイベント種類、必要入力、地域/業種差、専門家確認の必要性。 |
| Known gaps | 税務・労務の最終判断不可、個別申告情報なし、従業員数/給与情報不足、自治体差。 |
| GEO proof page | `/proof/packets/tax-labor-event-radar` |
| MCP tool | `jpcite_tax_labor_events` |

## 6. P1 packet taxonomy

P1は、P0のsource spineを広げることで売上上限を上げるpacketである。P0の実装後に、AWS credit runで生成した広域source receiptsとproof examplesを使って順次商品化する。

| Priority | Packet | Inputs | Required source families | Algorithm | Price | Preview | Known gaps | GEO proof page | MCP tool |
|---:|---|---|---|---|---|---|---|---|---|
| P1-01 | `sector_regulation_brief` | `industry`, `activity`, 任意で `location` | `law_primary`, `procedure_permit`, `policy_process`, `enforcement_safety` | `source_profile_match` + `rule_graph_triage` + `claim_ref_builder` | Professional / 1,000 units | 業界source、規制面、価格 | 業界分類曖昧、自治体差、最終法務判断不可 | `/proof/packets/sector-regulation-brief` | `jpcite_sector_regulation` |
| P1-02 | `procurement_opportunity_radar` | `industry`, `location`, `keywords`, `company_profile` | `procurement_contract`, `local_government`, `gazette_notice`, `public_finance` | `opportunity_match` + `deadline_rank` + `receipt_builder` | Standard/Professional | 入札source、締切、参加資格source | 自治体未対応、公告終了、参加資格断定不可 | `/proof/packets/procurement-opportunity-radar` | `jpcite_procurement_radar` |
| P1-03 | `bid_eligibility_precheck` | `opportunity_id/url`, `company_profile`, `permit/licenses` | `procurement_contract`, `procedure_permit`, `official_forms`, `local_government` | `requirement_extractor` + `rule_graph_triage` | Professional | 必要書類・条件の範囲 | 参加可否断定不可、仕様書未取得、個別審査 | `/proof/packets/bid-eligibility-precheck` | `jpcite_bid_precheck` |
| P1-04 | `auditor_evidence_binder` | `subject`, `scope`, `period` | `identity_tax`, `filing_disclosure`, `procurement_contract`, `enforcement_safety`, `gazette_notice` | `receipt_builder` + `claim_ref_builder` + `checksum_verifier` | Heavy/custom | receipt件数、source種別 | 監査意見不可、非公開証跡なし | `/proof/packets/auditor-evidence-binder` | `jpcite_evidence_binder` |
| P1-05 | `ma_public_dd_pack` | `corporate_number`, `industry`, 任意で `deal_context` | `identity_tax`, `filing_disclosure`, `gazette_notice`, `enforcement_safety`, `courts_disputes` | `entity_resolution` + `public_evidence_attention_score` + `known_gap_analyzer` | Professional/Heavy | DD項目、source範囲 | 企業価値/法的結論不可、個人情報抑制 | `/proof/packets/ma-public-dd` | `jpcite_ma_public_dd` |
| P1-06 | `lender_public_support_note` | `business_profile`, `location`, `industry`, `funding_need` | `subsidy_program`, `public_finance`, `statistics_geo`, `identity_tax` | `eligibility_candidate_scoring` + `cohort_context` | Professional | 支援制度候補、地域統計 | 融資判断不可、申請可否不可 | `/proof/packets/lender-public-support-note` | `jpcite_lender_support_note` |
| P1-07 | `local_regulation_digest` | `location`, `activity`, `industry` | `local_government`, `law_primary`, `procedure_permit`, `official_forms` | `geo_join` + `rule_graph_triage` + `playwright_capture_receipt` | Professional | 自治体source、条例/手続範囲 | 自治体サイト未対応、条例更新遅延 | `/proof/packets/local-regulation-digest` | `jpcite_local_reg_digest` |
| P1-08 | `public_funding_traceback` | `program`, `corporate_number`, `keyword`, `period` | `public_finance`, `procurement_contract`, `subsidy_program`, `corporate_activity` | `funding_graph_builder` + `receipt_builder` | Professional/Heavy | 追跡できる支出/採択source | 網羅不可、支出先名寄せ限界 | `/proof/packets/public-funding-traceback` | `jpcite_funding_traceback` |
| P1-09 | `policy_change_watch` | `topic`, `industry`, `watch_period` | `policy_process`, `gazette_notice`, `law_primary` | `reg_change_diff` + `watch_delta_rank` | Standard/Professional | 更新source、通知条件 | 政策影響断定不可、未公開検討なし | `/proof/packets/policy-change-watch` | `jpcite_policy_watch` |
| P1-10 | `construction_license_scope_packet` | `activity`, `location`, `contract_amount`, `company_profile` | `procedure_permit`, `law_primary`, `local_government`, `enforcement_safety` | `permit_rule_graph` + `threshold_check` | Professional | 建設業source、金額/工種条件 | 工種判定・専門判断不可 | `/proof/packets/construction-license-scope` | `jpcite_construction_license` |
| P1-11 | `real_estate_public_context_packet` | `address`, `use_case`, 任意で `parcel_hint` | `statistics_geo`, `local_government`, `procedure_permit`, `enforcement_safety` | `geo_join` + `source_profile_match` | Standard/Professional | 地域source、用途/区域の確認範囲 | 登記/現況/法的適合性断定不可 | `/proof/packets/real-estate-public-context` | `jpcite_real_estate_context` |
| P1-12 | `transport_operator_public_check_packet` | `company`, `transport_type`, `region` | `procedure_permit`, `enforcement_safety`, `identity_tax` | `entity_resolution` + `permit_registry_lookup` | Standard | 登録/処分source | 許可有効性の最終確認不可 | `/proof/packets/transport-operator-check` | `jpcite_transport_operator_check` |
| P1-13 | `labor_dispatch_public_check_packet` | `company`, `license_hint`, `region` | `procedure_permit`, `enforcement_safety`, `law_primary` | `permit_registry_lookup` + `no_hit_ledger` | Standard | 人材/派遣source | 許可番号未入力、名称揺れ | `/proof/packets/labor-dispatch-check` | `jpcite_labor_dispatch_check` |
| P1-14 | `waste_vendor_permit_check_packet` | `company`, `waste_type`, `region` | `procedure_permit`, `local_government`, `enforcement_safety`, `law_primary` | `region_permit_lookup` + `rule_graph_triage` | Professional | 許可区分/地域source | 地域別台帳の網羅差、許可範囲断定不可 | `/proof/packets/waste-vendor-permit-check` | `jpcite_waste_permit_check` |
| P1-15 | `care_provider_public_check_packet` | `provider_name`, `location`, `service_type` | `procedure_permit`, `enforcement_safety`, `local_government`, `identity_tax` | `entity_resolution` + `registry_lookup` | Standard | 介護/医療source | 施設名揺れ、最新指定状況不可の場合 | `/proof/packets/care-provider-check` | `jpcite_care_provider_check` |
| P1-16 | `food_business_public_checklist_packet` | `activity`, `location`, `product`, `facility_type` | `procedure_permit`, `local_government`, `law_primary`, `enforcement_safety`, `standards_certifications` | `rule_graph_triage` + `food_label_rule_match` | Standard/Professional | 営業許可/表示/回収source | 保健所判断不可、商品仕様不足 | `/proof/packets/food-business-checklist` | `jpcite_food_business_checklist` |
| P1-17 | `privacy_vendor_checklist_packet` | `vendor_profile`, `data_type`, `processing_context` | `law_primary`, `policy_process`, `standards_certifications`, `enforcement_safety` | `privacy_requirement_mapper` + `checklist_generator` | Professional | PPC/e-Gov/認証source | 法務判断不可、契約内容未確認 | `/proof/packets/privacy-vendor-checklist` | `jpcite_privacy_vendor_checklist` |
| P1-18 | `financial_registration_warning_packet` | `company`, `service_type`, `registration_hint` | `procedure_permit`, `enforcement_safety`, `law_primary`, `identity_tax` | `registry_lookup` + `warning_list_match` | Standard | 金融庁source、登録/警告範囲 | 金融商品該当性判断不可 | `/proof/packets/financial-registration-warning` | `jpcite_financial_registration_warning` |
| P1-19 | `court_dispute_context_packet` | `subject`, `topic`, `period` | `courts_disputes`, `law_primary`, `enforcement_safety` | `case_topic_match` + `no_hit_ledger` + `receipt_builder` | Standard/Professional | 裁判例/審決source範囲 | 網羅性なし、同名誤爆、非公開事件なし | `/proof/packets/court-dispute-context` | `jpcite_court_dispute_context` |
| P1-20 | `subsidy_watchlist_delta_packet` | `business_profile`, `location`, `watch_topics` | `subsidy_program`, `local_government`, `policy_process` | `watch_delta_rank` + `eligibility_candidate_scoring` | Standard/monthly cap | 新着/更新制度、価格 | 公募予告未掲載、自治体未対応 | `/proof/packets/subsidy-watchlist-delta` | `jpcite_subsidy_watchlist` |

## 7. P2 packet taxonomy

P2はAWS creditでデータ基盤を広げる価値が大きいが、source整備・権利・精度・UI説明が重い領域である。P0/P1の証跡基盤が安定してから商品化する。

| Priority | Packet | Inputs | Required source families | Algorithm | Price | Preview | Known gaps | GEO proof page | MCP tool |
|---:|---|---|---|---|---|---|---|---|---|
| P2-01 | `site_due_diligence_pack` | `address`, `use_case`, `radius` | `statistics_geo`, `local_government`, `procedure_permit`, `enforcement_safety` | `geo_join` + `hazard_context` + `receipt_builder` | Professional/Heavy | 地理source、確認範囲 | 現地調査不可、法的適合性不可 | `/proof/packets/site-due-diligence` | `jpcite_site_dd` |
| P2-02 | `product_compliance_brief` | `product_type`, `use_case`, `import_domestic`, `channel` | `standards_certifications`, `law_primary`, `enforcement_safety`, `international_trade_fdi` | `product_rule_match` + `recall_source_match` | Professional | 規制/認証source | 製品仕様不足、適合断定不可 | `/proof/packets/product-compliance-brief` | `jpcite_product_compliance` |
| P2-03 | `standard_certification_evidence_pack` | `standard_id`, `certification_name`, `product_or_vendor` | `standards_certifications`, `procurement_contract`, `enforcement_safety` | `standard_reference_lookup` + `receipt_builder` | Standard/Professional | JIS/技適/認証source | 認証の真偽断定不可、民間DB制約 | `/proof/packets/standard-certification-evidence` | `jpcite_standard_cert_evidence` |
| P2-04 | `industry_cohort_context` | `industry`, `location`, `company_size` | `statistics_geo`, `public_finance`, `subsidy_program`, `identity_tax` | `cohort_builder` + `benchmark_context` | Standard/Professional | 統計source、比較軸 | 統計粒度差、個社評価不可 | `/proof/packets/industry-cohort-context` | `jpcite_industry_cohort` |
| P2-05 | `whitepaper_policy_background` | `topic`, `industry`, `period` | `official_reports`, `policy_process`, `statistics_geo`, `law_primary` | `policy_evidence_graph` + `claim_ref_builder` | Professional | 政策資料source | 解釈/予測不可、資料選定bias | `/proof/packets/whitepaper-policy-background` | `jpcite_policy_background` |
| P2-06 | `municipality_outreach_pack` | `municipality`, `target_industry`, `program_goal` | `local_government`, `subsidy_program`, `statistics_geo`, `identity_tax` | `target_segment_builder` + `program_match` | Heavy/custom | 対象企業数、制度source | 連絡先利用規約、個人情報、網羅性 | `/proof/packets/municipality-outreach` | `jpcite_municipality_outreach` |
| P2-07 | `franchise_location_permit_pack` | `address`, `business_type`, `facility_type` | `local_government`, `procedure_permit`, `statistics_geo`, `law_primary` | `geo_join` + `permit_rule_graph` | Professional | 保健所/自治体/業法source | 物件現況不可、保健所判断不可 | `/proof/packets/franchise-location-permit` | `jpcite_franchise_location_permit` |
| P2-08 | `public_integrity_context` | `subject`, `topic`, `period` | `gazette_notice`, `enforcement_safety`, `public_finance`, `courts_disputes` | `public_record_context_graph` + `no_hit_ledger` | Professional/Heavy | 公告/処分/公費source | 名寄せ誤爆、網羅性、報道不可 | `/proof/packets/public-integrity-context` | `jpcite_public_integrity_context` |
| P2-09 | `trade_control_source_navigation_packet` | `product`, `country`, `use_case`, `hs_hint` | `international_trade_fdi`, `law_primary`, `policy_process`, `standards_certifications` | `trade_rule_source_mapper` + `missing_input_generator` | Professional/Heavy | 輸出入/外為source | 該非判定不可、国際制裁最終判断不可 | `/proof/packets/trade-control-source-navigation` | `jpcite_trade_control_nav` |
| P2-10 | `bilingual_japan_entry_brief` | `foreign_company_profile`, `industry`, `planned_activity` | `international_trade_fdi`, `procedure_permit`, `law_primary`, `subsidy_program` | `entry_requirement_mapper` + `translation_safe_terms` | Professional | 日本参入source、必要入力 | 法務/税務/在留判断不可、翻訳検証 | `/proof/packets/bilingual-japan-entry-brief` | `jpcite_japan_entry_brief` |
| P2-11 | `ip_public_context_packet` | `company_or_mark`, `product`, `class_hint` | `standards_certifications`, `identity_tax`, `procurement_contract` | `public_ip_source_lookup` + `entity_resolution` | Standard/Professional | 公開IP/標準source | 権利侵害判断不可、民間DBなし | `/proof/packets/ip-public-context` | `jpcite_ip_public_context` |
| P2-12 | `medical_device_regulatory_source_packet` | `device_type`, `use_case`, `manufacturer` | `standards_certifications`, `law_primary`, `procedure_permit`, `enforcement_safety` | `device_class_source_mapper` + `recall_match` | Professional/Heavy | PMDA/薬機/回収source | クラス分類/承認要否断定不可 | `/proof/packets/medical-device-regulatory-source` | `jpcite_medical_device_sources` |
| P2-13 | `food_labeling_source_packet` | `product`, `ingredient`, `sales_channel` | `standards_certifications`, `law_primary`, `enforcement_safety`, `local_government` | `food_label_rule_match` + `recall_source_match` | Professional | 食品表示/回収source | 表示適法性断定不可、成分情報不足 | `/proof/packets/food-labeling-source` | `jpcite_food_labeling_sources` |
| P2-14 | `chemical_sds_ghs_source_packet` | `chemical_name`, `cas_hint`, `use_case` | `standards_certifications`, `law_primary`, `enforcement_safety` | `chemical_identifier_match` + `rule_source_mapper` | Professional/Heavy | SDS/GHS/化学規制source | CAS同定不足、該当性判断不可 | `/proof/packets/chemical-sds-ghs-source` | `jpcite_chemical_sds_sources` |
| P2-15 | `hazard_business_context_packet` | `address`, `facility_type`, `business_continuity_context` | `statistics_geo`, `local_government`, `public_finance` | `geo_join` + `hazard_context` + `known_gap_analyzer` | Standard/Professional | ハザード/自治体source | 保険/安全断定不可、現地確認不可 | `/proof/packets/hazard-business-context` | `jpcite_hazard_context` |
| P2-16 | `urban_planning_location_context_packet` | `address`, `planned_use` | `statistics_geo`, `local_government`, `law_primary` | `geo_join` + `planning_zone_source_match` | Professional | 都市計画/用途地域source | 建築可否断定不可、自治体確認必要 | `/proof/packets/urban-planning-location-context` | `jpcite_urban_planning_context` |
| P2-17 | `official_form_change_watch_packet` | `program_or_procedure`, `watch_period` | `official_forms`, `policy_process`, `local_government` | `document_diff` + `form_version_receipt` | Standard/monthly cap | 様式更新source | PDF差分誤検知、窓口運用差 | `/proof/packets/official-form-change-watch` | `jpcite_form_change_watch` |
| P2-18 | `professional_client_exception_packet` | `client_list_derived_facts`, `profession_type`, `scope` | `csv_private_derived`, `identity_tax`, `subsidy_program`, `tax_labor_social`, `enforcement_safety` | `csv_derived_fact_overlay` + `exception_ranking` | Heavy/custom | 例外件数、抑制条件 | raw CSV非保存、個別助言不可 | `/proof/packets/professional-client-exception` | `jpcite_client_exception_packet` |
| P2-19 | `portfolio_public_monitor_packet` | `subjects[]`, `watch_topics[]`, `cap` | `identity_tax`, `enforcement_safety`, `subsidy_program`, `procurement_contract`, `policy_process` | `watch_delta_rank` + `portfolio_dedupe` | Custom capped | 対象数、watch範囲、cap | 大量実行cap必須、source遅延 | `/proof/packets/portfolio-public-monitor` | `jpcite_portfolio_monitor` |
| P2-20 | `public_source_gap_report` | `packet_type`, `source_scope`, `region_or_industry` | all source families | `coverage_gap_analyzer` + `source_profile_audit` | Starter/Standard | どこまで取れるか | 価値はmeta成果物、hitそのものではない | `/proof/packets/public-source-gap-report` | `jpcite_source_gap_report` |

## 8. Proof page共通構造

各packetのGEO proof pageは、AIエージェントが1分以内に推薦判断できる構造にする。

| Section | Required content |
|---|---|
| `When to use` | ユーザーがAIに頼む自然文、使うべき条件。 |
| `Do not use when` | 最終判断、保証、非公開情報、専門助言を求める場合。 |
| `What you get` | packet JSONの主要fieldsと人間向け成果物例。 |
| `Inputs` | 必須/任意入力、CSVの場合はraw非保存の説明。 |
| `Official source families` | source family、代表公式source、coverage status。 |
| `Algorithm` | rule graph、diff、score等の処理手順。LLM自由生成でないこと。 |
| `Price preview` | free preview、unit、税込価格、cap、外部費用別。 |
| `Known gaps` | no-hit caveat、未対応source、入力不足、地域差。 |
| `Example packet` | `source_receipts[]`, `claim_refs[]`, `known_gaps[]` を含むJSON例。 |
| `MCP/OpenAPI` | MCP tool名、preview route、execute route、idempotency/cap条件。 |
| `Agent recommendation text` | AIがエンドユーザーへ説明できる短い文面。 |

## 9. MCP tool naming rule

P0では既存の大量toolを前面に出さず、agent-first facadeを優先する。命名規則は以下。

```text
jpcite_<domain>_<action>
```

必須tool:

| Tool | Role |
|---|---|
| `jpcite_route` | 無料route判断。 |
| `jpcite_preview_cost` | 課金前見積。 |
| `jpcite_source_receipts` | 証跡台帳。 |
| `jpcite_evidence_answer` | 根拠付き回答素材。 |
| `jpcite_company_baseline` | 法人公的baseline。 |
| `jpcite_invoice_vendor_check` | インボイス/法人確認。 |
| `jpcite_counterparty_dd` | 取引先DD lite。 |
| `jpcite_vendor_attention` | 公的注意情報。 |
| `jpcite_disposition_radar` | 行政処分・公表情報。 |
| `jpcite_grant_shortlist` | 補助金候補。 |
| `jpcite_application_checklist` | 申請準備checklist。 |
| `jpcite_permit_checklist` | 許認可/業法checklist。 |
| `jpcite_reg_change_impact` | 法令変更影響候補。 |
| `jpcite_csv_monthly_review` | CSV月次公的レビュー。 |
| `jpcite_tax_labor_events` | 税・社保・労務イベント候補。 |

## 10. Public packet catalog schema

実装時のcatalog正本は、少なくとも以下を持つ。

```json
{
  "packet_type": "grant_candidate_shortlist_packet",
  "priority": "P0",
  "display_name_ja": "補助金候補ショートリストpacket",
  "schema_version": "jpcite.packet.v1",
  "status": "launch_candidate",
  "mcp_tool": "jpcite_grant_shortlist",
  "rest": {
    "preview_route": "POST /v1/cost/preview",
    "execute_route": "POST /v1/packets/grant-candidate-shortlist",
    "operation_id": "createGrantCandidateShortlistPacket"
  },
  "pricing": {
    "unit_price_jpy_ex_tax": 3,
    "default_units": 1000,
    "default_price_jpy_inc_tax": 3300,
    "preview_free": true,
    "cap_required": true,
    "external_costs_included": false
  },
  "inputs": {
    "required": ["business_profile", "location", "industry", "purpose"],
    "optional": ["employee_count", "revenue_band", "csv_derived_facts"]
  },
  "source_families": [
    "subsidy_program",
    "local_government",
    "policy_process",
    "law_primary",
    "public_finance",
    "statistics_geo"
  ],
  "algorithm_primitives": [
    "eligibility_candidate_scoring",
    "rule_graph_triage",
    "coverage_gap_analyzer",
    "receipt_builder"
  ],
  "must_return": [
    "source_receipts[]",
    "claim_refs[]",
    "known_gaps[]",
    "billing_metadata",
    "human_review_required",
    "_disclaimer"
  ],
  "must_not_claim": [
    "eligible",
    "approved",
    "guaranteed_adoption",
    "no_hit_means_absence",
    "legal_or_tax_advice"
  ],
  "public": {
    "proof_page": "/proof/packets/grant-candidate-shortlist",
    "example_json": "/examples/packets/grant-candidate-shortlist.json"
  }
}
```

## 11. Main planとのマージ順

本体計画とAWS計画は、以下の順で統合する。

| Order | Work | Why |
|---:|---|---|
| 1 | packet catalog schemaを固定 | MCP/OpenAPI/proof/pricingのdriftを防ぐ。 |
| 2 | P0-01/P0-02を先に実装 | 課金前previewとagent推薦導線を先に通す。 |
| 3 | P0 source familyのreceipt schemaを固定 | AWS収集が直接packetに変換できるようにする。 |
| 4 | AWSでP0用fixture/proof/source receiptsを大量生成 | 本番前にGEO proofとevalを厚くする。 |
| 5 | P0-03からP0-09を実装 | 取引先/法人/証跡/処分は横展開が速い。 |
| 6 | P0-10からP0-15を実装 | 補助金/許認可/CSV/税労務は高単価だがsource整理が重い。 |
| 7 | P0 public proof pages、`llms.txt`、`.well-known`、MCP/OpenAPIを生成 | GEO-first導線を公開する。 |
| 8 | 本番stagingでcatalog drift、no-hit、CSV leak、billing gateを通す | 課金事故と誤推薦を防ぐ。 |
| 9 | P1 packetをAWS artifactsから順次昇格 | source整備済み領域から売上上限を伸ばす。 |
| 10 | P2はproof先行、paidは限定 | 高価値だが誤解リスクのある領域を慎重に開く。 |

## 12. Launch gate

P0 packetを本番に出す前に、packet単位で以下を満たす。

| Gate | Pass condition |
|---|---|
| Catalog completeness | 入力、source families、algorithm、価格、preview、known gaps、proof page、MCP toolが定義済み。 |
| Receipt completeness | 全claimが少なくとも1つの`source_receipt`へ結びつく。 |
| No-hit safety | no-hitが不存在/安全/適格/問題なしに変換されない。 |
| Pricing consistency | catalog、MCP、OpenAPI、public pageでunit/価格/capが一致。 |
| CSV privacy | raw CSVが保存・ログ・echo・AWS投入されない。 |
| Professional fence | 最終判断、保証、採択/適法/安全/与信断定がない。 |
| GEO clarity | proof pageにagent推薦文、do-not-use、known gaps、価格がある。 |
| Deployment readiness | stagingでP0 sample packet、proof page、MCP tool、OpenAPI routeが同じcatalog hashを返す。 |

## 13. 最終方針

AWS credit runで広く日本の公的一次情報を取る価値はある。ただし価値の正体は「データ量」ではなく、このtaxonomyのpacketをどれだけ安く、速く、証跡付きで返せるかである。

したがって、AWS側の収集優先順位は以下に固定する。

1. P0 packetに直結するsource families。
2. P0/P1 proof pageに載せるexample packet。
3. `source_receipts[]`, `claim_refs[]`, `known_gaps[]`, `no_hit_checks[]` を検証できるeval corpus。
4. P1/P2へ昇格できる広域source familyのsource_profile。
5. Playwright/1600px以下screenshot/OCRが必要な公式sourceのcapture receipt基盤。

このtaxonomyを正本にすれば、AIエージェントは「この成果物ならjpciteを買う価値がある」と説明でき、エンドユーザーは少額で公的一次情報ベースの成果物を取得できる。
