# @bookyou/jpcite

Minimal TypeScript / JavaScript client for the **jpcite** REST API — Japanese institutional programs (補助金 / 融資 / 税制 / 認定), 法人番号 (T-number) lookup, 法令条文取得 (e-Gov CC-BY 4.0), and コンプライアンス検証 (排他/前提ルール).

- **Coverage**: 11,684 programs (S/A/B/C tier) + 13,801 適格事業者 + 9,484 laws + 181 排他ルール
- **Pricing**: ¥3/req metered (税込 ¥3.30). Anonymous tier = 3 req/day per IP, JST midnight reset.
- **Operator**: Bookyou株式会社 (適格請求書発行事業者番号 **T8010001213708**), info@bookyou.net
- **Zero dependencies**: uses Node 18+ global `fetch`. Works in Node, Deno, Bun, browsers.
- **API surface**: core search / 法人 / 法令 / 排他 helpers plus Evidence Packet, composite intel, and `funding_stack` helpers. For broader coverage (loans, tax incentives, dashboard, billing) use the official [`@autonomath/sdk`](https://www.npmjs.com/package/@autonomath/sdk).

## Install

```bash
npm install @bookyou/jpcite
# or
pnpm add @bookyou/jpcite
# or
bun add @bookyou/jpcite
```

## Quickstart

```typescript
import { JpciteClient } from "@bookyou/jpcite";

const jp = new JpciteClient(process.env.JPCITE_API_KEY);
```

API keys are issued at <https://jpcite.com/dashboard>. Calling without a key gives the anonymous 3 req/day tier.

## Examples

### 1. Search 補助金 / 助成金

```typescript
const res = await jp.searchPrograms("省エネ", {
  tier: ["S", "A"],
  prefecture: "東京都",
  limit: 5,
});

for (const p of res.results) {
  console.log(p.unified_id, p.primary_name, p.amount_max_man_yen, p.official_url);
}
```

### 2. 法人番号 lookup (T-number)

```typescript
const houjin = await jp.getHoujin("8010001213708");
//   or "T8010001213708" — leading T is stripped automatically.

console.log(houjin.name, houjin.invoice_registered, houjin.address);
// → Bookyou株式会社, true, 東京都文京区小日向2-22-1
```

### 3. 法令条文取得 (e-Gov CC-BY 4.0)

```typescript
const article = await jp.getLawArticle("所得税法", "第3条第1項");
console.log(article.law_name, article.article_number);
console.log(article.body);
```

Accepts either a unified law id (`LAW-jp-shotokuzeiho`) or a canonical 法令名 (`所得税法`).

### 4. コンプライアンス検証 (排他/前提ルール)

```typescript
const result = await jp.checkCompliance([
  "PROG-jp-jigyou-saikouchiku",
  "PROG-jp-monozukuri",
]);

for (const hit of result.hits) {
  console.log(hit.rule_id, hit.severity, hit.description);
}
console.log(`checked ${result.checked_rules} rules`);
```

### 5. Evidence / intel / funding_stack

```typescript
const packet = await jp.getEvidencePacket("program", "PROG-jp-example");
const match = await jp.intelMatch({
  industry_jsic_major: "E",
  prefecture_code: "13",
  keyword: "DX",
});
const stack = await jp.checkFundingStack(["PROG-A", "PROG-B"]);

console.log(packet.records.length, match.matched_programs.length);
console.log(stack.next_actions[0]?.action_id);
```

`funding_stack.next_actions` values are action objects:
`action_id`, `label_ja`, `detail_ja`, `reason`, `source_fields`.

## Errors

```typescript
import {
  JpciteError,        // base
  AuthError,          // 401 / 403
  NotFoundError,      // 404
  RateLimitError,     // 429 (with .retryAfter seconds)
} from "@bookyou/jpcite";

try {
  await jp.searchPrograms("x");
} catch (err) {
  if (err instanceof RateLimitError) {
    console.log(`retry after ${err.retryAfter}s`);
  } else if (err instanceof AuthError) {
    console.log("invalid API key");
  } else {
    throw err;
  }
}
```

## Use cases

- **Cursor / Continue / VS Code extensions** — embed Japanese subsidy + 法人 + 法令 lookup as RAG context for AI coding agents working on Japanese SMB / 会計 / 法務 software.
- **MCP clients** — call the same data through MCP via the upstream `autonomath-mcp` Python server, or directly through this REST wrapper.
- **Slack / Discord bots** — surface 補助金 alerts inside team channels.
- **freee / Money Forward / kintone integrations** — enrich corp records with 法人番号 + 適格事業者 status.

## Differences from `@autonomath/sdk`

|                          | `@bookyou/jpcite`         | `@autonomath/sdk`              |
| ------------------------ | ------------------------- | ------------------------------ |
| Methods                  | Core + Evidence/intel/funding_stack | 60+ (loans, tax, dashboard, …) |
| Brand surface            | jpcite (current)          | autonomath (legacy)            |
| Bundle size              | ~3 KB gzip                | ~8 KB gzip                     |
| Retry / backoff          | none (single attempt)     | exponential, 3 retries         |
| Audience                 | RAG / agent integrators   | full-feature backend devs      |

Both hit the same `https://api.jpcite.com` endpoint; pricing and rate limits are identical.

## Publish

```bash
npm publish --access=public
```

(Maintainer-only. Run from `sdk/npm-package/` after `npm run build`.)

## License

MIT — see [LICENSE](./LICENSE).

Data source attributions are honored on every response. e-Gov 法令 data is CC-BY 4.0; NTA invoice data is PDL v1.0; ministry / prefecture program metadata cites primary sources only (no aggregator scraping).
