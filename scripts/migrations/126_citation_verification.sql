-- target_db: jpintel
-- migration 126_citation_verification
--
-- §4.3 (jpcite_ai_discovery_paid_adoption_plan_2026-05-04.md) — persist
-- citation verification verdicts so Evidence Packets can surface a per-
-- citation `verification_status` / `verified_at` / `source_checksum`
-- without re-fetching every source URL on every request.
--
-- The runtime verifier (`src/jpintel_mcp/services/citation_verifier.py`)
-- already produces deterministic verdicts (verified / inferred / unknown
-- and a stale path keyed off source_checksum drift). Today those verdicts
-- only live in the request response. This table is the durable join target
-- so the Evidence Packet composer (§4.3 deliverable) can attach the latest
-- verdict to each citation it surfaces.
--
-- Schema (one row per (entity_id, source_url) verification snapshot):
--   id                    INTEGER PRIMARY KEY AUTOINCREMENT
--   entity_id             TEXT NOT NULL  — am canonical_id (e.g.
--                         `program:evp:p1`) or jpintel UNI-id; the same
--                         identifier the Evidence Packet record uses.
--   source_url            TEXT NOT NULL  — the cited URL; matches
--                         `am_source.source_url` / `record.source_url`.
--   verification_status   TEXT NOT NULL  — closed enum, mirrors
--                         `services.citation_verifier.VerificationResult`:
--                         {'verified', 'inferred', 'unknown', 'stale'}.
--   matched_form          TEXT           — the literal substring or numeric
--                         form that substantiated `verified` (NULL otherwise).
--   source_checksum       TEXT           — sha256 over the normalized source
--                         text at verify time; later runs compare against
--                         this to detect drift → emit 'stale'.
--   verified_at           TIMESTAMP NOT NULL — when this verdict was recorded.
--   verification_basis    TEXT           — short tag explaining how the
--                         verdict was reached (e.g. `excerpt_substring`,
--                         `numeric_form_match`, `local_catalog_only`,
--                         `live_fetch`, `stale_checksum_drift`).
--
-- Index posture:
--   The Evidence Packet hot path joins by (entity_id, source_url) and reads
--   the most recent verified_at / id pair — so the composite index carries
--   that lookup in one BTree walk.
--
-- Idempotency:
--   `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS` make
--   re-apply a no-op. No `ALTER TABLE` because every column is new.
--   No `INSERT` — initial backfill is a separate task (see §4.3 plan).
--
-- DOWN:
--   Additive only. Drop the index then the table to roll back; no read
--   path depends on the table existing today (composer fails-open when
--   the join returns no rows → status defaults to 'unknown').

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS citation_verification (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id             TEXT NOT NULL,
    source_url            TEXT NOT NULL,
    verification_status   TEXT NOT NULL CHECK (
        verification_status IN ('verified', 'inferred', 'unknown', 'stale')
    ),
    matched_form          TEXT,
    source_checksum       TEXT,
    verified_at           TIMESTAMP NOT NULL,
    verification_basis    TEXT
);

CREATE INDEX IF NOT EXISTS idx_citation_verification_entity_source_verified_at
    ON citation_verification(entity_id, source_url, verified_at DESC, id DESC);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
