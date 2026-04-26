# Cache architecture (4-Layer L0–L4)

AutonoMath's API is built on a **Pre-computed Reasoning Layer**: customer
queries do not trigger ad-hoc joins, FTS scans, or multi-tool plans at
request time. Every shape an answer can take has already been computed
overnight, or is being served straight from a hot cache row. This page
explains the four layers, why each one exists, and where the boundary
between them lives.

## Why a 4-layer split

A single ¥3 request must amortise:

- One FTS / index lookup (cheap, ~µs).
- Zero or more cross-table joins (medium, ~ms).
- Zero or more cross-database lookups (medium, ~ms — `jpintel.db` ⇄
  `autonomath.db` are not ATTACH-joinable, two connections required).
- Response serialisation (medium, ~ms — JSON encoding dominates p95 for
  high-cardinality enums).

Caching only the bottom layer (page cache) breaks down because page cache
is per-connection and cold on every Fly machine restart. Caching only the
top (full response blob) wastes storage on rare params. So we split the
work into **four cooperating layers**, each with its own freshness
contract:

| Layer | Name | Storage | Freshness | Rebuild cost |
| ----- | ---- | ------- | --------- | ------------ |
| **L0** | Storage | Raw SQLite + FTS5 | Every ingest write | Hours (full reingest) |
| **L1** | Atomic | Single-row lookups via primary key / index | Live | Microseconds |
| **L2** | Composite | Joins across tables | Live | Milliseconds |
| **L3** | Reasoner | `pc_*` materialized views | Nightly | Minutes |
| **L4** | Cache | `l4_query_cache` blobs | Per-row TTL | Microseconds (hit) / L3 cost (miss) |

## L0 — Storage

The on-disk SQLite files plus their FTS5 trigram indexes.

- `data/jpintel.db` (188 MB): `programs`, `case_studies`, `loan_programs`,
  `enforcement_cases`, `laws`, `court_decisions`, `bids`, `tax_rulesets`,
  `invoice_registrants`, plus the join tables `program_law_refs` and
  `enforcement_decision_refs`.
- `autonomath.db` (8.29 GB, unified primary as of 2026-04-25): the entity-fact
  EAV schema (`am_entities`, `am_entity_facts`, `am_relation`, `am_alias`,
  `am_authority`, `am_region`, ...). Owned by the data-collection CLI;
  the API repo opens it read-only.

L0 is the only layer that holds ground truth. Every other layer is a
projection or cache of L0 rows — corruption here is the only thing that
cannot be recovered without a re-ingest.

## L1 — Atomic queries

Single-row primary-key or unique-index lookups:

- `SELECT * FROM programs WHERE program_id = ?`
- `SELECT * FROM laws WHERE law_id = ?`

These are too cheap to cache (b-tree depth 3–4, < 1 µs warm). The API
serves them straight from L0.

## L2 — Composite joins

Multi-row reads that join 2–3 tables:

- "Programs that cite law X" → `programs ⨝ program_law_refs`
- "Loans within Y prefecture" → `loan_programs ⨝ region`
- "Adoptions for FY 2025" → `adoption_records ⨝ programs`

These are still served live — SQLite's planner handles them in single-
digit milliseconds with the right indexes — but they are the input to
**L3** materialized views below.

## L3 — Reasoner (the `pc_*` layer)

Multi-tool, multi-DB, or aggregate queries are pre-computed nightly into
the `pc_*` tables. As of migration 045 (2026-04-25) there are 32 such
tables on disk (14 from migration 044 + 18 from migration 045). The v8
plan target counts a broader "pre-computed table" definition that includes
the 19 baseline materialized representations (FTS5 trigram indexes,
`programs` denormalised rollups, ...) — counted that way the on-disk
total is 19 + 32 = 51 representations covering the L3 surface, comfortably
ahead of the T+90d 47 milestone.

The 14 tables added in migration 044:

| # | Table | Dimension | Purpose |
| - | ----- | --------- | ------- |
| 1 | `pc_top_subsidies_by_industry` | industry × top 20 | Faster industry-filter responses |
| 2 | `pc_top_subsidies_by_prefecture` | 47 prefectures × top 20 | Faster region-filter responses |
| 3 | `pc_law_to_program_index` | `law_id` → `program_ids[]` | Citation graph lookup |
| 4 | `pc_program_to_amendments` | `program_id` → `amendment_ids[]` | Change-history lookup |
| 5 | `pc_acceptance_stats_by_program` | `program_id` × FY | Pre-aggregated 採択率 |
| 6 | `pc_combo_pairs` | `program_a` × `program_b` | Compat / conflict pairs |
| 7 | `pc_seasonal_calendar` | month × programs | Deadline calendar tool |
| 8 | `pc_industry_jsic_aliases` | alias → JSIC | Natural-language matcher |
| 9 | `pc_authority_to_programs` | `authority_id` → `program_ids[]` | "All METI programs" enum |
| 10 | `pc_law_amendments_recent` | last 365 days | Change feed |
| 11 | `pc_enforcement_by_industry` | industry × enforcement | Risk lookup |
| 12 | `pc_loan_by_collateral_type` | collateral × top loans | 担保軸での絞り込み |
| 13 | `pc_certification_by_subject` | subject × top certs | "ISO27001 が要る制度" |
| 14 | `pc_starter_packs_per_audience` | 5 audience × pack | Audience-aware landing |

The 18 tables added in migration 045:

| # | Table | Dimension | Purpose |
| - | ----- | --------- | ------- |
| 15 | `pc_amendment_recent_by_law` | law × 直近 365 日 amendment | Law-first change feed |
| 16 | `pc_program_geographic_density` | prefecture × tier × count | Region density chart |
| 17 | `pc_authority_action_frequency` | authority × month | "Active authority" indicator |
| 18 | `pc_law_to_amendment_chain` | law → ordered amendments | Versioned-law lookup |
| 19 | `pc_industry_jsic_to_program` | JSIC × top 50 programs | All-program industry lookup |
| 20 | `pc_amount_max_distribution` | amount bucket × count | Funding-size histogram |
| 21 | `pc_program_to_loan_combo` | program × compatible loans | Combo planner |
| 22 | `pc_program_to_certification_combo` | program × required certs | Eligibility planner |
| 23 | `pc_program_to_tax_combo` | program × applicable tax 特例 | Tax stacking |
| 24 | `pc_acceptance_rate_by_authority` | authority × FY | 採択率 rollup |
| 25 | `pc_application_close_calendar` | month × close-date programs | Close-only calendar |
| 26 | `pc_amount_to_recipient_size` | amount × SMB size | Scale-fit guidance |
| 27 | `pc_law_text_to_program_count` | law → program count | Citation rollup |
| 28 | `pc_court_decision_law_chain` | court × law × decision | Case-law graph |
| 29 | `pc_enforcement_industry_distribution` | industry × severity × 5yr count | Risk histogram |
| 30 | `pc_loan_collateral_to_program` | collateral × programs | Collateral-axis bridge |
| 31 | `pc_invoice_registrant_by_pref` | pref × 適格事業者 count | Invoice density |
| 32 | `pc_amendment_severity_distribution` | severity × month | Change-feed trend |

Refreshed by `scripts/cron/precompute_refresh.py` once per night, using a
DELETE-then-INSERT pattern inside a single transaction per table. The pre-
launch state is **empty**: tables exist, indexes exist, the cron stub
runs cleanly, but the projection bodies are deferred to follow-up tickets.
API code falls through to L0/L1/L2 on `pc_*` miss, so the launch path is
identical to today.

### Numerical target

| Date | Total L3 representations | of which `pc_*` tables |
| ---- | ----------------------: | ---------------------: |
| Launch (2026-05-06) | 19 | 0 |
| **T+30d (post mig 044)** | 33 | 14 |
| **T+90d (post mig 045, current)** | **51** | **32** |
| T+180d | 79 | ≥ 50 |
| Y3 | 100+ | ≥ 80 |

Each new `pc_*` ticket should include the refresher body it expects in
`scripts/cron/precompute_refresh.py`.

## L4 — Hot blob cache (`l4_query_cache`)

L4 sits **above** L3 and caches the **serialized API response blob** —
not the rows that produced it. Migration 043 creates a single table:

```sql
CREATE TABLE l4_query_cache (
    cache_key   TEXT PRIMARY KEY,        -- sha256(tool + canonical_json(params))
    tool_name   TEXT NOT NULL,
    params_json TEXT NOT NULL,            -- canonical JSON (sort_keys, no whitespace)
    result_json TEXT NOT NULL,            -- the response blob the API returns
    hit_count   INTEGER NOT NULL DEFAULT 0,
    last_hit_at TEXT,
    ttl_seconds INTEGER NOT NULL DEFAULT 86400,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### Why blob, not rows

The Zipf-shaped traffic tail (top ~100 distinct param sets per tool) is
~80% of all calls in steady state. Re-running the L0/L1/L2/L3 query for
each repeat is wasted CPU; the response is byte-identical. Caching the
serialized blob skips the JOIN, the JSON encoding, and the response model
validation step in one go.

### Key shape

The single source of truth is `cache.l4.canonical_cache_key`:

```python
def canonical_cache_key(tool_name: str, params: dict) -> str:
    payload = f"{tool_name}\n{canonical_params(params)}".encode()
    return hashlib.sha256(payload).hexdigest()
```

`canonical_params` is `json.dumps(params, sort_keys=True, ensure_ascii=False,
separators=(",", ":"))`. **Never hand-roll a sha256** elsewhere — drift
silently misses the cache.

### Read path

```python
from jpintel_mcp.cache import canonical_cache_key, get_or_compute

key = canonical_cache_key("search_tax_incentives", params)
result = get_or_compute(
    cache_key=key,
    tool="search_tax_incentives",
    params=params,
    compute=lambda: _real_search(params),
    ttl=86400,
)
```

`get_or_compute` returns the cached value on hit, or calls `compute()`
and stores the result on miss. Stale rows (TTL expired) are treated as
miss; they are not deleted on read (avoiding write-on-read amplification).

### Write path

L4 is populated **organically** as customer traffic flows through the
API. Pre-launch the table is empty by design — this is not a bug, it is
the launch-day expected state. Hit rate climbs over the first ~7 days as
the Zipf tail forms.

### Eviction posture

Two cron paths keep the table bounded:

1. `scripts/cron/l4_cache_warm.py` (daily): reads `usage_events` over the
   last 7 days, ranks by `(endpoint, params_digest)` Zipf, optionally
   re-warms the top-100 keys, sweeps TTL'd rows, and trims the table to
   a soft cap (default 1000 rows) by `last_hit_at` ascending.
2. `scripts/cron/precompute_refresh.py` calls `cache.l4.sweep_expired()`
   after the `pc_*` refresh so the L4 cache is consistent with the
   freshly-rebuilt L3 layer.

### Hit-rate target

| Date | Hit rate | Margin impact |
| ---- | -------- | ------------- |
| Launch | 0% (empty) | baseline 92% |
| T+30d | 60% | 93% |
| Y1 (Zipf saturation) | 80% | 95% |

The 95% margin number is what unlocks the ¥1M/month projection in
`project_autonomath_expansion_plan` without breaking the
non-negotiable ¥3/req metered pricing.

## Layer cooperation (read flow)

```
                     ┌────────────────────────────┐
                     │   incoming /v1 request     │
                     └──────────────┬─────────────┘
                                    │
                                    ▼
                          ┌──────────────────┐
                          │   L4 cache?      │ ← hash(tool, params)
                          └─────┬────────────┘
                                │ hit
                                │  └──────────────► serialised JSON ▶ response
                                │ miss
                                ▼
                          ┌──────────────────┐
                          │   L3 pc_* row?   │ ← materialized view
                          └─────┬────────────┘
                                │ hit
                                │  └──────────────► row(s) → L4 INSERT ▶ response
                                │ miss
                                ▼
                          ┌──────────────────┐
                          │   L2 join        │ ← live JOIN
                          └─────┬────────────┘
                                │
                                ▼
                          ┌──────────────────┐
                          │   L1 atomic      │ ← single-row b-tree
                          └─────┬────────────┘
                                │
                                ▼
                          ┌──────────────────┐
                          │   L0 storage     │ ← bytes on disk
                          └──────────────────┘
```

A miss at any layer always falls through to the layer below. There is no
"cache wall": correctness is identical with or without the cache.

## Layer cooperation (write flow)

L0 is mutated by ingest. L1/L2 are live views with no separate write
path. L3 is rebuilt nightly by `precompute_refresh.py` (DELETE-then-
INSERT per table inside a transaction). L4 entries are invalidated
either:

- Implicitly via TTL (default 24h, 1h for amendment-coupled tools).
- Explicitly by `cache.l4.invalidate_tool(tool_name)` after a schema or
  source change that affects a specific tool's response shape.
- By the `precompute_refresh.py` sweep step at the end of each nightly
  refresh.

## Operational levers

- **Cache miss spike** → check `usage_events` for a new top-N param
  pattern, then add a `pc_*` row (or pre-warm via `l4_cache_warm.py`).
- **L4 staleness complaint** → drop `ttl_seconds` for the affected tool
  (1h for amendment-coupled paths is the established floor).
- **Storage budget alert** → drop `--soft-cap` in `l4_cache_warm.py`
  (default 1000 → 500). Each row is ≤ 32 KB compressed, so even 1000
  rows is ~30 MB.

## Files

- `scripts/migrations/043_l4_cache.sql` — `l4_query_cache` table.
- `scripts/migrations/044_precompute_tables.sql` — 14 `pc_*` tables (C3 wave).
- `scripts/migrations/045_precompute_more.sql` — 18 `pc_*` tables (D8 wave).
- `src/jpintel_mcp/cache/__init__.py`, `src/jpintel_mcp/cache/l4.py` —
  helper API (`canonical_cache_key`, `get_or_compute`, `invalidate`,
  `invalidate_tool`, `sweep_expired`).
- `scripts/cron/l4_cache_warm.py` — daily Zipf warm-up + LRU trim.
- `scripts/cron/precompute_refresh.py` — nightly `pc_*` rebuild
  (32 tables) + L4 expired sweep.
- `tests/test_precompute_schemas.py` — 102-case schema + dry-run
  invariants (table existence, column shape, indexes, cron iteration).
