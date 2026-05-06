# jpcite 本体実装準備計画 2026-05-06

## 目的

外部の2本の情報収集CLIが重い調査を進める間に、本体側は「深い有料アウトプット」を受け止めるDB/API/検証基盤を準備する。

本体の焦点は、検索結果を増やすことではなく、以下を出せる状態にすること。

- Evidence Packet を保存・再検証できる
- source document / extracted fact / corpus snapshot が追跡できる
- 法人・制度・法令・税制・行政処分・採択・インボイスを横断した完成物を返せる
- GPT / Claude / Cursor が jpcite を使う理由を、回答品質と再現性で示せる
- 無料3回/日で価値が見え、有料ユーザーが深い成果物に満足する

## 公開表記の扱い

`https://jpcite.com/about` の「法令 (うち本文収録 154 件)」は古い表示だった。

手元DBで確認した現行値:

- `data/jpintel.db.laws`: 法令メタデータ 9,484 件
- `autonomath.db.am_law_article`: 法令本文DB 6,493 法令
- `autonomath.db.am_law_article`: 条文本文行 352,970 行

ただし、これから大量の情報収集とデータ基盤拡張を行うため、現時点では公開サイト・README・配布文面の数字は先に変更しない。公開表記の更新は、情報収集後にSOTを確定してからまとめて行う。

後で行う候補:

- `scripts/generate_public_counts.py` に本文収録済み法令数と条文行数を追加
- `site/_data/public_counts.json` を正本に寄せる
- `site/about.html`, `site/index.html`, `site/llms.txt`, `site/press/index.html`, README, registry submission などを一括更新
- 「154件」表記を公開上どう説明するかを、全文検索対象、条文DB対象、metadata resolver対象に分けて整理する

## 外部CLIとの分担

### CLI-A: Public Source Foundation

担当:

- 追加すべき一次情報ソース
- 取得方式
- 利用条件
- join key
- schema backlog
- どの完成物に効くか

成果物:

- `tools/offline/_inbox/public_source_foundation/source_profiles_YYYY-MM-DD.jsonl`
- `source_matrix.md`
- `schema_backlog.md`
- `risk_register.md`

本体側の受け取り方:

- `schema_backlog.md` を migration queue に分解
- `source_profiles_*.jsonl` を `source_registry` 設計に反映
- P0ソースは `source_document` / `artifact` / `extracted_fact` へ接続する

### CLI-B: Output and Market Validation

担当:

- persona別の課金される完成物
- GPT / Claude 単体との差分
- 初回3回無料で見せる体験
- benchmark query
- 顧客インタビュー質問

成果物:

- `tools/offline/_inbox/output_market_validation/persona_value_map.md`
- `artifact_catalog.md`
- `competitive_matrix.md`
- `benchmark_design.md`
- `interview_questions.md`

本体側の受け取り方:

- `artifact_catalog.md` を API endpoint と response schema に変換
- `benchmark_design.md` を regression / eval harness に変換
- persona別完成物を docs / examples / trial flow に反映

## 実装順序

### 1. Corpus Snapshot 台帳

最初に `corpus_snapshot` を作る。

理由:

- Evidence Packet と artifact の時点固定に必要
- 「その回答はどのDBスナップショットで作ったか」を後から再現するため
- GPT / Claude に渡す根拠パケットの信用を上げるため

想定migration:

- `scripts/migrations/172_corpus_snapshot.sql`

候補schema:

- `corpus_snapshot_id`
- `db_name`
- `snapshot_kind`
- `created_at`
- `table_counts_json`
- `content_hash`
- `source_freshness_json`
- `known_gaps_json`

seed:

- `programs`
- `laws`
- `am_law_article`
- `tax_rulesets`
- `court_decisions`
- `am_source`
- `am_entities`
- `am_entity_facts`

### 2. Artifact 台帳

次に `artifact` を作る。

対象:

- raw PDF
- HTML
- JSONL
- 生成済み report
- Evidence Packet に添付する引用可能ファイル

候補schema:

- `artifact_id`
- `artifact_kind`
- `uri`
- `sha256`
- `bytes`
- `mime_type`
- `retention_class`
- `license`
- `corpus_snapshot_id`
- `created_at`

注意:

- public corpus raw と customer-generated artifact は分ける
- 有料ユーザー生成物は retention / privacy を別テーブルか別DBで扱う

### 3. Source Document 台帳

`source_document` を追加し、`am_source` を seed 元にする。

候補schema:

- `source_document_id`
- `source_url`
- `canonical_url`
- `domain`
- `publisher`
- `document_kind`
- `license`
- `content_hash`
- `fetched_at`
- `last_verified_at`
- `http_status`
- `artifact_id`
- `corpus_snapshot_id`
- `robots_status`
- `tos_note`
- `known_gaps_json`

目的:

- 回答ごとの出典一覧を固定する
- URLが死んでも取得時点の証跡を残す
- source quality layer を作れるようにする

### 4. Extracted Fact v2

`am_entity_facts` をそのまま使うだけでは、引用位置・quote・page/span が弱い。`extracted_fact` を追加する。

候補schema:

- `fact_id`
- `subject_kind`
- `subject_id`
- `source_document_id`
- `field_name`
- `value_text`
- `value_number`
- `value_date`
- `quote`
- `page_number`
- `span_start`
- `span_end`
- `selector_json`
- `extraction_method`
- `confidence_score`
- `valid_from`
- `valid_until`
- `known_gaps_json`

backfill:

- 既存 `am_entity_facts` から投入
- quote / page / span がないものは `known_gaps=['quote_position_missing']`

### 5. Entity ID Bridge

法人番号、インボイス、gBizINFO、EDINET、内部entityを結ぶ。

候補schema:

- `entity_id`
- `id_namespace`
- `external_id`
- `bridge_kind`
- `confidence`
- `source_document_id`
- `observed_at`
- `valid_from`
- `valid_until`

seed:

- `houjin_master`
- `invoice_registrants`
- `am_id_bridge`
- EDINET / gBizINFO はCLI-Aの調査結果を受けて追加

### 6. Evidence Packet 永続化

現状の `services/evidence_packet.py` は composer 中心で「NO writes」。ここに optional persistence を足す。

想定migration:

- `scripts/migrations/177_evidence_packet_persistence.sql`

候補schema:

- `evidence_packet`
  - `packet_id`
  - `endpoint`
  - `request_hash`
  - `api_key_hash`
  - `corpus_snapshot_id`
  - `created_at`
  - `audit_seal_id`
  - `known_gaps_json`
- `evidence_packet_item`
  - `packet_id`
  - `item_index`
  - `subject_kind`
  - `subject_id`
  - `fact_id`
  - `source_document_id`
  - `citation_verification_id`
  - `item_hash`

API方針:

- 既存 shape は壊さない
- `persist=true` を追加
- 有料keyでは自動保存を検討
- 匿名3回枠は原則保存しない、または短期retention

## Derived Data Layer

### Program Decision Layer

目的:

- 補助金・融資・税制の「見るべき / 見送るべき」を返す

必須フィールド:

- `fit_score`
- `win_signal_score`
- `urgency_score`
- `documentation_risk_score`
- `deadline_days_remaining`
- `rank_reason_codes`
- `recommended_action`
- `next_questions`
- `source_fact_ids`
- `known_gaps`

### Corporate Risk Layer

目的:

- 法人DD、金融、営業BD、M&A/VC向けの横断リスク確認

必須フィールド:

- `invoice_status_signal`
- `enforcement_signal`
- `public_funding_dependency_signal`
- `procurement_signal`
- `edinet_signal`
- `name_change_signal`
- `risk_timeline`
- `dd_questions`
- `risk_reason_codes`
- `known_gaps`

### Source Quality Layer

目的:

- 回答の信用を数値化する

必須フィールド:

- `source_document_id`
- `publisher`
- `document_kind`
- `fetched_at`
- `content_hash`
- `license`
- `verification_status`
- `freshness_bucket`
- `quote_coverage`
- `confirming_source_count`
- `cross_source_agreement`
- `quality_tier`
- `known_gaps`

### Document Requirement Layer

目的:

- 申請キットを「候補一覧」から「提出準備」に引き上げる

必須フィールド:

- `program_id`
- `document_name`
- `required_or_optional`
- `applicant_condition`
- `source_document_id`
- `quote`
- `known_gaps`

### Monitoring Delta Layer

目的:

- 月次ダイジェスト、法改正、制度変更、取引先状態変化を出す

必須フィールド:

- `subject_kind`
- `subject_id`
- `previous_snapshot_id`
- `current_snapshot_id`
- `changed_fields`
- `severity`
- `action_required`
- `source_document_ids`

## Artifact API 実装候補

最初に作る順序:

1. `POST /v1/artifacts/compatibility_table`
2. `POST /v1/artifacts/houjin_dd_pack`
3. `POST /v1/artifacts/application_kit`
4. `POST /v1/artifacts/tax_client_impact_memo`
5. `POST /v1/artifacts/monitoring_digest`
6. `GET /v1/artifacts/{artifact_id}`

共通response envelope:

```json
{
  "artifact_id": "art_...",
  "artifact_type": "houjin_dd_pack",
  "corpus_snapshot_id": "snap_...",
  "packet_id": "pkt_...",
  "summary": {},
  "sections": [],
  "sources": [],
  "known_gaps": [],
  "next_actions": [],
  "human_review_required": [],
  "audit_seal": {}
}
```

## 最初の有料価値に直結する4本

### Compatibility Table

既存 `/v1/funding_stack/check` が強いので最短。

価値:

- 補助金・融資・税制の併用可否
- 見送り理由
- 次に聞く質問
- 税理士、補助金コンサル、金融機関に刺さる

### Houjin DD Pack

既存 `/v1/intel/houjin/{houjin_id}/full` と DD batch を活用。

価値:

- 法人番号起点の出典付きDD
- インボイス、行政処分、採択、入札、EDINETを横断
- M&A/VC、金融、営業BDに刺さる

### Application Kit

`document_requirement_layer` が必要。

価値:

- 必要書類
- 対象外理由
- ヒアリング質問
- 申請前チェックリスト
- 行政書士、補助金コンサルに刺さる

### Tax Client Impact Memo

法令本文DB、税制ルールセット、NTA/KFS/通達が効く。

価値:

- 顧問先向け初期調査メモ
- 根拠条文 / 通達 / 裁決の chain
- 税理士・会計事務所に刺さる

## Benchmark / QA

比較arm:

- `direct_web`: GPT/Claude + Web検索
- `jpcite_packet`: Evidence Packetのみ
- `jpcite_precomputed_intelligence`: 事前生成bundle

評価指標:

- citation_rate
- source_url coverage
- fetched_at coverage
- unsupported_claim_rate
- known_gaps coverage
- time_to_first_usable_answer
- reviewer_minutes_saved
- copy_paste artifact completion rate
- jpcite_requests
- yen_cost_per_answer

最低限のテスト:

- migration apply/rollback
- backfill unit test
- Evidence Packet persistence test
- artifact common envelope contract test
- existing endpoint regression
- source_document 解決率 smoke
- known_gaps の欠落検知

## Cloudflare / WAF 準備

現状の要点:

- `api.jpcite.com` は Fly direct の可能性があり、Cloudflare proxied になっていないと WAF は効かない
- Cloudflare Free では Custom Rules 5、Rate Limit 1 の想定で圧縮が必要
- Business なら既存 `cloudflare-rules.yaml` に近い形で展開しやすい

本体側でやること:

1. DNS proxy ON / Full strict の手順を runbook 化
2. Free向け5 rule案を作る
3. Business向けfull rule案を作る
4. WAF検証コマンドを固定する
5. app内 token bucket / anon 3 req/day / monthly cap を残す

注意:

- WAF設定は本番に影響するので、実変更は明示タイミングで行う
- Origin bypass 対策は別タスクにする

## 30日実装計画

### Day 1-3

- 法令count表示の修正を完了
- `corpus_snapshot` migration案
- `source_document` / `artifact` / `extracted_fact` schema案
- CLI-A / CLI-B を走らせる

### Day 4-7

- `corpus_snapshot` seed
- `source_document` backfill
- `source_quality_layer` prototype
- Evidence Packet `persist=true` の最小実装

### Day 8-14

- `compatibility_table` artifact
- `houjin_dd_pack` artifact
- artifact common envelope
- benchmark harness v1

### Day 15-21

- `document_requirement_layer`
- `application_kit` JSON artifact
- `tax_client_impact_memo` skeleton
- docs/examples/trial flow 反映

### Day 22-30

- monitoring digest prototype
- CLI-AのP0 sourceをschema backlogへ反映
- CLI-Bのpersona benchmarkをevalに反映
- Cloudflare WAF runbookとFree/Business rule分岐

## 完了条件

最初の完成条件:

- ユーザーが1回のAPI呼び出しで「完成物」を受け取れる
- その完成物に `artifact_id`, `packet_id`, `corpus_snapshot_id`, `sources`, `known_gaps` が入る
- 出典URLと取得時刻が見える
- GPT / Claude 単体との差分を benchmark で説明できる
- 匿名3回無料で「これは得」と感じるサンプル導線がある

## 次に本体で着手するタスク

1. `corpus_snapshot` / `source_document` / `artifact` / `extracted_fact` のmigration設計
2. `scripts/generate_public_counts.py` を基準に公開件数のSOTを固める
3. Evidence Packet composer に optional persistence を追加する設計
4. `compatibility_table` artifact のresponse contractを先に作る
5. CLI-A/Bの `_inbox` 出力を取り込む統合手順を決める
