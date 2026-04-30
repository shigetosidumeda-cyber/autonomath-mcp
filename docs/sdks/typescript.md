# TypeScript / JavaScript SDK

Package name: `@autonomath/sdk`. **Pre-release — npm publish pending.** Source
lives in this repo at [`sdk/typescript/`](https://github.com/shigetosidumeda-cyber/autonomath-mcp/tree/main/sdk/typescript).

Zero runtime dependencies. Works in Node 20+, Deno, Bun, and modern browsers
(uses the global `fetch`).

## Install

Direct from git until the npm publish lands:

```bash
npm install "git+https://github.com/shigetosidumeda-cyber/autonomath-mcp.git#subdirectory=sdk/typescript"
```

For the optional MCP bridge (spawn the Python `autonomath-mcp` server from Node),
also run:

```bash
pip install autonomath-mcp
```

## Quickstart

```ts
import { AutonoMath } from "@autonomath/sdk";

const am = new AutonoMath({
  apiKey: process.env.AUTONOMATH_API_KEY, // optional — anonymous = 3 req/日
});

const meta = await am.meta();
console.log(meta.total_programs, meta.tier_counts);

const programs = await am.searchPrograms({
  q: "省エネ",
  tier: ["S", "A"],
  prefecture: "東京都",
  limit: 10,
});
for (const p of programs.results) {
  console.log(p.unified_id, p.primary_name, p.amount_max_man_yen);
}
```

## Authentication

Pass `apiKey` to the constructor; the SDK sends it as `X-API-Key`. Issue keys
from your [dashboard](https://jpcite.com/dashboard).

Without an API key, anonymous IPs get 3 requests per day (resets JST 00:00
on the 1st).

## API surface

| Method                          | REST endpoint                          | Notes                              |
| ------------------------------- | -------------------------------------- | ---------------------------------- |
| `am.healthz()`                  | `GET /healthz`                         | Free liveness check                |
| `am.meta()`                     | `GET /meta`                            | Catalog totals                     |
| `am.searchPrograms(params)`     | `GET /v1/programs/search`              | 11,684 補助金/助成金/認定        |
| `am.getProgram(id)`             | `GET /v1/programs/{id}`                | Full enriched detail               |
| `am.searchLoans(params)`        | `GET /v1/loans/search`                 | 三軸 collateral/guarantor 分解   |
| `am.getLoan(id)`                | `GET /v1/loans/{id}`                   |                                    |
| `am.searchTaxIncentives(p)`     | `GET /v1/tax_rulesets/search`          | インボイス / 電帳法 etc.         |
| `am.getTaxIncentive(id)`        | `GET /v1/tax_rulesets/{id}`            |                                    |
| `am.searchEnforcement(params)`  | `GET /v1/enforcement/search`           | 1,185 行政処分                    |
| `am.getEnforcement(id)`         | `GET /v1/enforcement/{id}`             |                                    |
| `am.getLaw(id)`                 | `GET /v1/laws/{id}`                    | e-Gov, CC-BY                       |
| `am.getLawArticle(id, art)`     | `GET /v1/laws/{id}/articles/{art}`     |                                    |
| `am.listExclusionRules()`       | `GET /v1/exclusions/rules`             | 181 排他/前提ルール              |
| `am.checkExclusions(ids)`       | `POST /v1/exclusions/check`            |                                    |
| `am.me()`                       | `GET /v1/me`                           | Account info (auth required)       |
| `am.dashboard()`                | `GET /v1/me/dashboard`                 | Usage / charges (auth required)    |
| `am.setCap(jpy)`                | `POST /v1/me/cap`                      | Monthly ¥-cap (税抜)             |
| `am.fetch(method, path, body)`  | (any endpoint)                         | Escape hatch                       |

All response types are exported (`Program`, `Loan`, `TaxRule`, `Enforcement`,
`Law`, `LawArticle`, `Meta`, `DashboardSummary`, etc.).

## Errors

```ts
import {
  AutonoMathError,
  AuthError,        // 401 / 403
  BadRequestError,  // 400 / 422
  CapReachedError,  // 402 (monthly ¥-cap)
  NotFoundError,    // 404
  RateLimitError,   // 429 — has .retryAfter (seconds)
  ServerError,      // 5xx
} from "@autonomath/sdk";

try {
  await am.searchPrograms({ q: "..." });
} catch (e) {
  if (e instanceof RateLimitError) {
    await new Promise((r) => setTimeout(r, (e.retryAfter ?? 1) * 1000));
  } else if (e instanceof CapReachedError) {
    console.warn(`monthly cap ¥${e.capJpy} reached`);
  } else {
    throw e;
  }
}
```

Retries are automatic on 429 (respects `Retry-After`) and 5xx (exponential
backoff: 500 ms → 1 s → 2 s, capped at 8 s, max 3 attempts).

## Use cases by audience

### 開発者 (Developer / agent)

Build assistant flows that pull programs + check exclusion rules in one shot:

```ts
const programs = await am.searchPrograms({ q: "DX 投資", tier: ["S", "A"] });
const ids = programs.results.map((p) => p.unified_id);
const exclusions = await am.checkExclusions(ids);
// Render: candidate programs + which combinations are mutually exclusive
```

### 税理士向け SaaS (Tax advisor SaaS)

Surface ⼩規模事業者向けの税制 rulesets next to client invoices:

```ts
const taxes = await am.searchTaxIncentives({
  q: "インボイス 軽減",
  effective_on: new Date().toISOString().slice(0, 10),
});
for (const t of taxes.results) {
  console.log(t.rule_name, t.effective_to, t.sunset_date);
}
```

### 行政書士 SaaS (Gyōseishoshi / paralegal SaaS)

Cross-reference a candidate program with the 行政処分 record of the operator:

```ts
const enforcement = await am.searchEnforcement({
  q: "宅建業法",
  authority: "国土交通省",
  decided_from: "2024-01-01",
});
```

### 金融機関 / 創業支援 (Lender / accelerator)

Surface 融資 options matching the borrower's collateral profile:

```ts
const loans = await am.searchLoans({
  q: "創業",
  collateral: "not_required",
  personal_guarantor: "not_required",
});
```

### 中小企業内製 (SMB internal automation)

Build a deadline calendar from the programs API:

```ts
const programs = await am.searchPrograms({
  q: "ものづくり",
  tier: ["S"],
  limit: 50,
});
const open = programs.results
  .map((p) => p.application_window)
  .filter((w): w is Record<string, unknown> => w !== null);
```

## MCP usage

The MCP server (93 tools, protocol 2025-06-18) is implemented in Python.
Spawn it from Node for MCP hosts:

```ts
import { spawnMcp, mcpServerConfig } from "@autonomath/sdk/mcp";

// 1. Spawn directly (host pipes stdin/stdout)
const proc = spawnMcp({ apiKey: process.env.AUTONOMATH_API_KEY });
process.stdin.pipe(proc.stdin);
proc.stdout.pipe(process.stdout);

// 2. Or generate a config blob for Claude Desktop
const cfg = mcpServerConfig({ apiKey: "am_..." });
```

For Claude Desktop, drop into `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "autonomath": {
      "command": "autonomath-mcp",
      "args": [],
      "env": { "AUTONOMATH_API_KEY": "am_..." }
    }
  }
}
```

See [MCP ツール](../mcp-tools.md) for the full tool list.

## Configuration

| Option            | Default                       | Notes                                    |
| ----------------- | ----------------------------- | ---------------------------------------- |
| `apiKey`          | `undefined`                   | `X-API-Key` header                       |
| `baseUrl`         | `https://api.jpcite.com`   | Override for self-host / staging         |
| `timeoutMs`       | `30000`                       | Per-request `AbortController`            |
| `maxRetries`      | `3`                           | 429 / 5xx                                |
| `fetch`           | global `fetch`                | Inject custom (undici, polyfill, etc.)   |
| `userAgentSuffix` | `undefined`                   | Appended to `User-Agent`                 |

## Bundle size

ESM build: 18 KB unminified, ~4 KB gzipped. Zero dependencies.

## Versioning

`@autonomath/sdk` follows the AutonoMath API version. `0.2.x` → API v1,
MCP protocol 2025-06-18.

See also: [Python SDK](https://pypi.org/project/autonomath-mcp/) ·
[REST API リファレンス](../api-reference.md) · [料金](../pricing.md)
