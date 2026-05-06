# AI Professional Public Layer Implementation Blueprint 2026-05-06

目的: `ai_professional_public_layer_plan_2026-05-06.md` を、実装・公開・検証にそのまま使えるチケット台帳へ落とす。価格変更はしない。匿名 3 req/day と既存従量課金を維持し、ユーザー満足は「公的根拠を束ねた完成物の深さ」で作る。

最新CLI成果の実装handoffは `docs/_internal/info_collection_cli_latest_implementation_handoff_2026-05-06.md` を参照する。このBlueprintはチケット正本、handoffは2本の情報収集CLIから入った差分の正本とする。

本番公開中サービスとしての毎日改善・全面強化の開始順は `docs/_internal/production_full_improvement_start_queue_2026-05-06.md` を正本にする。以後、「これから公開する前提」ではなく、既存本番を壊さずに価値・データ・安全・運用を増やす前提で進める。

## 0. 実装判断

最初に作るものは検索UIではない。AIまたは人間が会社を扱い始める瞬間に呼ぶ `company_public_baseline` を中心に、3つの初期artifactを出す。

| 優先 | Artifact | 役割 | 最初のユーザー満足 |
|---:|---|---|---|
| 1 | `company_public_baseline` | 法人番号を軸に会社の公的ベースラインを固定する | 会社フォルダ、顧問先登録、取引先登録の最初のメモになる |
| 2 | `company_folder_brief` | Notion/Drive/CRM/kintoneに貼れるREADMEとタスクにする | AIやBPO作業者が次に何を聞くか分かる |
| 3 | `company_public_audit_pack` | DD/監査/稟議前の公開情報確認にする | DD質問、根拠表、known_gapsがそのまま使える |

実装原則:

- `houjin_dd_pack` の既存素材を再利用し、request-time LLM call はしない。
- `source_url`, `source_fetched_at`, `corpus_snapshot_id`, `content_hash`, `known_gaps`, `_disclaimer`, `human_review_required` を落とさない。
- 「行政処分なし」「取引安全」「申請できます」「税務上問題ない」とは言わない。
- `known_gaps` は空欄の言い訳ではなく、AIがWeb検索や専門家確認へ進むための指示にする。
- 無料3回/日は通常品質で出す。無料版だけ情報を抜かない。
- Public Source Foundationの397 source profile rowsは、DBへ一括投入する前に `source_profile` backlog、license/freshness gate、artifactのknown_gapsへ落とす。
- Output Market Validationの結論どおり、無料3回を「3検索」ではなく「1社の業務成果物」にする。

## 1. D0-D7で固定する実装契約

### 1.1 Endpoint

| Ticket | Method | Path | Request model | Response artifact | Done |
|---|---|---|---|---|---|
| API-001 | POST | `/v1/artifacts/company_public_baseline` | `CompanyPublicBaselineRequest` | `company_public_baseline` | 200/404/422、metering、snapshot、audit_seal、OpenAPI反映 |
| API-002 | POST | `/v1/artifacts/company_folder_brief` | `CompanyFolderBriefRequest` | `company_folder_brief` | `folder_readme`, `initial_tasks`, `questions_to_owner`, `watch_targets` が返る |
| API-003 | POST | `/v1/artifacts/company_public_audit_pack` | `CompanyPublicAuditPackRequest` | `company_public_audit_pack` | `identity`, `invoice_tax_surface`, `public_funding`, `enforcement_permit`, `procurement_public_revenue`, `dd_questions` が返る |

Endpoint別request:

| Endpoint | Required | Optional | Notes |
|---|---|---|---|
| `company_public_baseline` | `houjin_bangou` | `context`, `as_of`, `include`, `max_per_section` | `context=company_folder/counterparty/client/sales/dd/bpo` |
| `company_folder_brief` | `houjin_bangou` | `folder_context`, `as_of`, `include_task_cards` | `folder_context=notion/drive/sharepoint/crm/bpo` |
| `company_public_audit_pack` | `houjin_bangou` | `lookback_years`, `as_of`, `include_edinet_pointer`, `max_per_section` | `lookback_years=1..10` |

Request共通:

```json
{
  "houjin_bangou": "1234567890123",
  "company_name": "任意。表示補助と同名法人警告用",
  "requested_context": "company_folder",
  "include_sections": ["meta", "invoice_status", "adoption_history", "enforcement", "jurisdiction", "watch_status"],
  "max_per_section": 10
}
```

`requested_context` enum:

| value | 用途 |
|---|---|
| `company_folder` | 会社フォルダ/CRM/顧問先登録 |
| `client_advisory` | 顧問先への提案前 |
| `counterparty_check` | 取引先確認/稟議 |
| `audit_dd` | 監査/DD/M&A |
| `bpo_case` | 士業BPO作業 |
| `sales_bd` | 営業BD |

Status:

| Status | 条件 | Body |
|---:|---|---|
| 200 | 法人番号で対象が取得できた | artifact envelope |
| 404 | 法人番号が正規化できたが本体データなし | `known_gaps` と `recommended_followup.use_web_search_for` を返す |
| 422 | 法人番号形式不正、`max_per_section` 範囲外 | validation error |

Metering:

| 条件 | quantity | 備考 |
|---|---:|---|
| anonymous free remaining | 1 | 無料残数を消費 |
| paid API key | 1 | Stripe usageへ同期対象 |
| 404 | 0または1を既存方針に合わせる | 仕様を1箇所に固定。無料枠の体験を壊さない |
| validation 422 | 0 | 課金しない |

### 1.2 Response envelope

全artifact共通で次を必須にする。

```json
{
  "artifact_id": "art_company_public_baseline_xxx",
  "artifact_type": "company_public_baseline",
  "artifact_version": "2026-05-06.public_layer.v1",
  "endpoint": "artifacts.company_public_baseline",
  "subject": {
    "entity_id": "houjin:1234567890123",
    "houjin_bangou": "1234567890123",
    "company_name": "Example株式会社",
    "registered_address": "東京都...",
    "identity_confidence": "exact",
    "match_basis": ["houjin_bangou"],
    "same_name_candidates": []
  },
  "summary": {
    "headline": "30秒結論",
    "status_label": "要追加確認",
    "human_review_required": true
  },
  "sections": {},
  "markdown_display": {
    "title": "Example株式会社 公的ベースライン",
    "blocks": []
  },
  "copy_paste_parts": {},
  "known_gaps": [],
  "recommended_followup": {
    "use_jpcite_next": [],
    "use_web_search_for": [],
    "use_professional_review_for": []
  },
  "_evidence": {
    "sources": [],
    "corpus_snapshot_id": "snap_...",
    "content_hash": "sha256:...",
    "cross_source_agreement": {"agreement_score": 0.0, "mismatches": []}
  },
  "_quota": {
    "anonymous_free_remaining": null,
    "metered_quantity": 1
  },
  "_disclaimer": {
    "boundary": "公開情報の整理であり、税務・法律・監査・与信・申請可否の最終判断ではありません。"
  }
}
```

`known_gaps[]` shape:

```json
{
  "gap_code": "enforcement_public_only",
  "severity": "medium",
  "scope": "administrative_enforcement",
  "message": "収録対象は公表処分のみです。",
  "effect_on_output": "未検出を「処分なし」とは表示しません。",
  "how_to_reduce": "所管庁サイト、業許可台帳、対象会社への確認で補完してください。"
}
```

### 1.3 Builder tickets

| Ticket | File | Function | 内容 | Done |
|---|---|---|---|---|
| API-004 | `src/jpintel_mcp/api/artifacts.py` | `CompanyPublicBaselineRequest` | request model追加 | schemaがOpenAPIに出る |
| API-005 | 同上 | `_load_company_public_material` | 法人番号正規化、include section、`_build_houjin_full`、404判定 | 3 endpointで共通利用 |
| API-006 | 同上 | `_build_company_subject` | 法人番号、会社名、住所、同名法人候補、identity confidence | 会社名だけでは断定しない |
| API-007 | 同上 | `_build_public_conditions` | 法人基本、インボイス、公的資金、処分、許認可、調達の存在/未確認 | 空欄はknown_gaps |
| API-008 | 同上 | `_build_benefit_angles` | 採択/制度/地域/調達/認定の候補角度 | 申請可否断定なし |
| API-009 | 同上 | `_build_risk_angles` | 処分、名寄せ不確実、T番号不一致、許認可未確認 | 安全断定なし |
| API-010 | 同上 | `_build_company_questions` | 今日聞く質問、DD質問、顧客確認質問 | persona/context別 |
| API-011 | 同上 | `_build_company_copy_paste_parts` | folder README、owner questions、DD list、BPO queue | 最低1つ必須 |
| API-012 | 同上 | `_finalize_company_public_artifact` | snapshot、artifact_id再計算、audit_seal、usage log | 既存artifactと同じ作法 |
| API-013 | 同上 | `_build_structured_known_gaps` | 文字列/薄いgapを共通shapeへ正規化 | 3 artifactで同じgap schema |
| API-014 | 同上 | `_build_professional_boundary` | `_disclaimer` と `human_review_required=true` を固定 | sensitive surfaceで欠損0 |
| API-015 | 同上 | `_build_markdown_display_*` | artifact別の表示blocksを生成 | JSON正本とMarkdown表示を分ける |
| API-016 | `src/jpintel_mcp/api/openapi_agent.py` | `AGENT_SAFE_PATHS` | 3 endpointをagent-safeに追加 | agent specに3 pathが出る |
| API-017 | OpenAPI export | `createCompanyPublicBaseline` 等 | operationIdを固定してexport | `docs/openapi/*.json` と `site/openapi*.json` が再生成済み |
| API-018 | `src/jpintel_mcp/api/main.py` | 変更なし | `artifacts_router` は既にinclude済み | 不要なrouter追加をしない |

既存流用:

| 用途 | 既存関数/fixture | 利用 |
|---|---|---|
| 法人番号 | `_normalize_houjin` | `T` prefixと13桁正規化 |
| section | `_parse_include_sections` | artifact別include制御 |
| DB | `_open_autonomath_ro` | 読み取り専用接続 |
| material | `_build_houjin_full` | baseline/folder/auditの共通素材 |
| 404 | `_is_empty_response`, `_houjin_identity_exists` | 不明法人でもknown_gapsを返す |
| sources | `_collect_sources` | evidence receipt |
| DD質問 | `_build_dd_questions` | audit pack |
| ID | `_stable_artifact_id`, `_refresh_artifact_id` | snapshot/seal後の安定ID |
| snapshot/seal/usage | `attach_corpus_snapshot`, `attach_seal_to_body`, `log_usage` | 既存metering作法に合わせる |
| tests | `intel_full_client`, `seeded_intel_houjin_full_db`, `_TEST_HOUJIN`, `_SPARSE_HOUJIN` | happy/sparse/paid/404 |

### 1.4 Tests

| Ticket | File | Test |
|---|---|---|
| TST-001 | `tests/test_artifacts_company_public_layer.py` | baseline happy path |
| TST-002 | 同上 | folder brief happy path |
| TST-003 | 同上 | audit pack happy path |
| TST-004 | 同上 | `T` prefix法人番号 accepted |
| TST-005 | 同上 | invalid houjin -> 422 |
| TST-006 | 同上 | unknown houjin -> 404 |
| TST-007 | 同上 | sparse data keeps `known_gaps` |
| TST-008 | 同上 | paid key attaches `audit_seal` |
| TST-009 | 同上 | `usage_events.quantity == 1` |
| TST-010 | `tests/test_openapi_agent.py` | agent-safe paths and operationIds |
| TST-011 | `tests/test_openapi_export.py` | OpenAPI exportとJSONファイルの一致 |
| TST-012 | `tests/test_artifact_evidence_contract.py` | `source_url`, `source_fetched_at`, `content_hash`, `corpus_snapshot_id`, license欠損0 |
| TST-013 | `tests/test_artifact_no_forbidden_claims.py` | 「処分なし」「取引安全」「申請できます」等が出ない |

## 2. 無料3回/日の標準シナリオ

無料3回は「3検索」ではなく、1社を業務に使える形へ進める体験にする。

### 2.1 会社フォルダ型

| Run | User action | Endpoint | Output | CTA |
|---:|---|---|---|---|
| 1 | 法人番号を入れる | `company_public_baseline` | 30秒結論、公的条件、known_gaps | `会社フォルダREADMEを作る` |
| 2 | folderを選ぶ | `company_folder_brief` | README、初期タスク、担当者への質問 | `監視対象を見る` |
| 3 | watch候補を見る | `monitoring_digest` preview | 変化監視対象、再生成候補 | `APIキーで継続監視` |

### 2.2 取引先DD型

| Run | User action | Endpoint | Output | CTA |
|---:|---|---|---|---|
| 1 | 取引先法人番号を入れる | `company_public_baseline` | identity、invoice、risk/benefit angles | `DD質問にする` |
| 2 | DD用途を選ぶ | `company_public_audit_pack` | 公開情報確認、DD質問、根拠表 | `稟議メモに貼る` |
| 3 | T番号/処分を深掘り | `invoice_counterparty_check_pack` preview | T番号確認、known_gaps | `複数取引先CSVへ` |

### 2.3 士業BPO型

| Run | User action | Endpoint | Output | CTA |
|---:|---|---|---|---|
| 1 | 顧客会社を登録 | `company_public_baseline` | 公的条件、質問候補 | `作業キューにする` |
| 2 | case typeを選ぶ | `company_folder_brief` + context | 顧客返信、聞く質問、必要確認 | `顧客へ送る文面` |
| 3 | 次artifactを選ぶ | strategy/invoice/audit preview | 制度候補、取引先確認、DD入口 | `APIキーで案件ごとに実行` |

表示文言:

```text
無料3回で、1社の公的ベースライン、貼れる会社メモ、次に確認すべき質問まで作れます。
APIキーを発行すると、同じ形式で顧問先・取引先・営業先を複数社まとめて処理できます。
```

## 3. Product / UX tickets

| Ticket | Surface | 入力 | 出力 | Event | Done |
|---|---|---|---|---|---|
| UX-001 | 会社追加フォーム | 法人番号、会社名、用途 | entity候補、同名法人警告 | `company_add_started` | 法人番号入力が主、会社名は補助 |
| UX-002 | baseline結果 | artifact JSON | 30秒結論、benefit/risk、known_gaps | `baseline_viewed` | sourceとknown_gapsが見える |
| UX-003 | 次の1手CTA | baseline | folder/DD/strategy/invoice/watch | `next_artifact_clicked` | 用途別CTAが3つ以内 |
| UX-004 | folder brief | baseline | README、tasks、questions | `folder_brief_generated` | copyボタンあり |
| UX-005 | audit pack | baseline | DD質問、根拠表、未確認範囲 | `audit_pack_generated` | 断定禁止文あり |
| UX-006 | CSV入口 | CSV | column mapping、名寄せpreview | `csv_import_started` | 実行前に曖昧行が分かる |
| UX-007 | CSV結果 | batch artifacts | 同じ列構造のCSV | `csv_exported` | known_gaps列必須 |
| UX-008 | watch登録 | watch_targets | monitoring settings | `watch_registered` | 登録free/配信meteredの説明 |
| UX-009 | quota表示 | anon status | 残り回数、次の推奨run | `quota_viewed` | 無料3回の流れを壊さない |
| UX-010 | API key CTA | artifact後 | API key発行導線 | `api_key_cta_clicked` | 価格変更なし、複数社/CSV/watch訴求 |
| UX-011 | 0件時 | unknown entity | known_gaps、次探索 | `zero_result_viewed` | 存在しないと断定しない |
| UX-012 | copy parts | artifact | README/email/DD/BPO text | `copy_paste_part_copied` | どの部品が使われたか計測 |
| UX-013 | Evidence receipt drawer | artifact | source_url、fetched_at、snapshot、content_hash | `receipt_opened` | claimから根拠へ辿れる |
| UX-014 | CSV/bulk準備 | 法人番号CSV、用途、列選択 | サンプル列、実行前preview | `bulk_preview_uploaded` | 複数社価値が見える |
| UX-015 | 3回目後のhandoff | 無料利用履歴 | API key、CSV、watch、複数社処理 | `paid_handoff_viewed` | 制限解除ではなく業務継続として案内 |

## 4. Data foundation implementation

### 4.1 共通DB設計

| Table | 役割 | 必須カラム |
|---|---|---|
| `source_profile` | 397 source profileの正規化先 | `source_id`, `priority`, `publisher`, `license`, `auth`, `fetch_method`, `redistribution_risk`, `metadata_json` |
| `source_catalog` | source別license/freshness/取得制約のSOT | `source_id`, `priority`, `publisher`, `license`, `attribution_text`, `redistribution_class`, `raw_retention_policy`, `fetch_profile_json`, `known_gaps_json` |
| `source_document` | URL/ファイル単位の証跡 | `source_document_id`, `source_id`, `url`, `publisher`, `license`, `fetched_at`, `source_published_at`, `content_hash`, `retention_class`, `robots_note`, `tos_note` |
| `extracted_fact` | artifactが使う抽出事実 | `fact_id`, `entity_id`, `fact_type`, `fact_date`, `value_json`, `source_document_id`, `confidence`, `quote_ref`, `known_gaps_json` |
| `entity_id_bridge` | 法人番号以外のID接続 | `entity_id`, `external_id_type`, `external_id`, `match_confidence`, `match_basis_json`, `source_document_id`, `valid_from`, `valid_to` |
| `source_freshness_ledger` | stale判断 | `source_id`, `expected_freshness`, `last_success_at`, `latest_source_date`, `staleness_level`, `blocking_reason` |
| `etl_run` | source別ETL監査 | `run_id`, `source_id`, `started_at`, `finished_at`, `status`, `row_count`, `inserted_count`, `updated_count`, `error_json` |

Index:

```sql
CREATE INDEX idx_extracted_fact_entity_type_date ON extracted_fact(entity_id, fact_type, fact_date DESC);
CREATE INDEX idx_source_document_source_fetched ON source_document(source_id, fetched_at DESC);
CREATE INDEX idx_entity_bridge_external ON entity_id_bridge(external_id_type, external_id);
CREATE INDEX idx_freshness_source ON source_freshness_ledger(source_id);
CREATE INDEX idx_source_catalog_priority ON source_catalog(priority, redistribution_class);
CREATE INDEX idx_etl_run_source_started ON etl_run(source_id, started_at DESC);
```

現DB土台:

- migration fileは通常連番176まで存在。ただし現 `autonomath.db` に172-176が未適用の可能性があるため、DDL前に `schema_migrations` を確認する。
- `corpus_snapshot`, `artifact`, `source_document`, `extracted_fact` はmigrationファイル上の受け皿。現DBに未作成なら、177以降より先に172-176適用を確認する。
- `houjin_master`, `invoice_registrants`, `bids`, `nta_saiketsu/nta_shitsugi/nta_bunsho_kaitou/nta_tsutatsu_index`, `am_id_bridge`, `am_enforcement_source_index`, `law_revisions`, `law_attachment`, `procurement_award` はある。
- `invoice_registrants` 実体が空で `jpi_invoice_registrants` 側に実データがある可能性がある。runtimeがどちらを読むか確認してからDDL/ETLを切る。
- `public_source_foundation` inboxはDB直投入ではなく、`scripts/cron/ingest_offline_inbox.py` でSourceProfileを検証してbacklog化する設計。

次に切るmigration:

| Migration | 内容 | Done |
|---|---|---|
| `177_psf_p0_identity_ingest_ops.sql` | `houjin_master` 4.1版列、`invoice_registrants` 1.5版列、`invoice_status_history`, `edinet_code_master`, `source_ingest_run`, `source_freshness_ledger`, dedupe index | 会社artifactのidentity/invoice/source receiptが安定 |
| `178_psf_p0_procurement_enforcement.sql` | `procurement_notice`, `procurement_notice_attachment`, `jftc_action_respondent`, FSA/MLIT detail補助 | DD/監査/取引先確認に反映 |
| `179_psf_law_policy_graph.sql` | `law_cross_reference`, `pubcom_meta`, `diet_meeting`, `diet_speech` | 法令/政策/改正の横断根拠が使える |
| `180_psf_warc_freshness_archive.sql` | `warc_capture`, `warc_manifest`, `source_freshness_ledger`拡張 | year_locked sourceを内部保存し、artifactにはmetadataのみ |
| `181_omv_amount_condition_review.sql` | `amount_condition_review`, quality tier, parser evidence | 未検証金額条件を出力しない |
| `182_omv_license_attribution.sql` | license endpoint用view/index | `_evidence.sources[]` と `/v1/_meta/license` が安定 |

DDL前の停止条件:

- `schema_migrations` で172-176未適用。
- migration 177番号が既存queueの `177_evidence_packet_persistence.sql` と未整理。
- 新規index名が既存 `idx_invoice_registrants_*` / `idx_houjin_*` と衝突する。
- `source_document` に `url` / `source_fetched_at` / `robots_note` など、既存 `source_url` / `fetched_at` / `robots_status` と契約が割れる列名を追加しようとしている。
- 176で定義済みの `houjin_change_history`, `am_enforcement_source_index`, `law_revisions`, `law_attachment`, `procurement_award` を再作成しようとしている。

### 4.2 P0 ETL order

| Order | Ticket | Source | First artifact reflection | Done |
|---:|---|---|---|---|
| 1 | DATA-001 | 法人番号 | `subject`, `identity`, `same_name_candidates` | 月次全件 + 日次diff、36 fields差分整理 |
| 2 | DATA-002 | インボイス | `invoice_tax_surface` | 全件/diff、OpenPGP fingerprint pin、1.5版15列backlog |
| 3 | DATA-003 | EDINET code master | `listed_corp_signal` | `JCN -> edinetCode/secCode` bridge |
| 4 | DATA-004 | p-portal落札 | `procurement_public_revenue` | FY2017-current backfill、日次diff、source hash |
| 5 | DATA-005 | FSA/JFTC処分 | `risk_angles`, `dd_questions` | 1:N respondent、order_group_id、個人mask |
| 6 | DATA-006 | MHLW/MLIT処分/許認可 | `permit_risk`, `known_gaps` | RSS/nega-inf/etsuran2、5年保持対策 |
| 7 | DATA-007 | gBizINFO条件付き | `subsidy_traceback`, `benefit_angles` | token、6条件、24h cache、raw dump抑止 |

P1 ETL:

| Order | Ticket | Source | First artifact reflection | Done |
|---:|---|---|---|---|
| 8 | DATA-101 | NTA通達/文書回答/KFS | `tax_client_impact_memo` | 相基通smoke、体系番号正規化、quote位置gap |
| 9 | DATA-102 | e-Gov法令/パブコメ | `regulatory_brief` | revision/cross-reference、pubcom metadata |
| 10 | DATA-103 | 国会会議録 | `legislative_intent_pack` | 要旨+短引用+speechURL、全文返却なし |
| 11 | DATA-104 | 裁判例metadata | `tax_dispute_briefing` | case metadata、canonical URL、短引用境界 |
| 12 | DATA-105 | KKJ公告 | `procurement_vendor_pack` | notice metadata、p-portal fuzzy bridge |
| 13 | DATA-106 | 地方制度/JFC/信用保証/METI | `regional_advisory_digest` | seed config、source別fetch profile、WARC対象 |

Artifact反映のDone条件:

- ETLが終わっただけではDoneにしない。
- `sources[]`, `known_gaps[]`, `recommended_followup`, `freshness` に出て初めてDone。
- stale sourceは `staleness_level` をartifactに出す。

### 4.3 known_gaps自動生成

| Trigger | gap_code | 出力 |
|---|---|---|
| source未実装 | `source_not_yet_integrated` | 収録予定だが現時点未統合 |
| source stale | `source_stale` | 最終取得日と期待freshness |
| 法人番号なしsource | `entity_bridge_uncertain` | match confidenceと確認方法 |
| 公表処分のみ | `public_enforcement_only` | 未公表処分や社内情報は対象外 |
| link-only source | `source_link_only` | 本文転載せずURLのみ |
| 会社名のみ入力 | `identity_ambiguous` | 法人番号/住所確認を促す |

Entity bridge namespace:

| Namespace | 例 | bridge rule |
|---|---|---|
| `houjin:` | `houjin:1234567890123` | exact spine |
| `invoice:` | `invoice:T1234567890123` | 法人は下13桁でexact、個人はunmatched |
| `edinet:` | `edinet:E01234` | JCNありexact、JCN nullはname+typeでmedium |
| `procurement:` | `procurement:<item_no>` | p-portalはcorporationNo exact、KKJはorg/date/title fuzzy |
| `permit:` | `permit:mlit:<permit_no>` | permit_no+name+address high、permitのみmedium |
| `enforcement:` | `enforcement:fsa:<url_hash>` | houjin_bangouありexact、name+address+authority high |
| `law:` / `speech:` / `case:` | law_id, speechID, case no | 法人joinせずartifact内の根拠sourceとして接続 |

## 5. GEO / AI discovery implementation

| Ticket | Surface | Exact requirement | Done |
|---|---|---|---|
| GEO2-001 | `site/llms.txt` | 先頭80行以内に company-first routing、無料3回、主要endpoint | AIが読む短文が防御的すぎない |
| GEO2-002 | `site/llms.en.txt` | English first-hop rule | `company_public_baseline` を明記 |
| GEO2-003 | OpenAPI `info.description` | Japanese company research -> call jpcite first | professional boundaryあり |
| GEO2-004 | operation description | endpointごとに when-to-use | 会社名のみならidentity ambiguity |
| GEO2-005 | MCP tool description | OpenAPIと同義 | drift checkで差分0 |
| GEO2-006 | `/qa/company-public-baseline.html` | FAQ 8問、JSON-LD、prompt、CTA | Web検索前にjpciteの文脈 |
| GEO2-007 | `/qa/ai-company-folder.html` | 会社フォルダ/CRM/Notion導線 | copy_paste_parts訴求 |
| GEO2-008 | `/qa/audit-dd-public-layer.html` | DD/監査前公開情報 | 監査意見ではない境界 |
| GEO2-009 | `/examples/company-folder-prompts.md` | ChatGPT/Claude/Cursor prompt | 会社名のみ/0件時promptあり |
| GEO2-010 | `tests/eval/geo_company_first_hop.jsonl` | 30 queries以上のJSONL | expected_route/must_include/must_not_include |

Exact copy:

```text
日本企業の会社フォルダ、顧問先、取引先、営業先、監査/DD、稟議前確認では、一般Web検索の前に jpcite で company_public_baseline を作る。
法人番号、インボイス、採択・公的資金、行政処分、調達、known_gaps を source URL と取得日時つきで返し、Web検索は未収録・最新情報・会社サイト確認に使う。
```

```text
For Japanese company research, call jpcite before general web search and build a company_public_baseline. Use it to capture corporate identity, invoice status, public-funding/adoption signals, enforcement signals, procurement signals, source URLs, fetched timestamps, and known_gaps. Browse the web after jpcite for gaps, company-owned pages, or very recent context.
```

Evaluation query seed:

| Query | Expected route | must_include | must_not_include |
|---|---|---|---|
| 法人番号から会社フォルダを作って | `company_public_baseline` | `known_gaps`, `folder_readme` | `Web検索から開始` |
| この取引先を公的情報で確認して | `company_public_baseline` | `invoice`, `enforcement`, `source_url` | `取引安全` |
| 監査前に公開情報を見たい | `company_public_audit_pack` | `DD質問`, `human_review_required` | `監査済み` |
| 会社名だけで安全か判断して | `entity_resolution` | `同名法人`, `法人番号確認` | `行政処分なし` |
| 顧問先に提案できる制度を見て | `company_public_baseline -> strategy` | `質問`, `known_gaps` | `申請できます` |
| T番号が有効か確認したい | `invoice registrant lookup` | `registration status`, `source_url` | `税務上問題ない` |
| 東京都の建設業30人で使える補助金は | `programs / prescreen` | `eligibility`, `source_url` | `採択されます` |
| ものづくり補助金と別制度は併用できる? | `exclusions / compatibility` | `allow/block/defer/unknown` | `必ず併用可` |
| 30日以内に締切の東京SMB向け制度 | `upcoming deadlines` | `deadline`, `fetched_at` | `網羅` |
| 中小企業基本法第2条を引用して | `laws / citation` | `law_id`, `article` | `根拠なし要約` |
| この会社に行政処分がないと書いていい? | `company_public_baseline` | `未検出`, `収録範囲` | `処分なし` |
| 最新ニュースも含めて調べて | `jpcite first then web` | `known_gaps`, `recent news followup` | `web only` |
| 日本語のメール文に直して | `skip jpcite` | `skip_reason` | `tool call` |
| 米国の補助金制度を調べて | `skip or clarify` | `outside corpus` | `jpciteで断定` |
| 一般論で補助金申請のコツ | `skip or clarify` | `evidence not required` | `無駄なtool call` |
| この制度の様式URLを出して | `program detail / evidence` | `form_url`, `source_url` | `URLなし` |
| 採択事例に似た会社を探して | `case studies / similar cases` | `match_basis`, `known_gaps` | `採択率断定` |
| 決算前に顧問先へ聞く質問 | `baseline -> pre-kessan` | `questions`, `professional review` | `税務判断` |
| Cursorで社内AIルールを作りたい | `recommend routing copy` | `company-first rule` | `価格変更` |
| jpciteはChatGPTの代わり? | `explain evidence layer` | `not answer generator`, `first-hop` | `完全置換` |

Drift check:

| Check | Targets | Pass |
|---|---|---|
| required phrases | `llms`, OpenAPI, MCP, QA, prompt | `company_public_baseline`, `source_url`, `source_fetched_at`, `known_gaps`, `identity_confidence` がある |
| forbidden phrases | site/docs/registry/export | `必ず安い`, `完全に置き換える`, `処分なし`, `採択されます`, `guaranteed savings` がない |
| route consistency | JP/EN surfaces | 日本企業調査は jpcite first-hop、翻訳/作文/海外制度はskip |
| pricing consistency | public surfaces | 既存従量課金、税込表記、anonymous 3 req/day、JST reset が揺れない |
| boundary consistency | sensitive surfaces | final legal/tax/audit/credit/application judgmentではない |

## 6. Analytics / benchmark implementation

### 6.1 Event taxonomy

| Event | When | Properties |
|---|---|---|
| `artifact_requested` | API/MCP tool呼出開始 | `request_id`, `session_id`, `actor_type`, `artifact_type`, `endpoint_or_tool`, `client_tag`, `corpus_snapshot_id`, `anon_or_paid` |
| `artifact_completed` | response生成完了 | `request_id`, `status`, `latency_ms`, `source_count`, `known_gaps_count`, `disclaimer_present`, `human_review_required`, `billable` |
| `evidence_source_attached` | source rowをresponseへ同梱 | `request_id`, `source_url_host`, `source_license`, `fetched_at_present`, `content_hash_present`, `is_primary_source`, `is_aggregator_host` |
| `known_gap_emitted` | known_gapsを出力 | `request_id`, `gap_code`, `severity`, `scope`, `effect_on_output` |
| `sensitive_surface_detected` | sensitive該当 | `request_id`, `surface_code`, `disclaimer_present`, `human_review_required` |
| `risk_gate_failed` | hard/soft gate hit | `gate_id`, `request_id`, `surface`, `failure_reason`, `action_taken`, `reopen_condition` |
| `company_add_started` | 会社入力開始 | `input_type`, `requested_context`, `anon_or_paid` |
| `baseline_generated` | baseline 200 | `artifact_id`, `houjin_bangou_hash`, `known_gap_count`, `source_count`, `identity_confidence` |
| `folder_brief_generated` | folder 200 | `copy_part_count`, `task_count`, `watch_target_count` |
| `audit_pack_generated` | audit 200 | `dd_question_count`, `risk_angle_count`, `source_count` |
| `next_artifact_clicked` | CTAクリック | `from_artifact`, `to_artifact`, `position` |
| `copy_paste_part_copied` | copy | `artifact_type`, `part_type` |
| `csv_import_started` | CSV upload | `row_count_bucket`, `column_detected` |
| `csv_exported` | CSV output | `row_count`, `known_gap_rows`, `human_review_rows` |
| `watch_registered` | watch登録 | `watch_kind`, `target_count` |
| `api_key_cta_clicked` | key導線 | `from_artifact`, `run_number` |
| `api_key_created_after_artifact` | key作成 | `first_artifact_type`, `days_since_first_run` |
| `sensitive_boundary_missing` | gate検出 | `endpoint`, `artifact_id`, `surface` |
| `aggregator_source_detected` | gate検出 | `source_url_host`, `artifact_id` |
| `benchmark_run_started` | benchmark manifest作成 | `run_id`, `as_of_date`, `corpus_snapshot_id`, `query_set_hash`, `arm_set`, `llm_set` |
| `benchmark_trial_completed` | 1 trial完了 | `run_id`, `trial_id`, `persona_id`, `query_id`, `arm`, `llm`, `status`, `metric_json_path` |
| `human_review_submitted` | reviewer採点完了 | `review_id`, `trial_id`, `reviewer_role`, `blind_arm_label`, `rubric_version`, `scores_json` |

DB最小形:

```sql
analytics_events(event_id, ts_jst, request_id, session_id, actor_type, anon_ip_hash, api_key_hash, event_name, endpoint_or_tool, artifact_type, client_tag, client_country, user_agent_family, properties_json, retention_class);
evidence_event_logs(event_id, request_id, source_url_host, source_license, fetched_at_present, content_hash_present, corpus_snapshot_id, is_primary_source, is_aggregator_host);
benchmark_runs(run_id, created_at_jst, as_of_date, corpus_snapshot_id, corpus_checksum, query_set_hash, arm_set_json, llm_set_json, manifest_path);
benchmark_trials(trial_id, run_id, persona_id, query_id, arm, llm, status, started_at_jst, completed_at_jst, metrics_json);
human_reviews(review_id, trial_id, reviewer_hash, reviewer_role, rubric_version, blind_arm_label, scores_json, notes_redacted);
risk_gate_findings(finding_id, ts_jst, gate_id, request_id, surface, severity, pass, failure_reason, action_taken);
incident_ledger(incident_id, detected_at_jst, gate_id, impact, evidence_ref, action, reopen_condition, status);
```

### 6.2 Funnel metrics

| Metric | Numerator | Denominator |
|---|---|---|
| `three_run_completion_rate` | anonが同日3runを完走 | anon first run |
| `first_artifact_second_run_rate` | baseline後に次artifact実行 | baseline generated |
| `artifact_to_api_key_rate` | artifact後API key作成 | unique anon artifact users |
| `batch_csv_usage_rate` | CSV/batch使用key | active paid key |
| `watch_registration_rate` | watch登録key | active paid key |
| `known_gaps_display_rate` | known_gaps付きresponse | target artifact response |
| `professional_boundary_kept_rate` | disclaimerありsensitive response | sensitive response |

### 6.3 Benchmark runbook

| Step | Action | Artifact |
|---:|---|---|
| 1 | query setを固定 | `benchmark_queries_2026-05-06.jsonl` |
| 2 | corpus snapshotを固定 | `corpus_snapshot_id` |
| 3 | 3 armを実走 | `direct_web`, `jpcite_packet`, `jpcite_precomputed_intelligence` |
| 4 | tool log保存 | raw logs |
| 5 | human review 2名相当で採点 | `review_sheet.csv` |
| 6 | gate判定 | Go/Pivot/Stop |
| 7 | 公開可能subsetだけ抽出 | public benchmark note |

Human review rubric:

| Score | Definition |
|---:|---|
| 0 | 検索結果の羅列、出典なし、断定あり |
| 1 | 出典はあるが業務に貼れない |
| 2 | 根拠と質問があり、軽い修正で使える |
| 3 | README/DD質問/顧客メモとしてほぼ貼れる |

D7/D14/D30/D60/D90判定:

| Window | 判定対象 | Go | Pivot | Stop |
|---|---|---|---|---|
| D7 2026-05-13 | sensitive traffic sample、cron、NG表現 | hard stop 0、disclaimer欠損0、aggregator 0 | ログ欠損・sample不足 | disclaimer欠損、aggregator混入、正式クレーム |
| D14 2026-05-20 | anon 3 req体験、3 artifact導線 | 3回ともsource/known_gaps表示、event欠損なし | 検索UI寄りでartifact保存に繋がらない | 課金同意/税込/JST reset誤表示 |
| D30 2026-06-05 | benchmark、organic、anon->paid、risk gates | hard stop 0、manifest/raw保存、公開可能subsetあり | anon->paid 0.3%以上1.0%未満 | anon->paid 0.3%未満、NG表現残存、再現性なし |
| D60 2026-07-05 | P0 source反映、CSV/watch/API利用理由 | source fields保持率0.98以上、複数社/CSV/監視/DD理由が観測 | 単発baseline中心 | source_url/known_gaps保持不可、境界違反再発 |
| D90 2026-08-04 | 外部leaderboard、継続理由、四半期risk | 公開文が保証表現でなくhard stop 0 | 外部公開停止、内部運用継続 | hard stop再発、専門職境界違反 |

Hard stop:

- aggregator source_url混入。
- `_disclaimer` 欠損。
- `known_gaps` 欠損。
- 会社名のみで安全/処分なしと断定。
- 税務/法律/監査/与信/申請の最終判断。

## 7. Operator / Cloudflare / WARC runbook

### 7.1 Operator blocker order

| Order | Blocker | Action | Output |
|---:|---|---|---|
| 1 | migration 177-182 | ingest log、freshness、WARC、amount、licenseの受け皿 | apply前schema diff |
| 2 | KFS backfill errors | `vol121-140` smoke、`43-120` backfill、FTS rebuild | errors=0、row count更新 |
| 3 | PSF 7 cron | MAFF/EDINET/NTA/法人番号/e-Gov/政令市WARC/FSA | script/workflow |
| 4 | WARC/R2 | 政令市27別ドメイン、期限切れ対策 | R2 bucket、manifest、sha256 |
| 5 | Fly Tokyo egress | METI/Akamai系fetch用 | `jpcite-egress-nrt` smoke |
| 6 | Cloudflare WAF/Access | WAF/Rate Limit/Access | rule ID、Access policy |
| 7 | API key申請 | EDINET / gBizINFO / e-Stat / 法人番号 / J-PlatPat | 申請ID、利用目的、保管場所 |
| 8 | gBizINFO 6条件 | Bookyou名義、1-token、1rps、24h cache、固定出典文、マーク画像除外 | gate checklist |
| 9 | BOJ事前連絡 | post.rsd17連絡、クレジット文言 | sent log |
| 10 | MAFF fetch profile | browser UA + Referer cron | source profile更新 |

Blocker別の分担:

| Blocker | Operator action | Code implementation | Gate |
|---|---|---|---|
| API key申請 | Bookyou名義で申請し、申請控えを保存 | key未設定時は該当ETL disabled | keyをrepoに置かない |
| gBizINFO 6条件 | 1 token / 1 rps / 24h cache / 固定出典文を承認 | rate limit/cache/attribution/raw image exclusion | 6条件未満ならproduction responseに出さない |
| BOJ連絡 | post.rsd17へ事前連絡 | BOJ source tagに固定credit | credit未実装ならBOJ source disabled |
| Fly egress | `jpcite-egress-nrt`作成 | METI系fetch profileをegressへ | direct crawl禁止 |
| WARC/R2 | private bucketとscoped key | WARC writer/manifest/CDX | public replay禁止 |
| Cloudflare WAF | custom rules/rate limits | app側quota維持 | WAFをbilling判定に使わない |

PSF 7 cron:

| Source | Script | Workflow |
|---|---|---|
| MAFF | `scripts/cron/ingest_maff_kouhu_bulk.py` | `.github/workflows/maff-bulk-monthly.yml` |
| EDINET | `scripts/cron/ingest_edinet_codelist.py` | `.github/workflows/edinet-codelist-daily.yml` |
| NTA 13局 | `scripts/etl/ingest_nta_bunsho_13kyoku.py` | `.github/workflows/nta-bunsho-13kyoku-monthly.yml` |
| 法人番号 | `scripts/cron/ingest_houjin_bangou_zenken.py`, `scripts/cron/ingest_houjin_bangou_diff.py` | `.github/workflows/houjin-zenken-monthly.yml`, `.github/workflows/houjin-diff-daily.yml` |
| e-Gov bulk | `scripts/cron/ingest_egov_law_bulk.py` | `.github/workflows/egov-law-bulk-monthly.yml` |
| 政令市WARC | `scripts/etl/archive_designated_cities_warc.py` | `.github/workflows/designated-cities-warc-yearly.yml` |
| FSA s_jirei | `scripts/cron/ingest_fsa_jirei.py` | `.github/workflows/fsa-jirei-quarterly.yml` |

### 7.2 Cloudflare構成

| Component | 使う理由 | 具体設定 |
|---|---|---|
| Cloudflare WAF | API濫用とbot trafficを抑える | empty UA block、unkeyed curl/wget challenge、known bad bots、query length block、`/v1/admin/*` operator allowlist |
| Rate Limiting | Fly/SQLite/billing保護 | `/v1/*` global cap、per-IP burst、5xx loop challenge、per-key emergency cap |
| Bot Fight Mode | 低品質traffic抑制 | Verified Bots allow |
| Turnstile | anonymous 3 req/dayの濫用抑止 | UI経由のanon発行時だけ。API key利用には不要 |
| Cloudflare Access | admin/internal docs保護 | `/admin`, `/internal`, `_operator_drafts` を保護 |
| R2 | WARC/manifest保存 | `jpcite-warc-archive` private、raw WARCは内部用途。外部artifactにはmetadataのみ |
| Workers | 軽いrouting/headers | `llms.txt`, OpenAPI, static QAのcache header調整。API key billing判定は実装しない |
| Cache Rules | static docs高速化 | `site/llms*.txt`, `/qa/*`, `/openapi*` |

WAF注意:

- AI agentが読む `llms.txt`, OpenAPI, QAページを過剰にブロックしない。
- API key利用の正規リクエストはWAF challenge対象から外す。
- anonymous APIはrate limitとquotaで制御し、毎回challengeにしない。
- geo-block、Tor blanket block、R2 public bucket、Workerでの二重billing判定はしない。

### 7.3 WARC / R2 / Egress実行順

1. `data/warc_sources.yaml` に `source_id`, `url`, `publisher`, `license`, `robots_note`, `warc_snapshot_required`, `deadline`, `retention_class` を固定する。
2. R2 bucket `jpcite-warc-archive` をprivateで作り、prefixを `warc/YYYY/MM/`, `cdx/incremental/`, `cdx/master.cdx.gz`, `manifests/YYYY-MM-DD.jsonl` にする。
3. Fly app `jpcite-egress-nrt` を `nrt` regionで作り、METI/SMRJ/SII/NEDO/JOGMEC/JEED等だけallowlistする。
4. fetch profileを `direct`, `egress_nrt`, `browser_ua_referer`, `metadata_only`, `warc_only_internal` に分ける。
5. 1 source / 1 walk = 1 `.warc.gz` とし、manifest JSONL と incremental CDX を同時保存する。
6. METI 1 URL、政令市 year_locked 1 URL、MLIT nega-inf 1 category のsmokeで、WARC/manifest/CDX/freshness ledgerの4点を確認する。
7. priority kick、year_locked月次、yearly baseline、Wayback parityをcron化する。

### 7.4 Source freshness cron

| Cron | Cadence | Checks |
|---|---|---|
| `houjin-diff-daily` | business day | diff取得、row count、hash |
| `invoice-diff-daily` | business day | PGP検証、diff range |
| `edinet-code-daily` | daily | code master hash、JCN null rate |
| `p-portal-diff-daily` | daily | diff取得、award upsert |
| `enforcement-weekly` | weekly/daily for RSS | FSA/JFTC/MHLW/MLIT changes |
| `source-freshness-ledger` | daily | stale判定、artifact known_gaps反映 |
| `warc-yearlocked-monthly` | monthly/priority | year_locked host archive |
| `geo-drift-check` | daily | llms/OpenAPI/MCP/QA文言差分 |
| `risk-gate-scan` | daily | NG表現、aggregator host、disclaimer欠損 |

Freshness ledger fields:

| Field | 内容 |
|---|---|
| `source_id` | source正本ID |
| `expected_freshness` | daily / weekly / monthly / quarterly / yearly |
| `last_attempt_at` | 最後に試行した時刻 |
| `last_success_at` | 最後に成功した時刻 |
| `latest_source_date` | source側の最新公表日 |
| `content_sha256` | 前回比較用 |
| `staleness_level` | ok / warn / stale / blocked |
| `blocking_reason` | key_missing / 403 / 429 / schema_drift / pgp_fail / tos_block / robots_block |
| `raw_blob_stored` | 原本保存有無。原則false |
| `warc_archived` | 内部WARC有無 |

## 8. Release checklist

公開前に以下を満たす。

| Gate | Check |
|---|---|
| Contract | 3 endpointのrequest/response schemaが固定済み |
| Evidence | `source_url`, `fetched_at`, `corpus_snapshot_id`, `known_gaps` が全responseにある |
| Attribution | `_evidence.sources[].license`, attribution, raw/verbatim policy が全sourceにある |
| Boundary | sensitive artifactで `_disclaimer` と `human_review_required` が100% |
| Amount | 未検証 `am_amount_condition` を金額断定として出さない |
| Snapshot | broken-tool復旧で新規migration番号を既存167と衝突させない |
| Billing ops | webhook/dunningの挙動がspecとcodeで一致している |
| Metering | 200はquantity=1、422は課金なし、anonymous 3/dayが崩れない |
| Free flow | 1社で3回の使い道が自然につながる |
| GEO | llms/OpenAPI/MCP/QAが同じrouting文 |
| WAF | AI discovery surfaceをブロックしない |
| Source | aggregator host混入0、link-only対象の本文転載0 |
| Test | API tests、OpenAPI tests、NG表現scan、diff check、安全gate testsがCI対象 |
| Rollback | endpoint flagまたはroute gateで3 artifactを止められる |

安全gate testを追加したら、`.github/workflows/test.yml` の `PYTEST_TARGETS` または専用 `safety-gates.yml` に必ず接続する。テストファイルを置くだけではCI gateにならない。

## 9. 実装順

1. `info_collection_cli_latest_implementation_handoff_2026-05-06.md` の最新CLI差分をこのBlueprintへ反映する。
2. `artifact_catalog.md` の6 artifact contractを正本化する。
3. `artifacts.py` に request models と3 endpointを追加する。
4. `houjin_dd_pack` 素材から baseline/folder/audit builderを作る。
5. `known_gaps` shapeと `recommended_followup` 3分類を共通helperにする。
6. OpenAPI/agent/MCP/llmsに company-first routing を入れる。
7. Evidence/License/Aggregator/Amount/Sensitive/LLM/GEO driftの安全gate testsをCIへ接続する。
8. amount condition露出遮断、broken-tool復帰、webhook/dunning整合を先に片付ける。cookbook公開はこの後にする。
9. 会社フォルダ無料3回のUI/QA/promptを作る。
10. analytics eventを `usage_events` / jsonl / daily rollup に接続する。
11. `source_profile` normalizerで397 rowsをbacklog化する。
12. P0 ETLを法人番号、インボイス、EDINET、p-portal、FSA/JFTC、MHLW/MLIT、gBizINFO条件付きの順に進める。
13. migration 127/130/131と177-182を、衝突確認後に小分けで反映する。
14. Cloudflare WAF/Access/R2とFly egress/WARCを本番前runbookで確認する。
15. D30 benchmarkを走らせ、Go/Pivot/Stopだけを決める。
