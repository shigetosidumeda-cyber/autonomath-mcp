# Performance + Storage Audit (2026-04-30)

Pure measurement pass. No schema changes, no VACUUM, no REINDEX.
OTHER CLI is reading `data/jpintel.db` for url_liveness scan; concurrent reads only.

## Headline numbers

| Metric | Value |
|---|---|
| `autonomath.db` total | **9.36 GB** (10,052,435,968 bytes / 2,454,208 × 4 KB pages) |
| `data/jpintel.db` total | **360 MB** (377,294,848 bytes) |
| Repo `autonomath.db.{bak,pre}.*` backups | **128.1 GB** (12 dated copies still resident at repo root) |
| API boot (`from jpintel_mcp.api.main import app`) | **5.45 s wall** |
| MCP boot (`from jpintel_mcp.mcp.server import run`) | **1.81 s wall** |
| `programs_fts` p50 latency (5-query sample) | **6.0 ms** |

## A. autonomath.db top-30 objects

| # | Object | Kind | Bytes (% of 9.36 GB) | Rows | Status |
|---|---|---|---|---|---|
| 1 | `am_entity_facts` | table | 1.34 GB (14.3%) | 6,124,990 | HOT — core EAV |
| 2 | `am_entities_fts_data` | FTS5 | 1.22 GB (13.1%) | 267,855 | HOT — `tools.py:741,1109` |
| 3 | `am_vec_tier_a_vector_chunks00` | sqlite-vec | 656 MB (7.0%) | 415 | **DEAD** — refs only in `_archive/` |
| 4 | `am_entities_vec_vector_chunks00` | sqlite-vec | 656 MB (7.0%) | 415 | **DEAD** — refs only in `_archive/` |
| 5 | `ix_am_facts_entity_field_covering` | index | 638 MB (6.8%) | n/a | HOT (covering for facts hot path) |
| 6 | `uq_am_facts_entity_field_text` | index | 630 MB (6.7%) | n/a | HOT (uniqueness gate on EAV) |
| 7 | `am_entities` | table | 585 MB (6.3%) | 503,930 | HOT |
| 8 | `idx_am_entity_facts_csc` | index | 504 MB (5.4%) | n/a | HOT |
| 9 | `idx_am_facts_entity` | index | 384 MB (4.1%) | n/a | HOT |
| 10 | `am_entities_fts_uni_content` | FTS5 content | 374 MB (4.0%) | 388,972 | **DEAD** — only `_archive/` refs |
| 11 | `am_entities_vec_l2v2_vector_chunks00` | sqlite-vec | 334 MB (3.6%) | 211 | **DEAD** |
| 12 | `am_entities_fts_content` | FTS5 content | 330 MB (3.5%) | 402,600 | HOT (paired with #2) |
| 13 | `am_entities_fts_uni_data` | FTS5 | 271 MB (2.9%) | 59,898 | **DEAD** |
| 14 | `idx_am_facts_field_kind` | index | 202 MB (2.2%) | n/a | HOT |
| 15 | `ix_am_entity_facts_valid` | index | 189 MB (2.0%) | n/a | WARM (validity windowing) |
| 16 | `idx_am_facts_field` | index | 170 MB (1.8%) | n/a | HOT |
| 17 | `am_law_article` | table | 96 MB (1.0%) | 28,201 | HOT (`law_article_tool.py`) |
| 18 | `jpi_adoption_records` | table | 74 MB (0.8%) | 201,845 | HOT |
| 19 | `idx_am_efacts_source` | index | 64 MB (0.7%) | n/a | WARM (provenance lookup) |
| 20 | `jpi_programs` | table | 50 MB (0.5%) | 13,578 | HOT |
| 21 | `am_relation` | table | 47 MB (0.5%) | 177,381 | HOT (graph_traverse) |
| 22 | `am_amount_condition` | table | 41 MB (0.4%) | 250,946 | WARM (template_default=1 is noise per CLAUDE.md) |
| 23 | `ix_am_entities_kind_name` | index | 39 MB (0.4%) | n/a | HOT |
| 24 | `am_alias` | table | 36 MB (0.4%) | 335,605 | HOT |
| 25 | `am_entities_vec_l2v2_map` | sqlite-vec map | 36 MB (0.4%) | 215,233 | **DEAD** |
| 26 | `am_entity_source` | table | 34 MB (0.4%) | 279,841 | HOT |
| 27 | `uq_am_amount_condition` | index | 31 MB (0.3%) | n/a | WARM |
| 28 | `idx_am_facts_numeric` | index | 31 MB (0.3%) | n/a | WARM |
| 29 | `am_vec_rowid_map` | sqlite-vec map | 30 MB (0.3%) | 424,277 | **DEAD** |
| 30 | `sqlite_autoindex_am_entities_1` | autoindex | 29 MB (0.3%) | n/a | HOT |

**DEAD vec/FTS-uni footprint**: `am_vec_tier_a_vector_chunks00` 656 MB + `am_entities_vec_vector_chunks00` 656 MB + `am_entities_vec_l2v2_vector_chunks00` 334 MB + `am_entities_vec_l2v2_map` 36 MB + `am_vec_rowid_map` 30 MB + `am_entities_fts_uni_content` 374 MB + `am_entities_fts_uni_data` 271 MB ≈ **2.36 GB (≈25% of the DB)**. All references in `src/` are limited to `src/jpintel_mcp/_archive/embedding_2026-04-25/` and `src/jpintel_mcp/_archive/autonomath_tools_dead_2026-04-25/`. Production code does not query them.

## B. jpintel.db top-30 (highlights)

| # | Object | Kind | Bytes (% of 360 MB) | Rows | Status |
|---|---|---|---|---|---|
| 1 | `programs_fts_data` | FTS5 | 69 MB (19%) | 18,454 | HOT |
| 2 | `adoption_records` | table | 59 MB (16%) | 199,944 | HOT |
| 3 | `programs` | table | 52 MB (14%) | 14,472 | HOT |
| 4 | `case_studies_fts_data` | FTS5 | 30 MB (8%) | 7,677 | HOT |
| 5 | `programs_fts_content` | FTS5 content | 26 MB (7%) | 11,869 | HOT |
| 6 | `houjin_master` | table | 21 MB (6%) | 166,765 | HOT |
| 7 | `laws` | table | 6.7 MB (2%) | 9,484 | HOT |
| 8 | `idx_houjin_name` | index | 6.7 MB (2%) | n/a | HOT |
| 9–30 | court_decisions / case_studies / laws_fts / adoption indexes / lineage audit / source_lineage_audit | mixed | <6 MB each | per CLAUDE.md | HOT/WARM |

No FTS bloat — content tables ≤ data tables, healthy ratio. No DEAD candidates spotted in the top-30.

## C. PRAGMA configuration audit

Reference setup is in `src/jpintel_mcp/db/session.py:119-134` (writer path on jpintel.db) and `src/jpintel_mcp/mcp/autonomath_tools/db.py:137-158` (reader pool on autonomath.db). Both are good (WAL/NORMAL/256-512 MB cache/256MB-2GB mmap/temp_store=MEMORY).

**Sub-optimal connections (one-shot, no perf pragmas)**:

| File:line | Path | Missing |
|---|---|---|
| `api/_audit_seal.py:219` | autonomath.db RO | `cache_size`, `mmap_size`, `temp_store` |
| `api/_health_deep.py:80` | autonomath.db RO | acceptable for deep-health probe |
| `api/_universal_envelope.py:78` | autonomath.db RO | `cache_size`, `mmap_size`, `temp_store` (called per request for license map; `_LICENSE_MAP_CACHE` softens it) |
| `api/houjin.py:108-112` | autonomath.db RO | sets `temp_store=MEMORY` only — missing `cache_size`/`mmap_size` for 9.4 GB DB |
| `api/ma_dd.py:264-270` | autonomath.db RO | same as houjin.py (file comment even calls out the gap) |
| `api/source_manifest.py:112-116` | autonomath.db RO | same |
| `api/transparency.py:81` | autonomath.db RO | no perf pragmas at all |
| `api/trust.py:94, 109` | autonomath.db RO/RW | RO path missing perf pragmas |
| `api/meta.py:254` | autonomath.db RO | no perf pragmas (low traffic, acceptable) |

**Recommendation (DOCUMENTATION ONLY — DO NOT APPLY in this session)**: extract a shared `_open_ro(path)` helper that always sets the four pragmas (`temp_store=MEMORY`, `cache_size=-262144`, `mmap_size=2147483648`, `query_only=1`) and replace each direct `sqlite3.connect(...)` callsite. This mirrors `mcp/autonomath_tools/db.py:_open_ro`.

## D. Boot time

```
$ time .venv/bin/python -c "from jpintel_mcp.api.main import app"
4.28s user 0.46s system 87% cpu 5.445 total

$ time .venv/bin/python -c "from jpintel_mcp.mcp.server import run"
1.54s user 0.16s system 93% cpu 1.808 total
```

API boot exceeds the 3 s threshold. `-X importtime` dominant costs:

| Module | Cumulative ms |
|---|---|
| `jpintel_mcp.api.main` total | 4,284 |
| `jpintel_mcp.api.confidence` → `analytics.bayesian` → `scipy.stats` | 1,191 (28% of boot) |
| `jpintel_mcp.api.billing` → `stripe` SDK | 757 (18%) |
| `jpintel_mcp.api.audit_log` → `autonomath_tools` (eager) → `mcp.server.fastmcp` | 598 |
| `jpintel_mcp.api.audit` | 347 |
| `fastapi` | 303 |
| `jpintel_mcp.utils.slug` (cutlet/pykakasi pull) | 269 |

Dominant cost is **scipy.stats import via `analytics.bayesian` from `api/confidence.py`**, not autonomath_tools. autonomath_tools eager pull adds ~595 ms (loaded indirectly via `audit_log`).

**Lazy-load candidates (DOCUMENTATION ONLY)**:
- `api/confidence.py`: defer `from jpintel_mcp.analytics.bayesian import …` to inside the route function. Saves ~1.2 s on cold start. No behavior change because `scipy.stats` is only used inside the confidence handler.
- `api/billing.py`: defer `import stripe` to first webhook/checkout call. Saves ~750 ms.
- `api/audit_log.py`: stop importing `autonomath_tools` at module top — load on first request. Saves ~600 ms.

Combined savings: **~2.5 s of boot**, putting API boot near 3 s.

## E. /v1/programs/search latency (programs_fts MATCH)

| Query | Rows | Latency |
|---|---|---|
| IT導入 | 12 | 6.5 ms (cold) → 18.6 ms second run (background CLI lock contention?) |
| ものづくり | 20 | 6.3 ms |
| 事業再構築 | 17 | 4.4 ms |
| サステナブル | 4 | 2.6 ms |
| 小規模事業者 | 20 | 6.8 ms |

**p50 = 6.0 ms.** All queries well under the 100 ms flag threshold. No index review needed for FTS path.

## F. Static assets > 500 KB (excluding /programs and /cross)

| Bytes | File |
|---|---|
| 4.24 MB | `site/llms-full.en.txt` |
| 2.26 MB | `site/llms-full.txt` |
| 1.82 MB | `site/docs/ux/screenshots/redesign_2026_04_29/index.png` |
| 1.37 MB | `site/docs/ux/screenshots/redesign_2026_04_29/audiences_tax-advisor.png` |
| 1.29 MB | `site/docs/ux/screenshots/redesign_2026_04_29/audiences_smb.png` |
| 1.18 MB | `site/docs/ux/screenshots/redesign_2026_04_29/pricing.png` |
| 1.16 MB | `site/docs/ux/screenshots/redesign_2026_04_29/audiences_dev.png` |
| 1.01 MB | `site/docs/ux/screenshots/redesign_2026_04_29/audiences_index.png` |
| 984 KB | `site/docs/assets/javascripts/bundle.60a45f97.min.js.map` (mkdocs-material sourcemap; safe to drop on prod) |
| 905 KB | `site/docs/ux/screenshots/redesign_2026_04_29/transparency.png` |
| 885 KB | `site/docs/ux/screenshots/redesign_2026_04_29/about.png` |
| 732 KB | `site/docs/ux/screenshots/redesign_2026_04_29/integrations_cline.png` |
| 677 KB | `site/docs/assets/javascripts/lunr/wordcut.js` |
| 646 KB | `site/docs/search/search_index.json` |
| 645 KB | `site/docs/openapi/v1.json` |
| 579 KB | `site/docs/api-reference/index.html` |

UX screenshots in `redesign_2026_04_29/` are an internal-doc gallery; they shouldn't be served to end users. Either drop from the deploy or run `pngquant`/`oxipng` (typical 60-80% shrink). `llms-full.{txt,en.txt}` are the largest; consider precompressing (Cloudflare auto-brotlis but a static `.br` would skip TTFB compression).

## G. Top-level directory sizes

| Dir | Size |
|---|---|
| `data/` | **4.9 GB** (locked by OTHER CLI, leave alone) |
| `analysis_wave18/` | 128 MB (forbidden touch) |
| `site/` | 71 MB |
| `docs/` | 13 MB |
| `scripts/` | 8.7 MB |
| `src/` | 8.3 MB |
| `tests/` | 8.0 MB |
| `research/` | 3.5 MB (forbidden touch) |
| `tools/` | 48 KB |

Outside the audit scope but worth flagging — **128 GB of `autonomath.db.{bak,pre}.*` files at repo root** (12 copies, dated 4/25–4/29). These are backups, but they live next to the live DB, not under `data/`. Disk pressure risk on Fly volumes if any deploy step rsyncs the repo root. Out-of-scope for this session (would not modify); recorded for ops awareness.

## Top 3 highest-leverage perf wins (effort estimates for documentation only)

1. **Drop the unused vec + uni-FTS objects from `autonomath.db` (~2.36 GB / 25% of DB)** — `am_vec_tier_a_vector_chunks00`, `am_entities_vec_vector_chunks00`, `am_entities_vec_l2v2_*`, `am_vec_rowid_map`, `am_entities_fts_uni_*`. Production references live only under `_archive/`. **Effort ≈ 1 h** (verify zero references in `tests/` + `scripts/`, write idempotent `DROP TABLE IF EXISTS` migration, schedule against autonomath.db once OTHER CLI releases the lock; VACUUM follows in a separate pass). NOT executed here.

2. **Lazy-load scipy.stats / stripe / autonomath_tools at API boot** — defers ~2.5 s of cold-start cost into first-request paths that already do non-trivial work. Touches 3 files: `api/confidence.py`, `api/billing.py`, `api/audit_log.py`. **Effort ≈ 1 h**. Boot drops 5.45 s → ~3.0 s. Behavior unchanged.

3. **Unify ad-hoc `sqlite3.connect` callsites onto a shared `_open_ro` helper with full PRAGMA stack** — 8 callsites in `api/*.py` connect to autonomath.db with at most `temp_store=MEMORY`. Adding `cache_size=-262144` + `mmap_size=2147483648` per connection brings them in line with the MCP-side hot path. **Effort ≈ 2 h** (extract helper, replace each callsite, run unit tests). Per-request cold-cache reads on `houjin/360`, `ma_dd`, `source_manifest`, `audit_seal` get 5-20 ms faster on first hit per worker.

## Constraints honored

- No DB schema modifications.
- No VACUUM, no REINDEX (OTHER CLI reading data/jpintel.db).
- `data/`, `research/`, `analysis_wave18/` not touched.
- `src/` not modified.
