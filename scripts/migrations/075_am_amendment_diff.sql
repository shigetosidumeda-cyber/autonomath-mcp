-- target_db: autonomath
-- migration 075_am_amendment_diff (Z3 — replace phantom amendment-snapshot moat with a real diff log)
--
-- Why this exists:
--   `am_amendment_snapshot` advertises a per-program time-series of eligibility
--   changes (14,596 rows across version_seq=1, 2, ...). Z3 audit (2026-04-28)
--   confirmed the supposed time-series is fake: 100% of (v1, v2) pairs share
--   the SAME `eligibility_hash`. The "two-version snapshot" was a bulk
--   bookkeeping artifact, not a real change log. `query_at_snapshot`,
--   `program_lifecycle`, and the X9 Hygiene moat layer all silently degrade
--   to "no useful change history."
--
--   This migration introduces the real append-only diff log. Going forward,
--   `scripts/cron/refresh_amendment_diff.py` recomputes per-field hashes from
--   the LIVE `am_entity_facts` snapshot, compares against the previous
--   recorded hash for the same (entity_id, field_name), and inserts ONE row
--   per genuine value change. When nothing changed, nothing is written —
--   running the cron twice in a row is a no-op.
--
-- Why a NEW table (not fix the old one):
--   * `am_amendment_snapshot` is referenced by `programs_active_at_v2` (mig
--     070) and several MCP tools (`query_at_snapshot`, `program_lifecycle`).
--     Mutating its 14,596 rows in-place would silently rewrite every join
--     they perform. The legacy table stays — it is the read model for the
--     "current effective window" projection. The new diff table sits
--     alongside as the change log.
--   * The legacy table records snapshot METADATA (version_seq, observed_at,
--     amount_max_yen, target_set_json, raw_snapshot_json). The new diff
--     table records a SINGLE FIELD-LEVEL change per row, which is what an
--     auditor / customer actually wants to query.
--
-- Append-only contract:
--   No UPDATE, no DELETE, no UPSERT. Once a diff row is written it is final.
--   The cron uses INSERT only. Schema enforces this via no UNIQUE constraint
--   on (entity_id, field_name) — same field can change repeatedly and we
--   want every change preserved.
--
-- DOWN: not provided — append-only audit log is read-only and dropping the
-- table would destroy provenance the customer paid (¥3/req) to query.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_amendment_diff (
    diff_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id      TEXT NOT NULL,                          -- am_entities.canonical_id
    field_name     TEXT NOT NULL,                          -- e.g. 'eligibility_text', 'amount_max_yen', 'deadline'
    prev_value     TEXT,                                   -- canonical string of the previous value (NULL on first observation)
    new_value      TEXT,                                   -- canonical string of the new value (NULL when field disappeared)
    prev_hash      TEXT,                                   -- sha256(prev_value); NULL on first observation
    new_hash       TEXT,                                   -- sha256(new_value); NULL when field disappeared
    detected_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_url     TEXT,                                   -- which fetch produced this diff (am_entities.source_url at detection time)
    FOREIGN KEY (entity_id) REFERENCES am_entities(canonical_id)
);

CREATE INDEX IF NOT EXISTS ix_am_amendment_diff_entity_time
    ON am_amendment_diff(entity_id, detected_at DESC);

CREATE INDEX IF NOT EXISTS ix_am_amendment_diff_field
    ON am_amendment_diff(field_name, detected_at DESC);

-- Bookkeeping recorded by scripts/migrate.py.
