# OTHER CLI Research Work Order 09/32

Run ID: `20260430`
Lane: `url_liveness` - Tier A and tier S official URL liveness
Shard: `03`

## Mission

Check official/source URLs for reachable status, redirect target, PDF/HTML type, staleness hints, and broken or placeholder origins. Target Tier A first; include tier S rescans if the shard has capacity.

## Shard Scope (yours and yours only — do NOT overlap with other shards)

Tier A, prefecture in (神奈川県, 新潟県, 富山県, 石川県, 福井県, 山梨県). Approx 168 rows.

## Seed Inputs

- Source query: `SELECT unified_id, primary_name, source_url, prefecture, tier FROM programs WHERE tier='A' AND excluded=0` against data/jpintel.db (1,340 rows expected).
- Skip rows with NULL source_url or aggregator domains (noukaweb / hojyokin-portal / biz.stayway).
- Tier S rescan target: WHERE tier='S' AND source_url_status='broken' (after migration 118 lands; ~13 rows from the 2026-04-30 audit).

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

- Record status_code, final_url, content_type, checked_at, tier, source_table/source_id if known.
- Classify each URL as ok, redirect, soft_404, hard_404, timeout, blocked, placeholder, or non_primary.
- Final file should target Tier A 1,340 rows when source selection is available.

## Shard Output

Write shard-level output here:

- `analysis_wave18/loops/20260430/url_liveness_shard03.json`

## Final Deliverable For This Lane

If you are the last or coordinating agent for this lane, merge/dedupe shard outputs into:

- `analysis_wave18/url_liveness_2026-04-30.json`

## Previous Loop Review

No previous loop review.

## Final Response Contract

List only:

- files_written
- rows_or_objects_written
- blockers
- suggested_next_queries
