> ⚠️ SUPERSEDED (2026-05-06 by Claude session A housekeeping)
> 本 prompt は **single-CLI 版**。dual-CLI 300-agent 版 INFO_COLLECTOR_VALUE_GROWTH_DUAL_CLI_300_AGENTS_2026-05-06.md に **superseded**。
> 単独 CLI で立ち上げる場合のみ本 prompt を使用、複数 CLI 並列実行時は dual-CLI 版を起点とする。
> 既存 dual-CLI 成果物は tools/offline/_inbox/value_growth_dual/_INDEX.md 参照。

# jpcite Value Growth Info Collector Loop 2026-05-06

このファイルは、別CLIへそのまま貼って実行するための情報収集・整理プロンプトです。

目的は、jpciteを「検索API」から「AI、士業、BPO、会社顧問、監査/DDが最初に使う日本企業・公的制度の根拠レイヤー」へさらに近づけることです。価格変更や課金モデル変更ではなく、今の無料3回/日と従量課金前提のまま、ユーザーが得だと感じる出力、データ結合、機能を深くするための調査を行ってください。

## 実行指示

```text
cd /Users/shigetoumeda/jpcite
/loop tools/offline/INFO_COLLECTOR_VALUE_GROWTH_2026-05-06.md
```

CLIは投入できる最大エージェント数を使ってください。1 iterationで終わらせず、成果物を読み直し、穴を見つけ、次iterationで補完してください。各iterationの最後に必ずprogressを更新してください。

## 絶対条件

- コード変更はしない。成果物は `tools/offline/_inbox/value_growth/` 配下にMarkdown/JSONL/YAML/CSVで保存する。
- jpcite側で外部LLM APIを呼ぶ前提を置かない。jpciteは公的データ、構造化、根拠、known_gaps、次質問を返す。
- 「採択確定」「融資可」「税務判断済み」「監査済み」「安全」「問題なし」などの断定を成果物に入れない。
- aggregatorや民間まとめサイトを一次ソース扱いしない。調査対象として比較するのはよいが、source_urlには公式・一次資料を使う。
- すべてのsource候補に license / terms / robots / 取得方法 / 再配布リスク / attribution要否 / 商用利用上の注意を付ける。
- 個人情報、士業法、景表法、著作権、官報/商業登記/国会会議録などの制約を risk_register に残す。
- 会社名だけで単一法人と確定しない。法人番号、所在地、EDINETコード、T番号、許認可番号などの join confidence を必ず持たせる。
- 既存成果を読む。特に以下を前提にする。
  - `docs/_internal/ai_professional_public_layer_plan_2026-05-06.md`
  - `docs/_internal/bpo_shigyo_paid_value_plan_2026-05-06.md`
  - `docs/_internal/practitioner_output_catalog_2026-05-06.md`
  - `docs/_internal/production_full_improvement_start_queue_2026-05-06.md`
  - `tools/offline/_inbox/public_source_foundation/source_matrix.md`
  - `tools/offline/_inbox/public_source_foundation/schema_backlog.md`
  - `tools/offline/_inbox/public_source_foundation/risk_register.md`
  - `tools/offline/_inbox/output_market_validation/FINAL_ANSWER_v2.md`
  - `tools/offline/_inbox/output_market_validation/progress_v5.md`

## 成果物の保存先

すべてこのディレクトリへ保存してください。

```text
tools/offline/_inbox/value_growth/
```

必須ファイル:

| file | 内容 |
|---|---|
| `00_PROGRESS.md` | iterationごとの実施内容、投入agent数、未解決点、次iteration |
| `01_EXECUTIVE_SUMMARY.md` | 価値向上の結論、優先順位、今すぐ実装へ落とすもの |
| `02_SOURCE_PROFILE_VALUE_GROWTH.jsonl` | 追加収集すべきsource profile。1行1source |
| `03_ARTIFACT_SPEC_CATALOG.md` | ユーザーが課金したくなるartifact仕様 |
| `04_SCHEMA_AND_JOIN_BACKLOG.md` | 追加table、column、join key、confidence設計 |
| `05_COMPANY_FIRST_GRAPH.md` | 法人番号起点の情報グラフ、join confidence、known_gaps |
| `06_PERSONA_VALUE_MAP.md` | BPO、税理士、会計士、行政書士、社労士、金融、M&A、AI dev別の価値 |
| `07_GEO_AGENT_ROUTING.md` | AIがWeb検索前にjpciteを呼ぶためのllms/OpenAPI/MCP文言 |
| `08_EVAL_QUERIES.jsonl` | artifact評価クエリ。persona/query/must_include/must_not_claim/data_join_needed |
| `09_RISK_REGISTER.md` | license、robots、法務、個情、業法、WAF、再配布リスク |
| `10_IMPLEMENTATION_TICKETS.md` | 実装に落とせるチケット。P0/P1/P2、受け入れ条件、テスト案 |
| `11_FIRST_HOP_BENCHMARK.md` | AIがWeb検索前にjpciteを呼ぶかを測る4-arm評価設計 |
| `12_SOURCE_GAP_PRIORITY_LIST.md` | 追加収集sourceの優先順位、artifactへの効き方、未収集時のknown_gaps |

任意で追加:

- `parts/*.md`: agent別deep dive
- `source_samples/*.jsonl`: 公式sourceのサンプル行
- `schema/*.sql.md`: migration案
- `benchmarks/*.md`: GPT/Claude/Web検索比較設計

## 成果物スキーマ

### SourceProfile JSONL

`02_SOURCE_PROFILE_VALUE_GROWTH.jsonl` は1行1sourceで、最低限この形にしてください。

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
  "robots_policy": "capture exact robots/terms",
  "license_or_terms": "capture exact license/terms and attribution text",
  "redistribution_risk": "low|medium|high with reason",
  "update_frequency": "daily|weekly|monthly|event",
  "join_keys": ["houjin_bangou"],
  "target_tables": ["houjin_master", "houjin_change_history", "source_document"],
  "new_tables_needed": [],
  "artifact_outputs_enabled": ["company_public_baseline", "company_public_audit_pack", "monitoring_digest"],
  "sample_urls": [],
  "sample_fields": [],
  "known_gaps": [],
  "checked_at": "2026-05-06T00:00:00+09:00",
  "source_value_hypothesis": "このsourceがどの実務アウトプットを深くするか",
  "acceptance_criteria": ["row count estimate", "license captured", "sample parsed", "join key tested"]
}
```

### Artifact Spec

`03_ARTIFACT_SPEC_CATALOG.md` は各artifactごとに以下を必ず埋めてください。

```text
artifact_id:
target_personas:
job_to_be_done:
input:
required_data_joins:
output_sections:
copy_paste_parts:
known_gaps:
recommended_followup:
professional_boundary:
pricing_value_reason:
why_jpcite_before_web_search:
acceptance_tests:
```

### Eval Query JSONL

`08_EVAL_QUERIES.jsonl` は最低100行を目標にしてください。

```json
{
  "persona": "税理士",
  "query": "法人番号から顧問先の決算前確認事項を根拠付きで作りたい。",
  "expected_artifact": "pre_kessan_impact_pack",
  "must_include": ["source_url", "known_gaps", "顧問先への質問", "専門家確認境界"],
  "must_not_claim": ["税務判断完了", "適用確定", "申告書作成済み"],
  "data_join_needed": ["houjin_master", "invoice_registrants", "tax_rulesets", "program_catalog", "source_document"]
}
```

## 調査の中心仮説

jpciteの価値は「公的サイトを検索できること」ではありません。価値は、AIや実務者が会社や制度を扱う時に、複数の一次データを法人番号・制度ID・地域・業種・時点で結合し、次のような完成物に変換できることです。

- 会社フォルダREADME
- 顧問先への質問
- 決算前確認メモ
- 取引先確認表
- 監査/DDの公開情報証跡表
- 稟議に貼る公的支援・リスクメモ
- 補助金/税制/融資の申請前質問票
- 月次変更監視digest
- AI/RAGに渡すsource-linked evidence packet

この仮説を、データ、出力、機能、評価の4方向から検証してください。

## Agent割り当て

最大エージェントで以下を並列実行してください。agent数が足りない場合はP0から順に割り当ててください。

### P0-A 会社起点データグラフ

目的: 法人番号を起点に、会社の公的条件、メリット、リスク、known_gapsを返すためのデータグラフを設計する。

調査対象:

- 法人番号、法人基本、変更履歴
- インボイス登録、登録履歴
- gBizINFOの法人活動情報
- EDINETコード、上場/非上場、提出書類、XBRLメタ
- 補助金採択、調達、表彰、認定、許認可
- 行政処分、指名停止、業許可取消
- 同名法人、旧商号、所在地変更

出力:

- `parts/company_first_graph.md`
- `05_COMPANY_FIRST_GRAPH.md` へ統合するjoin graph
- join confidence定義: exact/high/medium/low/unmatched
- `company_public_baseline` に必要なfield一覧

### P0-B 士業/BPO完成物

目的: 課金される出力を「検索結果」ではなく「業務完成物」として設計する。

対象persona:

- AI-BPO運営者
- 税理士、会計士、行政書士、社労士、中小企業診断士
- 会計BPO、補助金BPO、労務BPO
- M&A/DD、金融機関、会社顧問、経営コンサル

必ず設計するartifact:

- `company_public_baseline`
- `company_folder_brief`
- `company_public_audit_pack`
- `pre_kessan_impact_pack`
- `invoice_counterparty_check_pack`
- `portfolio_screening_csv`
- `monthly_client_opportunity_digest`
- `permit_risk_pack`
- `procurement_vendor_pack`
- `subsidy_loan_combo_strategy`

出力:

- `parts/practitioner_artifact_deepdive.md`
- `03_ARTIFACT_SPEC_CATALOG.md`
- 各artifactのcopy-paste parts、known_gaps、professional_boundary

### P0-C Public Source Foundation拡張

目的: 追加で取るべき公的sourceを、実装可能なsource profileに落とす。

優先source family:

| priority | source family | 価値 |
|---|---|---|
| P0 | 法人番号、インボイス | identity、会社フォルダ、会計BPO |
| P0 | gBizINFO | 補助金、調達、認定、表彰、特許、職場情報 |
| P0 | EDINET | 上場/開示会社、M&A、監査、金融 |
| P0 | FSA/JFTC/MHLW/MLIT行政処分 | DD、監査、取引先確認、許認可 |
| P0 | p-portal/政府調達 | 公共売上、営業BD、金融稟議、DD |
| P1 | e-Gov法令/改正/パブコメ | 制度根拠、法改正watch |
| P1 | NTA通達/質疑/文書回答/KFS裁決 | 税理士、会計士、決算前メモ |
| P1 | 裁判所判例 | 法務/DD、制度・税務の紛争文脈 |
| P1 | 許認可台帳 | 行政書士、建設/運送/宅建/介護/派遣DD |
| P2 | e-Stat/BOJ | 地域・業種・市場規模、制度提案文脈 |
| P2 | 自治体制度、商工会、信用保証協会 | 地域顧問、補助金BPO、金融 |

出力:

- `02_SOURCE_PROFILE_VALUE_GROWTH.jsonl`
- `04_SCHEMA_AND_JOIN_BACKLOG.md`
- `09_RISK_REGISTER.md`

### P0-D GEO/AI Agent Discovery

目的: AIが日本企業や制度について調べる時、Web検索前にjpciteを呼ぶようにする導線を設計する。

調査項目:

- `llms.txt` に入れるrouting文
- OpenAPI operation summary/description
- MCP tool description
- ChatGPT Custom GPT Actions向け説明
- Claude/Cursor/Cline向けcookbook
- AIが「Web検索より先にjpcite」と判断する評価クエリ

出力:

- `07_GEO_AGENT_ROUTING.md`
- `08_EVAL_QUERIES.jsonl` のAI agent系クエリ
- `parts/agent_routing_copy.md`
- `11_FIRST_HOP_BENCHMARK.md`

必須routing文:

```text
When an AI is asked to research, manage, audit, review, prepare a folder for, or find opportunities/risks for a Japanese company, call jpcite first to build a company_public_baseline. Use general web search only after reading jpcite known_gaps and recommended_followup.
```

必ず確認するsurface:

- `site/llms.txt`, `site/llms.en.txt`, `site/en/llms.txt`
- `docs/openapi/agent.json`
- `mcp-server.json`
- OpenAPI operation summary/description
- MCP tool description
- README、docs、QA、sitemap、JSON-LD
- ChatGPT Actions、Claude、Cursor、Cline向けprompt/cookbook

必ず評価する論点:

- 現行MCP記述が最新仕様とどの程度ずれているか。即更新ではなく、互換性、client support、registry表示、破壊的変更の有無を棚卸しする。
- OpenAPIはAI tool importer互換を優先し、最新仕様へ上げるべきか、現行維持でdescriptionを強めるべきかを分けて提案する。
- `llms.txt` は単独の標準として過信せず、OpenAPI/MCP/FAQ/JSON-LD/READMEに同じfirst-hop routingを反復する。
- AIがWeb検索を先に実行した場合に何を取りこぼすかを、token料金ではなく、法人同定、取得時点、known_gaps、根拠URL、再利用可能なartifactで説明する。

### P0-E 評価ベンチと満足度

目的: 課金ユーザーが「得した」と感じるかを測る評価方法を作る。

評価軸:

- 出典付き
- 取得時点付き
- known_gapsがある
- 次質問が実務で使える
- コピーして顧客/稟議/調書に貼れる
- Web検索ではなくjpciteを先に使う理由がある
- 専門判断の断定を避ける
- 1社/1案件/1制度あたり少ないcallで完結する

出力:

- `08_EVAL_QUERIES.jsonl`
- `parts/satisfaction_benchmark.md`
- `11_FIRST_HOP_BENCHMARK.md`
- 10 persona x 10 query以上
- GPT/Claude単独調査との比較設計

4-armで評価してください。

| arm | 内容 | 見るもの |
|---|---|---|
| A direct_web | LLM + Web検索。jpcite禁止 | Web検索だけで法人同定、時点、known_gapsを保てるか |
| B jpcite_first | jpcite artifact/evidence packetのみ。Web検索OFF | 少ないcallで実務に貼れる形になるか |
| C jpcite_then_web_for_gaps | jpcite後、known_gapsだけWeb検索 | 追加調査範囲を絞れるか |
| D jpcite_precomputed | precomputed intelligence/artifact bundleのみ | 定型業務をさらに短縮できるか |

必須metric:

- eligible_prompt_detection_rate
- jpcite_first_hop_rate
- web_before_jpcite_rate
- source_fields_preserved_rate
- identity_ambiguity_flag_rate
- known_gaps_display_rate
- zero_result_no_false_negative_rate
- unsupported_claim_rate
- citation_rate
- source_url_coverage
- fetched_at_coverage
- professional_boundary_kept_rate
- answer_usefulness_score
- copy_paste_artifact_completion_rate
- time_to_first_usable_answer
- web_search_count
- jpcite_requests
- yen_cost_per_answer

### P1-F Batch/Watch/継続課金

目的: 1回使って終わりではなく、顧問先・取引先・案件を継続管理する機能を設計する。

機能候補:

- `portfolio_screening_csv`
- `monthly_client_opportunity_digest`
- `monitoring_digest`
- `watch_targets`
- webhook通知
- 差分だけ再生成
- source freshness digest
- company folder sync

出力:

- `parts/batch_watch_value.md`
- API仕様案、schema案、評価クエリ

### P1-G 許認可/業種別深掘り

目的: 行政書士、社労士、建設/運送/介護/不動産/食品/産廃などで高価値な業許可・処分・台帳を洗い出す。

優先業種:

- 建設業
- 宅建/不動産
- 運送/自動車
- 介護/医療/福祉
- 労働者派遣/職業紹介
- 食品/旅館/衛生
- 産廃/環境
- 補助金・公共調達が多い製造/IT/建設

出力:

- `parts/permit_industry_pack.md`
- source profiles
- `permit_risk_pack` artifact案

### P1-H 税務・会計・決算前メモ

目的: 税理士/会計BPOが使う決算前・月次・インボイス・税制確認の出力を深くする。

調査対象:

- NTA通達
- 質疑応答事例
- 文書回答
- KFS裁決
- 税制改正/期限
- インボイス経過措置
- 中小企業税制、賃上げ、投資促進、研究開発税制

出力:

- `parts/tax_accounting_pack.md`
- `pre_kessan_impact_pack` spec
- `invoice_counterparty_check_pack` spec

### P1-I 調達/採択/公的売上

目的: 公共調達、採択履歴、補助金、表彰、認定を会社の「公的売上・公的支援シグナル」として整理する。

出力:

- `parts/public_revenue_signal.md`
- `procurement_vendor_pack` spec
- `loan_memo_public_support_note` spec
- p-portal/gBizINFO/KKJ/自治体調達のjoin設計

### P2-J 競合・代替手段比較

目的: ユーザーがなぜGPT/Claude単独、Google検索、民間DB、補助金ポータルではなくjpciteを使うかを整理する。

注意:

- 誹謗しない。
- 断定的な優位性表現を避ける。
- 比較軸は一次資料、出典、取得時点、known_gaps、API/MCP、低単価、反復処理、会社起点の結合。

出力:

- `parts/competitive_value_matrix.md`
- `01_EXECUTIVE_SUMMARY.md` に統合

## 追加で重点調査すべき公式source

以下は候補です。必ず公式URL、terms、robots、API有無、サンプル、join keyを確認してください。

### 会社identity/活動

- 国税庁法人番号公表サイト Web-API、月次/差分データ
- 国税庁適格請求書発行事業者公表サイト
- gBizINFO API
- EDINET API / EDINETコードリスト
- J-PlatPat / 特許庁関連公開情報

### 行政処分/許認可

- FSA行政処分等
- JFTC排除措置/課徴金/警告
- MHLW労働局、厚生局、派遣/職業紹介/介護関連
- MLIT建設、宅建、運送、自動車、ネガティブ情報
- 環境省/自治体の産廃、食品衛生、旅館業などの公表処分

### 税務/法令/裁決/判例

- e-Gov法令API、改正履歴
- e-Govパブコメ
- NTA通達、質疑応答、文書回答
- 国税不服審判所裁決事例
- 裁判所裁判例
- 国会会議録

### 補助金/融資/調達/地域制度

- p-portal政府電子調達
- KKJ官公需情報
- gBizINFO補助金/調達/認定
- JFC融資商品
- 信用保証協会
- 47都道府県、政令市、中核市、商工会/商工会議所
- e-Stat、BOJ、経済センサス、法人企業統計

### 事故/リコール/安全/業種リスク

- 消費者庁リコール/食品リコール
- NITE製品事故
- 厚労省食品衛生/医療/介護関連公表
- 国交省自動車リコール/処分
- 環境/産廃関連公表

## 追加で必ず深掘りするsource gap

次のsourceは、課金価値のあるartifactに直結するため、P0/P1として必ずsource profile化してください。単にURLを列挙せず、schema、join key、license risk、artifactへの効き方、acceptance criteriaまで落とします。

### CAA 食品リコールDB

- source family: 消費者庁食品リコール
- expected table: `food_recall_event`
- key fields: `rcl_id`, `published_at`, `product_name`, `business_operator_name`, `manufacturer_name`, `reason`, `hazard_category`, `recall_method`, `source_url`, `fetched_at`, `content_hash`, `known_gaps_json`
- join keys: `rcl_id`, `business_operator_name + address`, `manufacturer_name + product_name`, enrich後 `houjin_bangou`, `match_confidence`
- enabled artifacts: `company_public_audit_pack`, `sales_target_dossier`, 食品/小売向け `monitoring_digest`, industry pack
- risk: 社名fuzzy joinの誤結合。`match_confidence < 0.95` はcustomer-facingに出さない。
- acceptance: 最新IDから50件サンプルし、200/404/欠番を分類。10件以上でfull schemaを埋め、全件に `source_url/fetched_at/content_hash` を付ける。

### RSシステム / 行政事業レビュー

- source family: 行政事業レビューREST API
- expected tables: `rs_project`, `rs_recipient`
- key fields: `project_number`, `lineage_id`, `fiscal_year`, `ministry_id`, `budget_project_id`, `project_name`, `project_summary`, `total_budget`, `recipient_name`, `recipient_houjin_bangou`, `amount_yen`
- join keys: `project_number`, `lineage_id`, `budget_project_id`, `ministry_id`, `fiscal_year`, `recipient_houjin_bangou`
- enabled artifacts: `public_revenue_signal`, `company_public_audit_pack`, `subsidy_traceback`, `adoption_skew_gap_report`
- risk: 年度横断で `lineage_id` と `project_number` を混同しない。利用規約、出典表示、再配布条件を確認する。
- acceptance: 1 fiscal year x 1 ministry の全ページを取得し、pagination/rate/null率、法人番号fill率、固定出典文を出す。

### 中労委・地労委 労務リスク

- source family: 中央労働委員会命令DB + 主要地労委
- expected table: `labor_enforcement`
- key fields: `case_id`, `detail_id`, `decision_date`, `tribunal`, `case_name`, `decision_type`, `party_alias_raw`, `respondent_name_candidate`, `houjin_bangou`, `match_confidence`, `source_url`, `fetched_at`, `public_gate`
- join keys: `mei/m{NNNNN}`, `decision_date`, `case_name`, `tribunal`, `respondent_name_candidate`, `houjin_bangou`
- enabled artifacts: `company_public_audit_pack`, M&A/DD `risk_timeline`, `worker_safety_radar`, `monitoring_digest`
- risk: 当事者匿名化、名誉毀損、誤名寄せ。`match_confidence < 0.95` は公開除外。
- acceptance: 直近5年20件、古い年10件を詳細確認し、裁定enumと公開可/不可gateを明示する。

### SBIR / NEDO / AMED / JST / ATLA 採択先

- source family: 公的R&D採択
- expected table: `rd_award`
- key fields: `agency`, `program_name`, `fiscal_year`, `award_id`, `call_url`, `result_url`, `attachment_url`, `project_title`, `recipient_name`, `recipient_role`, `amount_yen`, `houjin_bangou`, `match_confidence`, `source_url`, `fetched_at`
- join keys: `agency + fiscal_year + award_id`, project title + recipient name, enrich後 `houjin_bangou`
- enabled artifacts: `public_revenue_signal`, `similar_cases`, `sales_target_dossier`, AI dev/RAG `evidence_packet`
- risk: PDF/XLSX添付の再配布境界、ATLAの文脈、本文丸写し不可。メタと短い要約中心。
- acceptance: NEDO、AMED、MLIT SBIRから各30件以上の粒度差を報告し、announcement-levelとrecipient-levelを分離する。

### 公式ディレクトリ / 認定一覧

- source family: スポーツエール、観光庁、こども家庭庁、産業支援拠点など
- expected table: `official_directory_entry`
- key fields: `source_family`, `agency`, `certification_year`, `name`, `address`, `category`, `status`, `prefecture`, `source_url`, `fetched_at`, `houjin_bangou`, `match_confidence`
- join keys: `name + address`, `prefecture`, `agency + year + name`, enrich後 `houjin_bangou`
- enabled artifacts: `company_public_baseline`, `sales_target_dossier`, `lead_list_enrichment_csv`, industry pack
- risk: 施設・個人情報混在、法人番号なしsourceの誤結合。
- acceptance: 代表sourceで50行以上を抽出し、列構造、住所有無、法人名正規化ルール、公開可否を確認する。

### JFC + 信用保証協会 51機関 融資三軸

- source family: JFC融資商品、信用保証協会制度、自治体制度融資
- expected table: `loan_program`
- key fields: `agency_id`, `agency_name`, `region_code`, `program_name`, `program_slug`, `target`, `max_amount_yen`, `rate_text`, `guarantee_fee`, `collateral_enum`, `personal_guarantor_enum`, `third_party_guarantor_enum`, `source_url`, `fetched_at`, `extracted_text`
- join keys: `agency_id + program_slug`, `region_code`, `program_name_normalized`
- enabled artifacts: `loan_meeting_prep_pack`, `subsidy_loan_combo_strategy`, `lender_public_risk_sheet`, `hierarchy_program_compare`
- risk: 信用保証協会ごとのToS、PDF/OCR品質、本文転載。
- acceptance: 10協会以上で担保・保証人・第三者保証人の三軸enumを確認し、free text「要相談」に潰さない。

### API key / entity bridge 申請台帳

- source family: 法人番号Web-API、EDINET、gBizINFO、e-Stat、J-PlatPat
- expected table: `api_key_application`
- key fields: `source_id`, `official_apply_url`, `applicant_name_required`, `allowed_use`, `token_scope`, `rate_policy`, `storage_policy`, `redistribution_policy`, `status`, `blocking_reason`
- join keys: `houjin_bangou`, `corporate_number`, `edinetCode`, `secCode`, `docID`, `stat_code`, `region_code`, `application_number`
- enabled artifacts: 全artifactの `known_gaps`, `freshness ledger`, `source_review_backlog`
- risk: key未取得でscrape代替しない。key pendingは `blocking_reason=api_key_pending` として明示する。
- acceptance: 公式申請URL、必要名義、審査期間、禁止事項、出典文、rate limit、cache制限を1表にする。

## 実装候補の優先順位

### P0 すぐ実装へ落とす候補

1. `company_public_baseline` のrich shape固定
   - `identity_confidence`
   - `benefit_angles`
   - `risk_angles`
   - `questions_to_ask`
   - `folder_tasks`
   - `watch_targets`
   - `source_receipts`
   - `recommended_followup_by_channel`

2. `company_public_audit_pack` の監査/DD向け強化
   - evidence table
   - source receipts
   - mismatch flags
   - DD質問
   - 確認範囲/known_gaps

3. `pre_kessan_impact_pack`
   - 顧問先への質問
   - 必要証憑
   - 税制/制度候補
   - 専門家確認境界

4. `invoice_counterparty_check_pack`
   - T番号/法人番号/名称/所在地の一致
   - 取引先確認メール
   - BPO work queue
   - CSV batch

5. `portfolio_screening_csv`
   - 顧問先/取引先を複数件処理
   - 1行1会社のknown_gaps
   - 次に使うartifact

### P1 継続課金/高価値候補

6. `monthly_client_opportunity_digest`
7. `monitoring_digest`
8. `permit_risk_pack`
9. `procurement_vendor_pack`
10. `subsidy_loan_combo_strategy`
11. `fdi_company_entry_brief`
12. `public_revenue_signal`

## 受け入れ基準

この情報収集ループは、以下を満たすまで完了扱いにしないでください。

- SourceProfile 100行以上。ただしP0/P1で最低60行。
- Artifact spec 15個以上。
- Persona別 value map 10 persona以上。
- Eval query 100行以上。
- 実装チケット 30件以上。各チケットに受け入れ条件とテスト案がある。
- sourceごとにlicense/terms/robots/attribution/reuse riskがある。
- artifactごとにknown_gapsとprofessional_boundaryがある。
- AI agent routing文、llms.txt文言、OpenAPI/MCP description案がある。
- 「GPT/Claude単独より何が嬉しいか」がtoken料金ではなく、根拠、結合、確認範囲、転記可能性、反復処理として説明されている。

## 公式source確認メモ

外部CLIは下記を起点に、必ず最新の公式ページを再確認してください。

- 国税庁法人番号公表サイト Web-API: `https://www.houjin-bangou.nta.go.jp/webapi/index.html`
- 国税庁法人番号 Web-API利用規約: `https://www.houjin-bangou.nta.go.jp/webapi/riyokiyaku.html`
- gBizINFO API利用: `https://info.gbiz.go.jp/hojin/APIManual`
- e-Stat API: `https://www.e-stat.go.jp/api`
- EDINET API仕様書: `https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140206.pdf`

確認時は、APIの有無だけでなく、利用規約、出典表示文言、再配布可否、機械取得制限、API key申請要否、rate limit、robots、サンプルレスポンス、更新頻度を必ず記録してください。

## 最終出力の書き方

`01_EXECUTIVE_SUMMARY.md` は、次の形で短く強くまとめてください。

```text
jpciteの次の価値向上は、会社起点のpublic evidence layerを厚くすること。
AI/BPO/士業が日本企業を扱う時、Web検索前にjpciteで会社の公的ベースラインを作り、根拠、known_gaps、質問、作業キュー、監視対象を返す。
そのために追加収集すべきデータは、法人identity、インボイス、gBizINFO、EDINET、行政処分、許認可、調達、税務通達/裁決、地域制度、統計。
最初に実装すべき完成物は company_public_baseline、company_public_audit_pack、pre_kessan_impact_pack、invoice_counterparty_check_pack、portfolio_screening_csv、monitoring_digest。
```

以上。
