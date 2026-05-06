# jpcite Dual CLI Value Growth Loop 2026-05-06

このファイルは、2つの別CLIに同じ内容を貼って同時実行するための大規模情報収集・情報基盤強化・機能強化プロンプトです。

延べ300エージェント程度を前提に、2つのCLIが重複せず、片方は情報基盤、片方は顧客価値・出力・GEO・機能化を深掘りします。両CLIは同じファイルを読んでよいです。最初に自分のslotをclaimし、以後はslotに応じて担当を変えてください。

## 実行方法

2つのCLIそれぞれで、同じコマンドを貼ってください。

```text
cd /Users/shigetoumeda/jpcite
/loop tools/offline/INFO_COLLECTOR_VALUE_GROWTH_DUAL_CLI_300_AGENTS_2026-05-06.md
```

## 絶対目的

jpciteを「補助金検索API」ではなく、AI、士業、BPO、会社顧問、金融、M&A、監査/DDが、日本企業や制度を扱う時に最初に叩く公的根拠レイヤーにする。

狙う価値は、外部LLMの料金削減保証ではありません。狙う価値は以下です。

- 会社・制度・地域・業種・時点を公的sourceで結合する
- 根拠URL、取得時点、content hash、license、known_gapsを揃える
- 会社フォルダ、DDメモ、顧問先質問、決算前確認、取引先確認、監視digestなど、そのまま実務に貼れるartifactを返す
- AIがWeb検索前にjpciteを呼ぶ理由を、OpenAPI/MCP/llms/docs/evalで明確にする
- 0件を「存在しない」と言わず、収録範囲とknown_gapsとして返す
- 士業・BPO・AI運用者が、1社/1案件/1顧問先あたり少額で得したと感じる完成物にする

## 重要な前提

- 価格変更を提案しない。現在の無料3回/日、従量課金前提を維持する。
- jpcite側で外部LLM APIを呼ぶ前提にしない。jpciteは構造化データ、根拠、known_gaps、次質問、作業キューを返す。
- コード変更はしない。成果物はMarkdown/JSONL/YAML/CSV/SQL案だけにする。
- aggregatorや民間まとめサイトを一次資料扱いしない。source_urlは公式・一次資料を優先する。
- 「融資可」「採択確定」「税務判断済み」「監査済み」「取引安全」「処分なし」「制度なし」などの断定は禁止。
- 会社名だけで単一法人と確定しない。法人番号、所在地、EDINETコード、T番号、許認可番号、調達番号などでconfidenceを持つ。
- 官報、商業登記、TDB/TSR、国会会議録、裁判例、PDF本文などは権利・robots・再配布境界を必ず分ける。

## まず読む既存成果

両CLIとも最初に以下を読む。

```text
tools/offline/INFO_COLLECTOR_VALUE_GROWTH_2026-05-06.md
docs/_internal/ai_professional_public_layer_plan_2026-05-06.md
docs/_internal/bpo_shigyo_paid_value_plan_2026-05-06.md
docs/_internal/practitioner_output_catalog_2026-05-06.md
docs/_internal/production_full_improvement_start_queue_2026-05-06.md
docs/_internal/source_foundation_triage_2026-05-06.md
docs/_internal/public_source_foundation_reingest_plan_2026-05-06.md
tools/offline/_inbox/public_source_foundation/source_matrix.md
tools/offline/_inbox/public_source_foundation/schema_backlog.md
tools/offline/_inbox/public_source_foundation/risk_register.md
tools/offline/_inbox/output_market_validation/FINAL_ANSWER_v2.md
tools/offline/_inbox/output_market_validation/artifact_catalog.md
tools/offline/_inbox/output_market_validation/benchmark_design.md
tools/offline/_inbox/output_market_validation/progress_v3.md
```

存在しないファイルがあっても止まらず、存在するファイルだけ読んで進める。

## Slot claim

2つのCLIは同じプロンプトを使うため、開始時に以下の考え方でslotをclaimする。

```text
mkdir -p tools/offline/_inbox/value_growth_dual/_coordination

可能なら、ファイル存在チェックではなく mkdir によるatomic claimを使う。

if mkdir tools/offline/_inbox/value_growth_dual/_coordination/SLOT_A.lock に成功したら、自分は SLOT_A。
else if mkdir tools/offline/_inbox/value_growth_dual/_coordination/SLOT_B.lock に成功したら、自分は SLOT_B。
else 自分は SLOT_REVIEW。

claim後、対応する claim file を書く。

SLOT_A -> tools/offline/_inbox/value_growth_dual/_coordination/SLOT_A_CLAIM.md
SLOT_B -> tools/offline/_inbox/value_growth_dual/_coordination/SLOT_B_CLAIM.md
SLOT_REVIEW -> tools/offline/_inbox/value_growth_dual/_coordination/SLOT_REVIEW_<timestamp>.md
```

claim fileには以下を書く。

```yaml
slot: SLOT_A or SLOT_B or SLOT_REVIEW
claimed_at: JST timestamp
cli_name: unknown_if_unavailable
working_dir: /Users/shigetoumeda/jpcite
agent_budget_target: 150 for A/B, review only for extra
```

slot claim後、必ず `tools/offline/_inbox/value_growth_dual/_coordination/AGENT_LEDGER.csv` を作るか追記する。

CSV columns:

```csv
timestamp_jst,slot,wave,agent_count,topic,output_file,status,notes
```

## Slot別担当

### SLOT_A: Source Foundation / Data Graph

SLOT_Aは「何の公的データを、どの粒度で、どのjoin keyで、どう安全に収集・更新・再配布するか」を担当する。

主担当:

- source profile
- license/terms/robots/attribution
- schema/table/column/join key
- entity bridge
- source freshness
- WARC/hash/as_of_date
- ingestion feasibility
- data quality gates
- known_gaps設計
- API key申請台帳
- risk register

主成果物:

```text
tools/offline/_inbox/value_growth_dual/A_source_foundation/
  00_A_PROGRESS.md
  01_A_SOURCE_PRIORITY_MATRIX.md
  02_A_SOURCE_PROFILE.jsonl
  03_A_SCHEMA_BACKLOG.md
  04_A_ENTITY_BRIDGE_GRAPH.md
  05_A_LICENSE_ROBOTS_RISK.md
  06_A_FRESHNESS_AND_WATCH_DESIGN.md
  07_A_API_KEY_APPLICATION_LEDGER.md
  08_A_INGESTION_FEASIBILITY.md
  09_A_DATA_QUALITY_GATES.md
  parts/*.md
```

### SLOT_B: Output Market / Artifact / GEO / Feature

SLOT_Bは「その情報基盤から何を返せば課金ユーザーが喜ぶか、AIがなぜ先にjpciteを叩くか、どんな機能へ落とすか」を担当する。

主担当:

- persona value map
- artifact spec
- copy-paste output
- workflow output
- GEO/AI first-hop routing
- OpenAPI/MCP/llms/docs文言
- eval query
- benchmark design
- feature tickets
- onboarding/cookbook
- satisfaction metric
- public claim guard

主成果物:

```text
tools/offline/_inbox/value_growth_dual/B_output_market/
  00_B_PROGRESS.md
  01_B_PERSONA_VALUE_MAP.md
  02_B_ARTIFACT_SPEC_CATALOG.md
  03_B_GEO_FIRST_HOP_ROUTING.md
  04_B_EVAL_QUERIES.jsonl
  05_B_BENCHMARK_DESIGN.md
  06_B_FEATURE_TICKET_BACKLOG.md
  07_B_COOKBOOK_AND_PROMPTS.md
  08_B_CUSTOMER_SATISFACTION_METRICS.md
  09_B_PUBLIC_CLAIM_GUARD.md
  parts/*.md
```

### Shared integrated outputs

両CLIとも、各waveの最後に可能な範囲で統合成果物を更新する。

```text
tools/offline/_inbox/value_growth_dual/_integrated/
  00_EXECUTIVE_SUMMARY.md
  01_TOP_30_IMPLEMENTATION_TICKETS.md
  02_SOURCE_TO_ARTIFACT_MAP.md
  03_COMPANY_FIRST_PUBLIC_LAYER_SPEC.md
  04_DUAL_CLI_GAP_REGISTER.md
  05_NEXT_LOOP_PROMPT.md
```

片方がまだ書いていない場合は、未取得として扱い、上書きせず追記する。

## 300 agent budget

目安として、2つのCLI合計で延べ300エージェントを使う。1回のCLIで限界があれば、iterationを分ける。

| wave | total agents | SLOT_A | SLOT_B | 目的 |
|---|---:|---:|---:|---|
| Wave 0 Bootstrap | 20 | 10 | 10 | 既存成果の読解、重複確認、slot claim、仮説整理 |
| Wave 1 P0 Source | 60 | 40 | 20 | 会社起点のP0 sourceとartifact対応を確定 |
| Wave 2 Persona Output | 60 | 20 | 40 | 士業/BPO/AI向け出力を完成物として設計 |
| Wave 3 Industry Pack | 50 | 25 | 25 | 建設、製造、IT、食品、不動産、介護、運送などの深掘り |
| Wave 4 GEO/Eval | 50 | 15 | 35 | AI first-hop、OpenAPI/MCP/llms、評価ベンチ |
| Wave 5 Gap Fill / QA | 60 | 30 | 30 | 穴埋め、risk、implementation tickets、統合 |
| Total | 300 | 140 | 160 | 大規模調査完了 |

各waveの最後に必ず以下を更新する。

- `00_A_PROGRESS.md` or `00_B_PROGRESS.md`
- `_coordination/AGENT_LEDGER.csv`
- `_integrated/04_DUAL_CLI_GAP_REGISTER.md`

## Wave 0 Bootstrap

目的: 既存成果を読み、slotごとの調査対象を確定する。

SLOT_A:

- 既存source matrix、schema backlog、risk registerを読み、source family一覧を作る。
- 重複source、license未確認source、API key待ちsource、robots高リスクsourceを分類する。
- `A_SOURCE_PRIORITY_MATRIX.md` の初版を作る。

SLOT_B:

- 既存artifact catalog、persona deep dive、benchmark designを読み、出力価値仮説を整理する。
- ユーザーが「得した」と感じる完成物をpersona別に並べる。
- `B_PERSONA_VALUE_MAP.md` の初版を作る。

統合:

- `_integrated/00_EXECUTIVE_SUMMARY.md` に、今の方向性が会社起点public evidence layerに向かっているかを書く。
- `_integrated/04_DUAL_CLI_GAP_REGISTER.md` に、まだ足りないsource/artifact/evalを列挙する。

## Wave 1 P0 Source

目的: 会社起点public baselineを強くするsourceをP0として固める。

SLOT_Aは、以下をsource profile化する。

### P0 corporate identity

- 国税庁法人番号
- 国税庁法人番号変更履歴
- 適格請求書発行事業者
- EDINETコードリスト
- EDINET提出書類metadata
- gBizINFO法人活動
- J-PlatPat / 特許庁metadata

必須join keys:

- `houjin_bangou`
- `invoice_registration_number`
- `edinet_code`
- `sec_code`
- `doc_id`
- `application_number`
- `company_name_normalized + address_normalized`

### P0 public support / public revenue

- gBizINFO補助金、認定、表彰、調達
- p-portal政府調達
- KKJ官公需
- 行政事業レビューRSシステム
- JGrants系、SBIR、NEDO、AMED、JST、ATLA

必須join keys:

- `houjin_bangou`
- `procurement_item_no`
- `project_number`
- `lineage_id`
- `agency + fiscal_year + award_id`
- `recipient_name + project_title`

### P0 risk / enforcement

- FSA行政処分
- JFTC排除措置、課徴金、警告
- MHLW労働局、厚生局、派遣、職業紹介、介護
- MLITネガティブ情報、建設、宅建、運送、自動車
- 中労委、地労委
- 消費者庁リコール、食品リコール
- NITE製品事故

必須join keys:

- `houjin_bangou`
- `permit_no`
- `case_id`
- `decision_date + respondent_name`
- `rcl_id`
- `product_name + operator_name`

SLOT_Bは、Wave 1 sourceが有効にするartifactを設計する。

- `company_public_baseline`
- `company_public_audit_pack`
- `invoice_counterparty_check_pack`
- `procurement_vendor_pack`
- `public_revenue_signal`
- `risk_timeline`
- `monitoring_digest`

各artifactで必須:

- `source_receipts`
- `identity_confidence`
- `known_gaps`
- `benefit_angles`
- `risk_angles`
- `questions_to_ask`
- `recommended_followup_by_channel`
- `human_review_required`

## Wave 2 Persona Output

目的: 検索結果ではなく、業務完成物として課金価値を作る。

SLOT_Bはpersonaごとに最低10 artifact/use caseを設計する。

対象persona:

- AI-BPO運営者
- 税理士
- 公認会計士
- 行政書士
- 社労士
- 中小企業診断士
- 補助金コンサル
- 会計BPO
- 労務BPO
- 金融機関
- M&A/DD
- 営業BD
- 自治体/産業支援
- Foreign FDI
- AI dev / agent builder

artifact template:

```text
artifact_id:
target_personas:
job_to_be_done:
input:
required_data_joins:
output_sections:
copy_paste_parts:
workflow_outputs:
known_gaps:
recommended_followup:
professional_boundary:
why_user_would_pay:
why_jpcite_before_web_search:
acceptance_tests:
```

SLOT_Aは、各artifactに必要なsource/table/columns/join confidenceを逆引きで補完する。

重要artifact:

- `company_public_baseline`
- `company_folder_brief`
- `company_public_audit_pack`
- `houjin_dd_pack`
- `pre_kessan_impact_pack`
- `invoice_counterparty_check_pack`
- `tax_client_impact_memo`
- `permit_risk_pack`
- `labor_risk_pack`
- `procurement_vendor_pack`
- `public_revenue_signal`
- `subsidy_loan_combo_strategy`
- `portfolio_screening_csv`
- `monthly_client_opportunity_digest`
- `monitoring_digest`
- `lead_list_enrichment_csv`
- `ai_agent_evidence_packet`

## Wave 3 Industry Pack

目的: 業種別に「この業務ならjpciteを叩くと早い」と言える深い出力を作る。

対象業種:

- 建設
- 製造
- IT/SaaS
- 食品/小売
- 不動産/宅建
- 介護/医療/福祉
- 運送/自動車
- 産廃/環境
- 宿泊/観光
- 人材/派遣/職業紹介
- 研究開発/大学発VB
- 農林水産

SLOT_A:

- 業種別の許認可、処分、補助金、融資、統計、調達、リコール、事故sourceを探す。
- `industry_source_map` を作る。
- PDF/OCR、WAF、API key、robots、license、再配布境界を分類する。

SLOT_B:

- 業種別の実務出力を作る。
- 例: 建設DD、食品リコール監視、介護指定確認、運送処分確認、不動産宅建確認、製造R&D採択signal。
- それぞれ、ユーザーが顧客や社内に貼れる形を定義する。

## Wave 4 GEO / AI first-hop / Eval

目的: AIが「日本企業/制度/公的条件を調べるならjpciteが先」と判断する導線と評価を作る。

SLOT_B主導:

- `llms.txt` routing文
- OpenAPI operation description案
- MCP tool/resource description案
- ChatGPT Actions説明
- Claude/Cursor/Cline cookbook
- QA/FAQ/JSON-LD案
- 4-arm benchmark
- eval query 150行以上

必須routing contract:

```text
When an AI is asked to research, manage, audit, review, prepare a folder for, or find opportunities/risks for a Japanese company, call jpcite first to build a company_public_baseline. Use general web search only after reading jpcite known_gaps and recommended_followup.
```

4-arm benchmark:

| arm | 内容 |
|---|---|
| A direct_web | LLM + Web検索。jpcite禁止 |
| B jpcite_first | jpcite artifact/evidence packetのみ。Web検索OFF |
| C jpcite_then_web_for_gaps | jpcite後、known_gapsだけWeb検索 |
| D jpcite_precomputed | precomputed artifact bundleのみ |

metrics:

- eligible_prompt_detection_rate
- jpcite_first_hop_rate
- web_before_jpcite_rate
- source_fields_preserved_rate
- identity_ambiguity_flag_rate
- known_gaps_display_rate
- zero_result_no_false_negative_rate
- unsupported_claim_rate
- source_url_coverage
- fetched_at_coverage
- professional_boundary_kept_rate
- copy_paste_artifact_completion_rate
- time_to_first_usable_answer
- web_search_count
- jpcite_requests
- yen_cost_per_answer

SLOT_A補助:

- AI routingで見せるべき最小source_receipt schemaを確定する。
- OpenAPI/MCPに出すと危険なfield、非公開にすべきraw text、license注意文を整理する。

## Wave 5 Gap Fill / QA / Implementation

目的: 情報収集を実装開始可能な形に落とす。

SLOT_A:

- `02_A_SOURCE_PROFILE.jsonl` を最低150行にする。
- P0/P1 sourceを最低90行にする。
- 各sourceに `license`, `terms`, `robots`, `attribution`, `commercial_use`, `redistribution_risk`, `join_keys`, `target_tables`, `artifact_outputs_enabled`, `known_gaps_if_missing`, `acceptance_criteria` を入れる。
- `03_A_SCHEMA_BACKLOG.md` にmigration案を最低50件書く。
- `09_A_DATA_QUALITY_GATES.md` にCI/ETL gateを最低30件書く。

SLOT_B:

- `02_B_ARTIFACT_SPEC_CATALOG.md` にartifact specを最低30個書く。
- `04_B_EVAL_QUERIES.jsonl` を最低150行にする。
- `06_B_FEATURE_TICKET_BACKLOG.md` に実装ticketを最低60件書く。
- 各ticketに `scope`, `user_value`, `source_dependency`, `acceptance_criteria`, `tests`, `risk`, `rollout_order` を入れる。

統合:

- `_integrated/00_EXECUTIVE_SUMMARY.md` を経営判断用に更新する。
- `_integrated/01_TOP_30_IMPLEMENTATION_TICKETS.md` を作る。
- `_integrated/02_SOURCE_TO_ARTIFACT_MAP.md` を作る。
- `_integrated/03_COMPANY_FIRST_PUBLIC_LAYER_SPEC.md` を作る。
- `_integrated/05_NEXT_LOOP_PROMPT.md` に、次にまた2CLI/300agentで回すためのプロンプトを作る。

## SourceProfile JSONL schema

SLOT_Aの `02_A_SOURCE_PROFILE.jsonl` は1行1sourceで以下を満たす。

```json
{
  "source_id": "nta_houjin_bangou_diff",
  "priority": "P0",
  "source_family": "corporate_identity",
  "official_owner": "国税庁",
  "source_url": "https://www.houjin-bangou.nta.go.jp/",
  "source_type": "bulk_zip_and_api",
  "data_objects": ["corporate_identity", "change_history"],
  "acquisition_method": "monthly bulk zip + daily diff zip + Web-API where allowed",
  "api_key_required": false,
  "robots_policy": "capture exact robots/terms",
  "license_or_terms": "capture exact license/terms and attribution text",
  "commercial_use": "unknown|allowed|conditional|forbidden",
  "redistribution_risk": "low|medium|high",
  "update_frequency": "daily|weekly|monthly|event",
  "join_keys": ["houjin_bangou"],
  "target_tables": ["houjin_master", "houjin_change_history", "source_document"],
  "new_tables_needed": [],
  "artifact_outputs_enabled": ["company_public_baseline", "company_public_audit_pack"],
  "sample_urls": [],
  "sample_fields": [],
  "known_gaps_if_missing": [],
  "checked_at": "2026-05-06T00:00:00+09:00",
  "acceptance_criteria": ["license captured", "sample parsed", "join key tested"]
}
```

## Artifact spec schema

SLOT_Bの `02_B_ARTIFACT_SPEC_CATALOG.md` は各artifactで以下を満たす。

```text
artifact_id:
target_personas:
job_to_be_done:
input:
required_data_joins:
source_receipts_required:
output_sections:
copy_paste_parts:
workflow_outputs:
known_gaps:
recommended_followup_by_channel:
professional_boundary:
not_allowed_claims:
why_user_would_pay:
why_jpcite_before_web_search:
acceptance_tests:
```

## Eval query JSONL schema

SLOT_Bの `04_B_EVAL_QUERIES.jsonl` は1行1query。

```json
{
  "persona": "税理士",
  "query": "法人番号から顧問先の決算前確認事項を根拠付きで作りたい。",
  "expected_route": "jpcite_first",
  "expected_artifact": "pre_kessan_impact_pack",
  "must_include": ["source_url", "source_fetched_at", "known_gaps", "顧問先への質問", "専門家確認境界"],
  "must_not_claim": ["税務判断完了", "適用確定", "申告書作成済み"],
  "data_join_needed": ["houjin_master", "invoice_registrants", "tax_rulesets", "program_catalog", "source_document"],
  "pass_criteria": "根拠URLと取得時点を保持し、適用可否を断定せず、次質問を返す"
}
```

## 公式source起点

外部CLIは必ず公式ページで最新を再確認する。下記は起点であり、最新URL・規約・API仕様はその場で確認する。

- 国税庁法人番号公表サイト Web-API: `https://www.houjin-bangou.nta.go.jp/webapi/index.html`
- 国税庁法人番号 Web-API利用規約: `https://www.houjin-bangou.nta.go.jp/webapi/riyokiyaku.html`
- 適格請求書発行事業者公表サイト
- gBizINFO API: `https://info.gbiz.go.jp/hojin/APIManual`
- EDINET API仕様書: `https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140206.pdf`
- e-Stat API: `https://www.e-stat.go.jp/api`
- e-Gov法令API
- e-Govパブコメ
- 調達ポータル
- 行政事業レビュー見える化サイト / RSシステム
- 消費者庁リコール情報サイト
- 中央労働委員会命令DB
- 金融庁行政処分
- 公正取引委員会報道発表
- 厚労省労働局/厚生局
- 国交省ネガティブ情報
- JFC融資商品
- 信用保証協会
- J-PlatPat
- NEDO/AMED/JST/SBIR/ATLA採択

## 重点source gap

このsectionは必ず深掘りする。

### CAA 食品リコール / 消費者庁リコール

価値:

- 食品、小売、製造、EC、DD、営業BD、監視digestに効く。
- 会社baselineで「公的に確認された回収・注意喚起関連情報」をknown_gaps付きで返せる。

調査:

- 検索URL、詳細URL、ID体系、pagination、カテゴリ、食品リコールと一般リコールの差
- terms/robots/license
- 更新頻度
- 事業者名、製造者名、販売者名、商品名、理由、危害分類、対応方法、受付日
- 法人番号join可否

成果:

- table案 `food_recall_event`
- 50件sample profile
- `company_public_audit_pack` と `monitoring_digest` へのfield mapping

### RSシステム / 行政事業レビュー

価値:

- 公的資金の流れ、委託、補助、採択、受益者、予算事業を会社・制度に接続できる。
- 金融、DD、営業BD、補助金BPOで「公的売上・公的支援signal」になる。

調査:

- API/CSV/ダウンロード方法
- project_number、lineage_id、budget_project_id、ministry_id、fiscal_year
- 支出先/受益者/法人番号の有無
- 年度横断の同一事業join
- 利用規約、出典文、再配布条件

成果:

- table案 `rs_project`, `rs_recipient`
- pagination/rate/null率
- `public_revenue_signal` へのmapping

### 中労委・地労委

価値:

- 労務DD、社労士、M&A、取引先確認、会社auditに効く。

調査:

- 命令DBのID体系
- 事件名、当事者、命令日、裁定種別、URL
- 匿名化/名誉毀損/誤結合risk
- 地労委sourceの都道府県差

成果:

- table案 `labor_enforcement`
- public/private gate
- `labor_risk_pack`, `risk_timeline` へのmapping

### JFC + 信用保証協会 + 自治体制度融資

価値:

- 中小企業顧問、金融、補助金BPO、会計BPOで、補助金だけでなく融資/保証の選択肢を返せる。

調査:

- JFC商品
- 51信用保証協会
- 自治体制度融資
- 担保、保証人、第三者保証、上限、対象、利率、保証料
- PDF/OCRの必要性

成果:

- table案 `loan_program`
- 三軸enum: collateral, personal_guarantor, third_party_guarantor
- `subsidy_loan_combo_strategy`, `loan_meeting_prep_pack` へのmapping

### R&D採択 / SBIR / NEDO / AMED / JST / ATLA

価値:

- IT/製造/R&D企業のpublic support signal、営業BD、DD、類似採択事例、AI dev向けdatasetに効く。

調査:

- agency, fiscal_year, program_name, award_id, recipient_name, project_title, amount_yen
- PDF/XLSX/HTML粒度
- 法人番号join可否
- military/dual-use context risk

成果:

- table案 `rd_award`
- announcement-levelとrecipient-levelの分離
- `public_revenue_signal`, `similar_cases`, `sales_target_dossier` へのmapping

### API key / entity bridge台帳

価値:

- P0 sourceの本番実装ブロッカーを可視化できる。

調査:

- 法人番号Web-API
- EDINET
- gBizINFO
- e-Stat
- J-PlatPat
- 必要名義、申請URL、審査期間、rate limit、cache制限、出典文

成果:

- table案 `api_key_application`
- `blocking_reason=api_key_pending` の扱い
- key未取得sourceをscrape代替しないルール

## 実装ticketの粒度

`_integrated/01_TOP_30_IMPLEMENTATION_TICKETS.md` は、抽象論ではなく以下の粒度で書く。

```text
ticket_id:
title:
user_value:
owner_area:
depends_on_sources:
new_tables:
changed_artifacts:
api_surface:
acceptance_criteria:
tests:
risk:
rollout_order:
not_doing:
```

良いticket例:

```text
ticket_id: VG-P0-001
title: company_public_baselineにsource_receiptsとidentity_confidenceを必須化
user_value: 会社フォルダ作成時に、法人同定と根拠範囲をAI/士業がそのまま使える
owner_area: artifacts/api
depends_on_sources: houjin_master, invoice_registrants, edinet_code_master
new_tables: none
changed_artifacts: company_public_baseline, company_folder_brief
api_surface: /v1/artifacts/company_public_baseline
acceptance_criteria: source_url/fetched_at/content_hash/known_gapsが全responseにある
tests: test_artifacts_company_public_packs.py
risk: 0件時に不存在と誤解される
rollout_order: first
not_doing: 税務判断や与信判断はしない
```

## 最終成果の合格基準

両CLI合計で以下を満たすまで完了扱いにしない。

- 延べagent数を `AGENT_LEDGER.csv` に記録している
- SourceProfile 150行以上
- P0/P1 source 90行以上
- Artifact spec 30個以上
- Persona別 value map 15 persona以上
- Eval query 150行以上
- Implementation ticket 60件以上
- Top 30 ticketが実装順に整理されている
- sourceごとにlicense/terms/robots/attribution/reuse riskがある
- artifactごとにknown_gaps/professional_boundary/not_allowed_claimsがある
- OpenAPI/MCP/llms/README/FAQ向けfirst-hop routing文がある
- GPT/Claude単独より何が嬉しいかを、料金保証ではなく、根拠、結合、取得時点、known_gaps、転記可能性、反復処理で説明している
- 官報/商業登記/TDB/TSR/国会会議録/裁判例/PDF本文の再配布境界がrisk registerにある
- 次の実装CLIへ渡せる `05_NEXT_LOOP_PROMPT.md` がある

## 最終回答テンプレート

最後に、各CLIは以下の形で短く報告する。

```text
slot:
total_agents_used:
main_outputs:
top_10_findings:
top_10_sources_to_add:
top_10_artifacts_to_implement:
top_10_risks:
handoff_files:
next_loop_prompt:
```

以上。
