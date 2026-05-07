# W20 — am_amount_condition Quality-Tier Validation Report

- Generated: `2026-05-05T02:49:07.278245+00:00`
- DB: `/Users/shigetoumeda/jpcite/autonomath.db`
- Mode: `APPLIED`
- Migration applied: `150_am_amount_condition_quality_tier.sql`
- Script: `scripts/etl/revalidate_amount_conditions.py`

## Why

`am_amount_condition` holds 250,946 rows; the majority were filled by a
broken ETL pass that copied the program ceiling into every per-record
row (¥500K / ¥2M / and 6 other round-number buckets). Surfacing those
values via the ¥3/billable unit metered API would create 詐欺 risk under
景表法 / 消費者契約法. Migration 150 added a 3-tier `quality_tier`
column. This script reclassifies every row by:

1. **verified** — `extracted_text` literally contains the `fixed_yen`
   as digits, 万 form, or 億 form.
2. **template_default** — `fixed_yen` belongs to a dynamic
   template-bucket cluster (count >= 200 AND
   non-empty-extracted_text rate < 0.5%).
3. **unknown** — anything else (NULL fixed_yen, sparse one-off values,
   or rows whose extracted_text does not mention the value).

The surface side filters `quality_tier = 'verified'` for customer-facing
output. `template_default` and `unknown` rows remain on disk for audit
but are NOT exposed via the metered API.

## Tier distribution

| Tier               | Before script | After script | Share |
|--------------------|--------------:|-------------:|------:|
| verified           |           116 |          116 |  0.05% |
| template_default   |       240,109 |      240,109 | 95.68% |
| unknown            |        10,721 |       10,721 |  4.27% |
| **TOTAL**          |       250,946 |      250,946 | 100.00% |

## Detected template-default buckets

`fixed_yen` values with count >= 200 rows, sorted by
size. The `with_text` column counts rows in that bucket whose
`extracted_text` is non-empty. Buckets where `with_text/total <
0.5%` are flagged as template defaults.

| fixed_yen | total_n | with_text | text_ratio | template? |
|----------:|--------:|----------:|-----------:|:---------:|
|   3,500,000 |    72,918 |     0 |  0.000% | yes |
|     500,000 |    61,363 |   106 |  0.173% | yes |
|  12,500,000 |    49,210 |     0 |  0.000% | yes |
|   4,500,000 |    32,392 |     0 |  0.000% | yes |
|  70,000,000 |    16,379 |     0 |  0.000% | yes |
|  15,000,000 |     5,077 |     5 |  0.098% | yes |
|   2,000,000 |     2,606 |   108 |  4.144% | no |
|  90,000,000 |     1,887 |     0 |  0.000% | yes |
|   1,500,000 |       661 |     1 |  0.151% | yes |
|  30,000,000 |       413 |     7 |  1.695% | no |
|   1,000,000 |       244 |   125 | 51.230% | no |
|           0 |       222 |     0 |  0.000% | yes |

Total template buckets flagged: **9**.

## API filter convention

Surface tools (current and future) MUST filter:

```sql
SELECT ... FROM am_amount_condition
 WHERE quality_tier = 'verified'
   -- AND (whatever else)
```

The legacy `template_default = 0` filter is now a SUBSET of the new
filter (every row with template_default=0 is either verified or
unknown). The new filter is stricter and safer.

## Operator next actions

1. Increase `verified` share by extracting `extracted_text` from source
   PDFs/HTML in `tools/offline/` (operator-LLM, NOT runtime). Each such
   re-extraction promotes a row from `unknown` -> `verified` for free.
2. Re-run this script monthly (or via a cron) to catch newly-emerged
   template buckets after fresh ingest waves.
3. Wire the API filter into any new tool that joins `am_amount_condition`
   (see `src/jpintel_mcp/mcp/autonomath_tools/gx_tool.py` for the
   reference convention).
