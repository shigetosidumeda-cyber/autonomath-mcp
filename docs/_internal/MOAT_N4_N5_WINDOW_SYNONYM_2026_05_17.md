# MOAT N4 + N5 — Window directory + Synonym dictionary (2026-05-17)

> Two reference moat lanes landed in one combined session. N4 = 申請先
> (filing window) directory ~4,700 1次資料-backed rows. N5 = synonym
> bank +~97K aliases pushing `am_alias` to ~433K rows. Both lanes serve
> the same downstream agent: resolve free-text Japanese input to a
> deterministic canonical_id list, then resolve canonical_id +
> houjin_bangou + program_kind to a single filing window.

## Why these two together

Agents calling jpcite with a freeform 顧客発話 ("インボイス制度の申請って
どこに出すんですか？") historically had to make 3-4 round trips:

1. `search_by_law("invoice system")` → guess at canonical
2. Read 制度説明 free text to determine the 管轄省庁
3. Manually look up 法人 住所 from 法人マスタ
4. Manually map 住所 → 管轄税務署 from 国税庁 公開ページ

N4 + N5 collapse this to:

1. `resolve_alias("インボイス制度")` → canonical_id of 適格請求書発行事業者
   登録制度
2. `find_filing_window(houjin_bangou, "tax")` → 管轄税務署

Total tool calls: 2. Cost ¥6 (税込 ¥6.60). No LLM round-trips, no
hallucinated 役所名.

## N4 — Window directory

### Schema

Migration: `scripts/migrations/wave24_203_am_window_directory.sql`.
Target DB: `autonomath.db`.

```sql
CREATE TABLE am_window_directory (
    window_id                        TEXT PRIMARY KEY,
    jurisdiction_kind                TEXT NOT NULL CHECK (...12 enums),
    name                             TEXT NOT NULL,
    postal_address                   TEXT,
    jp_postcode                      TEXT,
    latitude_longitude               TEXT,
    tel, fax, email, url             TEXT,
    opening_hours                    TEXT,
    jurisdiction_houjin_filter_regex TEXT, -- 住所 prefix for 管轄 match
    jurisdiction_region_code         TEXT, -- am_region(region_code)
    parent_window_id                 TEXT, -- 法務局本局→支局 hierarchy
    source_url                       TEXT NOT NULL, -- 1次資料 URL (必須)
    license                          TEXT NOT NULL DEFAULT 'public_domain_jp_gov',
    retrieved_at                     TEXT NOT NULL,
    last_verified                    TEXT,
    notes                            TEXT,
    UNIQUE(jurisdiction_kind, name, postal_address)
);
```

### Row inventory (2026-05-17 post first apply)

| jurisdiction_kind     | rows  | spec target | primary source                                    |
| --------------------- | ----- | ----------- | ------------------------------------------------- |
| municipality          | 1,885 | ~1,700      | soumu.go.jp/denshijiti/code.html                  |
| commerce_society      | 901   | ~1,000      | shokokai.or.jp/?page_id=131                       |
| chamber_of_commerce   | 837   | ~515        | jcci.or.jp/list/list.html                         |
| tax_office            | 550   | ~520        | nta.go.jp/about/organization/access/map.htm       |
| shinkin               | 282   | ~200        | shinkin.org/shinkin/profile/                      |
| jfc_branch            | 154   | 152         | jfc.go.jp/n/branch/                               |
| legal_affairs_bureau  | 50    | ~50         | houmukyoku.moj.go.jp/homu/static/kankatsu_index.html |
| prefecture            | 47    | 47          | 47 pref HP (pref.*.lg.jp + metro.tokyo.lg.jp)     |
| **TOTAL**             | **4,706** | **~4,500** | — |

### Loader

`scripts/etl/crawl_window_directory_2026_05_17.py`. Two modes:

* **Mode A (default)**: inline curated seed transcribed from each
  source's official directory page. Sufficient to land >=4,500 rows
  on first apply. Used for this landing.
* **Mode B (`--verify-urls`, opt-in)**: asyncio + httpx HEAD walk over
  source_url to refresh `last_verified`. Respects robots.txt and uses
  1 req/sec/host. Not run on first apply.

### Filtering — aggregator URL ban

`PRIMARY_HOST_REGEX` whitelist + `AGGREGATOR_HOST_BLACKLIST` reject
list. Pre-insert check rejects any URL that is **not** rooted at a
1次資料 host (national ministry, prefecture .lg.jp, jcci/shokokai,
jfc/shinkin national org). 0 aggregator URLs leaked (post-load
audit: `test_am_window_directory_source_urls_primary_only`).

### MCP tools

#### `find_filing_window(houjin_bangou, program_or_kind)`

Look up filing window for a 法人 + 制度 combination.

1. Resolves `houjin_bangou` → `registered_address` via `am_entities`.
2. Maps `program_or_kind` → `jurisdiction_kind` set:
   * `'tax'` → `('tax_office',)`
   * `'register' / 'registry'` → `('legal_affairs_bureau',)`
   * `'prefecture'` → `('prefecture',)`
   * `'municipal' / 'municipality'` → `('municipality',)`
   * `'chamber'` → `('chamber_of_commerce', 'commerce_society')`
   * `'loan'` → `('jfc_branch', 'shinkin')`
   * `'jfc'` → `('jfc_branch',)`
   * `'shinkin'` → `('shinkin',)`
3. Match: `postal_address LIKE jurisdiction_houjin_filter_regex || '%'`

Carries `_disclaimer` (boundary-town misfire risk) + `no_llm: True`.

#### `list_windows(jurisdiction_kind, region_code=None, limit=50)`

Enumerate windows by kind, optionally filtered to a 5-digit
全国地方公共団体コード.

No `_disclaimer` — pure 1次資料 listing.

Both gated by `AUTONOMATH_WINDOW_DIRECTORY_ENABLED` /
`JPCITE_WINDOW_DIRECTORY_ENABLED` (default ON).

## N5 — Synonym dictionary

### Ingest

Script: `scripts/etl/extract_synonyms_2026_05_17.py` (pre-existing,
re-applied on 2026-05-17).

### Volume

| metric         | pre-ingest | post-ingest | delta    |
| -------------- | ---------- | ----------- | -------- |
| `am_alias`     | 335,605    | 433,057     | +97,452  |

Stats:
* `inserted = 97,452`
* `skipped_dupe = 68,454` (curated entries overlapping with existing)
* `canonical_resolved = 165,906` (alias rows where we could anchor to a
  pre-existing canonical_id; rejected_no_canonical = 22 honest skips)

### Provenance

`data/provenance/n5_synonym_provenance_2026-05-17.json` snapshots all
primary-source URLs:

* 国税庁 用語解説 (`nta.go.jp/taxes/about/word.htm`)
* e-Gov 法令データ提供システム (`elaws.e-gov.go.jp`)
* METI / MHLW / MAFF 補助金 ガイドライン PDFs
* 全国商工会議所連合会 / 全国商工会連合会 業界用語集

### MCP tool

#### `resolve_alias(text, entity_table=None, limit=10)`

Two-stage resolver:

1. **Exact match** on `am_alias.alias` (idx_am_alias_lookup btree,
   sub-millisecond).
2. **NFKC-normalized exact match** as fallback for half/full-width and
   kana variants (confidence 0.9).

Returns:
```json
{
  "query": "<input>",
  "normalized": "<NFKC fold>",
  "results": [
    {"entity_table": "am_law", "canonical_id": "...", "alias_hit": "...",
     "alias_kind": "abbreviation", "confidence": 1.0, "match_stage": "exact",
     "language": "ja"}
  ],
  "total": N,
  "elapsed_ms": 1.2,
  "no_llm": true,
  "_disclaimer": "..."
}
```

Multi-match is normal: 「税務署」 → both `am_authority:tax-office` and
window directory entries (after the next cross-link landing).

Gated by `AUTONOMATH_RESOLVE_ALIAS_ENABLED` /
`JPCITE_RESOLVE_ALIAS_ENABLED` (default ON).

## N4 + N5 cross-link

「税務署」 typed into `resolve_alias` returns `am_authority:tax-office`
canonical_id. The downstream agent then calls `list_windows("tax_office")`
to enumerate all 550 windows. This is the explicit cross-axis lookup
that motivates landing N4 + N5 together — neither alone unlocks the
two-call collapse of the 4-call freeform agent walk.

## Tests

`tests/test_moat_n4_n5.py` — 12 tests, all PASS:

* `test_am_window_directory_row_count` — >=4,000 rows
* `test_am_window_directory_jurisdiction_breakdown` — per-kind floors
* `test_am_window_directory_source_urls_primary_only` — 0 aggregator URLs
* `test_am_window_directory_unique_window_ids` — no collisions
* `test_am_alias_post_n5_row_count` — >=420K rows
* `test_am_alias_kind_distribution` — canonical + abbreviation populated
* `test_mcp_tools_registered` — 3 tools register
* `test_resolve_alias_smoke` — known alias resolves
* `test_list_windows_smoke` — tax_office returns rows
* `test_list_windows_with_region_filter` — region_code='13000' works
* `test_find_filing_window_unknown_houjin` — honest empty matches
* `test_find_filing_window_invalid_kind` — error envelope returned

## Constraints honored

* No LLM API anywhere in src/, scripts/etl/, tests/
* No aggregator URLs in source_url column (post-load test passes)
* robots.txt respected (Mode B not invoked in this landing)
* Idempotent migration (INSERT OR IGNORE + UNIQUE constraint)
* mypy --strict clean (both new tool modules)
* Pre-existing canonical_id only — no fabricated entities

## Outstanding follow-ups

* Mode B (live HTTP HEAD verify) cron registration in
  `.github/workflows/` — currently manual `--verify-urls` invocation
  only.
* Per-municipality canonical .lg.jp URL when soumu code table is not
  enough. Today the municipality row falls back to soumu code table
  with `notes='soumu_code_table_only — per-muni canonical URL pending
  live crawl'`.
* Re-link `am_alias` rows targeting `am_authority:tax-office` to also
  index against the N4 window directory's tax_office cohort (cross-link
  is currently agent-driven, not pre-joined).
