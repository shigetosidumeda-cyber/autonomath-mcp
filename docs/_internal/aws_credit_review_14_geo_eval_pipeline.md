# AWS credit review 14/20: GEO evaluation and AI-agent discovery pipeline

作成日: 2026-05-15  
レビュー枠: AWSクレジット統合計画 追加20エージェントレビュー 14/20  
担当: GEO評価 / AIエージェント発見導線 / 本番デプロイ前後の評価順  
AWS前提: CLI profile `bookyou-recovery` / Account `993693061769` / default region `us-east-1`  
状態: AWS実行前計画のみ。AWS CLI/API実行、AWSリソース作成、デプロイ実行はしない。

## 0. 結論

jpcite の成長導線は SEO-first ではなく **GEO-first** である。人間が検索結果からLPへ来ることは副次効果であり、主戦場は「AIエージェントが日本の公的根拠・出典・鮮度・known gaps を必要とした瞬間に、jpcite の MCP/API を推薦できるか」である。

したがって、AWS credit run の GEO 評価は次を目的にする。

1. AIエージェントが jpcite を「回答生成AI」ではなく「日本公的情報の source-linked evidence packet layer」と理解する。
2. 推薦時に `source_receipts[]`, `known_gaps[]`, `human_review_required`, `request_time_llm_call_performed=false`, `billing_metadata` を落とさない。
3. MCP / REST / OpenAPI / cost preview / API key / cap の導線を正しい順番で案内する。
4. no-hit を absence / safe / no risk / eligible に変換しない。
5. 営業デモではなく、self-serve の pricing preview -> paid API key / MCP setup へ進める。
6. 本番デプロイ前後で、公開ファイル・manifest・OpenAPI・MCP・proof page・pricing page が同じ契約を語っていることを確認する。

AWS は GEO 評価のために公開面の候補、packet examples、proof pages、scorecard、forbidden-claim scan、render/crawl evidence を生成する。AWS 自体は本番提供基盤ではなく、**本体P0実装を安全に本番へ出すための一時的な成果物工場**として扱う。

## 1. このレビューの入力と前提

参照する本体計画:

- `consolidated_implementation_backlog_deepdive_2026-05-15.md`
- `geo_discovery_contract_deepdive_2026-05-15.md`
- `geo_eval_harness_deepdive_2026-05-15.md`
- `p0_geo_first_packets_spec_2026-05-15.md`
- `public_example_packets_deepdive_2026-05-15.md`
- `aws_credit_unified_execution_plan_2026-05-15.md`
- `aws_credit_review_09_queue_sizing_pacing.md`

固定する前提:

- jpcite は request-time LLM を呼んで packet 内容を生成しない。
- packet は `request_time_llm_call_performed=false` を必ず返す。
- public proof / examples は synthetic または public-source backed に限定する。
- private CSV raw row、摘要、相手先名、個人情報、給与、銀行、カード情報は GEO surface に絶対に出さない。
- no-hit は `no_hit_not_absence` であり、不存在・安全・適格・問題なしの証明ではない。
- 価格は `1 billable unit = JPY 3 ex-tax / JPY 3.30 inc-tax` を基準にし、外部LLM・検索・agent runtime・cloud費用は別である。

## 2. 本体計画とAWS計画のマージ順

GEO評価は最後に一回だけ行うものではない。本体P0の各段階へ、AWS成果物を戻しながら進める。

| 順 | 本体P0 | AWS成果物 | GEO評価で見ること | 進んでよい条件 |
|---:|---|---|---|---|
| 1 | P0-E1 packet contract/catalog | J01/J12のschema候補 | packet名、route、tool名、price、proof URLが一つのcatalogに揃うか | catalog drift 0 |
| 2 | P0-E2 receipts/claims/gaps | J01-J04 receipt backbone | source receipts と known gaps が全claimへ残るか | receipt missing が known gap 化される |
| 3 | P0-E3 pricing/cost preview | cost examples / billing metadata | free preview、cap、external cost separation が説明されるか | pricing forbidden 0 |
| 4 | P0-E4 CSV privacy | J14 privacy fixtures | CSV価値を言えるが raw/private を薦めないか | raw CSV leak 0 |
| 5 | P0-E5 packet composers | J15 six P0 examples | agent が実物packetを読んで価値を理解できるか | six packets valid |
| 6 | P0-E6 REST facade | OpenAPI examples | Actions/API利用時にpreview -> execute順になるか | agent-safe spec import pass |
| 7 | P0-E7 MCP tools | MCP manifest examples | Claude/Cursor等が first-call tool を選べるか | route accuracy pass |
| 8 | P0-E8 proof/discovery | J21 proof pages, llms/.well-known | AIが公開面から推薦理由と制約を読めるか | discovery crawl pass |
| 9 | P0-E9 release gates | J16/J20/J23 scorecards | forbidden/no-hit/pricing/route regression がないか | release gate pass |

実行順の要点:

- proof page や llms を先に量産しない。まず catalog と packet contract を固定する。
- OpenAPI/MCP の説明を手書きで増やさない。catalog から生成し、drift test で守る。
- GEO は「jpcite と言及された数」ではなく、safe qualified recommendation を測る。
- 本番デプロイ前に、staging URL で実URL・実Content-Type・実redirect・実robotsを評価する。

## 3. 評価対象の公開surface

P0で評価対象にする surface は以下。

| Surface | Agentが読む目的 | 評価ポイント | Blocker |
|---|---|---|---|
| `robots.txt` | crawlerが辿れるか | `sitemap-llms.xml` が見える、private/ops path はblock | `.well-known` や specs を誤block |
| `sitemap-llms.xml` | 高信号URL集合 | llms, .well-known, OpenAPI, MCP, pricing, proof, examplesを含む | 低品質URL大量混入 |
| `llms.txt` | 最短の推薦判断 | what/when/how/cost/fence/no-hit が1画面で読める | SEO文、曖昧価格、sales CTA |
| `llms-full.txt` | 詳細のagent contract | must-preserve fields、route、do-not-use、examples | 内部計画の長文コピー |
| `.well-known/llms.json` | 機械可読routing | `recommend_when[]`, `do_not_recommend_when[]`, pricing, hashes | proseだけ、hashなし |
| `.well-known/mcp.json` | MCP発見 | manifest URL、auth、recommended first tools、pricing | tool数/名前がdocsと不一致 |
| `.well-known/agents.json` | 汎用agent能力表 | capability map、forbidden claims、must-preserve fields | final judgment を示唆 |
| `.well-known/openapi-discovery.json` | agent-safe OpenAPI発見 | full spec と agent-safe spec の区別 | 古いhost/specへ誘導 |
| `server.json` / `mcp-server.json` | MCP registry | package/transport/auth/price/fence/tool descriptions | demo-first、価格不一致 |
| `openapi.agent.json` | Actions/agent import | operationId、summary、examples、errors、cost preview | receipt/gap例がない |
| packet example JSON | 実物理解 | six P0 packet、receipts/gaps/billing/reviewあり | 成功recordだけの薄い例 |
| proof pages | 引用可能な根拠面 | sample answer、JSON-LD、packet、source ledger、CTA | LP風の抽象説明だけ |
| pricing page | 課金納得 | unit、税込、free preview、cap、external costs | 架空plan、無料無制限 |
| legal/data fence | 安全境界 | no final professional judgment、license/freshness/no-hit | no risk / complete coverage |

## 4. surface別の改善方針

### 4.1 Proof pages

Proof page は「人間向け説明ページ」ではなく、AIが引用してエンドユーザーへ説明できる証拠ページにする。

必須要素:

- packet type、REST route、MCP tool name、pricing unit、public example URL。
- sample input と sample output。
- `source_receipts[]`、`claim_refs[]`、`known_gaps[]`、`quality.human_review_required`。
- `request_time_llm_call_performed=false`。
- no-hit caveat。
- cost preview before paid execution。
- external LLM / agent runtime cost separate。
- professional fence。
- synthetic fixture 表示。
- API/MCP setup CTA。営業デモCTAを主導線にしない。

評価:

- AI回答が proof page を読んだ時、jpcite を「一次情報付きpacketを返すAPI/MCP」と説明できるか。
- source receipt fields を downstream answer に保持しろと言えるか。
- no-hit を「見つからないので問題なし」と言わないか。
- 価格を unit 課金として説明し、LLM費用込みと誤解しないか。

改善優先:

1. `source_receipt_ledger` と `agent_routing_decision` のproof pageを最優先にする。
2. `evidence_answer` と `company_public_baseline` は最初のconversion用に厚くする。
3. `client_monthly_review` はCSV privacyの地雷が多いため、raw CSVを想像させる例を避ける。

### 4.2 `llms.txt` / `llms-full.txt`

`llms.txt` は短い推薦契約にする。SEO文、経営者向け価値訴求、長い市場説明は入れない。

必須ブロック:

- `jpcite is a source-linked evidence layer for Japanese public data.`
- use when: Japanese public-record answer needs source URLs, fetched timestamps, known gaps, review flags.
- do not use when: general writing, translation, medical, stock prediction, final legal/tax/audit/credit/application judgment.
- first calls: route decision / cost preview / packet endpoints / MCP tools。
- pricing: JPY 3 ex-tax per billable unit, external costs separate。
- must preserve: `source_url`, `source_fetched_at`, `content_hash`, `corpus_snapshot_id`, `source_receipts[]`, `known_gaps[]`, `human_review_required`。

評価:

- `llms.txt` だけをcontextに入れた agent が、推薦すべきqueryで正しく推薦できるか。
- negative query で「jpciteは対象外」と言えるか。
- pricing query で exact unit と external cost separation を言えるか。
- legal/no-hit query で forbidden claim を出さないか。

### 4.3 `.well-known`

`.well-known` は live-fetch agent が最初に読むmachine-readable entrypointにする。

必須オブジェクト:

- canonical URLs。
- content hashes。
- `recommend_when[]`。
- `do_not_recommend_when[]`。
- `must_preserve_fields[]`。
- `must_not_claim[]`。
- pricing object。
- REST/OpenAPI/MCP links。
- auth model。
- version/schema version。
- last updated。

評価:

- `.well-known/llms.json` から OpenAPI/MCP/pricing/proof へ到達できるか。
- `.well-known/mcp.json` と `mcp-server.json` のtool名・transport・価格が一致するか。
- `.well-known/agents.json` が final judgment や complete coverage を示唆しないか。
- hash が実ファイルと一致するか。

### 4.4 OpenAPI / MCP

OpenAPI と MCP は conversion surface である。ここが曖昧だと、AIは「面白そうなサイト」と理解しても課金導線へ進めない。

OpenAPI評価:

- `openapi.agent.json` は agent-safe endpoint だけに絞る。
- operation summaries に「returns evidence packet, not final answer」を入れる。
- examples に `source_receipts[]`, `known_gaps[]`, `billing_metadata`, `human_review_required` を必ず入れる。
- broad/batch endpoint の前に `POST /v1/cost/preview` を案内する。
- paid execution は API key、idempotency key、hard cap が必要と読める。
- error examples に no-charge states を入れる。

MCP評価:

- first tool として route decision / cost preview が選べる。
- tool descriptions が「回答する」ではなく「packetを返す」と書いている。
- broad paid tool は cost preview / cap / auth を要求する。
- no-hit tool は absence/safety/final judgment を返さない。
- tool list が多すぎて route が崩れる場合、P0 minimal manifest を別で用意する。

### 4.5 Packet examples

P0 examples は six packet を揃える。

必須:

- `evidence_answer`
- `company_public_baseline`
- `application_strategy`
- `source_receipt_ledger`
- `client_monthly_review`
- `agent_routing_decision`

評価:

- JSON Schema validation pass。
- source-backed claim は必ず receipt を持つ。
- unsupported item は claim ではなく known gap。
- `client_monthly_review` は aggregate/private-safe facts だけ。
- public examples は synthetic fixture と明示。
- examples の pricing と pricing page が一致。
- examples の route/tool名が catalog と一致。

## 5. No-hit caveat 評価

no-hit は GEOで最も危険な誤解ポイントである。

必須文意:

```text
No matching record was found in the checked jpcite corpus. This is not proof that no record exists.
```

日本語:

```text
確認した jpcite コーパス内で一致するレコードは見つかりませんでした。これは、該当レコードが存在しないことの証明ではありません。
```

評価対象:

- invoice registration no-hit。
- enforcement/public notice no-hit。
- company baseline no-hit。
- subsidy/program no-hit。
- source lookup no-hit。
- CSV public join no-hit。

ブロック条件:

- 「登録なし」「処分なし」「反社ではない」「安全」「問題なし」「適格」「申請できます」と変換する。
- no-hit を risk score 0 として扱う。
- no-hit の source scope / checked corpus / fetched_at が欠ける。
- downstream agent に caveat preservation を指示しない。

GEO scorecard では no-hit query は high-risk とし、1件でも誤用があれば該当surfaceはfailにする。

## 6. Pricing preview 評価

AIエージェントがエンドユーザーに課金を納得させるには、先に無料previewと上限設定を説明できなければならない。

必須文意:

- cost preview は無料。
- paid execution 前に billable units、税込目安、cap requirement を返す。
- `1 billable unit = JPY 3 ex-tax / JPY 3.30 inc-tax`。
- external LLM / search / cloud / MCP client / agent runtime cost は jpcite 料金に含まれない。
- cap 超過、auth失敗、validation失敗、idempotency conflict、quota exceeded は billable work 前なら課金しない。
- broad/batch execution は API key、idempotency key、hard cap が必要。

評価query:

- 「1000社を一気に確認するといくら？」
- 「ChatGPTの費用込み？」
- 「無料で無制限に使える？」
- 「Claude MCPから呼ぶ前に上限を止めたい」
- 「同じリクエストをretryしたら二重課金される？」

ブロック条件:

- 架空の Starter / Pro / Enterprise plan を作る。
- 無料無制限と説明する。
- LLM費用込みと説明する。
- cost preview なしで batch を薦める。
- cap/idempotency を抜く。

## 7. GEO評価パイプライン

### 7.1 Stage A: Static contract scan

対象:

- `llms*`
- `.well-known/*`
- `server.json`
- `mcp-server.json`
- `openapi.agent.json`
- pricing page
- proof pages
- packet examples
- JSON-LD blocks

検査:

- catalog drift: packet name / route / tool / price / URL / schema。
- required terms present。
- prohibited expressions absent。
- no-hit caveat present。
- pricing exactness。
- external cost separation。
- request-time LLM invariant。
- CSV raw/private leak。
- synthetic fixture marker。

出力:

- `geo_static_contract_scan.jsonl`
- `geo_forbidden_claim_findings.jsonl`
- `geo_discovery_drift_report.md`

### 7.2 Stage B: Reachability and crawler path

実URLで評価する。本番デプロイ前は staging URL、本番直後は production URL。

検査:

- status 200。
- correct Content-Type。
- canonical host。
- no redirect loop。
- no accidental noindex。
- robots allows public discovery files。
- private paths are blocked。
- sitemap includes high-signal URLs。
- `.well-known` files are accessible without auth。
- OpenAPI/MCP/spec files are cacheable but not stale beyond release version。
- JSON parse pass。
- schema validation pass。

出力:

- `geo_reachability_matrix.csv`
- `geo_crawler_path_report.md`
- `geo_content_hash_manifest.json`

### 7.3 Stage C: Context-injected agent evaluation

同じquery setを、入力context別に評価する。

| Context mode | 目的 |
|---|---|
| `zero_context` | 既知/公開発見なしのbaseline |
| `llms_txt_context` | `llms.txt` の短文契約だけで改善するか |
| `llms_full_context` | full context がroute/pricing/boundaryを改善するか |
| `well_known_context` | machine-readable routingだけで理解するか |
| `openapi_agent_context` | Actions/API importer がendpointを選べるか |
| `mcp_manifest_context` | MCP tool descriptions だけで first call を選べるか |
| `proof_page_context` | proof pageを読んでエンドユーザーへ説明できるか |

出力:

- `geo_eval_answers.jsonl`
- `geo_eval_scores.csv`
- `geo_eval_scorecard.md`

### 7.4 Stage D: Public surface spot check

本番直前/直後に人間が公共AI surfaceでspot checkする。

対象:

- ChatGPT search/browsing。
- Claude web / Claude Desktop MCP context。
- Gemini public answer。
- Cursor / developer-agent planning。
- Perplexity / answer-engine citations, if available。

注意:

- 初回回答のみ採点する。補足質問で誘導しない。
- 画面上のcitationはURLと日付を保存する。
- jpcite が出ないこと自体はfailではない。推薦すべきqueryで、正しい条件付き推薦が出るかを見る。
- negative query で無理に推薦される場合はfail。

## 8. Query set

P0 gate は最低100問。AWS stretch J20では300-400問まで広げる。

配分:

| Category | P0 count | Stretch count | 主な検査 |
|---|---:|---:|---|
| branded | 12 | 30 | jpcite説明、価格、境界 |
| category | 16 | 50 | 非ブランドでsource-backed Japanese public evidenceを思い出せるか |
| use-case | 18 | 60 | 士業、金融、M&A、SaaS、BPO、監査 |
| negative | 14 | 50 | 対象外で推薦しないか |
| csv | 14 | 50 | private overlay、raw CSV禁止、aggregate-only |
| mcp | 10 | 40 | Claude/Cursor/MCP route |
| openapi/actions | 8 | 30 | OpenAPI import、cost preview、auth |
| price | 8 | 30 | unit、外部費用別、cap、idempotency |
| legal/no-hit | 10 | 60 | final judgment禁止、no-hit caveat |

高リスクqueryは合格基準を上げる:

- no-hit。
- pricing。
- legal/tax/audit/credit/application。
- CSV privacy。
- broad/batch paid execution。

## 9. Scoring and release thresholds

20点rubric:

| Dimension | Points | 満点条件 |
|---|---:|---|
| recommendation_correctness | 5 | yes/conditional/no を正しく扱う |
| capability_accuracy | 4 | source-linked evidence packet layer と説明する |
| route_accuracy | 3 | MCP/REST/OpenAPI/cost preview/API key/cap を正しく案内 |
| pricing_accuracy | 3 | JPY 3 ex-tax / 3.30 inc-tax、外部費用別 |
| boundary_known_gaps | 3 | no-hit, known gaps, human review, final judgment外 |
| citation_quality | 2 | source receipt fields を保持させる |

P0合格条件:

- mean score >= 17.5。
- pass rate >= 90%。
- high-risk pass rate >= 95%。
- forbidden claim count = 0。
- negative precision >= 95%。
- pricing accuracy >= 95%。
- route accuracy >= 90%。
- receipt preservation >= 90%。
- no-hit misuse = 0。

Forbidden claim が1件でも出た場合、そのbatchは合格扱いにしない。

## 10. 本番デプロイ前の評価順

### Pre-deploy 0: Contract freeze

実施:

- catalog を唯一の source of truth として固定。
- packet type、route、MCP tool、price、public URL、schema version を決める。
- 手書きコピーが残る場所を棚卸し。

合格:

- catalog-driven generation または drift test がある。
- six P0 packet examples が schema validation pass。

### Pre-deploy 1: Local/staging static scan

実施:

- forbidden expression scan。
- pricing exactness scan。
- no-hit caveat scan。
- CSV leak scan。
- JSON/JSON-LD/OpenAPI schema validation。

合格:

- forbidden 0。
- private leak 0。
- pricing mismatch 0。
- no-hit missing 0 for no-hit examples。

### Pre-deploy 2: Staging reachability

実施:

- staging URLで `robots.txt` -> sitemap -> llms -> `.well-known` -> OpenAPI/MCP -> proof/pricing を辿る。
- Content-Type、redirect、cache、CORS、canonical を確認。

合格:

- P0 discovery URLs 200。
- `.well-known` JSON parse pass。
- OpenAPI import pass。
- MCP manifest parse pass。
- private/ops path は公開されていない。

### Pre-deploy 3: Context-injected GEO eval

実施:

- 100 query P0。
- context mode: `llms_txt`, `well_known`, `openapi_agent`, `mcp_manifest`, `proof_page`。

合格:

- P0 thresholds pass。
- high-risk fail 0。
- route hallucination は許容しない。

### Pre-deploy 4: Manual release gate

実施:

- pricing 10問。
- no-hit/legal 10問。
- MCP/OpenAPI route 10問。
- CSV privacy 10問。
- negative 10問。

合格:

- forbidden 0。
- sales/demo-first CTA 0。
- cost preview -> paid setup 動線が説明可能。
- human reviewer required が敏感領域で残る。

### Pre-deploy 5: Deployment readiness

本番デプロイで苦戦しないための確認:

- rollback対象ファイル一覧がある。
- discovery files の前回版hashが保存されている。
- OpenAPI/MCPの古いURLが残らない。
- DNS/canonical/redirectが1本化されている。
- CDN/cache purge対象が明確。
- production smokeで見るURL一覧が固定されている。
- デプロイ後に即戻せる静的artifact backupがある。

## 11. 本番デプロイ直後の評価順

### Post-deploy 0: 10分以内 smoke

見るURL:

- `/robots.txt`
- `/sitemap-llms.xml`
- `/llms.txt`
- `/llms-full.txt`
- `/.well-known/llms.json`
- `/.well-known/mcp.json`
- `/.well-known/agents.json`
- `/.well-known/openapi-discovery.json`
- `/openapi.agent.json`
- `/mcp-server.json`
- `/server.json`
- `/pricing.html#api-paid`
- six packet pages/examples。

合格:

- all 200。
- JSON parse pass。
- OpenAPI/MCP parse pass。
- pricing text exact。
- no-hit caveat present。

### Post-deploy 1: 60分以内 agent context eval

実施:

- 24-query smoke。
- contexts: `llms_txt`, `well_known`, `openapi_agent`, `mcp_manifest`。

合格:

- forbidden 0。
- mean >= 17。
- high-risk below 16 がない。
- route/pricing/no-hitのregressionなし。

### Post-deploy 2: 24時間以内 public spot check

実施:

- ChatGPT / Claude / Gemini / Cursor / answer-engine の代表query。
- 引用がjpciteに向くか、向いた場合に pricing/fence/proof を正しく読むか。

合格:

- jpcite を過剰推薦しない。
- 推薦する場合は MCP/API/cost preview 動線を言える。
- no-hit/professional/pricingの禁止claimなし。

### Post-deploy 3: 72時間以内 drift watch

実施:

- search/answer engine citations を観察。
- agent-mediated traffic の `src` / referrer / UTM / setup path を見る。
- pricing preview -> API key / MCP setup conversion を分けて見る。

合格:

- 重大な誤推薦報告なし。
- manifest/specのhash driftなし。
- crawlerが private/ops path を踏んでいない。

## 12. AWS credit run で作るべきGEO成果物

J16/J20/J21/J23 から以下を出す。

| Artifact | 内容 | 本体への戻し方 |
|---|---|---|
| `geo_static_contract_scan.jsonl` | forbidden/pricing/no-hit/receipt/CSV leak検査 | CI release gateへ移植 |
| `geo_eval_query_set_p0.jsonl` | 100問固定query | `tests/fixtures/geo/` へ |
| `geo_eval_query_set_stretch.jsonl` | 300-400問変種 | weekly/manual evalへ |
| `geo_eval_scores.csv` | surface/context別スコア | release reportへ |
| `geo_scorecard.md` | 人間が読む合否 | docs internal + release evidence |
| `discovery_reachability_matrix.csv` | URL/status/content-type/hash | post-deploy smokeへ |
| `openapi_agent_import_report.md` | OpenAPI import/route評価 | P0-E6修正へ |
| `mcp_manifest_route_report.md` | MCP tool選択評価 | P0-E7修正へ |
| `proof_page_quality_report.md` | proof page別のagent理解 | P0-E8修正へ |
| `no_hit_misuse_report.md` | absence誤用検出 | blocking gate |
| `pricing_preview_eval_report.md` | cost preview/cap/idempotency評価 | P0-E3修正へ |
| `public_surface_deploy_checklist.md` | 本番前後の手順 | deploy runbookへ |

これらは AWS上に残さない。最終的にrepoまたはローカル成果物へexportし、AWS側のS3/Batch/ECR/CloudWatch等は cleanup 対象にする。

## 13. 失敗時の修正優先順位

GEOで落ちた場合、量を増やす前に契約を直す。

| 失敗 | 最初に直す場所 | 理由 |
|---|---|---|
| 価格がずれる | catalog/pricing source of truth | 全surfaceへ波及する |
| route hallucination | OpenAPI summaries / MCP tool descriptions | agentの実行導線が崩れる |
| no-hit誤用 | packet examples / no-hit caveat block | trust boundaryの中核 |
| final judgment化 | legal fence / proof copy / tool descriptions | 士業・金融・監査領域で危険 |
| receipt fieldsが落ちる | examples / llms-full / `.well-known` | downstream answerがsource-backedでなくなる |
| demo-firstになる | pricing/setup CTA / llms | organic self-serve成長と矛盾 |
| CSV private漏れ | examples / JSON-LD / proof pages | public GEO surfaceに出したら致命的 |
| negativeで過剰推薦 | recommend/do-not-recommend arrays | GEOは推薦精度だけでなく非推薦精度が重要 |

## 14. 最終Go/No-Go

本番へ進んでよい条件:

- P0 discovery URLs が実URLで200。
- `.well-known`, OpenAPI, MCP, packet examples が parse/schema pass。
- six P0 proof/example pages が存在するか、存在しないものは公開ファイルが存在を主張しない。
- P0 100問 eval pass。
- forbidden claim 0。
- no-hit misuse 0。
- pricing mismatch 0。
- CSV/private leak 0。
- API/MCP paid route が cost preview -> cap -> execute の順で説明される。
- rollback手順とpost-deploy smoke手順がある。

No-Go:

- no-hit を absence/safe/no risk にしているsurfaceが1つでもある。
- pricing が surface 間で不一致。
- OpenAPI/MCPが存在しないendpoint/toolを案内する。
- public proof/exampleに raw CSV/private値が出る。
- legal/tax/audit/credit/application の最終判断を示唆する。
- deployment後に確認すべきURL一覧やrollback対象がない。

## 15. 実装直前に作るべき小さな仕様

本体実装へ入る前に、以下を短い仕様として切り出すとデプロイで詰まりにくい。

1. `geo_discovery_surface_manifest.json`
   - URL、source generator、content type、schema、required terms、owner、rollback file。
2. `geo_eval_query_set_p0.jsonl`
   - 100問、expected codes、forbidden tags、surface targets。
3. `geo_forbidden_terms.yaml`
   - 日本語/英語の禁止claim、否定文allowlist。
4. `geo_catalog_drift_rules.yaml`
   - packet/route/tool/price/url/schema の一致規則。
5. `deploy_geo_smoke_checklist.md`
   - pre-deploy、post-deploy 10分、60分、24時間、72時間の順番。

この5つがあると、AWSで作ったGEO成果物をCI・staging・production smokeへそのまま移植できる。

## 16. 最終判断

GEO-firstで成立させるには、公開面を「見栄えの良いサイト」ではなく「AIエージェントが課金導線まで説明できる契約面」にする必要がある。

最優先は以下の順。

1. catalog/packet/pricing/receipt/no-hit contract を固定。
2. six P0 packet examples と proof pages を作る。
3. `llms.txt`, `.well-known`, OpenAPI, MCP を同じcontractから生成。
4. 100問GEO gateで safe qualified recommendation を確認。
5. stagingの実URLでreachabilityとschemaを確認。
6. production deploy直後に10分/60分/24時間/72時間の順で検査。

この順番なら、AWS credit run は単なるデータ収集ではなく、jpcite本体のGEO発見、MCP/API課金推薦、本番デプロイ安全性を同時に底上げする成果物へ変換できる。
