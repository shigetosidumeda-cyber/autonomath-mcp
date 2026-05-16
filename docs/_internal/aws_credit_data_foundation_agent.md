# AWS credit data foundation agent plan for jpcite

作成日: 2026-05-15  
担当: jpcite向けデータ基盤拡張  
対象クレジット: USD 19,493.94  
実行窓: 1-2週間  
状態: Markdown計画のみ。実装コード、AWS CLI/API実行、Terraform/CDK、ジョブ投入はこの文書の範囲外。

## 0. 結論

この担当レーンでは、AWSクレジットを長期インフラではなく、短期の「公的source lake + source receipt量産 + 鮮度/未検出証跡」の構築に使う。

推奨する消化枠は **USD 10,800-13,200**。全体クレジットの安全消化目標は既存の `aws_credit_acceleration_plan_2026-05-15.md` に合わせ、実意図消化は **USD 18,300-18,700** まで、**USD 800-1,200** は請求遅延・対象外費用・削除ラグのバッファとして残す。この担当レーンは残枠を他レーン、特にpacket/proof生成、GEO/eval/load test、release gateへ渡せる形で止める。

最優先成果物は次の5つ。

1. S3 source lake: raw/normalized/parquet/receipt/reportを分離した再現可能な公的source lake。
2. Glue/Athena catalog: source family、snapshot、license boundary、freshnessで即クエリできるData Catalog。
3. Parquet canonical datasets: `source_profile`、`source_document`、`source_receipt`、`claim_ref`、`no_hit_check`、`freshness_ledger`、`official_source_acquisition`。
4. receipt-grade extraction: 公式sourceからAI向けclaimへつなぐ `source_receipts[]` と `known_gaps[]`。
5. acquisition priority ledger: どの公式データを先に取り、何を保留し、なぜ費用を使うかの台帳。

## 1. 安全ルール

このレーンは、支出を「後で残るデータ資産」に変換する。GPU、常時OpenSearch、大型DB、商用Marketplace、予約購入、Savings Plans、Support upgrade、長期常駐Fargate serviceには使わない。

必須ルール:

- すべてのAWS支出はタグで識別する: `Project=jpcite`, `CreditRun=2026-05`, `Purpose=data-foundation`, `AutoStop=2026-05-29`。
- computeは原則として短命batch。S3とParquet成果物だけを残す。
- public sourceの取得は公式API、公式bulk、公式CSV/ZIP、公式HTML/PDFに限定する。
- robots、利用規約、API key、rate limit、出典表示、第三者権利が未確認のsourceは `source_review_backlog` に止める。
- raw payload retentionが危ういsourceは、raw本文を残さず `content_hash`、headers、URL、取得時刻、正規化fact、短いmetadataだけにする。
- private CSV原文、支払先名、摘要、行単位金額、顧客固有識別子はpublic source lakeへ入れない。
- `no_hit` は不存在証明ではない。必ず `receipt_kind=no_hit_check` と `known_gaps[].code=no_hit_not_absence` を付ける。
- `source_unavailable`、`parse_failed`、`snapshot_stale`、`permission_limited` を `no_hit` に変換しない。
- Athena/Glue/Textract/Fargate/Batch/Cost Explorer/Budgetsの単価とクレジット適用範囲は実行前にAWS公式画面で再確認する。

## 2. 予算配分

この担当レーンの標準案は USD 11,900。支出進捗が速すぎる場合は USD 10,800で止め、他レーンへ渡す。source lakeが順調で抽出対象PDFが多い場合だけ USD 13,200まで伸ばす。

| Bucket | Target USD | Stretch USD | 目的 | 止め条件 |
|---|---:|---:|---|---|
| S3 source lake / manifests | 900 | 1,400 | raw/normalized/parquet/report、checksum、lifecycle、inventory相当の成果物 | raw保存対象を絞っても費用が増え続ける |
| Batch/Fargate/EC2 Spot ETL | 3,200 | 4,300 | API/bulk取得、HTML/PDF fetch、normalization、Parquet build、compaction | P0 source familyがreceipt化可能になった |
| Glue Data Catalog / crawlers / schema QA | 1,100 | 1,700 | Catalog、partition projection、schema drift検査、data quality query | Athenaで主要レポートが返る |
| Athena query / reports | 600 | 1,000 | coverage、freshness、no-hit、license boundary、claim graph検査 | 日次reportが生成できる |
| PDF/OCR extraction | 2,400 | 3,400 | 自治体・省庁PDFから制度条件、期限、対象、除外、必要書類を抽出 | OCR候補のprecisionが低い、またはreview待ちが詰まる |
| Official source acquisition probes | 1,200 | 1,600 | API key待ち以外の公式取得可否、rate/terms/freshness確認 | terms未確認sourceが増えすぎる |
| Parquet compaction / dedupe / quality | 1,000 | 1,300 | 小ファイル整理、snapshot間差分、claim/source重複除去 | query costが安定し、重複率が閾値内 |
| Reserved contingency inside lane | 1,500 | 500 | 請求遅延、リトライ、失敗job、再取得、Cost Explorer API等 | 意図して使わない |

全体クレジットへの接続:

| 全体枠 | このレーンの扱い |
|---|---|
| USD 18,300-18,700 target spend | このレーンは最大USD 13,200まで。残りはpacket/proof/evalへ渡す |
| USD 800-1,200 buffer | このレーンでは触らない |
| USD 17,000 warning | 新規source family投入を止め、既存job完走とexportだけにする |
| USD 18,300 slowdown | OCRとcompute-heavy ETLを止める |
| USD 18,700 stop | 残作業はS3 export、レポート、削除確認だけにする |

## 3. S3 source lake設計

S3は「URL別の雑多なdump」ではなく、監査可能なlakeにする。bucket名は実行者が決めるが、prefix contractは固定する。

```text
source-lake/
  raw/{source_id}/snapshot_date=YYYY-MM-DD/run_id=.../
  normalized/{source_id}/snapshot_date=YYYY-MM-DD/
  parquet/{dataset}/snapshot_id=corpus-YYYY-MM-DD/
  receipts/{snapshot_id}/source_id=.../
  no_hit/{snapshot_id}/source_id=.../
  freshness/{snapshot_id}/
  acquisition/{snapshot_id}/
  reports/{run_id}/
  quarantine/{source_id}/reason=.../
  review_backlog/{snapshot_id}/
  manifests/{run_id}/
```

Raw retention policy:

| Class | 対象 | 保存方針 |
|---|---|---|
| `raw_allowed` | PDL/政府標準利用規約等でraw保持と内部処理が明確なAPI/CSV/ZIP | raw bytes + headers + hashを保存 |
| `hash_only` | 本文再配布や第三者権利が不明なHTML/PDF | rawは短期のみ。長期成果物はhash、URL、metadata、抽出fact |
| `metadata_only` | 官報、民間/契約性があるもの、個人情報リスクが高いsource | raw本文なし。取得範囲と公式URLだけ |
| `blocked` | API key未取得、terms未確認、robots不可、rate不明 | fetchしない。`source_review_backlog` に止める |

必須manifest:

- `run_manifest.json`: run_id、開始/終了、source_id、snapshot_id、job種別、入力件数、出力件数、失敗件数。
- `object_manifest.parquet`: S3 key、size、etag、sha256、content_type、source_url、fetched_at、retention_class。
- `source_document_manifest.parquet`: `source_document_id`、canonical URL、publisher、license boundary、content_hash。
- `quarantine_manifest.parquet`: failure reason、retryable、operator review要否。
- `cost_manifest.parquet`: service、tag、run_id、概算/実測cost、stop threshold。

## 4. Glue/Athena設計

Glue Data Catalogは、アプリDBの正本ではなく、credit run中の監査・検証・export用の分析面とする。最終的に本体DBへ取り込む候補は、review済みParquet/JSONLとして渡す。

Database候補:

| Database | 役割 |
|---|---|
| `jpcite_source_lake` | raw/normalized/source_document/acquisition |
| `jpcite_receipts` | source_receipt、claim_ref、claim_source_link、no_hit_check |
| `jpcite_quality` | freshness、license、schema drift、quarantine、coverage |

Athenaで必ず出すreport:

| Report | 目的 |
|---|---|
| `p0_source_coverage` | P0 source familyごとの取得、正規化、receipt化率 |
| `source_profile_completeness` | `source_profile`必須列の欠損とreview待ち |
| `receipt_missing_fields` | audit-grade receiptに足りない列 |
| `no_hit_safety_audit` | `no_hit_not_absence`欠落、失敗状態との混同を検出 |
| `freshness_breach` | `stale_after_days`超過とblocking reason |
| `license_boundary_exposure` | `metadata_only`や`hash_only`の本文露出事故を検出 |
| `claim_conflict_report` | 同一subject/fieldで値が衝突するclaim |
| `private_leak_scan` | private CSV由来語、摘要、raw行、金額明細がpublic lakeへ混入していないか |

Athena cost control:

- Parquet + Snappy/ZSTD圧縮を基本にする。
- partitionは `snapshot_id`、`source_id`、`source_family`、`receipt_kind`、`freshness_bucket` を中心にする。
- 小ファイルを残しすぎない。query前にcompaction batchを入れる。
- raw JSON/HTML/PDFをAthenaで直接大量scanしない。
- report queryは日次/節目だけ。探索queryを無制限に回さない。

## 5. Parquet canonical datasets

このレーンで残すべきParquet正本候補:

### 5.1 `source_profile`

`source_profile` は出典の契約台帳。URL一覧ではない。

必須列:

| Column | 内容 |
|---|---|
| `source_id` | stable source identifier |
| `profile_version` | profile更新日 |
| `source_family` | corporation, invoice, law, program, procurement, enforcement等 |
| `official_owner` | 公式主体 |
| `source_url` | 公式入口URL |
| `source_type` | api, bulk_csv, zip, pdf, html, ckan, sparql等 |
| `data_objects` | corporation, invoice_registrant, program, bid, law等 |
| `join_keys` | 法人番号、T番号、EDINET code、program id等 |
| `acquisition_method` | official API, bulk download, scheduled fetch等 |
| `auth_required` | none/app_id/api_key/token/id_password/review |
| `robots_policy` | allowed, disallowed, unknown, review |
| `license_boundary` | raw_allowed, derived_fact, hash_only, metadata_only, blocked |
| `commercial_use` | allowed, conditional, prohibited, unknown |
| `redistribution_risk` | low, medium, high |
| `freshness_window_days` | expected freshness |
| `geo_exposure_allowed` | agent/public exposure可否 |
| `known_gaps_if_missing` | missing時に出すgap code |
| `checked_at` | review時刻 |

### 5.2 `source_document`

取得された公式payload/documentの観測台帳。

必須列:

- `source_document_id`
- `source_id`
- `source_url`
- `canonical_source_url`
- `fetched_at`
- `source_published_at`
- `payload_hash`
- `content_hash`
- `source_checksum`
- `corpus_snapshot_id`
- `content_type`
- `retention_class`
- `license_boundary`
- `http_status`
- `parser_status`
- `raw_s3_key` または `raw_retention_reason`

### 5.3 `source_receipt`

AI-facing claimを支える出典状態。citation stringではなく監査edge。

必須列:

- `source_receipt_id`
- `receipt_kind`: `positive_source`, `no_hit_check`, `stale_check`, `license_check`, `schema_check`
- `source_id`
- `source_document_id`
- `source_url`
- `source_fetched_at`
- `last_verified_at`
- `content_hash` または `source_checksum`
- `corpus_snapshot_id`
- `license_boundary`
- `freshness_bucket`
- `verification_status`
- `support_level`: `direct`, `derived`, `weak`, `no_hit_not_absence`
- `claim_refs`
- `used_in`
- `known_gaps`

### 5.4 `claim_ref` / `claim_source_link`

claimはAIが再利用する最小fact。public/private namespaceを混ぜない。

必須列:

- `claim_id`
- `claim_stable_key`
- `namespace`: `pub` または tenant/private namespace
- `claim_kind`
- `subject_kind`
- `subject_id`
- `field_name`
- `canonical_value_hash`
- `value_display_policy`
- `valid_time_scope`
- `corpus_snapshot_id`
- `support_level`
- `visibility`

`claim_source_link` は N:M edge として、`claim_id`、`source_receipt_id`、`support_level`、`link_status`、`created_at` を持つ。

### 5.5 `no_hit_check`

`no_hit`はsource checkの結果であり、positive factではない。

必須列:

- `no_hit_check_id`
- `source_receipt_id`
- `source_id`
- `query_kind`: exact_id, fuzzy_name, join_bridge, multi_source_screen, private_csv_match等
- `query_hash`
- `query_summary_public`
- `checked_scope`
- `snapshot_id`
- `identity_confidence`
- `status`: `no_hit`, `not_in_scope`, `source_unavailable`, `parse_failed`, `snapshot_stale`, `permission_limited`
- `no_hit_means`
- `no_hit_does_not_mean`
- `next_verification_step`
- `known_gaps`

Invariant:

```text
status = no_hit implies receipt_kind = no_hit_check
status = no_hit implies known_gaps contains no_hit_not_absence
status in source_unavailable|parse_failed|snapshot_stale|permission_limited must not be coerced to no_hit
```

### 5.6 `freshness_ledger`

sourceごとの鮮度をpacketやagentが読める形にする。

必須列:

- `source_id`
- `source_family`
- `snapshot_id`
- `expected_freshness`
- `freshness_window_days`
- `stale_after_days`
- `last_success_at`
- `latest_source_date`
- `latest_observed_change_at`
- `freshness_bucket`: within_24h, within_7d, within_30d, stale, unknown
- `blocking_reason`
- `next_refresh_due_at`
- `source_unavailable_count`
- `parser_failure_count`
- `receipt_count`
- `no_hit_count`

## 6. Official source acquisition 優先順位

優先度は「jpciteの有料価値」「join keyの強さ」「receipt化しやすさ」「規約リスク」「鮮度価値」で決める。

### P0: 1-2週間で必ずlake化する

| Priority | Source ID | 公式source | 主な成果物 | 理由 |
|---|---|---|---|---|
| P0-1 | `houjin_bangou` | 国税庁 法人番号 | entity spine, company baseline, join bridge | 全sourceの法人名寄せ土台 |
| P0-2 | `invoice_registrants` | 国税庁 適格請求書 | invoice status, no-hit exact T番号 | 税務/支払先確認で即価値 |
| P0-3 | `egov_laws` | e-Gov法令API/法令データ | law revision, article claim refs | 法令根拠と改正差分 |
| P0-4 | `jgrants_subsidies` | Jグランツ補助金情報API | program, deadline, eligibility, no-hit program search | 補助金artifactの根拠 |
| P0-5 | `gbizinfo` | gBizINFO | certification/subsidy/procurement derived facts | 法人別活動情報の横断。ただし条件付き |
| P0-6 | `edinet_disclosures` | EDINET API | listed company metadata, documents, code bridge | 上場企業/投資先DD |
| P0-7 | `procurement_portal` | 調達ポータル | procurement award/notice receipts | 公的売上/入札機会 |
| P0-8 | `fsa_jftc_mhlw_mlit_enforcement` | 監督官庁/省庁処分公表 | enforcement source receipts | DD/監査で差別化 |
| P0-9 | `estat` | e-Stat API | regional/industry statistics | 補助金・事業説明の客観指標 |
| P0-10 | `address_base_registry` | アドレス・ベース・レジストリ | address normalization, municipality bridge | 地域/自治体制度のjoin |

### P1: P0完了後に費用を使う

| Priority | Source ID | 公式source | 使い方 |
|---|---|---|---|
| P1-1 | `nta_tax_guidance` | 国税庁 通達/質疑/文書回答/KFS | 税務artifactの根拠。引用/個別事案注記を厳格化 |
| P1-2 | `egov_public_comment` | e-Govパブコメ | 制度変更予兆、募集/結果metadata |
| P1-3 | `courts_hanrei` | 裁判所 裁判例 | metadataと短い根拠。未掲載をno-hitにしない |
| P1-4 | `jpo_patent_api` | 特許庁 API/標準データ | IP/技術シグナル。利用登録と上限確認後 |
| P1-5 | `real_estate_library` | 国交省 不動産情報ライブラリ | 不動産/地域データ。個別物件推定に注意 |
| P1-6 | `ksj_national_land` | 国土数値情報 | 地域/地理文脈。dataset別licenseをprofile化 |
| P1-7 | `data_go_jp_catalog` | DATA.GO.JP | dataset discovery。個別resource条件を継承 |
| P1-8 | `local_program_index` | 都道府県/政令市/中核市 | 補助金long tail。WARC/hash-only運用 |

### P2: review待ちまたはmetadata-only

| Source | 方針 |
|---|---|
| 官報 | metadata/deep link優先。raw PDF本文の長期保持や全文再配布を避ける |
| RESAS | 提供状況/API申込可否を確認し、終了/制限があれば代替sourceへ |
| 民間倒産/信用情報 | 契約なし本文ingest禁止。URL/title/date程度のpointerに限定 |
| 商業登記on-demand | bulk化しない。顧客明示操作の都度、約款範囲で扱う |

## 7. 1-2週間の作業順序

### Day 0: 設計固定とsmoke

- source_profile必須列、Parquet schema、S3 prefix、snapshot_id命名を固定する。
- P0 sourceのlicense boundaryを `raw_allowed` / `derived_fact` / `hash_only` / `metadata_only` / `blocked` に分類する。
- USD 100-300相当のsmokeだけで、S3 manifest、Glue table、Athena report、cost tagが通るか確認する。
- API key未取得sourceはfetch queueに入れず、`blocking_reason=api_key_pending` で止める。

### Days 1-3: P0 source lake

- 法人番号、インボイス、e-Gov法令、Jグランツ、調達ポータル、EDINET code/document metadataを優先してraw/normalized/parquet化する。
- enforcement系はsource profileとsource_documentの枠を先に作り、法人番号joinはconfidence付きにする。
- `source_document_manifest` と `freshness_ledger` を初日から出す。
- Athenaで `p0_source_coverage` と `source_profile_completeness` を出す。

### Days 4-7: receipt / no-hit / freshness

- `source_receipt`、`claim_ref`、`claim_source_link` をsource familyごとに生成する。
- exact lookup、fuzzy lookup、join bridge、multi-source screenの `no_hit_check` を分ける。
- no-hit安全監査を通し、`未登録`、`処分歴なし`、`採択なし`、`安全` のような変換を検出する。
- `freshness_bucket` を全receiptへ付け、stale sourceはagent-facing claimを弱める。

### Days 8-10: PDF/OCRと公式source acquisition

- 補助金/自治体/省庁PDFは、期限、対象、金額、除外条件、必要書類、問い合わせ先、根拠条項の抽出に絞る。
- OCR結果はcandidate扱いにし、`source_receipt` と `known_gaps` が揃うまでaudit-gradeにしない。
- official source acquisition templateをsourceごとに埋め、未確認欄があるsourceは実装投入しない。
- license boundaryが弱いものはmetadata/hash-onlyへ降格する。

### Days 11-14: compaction / export / handoff

- Parquet小ファイルを整理し、Athena reportを最終出力する。
- `receipt_missing_fields`、`freshness_breach`、`license_boundary_exposure`、`private_leak_scan` を0またはreview済みにする。
- 本体DB/実装者へ渡す成果物を `review_backlog`、`schema_backlog`、`source_document_backlog` に分ける。
- compute-heavy resourceを止め、S3成果物、manifest、Markdown handoffだけを残す。

## 8. 成果物チェックリスト

最終的にこの担当レーンから渡すもの:

- `source_profile.parquet`
- `source_document.parquet`
- `source_receipt.parquet`
- `claim_ref.parquet`
- `claim_source_link.parquet`
- `no_hit_check.parquet`
- `freshness_ledger.parquet`
- `official_source_acquisition.parquet`
- `object_manifest.parquet`
- `quarantine_manifest.parquet`
- `source_review_backlog.jsonl`
- `schema_backlog.jsonl`
- `source_document_backlog.jsonl`
- `p0_source_coverage.md`
- `receipt_missing_fields.md`
- `no_hit_safety_audit.md`
- `freshness_breach.md`
- `license_boundary_exposure.md`
- `private_leak_scan.md`
- `cost_ledger.md`

合格条件:

| Area | Gate |
|---|---|
| Source lake | P0 sourceのraw/normalized/parquet/report prefixが揃う |
| Profile | P0の `source_profile` 必須列欠損が0、P1/P2はreview理由付き |
| Receipts | P0のAI-facing claimに `source_receipts[]` または `known_gaps[]` がある |
| no-hit | `no_hit_not_absence` 欠落が0 |
| Freshness | stale/unknownがagent-facingで断定表現に使われない |
| License | `metadata_only` / `hash_only` sourceの本文露出が0 |
| Privacy | private CSV raw/row-level再構成可能データのpublic lake混入が0 |
| Cost | planned lane cap内、stop threshold超過前にcompute停止 |

## 9. 既存内部資料との接続

この文書は以下を前提にする。

- `docs/_internal/aws_credit_acceleration_plan_2026-05-15.md`: 全体のAWS credit消化枠と停止線。
- `docs/_internal/geo_source_receipts_data_foundation_spec_2026-05-15.md`: `source_profile`、`source_receipt`、`claim_ref`、`known_gaps` の契約。
- `docs/_internal/official_source_acquisition_plan_deepdive_2026-05-15.md`: P0/P1公式source調査テンプレート。
- `docs/_internal/no_hit_semantics_edge_cases_deepdive_2026-05-15.md`: no-hitの意味と禁止表現。
- `docs/_internal/source_foundation_triage_2026-05-06.md`: 既存source foundation triageとP0/P1 source順序。
- `docs/_internal/public_source_foundation_reingest_plan_2026-05-06.md`: normalizer後の固定投入順。
- `docs/_internal/source_receipt_claim_graph_deepdive_2026-05-15.md`: claim graphとdedupe規則。

## 10. AWS公式確認メモ

実行前に、運用者はAWS公式ページまたはBilling Consoleで最新料金とcredit適用範囲を確認する。

- Amazon S3 pricing: storage、request、retrieval、data transfer、management/insightsが費用要素。
- AWS Glue pricing: ETL/crawler等はDPU-hour等、Data Catalogのmetadata storage/request等が費用要素。
- Amazon Athena pricing: S3上のdata scanned量が主な費用要素。Parquet/partition/圧縮でscan量を減らす。
- Amazon Textract pricing: Detect Document Text、Analyze Document等はAPI/ページ種別で費用が変わる。
- AWS Batch pricing: Batch自体の追加料金ではなく、EC2/Fargate/Lambda等の実行resource費用がかかる。
- AWS Fargate pricing: vCPU、memory、OS/architecture、storage、実行秒数で費用が決まる。Fargate Spotは中断耐性jobだけに使う。
- AWS Cost Explorer pricing: API requestやhourly granularity等が費用になるため、監視queryも無制限に回さない。
- AWS Budgets pricing: action-enabled budget等の料金と無料枠を実行前に確認する。

## 11. Non-goals

- AWS resourceをこの文書から作成しない。
- 実装コード、migration、CLI command、Terraform/CDKをこの文書に含めない。
- 民間データ、非公式ミラー、ブログ、二次配布サイトを一次sourceとして採用しない。
- raw public documentを無制限に保存・再配布しない。
- private CSV rawをpublic source lakeへ混ぜない。
- 法務、税務、監査、採択可否、与信、安全性を自動で断定しない。
