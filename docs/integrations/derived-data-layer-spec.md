# jpcite Derived Data Layer Spec

Status: draft  
Date: 2026-05-05  
Scope: 深い回答を作るための派生データレイヤー仕様。価格、unit、課金導線は対象外。

## 1. Purpose

この仕様は、jpcite の検索結果、Evidence Packet、法人 DD、申請キット、月次監視を「候補一覧」から「業務で判断しやすい完成物」に変えるための派生データ構造を定義する。

中心は次の 6 レイヤー。

| Layer | 役割 |
|---|---|
| `program_decision_layer` | 制度候補を顧問先・法人・案件ごとの提案順、勝ち筋、不足情報に変換する |
| `corporate_risk_layer` | 法人番号起点で公的リスク、DD 質問、時系列確認点を束ねる |
| `source_quality_layer` | 出典の鮮度、引用位置、検証状態、欠落を回答 UI に出せる形にする |
| `document_requirement_layer` | 公募要領と様式を、必要書類、対象経費、提出順、ヒアリング項目に変換する |
| `monitoring_delta_layer` | 前回 packet からの制度、法令、処分、法人状態の差分を検出する |
| `private_overlay_inputs` | 顧客固有の非公開情報を公開 corpus に重ね、回答を一般論から対象者別にする |

## 2. Non-Goals

- 価格、課金単位、無料枠、conversion event は扱わない。
- 法律、税務、申請可否の最終判断は扱わない。出力は根拠付きの候補、確認範囲、不足質問に限定する。
- 公開 corpus と顧客 private data を同じ正本に混ぜない。private data は overlay として扱う。
- LLM 生成本文の保存仕様は扱わない。ここでは LLM が読む構造化材料を定義する。

## 3. Common Contract

全レイヤーは次を返せる必要がある。

| Field | Meaning |
|---|---|
| `layer_name` | この仕様上のレイヤー名 |
| `subject_kind` | `program`, `houjin`, `private_overlay`, `watch`, `query` など |
| `subject_id` | 制度 ID、法人番号、overlay ID、watch ID など |
| `corpus_snapshot_id` | 公開 corpus の時点 |
| `computed_at` | 派生値を作った時刻 |
| `source_fact_ids` | 判断に使った fact ID 配列 |
| `source_document_ids` | 根拠文書 ID 配列 |
| `quality_tier` | `S`, `A`, `B`, `C`, `X` |
| `known_gaps` | 未収録、未検証、古い、根拠不足などの明示 |

値が不明な場合もキーを省略しない。`null` と `known_gaps` を同時に返す。

## 4. `program_decision_layer`

制度候補を「この顧問先に最初に提案すべき順」に変えるレイヤー。`programs` の検索順位ではなく、対象者の属性、締切、必要書類、採択シグナル、併用制約、未知条件を合わせて decision-ready な候補にする。

### fields

| Field | Type | Meaning |
|---|---|---|
| `program_id` | string | `programs.unified_id` / `jpi_programs.unified_id` |
| `subject_entity_id` | string/null | 公開 entity に解決できる対象法人、地域、業種など |
| `private_overlay_id` | string/null | 顧客固有入力を使った場合の overlay ID |
| `fit_score` | number/null | 所在地、業種、規模、投資目的、制度目的の適合度 |
| `win_signal_score` | number/null | 採択統計、類似採択、地域/業種密度から見た勝ち筋 |
| `urgency_score` | number/null | 締切、次回公募、社内準備期間から見た緊急度 |
| `documentation_risk_score` | number/null | 必要書類の多さ、様式未確認、証憑不足のリスク |
| `eligibility_gap_count` | integer | 必須条件に対して不足している入力軸の数 |
| `blocking_rule_count` | integer | 明確に block になった eligibility/exclusion rule 数 |
| `unknown_rule_count` | integer | 根拠不足または入力不足で unknown の rule 数 |
| `deadline_days_remaining` | integer/null | 直近締切までの日数 |
| `changed_since_last_packet` | boolean/null | 同じ対象の前回 packet から重要項目が変わったか |
| `rank_reason_codes` | string[] | `deadline_near`, `strong_industry_match`, `missing_invoice_status` など |
| `next_questions` | object[] | 顧客に聞くべき質問。field、reason、blocking/semi-blocking を持つ |
| `recommended_action` | string | `propose_now`, `collect_docs`, `watch`, `defer`, `exclude`, `broaden_search` |
| `source_fact_ids` | string[] | score と reason の根拠 fact |
| `known_gaps` | object[] | 未確認の制度条件、未収録の公募回、PDF 未取得など |

### source tables

| Source table/view | Role |
|---|---|
| `programs` / `jpi_programs` | 制度の正本、地域、制度種別、期間、source URL |
| `am_recommended_programs` | 法人ごとの既存推奨順位、reason_json |
| `am_program_eligibility_predicate` / `v_am_program_required_predicates` | eligibility gap、block、unknown の判定 |
| `exclusion_rules` / `compat_matrix` / `rule` | 併用、排他、前提認定、defer 理由 |
| `am_program_adoption_stats` | 採択件数、採択率、業種/地域分布 |
| `case_studies` / `jpi_adoption_records` | 類似採択、採択企業特徴、勝ち筋 signal |
| `am_region_program_density` / `am_region_program_density_breakdown` | 地域 x 業種の制度密度 |
| `am_program_calendar_12mo` / `am_application_round` | 締切、募集中、次回公募 |
| `am_program_documents` | 書類リスク、様式 URL、必要証憑 |
| `source_document` / `extracted_fact` | 引用位置付き根拠 |
| `private_overlay` | 決算月、投資予定、社内優先度、過去申請など |

### artifact sections improved

| Artifact section | Improvement |
|---|---|
| 候補ランキング | 一般的な検索順位ではなく、対象者別の提案順になる |
| なぜこの制度か | score ではなく reason code と根拠 fact で説明できる |
| 申請可否プリスクリーン | block、unknown、入力不足を分けて表示できる |
| 次に聞く質問 | `next_questions` からヒアリング表を作れる |
| 顧問先向け一言 | `recommended_action` と rank reason から短文提案を作れる |
| 0 件時の coverage report | `broaden_search` と known gaps で「該当なし」と断定しない |

### freshness

- 日次: 締切、募集状態、source liveness、直近変更。
- 週次: 採択統計、類似採択、地域/業種密度、推薦 score。
- 顧客入力更新時: `private_overlay_id` に紐づく fit、gap、next_questions を再計算する。
- `corpus_snapshot_id` が変わった場合、前回 packet との差分比較を優先し、古い score をそのまま使わない。

### quality caveats

- `fit_score` は最終採択可能性ではない。入力と収録 rule に対する適合度である。
- `win_signal_score` は採択保証ではない。採択統計がない制度では `null` にし、`known_gaps` に denominator 不足を出す。
- eligibility predicate が未抽出の軸は「制約なし」ではなく `unknown` とする。
- `private_overlay` が未検証または古い場合、対象者別 ranking は `quality_tier` を下げる。
- 締切や様式は source freshness が低い場合、回答本文で一次確認を促す。

## 5. `corporate_risk_layer`

法人番号を起点に、インボイス、行政処分、採択履歴、調達、EDINET、官報、名称変更、関連法人を DD の確認項目へ変換するレイヤー。

### fields

| Field | Type | Meaning |
|---|---|---|
| `houjin_no` | string | 13 桁法人番号 |
| `resolved_entity_id` | string/null | jpcite 内の法人 entity ID |
| `invoice_status_signal` | object/null | 適格請求書登録状態、取消/失効/未登録 signal |
| `enforcement_signal` | object/null | 行政処分、返還、取消、指名停止などの signal |
| `public_funding_dependency_signal` | object/null | 採択件数、採択額、特定制度依存の signal |
| `procurement_signal` | object/null | 入札/落札、公共調達依存、所管集中の signal |
| `edinet_signal` | object/null | EDINET 開示、上場/非上場、提出書類、重要変更 signal |
| `kanpou_signal` | object/null | 官報上の公告、破産、合併、決算公告など |
| `name_change_signal` | object/null | 商号、所在地、代表者等の変更履歴 signal |
| `related_entity_signal` | object/null | 関連法人、同一住所、代表者/名称近似、ID bridge |
| `risk_timeline` | object[] | 日付順の public event 配列 |
| `dd_questions` | object[] | 追加 DD で確認すべき質問 |
| `risk_reason_codes` | string[] | `recent_enforcement`, `invoice_unregistered`, `name_changed` など |
| `source_fact_ids` | string[] | signal の根拠 fact |
| `known_gaps` | object[] | EDINET 対象外、官報未照合、法人番号未確定など |

### source tables

| Source table/view | Role |
|---|---|
| `houjin_master` | 法人番号、商号、所在地、法人基本情報 |
| `entity_id_bridge` | 法人番号、gBizINFO、インボイス番号、EDINET code などの接続 |
| `invoice_registrants` / `jpi_invoice_registrants` / `invoice_registration_history` | 適格請求書登録状態 |
| `enforcement_cases` / `am_enforcement_detail` | 行政処分、返還、取消、金額、法的根拠 |
| `am_enforcement_industry_risk` | 業種 x 地域の処分傾向 |
| `case_studies` / `jpi_adoption_records` | 採択履歴、採択制度、採択額 |
| `bids` / `procurement_notice` / `procurement_result` | 公共調達、落札、公告 |
| `edinet_documents` | EDINET 提出書類、期間、提出日 |
| `kanpou_notice` | 官報公告、破産、合併、公告種別 |
| `am_houjin_360_snapshot` | 月次で凍結した 360 signal と履歴 |
| `source_document` / `extracted_fact` | signal の出典と引用位置 |

### artifact sections improved

| Artifact section | Improvement |
|---|---|
| 法人 360 サマリー | 断片情報ではなく signal と時系列で並ぶ |
| 公的 DD 質問 | `dd_questions` で追加確認をそのまま列挙できる |
| 稟議添付リスク注記 | 事実、未確認、要ヒアリングを分けられる |
| 取引先/投資先監視 | 重要イベントを前回 snapshot から比較できる |
| 制度推薦の抑制 | 処分や invoice 状態を `program_decision_layer` の block/unknown に渡せる |

### freshness

- 日次: EDINET、官報、重要な行政処分、調達公告。
- 月次: 法人番号全件、インボイス全件、法人 360 snapshot。
- 週次: 採択履歴、処分詳細の再照合、関連法人候補。
- 法人番号解決が曖昧な場合、signal を確定せず `known_gaps` に候補法人を出す。

### quality caveats

- 同名法人、旧商号、支店名は誤結合リスクが高い。法人番号が未確定なら risk signal は `inferred` 扱いにする。
- EDINET は対象会社が限定されるため、未検出は「開示なし」ではなく「EDINET corpus では未検出」とする。
- 官報、処分、調達は網羅性が source ごとに異なる。未収録領域は `known_gaps` に出す。
- `public_funding_dependency_signal` は依存度の兆候であり、財務 DD の代替ではない。
- `related_entity_signal` は候補提示に留め、支配関係や実質所有者を断定しない。

## 6. `source_quality_layer`

回答の深さを支える trust 表示レイヤー。免責文ではなく、確認範囲、出典鮮度、引用位置、検証状態を artifact の UI と本文に出せる形にする。

### fields

| Field | Type | Meaning |
|---|---|---|
| `source_document_id` | string | 文書台帳 ID |
| `source_url` | string | 一次資料または取得元 URL |
| `canonical_url` | string/null | 正規化 URL |
| `publisher` | string/null | 所管、発行者 |
| `document_kind` | string | `html`, `pdf`, `csv`, `json`, `xlsx` など |
| `source_fetched_at` | string/null | 初回または直近取得日時 |
| `last_verified` | string/null | URL と内容を最後に再確認した日時 |
| `http_status` | integer/null | 再検証時の HTTP status |
| `content_hash` | string/null | 文書内容 hash |
| `license` | string/null | 再配布、引用、表示可否 |
| `verification_status` | string | `verified`, `inferred`, `stale`, `unknown` |
| `freshness_bucket` | string | `fresh`, `aging`, `stale`, `unknown` |
| `quote_coverage` | object/null | page/span/selector 付き fact の割合 |
| `confirming_source_count` | integer | 同じ fact を支える独立 source 数 |
| `cross_source_agreement` | string/null | `agree`, `conflict`, `single_source`, `unknown` |
| `quality_tier` | string | `S`, `A`, `B`, `C`, `X` |
| `known_gaps` | object[] | PDF 未抽出、URL 死活未確認、license 不明など |

### source tables

| Source table/view | Role |
|---|---|
| `source_document` | URL ではなく取得済み文書の正本 |
| `artifact` | PDF/HTML snapshot/raw fetch/report の保存物 |
| `extracted_fact` | quote、page、span、selector 付き fact |
| `am_source` | 既存 source freshness と provenance seed |
| `am_entity_facts` | 既存 fact seed |
| `citation_verification` | URL 到達性、引用検証、verified/stale 状態 |
| `am_data_quality_snapshot` | freshness、license、cross-source KPI の集約 |
| `corpus_snapshot` | 回答時点と row checksum |
| `evidence_packet_item` | packet 内 item と source/fact の接続 |

### artifact sections improved

| Artifact section | Improvement |
|---|---|
| 確認範囲 | 公式 URL、取得日、PDF、様式、未確認先を構造化して表示できる |
| 出典表 | claim-to-source、取得日、品質 tier、license を並べられる |
| 引用候補 | quote/page/span により人間の引用確認時間を減らせる |
| known gaps | 欠陥ではなく「収録範囲」として表示できる |
| audit seal | corpus snapshot と source hash を説明できる |

### freshness

- URL liveness と `last_verified`: 日次から週次。行政の重要 source は日次優先。
- PDF/HTML content hash: 取得時と再検証時に比較。
- `am_data_quality_snapshot`: 日次集計。
- `corpus_snapshot`: packet 作成時に固定し、回答の再現性に使う。

### quality caveats

- `verified` は URL と引用候補の確認状態であり、制度適用の正しさを保証しない。
- `stale` は即不正ではない。古いが参照可能な source と、到達不能な source を分ける。
- `confirming_source_count > 1` でも、同一機関の転載であれば独立確認とはみなさない。
- PDF OCR やページ抽出は span ずれが起きるため、quote が短すぎる場合は tier を上げない。
- license が不明な source は回答本文に要約中心で使い、長い引用を避ける。

## 7. `document_requirement_layer`

公募要領、様式、FAQ、募集要項から、申請前に必要な書類、対象経費、提出順、顧客ヒアリング項目を作るレイヤー。

### fields

| Field | Type | Meaning |
|---|---|---|
| `program_id` | string | 対象制度 ID |
| `requirement_id` | string | requirement row ID |
| `doc_name` | string | 書類名 |
| `doc_kind` | string/null | `申請書`, `計画書`, `見積書`, `登記簿`, `納税証明`, `財務諸表`, `同意書`, `その他` |
| `yoshiki_no` | string/null | 様式番号 |
| `is_required` | boolean | 必須か任意か |
| `submission_phase` | string/null | 事前相談、申請時、交付決定後、実績報告、請求時など |
| `applicant_action` | string/null | 取得、作成、顧客確認、窓口確認、専門家確認 |
| `customer_input_required` | object[] | 顧客から聞く必要がある項目 |
| `depends_on_predicate_ids` | string[] | 条件付きで必要になる eligibility predicate |
| `target_expense_refs` | object[] | 対象経費、対象外経費、引用位置 |
| `url` | string/null | 様式または要項 URL |
| `source_clause_quote` | string/null | 根拠 quote |
| `page_number` | integer/null | PDF ページ |
| `span_start` / `span_end` | integer/null | 引用位置 |
| `common_defect_codes` | string[] | よくある不備、未添付、日付不整合など |
| `known_gaps` | object[] | 様式 URL 未確認、ページ未抽出、対象経費未抽出など |

### source tables

| Source table/view | Role |
|---|---|
| `am_program_documents` | 制度 x 書類の正規化テーブル |
| `program_documents` | 既存の公募要領、様式、PDF 入口 |
| `source_document` / `artifact` | 公募要領 PDF、様式ファイル、HTML snapshot |
| `extracted_fact` | 書類名、対象経費、提出期限、窓口の引用位置 |
| `am_program_eligibility_predicate` | 条件付き書類、前提認定、規模条件 |
| `am_program_calendar_12mo` / `am_application_round` | 提出時期、公募回、締切 |
| `rule` | 併用時の追加書類、排他、事前認定 |
| `private_overlay` | 顧客が既に持っている書類、決算月、投資計画 |

### artifact sections improved

| Artifact section | Improvement |
|---|---|
| 申請キット | URL 集ではなく、提出物、取得元、作成順に変わる |
| 顧客ヒアリング表 | `customer_input_required` から質問を生成できる |
| 対象経費確認 | quote/page/span 付きで対象、対象外、不明を分けられる |
| 不備リスク | `common_defect_codes` と不足書類で事前チェックができる |
| 行政書士/補助金コンサル向け作業順 | phase ごとに事前相談から実績報告まで並べられる |

### freshness

- 公募要領 PDF、様式 URL: 週次再検証。締切前 30 日以内は日次優先。
- 公募回、提出期間: `am_program_calendar_12mo` の日次/夜間更新を優先。
- 対象経費、必要書類抽出: PDF hash が変わったら再抽出。
- 顧客が「保有済み書類」を更新した場合、欠落リストを即再計算する。

### quality caveats

- 公募要領と様式が別 PDF の場合、片方だけ verified でも全体を verified にしない。
- PDF から抽出できない表、脚注、別紙は `known_gaps` として残す。
- 必要書類は申請者属性で変わる。`depends_on_predicate_ids` が unresolved の場合は必須/任意を断定しない。
- `target_expense_refs` は対象経費の説明であり、実際の支出可否の最終判断ではない。
- 自治体や窓口の運用で追加書類が求められる場合があるため、窓口確認欄を残す。

## 8. `monitoring_delta_layer`

保存検索、watch、前回 Evidence Packet、月次 snapshot を比較し、何が変わり、どの顧問先・法人・制度に影響するかを返すレイヤー。

### fields

| Field | Type | Meaning |
|---|---|---|
| `delta_id` | string | 差分イベント ID |
| `watch_id` | string/null | customer watch ID |
| `saved_search_id` | string/null | saved search ID |
| `subject_kind` | string | `program`, `houjin`, `law`, `tax_ruleset`, `source`, `query` |
| `subject_id` | string | 対象 ID |
| `previous_packet_id` | string/null | 比較元 packet |
| `current_packet_id` | string/null | 比較先 packet |
| `previous_corpus_snapshot_id` | string/null | 比較元 snapshot |
| `current_corpus_snapshot_id` | string | 比較先 snapshot |
| `delta_kind` | string | `deadline_changed`, `new_program`, `status_changed`, `source_changed`, `enforcement_detected`, `invoice_status_changed`, `law_amended` など |
| `severity` | string | `info`, `watch`, `action`, `urgent` |
| `changed_fields` | object[] | field、old、new、source、confidence |
| `deadline_days_remaining` | integer/null | 締切が関係する場合の日数 |
| `affected_private_overlay_ids` | string[] | 影響する顧問先/案件 overlay |
| `recommended_next_action` | string/null | `notify_client`, `refresh_application_kit`, `ask_question`, `ignore` など |
| `source_fact_ids` | string[] | 差分の根拠 fact |
| `known_gaps` | object[] | baseline 不在、source stale、比較不能など |

### source tables

| Source table/view | Role |
|---|---|
| `saved_searches` | 検索条件、frequency、profile fan-out |
| `customer_watches` / `watchlist` | 法人、制度、source、地域の監視対象 |
| `evidence_packet` / `evidence_packet_item` | 前回回答と比較対象 |
| `corpus_snapshot` | snapshot 差分の基準 |
| `am_amendment_diff` | 制度、法令、source field の差分 |
| `am_program_calendar_12mo` | 締切接近、公募状態変化 |
| `am_tax_amendment_history` | 税制改正、延長、sunset |
| `source_document` / `citation_verification` | source hash、URL 到達性、stale 化 |
| `enforcement_cases` / `am_enforcement_detail` | 新規処分、返還、取消 |
| `invoice_registration_history` | インボイス登録状態の変更 |
| `private_overlay` | 差分が影響する顧客/案件 |

### artifact sections improved

| Artifact section | Improvement |
|---|---|
| 月次公的イベント監視 | 前回から変わった点だけを並べられる |
| 顧問先ダイジェスト | 影響する顧問先と次アクションを出せる |
| 法人 DD 監視 | 新規処分、invoice 状態、官報/EDINET 変化を拾える |
| 申請キット更新 | PDF/様式 hash 変更時に再確認を促せる |
| 税制改正インパクトメモ | 改正、延長、sunset を対象者別に通知できる |

### freshness

- 差分生成は watch frequency に従う。daily、weekly、monthly を想定する。
- 締切 14 日以内、処分検知、invoice 取消、source 404 は urgent queue に載せる。
- baseline packet がない初回は `delta_kind=baseline_created` とし、変更とは扱わない。
- snapshot が飛んだ場合は field-level diff ではなく packet-level rebaseline を優先する。

### quality caveats

- 差分は「jpcite の収録 snapshot 間の差」であり、現実世界の全変更を保証しない。
- 前回 source が stale または取得不能だった場合、old/new 比較の confidence を下げる。
- PDF hash 変更は重要だが、本文上の意味変更とは限らない。抽出 fact の変化と分ける。
- 顧客 overlay の対象者属性が古いと、affected 判定が過大/過小になる。
- 初回 baseline なしで「新規」と断定しない。

## 9. `private_overlay_inputs`

公開 corpus の上に顧客固有情報を重ねる入力レイヤー。税理士、補助金コンサル、金融機関、M&A/VC が「この会社ならどうか」を判断するための非公開コンテキストを扱う。

### fields

| Field | Type | Meaning |
|---|---|---|
| `private_overlay_id` | string | overlay row ID |
| `api_key_hash` | string | 顧客/親 API key の分離境界 |
| `customer_scope_id` | string/null | 事務所、顧問先群、部門などの scope |
| `client_profile_id` | string/null | 顧問先 profile ID |
| `overlay_kind` | string | `client_profile`, `investment_plan`, `application_status`, `internal_rule`, `note`, `mapping` |
| `houjin_no` | string/null | 解決済み法人番号 |
| `customer_entity_ref` | string/null | 顧客側管理 ID |
| `display_name` | string/null | 顧客内表示名 |
| `prefecture` / `city` | string/null | 所在地入力 |
| `jsic_code` / `industry_text` | string/null | 業種入力 |
| `capital_yen` | integer/null | 資本金 |
| `employee_count` | integer/null | 従業員数 |
| `fiscal_year_end_month` | integer/null | 決算月 |
| `invoice_status_override` | string/null | 顧客が確認済みの invoice 情報。公開 corpus と矛盾する場合は conflict にする |
| `investment_plan_json` | object/null | 投資目的、予定日、金額、設備、拠点、資金使途 |
| `past_adopted_program_ids` | string[] | 既採択、申請済み、申請予定制度 |
| `internal_rule_json` | object/null | 社内で除外する制度、地域、リスク方針 |
| `status_json` | object/null | 対応済み、確認中、申請予定、顧客確認待ち |
| `consent_scope` | string | `single_request`, `saved_profile`, `watch`, `enterprise` |
| `verified_by_customer_at` | string/null | 顧客が入力を確認した日時 |
| `retention_until` | string/null | 保持期限 |
| `source_trace` | object/null | CSV import、UI、API、CRM などの入力経路 |
| `known_gaps` | object[] | 未入力、古い、法人番号未照合、自己申告など |

### source tables

| Source table/view | Role |
|---|---|
| `private_overlay` | 顧客固有情報の正本 |
| `client_profiles` | 顧問先単位の profile、saved search fan-out |
| `saved_searches.profile_ids_json` | 顧問先別ダイジェスト対象 |
| `customer_watches` / `watchlist` | overlay を使う継続監視対象 |
| `usage_events.client_tag` | 顧問先タグ、利用経路の監査補助 |
| `houjin_master` / `entity_id_bridge` | 公開法人情報への照合 |
| `program_decision_layer` | overlay を使った fit/gap/next_questions の消費先 |
| `monitoring_delta_layer` | overlay 対象者への差分通知 |

### artifact sections improved

| Artifact section | Improvement |
|---|---|
| 顧問先別チャンスリスト | 決算月、投資予定、所在地、業種を反映できる |
| 補助金プリスクリーン | 入力済み属性で eligibility gap を減らせる |
| 申請キット | 保有済み書類、投資内容、提出希望時期を反映できる |
| 金融機関向け稟議シート | 資金使途、設備投資、社内ルールを制度候補と並べられる |
| 月次監視 | 顧客ごとに影響する差分だけを通知できる |
| 0 件時の質問 | 何が未入力だから候補が狭いかを説明できる |

### freshness

- 顧客入力は customer-driven。更新時に対象 overlay の decision/delta を即再計算する。
- `verified_by_customer_at` が 90 日を超えた profile は `aging`、180 日超は `stale` として扱う。
- 投資予定、決算月、申請状況は watch/digest のたびに stale 判定を行う。
- 公開 corpus と矛盾する入力は上書きせず、`conflict` として両方の根拠を残す。

### quality caveats

- private overlay は自己申告情報であり、公開 source で verified された fact とは区別する。
- 顧客間で overlay を共有しない。`api_key_hash` と `customer_scope_id` を分離境界にする。
- `invoice_status_override` や申請状況は公開 corpus と矛盾しうる。矛盾は ranking に使う前に `known_gaps` へ出す。
- 古い投資計画や決算月を使うと、緊急度と fit が誤る。
- PII や秘密情報を Evidence Packet の公開再利用 cache に混ぜない。

## 10. Layer Composition

完成物は 1 レイヤーだけで作らない。標準の組み合わせは次の通り。

| Artifact | Required layers |
|---|---|
| 顧問先一括チャンスリスト | `private_overlay_inputs`, `program_decision_layer`, `source_quality_layer`, `monitoring_delta_layer` |
| 補助金 採択可能性・類似採択分析 | `program_decision_layer`, `source_quality_layer`, `document_requirement_layer` |
| 公募要領読み込み済み申請キット | `document_requirement_layer`, `program_decision_layer`, `source_quality_layer`, `private_overlay_inputs` |
| 法人 360 公的 DD パック | `corporate_risk_layer`, `source_quality_layer`, `monitoring_delta_layer` |
| 稟議添付 公的支援・リスクシート | `program_decision_layer`, `corporate_risk_layer`, `source_quality_layer`, `private_overlay_inputs` |
| 月次公的イベント監視 | `monitoring_delta_layer`, `source_quality_layer`, `private_overlay_inputs` |

## 11. Minimum Viable Build Order

1. `source_quality_layer` を Evidence Packet と全 artifact の共通表示に接続する。
2. `program_decision_layer` を `am_program_eligibility_predicate`, `am_program_documents`, `am_program_calendar_12mo`, `private_overlay` から作る。
3. `corporate_risk_layer` を `am_houjin_360_snapshot`, invoice, enforcement, adoption, ID bridge から作る。
4. `document_requirement_layer` を PDF hash 変更時に再抽出できるようにする。
5. `monitoring_delta_layer` を saved search/watch と packet baseline に接続する。
6. `private_overlay_inputs` を customer scope と retention を持つ入力正本にし、公開 corpus cache と分離する。
