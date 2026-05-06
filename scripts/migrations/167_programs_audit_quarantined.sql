-- target_db: jpintel
-- migration 167_programs_audit_quarantined (W21-2 zero-source repair flag)
--
-- Why this exists:
--   Wave 21-2 cross-source verification audit (2026-05-05) found 1,159
--   programs with verification_count = 0 — i.e. zero recognised first-
--   party hostnames across primary source_url + EAV-graph secondaries.
--   Zero-source programs are a 詐欺リスク surface: we cannot point a
--   customer at a primary citation, so the row may not be promoted on
--   any search path (REST, MCP, generated SEO pages, llms.txt feeds).
--
--   The repair pass extends the host classifier where it had genuine
--   first-party gaps (e.g. *.g-reiki.net 例規 hosting, JAXA funding
--   pages, 持続化補助金 official portals, 政府系金融 sites). What it
--   cannot recover is *quarantined* — surfaced internally as data-
--   hygiene work, kept in the table for traceability, but excluded
--   from every customer-facing search surface.
--
-- Schema:
--   audit_quarantined INTEGER NOT NULL DEFAULT 0
--     1 = quarantined by Wave 21-2 zero-source repair (or any future
--     hygiene sweep). 0 = healthy. Boolean stored as 0/1 to align with
--     the existing `excluded` column convention. Treated as part of
--     the search-surface filter alongside `excluded` and `tier='X'`.
--
--   audit_quarantined_reason TEXT
--     Free-text label for the quarantine reason (e.g.
--     'w21_2_zero_source_unrecoverable'). NULL when audit_quarantined=0.
--
--   audit_quarantined_at TEXT
--     ISO-8601 UTC timestamp set when audit_quarantined flips 0 -> 1.
--     NULL when audit_quarantined=0. Never modified on rerun (idempotent
--     repair re-applies the flag without rewriting the timestamp).
--
-- Idempotency:
--   ALTER TABLE ADD COLUMN is no-op on the second run for the duplicate-
--   column-skipping path in scripts/migrate.py. Index creation uses IF
--   NOT EXISTS. Repair script (separate) is also rerunnable.
--
-- Search-surface impact:
--   Consumers must AND (audit_quarantined = 0) into the existing
--   (excluded = 0 AND tier IN ('S','A','B','C')) filter. Equivalent to
--   demoting the row to tier X without rewriting the tier column —
--   tier ranking algorithms keep working.
--
-- DOWN:
--   SQLite < 3.35 cannot DROP COLUMN. Rollback is a no-op (column
--   stays, defaults to 0, search filter remains valid).

PRAGMA foreign_keys = ON;

ALTER TABLE programs ADD COLUMN audit_quarantined INTEGER NOT NULL DEFAULT 0;
ALTER TABLE programs ADD COLUMN audit_quarantined_reason TEXT;
ALTER TABLE programs ADD COLUMN audit_quarantined_at TEXT;

CREATE INDEX IF NOT EXISTS idx_programs_audit_quarantined
  ON programs (audit_quarantined)
  WHERE audit_quarantined = 1;

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
