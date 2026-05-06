# autonomath (Python SDK)

Python client for the [jpcite](https://jpcite.com) REST API - a catalog
of Japanese institutional programs (subsidies, loans, tax incentives) with an
exclusion-rule engine.

## Install

```bash
pip install autonomath
```

(Currently unpublished; install locally with `pip install -e path/to/sdk/python`.)

## Quick start

```python
from autonomath import Client

c = Client(api_key="am_...")  # or leave None for anonymous free tier

meta = c.meta()
print(meta.total_programs, meta.tier_counts)

resp = c.search_programs(tier=["S", "A"], prefecture="東京都", limit=10)
for p in resp.results:
    print(p.unified_id, p.primary_name, p.tier)

detail = c.get_program(resp.results[0].unified_id)
print(detail.enriched)

check = c.check_exclusions([p.unified_id for p in resp.results])
for hit in check.hits:
    print(hit.rule_id, hit.severity, hit.programs_involved)

packet = c.get_evidence_packet("program", resp.results[0].unified_id)
print(packet.quality.known_gaps)

match = c.intel_match(industry_jsic_major="E", prefecture_code="13", keyword="DX")
print(match.total_candidates)
```

## Evidence / intel helpers

The SDK includes typed wrappers for:

- `get_evidence_packet(kind, id)` / `query_evidence_packet(...)`
- `intel_match(...)`
- `intel_bundle_optimal(...)`
- `get_intel_houjin_full(houjin_id, ...)`
- `check_funding_stack(program_ids)`

`check_funding_stack(...).next_actions` values are typed action objects with
`action_id`, `label_ja`, `detail_ja`, `reason`, and `source_fields`.

## Async

```python
import asyncio
from autonomath import AsyncClient

async def main():
    async with AsyncClient(api_key="am_...") as c:
        meta = await c.meta()
        print(meta.total_programs)

asyncio.run(main())
```

## Configuration

| Option        | Default                     | Notes                                         |
| ------------- | --------------------------- | --------------------------------------------- |
| `api_key`     | `None`                      | `X-API-Key` header. `None` = anonymous/free.  |
| `base_url`    | `https://api.jpcite.com` | Override for self-hosted deployments.         |
| `timeout`     | `30.0`                      | Per-request seconds.                          |
| `max_retries` | `3`                         | Applied to 429 and 5xx responses.             |

Retry behavior:

- `429 Too Many Requests` respects the `Retry-After` header (seconds).
- `5xx` retried with exponential backoff (0.5s, 1s, 2s, ...).
- 4xx other than 429 are raised immediately.

## Errors

All SDK errors inherit from `autonomath.AutonoMathError`:

- `AuthError` (401 / 403)
- `NotFoundError` (404)
- `RateLimitError` (429, carries `retry_after`)
- `ServerError` (5xx)

`autonomath.JpintelError` is retained as a deprecated alias for `AutonoMathError`.
New code should import `AutonoMathError`.

## Develop

```bash
cd sdk/python
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```
