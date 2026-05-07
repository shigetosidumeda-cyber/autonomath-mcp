# Partial response (`?fields_partial=`)

A second size-shrinking knob on top of the existing
[`?compact=true`](compact_response.md) envelope projection. Where
`compact` is a **fixed lossy projection** (always strips the same set of
verbose fields), `fields_partial` is a **caller-defined projection** —
you list exactly which fields you need and everything else is dropped.

> Default: full envelope (back-compat preserved).
> Partial: opt-in via `?fields_partial=...` query parameter.
> Never on by default; legacy clients are never broken.

## When to use

Use `fields_partial` when:

- You inject the response straight into an **LLM prompt context** and
  only consume a few keys per row (typically `unified_id`,
  `primary_name`, `source_url`).
- You drive a **dashboard tile** that renders a fixed set of columns.
- You bulk-fetch into a CSV-style data store and the source envelope
  carries far more keys than your destination schema.

Skip `fields_partial` when you need every key (the default envelope is
already optimal) or when you only want the fixed compact projection
(use [`?compact=true`](compact_response.md) instead).

## Endpoints

`fields_partial` is wired on these REST endpoints:

| Endpoint | Method | Notes |
|----------|--------|-------|
| `/v1/programs/search`                              | GET | top-level + `results.*` |
| `/v1/programs/{unified_id}`                        | GET | top-level only (single record) |
| `/v1/laws/search`                                  | GET | top-level + `results.*` |
| `/v1/evidence/packets/{subject_kind}/{subject_id}` | GET | json output only; ignored on csv/md |

The MCP server tools do not surface `fields_partial` directly — call the
REST endpoint when you need byte-level control.

## Syntax

Comma-separated tokens. Each token is either a top-level key or a
dotted child path:

```
fields_partial=unified_id,primary_name,source_url
fields_partial=total,results.unified_id,results.primary_name
fields_partial=results.unified_id,results.tier,results.source_url
```

* Top-level token (`total`) keeps the top-level field as-is.
* Dotted token (`results.unified_id`) marks `results` as kept AND
  projects each list/dict child of `results` down to the listed
  child fields only.
* Whitespace around tokens is trimmed.
* Unknown / typo'd tokens are silently ignored — they will not error
  out the request, but they will not magically materialize either.

## Always-included (protected) fields

These fields are part of the legal / audit / billing envelope and are
**always** returned regardless of your projection:

- `_disclaimer` (and `_disclaimer_en`)
- `corpus_snapshot_id`
- `corpus_checksum`
- `audit_seal`
- `_billing_unit`

The reason: they identify which corpus the answer was computed against,
attribute the data to its primary source under 景表法 / 消費者契約法,
and persist the per-call audit trail. Stripping any of them would
orphan the response from its provenance and break downstream
reproducibility (会計士 audit, Stripe metered reconciliation,
compliance review). The server enforces this even if you list a
narrower projection.

## Example: `/v1/programs/search`

Full response (default):

```bash
curl "https://api.jpcite.com/v1/programs/search?tier=A&limit=3"
```

Returns ~3,300 bytes. Each row carries `unified_id`, `primary_name`,
`tier`, `authority_level`, `authority_name`, `prefecture`,
`program_kind`, `amount_max_man_yen`, `subsidy_rate`,
`funding_purpose[]`, `target_types[]`, `official_url`, `source_url`,
`source_fetched_at`, `next_deadline`, plus the envelope wrapper.

Partial response (LLM-context optimised):

```bash
curl "https://api.jpcite.com/v1/programs/search?tier=A&limit=3&fields_partial=total,results.unified_id,results.primary_name"
```

Returns ~420 bytes — the same `total` + a 2-key projection of each
`results[]` row, plus the protected envelope. Approximately **87%
size reduction** observed on this query against the production
corpus.

Sample sizes (measured against `data/jpintel.db` snapshot, tier=A,
limit=3):

```
{"full": 3295, "fields=total,results.unified_id,results.primary_name": 419, "reduction": "87.3%"}
```

## Pricing posture

`fields_partial` does **not** change the per-request charge
(¥3 / unituest, 税込 ¥3.30 — see the pricing page). It only changes the
response payload size. The intent is to reduce *your* downstream LLM
input-token cost, not to discount jpcite billing.

## Combining with other knobs

| Knob | Layer | Role |
|------|-------|------|
| `fields=minimal\|default\|full`        | DB-side | which columns are loaded |
| `compact=true`                         | envelope | fixed lossy projection |
| `fields_partial=...`                   | envelope | caller-defined projection |

You can combine them. `fields_partial` runs LAST in the pipeline so it
sees whatever the prior layers produced. Common combo:

```bash
curl "https://api.jpcite.com/v1/programs/search?fields=minimal&fields_partial=total,results.unified_id,results.primary_name"
```

This loads only the minimal column whitelist from the DB AND applies
your final-mile projection on the JSON envelope.

## OpenAPI

The `fields_partial` parameter appears on each enabled endpoint in
`docs/openapi/v1.json`. Regenerate after server upgrades:

```bash
.venv/bin/python scripts/export_openapi.py --out docs/openapi/v1.json
```

## Stability

Backwards-compatible. Adding `fields_partial=...` to an existing call
will only ever return *fewer* keys; it cannot inject new keys. Removing
the parameter restores the full default envelope. Safe to deploy in
front of legacy SDKs that ignore unknown query parameters.
