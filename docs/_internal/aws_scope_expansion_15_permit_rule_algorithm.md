# AWS scope expansion 15/30: permit and regulated-business rule algorithm

作成日: 2026-05-15

対象: jpcite JP site / AWS credit acceleration / permit-regulation packet factory

制約:

- AWS CLI/API/リソース作成は行わない。
- この文書は設計と実装準備のみ。
- raw CSV、未加工の顧客入力、個人情報を永続化しない前提で設計する。
- 一次情報に基づく判定だけを出す。推測で「許可不要」「適法」「安全」と断定しない。

## 1. 結論

許認可・業法チェックは成立する。ただし、通常のLLM回答として作ると危険で、必ず次の形にする必要がある。

1. ユーザーの事業内容を、業種、地域、行為、規模、人員、設備、資格、取引形態、顧客属性、過去処分、既存許認可に正規化する。
2. 公的一次情報から作った versioned rule graph に照合する。
3. 判定は `required` / `possibly_required` / `not_triggered_by_known_inputs` / `unknown_due_to_missing_input` / `human_review_required` の5段階に限定する。
4. `not_triggered_by_known_inputs` は「許可不要」ではない。入力済み条件では発火していない、という意味に固定する。
5. 出力は必ず `source_receipts[]`, `claim_refs[]`, `known_gaps[]`, `missing_questions[]`, `human_review_required` を持つ。
6. ルールの根拠は e-Gov法令、所管省庁ページ、自治体標準ODS、許認可台帳、行政処分情報、官報・告示・通達・パブコメ結果などに限定する。

この機能は「AIエージェントがエンドユーザーに安く売れる成果物」と相性がよい。理由は、エンドユーザーが本当に欲しいのは条文全文ではなく、次のような成果物だからである。

- この事業を始める前に必要な許認可・届出・登録の一覧
- 管轄窓口と提出先
- 申請前に不足している入力・書類・資格・設備
- 禁止行為・注意行為
- 更新期限・変更届・廃止届のカレンダー
- 取引先が必要許認可を持っていそうかの一次情報ベース確認
- 行政処分・取消・欠格に関係しうるリスク確認

## 2. 売れる成果物から逆算した優先順位

最初に作るべき成果物は、技術的に作りやすい順ではなく、AIエージェントがエンドユーザーへ推薦しやすく、かつ課金されやすい順にする。

| 優先 | 成果物ID | エンドユーザーの問い | 売れる理由 | 必要な判定 |
|---|---|---|---|---|
| P0 | `permit_launch_check` | この事業を始めるには何が必要か | 開業・新規事業の直前に痛みが強い | 必要許認可、届出、登録、資格、設備、管轄 |
| P0 | `regulated_action_check` | この行為はやってよいか | 禁止・罰則・炎上回避の価値が高い | 禁止行為、条件付き可、要人間確認 |
| P0 | `license_due_diligence` | この取引先は必要許認可を持つか | B2B取引前の審査で反復利用される | 許可台帳、処分情報、法人番号、名称一致 |
| P0 | `renewal_and_change_calendar` | 更新・変更届を忘れていないか | 継続課金・リテンション向き | 有効期間、変更事由、更新期限、届出期限 |
| P1 | `application_readiness_checklist` | 申請前に何が足りないか | 申請代行・士業連携に繋がる | 申請要件、書類、資格、設備、財産基礎 |
| P1 | `multi_prefecture_routing` | 大臣/知事/自治体どこに出すか | 複数拠点事業者に刺さる | 拠点数、営業所、地域、管轄 |
| P1 | `past_sanction_risk_packet` | 過去処分が許可に影響するか | 役員変更・M&A・取引前審査で価値 | 処分歴、欠格事由、期間、対象者範囲 |
| P1 | `csv_overlay_permit_watch` | 会計CSVから許認可が必要そうな取引があるか | CSV投入だけで価値が出る | 勘定科目/摘要から行為候補を抽出し、公的ルールに照合 |

## 3. 判定対象の入力schema

入力は自然文のまま扱わない。自然文は一度 `business_profile` に落とす。

```json
{
  "request_id": "req_20260515_xxx",
  "locale": "ja-JP",
  "evaluation_date": "2026-05-15",
  "entity": {
    "name": "株式会社サンプル",
    "corporate_number": "optional",
    "invoice_number": "optional",
    "legal_form": "corporation|sole_proprietor|association|unknown",
    "officers": [
      {
        "role": "representative|director|manager|unknown",
        "sanction_check_requested": true
      }
    ]
  },
  "locations": [
    {
      "prefecture": "東京都",
      "municipality": "渋谷区",
      "address_granularity": "prefecture|municipality|address|unknown",
      "facility_role": "head_office|branch|sales_office|warehouse|store|factory|clinic|garage|unknown"
    }
  ],
  "industry_candidates": [
    "construction",
    "real_estate",
    "food",
    "labor_dispatch",
    "employment_placement",
    "industrial_waste",
    "transport",
    "travel",
    "medical",
    "care",
    "financial",
    "telecom",
    "product_safety",
    "alcohol",
    "secondhand_goods",
    "privacy_ecommerce"
  ],
  "acts": [
    {
      "act_type": "sell|broker|manufacture|import|transport|dispose|introduce_workers|dispatch_workers|construct|operate_facility|collect_data|provide_medical_service|unknown",
      "object": "land|building|food|alcohol|waste|worker|patient|vehicle|electric_product|personal_data|unknown",
      "for_fee": true,
      "continuous_business": true,
      "channel": "offline|online|marketplace|agency|direct|unknown"
    }
  ],
  "scale": {
    "annual_revenue_jpy": null,
    "contract_amount_jpy": null,
    "single_project_amount_jpy": null,
    "building_area_m2": null,
    "vehicles": null,
    "beds": null,
    "employees": null,
    "prefecture_count": null,
    "facility_count": null
  },
  "people_and_qualifications": [
    {
      "role": "responsible_manager|dedicated_technician|qualified_real_estate_transaction_agent|food_sanitation_manager|driver|medical_doctor|care_manager|unknown",
      "qualification_name": "optional",
      "full_time": "true|false|unknown",
      "site_assignment": "location_id|unknown"
    }
  ],
  "facilities_and_equipment": [
    {
      "facility_type": "kitchen|clinic|garage|warehouse|processing_plant|office|unknown",
      "equipment": ["refrigerator", "vehicle", "storage", "inspection_equipment"],
      "meets_standard_self_reported": "true|false|unknown"
    }
  ],
  "existing_permits": [
    {
      "permit_type": "optional",
      "permit_number": "optional",
      "authority": "optional",
      "valid_until": "optional",
      "source": "user_upload|public_registry|unknown"
    }
  ],
  "past_sanctions": [
    {
      "source": "public_registry|user_report|unknown",
      "authority": "optional",
      "date": "optional",
      "description": "optional"
    }
  ],
  "csv_derived_facts": [
    {
      "fact_type": "vendor_payment|sales_category|asset_purchase|payroll|rent|vehicle_expense|unknown",
      "period": "YYYY-MM",
      "aggregate_only": true
    }
  ]
}
```

### 3.1 入力で必須化しない方がよい項目

最初から全項目を聞くと離脱する。最初は次の5つだけでよい。

1. 何をする事業か。
2. どこで行うか。
3. 継続・有償で行うか。
4. 対象物・対象者は何か。
5. 規模は分かる範囲でどれくらいか。

不足は `missing_questions[]` として後から聞く。ここで数学的には「不確実性を最も減らす質問」を選ぶ。

## 4. 正規化taxonomy

自然文を次のtaxonomyに正規化する。taxonomyはルールの安定IDであり、表示名を変えてもIDは変えない。

### 4.1 行為taxonomy

| act_type | 意味 | 例 |
|---|---|---|
| `construct` | 建設工事の完成を請け負う | 内装工事、電気工事、外構工事 |
| `real_estate_sell_exchange` | 宅地建物の売買・交換 | 自社物件売買、土地売買 |
| `real_estate_broker_agency` | 宅地建物の売買/交換/貸借の代理・媒介 | 賃貸仲介、売買仲介 |
| `food_manufacture` | 食品製造 | 弁当、菓子、惣菜 |
| `food_sale_or_service` | 食品販売・飲食提供 | 飲食店、移動販売、EC食品販売 |
| `alcohol_sale` | 酒類販売・代理・媒介 | EC酒販、店舗酒販 |
| `worker_dispatch` | 労働者派遣 | 派遣先の指揮命令で労働 |
| `employment_placement` | 職業紹介 | 求人者と求職者の雇用関係成立をあっせん |
| `waste_collect_transport` | 産廃・一般廃棄物の収集運搬 | 産廃回収 |
| `waste_disposal` | 廃棄物の処分 | 中間処理、最終処分 |
| `freight_transport` | 有償貨物運送 | トラック輸送 |
| `passenger_transport` | 有償旅客運送 | タクシー、バス、送迎 |
| `travel_arrangement` | 旅行業務 | 募集型企画旅行、手配旅行 |
| `medical_service` | 医療提供 | 診療所、病院、助産所 |
| `care_service` | 介護サービス提供 | 訪問介護、通所介護 |
| `financial_intermediation` | 金融商品・貸金・決済等 | 金融商品取引、貸金、資金移動 |
| `telecom_service` | 電気通信役務 | 通信回線、媒介、届出対象サービス |
| `electric_product_import_manufacture` | 電気用品の輸入・製造 | PSE対象品輸入 |
| `secondhand_goods_trade` | 古物の売買・交換・委託売買 | 中古品買取販売 |
| `consumer_remote_sale` | 消費者向け通信販売等 | EC、定期購入 |
| `personal_data_handling` | 個人データ取扱い | CRM、求人DB、健康情報 |

### 4.2 対象物taxonomy

| object_type | 用途 |
|---|---|
| `land` / `building` | 宅建、建設、建築、都市計画 |
| `food` / `additive` / `utensil_container` | 食品衛生、輸入食品 |
| `alcohol` | 酒税法、酒類販売免許 |
| `waste_industrial` / `waste_general` | 廃棄物処理法、自治体許可 |
| `worker` / `job_seeker` / `employer` | 派遣、職業紹介 |
| `vehicle_freight` / `vehicle_passenger` | 運送 |
| `patient` / `medicine` / `medical_device` | 医療、薬機 |
| `care_recipient` | 介護保険 |
| `electric_product` | 電気用品安全法 |
| `personal_information` / `special_care_required_data` | 個人情報保護法 |

### 4.3 地域taxonomy

地域は単なる住所ではなく、管轄判定に使う。

- `prefecture`
- `municipality`
- `ordinance_designated_city`
- `health_center_jurisdiction`
- `labor_bureau_jurisdiction`
- `regional_transport_bureau`
- `regional_development_bureau`
- `tax_office_jurisdiction`
- `police_station_jurisdiction`

自治体ごとに食品営業、旅館、風営、屋外広告、廃棄物などが変わるため、自治体レベルの `source_profile` を別に持つ。

## 5. 一次情報source family

### 5.1 共通source

| source family | 用途 | 取得方式 | 優先度 |
|---|---|---|---|
| e-Gov法令API / XML一括 | 法律・政令・省令の条文 | API / XML bulk | P0 |
| 所管省庁の制度ページ | 要件、手続、Q&A、標準処理期間 | fetch / Playwright / PDF | P0 |
| 告示・通達・ガイドライン | 条文だけでは分からない運用 | fetch / PDF / OCR | P0 |
| e-Govパブコメ結果 | 改正予定・解釈補足 | RSS / fetch | P1 |
| 官報・公示・公告 | 告示、公告、取消、改正公布 | fetch / screenshot / OCR | P1 |
| 自治体標準ODS | 食品等営業許可・届出、医療機関、介護事業所等 | CSV/XLSX/fetch | P0/P1 |
| 行政処分・ネガティブ情報 | 欠格・取引先審査・注意喚起 | fetch / Playwright | P0 |

### 5.2 参照確認済みの公式入口

この文書では下記の公式入口を一次情報候補として採用する。

- e-Gov法令検索 XML一括ダウンロード: https://laws.e-gov.go.jp/bulkdownload/
- e-Gov法令API仕様: https://laws.e-gov.go.jp/file/houreiapi_shiyosyo.pdf
- e-Gov Developer API: https://developer.e-gov.go.jp/contents/specification
- e-Govパブリック・コメント: https://public-comment.e-gov.go.jp/servlet/Public
- デジタル庁 自治体標準オープンデータセット: https://www.digital.go.jp/resources/open_data/municipal-standard-data-set-test
- 国土交通省 建設業許可: https://www.mlit.go.jp/totikensangyo/const/1_6_bt_000080.html
- 国土交通省 建設業許可要件: https://www.mlit.go.jp/totikensangyo/const/1_6_bt_000082.html
- 国土交通省 宅地建物取引業免許: https://www.mlit.go.jp/totikensangyo/const/1_6_bt_000242.html
- 国土交通省 ネガティブ情報等検索サイト: https://www.mlit.go.jp/nega-inf/cgi-bin/search.cgi
- 厚生労働省 食品営業規制: https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/shokuhin/kigu/index_00010.html
- 厚生労働省 食品衛生申請等システム: https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/shokuhin/kigu/index_00012.html
- 厚生労働省 労働者派遣事業: https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/roudoushahakennjigyou.html
- 厚生労働省 職業紹介事業制度: https://www.mhlw.go.jp/bunya/koyou/haken-shoukai01.html
- 厚生労働省 医療機能情報提供制度: https://www.mhlw.go.jp/stf/newpage_35867.html
- 厚生労働省 介護サービス情報公表制度: https://www.mhlw.go.jp/stf/kaigo-kouhyou.html
- 環境省 産業廃棄物処理業許可: https://www.env.go.jp/hourei/11/000173.html
- 環境省 産業廃棄物処理業者情報: https://www.env.go.jp/recycle/waste/info_1_1/ctriw-info.html
- 国土交通省 一般貨物自動車運送事業: https://www.mlit.go.jp/jidosha/jidosha_tk4_000102.html
- 観光庁 旅行業法: https://www.mlit.go.jp/kankocho/seisaku_seido/ryokogyoho/index.html
- 観光庁 旅行業登録確認: https://www.mlit.go.jp/kankocho/seisaku_seido/ryokochui/torokukakunin.html
- 国税庁 酒類免許: https://www.nta.go.jp/taxes/sake/menkyo/mokuji.htm
- 国税庁 酒類販売業免許解釈通達: https://www.nta.go.jp/law/tsutatsu/kihon/sake/2-05.htm
- 経済産業省 電気用品安全法 手続: https://www.meti.go.jp/policy/consumer/seian/denan/procedure.html
- 経済産業省 電気用品安全法 届出: https://www.meti.go.jp/policy/consumer/seian/denan/procedure_03.html
- 消費者庁 特定商取引法: https://www.caa.go.jp/policies/policy/consumer_transaction/specified_commercial_transactions/index.html
- 個人情報保護委員会 法令・ガイドライン: https://www.ppc.go.jp/personalinfo/legal/
- 警察庁 古物営業法手続: https://www.npa.go.jp/policies/application/form/12/index.html

## 6. ルールグラフ設計

### 6.1 ノード

```text
BusinessProfile
  -> Entity
  -> Location
  -> Act
  -> Object
  -> Scale
  -> PersonQualification
  -> FacilityEquipment
  -> ExistingPermit
  -> PastSanction

RegulatoryRegime
  -> Law
  -> Ordinance
  -> NoticeGuideline
  -> LocalRule
  -> Authority

Requirement
  -> Permit
  -> Registration
  -> Notification
  -> Approval
  -> Certification
  -> Report
  -> RecordKeeping
  -> DisplayObligation
  -> Renewal
  -> ChangeNotification
  -> Prohibition
  -> HumanReview

Evidence
  -> SourceReceipt
  -> ClaimRef
  -> ScreenshotReceipt
  -> PdfReceipt
  -> TableReceipt
```

### 6.2 エッジ

| edge | 意味 |
|---|---|
| `act_triggers_regime` | 行為が制度を発火させる |
| `object_triggers_regime` | 対象物が制度を発火させる |
| `scale_crosses_threshold` | 規模が閾値を超える |
| `location_selects_authority` | 地域が管轄を決める |
| `facility_requires_standard` | 施設・設備要件がある |
| `person_requires_qualification` | 人員・資格要件がある |
| `existing_permit_satisfies_requirement` | 既存許可が要件を満たす可能性 |
| `sanction_may_block_or_raise_risk` | 過去処分が欠格・注意に関係しうる |
| `rule_has_source` | ルールが一次情報に紐づく |
| `rule_superseded_by` | 改正・更新で旧ルールになった |
| `unknown_blocks_conclusion` | 不明入力が断定を止める |

### 6.3 ルールはDAGを基本にする

許認可判定は循環参照を避ける。例外・経過措置は別ノードにする。

```text
Act -> Regime -> Requirement -> Authority -> OutputClaim
                -> Exception -> OutputClaim
                -> MissingInput -> Question
```

例外は「結論を取り消す」のではなく「上位ルールを限定する」形で表現する。

## 7. 三値論理と5段階出力

### 7.1 内部論理

内部評価は `TRUE`, `FALSE`, `UNKNOWN` の三値で行う。

| AND | TRUE | FALSE | UNKNOWN |
|---|---|---|---|
| TRUE | TRUE | FALSE | UNKNOWN |
| FALSE | FALSE | FALSE | FALSE |
| UNKNOWN | UNKNOWN | FALSE | UNKNOWN |

| OR | TRUE | FALSE | UNKNOWN |
|---|---|---|---|
| TRUE | TRUE | TRUE | TRUE |
| FALSE | TRUE | FALSE | UNKNOWN |
| UNKNOWN | TRUE | UNKNOWN | UNKNOWN |

NOTは慎重に扱う。`NOT UNKNOWN` は `UNKNOWN` とする。

### 7.2 外部出力

| output status | 意味 | 禁止される言い換え |
|---|---|---|
| `required` | 入力済み事実と一次情報ルールで必要性が発火 | 絶対に許可される |
| `possibly_required` | 重要条件が一部不明だが可能性が高い | 必ず必要 |
| `not_triggered_by_known_inputs` | 入力済み条件だけでは発火しない | 許可不要、安全、適法 |
| `unknown_due_to_missing_input` | 判定に必要な入力がない | 不要 |
| `human_review_required` | 地方差、例外、裁量、欠格、罰則、専門判断がある | AIで確定 |

### 7.3 no-hit表現

許可台帳や処分情報で該当が出ない場合:

- 許容: `指定した検索条件では、このsourceでは該当を確認できませんでした。`
- 許容: `名称揺れ、管轄違い、更新遅延、非公開情報の可能性があります。`
- 禁止: `許可を持っていません。`
- 禁止: `処分歴はありません。`
- 禁止: `問題ありません。`

## 8. ルールDSL

最初はJSONでよい。将来はRego/Datalog/SQLへの変換を可能にする。

### 8.1 Rule schema

```json
{
  "rule_id": "permit.construction.license.required.v1",
  "status": "active",
  "effective_from": "2025-04-01",
  "effective_to": null,
  "jurisdiction": {
    "country": "JP",
    "national_or_local": "mixed",
    "authority_selector": "construction_authority_by_office_count"
  },
  "regime": {
    "law_name": "建設業法",
    "regime_id": "construction_business_license"
  },
  "trigger": {
    "all": [
      { "field": "acts.act_type", "op": "contains", "value": "construct" },
      { "field": "acts.continuous_business", "op": "eq", "value": true }
    ]
  },
  "thresholds": [
    {
      "threshold_id": "minor_construction_possible_exemption",
      "logic": {
        "any_unknown_blocks_exemption": true,
        "conditions": [
          {
            "field": "scale.single_project_amount_jpy",
            "op": "lt",
            "value": 15000000,
            "applies_when": { "field": "object", "op": "eq", "value": "building_general" }
          }
        ]
      }
    }
  ],
  "output": {
    "requirement_type": "permit",
    "requirement_name": "建設業許可",
    "status_when_triggered": "required",
    "human_review_required": true,
    "disclaimer_key": "not_legal_advice"
  },
  "source_refs": [
    {
      "source_id": "mlit_construction_license_page",
      "url": "https://www.mlit.go.jp/totikensangyo/const/1_6_bt_000080.html",
      "evidence_type": "official_page",
      "claim_path": "建設業許可/軽微な建設工事"
    }
  ],
  "known_gaps": [
    "工事種別と請負金額が不明な場合、軽微な建設工事の例外判定はできない。",
    "地方整備局・都道府県の個別確認資料は管轄により差がある。"
  ]
}
```

### 8.2 Requirement output schema

```json
{
  "requirement_id": "req_construction_license_001",
  "requirement_type": "permit",
  "name": "建設業許可",
  "status": "required",
  "severity": "blocker",
  "why_triggered": [
    {
      "fact_ref": "fact.act.construct",
      "claim_ref": "claim.mlit.construction_license.001"
    }
  ],
  "authority": {
    "selector": "construction_authority_by_office_count",
    "candidate": "国土交通大臣または都道府県知事",
    "known_gap": "営業所が複数都道府県か不明"
  },
  "missing_questions": [
    {
      "question_id": "q_construction_amount",
      "question": "1件あたりの請負金額と工事種別は分かりますか。",
      "reason": "軽微な建設工事の例外判定に必要"
    }
  ],
  "source_receipts": [],
  "claim_refs": [],
  "known_gaps": [],
  "human_review_required": true
}
```

## 9. 決定表: P0業種

この表は最初のルール登録対象である。詳細条文・例外は各source_profileに分離し、ここでは実装入口のトリガーを固定する。

### 9.1 建設業

| 項目 | 設計 |
|---|---|
| trigger | `construct` を業として行う |
| 主要source | 国土交通省 建設業許可、e-Gov 建設業法 |
| 判定軸 | 工事種別、請負金額、木造住宅延床面積、営業所所在地、一般/特定、業種区分 |
| 必要になりうるもの | 建設業許可、変更届、更新、経営事項審査、主任技術者/監理技術者 |
| authority | 大臣/知事。営業所が2以上の都道府県かで分岐 |
| human_review | 高。軽微工事、業種分類、技術者要件、特定建設業は人間確認 |
| no-hit | 建設業者検索で該当なしは無許可断定不可 |

決定表:

| 条件 | 結果 |
|---|---|
| 建設工事を継続・有償で請け負う | `possibly_required` 以上 |
| 軽微な建設工事の例外に明確に該当 | `not_triggered_by_known_inputs` ただし許可不要断定なし |
| 元請で一定額以上の下請契約 | 特定建設業許可の可能性 |
| 工事種別・金額不明 | `unknown_due_to_missing_input` |

### 9.2 宅地建物取引業

| 項目 | 設計 |
|---|---|
| trigger | 宅地/建物の売買、交換、売買/交換/貸借の代理・媒介を業として行う |
| 主要source | 国土交通省 宅地建物取引の免許 |
| 判定軸 | 行為、対象、業として行うか、事務所の都道府県数、専任宅建士 |
| 必要になりうるもの | 宅建業免許、専任宅建士、営業保証金/保証協会、変更届、更新 |
| authority | 大臣/知事 |
| human_review | 中。自社賃貸、単発取引、媒介該当性は確認 |

決定表:

| 条件 | 結果 |
|---|---|
| 宅地建物の売買/交換を業として行う | `required` 候補 |
| 宅地建物の代理/媒介を業として行う | `required` 候補 |
| 自己所有物件の賃貸のみ | `not_triggered_by_known_inputs` 候補、人間確認 |
| 2都道府県以上に事務所 | 大臣免許候補 |

### 9.3 食品営業

| 項目 | 設計 |
|---|---|
| trigger | 食品製造、販売、飲食提供、輸入、営業上使用 |
| 主要source | 厚生労働省 食品営業規制、食品衛生申請等システム、自治体標準ODS |
| 判定軸 | 許可営業/届出営業/届出対象外、施設所在地、品目、提供形態、製造/販売/輸入 |
| 必要になりうるもの | 営業許可、営業届出、食品衛生責任者、HACCPに沿った衛生管理、輸入届出 |
| authority | 保健所/都道府県等 |
| human_review | 高。自治体差と品目差が大きい |

決定表:

| 条件 | 結果 |
|---|---|
| 飲食店営業に近い行為 | 営業許可候補 |
| 食品販売のみ | 届出または許可候補 |
| 営業上使用する食品等輸入 | 輸入届出候補 |
| 品目・施設・提供形態不明 | `unknown_due_to_missing_input` |

### 9.4 労働者派遣

| 項目 | 設計 |
|---|---|
| trigger | 自社雇用労働者を派遣先の指揮命令下で働かせる |
| 主要source | 厚生労働省 労働者派遣事業 |
| 判定軸 | 指揮命令関係、雇用関係、有償/業、派遣先、禁止業務、日雇派遣等 |
| 必要になりうるもの | 労働者派遣事業許可、情報提供、事業報告、管理体制 |
| authority | 厚生労働大臣/労働局 |
| human_review | 高。業務委託との境界、偽装請負リスク |

決定表:

| 条件 | 結果 |
|---|---|
| 派遣先の指揮命令で労働 | `required` 候補 |
| 請負だが実態として指揮命令がある可能性 | `human_review_required` |
| 港湾/建設/警備など禁止・制限領域候補 | `human_review_required` |

### 9.5 職業紹介

| 項目 | 設計 |
|---|---|
| trigger | 求人者と求職者の雇用関係成立をあっせん |
| 主要source | 厚生労働省 職業紹介事業制度、募集情報等提供と職業紹介の区分 |
| 判定軸 | あっせん性、有料/無料、取扱職業、学校/自治体等例外 |
| 必要になりうるもの | 有料職業紹介許可、無料職業紹介許可/届出、手数料表、職業紹介責任者 |
| authority | 厚生労働大臣/労働局 |
| human_review | 高。求人メディアと職業紹介の境界 |

決定表:

| 条件 | 結果 |
|---|---|
| 求人者と求職者を個別にあっせん | `required` 候補 |
| 求人情報掲載のみ | `not_triggered_by_known_inputs` 候補。ただし契約・実態確認 |
| 成功報酬・推薦・面接調整あり | 職業紹介該当可能性上昇 |

### 9.6 産業廃棄物

| 項目 | 設計 |
|---|---|
| trigger | 産業廃棄物の収集運搬、処分を業として行う |
| 主要source | 環境省 法令・通達、産廃情報、自治体情報 |
| 判定軸 | 廃棄物種類、収集運搬/処分、積替保管、区域、施設、技術能力、更新状況 |
| 必要になりうるもの | 産業廃棄物収集運搬業許可、処分業許可、施設設置許可、更新 |
| authority | 都道府県/政令市等 |
| human_review | 高。自治体差、一般廃棄物との区別、積替保管 |

決定表:

| 条件 | 結果 |
|---|---|
| 他者の産廃を有償で収集運搬 | 許可候補 |
| 処分を行う | 処分業許可候補 |
| 排出者自身の運搬 | 例外可能性。ただし人間確認 |
| 更新申請中で期限経過 | 有効性の扱いに注意。一次情報と自治体確認 |

### 9.7 貨物・旅客運送

| 項目 | 設計 |
|---|---|
| trigger | 他人の需要に応じ、有償で貨物/旅客を自動車で運送 |
| 主要source | 国土交通省 一般貨物自動車運送事業、道路運送法/貨物自動車運送事業法 |
| 判定軸 | 貨物/旅客、有償性、車両、営業所、車庫、運行管理、安全管理 |
| 必要になりうるもの | 一般貨物許可、旅客運送許可/登録、運賃料金届出、事業計画変更 |
| authority | 地方運輸局等 |
| human_review | 高。自家輸送、有償性、ライドシェア/送迎境界 |

### 9.8 旅行業

| 項目 | 設計 |
|---|---|
| trigger | 旅行業務を営む |
| 主要source | 観光庁 旅行業法、旅行業登録確認 |
| 判定軸 | 第1種/第2種/第3種/地域限定/旅行業者代理業、企画旅行/手配旅行、営業所 |
| 必要になりうるもの | 旅行業登録、旅行業務取扱管理者、営業保証金/弁済業務保証金 |
| authority | 観光庁長官/都道府県 |
| human_review | 中-高 |

### 9.9 酒類販売

| 項目 | 設計 |
|---|---|
| trigger | 酒類を継続的に販売、販売代理、媒介 |
| 主要source | 国税庁 酒類免許、酒類販売業免許解釈通達 |
| 判定軸 | 小売/卸、通信販売、販売場、地域、品目、継続性、代理/媒介 |
| 必要になりうるもの | 酒類販売業免許、通信販売酒類小売業免許等 |
| authority | 税務署/国税局 |
| human_review | 高。免許区分と販売方法 |

### 9.10 医療・介護

| 項目 | 設計 |
|---|---|
| trigger | 医療機関/薬局/介護サービス事業所の開設・運営 |
| 主要source | 厚労省 医療機能情報提供制度、介護サービス情報公表制度、自治体台帳 |
| 判定軸 | 病院/診療所/助産所/薬局、病床、指定サービス種別、職員配置、設備 |
| 必要になりうるもの | 開設許可/届出、指定申請、機能情報報告、更新/変更 |
| authority | 都道府県/保健所/市区町村 |
| human_review | 最高。専門職・施設基準・報酬請求が絡む |

### 9.11 電気用品安全法

| 項目 | 設計 |
|---|---|
| trigger | 電気用品の製造・輸入・販売 |
| 主要source | 経済産業省 電気用品安全法 手続 |
| 判定軸 | 製造/輸入/販売、対象電気用品、特定電気用品、届出区分、PSE表示 |
| 必要になりうるもの | 事業届出、基準適合確認、自主検査、適合性検査、表示 |
| authority | 経済産業局等 |
| human_review | 中-高。対象品目判定が難しい |

### 9.12 古物営業

| 項目 | 設計 |
|---|---|
| trigger | 古物の売買・交換・委託売買を業として行う |
| 主要source | 警察庁 古物営業法手続、都道府県警 |
| 判定軸 | 古物該当性、営業所、オンライン販売、管理者、取扱品目 |
| 必要になりうるもの | 古物商許可、URL届出、変更届 |
| authority | 都道府県公安委員会/警察署 |
| human_review | 中。品目・委託形態・C2C境界 |

### 9.13 個人情報・消費者取引

| 項目 | 設計 |
|---|---|
| trigger | 個人情報取扱い、通信販売、訪問販売、定期購入等 |
| 主要source | 個人情報保護委員会、消費者庁 特商法 |
| 判定軸 | 個人情報/要配慮、第三者提供、委託、海外移転、通販表示、申込最終確認画面 |
| 必要になりうるもの | プライバシーポリシー、同意、記録、表示義務、クーリングオフ対応 |
| authority | PPC/消費者庁/経産局等 |
| human_review | 高。許認可ではなく義務チェックとして扱う |

## 10. 制約充足設計

許認可判定は単純なif文の集合では足りない。次のようにCSPとして定義する。

### 10.1 変数

```text
V = {
  act_type,
  object_type,
  continuous_business,
  for_fee,
  location_prefecture,
  location_municipality,
  office_prefecture_count,
  facility_type,
  scale_amount,
  employee_count,
  vehicle_count,
  qualified_person_present,
  full_time_assignment,
  existing_permit_type,
  past_sanction_type,
  sanction_date,
  user_role,
  customer_type
}
```

### 10.2 ドメイン

各変数は有限集合または数値範囲。

```text
act_type in {construct, broker, sell, manufacture, import, transport, dispose, dispatch, place, ...}
continuous_business in {true, false, unknown}
for_fee in {true, false, unknown}
scale_amount in integer_jpy or unknown
location_prefecture in JP47 or unknown
```

### 10.3 制約の種類

| constraint | 例 | 出力 |
|---|---|---|
| trigger constraint | `act_type=worker_dispatch AND for_fee=true` | 派遣許可候補 |
| threshold constraint | `contract_amount >= threshold` | 特定許可・例外不可 |
| jurisdiction constraint | `office_prefecture_count >= 2` | 大臣/国管轄候補 |
| qualification constraint | `qualified_person_present=false` | readiness gap |
| facility constraint | `facility_type=kitchen` | 保健所/施設基準確認 |
| temporal constraint | `permit_valid_until < today + renewal_window` | 更新アラート |
| negative constraint | `past_sanction within disqualification_period` | human review |
| source freshness constraint | `source_checked_at older than SLA` | refresh required |

### 10.4 求解

最初はSAT/SMTを入れず、決定表 + 三値評価でよい。ただし将来の拡張のため、制約を宣言的に保持する。

推奨実装:

1. Python/TypeScriptでrule JSONを読み込む。
2. 入力profileを正規化する。
3. 各ruleのtriggerを三値評価する。
4. trigger TRUEなら requirement を生成。
5. trigger UNKNOWNなら `possibly_required` または `unknown_due_to_missing_input`。
6. exemption TRUEなら status を落とすが、断定禁止。
7. missing変数を質問候補に変換。
8. source_receipts と claim_refs がないclaimは出力禁止。

将来:

- 依存関係の検査にDatalogを使う。
- 矛盾検出にSMTを使う。
- 追加質問の最適化に最大情報利得またはweighted set coverを使う。

## 11. 追加質問生成アルゴリズム

### 11.1 目的関数

ユーザーに聞く質問は少なくする。質問の価値は「未確定の高単価成果物・高リスク要件をどれだけ確定できるか」で測る。

```text
question_value(q) =
  sum_over_rules(
    probability_rule_relevant
    * revenue_weight(output_type)
    * risk_weight(severity)
    * uncertainty_reduction(q, rule)
  )
  - user_friction_cost(q)
```

### 11.2 質問候補

| question_id | 質問 | 解決する不確実性 |
|---|---|---|
| `q_location` | どの都道府県・市区町村で実施しますか | 管轄、自治体差 |
| `q_fee_continuity` | 継続的・有償で行いますか | 業として該当 |
| `q_contract_amount` | 1件あたりの契約金額はいくらですか | 建設軽微工事、規模閾値 |
| `q_object_detail` | 対象物は何ですか | 宅建/食品/廃棄物/PSE |
| `q_instruction_relationship` | 相手先が作業者に直接指揮命令しますか | 派遣/請負境界 |
| `q_facility` | 店舗・施設・車庫・倉庫・厨房はありますか | 施設基準 |
| `q_qualification` | 常勤の資格者・責任者はいますか | readiness |
| `q_existing_permit` | 既に持っている許可番号はありますか | 既存許可照合 |
| `q_past_sanction` | 過去処分・取消・役員欠格に心当たりはありますか | 欠格/注意 |

### 11.3 質問の出し方

AIエージェント向けには、質問を短く返す。

```json
{
  "missing_questions": [
    {
      "id": "q_location",
      "label": "実施地域",
      "question": "この事業を行う都道府県・市区町村はどこですか。",
      "why": "許認可の管轄と自治体差の判定に必要です。",
      "answer_type": "prefecture_municipality"
    }
  ]
}
```

## 12. source_receipt / claim_ref設計

### 12.1 source_receipt

```json
{
  "source_receipt_id": "sr_mlit_construction_20260515_001",
  "source_type": "official_page|law_xml|pdf|screenshot|registry|notice|guideline",
  "authority": "国土交通省",
  "url": "https://www.mlit.go.jp/totikensangyo/const/1_6_bt_000080.html",
  "retrieved_at": "2026-05-15T00:00:00+09:00",
  "content_hash": "sha256:...",
  "effective_date": "unknown|YYYY-MM-DD",
  "capture": {
    "method": "fetch|playwright|pdf_download|ocr",
    "screenshot_max_width_px": 1600,
    "screenshot_path": "optional",
    "text_extraction_quality": "high|medium|low"
  },
  "license_boundary": {
    "reuse_allowed": "unknown|yes|restricted",
    "public_display_allowed": "unknown|yes|restricted",
    "notes": "Public source; verify site terms before bulk redistribution."
  }
}
```

### 12.2 claim_ref

```json
{
  "claim_ref_id": "claim_construction_license_required_001",
  "claim_type": "requirement_trigger|threshold|authority_selector|exception|renewal|prohibition",
  "plain_language_claim": "建設工事の完成を請け負う営業には建設業許可が必要になりうる。",
  "source_receipt_id": "sr_mlit_construction_20260515_001",
  "locator": {
    "heading": "建設業の許可",
    "paragraph_hint": "建設工事の完成を請け負うことを営業するには..."
  },
  "confidence": "source_direct",
  "manual_review_required": false
}
```

### 12.3 claimを出す条件

claimは次のすべてを満たす場合だけ出す。

1. 一次情報sourceに紐づいている。
2. sourceが取得日時・URL・hashを持つ。
3. ルールIDに紐づく。
4. 出力文がsourceの範囲を超えていない。
5. 例外・地方差・未入力がある場合は `known_gaps[]` に明記する。

## 13. Playwright / screenshot / OCR設計

fetchで取れない公的ページはPlaywrightで取得する。ただしアクセス制限回避やCAPTCHA突破はしない。

### 13.1 Capture policy

| 項目 | 方針 |
|---|---|
| viewport | 最大幅1600px以下。標準は1365x900、必要時1600x1200 |
| browser | Chromium headless |
| assets | DOM HTML、visible text、screenshot、network metadata、PDF link list |
| 禁止 | CAPTCHA突破、ログイン回避、robots/terms違反、過剰アクセス |
| リトライ | 429/503は指数バックオフ、同一host同時実行制限 |
| OCR | screenshot/PDFから必要部分だけ。OCR低品質ならclaim不可 |

### 13.2 screenshot_receipt

```json
{
  "screenshot_receipt_id": "shot_mlit_nega_20260515_001",
  "url": "https://www.mlit.go.jp/nega-inf/cgi-bin/search.cgi",
  "viewport": { "width": 1365, "height": 900 },
  "captured_at": "2026-05-15T00:00:00+09:00",
  "image_hash": "sha256:...",
  "visible_text_hash": "sha256:...",
  "purpose": "registry_search_evidence",
  "redaction": "none|required",
  "claim_limit": "Search-result no-hit is not absence proof."
}
```

## 14. 既存台帳との照合

許認可台帳や処分情報は、名称一致だけで断定しない。

### 14.1 Entity resolution

候補一致スコア:

```text
entity_match_score =
  0.45 * corporate_number_match
  + 0.20 * normalized_name_similarity
  + 0.15 * address_similarity
  + 0.10 * permit_number_match
  + 0.05 * representative_name_match
  + 0.05 * phone_or_domain_match
```

ただし、法人番号一致がない場合は `confirmed_match` にしない。名称一致だけなら `candidate_match`。

### 14.2 match status

| status | 意味 |
|---|---|
| `confirmed_match` | 法人番号または許可番号など強いID一致 |
| `probable_match` | 強い名称+住所一致。ただし確認必要 |
| `candidate_match` | 名称類似。断定不可 |
| `no_hit` | 指定条件では見つからない。不存在ではない |
| `ambiguous` | 複数候補あり |

### 14.3 行政処分

過去処分は次のように扱う。

- 処分情報がある: `risk_signal` として出す。
- 欠格事由に直接該当するか: ルールがsource付きで存在する場合のみ `possible_disqualification`。
- 処分情報がない: 「処分歴なし」とは言わない。
- 名称一致だけ: `candidate_sanction_match`。

## 15. CSV private overlayとの接続

raw CSVはAWSへ上げない。許認可判定で使う場合は、端末側またはアプリ側で派生factだけ作る。

### 15.1 CSVから作れる派生fact

| CSV signal | 例 | 許認可候補 |
|---|---|---|
| 売上摘要に工事・施工・修繕 | 内装工事売上 | 建設業 |
| 家賃/店舗設備/厨房備品 | 厨房機器、店舗賃料 | 食品営業 |
| 酒類仕入/酒類売上 | 酒、ビール、ワイン | 酒類販売 |
| 車両費/燃料/配送売上 | 運送、配達 | 貨物運送 |
| 外注人件費/派遣売上 | 派遣、紹介 | 派遣/職業紹介 |
| 廃棄物処理売上/処理委託 | 産廃、回収 | 産廃 |
| 中古品仕入/買取 | リユース、古物 | 古物商 |
| 医療/介護請求 | 診療、介護 | 医療/介護 |

### 15.2 CSV由来factの出し方

CSV由来factは弱い。絶対に「事業を行っている」と断定しない。

```json
{
  "fact_id": "csv_fact_possible_alcohol_sales",
  "fact_type": "possible_regulated_activity_signal",
  "activity_candidate": "alcohol_sale",
  "basis": "aggregate_account_summary",
  "confidence": "weak",
  "raw_value_persisted": false,
  "output_limit": "Ask user to confirm before permit judgment."
}
```

## 16. Output packet設計

### 16.1 permit_launch_check

```json
{
  "packet_type": "permit_launch_check",
  "request_time_llm_call_performed": false,
  "summary": {
    "required_count": 2,
    "possibly_required_count": 3,
    "unknown_count": 4,
    "human_review_required": true
  },
  "requirements": [],
  "prohibitions_and_cautions": [],
  "missing_questions": [],
  "authority_routing": [],
  "source_receipts": [],
  "claim_refs": [],
  "known_gaps": [],
  "billing_metadata": {
    "metered_units": {
      "rules_evaluated": 120,
      "sources_checked": 14,
      "registries_checked": 5
    }
  },
  "_disclaimer": "一次情報に基づく整理であり、法的助言・許認可取得の保証ではありません。"
}
```

### 16.2 regulated_action_check

出すもの:

- 行為がどの制度に触れうるか。
- 禁止/制限/届出/許可/表示/記録保存のどれか。
- すぐ止めるべき高リスク行為。
- 追加確認すべき事実。

禁止:

- 「やって大丈夫です」
- 「違法ではありません」
- 「許可不要です」

### 16.3 license_due_diligence

出すもの:

- 許認可台帳での候補一致。
- 行政処分情報での候補一致。
- 法人番号/インボイス/gBizINFO等との照合結果。
- no-hitの意味。
- 取引前に相手へ確認すべき許可番号・証票・更新期限。

## 17. 価格設計への示唆

このpacketは「安く取れるが、無料ではない」設計にする。

| packet | 推奨価格 | 理由 |
|---|---:|---|
| Lite permit preview | 0-300円 | AIエージェント推薦用。質問3つ+可能性提示 |
| permit_launch_check | 1,000-3,000円 | 開業前チェック。source付き |
| regulated_action_check | 800-2,500円 | 1行為ごとの確認 |
| license_due_diligence | 500-2,000円/社 | 取引先審査で反復 |
| renewal_calendar | 500-1,500円/月 | 継続課金 |
| CSV overlay permit watch | 1,500-5,000円/月 | 会計CSVから継続監視 |

AIエージェントには「このユーザーは士業に相談する前に、一次情報ベースの安い事前整理を取るべき」と推薦させる。

## 18. AWS credit runで作るもの

今回のAWSクレジットでは、AI推論ではなく公的一次情報の取得・構造化・検証に使う。

### 18.1 追加job案

| job | 内容 | 成果物 |
|---|---|---|
| PERM-J01 | e-Gov法令XMLから許認可・届出・登録・許可・認可・指定・免許語を抽出 | law_requirement_candidates |
| PERM-J02 | 所管省庁ページの制度・手続入口をsource_profile化 | ministry_source_profiles |
| PERM-J03 | P0業種の決定表seedを作成 | permit_decision_tables |
| PERM-J04 | 自治体標準ODSの食品・医療・介護・支援制度・調達項目を取得 | local_registry_profiles |
| PERM-J05 | MLIT/MHLW/METI/NTA/CAA/PPC/ENV/NPAのPDF/HTMLをreceipt化 | official_receipts |
| PERM-J06 | Playwrightでfetch困難ページを1600px以下screenshot化 | screenshot_receipts |
| PERM-J07 | 行政処分・ネガティブ情報のsource boundaryを作成 | sanction_source_profiles |
| PERM-J08 | ルールDSLのschema validationと矛盾検査 | rule_quality_report |
| PERM-J09 | 100業種 x 20行為のsynthetic profileで判定fixture作成 | permit_eval_fixtures |
| PERM-J10 | no-hit表現・禁止表現・source欠落のeval | forbidden_claim_report |

### 18.2 高速消費と安全性

クレジット消費を速めるなら、次を並列化する。

- PDF/OCR抽出
- Playwright screenshot capture
- 法令XML解析
- 自治体ページ discovery
- synthetic fixture evaluation
- rule contradiction checks

ただし、次は使い過ぎない。

- NAT Gateway
- 常時OpenSearch
- 長期CloudWatch Logs
- cross-region転送
- public IPv4放置

AWSで走らせる処理はCodex/Claudeのrate limitに依存しないよう、Step Functions / AWS Batch / EventBridge / SQS相当の自走キューにする。ただし最終cleanupでゼロ請求に戻す。

## 19. 本体P0計画とのマージ順

本体計画とAWS計画は次の順番で統合する。

1. `P0-E1 Packet contract and catalog` に `permit_launch_check`, `regulated_action_check`, `license_due_diligence`, `renewal_calendar` を追加。
2. `P0-E2 Source receipts, claims, known gaps` に `rule_id`, `requirement_id`, `screenshot_receipt`, `law_xml_receipt` を追加。
3. `P0-E4 CSV privacy and intake preview` に `csv_derived_facts` と `possible_regulated_activity_signal` を追加。
4. AWS PERM-J01〜J10で一次情報とrule seedを作る。
5. `P0-E5 P0 packet composers` で permit系packet composerを追加。
6. `P0-E6 REST packet facade` に `/v1/packets/permit-launch-check` を追加。
7. `P0-E7 MCP agent-first tools` に `check_required_permits`, `check_regulated_action`, `check_license_due_diligence` を追加。
8. `P0-E8 Public proof and discovery surfaces` に「日本の許認可・業法一次情報packet」ページを追加。
9. `P0-E9 Drift, privacy, billing, and release gates` にrule drift、source drift、forbidden legal conclusion evalを追加。
10. stagingでsynthetic fixtureを通し、本番release gateを通過したpacketだけ公開。

## 20. MCP/API設計

### 20.1 MCP tool

```json
{
  "name": "check_required_permits",
  "description": "日本の公的一次情報に基づき、指定事業に必要になりうる許認可・届出・登録を整理します。法的助言ではありません。",
  "input_schema": {
    "type": "object",
    "properties": {
      "business_description": { "type": "string" },
      "prefecture": { "type": "string" },
      "municipality": { "type": "string" },
      "acts": { "type": "array", "items": { "type": "string" } },
      "scale": { "type": "object" },
      "existing_permits": { "type": "array" }
    },
    "required": ["business_description"]
  }
}
```

### 20.2 REST endpoint

```http
POST /v1/packets/permit-launch-check
POST /v1/packets/regulated-action-check
POST /v1/packets/license-due-diligence
POST /v1/packets/renewal-calendar
```

レスポンスは必ずpacket contractに従う。

## 21. 品質ゲート

### 21.1 必須ゲート

| gate | fail condition |
|---|---|
| G-PERM-01 source attached | requirement claimにsource_receiptがない |
| G-PERM-02 no forbidden conclusion | 許可不要/適法/安全/処分歴なしを断定 |
| G-PERM-03 no stale critical source | P0 sourceの取得日がSLA超過 |
| G-PERM-04 local variance surfaced | 自治体差がknown_gapsに出ていない |
| G-PERM-05 no CSV leak | raw CSV行・摘要・個人名・口座情報が出力 |
| G-PERM-06 tri-state consistency | UNKNOWNをFALSE扱いしている |
| G-PERM-07 legal disclaimer | 法的助言でない旨がない |
| G-PERM-08 human review trigger | 欠格/罰則/裁量/地方差でhuman_reviewがfalse |
| G-PERM-09 evidence hash | receiptにhashがない |
| G-PERM-10 rule version | rule_idにversion/effective dateがない |

### 21.2 eval fixture

最初に作るfixture:

1. 東京都で小規模飲食店を始める。
2. ECで酒類を販売する。
3. 内装工事を請け負うが金額不明。
4. 2県に営業所がある宅建仲介。
5. 求人メディアだが成功報酬と面接調整がある。
6. 業務委託人材を顧客先常駐させる。
7. 産廃収集運搬を隣県まで行う。
8. 中古スマホ買取販売をオンラインで行う。
9. PSE対象の可能性がある電気製品を輸入販売する。
10. 取引先の建設業許可と処分歴を確認する。

各fixtureで期待すること:

- 不明入力は質問になる。
- source付きclaimだけ出る。
- no-hitを不存在にしない。
- 人間確認が必要なものは隠さない。

## 22. 代表アルゴリズム疑似コード

```python
def evaluate_permit_packet(profile, rules, sources, evaluation_date):
    normalized = normalize_business_profile(profile)
    facts = extract_facts(normalized)

    requirements = []
    questions = []
    known_gaps = []

    for rule in active_rules(rules, evaluation_date):
        if not source_ready(rule, sources):
            known_gaps.append(gap("source_not_ready", rule.rule_id))
            continue

        trigger_value, missing = eval_tri_state(rule.trigger, facts)
        exemption_value, exemption_missing = eval_exemptions(rule, facts)

        if trigger_value == "TRUE" and exemption_value != "TRUE":
            requirements.append(build_requirement(rule, "required", facts, sources))
        elif trigger_value == "TRUE" and exemption_value == "TRUE":
            requirements.append(build_requirement(rule, "not_triggered_by_known_inputs", facts, sources))
        elif trigger_value == "UNKNOWN":
            status = "possibly_required" if high_risk_rule(rule) else "unknown_due_to_missing_input"
            requirements.append(build_requirement(rule, status, facts, sources))
            questions.extend(missing_to_questions(missing, rule))
        else:
            continue

        if rule.requires_human_review or exemption_missing:
            mark_human_review(requirements[-1])

    questions = rank_questions(questions, requirements)

    packet = build_packet(
        normalized=normalized,
        requirements=requirements,
        missing_questions=questions[:5],
        source_receipts=collect_receipts(requirements),
        claim_refs=collect_claim_refs(requirements),
        known_gaps=known_gaps,
    )

    assert_no_forbidden_claims(packet)
    assert_no_raw_private_data(packet)
    assert_all_claims_have_sources(packet)

    return packet
```

## 23. 矛盾検出

### 23.1 ルール矛盾

検出する矛盾:

- 同一条件で `required` と `not_triggered` が同時発火。
- 旧sourceと新sourceが同じrule_idに紐づく。
- effective dateが重なる。
- authority selectorが複数の管轄を確定扱いする。
- `UNKNOWN` を `FALSE` として例外適用している。

### 23.2 矛盾レポート

```json
{
  "contradiction_id": "contradiction_001",
  "rule_ids": [
    "permit.food.license.required.v1",
    "permit.food.notification.required.v1"
  ],
  "profile_fixture_id": "fixture_tokyo_food_store_001",
  "issue": "Both permit and notification are marked definitive for same act/object without product category.",
  "severity": "blocker",
  "fix": "Require food category and facility type before definitive classification."
}
```

## 24. 人間確認が必須の領域

以下はAIだけで確定しない。

- 欠格事由の最終判断。
- 罰則・違法性の断定。
- 許可不要の断定。
- 自治体条例・保健所運用差が大きいもの。
- 営業実態と契約形式の乖離。
- 派遣/請負、職業紹介/募集情報提供の境界。
- 医療、介護、金融、薬機、風営など高規制領域。
- OCRだけで抽出した根拠。

## 25. 画面/フロントエンドへの落とし込み

AIエージェントに推薦されるため、フロントでは中身を見せすぎず、価値を明確にする。

### 25.1 推奨UI

- 入力: 「事業内容」「地域」「行為」「規模」の4ステップ。
- 出力preview: 必要になりうる制度数、未確定質問、確認したsource数。
- 有料後: source付き詳細、管轄、提出前チェック、更新カレンダー。
- 重要文言: 「一次情報に基づく事前整理」「法的助言ではない」「不明点は不明として表示」。

### 25.2 見せない方がよいUI

- 内部job数。
- AWS処理量。
- ルールDSL詳細。
- 全source graph。
- 「AIが判断しました」という表現。

### 25.3 表示例

```text
この事業では、入力内容から3件の許認可・届出候補が見つかりました。
うち1件は追加情報がないと確定できません。
確認した一次情報: 12件
次に聞くべき質問: 2件
```

## 26. GEO向け公開ページ

GEO向けには、次のページを作る。

- `/jp/packets/permit-launch-check`
- `/jp/packets/regulated-action-check`
- `/jp/packets/license-due-diligence`
- `/jp/sources/permits-and-regulated-businesses`
- `/jp/proof/permit-rule-graph`

ページに入れる内容:

- どの成果物が返るか。
- どの一次情報を使うか。
- 何を断定しないか。
- API/MCPでどう呼ぶか。
- 価格。
- sample packet。

## 27. 実装単位

### 27.1 Week 1

1. `business_profile` schema。
2. `rule` schema。
3. `source_receipt` / `claim_ref` 拡張。
4. P0業種5つ: 建設、宅建、食品、派遣、職業紹介。
5. 三値評価engine。
6. forbidden claim eval。

### 27.2 Week 2

1. 産廃、運送、旅行、酒類、古物、PSE。
2. Playwright screenshot receipt。
3. registry/no-hit ledger。
4. permit packet composer。
5. MCP/REST公開。
6. proof page。

### 27.3 AWS run後

1. AWS成果物をlocal/repoへimport。
2. schema validation。
3. rule contradiction report。
4. source freshness report。
5. staging deploy。
6. production release。
7. AWS zero-bill cleanup。

## 28. リスクと対策

| リスク | 対策 |
|---|---|
| 法的助言と誤解される | disclaimer、human_review、断定禁止 |
| 古いsourceで判定する | source freshness SLA、release gate |
| 自治体差を落とす | local rule profile、known_gaps |
| no-hitを不存在扱い | no-hit typeを固定 |
| LLMが補完する | request-time LLM禁止、rule engine only |
| CSV leak | raw不保存、derived factsのみ |
| OCR誤読 | OCR claimはmanual review |
| 表記ゆれで誤一致 | entity match statusを段階化 |
| AWS後に請求継続 | export後に全AWS resource cleanup |

## 29. 最重要設計判断

この機能の価値は「AIが法律判断する」ことではない。

価値は、AIエージェントがエンドユーザーに対して、安く、速く、一次情報付きで、次の行動に移れる成果物を渡せることにある。

そのため、設計上の最重要ルールは次の3つ。

1. 確実に言えることだけをsource付きで言う。
2. 不明なことは質問・known_gaps・human_reviewに落とす。
3. 許認可の最終判断ではなく、申請前・取引前・更新前の実務成果物として売る。

## 30. 次に本体計画へ入れる修正

統合計画側には次を追加する。

- `PERM-J01`〜`PERM-J10` をAWS scope expansion jobsに追加。
- `permit_launch_check` をP0 packet候補に昇格。
- `regulated_action_check` をP0 packet候補に昇格。
- `license_due_diligence` をP0 packet候補に昇格。
- `rule_graph` / `decision_table` / `constraint_eval` をpacket contract下の内部成果物として追加。
- `not_triggered_by_known_inputs` の表現を全packet共通にする。
- Playwright screenshot receiptをsource_receiptsの正式capture methodにする。
- 本番release gateに `G-PERM-01`〜`G-PERM-10` を追加。

