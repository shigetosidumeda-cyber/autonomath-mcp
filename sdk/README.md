# jpcite SDKs

Official client SDKs for the jpcite REST API.

| Language   | Package               | Path                                         |
| ---------- | --------------------- | -------------------------------------------- |
| Python     | `autonomath`          | [`sdk/python`](./python)                     |
| TypeScript | `@autonomath/sdk`     | [`sdk/typescript`](./typescript)             |

## Current status

Both SDKs are hand-written wrappers over `https://api.jpcite.com`. Python is
currently installed from `sdk/python`; TypeScript is packaged as
`@autonomath/sdk` and mirrors the REST + optional MCP helper surface. The
minimal endpoint coverage is:

- `GET /meta`, `GET /healthz`
- `GET /v1/programs/search`
- `GET /v1/programs/{unified_id}`
- `GET /v1/exclusions/rules`
- `POST /v1/exclusions/check`

Shared behavior:

- `X-API-Key` auth (Bearer also accepted server-side, but SDKs default to header).
- Retries: `429` respects `Retry-After`, `5xx` exponential backoff (max 3 retries).
- Typed models (Pydantic on Python, TypeScript interfaces on TS).
- Sync + async in Python; async-only in TS (fetch is async by nature).
- User-Agent: `autonomath-python/{ver}` / `@autonomath/sdk/{ver}`.

## Future: OpenAPI-generated SDKs

FastAPI already publishes an OpenAPI document at `/openapi.json`. Once the
schema stabilizes we plan to switch to generated SDKs so we can stop hand-
syncing types.

Planned pipeline:

```
# Python
datamodel-code-generator --input openapi.json --output sdk/python/jpintel/_generated.py

# TypeScript
npx openapi-typescript https://api.jpcite.com/v1/openapi.json -o sdk/typescript/src/_generated.ts
# (optionally openapi-fetch on top for a typed request helper)
```

The hand-written `Client` / `AsyncClient` stays as a thin, ergonomic layer on
top of the generated types (endpoint methods, retry logic, auth). Only the
model files (`types.py`, `types.ts`) become generated.

### When to switch

- Server schema has been stable for one minor release cycle.
- Field names in `Program` / `ExclusionRule` are locked.
- Tier / enum strings are finalized in `docs/canonical/`.

Target: end of **Week 4**. Until then we accept the hand-sync cost; the
surface is small (6 endpoints, ~7 model types) and we would rather take fast
breaking changes now than maintain a generator over a moving schema.

## API surface notes

Things observed while writing the SDKs that we may want to tighten on the
server side before generating clients:

- `a_to_j_coverage` is typed as `dict[str, Any]` on the server; generated
  clients will render it as `Record<string, unknown>`. Consider splitting into
  a proper model once the coverage dimensions stabilize.
- `application_window` is `dict | None` - same note.
- `ExclusionRule.extra` is a free-form dict.
- `tier` is a closed enum `S|A|B|C|X` - already narrow, ideal for codegen.
- `GET /v1/programs/search` has no pagination cursor; the SDK exposes
  `limit`/`offset` directly, matching the server. Consider a `next_offset`
  convenience field in the response before we generate so pagination helpers
  can be code-generated uniformly.

## Developing

Python:

```bash
cd sdk/python
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

TypeScript:

```bash
cd sdk/typescript
npm install
npm run typecheck
npm test
npm run build
```
