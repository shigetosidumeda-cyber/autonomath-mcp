# OTHER CLI Research Work Order 03/32

Run ID: `20260430`
Lane: `pdf_structure` - Government PDF extraction research
Shard: `01`

## Mission

Inspect public grant/program PDFs and map extractable fields by publisher/domain. This loop produces parser requirements, not production parser code.

## Shard Scope (yours and yours only — do NOT overlap with other shards)

publisher_domain ⊆ {meti.go.jp, smrj.go.jp}. ものづくり / 中小企業庁 系 公募要領.

## Seed Inputs

- Source query: `SELECT source_url FROM programs WHERE tier IN ('S','A') AND source_url LIKE '%.pdf'` against data/jpintel.db.
- Tier S has 114 rows, Tier A has 1,340 rows; expect ~30% to be direct-PDF source_url. Targets: ~430 PDFs total.
- Use pdfplumber + regex; do NOT call any text extraction LLM.

## Hard Constraints

- Do not call any LLM API or hosted model API. Use regex, rules, difflib, sqlite, pdfplumber, csv/json tooling only.
- Do not use aggregator sites as evidence: noukaweb, hojyokin-portal, biz.stayway, or similar portals are discovery hints only.
- Respect robots.txt, crawl-delay, rate limits, and public-source terms.
- Do not propose tier SKUs, subscription tiers, or changes to the ¥3/request metered model.
- Do not write to src/, scripts/, .github/, docs/_internal/, fly.toml, server.json, smithery.yaml, or deployment files.
- Write job definitions and run logs only under research/loops/.
- Write research outputs only to analysis_wave18/, data/snapshots/, or data/structured_facts/.
- Do not estimate work-hours or calendar schedules. Return evidence and next concrete questions only.

## Evidence Rules

- For each PDF, record source_url, publisher_domain, page_count, text_extractable, tables_detected, fields_found.
- Fields of interest: deadline, eligible_applicant, subsidy_rate, max_amount, required_docs, contact, update_date.
- Include parser_risk: low, medium, high, or blocked, with the reason.

## Shard Output

Write shard-level output here:

- `data/structured_facts/research_20260430/pdf_structure_shard01.json`

## Final Deliverable For This Lane

If you are the last or coordinating agent for this lane, merge/dedupe shard outputs into:

- `analysis_wave18/pdf_extraction_research_2026-04-30.md`

## Previous Loop Review

No previous loop review.

## Final Response Contract

List only:

- files_written
- rows_or_objects_written
- blockers
- suggested_next_queries
