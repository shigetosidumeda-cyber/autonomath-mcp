# TypeScript / JavaScript

TypeScript / JavaScript から jpcite API を呼び出すためのガイドです。現時点では公開 npm package はありません。Node 20+、Deno、Bun、modern browsers では global `fetch` で REST API を直接呼べます。

公開 npm package が出るまでは REST API を直接呼ぶか、MCP server を利用してください。

## REST fetch quickstart

TypeScript package は公開準備中です。現時点では REST API を直接呼ぶか、MCP server を利用してください。

Node から MCP server を起動する場合は、Python 側の MCP package も入れてください。

```bash
pip install autonomath-mcp
```

## Quickstart

```ts
const apiKey = process.env.JPCITE_API_KEY; // optional; anonymous = 3 req/day
const baseUrl = "https://api.jpcite.com";

const params = new URLSearchParams({
  q: "省エネ",
  prefecture: "東京都",
  limit: "10",
});

const res = await fetch(`${baseUrl}/v1/programs/search?${params}`, {
  headers: apiKey ? { "X-API-Key": apiKey } : {},
});
if (!res.ok) {
  throw new Error(`jpcite API error: ${res.status}`);
}

const programs = await res.json();
for (const p of programs.results ?? []) {
  console.log(p.unified_id, p.primary_name, p.amount_max_man_yen);
}
```

## Authentication

Send the key as `X-API-Key`. Issue keys from your [dashboard](https://jpcite.com/dashboard).

`JPCITE_API_KEY` is a jpcite REST/MCP key, not an OpenAI / Anthropic /
Gemini key. Use `JPCITE_API_KEY` for new integrations.

Without an API key, anonymous IPs get 3 requests per day (resets at the next
JST 00:00).

## Planned SDK wrapper names

| Method                          | REST endpoint                          | Notes                              |
| ------------------------------- | -------------------------------------- | ---------------------------------- |
| `client.healthz()`                  | `GET /healthz`                         | Free liveness check                |
| `client.meta()`                     | `GET /meta`                            | Catalog totals                     |
| `client.searchPrograms(params)`     | `GET /v1/programs/search`              | 11,684 補助金/助成金/認定        |
| `client.getProgram(id)`             | `GET /v1/programs/{id}`                | Full enriched detail               |
| `client.searchLoans(params)`        | `GET /v1/loan-programs/search`         | 三軸 collateral/guarantor 分解   |
| `client.getLoan(id)`                | `GET /v1/loan-programs/{id}`           |                                    |
| `client.searchTaxIncentives(p)`     | `GET /v1/tax_rulesets/search`          | インボイス / 電帳法 etc.         |
| `client.getTaxIncentive(id)`        | `GET /v1/tax_rulesets/{id}`            |                                    |
| `client.searchEnforcement(params)`  | `GET /v1/enforcement-cases/search`     | 1,185 行政処分                    |
| `client.getEnforcement(id)`         | `GET /v1/enforcement-cases/{id}`       |                                    |
| `client.getLaw(id)`                 | `GET /v1/laws/{id}`                    | e-Gov, CC-BY                       |
| `client.getLawArticle(id, art)`     | See REST API reference                 |                                    |
| `client.listExclusionRules()`       | `GET /v1/exclusions/rules`             | 181 排他/前提ルール              |
| `client.checkExclusions(ids)`       | `POST /v1/exclusions/check`            |                                    |
| `client.me()`                       | `GET /v1/me`                           | Account info (auth required)       |
| `client.dashboard()`                | `GET /v1/me/dashboard`                 | Usage / charges (auth required)    |
| `client.setCap(jpy)`                | `POST /v1/me/cap`                      | Monthly ¥-cap (税抜)             |
| `client.fetch(method, path, body)`  | (any endpoint)                         | Escape hatch                       |

The method names are planned SDK wrappers. Until the npm package is public, use the REST endpoints directly.

## Errors

```ts
const res = await fetch(`${baseUrl}/v1/programs/search?q=DX`, {
  headers: apiKey ? { "X-API-Key": apiKey } : {},
});

if (res.status === 429) {
  const retryAfter = Number(res.headers.get("Retry-After") ?? "1");
  await new Promise((r) => setTimeout(r, retryAfter * 1000));
} else if (res.status === 402) {
  throw new Error("monthly cap reached");
} else if (!res.ok) {
  throw new Error(`jpcite API error: ${res.status}`);
}
```

When you build your own wrapper, retry 429 (respect `Retry-After`) and transient
5xx responses with capped exponential backoff.

## Use cases by audience

### 開発者 (Developer / agent)

Build assistant flows that pull programs + check exclusion rules in one shot:

```ts
const programs = await searchPrograms({ q: "DX 投資", tier: ["S", "A"] });
const ids = programs.results.map((p) => p.unified_id);
const exclusions = await checkExclusions(ids);
// Render: candidate programs + which combinations are mutually exclusive
```

### 税理士向け SaaS (Tax advisor SaaS)

Surface ⼩規模事業者向けの税制 rulesets next to client invoices:

```ts
const taxes = await searchTaxIncentives({
  q: "インボイス 軽減",
  effective_on: new Date().toISOString().slice(0, 10),
});
for (const t of taxes.results) {
  console.log(t.rule_name, t.effective_to, t.sunset_date);
}
```

### 行政書士 SaaS (Gyōseishoshi / paralegal SaaS)

候補制度と関連しそうな行政処分情報をあわせて確認します。

```ts
const enforcement = await searchEnforcement({
  q: "宅建業法",
  authority: "国土交通省",
  decided_from: "2024-01-01",
});
```

### 金融機関 / 創業支援 (Lender / accelerator)

Surface 融資 options matching the borrower's collateral profile:

```ts
const loans = await searchLoans({
  q: "創業",
  collateral: "not_required",
  personal_guarantor: "not_required",
});
```

### 中小企業内製 (SMB automation)

Build a deadline calendar from the programs API:

```ts
const programs = await searchPrograms({ q: "ものづくり", tier: ["S"], limit: 50 });
const open = programs.results
  .map((p) => p.application_window)
  .filter((w): w is Record<string, unknown> => w !== null);
```

## MCP usage

MCP server (96 tools, protocol 2025-06-18) を Claude Desktop から起動する例です。

For Claude Desktop, drop into `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "jpcite": {
      "command": "autonomath-mcp",
      "args": [],
      "env": { "JPCITE_API_KEY": "am_..." }
    }
  }
}
```

See [MCP ツール](../mcp-tools.md) for the full tool list.

## Configuration

| Option            | Default                       | Notes                                    |
| ----------------- | ----------------------------- | ---------------------------------------- |
| `apiKey`          | `undefined`                   | `X-API-Key` header                       |
| `baseUrl`         | `https://api.jpcite.com`   | API base URL                             |
| `timeoutMs`       | `30000`                       | Per-request `AbortController`            |
| `maxRetries`      | `3`                           | 429 / 5xx                                |
| `fetch`           | global `fetch`                | Inject custom (undici, polyfill, etc.)   |
| `userAgentSuffix` | `undefined`                   | Appended to `User-Agent`                 |

## Bundle size

No npm package is published yet, so bundle size is not stated here.

## Versioning

The TypeScript package is pre-release. API v1 is the REST contract; package naming remains compatibility-bound until public npm release.

See also: [Python MCP package](https://pypi.org/project/autonomath-mcp/) ·
[REST API リファレンス](../api-reference.md) · [料金](../pricing.md)
