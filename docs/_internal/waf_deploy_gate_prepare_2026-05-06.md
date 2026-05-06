# WAF / Deploy Gate Prepare 2026-05-06

Owner scope: WAF and production deploy gate preparation only. Do not change
application code from this runbook.

## Source check

Cloudflare's current WAF docs say custom rules filter incoming requests and
can Block, Managed Challenge, or Skip matching traffic. Rules are evaluated in
order, and terminating actions stop later rules for that request:
https://developers.cloudflare.com/waf/custom-rules/

Cloudflare documents Skip as a selective bypass for security products that
would otherwise block or challenge legitimate traffic. Skip is not the same as
IP Access Allow; Allow can bypass WAF custom rules entirely, while Skip can be
limited to selected products/phases:
https://developers.cloudflare.com/waf/custom-rules/skip/
https://developers.cloudflare.com/waf/troubleshooting/phase-interactions/

Cloudflare bot docs also note path-specific bot handling belongs in WAF custom
rules, while global AI-bot toggles / managed robots behavior apply broadly:
https://developers.cloudflare.com/bots/additional-configurations/custom-rules/

## jpcite WAF policy

Goal: protect paid/API/data/admin surfaces without breaking AI discovery.

Protect with WAF custom rules, rate limits, or managed challenge:

- `api.jpcite.com/v1/*`
- `api.jpcite.com/mcp*` if exposed over HTTP
- `/v1/*`, `/api/*`, `/data/*`, `/admin/*`, `/billing/*`, `/dashboard*`
- Auth, webhook, export, search, and high-cost compute paths
- Unknown methods on API hosts, especially non-GET/HEAD/OPTIONS unless the
  endpoint explicitly needs them

Keep open for AI discovery and public indexing:

- `/llms.txt`, `/llms.en.txt`, `/en/llms.txt`
- `/openapi*.json`, `/openapi/*.json`
- `/mcp-server.json`, `/mcp-server.full.json`, `/server.json`
- `/docs/*`, `/getting-started*`, `/mcp-tools*`, `/api-reference*`
- `/robots.txt`, `/sitemap*.xml`, `/status*`, `/healthz`
- `/qa/*`, `/qa/llm-evidence/*`, `/qa/mcp/*`
- Public docs, pricing, integrations, changelog, examples, and launch pages

Do not enable a blanket "Block AI bots" or managed robots.txt policy across
the whole zone without explicit exceptions for the discovery paths above. The
product depends on LLMs finding `llms.txt`, OpenAPI, MCP manifests, docs,
robots, status, and QA evidence routes.

Preferred order:

1. Early Skip rule for the discovery allowlist above. Skip only the security
   product causing false positives; do not use broad IP Access Allow.
2. Block/challenge obvious abuse on API/data/admin surfaces.
3. Rate-limit expensive API/search/MCP surfaces by IP/API key where available.
4. Log-only canary before enforcement when changing rule expressions.

## Deploy gate risk

The existing production seed gate used `programs > 10000` as the catalog
sentinel. Current DB observations for this handoff are:

- `programs=0`
- `jpi_programs=13578`

That means a deploy can fail even when the production catalog is present in
`jpi_programs`. The gate should accept either table while migrations are in
this transitional state:

```text
max(count(programs), count(jpi_programs)) >= 10000
```

The post-deploy functional smoke remains separate: `/v1/programs/search` must
return `total > 0` because that validates the served search path, not just raw
table size.

## Kill switch smoke base URL

Production smoke and kill-switch checks must target:

```bash
BASE_URL=https://api.jpcite.com
```

Do not use `https://jpcite.com` for API kill-switch smoke. The apex is the
public/docs surface and may stay healthy while API routing or Fly origin is
degraded.
