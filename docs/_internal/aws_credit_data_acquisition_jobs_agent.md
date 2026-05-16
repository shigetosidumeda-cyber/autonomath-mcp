# AWS credit data acquisition / analysis jobs agent plan

作成日: 2026-05-15  
担当: 1-2週間で走らせる具体的データ取得/解析ジョブ一覧  
対象クレジット: USD 19,493.94  
状態: 計画レビューのみ。実装、AWS CLI/API実行、Terraform/CDK、ジョブ投入、外部API大量実行はこの文書の範囲外。

## 0. 結論

この担当レーンは、AWSクレジットを「短期で残るデータ資産」に変えるためのジョブ台帳を定義する。対象は、公的ソース取得、PDF/HTML解析、source receipt生成、known gaps検出、packet/proof/evalへ渡す中間成果物である。

全体計画 `aws_credit_acceleration_plan_2026-05-15.md` の安全消化目標に合わせ、意図的に使う上限は **USD 18,300-18,700**、バッファ **USD 800-1,200** は残す。このジョブ一覧の標準予算は **USD 14,500**、選択的な伸長時でも **USD 18,000** で停止し、残額は請求遅延・対象外費用・削除ラグに残す。

成功の定義:

1. P0/P1公的source familyから `source_profile`, `source_document`, `source_receipt`, `claim_ref`, `known_gaps` が生成できる。
2. すべてのAI向けclaimが `source_receipts[]` または `known_gaps[]` に接続される。
3. `no-hit` は常に `no_hit_not_absence` として扱われ、不存在・登録なし・リスクなしに変換されない。
4. private CSV由来のraw値、摘要、取引先、個人名、金額明細はpublic source lakeやpublic proofへ出ない。
5. AWS上に長期常駐リソースを残さず、S3/Parquet/JSONL/MDレポートだけを成果物として残す。

## 1. 共通ルール

### 1.1 実行境界

- この文書はジョブ定義であり、AWS実行手順ではない。
- 実行担当が別途、Budgets、Cost Explorer、tag、TTL、emergency stopを確認してからだけ投入する。
- GPU、長期OpenSearch、Marketplace、Reserved Instances、Savings Plans、Support upgrade、外部LLM API大量消費は禁止。
- computeは短命Batch/Fargate/EC2 Spot/CodeBuildに限定し、成果物はS3 prefixへexportする。
- `request_time_llm_call_performed=false` はpacket/proof/eval成果物で維持する。

### 1.2 標準出力契約

各ジョブは最低限、次を出す。

| Artifact | 目的 |
|---|---|
| `run_manifest.json` | run_id、job_id、入力件数、出力件数、失敗件数、cost estimate、停止理由 |
| `object_manifest.parquet` | URL/key/hash/content_type/retention_class/fetched_at |
| `source_profile_delta.jsonl` | 新規/更新source profile候補 |
| `source_document.parquet` | 取得payload/document単位の観測台帳 |
| `source_receipts.jsonl` | claimやno-hitを支える監査edge |
| `claim_refs.jsonl` | AIが再利用する最小fact |
| `known_gaps.jsonl` | 断定禁止境界 |
| `quarantine.jsonl` | terms不明、parse失敗、identity曖昧、private混入疑い |
| `job_report.md` | 人間レビュー用の採否、残課題、次回投入対象 |

### 1.3 `known_gaps` enum

Public / agent-facing の `known_gaps[].code` は、既存案に合わせて次の7個だけを使う。

| code | 主な発生条件 |
|---|---|
| `csv_input_not_evidence_safe` | CSV raw値やprivate overlayが外部向け根拠に使えない |
| `source_receipt_incomplete` | URL、取得日時、hash、license、引用位置などが不足 |
| `pricing_or_cap_unconfirmed` | cost preview、月次cap、plan条件が未確認 |
| `no_hit_not_absence` | 0件、未検出、照会失敗を不存在にできない |
| `professional_review_required` | 税務、法務、監査、融資、与信、補助金判断が必要 |
| `freshness_stale_or_unknown` | 取得時点が古い/不明、現在有効性を断定できない |
| `identity_ambiguity_unresolved` | 同名、旧商号、所在地揺れ、識別子bridge不足 |

## 2. 1-2週間ジョブ一覧

### J01. Official source profile sweep

| 項目 | 内容 |
|---|---|
| 目的 | 公的sourceごとの取得可否、利用条件、freshness、join key、agent露出可否を台帳化する |
| 入力 | 既存source catalog、P0/P1 source候補、公式入口URL、terms/robots/API spec URL |
| 出力 | `source_profile_delta.jsonl`, `source_review_backlog.jsonl`, `license_boundary_report.md` |
| AWSサービス | AWS Batch on Fargate Spot、S3、Glue Data Catalog、Athena |
| 予算 | USD 600-900 |
| 成功条件 | P0 source familyの90%以上に `source_id`, `official_owner`, `source_type`, `join_keys`, `license_boundary`, `freshness_window_days`, `known_gaps_if_missing` が入る |
| jpcite価値 | AIに「どのsourceから何を言えるか」を説明する土台になる |
| `source_receipts`接続 | このジョブ自体は主に `source_profile` を生成し、後続receiptの `source_id`, `license_boundary`, `freshness_bucket` の参照元になる |
| `known_gaps`接続 | terms不明は `source_receipt_incomplete`、freshness不明は `freshness_stale_or_unknown`、API制限はraw detailへ退避 |

### J02. NTA法人番号 master mirror and diff

| 項目 | 内容 |
|---|---|
| 目的 | 法人番号の名称、所在地、変更履歴を取得し、company identityの正規化基盤を作る |
| 入力 | NTA法人番号公表サイト/API/bulk、既存company candidates、旧商号/所在地正規化ルール |
| 出力 | `houjin_master.parquet`, `houjin_change_events.parquet`, `identity_claim_refs.jsonl`, `source_receipts.jsonl` |
| AWSサービス | AWS Batch on EC2 Spot CPU、S3、Glue、Athena |
| 予算 | USD 900-1,300 |
| 成功条件 | 法人番号単位のidentity claimにdirect receiptが付き、重複/変更履歴/同名衝突レポートが出る |
| jpcite価値 | 会社公開baseline、counterparty DD、CSV public joinの精度を上げる |
| `source_receipts`接続 | `receipt_kind=positive_source`, `source_id=nta_houjin`, `claim_kind=company_identity` |
| `known_gaps`接続 | 同名や旧商号で確定できない場合は `identity_ambiguity_unresolved`、snapshot古さは `freshness_stale_or_unknown` |

### J03. NTA invoice registrants mirror and no-hit checks

| 項目 | 内容 |
|---|---|
| 目的 | インボイス登録状態を照会可能なreceiptへ変換し、no-hitを不存在にしない形で記録する |
| 入力 | NTAインボイス公式データ/API、T番号候補、法人番号bridge候補 |
| 出力 | `invoice_registrants.parquet`, `invoice_no_hit_checks.jsonl`, `source_receipts.jsonl`, `known_gaps.jsonl` |
| AWSサービス | AWS Batch on Fargate Spot、S3、Glue、Athena |
| 予算 | USD 700-1,100 |
| 成功条件 | T番号があるclaimはpositive/no-hit receiptに分岐し、no-hitの100%に `no_hit_not_absence` が付く |
| jpcite価値 | 会社baselineと会計CSV private overlayの公開照合価値を上げる |
| `source_receipts`接続 | 登録確認は `positive_source`、未検出は `no_hit_check` として保存 |
| `known_gaps`接続 | no-hitは必ず `no_hit_not_absence`、法人番号/T番号bridge不足は `identity_ambiguity_unresolved` |

### J04. e-Gov law / legal basis snapshot

| 項目 | 内容 |
|---|---|
| 目的 | 制度、申請、規制、根拠条文に使うe-Gov法令sourceをsnapshot化する |
| 入力 | e-Gov法令API/法令ID、既存law references、制度文書から抽出された法令名/条番号候補 |
| 出力 | `law_snapshot.parquet`, `law_article_claim_refs.jsonl`, `source_receipts.jsonl`, `stale_law_report.md` |
| AWSサービス | AWS Batch on Fargate Spot、S3、Glue、Athena |
| 予算 | USD 800-1,200 |
| 成功条件 | P0 packetで参照される法令claimの80%以上にsource receiptと取得時点が付く |
| jpcite価値 | 補助金、許認可、士業向けpacketの根拠整理が強くなる |
| `source_receipts`接続 | `source_id=egov_law`, `receipt_kind=positive_source`, `claim_kind=legal_basis` |
| `known_gaps`接続 | 改正未確認や施行日不明は `freshness_stale_or_unknown`、専門判断は `professional_review_required` |

### J05. J-Grants / public program acquisition

| 項目 | 内容 |
|---|---|
| 目的 | 補助金/支援制度の対象、期間、金額、申請窓口、必要書類候補をreceipt化する |
| 入力 | J-Grants、METI/SME/自治体制度ページ、既存program IDs、公式PDF/HTML URL |
| 出力 | `programs.parquet`, `program_rounds.parquet`, `program_requirements.parquet`, `program_source_receipts.jsonl`, `program_known_gaps.jsonl` |
| AWSサービス | AWS Batch on EC2 Spot CPU、S3、Glue、Athena、必要時のみTextract |
| 予算 | USD 1,600-2,300 |
| 成功条件 | P0制度候補の70%以上でdeadline/target/amount/contact/source URLがreceipt付きで取得される |
| jpcite価値 | `application_strategy` packetの候補提示と確認質問の質を上げる |
| `source_receipts`接続 | 制度条件ごとに `claim_ref` を作り、PDF/HTML/APIのreceiptへ接続 |
| `known_gaps`接続 | 採択/申請可否は `professional_review_required`、期限古さは `freshness_stale_or_unknown`、要件未解析は `source_receipt_incomplete` |

### J06. Ministry / municipality PDF extraction

| 項目 | 内容 |
|---|---|
| 目的 | 省庁・自治体PDFから、締切、対象者、除外条件、必要書類、問い合わせ先を構造化する |
| 入力 | J05/J01で許可されたPDF URL、content hash、source profile、OCR対象優先度 |
| 出力 | `pdf_extracted_facts.parquet`, `pdf_parse_failures.jsonl`, `source_receipts.jsonl`, `review_backlog.jsonl` |
| AWSサービス | AWS Batch on EC2 Spot CPU、S3、TextractまたはCPU PDF parser、Athena |
| 予算 | USD 2,000-3,200 |
| 成功条件 | OCR/parse対象の60%以上で最低1つのreviewable factを抽出し、低信頼factはquarantineされる |
| jpcite価値 | 人間が読むPDFをAI前処理済みのclaim/receiptに変換できる |
| `source_receipts`接続 | `source_document_id`, `content_hash`, `page_or_section_ref`, `support_level=direct|derived|weak` を付与 |
| `known_gaps`接続 | OCR低信頼/ページ位置不明は `source_receipt_incomplete`、古い募集要項は `freshness_stale_or_unknown` |

### J07. gBizINFO / public business signals join

| 項目 | 内容 |
|---|---|
| 目的 | 法人番号を軸に公的ビジネス情報、届出/認定/表彰/調達等の公開signalをjoinする |
| 入力 | gBizINFO等の公式API/bulk、J02法人番号master、source profile |
| 出力 | `business_public_signals.parquet`, `join_candidates.parquet`, `identity_mismatch_ledger.jsonl`, `source_receipts.jsonl` |
| AWSサービス | AWS Batch on EC2 Spot memory、S3、Glue、Athena |
| 予算 | USD 1,000-1,600 |
| 成功条件 | join confidenceが説明可能で、低信頼joinはclaim化されずmismatch ledgerへ落ちる |
| jpcite価値 | company baselineやadvisor reviewで「公開情報ベースの確認材料」を増やす |
| `source_receipts`接続 | join済みsignalごとにsource receipt、join edge、identity confidenceを保存 |
| `known_gaps`接続 | identifier不足や同名衝突は `identity_ambiguity_unresolved`、source不完全は `source_receipt_incomplete` |

### J08. EDINET / securities public metadata snapshot

| 項目 | 内容 |
|---|---|
| 目的 | 上場/開示系の公的metadataを、法人番号/EDINET code/名称に接続できる形で保存する |
| 入力 | EDINET API/metadata、法人番号候補、会社名正規化辞書 |
| 出力 | `edinet_metadata.parquet`, `edinet_houjin_bridge.parquet`, `source_receipts.jsonl`, `identity_gaps.jsonl` |
| AWSサービス | AWS Batch on Fargate Spot、S3、Glue、Athena |
| 予算 | USD 700-1,100 |
| 成功条件 | EDINET codeと法人番号のbridge候補がconfidence付きで出力され、低confidenceは断定されない |
| jpcite価値 | 公開企業baseline、金融/監査前段資料のsource coverageを強化する |
| `source_receipts`接続 | metadata claimに `source_id=edinet`, `claim_kind=public_filing_metadata` を付与 |
| `known_gaps`接続 | code bridge未解決は `identity_ambiguity_unresolved`、最新性不明は `freshness_stale_or_unknown` |

### J09. Procurement / public tender acquisition

| 項目 | 内容 |
|---|---|
| 目的 | 官公庁・自治体調達/入札情報を取得し、会社/業種/地域に紐づくpublic opportunityや履歴候補を作る |
| 入力 | p-portal、JETRO、官公庁/自治体入札ページ、source profile、robots/terms確認済みURL |
| 出力 | `procurement_notices.parquet`, `bid_deadlines.parquet`, `procurement_source_receipts.jsonl`, `freshness_report.md` |
| AWSサービス | AWS Batch on EC2 Spot CPU、S3、Glue、Athena |
| 予算 | USD 1,000-1,700 |
| 成功条件 | 対象sourceの取得時点、公告日、締切、発注者、URL、hashが揃い、期限切れはstale扱いになる |
| jpcite価値 | monthly reviewやapplication strategyに、公開機会の候補を追加できる |
| `source_receipts`接続 | 公告単位でpositive receipt、期限/対象/発注者claimへ接続 |
| `known_gaps`接続 | 締切古さは `freshness_stale_or_unknown`、参加可否は `professional_review_required`、parse不全は `source_receipt_incomplete` |

### J10. Enforcement / sanction / court-public notice sweep

| 項目 | 内容 |
|---|---|
| 目的 | 行政処分、公表情報、裁判所/省庁告知などの公開noticeを収集し、no-hitの危険な言い換えを防ぐ |
| 入力 | 省庁/自治体の処分公表ページ、裁判所/公告系source、法人番号/名称候補、source profile |
| 出力 | `public_notices.parquet`, `notice_entity_candidates.parquet`, `no_hit_checks.jsonl`, `source_receipts.jsonl`, `known_gaps.jsonl` |
| AWSサービス | AWS Batch on EC2 Spot CPU、S3、Glue、Athena |
| 予算 | USD 1,100-1,800 |
| 成功条件 | positive noticeはsource付きで出力され、未検出は必ずno-hit checkとして範囲/条件/snapshotを持つ |
| jpcite価値 | DD前段資料で「確認できた範囲」と「未確認範囲」を分離できる |
| `source_receipts`接続 | positive noticeは `positive_source`、未検出は `no_hit_check` |
| `known_gaps`接続 | 未検出は `no_hit_not_absence`、同名/法人番号不明は `identity_ambiguity_unresolved`、最終判断は `professional_review_required` |

### J11. e-Stat / regional statistics enrichment

| 項目 | 内容 |
|---|---|
| 目的 | 地域、産業、人口、事業所などの公的統計をpacket用の背景claimに変換する |
| 入力 | e-Stat API/統計表、地域コード、産業分類、source profile |
| 出力 | `regional_stats.parquet`, `stat_claim_refs.jsonl`, `source_receipts.jsonl`, `unit_normalization_report.md` |
| AWSサービス | AWS Batch on Fargate Spot、S3、Glue、Athena |
| 予算 | USD 600-1,000 |
| 成功条件 | 統計値に単位、時点、地域コード、表ID、hash、取得時点が付く |
| jpcite価値 | 申請戦略、地域別支援策、public packetの背景根拠を増やす |
| `source_receipts`接続 | 統計表セル/系列単位のclaimにreceiptを付ける |
| `known_gaps`接続 | 最新統計でない場合は `freshness_stale_or_unknown`、単位/表解釈が不明なら `source_receipt_incomplete` |

### J12. Source receipt completeness audit

| 項目 | 内容 |
|---|---|
| 目的 | 全ジョブのreceiptがaudit-grade必須項目を満たすか検査する |
| 入力 | 全 `source_receipts.jsonl`, `source_document.parquet`, `source_profile_delta.jsonl`, `claim_refs.jsonl` |
| 出力 | `receipt_missing_fields.parquet`, `receipt_completeness_summary.md`, `known_gaps_patch_candidates.jsonl` |
| AWSサービス | Athena、Glue、S3、CodeBuildまたはBatch small job |
| 予算 | USD 400-800 |
| 成功条件 | required field欠損率がP0 packet対象で5%未満、欠損claimは `known_gaps` に降格される |
| jpcite価値 | agentが使える根拠と使えない根拠を機械的に分離できる |
| `source_receipts`接続 | 全receiptの `source_url`, `last_verified_at`, `content_hash`, `corpus_snapshot_id`, `license_boundary`, `used_in`, `claim_refs` を検査 |
| `known_gaps`接続 | 欠損は `source_receipt_incomplete`、staleは `freshness_stale_or_unknown` |

### J13. Claim graph dedupe / conflict analysis

| 項目 | 内容 |
|---|---|
| 目的 | 同一subject/fieldの重複、矛盾、snapshot差分、support levelの不正昇格を検出する |
| 入力 | `claim_refs.jsonl`, `claim_source_link`, `source_receipts.jsonl`, `source_profile` |
| 出力 | `claim_graph.parquet`, `claim_conflicts.jsonl`, `dedupe_report.md`, `packet_claim_patch_candidates.jsonl` |
| AWSサービス | AWS Batch on EC2 Spot memory、S3、Glue、Athena |
| 予算 | USD 700-1,200 |
| 成功条件 | duplicate merge候補、value conflict、no-hitによる不正support昇格が検出される |
| jpcite価値 | AI向けpacketの主張が重複/矛盾したまま出るリスクを下げる |
| `source_receipts`接続 | claimとreceiptのN:M edgeを正規化し、support summaryを生成 |
| `known_gaps`接続 | 矛盾で断定不可なら `source_receipt_incomplete`、no-hit混入は `no_hit_not_absence`、同定由来は `identity_ambiguity_unresolved` |

### J14. CSV private overlay safety and public join candidate analysis

| 項目 | 内容 |
|---|---|
| 目的 | freee/MF/弥生の合成fixtureから、private CSVを外部根拠にしない安全なjoin候補だけを作る |
| 入力 | 合成CSV fixtures、provider alias map、法人番号/T番号が明示されたsafe identifiers、J02/J03 public source |
| 出力 | `csv_provider_profile.parquet`, `csv_public_join_candidates.jsonl`, `csv_privacy_leak_scan.md`, `known_gaps.jsonl` |
| AWSサービス | CodeBuild batch、AWS Batch on Fargate Spot、S3、Athena |
| 予算 | USD 600-1,000 |
| 成功条件 | raw摘要/取引先/金額明細がpublic outputへ出ず、join候補はsafe identifier由来だけになる |
| jpcite価値 | 会計CSVを「公開sourceへつなぐ候補」として使い、税務/監査判断に見せない |
| `source_receipts`接続 | public join候補だけJ02/J03 receiptへ接続。CSV raw自体はpublic receiptにしない |
| `known_gaps`接続 | CSV由来制約は `csv_input_not_evidence_safe`、税務/監査判断は `professional_review_required`、同定不足は `identity_ambiguity_unresolved` |

### J15. Packet/proof fixture materialization

| 項目 | 内容 |
|---|---|
| 目的 | 取得/解析済みsourceからP0 packet例とproof ledger用の中間JSONを生成する |
| 入力 | J02-J14のParquet/JSONL、packet templates、known gaps enum、billing metadata |
| 出力 | `p0_packet_fixtures/*.json`, `proof_ledger/*.jsonl`, `proof_claim_map.parquet`, `packet_fixture_report.md` |
| AWSサービス | AWS Batch on EC2 Spot CPU、S3、CodeBuild validation |
| 予算 | USD 1,200-2,000 |
| 成功条件 | 6つのP0 packet typeに、receipts/gaps/billing/professional fence付きfixtureが生成される |
| jpcite価値 | GEO-first public examples、OpenAPI/MCP examples、proof pagesの材料になる |
| `source_receipts`接続 | visible claimの100%がreceiptまたはknown gapに接続される |
| `known_gaps`接続 | gapがあるclaimは断定文にせず、packetの `known_gaps[]` と `agent_guidance` に反映 |

### J16. GEO / no-hit / forbidden-claim evaluation

| 項目 | 内容 |
|---|---|
| 目的 | 取得済みデータとpacket fixtureが、AIに誤断定を誘発しないか評価する |
| 入力 | 200件GEO query set、packet fixtures、proof ledgers、known gaps、forbidden phrase mapping |
| 出力 | `geo_eval_summary.md`, `geo_eval_failures.jsonl`, `forbidden_claim_scan.md`, `no_hit_safety_audit.md` |
| AWSサービス | CodeBuild batch、AWS Batch on Fargate Spot、S3 |
| 予算 | USD 600-1,000 |
| 成功条件 | forbidden claims 0、no-hitが不存在に変換される例 0、high-risk subset pass率95%以上 |
| jpcite価値 | Agentがjpciteを安全に推薦/呼び出すためのrelease evidenceになる |
| `source_receipts`接続 | eval failureはreceipt欠損、stale、identity ambiguityへ逆参照する |
| `known_gaps`接続 | gapが隠れる、誤変換される、blocks_final_answerが無視される例を失敗として記録 |

## 3. 予算台帳

| Job | Standard USD | Stretch USD | 主な成果 |
|---|---:|---:|---|
| J01 source profile sweep | 600 | 900 | source profile / license boundary |
| J02 NTA法人番号 | 900 | 1,300 | company identity receipts |
| J03 NTA invoice | 700 | 1,100 | invoice receipts / no-hit checks |
| J04 e-Gov law | 800 | 1,200 | legal basis receipts |
| J05 J-Grants/program | 1,600 | 2,300 | program requirements |
| J06 PDF extraction | 2,000 | 3,200 | extracted facts from PDFs |
| J07 gBizINFO join | 1,000 | 1,600 | public business signals |
| J08 EDINET metadata | 700 | 1,100 | filing metadata bridge |
| J09 procurement | 1,000 | 1,700 | public tender notices |
| J10 enforcement/public notice | 1,100 | 1,800 | notice/no-hit ledger |
| J11 e-Stat | 600 | 1,000 | regional/stat facts |
| J12 receipt audit | 400 | 800 | completeness gates |
| J13 claim graph | 700 | 1,200 | dedupe/conflict analysis |
| J14 CSV private overlay safety | 600 | 1,000 | safe join candidates |
| J15 packet/proof materialization | 1,200 | 2,000 | P0 packet fixtures |
| J16 GEO/no-hit eval | 600 | 1,000 | release evidence |
| **Subtotal** | **14,500** | **23,200** | Stretchは全部使わない |

実行時の採用案:

| Mode | 対象 | 上限 |
|---|---|---:|
| Conservative 7-10 days | J01-J06, J12-J16 | USD 10,100-16,000 |
| Standard 14 days | J01-J16を標準枠で実行 | USD 14,500 |
| Stretch selective | J05/J06/J10/J15だけ増額 | USD 16,900-18,000 |

Stretch合計は理論値であり、全ジョブを上限まで伸ばさない。実行時は、accepted artifactが増えないジョブを止め、J12/J16のQAとexportへ残額を回す。

## 4. 実行順序

### Day 0-1: Pilot / controls

- AWS側のBudgets、Cost Explorer、tag、TTL、stop runbookが確認済みであることを前提にする。
- J01を小さく走らせ、source profileとlicense boundaryの形を固定する。
- J02/J03を小サンプルで走らせ、positive/no-hit receiptのshapeを確認する。
- J12を小さく走らせ、receipt必須項目の欠損検査を先に動かす。

### Day 2-4: P0 source acquisition

- J02, J03, J04, J05を標準枠で実行する。
- J06はterms/retentionが明確なPDFだけ投入する。
- J12を毎日実行し、欠損が多いsource familyは取得量を増やさずprofile/parseを修正対象に戻す。

### Day 5-8: Join / expansion

- J07, J08, J09, J10, J11を投入する。
- identity bridgeが低信頼なsourceはclaim化せず、J13のconflict/identity analysisへ渡す。
- J06はaccepted fact率が高いsource familyだけ継続する。

### Day 9-11: QA / packet materialization

- J12, J13を全量で実行する。
- J14でprivate CSV safetyとpublic join候補を検査する。
- J15でP0 packet/proof fixture中間成果物を生成する。

### Day 12-14: Eval / drain / export

- J16でGEO/no-hit/forbidden-claim evalを実行する。
- 失敗が価値ある場合だけ該当source/jobを小さく再実行する。
- Compute-heavy queueを止め、S3 manifest、Parquet、JSONL、MD report、cost ledgerだけを残す。

## 5. 成功/停止ゲート

### 5.1 成功ゲート

| Gate | 合格条件 |
|---|---|
| Source profile | P0 source familyの90%以上が取得条件とlicense boundaryを持つ |
| Receipt completeness | P0 packet対象receiptの必須項目欠損率5%未満 |
| No-hit safety | no-hit receiptの100%に `known_gaps.code=no_hit_not_absence` |
| Identity safety | confidence floor未満のjoinがsupported claimへ昇格しない |
| Freshness safety | stale/unknown sourceが現在有効な事実として断定されない |
| Private safety | private CSV raw値、摘要、取引先、金額明細がpublic artifactに0件 |
| Packet readiness | 6つのP0 packet fixtureでvisible claimの100%がreceiptまたはgapへ接続 |
| GEO safety | forbidden claims 0、high-risk pass率95%以上 |

### 5.2 停止ゲート

| Trigger | Action |
|---|---|
| 実測+forecast USD 17,000 | 新規source family投入を止め、既存job完走/QA/exportに限定 |
| 実測+forecast USD 18,300 | OCR/PDF/large joinを止める |
| 実測+forecast USD 18,700 | 新規compute停止。manifest/export/delete確認のみ |
| receipt欠損率が改善しない | 取得量を増やさずJ01/J12へ戻す |
| accepted extracted fact率が低い | J06を停止し、PDF source familyをreview backlogへ移す |
| private leak疑い | J14/J15/J16以外を停止し、public artifact生成を保留 |
| no-hit誤変換 | J15/J16を失敗にし、packet/proof出力を公開不可にする |
| terms/robots不明 | fetchせず `source_review_backlog` へ移す |

## 6. source_receipts / known_gaps 接続ルール

### 6.1 Receipt kind

| receipt_kind | 使う場面 | support_level |
|---|---|---|
| `positive_source` | 公式sourceから直接確認できたfact | `direct` or `derived` |
| `no_hit_check` | 対象source/条件/snapshotで未検出 | `no_hit_not_absence` |
| `stale_check` | 取得時点が古い、現在性に制限がある | `weak` |
| `license_check` | 利用/露出境界の確認 | `weak` |
| `schema_check` | parser/schema driftの確認 | `weak` |

### 6.2 Claimの扱い

- `support_level=direct|derived|weak` のclaimは、最低1つの `source_receipt_id` を持つ。
- `support_level=no_hit_not_absence` は実体factを支えない。未検出チェックのclaimだけに使う。
- `source_receipt_id` がないclaimは、supported claimとして出さず `known_gaps.code=source_receipt_incomplete` へ落とす。
- 税務、法務、監査、融資、与信、採択、申請可否の判断claimは作らない。必要な場合は `professional_review_required` にする。
- private CSV由来claimはtenant/private namespaceに閉じ、public source foundationに混ぜない。

### 6.3 `used_in` と proof接続

各receiptは、後続packet/proofで次の形に接続できる必要がある。

```json
{
  "source_receipt_id": "sr_...",
  "receipt_kind": "positive_source",
  "source_id": "nta_houjin",
  "source_document_id": "sd_...",
  "source_url": "https://...",
  "last_verified_at": "2026-05-15T00:00:00Z",
  "source_checksum": "sha256:...",
  "corpus_snapshot_id": "corpus-2026-05-15",
  "license_boundary": "derived_fact",
  "freshness_bucket": "within_7d",
  "verification_status": "verified",
  "support_level": "direct",
  "claim_refs": ["claim_..."],
  "used_in": ["records[0].facts[0]"],
  "known_gaps": []
}
```

## 7. 最終成果物

1-2週間の終点で残すもの:

- `source_profile_delta.jsonl` とreview済みsource profile候補。
- `source_document.parquet` とobject/hash manifest。
- `source_receipts.jsonl`、`claim_refs.jsonl`、`claim_source_link.parquet`。
- `known_gaps.jsonl` とgap code別summary。
- `quarantine.jsonl` とsource review backlog。
- `receipt_completeness_summary.md`。
- `claim_conflicts.jsonl` とdedupe report。
- `p0_packet_fixtures/*.json` と `proof_ledger/*.jsonl`。
- `geo_eval_summary.md`、`forbidden_claim_scan.md`、`no_hit_safety_audit.md`。
- `cost_manifest.parquet` とjob別accepted artifact単価。

この成果物が揃えば、AWSクレジットは単なる一時的computeではなく、jpciteのGEO-first evidence layer、agent-safe OpenAPI/MCP examples、proof pages、private-safe CSV overlayの具体的な入力資産として残る。
