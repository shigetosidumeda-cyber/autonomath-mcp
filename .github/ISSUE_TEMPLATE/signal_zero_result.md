---
name: Signal — Zero result pattern
about: A query consistently returns 0 results (data gap or query-parsing bug). Convert from weekly digest.
title: "[data-gap] zero-result burst: "
labels: ["data-gap", "triage"]
---

## Signal type

Zero-result pattern (data gap or FTS tokenizer failure)

## Evidence from digest

<!-- Paste the SQL output row from weekly_digest.py verbatim. Include query text, count, and date range. -->

```
query:
count:
date range:
```

## Affected endpoint / tool

<!-- e.g. /v1/programs/search, search_programs MCP tool -->

## Heuristic check performed

<!-- Run the relevant heuristic from docs/improvement_loop.md §5 and paste output. -->

H-number checked: H__

```sql
-- query run:

-- result:
```

## Likely root cause

- [ ] Data not loaded (table empty — schema ready)
- [ ] FTS tokenizer false-negative (single-kanji overlap or phrase not quoted)
- [ ] Enum value mismatch (filter value not in canonical list)
- [ ] Prefecture has < 5 programs (geographic gap)
- [ ] Other (describe):

## Priority

<!-- Apply the decision tree from docs/improvement_loop.md §2 -->

- [ ] PC1 — top-10 query class, blocks many users
- [ ] PC2 — 中核 use case, zero results for 10+ identical queries
- [ ] PC3 — long-tail, user can work around

## Fix plan

<!-- One sentence. e.g. "Load invoice_registrants from PDL v1.0 bulk export" -->

## Definition of done

- [ ] Query returns ≥ 1 result OR a clear "no data available" message with source citation
- [ ] `pytest` passes
- [ ] Heuristic SQL confirms 0 remaining zero-result hits for this query pattern
