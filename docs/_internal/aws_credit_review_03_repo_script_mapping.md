# AWS credit review 03: repo script mapping

作成日: 2026-05-15  
担当: repo script mapping  
Status: planning/review only. 実装、AWS CLI、AWS resource作成、Batch投入、既存ジョブ実行はこの文書の範囲外。

## 0. 結論

既存の `scripts/cron`, `scripts/ingest`, `tools/offline` は、AWS credit run の材料として十分に使える。ただし「そのままAWS Batchで本番DBへ書く」のは危険で、標準形は次に限定する。

1. `scripts/ingest/*` と一部 `scripts/cron/ingest_*` は、公的source取得・parse・mirror候補生成の既存資産として使う。
2. `tools/offline/run_*_batch.py` は、LLMを呼ばない prompt/schema/shard generator としては使えるが、operator-only前提を破って外部LLMをAWSから叩かない。
3. 本番SQLite/R2/Stripe/Cloudflare/Webhook/SMTPへ副作用を持つcronは、AWS Batch直実行禁止。S3上のartifact生成に変換するwrapperが必要。
4. AWS成果物は `source_profile` / `source_document` / `source_receipt` / `claim_ref` / `known_gaps` / public-safe packet examples / proof pages / GEO reports / synthetic CSV fixtures へ接続する。既存DB tableへ直接大量upsertすることはP0 gateではない。
5. P0 packet/source_receipts/CSV/GEO計画への接続は、「既存ジョブを流用する」ではなく「既存ジョブの取得・parse知識をsource-receipt成果物契約へ出す」で整理する。

## 1. 前提と読んだ範囲

対象:

- `scripts/cron/`
- `scripts/ingest/`
- `tools/offline/`
- AWS credit計画群: `aws_credit_*_agent.md`, `aws_credit_acceleration_plan_2026-05-15.md`, `aws_credit_unified_execution_plan_2026-05-15.md`
- P0接続先: `p0_geo_first_packets_spec_2026-05-15.md`, `geo_source_receipts_data_foundation_spec_2026-05-15.md`, `source_receipt_claim_graph_deepdive_2026-05-15.md`, CSV/GEO deep dive群

既存の重要制約:

- `tools/offline/README.md` は operator-only を明記しており、production import pathからの利用、LLM SDK/API keyのrequest-time利用を禁止している。
- AWS credit計画側も、request-time LLM化、外部LLM API大量消費、raw CSV/private row保存、長期常駐resourceを禁止している。
- P0統合計画では、AWSは本番依存基盤ではなく、release evidenceと実装材料を残す一時computeと定義されている。

## 2. AWS Batch投入可否の分類

| Class | 判定 | 代表例 | 条件 |
|---|---|---|---|
| A | ほぼそのままBatch候補 | deterministic ingest/read-only audit/precompute with `--dry-run`, `--limit`, `--db` | 本番DBではなくshard DB copyまたはlocal temp DBを使い、成果物をS3 JSONL/Parquet/MDへ出す |
| B | wrapper必須 | source crawlers, PDF parsers, gBiz/EDINET/API jobs, offline prompt sharders | `AWS_BATCH_JOB_ARRAY_INDEX`対応、S3 input/output manifest、timeout、rate limit、no direct public publish |
| C | 危険・原則禁止 | Stripe refund/reconcile, SMTP submit, Cloudflare mutation/export, R2 backup/restore, webhook fanout, secrets rotation | AWS credit runの目的外。dry-runでもP0成果物と直接関係が薄い |
| D | operator-only/LLM boundary | `tools/offline` LLM benches, sampling runner, batch translation | AWSから外部LLM APIを大量に叩かない。実施するなら別budget/別承認でAWS credit計画外 |
| E | 新規wrapperが必要 | P0 packet/proof/source_receipt/CSV fixture/GEO artifact generator | 既存スクリプトには該当contractを直接出すentrypointが不足 |

## 3. `scripts/ingest` mapping

### 3.1 公的source取得としてBatch化しやすい

| Existing script family | AWS workload | 接続するAWS job | P0/P1接続 | 注意 |
|---|---|---|---|---|
| `ingest_invoice_registrants.py`, `scripts/cron/ingest_nta_invoice_bulk.py` | NTA invoice bulk/delta mirror | J03 invoice registrants mirror and no-hit checks | `company_public_baseline`, `client_monthly_review`, `source_receipt_ledger` | web UI scrape禁止の設計を維持。sole proprietor等private-adjacent表示はpublic proofへ出さない |
| `ingest_laws.py`, `ingest_law_articles_egov.py`, `ingest_law_revisions_egov.py`, `ingest_law_shiko_rei_kisoku_bulk.py` | e-Gov law/article/revision acquisition | J04 law/source receipt foundation | `evidence_answer`, `application_strategy`, GEO citation quality | law_id単位/条文単位にshard化可能。source receiptは条・項・取得時点・hashが必要 |
| `ingest_nta_corpus.py`, `ingest_tsutatsu_nta.py`, `ingest_shohi_tsutatsu.py` | NTA corpus/tax source extraction | J04/J06 public source extraction | tax/accounting-adjacent packetsのknown gap根拠 | 専門判断を出さず、source claimと`professional_review_required`へ落とす |
| `ingest_pref_programs_47.py`, `ingest_jcci_programs.py`, `ingest_shokokai_programs.py`, `ingest_smrj_programs.py`, `ingest_nedo_programs.py`, `ingest_jst_programs.py`, `ingest_sii_programs.py`, `ingest_amed_jsps_jfc_programs.py` | program/source acquisition | J05 grants/program source sweep | `application_strategy`, `public_opportunity_candidate_sheet`, GEO public-data queries | 既存はDB upsert前提。AWSではsource_document/receipt/claim_ref出力wrapperが必要 |
| `ingest_bids_geps.py`, `ingest_bids_chotatsu.py` | procurement/tender acquisition | J09 procurement acquisition | `client_monthly_review`, opportunity candidate packets | 期限・公告日・発注者・URL/hashをreceipt化。参加可否判断は禁止 |
| `ingest_court_decisions*.py`, `ingest_cases_daily.py` | court/case public notice | J10 public notice sweep | DD前段、no-hit boundary, source ledger | 未検出を「問題なし」にしない。name-only joinはgap |
| `ingest_enforcement_*.py` | enforcement/sanction/public notice extraction | J10 enforcement notice sweep | `company_public_baseline`, `source_receipt_ledger`, high-risk GEO | PDF/HTML混在でparse失敗が多い。positive sourceとno-hit checkを分離 |

### 3.2 Batch直載せの危険点

多くの `scripts/ingest` は `sqlite3.connect(args.db)` で既存DBへ直接upsertする。AWS Batchで同じDBへ並列書き込みすると、SQLite writer lock、partial commit、source freshness drift、重複receipt欠落が起きる。AWSでは次のどちらかに変える。

- Extract mode: 取得・parse結果を `source_document.parquet`, `source_receipts.jsonl`, `claim_refs.jsonl`, `known_gaps.jsonl`, `quarantine.jsonl` としてS3へ出す。
- Staging DB mode: shardごとにlocal SQLiteへ書き、終了後にmanifest付きでexportし、別gateでmergeする。

既存引数に `--dry-run`, `--limit`, `--max-rows`, `--source-file`, `--cache-dir`, `--batch-size`, `--db` があるものはwrapperしやすい。ないものは先にthin wrapperで制御する。

## 4. `scripts/cron` mapping

### 4.1 AWS Batchに回せる既存cron

| Existing cron family | Batch適性 | AWS成果物 | P0接続 |
|---|---|---|---|
| `ingest_gbiz_*_v2.py`, `ingest_gbiz_bulk_jsonl_monthly.py` | B | `business_public_signals.parquet`, identity/join receipts, mismatch ledger | company baseline, CSV public join candidates |
| `ingest_edinet_daily.py` | B | EDINET metadata snapshot, bridge candidates, source receipts | company baseline, audit/accounting public evidence |
| `ingest_kokkai_weekly.py`, `ingest_shingikai_weekly.py`, `ingest_egov_pubcomment_daily.py`, `poll_egov_amendment_daily.py` | A/B | public policy/source delta receipts, freshness ledger | evidence answer, application strategy, GEO freshness |
| `ingest_municipality_subsidy_weekly.py`, `poll_adoption_rss_daily.py`, `detect_budget_to_subsidy_chain.py` | B | program/update/adoption claim refs and known gaps | application strategy, public opportunity packets |
| `export_parquet_corpus.py` | B | Parquet corpus, license manifest, checksum | source lake, Athena QA, release evidence |
| `aggregate_*`, `rollup_freshness_daily.py`, `precompute_data_quality.py` | A | QA reports, freshness summaries, completeness reports | release gate evidence |
| `precompute_*`, `refresh_*`, `backfill_*`, `confidence_update.py` | B | deterministic derived facts, confidence/backlog artifacts | packet composer fixtures, claim graph |
| `ingest_offline_inbox.py` | B | validated JSONL intake from offline batches | ingestion gate for generated structured rows |
| `regen_*`, `generate_*rss`, `sitemap_gen`-like static generators | B | static proof/discovery candidates | proof pages, `llms.txt`, `.well-known`, sitemap |

### 4.2 AWS Batchで危険または対象外のcron

| Existing cron | 理由 | 判定 |
|---|---|---|
| `backup_*`, `restore_*`, `r2_backup.sh`, `r2_upload_jpintel.sh`, `verify_backup_daily.py` | R2/backup/restore副作用。AWS credit成果物ではなく運用保全 | C |
| `stripe_*`, `sla_breach_refund.py`, `predictive_billing_alert.py`, `volume_rebate.py` | 課金・返金・顧客通知に触れる | C |
| `dispatch_webhooks.py`, `webhook_health.py`, `revalidate_webhook_targets.py`, `amendment_alert*`, `same_day_push.py`, `weekly_digest.py`, `send_daily_kpi_digest.py` | 実顧客/外部webhook/email通知の副作用 | C |
| `cf_*`, `cloudflare_*`, `index_now_ping.py` | Cloudflare/API mutationまたはpublic indexing副作用 | C。read-only analyticsのみ別枠 |
| `sync_kintone.py` | partner/customer integration credentials | C |
| `db_boot_hang_alert.py`, `health_drill.py`, `operator_*`, `restore_drill_monthly.py` | production ops runbookでありAWS成果物ではない | C |
| `fill_laws_*`, `fill_programs_en*`, translation系 | 外部翻訳API/ネットワーク費用・品質境界が曖昧 | D/B。`--no-network`またはlocal-only review CSVなら可 |

## 5. `tools/offline` mapping

### 5.1 使えるがwrapper前提のもの

| Existing tool | 既存の役割 | AWSでの使い方 | 接続先 |
|---|---|---|---|
| `_runner_common.py`, `run_narrative_batch.py`, `run_app_documents_batch.py`, `run_enforcement_summary_batch.py`, `run_extract_eligibility_predicates_batch.py`, `run_extract_exclusion_rules_batch.py`, `run_houjin_360_narrative_batch.py`, `run_invoice_buyer_seller_batch.py`, `run_tag_jsic_batch.py` | DBから未処理rowをSELECTし、subagent prompt/schema/inbox pathを出す | AWSでは「prompt sharder」としてのみ利用可。LLM実行はしない。出力をS3 manifest化するwrapperが必要 | P1/P2 packet厚み、application documents、eligibility predicates |
| `generate_program_narratives.py` | narrative batch shard作成 | prompt/job manifest生成まで | packet sections候補。ただしP0 public claimへ直結させない |
| `ingest_narrative_inbox.py`, `scripts/cron/ingest_offline_inbox.py` | JSONL validation and DB ingest | AWSではvalidation-only dry-runまたはstaging DB ingest | generated structured rowsのQA |
| `generate_aliases.py`, `extract_prefecture_municipality.py`, `extract_narrative_entities.py` | deterministic extraction/backfill CSV | read-only DB copyからCSV/JSONL diff生成 | identity/join quality, known gaps |
| `embed_corpus_local.py`, `embed_canonical_entities.py`, `batch_embedding_refresh.py` | local sentence-transformers/sqlite-vec population | GPUなしCPU/EC2でcheckpoint必須。external LLMなしなら可 | search/retrieval benchmark、P1 algorithm fixtures |
| `bench_vec_search.py`, `bench_prefetch_probe.py`, `geo_bench_500.py` | local/API benchmark and reports | static endpoint or local fixture against S3/report output | GEO eval, retrieval QA |
| `operator_review/log_citation_sample.py`, `compute_dirty_fingerprint.py` | review/evidence helpers | CSV/JSON report generationのみ | release evidence |

### 5.2 AWS credit runから外すもの

| Existing tool | 理由 |
|---|---|
| `llm_citation_bench.py`, `aeo_citation_bench.py`, `citation_bench_production.py`, `ai_mention_share_monthly.py`, `sampling_runner.py`, `sampling_review.py --re-grade`, `batch_translate_corpus.py` | 外部LLM API/API key/costが主目的。AWS creditでは外部token代は消えない |
| `submit_*_mail.py`, `blog_post_helper.py --post` | SMTP/外部投稿副作用 |
| `rotate_audit_seal.py` | secret rotation。AWS Batchに載せる意味がない |
| `narrative_rollback.py` | customer credit/rollback補助であり、本番副作用が強い |
| `visual_audit.py` | Playwright screenshot helper。必要ならP0 static validation専用wrapperへ作り替える |

## 6. 新規wrapperが必要な領域

既存repoには、AWS計画が要求する最終artifact contractを直接吐くentrypointが不足している。最低限、次のwrapperを作る前提で整理する。

| Wrapper | 役割 | 既存資産 |
|---|---|---|
| `aws_batch_source_job_wrapper` | shard manifestを読み、既存ingest/parserを呼び、DB writeではなくsource_document/source_receipts/claim_refs/known_gapsをS3へ出す | `scripts/ingest/*`, `scripts/cron/ingest_*` |
| `aws_batch_sqlite_stage_wrapper` | local copied SQLiteへ書く既存jobを隔離し、差分/manifest/checksumをexport | DB upsert前提cron |
| `source_receipt_normalizer` | 既存row/source_url/raw_jsonからP0 receipt fieldsへ正規化 | gBiz/invoice/law/program/enforcement jobs |
| `packet_example_generator` | six P0 packet examplesをcontractに沿って生成 | existing composers/tests/docs, source_receipt outputs |
| `proof_page_static_generator` | proof pages, ledger pages, sitemap shards, JSON-LD safe metadata | static generation scripts, packet examples |
| `csv_fixture_privacy_generator` | freee/MF/Yayoi synthetic/header-only fixtures、alias matrix、leak scan | tests around CSV formats; deep dive docs |
| `geo_eval_artifact_runner` | query set、surface run、forbidden scan、scorecardをS3/`docs/_internal`形式で出力 | `tools/offline/geo_bench_500.py`, GEO docs |

Wrapper共通の必須フィールド:

- `run_id`, `workload`, `shard_id`, `input_manifest_uri`, `output_prefix`
- `source_family`, `source_id`, `data_class=public-only|synthetic-only`
- `dry_run`, `limit`, `timeout_seconds`, `rate_limit`, `retry_count`
- `rows_seen`, `rows_accepted`, `rows_quarantined`, `known_gap_counts`
- `content_hash`, `corpus_snapshot_id`, `license_boundary`
- `cost_estimate`, `started_at`, `finished_at`, `exit_code`

## 7. AWS成果物からP0 packet/source_receipts/CSV/GEOへの接続

| AWS artifact | 生成元候補 | P0接続 | Gate |
|---|---|---|---|
| `source_profile_delta.jsonl` | source profile sweep, existing source URLs in ingest scripts | source catalog, receipt normalizer | license/freshness/join keyが埋まる |
| `source_document.parquet` | law/program/invoice/gBiz/enforcement parsers | claim extraction input, proof pages | URL/hash/fetched_at/content_typeあり |
| `source_receipts.jsonl` | normalizer wrapper | packet `source_receipts[]`, `source_receipt_ledger` | public claimごとにreceiptまたはknown gap |
| `claim_refs.jsonl` | parser + normalizer | `evidence_answer`, `company_public_baseline`, `application_strategy` | claim kind/support level/freshnessが明示される |
| `known_gaps.jsonl` | no-hit, parse failure, identity ambiguity | packet `known_gaps[]`, GEO boundary answers | no-hitをabsence/safeへ変換しない |
| `packet_examples/*.json` | new packet generator | six P0 packet examples, REST/MCP docs | `request_time_llm_call_performed=false` |
| `proof_pages/**` | static proof generator | public proof/discovery surface | private overlay, raw CSV, unreviewed QA混入なし |
| `csv_fixtures/**` | new CSV fixture generator | CSV analyze/preview tests, `client_monthly_review` | synthetic/header-only/aggregate-only |
| `geo_eval_*` reports | GEO runner | release evidence, agent discovery quality | forbidden claim 0 |

## 8. Recommended execution order

1. P0 contract freeze: packet envelope、six packet registry、receipt fields、known gap enum、CSV privacy allowlist、GEO rubricを先に固定する。
2. Dry pilot: 1 source familyを既存scriptでsmall shard取得し、DB writeではなくS3 artifactへ変換できるか確認する。
3. Source receipt lane: invoice/law/program/gBiz/enforcementの順にreceipt/claim/gapを作る。
4. Output lane: six P0 packet examples、proof pages、source receipt ledger examplesを作る。
5. CSV lane: 既存codeはCSV intakeよりCSV export/testが中心なので、新規synthetic fixture/leak scan wrapperを先に作る。
6. GEO lane: 100+100 query set、forbidden scan、surface matrixを生成する。
7. Drain: accepted/rejected manifest、quarantine、cost ledger、cleanup ledgerを残す。

## 9. 最終判定

AWS Batchで回せる既存ジョブは多いが、価値が残るのは「本番DBを増やすrun」ではなく「P0契約に接続できるsource receiptとrelease evidenceを残すrun」である。

直近の実装優先は、新しい大規模crawlerではなく、既存 `scripts/ingest` / `scripts/cron/ingest_*` の取得・parse成果を `source_document`, `source_receipts`, `claim_refs`, `known_gaps` へ変換するthin wrapperである。これがないままAWS Batchへ既存cronを投げると、SQLite lock、外部副作用、operator-only/LLM境界違反、P0 contract driftが同時に起きる。
