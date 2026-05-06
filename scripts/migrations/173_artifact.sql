-- target_db: autonomath
-- migration 173_artifact
--
-- Schema-only receiver for public-corpus artifacts: raw fetches, normalized
-- HTML/PDF copies, JSONL extraction outputs, benchmark files, and audit proof
-- files that can be referenced by source documents and evidence packets.
--
-- Why this exists:
--   A URL alone is not enough for reproducibility. Downstream artifacts need
--   a stable ledger entry for the stored bytes, checksum, MIME type,
--   retention posture, license, and corpus snapshot that produced or
--   observed the artifact.
--
--   Customer-specific paid deliverables are deliberately out of scope for
--   this migration. Use only public-corpus or non-customer operational
--   artifact rows here.
--
-- Schema notes:
--   * metadata_json / known_gaps_json are serialized JSON TEXT.
--   * corpus_snapshot_id is a soft reference so rollback companions can be
--     operator-run independently during schema review.
--
-- Idempotency:
--   CREATE TABLE / INDEX IF NOT EXISTS. No seed data.
--
-- DOWN:
--   See companion `173_artifact_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS artifact (
    artifact_id            TEXT PRIMARY KEY,
    artifact_kind          TEXT NOT NULL CHECK (artifact_kind IN (
                              'raw_fetch','html','pdf','text','csv','tsv',
                              'json','jsonl','xlsx','docx','report',
                              'benchmark','audit_proof','evidence_attachment',
                              'other'
                          )),
    uri                    TEXT NOT NULL,
    sha256                 TEXT,
    bytes                  INTEGER CHECK (bytes IS NULL OR bytes >= 0),
    mime_type              TEXT,
    retention_class        TEXT NOT NULL DEFAULT 'cache' CHECK (retention_class IN (
                              'cache','temporary','public_release','audit_7y',
                              'derived_public','other'
                          )),
    license                TEXT,
    corpus_snapshot_id     TEXT,
    created_at             TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at             TEXT,
    metadata_json          TEXT NOT NULL DEFAULT '{}',
    known_gaps_json        TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_artifact_kind_created
    ON artifact(artifact_kind, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_artifact_snapshot
    ON artifact(corpus_snapshot_id)
    WHERE corpus_snapshot_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_artifact_sha256
    ON artifact(sha256)
    WHERE sha256 IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_artifact_uri
    ON artifact(uri);

CREATE INDEX IF NOT EXISTS idx_artifact_retention_expires
    ON artifact(retention_class, expires_at)
    WHERE expires_at IS NOT NULL;

-- Bookkeeping is recorded by entrypoint.sh §4 self-heal loop into
-- schema_migrations(id, checksum, applied_at). Do NOT INSERT here.
