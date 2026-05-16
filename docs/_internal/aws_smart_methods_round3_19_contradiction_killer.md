# AWS smart methods round3 19/20: contradiction killer

作成日: 2026-05-15

担当: Round3 final cross-review 19/20 / contradiction killer

制約:

- AWS CLI/API/resource creation は実行しない。
- 既存コードは変更しない。
- 出力はこのMarkdownのみ。
- 対象は `aws_smart_methods_round3_01-18`、master plan、round2 integrated、final12 integrated。

## 0. Verdict

判定: **条件付きPASS。ただし、正本計画へ入れるべき矛盾解消差分がある。**

Round3で出た追加案は、方向としては正しい。

中核は次の形に収束させるべき。

1. `Outcome Contract Catalog` を公開商品レイヤーにする。
2. `JPCIR` を唯一の内部交換形式にする。
3. `Policy Decision Firewall` をすべてのclaim/output/surfaceの前段に置く。
4. `Public Packet Compiler` で出力を作る。
5. `Agent Decision Protocol` でAI agentに購入判断を渡す。
6. `Release Capsule` を本番公開単位にする。
7. `AWS Artifact Factory Kernel` は短期の成果物工場に限定する。
8. `AI Execution Control Plane` で、人間の手作業ではなく機械検証と状態遷移で実行する。

ただし、このまま全部をP0へ入れると過剰設計になる。

**修正後の結論:**

- P0は「売れる最小成果物 + AI推薦 + 安全な証跡 + Release Capsule + AWS実行前の機械gate」に絞る。
- P1でAWS canary/full run、Source OS、CSV private overlay、watch foundationを広げる。
- P2で広域graph、自治体/裁判/標準/継続学習を強化する。

## 1. Inputs Reviewed

横断対象:

- `aws_jpcite_master_execution_plan_2026-05-15.md`
- `aws_smart_methods_round2_integrated_2026-05-15.md`
- `aws_final_12_review_integrated_smart_methods_2026-05-15.md`
- `aws_smart_methods_round3_01_meta_architecture.md`
- `aws_smart_methods_round3_02_product_packaging.md`
- `aws_smart_methods_round3_03_agent_mcp_ux.md`
- `aws_smart_methods_round3_04_evidence_data_model.md`
- `aws_smart_methods_round3_05_source_acquisition.md`
- `aws_smart_methods_round3_06_aws_factory_cost.md`
- `aws_smart_methods_round3_07_pricing_billing_consent.md`
- `aws_smart_methods_round3_08_csv_private_overlay.md`
- `aws_smart_methods_round3_09_legal_policy_privacy.md`
- `aws_smart_methods_round3_10_evaluation_geo_quality.md`
- `aws_smart_methods_round3_11_release_runtime_capsule.md`
- `aws_smart_methods_round3_12_developer_runbook.md`
- `aws_smart_methods_round3_13_implementation_architecture.md`
- `aws_smart_methods_round3_14_freshness_watch.md`
- `aws_smart_methods_round3_15_trust_accountability_ui.md`
- `aws_smart_methods_round3_16_abuse_risk_controls.md`
- `aws_smart_methods_round3_17_metrics_learning_loop.md`
- `aws_smart_methods_round3_18_revenue_strategy_critique.md`

## 2. Non-Negotiable Invariants

以下は正本計画で上書き不能にする。

| ID | Invariant | 解釈 |
|---|---|---|
| INV-01 | GEO-first | SEO記事ではなくAI agentが発見、推薦、説明しやすいsurfaceを優先する |
| INV-02 | Outcome-first | 公開商品はpacket名ではなく、買い手の成果物単位で見せる |
| INV-03 | Cheapest sufficient | 高い成果物ではなく、目的に対して最安で十分なrouteを推薦する |
| INV-04 | Public evidence only for public claims | 公開claimは公的一次情報receiptに裏付ける |
| INV-05 | No request-time fact LLM | 事実claimをrequest-time LLMで生成しない |
| INV-06 | No-hit is scoped observation | no-hitは不存在証明ではない |
| INV-07 | Real CSV non-AWS | 実ユーザーCSVはAWS credit runに入れない |
| INV-08 | AWS is disposable | AWSは短期artifact factory。本番runtimeではない |
| INV-09 | Zero-bill after teardown | S3を含めAWS資源を残さない前提 |
| INV-10 | AI executes implementation | 人間の手作業チェックリストをSOTにしない |
| INV-11 | Explicit phase boundary for live AWS | 現在の計画/実装フェーズではAWS実行禁止。将来のlive phaseは機械gate通過後にAIが実行する |
| INV-12 | Release Capsule is the publish unit | 本番公開は検証済みcapsuleへのpointer切替で行う |

## 3. Canonical Vocabulary Corrections

複数文書で表記揺れがある。正本では以下へ統一する。

| 古い/揺れる表現 | 正本表現 | 理由 |
|---|---|---|
| `jpcite_cost_preview` | `jpcite_preview_cost` | agent/MCP tool名の揺れを消す |
| `agent_routing_decision` paid packet | free control output | routingは購入前判断であり課金対象にしない |
| packet-first public catalog | `Outcome Contract Catalog` | エンドユーザーが買うのはAPI部品ではなく成果物 |
| generic `score` | typed `score_set` | 信用スコア/安全スコア誤認を防ぐ |
| trust score | `trust_vector` / `support_state` | 単一スコアは過剰断定になりやすい |
| visible AWS spend | `control_spend_usd` | Cost Explorer遅延より内部台帳を主制御にする |
| permanent evidence graph | JPCIR JSONL + compiled Evidence Lens | zero-billとP0速度を両立する |
| manual runbook | machine-readable execution graph | AI実行前提に合わせる |
| human review as implementation gate | AI fail-closed gate | 人間作業依存を排除する |
| human_review_required | professional/end-user review caveat | 実装作業者ではなく成果物利用者への注意 |
| manual_policy_review_required | `policy_unresolved_fail_closed` | AI実行では未解決policyをブロック状態として扱う |
| zero-AWS claim during factory run | `zero_aws_pending` | AWS稼働中にzero-AWSと表示しない |

## 4. Contradictions Killed

### C-01: "AIが全部やる" vs human/manual review

問題:

Round3文書の一部に `human review queue`、`requires_human_review`、`manual policy review` が残っている。

解消:

- 実装、検証、release gateはAIが行う。
- 人間の手作業確認を必須工程にしない。
- `human_review_required` は成果物の利用注意であり、開発者作業ではない。
- policy/termsがAIで確定できない場合は、`policy_unresolved_fail_closed` としてclaim/support/publicationを止める。
- この状態は失敗ではなく `gap_artifact` として資産化する。

正本マージ差分:

- `human_review_required` の定義を成果物利用者向けcaveatへ限定する。
- `manual_policy_review_required` をSOTから削除し、`policy_unresolved_fail_closed` に置換する。
- release blockerへ `manual checklist required for release` を追加する。

採用判断: **採用必須**

### C-02: "AWS creditを使い切る" vs "現金請求ゼロ"

問題:

ユーザーはUSD 19,493.94をできるだけ使い切りたい。一方で現金請求は絶対不可。

解消:

- `USD 19,493.94` ぴったり消化は狙わない。
- `USD 19,300` を意図的上限にする。
- `control_spend_usd`、budget lease、service risk escrow、panic reserveで止める。
- 残りcreditが少し失効しても、現金請求回避を優先する。

正本マージ差分:

- `use all credit` の表現を `maximize useful credit conversion up to USD 19,300 safety line` に置換する。
- `Credit Exhaustion Without Cash Exposure Protocol` をAWS実行gateに入れる。

採用判断: **採用必須**

### C-03: "AWSを速く燃やす" vs "売れる成果物を作る"

問題:

高速消費だけを目標にすると、使えないスクレイプ、重いOCR、過剰OpenSearchなどが増える。

解消:

- AWS spendはjobではなく `Accepted Artifact Futures` に割り当てる。
- `Canary Economics` でaccepted artifact率を見て拡張する。
- `Marginal Value Frontier` で価値密度の低いlaneを自動停止する。
- 失敗も `terms_block`、`source_gap`、`capture_failed` として資産化するが、公開claimにはしない。

正本マージ差分:

- AWS job schemaに `accepted_artifact_target`、`artifact_value_density`、`abort_cost_usd`、`teardown_debt` を必須化する。
- source/jobは `output_gap_map` に紐づかない限りfull runへ進めない。

採用判断: **採用必須**

### C-04: "AWSが自走する" vs "安全停止できる"

問題:

Codex/Claude/local CLIが止まってもAWSを動かしたい。一方で暴走は不可。

解消:

- 自走はAWS内部のfactory kernelに限定する。
- 新しいサービス種別、新しい上限、新しいsource classは勝手に追加しない。
- `Autonomous Operator Silence Mode` では既存plan内のlease済みworkだけ進める。
- stop lines、service caps、kill switch、panic snapshot、rolling exportを必須にする。

正本マージ差分:

- `AI can execute everything` と `AWS can self-run` を分ける。
- live AWSは封印済みcommand bundle、budget lease、service risk escrow内だけで進む。

採用判断: **採用必須**

### C-05: zero-bill vs watch products

問題:

watch商品は継続更新が必要だが、AWS資源を残すとzero-billに反する。

解消:

- AWSはbaseline、fixtures、watch replay、freshness contractを作るだけ。
- teardown後のwatchは非AWS runtime、既存CI、ローカルAI executor、pull-triggered refreshで行う。
- AWS EventBridge/Lambda/S3/OpenSearch/CloudWatchをwatch用に残さない。

正本マージ差分:

- `Watch products` はP1/P2扱い。
- P0では `freshness_contract`、`no_hit_lease`、`stale_safe_response_mode` のschemaだけ凍結する。

採用判断: **採用。ただしP0はschema/gateのみ**

### C-06: Release Capsule vs continuous updates

問題:

Release Capsuleはimmutable。一方でsource更新、watch、freshnessが必要。

解消:

- 既存capsuleを更新しない。
- 更新ごとに新しいcapsuleを作る。
- 本番はdual pointerで切替。
- rollbackはpointer switch。

正本マージ差分:

- `Release Capsule` に `supersedes_capsule_id`、`freshness_snapshot_id`、`capsule_state` を追加する。

採用判断: **採用必須**

### C-07: Evidence Product OS / Knowledge Graph vs P0実装速度

問題:

Evidence Product OS、Official Evidence Knowledge Graph、EvidenceQLなどを全部P0で作ると重すぎる。

解消:

- P0ではgraph databaseを作らない。
- P0はJPCIR JSONL、manifest、pure compiler passes、Evidence Lens assetsで十分。
- EvidenceQL、Conflict-aware maintenance、Source Twinなどは内部モデルとしてschemaだけ一部採用し、実装はP1/P2へ送る。

正本マージ差分:

- `Official Evidence Knowledge Graph` はP0公開runtimeでもDBでもないと明記する。
- P0 module boundaryに `jpcir`, `policy`, `evidence`, `composer`, `packet`, `billing`, `capsule`, `surface`, `execution` だけを置く。

採用判断: **アーキテクチャとして採用、実装は縮小採用**

### C-08: Outcome-first vs packet/API-first

問題:

初期計画はpacket/APIの説明が強く、エンドユーザーが買う理由が弱くなる。

解消:

- 公開商品は `Outcome Contract Catalog`。
- packetは内部実行単位。
- agentは `agent_purchase_decision` で「最安で十分な成果物」を説明する。

正本マージ差分:

- public catalog、proof pages、MCP/OpenAPI説明をOutcome-firstへ変更する。
- `packet_id` は残すが、`outcome_contract_id` を上位keyにする。

採用判断: **採用必須**

### C-09: cheapest sufficient route vs revenue maximization

問題:

短期売上最大化は高いpacket推薦に寄りやすい。GEO主戦ではagent信頼を壊す。

解消:

- `Cheapest Sufficient Route Solver` を採用する。
- 高いtierは「何が追加で得られるか」をcoverage ladderとして説明する。
- 売上はupsellではなく、信頼、volume、watch conversion、receipt reuse、portfolio batchで伸ばす。

正本マージ差分:

- release gateに `cheapest_sufficient_route_audit` を追加する。
- `reason_not_to_buy` をpreviewに必須化する。

採用判断: **採用必須**

### C-10: proof page vs paid leakage

問題:

agent_decision_pageやproof pageが詳細すぎると、有料成果物の価値を無料で漏らす。

解消:

- proof pageは `Public Proof Surrogate`。
- 無料previewはcoverage、price、gap、source families、example shapeまで。
- paid outputの結論、詳細claim集合、CSV-derived context、full traceは出さない。
- `Preview Exposure Budget` と `Paid Output Extraction Guard` を入れる。

正本マージ差分:

- `agent_decision_page` に `paid_leakage_budget` を必須化する。
- proof page buildをrelease blocker対象にする。

採用判断: **採用必須**

### C-11: CSV売上機会 vs privacy/zero-bill

問題:

CSVは売上機会が大きいが、raw CSVを扱うとAWS・ログ・サポート・public proofで漏れる。

解消:

- real CSVはAWSへ入れない。
- P0はCSV契約、synthetic fixtures、header-only preview、leak testsまで。
- 実CSV機能は `Local-First CSV Fact Extractor` を優先し、server fallbackはmemory-only。
- public source receiptとCSV-derived private receiptを混ぜない。

正本マージ差分:

- `PrivateFactCapsule` はP0 schema採用。
- `real_csv_processing` はP1 feature flagにする。
- name-only counterparty join、payroll/bank/person filesはP0不採用。

採用判断: **schemaはP0採用、実機能はP1延期**

### C-12: legal/tax/permit value vs overclaim risk

問題:

法務、税務、許認可、補助金は価値が高いが、「適法」「 eligible」「許可不要」「問題なし」などの断定が危険。

解消:

- 表現を `candidate`、`checklist`、`public_evidence_support`、`needs_professional_review` へ寄せる。
- `eligible` は外部表示禁止。
- `not_enough_info`、`known_gaps`、`gap_coverage_matrix` を常時表示する。

正本マージ差分:

- forbidden language linterに以下を追加:
  - `eligible`
  - `safe`
  - `no problem`
  - `permit not required`
  - `compliant`
  - `信用スコア`
  - `安全`
  - `問題なし`
  - `許可不要`

採用判断: **採用必須**

### C-13: Playwright "突破" vs terms/safety

問題:

「フェッチ困難を突破」という表現は、規約回避、CAPTCHA回避、stealth/proxyに誤読される。

解消:

- Playwrightは公開ページのrendered observationだけに使う。
- login、CAPTCHA、403/429回避、stealth、proxy、rate-limit回避は不採用。
- screenshotは各辺 `<=1600px`。
- HARはmetadata-only。body/cookie/auth header禁止。
- OCR単独では日付、金額、条番号、法人番号を断定しない。

正本マージ差分:

- `Playwright capture` に `public_rendered_observation_only` を必須field化する。

採用判断: **採用必須**

### C-14: broad source expansion vs sellable source

問題:

公的一次情報を広く集めるのは価値があるが、売れる成果物に直結しない収集が増える。

解消:

- `Source Capability Contract` と `output_gap_map` を先に置く。
- sourceは「source family」ではなく「どのoutcomeのどのgapを埋めるか」で採用する。
- `accepted_artifact_target` なしのAWS jobは走らせない。

正本マージ差分:

- source registryに `primary_outcome_contract_ids[]` と `gap_ids[]` を必須化する。
- broad crawlはP2。P0/P1ではcanary yieldが出たsourceだけ拡張する。

採用判断: **採用必須**

### C-15: Trust UI vs overexplaining internals

問題:

信頼を示すためにAWS台帳や内部graphを見せすぎると、エンドユーザーに不要で、agentにもnoiseになる。

解消:

- end-user UIはTrust Surface Compilerの要約だけ。
- agent JSONには機械可読manifestを出す。
- AWS control tables、budget leases、internal graphなどはpublic UIに出さない。

正本マージ差分:

- `Trust Surface Compiler` はP0採用。ただしpublic UIは最小表示。
- `Trust Dependency Graph`、`Accountability Timeline` はP1/P2へ延期。

採用判断: **P0縮小採用**

### C-16: metrics/learning vs privacy

問題:

改善ループにraw prompt、raw CSV、private factsが混ざると危険。

解消:

- telemetryはaggregateのみ。
- raw prompt、raw CSV、private facts、secrets、PIIは保存しない。
- auto-applyはcopy/layout/catalog metadataなど低リスクのみ。
- pricing、policy、source terms、public claim approvalはAI単独auto-applyしない。未解決ならfail-closed。

正本マージ差分:

- `Privacy-Safe Learning Control Plane` はP1。
- P0はtelemetry schemaとforbidden telemetry lintだけ。

採用判断: **P0 schemaのみ、学習loopはP1延期**

### C-17: Agent surface richness vs 155 tools / full OpenAPI迷子

問題:

AI agentに全tool/full OpenAPIを見せると推薦導線が崩れる。

解消:

- P0はMCP 4-tool facadeに絞る。
- full OpenAPIはdeveloper向け。
- agent-safe OpenAPIはOutcome/preview/execute/retrieveの小さいsurfaceへ分離する。

正本マージ差分:

- `Capability Matrix Manifest` で公開可能toolだけを出す。
- full REST pathsはagent decision pageの主導線にしない。

採用判断: **採用必須**

### C-18: Billing by API call vs accepted artifact pricing

問題:

API実行ごと課金だと、no-hit、policy block、gap-heavy出力で不満が出る。

解消:

- 課金は `Consent Envelope` + `Scoped Cap Token` + `Accepted Artifact Pricing`。
- no accepted artifactの場合はfree/void/partialにする。
- no-hitはscopeと価値が明示された場合のみaccepted artifactになり得る。

正本マージ差分:

- billing ledgerへ `charge_decision` と `acceptance_reason` を必須化する。
- `billing_metadata` はすべての有料/無料previewに含める。

採用判断: **採用必須**

### C-19: AWS zero-bill vs permanent evidence/proof archive

問題:

証跡を残したいからS3を残すと、zero-billに反する。

解消:

- AWS外へのrolling exportを行う。
- S3は最終削除。
- proofはRelease Capsule内のminimized surrogate。
- raw screenshot/HAR/DOM/OCR全文をpublic/prod archiveにしない。

正本マージ差分:

- `External Export Gate` と `Zero-Bill Proof Ledger` をteardown前必須にする。
- `permanent AWS archive` は不採用リストに固定する。

採用判断: **採用必須**

### C-20: RC1最速本番 vs 追加スマート機能の大量化

問題:

Round3で有効な機能が多く出たが、全部やると本番が遅れる。

解消:

- P0は「最初に売れる、agentが推薦できる、事故らない」だけに集中する。
- 高度なsource expansion、watch、full graph、privacy-safe learningはP1/P2へ送る。

正本マージ差分:

- P0/P1/P2を下記の最終cutに置換する。

採用判断: **採用必須**

## 5. Final P0 / P1 / P2 Cut

### P0: RC1 and AWS-canary prerequisite

P0はこれだけに絞る。

1. `Outcome Contract Catalog` minimal
2. `JPCIR` base header and P0 record schemas
3. `Invariant Registry`
4. `Policy Decision Firewall` minimal
5. `No-Hit Language Pack`
6. `known_gaps[]` and `gap_coverage_matrix[]`
7. `source_receipts[]` and `claim_refs[]`
8. `Public Packet Compiler` minimal
9. `Agent Decision Protocol` minimal
10. `jpcite_preview_cost`
11. `Consent Envelope`
12. `Scoped Cap Token v3` schema
13. `Accepted Artifact Pricing` decision schema
14. `Trust Surface Compiler` minimal
15. `agent_decision_page` minimal
16. `Release Capsule` manifest
17. `Surface Parity Checker`
18. `Forbidden Language Linter`
19. `Golden Agent Session Replay` minimal
20. `AI Execution Control Plane`
21. no-op AWS command plan compiler
22. AWS artifact contract schemas
23. zero-AWS dependency scanner
24. production-without-AWS smoke
25. CSV non-AWS schema and synthetic/header-only fixture tests

P0 public outcomes:

| Outcome | Status | Reason |
|---|---|---|
| `company_public_baseline` | P0 paid | 低摩擦、法人番号/インボイス/公的情報で売りやすい |
| `invoice_vendor_public_check` | P0 paid or bundle | CSVなしでも使える。会計文脈とも接続しやすい |
| `source_receipt_ledger` | P0 paid/support | jpciteの差別化を見せる |
| `evidence_answer` | P0 paid/support | general Q&Aではなく証跡付き回答に限定 |
| `agent_routing_decision` | P0 free control | 有料にしない |
| `jpcite_preview_cost` | P0 free control | 購入前判断 |

P0でやらないこと:

- full graph DB
- permanent AWS archive
- full CSV private overlay
- broad municipality crawl
- court/standards/geospatial broad corpus
- watch billing runtime
- real AWS resource creation before live AWS phase
- legal/tax/permit final judgment outputs
- LLM-only terms approval

### P1: After RC1, before broad corpus import

P1で広げる。

1. AWS guardrail/canary/live factory execution
2. `Source Operating System` canary expansion
3. `Source Capability Contract`
4. `Evidence Aperture Router`
5. `Public Corpus Yield Compiler`
6. `Canary Economics`
7. `Budget Token Market v2`
8. `Accepted Artifact Futures`
9. `Release Capsule` pointer runtime
10. `Local-First CSV Fact Extractor`
11. `PrivateFactCapsule` runtime
12. grants/readiness candidate outcomes
13. permit checklist outcomes
14. regulation change watch foundation
15. broader Golden Agent Session Replay
16. Privacy-Safe Learning Control Plane aggregate metrics

### P2: After broad corpus baseline

P2へ延期する。

1. full Official Evidence Knowledge Graph
2. EvidenceQL
3. Source Twin Registry
4. Trust Dependency Graph
5. Accountability Timeline
6. watch portfolio batching
7. broad municipality archetype expansion
8. courts/disputes/enforcement broad baseline
9. standards/certifications broad baseline
10. statistical/geospatial enrichment
11. autonomous pricing/product learning auto-apply beyond safe metadata
12. portfolio/competitor large batch products

## 6. Adopt / Defer / Reject

### Adopt Immediately

| Method | Adoption | Reason |
|---|---|---|
| Evidence Product OS | architecture only | 上位概念として有効 |
| JPCIR | P0 | 実装を一本化する |
| Outcome Contract Catalog | P0 | 売上/GEOの中心 |
| Agent Decision Protocol | P0 | agent推薦の中心 |
| Cheapest Sufficient Route Solver | P0 | 信頼とGEO維持 |
| Policy Decision Firewall | P0 | legal/privacy/termsの一元gate |
| No-Hit Language Pack | P0 | 誤表現防止 |
| Public Packet Compiler | P0 | 出力を機械生成に寄せる |
| Release Capsule | P0 | 本番安全性/rollback/zero-AWS |
| Trust Surface Compiler minimal | P0 | trust/copy/surface parityを機械化 |
| AI Execution Control Plane | P0 | 人間手作業依存を消す |
| Budget/Artifact contract schemas | P0 | AWS実行前提の安全契約 |
| Zero-Bill Proof Ledger | P0 schema, P1 execution | zero-bill証跡 |
| Golden Agent Session Replay minimal | P0 | GEO推薦品質をrelease gate化 |

### Defer

| Method | Target | Reason |
|---|---|---|
| full graph DB / EvidenceQL | P2 | P0速度を落とす |
| CSV full private overlay | P1 | privacyと信頼の実装が必要 |
| Watch products billing | P1/P2 | zero-AWS後の非AWS実行pathが必要 |
| broad municipality crawl | P2 | yield未知、cost大 |
| standards/court/geospatial broad expansion | P2 | 初期売上に直結しにくい |
| Trust Dependency Graph | P2 | P0はsurface parityで足りる |
| advanced learning loops | P1/P2 | privacy-safe aggregateから始める |
| automated source terms classifier | P2 | AI単独approval不可 |
| portfolio/competitor collection products | P2 | abuse controlが重い |

### Reject

| Method | Reason |
|---|---|
| exact USD 19,493.94 burn | 現金請求ゼロと衝突 |
| permanent AWS/S3 archive | zero-billに反する |
| raw CSV upload to AWS | privacy boundary違反 |
| public raw screenshot/HAR/DOM archive | copyright/privacy/termsリスク |
| CAPTCHA/login/403/429 bypass | 公開一次情報の観測範囲を超える |
| stealth/proxy scraping | trustを壊す |
| 155-tool public MCP surface | agentが迷う |
| packet-first public pricing | end-user価値が弱い |
| generic trust/credit/safety score | 過剰断定 |
| `eligible` / `safe` / `permit not required` external claims | legal/tax/permit overclaim |
| LLM-only terms/legal approval | deterministic gateにならない |
| manual checklist as SOT | AI実行前提と矛盾 |
| live AWS commands embedded in Markdown | 誤実行リスク |

## 7. Master Plan Merge Diff

このファイル自体では正本を書き換えない。次のAI実装タスクで正本へ入れる差分は以下。

### 7.1 Add a "Contradiction-Killer Canonical Rules" section

追加内容:

- canonical vocabulary table
- non-negotiable invariants
- P0/P1/P2 final cut
- adopted/deferred/rejected method table

### 7.2 Replace immediate implementation order

正本の実装順は次へ置換する。

1. Freeze `Outcome Contract Catalog` minimal.
2. Freeze P0 packet envelope.
3. Define JPCIR base header and P0 record schemas.
4. Implement Invariant Registry.
5. Implement Policy Decision Firewall minimal.
6. Implement no-hit/known gaps/gap coverage contracts.
7. Implement source receipt and claim ref validators.
8. Implement Public Packet Compiler minimal.
9. Implement Agent Decision Protocol minimal.
10. Implement `jpcite_preview_cost`.
11. Implement Consent Envelope / Scoped Cap Token v3 schemas.
12. Implement Accepted Artifact Pricing decision schema.
13. Implement Trust Surface Compiler minimal.
14. Implement agent_decision_page minimal.
15. Implement Release Capsule manifest and pointer switch contract.
16. Implement Surface Parity Checker.
17. Implement Forbidden Language Linter.
18. Implement Golden Agent Session Replay minimal.
19. Implement AI Execution Control Plane and execution graph.
20. Implement no-op AWS command plan compiler.
21. Implement AWS artifact contract schemas and spend simulator.
22. Run local release gates.
23. Ship RC1 capsule without AWS runtime dependency.
24. Enter live AWS phase only after explicit phase transition and machine preflight pass.

### 7.3 Replace human/manual wording

正本全体で置換:

| Replace | With |
|---|---|
| human operator | AI executor |
| manual checklist | machine-readable gate |
| human review queue | fail-closed policy state |
| requires_human_review as implementation step | professional/end-user review caveat |
| manual policy approval | policy unresolved, not publishable |

注意:

`human_review_required` という出力fieldは残してよい。ただし意味は「この成果物を利用する人間・専門家側の確認が必要」というcaveatであり、開発実行の人間作業ではない。

### 7.4 Add release blockers

追加するrelease blockers:

- Release Capsule contains AWS runtime dependency.
- Release Capsule contains real CSV, private fact raw values, raw screenshot archive, raw HAR body, or auth/cookie material.
- Public surface contains paid output leakage beyond preview budget.
- Agent surface recommends a higher route while a cheaper sufficient route exists.
- Output uses forbidden legal/safety language.
- `agent_routing_decision` is charged.
- `jpcite_cost_preview` appears instead of canonical `jpcite_preview_cost`.
- `zero_aws_attested` appears while AWS factory is still running.
- Source/job lacks `accepted_artifact_target`.
- AWS job lacks teardown recipe.
- live AWS command bundle exists before preflight pass.
- manual checklist is required to release.
- no-hit appears as absence/safety/compliance proof.
- public proof contains raw CSV-derived relationship.
- source terms policy is unresolved but claim is published.

### 7.5 Add AI execution boundary

正本へ以下を追加:

AI performs implementation, validation, local release, and future AWS execution within the active phase. The plan must not depend on human step-by-step execution. However, phase transition into live AWS is a machine-readable boundary state. In planning mode, AWS command/API/resource execution is forbidden. In live AWS mode, AI may execute only sealed command bundles that pass account/profile/region, budget, service, policy, privacy, teardown, and rollback gates.

### 7.6 Add AWS zero-bill wording

正本へ以下を追加:

Zero-AWS / zero-bill language is stateful. During AWS factory execution the state is `zero_aws_pending`. Only after external export, checksum verification, teardown, resource inventory, and production smoke without AWS may the state become `attested_zero_aws`.

### 7.7 Add revenue gate

正本へ以下を追加:

Before broad source collection or expensive AWS stretch, each job must map to at least one `outcome_contract_id`, one `gap_id`, and one expected public or internal accepted artifact. Broad collection without revenue or gap linkage is rejected.

## 8. Final Canonical Architecture After Killing Contradictions

最終形:

```text
Outcome Contract Catalog
  -> Agent Decision Protocol
  -> Consent Envelope / Scoped Cap Token
  -> JPCIR records
  -> Policy Decision Firewall
  -> Evidence Lens
  -> Public Packet Compiler
  -> Trust Surface Compiler
  -> Release Capsule
  -> Agent-safe surfaces / MCP facade / proof surrogate pages
```

AWSは別枠:

```text
AWS Artifact Factory Kernel
  -> Accepted Artifact Futures
  -> Budget Token Market
  -> Source Capability Contract
  -> Canary Economics
  -> Rolling External Exit Bundle
  -> Zero-Bill Proof Ledger
  -> teardown
```

AI実行はさらに別枠:

```text
AI Execution Control Plane
  -> execution_graph
  -> invariant registry
  -> no-op AWS plan compiler
  -> preflight scorecard
  -> autonomous action ledger
  -> rollback state machine
  -> golden failure replay
```

この3つを混ぜないことが最重要。

## 9. Final Risk Register

| Risk | Status | Final resolution |
|---|---|---|
| P0 over-design | High | P0をJPCIR/compiler/capsule/agent decisionに絞る |
| AWS overrun | High | USD 19,300 safety line、budget lease、service escrow |
| Human-dependent implementation | High | machine gatesへ置換 |
| Legal/tax overclaim | High | forbidden language + checklist/candidate表現 |
| CSV leakage | High | P0 real CSV不可、P1 local-first |
| Proof leakage | High | preview exposure budget |
| Agent distrust by upsell | Medium | cheapest sufficient route |
| Broad source vanity work | Medium | outcome/gap-linked source only |
| Watch vs zero-bill | Medium | non-AWS watch path only |
| Trust UI noise | Medium | end-user summary + agent JSON split |
| Privacy telemetry leak | Medium | aggregate-only telemetry |
| Tool surface confusion | Medium | MCP 4-tool facade |

## 10. Final Recommendation

正本計画は実行可能な状態に近いが、Round3の追加スマート案をそのまま全部P0へ入れるのは危険。

最もスマートな最終方針はこれ:

1. **P0は売れる最小成果物とAI推薦導線に集中する。**
2. **高度なgraph/source/watch/learningは、JPCIR schemaで受け止めるが実装はP1/P2へ送る。**
3. **人間作業前提の語彙をすべてAI fail-closed/machine gateへ変換する。**
4. **AWSは短期工場として自走させるが、accepted artifactとbudget leaseで制御する。**
5. **本番はRelease Capsuleのpointer切替で出し、AWSには依存させない。**
6. **GEO/売上は高額upsellではなく、最安で十分な成果物をAI agentが自信を持って推薦できる構造で伸ばす。**

この修正を入れれば、Round3 01-18、round2 integrated、final12 integrated、master planの主要矛盾は解消できる。

## 11. Status

- AWS CLI/API/resource creation: **not executed**
- Existing code changes: **none**
- Output file: `docs/_internal/aws_smart_methods_round3_19_contradiction_killer.md`
- Master plan changes: **not applied here; merge diff documented above**

