# 税務会計AI — SDK Samples

Paste-and-run scripts in 5 languages. **Zero dependencies, no build step.**
Each script reads `ZEIMU_KAIKEI_API_KEY` from env (or runs anonymous: 50 req/月 per IP).

> 注: 本SDKは情報検索のみ。税理士法 §52 により、個別税務助言は税理士にご相談ください。

## Index

| Language       | File                                              | What it does                                                                               | Run                            |
| -------------- | ------------------------------------------------- | ------------------------------------------------------------------------------------------ | ------------------------------ |
| JavaScript     | [`javascript/quickstart.js`](./javascript/quickstart.js)             | Search programs by keyword + list tax incentives (50 lines, fetch)                          | `node quickstart.js`           |
| JavaScript     | [`javascript/search-and-filter.js`](./javascript/search-and-filter.js) | Paginated search with `prefecture` + `tier` + `funding_purpose` filter chain + 429/5xx retry | `node search-and-filter.js`    |
| Go             | [`go/quickstart.go`](./go/quickstart.go)                              | Search + tax incentives (stdlib `net/http`, no go.mod needed)                              | `go run quickstart.go`         |
| Go             | [`go/search-and-filter.go`](./go/search-and-filter.go)                | Paginated filter chain + retry-after + exponential backoff                                  | `go run search-and-filter.go`  |
| Ruby           | [`ruby/quickstart.rb`](./ruby/quickstart.rb)                          | Search + tax incentives (stdlib `Net::HTTP` + `JSON`, no gems)                              | `ruby quickstart.rb`           |
| PHP            | [`php/quickstart.php`](./php/quickstart.php)                          | Search + tax incentives (cURL extension, no Composer)                                       | `php quickstart.php`           |
| curl / bash    | [`curl/quickstart.sh`](./curl/quickstart.sh)                          | Five representative `curl` calls: healthz, meta, search, tax_rulesets, filter chain         | `bash quickstart.sh`           |

## Auth

Two paths:

- **Anonymous** (no key set): 50 req/月 per IP. JST 月初 00:00 リセット. Best for evaluation.
- **Authenticated** (set `ZEIMU_KAIKEI_API_KEY=sk_xxx`): ¥3 / req metered (税込 ¥3.30). Get a key from <https://zeimu-kaikei.ai/pricing>.

```bash
export ZEIMU_KAIKEI_API_KEY=sk_xxx_your_key_here
node sdk/samples/javascript/quickstart.js
```

## Endpoint surface used in samples

All samples hit the documented public REST API at `https://api.zeimu-kaikei.ai/v1`:

| Endpoint                              | Used by                                   |
| ------------------------------------- | ----------------------------------------- |
| `GET /healthz`                        | curl                                      |
| `GET /v1/meta`                        | curl                                      |
| `GET /v1/programs/search`             | all                                       |
| `GET /v1/tax_rulesets/search`         | js, go, ruby, php, curl                   |

Full endpoint catalog: <https://api.zeimu-kaikei.ai/v1/openapi.json>.

## Error handling cheatsheet (all samples)

| HTTP | Meaning                                | Fix                                                    |
| ---- | -------------------------------------- | ------------------------------------------------------ |
| 401  | Auth failed                            | Check `ZEIMU_KAIKEI_API_KEY` value                     |
| 403  | Key revoked or quota exhausted         | Visit <https://zeimu-kaikei.ai/dashboard>             |
| 404  | Path or `unified_id` not found         | Verify path against `/v1/openapi.json`                 |
| 429  | Rate limited                           | Honor `Retry-After` header (samples retry up to 2x)    |
| 5xx  | Server error                           | Exponential backoff (samples retry 0.5s/1s/2s)         |

## Want a real client library?

- **Python**: `pip install autonomath-mcp` — full client + MCP server in one package.
- **TypeScript / Node**: `npm install @autonomath/sdk` — typed client with retry + MCP spawn helper.

The samples in this directory are intentionally lightweight (single-file, paste-and-run). Use the published packages above if you want typed responses, retry policy, and OpenAPI-generated models.

## Compliance notes

- These scripts query a public REST API; they do **not** call any LLM API.
- The API returns Japanese institutional data (subsidy / tax / law records) — it does not generate tax advice.
- §52 disclaimer: every sample includes a header comment reminding users that individual tax advice requires a licensed 税理士 (Certified Public Tax Accountant).
