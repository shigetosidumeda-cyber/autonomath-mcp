# jpcite TypeScript SDK (`@autonomath/sdk`)

Official TypeScript / JavaScript SDK for [jpcite](https://jpcite.com)
REST + MCP API. The package is currently published as `@autonomath/sdk`
for compatibility. Catalogs Japanese institutional programs:

- 11,684 searchable 補助金 / 助成金 / 認定制度
- 108 融資 (担保 / 個人保証人 / 第三者保証人 三軸分解)
- 2,286 採択事例
- 1,185 行政処分
- 50 税制 ruleset (インボイス / 電帳法 etc.)
- 9,484 法令 (e-Gov, CC-BY)
- 181 排他/前提ルール

Zero runtime dependencies. Works in Node 20+, Deno, Bun, modern browsers
(global `fetch`).

## Install

**Pre-release — npm publish pending.** Install direct from git for now:

Public npm release is pending. Until then, call the REST API directly or use the
MCP package from Python.

For the optional MCP bridge, also install the Python MCP server:

```bash
pip install autonomath-mcp
# or
pipx install autonomath-mcp
```

## Quickstart

```ts
import { Jpcite } from "@autonomath/sdk";

const am = new Jpcite({
  apiKey: process.env.JPCITE_API_KEY, // optional — anonymous gets 3 req/日
});

// 1. Search programs
const programs = await am.searchPrograms({
  q: "省エネ",
  tier: ["S", "A"],
  prefecture: "東京都",
  limit: 10,
});
for (const p of programs.results) {
  console.log(p.unified_id, p.primary_name, p.tier);
}

// 2. Get one program with full detail
const detail = await am.getProgram(programs.results[0]!.unified_id);
console.log(detail.amount_max_man_yen, detail.application_window);

// 3. Search loans (三軸: collateral / personal / third-party guarantor)
const loans = await am.searchLoans({
  q: "創業",
  collateral: "not_required",
  personal_guarantor: "not_required",
});

// 4. Search tax incentives
const taxes = await am.searchTaxIncentives({ q: "省エネ", effective_on: "2026-04-25" });

// 5. Check exclusion rules
const check = await am.checkExclusions(programs.results.map((p) => p.unified_id));
for (const hit of check.hits) {
  console.log(hit.severity, hit.programs_involved, hit.description);
}

// 6. Pull AI-facing evidence/intel envelopes
const packet = await am.getEvidencePacket("program", programs.results[0]!.unified_id);
const match = await am.intelMatch({
  industry_jsic_major: "E",
  prefecture_code: "13",
  keyword: "DX",
});
console.log(packet.quality.known_gaps, match.matched_programs.length);
```

## Endpoints

| Method                          | REST endpoint                          |
| ------------------------------- | -------------------------------------- |
| `am.healthz()`                  | `GET /healthz`                         |
| `am.meta()`                     | `GET /meta`                            |
| `am.searchPrograms(params)`     | `GET /v1/programs/search`              |
| `am.getProgram(id)`             | `GET /v1/programs/{id}`                |
| `am.searchLoans(params)`        | `GET /v1/loan-programs/search`         |
| `am.getLoan(id)`                | `GET /v1/loan-programs/{id}`           |
| `am.searchTaxIncentives(p)`     | `GET /v1/tax_rulesets/search`          |
| `am.getTaxIncentive(id)`        | `GET /v1/tax_rulesets/{id}`            |
| `am.searchEnforcement(params)`  | `GET /v1/enforcement-cases/search`     |
| `am.getEnforcement(id)`         | `GET /v1/enforcement-cases/{case_id}`  |
| `am.getLaw(id)`                 | `GET /v1/laws/{id}`                    |
| `am.getLawArticle(name, art)`   | `GET /v1/am/law_article?...`           |
| `am.listExclusionRules()`       | `GET /v1/exclusions/rules`             |
| `am.checkExclusions(ids)`       | `POST /v1/exclusions/check`            |
| `am.getEvidencePacket(kind,id)` | `GET /v1/evidence/packets/{kind}/{id}` |
| `am.queryEvidencePacket(body)`  | `POST /v1/evidence/packets/query`      |
| `am.intelMatch(body)`           | `POST /v1/intel/match`                 |
| `am.intelBundleOptimal(body)`   | `POST /v1/intel/bundle/optimal`        |
| `am.getIntelHoujinFull(id)`     | `GET /v1/intel/houjin/{id}/full`       |
| `am.checkFundingStack(ids)`     | `POST /v1/funding_stack/check`         |
| `am.me()`                       | `GET /v1/me`                           |
| `am.dashboard()`                | `GET /v1/me/dashboard`                 |
| `am.setCap(jpy)`                | `POST /v1/me/cap`                      |

`checkFundingStack(...).next_actions` values are action objects with
`action_id`, `label_ja`, `detail_ja`, `reason`, and `source_fields`.
| `am.fetch(method, path, body)`  | (escape hatch for any endpoint)        |

## Errors

All SDK errors inherit from `JpciteError` (`AutonoMathError` remains as a
compatibility alias):

```ts
import {
  JpciteError,
  AuthError,        // 401 / 403
  BadRequestError,  // 400 / 422
  CapReachedError,  // 402 (monthly ¥-cap)
  NotFoundError,    // 404
  RateLimitError,   // 429 (carries .retryAfter seconds)
  ServerError,      // 5xx
} from "@autonomath/sdk";

try {
  await am.searchPrograms({ q: "..." });
} catch (e) {
  if (e instanceof RateLimitError) {
    console.warn(`rate limited; retry after ${e.retryAfter}s`);
  } else if (e instanceof CapReachedError) {
    console.warn(`monthly cap ¥${e.capJpy} reached (used ¥${e.currentMonthChargesJpy})`);
  } else {
    throw e;
  }
}
```

Retries are automatic for 429 (respects `Retry-After`) and 5xx
(exponential backoff: 500 ms → 1 s → 2 s, capped at 8 s, max 3 retries).

## Pricing

¥3/req tax-excluded (¥3.30 incl), metered per successful billable request.
Anonymous tier: 3 req/day per IP, JST next-day reset. No tier SKUs, no
seat fees, no annual minimum commitment.
Sign up: https://jpcite.com/

`JPCITE_API_KEY` is the jpcite REST/MCP key sent as `X-API-Key`; it is not an
OpenAI / Anthropic / Gemini key. The Python MCP server still accepts
`AUTONOMATH_API_KEY` as a legacy alias.

## MCP usage (optional)

The jpcite MCP server is currently distributed as the Python package
`autonomath-mcp` (139 tools) for compatibility.
This package can spawn it as a child process for Node-based MCP hosts.

```ts
import { spawnMcp, mcpServerConfig } from "@autonomath/sdk/mcp";

// 1. Spawn directly
const proc = spawnMcp({ apiKey: process.env.JPCITE_API_KEY });
process.stdin.pipe(proc.stdin);
proc.stdout.pipe(process.stdout);

// 2. Or generate a config blob for Claude Desktop / etc.
const cfg = mcpServerConfig({ apiKey: "am_..." });
// {
//   "mcpServers": {
//     "jpcite": cfg
//   }
// }
```

Direct install for Claude Desktop is also available without this SDK
(see https://jpcite.com/docs/mcp-tools/).

## Options

| Option            | Default                       | Notes                                            |
| ----------------- | ----------------------------- | ------------------------------------------------ |
| `apiKey`          | `undefined`                   | `X-API-Key` header. Omit for anonymous (3/day per IP). |
| `baseUrl`         | `https://api.jpcite.com`   | Override for self-hosted deployments.            |
| `timeoutMs`       | `30000`                       | Per-request timeout via `AbortController`.       |
| `maxRetries`      | `3`                           | Applied to 429 and 5xx responses.                |
| `fetch`           | global `fetch`                | Inject custom fetch (undici, polyfill, etc.).    |
| `userAgentSuffix` | `undefined`                   | Appended to `User-Agent`.                        |

## Bundle size

ESM build: ~7 KB minified, ~3 KB gzip. Zero dependencies.

## Versioning

`@autonomath/sdk` follows the jpcite REST API version. SDK 0.2.x →
API v1, MCP protocol 2025-06-18.

## License

MIT — see [LICENSE](./LICENSE).

Contact: info@bookyou.net
