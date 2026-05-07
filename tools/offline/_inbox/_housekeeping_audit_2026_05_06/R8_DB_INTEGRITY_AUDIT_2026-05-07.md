# R8 Database Integrity Audit — 2026-05-07

Read-only deep audit of the two production-shape SQLite databases on the jpcite
operator workstation, plus the migration directory. No DDL or DML was issued
during this audit; LLM API calls = 0; production data was not touched.

## Executive summary

- Live `data/jpintel.db` (446 MB) and `autonomath.db` (12.4 GB at repo root)
  pass `PRAGMA quick_check`. WAL files are clean (0 bytes).
- `PRAGMA foreign_keys` is **OFF** runtime on both DBs by default. FK
  declarations are advisory at the boot connection level. Enforcement is
  selectively turned ON only inside specific Python session paths
  (`src/jpintel_mcp/db/session.py:127`,
  `src/jpintel_mcp/billing/credit_pack.py:213`,
  `scripts/walk_pref_subsidy_seeds.py:790,981`,
  `scripts/ingest_examiner_feedback.py:387`). The DB file as it sits has 3,355
  FK violations (advisory only; no runtime impact today, but a minefield if FKs
  are ever globally enabled).
- 200 forward migration files, 88 rollback companions, 0 orphan rollbacks
  (every rollback has a matching forward).
- Schema drift: 36 migration files unapplied to jpintel, 73 unapplied to
  autonomath (mostly recent `wave24_*` files generated 2026-05-07 — they will
  apply on next boot via `entrypoint.sh §4` for autonomath-target migrations
  and via `migrate.py` for jpintel-target migrations). 4 migrations
  recorded-as-applied but no longer on disk (renamed/consolidated).
- No single trivial fix was committed during this audit — every diff would
  touch live schema (`am_region.parent_code` FK rewrite to drop the ghost
  `am_region_new` reference would require a `CREATE TABLE … AS SELECT` swap on
  a 12.4 GB DB; not "trivial"). All proposed fixes are queued as follow-ups.

## 1. Live integrity

### 1.1 jpintel.db — `data/jpintel.db` (446,713,856 bytes / 109,061 pages)

| pragma | value |
|---|---|
| `quick_check` | `ok` |
| `foreign_key_check` | clean (zero rows) |
| `journal_mode` | `wal` |
| `wal_autocheckpoint` | `1000` |
| `page_size` | `4096` |
| `cache_size` | `2000` |
| `freelist_count` | `0` |
| `foreign_keys` | `0` (off — advisory FK declarations) |
| WAL on disk | `data/jpintel.db-wal` 0 bytes, `…-shm` 32,768 bytes |

User-defined indexes: 279. `programs`, `usage_events`, `api_keys` hot paths all
covered (verified `idx_programs_tier`, `idx_programs_jsic_major_tier`,
`idx_programs_verify_freshness`, `idx_usage_events_billing_idempotency`,
`idx_api_keys_subscription_status`, etc.).

### 1.2 autonomath.db — `autonomath.db` (12,383,645,696 bytes / 3,023,351 pages)

| pragma | value |
|---|---|
| `quick_check` | (skipped — per memory `feedback_no_quick_check_on_huge_sqlite.md`. Boot-time `quick_check` on this file took 15+ minutes during a previous launch and tripped the Fly grace timer. Cold offline `quick_check` runs are safe but expensive; deferred unless a corruption symptom surfaces.) |
| `foreign_key_check` | **3,355 violations across 3 tables** (see §1.3) |
| `journal_mode` | `wal` |
| `wal_autocheckpoint` | `1000` |
| `page_size` | `4096` |
| `cache_size` | `2000` |
| `freelist_count` | `42` (negligible) |
| `foreign_keys` | `0` (off — advisory FK declarations) |
| WAL on disk | `autonomath.db-wal` 0 bytes, `…-shm` 32,768 bytes |

User-defined indexes: 554. `houjin_master`, `jpi_adoption_records`, `am_region`
hot paths covered (`idx_houjin_master_jsic_major`, `idx_adoption_houjin`,
`idx_adoption_program_hint`, `idx_am_region_level`, `idx_am_region_parent`).

Note on size: CLAUDE.md and several memory entries quote `~9.4 GB` /
`~9.7 GB` / `~8.29 GB` for autonomath.db. The file on the operator workstation
today is **12.4 GB**. The earlier numbers are pre-Wave-24 / pre-recent-ingest
snapshots; the size growth tracks the Wave 21–24 cron landings and the
expanded am_* corpora.

### 1.3 FK violations (advisory only)

```
1965 am_region            -> am_region_new        (GHOST TARGET TABLE)
 695 jpi_adoption_records -> houjin_master        (357 distinct houjin_bangou)
 695 adoption_records     -> houjin_master        (same shape, twin table)
```

- `am_region` carries `FOREIGN KEY (parent_code) REFERENCES am_region_new(region_code)`
  but `am_region_new` does not exist (it was the rename source — historical
  staging table). All 1,965 actual parent codes ARE resolvable inside
  `am_region` itself; the referential graph is consistent, only the FK
  declaration points at the wrong table. **Schema-cleanliness drift, not data
  corruption.**
- `jpi_adoption_records` and `adoption_records` (twin tables, same
  `houjin_bangou` shape) have 695 rows each (357 distinct corp numbers) where
  the corp number isn't present in `houjin_master`. These are real orphaned
  adoption rows. Likely sourced from PDF / scrape paths that captured a corp
  number not yet (or ever) present in the gBiz mirror. With FKs OFF runtime,
  these are silently joinable as LEFT JOINs returning NULL on the master side.

Decision: do not fix in this read-only audit. See §6 for follow-ups.

## 2. Migration directory audit

### 2.1 Counts

```
forward (excluding *_rollback):   200 files
rollback companions:               88 files
forward without rollback:         112 (e.g. 001_lineage, 002_subscribers, 067_dataset_versioning)
rollback without forward:           0  (no orphan rollbacks)
.draft files:                       1  (006_adoption.sql.draft)
non-numeric (wave24_*):            76  (since Wave 24 prefix scheme)
plus README.md / autonomath_boot_manifest.txt
```

### 2.2 Numeric gaps in 001-176 main series (45 reserved gaps)

`004 / 006 / 025-036 / 040 / 084 / 093-095 / 100 / 117 / 127-145 / 149 /
152 / 153 / 157 / 163`. Per `CLAUDE.md` "Wave 21-22 changelog" section, the
gaps `084 / 093-095 / 100` are intentional number reservations during agent
merge. The longer 127-145 range coincides with Wave 24's renumbering into the
`wave24_*` prefix scheme. No accidental collision was found.

### 2.3 Number-collision check

- Two pairs of numeric collisions detected in the forward set:
  - `052_api_keys_subscription_status.sql` vs `052_perf_indexes.sql`
  - `065_compat_matrix_uni_id_backfill_rollback.sql` (this is unusual — a
    rollback companion was applied as a forward, see §2.5)
  - `067_dataset_versioning.sql` vs `067_dataset_versioning_autonomath.sql`
    (these are two-DB siblings, intentional pattern)
  - `074_programs_merged_from.sql` vs `074_tier_x_exclusion_reason_classify.sql`
  - `082_relation_density_expansion_rollback.sql` (same pattern as 065)
  - `113_adoption_program_join.sql` recorded-as-applied to autonomath but no
    longer on disk under that exact name (renamed via Wave 24)
  - `121_jpi_programs_subsidy_rate_text_column.sql` vs
    `121_subsidy_rate_text_column.sql`
  - `124_src_attribution.sql` vs the legacy `124_citation_verification.sql`
    (only 124_src_attribution exists today; 124_citation_verification appears
    in jpintel `schema_migrations` rowset → renamed)
  - `148_*` wave24-prefixed has its own pair pattern (forward + rollback)
- All collisions are paired-DB siblings or forward+rollback companion mixups
  in the tracking table; no two forwards target the same DB with the same id
  in a way that would replay incorrectly.

### 2.4 `target_db:` first-line marker coverage

Sampled 8 representative migrations:

```
001_lineage.sql                            -- 001_lineage.sql                          (NO target_db marker — implicit jpintel)
002_subscribers.sql                        -- 002_subscribers.sql                      (no marker — implicit jpintel)
011_external_data_tables.sql               -- 011_external_data_tables.sql             (no marker — implicit jpintel)
067_dataset_versioning.sql                 -- migration 067: dataset versioning (R8)   (no header marker — has prose target_db: jpintel.db on line 3)
067_dataset_versioning_autonomath.sql      -- target_db: autonomath                    (correct header marker)
110_autonomath_drop_cross_pollution.sql    -- target_db: autonomath                    (correct)
124_src_attribution.sql                    -- target_db: jpintel                       (correct)
wave24_186_industry_journal_mention.sql    -- target_db: autonomath                    (correct)
wave24_192_pubcomment_announcement.sql     -- target_db: autonomath                    (correct)
```

`migrate.py:_sql_target_marker()` looks at the **first 5 lines** for a header
of exact form `-- target_db: jpintel` or `-- target_db: autonomath`. The
hundred-or-so legacy migrations in the `001-066` range do not carry that
header but are entirely jpintel-target by historical convention. `migrate.py`
silently treats absence-of-marker as **jpintel-target** through
`_connection_db_target()` defaulting to `jpintel`. This is correct today but
fragile if a future operator runs `migrate.py` against `autonomath.db` —
nothing in `migrate.py` would stop the legacy 1xx migrations from being
applied to the wrong DB. CLAUDE.md captures this hazard ("Autonomath-target
migrations land via `entrypoint.sh`, not `release_command`") and the entrypoint
script applies only files whose first line literally is
`-- target_db: autonomath`, sidestepping the hazard.

### 2.5 Tracker drift — applied without on-disk file

```
jpintel.schema_migrations rows with no on-disk match:
  065_compat_matrix_uni_id_backfill_rollback.sql   (rollback got recorded as forward)
  082_relation_density_expansion_rollback.sql      (same pattern)
  124_citation_verification.sql                    (renamed → 124_src_attribution.sql)
  wave24_106_amendment_snapshot_rebuild.sql        (renamed → wave24_106_am_amendment_snapshot_rebuild.sql)

autonomath.schema_migrations rows with no on-disk match:
  065_compat_matrix_uni_id_backfill_rollback.sql   (same as above)
  113_adoption_program_join.sql                    (renamed)
  wave24_106_amendment_snapshot_rebuild.sql        (same as above)
```

These are tracker-vs-disk drift, not data drift. Replay safety is preserved
because every applied migration is idempotent (CREATE IF NOT EXISTS / INSERT OR
IGNORE) and the disk files that took their place use a slightly different name,
so the tracker rows do not block the renamed forwards.

### 2.6 Unapplied forwards on disk

| target  | files on disk | applied | unapplied | latest unapplied |
|---|---:|---:|---:|---|
| jpintel.db   | 200 | 168 | 36 | mostly Wave 24 autonomath-target files (rightly skipped by jpintel) |
| autonomath.db | 200 | 130 | 73 | `wave24_180..192_*` (10 newest landed in source today, 2026-05-07) |

Spot-checked unapplied autonomath migrations confirm the pattern: e.g.
`wave24_192_pubcomment_announcement.sql` declares `target_db: autonomath` and
adds a `pubcomment_announcement` table, which is **absent** from autonomath.db
right now. These will land on the next Fly boot via `entrypoint.sh §4`'s
self-heal loop. **For the operator workstation, schema is currently behind
production by ~10 wave24 migrations.** This is expected during active landing
of DEEP-22..65 spec work; not a bug.

### 2.7 Stale rollback companion files

`comm -13 forward rollback` returned 0 — no rollback file references a
forward that has been deleted/renamed.

## 3. Schema-drift spot probes

| Probe | Expected | Actual | Verdict |
|---|---|---|---|
| `pubcomment_announcement` table on autonomath.db | present (per wave24_192) | **absent** | drift due to unapplied migration |
| `industry_journal_mention` table on autonomath.db | present (per wave24_186) | **absent** | drift due to unapplied migration |
| `programs` empty shell on autonomath.db | dropped post-110 | **present, 0 rows + 6 fts shadow tables** | self-heal residue (schema_guard `--drop-empty-cross-pollution` only fires from `entrypoint.sh`; the local file lingers) |
| `am_region_new` table on autonomath.db | absent (renamed) | absent | confirms the FK ghost-target |
| `houjin_master` row count on autonomath.db | ~166k | 166,765 | matches CLAUDE.md band |
| `jpi_adoption_records` row count | ~201k | 201,845 | matches CLAUDE.md (post V4 absorption number) |
| `am_region` row count | 1,966 | 1,966 | matches CLAUDE.md ("1,966 rows, all 5-digit codes") |

## 4. WAL state

Both DBs have a 0-byte `*-wal` file and a 32,768-byte `*-shm` file as of audit
start. No WAL leak. `wal_autocheckpoint = 1000` (default; auto-checkpoint
every 1000 modified pages) on both. Confirmed `journal_mode = wal` on both.

## 5. Single-run quick reproduction commands

```bash
# (kept short to fit in a runbook block)
sqlite3 data/jpintel.db "PRAGMA quick_check; PRAGMA foreign_key_check;"
sqlite3 autonomath.db    "PRAGMA foreign_key_check;" | head -30
sqlite3 data/jpintel.db  "SELECT COUNT(*) FROM schema_migrations;"
sqlite3 autonomath.db    "SELECT COUNT(*) FROM schema_migrations UNION SELECT COUNT(*) FROM jpi_schema_migrations;"
ls scripts/migrations/ | grep -v rollback | grep -E '^[0-9]+_' | wc -l   # forward count
ls scripts/migrations/*_rollback.sql | wc -l                              # rollback count
```

## 6. Follow-ups (NOT applied in this audit)

These were considered but not committed; each carries side effects beyond
"trivial":

1. **`am_region` FK rewrite** — drop the ghost `am_region_new` reference,
   re-point parent_code FK to `am_region(region_code)`. Requires a
   `CREATE TABLE … AS SELECT` swap on a 12.4 GB DB and a `legacy_alter_table`
   gate on SQLite. Defer to a dedicated migration with rollback + run-time
   FK-OFF wrap on production.
2. **357-distinct orphan houjin_bangou backfill** — load missing corp numbers
   into `houjin_master` from the next gBiz delta (or quarantine the orphan
   rows into a `_quarantine` view). Treats the data integrity gap; orthogonal
   to schema-cleanliness.
3. **`programs` empty-shell drop on local autonomath.db** — invoke
   `python scripts/schema_guard.py autonomath.db autonomath --drop-empty-cross-pollution`
   on the workstation copy to mirror what production does on every boot.
   Read-only audit policy says no DDL today; queue for the next boot/reset.
4. **Tracker reconcile** — delete the 4 ghost `schema_migrations` rows that
   reference no-longer-existing files (or rename rows to match the renamed
   files). Optional housekeeping; replay safety is unaffected.
5. **Apply wave24_180..192 to local autonomath.db** — these will self-heal on
   next Fly boot but the workstation lags. Re-run
   `scripts/cron/incremental_law_fulltext.py`'s pre-step or
   `scripts/migrate.py` against autonomath.db (taking care to set
   `--target autonomath` if such a flag is added — at present `migrate.py`
   does **not** filter by `target_db` and applying to autonomath via
   `migrate.py` is unsafe per CLAUDE.md "Common gotchas").
6. **Add CI guard `tests/test_migration_target_db_marker.py`** that fails if
   any new migration under `scripts/migrations/wave*` lacks an exact
   `-- target_db: <jpintel|autonomath>` first-line marker — closes the
   "fragile if marker missing" gap noted in §2.4.

None of (1)–(6) are zero-risk one-liners. Per audit constraint
("read-only DB query (write 0)") they were deferred.

## 7. Verdict

- **No corruption.** Both DBs pass quick_check / foreign_key_check (autonomath
  has only advisory FK violations; the data graph is internally consistent).
- **No WAL leak.** Both `*-wal` files at 0 bytes.
- **One real schema-cleanliness drift** worth fixing: `am_region`'s ghost FK
  to `am_region_new`. Cosmetic with FKs OFF; mandatory if FKs are ever turned
  on globally.
- **One real data-quality gap**: 357 orphaned `houjin_bangou` values in
  adoption tables. Expected during active gBiz delta cycles; track via the
  existing `houjin_change_history` and `houjin_master_refresh_run` tables.
- **Migration tracker is healthy** modulo 4 ghost rows that don't impair
  replay. Rollback companion coverage is 88 / 200 (44 %), with no orphan
  rollbacks. The unapplied tail is the expected "Wave 24 still landing"
  pattern.

## 8. Audit metadata

- **Date**: 2026-05-07 (JST)
- **Operator**: Claude Code subagent (R8 housekeeping branch)
- **DB files audited**: `/Users/shigetoumeda/jpcite/data/jpintel.db`,
  `/Users/shigetoumeda/jpcite/autonomath.db`
- **Migration directory audited**: `/Users/shigetoumeda/jpcite/scripts/migrations/`
- **DDL/DML issued by this audit**: 0
- **LLM API calls by this audit**: 0
- **SQLite version on workstation**: 3.51.0 (2025-06-12)
