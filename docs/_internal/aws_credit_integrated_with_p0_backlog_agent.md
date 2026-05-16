# AWS credit integrated with P0 backlog review

作成日: 2026-05-15  
担当: P0 packet / source_receipt / CSV / GEO / release gate backlog と AWS credit plan の統合レビュー  
Status: planning only。実装、AWS CLI、AWS resource作成、workload実行はこの文書の範囲外。

## 0. 結論

AWS credit run は独立したインフラ計画ではなく、既存の `consolidated_implementation_backlog_deepdive_2026-05-15.md` を加速する短期の成果物生成レーンとして扱う。

統合後の優先順位は次の通り。

1. P0 の packet contract / source receipt / CSV privacy / pricing guard / release gate を先に固定する。
2. AWS credit は、その固定契約に投入できる `source_profile`、`source_document`、`source_receipt`、`claim_ref`、`known_gaps`、public-safe packet examples、proof pages、GEO eval reports を作る。
3. AWS 上の batch、S3、Glue、Athena、OCR、static generation は本番依存基盤にしない。credit終了後に残すのは成果物、manifest、ledger、review backlog、release evidenceだけ。
4. P0 release gate を満たさないAWS成果物は、P1/P2 backlogの入力またはreview backlogに落とし、公開面・MCP・OpenAPI・課金面へ流さない。

つまり、AWS credit の目的は「クレジット消化」ではなく、P0 release gate の証拠と P1/P2 の実装材料を前倒しで買うこと。

## 1. Source of truth

統合時の優先順位は以下で固定する。

| 順位 | Source | 役割 |
|---:|---|---|
| 1 | `consolidated_implementation_backlog_deepdive_2026-05-15.md` | P0/P1/P2 backlog の正本 |
| 2 | `p0_geo_first_packets_spec_2026-05-15.md` | P0 packet envelope、six packet catalog、REST/MCP/public page contract |
| 3 | `geo_source_receipts_data_foundation_spec_2026-05-15.md` / `source_receipt_claim_graph_deepdive_2026-05-15.md` | source receipt、claim graph、known gap、no-hit、private CSV namespace |
| 4 | `csv_accounting_outputs_deepdive_2026-05-15.md` / CSV privacy系deep dive | CSV intake、aggregate-only、fixture、leak scan |
| 5 | `geo_eval_harness_deepdive_2026-05-15.md` / `release_gate_checklist_deepdive_2026-05-15.md` | GEO評価とrelease blocker |
| 6 | AWS credit計画群 | 上記を加速する一時的な compute/output/security/cost runbook |

AWS文書側で新しい packet type、source schema、pricing rule、CSV retention rule、GEO pass threshold が出てきた場合は、AWS側を修正対象とする。P0正本を暗黙に上書きしない。

## 2. Integrated backlog map

### 2.1 P0に直結するAWS消化タスク

P0 は「公開・課金・agent discoveryに乗せる最低単位」。AWS credit を使うなら、この表の範囲に限定する。

| P0 epic | AWS credit task | AWS output | 接続先 | Gate |
|---|---|---|---|---|
| P0-E1 Packet contract and catalog | P0 packet examples生成 | six P0 packet example JSON, catalog drift report | `data/packet_examples/`, public packet pages, OpenAPI/MCP examples | schema validates, catalog metadata一致 |
| P0-E2 Source receipts, claims, known gaps | P0 official source lake / receipt precompute | `source_profile`, `source_document`, `source_receipt`, `claim_ref`, `claim_source_link`, `no_hit_check`, `freshness_ledger` | packet composers, proof pages, source receipt ledger | every public claim has receipt or known gap |
| P0-E3 Pricing policy and cost preview | batch/csv/fanout cost fixture generation | cost preview cases, cap/idempotency scenarios, billing metadata examples | `POST /v1/cost/preview`, `POST /v1/packets/preview`, public pricing copy | no hidden charge, no duplicate charge, batch requires cap |
| P0-E4 CSV privacy and intake preview | synthetic provider fixtures and leak scans | header-only/synthetic CSV fixtures, provider alias matrix, privacy scan reports | CSV analyze/preview tests, `client_monthly_review` | no raw/private value persistence or public leak |
| P0-E5 P0 packet composers | offline packet/proof precompute | public-safe examples for six packets, source receipt ledgers | composer fixtures and public examples | thin composer behavior matches contract |
| P0-E6 REST packet facade | OpenAPI P0 projection examples | P0 agent-safe OpenAPI examples, error/cap examples | REST docs and tests | routes match catalog and guard order |
| P0-E7 MCP agent-first tools | P0 MCP catalog/discovery assets | MCP tool descriptions, alias map, `.well-known/mcp.json` candidate | MCP manifest/docs | tool names, billing, preserve fields match catalog |
| P0-E8 Public proof and discovery surfaces | static proof/public packet/GEO discovery generation | proof pages, `llms.txt`, `.well-known/*`, sitemap/report | public site candidate | no forbidden claim, no private overlay leak |
| P0-E9 Drift, privacy, billing, release gates | release evidence bundle | receipt completeness, leak scan, forbidden-claim scan, GEO scorecard, cost ledger | release gate checklist | all blockers green |

### 2.2 P1に接続するAWS消化タスク

P1 は P0契約が固定された後に厚みを増す領域。AWS creditで作ってよいが、P0公開ブロッカーにしない。

| P1 epic | AWS credit task | P1 handoff |
|---|---|---|
| P1-E1 Persistence and replay | packet run replay datasetの設計検証だけ | `packet_runs` migration候補、retention/replay test cases |
| P1-E2 Public source expansion | P0外のofficial source profile sweep | `source_review_backlog.jsonl`, license/freshness/source priority |
| P1-E3 Algorithmic outputs | ranking/similarity/change detection benchmark fixtures | algorithm input/output fixtures with version and confidence |
| P1-E4 CSV provider templates | freee/Money Forward/Yayoi variant expansion | provider alias matrix, synthetic edge cases, rejection corpus |
| P1-E5 Full ICP packet catalog | P0 six packet以外の候補生成 | packet candidate backlog only。P0 catalogへ混入させない |
| P1-E6 Proof page UX and audit ledger depth | claim/receipt drilldown static prototypes | proof UX examples, hash/freshness filter cases |
| P1-E7 Billing risk controls depth | anomaly/monthly cap/reconciliation scenarios | abuse and cap fixtures, operator alert examples |
| P1-E8 Agent surface playbooks | ChatGPT/Claude/Cursor/Gemini setup eval | integration playbook drafts and failure matrix |
| P1-E9 GEO evaluation harness | weekly mutation set and multi-surface eval | `geo_eval_*` reports, detector dictionaries, regression baseline |

### 2.3 P2に接続するAWS消化タスク

P2 は scale/automation/market expansion。creditで前処理はしてよいが、P0/P1 gateを迂回しない。

| P2 epic | AWS credit task | P2 handoff |
|---|---|---|
| P2-E1 Large-scale prebuilt packet generation | broad static packet/proof generation | generated library candidates, accepted/rejected manifest |
| P2-E2 Watchlists/webhooks/recurring monitors | recurring monitor simulation only | idempotency and cap fixtures。production monitorは作らない |
| P2-E3 Marketplace/directory distribution | marketplace metadata validation | submission asset checklist, drift report |
| P2-E4 Enterprise controls | retention/audit export/security evidence | enterprise backlog material。P0には入れない |
| P2-E5 Advanced source acquisition automation | parser drift/freshness alert corpus | source automation backlog and stale-source triggers |
| P2-E6 Multilingual/international surfaces | English discovery copy/eval variants | i18n discovery candidates with fence preservation |
| P2-E7 Partner integrations | partner-like fixture research | OAuth/partner production integrationは除外 |

## 3. Collision and duplication cleanup

### 3.1 P0/P1/P2 naming collision

AWS batch plan の `P0 pilot / P1 ramp / P2 full run / P3 drain` は backlog の P0/P1/P2 と衝突する。統合後は AWS 実行フェーズを以下に改名して扱う。

| 旧AWS表記 | 統合後の表記 | 意味 |
|---|---|---|
| P0 pilot | AWS-F0 pilot | tag、budget、queue、smoke、stop drill |
| P1 ramp | AWS-F1 ramp | 小規模source/receipt/output run |
| P2 full run | AWS-F2 full useful run | gateに通る成果物だけを拡張 |
| P3 drain | AWS-F3 drain | re-run、export、cleanup、ledger |

Backlog の P0/P1/P2 は product priority、AWS-F0/F1/F2/F3 は short-run operation phase として分離する。

### 3.2 Queue name duplication

AWS文書間で queue name が2系統ある。

- CLI runbook: `jpcite-source-crawl`, `jpcite-pdf-parse`, `jpcite-parquet-build`, `jpcite-packet-precompute`, `jpcite-geo-eval`, `jpcite-load-test`
- Batch compute plan: `jpcite-credit-control-ondemand`, `jpcite-credit-fargate-spot-short`, `jpcite-credit-ec2-spot-cpu`, `jpcite-credit-ec2-spot-memory`, `jpcite-credit-ec2-ondemand-rescue`, `jpcite-credit-codebuild-batch`

統合上は「logical workload」と「compute queue」を分ける。

| Logical workload | Canonical compute queue |
|---|---|
| source crawl/profile sweep | `jpcite-credit-fargate-spot-short` or `jpcite-credit-ec2-spot-cpu` |
| pdf parse/ocr | `jpcite-credit-ec2-spot-cpu` |
| parquet build/compaction | `jpcite-credit-ec2-spot-memory` |
| packet/proof precompute | `jpcite-credit-fargate-spot-short` |
| geo eval | `jpcite-credit-codebuild-batch` or small Fargate queue |
| load/static validation | `jpcite-credit-codebuild-batch` |

CLI runbook の短いqueue名は貼り付け用草案として残してよいが、最終runbookでは compute queue名と workload tag を分ける。`jpcite-load-test` はP0では「public/static validation」に限定し、production負荷試験へ広げない。

### 3.3 Budget threshold mismatch

AWS文書には停止線が複数ある。

- acceleration plan: target USD 18,300-18,700、stop USD 18,900、buffer USD 800-1,200
- cost guardrails: gross burn limit USD 19,000、L3 17,544.55、L4 18,519.24、L5 19,000

統合後は安全側に寄せて以下を採用する。

| Line | Amount | Action |
|---|---:|---|
| watch | USD 17,000 | 成果物効率を見て追加runを絞る |
| soft brake | USD 18,300 | 新規高額job停止。P0 release evidence不足分だけ小粒再実行 |
| stop window | USD 18,519.24 | queue disable、new submit deny、running drain判断 |
| hard stop | USD 18,900 | cancel/terminate、transient resource削除準備 |
| accounting ceiling | USD 19,000 | 反映遅延込みの超過防止線。到達前に停止済みであること |

「USD 19,493.94を使い切る」は採用しない。使い切り狙いはP0/P1/P2 backlogの品質を上げず、現金請求リスクだけを増やす。

### 3.4 CSV boundary duplication

CSV関連計画は同じルールを何度も書いている。統合後の単一ルールは次。

- raw CSV bytes、raw rows、row-level normalized records、free-text memo、counterparty names、personal identifiers、payroll detail、bank account data は保存・ログ・公開・fixture化しない。
- AWS credit run は synthetic/header-only/redacted fixtures と aggregate-only private overlay だけを作る。
- private CSV-derived claim は public claim namespace、public source foundation、proof page、GEO public sampleへ入れない。
- `client_monthly_review` は P0 では normalized `derived_business_facts` first。CSV upload/parserは別gate。

このルールに反するAWS成果物は、生成コストに関係なく破棄または内部security reviewへ隔離する。

### 3.5 Source receipt vs proof page duplication

`source_receipt_ledger` packet、proof page、Athena receipt QA report が重複しやすい。役割を分ける。

| Artifact | Audience | Role |
|---|---|---|
| `source_receipt` dataset | internal implementation | packet composer and claim graph input |
| `source_receipt_ledger` packet | API/MCP user and agent | one packet's claim-to-source ledger |
| proof page | public/agent crawler | public-safe verification surface |
| Athena QA report | operator/release reviewer | completeness, stale, license, leak, no-hit audit |

同じ receipt fields を使うが、公開粒度と保持先は別。Athena QA reportをそのままpublic proofにしない。

### 3.6 GEO output duplication

GEO plan と AWS outputs plan の eval assets は統合する。正本は `geo_eval_harness_deepdive_2026-05-15.md` のrubric。

AWS credit が生成してよいのは、回答・score・failure・mutation・forbidden scan の artifacts。GEOの成功指標は mention share ではなく safe qualified recommendation share。P0 releaseは forbidden claim 0 が絶対条件。

## 4. Integrated execution order

### Step A: P0 contract freeze before AWS-F0

AWS run開始前に固定するもの。

1. `jpcite.packet.v1` envelope
2. six P0 packet registry
3. required source receipt fields
4. known gap enum and no-hit semantics
5. CSV aggregate-only allowlist and reject codes
6. billing metadata and cost preview/cap rules
7. public page and OpenAPI/MCP drift expectations
8. release blocker taxonomy

この固定がないままAWSで大量生成すると、あとで生成物のschema driftを直すだけの作業になる。

### Step B: AWS-F0 pilot

目的は spend ではなく contract-to-artifact の smoke。

Required pilot outputs:

- 1 source familyの `source_profile` / `source_document` / `source_receipt`
- 1 positive receipt と 1 no-hit receipt
- 1 P0 packet example draft
- 1 proof page candidate
- 1 synthetic CSV fixture and leak scan
- 1 GEO smoke report
- cost tag and stop ledger

Pilot gate:

- source receipt required fields欠損はknown gap化される
- no-hit が absence claim に変換されない
- raw/private CSV values が成果物・ログ・fixtureにない
- packet example validates against contract
- stop command/queue disable手順が空queueで確認済み

### Step C: AWS-F1/F2 useful run

投入順は product backlog の依存関係に合わせる。

1. P0 official source profile/source document/source receipt
2. claim graph/no-hit/freshness/known gap QA
3. six P0 packet examples
4. proof pages and source receipt ledger examples
5. CSV synthetic fixture matrix and leak scan
6. OpenAPI/MCP/llms/.well-known discovery assets
7. GEO 100+ regression and forbidden claim scan
8. P1/P2 source expansion and generated library candidates

P0 release evidenceが不足している間は、P2 broad generationやpartner/international/marketplace assetsに進まない。

### Step D: AWS-F3 drain and handoff

AWS終了時に残すもの。

| Handoff bucket | Contents |
|---|---|
| P0 implementation input | schemas, packet examples, receipt fixtures, CSV fixtures, OpenAPI/MCP examples |
| P0 release evidence | leak scans, forbidden-claim scans, receipt completeness, GEO scorecard, drift reports |
| P1 backlog input | source expansion backlog, provider alias variants, algorithm fixtures, proof UX candidates |
| P2 backlog input | large generation candidates, marketplace/i18n/partner checklists |
| Operator ledger | gross burn, paid exposure, resource manifest, cleanup status |

残してはいけないもの:

- running compute
- public S3 bucket
- unreviewed public sync
- raw CSV or private row-level material
- unbounded OpenSearch/ECS/NAT/Glue resources
- release-gate未通過のpublic discovery changes

## 5. Release gate integration

AWS成果物をP0 releaseへ入れるには、通常のP0 release gateに次を追加する。

| Gate | Block condition |
|---|---|
| Contract drift | AWS-generated packet/example/proof/OpenAPI/MCP asset が catalog正本と不一致 |
| Receipt completeness | public claim に receipt も known gap もない |
| No-hit safety | no-hitを「問題なし」「不存在」「安全」に変換している |
| CSV privacy | raw/private CSV value、row-level再構成可能値、real customer-like valueが出る |
| Billing/cost | batch/CSV/fanoutが preview/cap/idempotency なしでbillable扱い |
| GEO forbidden claim | legal/tax/audit/credit/grant guarantee、free unlimited、complete real-time coverage等のforbidden claimが1件でもある |
| Public boundary | private overlay、internal QA、unreviewed artifact が public site/discovery/JSON-LD へ混入 |
| AWS cleanup | spend-heavy resource が停止されていない、または final ledger がない |

AWS cost ledger は product releaseの十分条件ではない。安く安全に走っても、packet/source/CSV/GEO gatesを満たさなければ公開しない。

## 6. Recommended backlog insertions

### P0 additions

既存P0 epicを増やさず、各epicのacceptanceにAWS成果物を接続する。

| Add to | Item |
|---|---|
| P0-E2 | AWS-generated source receipt fixtures must pass claim graph/no-hit/license/freshness tests before composer use |
| P0-E4 | AWS-generated CSV fixtures are synthetic/header-only/redacted and included in leak scan corpus |
| P0-E5 | Six P0 public examples can be generated offline, but composer tests decide acceptance |
| P0-E8 | Proof/discovery pages generated from AWS artifacts remain private candidates until release scan passes |
| P0-E9 | Release gate includes AWS artifact manifest, cleanup ledger, cost ledger, and public/private boundary scan |

### P1 additions

| Add to | Item |
|---|---|
| P1-E2 | Use AWS source expansion outputs as reviewed backlog, not direct ingestion |
| P1-E4 | Promote provider alias variants only after synthetic fixture tests and privacy review |
| P1-E6 | Use proof page prototypes to improve UX after P0 proof fields stabilize |
| P1-E9 | Treat AWS GEO reports as baseline seed; keep weekly regression independent of AWS |

### P2 additions

| Add to | Item |
|---|---|
| P2-E1 | Large generated packet/proof libraries require same receipt/gap/drift gates as six P0 examples |
| P2-E5 | Parser/source automation must create gaps before stale claims leak |
| P2-E7 | Partner-like fixture research does not imply approved partner integration or OAuth scope |

## 7. Final integrated priority

If capacity or credit window is constrained, spend only on this narrow order:

1. P0 source receipt foundation for the six packet examples.
2. CSV synthetic fixture and privacy leak scan corpus.
3. Six P0 packet examples plus source receipt ledger/proof pages.
4. OpenAPI/MCP/discovery examples that point to the same packet catalog.
5. GEO P0 regression and forbidden-claim reports.
6. Cost/cleanup/final AWS ledger.

Defer everything else. In particular, do not use AWS credit to broaden packet taxonomy, run generalized load tests, create VC/demo collateral, build long-lived infrastructure, or generate public pages at scale before P0 receipt/privacy/billing/GEO gates pass.

## 8. Non-goals

- Do not implement code from this document.
- Do not execute AWS CLI or create AWS resources from this document.
- Do not change P0 packet schema, pricing, CSV retention, or release thresholds inside AWS runbooks.
- Do not let AWS queue phase labels override backlog P0/P1/P2 priority.
- Do not publish AWS-generated artifacts without P0 release gate review.
- Do not treat credit consumption as evidence of product readiness.
