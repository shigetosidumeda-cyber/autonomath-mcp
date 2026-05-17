# CL7 — 5 Unapplied Migration Apply Prescription (READ-ONLY audit)

**Date:** 2026-05-17 (evening)
**Lane:** `lane:solo` (audit only — apply is a separate lane, CodeX-scoped)
**Scope:** 6 migration files landed in `scripts/migrations/` but **not yet applied** to `autonomath.db`, and **not yet registered** in the boot manifest.
**Posture:** READ-ONLY. This doc prescribes commands; it does not execute them.

---

## 1. State as of 2026-05-17 evening

`.venv/bin/python` probe against `/Users/shigetoumeda/jpcite/autonomath.db` confirms all 6 target tables are absent:

| Table | autonomath.db state |
| --- | --- |
| `am_outcome_chunk_map` | NOT_EXIST |
| `am_outcome_cohort_variant` | NOT_EXIST |
| `am_nta_qa` | NOT_EXIST |
| `am_chihouzei_tsutatsu` | NOT_EXIST |
| `am_pdf_watch_log` | NOT_EXIST |
| `am_municipality_subsidy` | NOT_EXIST |

`grep -E "wave24_2(12|13|16|17|20|21)"` against both manifests:

- `scripts/migrations/autonomath_boot_manifest.txt` — **0 hits** for all 6.
- `scripts/migrations/jpcite_boot_manifest.txt` — **0 hits** for all 6.

Consequence under `entrypoint.sh §4` (lines 564–597, `AUTONOMATH_BOOT_MIGRATION_MODE=manifest` default): the boot self-heal loop iterates every `scripts/migrations/*.sql`, calls `am_mig_in_manifest`, and **skips** any filename not present in the manifest. None of the 6 files will auto-apply on `fly deploy` regardless of how many times the machine reboots. The migrations are dormant.

`PRAGMA migration_apply` is not a real SQLite pragma; the actual apply path is `sqlite3 <DB> < <file.sql>` (or `Connection.executescript` from Python). All 6 files are `target_db: autonomath` (header line 1 confirmed) and use only `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` / `CREATE VIRTUAL TABLE IF NOT EXISTS` / `CREATE TRIGGER IF NOT EXISTS` / `CREATE VIEW IF NOT EXISTS` — pure additive DDL, no DML, fully idempotent.

---

## 2. Per-migration prescription

Working directory for all commands: `/Users/shigetoumeda/jpcite`. Use the repo-rooted `autonomath.db`. Always run `cp -a autonomath.db autonomath.db.bak_$(date -u +%Y%m%dT%H%M%SZ)` first when applying to local SOT.

### 2.1 GG4 — `wave24_220_am_outcome_chunk_map.sql`

- **Path:** `scripts/migrations/wave24_220_am_outcome_chunk_map.sql`
- **Target table:** `am_outcome_chunk_map` (43,200 row target = 432 outcome × 100 chunk)
- **Header:** `-- target_db: autonomath` (line 1 verified)
- **Idempotency:** `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS` × 2. PK `(outcome_id, rank)`. Safe to re-run.
- **boot_manifest status:** NOT registered in autonomath_boot_manifest.txt / jpcite_boot_manifest.txt. Will not auto-apply.
- **DRY_RUN (parse-only, no write):**
  ```bash
  .venv/bin/python -c "
  import sqlite3
  with open('scripts/migrations/wave24_220_am_outcome_chunk_map.sql') as f:
      sql = f.read()
  mem = sqlite3.connect(':memory:')
  mem.executescript(sql)
  print('DRY_RUN_OK: parsed and applied to :memory:')
  mem.close()
  "
  ```
- **LIVE apply:**
  ```bash
  cp -a autonomath.db autonomath.db.bak_$(date -u +%Y%m%dT%H%M%SZ)
  .venv/bin/python -c "
  import sqlite3
  conn = sqlite3.connect('autonomath.db')
  with open('scripts/migrations/wave24_220_am_outcome_chunk_map.sql') as f:
      conn.executescript(f.read())
  conn.commit(); conn.close()
  print('APPLIED: wave24_220_am_outcome_chunk_map')
  "
  .venv/bin/python -c "import sqlite3; print(sqlite3.connect('autonomath.db').execute('SELECT COUNT(*) FROM am_outcome_chunk_map').fetchone())"
  ```
- **Post-apply populate (43,200 rows):**
  ```bash
  .venv/bin/python scripts/aws_credit_ops/pre_map_outcomes_to_top_chunks_2026_05_17.py
  ```
- **boot_manifest registration (required for prod auto-apply on Fly):** append `wave24_220_am_outcome_chunk_map.sql` to BOTH `scripts/migrations/autonomath_boot_manifest.txt` AND `scripts/migrations/jpcite_boot_manifest.txt` (the two MUST stay byte-identical per Wave 46.F dual-read alias).

### 2.2 GG7 — `wave24_221_am_outcome_cohort_variant.sql`

- **Path:** `scripts/migrations/wave24_221_am_outcome_cohort_variant.sql`
- **Target table:** `am_outcome_cohort_variant` (2,160 row target = 432 outcome × 5 cohort)
- **Header:** `-- target_db: autonomath` verified.
- **Idempotency:** `CREATE TABLE IF NOT EXISTS`, `CREATE UNIQUE INDEX IF NOT EXISTS ux_outcome_cohort_variant_tuple ON (outcome_id, cohort)`, `CREATE INDEX IF NOT EXISTS` × 2, `DROP VIEW IF EXISTS v_outcome_cohort_variant_top` followed by `CREATE VIEW`. Re-run is destructive only for the view (acceptable — view is derived).
- **boot_manifest status:** NOT registered.
- **DRY_RUN:** identical pattern to §2.1, substitute filename.
- **LIVE apply:** identical pattern, substitute filename.
- **Post-apply populate:**
  ```bash
  .venv/bin/python scripts/aws_credit_ops/generate_cohort_outcome_variants_2026_05_17.py
  ```

### 2.3 AA1 — `wave24_212_am_nta_qa.sql`

- **Path:** `scripts/migrations/wave24_212_am_nta_qa.sql`
- **Target table:** `am_nta_qa` (~2,150 質疑応答 + 文書回答 target, 7-cat enum)
- **Header:** `-- target_db: autonomath` verified.
- **Idempotency:** `CREATE TABLE IF NOT EXISTS` + 3 `CREATE INDEX IF NOT EXISTS` + `CREATE VIRTUAL TABLE IF NOT EXISTS am_nta_qa_fts` (FTS5 trigram) + 3 `CREATE TRIGGER IF NOT EXISTS` (FTS sync) + 1 `CREATE VIEW IF NOT EXISTS v_am_nta_qa_coverage`. All additive.
- **boot_manifest status:** NOT registered.
- **DRY_RUN / LIVE apply:** identical pattern. Confirm FTS5 trigram tokenizer present in the runtime sqlite build (`SELECT sqlite_compileoption_used('ENABLE_FTS5')` should return 1).
- **Post-apply populate:**
  ```bash
  .venv/bin/python scripts/etl/ingest_nta_qa_to_db_2026_05_17.py
  ```
  (Depends on a successful S3-staged NTA crawl from `scripts/etl/crawl_nta_corpus_2026_05_17.py`; URL repair status is a pre-condition outside this audit's scope.)

### 2.4 AA1 — `wave24_213_am_chihouzei_tsutatsu.sql`

- **Path:** `scripts/migrations/wave24_213_am_chihouzei_tsutatsu.sql`
- **Target table:** `am_chihouzei_tsutatsu` (~6,000 地方税 通達 target × 47 prefecture)
- **Header:** `-- target_db: autonomath` verified.
- **Idempotency:** `CREATE TABLE IF NOT EXISTS` + 3 indexes + FTS5 mirror table + 3 triggers + 1 view, all `IF NOT EXISTS`.
- **boot_manifest status:** NOT registered.
- **DRY_RUN / LIVE apply:** identical pattern.
- **Post-apply populate:**
  ```bash
  .venv/bin/python scripts/etl/ingest_chihouzei_tsutatsu_2026_05_17.py
  ```

### 2.5 CC4 — `wave24_216_am_pdf_watch_log.sql`

- **Path:** `scripts/migrations/wave24_216_am_pdf_watch_log.sql`
- **Target table:** `am_pdf_watch_log` (empty scaffold OK — populated by cron + Lambda after deploy)
- **Header:** `-- target_db: autonomath` verified.
- **Idempotency:** `CREATE TABLE IF NOT EXISTS` (51-value source_kind enum), 6 `CREATE INDEX IF NOT EXISTS`, 1 `CREATE VIEW IF NOT EXISTS v_am_pdf_watch_funnel`. Pure DDL.
- **boot_manifest status:** NOT registered.
- **DRY_RUN / LIVE apply:** identical pattern. After apply, table is correctly empty (count=0); rows arrive via:
  - `scripts/cron/pdf_watch_detect_2026_05_17.py` (hourly poll)
  - `infra/aws/lambda/pdf_watch_textract_submit.py` (SQS drain)
  - `pdf_watch_textract_collect.py` (SNS-triggered)
  - `pdf_watch_kg_extract.py` (spaCy ja_core_news_lg NER, no LLM)

### 2.6 DD2 — `wave24_217_am_municipality_subsidy.sql`

- **Path:** `scripts/migrations/wave24_217_am_municipality_subsidy.sql`
- **Target table:** `am_municipality_subsidy` (empty scaffold OK — populated by DD2 crawler + Textract bulk)
- **Header:** `-- target_db: autonomath` verified.
- **Idempotency:** `CREATE TABLE IF NOT EXISTS` (UNIQUE on `(municipality_code, program_name, source_url)`), 5 indexes, 2 views (`v_municipality_subsidy_by_prefecture`, `v_municipality_subsidy_by_jsic_major`).
- **boot_manifest status:** NOT registered.
- **DRY_RUN / LIVE apply:** identical pattern.
- **Post-apply populate:**
  ```bash
  .venv/bin/python scripts/etl/crawl_municipality_subsidy_2026_05_17.py
  .venv/bin/python scripts/aws_credit_ops/textract_municipality_bulk_2026_05_17.py
  .venv/bin/python scripts/etl/ingest_dd2_municipality_subsidy_2026_05_17.py
  ```
  Cost ceiling: $4,500 worst-case (6,000 PDF × 15 page × $0.05). Respect AWS canary hard-stop budget per `feedback_aws_canary_hard_stop_5_line_defense`.

---

## 3. Generic apply template

Use these two reusable invocations and substitute `<NAME>` with the migration basename (without `.sql`).

**Dry-run (zero impact, parses + applies to in-memory DB):**
```bash
.venv/bin/python -c "
import sqlite3, sys
NAME='<NAME>'
with open(f'scripts/migrations/{NAME}.sql') as f:
    sql = f.read()
m = sqlite3.connect(':memory:')
try:
    m.executescript(sql)
    print(f'DRY_RUN_OK: {NAME}')
except Exception as e:
    print(f'DRY_RUN_FAIL: {NAME}: {e}', file=sys.stderr); sys.exit(1)
m.close()
"
```

**Live apply (autonomath.db, with backup):**
```bash
NAME=<NAME>
cp -a autonomath.db autonomath.db.bak_$(date -u +%Y%m%dT%H%M%SZ) \
  && .venv/bin/python -c "
import sqlite3
NAME='$NAME'
conn = sqlite3.connect('autonomath.db')
with open(f'scripts/migrations/{NAME}.sql') as f:
    conn.executescript(f.read())
conn.commit(); conn.close()
print(f'APPLIED: {NAME}')
"
```

**schema_migrations bookkeeping** is handled by `entrypoint.sh §4` on Fly boot when the migration is in the manifest. For local manual apply, insert the row by hand if downstream tooling depends on it:
```bash
.venv/bin/python -c "
import hashlib, sqlite3, datetime
NAME='<NAME>'
with open(f'scripts/migrations/{NAME}.sql','rb') as f: data=f.read()
conn = sqlite3.connect('autonomath.db')
conn.execute('INSERT OR REPLACE INTO schema_migrations(id, checksum, applied_at) VALUES(?, ?, ?)',
             (NAME, hashlib.sha256(data).hexdigest(),
              datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')))
conn.commit(); conn.close()
"
```

---

## 4. Pre-deploy manifest verify gate

Per `feedback_pre_deploy_manifest_verify` (`boot_manifest ⊇ schema_guard` invariant): for **production** auto-apply, all 6 filenames MUST be appended to BOTH manifests before the next `fly deploy`. Manifest entries (one per line, bare filename, no path):

```
wave24_212_am_nta_qa.sql
wave24_213_am_chihouzei_tsutatsu.sql
wave24_216_am_pdf_watch_log.sql
wave24_217_am_municipality_subsidy.sql
wave24_220_am_outcome_chunk_map.sql
wave24_221_am_outcome_cohort_variant.sql
```

The two manifest files MUST stay byte-identical (Wave 46.F dual-read alias). Use `diff scripts/migrations/jpcite_boot_manifest.txt scripts/migrations/autonomath_boot_manifest.txt` as the gate check.

---

## 5. Responsibility split

- **This audit (Claude, `lane:solo`):** READ-ONLY analysis + prescription doc. No DB writes.
- **Migration apply lane (CodeX, `scripts/` scope):** DRY_RUN → LIVE apply → boot_manifest append → `safe_commit.sh`.
- **Data populate lane (lane TBD per migration):** Each `Post-apply populate` invocation listed above. GG4 + GG7 are local-CPU + FAISS; AA1 depends on URL repair; CC4 + DD2 depend on AWS-side cron + Textract bulk gated by `feedback_aws_canary_hard_stop_5_line_defense`.

---

## 6. References

- `entrypoint.sh` lines 520–620 (autonomath boot self-heal §4)
- `scripts/migrations/autonomath_boot_manifest.txt` (494 lines, 6 target filenames absent)
- `scripts/migrations/jpcite_boot_manifest.txt` (494 lines, byte-identical alias)
- `feedback_pre_deploy_manifest_verify` (memory)
- `feedback_aws_canary_hard_stop_5_line_defense` (memory)
- `project_jpcite_wave60_94_complete` (Wave 60-94 outcome catalog 432 row SOT)
