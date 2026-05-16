# VC narrative alignment deep dive

Date: 2026-05-15  
Owner lane: VC narrative / business model alignment with product plan  
Status: internal planning only. This is not shipped product behavior, public pricing copy, or investor disclosure.

## 0. Executive thesis

以前のVC向け7枚PDFでは、jpciteを「日本公的データAPI / MCP」として説明していた。今回の深掘り後は、より強い仮説へ寄せる。

> jpcite is metered evidence infrastructure for AI agents working with Japanese public institutional data. It turns public sources, source receipts, known gaps, CSV-derived private context, and review fences into small prebuilt packets before an AI model answers.

市場は「人間が検索窓で公的データを探す市場」ではない。初期市場は、AI agent、Custom GPT、SaaS内AI、士業/金融/支援機関の反復ワークフローが、日本の公的情報を扱う前に evidence packet を必要とする市場である。

VC向けの要点:

1. 売るものは検索APIではなく、AIが回答前に読む `source_receipts` 付き成果物packet。
2. 課金は席数ではなく、成功した evidence/packet/subject/source receipt set の metered units。
3. 成長導線は営業主導ではなく、GEO-first: AIが根拠確認を必要と判断した瞬間に推薦・preview・API/MCP実行へ流す。
4. Moatは「行数」ではなく、source receipts、packet catalog、GEO eval、CSV-derived private overlay の複合で作る。
5. 3 JPY/unit は高ACV直販には向かない。VC narrative は、低接触・高頻度・大量反復の agent/SaaS infrastructure として成立させる必要がある。

## 1. Market wedge

### 1.1 Start market

P0市場は、次の条件を満たす workflow に絞る。

- 日本の公的制度、法人、インボイス、補助金、調達、EDINET、法令、行政処分を扱う。
- AI単体回答では、制度名、URL、締切、法人同定、no-hit解釈の誤りが実務リスクになる。
- 出典URL、取得時刻、content hash、known gaps、human review flag が下流回答に残ることに価値がある。
- 1回の検索ではなく、顧問先、取引先、会員、借り手、SaaS tenant、agent conversation に対して反復される。

初期の市場定義:

| Market layer | Buyer / adopter | Usage driver | Why now |
|---|---|---|---|
| Agent builders | Custom GPT作者、MCP利用者、SaaS AI開発者 | 日本公的データをAI toolとして追加 | AI回答に出典と限界が求められる |
| Professional workflows | 税理士、会計士、行政書士、診断士、補助金コンサル | 顧問先・案件・申請前確認 | 手作業検索とPDF確認が反復している |
| Embedded SaaS | 会計/業務/CRM/バックオフィスSaaS | tenant内AI機能の根拠層 | SaaS各社がAI機能を持つが公的データ基盤は重い |
| Financial / DD workflows | 信金、地銀、M&A、VC、内部監査 | 取引先・投資先・借り手 public baseline | 本格調査前のfirst-hop公的証跡が必要 |
| Public support networks | 商工会、自治体支援窓口、支援機関 | 会員別制度候補、相談前整理 | 多数の会員に低単価で横展開できる |

### 1.2 What market it is not

VC説明では、次を主市場にしない。

| Not the primary market | Reason |
|---|---|
| 人間向け補助金検索サイト | SEO/記事/相談送客は先行競合が強く、jpciteのreceipt価値が伝わりにくい |
| 会計SaaS本体 | 仕訳、申告、給与、銀行連携ではfreee/MF/弥生に勝ちに行かない |
| 民間信用調査 | 非公開情報、取材、信用判断はTDB/TSR等の領域 |
| 法務/税務/監査/融資の最終判断 | jpciteは根拠整理であり、専門判断を売らない |
| 汎用RAG SaaS | private corpus RAGではなく、日本公的情報のsource-backed packet layer |

## 2. Charging model

### 2.1 Pricing narrative

Public baseline:

```text
unit_price_ex_tax_jpy = 3
unit_price_inc_tax_jpy = 3.30
pricing_model = metered_units
external_llm_costs_included = false
```

VC向けの表現:

> jpcite is not priced per seat because the buyer is often an agent, workflow, or embedded SaaS surface. It charges per successful evidence unit and gives agents a free cost preview before billable execution.

課金設計の意味:

| Design | Business implication |
|---|---|
| Single visible unit price | agentがユーザーへ説明しやすく、procurement frictionが低い |
| Cost preview free | 自律agentが実行前に予算判断できる |
| Hard cap required for paid batch/CSV | agent overcallと請求不信を抑える |
| Idempotency | retryやbatch再送で二重課金しない |
| External LLM costs excluded | gross marginが推論API価格に連動しにくい |
| No-hit MVP non-billable | billing disputeを減らし、trust-firstにする |

### 2.2 Billable units by value surface

| Value surface | Unit | Why it can scale |
|---|---|---|
| `evidence_answer` | successful packet | AI回答前の基本呼び出し |
| `company_public_baseline` | resolved subject | 取引先、顧問先、借り手、投資先ごとに反復 |
| `application_strategy` | normalized applicant profile | 補助金/制度相談ごとに反復 |
| `source_receipt_ledger` | `ceil(unique_receipts / 25)` | 監査、DD、SaaS trustでreceipt数に応じて伸びる |
| `client_monthly_review` | accepted client subject | 税理士、信金、商工会の月次反復 |
| CSV-derived packets | packet / subject / source receipt set | file uploadからprivate context overlayが生まれる |
| `agent_routing_decision` | free control | 推薦精度とcost governanceを上げる無料導線 |

### 2.3 Revenue expectation from unit math

3 JPY/unit は、単体顧客の高額契約ではなく、unit volumeで成立する。VC向けにはこの制約を正面から置く。

| Monthly billable units | Monthly revenue ex-tax | Annualized revenue ex-tax | Interpretation |
|---:|---:|---:|---|
| 100,000 | JPY 300,000 | JPY 3.6M | learning stage。投資対象としてはまだ小さい |
| 1,000,000 | JPY 3.0M | JPY 36M | early infrastructure traction |
| 10,000,000 | JPY 30.0M | JPY 360M | embedded agent/SaaS/channelが必要 |
| 50,000,000 | JPY 150.0M | JPY 1.8B | VC-scale候補。直販だけでは到達困難 |
| 100,000,000 | JPY 300.0M | JPY 3.6B | category infrastructure scale |

Investor-facing conclusion:

- 100k-1M units/month は product proof と pricing trust の段階。
- 10M units/month 以上は、agent recommendation、SaaS embedding、CSV/batch/watchlist のどれかが効き始めた証拠。
- 50M units/month 以上は、単発検索ではなく「反復監視されるsubject graph」が回っている状態。

## 3. GEO-first growth hypothesis

### 3.1 Core hypothesis

GEO-first growth means:

> AI agents discover, recommend, and call jpcite when a user task requires Japanese public-source evidence before answer generation.

SEOは補助線であり、主KPIは人間の検索順位ではない。見るべきは safe qualified recommendation share である。

### 3.2 Growth loop

```text
Public proof surfaces
  -> AI crawler / live agent reads jpcite contract
  -> user asks evidence-sensitive Japan public data question
  -> agent recommends cost preview or calls routing decision
  -> preview shows units, cap, known gaps, external costs separate
  -> paid packet execution
  -> source receipts and known gaps are preserved downstream
  -> downstream answer cites packet/proof surface
  -> more agent memory / examples / evaluations reinforce routing
```

### 3.3 GEO surfaces that matter

| Surface | Role in growth |
|---|---|
| `llms.txt`, `llms-full.txt`, `.well-known/*` | agentが「いつ使うか、何を保持するか、何を断定しないか」を読む |
| Public packet examples | sample input/outputでtool selectionを学習させる |
| Pricing/cost preview pages | agentが費用を説明できる |
| Legal/data fence pages | 推薦時の安全境界を明示する |
| OpenAPI/MCP manifests | 実行導線。GEOからconversionへつなぐ |
| GEO eval harness | 推薦のrecall/precision、価格、境界、citation保持を回帰テストする |

### 3.4 GEO KPIs

| KPI | Why it matters |
|---|---|
| Safe qualified recommendation share | 使うべき場面で、制約付きで推薦されているか |
| Negative precision | 対象外用途で推薦しないか |
| Pricing accuracy in agent answers | 3 JPY ex-tax、外部LLM費用別、capを正しく説明できるか |
| Must-preserve field retention | `source_receipts`, `known_gaps`, `source_fetched_at` が下流に残るか |
| Preview-to-execution conversion | agent推薦が実行に変わるか |
| Agent-sourced executions | 人間直販ではなくAI経由の分布を測る |
| Forbidden claim rate | 採択保証、税務判断、与信安全などの誤推薦がないか |

## 4. Packet volume scenarios

### 4.1 Per workflow assumptions

Directional assumptions for planning only:

| Workflow | Unit driver | Low | Base | High |
|---|---|---:|---:|---:|
| Agent evidence answer | one successful packet | 1 unit/call | 1 unit/call | 1-3 units/call with receipt ledger |
| Company public baseline | resolved company subject | 1 unit/subject | 2-4 units incl. receipts | 5+ units with DD/watch deltas |
| Client monthly review | accepted client subject | 1-2 units/client/month | 3-6 units/client/month | 8-12 units/client/month |
| CSV intake + advisor brief | file and derived artifacts | 2-5 units/file | 5-20 units/file | 20-100 units/file with joins |
| Source receipt ledger | receipt set | 1 unit/25 receipts | 2-5 units/binder | 10+ units/binder |
| SaaS embedded workflow | tenant/month | 3-10 units | 20-100 units | 100+ units if periodic monitoring |

### 4.2 Customer/channel scenarios

| Scenario | Volume model | Monthly units | Monthly revenue ex-tax | Narrative |
|---|---:|---:|---:|---|
| Developer proof | 200 builders x 500 units | 100,000 | JPY 300,000 | API/MCP utility is real, but not yet VC-scale |
| Professional niche | 1,000 small firms x 1,000 units | 1,000,000 | JPY 3.0M | self-serve professional workflows begin repeating |
| Accounting/channel wedge | 5,000 firms x 2,000 units | 10,000,000 | JPY 30.0M | monthly client review and CSV intake drive recurring volume |
| Embedded SaaS wedge | 20 SaaS partners x 500k units | 10,000,000 | JPY 30.0M | AI feature infrastructure, low-touch partner distribution |
| Financial/DD watchlists | 200 institutions/teams x 100k units | 20,000,000 | JPY 60.0M | borrower/counterparty watchlists create subject recurrence |
| Agent platform scale | 5M evidence calls + 25M subject/receipt units | 30,000,000 | JPY 90.0M | GEO + MCP/OpenAPI become primary acquisition |
| Infrastructure scale | mixed embedded + agent + watchlist | 100,000,000 | JPY 300.0M | category-level metered evidence layer |

### 4.3 Unit economics logic

The attractive margin case depends on four operating facts:

1. No request-time LLM call is inside jpcite unit economics.
2. Packet serving is mostly local/precomputed after source ingestion.
3. Source receipts are reused across many packets and subjects.
4. Batch/CSV/watchlist execution reduces orchestration overhead per unit.

The unattractive case:

- high-touch support for tiny invoices
- bespoke enterprise data work at 3 JPY/unit
- live scraping or LLM extraction on every request
- billing disputes from unclear no-hit/cap behavior
- agents overcalling without preview/cap

Therefore, the product plan must keep the architecture aligned with:

- prebuilt packet catalog
- free preview and paid cap
- receipt reuse
- no raw CSV persistence
- self-serve API/MCP distribution
- generated/drift-tested docs, OpenAPI, MCP, and proof pages

## 5. Moat narrative

### 5.1 Moat is not rows

The moat is not "we have many public rows." Public rows can be copied, re-crawled, or accessed through official APIs. The defensibility comes from the compounding system around those rows.

### 5.2 Four-part moat

| Moat layer | What compounds | Why hard to copy |
|---|---|---|
| Source receipts | URL, fetched_at, content hash, license boundary, query, no-hit meaning, claim links | A crawler can copy data, but reproducing trustworthy observation history and no-hit semantics takes time |
| Packet catalog | standard outputs like `company_public_baseline`, `application_strategy`, `client_monthly_review` | Customers integrate to outputs, not raw data. The catalog becomes workflow API surface |
| GEO eval | 100+ query set, safe recommendation scoring, forbidden claim regression | Agent recommendation quality becomes measured distribution infrastructure |
| CSV-derived private overlay | tenant-private derived facts joined to public receipts without exposing raw rows | Public data alone is generic; private context makes packets workflow-specific while preserving privacy |

### 5.3 Source receipt moat

Source receipts convert public data into auditable AI inputs.

Important properties:

- claim-level mapping, not just URL citation
- hit, no-hit, blocked, stale, license-limited states in one ledger
- `no_hit_not_absence` preserved as a machine-readable gap
- source profile separates source contract from one observation
- corpus snapshot and checksum make packets reproducible

Investor framing:

> Public data is accessible; trusted public-data evidence history is not. jpcite's receipts turn one-off crawling into a reusable audit layer for AI agents.

### 5.4 Packet catalog moat

The catalog is the product surface agents and SaaS builders integrate to.

P0 catalog:

- `evidence_answer`
- `company_public_baseline`
- `application_strategy`
- `source_receipt_ledger`
- `client_monthly_review`
- `agent_routing_decision`

Expansion catalog:

- CSV coverage receipt
- advisor handoff brief
- public join candidate sheet
- saved search delta
- funding stack compatibility
- auditor evidence binder
- member program watchlist
- borrower / counterparty public watchlist

Moat mechanism:

- Every packet has a stable schema, pricing unit, known gaps, receipt requirements, and agent guidance.
- API, MCP, OpenAPI, public examples, and docs should be generated or drift-tested from one catalog.
- Integrations become sticky because downstream agents preserve packet fields.

### 5.5 GEO eval moat

GEO is not a marketing slogan; it is an eval-controlled distribution system.

Defensible elements:

- query set across branded, category, use-case, negative, CSV, MCP, price, legal-boundary prompts
- scoring rubric for recommendation correctness, route accuracy, pricing accuracy, citation quality, boundary safety
- forbidden claim taxonomy with zero-tolerance release gate
- cross-surface checks for ChatGPT, Claude, Gemini, Cursor/generic agents

Investor framing:

> jpcite measures whether AI agents recommend it correctly, not just whether humans click search results.

### 5.6 CSV-derived private overlay moat

CSV is the bridge from public infrastructure to customer-specific workflow.

Value:

- accounting CSV produces private derived facts: period, row count, account vocabulary, activity density, industry signals, review queue
- public joins add official receipts: NTA法人番号, invoice, EDINET, procurement, gBizINFO, jGrants, e-Stat
- raw rows, descriptions, counterparties, payroll/bank details do not become public claims

Moat mechanism:

- Public source data alone is broad but generic.
- Customer CSV alone is private but unverified.
- The overlay combines private workflow context with public source receipts, while preserving privacy and professional boundaries.

VC phrasing:

> jpcite becomes more valuable when a customer brings a list, ledger, CRM, or watchlist. The private overlay tells the agent what matters; the public receipt layer tells it what can be safely cited.

## 6. Revised 7-slide VC narrative

### Slide 1: Problem

AI agents are increasingly asked to answer Japanese public-data questions, but public institutional information is scattered across official APIs, PDFs, ministry pages, local government pages, registries, and CSVs. LLMs can write fluent answers, but they often lose source freshness, no-hit nuance, and professional boundaries.

### Slide 2: Product

jpcite returns compact evidence packets before answer generation: source receipts, known gaps, fetched timestamps, content hashes, billing metadata, and human review flags. It is not an answer generator or final professional judgment engine.

### Slide 3: Market

Initial wedge: agent builders, professional workflows, embedded SaaS, financial/DD watchlists, and public support networks that need repeated Japanese public-source evidence. The unit of expansion is monitored subjects and packet workflows, not seats.

### Slide 4: Business model

Metered units at JPY 3 ex-tax per successful evidence/packet unit. Free preview, hard caps, idempotency, and no bundled external LLM cost make autonomous agent spending governable. Gross margin depends on precompute, receipt reuse, and self-serve distribution.

### Slide 5: Growth

GEO-first distribution: public proof surfaces, llms files, OpenAPI/MCP manifests, packet examples, and eval harnesses teach agents when to recommend and call jpcite. Primary metric is safe qualified recommendation share, not pageview SEO.

### Slide 6: Moat

Moat = source receipts + packet catalog + GEO eval + CSV-derived private overlay. Rows are replicable; trusted, reusable, agent-readable evidence workflows are harder to copy.

### Slide 7: Milestones

Near-term proof points:

- six P0 packets live with examples and receipts
- cost preview / cap / idempotency in paid execution
- public proof pages and discovery files consistent with OpenAPI/MCP
- GEO eval pass with zero forbidden claims
- first repeat workflows: client monthly review, company baseline, CSV advisor brief, embedded SaaS evidence calls

## 7. Investor metric dashboard

| Metric | Target interpretation |
|---|---|
| Billable units/month | core revenue volume |
| Preview-to-execution conversion | trust and pricing clarity |
| Agent-sourced execution share | GEO/MCP/OpenAPI distribution strength |
| Repeat subject rate | recurring workflow proof |
| Units per customer/month | expansion without seat pricing |
| Packet mix | whether value is moving from search to prebuilt outputs |
| Source receipt reuse rate | margin and moat signal |
| Packet cache hit rate | serving efficiency |
| Gross margin after Stripe/support | true unit economics |
| Dispute/refund rate per 10k units | billing trust |
| Cost-cap rejection rate | autonomous spend governance |
| Forbidden claim rate in GEO eval | safety and brand risk |
| CSV overlay adoption | private-context workflow value |

## 8. Narrative risks and fixes

| Risk | Why it hurts VC story | Fix |
|---|---|---|
| "Just a search API" perception | commoditizes against Google, J-Grants, RAG, MCP tools | Lead with prebuilt packets, receipts, known gaps, and review fences |
| Low unit price looks small | investors may see tiny ARPU | Show unit-volume thresholds and embedded/agent distribution path |
| Professional services confusion | suggests high support and liability | State evidence support, not final judgment; self-serve packet infrastructure |
| GEO sounds like marketing | weak if unmeasured | Tie to eval harness, recommendation accuracy, agent-sourced execution |
| CSV sounds privacy risky | blocks SaaS/professional adoption | Emphasize derived facts only, raw row minimization, tenant-private namespace |
| No-hit disputes | trust and support cost risk | MVP no-hit non-billable; `no_hit_not_absence` everywhere |
| Public rows are copyable | weak moat | Reframe moat around receipts, catalog, eval, and private overlay |
| Direct sales mismatch | 3 JPY/unit cannot support high-touch sales | Prioritize self-serve, SaaS embedding, batch/watchlist, agent recommendation |

## 9. Current alignment decision

The updated VC narrative should replace the older "Japanese public data API" headline with:

> Metered evidence infrastructure for AI agents working with Japanese public institutional data.

The business model should be explained from unit volume upward, not from seats downward.

The growth model should be explained as GEO-first agent recommendation plus API/MCP conversion, not SEO-first human acquisition.

The moat should be explained as the compounding interaction of:

1. source receipts and claim graph,
2. prebuilt packet catalog,
3. GEO evaluation and discovery contracts,
4. CSV-derived private overlay joined to public receipts.

The practical bar for VC-scale credibility is not launching the API. It is showing that agents and embedded workflows repeatedly generate billable evidence units while preserving receipts, gaps, pricing accuracy, and professional boundaries.

