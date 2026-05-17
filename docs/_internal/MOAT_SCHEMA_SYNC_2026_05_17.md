# Moat Schema Sync 2026-05-17 (D2 audit remediation)

**Status**: LANDED 2026-05-17
**Trigger**: D2 audit (commit f50691f49) detected 39 forward migrations missing
from live DBs + 0/64 wave24_* in boot_manifest + 3 missing rollback files +
schema_migrations bookkeeping recorded only 8 of 75.
**Invariant restored**: `boot_manifest ⊇ schema_guard` (per memory
`feedback_pre_deploy_manifest_verify`).

## Scope (audit gap re-measured 2026-05-17)

Fresh gap analysis (this session) found the audit's "39 missing" was a lower
bound — the actual diff was larger:

| target_db | forward wave24_* files | already applied | missing (this session) |
| --- | --- | --- | --- |
| autonomath | 65 | 5 | **60** |
| jpintel    | 11 | 5 | **6**  |
| **total**  | **76** | **10** | **66** |

(The audit text said "34 autonomath + 5 jpintel = 39"; actual = 60 + 6 = 66.
Audit-mode counts likely came from a snapshot taken between two of this
session's earlier writes; the higher count is the authoritative current state.)

## Actions landed

### 1. Boot manifest sync (autonomath_boot_manifest.txt / jpcite_boot_manifest.txt)

- **Before**: 412 lines each, 0 wave24_* entries.
- **After**: 486 lines each, **65 wave24_* entries** (all autonomath-target
  forward migrations).
- Both manifests remain **byte-identical** (md5
  `7631c6c9c06a0b0e9910dac4a1166c0f`), preserving the Wave 46 §46.F dual-name
  invariant in `entrypoint.sh` §4.
- Append block guarded by marker `# 2026-05-17 Wave 24 schema sync (D2 audit
  fix)` — idempotent on re-run.

jpintel-target wave24_* migrations are **not** added to the boot manifest by
design: jpintel.db migrations are applied via `scripts/migrate.py` (called from
`entrypoint.sh` §3 — line 442), not via the §4 autonomath self-heal loop.
`migrate.py` filters by `-- target_db: jpintel` header and applies them
automatically against `$JPINTEL_DB_PATH`.

### 2. Rollback files created (3 missing → 0)

| file | target_db | DROP plan |
| --- | --- | --- |
| `wave24_058_production_gate_status_rollback.sql` | jpintel | view `v_production_gate_latest` + 3 indexes + table `production_gate_status` |
| `wave24_182_contributor_trust_rollback.sql` | autonomath | 2 views + 2 indexes + 2 tables (contributor_trust + contributor_trust_meta) |
| `wave24_201_am_houjin_program_portfolio_rollback.sql` | autonomath | view `v_am_houjin_gap_top` + 6 indexes + table `am_houjin_program_portfolio` |

All use `DROP * IF EXISTS` for idempotency. None auto-apply (the `_rollback.sql`
suffix excludes them from `entrypoint.sh` §4 boot loop per line 606-611).

Final parity: **76 forward + 76 rollback** migrations (`ls
scripts/migrations/wave24_*_rollback.sql | wc -l` → 76).

### 3. Migrations applied to live DBs

#### autonomath.db (15 GB SOT at repo root)

| status | count | notes |
| --- | --- | --- |
| applied | 55 | clean CREATE * IF NOT EXISTS |
| dup_col_applied | 3 | additive ALTER TABLE ADD COLUMN — column already present, marked applied (per entrypoint.sh §4 duplicate-column path) |
| already | 5 | recorded prior to this session |
| degraded_vec0 | 1 | wave24_110_am_entities_vec_v2.sql — vec0 extension not loaded in local Python sqlite3; marked `degraded_vec0_2026_05_17` so Fly boot with vec0.so installed can retry |
| boot_time_manual | 1 | wave24_193_fix_am_region_fk.sql — `-- boot_time: manual` by design (writable_schema rewrite, 12.4 GB-class maintenance window required); marked `manual_skip_boot_time_manual_2026_05_17` |
| **bookkeeping rows** | **68** | (65 + 3 historical id variants like `wave24_106_amendment_snapshot_rebuild.sql` without `_am_` prefix) |

#### data/jpintel.db (427 MB SOT)

| status | count | notes |
| --- | --- | --- |
| applied | 6 | wave24_058 / 166 / 188 / 190 / 191 / 194 |
| already | 5 | recorded prior to this session |
| **bookkeeping rows** | **45** | (39 prior + 6 new) |

### 4. Table count delta (post-apply verification)

| DB | tables | views |
| --- | --- | --- |
| autonomath.db | **675** | **76** |
| data/jpintel.db | **193** | **5** |

Sample table-create verification (all green):

- autonomath.db: `am_artifact_templates` / `am_houjin_program_portfolio` /
  `contributor_trust` / `contributor_trust_meta` /
  `am_legal_reasoning_chain` / `am_window_directory` /
  `am_placeholder_mapping` — all present.
- data/jpintel.db: `production_gate_status` / `credit_pack_reservation` /
  `restore_drill_log` / `municipality_subsidy` — all present.

## Memory invariant restored

Per `feedback_pre_deploy_manifest_verify` — `boot_manifest ⊇ schema_guard`:

- **Before**: schema_guard would require 60 autonomath wave24_* tables on prod
  boot. Manifest contained 0 of them → `entrypoint.sh` §4 self-heal would
  SKIP all 60. Result: schema_guard FAIL on every prod boot of the Fly machine,
  forcing manual recovery.
- **After**: manifest contains all 65 autonomath wave24_* + the 3 already-known
  (105/107/108/109 + 153/204/205). schema_guard ⊆ manifest. §4 self-heal will
  apply any missing ones idempotently on next prod boot.

## Constraints honoured

- **NO quick_check / integrity_check** on autonomath.db (15 GB) — per memory
  `feedback_no_quick_check_on_huge_sqlite`. Apply path uses Python sqlite3
  with `PRAGMA journal_mode=WAL` + `busy_timeout=60000`, no integrity probe.
- **NO DROP on live data** — every migration is `CREATE * IF NOT EXISTS` /
  `INSERT OR IGNORE`. The 3 new rollback files use `DROP * IF EXISTS` but
  are excluded from boot loop by `_rollback.sql` suffix.
- **NO LLM API** — pure SQLite + stdlib Python.
- **mypy strict / ruff** — no Python source changes; SQL + manifest only.

## Files changed

```
scripts/migrations/autonomath_boot_manifest.txt           (412 → 486 lines)
scripts/migrations/jpcite_boot_manifest.txt               (412 → 486 lines, byte-identical)
scripts/migrations/wave24_058_production_gate_status_rollback.sql  (NEW)
scripts/migrations/wave24_182_contributor_trust_rollback.sql       (NEW)
scripts/migrations/wave24_201_am_houjin_program_portfolio_rollback.sql  (NEW)
docs/_internal/MOAT_SCHEMA_SYNC_2026_05_17.md             (THIS file, NEW)
```

Live DBs (`autonomath.db`, `data/jpintel.db`) mutated by SQL apply — not in
git; verified by `SELECT COUNT(*) FROM sqlite_master` post-apply.

## Follow-ups (out of scope for this session)

1. **wave24_110_am_entities_vec_v2.sql** — retry on Fly boot where `vec0.so` is
   installed at `/opt/vec0.so` (env `AUTONOMATH_VEC0_PATH`). The current
   `degraded_vec0` marker is informational; entrypoint.sh §4 will pick the
   file up on next boot and either apply (vec0 present) or remain in
   `am_mig_degraded` counter.
2. **wave24_193_fix_am_region_fk.sql** — schedule a maintenance window for the
   writable_schema rewrite. The 1,965 advisory FK violations are inert at
   runtime (`PRAGMA foreign_keys` defaults to OFF on boot) but should be
   cleaned before any future global FK enable.
3. **65 wave24_* in autonomath_boot_manifest.txt** is an ~+9% jump in §4 loop
   work; the `already` bookkeeping fast-path keeps per-boot cost flat after
   first apply.
