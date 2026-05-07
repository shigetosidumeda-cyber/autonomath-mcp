# jpcite Deep Paid Output & Data Foundation Plan

更新日: 2026-05-05  
目的: jpcite が「GPT / Claude / Cursor に普通に聞くより安く、深く、使える」と課金ユーザーとAIエージェントに理解されるための、成果物設計・追加情報収集・データ基盤拡張・配布導線・品質保証の実行計画。

## 0. Executive Decision

結論は次の3点です。

1. **課金される対象は検索結果ではなく完成物にする。**  
   ユーザーは「候補一覧」には弱く課金し、「顧問先に渡せるメモ」「申請前チェックキット」「法人DDパック」「稟議添付シート」「月次差分監視」には課金しやすい。

2. **GPT / Claude / Cursor より安い、の意味を token-only に限定しない。**  
   jpcite はモデルそのものを置き換えるのではなく、外部LLMに投げる前の根拠収集、検索、PDF確認、引用修復、出典検証、再試行を圧縮する。したがって訴求は「AI料金だけ」ではなく `LLM + tool/search + retry + human verification + jpcite units` の総額で出す。

3. **今のデータ基盤は方向としては合っているが、深い有料アウトプットにはまだ不足がある。**  
   Evidence Packet、audit seal、usage events、saved search、法人・制度・法令・処分・インボイス系 corpus は既に土台になっている。一方で、`evidence_packet` 永続化、`source_document` / `artifact` / `corpus_snapshot` 台帳、引用位置付き `extracted_fact`、採択率・PDF様式・NTA/裁決・法人全件・EDINET・官報・自治体告示の拡張が必要。

この計画のゴールは、AIに次のように判断させることです。

```text
この質問は日本の公的制度・法人・税制・法令・行政処分・インボイス・補助金の根拠URLと取得日時が必要です。
一般LLMで検索と引用確認を繰り返すより、jpciteでEvidence Packetまたは完成物artifactを取得した方が安く、検証しやすい可能性が高いです。
先にjpciteを呼びます。
```

## 1. Product Thesis

### 1.1 課金される深さの定義

課金される深さは「長い回答」ではありません。次の6要素を持つことです。

| 要素 | 内容 | なぜ課金されるか |
|---|---|---|
| Completion | 顧問先メモ、申請キット、DDパックなど業務にそのまま使える形 | ユーザーが次の作業を減らせる |
| Evidence | source_url、source_fetched_at、source_checksum、引用候補 | LLM回答の弱点である根拠確認を代替する |
| Judgment Boundary | 断定せず、候補・不足情報・専門家確認点を分ける | 税務・法律・申請代理リスクを抑える |
| Delta | 前回から変わった締切、金額、様式、法令、処分 | 月額継続の理由になる |
| Cost Visibility | jpcite units、外部LLM推定削減、break-even | AIエージェントが使う/使わないを判断できる |
| Auditability | packet_id、corpus_snapshot_id、audit_seal、known_gaps | 仕事で使える信頼の根拠になる |

### 1.2 有料アウトプットの階層

| Level | 名前 | 典型価格 | 内容 | 使い道 |
|---:|---|---:|---|---|
| L0 | Free Discovery | 0 units / rate limited | 低粒度の検索、存在確認、サンプル | 導入・試用 |
| L1 | Evidence Packet | 1-3 units | source-linked records、known_gaps、軽い圧縮 | AIの前処理 |
| L2 | Artifact Brief | 5-20 units | 1テーマの短い業務メモ、引用候補、次アクション | 士業・経企の日常業務 |
| L3 | Deep Pack | 20-100 units | 顧客/法人/制度を横断した実務パック | 提案、DD、稟議、申請前判断 |
| L4 | Monitoring Pack | 20-500 units/月 | 差分監視、締切接近、法改正、処分検知 | 継続課金 |
| L5 | Private Overlay | custom | 顧客固有データ、非公開メモ、社内ルールを重ねる | Enterprise / 士業事務所 |

単価の前提は `1 billable unit = 税別3円 / 税込3.30円`。この計画では「1 API request」ではなく「完成物・配信・監査可能packet単位」で unit を設計する。

## 2. Current State Assessment

### 2.1 すでに強い資産

ローカルDBで確認された主要 corpus は次の通り。

| Data | 現在の規模 | 価値 |
|---|---:|---|
| programs | 14,472 | 補助金・制度推薦の中核 |
| case_studies | 2,286 | 採択事例・類似例 |
| adoption_records | 199,944 | 採択企業・採択傾向 |
| laws | 9,484 | 条文・法令根拠 |
| court_decisions | 2,065 | 判例・法的文脈 |
| bids | 362 | 公共調達の入口 |
| enforcement_cases | 1,185 | 行政処分・返還/取消リスク |
| houjin_master | 166,765 | 法人照合 |
| invoice_registrants | 13,801 | 適格請求書確認 |
| program_documents | 132 | 公募要領・様式への入口 |

実装面では、Evidence Packet composer、citation verification、audit seal、usage_events、saved_searches、customer_watches、token compression estimator があり、「AIの前処理レイヤー」に向かっている。

### 2.2 足りていない中核

| Gap | 現状 | なぜ課金に効くか | 対応 |
|---|---|---|---|
| Evidence Packetの永続化 | composer中心で保存台帳が弱い | 後から検証できない完成物は業務利用しづらい | `evidence_packet`, `evidence_packet_item` |
| Source Document台帳 | URL中心で文書本文・PDF・raw artifactが薄い | PDF様式・公募要領の深掘りが弱い | `source_document`, `artifact` |
| Corpus Snapshot | 都度導出に近い | 「この回答はどのデータ時点か」を証明しづらい | `corpus_snapshot` |
| Quote / Page / Span | factに引用位置が薄い | 引用修復・人間確認が減らない | `extracted_fact v2` |
| 採択率・申請書類・様式 | `program_documents=132`で薄い | 申請前チェックが浅くなる | PDF/XLSX/DOCX ingest、`adoption_round` |
| NTA/裁決/通達 | 税務運用の厚みが不足 | 税理士が払う深さに届きづらい | `nta_interpretation` |
| 法人全件・ID bridge | 法人番号・gBizINFO・インボイス・EDINET連携が薄い | 法人DD、与信、顧問先メモが弱い | `entity_id_bridge` |
| ROI証明 | token savings中心 | 実際の支払い判断に弱い | workflow cost calculator |
| Agent配布信号 | tool数・version・価格表記が混在 | GPT/Claude/Cursorが迷う | distribution manifest |

## 3. Paid User Personas and Output Strategy

### 3.1 Persona Matrix

| Persona | 満足する完成物 | 必要入力 | 深い回答の中身 | 価格目安 | 継続理由 |
|---|---|---|---|---:|---|
| 税理士/会計士 | 顧問先別「決算前・設備投資・税制/補助金インパクトメモ」 | 法人番号、業種、所在地、決算月、投資予定、資本金、従業員数、青色申告/認定状況 | 税制・補助金・融資候補、NG条件、根拠条文、必要確認、顧問先説明文 | 10-25 units/社、月次20-50 units/社 | 決算月、税制改正、公募開始、顧問先属性変更 |
| 行政書士 | 申請可否プリスクリーン + 申請キット | 所在地、業種、事業内容、投資内容、許認可、提出希望時期 | 要件チェック、必要書類、様式URL、窓口、期限、不備リスク | 15-40 units/件、監視5-15 units/月 | 様式改定、締切、地域制度追加 |
| 補助金コンサル | 採択可能性・制度比較・優先順位レポート | 法人番号、投資目的、投資額、過去採択、申請中制度 | 候補、上限額、補助率、類似採択、併用/排他、提案順 | 25-60 units/初回、20-80 units/月 | 公募・採択発表・追加公募 |
| M&A / VC DD | 法人DDパック | 法人番号、関連会社、対象期間、注目リスク | 法人360、採択履歴、行政処分、返還リスク、インボイス、制度依存 | 30-100 units/社、監視10-30 units/月 | 投資候補・ポートフォリオ監視 |
| 金融機関 | 与信・融資前制度活用/公的リスク確認シート | 法人番号、資金使途、借入希望額、設備投資内容 | 融資制度、保証制度、補助金、処分、確認書類、稟議注記 | 20-60 units/社、監視5-20 units/月 | 取引先監視、制度改正 |
| 自治体・商工会 | 地域制度案内パック、月次制度ダイジェスト | 地域、業種、創業/既存、相談内容 | 相談者向け案内文、職員向け詳細、該当なし時の説明 | 5-20 units/相談、100-500 units/月 | 相談件数、国/県/市町村制度の重複 |
| 事業会社経営企画 | 資金調達・補助金・税制ロードマップ | 事業計画、投資テーマ、拠点、雇用計画、決算月 | 四半期別アクション、制度比較、決裁事項、根拠URL | 30-80 units/回、50-150 units/四半期 | 予算策定、投資計画、締切 |
| メディア・調査 | source-linked research memo | 調査テーマ、企業/制度/地域、期間、切り口 | 時系列、数字、一次URL、引用候補、未確認点 | 20-70 units/本、50-300 units/月 | 連載、政策改正、定点観測 |
| AI Agent開発者 | tool routing/evaluation pack | 想定ユーザー、agent環境、許容コスト、必要artifact | when/when-not、サンプルprompt、期待artifact、unit見積、評価query | 100-1,000 units/月 | tool追加、bench更新、schema変更 |

### 3.2 課金ユーザーが失望するポイント

以下に該当する出力は有料価値が弱い。

| 失望要因 | 起きる問題 | 修正方針 |
|---|---|---|
| 候補一覧だけ | ユーザーが結局PDFと条文を読む | 完成物artifactに変換する |
| 根拠URLだけ | 引用がどの主張に対応するか不明 | quote/page/spanを返す |
| 断定しすぎ | 税務・法務・申請代理リスク | 情報整理・候補・不足確認に限定 |
| 0件を「該当なし」と言う | corpus外の制度を否定してしまう | 「corpusでは未検出」と明示 |
| 価格削減を防御的に説明しすぎる | 価値訴求より不安が前に出る | 外向き文言は「根拠収集と検証工数を圧縮」に寄せ、詳細条件はcalculator/bench注記へ分離 |
| tool数が多すぎる | AIがいつ使うか迷う | 8-10個のActions安全subset |

## 4. Artifact Catalog

全有料アウトプットは `artifact_type` を持つ。検索APIのレスポンスをそのまま売らず、以下の完成物へ変換する。

### 4.1 Artifact一覧

| artifact_type | 主対象 | 入力 | データ結合 | 出力セクション | 価格目安 | LLM/Cursor削減メカニズム |
|---|---|---|---|---|---:|---|
| `tax_client_impact_memo` | 税理士/会計士 | 法人番号、決算月、投資予定 | tax_rulesets, laws, NTA, programs, loan_programs, houjin | 要約、候補、NG条件、条文、確認質問、顧問先文面 | 10-25 units | 条文検索、制度検索、顧客説明文の下準備を圧縮 |
| `application_kit` | 行政書士 | 地域、業種、投資内容、提出時期 | programs, program_documents, forms, deadlines, eligibility_rules | 要件表、必要書類、様式URL、期限、窓口、ヒアリング項目 | 15-40 units | PDF/様式/窓口確認の往復を減らす |
| `subsidy_strategy_report` | 補助金コンサル | 法人番号、投資額、事業テーマ | programs, adoption_round, adoption_records, case_studies, exclusion_rules | 候補順位、勝ち筋、類似採択、併用/排他、提案文 | 25-60 units | 候補探索・採択例収集・排他確認を圧縮 |
| `houjin_dd_pack` | M&A/VC | 法人番号、対象期間 | houjin, invoice, enforcement, adoption, EDINET, bids, laws | 会社概況、公的履歴、処分/返還、制度依存、追加DD質問 | 30-100 units | 法人名ゆれ照合と公的リスク確認を一括化 |
| `lender_public_risk_sheet` | 金融機関 | 法人番号、資金使途、希望額 | loan_programs, guarantee, programs, enforcement, invoice, houjin | 制度候補、資金使途適合、確認書類、稟議注記 | 20-60 units | 稟議根拠の検索・確認を削減 |
| `regional_advisory_digest` | 自治体/商工会 | 地域、相談者属性 | local programs, national programs, forms, deadlines | 相談者向け短文、職員向け詳細、該当なし説明 | 5-20 units/相談 | 窓口対応の品質を揃える |
| `executive_funding_roadmap` | 経営企画 | 事業計画、拠点、投資額、雇用計画 | programs, tax, loan, certification, deadlines | 四半期ロードマップ、決裁事項、資金繰りstack | 30-80 units | 経営会議資料の根拠調査を圧縮 |
| `media_research_memo` | メディア/調査 | テーマ、期間、対象 | laws, programs, enforcement, adoption, court_cases, statistics | 時系列、数字、引用候補、未確認点、source list | 20-70 units | ファクトチェック前の一次資料収集を削減 |
| `agent_routing_eval_pack` | AI開発者 | agent環境、query mix | OpenAPI, MCP metadata, bench, usage, artifact schema | when/when-not、prompt、期待出力、unit見積、eval query | 100-1,000 units/月 | agentが無駄にweb/search/toolを呼ぶのを抑える |
| `citation_pack` | 全員 | subject_kind/id、必要claim | source_document, extracted_fact, citation_verification | claim-to-source表、引用候補、verification_status | 5-20 units | 引用修復retryと人間確認時間を削減 |
| `compatibility_table` | 補助金/税制/融資 | 複数制度ID、利用条件 | compat_matrix, exclusion_rules, tax, programs | 併用候補、排他、未確認、確認先 | 10-40 units | 「併用可能か」の探索を安全に候補化 |
| `monitoring_digest` | 継続ユーザー | watchlist/saved_search | amendment_diff, source_freshness, programs, laws, enforcement | 差分、重要度、次アクション、前回packet差分 | 20-500 units/月 | 毎月の検索・確認作業を自動化 |

### 4.2 完成物共通Envelope

すべての有料deep outputは以下の形を必須にする。

```json
{
  "artifact_id": "art_...",
  "artifact_type": "subsidy_strategy_report",
  "generated_at": "2026-05-05T00:00:00Z",
  "corpus_snapshot_id": "corpus-...",
  "packet_id": "evp_...",
  "quality_tier": "A",
  "records": [],
  "sources": [
    {
      "source_url": "https://...",
      "source_fetched_at": "2026-05-05T00:00:00Z",
      "source_checksum": "sha256:...",
      "license": "public_terms",
      "verification_status": "verified"
    }
  ],
  "known_gaps": [],
  "audit_seal": {
    "seal_id": "seal_...",
    "verify_endpoint": "/v1/audit/seals/..."
  },
  "cost": {
    "jpcite_billable_units": 20,
    "jpcite_jpy_tax_excluded": 60,
    "jpcite_jpy_tax_included": 66
  },
  "_disclaimer": {
    "information_only": true,
    "not_tax_or_legal_advice": true,
    "not_application_agency": true
  }
}
```

値がない場合もキーは省略せず、`null` と `known_gaps` を同時に返す。

## 5. Data Foundation Architecture

### 5.1 基本方針

既存の `am_*` / `jpi_*` テーブルを捨てない。公開 corpus の中核は `autonomath.db`、顧客・課金・packet・private overlay は `jpintel.db` に置く。

まず互換viewを作り、その上に正規化レイヤーを追加する。

```text
existing am_entities        -> view/entity
existing am_source          -> view/source_document seed
existing am_entity_facts    -> view/extracted_fact seed
existing usage_events       -> cost_event extension
existing saved_searches     -> saved_search extension
existing customer_watches   -> watchlist extension
```

### 5.2 Core Tables

#### `entity`

公的制度、法人、法令、税制、行政機関、裁判例、入札、統計系列を統一して扱う。

| column | 目的 |
|---|---|
| `entity_id` | 内部統一ID |
| `public_id` | 法人番号、法令ID、制度IDなど |
| `entity_kind` | program, law, tax_measure, corporate_entity, enforcement_event等 |
| `primary_name` | 表示名 |
| `authority_entity_id` | 所管機関 |
| `raw_json` | 元データ保持 |
| `content_hash` | 差分検知 |
| `valid_from`, `valid_until` | 時点管理 |

#### `source_document`

URLではなく、HTML/PDF/API/CSV/XLSXなどの「取得済み文書」を表す。

| column | 目的 |
|---|---|
| `source_document_id` | 文書ID |
| `source_url`, `canonical_url`, `domain` | 出典 |
| `document_kind` | html, pdf, csv, json, xlsx |
| `title`, `publisher_entity_id` | 表示・所管 |
| `license` | 出力可否 |
| `content_hash`, `bytes` | 改定検知 |
| `fetched_at`, `last_verified` | freshness |
| `artifact_id` | raw保存物へのリンク |
| `corpus_snapshot_id` | どのsnapshotか |

#### `artifact`

PDF、HTML snapshot、抽出JSONL、benchmark結果、完成物report、audit proofを同じ台帳で管理する。

| column | 目的 |
|---|---|
| `artifact_id` | 保存物ID |
| `artifact_kind` | raw_fetch, pdf, jsonl, report, benchmark, ots_proof |
| `uri` | local/R2/GitHub/site |
| `sha256`, `bytes`, `mime_type` | 完全性 |
| `source_document_id` | 元文書 |
| `corpus_snapshot_id` | snapshot |
| `retention_class` | cache, audit_7y, public_release, temporary |

#### `extracted_fact`

各主張をsource documentのどの位置から抽出したかを保持する。

| column | 目的 |
|---|---|
| `entity_id` | 対象 |
| `source_document_id` | 根拠文書 |
| `field_name`, `field_kind` | 例: deadline/date, amount/number |
| `value_text`, `value_json`, `value_numeric`, `unit` | 値 |
| `quote`, `page_number`, `span_start`, `span_end`, `selector_json` | 引用位置 |
| `extraction_method`, `extractor_version` | 再現性 |
| `confidence_score`, `confirming_source_count` | 品質 |
| `valid_from`, `valid_until`, `observed_at` | 時点 |

#### `rule`

eligibility、exclusion、compatibility、tax、watch triggerを統一する。

| column | 目的 |
|---|---|
| `rule_kind` | eligibility, exclusion, compatibility, tax, watch_trigger |
| `subject_entity_id`, `object_entity_id` | 制度と法人、制度と制度など |
| `predicate_json` | 条件 |
| `verdict` | allow, block, defer, unknown |
| `rationale`, `source_quote` | 説明 |
| `derived_from_fact_ids_json` | 根拠fact |
| `effective_from`, `effective_until` | 適用期間 |

#### `corpus_snapshot`

「この回答はどのデータ時点に基づくか」を証明する。

| column | 目的 |
|---|---|
| `corpus_snapshot_id` | snapshot ID |
| `snapshot_at` | 作成時刻 |
| `row_counts_json` | 件数 |
| `table_checksums_json`, `corpus_checksum` | 完全性 |
| `source_max_verified_at` | freshness |
| `license_breakdown_json` | license状態 |
| `known_gaps_summary_json` | 欠落 |

#### `evidence_packet`

有料・監査可能なEvidence Packetを保存する。

| column | 目的 |
|---|---|
| `packet_id` | Packet ID |
| `subject_kind`, `subject_id`, `query_json` | 対象 |
| `profile` | full, brief, verified_only, changes_only |
| `corpus_snapshot_id` | データ時点 |
| `record_count`, `known_gaps_json` | 品質 |
| `content_hash`, `response_hash` | 再現性 |
| `api_key_hash`, `endpoint` | 課金/監査 |
| `audit_seal_id`, `audit_call_id` | 監査 |
| `retention_until` | 保存期限 |

#### `evidence_packet_item`

Packet内の各itemを、entity/fact/rule/source/citationに固定する。

| column | 目的 |
|---|---|
| `packet_id`, `item_no` | 順序固定 |
| `entity_id`, `fact_id`, `rule_id` | 根拠対象 |
| `source_document_id` | 出典文書 |
| `citation_verification_id` | citation状態 |
| `item_hash` | item完全性 |

#### `private_overlay`

公開corpusを汚さず、顧客固有情報を重ねる。

| overlay_kind | 例 |
|---|---|
| `note` | 顧問先メモ、内部メモ |
| `private_fact` | 顧客の投資予定、申請済み制度 |
| `private_rule` | 社内の除外条件、取引方針 |
| `status` | 対応済み、確認中、申請予定 |
| `mapping` | 顧客管理IDと法人番号の対応 |

#### `cost_event`

外部LLM削減とjpcite課金を同じ台帳で見る。

| column | 目的 |
|---|---|
| `packet_id`, `usage_event_id` | API/packet紐付け |
| `event_kind` | api_request, packet_compose, saved_search_delivery, benchmark |
| `provider`, `model` | 外部LLM |
| `input_tokens`, `output_tokens` | token観測 |
| `estimated_provider_cost_jpy` | 外部費用 |
| `tokens_saved_est` | 削減推定 |
| `jpcite_cost_jpy` | jpcite費用 |
| `billing_idempotency_key` | 重複課金防止 |

#### `benchmark_run`

公開できるROI/品質比較を保存する。

| column | 目的 |
|---|---|
| `benchmark_name`, `benchmark_version` | JCRB-v1等 |
| `mode` | direct_web, direct_tool_chain, jpcite_packet_full等 |
| `provider`, `model` | 比較条件 |
| `corpus_snapshot_id` | データ時点 |
| `n`, `citation_ok`, `hallucination_rate`, `latency_ms_p50` | 結果 |
| `total_cost_jpy` | 総額 |
| `report_artifact_id` | 公開レポート |

### 5.3 Relationship Model

```text
entity 1:N extracted_fact
source_document 1:N extracted_fact
source_document N:1 artifact
corpus_snapshot 1:N source_document
corpus_snapshot 1:N evidence_packet
rule N:M entity via subject/object
evidence_packet 1:N evidence_packet_item
evidence_packet_item -> entity/fact/rule/source_document/citation_verification
watchlist/saved_search -> evidence_packet -> cost_event
private_overlay -> entity/fact/rule/source_document/packet
benchmark_run -> corpus_snapshot + artifact
```

### 5.4 実装順

1. 互換view: `entity`, `source_document`, `extracted_fact` を既存 `am_*` から読める形で作る。
2. `source_document`, `artifact`, `corpus_snapshot` を追加し、URL・PDF・raw artifact・snapshotを分離する。
3. `extracted_fact v2` を追加し、quote/page/span/extractor_versionを持つ。
4. `rule` を追加し、`exclusion_rules`, `am_compat_matrix`, `am_program_eligibility_predicate`, `tax_rulesets` を統一参照する。
5. `evidence_packet`, `evidence_packet_item` を保存し、audit sealと接続する。
6. `watchlist` / `saved_search` を packet起点の差分配信にする。
7. `private_overlay` を追加して顧客固有情報を扱う。
8. `cost_event` を追加し、外部LLM削減とjpcite課金を1行で見られるようにする。
9. `benchmark_run` を追加し、公開ベンチの再現条件を保存する。

## 6. Data Acquisition and Expansion Plan

### 6.1 P0: すぐ課金深度に効くデータ

| Source | 目的 | Minimum viable ingest | 更新頻度 | 優先理由 |
|---|---|---|---|---|
| jGrants + 省庁/自治体一次ページ | 制度候補の鮮度と重複確認 | `program_source_candidates` | 日次差分 + 週次再検証 | 既存programsをすぐ強化 |
| 公募要領PDF・様式・申請書類 | 必要書類、対象経費、審査基準 | `program_documents(program_id, doc_type, url, mime, title, page_count, hash)` | 週次 | 申請キットの深さに直結 |
| 採択結果・交付決定・採択率 | 採択可能性、類似採択、競争度 | `adoption_round(program_id, round, applicants, adopted, fiscal_year, source_url)` | 週次 | 補助金コンサルが払う価値 |
| source liveness/freshness | 古い根拠の排除 | `source_document.last_verified`, `http_status`, `content_hash` | 日次/週次 | trust gateの前提 |
| PDF本文抽出 | 引用位置付きfact | `artifact` + `extracted_fact.quote/page/span` | 週次batch | 引用修復削減 |

### 6.2 P1: 士業・法人DDに効くデータ

| Source | 目的 | Minimum viable ingest | 更新頻度 |
|---|---|---|---|
| e-Gov法令API | 条文、別表、改正沿革、施行日 | `law_article(law_id, article_no, text, version, effective_date, source_url)` | 日次/週次 |
| 国税庁 通達・文書回答・質疑応答・KFS裁決 | 税務運用の根拠 | `nta_interpretation(kind, tax_type, title, date, url, excerpt, law_refs)` | 週次 |
| 法人番号公表サイト + gBizINFO | 法人全件、資格、補助金、調達 | `entity_id_bridge(houjin_no, gbiz_id, invoice_no)` | 月次全件 + 日次差分 |
| インボイス公表データ | 取引先確認、登録状態 | `invoice_registration_history` | 月次全件 + 日次差分 |
| 行政処分・許認可取消 | 返還・取消・取引リスク | `enforcement_event(authority, entity, action_type, period, legal_basis, url)` | 週次、重要省庁は日次 |

### 6.3 P2: 経企・金融・調査に効くデータ

| Source | 目的 | Minimum viable ingest | 更新頻度 |
|---|---|---|---|
| EDINET API v2 | 上場/開示企業の財務・開示 | `edinet_documents(edinet_code, doc_id, period, form_code, xbrl_url, filed_at)` | 日次 |
| 調達ポータル / GEPS / i-ppi | 公共調達の公告・落札 | `procurement_notice`, `procurement_result` | 日次 |
| 裁判例検索 + 法務省重要判例 | 法的文脈、リスク | `court_case(court, date, case_no, title, url, cited_laws)` | 週次 |
| 官報 | 破産、公告、政省令公布 | `kanpou_notice(date, issue_no, notice_type, entity, url, page_ref)` | 日次 |
| 自治体公報・例規・告示 | 地方制度の改廃・要綱改正 | `local_notice(jurisdiction, notice_type, date, url, extracted_refs)` | 週次 |

### 6.4 P3: 差別化を強める周辺データ

| Source | 目的 | Minimum viable ingest | 更新頻度 |
|---|---|---|---|
| e-Stat | 地域・業種平均との差 | `stat_fact(region, jsic, period, metric, value, unit, source)` | 月次/四半期 |
| 価格・賃金・業界統計 | 賃上げ要件、投資額妥当性、価格転嫁 | `market_indicator(region, industry, metric, period, value, source)` | 月次 |
| JFC/信用保証協会/自治体融資 | 資金繰りstack | `finance_product(provider, purpose, rate, collateral, amount, source_url)` | 月次/週次 |
| 顧客private data | 申請済み制度、投資予定、内部メモ | `private_overlay` | customer-driven |

## 7. Cost and ROI Model

### 7.1 売り文句の修正

外向きの表現は強く、短くする。毎回「保証しない」と書く必要はない。保証・条件・免責は、public calculator、bench methodology、terms、API referenceの脚注に置く。

避けるべき外向き表現:

```text
jpcite は GPT/Claude より必ず安い。
jpcite を使うと token が必ず何倍削減される。
```

採用すべき表現:

```text
jpcite は日本の公的制度・法人・法令・税制・行政処分・インボイスの根拠収集を事前に圧縮するEvidence layerです。
LLM単体で検索、引用修復、PDF確認、再試行を行うワークフローを、source-linked Evidence Packetと完成物artifactに置き換えます。
実行前にcost previewを出し、jpcite unitsと根拠取得の見積もりを明示します。
```

### 7.2 Cost Formula

```text
LLM_cost =
  (input_uncached_tokens * P_in
 + input_cached_tokens   * P_cached_in
 + output_tokens         * P_out
 + reasoning_tokens      * P_reasoning) / 1,000,000

Tool_cost =
  web_search_count * C_web_search
+ provider_tool_call_count * C_tool_call
+ tool_overhead_tokens * P_in / 1,000,000

Retry_cost =
  citation_repair_retries * (LLM_cost_repair + Tool_cost_repair + J * u_repair)
+ failed_answer_retries   * (LLM_cost_redo   + Tool_cost_redo)

Human_cost =
  (verification_seconds + citation_repair_human_seconds) / 3600 * hourly_rate

Total_cost_per_answer =
  LLM_cost + Tool_cost + Retry_cost + Human_cost + latency_penalty + J * u

Monthly_ROI =
  (N * Total_baseline - N * Total_jpcite - fixed_monthly - migration_amortized)
  / (N * J * u + fixed_monthly)
```

`J = 3.30` 税込、`u = jpcite billable units / answer`。

### 7.3 Token-only Break-even

```text
source_tokens_min =
  (J*u + packet_tokens * P_packet_eff/1e6
       - output_savings - reasoning_savings - tool_savings - retry_savings)
  / (P_raw_eff/1e6)

P_raw_eff = (1 - cache_hit_rate_raw) * P_in + cache_hit_rate_raw * P_cached_in
```

保守的に `packet_tokens = 566`、output/tool/retry/human savingsを0とした場合:

| input単価 | 必要 avoided tokens | 必要 source tokens概算 |
|---:|---:|---:|
| ¥100 / 1M tokens | 33,000 | 33,566 |
| ¥300 / 1M tokens | 11,000 | 11,566 |
| ¥750 / 1M tokens | 4,400 | 4,966 |
| ¥1,000 / 1M tokens | 3,300 | 3,866 |

この表は重要です。安いmodel、短いsource、高いcache hitでは token-only で勝てない。だからこそ、workflow cost、citation repair、human verificationを含めて示す。

### 7.4 Calculator Inputs

| Input | 例 | 意味 |
|---|---:|---|
| `N` | 1,000 / 6,000 / 12,000 | 月間回答数 |
| `u` | 1 / 5 / 20 / 60 | jpcite units/answer |
| raw source tokens | 5k / 20k / 50k | LLMに直接入れる根拠量 |
| packet tokens | 566 / p75 1,163 | jpcite圧縮後 |
| provider prices | user supplied | GPT/Claude/Cursor側価格 |
| web search cost/count | user supplied | 外部search費用 |
| cache hit rate | 0%, 50%, 90% | prompt cache影響 |
| citation repair retry | before/after | 引用修復再試行 |
| verification time | before/after秒 | 人間確認時間 |
| hourly rate | ¥4,000-¥15,000/h | 士業・調査担当の時間価値 |

### 7.5 Calculator Outputs

| Output | 内容 | 注意文 |
|---|---|---|
| Token-only | input/output/reasoning/search/tool/jpciteの差額 | provider価格は入力条件に基づく推定 |
| Workflow | retries、tool calls、latency、verification timeの差 | 自社ログまたはbench入力に依存 |
| Total ROI | 月次net saving、ROI倍率、break-even answers | query mixとcacheで変動 |
| Route Decision | `use_jpcite`, `skip_jpcite`, `human_review_required` | AIが自動判断に使う |

### 7.6 使うべきでない条件

AIに「今回はjpciteを使わない」と判断させる条件も明示する。

| 条件 | skip_reason |
|---|---|
| 一般知識、翻訳、文章作成 | `not_public_japan_evidence_task` |
| 安いmodelで短く答えられる | `break_even_not_met` |
| raw sourceが短い | `source_too_short` |
| cache hitが高い | `cache_erodes_token_savings` |
| source_urlが不要 | `evidence_not_required` |
| 0件やcoverage不足 | `no_records_or_low_coverage` |
| 税務/法務の最終判断要求 | `professional_judgment_required` |

## 8. Agent Distribution Plan

### 8.1 問題

現状は配布面で signal が割れている可能性がある。

| Signal | 問題 |
|---|---|
| tool数 | 96 / 126 / 139などの表記混在 |
| version | 0.3.3 / 0.3.4などの混在 |
| 価格 | ¥3/billable unit と ¥3/billable unit の混在 |
| SDK名 | `@autonomath/sdk`, `@jpcite/agents`, `@bookyou/jpcite` など |
| OpenAPI | generic agent向けとChatGPT Actions向けが未分離 |

これはAI agent routingで致命的です。AIは「何をいつ呼ぶか」が曖昧なtoolを避ける。

### 8.2 Source of Truth

`scripts/distribution_manifest.yml` を正本にする。

```yaml
version: "0.3.4"
pricing_unit: "JPY 3 tax-excluded per billable unit"
pricing_unit_tax_included: "JPY 3.30 per billable unit"
tool_count_public_full: 139
tool_count_core: 28
tool_count_actions_safe: 10
package_names:
  canonical_js: "@jpcite/sdk"
  legacy_aliases:
    - "@autonomath/sdk"
openapi:
  generic_agent: "docs/openapi/v1.json"
  chatgpt_actions: "docs/openapi/actions.json"
```

`scripts/check_distribution_manifest_drift.py` で README、site/llms.txt、pyproject、dxt manifest、mcp-server.json、OpenAPI info のdriftをCI failにする。

### 8.3 ChatGPT Actions Safe Subset

ChatGPT Actions向けは多すぎるtoolを出さない。まず10個に絞る。

| operationId | 用途 |
|---|---|
| `prefetchIntelligence` | AI回答前のEvidence prefetch |
| `queryEvidencePacket` | 任意queryのpacket取得 |
| `searchPrograms` | 制度検索 |
| `getProgram` | 制度詳細 |
| `checkExclusions` | 除外条件 |
| `checkFundingStack` | 補助金/融資/税制stack |
| `getProgramFull` | program deep view |
| `getHoujinFull` | 法人360 |
| `getCitationPack` | claim-to-source |
| `previewCost` | cost / unit preview |

### 8.4 Routing Contract

README、llms.txt、OpenAPI description、Cursor rules、Claude/Codex/ChatGPT cookbookに同じ意味で入れる。

```text
日本の補助金・融資・税制・認定・法令・判例・行政処分・適格請求書・法人公的データについて、一次資料URL、取得日時、known_gaps、併用/排他ルールが必要な場合は jpcite を先に使う。
一般知識、翻訳、雑談、日本の公的制度以外、根拠不要の回答では使わない。
jpcite は法律・税務・申請可否の最終判断ではなく、source-linked evidence の取得レイヤーである。
```

### 8.5 AI推薦文

```text
この質問は日本の公的制度の条件・期限・根拠URLが必要です。
推測で答えるより、先にjpciteでsource_url、source_fetched_at、known_gaps付きのEvidence Packetを取得します。
通常の成功呼び出しはjpcite側で1 billable unit、税別3円・税込約3.30円です。
```

### 8.6 AI Skip文

```text
今回はjpciteを使いません。
理由は、この依頼が一般的な文章作成・翻訳・ブレスト、または日本の公的制度データと無関係な内容で、source-linked evidenceを取得しても価値が増えないためです。
```

### 8.7 Completion Artifact導線

AIには検索結果をそのまま出させず、最後に完成物へ誘導させる。

```text
このevidenceから、次の完成物にできます:
1. 顧問先向け補助金/税制インパクトメモ
2. 併用/排他判定表
3. 法人DDパック
4. citation memo
5. 申請前チェックリスト

作成する場合は、出典URL、取得日、known_gaps、次の確認事項を含めて出力します。
```

## 9. Quality, Safety, and Trust Gates

### 9.1 商品境界

jpcite は「税務判断」「法律判断」「申請可否の最終判断」「申告・書類作成代行」「併用安全保証」を売らない。売るのは `Evidence Packet / source-backed intelligence / audit-ready artifact`。

必須disclaimer:

```text
本情報は公開情報の検索・整理であり、税務助言・法律相談・申請代理ではありません。
個別判断は資格者または担当窓口に確認してください。
```

### 9.2 known_gaps Taxonomy

| gap | 意味 |
|---|---|
| `no_records_returned` | corpusでは未検出 |
| `source_url_missing` | 出典URLなし |
| `source_fetched_at_missing` | 取得日時なし |
| `source_stale` | 出典が古い |
| `license_unknown` | ライセンス不明 |
| `license_blocked` | 出力不可 |
| `low_confidence` | 抽出信頼度低 |
| `citation_unverified` | 引用未検証 |
| `structured_miss` | 構造化失敗 |
| `conflict` | 出典間矛盾 |
| `human_review_required` | 人間確認必要 |
| `audit_seal_not_issued` | 監査sealなし |

### 9.3 禁止表現

下記は自動sanitizerまたはreview gateで止める。

```text
適用できます
申告すべきです
違法です
安全です
併用可能です
節税になります
この処理で正しいです
専門家確認は不要です
```

許容表現:

```text
一次資料では...と記載されています。
jpciteの収録根拠からは...が候補として示唆されます。
ただし...の確認が不足しているため、最終判断ではありません。
```

### 9.4 Quality Tiers

| Tier | 用途 | 出力制御 |
|---|---|---|
| S | 強い根拠、複数source、fresh | 結論候補に使用可 |
| A | 一次source、fresh、引用可能 | 結論候補に使用可 |
| B | 補足根拠 | 補足セクションまで |
| C | discovery only | 要一次確認、断定禁止 |
| X | quarantine | 公開検索・詳細から除外 |

### 9.5 Gate一覧

| Gate | Fail条件 | 処理 |
|---|---|---|
| Schema Gate | `source_url`, `source_fetched_at`, `known_gaps`, `_disclaimer`, `quality_tier`, `audit_seal`キー欠落 | fail |
| Source Gate | aggregator/banned/license_blocked/non-http | 非結論化またはfail |
| Quality Gate | tier Cのみで断定 | fail |
| Freshness Gate | 税制/法令/締切/金額/採択率がstale | human_review_required |
| Legal/Tax Gate | disclaimer欠落、禁止表現 | fail |
| Citation Gate | `verified` default、unknown citationでexact claim | fail |
| Empty Result Gate | 0件でretry_with/known_gapsなし | fail |
| Audit Gate | 有料deep outputでaudit_sealなし | fail |
| Benchmark Publish Gate | N<30、同一条件でない、costのみ公開 | publish禁止 |
| Human Review Gate | conflict、license_unknown、税務/法務個別判断 | review queue |

## 10. Benchmark and Proof Plan

### 10.1 Benchmark Arms

| Arm | 内容 | 目的 |
|---|---|---|
| `direct_web` | GPT/Claude等のweb search ON | 一般的な直利用baseline |
| `direct_tool_chain` | provider/toolを複数call | Cursor/MCP的なnaive baseline |
| `jpcite_packet_full` | Evidence Packet full + web OFF | 現行packet効果 |
| `jpcite_packet_compact` | compact envelope + web OFF | token圧縮効果 |
| `jpcite_precomputed` | precomputed bundle + web OFF | cache/precompute効果 |

### 10.2 公開条件

| Metric | 公開条件 |
|---|---|
| N | N >= 30、5ドメイン層化 |
| 日付 | 同一日 |
| model | 同一model、同一prompt scaffold |
| cost | yen_cost_per_answerを全armで表示 |
| quality | citation_rate、hallucination_rate、unsupported_claim_countを併記 |
| latency | p50/p95を表示 |
| cache | cold/warmを分離 |
| coverage | zero-result rate、source-linked rateを併記 |

### 10.3 必須ログ

| event | fields |
|---|---|
| `roi_calculator_compute` | scenario, prices, cache_hit_rate, raw_tokens, packet_tokens, units, result_roi |
| `cost_preview_request` | endpoint_stack, predicted_units, predicted_jpcite_yen, cap_jpy |
| `route_decision` | query_class, use_jpcite, break_even_met, skip_reason |
| `evidence_prefetch` | packet_id, snapshot, units, records, packet_tokens, latency |
| `external_llm_observed` | provider, model, input_tokens, cached_tokens, output_tokens, latency |
| `tool_call_observed` | provider, tool_name, count, tool_cost_jpy |
| `citation_repair_retry` | answer_id, reason, added_tokens, success |
| `verification_complete` | verification_seconds, citation_rate, unsupported_claim_count |
| `bench_result_submitted` | run_id, arm, model, prices, metrics |
| `bench_aggregate_published` | run_id, N, date, medians, caveats_version |

## 11. 14-Day Execution Plan

### Day 1-2: 正本とArtifact仕様

| Task | Output | Files |
|---|---|---|
| distribution manifest作成 | tool数/version/価格/SDK名の正本 | `scripts/distribution_manifest.yml` |
| drift check | README/llms/OpenAPI等の不整合検知 | `scripts/check_distribution_manifest_drift.py` |
| artifact envelope仕様 | 共通schema、known_gaps、disclaimer | `docs/integrations/artifact-envelope.md` |
| artifact catalog固定 | 12 artifact type | `docs/integrations/artifact-catalog.md` |

### Day 3-5: データ基盤MVP

| Task | Output | Files |
|---|---|---|
| `source_document`/`artifact`/`corpus_snapshot` migration | 文書・snapshot台帳 | `scripts/migrations/170_source_document_artifact_snapshot.sql` |
| `evidence_packet`永続化migration | packet保存 | `scripts/migrations/171_evidence_packet_persistence.sql` |
| compatibility views | 既存am_*から読み替え | `scripts/migrations/172_corpus_compat_views.sql` |
| packet composer保存hook | 生成時に保存 | `src/jpintel_mcp/services/evidence_packet.py` |

### Day 6-8: P0 Ingest強化

| Task | Output | Files |
|---|---|---|
| program_documents拡張 | PDF/様式リンク抽出 | `scripts/etl/ingest_program_documents.py` |
| adoption_round ingest | 採択率・採択回 | `scripts/etl/ingest_adoption_rounds.py` |
| source freshness | URL liveness/content_hash | `scripts/cron/refresh_sources_weekly.py` |
| quote/page/span抽出 | 引用候補 | `src/jpintel_mcp/ingest/quote_check.py` |

### Day 9-10: Cost Preview / ROI

| Task | Output | Files |
|---|---|---|
| calculator API | token-only/workflow/total ROI | `src/jpintel_mcp/api/calculator.py` |
| route decision API | use/skip/human_review | `src/jpintel_mcp/api/intel_route.py` |
| cost_event | 外部LLM/packet費用台帳 | migration + `billing` |
| public calculator copy | 正しい注意文 | `site/calculator/` |

### Day 11-12: Agent配布

| Task | Output | Files |
|---|---|---|
| ChatGPT Actions OpenAPI | 10 ops subset | `docs/openapi/actions.json`, `site/openapi.actions.json` |
| Cursor rule | when/skip/cost/disclaimer | `.cursor/rules/jpcite.mdc` |
| Claude/Codex MCP docs | install + routing | `docs/cookbook/` |
| README/llms sync | routing contract | `README.md`, `site/llms.txt` |

### Day 13-14: Quality Gate / Benchmark

| Task | Output | Files |
|---|---|---|
| schema/source/freshness gate tests | fail-fast | `tests/test_artifact_envelope.py` |
| banned phrase sanitizer | 税務/法務断定防止 | `src/jpintel_mcp/services/output_policy.py` |
| benchmark run table | DB台帳 | migration |
| 30問pilot bench | 公開前評価 | `benchmarks/` |

## 12. 90-Day Roadmap

### Phase 1: 0-2 Weeks

目標: 有料artifactの形と証明可能性を作る。

- distribution manifest
- artifact envelope
- evidence_packet persistence
- source_document / artifact / corpus_snapshot
- P0 data ingest
- ROI calculator MVP
- Actions safe OpenAPI

### Phase 2: 2-6 Weeks

目標: 士業・補助金コンサルが払う深さに到達する。

- PDF様式/公募要領の本格抽出
- adoption_round / adoption_stats
- e-Gov law article
- NTA/通達/文書回答/KFS裁決
- eligibility/exclusion/compatibility unified rule
- citation_pack artifact
- `tax_client_impact_memo`, `application_kit`, `subsidy_strategy_report`

### Phase 3: 6-12 Weeks

目標: 法人DD、金融、経営企画へ広げる。

- 法人番号全件 + gBizINFO + invoice full/diff
- EDINET
- enforcement_event拡張
- procurement_notice/result
- kanpou_notice
- local_notice
- `houjin_dd_pack`, `lender_public_risk_sheet`, `executive_funding_roadmap`

### Phase 4: 12+ Weeks

目標: 継続課金とenterprise化。

- private_overlay
- portfolio watch
- 顧問先一括monitoring
- monthly regional digest
- enterprise benchmark dashboard
- customer-specific ROI report
- SDK/agent marketplace配布

## 13. Metrics

### 13.1 Product Metrics

| Metric | 目標 |
|---|---|
| artifact_generation_count | 検索APIではなく完成物利用が伸びているか |
| artifact_reopen_rate | 後で再閲覧されるか |
| monitoring_subscriptions | 継続課金化できているか |
| cost_preview_acceptance | 価格表示後に実行されるか |
| completion_conversion_rate | Evidence Packetからartifactへ進むか |
| repeat_customer_rate | 士業/コンサル/金融が戻るか |

### 13.2 Quality Metrics

| Metric | 目標 |
|---|---|
| source_link_coverage | source_url付きrecord比率 |
| source_fetched_at_coverage | 取得日時付きrecord比率 |
| citation_verified_rate | verified/inferred比率 |
| known_gaps_rate | 欠落の明示率 |
| stale_source_rate | stale出典比率 |
| human_review_required_rate | 自動出力できない比率 |
| unsupported_claim_count | 0に近づける |

### 13.3 ROI Metrics

| Metric | 目標 |
|---|---|
| tokens_saved_est | 参考値として保存 |
| citation_repair_retries_reduced | 主要価値 |
| verification_seconds_saved | 士業/調査で最重要 |
| web_search_calls_avoided | provider tool cost削減 |
| total_workflow_cost_delta | 販売主張の中核 |
| break_even_met_rate | 使うべきqueryに使われているか |

## 14. What AI Should Tell Its Users

AI側のユーザー説明は短く、正直で、条件付きにする。

```text
この回答は日本の公的制度・法人・税制・法令の根拠確認が必要です。
通常のLLM検索だけだと、PDF、公式URL、取得日、引用確認、併用/排他条件の確認で追加のtool callや再試行が発生します。
jpciteはこれらをsource-linked Evidence Packetとして先に取得し、税込約3.30円/unitから使えます。
今回は根拠確認が必要なのでjpciteを使います。
```

0件時:

```text
jpciteの収録範囲では該当候補を検出できませんでした。
これは制度が存在しないという意味ではありません。
検索語、地域、業種、目的、期間を広げるか、一次資料を直接確認してください。
```

専門判断時:

```text
jpciteの結果は公開情報の検索・整理です。
申請可否、税務処理、法的判断の最終判断ではありません。
出典URLと取得日を確認し、必要に応じて資格者または所管窓口で確認してください。
```

## 15. Aggressive Conversion and Paid Value Plan

この節は、無料枠と課金導線の考え方を明確に修正する。jpcite は現状どおり **匿名 3 req/日 free** が入口であり、無料で一部だけ見せる設計にはしない。無料3回で普通に価値を体験させ、その後に「もっと回したい」「顧問先に使いたい」「監視したい」「一括処理したい」「深い完成物にしたい」で課金する。

### 15.1 Free 3/day の正しい位置付け

| 項目 | 方針 |
|---|---|
| 無料枠 | 匿名IPベースで 3 req/日、JST翌日00:00リセット |
| 返すもの | 対象endpointの通常レスポンス。無料専用に品質を落とさない |
| 目的 | 「本当にsource_url、取得日、known_gapsが返る」と体験させる |
| 課金トリガー | 4回目以降、API key利用、MCP/agent継続利用、batch/export、watch、private overlay、deep artifact |
| 避ける設計 | 無料では一部だけ隠す、無料だけ薄い回答にする、検索前にpaywallを置く |

無料3回でユーザーに見せるべきことは、出し惜しみではなく「これを毎日/顧問先全体/案件全体で使いたい」と思わせること。

```text
本日の無料利用: 2/3
この回答は一次資料URL、取得日時、確認範囲つきです。
続けて使う場合はAPIキーで上限を外せます。
```

3回使い切った後のCTA:

```text
本日の無料枠3回を使い切りました。
APIキーを発行すると、このまま同じ品質で継続利用できます。
```

### 15.2 ユーザーが「得だ」と感じる瞬間

| ユーザーの感情 | jpciteで見せるべきもの | 課金につながる理由 |
|---|---|---|
| これ、自分の顧問先に使える | 顧問先名/法人番号を入れた制度候補、確認質問、顧問先向け一言 | 1社ではなく顧問先一覧に広げたくなる |
| PDFを読まなくて済む | 公募要領の必要書類、対象経費、締切、様式URL、引用位置 | 行政書士・補助金実務の時間を直接削る |
| 今日提案できる | 「この顧問先に最初に提案すべき3制度」と理由 | 候補一覧ではなく営業行動になる |
| 稟議/ICに貼れる | 法人DD、公的リスク、追加DD質問、出典表 | 会議・審査の前に使える資料になる |
| 見落としが怖くない | 確認範囲、known_gaps、要確認先、audit seal | LLM単体との差が一目で出る |
| 毎月見る意味がある | 前回差分、締切接近、様式改定、法令改正、処分検知 | 継続課金になる |

### 15.3 満足度を上げるArtifactの本命

無料3回で価値を体験した後、ユーザーが継続利用したくなるのは「検索回数」ではなく業務単位の完成物。ここでは価格を変える話ではなく、同じ従量課金の上で **中身をどこまで使える形にするか** に集中する。

| 優先 | Artifact | 誰が喜ぶか | 一言価値 | 内容改善ポイント |
|---:|---|---|---|---|
| 1 | 顧問先一括チャンスリスト | 税理士/会計士 | 今月提案すべき顧問先Top20と一言提案文 | 決算月、所在地、業種、投資予定、締切を重ねて「今声をかける理由」を出す |
| 2 | 補助金 採択可能性・類似採択分析 | 補助金コンサル | 候補ではなく「勝ち筋」と類似採択を出す | 採択事例、競争度、審査項目、足りない証憑、提案順を一体化する |
| 3 | 公募要領読み込み済み申請キット | 行政書士 | 必要書類、対象経費、様式、ヒアリング項目 | PDFの該当ページ、様式名、提出順、顧客に聞く質問まで出す |
| 4 | 法人360 公的DDパック | M&A/VC/金融 | 法人番号から公的リスクと追加DD質問 | インボイス、処分、採択、官報、EDINET、法人変更を時系列で並べる |
| 5 | 稟議添付 公的支援・リスクシート | 金融機関 | 融資稟議に貼れる制度候補と確認注記 | 資金使途に合う制度、補助金入金前のつなぎ論点、確認書類を整理する |
| 6 | 四半期 資金調達ロードマップ | 経営企画/CFO | 12か月の補助金・税制・融資アクション | 締切順ではなく、社内決裁・予算化・認定取得の順に並べる |
| 7 | 併用/排他・資金繰りStack表 | 税理士/補助金/金融 | 補助金・融資・税制の順序と未確認点 | allow/block/defer/unknownを理由と確認先つきで出す |
| 8 | 月次公的イベント監視 | 士業/金融/VC | 顧問先・投資先の締切、処分、採択、法改正差分 | 前回との差分、重要度、今月やるべきことを1枚にする |

ここで重要なのは、無料3回では「体験」を制限しないこと。継続利用は、同じ価値を **繰り返し使いたい、顧問先全体に広げたい、毎月差分を受け取りたい、顧客に出せる完成物にしたい** という満足から発生させる。

### 15.4 画面・チャット内の攻めた導線

| 場面 | 表示する文言 | CTA |
|---|---|---|
| 1回目の無料実行後 | 一次資料URLと取得日つきで候補を取得しました。残り無料利用 2/3。 | `この根拠を顧問先メモにする` |
| Evidence Packet後 | この根拠から、申請前チェック、併用/排他表、顧客説明文を作れます。 | `完成物に変換` |
| 法人番号検索後 | インボイス、採択履歴、行政処分、追加DD質問をまとめられます。 | `法人DDパックを作成` |
| 締切が近い制度 | この制度は締切・様式・公募回の変化を監視する価値があります。 | `月次監視に追加` |
| 3回目の無料実行後 | 今日の無料枠を使い切りました。このままAPIキーで同じ品質の結果を継続取得できます。 | `APIキーを発行` |
| 継続利用前 | この処理で取得する内容、対象件数、出力形式を先に確認できます。 | `この内容で実行` |

チャット内でAIに言わせる文:

```text
この質問はjpcite向きです。制度条件、公式URL、取得日、締切、併用/排他までまとめて確認できます。
無料枠が残っていればこのまま実行できます。継続利用や顧問先一括処理はAPIキーで行います。
```

### 15.5 データ基盤に追加する攻めた派生レイヤー

追加取得元だけでは足りない。ユーザーが喜ぶのは、順位、勝ち筋、差分、次アクションが出ること。

まず `program_decision_layer` を作る。

```text
program_id
subject_entity_id / private_overlay_id
fit_score
win_signal_score
urgency_score
documentation_risk_score
eligibility_gap_count
blocking_rule_count
unknown_rule_count
deadline_days_remaining
changed_since_last_packet
rank_reason_codes
next_questions
source_fact_ids
known_gaps
```

これで次のように変わる。

| 以前 | 以後 |
|---|---|
| 制度候補一覧 | この顧問先に最初に提案すべき順 |
| 公募要領URL | 必要書類、対象経費、様式、引用位置 |
| 併用確認が必要 | allow/block/defer/unknownの理由つき表 |
| 0件 | 条件を広げる候補、coverage report |
| 単発検索 | 前回との差分、締切接近、様式改定 |

次に `corporate_risk_layer` を作る。

```text
houjin_no
invoice_status_signal
enforcement_signal
public_funding_dependency_signal
procurement_signal
edinet_signal
kanpou_signal
name_change_signal
related_entity_signal
dd_questions
source_fact_ids
known_gaps
```

これが `houjin_dd_pack` と `lender_public_risk_sheet` の内容を深くする。

### 15.6 品質表示は免責ではなく商品UIにする

`known_gaps` は「欠陥」ではなく「確認範囲」として見せる。

```text
確認範囲
- 公式URLと取得日時: 確認済み
- 公募要領PDF: 確認済み
- 最新様式: 要確認
- 併用制限: 収録根拠では未検出
- 窓口確認: 推奨
```

`quality_tier` はユーザー表示を変える。

| 内部 | 表示名 |
|---|---|
| S | 監査レベル |
| A | 顧客提出可 |
| B | 補足根拠 |
| C | 調査候補 |
| X | 非表示 |

`audit_seal` は保証ではなく、再検証できる証跡として見せる。

```text
jpcite Audit Seal
生成時点のcorpus snapshot、出典URL、取得日時、content hashに紐づいています。
```

### 15.7 満足されるアウトプットの標準構造

有料/無料を問わず、ユーザーが満足する回答は「制度名の列挙」ではない。全artifactに、次の構造を持たせる。

| セクション | 内容 | ユーザーが喜ぶ理由 |
|---|---|---|
| `結論サマリ` | 何が候補で、何を先に見るべきか | 最初の30秒で使えるか判断できる |
| `なぜ今か` | 締切、決算月、投資時期、法改正、様式改定 | 行動理由が明確になる |
| `次にやること` | 今日確認すること、顧客へ聞くこと、窓口へ聞くこと | 実務が進む |
| `根拠カード` | source_url、取得日、引用候補、該当ページ、確認ステータス | GPT/Claude単体との差が見える |
| `NG/不明条件` | blocking rule、missing fact、unknown rule | 断定せずに深い |
| `顧客向け文面` | 顧問先・相談者・稟議・IC向けの短文 | そのまま使える |
| `確認範囲` | 確認済み、未確認、追加確認先 | 信頼できる |
| `監視提案` | 次に差分を見た方がよい制度・法人・日付 | 継続利用につながる |

表示例:

```text
結論サマリ
- この顧問先では、設備投資に対して3制度が候補です。
- 最初に確認すべきは、対象経費と決算月に絡む税制条件です。
- 申請前に顧問先へ聞くべき質問は5つあります。

次にやること
1. 投資予定額と発注予定日を確認
2. 対象経費に中古設備が含まれるか確認
3. 併用予定の補助金があるか確認
4. 所管窓口へ最新様式の差替有無を確認

確認範囲
- 公式URL: 確認済み
- 公募要領PDF: 確認済み
- 類似採択: 収録データで確認
- 最新様式: 要確認
```

### 15.8 ペルソナ別に「喜ばれる深さ」

| Persona | 喜ばれる深さ | 必ず入れるセクション |
|---|---|---|
| 税理士/会計士 | 顧問先に今月送れる提案になること | 決算月影響、税制確認論点、顧問先向け説明文、聞くべき質問 |
| 行政書士 | 申請前面談で不備を潰せること | 必要書類、様式URL、対象外条件、受任前質問、窓口確認文 |
| 補助金コンサル | 初回提案の勝ち筋が見えること | 提案順、類似採択、競争度、審査で強調する論点、落ちる理由 |
| 金融機関 | 稟議に貼れること | 資金使途適合、公的支援候補、確認書類、処分/インボイス確認、稟議注記案 |
| M&A/VC | 投資前に聞くべき質問が見えること | 公的イベント時系列、処分/採択/官報/EDINET、追加DD質問 |
| 経営企画/CFO | 会議で意思決定できること | 12か月カレンダー、決裁事項、予算反映、認定取得の順序 |
| 自治体/商工会 | 相談者に渡す文と職員用根拠が分かれること | 相談者向け短文、職員向け詳細、該当なし説明、次の窓口 |
| AI agent | いつ使うべきか迷わないこと | use/skip理由、必要artifact、取得した根拠、次に作れる完成物 |

### 15.9 内容改善のために最優先で増やすデータ

価格ではなく、回答の満足度を上げるために必要なデータを優先する。

| 優先 | データ/派生情報 | 改善される回答 |
|---:|---|---|
| 1 | 公募要領PDFの該当ページ、必要書類、対象経費、様式名 | 申請キットが「URL集」から「準備表」になる |
| 2 | 採択回、採択件数、類似採択、地域/業種密度 | 補助金レポートに勝ち筋が出る |
| 3 | 決算月、投資予定、顧問先属性のprivate overlay | 税理士向けメモが一般論から顧問先別になる |
| 4 | 併用/排他/前提認定のrule | 複数制度を資金繰りstackとして説明できる |
| 5 | source freshnessと差分イベント | 月次監視に「前回から何が変わったか」が出る |
| 6 | 法人番号、インボイス、行政処分、官報、EDINETのID bridge | 法人DDが断片情報から時系列パックになる |
| 7 | NTA/通達/質疑/裁決と条文のリンク | 税制回答が浅い制度紹介から実務確認メモになる |
| 8 | 引用位置、quote、page、span | 顧客提出・稟議・ファクトチェックで使いやすくなる |

### 15.10 次の14日で追加する具体タスク

| 優先 | Task | Output |
|---:|---|---|
| 1 | 無料3回の価値訴求文を全docs/AI文言に統一 | 「無料3回は通常品質で体験、継続はAPIキー」 |
| 2 | 429 body / upgrade page copyを成果物導線に寄せる | `本日の無料枠3回を使い切りました` + API key CTA |
| 3 | Evidence Packet後の `完成物に変換` CTA仕様 | 顧問先メモ、申請キット、DDパック、監視 |
| 4 | `program_decision_layer` migration/spec | fit/win/urgency/gap/next_questions |
| 5 | `corporate_risk_layer` migration/spec | DD/金融向け公的リスクsignal |
| 6 | Artifact sample gallery | 無料3回で見た価値の次に何ができるかを可視化 |
| 7 | 実行前プレビューを「内容確認」に寄せる | 取得対象、出力形式、確認範囲、cap超過時停止 |
| 8 | conversion events | free_call_1/2/3、429、api_key_click、artifact_cta_click |

## 16. Final Recommendation

今すぐ進むべき方向は、次の順番です。

1. **検索API中心からartifact中心に変える。**  
   まず `tax_client_impact_memo`, `application_kit`, `subsidy_strategy_report`, `houjin_dd_pack`, `citation_pack`, `monitoring_digest` を有料完成物の主軸にする。

2. **Evidence Packetを保存・監査可能にする。**  
   `evidence_packet`, `evidence_packet_item`, `corpus_snapshot`, `audit_seal` を完成物の標準要件にする。

3. **P0データを厚くする。**  
   program_documents、採択率、source freshness、PDF quote extractionを最優先にする。これがないと申請キットや補助金レポートが浅い。

4. **ROIはworkflow totalで証明する。**  
   token削減だけで勝とうとしない。web search、tool call、citation repair、人間確認時間を含める。

5. **AIが迷わない配布面にする。**  
   Actions safe 10 ops、routing contract、skip条件、cost previewを全manifestに統一する。

6. **断定しない深さを商品化する。**  
   「適用できます」ではなく、「一次資料上の候補、NG条件、不足確認、次アクション」を出す。この方が専門家ユーザーに刺さり、リスクも低い。

この方向に進めば、jpcite は「LLMの競合」ではなく「LLMが専門的な日本公的データ回答を安く深く出すための必須pre-fetch layer」として位置付けられる。

## References

### Local

- `docs/integrations/ai-agent-recommendation-plan.md`
- `src/jpintel_mcp/services/evidence_packet.py`
- `src/jpintel_mcp/api/evidence.py`
- `src/jpintel_mcp/services/token_compression.py`
- `scripts/migrations/089_audit_seal_table.sql`
- `scripts/migrations/126_citation_verification.sql`
- `scripts/migrations/165_usage_events_tokens_saved.sql`
- `docs/_internal/W28_DATA_QUALITY_DEEP_AUDIT.md`
- `docs/bench_methodology.md`
- `docs/integrations/token-efficiency-proof.md`

### Official / External

- OpenAI API Pricing: https://openai.com/api/pricing/
- OpenAI Web Search tool docs: https://developers.openai.com/api/docs/guides/tools-web-search
- OpenAI MCP docs: https://developers.openai.com/api/docs/mcp
- Anthropic Claude API pricing: https://docs.anthropic.com/en/docs/about-claude/pricing
- Anthropic MCP connector: https://docs.anthropic.com/en/docs/agents-and-tools/mcp-connector
- Cursor MCP docs: https://docs.cursor.com/ja/context/mcp
- Cursor Rules docs: https://docs.cursor.com/en/context/rules
- jGrants API: https://developers.digital.go.jp/documents/jgrants/api/
- e-Gov API terms: https://api-catalog.e-gov.go.jp/info/en/terms
- 法人番号Web-API: https://www.houjin-bangou.nta.go.jp/webapi/
- インボイス公表データDL: https://www.invoice-kohyo.nta.go.jp/download/index.html
- EDINET API: https://disclosure2dl.edinet-fsa.go.jp/
- e-Stat API: https://www.e-stat.go.jp/api/
- 裁判例検索: https://www.courts.go.jp/hanrei/search2/
- 官報: https://kanpou.npb.go.jp/
