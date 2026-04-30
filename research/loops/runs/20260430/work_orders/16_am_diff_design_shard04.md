# OTHER CLI Research Work Order 16/32

Run ID: `20260430`
Lane: `am_diff_design` - Amendment diff design and false-positive research
Shard: `04`

## Mission

Collect read-only snapshots and design diff behavior for programs/laws likely to change. Do not write migrations, cron jobs, or production code from this loop.

## Shard Scope (yours and yours only — do NOT overlap with other shards)

Tier S programs 46-60. False-positive: reordered FAQ section without semantic change.

## Seed Inputs

- Snapshot scope: `SELECT unified_id, primary_name, source_url FROM programs WHERE tier='S' AND excluded=0 LIMIT 114` (tier S only first; expand to A in later loops).
- Per snapshot: fetch source_url, save raw HTML / PDF bytes + sha256 to data/snapshots/am_diff_{run_id}_shard{shard:02d}.json.
- Compare against any prior snapshot for the same source_url; emit diff candidates with field-level hints.

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

- Record snapshot cycle, diff algorithm candidates, false-positive patterns, and schema suggestions.
- Use difflib or structured field comparison only; no LLM extraction.
- If no previous snapshot exists, write baseline snapshot and mark diff_status=baseline_only.

## Shard Output

Write shard-level output here:

- `data/snapshots/am_diff_20260430_shard04.json`
- `analysis_wave18/loops/20260430/am_diff_design_shard04.md`

## Final Deliverable For This Lane

If you are the last or coordinating agent for this lane, merge/dedupe shard outputs into:

- `analysis_wave18/am_diff_design_2026-04-30.md`

## Previous Loop Review

No previous loop review.

## Final Response Contract

List only:

- files_written
- rows_or_objects_written
- blockers
- suggested_next_queries
