# OTHER CLI Research Work Order 22/32

Run ID: `20260430`
Lane: `consultant_firms` - Consultant and firm list for direct outreach
Shard: `06`

## Mission

Build a primary-source list of likely customers or partners: certified tax accountants, administrative scriveners, SME consultants, subsidy consultants, and RAG/LLM implementation shops with Japan-facing evidence workflows.

## Shard Scope (yours and yours only — do NOT overlap with other shards)

category=中小企業診断士, region=全国 (協会所属 + 補助金実績公開あり).

## Seed Inputs

- 中小企業庁 認定支援機関 検索: https://ninteishien.force.com/NSK_NinteiKensaku
- 日本行政書士会連合会: https://www.gyosei.or.jp/information/ (各都道府県会名簿経由)
- 中小企業診断協会: https://www.j-smeca.jp/ (会員検索)
- 全国社会保険労務士会連合会: https://www.shakaihokenroumushi.jp/ (会員名簿)
- 日本税理士会連合会: https://www.nichizeiren.or.jp/taxaccount/find/

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

- Final CSV should contain 100+ rows if enough primary-source candidates exist.
- CSV columns: name, category, region, public_url, contact_url, evidence_url, why_relevant, notes.
- Do not invent emails; leave contact_url blank if no public contact page is found.

## Shard Output

Write shard-level output here:

- `analysis_wave18/loops/20260430/consultant_firms_shard06.csv`

## Final Deliverable For This Lane

If you are the last or coordinating agent for this lane, merge/dedupe shard outputs into:

- `analysis_wave18/consultant_firms_2026-04-30.csv`

## Previous Loop Review

No previous loop review.

## Final Response Contract

List only:

- files_written
- rows_or_objects_written
- blockers
- suggested_next_queries
