# FTS index audit + search smoke (ext tables, 2026-04-24)

Task #85. Purpose: verify that expansion-dataset search endpoints (case_studies, loan_programs, enforcement_cases, invoice_registrants) perform within launch-acceptable latency, and document whether FTS virtual tables should be added.

## FTS virtual tables currently in DB

```
programs_fts        ✓ (1.2M+ FTS entries, trigram)
laws_fts            ✓
tax_rulesets_fts    ✓
court_decisions_fts ✓ (0 rows base)
bids_fts            ✓ (0 rows base)
adoption_fts        ✓ (separate from case_studies — ingest-side staging)
ministry_faq_fts    ✓
houjin_master_fts   ✓
support_org_fts     ✓
verticals_deep_fts  ✓
```

## FTS virtual tables NOT in DB

```
case_studies_fts        (table: case_studies, 2,286 rows)
loan_programs_fts       (table: loan_programs, 108 rows)
enforcement_cases_fts   (table: enforcement_cases, 1,185 rows)
invoice_registrants_fts (table: invoice_registrants, 11,395 rows — growing via NTA load)
```

These four search endpoints use `LIKE '%q%'` OR-chains (see `src/jpintel_mcp/api/case_studies.py:154`, same pattern for the other three).

## Smoke test (5 iterations, p50/p95 across runs)

| Query | Rows | p50 | p95 | Verdict |
|---|---|---|---|---|
| case_studies q=太陽光 | 2,286 | 6.6ms | 59.2ms | OK for launch |
| loan_programs q=小規模 | 108 | 0.1ms | 2.1ms | Trivial |
| enforcement_cases q=補助金 | 1,185 | 0.5ms | 9.3ms | Trivial |
| invoice_registrants q=東京 (LIKE name+address) | 11,395 | 1.7ms | 56.3ms | OK now, risk at scale |
| invoice_registrants prefecture=東京都 (indexed) | 11,395 | 0.0ms | 0.3ms | Instant |

All LIKE-based queries land under 100ms p95 at current row counts. **No launch blocker.**

## Post-launch recommendations

1. **invoice_registrants_fts** — HIGH PRIORITY. NTA full bulk is ~4M rows. LIKE on 4M rows will cross 1s easily. Add FTS5 virtual table over `normalized_name + address_normalized + trade_name` using trigram tokenizer before the full bulk load ships. Migration slot already available.
2. **case_studies_fts** — MEDIUM. Current 2,286 will grow with additional j-グランツ採択事例 ingests. Add FTS when row count crosses ~20K or p95 > 200ms.
3. **loan_programs_fts** — SKIP (108 rows; FTS overhead > LIKE cost).
4. **enforcement_cases_fts** — LOW. Growth is slow (annual 行政処分 publication); defer until p95 > 200ms.

## What shipped in this audit

- No schema changes (audit only).
- Smoke test verified launch-readiness.
- 2 FTS tables queued for post-launch migration work.

## Method note

Same methodology as `docs/performance.md` (sqlite3 connection via Python, 5 sequential runs, picks p50 and max as rough p95 proxy).
