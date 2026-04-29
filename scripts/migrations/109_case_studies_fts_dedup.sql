-- target_db: jpintel
-- migration 109_case_studies_fts_dedup
--
-- BUG FIX (caught 2026-04-29 in migration audit):
--
-- Migration 057_case_studies_fts.sql contains a bare
-- `INSERT INTO case_studies_fts SELECT ... FROM case_studies` that
-- duplicates every row on every re-execution. Production jpintel.db
-- has 2× the expected FTS row count (4,572 rows for 2,286 case_studies),
-- meaning every search hit returns the row twice.
--
-- Reproduce:
--   sqlite3 data/jpintel.db "SELECT COUNT(*) FROM case_studies;"      → 2286
--   sqlite3 data/jpintel.db "SELECT COUNT(*) FROM case_studies_fts;"  → 4572
--   sqlite3 data/jpintel.db "SELECT case_id, COUNT(*) FROM case_studies_fts GROUP BY case_id HAVING COUNT(*)>1 LIMIT 3;"
--   → mirasapo_case_118|2
--   → mirasapo_case_119|2
--
-- Fix: invoke FTS5's `rebuild` command, which atomically drops the
-- contents of the FTS index and re-populates from the configured
-- content source. For a non-content FTS5 (the case here — the FTS
-- table is standalone, not declared `content='case_studies'`), the
-- rebuild path is a manual DELETE + INSERT against the same shape
-- the original migration 057 used.
--
-- Idempotency: re-running this migration is safe — the DELETE empties
-- the index, the INSERT repopulates from the canonical case_studies
-- table. End state is always (case_studies row count) FTS rows.

DELETE FROM case_studies_fts;

INSERT INTO case_studies_fts (case_id, company_name, case_title, case_summary, source_excerpt)
SELECT case_id,
       COALESCE(company_name, ''),
       COALESCE(case_title, ''),
       COALESCE(case_summary, ''),
       COALESCE(source_excerpt, '')
FROM case_studies;

-- Bookkeeping recorded by scripts/migrate.py.
