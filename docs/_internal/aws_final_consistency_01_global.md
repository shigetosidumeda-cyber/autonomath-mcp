# AWS final consistency 01/10: global alignment review

作成日: 2026-05-15
担当: 最終矛盾チェック 1/10 / 全体整合性
対象: `aws_credit_review_01-20`, `aws_scope_expansion_01-30`, 本体P0計画
AWS前提: profile `bookyou-recovery` / account `993693061769` / region `us-east-1`
状態: 計画レビューのみ。AWS CLI/API、AWSリソース作成、デプロイ、既存コード変更は行っていない。
出力制約: このMarkdownのみ。

## 0. Executive conclusion

全体方針は成立している。

ただし、実行前に統合計画へ必ずマージすべき修正がある。最重要は次の7点。

1. AWS workload regionは `us-east-1` に統一する。既存の `ap-northeast-1` 例は実行前に削除または「別承認の例外」に落とす。
2. 「クレジットをちょうど使い切る」と「現金請求ゼロ」は完全には両立しない。実行上の上限は `USD 19,300` のまま維持し、`USD 19,493.94` は目標ではなく額面として扱う。
3. AWSはCodex/Claudeのrate limitに依存せず自走させる。ただし、Cost/quality/terms/telemetry異常時はAWS内のkill switchで自動停止する。
4. 本番デプロイはAWS全量完了を待たない。RC1は3 packet程度、proof pages、agent-safe OpenAPI/MCP、cost previewで早く出す。
5. productionはAWS S3、Batch、OpenSearch、Glue、Athenaをruntime dependencyにしない。AWSは短期artifact factoryであり、成果物は検証済みbundleとして取り込む。
6. raw CSVはAWS、repo、static asset、logs、proof pagesへ一切入れない。AWSではsynthetic/header-only/redacted fixtureのみ扱う。
7. request-time LLMなしを維持する。Bedrock等を使う場合も公開一次情報のoffline候補抽出だけで、claim supportにはreceipt/spanを必須にする。

この7点を固定すれば、AWS credit run、本体P0、GEO-first販売導線、本番デプロイ、zero-bill cleanupは一つの計画として通せる。

## 1. Inputs checked

ローカルで確認した対象:

- `docs/_internal/consolidated_implementation_backlog_deepdive_2026-05-15.md`
- `docs/_internal/aws_credit_unified_execution_plan_2026-05-15.md`
- `docs/_internal/aws_credit_review_01_cost_stoplines.md` から `aws_credit_review_20_final_synthesis.md`
- `docs/_internal/aws_scope_expansion_01_public_corpus_map.md` から `aws_scope_expansion_30_synthesis.md`
- `.github/workflows/deploy.yml`
- `.github/workflows/deploy-jpcite-api.yml`
- `.github/workflows/pages-deploy-main.yml`
- `.github/workflows/geo_eval.yml`
- `.github/workflows/openapi_drift_v3.yml`
- `.github/workflows/mcp_drift_v3.yml`

注意:

- `aws_scope_expansion_30_synthesis.md` 作成時点では `scope 25-29` が未検出と書かれているが、現在のワークスペースでは `aws_scope_expansion_25` から `29` まで存在する。
- したがって、`scope 30` の「25-29欠落」は古い観測として扱い、最終SOTには採用しない。

## 2. Final source-of-truth decisions

| Area | 決定 | 理由 |
|---|---|---|
| AWS profile | `bookyou-recovery` | ユーザー指定 |
| AWS account | `993693061769` | ユーザー指定 |
| Workload region | `us-east-1` | ユーザー指定default。S3/ECR/Batch/CloudWatch/Glue/Athena/OpenSearchの分散を避ける |
| Billing/control region | `us-east-1` | Cost Explorer/Budgets/Billing control plane |
| Credit face value | `USD 19,493.94` | 額面であり実行目標ではない |
| Intentional absolute safety line | `USD 19,300` | billing lag、credit非対象、cleanup遅延の安全余白 |
| No-new-work | `USD 18,900` | 以後は新規収集ではなくexport/checksum/cleanup中心 |
| Growth strategy | GEO-first | AIエージェントが見つけ、推薦し、MCP/API/cost previewへ送る |
| Product unit | source-backed output packet | 検索/cacheではなく成果物を売る |
| Runtime AWS dependency | 禁止 | AWS credit後にzero-billへ戻すため |
| raw CSV | 保存、ログ、AWS投入、公開、fixture実値化を禁止 | privacy/product trustの中核 |
| request-time LLM | 禁止 | `request_time_llm_call_performed=false` |
| no-hit | `no_hit_not_absence` | 不存在、安全、問題なしを断定しない |

## 3. Global contradictions and resolutions

### G01. Region conflict

問題:

- 統合計画の古い箇所に `ap-northeast-1` を推奨する記述が残る。
- 追加レビュー、ユーザー提示、scope expansion後半は `us-east-1` に寄っている。

採用解:

- 実行標準は `us-east-1` 単一。
- `ap-northeast-1` は「全workloadを同一regionへ明示的に切り替える場合のみ」の別承認例外。
- 実行runbook、IAM region deny、bucket名、ECR、Batch、CloudWatch、Glue、Athena、OpenSearch、Textract/Bedrock前提をすべて `us-east-1` に揃える。

### G02. "Use all credit" vs "zero cash bill"

問題:

- ユーザー意図はUSD 19,500近いcreditをほぼ使い切ること。
- しかしAWS billingには遅延があり、credit非対象/税/サポート/転送/ログ/cleanup遅延もあり得る。

採用解:

- `USD 19,493.94` ちょうどは狙わない。
- `USD 19,300` を意図的な上限とする。
- `USD 19,100-19,300` はmanual stretchのみ。
- 残額約USD 193.94は浪費ではなく、現金請求を避けるための保険として説明する。

### G03. AWS自走 vs 監視不能暴走

問題:

- Codex/Claudeがrate limitでもAWSは止まらない必要がある。
- 一方で、監視不能のまま走るとcredit超過やterms/privacy事故が起きる。

採用解:

- 起動前にjob registry、dependency graph、max spend、max runtime、max items、max retryを固定する。
- AWS内部にcost watcher、artifact yield watcher、terms/privacy watcher、queue disable、job cancel、compute cap shrink、IAM denyを置く。
- Cost Explorer lagを補うため、AWS請求値だけでなくjob-side estimated spend ledgerを併用する。
- telemetry failure時は「停止」ではなく、まずno-new-workに移行し、running jobsを短時間でdrain/cancelする。
- Codex/Claude不在でもJ01-J16標準runまでは自走可能にし、`USD 18,900` 以降のstretchは事前承認された小型jobだけに限定する。

### G04. Fast production vs full corpus

問題:

- AWS全量完了を待つと本番デプロイが遅れる。
- 先に本番を出すとsource coverageが薄い可能性がある。

採用解:

- RC1は完成版ではなく「AIエージェントが推薦できる最小の有料導線」として出す。
- RC1候補は `agent_routing_decision`, `source_receipt_ledger`, `evidence_answer`。
- `company_public_baseline` はstable ID入力だけ。
- `application_strategy` と `client_monthly_review` はRC1ではlimitedまたはdisabled。
- AWSは背後でstandard/stretchを継続し、RC2/RC3へ小分けimportする。

### G05. AWS成果物利用 vs production非依存

問題:

- AWSで作るsource lakeやparquetは大きく、productionが直接読むとzero-bill cleanupできない。

採用解:

- AWS成果物はproduction source of truthではなく、import候補。
- productionへ入れてよいものは、validated compact bundleだけ。
- 禁止: S3 URL埋め込み、OpenSearch runtime依存、Glue/Athena runtime依存、Batch同期呼び出し、AWS log/HAR/raw lake直接利用。
- Final export、checksum、repo/static/db import validation後にAWS側を削除する。

### G06. raw CSV value vs raw CSV non-retention

問題:

- CSV overlayは売上価値が高い。
- しかしraw CSVをAWSやassetへ入れるとprivacy事故になる。

採用解:

- raw CSVはAWS credit runの対象にしない。
- 本体runtimeでもsession-only/analyze-onlyとし、raw rows、free-text memo、counterparty names、payroll、bank account、personal identifiersを保存/ログ/echoしない。
- AWSではsynthetic/header-only/redacted fixturesとformat matrixだけを作る。
- packetへ入れるのはperiod coverage、account-category aggregate、count/amount band、missing-field indicator、suppressed derived factsだけ。

### G07. Bedrock/LLM use vs request-time LLMなし

問題:

- Bedrock batch分類案があり、LLM利用に見える。
- jpciteの根幹はrequest-time LLMなし、hallucinationなし。

採用解:

- Bedrockはoptional stretch。公開一次情報に対するoffline candidate extraction/classificationだけ。
- LLM出力はclaim supportにならない。必ずreceipt、span、source profile、quality gateを通す。
- paid packetは常に `request_time_llm_call_performed=false`。
- LLMで本文を自由生成しない。出力はtemplate/rule/graph/score/diff/constraint solverで組み立てる。

### G08. Playwrightでの取得強化 vs access control回避

問題:

- ユーザーはfetch困難な部分をPlaywright/1600px以下screenshotで突破するイメージを持っている。
- ただしCAPTCHA、login、paywall、rate limit、robots/terms回避は不可。

採用解:

- 「突破」は公開ページを正しくレンダリングして観測する意味に限定する。
- CAPTCHA突破、認証回避、proxy rotation、robots/terms回避は禁止。
- source_profile gateで許可されたsourceだけを対象にする。
- screenshotは各辺1600px以下、初期は `public_publish_allowed=false`。
- claimの根拠は画像そのものではなく、DOM/text/OCR span、content hash、screenshot hash、final URL、timestampに紐づける。

### G09. Screenshot receipt vs public redistribution

問題:

- screenshotは強い証跡になるが、公開再配布条件はsourceごとに違う。

採用解:

- screenshotは内部receipt artifactとして扱う。
- proof page公開は、source_profileで許可された短い引用、metadata、link、hash、取得時点の説明を中心にする。
- 不明な場合は `metadata_only` / `link_only` / `review_required`。

### G10. Broad source lake vs revenue-backed outputs

問題:

- public sourceを広く取りすぎると、creditは消えるが売れるpacketにならない。

採用解:

- 優先度は成果物から逆算する。
- 初期の売上優先は `counterparty_public_check`, `application_strategy_pack`, `permit_precheck_pack`, `administrative_disposition_radar`, `reg_change_impact_brief`, `client_monthly_review`, `tax_labor_event_radar`。
- source lake単体はROIに数えない。accepted artifactは `source_receipts`, `claim_refs`, `known_gaps`, `no_hit_checks`, `algorithm_trace`, packet fixtures, proof pages, GEO eval, deploy artifactsだけ。

### G11. no-hit as value vs absence proof

問題:

- no-hitは成果物価値があるが、エンドユーザーが「問題なし」と誤解しやすい。

採用解:

- no-hitは「この検索条件、このsource、この時点、この正規化条件ではヒット確認できなかった」という証跡に限定する。
- 禁止表現: 問題なし、リスクなし、処分歴なし、登録なしの証明、安全。
- packet/proof/MCP/OpenAPIすべてで `no_hit_not_absence` を明示する。

### G12. Legal/compliance outputs vs professional advice

問題:

- 法令、制度、業法、許認可、税労務は高価値だが、法的/税務/許認可判断に見えるリスクがある。

採用解:

- packetは `candidate`, `checklist`, `questions`, `evidence_binder`, `needs_review` に限定する。
- 「適法」「許可不要」「申請できる」「採択される」「税務処理が正しい」は禁止。
- `human_review_required` と `_disclaimer` を全packetに入れる。

### G13. Vendor risk vs credit scoring

問題:

- 取引先確認は売れるが、信用力スコア/与信判断に見えると危険。

採用解:

- 指標名は `public_evidence_attention_score` とする。
- `evidence_quality_score` と `coverage_gap_score` を併記する。
- 出力は「注意して見る公的情報の優先順位」であり、信用・安全・取引可否の結論ではない。

### G14. Full OpenAPI/MCP size vs agent usability

問題:

- 既存surfaceには155 MCP tools、302 OpenAPI paths相当の大きさがある。
- GEO-firstではAIエージェントが迷う。

採用解:

- RC1はagent-safe subsetを出す。
- P0 MCP facadeとGPT30/agent-safe OpenAPIを正面に置く。
- full catalogはexpert/developer向けリンクに下げる。
- packet catalog、pricing、proof pages、llms/.well-knownは同じSOTから生成し、drift testを必須にする。

### G15. Source terms/robots vs public-primary-source expansion

問題:

- 公的sourceでも自動取得、再配布、検索結果画面、PDF転載の条件がsourceごとに違う。

採用解:

- J01/source_profile gateを大量取得前に実行する。
- terms/robots/licenseが不明なsourceは `skip_ledger` または `metadata_only`。
- source termsが明確に許す場合以外、raw HTML/PDF/screenshot全文を公開しない。

### G16. Zero-bill cleanup vs artifact retention

問題:

- AWSを全部削除すると後から検証できない。
- しかしS3等を残すと請求が残る。

採用解:

- 削除前にfinal export bundle、checksum、manifest、import validation、local/non-AWS保管確認を終える。
- zero-bill標準ではS3も削除する。
- 残せるのはAWS外へ退避済みのartifact、manifest、checksum、ledgerだけ。
- Cleanup後にtagged resource inventory、翌日/3日後/月末のCost Explorer確認を入れる。

### G17. Scope 30 stale input note

問題:

- `aws_scope_expansion_30_synthesis.md` は25-29未検出と記載しているが、現在は25-29が存在する。

採用解:

- 最終SOTでは25-29を有効入力として扱う。
- `scope 30` の優先順位・矛盾候補は採用するが、入力欠落メモは無効化する。

## 4. Correct merged execution order

本体P0計画とAWS credit runは、次の順番で一つにする。

### Phase 0: Contract freeze

先に固定する。

- `jpcite.packet.v1`
- six P0 packet registry
- route/tool/pricing/public URL
- `source_receipts[]`
- `claim_refs[]`
- `known_gaps[]`
- `no_hit_checks[]`
- `billing_metadata`
- `algorithm_trace`
- `artifact_manifest_ref`
- `request_time_llm_call_performed=false`
- CSV privacy boundary
- no-hit copy
- source profile/license boundary

ここが固まる前にJ15/J21のpacket/proof大量生成をしない。

### Phase 1: Production skeleton and import gate

AWS大量run前に本体側の受け皿を作る。

- feature flags
- static proof renderer
- artifact import validator
- checksum validation
- schema validation
- leak scan
- no-hit phrase scan
- forbidden professional claim scan
- OpenAPI/MCP/catalog drift test

### Phase 2: AWS guardrails

最初のAWS作業は計算ではなく制御面。

- account/profile/region確認
- credit balance/expiry/eligible service確認
- IAM role分離
- permission boundary
- required tags
- Budgets/Budget Actions
- cost watcher
- queue caps
- S3 public block
- CloudWatch short retention
- stop drill
- cleanup drill

この時点ではAWSコマンド実行前の計画確定が必要。実行開始後は、guardrailsが通るまでspend-heavy jobを入れない。

### Phase 3: Canary run

`USD 100-300` 以内。

- J01 small source profile
- J02/J03 small identity/invoice receipt
- J04 small e-Gov receipt
- J12 completeness audit
- J15 one packet fixture
- J16 no-hit/forbidden/GEO smoke

合格条件:

- manifest/checksumがある
- receipt/claim/gap schemaがP0 contractと一致
- private/raw CSVが出ない
- no-hit misuse 0
- forbidden professional claim 0
- stop drillが効く

### Phase 4: RC1 implementation lane

AWS canaryを待ちながら本体P0を進める。

推奨PR順:

1. Packet contract/catalog
2. Source receipt/claim/known-gap/no-hit primitives
3. Pricing/cost preview/cap/idempotency
4. CSV analyze/preview privacy
5. P0 packet composers
6. REST facade
7. MCP agent-first facade
8. Public proof/discovery surfaces
9. Drift/privacy/billing/release gates

### Phase 5: AWS standard self-running lane

Canary合格後、Codex/Claudeなしでも自走できる形でJ01-J16を走らせる。

優先:

- J01 source profile sweep
- J02法人番号
- J03インボイス
- J04 e-Gov
- J05補助金/制度
- J06省庁/自治体PDF
- J07 gBizINFO
- J10行政処分/公表情報
- J12 receipt completeness
- J13 claim graph
- J15 packet/proof materialization
- J16 GEO/no-hit/forbidden evaluation

`USD 17,000` 到達後は低yield jobを止め、高yield artifact jobへ寄せる。

### Phase 6: RC1 staging and production

AWS全量完了を待たず、validated compact bundleでstagingへ入れる。

RC1 enabled:

- `agent_routing_decision`
- `source_receipt_ledger`
- `evidence_answer`
- `company_public_baseline` stable ID only

RC1 limited/disabled:

- `application_strategy` は候補/known gapsまで
- `client_monthly_review` はCSV privacy gate完了までdisabled

Production release conditions:

- source receiptあり
- known gapsあり
- no-hit caveatあり
- cost preview/cap/idempotencyあり
- API key required for paid execution
- OpenAPI/MCP/catalog driftなし
- proof pages/llms/.well-known整合
- raw CSVなし
- request-time LLMなし
- production runtime AWS dependencyなし

Deploy target:

- `deploy.yml` / `autonomath-api` は現行production SOT。
- `deploy-jpcite-api.yml` / `jpcite-api` はparallel laneまたは明示cutover target。
- `jpcite-api` へ切り替える場合はRC1安定後に別承認。

### Phase 7: AWS revenue-first expansion

RC1公開後、AWSは広域sourceを続ける。

優先source:

- grants/public programs
- permits/industry registries
- administrative dispositions/enforcement
- procurement/awards
- gazette/notices/public comments
- local governments
- tax/labor/social insurance
- court/admin decisions
- standards/certifications/product safety
- statistics/geospatial/real estate

成果物はRC2/RC3へ小分けimportする。

### Phase 8: Fast spend stretch

`USD 18,300` 以降は新しい広域探索を止め、成果物化へ寄せる。

`USD 18,900` 以降はno-new-work。

`USD 19,100-19,300` のmanual stretch優先順:

1. J24 final packaging/checksum/export
2. packet/proof/GEO artifacts
3. high-value Playwright capture for accepted sources
4. OCR/Textract for accepted high-value public PDFs/screenshots
5. Athena/Glue QA rerun and compaction
6. Bedrock batch public-only classification if review/receipt gates are ready
7. temporary OpenSearch benchmark only if it answers an immediate product decision

禁止:

- CPU burn
- 無目的load test
- 長期OpenSearch
- NAT-heavy構成
- private/raw CSV処理
- CAPTCHA/terms回避
- 未検証raw lake拡大
- production AWS dependency

### Phase 9: Final export and assetization

AWSで作ったものをproduction非依存assetへ変換する。

- immutable source snapshot references or allowed copies
- source profiles
- source receipts
- claim refs
- known gaps
- no-hit ledgers
- deterministic rules
- algorithm traces
- packet fixtures
- proof page inputs
- GEO eval cases
- pricing/cost preview examples
- release evidence manifests

Large raw lakeはproductionへ入れない。

### Phase 10: Zero-bill teardown

export/checksum/import validation後に削除する。

- S3 buckets/objects
- ECR images/repos
- Batch queues/compute environments/job definitions
- ECS/Fargate/EC2
- EBS volumes/snapshots
- OpenSearch
- Glue databases/crawlers/jobs
- Athena workgroups/result buckets
- CloudWatch logs/alarms/dashboards
- Lambda
- Step Functions
- EventBridge schedules
- NAT gateways
- Load balancers
- Elastic IP
- ENI
- run用Budget Actions/IAM emergency policies if no longer needed

最終状態:

- AWS account contains no jpcite tagged run resources.
- production can serve without AWS.
- Cost Explorerで新規日次費用が増えない。

### Phase 11: Post-teardown checks

削除当日だけでは不十分。

- 翌日
- 3日後
- 月末またはcredit expiry後

でCost Explorer、resource inventory、Budgets、CloudWatch/S3/ECR/OpenSearch/EC2/EBS/NAT/EIPを再確認する。

## 5. One-week fast run target

ユーザー意図に合わせるなら、実行開始後は1週間で大半を消化する設計にする。

| Day | AWS lane | Product/deploy lane | Spend intent |
|---:|---|---|---|
| 0 | Guardrails、stop drill、canary | contract/import gate準備 | USD 100-300 |
| 1 | J01-J04/J12/J15/J16小規模 | P0 PR1-PR3 | low but validated |
| 2 | J01-J16 standard開始 | P0 PR4-PR8、RC1 staging準備 | accelerate |
| 3 | standard継続、J05/J06/J07/J10強化 | RC1 staging/production判断 | deploy first value |
| 4 | J25-J40 revenue/broad corpus | RC2 import候補 | heavy useful burn |
| 5 | Playwright/OCR/Textract selected lanes | proof/GEO/pages拡張 | heavy useful burn |
| 6 | accepted artifacts中心にstretch | RC2/RC3小分けimport | approach no-new-work |
| 7 | J24/export/checksum、manual stretch、cleanup開始 | production非依存確認 | stop before USD 19,300 |

1週間で使い切れない場合は、Day 8-14へ延長する。ただし、延長理由は「accepted artifactが増えるから」であり、単なる消費ではない。

## 6. Information scope sufficiency

現時点の情報範囲は、JP public-primary-source serviceとしてかなり広い。

必須backbone:

- 法人番号
- インボイス
- e-Gov法令/XML
- e-Stat
- source_profile/license/robots/terms
- address/municipality normalization

高売上source:

- J-Grants、補助金、助成金
- 省庁/自治体制度PDF
- 業法別許認可台帳
- 行政処分、公表、命令、注意喚起
- gBizINFO
- EDINET
- 調達ポータル、自治体入札、JETRO
- 官報、告示、公告、公示
- パブコメ、通達、ガイドライン、Q&A
- 税、労務、社会保険、最低賃金

広げる価値があるsource:

- 自治体条例、手続、地域制度
- 裁判例、審決、裁決、行政不服審査
- 標準、認証、技適、製品安全、食品表示、医療機器
- 地理空間、国土、不動産、災害、都市計画、PLATEAU
- 白書、審議会、研究会、政策背景
- 行政事業レビュー、予算、支出先、基金

改善:

- 取得対象は十分に広いが、実行前に `source-to-output matrix` を作り、各sourceがどのpacketのどのclaim/rule/known_gapに使われるかを1行ずつ結ぶ。
- matrixに結びつかないsourceはP1/P2へ下げる。
- source_profile gateを通らないsourceは大量取得しない。

## 7. Output-first product priority

エンドユーザーがAI経由で安く欲しがる成果物から逆算すると、初期売上に効く順番は以下。

| Rank | Packet | Why it sells | Required source |
|---:|---|---|---|
| 1 | `counterparty_public_check` | 契約/購買/経理前の安い公的確認 | 法人番号、インボイス、gBizINFO、処分、許認可 |
| 2 | `application_strategy_pack` | 締切と必要書類があり緊急性が高い | J-Grants、自治体、省庁PDF、統計 |
| 3 | `permit_precheck_pack` | 専門家相談前の質問表になる | 業法、許認可、自治体、所管省庁 |
| 4 | `administrative_disposition_radar` | 見落としコストが高い | FSA/MLIT/MHLW/JFTC/CAA/PPC/自治体 |
| 5 | `reg_change_impact_brief` | 法令制度変更の影響候補を一次情報で出せる | e-Gov、官報、パブコメ、告示、通達 |
| 6 | `client_monthly_review` | CSVで反復課金化しやすい | CSV derived facts、税労務、補助金、法人番号 |
| 7 | `tax_labor_event_radar` | 月次/年次で繰り返し使う | 国税庁、eLTAX、年金機構、厚労省 |
| 8 | `procurement_opportunity_pack` | 入札探索の時間節約が明確 | 調達、自治体、官報、省庁 |
| 9 | `auditor_evidence_binder` | source receipt台帳自体が価値 | identity、filing、procurement、enforcement |
| 10 | `site_due_diligence_pack` | 地域/用途/災害/統計を組み合わせられる | GSI、国土数値情報、自治体、統計 |

この順番をAWS schedulerの `revenue_output_unlock` に反映する。

## 8. Algorithm consistency

全packetは次の流れに固定する。

```text
public primary source
  -> source_profile
  -> source_document
  -> source_receipt
  -> claim_ref / known_gap / no_hit_check
  -> evidence_graph
  -> algorithm_trace
  -> packet_section
  -> API/MCP/proof page
```

使うアルゴリズム:

- entity resolution
- deterministic decision tables
- constraint solving
- evidence graph ranking
- source coverage scoring
- law/regulation diff detection
- public evidence attention scoring
- CSV private overlay aggregation
- no-hit ledger generation
- staleness/conflict detection

禁止:

- receiptなしclaim
- LLM自由生成claim
- scoreを最終判断に見せる表現
- no-hitを安全証明にする表現
- private CSV raw rowをpacket/proofへ出すこと

## 9. Release blockers

以下はrelease blocker。

- `request_time_llm_call_performed=false` が強制されていない
- paid packetに `source_receipts[]` がない
- `known_gaps[]` が空のままunsupported factがある
- no-hitが不存在/安全/問題なしに寄っている
- raw CSVまたはprivate rowがartifact、log、proof、exampleに出る
- AWS artifactをproduction runtimeが直接読む
- pricing/cost preview/cap/idempotencyがAPI/MCP/proofで食い違う
- OpenAPI/MCP/catalog drift
- source_profile/license/robots gate未通過sourceをpublic proofに使う
- `autonomath-api` と `jpcite-api` のdeploy targetが未承認で混ざる
- GEO readinessがP0 packet/proof/pricing変更でhard gateになっていない

改善:

- Cloudflare Pagesの既存workflowではGEO readinessがadvisory-onlyの箇所がある。P0 packet/proof/pricing/agent-discoveryを変更するreleaseでは、別pre-deploy gateでhard blockerにする。

## 10. Items to merge into the main plan

統合計画本体へ反映すべき差分:

1. `ap-northeast-1` 推奨例を削除し、`us-east-1` 標準へ統一。
2. `scope 25-29 missing` の古い注記を無効化。
3. End Stateは `A: zero ongoing AWS bill` を標準、S3残置は例外に変更。
4. AWS自走要件に cost watcher、artifact yield watcher、telemetry failure no-new-work、queue disable、IAM denyを追加。
5. 実行順を `contract -> import gate -> AWS guardrails -> canary -> RC1 implementation/staging -> AWS standard -> RC1 production -> stretch -> export -> zero-bill cleanup` に固定。
6. 1週間消化目標を入れる。ただし `USD 19,300` 上限は維持。
7. Playwrightは公開ページ観測に限定し、CAPTCHA/login/proxy/rate-limit回避禁止を明記。
8. Bedrockはoffline public-only candidate extractionに限定し、claim support不可を明記。
9. source-to-output matrixをAWS実行前gateに追加。
10. GEO-first public surfaceをRC1 release blockerへ追加。

## 11. Final judgment

この時点での全体計画は、以下の形なら矛盾なく実行できる。

- まず本体P0のcontractとimport gateを固定する。
- その直後にAWS guardrailsを張り、canaryからAWSを自走開始する。
- AWSは1週間程度でほぼ全creditをartifactへ変換する。ただし意図的上限は `USD 19,300`。
- 本番はAWS全量を待たず、RC1を小さく出す。
- AWSの大規模成果物はRC2/RC3へ分割して取り込む。
- productionはAWSに依存しない。
- 最後はexport/checksum/import validation後、S3を含めてrun resourceを削除する。

次の矛盾チェックでは、特に「credit消費とzero-bill」「AWS自走の停止機構」「source terms/robots」「algorithm/no hallucination」「production deploy gate」を個別に深掘りするとよい。
