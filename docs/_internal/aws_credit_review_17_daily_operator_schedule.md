# AWS credit review 17: daily operator schedule

作成日: 2026-05-15  
レビュー枠: AWSクレジット統合計画 追加20エージェントレビュー 17/20  
担当: 1-2週間の運用日程表、本体P0実装、staging、production deploy、AWS credit runの順序統合  
AWS CLI profile: `bookyou-recovery`  
AWS Account ID: `993693061769`  
Default / workload region: `us-east-1`  
状態: Markdownレビューのみ。AWS CLI/APIコマンド実行、AWSリソース作成、デプロイ実行はしない。

## 0. 結論

本体P0計画とAWS credit runは、次の順番で一体化する。

1. P0契約を先に固定する。
2. AWS guardrailと自走制御を先に作る。
3. USD 100-300のcanaryで成果物契約を検証する。
4. 最小のP0本体実装をstagingへ出す。
5. fast laneではDay 3-5に限定公開レベルのproduction deployを狙う。
6. AWS standard runはproduction deployを待たずに自走継続する。
7. AWS成果物を段階的にrepoへ戻し、full laneではDay 7-14で完全版へ寄せる。
8. USD 18,900以降はno-new-workに入り、export、checksum、cleanupへ切り替える。
9. credit run終了後はAWS上の有料リソースを残さない。

重要な判断:

- 本番デプロイを早めるため、AWS全成果物の完成をproductionの前提にしない。
- ただし、productionで見せるpacketは、source receipt、known gap、pricing/cap、no-hit caveat、forbidden claim gateを満たすものだけに限定する。
- fast lane productionは「最小安全リリース」であり、未完成packetはcatalog上で `disabled` / `preview_disabled` / `requires_more_receipts` として出す。
- full lane productionは「6 P0 packet + CSV private overlay + proof/discovery + GEO release gates」まで揃える。
- Codex/Claude/ChatGPTのレートリミットはAWS runの停止条件にしない。AWS側はBatch queue、budget action、scheduled cost poller、state ledger、stop/drain automatonで自走する。
- ただし、コスト監視やBudget Actionsが壊れた状態で盲目的に走らせない。telemetry failure、untagged spend、paid exposure、unexpected service driftが出た場合は、AIエージェントの有無に関係なくno-new-workへ落とす。

## 1. Operating Model

### 1.1 役割

一人で兼務してよいが、確認欄は役割ごとに分ける。

| Role | 見るもの | 主な判断 |
|---|---|---|
| Product owner | packet価値、公開文言、pricing、GEO導線 | productionへ出す価値があるか |
| AWS operator | Cost Explorer、Budgets、Batch、S3、CloudWatch、resource inventory | 継続、減速、停止、cleanup |
| Repo implementer | P0実装、tests、OpenAPI/MCP/site generation | codeが契約どおりか |
| QA / release owner | staging smoke、production gate、rollback準備 | deployしてよいか |
| Safety / privacy owner | CSV、no-hit、known gaps、terms、forbidden claims | 公開してはいけないものが混ざっていないか |
| Cost observer | cost ledger、artifact ROI、stopline | creditを価値ある成果物に変換できているか |

### 1.2 Lane

| Lane | 内容 | AWSとの関係 |
|---|---|---|
| Lane A: P0 implementation | packet contract/catalog、receipts、pricing、CSV、composers、REST/MCP、proof pages | AWS成果物の受け皿を作る |
| Lane B: AWS artifact factory | J01-J24をBatch/Spot/managed serviceで生成 | 本体の価値を増やす材料を作る |
| Lane C: import/eval | manifest、checksum、quality gate、repo import | AWS成果物を公開可能/内部利用/破棄へ分ける |
| Lane D: deploy | staging、production、post-deploy smoke、rollback | agentが推薦できる公開面へ出す |
| Lane E: zero-bill cleanup | export、checksum、resource delete、final inventory | credit後に請求を残さない |

### 1.3 Source Of Truth

- 本体P0: `docs/_internal/consolidated_implementation_backlog_deepdive_2026-05-15.md`
- AWS統合: `docs/_internal/aws_credit_unified_execution_plan_2026-05-15.md`
- IAM/Budgets: `docs/_internal/aws_credit_review_07_iam_budget_policy.md`
- Manifest: `docs/_internal/aws_credit_review_08_artifact_manifest_schema.md`
- Queue/pacing: `docs/_internal/aws_credit_review_09_queue_sizing_pacing.md`
- Terminal stages: `docs/_internal/aws_credit_review_10_terminal_command_stages.md`
- Daily schedule: this document

## 2. Non-Negotiable Gates

| Gate | 名前 | GO条件 | NO-GOなら |
|---|---|---|---|
| G0 | account/credit gate | `bookyou-recovery`、account `993693061769`、region `us-east-1`、credit balance/expiry/eligible service確認 | AWS write禁止 |
| G1 | P0 contract freeze | packet envelope、receipt fields、known gap enum、pricing metadata、CSV privacy rule、no-hit wording固定 | AWS scale禁止 |
| G2 | autonomous AWS controls | Budgets、Budget Actions、stop scripts、scheduled cost poller、queue disable/cancel/drain、ledgerがある | canaryより先へ進まない |
| G3 | canary artifact gate | canaryでmanifest、checksum、receipt、claim、gap、packet例、forbidden scanが通る | standard run禁止 |
| G4 | staging gate | tests、OpenAPI/MCP drift、privacy scan、billing/cap/idempotency、staging smokeが通る | production禁止 |
| G5 | production gate | production deploy go gate、rollback plan、post-deploy smoke、kill switch、public wording reviewが通る | production禁止 |
| G6 | cost stopline gate | `17,000 / 18,300 / 18,900 / 19,300` の制御が動く | no-new-workまたはemergency stop |
| G7 | safety gate | raw CSVなし、no-hit misuse 0、forbidden claim 0、license boundary不明はclaim supportに使わない | publish/import禁止 |
| G8 | zero-bill gate | export checksum OK、resource inventoryでrun resourceなし | credit run終了宣言禁止 |
| G9 | LLM-rate-limit independence | AWS runがterminal/chat sessionなしで継続/停止/cleanupできる | 長時間run禁止 |

## 3. LLM Rate Limitに依存しないAWS自走設計

ユーザーの要件は「CodexやClaude Codeのレートリミットが来てもAWSは止まらず、クレジットの安全線まで速く動く」ことである。これを満たすには、チャットエージェントをrunのheartbeatにしない。

### 3.1 自走に必要な部品

| Component | 役割 | 失敗時 |
|---|---|---|
| Batch queues | J01-J24をterminal sessionなしで処理する | queue disable/cancelへ |
| Checkpointed jobs | Spot interruptionやterminal切断後もshard再開できる | failed shardを低優先rerunへ |
| `run_state.json` | `preflight/canary/standard/stretch/drain/cleanup` の状態を記録 | state不明ならno-new-work |
| Cost poller | 15分ごとにcost/queued exposure/untagged spendをledgerへ書く | telemetry failureでno-new-work |
| Budget Actions | `DenyNewWork` / `EmergencyDenyCreates` を補助ブレーキとして貼る | break-glassはcleanup用途のみ |
| Queue cap controller | accepted artifact yieldとstoplineで並列度を上下する | capを0へ落とす |
| Artifact quality gate | receipt/gap/privacy/forbidden/no-hitをwaveごとに評価 | 次wave禁止 |
| Cleanup automaton | drain/export/checksum/deleteを順序化する | deletion前にchecksum不一致ならcomputeだけ止める |

### 3.2 事前承認の範囲

AIエージェントの追加指示がなくても進めてよい範囲:

- canary合格後、standard run J01-J16をUSD 17,000まで自動拡大。
- accepted artifact yieldが良く、安全gateが通る場合、selected stretchをUSD 18,900まで自動実行。
- USD 18,900に到達したら、手動判断を待たずno-new-workへ入る。
- no-new-work後は、新規jobを止め、finish/export/checksum/cleanupへ自動移行。

人間の明示承認が必要な範囲:

- USD 19,100-19,300のmanual stretch。
- cross-region利用。
- Bedrock/Textract/OpenSearchの上限引き上げ。
- productionへ新しいpaid packetを有効化する変更。
- cleanupでexport未確認artifactを破棄する判断。

AIレートリミット中の原則:

- AWS standard/stretchは止めない。
- ただし、新しい価値仮説の追加、手動stretch、prod有効化はしない。
- telemetry failure時は「継続」ではなく「no-new-work」へ落とす。

## 4. Fast LaneとFull Lane

### 4.1 Fast Lane: Day 3-5 production

目的:

- できるだけ早く `api.jpcite.com` と公開discovery面を、AIエージェントが推薦可能な最小安全形にする。
- AWS bulk outputを待たず、canary/既存data/小さなreceipt backboneでproductionへ出す。

productionで有効化できる最小packet候補:

| Packet | Fast lane status | 条件 |
|---|---|---|
| `evidence_answer` | enabled候補 | source_receipts、known_gaps、no-hit caveat、pricing metadataが揃う |
| `source_receipt_ledger` | enabled候補 | receipt completenessが検証済み |
| `agent_routing_decision` | enabled候補 | free preflightとして、使う/使わない/preview/cap/API keyを説明できる |
| `company_public_baseline` | conditional | stable company identityがある入力だけ。name-only曖昧入力はgap/validation error |
| `application_strategy` | disabledまたはlimited | eligibility/approval断定を避け、候補順位とknown gapsのみ |
| `client_monthly_review` | disabled | CSV privacy pipelineが通るまで公開実行しない |

Fast laneの公開表現:

- 「全6 packetが完全稼働」とは言わない。
- 有効packetだけを公開catalogへ出す。
- 未有効packetは `preview_disabled` とし、価格/ルートだけ先に出す場合も実行不可にする。
- paid executionはfree cost preview、API key、cap、idempotencyが通るまでONにしない。

Fast lane NO-GO:

- pricing/cap/idempotencyがない。
- no-hitを不存在/安全/適格へ変換している。
- source_receiptなしの再利用claimがある。
- public pageやOpenAPI例にraw CSV、private data、placeholder secretが混ざる。
- rollbackが即時にできない。

### 4.2 Full Lane: Day 7-14 production

目的:

- 6 P0 packet、CSV private overlay、proof pages、OpenAPI/MCP/llms/.well-known、GEO eval、release gatesを揃える。
- AWSで作ったsource_receipts/claim_refs/known_gaps/proof artifactsを本体へ取り込む。

Full lane GO:

- six P0 examplesがcommon envelopeでvalidateされる。
- `request_time_llm_call_performed=false` が全packetで固定。
- `source_receipts[]`、`claim_refs[]`、`known_gaps[]`、`billing_metadata`、`human_review_required` が全packetにある。
- CSV packetはaggregate-only derived factsだけを使う。
- OpenAPI、MCP manifest、public docs、proof pages、`llms.txt`、`.well-known` がcatalogとdriftしない。
- GEO eval、forbidden-claim scan、privacy leak scan、no-hit misuse scanが通る。

## 5. Daily Schedule: Day -1 to Day 14

時刻はJST前提。各日の朝/昼/夕で次を見る。

- 09:00: cost/artifact/quality/status確認
- 13:00: implementation/deploy gate確認
- 18:00: stopline/queue/production health確認
- 23:00: autonomous runの状態だけ確認。人間が不在でもAWSが次状態へ進む設計にする。

### Day -1: 契約固定と実行前棚卸し

目的:

- AWSにお金を使う前に、本体P0とAWS成果物の契約を固定する。
- production deployで迷わないようにrelease laneを決める。

やること:

- P0-E1 common envelopeを固定する。
- six P0 packetのstatusを `enabled_candidate / conditional / disabled` に分ける。
- `source_receipts`、`claim_refs`、`known_gaps`、`no_hit_checks`、`billing_metadata` の必須fieldを固定する。
- AWS `run_manifest` / `artifact_manifest` / `dataset_manifest` のschemaを固定する。
- Fast laneで出すpacketを仮決定する。
- production targetはcanonical Fly app `autonomath-api` として扱い、legacy app名混入をblockerにする。
- SQLite/Fly volume前提のため、productionはscale outしない。

GO:

- P0契約、AWS manifest契約、fast/full laneの違いが文書化済み。
- 未完成packetをproductionでONにしない方針が決まっている。

NO-GO:

- packet名、route、MCP tool、pricing unit、proof page URLが複数sourceに分裂している。
- AWS成果物をどこへimportするか決まっていない。

成果物:

- contract freeze note
- fast lane packet status matrix
- AWS run accepted artifact definition

見る人:

- Product owner、Repo implementer、Safety owner

止める場所:

- AWS write、staging deploy、production deployをすべて止める。

### Day 0: AWS preflight + guardrail setup + P0実装開始

目的:

- AWS account/credit/regionを確認し、write前の安全線を作る。
- 本体側はP0-E1/P0-E2の最小実装に着手する。

やること:

- AWS Billing consoleでcredit残高、期限、eligible services、現時点のpaid exposureを確認する。
- `bookyou-recovery`、account `993693061769`、region `us-east-1` をledgerへ記録する。
- Budgets、Budget Actions、permission boundary、required tags、stop scripts、resource inventory設計を確認する。
- Cost poller、queue cap controller、run state ledgerの設計を確定する。
- Repo側はpacket catalog、common envelope、receipt/gap primitivesの実装branchを切る。
- P0 contract testsを先に作る。

GO:

- G0/G1/G2が設計上通る。
- AWS writeを始める前にstop/drain手順がある。
- 本体P0 contract testsがfail-firstで置ける。

NO-GO:

- accountが違う。
- credit expiry/eligible servicesが不明。
- Budgetsをhard cap扱いしている。
- stop/drain/cleanup権限がない。

成果物:

- manual console gate
- IAM/Budget setup checklist
- P0 contract test skeleton
- run decision ledger

見る人:

- AWS operator、Cost observer、Repo implementer

止める場所:

- AWS write開始前で止める。

### Day 1: Stop drill + AWS canary + P0-E1/E2/E3実装

目的:

- 小さくAWSを動かして、成果物契約と停止手順を証明する。
- 本体はpacket contract、source receipt、pricing previewを最小実装する。

やること:

- AWS guardrail setup後、dummy/emptyでqueue disable、job cancel、compute cap 0、resource inventoryを練習する。
- CanaryとしてJ01/J03/J12/J15/J16の極小sliceを実行する前提でrunbookを用意する。
- Canary出力がmanifest/checksum/source_receipts/claim_refs/known_gaps/no_hit_checks/packet exampleを満たすか確認する。
- 本体側は `request_time_llm_call_performed=false`、`no_hit_not_absence`、known gap enumを固定する。
- `POST /v1/cost/preview` とcap/idempotencyの最小実装に入る。

GO:

- stop drillが成功。
- canary成果物がG3に通る。
- pricing previewが無料で、anonymous execution quotaを消費しない設計になっている。

NO-GO:

- stop drillが失敗。
- canary artifactにprivate/raw CSV、placeholder secret、forbidden claimが混ざる。
- no-hitがabsence/safety/eligibilityへ変換される。

成果物:

- stop drill ledger
- canary artifact package
- receipt/gap/pricing tests

見る人:

- AWS operator、Safety owner、Repo implementer

止める場所:

- AWS standard runへ進めない。

### Day 2: AWS P0-A backbone + minimal packet composers + staging準備

目的:

- source receipt backboneを作りながら、fast lane production候補のpacket composerを形にする。

やること:

- AWSはJ01-J04とJ11 coreを優先し、J12を各source family後に挟む。
- 本体は `evidence_answer`、`source_receipt_ledger`、`agent_routing_decision` を最初に実装する。
- `company_public_baseline` はstable identity入力だけconditionalで実装する。
- REST facadeとMCP wrapperは同じcatalogから生成/参照する。
- OpenAPI/MCP exampleはcanary artifactを使って生成候補にする。
- Staging deploy checklist、secrets registry、Fly app context、migration target boundaryを確認する。

GO:

- AWS cumulative spendが小さく、accepted artifact yieldが出ている。
- 3 packetのunit testsが通る。
- REST/MCP/catalogにdriftがない。
- staging app/環境がproduction volumeを触らない。

NO-GO:

- source_receiptなしのclaimがpacketに残る。
- pricing/cap/idempotencyより先にbillable workが動く。
- stagingとproduction secretやwebhook secretが混ざる。

成果物:

- P0-A receipt backbone
- 3 packet examples
- staging release candidate

見る人:

- Repo implementer、QA/release owner、Safety owner

止める場所:

- staging deploy前。

### Day 3: Staging deploy + fast lane production判定

目的:

- stagingで実サービスとして確認し、fast lane productionをDay 3に出せるか決める。

やること:

- Pre-deploy verify、production deploy go gateのread-onlyチェックをstaging前に通す。
- Stagingへdeployし、healthz、meta、packet endpoints、cost preview、MCP tool、OpenAPI agent subset、llms/well-known候補をsmokeする。
- Stagingでforbidden-claim、no-hit misuse、privacy leak、OpenAPI/MCP driftを確認する。
- AWSはJ01-J04/J11を継続しつつ、J05/J07/J10の小さなsource expansionへ進む。
- Fast lane production GO/NO-GO会議をする。

GO:

- staging smokeが通る。
- enabled packetの公開文言が安全。
- rollback手順が確認済み。
- production targetがcanonical `autonomath-api` である。

NO-GO:

- stagingで500、schema drift、secret mismatch、migration hang、health check failureが出る。
- `fly.toml` のsingle-machine SQLite制約に反したscale変更がある。
- public docsが全6 packet完全稼働のように見える。

成果物:

- staging smoke report
- fast lane production decision
- rollback packet

見る人:

- QA/release owner、Product owner、Repo implementer

止める場所:

- production deploy直前。

### Day 4: Fast lane production deploy候補 + AWS standard scale

目的:

- Day 3に見送った場合でも、Day 4に最小安全productionを狙う。
- AWS側は本線のartifact factoryを速く回す。

やること:

- Fast lane productionを実行するなら、enabled packetだけ公開し、disabled packetは実行不可にする。
- Deploy後、`https://api.jpcite.com/healthz`、packet endpoint、cost preview、MCP manifest、OpenAPI、public proof/discovery面をpost-deploy smokeする。
- AWSはJ05/J07/J09/J10/J06 text-layerを並列化し、J12/J13を挟む。
- Cost pollerとqueue cap controllerが自走しているか確認する。

GO:

- production post-deploy smokeが通る。
- enabled packetでbilling/cap/idempotencyが働く。
- AWS accepted artifact yieldが良く、failure/retry/untagged spendが問題ない。

NO-GO:

- production smoke失敗時は即rollback。
- AWS unexpected service spend > USD 100、untagged spend、NAT/data transfer driftはnew work停止。

成果物:

- fast lane production releaseまたはexplicit deferral
- production smoke report
- AWS standard scale status

見る人:

- Product owner、QA/release owner、AWS operator、Cost observer

止める場所:

- production rollback、またはAWS queue cap縮小。

### Day 5: Fast lane最終日 + CSV privacy実装 + proof bridge

目的:

- fast lane productionがまだならDay 5を最終判断日にする。
- full laneへ必要なCSV/privacy/proof/discoveryの土台を作る。

やること:

- Fast laneが未deployなら、Day 5でproduction GO/NO-GOを決める。NO-GOならfull laneへ切り替える。
- P0-E4 CSV analyze/preview、aggregate-only derived facts、formula/PII suppressionを実装する。
- AWSはJ14 synthetic/header-only/privacy matrixを走らせる前提で準備する。
- J15 packet/proof fixtureを小さく先行生成する。
- public proof pageとJSON-LDはclaim supportがあるものだけ候補にする。

GO:

- Fast lane productionが安全に出せる、またはfull laneへ明確に切替済み。
- CSV raw bytes/raw rows/raw memos/counterparty namesを保存/ログ/echoしない実装になっている。

NO-GO:

- CSV fixtureに実データが混ざる。
- `client_monthly_review` がraw/private rowを前提にしている。
- proof pageにunsupported claimがある。

成果物:

- CSV privacy tests
- proof fixture first batch
- fast/full lane decision record

見る人:

- Safety owner、Repo implementer、Product owner

止める場所:

- CSV packet公開、proof page公開。

### Day 6: Full lane staging candidate + AWS product bridge

目的:

- full laneのstaging candidateを作り、AWS成果物をP0 packetへ戻し始める。

やること:

- six P0 packetのcommon envelope validationを揃える。
- REST/MCP/OpenAPI/public pagesをcatalog生成またはdrift testで同期する。
- AWSはJ14/J15/J16/J13を優先し、packet examples、forbidden-claim scan、no-hit misuse report、GEO base evalを作る。
- Stagingへfull lane candidateを出す。

GO:

- six P0 packet examplesがvalidateされる。
- disabled/conditional statusがcatalogに明示される。
- GEO/no-hit/forbidden base evalが通る。

NO-GO:

- `request_time_llm_call_performed=false` が崩れる。
- application_strategyがeligibility/approvalを断定する。
- client_monthly_reviewがprivate rowを出す。

成果物:

- full lane staging candidate
- six packet example set
- base eval reports

見る人:

- QA/release owner、Safety owner、Repo implementer

止める場所:

- full lane production。

### Day 7: Full lane production GO候補

目的:

- Fast laneで出していない場合、Day 7を最初のfull lane production候補日にする。
- すでにfast lane production済みなら、full lane patch release候補にする。

やること:

- Production deploy go gateを通す。
- `scripts/ops/production_deploy_go_gate.py` の思想どおり、production mutation可否をread-onlyで確認する。
- Fly app context、secrets registry、migration target boundaries、dirty lane review、pre-deploy verifyを確認する。
- Production deploy後、post-deploy smoke、kill-switch smoke、API host smokeを行う。
- AWSはcumulative USD 12,000-15,500を目安にproduct artifact bridgeを完了させる。

GO:

- G4/G5/G7が通る。
- rollbackが即時にできる。
- public docsが実装状態と一致している。

NO-GO:

- critical dirty lane未レビュー。
- migration target不明。
- production API hostではなくapexだけを見ている。
- smoke失敗。

成果物:

- full lane production releaseまたはpatch
- post-deploy smoke report
- release gate evidence

見る人:

- Product owner、QA/release owner、Repo implementer

止める場所:

- production rollbackまたはrelease延期。

### Day 8: Controlled stretch開始 + post-prod import

目的:

- productionが出ている前提で、AWS creditをproof/discovery/GEO価値に変換する。

やること:

- J17 local gov PDF OCR expansionはJ06のaccepted extraction rateが良い場合だけ実行する。
- J18 Bedrock batchはpublic-only candidate classificationに限定する。
- J19 OpenSearchはtemporary retrieval benchmarkのみ。長期稼働させない。
- J20/J21でGEO adversarial evalとproof pagesを増やす。
- Repoへimportする成果物はmanifest/pass済みに限定する。
- Productionに入れるartifact updateはsmall patchとして出す。

GO:

- standard runでaccepted artifact yieldが良い。
- private leak 0、forbidden claim 0、no-hit misuse 0。
- spend forecastがUSD 18,300未満で健全。

NO-GO:

- stretchがCPU burnや長期infraになっている。
- license boundary不明sourceをclaim supportへ使っている。
- OpenSearch/Textract/Bedrockの上限が未管理。

成果物:

- stretch decision ledger
- expanded proof/GEO artifacts
- repo import batch 1

見る人:

- AWS operator、Safety owner、Cost observer

止める場所:

- stretch queue。

### Day 9: GEO/discovery強化 + staging/production patch

目的:

- AIエージェントが見に来たときに価値を理解しやすい公開面を強化する。

やること:

- `llms.txt`、`.well-known`、OpenAPI agent subset、MCP catalog、proof pagesをcatalogと同期する。
- GEO evalで「いつjpciteを推薦するか」「いつ推薦しないか」「cost preview/cap/API key」を検証する。
- Production patchはdrift testとpost-deploy smoke込みで出す。
- AWSはJ20/J21/J22を中心に、proof scale、QA rerun、Parquet compactionを行う。

GO:

- Agent-facing discovery surfaceが実装状態と一致する。
- no-hit/no-risk/eligibleなどの危険文言が公開面にない。
- production patchがsmall and reversible。

NO-GO:

- SEO向けの曖昧訴求がGEO契約より強くなっている。
- public pageがsource receiptを隠している。

成果物:

- discovery sync report
- GEO eval report
- production patch smoke

見る人:

- Product owner、QA/release owner、Safety owner

止める場所:

- public discovery publish。

### Day 10: Watch line到達前後の価値選別

目的:

- USD 17,000 watch line付近で、低価値jobを止め、高価値artifactだけを残す。

やること:

- accepted artifact per USD、failed shard、retry rate、review backlogを確認する。
- J17-J23のうち、production/GEO/proofに効くものだけ継続する。
- Low-yield source family、large Athena scan、低価値rerunを止める。
- Productionではartifact import batch 2を出すか判断する。

GO:

- USDあたりのaccepted receipt/proof/evalが増えている。
- failure rate < 10%、retry rate < 15%。
- untagged spendなし。

NO-GO:

- accepted artifact countが2時間停滞している。
- computeだけ燃えている。
- unexpected service spendが増えている。

成果物:

- cost/artifact ROI report
- low-yield stop list
- import batch 2 decision

見る人:

- Cost observer、AWS operator、Product owner

止める場所:

- low-value queues、rerun-low queue。

### Day 11: Slowdown line準備

目的:

- USD 18,300 slowdown lineを越える前に、探索をやめて最終成果物化へ寄せる。

やること:

- OCR/OpenSearch/Bedrock/large joinを継続する価値があるか再判定する。
- J24 final packaging/checksum/exportの準備を始める。
- proof pages、OpenAPI/MCP examples、packet examplesをfinal candidateへまとめる。
- Production側は新機能ONではなく、品質修正と文言修正を優先する。

GO:

- high-yield stretchだけが残っている。
- final export manifestが作れる状態。

NO-GO:

- 新しいsource familyを増やそうとしている。
- manual approvalなしにUSD 19,100-19,300 stretchへ入ろうとしている。

成果物:

- slowdown decision ledger
- final package candidate list
- production safety patch list

見る人:

- AWS operator、Cost observer、Safety owner

止める場所:

- stretch services、large join、wide scan。

### Day 12: No-new-work準備 + 最終production patch候補

目的:

- USD 18,900 no-new-workに入る前に、最後にpublish/importするものを決める。

やること:

- 新規AWS job投入を止める準備をする。
- finishさせるjob、cancelするjob、terminateするjobを分類する。
- Repo importの最終候補を `candidate / internal / review_required / do_not_import` に分ける。
- Final production patchを出すならこの日までにstagingを通す。
- zero-bill cleanup checklistを更新する。

GO:

- no-new-work後にやることがexport/checksum/cleanupだけになっている。
- production patchが品質改善であり、新しい危険面を増やさない。

NO-GO:

- 未検証artifactをproductionへ入れる。
- no-new-work直前に新しいmanaged serviceを作る。

成果物:

- final import plan
- no-new-work transition plan
- zero-bill cleanup precheck

見る人:

- QA/release owner、AWS operator、Safety owner

止める場所:

- new AWS job、new production feature flag。

### Day 13: Drain/export/checksum/cleanup開始

目的:

- 新規workを止め、価値ある成果物をAWS外へ持ち帰り、有料resourceを消し始める。

やること:

- Batch queueをdisableし、queued jobをcancelする。
- running jobはnear-complete/high-valueだけfinishさせ、他はterminateする。
- S3 artifactsをlocal/non-AWSへexportする。
- checksum ledgerを検証する。
- ECR、Batch、EC2/EBS、OpenSearch、Glue、Athena result、CloudWatch logs、Step Functions、Lambda、NAT/EIP/ENIをcleanup順に削除する。
- S3 bucketはexport/checksum完了後に削除候補へ入れる。

GO:

- checksumが一致している。
- final artifactsがrepo importまたはlocal export済み。
- cleanup roleで削除できる。

NO-GO:

- checksum mismatch。
- cleanupがDeny policyで詰まる。
- unknown tagged resourceが残っている。

成果物:

- export package
- checksum ledger
- cleanup ledger draft

見る人:

- AWS operator、Cost observer、Safety owner

止める場所:

- 新規workはすでに停止。checksum不一致時は削除対象を限定して再exportへ戻す。

### Day 14: Zero-bill確認 + final report + production安定化

目的:

- AWS credit runを閉じ、以後請求が走らない状態を確認する。
- productionに残すものと、次に実装するものを整理する。

やること:

- `CreditRun=2026-05` / `SpendProgram=aws-credit-batch-2026-05` のresource inventoryを最後まで確認する。
- S3 bucketも含め、zero ongoing AWS bill方針なら削除する。
- CloudWatch logs/alarms、ECR images、Athena workgroups/result buckets、Glue catalog、OpenSearch、Batch compute environments、EC2/EBS/snapshotsを再確認する。
- Budgets/Budget Actionsは、不要なら削除し、残す場合はnear-zero alarmだけにする。
- Final cost/artifact ROI、source receipt coverage、GEO eval、cleanup zero-bill reportをrepoへ保存する。
- Production healthを確認し、次のP1 backlogへ移す。

GO:

- tagged run resourcesが0。
- export/checksum/cleanup reportが揃う。
- production smokeが安定。

NO-GO:

- AWS上に有料resourceが残る。
- S3を残すのにzero billと言っている。
- cleanup reportがない。

成果物:

- `docs/_internal/aws_credit_run_ledger_2026-05.md`
- `docs/_internal/source_receipt_coverage_report_2026-05.md`
- `docs/_internal/geo_eval_aws_credit_run_2026-05.md`
- `docs/_internal/aws_cleanup_zero_bill_report_2026-05.md`
- final import PR/patch list

見る人:

- Product owner、AWS operator、Cost observer、QA/release owner

止める場所:

- credit run完了宣言。

## 6. Production Deploy Gate Detail

production deployで苦戦しないため、以下を日程表に組み込む。

### 6.1 事前確認

- canonical Fly appは `autonomath-api`。
- legacy app名 `jpcite-api`、`autonomath-api-tokyo`、`AutonoMath`、`jpintel-mcp` がdeploy commandに混ざらない。
- SQLite volume前提なので、LiteFS/Postgresなしにscale countを2へ増やさない。
- `fly.toml` のsingle-machine/volume制約を変えない。
- staging secretとproduction secretを混ぜない。
- Stripe webhook secretはendpointごとに分離する。
- `JPINTEL_CORS_ORIGINS` はproduction originを明示する。
- APPI intake/deletionを有効化するならTurnstile/secret gateを再確認する。

### 6.2 Read-only gates

production前にread-onlyで確認するもの:

- pre-deploy verify
- production deploy go gate
- OpenAPI drift
- MCP manifest drift
- llms/.well-known drift
- packet catalog drift
- privacy leak scan
- forbidden claim scan
- no-hit misuse scan
- billing/cap/idempotency tests
- dirty critical lanes review
- migration target boundary check

### 6.3 Smoke

production後に確認するもの:

- `GET https://api.jpcite.com/healthz`
- `POST /v1/cost/preview`
- enabled packet endpoint
- MCP manifest/tool discovery
- OpenAPI agent subset
- public packet/proof pages
- `llms.txt` / `.well-known`
- authなし、bad key、valid key
- rate limit/cap behavior
- Stripe webhook signature rejection for bad signature
- security headers/CORS
- kill-switch smoke against API host, not apex only

### 6.4 Rollback

- production smoke失敗なら即rollback。
- DB migrationが原因の場合、手編集rollbackではなくforward fix。
- public docsだけ先に戻してもAPIが壊れていれば解決扱いにしない。
- rollback後もAWS artifact factoryは自走継続できる。ただしproduction importを止める。

## 7. Cost And Stopline Operation

### 7.1 Stopline

| Line | USD | Day scheduleでの扱い |
|---|---:|---|
| Watch | 17,000 | Day 10前後。low-yield停止、高価値artifactのみ継続 |
| Slowdown | 18,300 | Day 11前後。OCR/OpenSearch/Bedrock/large joinを原則停止 |
| No-new-work | 18,900 | Day 12-13。新規job禁止、finish/export/checksum/cleanup |
| Manual stretch | 19,100-19,300 | 人間の明示承認がある場合だけ |
| Absolute safety | 19,300 | emergency stop。意図的に超えない |
| Credit face value | 19,493.94 | 目標値ではなくlag/non-credit buffer |

### 7.2 速く使うための方針

速く使うとは、成果物になる処理へ早く並列投入することであり、無意味にCPUを燃やすことではない。

- Day 1でcanary合格後、Day 2-4にJ01-J11を一気にstandard scaleへ上げる。
- J12/J13/J16を後回しにせずwaveごとに挟み、失敗runを早く止める。
- J15を早く回し、本体実装とproof pagesへ戻す。
- Day 8以降のstretchは、proof/GEO/OCR/QAに絞る。
- Cost pollerが生きている限り、チャットエージェント不在でもqueueは継続する。

### 7.3 止める条件

即時no-new-work:

- Cost telemetry failure
- untagged spend
- paid exposure `USD 25` 以上
- unexpected service spend `USD 100` 以上
- NAT/data transfer drift
- private/raw CSV leak
- forbidden professional claim
- no-hit misuse
- accepted artifact stagnation 2時間
- job failure rate > 10%
- retry rate > 15%

Emergency stop:

- control spend >= USD 19,300
- Marketplace/Support/RI/Savings Plans/commitment spend
- wrong account/regionでwrite済み
- public data leak
- cleanup不能なDeny誤設定

## 8. Final Output Definition

AWS credit runが成功したと言える条件:

- productionに少なくともagent-safe packet surfaceが出ている。
- full laneではsix P0 packetがcontract/gateを満たしている。
- AIエージェントが読むpublic surfacesが、実装状態、価格、cap、API/MCP導線、source receipt価値を正しく伝える。
- AWSでsource receipt、claim ref、known gap、no-hit、proof、GEO eval、CSV privacy fixtureが生成されている。
- 生成物はmanifest/checksum/provenance付きでrepoまたはlocal exportへ戻っている。
- AWS resource inventoryでcredit run有料resourceが残っていない。
- 以後のAWS請求が走らない状態になっている。

## 9. Recommended Merge Order Into The Main Plan

本体計画へこの順序で統合する。

1. `consolidated_implementation_backlog_deepdive_2026-05-15.md` のP0順を維持する。
2. P0-E1/E2/E3をDay 0-2の最優先にする。
3. P0-E5は3 packet fast laneと6 packet full laneに分ける。
4. P0-E6/E7/E8はDay 2-6にstagingへ出し、Day 3-7でproduction候補にする。
5. AWS J01-J16はDay 1-7にstandard runとして重ねる。
6. AWS J17-J24はDay 8-12のcontrolled stretchに寄せる。
7. P0-E9 release gatesはDay 1から毎日回し、最後だけにしない。
8. Day 13-14はAWS cleanupを最優先にし、新機能追加を止める。

この順序なら、本番デプロイを待ちすぎず、AWS creditも速く使いながら、最終的にはzero-bill cleanupまで閉じられる。
