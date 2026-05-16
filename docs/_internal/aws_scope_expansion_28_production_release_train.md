# AWS scope expansion 28: production release train

担当: 拡張深掘り 28/30 / 本番デプロイ短縮・release train  
対象: jpcite 本体P0計画、AWS credit run成果物、production release、GEO-first agent discovery  
作成日: 2026-05-15  
AWS前提: profile `bookyou-recovery`, account `993693061769`, default region `us-east-1`  
この文書ではAWS CLI/APIコマンドを実行しない。AWSは短期の成果物工場として扱い、production runtimeには残さない。

## 0. Executive summary

本番デプロイを早める正しい順番は、AWS全量成果物の完了を待つことではない。

正しいrelease trainは次の通り。

1. 本体P0 contractを先に固定する。
2. AWS成果物は `release_candidate=true` の小さなbundleへ切り出す。
3. RC1は3 packet + static proof pages + minimal MCP/APIでproductionへ早く出す。
4. RC2は売れる業務packetと広いsource familyを追加する。
5. RC3はCSV overlay、制度/業法/地域/統計/判例/標準/認証まで広げる。
6. AWSはCodex/Claudeのrate limitに依存せず自走し、成果物を小分けにexportする。
7. productionはAWS S3/Batch/OpenSearch/Glue/Athenaを読まない。
8. AWS credit消化後はartifactを外へ退避し、zero-bill teardownする。

最短で価値を出すには、static proof pagesを先行公開し、MCP/APIは小さいfacadeだけ公開する。

RC1は「完成版」ではなく「AI agentが推薦できる最小の有料導線」である。

## 1. Release trainの基本思想

### 1.1 なぜAWS全量を待たないか

AWS credit runは巨大な収集・抽出・検証・評価の並列処理になる。

全量完了を待つと、次の失敗が起こる。

- artifact量が大きすぎてreviewが詰まる。
- production importの差分が巨大化する。
- proof pages、OpenAPI、MCP、pricing、billing metadataの整合確認が遅れる。
- AWS creditは消化できても、ユーザーが触れるsurfaceが遅れる。
- deployment riskが一度に膨らむ。

したがってproductionは小さいbundleを順番に出す。

### 1.2 AWS成果物の扱い

AWSで作るものはproduction inputの候補であり、直接production source of truthではない。

AWSからproductionへ入れてよいもの:

- validated packet fixtures
- source profile registry candidates
- source receipts
- claim refs
- known gaps
- no-hit ledgers
- public proof page input
- OpenAPI/MCP examples
- GEO eval reports
- pricing/cost preview examples
- safe synthetic/header-only CSV fixtures
- release evidence manifests

AWSからproductionへ入れてはいけないもの:

- raw source lake
- raw CSV
- private user data
- AWS log
- crawler HAR with sensitive data
- unreviewed screenshots
- bulk parquet as runtime dependency
- OpenSearch index as production dependency
- S3 URL embedded in production runtime
- Bedrock/Textract intermediate output without source receipt validation

### 1.3 productionの役割

productionは次を公開する。

- AI agentが読むproof pages
- `llms.txt`
- `.well-known` discovery files
- small OpenAPI
- P0 MCP facade
- cost preview
- API key / MCP setup path
- capped paid packet execution
- no-hit caveat
- source receipt / known gapを含むoutput

productionは次をしない。

- request-time LLMで公的事実を生成しない。
- AWS batch jobを直接呼ばない。
- AWS S3をruntime sourceにしない。
- no-hitを安全証明にしない。
- CSV raw dataを保存しない。

## 2. Master sequence

全体順序は以下で固定する。

| Order | Stage | Owner lane | Goal | Production impact |
|---:|---|---|---|---|
| 0 | Contract freeze | Core repo | packet/output契約を固定 | なし |
| 1 | Feature flag skeleton | Core repo | RCごとのon/offを用意 | hidden |
| 2 | Static proof renderer | Core repo | fixtureから公開pageを生成 | staging only |
| 3 | AWS guardrails | AWS lane | budget/stopline/role/tag/cleanup前提 | production非依存 |
| 4 | AWS canary export | AWS lane | 小さなvalidated artifactを作る | RC1候補 |
| 5 | RC1 import | Core repo | 3 packet bundleをrepoへ入れる | staging |
| 6 | RC1 staging | Deploy lane | proof/MCP/API/cost previewを確認 | staging |
| 7 | RC1 production | Deploy lane | 最小公開 | production |
| 8 | AWS standard/stretch | AWS lane | 公的一次情報を拡張 | RC2/RC3候補 |
| 9 | RC2 import/deploy | Core + deploy | 売れる業務packetを追加 | production incremental |
| 10 | RC3 import/deploy | Core + deploy | 広域sourceとCSV overlayを追加 | production incremental |
| 11 | Final export | AWS lane | durable artifactsをAWS外へ退避 | production非依存 |
| 12 | Zero-bill teardown | AWS lane | 請求が残らない状態へ | production非依存 |
| 13 | Post-teardown checks | Ops lane | 翌日/3日後/月末後の残課金確認 | production監視のみ |

## 3. Contract freeze

### 3.1 Freezeするcontract

RC1前に固定する最小contract:

- `packet_id`
- `packet_version`
- `catalog_version`
- `source_receipts[]`
- `claim_refs[]`
- `known_gaps[]`
- `no_hit_checks[]`
- `billing_metadata`
- `request_time_llm_call_performed`
- `human_review_required`
- `_disclaimer`
- `algorithm_trace`
- `artifact_manifest_ref`
- `release_candidate`

### 3.2 Freezeしないもの

RC1時点で完全固定しなくてよいもの:

- 全packet種類
- 全MCP tools
- full OpenAPI
- full source registry
- CSV overlay paid execution
- industry-specific scoring weights
- all proof pages

### 3.3 Contract blocker

RC1前に1つでもあると止める。

- `request_time_llm_call_performed=false` が強制されていない。
- no-hitの文言が「不存在」「安全」「問題なし」に寄っている。
- `source_receipts[]` が空でもpaid outputになってしまう。
- billing metadataがAPI/MCP/proof pageで食い違う。
- public proof pageにprivate dataが混ざる可能性がある。
- AWS artifactをproduction runtimeが直接読む。

## 4. Feature flags

### 4.1 Flag namespace

productionを小さく出すため、機能はflagで分ける。

推奨namespace:

- `proof_pages.static.enabled`
- `proof_pages.packet.evidence_answer.enabled`
- `proof_pages.packet.source_receipt_ledger.enabled`
- `proof_pages.packet.agent_routing_decision.enabled`
- `api.packet.preview_cost.enabled`
- `api.packet.route.enabled`
- `api.packet.evidence_answer.enabled`
- `api.packet.source_receipt_ledger.enabled`
- `api.packet.agent_routing_decision.enabled`
- `mcp.agent_first.enabled`
- `mcp.full_catalog.visible`
- `billing.paid_execution.enabled`
- `billing.free_preview.enabled`
- `csv_overlay.preview.enabled`
- `csv_overlay.paid.enabled`
- `aws_import.rc1.enabled`
- `aws_import.rc2.enabled`
- `aws_import.rc3.enabled`
- `verticals.grants.enabled`
- `verticals.vendor_risk.enabled`
- `verticals.permits.enabled`
- `verticals.reg_change.enabled`
- `verticals.tax_labor.enabled`
- `verticals.local_government.enabled`
- `runtime.aws_dependency.allowed`

`runtime.aws_dependency.allowed` はproductionでは常にfalseにする。

### 4.2 RCごとのflag状態

| Flag | RC1 | RC2 | RC3 |
|---|---:|---:|---:|
| `proof_pages.static.enabled` | on | on | on |
| `api.packet.preview_cost.enabled` | on | on | on |
| `api.packet.route.enabled` | on | on | on |
| `api.packet.evidence_answer.enabled` | on | on | on |
| `api.packet.source_receipt_ledger.enabled` | on | on | on |
| `api.packet.agent_routing_decision.enabled` | on | on | on |
| `mcp.agent_first.enabled` | on | on | on |
| `mcp.full_catalog.visible` | off | expert-link | expert-link |
| `billing.free_preview.enabled` | on | on | on |
| `billing.paid_execution.enabled` | limited | on | on |
| `csv_overlay.preview.enabled` | off | limited | on |
| `csv_overlay.paid.enabled` | off | off/limited | limited/on |
| `verticals.grants.enabled` | off | on | on |
| `verticals.vendor_risk.enabled` | off | on | on |
| `verticals.permits.enabled` | off | on | on |
| `verticals.reg_change.enabled` | off | limited | on |
| `verticals.tax_labor.enabled` | off | limited | on |
| `verticals.local_government.enabled` | off | limited | on |
| `runtime.aws_dependency.allowed` | off | off | off |

### 4.3 Flag kill switches

必須kill switch:

- all paid execution off
- all MCP paid tools off
- CSV overlay off
- vertical packets off
- new AWS-imported bundle off
- proof page new set off
- cost preview fallback only
- API read-only preview mode

kill switchはdeploy rollbackより速く効く必要がある。

## 5. Static proof pages first

### 5.1 先に出す理由

GEO-firstでは、AI agentがまず読むのは人間営業資料ではなく、公開された高密度の根拠面である。

static proof pagesを先行する理由:

- production runtime riskが低い。
- 課金前に価値を説明できる。
- AI agentが推薦文を作りやすい。
- MCP/APIが小さくても導線が成立する。
- rollbackが簡単。
- AWS teardown後も残る。

### 5.2 RC1 proof page set

RC1で出すpage:

| Page | Purpose | Required content |
|---|---|---|
| `/proof/evidence-answer` | source-backed answerの価値説明 | example output, source_receipts, known_gaps, no-hit caveat, cost preview |
| `/proof/source-receipt-ledger` | 証跡台帳の価値説明 | receipt fields, fetch time, source family, checksum, limitations |
| `/proof/agent-routing-decision` | AI agentが買うべきpacketを判断する例 | route reason, free preview, paid cap, MCP/API path |
| `/packets` | packet catalog | 3 packet only, status, price, fields |
| `/pricing` | agent-readable pricing | unit price, cap, free preview, no charge states |
| `/docs/agents` | AI agent向け説明 | when to use, when not to use, setup |
| `/llms.txt` | machine-readable discovery | proof, pricing, OpenAPI, MCP, packet links |
| `/.well-known/jpcite.json` | canonical discovery | catalog hash, API, MCP, pricing, proof URLs |

### 5.3 Page content rule

proof pageはLPではない。

各pageに必ず入れる:

- packet name
- exact use case
- output example
- source family
- `source_receipts[]`の抜粋
- `claim_refs[]`の抜粋
- `known_gaps[]`
- no-hit caveat
- cost preview
- MCP tool name
- OpenAPI operation
- setup CTA
- last generated timestamp
- catalog version
- artifact manifest checksum

入れてはいけない:

- 「AIが調査済みなので安心」
- 「存在しないことを証明」
- 「公的機関が保証」
- 「審査済み企業」
- 「補助金に必ず通る」
- 「許認可不要」
- raw CSV例
- private company data without consent

### 5.4 Screenshot receipt handling

AWS Playwrightで作ったscreenshot receiptはproof pageに使える。

ただしRC1では次の条件を満たすものだけ。

- width <= 1600px
- public page
- no login
- no CAPTCHA bypass
- no personal data requiring suppression
- source URL and fetched_at available
- image checksum available
- text extraction or OCR result has claim_refs
- terms/robots check passed or manually marked allowed

RC1 proof pageではscreenshotを「見た目の補助」に留め、claimの根拠はDOM/PDF/text receiptに置く。

## 6. MCP/API minimal public surface

### 6.1 RC1 minimal API

RC1のAPIは小さくする。

必須:

- route packet
- preview cost
- get packet catalog
- get proof metadata
- execute `evidence_answer`
- execute `source_receipt_ledger`
- execute `agent_routing_decision`

任意:

- get source family summary
- get artifact manifest
- get no-hit explanation

出さない:

- full 155 tools as default
- raw search endpoint
- raw source lake endpoint
- arbitrary scrape endpoint
- CSV paid execution
- unsupported vertical decision endpoint

### 6.2 RC1 minimal MCP

RC1 MCP toolは10本以下に抑える。

推奨:

| Tool | Charge | Role |
|---|---:|---|
| `jpcite_route` | free | ユーザー意図をpacketへ振り分ける |
| `jpcite_preview_cost` | free | 実行前に価格・上限・no-charge条件を返す |
| `jpcite_get_packet_catalog` | free | agent-first catalogを返す |
| `jpcite_get_proof` | free | proof page metadataを返す |
| `jpcite_evidence_answer` | paid/capped | source-backed answer |
| `jpcite_source_receipt_ledger` | paid/capped | receipt ledger |
| `jpcite_agent_routing_decision` | paid/capped | packet選択理由 |
| `jpcite_explain_no_hit` | free | no-hit caveat説明 |

RC1 MCP outputはREST packetと同じcontractにする。

### 6.3 Agent-facing wording

AI agentがエンドユーザーへ説明する文面は、短く具体的にする。

推奨:

> jpcite can return a source-linked packet for Japanese public information. It is useful when you need URLs, fetched timestamps, claim-to-source links, known gaps, no-hit caveats, and a cost preview before paid execution.

禁止:

> jpcite proves whether a company is safe.

> jpcite can replace legal/accounting review.

> jpcite has checked every official source.

### 6.4 Full catalog exposure

既存155 MCP toolsやfull OpenAPIは消さない。

ただしRC1では:

- defaultには出さない。
- expert linkに退避する。
- agent-first catalogを先に出す。
- full catalogはdrift test対象にする。

## 7. RC1

### 7.1 RC1 goal

RC1の目的は、AI agentがjpciteを発見し、価値を理解し、free previewからMCP/API課金へ進める最小動線をproductionに出すこと。

RC1は売上の最初の面を作る。

### 7.2 RC1 scope

RC1 packet:

1. `evidence_answer`
2. `source_receipt_ledger`
3. `agent_routing_decision`

RC1 source families:

- NTA法人番号
- NTAインボイス
- e-Gov法令
- gBizINFO minimal
- J-Grants minimal
- e-Stat minimal

RC1 public surfaces:

- static proof pages
- packet catalog
- pricing page
- agent docs
- `llms.txt`
- `.well-known/jpcite.json`
- small OpenAPI
- P0 MCP manifest
- API key / MCP setup path

RC1 not included:

- CSV upload production execution
- broad local government coverage
- full industry permit engine
- legal-change alert subscription
- vendor risk score production claim
- OpenSearch-backed runtime search
- AWS-hosted production dependency

### 7.3 RC1 bundle content

RC1 import bundle must include:

- `run_manifest.json`
- `artifact_manifest.json`
- `dataset_manifest.json`
- packet fixtures
- proof page inputs
- source receipt samples
- no-hit sample cases
- known gap examples
- pricing examples
- MCP examples
- OpenAPI examples
- GEO eval smoke report
- private leak scan report
- checksum file

### 7.4 RC1 gates

RC1 Go条件:

- Contract gate pass
- Source receipt completeness gate pass
- No-hit wording gate pass
- Private leak scan pass
- Billing metadata parity pass
- API/MCP parity pass
- Proof page render pass
- GEO smoke pass
- Rollback path ready
- Production has no AWS runtime dependency

RC1 No-Go条件:

- `source_receipts[]`が空のpaid exampleがある。
- `known_gaps[]`が欠落している。
- no-hitを安全・不存在・保証として説明している。
- proof pageにprivate dataが混ざる。
- priceがpage/API/MCPで食い違う。
- production startupがAWS S3へ接続する。
- rollback image or previous manifestがない。
- feature flag kill switchが効かない。

### 7.5 RC1 deployment order

RC1は次の順番で出す。

1. Contract freeze branchを作る。
2. Feature flagsをhiddenで入れる。
3. Static proof rendererを入れる。
4. RC1 AWS artifact bundleをimportする。
5. Fixture validatorを通す。
6. Proof pagesをstagingで生成する。
7. Small OpenAPIを生成する。
8. P0 MCP manifestを生成する。
9. `llms.txt`と`.well-known`を生成する。
10. Cost previewをstagingで確認する。
11. Billing capをstagingで確認する。
12. GEO smokeをstagingで確認する。
13. Production deploy targetを確認する。
14. Productionへstatic proof pagesを先に出す。
15. Productionでfree controlsをonにする。
16. Paid packetをlimited capでonにする。
17. MCP manifestをproduction discoveryへ出す。
18. Post deploy smokeを走らせる。
19. 24時間monitoring windowを置く。
20. RC2 import準備へ進む。

### 7.6 RC1 rollout

RC1 rolloutは段階化する。

| Step | Traffic / exposure | What turns on |
|---:|---|---|
| 1 | internal only | proof pages hidden URL |
| 2 | staging | all RC1 surfaces |
| 3 | production public static | proof pages, pricing, docs |
| 4 | production free controls | route, cost preview, catalog |
| 5 | production limited paid | 3 packet, low cap |
| 6 | production MCP discovery | P0 MCP manifest |
| 7 | production GEO | sitemap/llms/.well-known stable |

Paid executionはstatic proof pagesより後。

### 7.7 RC1 monitoring

RC1で見るもの:

- proof page 200 rate
- proof page render errors
- OpenAPI fetch errors
- MCP manifest fetch errors
- route tool success rate
- cost preview success rate
- paid packet success rate
- no-charge states
- billing cap enforcement
- source receipt presence rate
- known gap presence rate
- no-hit misuse detection
- private leak scan regression
- agent crawler access to `llms.txt` and `.well-known`
- API latency
- error budget
- rollback readiness

### 7.8 RC1 rollback

rollback優先順:

1. Turn off paid packet flags.
2. Turn off MCP paid tools.
3. Leave free proof pages if accurate.
4. If proof page is wrong, remove new proof page set.
5. Revert `.well-known` catalog hash to previous version.
6. Revert small OpenAPI if operation mismatch exists.
7. Revert deployment image only if runtime/API is broken.
8. Keep AWS running unless AWS itself caused cost/safety incident.

RC1 rollback should not require AWS access.

## 8. RC2

### 8.1 RC2 goal

RC2の目的は、AI agentが「実務で買う理由」を説明できる成果物を増やすこと。

RC2は売上候補を増やすreleaseである。

### 8.2 RC2 packet additions

優先追加:

- `grant_candidate_shortlist`
- `procurement_opportunity_radar`
- `invoice_vendor_public_check`
- `vendor_public_evidence_packet`
- `permit_requirement_check`
- `administrative_action_check`
- `reg_change_impact_brief`

RC2 source expansion:

- J-Grants
- ミラサポplus
- 調達ポータル
- gBizINFO expanded
- EDINET metadata
- 国交省ネガティブ情報
- 金融庁登録/処分
- 消費者庁処分
- 官報/公告 minimal
- 自治体補助金 selected
- e-Govパブコメ selected

### 8.3 RC2 proof pages

RC2で追加するproof pages:

- `/proof/grant-candidate-shortlist`
- `/proof/procurement-opportunity-radar`
- `/proof/vendor-public-evidence`
- `/proof/permit-requirement-check`
- `/proof/reg-change-impact-brief`
- `/proof/admin-action-check`

RC2のproof pageは「売れる成果物」を中心にする。

### 8.4 RC2 feature flags

RC2はpacketごとにflagを分ける。

- `verticals.grants.enabled`
- `verticals.procurement.enabled`
- `verticals.vendor_risk.enabled`
- `verticals.permits.enabled`
- `verticals.reg_change.enabled`
- `proof_pages.rc2.enabled`
- `mcp.rc2_tools.enabled`
- `api.rc2_packets.enabled`

### 8.5 RC2 release order

RC2は一括にしない。

推奨順:

1. Grants/procurement proof pages
2. Grants/procurement API preview
3. Grants/procurement paid packet
4. Vendor public evidence proof page
5. Vendor public evidence API/MCP
6. Permit requirement proof page
7. Permit requirement limited paid
8. Reg change proof page
9. Reg change limited paid
10. MCP catalog update
11. GEO eval update
12. pricing/bundle update

### 8.6 RC2 gates

RC2 Go条件:

- RC1 metrics stable.
- RC2 artifact bundle has manifest.
- Each new packet has proof page.
- Each new packet has no-hit caveat.
- Each new packet has cost preview.
- Each new source family has license/terms ledger.
- Public screenshot receipts are sanitized.
- Algorithm trace exists for eligibility/risk/permit/reg-change outputs.

RC2 No-Go条件:

- risk scoreが「信用力」「安全性」へ見える。
- grant matchが「採択可能性保証」に見える。
- permit checkが「許認可不要」へ見える。
- legal/reg change briefが「法的助言」に見える。
- no-hitを処分なしの証明として扱う。

## 9. RC3

### 9.1 RC3 goal

RC3の目的は、広い公的一次情報とprivate overlay previewを組み合わせ、反復利用される成果物へ広げること。

RC3は継続利用と単価向上のreleaseである。

### 9.2 RC3 additions

RC3 packet候補:

- `csv_monthly_public_overlay_review`
- `csv_grant_match_packet`
- `tax_labor_event_radar`
- `local_government_requirement_packet`
- `industry_compliance_watch`
- `court_dispute_enforcement_check`
- `standards_certification_requirement_check`
- `geo_stat_market_context_packet`
- `food_labeling_compliance_packet`
- `privacy_personal_info_rule_check`

RC3 source expansion:

- 国税庁 tax guidance pages
- eLTAX public info
- 日本年金機構
- 厚労省 労働/助成金/最低賃金
- 自治体制度/条例/許認可
- 裁判所判例
- 公取委審決
- 中労委
- JISC/JIS
- 技適/PSE/PSC
- 食品表示/消費者庁
- 医療/介護情報
- 統計GIS/国土地理院/国土数値情報
- 不動産情報ライブラリ
- PLATEAU selected

### 9.3 CSV overlay position

RC3でCSV overlayを入れる場合も、raw CSVは保存しない。

許可:

- header detection
- local parse
- derived aggregate facts
- suppressed small groups
- synthetic examples
- redacted fixtures
- formula injection defense
- public source join candidate

禁止:

- raw CSV upload to AWS
- raw CSV persistence
- raw CSV logging
- row-level public proof page
- user private facts in GEO pages

### 9.4 RC3 release order

RC3はprivate overlayを最後にする。

推奨順:

1. Local government proof pages
2. Tax/labor public calendar proof pages
3. Standards/certification proof pages
4. Courts/enforcement proof pages
5. Geo/stat context proof pages
6. Algorithm traces for above
7. API preview tools
8. MCP default catalog refresh
9. CSV overlay preview local-only
10. CSV overlay paid limited
11. Pricing bundles
12. Agent recommendation examples
13. GEO eval expansion
14. Post-release monitoring

### 9.5 RC3 gates

RC3 Go条件:

- RC1/RC2 rollback path remains intact.
- CSV privacy test pass.
- formula injection test pass.
- suppression test pass.
- public/private boundary test pass.
- law/regulation/permit outputs use three-valued logic.
- risk outputs include evidence quality and coverage gap.
- screenshot capture terms/robots ledger complete.
- all new proof pages have source receipts and known gaps.

RC3 No-Go条件:

- private user facts appear in public page.
- algorithm output lacks trace.
- permit/legal/tax/labor output appears as professional advice.
- `known_gaps[]` omitted to improve conversion.
- source update date/fetched_at missing.

## 10. Parallel AWS lane while deploying

### 10.1 AWS自走要件

Codex/Claude Codeのrate limitで止まらないよう、AWS側は承認済みjob graphとして動く必要がある。

AWS lane requirements:

- jobs are defined before launch
- budgets and stoplines configured
- tags enforced
- queue priority fixed
- canary before full
- standard run before stretch
- artifact manifests generated per run
- cost/artifact ledger updated automatically
- kill switch available
- no production dependency
- export checkpoint at least daily

### 10.2 Production deployとの並走

RC1 production中もAWSは次を続けてよい。

- public source acquisition
- OCR/Textract pilot for public documents
- Playwright screenshot receipt generation
- Bedrock batch classification for public text only
- OpenSearch retrieval benchmark as temporary benchmark only
- proof page scale generation
- GEO eval expansion
- artifact packaging/checksum/export

ただしproductionはAWSを読まない。

### 10.3 AWS outputs release slicing

AWS成果物は次の単位で切る。

- `rc1-core`
- `rc2-grants-procurement`
- `rc2-vendor-risk`
- `rc2-permits`
- `rc2-reg-change`
- `rc3-tax-labor`
- `rc3-local-government`
- `rc3-courts-enforcement`
- `rc3-standards-certifications`
- `rc3-geo-stat`
- `rc3-csv-overlay-synthetic`

各sliceは独立してimport、test、rollbackできること。

## 11. Import discipline

### 11.1 Import lanes

AWS artifact importはlane分けする。

| Lane | Data | Repo destination | Risk |
|---|---|---|---|
| A | manifests | internal/release evidence | low |
| B | packet fixtures | test/data fixtures | medium |
| C | source receipts | data source registry candidates | medium |
| D | proof page inputs | static generation input | medium |
| E | OpenAPI/MCP examples | docs/generated or spec tests | medium |
| F | pricing examples | pricing tests/docs | medium |
| G | CSV synthetic fixtures | privacy tests only | high |
| H | broad corpus stats | internal reports | low |

### 11.2 Import validation

各importで必須:

- checksum verification
- manifest schema validation
- source URL validation
- fetched_at validation
- no private data scan
- license/terms ledger check
- no-hit wording scan
- billing metadata check
- packet schema check
- proof render check
- API/MCP parity check

### 11.3 Import rejection

拒否するartifact:

- manifestなし
- checksumなし
- source URLなし
- raw private data入り
- terms unclear but public page candidate
- screenshot only with no text receipt
- claim_refs not resolvable
- no-hit unsafe wording
- generated output without `request_time_llm_call_performed=false`
- production dependency on AWS URL

## 12. Deployment target discipline

### 12.1 Existing ambiguity

既存計画ではproduction targetとして `autonomath-api` と `jpcite-api` が混在する可能性がある。

このrelease trainでは次で固定する。

- current production SOT: existing production workflow / app
- `jpcite-api`: parallel lane or explicit cutover target
- DNS/API cutover: RC1とは別承認

### 12.2 RC1 target decision

RC1ではproduction target変更を避ける。

理由:

- artifact importとtarget cutoverを同時にすると原因分離できない。
- rollbackが複雑になる。
- AWS credit runの目的はartifact factoryでありproduction infra移行ではない。

### 12.3 Cutover timing

`jpcite-api` cutoverを行うならRC1安定後。

推奨:

- RC1 production stable for 24-48h
- RC2 static proof pages stable
- API/MCP drift tests pass
- rollback route documented
- DNS TTL and previous endpoint fallback confirmed

## 13. Rollout policy

### 13.1 Rollout units

rollout単位:

- static proof page set
- free control API
- paid packet API
- MCP manifest
- pricing change
- packet catalog change
- vertical packet group
- CSV overlay preview
- CSV overlay paid

### 13.2 Exposure order

必ず次の順番で露出する。

1. internal preview
2. staging public-like
3. production static only
4. production free controls
5. production paid limited
6. production MCP discovery
7. production GEO index surfaces
8. production bundle pricing

GEO index surfacesは最後に近い。

理由: AI agents/search enginesが古い/間違った情報を拾うと修正に時間がかかる。

### 13.3 Paid execution cap

RC1 paid cap:

- per request cap low
- per key daily cap low
- no automatic retry charges
- idempotency required
- free preview first
- no-charge on validation failure

RC2/RC3でcapを広げる。

## 14. Rollback

### 14.1 Rollback levels

| Level | Trigger | Action |
|---:|---|---|
| L1 | single packet bug | packet flag off |
| L2 | MCP mismatch | MCP manifest rollback |
| L3 | API mismatch | route/payed API flag off |
| L4 | proof page issue | affected static page set rollback |
| L5 | billing issue | all paid execution off |
| L6 | privacy issue | all new pages/tools off, incident review |
| L7 | deploy runtime issue | deployment image rollback |
| L8 | AWS cost incident | AWS kill switch and no-new-work |

### 14.2 Rollback assets

常に保持:

- previous packet catalog
- previous OpenAPI
- previous MCP manifest
- previous `.well-known`
- previous `llms.txt`
- previous proof page set
- previous deploy image
- previous DB snapshot if any
- previous feature flag state

AWS teardown前にproduction rollback assetsがAWS外にあることを確認する。

### 14.3 Rollback must not depend on AWS

rollbackにAWS S3 artifact fetchを要求してはいけない。

理由:

- zero-bill teardown後に使えない。
- credit expiration後の緊急rollbackで請求が走る。
- productionの独立性が崩れる。

## 15. Monitoring

### 15.1 Release health

見る指標:

- deploy success
- 5xx rate
- 4xx validation rate
- p95 latency
- packet execution success
- route success
- cost preview success
- MCP manifest fetch success
- OpenAPI fetch success
- proof page render success
- proof page broken links
- `llms.txt` fetch success
- `.well-known` fetch success

### 15.2 Evidence health

見る指標:

- source receipt presence rate
- claim_refs resolution rate
- known_gaps presence rate
- no-hit caveat presence rate
- artifact manifest checksum match
- source URL reachability
- fetched_at freshness
- source family coverage
- screenshot receipt validation
- OCR confidence distribution

### 15.3 Billing health

見る指標:

- free preview count
- paid execution count
- no-charge validation failure count
- cap hit count
- duplicate idempotency prevention
- unexpected paid event count
- billing metadata parity
- refund/void candidate count

### 15.4 Privacy/safety health

見る指標:

- private leak scan result
- CSV raw persistence scan
- formula injection detection
- small group suppression
- public/private boundary failures
- forbidden phrase detection
- no-hit unsafe wording

### 15.5 GEO health

見る指標:

- proof pages indexed/fetched
- `llms.txt` fetched
- `.well-known` fetched
- agent route accuracy eval
- agent pricing explanation eval
- agent no-hit caveat preservation eval
- agent setup recommendation eval
- broken citation rate

## 16. Zero-bill teardown sequence

### 16.1 Principle

AWS creditを使い切った後、AWSに継続請求を残さない。

productionがAWS非依存ならzero-bill teardownは安全に実行できる。

### 16.2 Before teardown

teardown前に完了すること:

- final artifact export
- checksum verification
- manifest archive outside AWS
- production RC bundle imported
- rollback assets outside AWS
- cost/artifact ledger exported
- zero-bill cleanup checklist ready
- pending jobs drained or stopped
- no production AWS dependency confirmed

### 16.3 Teardown order

削除順:

1. Stop new job submission.
2. Drain/stop Batch queues.
3. Stop ECS/Fargate tasks.
4. Terminate EC2/Spot workers.
5. Delete OpenSearch benchmark domains.
6. Delete temporary Textract/Bedrock output buckets after export.
7. Delete Glue crawlers/jobs/databases/tables created for run.
8. Delete Athena outputs/workgroups created for run.
9. Delete ECR images/repositories created for run.
10. Delete CloudWatch log groups/alarms/dashboards created for run.
11. Delete Step Functions/Lambda created for run.
12. Delete NAT gateways if any.
13. Release unattached EIPs.
14. Delete load balancers/target groups if any.
15. Delete ENIs/security groups/VPC endpoints created for run.
16. Delete S3 objects and buckets created for run if zero ongoing bill is mandatory.
17. Remove temporary IAM roles/policies after verification.
18. Keep only cost/billing access needed for post-checks.

### 16.4 Post-teardown checks

必須:

- immediate resource inventory
- next-day billing check
- 3-day billing check
- month-end billing check
- untagged spend check
- storage residual check
- public IPv4/NAT residual check
- CloudWatch Logs residual check
- snapshots/EBS residual check
- OpenSearch residual check
- S3 residual check

## 17. Production deploy and AWS spend coordination

### 17.1 Spend speed vs deploy speed

ユーザー希望は、AWS creditをできるだけ速く有効消化し、本番も早く出すこと。

両立策:

- AWS standard/stretchは速く走らせる。
- production RC1は小さく先に出す。
- AWS成果物は小分けexportする。
- RC2/RC3はimport単位を小さくする。
- spend stoplineは守る。
- productionはAWS非依存にする。

### 17.2 Credit use posture

目標:

- credit valueを最大限artifactへ変える。
- USD 19,493.94の額面ちょうどを狙わない。
- cost reporting lagと非credit対象請求を考慮する。
- absolute safety lineを超えない。
- stretchは手動承認にする。

### 17.3 AWS lane can continue while agents are rate-limited

Codex/Claudeが止まってもAWS側は:

- queued jobs continue
- budget stopline acts independently
- no-new-work policy can trigger
- artifact manifests continue per job
- exports continue per checkpoint

ただし、production deployはreview/gateが必要なので自動で無制限に進めない。

## 18. RC content mapping

### 18.1 RC1 mapping

| Value story | Packet | Source | Surface |
|---|---|---|---|
| 公的一次情報に基づく回答 | `evidence_answer` | NTA/e-Gov/gBizINFO/J-Grants minimal | proof/API/MCP |
| 出典台帳 | `source_receipt_ledger` | same | proof/API/MCP |
| AI agent routing | `agent_routing_decision` | catalog/pricing/proof | proof/API/MCP |

### 18.2 RC2 mapping

| Value story | Packet | Source | Surface |
|---|---|---|---|
| 使える補助金候補 | `grant_candidate_shortlist` | J-Grants/自治体/業種 | proof/API/MCP |
| 入札機会探索 | `procurement_opportunity_radar` | 調達ポータル/JETRO/自治体 | proof/API/MCP |
| 取引先公的確認 | `vendor_public_evidence_packet` | 法人番号/インボイス/gBizINFO/EDINET/処分 | proof/API/MCP |
| 許認可要否の確認準備 | `permit_requirement_check` | e-Gov/所管省庁/自治体 | proof/API/MCP |
| 制度変更影響 | `reg_change_impact_brief` | e-Gov/パブコメ/官報/告示 | proof/API/MCP |

### 18.3 RC3 mapping

| Value story | Packet | Source | Surface |
|---|---|---|---|
| CSVから月次の公的イベント候補 | `csv_monthly_public_overlay_review` | CSV derived facts + tax/labor public sources | API/MCP limited |
| 税労務カレンダー | `tax_labor_event_radar` | NTA/年金機構/厚労省/eLTAX | proof/API/MCP |
| 地域制度・自治体要件 | `local_government_requirement_packet` | 自治体/e-Gov/local ODS | proof/API/MCP |
| 裁判/処分/紛争確認 | `court_dispute_enforcement_check` | 裁判所/JFTC/消費者庁/FSA/MLIT | proof/API/MCP |
| 標準/認証要件 | `standards_certification_requirement_check` | JISC/METI/PPC/NITE/PMDA | proof/API/MCP |
| 地理統計文脈 | `geo_stat_market_context_packet` | e-Stat/GSI/国土数値情報 | proof/API/MCP |

## 19. Release blockers checklist

### 19.1 Always-blockers

- raw CSV persistence
- private data on public page
- request-time LLM public fact generation
- no-hit overclaim
- missing source receipts
- missing known gaps
- missing billing metadata
- API/MCP output mismatch
- proof page source mismatch
- production AWS runtime dependency
- rollback path missing
- zero-bill teardown impossible

### 19.2 RC1-specific blockers

- three core packets unavailable
- proof pages not generated
- pricing page missing
- `llms.txt` missing
- `.well-known` missing
- MCP default exposes full 155 tools
- paid execution without preview/cap

### 19.3 RC2-specific blockers

- grant/permit/vendor outputs overclaim
- source family license/terms unknown
- screenshot receipt unsanitized
- vertical packet lacks algorithm trace
- pricing bundle not reflected in API/MCP

### 19.4 RC3-specific blockers

- CSV privacy unproven
- local government data too stale without known gap
- legal/tax/labor output appears as advice
- standards/certification output appears as certification
- risk score lacks evidence quality and coverage gap

## 20. Final recommended calendar

### Day 0

- Freeze packet contract.
- Add feature flags.
- Add static proof renderer.
- Prepare AWS canary export requirements.

### Day 1

- Import RC1 canary bundle.
- Generate RC1 proof pages in staging.
- Generate small OpenAPI/MCP.
- Run leak/no-hit/billing/parity gates.

### Day 2

- Deploy static proof pages to production.
- Turn on free route/cost preview/catalog.
- Turn on limited paid 3 packet if gates pass.
- Keep AWS standard run moving.

### Day 3-4

- Monitor RC1.
- Import RC2 grants/procurement/vendor-risk slices.
- Add proof pages first, then API/MCP.

### Day 5-7

- Deploy RC2 incrementally.
- Continue AWS stretch for broader official corpus.
- Prepare RC3 public source proof pages.

### Day 8-10

- Deploy RC3 public-source packets.
- Enable CSV overlay preview only after privacy gates.
- Keep paid CSV limited until suppression/leak gates are stable.

### Day 11-14

- Final AWS export.
- Import only reviewed slices.
- Freeze final artifact archive outside AWS.
- Execute zero-bill teardown.
- Run post-teardown billing/resource checks.

## 21. Non-negotiable conclusions

1. RC1はAWS全量を待たない。
2. Static proof pagesを先に出す。
3. MCP/APIは最小facadeから出す。
4. Paid executionはcost previewとcapの後。
5. ProductionはAWS非依存。
6. AWSはrate limitに依存しない自走artifact factory。
7. RC2/RC3は小分けimport、小分けdeploy。
8. CSV overlayはRC3以降、raw保存なし。
9. GEO-firstなので、agent-facing docs/proof/llms/.well-knownが主戦場。
10. Credit消化後はzero-bill teardownを完了する。

このrelease trainを本体計画へマージする場合、実装順は `contract -> flags -> proof renderer -> AWS canary import -> RC1 static proof -> RC1 minimal MCP/API -> RC2 vertical packets -> RC3 overlays/broad corpus -> final export -> zero-bill teardown` で固定する。
