# 外部情報収集CLI inbox contract 2026-05-06

## 目的

外部で走る2本の情報収集CLIが `tools/offline/_inbox/` 配下に成果物を出した後、本体側がどう検証し、隔離し、実装 backlog に変換するかを定義する。

対象:

- CLI-A: `tools/offline/_inbox/public_source_foundation/`
- CLI-B: `tools/offline/_inbox/output_market_validation/`

この契約では、CLI成果物を本番DBへ直接投入しない。最初の受け取り先は「候補台帳」と「実装/API/test backlog」であり、DB migration や API 実装は人間レビュー後の別スライスで行う。

既存 `scripts/cron/ingest_offline_inbox.py` の流儀に合わせる点:

- JSONL は1行1JSONで処理する
- 行単位で validation し、失敗行は quarantine する
- 成功済みファイルは `_done/` に移す
- `--dry-run` 相当の検証だけの実行を前提にする
- 取り込み処理は LLM API を呼ばない

## 入力ディレクトリ

### CLI-A: public source foundation

期待ファイル:

- `tools/offline/_inbox/public_source_foundation/source_profiles_YYYY-MM-DD.jsonl`
- `tools/offline/_inbox/public_source_foundation/source_matrix.md`
- `tools/offline/_inbox/public_source_foundation/schema_backlog.md`
- `tools/offline/_inbox/public_source_foundation/risk_register.md`
- `tools/offline/_inbox/public_source_foundation/progress.md`

必須取り込み対象は `source_profiles_YYYY-MM-DD.jsonl`。Markdown は補助情報として読み、レビュー・backlog 補強に使う。

### CLI-B: output market validation

期待ファイル:

- `tools/offline/_inbox/output_market_validation/persona_value_map.md`
- `tools/offline/_inbox/output_market_validation/artifact_catalog.md`
- `tools/offline/_inbox/output_market_validation/competitive_matrix.md`
- `tools/offline/_inbox/output_market_validation/benchmark_design.md`
- `tools/offline/_inbox/output_market_validation/interview_questions.md`
- `tools/offline/_inbox/output_market_validation/progress.md`

CLI-B は Markdown が正本。`artifact_catalog.md` と `benchmark_design.md` は、機械抽出できる JSON block を含むことを期待する。JSON block が無い場合もファイル全体は quarantine せず、`manual_parse_required` として人間レビュー backlog に送る。

## 入力 schema

### SourceProfile JSONL

1行1件。必須/任意の区分は本体取り込み側の契約であり、CLI-A の元 prompt より少し厳しく扱う。

```json
{
  "source_id": "gbizinfo_api_v2",
  "priority": "P0",
  "official_owner": "デジタル庁",
  "source_url": "https://...",
  "source_type": "api",
  "data_objects": ["corporate_profile", "certification"],
  "acquisition_method": "REST API with API token",
  "api_docs_url": "https://...",
  "auth_needed": true,
  "rate_limits": "officially documented or unknown",
  "robots_policy": "allowed",
  "license_or_terms": "gov_standard",
  "attribution_required": "出典表示が必要",
  "redistribution_risk": "medium",
  "update_frequency": "daily",
  "expected_volume": "rows/files estimate",
  "join_keys": ["houjin_bangou"],
  "target_tables": ["source_document", "entity_id_bridge"],
  "new_tables_needed": ["edinet_documents"],
  "artifact_outputs_enabled": ["houjin_dd_pack"],
  "sample_urls": ["https://..."],
  "sample_fields": ["field_a", "field_b"],
  "known_gaps": ["license_needs_review"],
  "next_probe": "confirm paging and delta endpoint",
  "checked_at": "2026-05-06T00:00:00+09:00"
}
```

必須:

- `source_id`: `^[a-z0-9][a-z0-9_]{2,80}$`
- `priority`: `P0|P1|P2`
- `official_owner`: non-empty string
- `source_url`: absolute `http` or `https` URL
- `source_type`: `api|csv|html|pdf|zip|rss|sitemap`
- `data_objects`: non-empty string array
- `acquisition_method`: non-empty string
- `robots_policy`: `allowed|disallowed|not_applicable|unknown`
- `license_or_terms`: `pdl_v1.0|gov_standard|cc_by_4.0|public_domain|unknown|proprietary`
- `redistribution_risk`: `low|medium|high`
- `update_frequency`: `daily|weekly|monthly|ad_hoc|unknown`
- `join_keys`: array。空配列は valid だが backlog priority を落とす
- `target_tables`: array
- `new_tables_needed`: array
- `artifact_outputs_enabled`: array
- `sample_urls`: array
- `sample_fields`: array
- `known_gaps`: array
- `checked_at`: timezone 付き ISO-8601

任意:

- `api_docs_url`: URL または null
- `auth_needed`: boolean。欠落時は `unknown_auth` 扱いで quarantine ではなく review
- `rate_limits`: string
- `attribution_required`: string
- `expected_volume`: string
- `next_probe`: string

正規化:

- `source_id` は小文字化し、空白・ハイフンは `_` に寄せる。ただし正規化後に衝突した場合は quarantine
- `join_keys` は既知 key を優先順で並べる: `houjin_bangou`, `invoice_registration_number`, `source_url`, `law_id`, `law_number`, `article_number`, `case_number`, `decision_date`, `ministry`, `authority`, `prefecture`, `municipality`, `region_code`, `edinet_code`, `sec_code`, `procurement_notice_id`, `award_id`, `notice_url`
- `target_tables` に未知 table があっても valid。`schema_backlog` 側に送る

### Artifact catalog item

`artifact_catalog.md` から fenced `json` block を抽出する。1 block が1 artifact。JSON block が無い section は `manual_parse_required`。

```json
{
  "artifact_name": "法人DD Evidence Dossier",
  "persona": "M&A/VC/DD",
  "user_input": ["houjin_bangou", "company_name"],
  "output_format": "markdown",
  "required_sections": [
    "executive_summary",
    "cross_source_signals",
    "source_list",
    "known_gaps",
    "human_review_questions"
  ],
  "data_joins": ["houjin_master", "invoice_registrants", "enforcement_cases"],
  "copy_paste_ready_parts": ["DD質問票", "社内メモ"],
  "human_review_required": ["最終与信判断", "法的評価"],
  "paid_reason": "出典付きで複数公的DBを確認する時間を短縮する"
}
```

必須:

- `artifact_name`: non-empty string
- `persona`: non-empty string
- `user_input`: non-empty string array
- `output_format`: `markdown|json|csv|docx`
- `required_sections`: non-empty string array
- `data_joins`: array
- `copy_paste_ready_parts`: array
- `human_review_required`: non-empty string array
- `paid_reason`: non-empty string

本体側で付与する派生 field:

- `artifact_type`: `artifact_name` から slug 化
- `implementation_priority`: persona 選定後に `P0|P1|P2|defer`
- `api_contract_needed`: boolean
- `test_backlog_needed`: boolean
- `source_profile_dependencies`: SourceProfile の `artifact_outputs_enabled` と照合した `source_id[]`

### Benchmark query item

`benchmark_design.md` は persona 別に最低5問を期待する。機械抽出可能な fenced `json` block があれば1 query として読む。Markdown 表だけの場合は `manual_parse_required`。

```json
{
  "query": "この法人についてインボイス登録と行政処分履歴を確認し、DD質問票を作ってください",
  "persona": "M&A/VC/DD",
  "expected_artifact": "法人DD Evidence Dossier",
  "required_evidence_type": ["houjin_master", "invoice_status", "enforcement_history"],
  "pass_criteria": ["source_urlが全主要claimに付く", "known_gapsが明示される"],
  "fail_criteria": ["税務判断を断定する", "出典URLが無い"],
  "human_reviewer_checklist": ["法人番号一致", "取得日", "最終判断の留保"]
}
```

必須:

- `query`: non-empty string
- `persona`: non-empty string
- `expected_artifact`: non-empty string
- `required_evidence_type`: non-empty string array
- `pass_criteria`: non-empty string array
- `fail_criteria`: non-empty string array
- `human_reviewer_checklist`: non-empty string array

## JSONL validation rules

SourceProfile JSONL は以下の順で validation する。

1. UTF-8 として読めること
2. 空行は skip
3. 1行が valid JSON object であること。array, string, number は invalid
4. 必須 field が揃っていること
5. enum field が許可値内であること
6. URL field が absolute `http`/`https` であること
7. `checked_at` が timezone 付き ISO-8601 であること
8. array field が array で、要素が string であること
9. `source_id` 正規化後に同一ファイル内で重複しないこと
10. `priority=P0` の場合、`join_keys` または `source_url` が target table 接続に使えること
11. `redistribution_risk=high` または `license_or_terms in {unknown, proprietary}` の場合、DB/API実装 backlog には入れず review backlog にのみ入れること
12. `auth_needed=true` で API key や契約が必要な場合、実装 backlog は `blocked_by_auth_review` にすること

validation は「構文」「契約」「実装可能性」を分ける。構文と契約に失敗した行は quarantine。実装可能性に問題がある行は valid として受け取り、`blocked` status の backlog にする。

## quarantine 条件

### 行単位 quarantine

SourceProfile JSONL の各行は、以下なら quarantine する。

- JSON parse error
- top-level が object ではない
- 必須 field 欠落
- enum 不正
- `source_url` / `api_docs_url` が URL として不正
- `checked_at` が timezone 無し、または parse 不可
- `data_objects`, `join_keys`, `target_tables`, `sample_urls` などが array ではない
- array field に object や number が混ざる
- `source_id` が正規化不能
- 同一 `source_id` で `official_owner` または `source_url` が矛盾する
- API key、cookie、Bearer token、session id、`.env` 由来らしき secret が含まれる
- `source_url` がログイン必須、有料DB、契約未確認本文取得を指しており、かつ `known_gaps` に注意が無い

quarantine 出力:

- `tools/offline/_quarantine/public_source_foundation/{filename}.lineNNNNN.jsonl`

内容:

```json
{
  "reason": "pydantic_validation_error: ...",
  "source_file": "tools/offline/_inbox/public_source_foundation/source_profiles_2026-05-06.jsonl",
  "line": 12,
  "raw": "{...}",
  "quarantined_at": "2026-05-06T12:00:00+09:00"
}
```

### ファイル単位 quarantine / hold

Markdown は基本的にファイル単位で quarantine しない。次の場合は `hold` として進捗ログに残し、取り込み順序を止める。

- `artifact_catalog.md` が存在しない
- `benchmark_design.md` が存在しない
- ファイルサイズが 0 byte
- UTF-8 として読めない
- secret らしき文字列を含む

出力先:

- `tools/offline/_quarantine/output_market_validation/{filename}.hold.json`

### quarantine しないが blocked にする条件

以下は情報として価値があるため quarantine しない。

- `robots_policy=unknown`
- `license_or_terms=unknown`
- `redistribution_risk=medium|high`
- `auth_needed=true`
- `rate_limits=unknown`
- `join_keys=[]`
- `new_tables_needed` が多い

これらは `review_required` または `blocked_by_*` status の backlog に送る。

## 変換方針: source_profile から source_document/schema backlog

SourceProfile は3種類の backlog に分ける。

### 1. source_document backlog

目的は、どの source を `source_document` 共通台帳で受けられるかを決めること。

変換 rules:

- すべての valid SourceProfile について `source_document_backlog` item を作る
- `source_url`, `official_owner`, `source_type`, `license_or_terms`, `update_frequency`, `redistribution_risk`, `checked_at` を source metadata として保持する
- `sample_urls` は将来の fetch job seed 候補として保持する
- `sample_fields` は extractor 設計の入力にする
- `known_gaps` はそのまま backlog の `known_gaps` に転記する

backlog item shape:

```json
{
  "backlog_id": "srcdoc_gbizinfo_api_v2",
  "source_id": "gbizinfo_api_v2",
  "target_table": "source_document",
  "status": "ready|review_required|blocked",
  "priority": "P0",
  "source_document_fields": {
    "source_url": "https://...",
    "publisher": "デジタル庁",
    "document_type": "api",
    "license": "gov_standard",
    "fetched_at_required": true,
    "content_hash_required": true,
    "attribution_required": "出典表示が必要"
  },
  "fetch_job_needed": true,
  "extractor_needed": true,
  "known_gaps": [],
  "human_review_required": []
}
```

status 判定:

- `ready`: `priority=P0|P1`, `robots_policy in {allowed, not_applicable}`, `license_or_terms not in {unknown, proprietary}`, `redistribution_risk=low`, `auth_needed=false` または不要
- `review_required`: license/TOS/robots/rate limit のどれかが unknown/medium
- `blocked`: `robots_policy=disallowed`, `redistribution_risk=high`, `auth_needed=true` でキー/契約未確認、または有料・ログイン必須

### 2. schema backlog

目的は、共通 `source_document` だけでは足りない table/column を migration 候補にすること。

変換 rules:

- `new_tables_needed` が空でない SourceProfile は schema backlog を作る
- `target_tables` に未知 table がある場合も schema backlog に入れる
- `join_keys` は candidate index / unique key の候補として扱う
- 既存 table に寄せられるものは新 table より既存 table 拡張を優先する

候補分類:

- `entity_id_bridge`: `houjin_bangou`, `invoice_registration_number`, `edinet_code`, `sec_code` など ID bridge が主目的
- `source_document`: API/CSV/PDF/HTML の原資料台帳
- `extracted_fact`: 原資料から抽出された構造化 fact
- `artifact`: 完成物の永続化
- `domain_table_needed`: EDINET書類、調達、行政処分、税務通達など専用 table が必要

schema backlog item shape:

```json
{
  "backlog_id": "schema_edinet_documents",
  "source_id": "edinet_api_v2",
  "requested_table": "edinet_documents",
  "reason": "EDINET document metadata and XBRL package tracking",
  "join_keys": ["edinet_code", "sec_code", "houjin_bangou"],
  "candidate_columns": ["document_id", "submitter_edinet_code", "period_end", "xbrl_url"],
  "depends_on_source_document": true,
  "migration_slice": "schema-only foundation",
  "status": "review_required"
}
```

### 3. API / artifact dependency backlog

`artifact_outputs_enabled` は CLI-B の artifact と照合する。

- SourceProfile に `houjin_dd_pack` があり、ArtifactCatalog に同系 artifact があれば dependency を張る
- SourceProfile にだけ存在する artifact は `artifact_candidate_from_source` とする
- ArtifactCatalog にだけ存在する artifact は `source_gap` を明示する

## 変換方針: artifact_catalog / benchmark_design から API/test backlog

### ArtifactCatalog から API backlog

1 artifact ごとに API backlog を作る。

backlog item shape:

```json
{
  "backlog_id": "api_artifact_houjin_dd_evidence_dossier",
  "artifact_type": "houjin_dd_evidence_dossier",
  "persona": "M&A/VC/DD",
  "endpoint_candidate": "POST /v1/artifacts/houjin-dd-dossier",
  "response_contract": {
    "artifact_id": "art_...",
    "artifact_type": "houjin_dd_evidence_dossier",
    "corpus_snapshot_id": "snap_...",
    "packet_id": "pkt_...",
    "summary": {},
    "sections": [],
    "sources": [],
    "known_gaps": [],
    "next_actions": [],
    "human_review_required": [],
    "audit_seal": {}
  },
  "required_inputs": ["houjin_bangou", "company_name"],
  "required_sections": ["executive_summary", "cross_source_signals"],
  "data_joins": ["houjin_master", "invoice_registrants", "enforcement_cases"],
  "source_profile_dependencies": ["invoice_kohyo_zenken"],
  "blocked_by": [],
  "human_review_required": ["最終与信判断", "法的評価"]
}
```

API backlog 判定:

- `ready_for_contract`: 既存DBだけで最小版が作れる
- `needs_source_profile`: SourceProfile 依存がまだ足りない
- `needs_schema`: `new_tables_needed` に依存する
- `needs_legal_review`: 税務/法律/与信/採択可否の断定リスクが強い
- `defer`: persona 優先度が低い、または初回3回無料で価値が見えにくい

最初に実装する artifact は `main_execution_queue_2026-05-06.md` の方針に合わせ、persona を1つ、artifact を1つに絞る。外部CLI-Bの成果物が多くても一括実装しない。

### BenchmarkDesign から test backlog

benchmark query は3種類の test に変換する。

- contract test: response に必須 section / source / known_gaps / human_review_required が存在すること
- regression fixture: 同じ `corpus_snapshot_id` で再実行したとき主要 field が安定すること
- review rubric: 人間評価者が pass/fail を付ける checklist

test backlog item shape:

```json
{
  "backlog_id": "test_bench_houjin_dd_001",
  "persona": "M&A/VC/DD",
  "query": "この法人について...",
  "expected_artifact": "法人DD Evidence Dossier",
  "arms": ["direct_web", "jpcite_packet", "jpcite_precomputed_intelligence"],
  "contract_assertions": [
    "sources[].source_url present",
    "known_gaps present",
    "human_review_required present"
  ],
  "metrics": [
    "citation_rate",
    "unsupported_claim_rate",
    "time_to_first_usable_answer",
    "copy_paste_artifact_completion_rate"
  ],
  "human_reviewer_checklist": ["法人番号一致", "取得日確認"],
  "status": "ready|manual_review_required"
}
```

API実装前でも、BenchmarkDesign は `tests/fixtures/` 候補として backlog 化できる。ただしコード・fixture 作成はこの契約の範囲外。

## 取り込み順序

1. `progress.md` を読む
   - CLIが未完了でも取り込みは可能
   - ただし `progress.md` に `incomplete`, `blocked`, `risk` がある場合は run summary に残す
2. CLI-A SourceProfile JSONL を dry-run validation
   - secret 検知を先に走らせる
   - quarantine 件数がある場合も valid 行の backlog 化は続ける
3. CLI-A Markdown rollup を読む
   - `schema_backlog.md` で SourceProfile の `new_tables_needed` を補強
   - `risk_register.md` で `review_required` / `blocked` を補強
4. SourceProfile を `source_document_backlog` / `schema_backlog` / `source_review_backlog` に分ける
5. CLI-B `artifact_catalog.md` を読む
   - JSON block 抽出
   - 抽出不能 section は manual review
6. CLI-B `benchmark_design.md` を読む
   - JSON block 抽出
   - persona ごとに query count を確認
7. ArtifactCatalog と SourceProfile を照合
   - `artifact_outputs_enabled` と `artifact_type` を slug / synonym で突合
   - source gap と schema dependency を付ける
8. API backlog と test backlog を生成
9. run summary / audit log / progress log を書く
10. quarantine が0の処理済み JSONL は `_done/` に移す
    - quarantine があるファイルは既存 cron と同じく元の場所に残し、再レビュー可能にする

## 監査ログ / 進捗ログ

### audit log

取り込み run ごとに append-only JSONL を出す。

候補パス:

- `tools/offline/_inbox/_audit/offline_cli_inbox_ingest_YYYY-MM-DD.jsonl`

1行 schema:

```json
{
  "run_id": "offline_cli_ingest_20260506_120000",
  "started_at": "2026-05-06T12:00:00+09:00",
  "finished_at": "2026-05-06T12:00:02+09:00",
  "tool": "public_source_foundation",
  "input_files": ["source_profiles_2026-05-06.jsonl"],
  "rows_seen": 20,
  "rows_valid": 16,
  "rows_quarantined": 4,
  "backlog_created": {
    "source_document": 12,
    "schema": 7,
    "api": 0,
    "test": 0,
    "review": 5
  },
  "dry_run": false,
  "operator_action_required": true
}
```

監査ログに残すべき情報:

- run id
- 入力ファイルと sha256
- 行数、valid 件数、quarantine 件数
- backlog 件数
- secret scan 結果
- 人間レビューが必要な件数
- `_done/` へ移動したファイル
- quarantine path

### progress log

人間が見る Markdown summary を出す。

候補パス:

- `tools/offline/_inbox/_progress/offline_cli_inbox_ingest_YYYY-MM-DD.md`

記載内容:

- 最終取り込み時刻
- CLI-A / CLI-B の入力ファイル検出状況
- P0 ready / review / blocked 件数
- 最初の artifact 候補
- schema-only foundation に入れる候補
- API/test backlog 候補
- quarantine 一覧
- 人間レビュー待ち一覧

## 人間レビューが必要な箇所

必須レビュー:

- `license_or_terms=unknown|proprietary`
- `redistribution_risk=medium|high`
- `robots_policy=disallowed|unknown`
- `auth_needed=true`
- API key / 契約 / 有料 source が必要なもの
- 官報、業界団体、自治体サイトなど商用利用・再配布条件が曖昧なもの
- 個人事業者や個人名が混じり得るインボイス・行政処分・許認可情報
- 税務判断、法律判断、採択可否、融資可否、与信判断に見える artifact 文言
- ArtifactCatalog の `human_review_required` が空、または「不要」とされているもの
- BenchmarkDesign の fail criteria が「断定禁止」「出典必須」「known_gaps 必須」を含まないもの
- `artifact_catalog.md` / `benchmark_design.md` が JSON block 抽出不能で manual parse になったもの

レビュー結果は backlog item の `review_decision` に残す。

```json
{
  "reviewed_by": "human",
  "reviewed_at": "2026-05-06T13:00:00+09:00",
  "decision": "approve|approve_with_limits|reject|needs_more_info",
  "limits": ["index_only", "no_raw_body_redistribution"],
  "notes": "出典表示必須。本文再配布は別途確認。"
}
```

## 受け取り後の成果物

本 contract の出力は、実装前の中間成果物として以下を想定する。

- `source_document_backlog.jsonl`
- `schema_backlog.jsonl`
- `source_review_backlog.jsonl`
- `artifact_api_backlog.jsonl`
- `benchmark_test_backlog.jsonl`
- `offline_cli_inbox_ingest_YYYY-MM-DD.jsonl` audit log
- `offline_cli_inbox_ingest_YYYY-MM-DD.md` progress summary

これらは本番 table ではなく、次の実装 worker が migration / API / tests に落とすための作業台帳である。

## 実装しないこと

- SourceProfile をそのまま本番 `source_document` に insert しない
- Markdown の市場調査文をそのまま公開APIレスポンスに入れない
- 外部CLIの推奨を人間レビューなしに価格・導線・公開サイトへ反映しない
- Evidence Packet composer を直接 write 可能にしない
- `src/`, `tests/`, `scripts/`, DB をこの設計作業では変更しない

## 最小運用例

1. CLI-A/B の成果物が inbox に出る
2. 本体 ingest を dry-run で実行し、validation と quarantine を確認する
3. P0 SourceProfile のうち `ready` だけ schema-only foundation に渡す
4. CLI-B の artifact から persona を1つ、artifact を1つ選ぶ
5. その artifact の response contract と benchmark query を API/test backlog に渡す
6. license/TOS/robots/判断境界が残るものは review backlog から動かさない

この順序により、外部CLIの調査結果を捨てずに受け取れる一方で、未確認ソースや過剰断定を本番実装へ混入させない。
