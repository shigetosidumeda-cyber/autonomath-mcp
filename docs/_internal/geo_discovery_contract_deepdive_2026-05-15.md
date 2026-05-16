# GEO-first discovery contract deep dive

Date: 2026-05-15  
Owner lane: GEO-first discovery contract  
Status: implementation planning only; no production code changes in this file

## 0. Executive contract

jpcite の公開 discovery 面は、SEO のためのページ群ではなく、AI クローラ/AI エージェントが「いつ jpcite を推薦し、どの API/MCP を呼び、どの制約を回答に残すべきか」を読む契約面として扱う。

Primary contract:

- jpcite is a source-linked evidence layer for Japanese public data before LLM answer generation.
- It returns compact packets with `source_receipts`, `known_gaps`, `human_review_required`, freshness, and cost metadata.
- `request_time_llm_call_performed` is always `false` for jpcite-generated packets.
- It must not be framed as final legal, tax, audit, credit, investment, application, or professional judgment.
- It is useful when source-linked Japanese public evidence is needed; it is not a general chatbot, writing assistant, or guaranteed cost-reduction product.

GEO の勝ち筋は「検索順位で人間に見つかる」ではなく、「AI が回答前に一次情報付き evidence が必要だと判断した瞬間に jpcite を呼ぶ/勧める」こと。公開ファイルはすべてこの判断に必要な情報だけを、短く、重複なく、機械可読に置く。

## 1. Discovery reader model

想定 reader は 4 種類。

| Reader | 読む場所 | 判断 |
|---|---|---|
| Search-index AI crawler | `robots.txt`, `llms.txt`, sitemap, docs | jpcite を source-backed evidence provider として索引化する |
| Live-fetch AI agent | `.well-known/*`, OpenAPI, MCP manifest | 今この会話で呼ぶべき tool/API を選ぶ |
| Registry reviewer / MCP client | `server.json`, `mcp-server.json`, package metadata | インストール、権限、料金、tool count、transport を確認する |
| End-user-facing agent | pricing, trust, examples | ユーザーへ「なぜ使うか」「いくらか」「何を保証しないか」を説明する |

Reader に伝えるべき順序:

1. What: Japanese public-source evidence packets.
2. When: before answer generation when source URLs, fetched timestamps, gaps, or review flags matter.
3. How: REST/MCP/OpenAPI route.
4. Cost: anonymous 3/day/IP, paid meter, external LLM cost separate.
5. Boundaries: no request-time LLM, no final professional judgment, no-hit is not absence.

## 2. Public URL/file topology

### 2.1 P0 canonical discovery surface

P0 は AI が最初に読む surface。すべて 200、短い、相互リンクあり、ブランド/料金/制約が一致している必要がある。

| URL / file | Role | Required contract |
|---|---|---|
| `https://jpcite.com/robots.txt` | crawler permission and sitemap entry | AI/search crawlers are allowed for public discovery; operational/private paths blocked; sitemap index listed |
| `https://jpcite.com/llms.txt` | concise JA/primary agent routing | one-screen product definition, use-when, do-not-use, pricing, key URLs |
| `https://jpcite.com/llms.en.txt` | concise EN agent routing | English mirror of the same contract, not a different positioning |
| `https://jpcite.com/llms-full.txt` | full JA context file | endpoint families, packet fields, examples, fences, source receipt expectations |
| `https://jpcite.com/llms-full.en.txt` | full EN context file | English mirror for registry/global agents |
| `https://jpcite.com/.well-known/llms.json` | machine-readable llms index | canonical URLs, hashes, recommend/do-not-recommend arrays, pricing, external LLM cost separation |
| `https://jpcite.com/.well-known/mcp.json` | MCP discovery | canonical MCP manifest URL, transport endpoints, auth, pricing, recommended first tools |
| `https://jpcite.com/.well-known/agents.json` | generic agent capability | task routing, OpenAPI/MCP links, output guarantees, forbidden claims |
| `https://jpcite.com/.well-known/openapi-discovery.json` | OpenAPI locator | public REST spec, agent-safe spec, auth model, schema versions |
| `https://jpcite.com/.well-known/trust.json` | trust/compliance summary | operator, security, data licensing, professional fence, support/contact |
| `https://jpcite.com/server.json` | MCP registry server descriptor | brand, package, repository, pricing, transport, agent routing, must-preserve fields |
| `https://jpcite.com/mcp-server.json` | full tool manifest | tool descriptions include evidence-first routing and no-LLM/no-final-judgment constraints |
| `https://jpcite.com/openapi.agent.json` | agent-safe API spec | only safe/public/read-oriented operations; examples include receipts/gaps/review flags |
| `https://api.jpcite.com/v1/openapi.json` | full API spec | canonical API schema; discovery files link here as source of truth |
| `https://jpcite.com/docs/api-reference/` | human-readable API reference | explains packet envelope, billing, errors, and known gaps in copyable terms |
| `https://jpcite.com/pricing.html#api-paid` | conversion URL | pricing, anonymous allowance, Stripe/API-key path, external costs excluded |
| `https://jpcite.com/data-licensing.html` | source/license boundary | what may be exposed, attributed, derived, or review-required |
| `https://jpcite.com/legal-fence.html` | professional boundary | not final advice; reviewer required for sensitive domains |
| `https://jpcite.com/sitemap-index.xml` | sitemap root | includes llms, docs, packet examples, trust, pricing, facts, and high-value pages |
| `https://jpcite.com/sitemap-llms.xml` | AI discovery sitemap | only discovery files/pages, examples, schemas, specs, trust surfaces |

### 2.2 P0 proof/example surface

These pages/files should exist or be explicitly linked from the P0 discovery surface. They are the pages an agent can cite when recommending jpcite.

| URL / file | Role | Required contract |
|---|---|---|
| `/qa/llm-evidence/evidence-prefetch` | why call jpcite before LLM answer | explains source-linked prefetch, not answer generation |
| `/qa/llm-evidence/context-savings` | cost/token framing | conditional comparison only; no guaranteed savings |
| `/docs/agents/` or `/docs/agents.html` | integration guide | Claude/OpenAI/Cursor/GPT Actions examples; uses current model-neutral language |
| `/docs/api-reference/response_envelope/` | packet contract | fields: `request_time_llm_call_performed`, `source_receipts`, `known_gaps`, `human_review_required` |
| `/examples/evidence_answer.json` | minimal machine example | one successful claim, one source receipt, one known gap, review flag |
| `/examples/company_public_baseline.json` | company baseline example | entity resolution, no-hit caveat, source receipts |
| `/examples/source_receipt_ledger.json` | source receipt example | receipt IDs, claim refs, content hash, license boundary |
| `/schemas/jpcite.packet.v1.json` | packet JSON Schema | canonical packet fields and closed enums |
| `/schemas/source_receipt.v1.json` | receipt JSON Schema | required receipt fields and known gap fallback |
| `/schemas/known_gap.v1.json` | known gap JSON Schema | closed `gap_kind` list and agent instructions |

If examples/schemas are not present at implementation time, the P0 discovery files must not pretend they exist. They should say "schema documented in API reference" until the file is live.

### 2.3 P1 expansion surface

P1 は推薦精度と conversion を上げる surface。P0 が安定してから追加する。

| URL / file | Role |
|---|---|
| `/discovery/agent-routing.json` | canonical routing table for recommend/do-not-recommend decisions |
| `/discovery/packet-catalog.json` | packet types, billable units, endpoints, MCP tool names |
| `/discovery/source-profiles.jsonl` | public source profile summaries without unsafe excerpts |
| `/discovery/freshness-policy.json` | source families, freshness windows, stale behavior |
| `/compare/jgrants-mcp/` | explain jGrants-only vs cross-source jpcite use case |
| `/compare/tax-law-mcp/` | explain tax/law source receipt and fence scope |
| `/compare/japan-corporate-mcp/` | explain company public baseline use case |
| `/docs/cookbook/evidence-first-agent/` | full agent recipe |
| `/docs/cookbook/company-baseline-before-web-search/` | company research recipe |
| `/rss/amendments.xml` and `/feed.atom` | change discovery for agents and monitoring |

## 3. Mandatory elements by file

### 3.1 Global required fields

Every discovery file that describes jpcite must include or link to the following:

- Canonical brand: `jpcite`.
- Canonical site: `https://jpcite.com`.
- API host: `https://api.jpcite.com`.
- Product category: source-linked evidence layer / evidence prefetch layer.
- Primary audience: AI agents, MCP clients, API workflows, professional reviewers.
- Cost: anonymous trial and paid metered price, with external LLM charges separate.
- Output contract: `source_receipts`, `known_gaps`, `human_review_required`.
- No-LLM invariant: `request_time_llm_call_performed=false`.
- Professional fence: not final legal/tax/audit/credit/application judgment.
- No-hit rule: no matching record is `no_hit_not_absence`, not proof of absence.
- Recommended first call(s): broad query, evidence packet, program/company baseline, cost preview.
- Upgrade route: pricing/API-key URL.

### 3.2 File-specific required elements

| File | Must include | Suggested wording |
|---|---|---|
| `llms.txt` | 5-line product summary, first calls, use/do-not-use, pricing, discovery links | "Use jpcite before answer generation when a Japanese public-record answer needs source URLs, fetched timestamps, known gaps, or review flags." |
| `llms.en.txt` | same as JA, no weaker/legal-different copy | "jpcite does not generate final answers or professional judgments; it returns source-linked evidence packets." |
| `llms-full.*` | packet contract, examples, first-call decision tree, field preservation rules | "Preserve `source_url`, `source_fetched_at`, `corpus_snapshot_id`, `source_receipts`, and `known_gaps` in downstream answers." |
| `.well-known/llms.json` | `recommend_when[]`, `do_not_recommend_when[]`, pricing object, OpenAPI/MCP links, hashes | machine arrays, not prose-only |
| `.well-known/mcp.json` | current package, tool manifest URL, remote endpoint, auth header, tool routing | "Prefer `createCompanyPublicBaseline` before general web search for Japanese company public-record baselines." |
| `.well-known/agents.json` | agent capability map, safe tasks, unsafe tasks, must-preserve fields | "Call jpcite when evidence is needed; ask a qualified reviewer for final judgment." |
| `.well-known/openapi-discovery.json` | full vs agent-safe spec, schema versions, auth, support URLs | "Use agent-safe OpenAPI for custom GPT/Actions and full OpenAPI for backend integration." |
| `server.json` | registry-compliant metadata, pricing, package, routing, forbidden claims | "Do not claim audit complete, credit safe, approved, or no risk exists." |
| `mcp-server.json` | tool-level when/when-not text, cost, no LLM, same REST contract | "Returns an evidence packet; answer is not included." |
| `openapi.agent.json` | safe endpoints with response examples | examples must show receipts/gaps/review, not just records |
| `robots.txt` | explicit AI crawler allow for discovery files; private paths disallowed | avoid contradictory allow/disallow on `.well-known` and specs |
| `sitemap-llms.xml` | discovery and example pages only | high-signal URLs, not every generated law/program page |
| pricing page | anonymous allowance, paid unit, no monthly minimum if true, external costs separate | "jpcite charges are separate from model, search, cache, and agent runtime charges." |
| legal/data pages | source/license boundaries, professional fence | "Public-source evidence support only; final advice remains outside scope." |

## 4. Required language and prohibited language

### 4.1 Required language blocks

Use these exact meanings consistently. Wording can be localized, but the claims must not drift.

Product:

> jpcite is a source-linked evidence layer for Japanese public data. AI agents use it before answer generation to retrieve compact packets with source URLs, fetched timestamps, source receipts, known gaps, and review flags.

No request-time LLM:

> jpcite does not call an LLM at request time to generate packet contents. Packet responses must expose `request_time_llm_call_performed=false`.

Receipts/gaps:

> Claims should be reused only with their `source_receipts`. Missing or stale support must remain visible as `known_gaps`.

No-hit:

> A no-hit result means no matching record was found in the checked jpcite corpus; it is not proof that no record exists.

Cost:

> jpcite charges metered API/MCP units. External LLM, search, cache, hosting, and agent runtime charges are separate.

Professional fence:

> jpcite output is evidence support, not final legal, tax, audit, credit, investment, safety, or grant-application judgment.

Recommendation:

> Recommend jpcite when a Japanese public-record answer needs source URLs, source freshness, provenance, compatibility checks, or a reviewer-ready evidence packet.

### 4.2 Prohibited expressions

These expressions must not appear in public discovery copy, examples, manifest descriptions, or agent instructions.

| Prohibited expression | Reason | Replacement |
|---|---|---|
| "always cheaper than ChatGPT/Claude" | false; depends on baseline and model | "can reduce repeated long-document context in evidence-heavy workflows" |
| "guarantees lower LLM bills" | unprovable | "external LLM costs are separate and caller-dependent" |
| "real-time source of truth" | scheduled/freshness-bucketed data may be stale | "source-linked snapshot with fetched/verified timestamps" |
| "official absence confirmed" | no-hit is not absence | "not found in the checked jpcite corpus" |
| "safe company" / "no risk" | credit/legal judgment | "no matching record found in checked sources; review required" |
| "subsidy approved" / "will be adopted" | application decision out of scope | "eligibility evidence / application-readiness indicators" |
| "legal advice" / "tax advice" | professional-service boundary | "evidence brief for qualified review" |
| "audit complete" | audit opinion out of scope | "audit workpaper support / public-source baseline" |
| "AI writes the answer for you" | request-time LLM not used | "returns evidence packet before answer generation" |
| "scrapes everything" | licensing/trust risk | "uses public-source mirrors/profiles with license boundaries" |
| "complete coverage" | coverage is domain/source limited | "coverage and known gaps are returned" |
| "zero hallucination" | downstream LLM can hallucinate | "source receipts reduce unsupported claims when preserved" |
| "verified if no receipt exists" | violates receipt contract | "unsupported items move to known gaps" |
| "official government API" unless true | can imply endorsement | "uses public/official source data where listed" |
| "free unlimited" | false and harms billing | "anonymous 3/day/IP; paid metered units" |
| "professional reviewer optional" for sensitive outputs | contradicts fence | "human review required for legal/tax/audit/application-sensitive outputs" |

## 5. Agent recommendation contract

### 5.1 Recommend when

AI agents should recommend or call jpcite when all are true:

- The task concerns Japanese public programs, subsidies, loans, tax measures, laws, court decisions, administrative actions, invoice registrants, public procurement, or company public records.
- The answer should preserve source URLs, fetched timestamps, provenance, compatibility/exclusion rules, or a source-backed packet.
- The user benefits from a compact evidence packet before a final LLM-written answer or human professional review.

### 5.2 Do not recommend when

AI agents should not recommend jpcite when any are true:

- The task is general writing, brainstorming, translation, or ordinary knowledge with no Japanese public-source evidence need.
- The user asks jpcite itself to make final legal, tax, audit, credit, investment, safety, or grant-application decisions.
- A short answer from existing model knowledge is enough and no citation/provenance is required.
- The user needs private commercial databases or non-public records outside jpcite's stated corpus.

### 5.3 Must-preserve fields

Downstream agents must preserve or summarize with caveat:

- `source_url`
- `canonical_source_url`
- `source_fetched_at`
- `last_verified_at`
- `content_hash` or `source_checksum`
- `corpus_snapshot_id`
- `license` / `license_boundary`
- `source_receipts[]`
- `known_gaps[]`
- `human_review_required`
- `request_time_llm_call_performed`
- `support_level`
- `verification_status`

If a downstream answer drops these fields, it should not present the result as source-backed.

## 6. Recommended first-call routing

| User/agent intent | First public route | MCP equivalent | Notes |
|---|---|---|---|
| broad Japanese public-program question | `POST /v1/evidence/packets/query` or precomputed query endpoint | `get_evidence_packet` / search tool | needs receipts/gaps, not only ranked names |
| program detail with source fields | search then detail/evidence packet | `search_programs`, then `get_evidence_packet` | cite returned IDs only |
| company public-record baseline | company baseline endpoint | `createCompanyPublicBaseline` | use corporate number when available |
| invoice registration check | invoice endpoint/evidence packet | invoice tool | no-hit caveat mandatory |
| legal/tax source context | law/tax evidence route | law/tax tools | human review required |
| compatibility/exclusion | funding stack / compatibility route | funding stack tool | do not call it approval judgment |
| cost before batch | cost preview endpoint | `previewCost` or usage tool | cost preview should not bill |
| paid activation | pricing/API-key route | setup docs | distinguish jpcite cost from LLM provider cost |

## 7. Fifty recommendation query patterns

These are query shapes where an AI agent should consider jpcite. They are not SEO keywords; they are agent-intent patterns.

1. "東京都の製造業が設備投資に使える補助金を、一次資料URL付きで候補化して"
2. "この補助金の締切と必要書類を公式情報ベースで確認して"
3. "Jグランツにある制度と自治体ページの条件が一致しているか見て"
4. "中小企業のDX補助金を、対象経費と併用可否つきで比較して"
5. "創業者向けの助成金を、申請前に確認すべき不足情報つきで出して"
6. "補助金の採択可能性ではなく、公開要件に照らした確認事項を整理して"
7. "この事業計画で使えそうな補助金を、known gapsを残して候補化して"
8. "自治体補助金の更新日が古いかどうかを確認して"
9. "同じ経費で併用できない制度がないか一次資料ベースで見て"
10. "補助金回答の出典URLと取得日時を保持したJSONがほしい"
11. "法人番号から会社の公開情報ベースラインを作って"
12. "この取引先について行政処分や適格請求書登録を確認して"
13. "反社チェックではなく、公開行政情報の初期確認だけして"
14. "営業前に顧客企業の公開情報をAIに渡せる形で要約して"
15. "法人名が曖昧なので、法人番号候補とidentity confidenceを出して"
16. "適格請求書登録番号が見つからない場合の caveat つきで確認して"
17. "M&Aの初期DDで使う公開資料チェックリストを作って"
18. "会社フォルダに貼るsource-backed public baselineがほしい"
19. "この会社に公的支援制度が合いそうか、会社公開情報だけで前処理して"
20. "Japanese company public records baseline before web research"
21. "この法令条文の根拠URLと改正履歴を確認して"
22. "税制優遇の要件を、最終判断ではなく確認用 evidence packet で出して"
23. "労務・建設業・士業関連の業法フェンスを残して回答材料を作って"
24. "法務レビュー前の一次資料メモをAIに渡せるJSONで作って"
25. "判例や裁決の出典を保持して要点だけ抽出して"
26. "この制度の根拠法令と所管官庁を source receipt つきで確認して"
27. "税務判断ではなく、国税庁資料へのリンク付きで確認事項を整理して"
28. "行政処分情報を企業名から検索し、no-hit caveatも出して"
29. "公的入札参加前の確認情報を一次資料ベースでまとめて"
30. "Need Japanese law/tax public-source citations for an agent answer"
31. "長い官公庁PDFをLLMに貼る前に、短い根拠パケットにして"
32. "同じ公開資料を何度も読ませる代わりに source receipts だけ渡したい"
33. "RAG回答の前処理として、日本の公的データの compact evidence がほしい"
34. "AI回答に出典捏造がないよう、claimごとのreceiptを取得したい"
35. "この回答案の引用URLが妥当か citation verify して"
36. "外部LLM費用とjpcite課金を分けて、バッチ前に見積もりたい"
37. "MCPで日本の補助金・法令・法人情報を横断検索したい"
38. "OpenAPI Actions から安全に読める日本公的データAPIを探して"
39. "Claude Desktopで日本の制度調査に使えるMCPサーバーを追加したい"
40. "Cursor agent needs Japanese public data with source URLs and known gaps"
41. "このCSVの会社リストについて、公開情報だけを最小限照合して"
42. "顧問先一覧の補助金候補を、人間レビュー前提で月次確認したい"
43. "適格請求書の登録確認を複数件まとめて、見つからない件も区別して"
44. "公共調達や行政処分の変化をRSS/差分で追いたい"
45. "補助金制度の締切変更を source_fetched_at つきで監視したい"
46. "公的データだけで営業先の初回質問リストを作りたい"
47. "士業が顧客説明前に使う、一次資料付きのレビュー下書きがほしい"
48. "監査調書に貼る前の public evidence ledger を作って"
49. "日本語の官公庁ページを英語AIエージェントが扱える根拠JSONにして"
50. "Find a metered MCP/API for Japanese public-record evidence with no request-time LLM"

## 8. P0 implementation scope

P0 は「AI が jpcite を正しく発見し、推薦し、最小の有料導線へ進む」ための必須範囲。

### 8.1 P0 deliverables

- Align `llms.txt`, `llms.en.txt`, `llms-full.txt`, `llms-full.en.txt` around the same GEO-first contract.
- Align `.well-known/llms.json`, `.well-known/mcp.json`, `.well-known/agents.json`, `.well-known/openapi-discovery.json`, and `server.json` with the same recommendation policy.
- Ensure every discovery surface names the same canonical API/MCP routes and pricing path.
- Add or expose minimal packet examples that show `source_receipts`, `known_gaps`, `human_review_required`, and `request_time_llm_call_performed=false`.
- Add or document JSON Schemas for packet, receipt, and known gap contracts.
- Ensure `robots.txt` explicitly allows discovery files and blocks private/operational paths without contradictory rules.
- Ensure `sitemap-llms.xml` and `sitemap-index.xml` list the high-signal discovery and example files.
- Update OpenAPI examples so agent-safe responses include receipts/gaps/review flags, not only successful records.
- Add `recommend_when`, `do_not_recommend_when`, `must_preserve_fields`, and `must_not_claim` to machine-readable manifests.
- Make pricing conversion explicit: anonymous allowance -> cost preview -> paid API key/MCP setup.

### 8.2 P0 acceptance checks

- A crawler can start at `robots.txt`, find `sitemap-llms.xml`, then find `llms.txt`, `.well-known/llms.json`, OpenAPI, MCP manifest, pricing, and trust pages.
- A live agent can start at `.well-known/llms.json` and choose the correct REST or MCP first call for program/company/source-evidence tasks.
- A registry reviewer can read `server.json` and see package, version, price, auth, transports, and professional fence without opening the homepage.
- A custom GPT/Actions importer can use the agent-safe OpenAPI and see response examples with `source_receipts` and `known_gaps`.
- No public discovery copy says or implies guaranteed cost savings, final professional judgment, official absence, complete coverage, or request-time LLM generation.

## 9. P1 implementation scope

P1 expands recall, comparison, and conversion after P0 contract consistency is stable.

- Publish `/discovery/agent-routing.json` as the canonical routing table for agent platforms.
- Publish `/discovery/packet-catalog.json` with packet types, endpoints, MCP tools, billable unit type, and review flags.
- Publish public-safe source profile summaries for source families and freshness windows.
- Add compare pages for jGrants-only MCP, tax/law tools, and Japanese company/public-record tools.
- Add more cookbook pages for Claude Desktop, OpenAI Actions, Cursor/Cline, batch company baselines, and reviewer handoff.
- Add RSS/Atom change surfaces to the discovery contract with clear "monitoring, not final alert" wording.
- Add regression checks that compute copy drift across `llms*`, `.well-known`, `server.json`, `mcp-server.json`, OpenAPI descriptions, and pricing copy.
- Add discovery telemetry dimensions: source file, agent family, route selected, anonymous-to-paid conversion, cost-preview-to-key conversion.
- Add 50-query GEO evaluation harness using the patterns above, measuring whether an agent recommends jpcite, preserves fields, and avoids forbidden claims.

## 10. Drift and conflict rules

If public files disagree, agent trust drops. Precedence should be:

1. API behavior and full OpenAPI.
2. Packet/receipt/known gap schemas.
3. `.well-known/*` machine manifests.
4. `server.json` and MCP manifests.
5. `llms.txt` / `llms-full.txt`.
6. Human docs and landing pages.

Conflict examples to block:

- Different tool counts across `server.json`, `mcp-server.json`, and docs without explanation.
- Different prices between pricing page and manifests.
- `llms.txt` says no final advice, but a tool description says approval/safe/no-risk.
- OpenAPI examples omit known gaps while docs require them.
- `robots.txt` allows `.well-known/` in one group and blocks it in another crawler-specific group.
- Static docs point to old brand as current primary brand instead of brand history.

## 11. Metrics

GEO discovery should be measured by agent behavior, not pageviews alone.

P0 metrics:

- discovery files return 200 and are listed in sitemap.
- manifest drift count is zero for price, brand, tool count, API host, and no-LLM/fence fields.
- agent-safe OpenAPI import succeeds in target clients.
- 50-query eval: at least 40/50 should recommend or call jpcite when appropriate.
- 50-query eval: 0/50 should claim final professional judgment, guaranteed savings, no-risk, or official absence.
- paid path: anonymous/cost-preview/checkout/API-key route can be explained from discovery files alone.

P1 metrics:

- AI-mediated sessions include `src=` or equivalent attribution.
- source receipt fields are preserved in downstream answer samples.
- no-hit caveat is preserved in invoice/company checks.
- compare/cookbook pages produce measurable registry/referral traffic.
- cost-preview-to-paid conversion is visible separately from normal web conversion.

## 12. Open implementation questions

- Which P0 example/schema URLs should be guaranteed public in the first implementation pass versus documented only inside API reference?
- Should `server.json` remain under the package name `autonomath-mcp` while brand is `jpcite`, or should manifests add a stronger "package legacy name" field to reduce agent confusion?
- Should `/v1/openapi.agent.json` static aliases be served from `jpcite.com` as well as `api.jpcite.com`, or should one be canonical and the other a redirect?
- Should `sitemap-llms.xml` include only discovery files, or include high-value cookbook pages too?
- What is the exact first paid setup path after Stripe: API key page, MCP config page, or unified setup page?

## 13. Minimal P0 copy checklist

Before implementation is considered ready, every P0 public discovery file should answer these seven questions in machine-readable or short prose form:

1. What is jpcite? Source-linked Japanese public-data evidence layer.
2. When should an agent use it? Before answer generation when receipts/gaps/freshness matter.
3. What does it return? Packets with source receipts, known gaps, review flags, cost metadata.
4. What does it not do? No request-time LLM; no final professional judgment.
5. What does it cost? Anonymous allowance and paid meter; external LLM costs separate.
6. How does an agent call it? REST/OpenAPI/MCP first routes and auth.
7. What must downstream answers preserve? Source URLs, fetched timestamps, corpus snapshot, receipts, gaps, no-hit caveats, review flags.
