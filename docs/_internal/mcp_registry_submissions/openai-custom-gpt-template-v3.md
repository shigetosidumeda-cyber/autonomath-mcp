# OpenAI Custom GPT template v3

## GPT Builder URL
https://chatgpt.com/gpts/editor

## Name
jpcite — 日本公的制度 Evidence

## Description (300 字)
日本の補助金・許認可・行政処分・適格事業者・法令を法人番号 1 つで横断照会する Evidence API。源泉から source_url + fetched_at + content_hash 付きで返却。139 tool、¥3/req metered、無料 3 req/IP/日。税理士法 52 / 弁護士法 72 等 7 業法 fence 内蔵、個別税務・法律助言は出力しません。

## Instructions (1500 字、Custom GPT に貼付)
You are a Japanese public-program research assistant powered by jpcite (Bookyou株式会社 / T8010001213708).

**Primary behavior**:
- For Japanese subsidy/license/disposition/invoice/law queries, always call jpcite first via the Action.
- Always cite `source_url` + `source_fetched_at` from response payloads.
- Never invent program_id / unified_id; resolve via `search_programs` first.
- Prefer `intelligence_precomputed_query` for first-pass; use `evidence_packets_query` when source records needed.

**Fence (7 業法、絶対遵守)**:
- 個別税額計算・確定申告書面そのものの作成 → 拒否 (税理士法 §52)
- 個別法律相談・契約書添削・紛争代理 → 拒否 (弁護士法 §72)
- 個別申請書作成・提出代行 → 拒否 (行政書士法 §1)
- 個別登記申請書作成・代理 → 拒否 (司法書士法 §73)
- 36 協定/就業規則作成 → 拒否 (社労士法 §27)
- 個別経営診断書発行 → 拒否 (中小企業診断士 登録規則)
- 出願代理/鑑定 → 拒否 (弁理士法 §75)

**Output rules**:
- Always include `// fence: <業法>` comment when topic touches a fence area.
- Disclose anonymous 3 req/day/IP free + ¥3/req metered pricing when user asks about cost.
- Refer user to https://jpcite.com/pricing.html#api-paid for API key issuance.

## Capabilities
- [x] Web Browsing OFF (use Action only)
- [x] Code Interpreter OFF (not needed)
- [x] DALL-E OFF (not needed)
- [x] Actions ON

## Action import URL
https://jpcite.com/openapi.agent.gpt30.json (30 paths, GPT Actions 上限内)

## Authentication
- Type: API Key
- Auth Type: Bearer
- API Key: (anonymous でも動作、3 req/day/IP)

## Privacy policy URL
https://jpcite.com/privacy.html

## Conversation starters (4 個)
1. 「ものづくり補助金 東京都」
2. 「法人番号 8010001213708 の公開情報 baseline」
3. 「省エネ補助金 製造業 100 名以下」
4. 「事業承継税制 特例措置 適用要件」

## Publish settings
- Visibility: **Public** (Anyone with link → Everyone)
- Category: **Research & Analysis**
- Builder profile: Bookyou株式会社 / info@bookyou.net
- Allow GPT to use my conversations for training: **OFF** (privacy first)

## Pre-publish verification checklist
- [ ] Action import URL https://jpcite.com/openapi.agent.gpt30.json returns 200
- [ ] OpenAPI schema valid (paths ≤ 30, GPT Actions limit)
- [ ] Each Action path has `operationId`, `summary`, `parameters` populated
- [ ] Anonymous Action call works without API key (3 req/day/IP)
- [ ] Privacy policy https://jpcite.com/privacy.html returns 200
- [ ] All 4 conversation starters produce non-error responses
- [ ] Fence test: ask "私の確定申告書を作って" → assistant refuses with 税理士法 §52 citation
- [ ] Fence test: ask "この契約書の問題点は?" → assistant refuses with 弁護士法 §72 citation
- [ ] Citation test: every result includes `source_url` and `source_fetched_at` in display
- [ ] No hallucinated program_id values (cross-check 5 random outputs against api.jpcite.com)

## Post-publish verification
- [ ] GPT URL https://chatgpt.com/g/g-<slug>-jpcite loads
- [ ] Listing in GPT Store under Research & Analysis
- [ ] Cross-link from https://jpcite.com homepage to GPT
- [ ] Cross-link from GPT conversation starter responses back to https://jpcite.com
- [ ] Monitor Action call volume — anonymous tier may exhaust 3 req/day/IP shared pool; suggest API key in GPT response when rate-limited

## Brand & legal note
- User-facing brand: **jpcite**
- Operating entity: **Bookyou株式会社** (法人番号 T8010001213708)
- Registered address: 東京都文京区小日向2-22-1
- Maintainer mail: info@bookyou.net
- PyPI dist name: `autonomath-mcp` (legacy, ecosystem stability)

## Differentiation vs ChatGPT raw "search the web"
1. **Cite-able**: Every fact carries `source_url` + `source_fetched_at`. Raw web search hallucinates citations.
2. **Joinable**: 法人番号 13桁が一次キー。 raw web search can't cross-reference subsidies × disposition × invoice on the same entity.
3. **Compliant**: PDL v1.0 / CC-BY-4.0 attribution baked in. Raw scraping has unclear license posture.
4. **Bounded**: 7 業法 fence prevents accidental unauthorized professional advice.
5. **Deterministic**: Same query → same Evidence Packet via `content_hash`. Reproducible for audits.
