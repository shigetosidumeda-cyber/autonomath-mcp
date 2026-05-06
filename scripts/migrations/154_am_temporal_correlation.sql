-- target_db: autonomath
-- migration 154_am_temporal_correlation
--
-- Why this exists (post Wave 23 / pre-launch substrate, 2026-05-05):
--   We want a temporal-correlation surface that links 法令改正 →
--   制度変更 → 採択動向. Source signals today are sparse:
--     * `am_amendment_diff` is empty (cron populates post-launch).
--     * `am_amendment_snapshot` carries 14,596 captures but only ~144
--       rows expose a definitive `effective_from` date that is safe to
--       seed a time-series with.
--     * `jpi_adoption_records` (201,845 rows) holds adoption dates but
--       only a small subset has resolved `program_id` joins.
--   This mat view is **substrate-ready**: it precomputes pre/post
--   adoption-count windows around every datable amendment and stores
--   the post-to-pre ratio so downstream tools (and humans reading the
--   weekly KPI digest) can rank "amendment X correlated with N% jump
--   in adoptions" without re-deriving the join. Launch-day signal is
--   intentionally weak — cron-driven `am_amendment_diff` ingest will
--   compound the row count over weeks.
--
-- Schema:
--   * amendment_id TEXT NOT NULL              — am_amendment_snapshot.snapshot_id
--                                               (string-cast for forward
--                                               compatibility with future
--                                               am_amendment_diff.diff_id seed)
--   * amendment_effective_at TEXT NOT NULL    — normalized YYYY-MM-DD
--                                               (parsed from
--                                               am_amendment_snapshot.effective_from)
--   * law_canonical_id TEXT NOT NULL          — am_law_reference.law_canonical_id
--                                               or '' (empty string) when the
--                                               amendment carries no resolved
--                                               law citation. Sentinel '' lets
--                                               the PRIMARY KEY hold without
--                                               forcing every amendment through
--                                               a law join.
--   * program_id TEXT                         — jpi_programs.unified_id;
--                                               NULL when no program join could
--                                               be resolved via entity_id_map.
--   * adoption_count_pre30d  INTEGER          — adoptions in [-30d, 0)
--   * adoption_count_post30d INTEGER          — adoptions in (0,  +30d]
--   * adoption_count_pre90d  INTEGER          — adoptions in [-90d, 0)
--   * adoption_count_post90d INTEGER          — adoptions in (0,  +90d]
--   * ratio_post_to_pre REAL                  — post30d / max(pre30d, 1)
--   * computed_at TEXT NOT NULL DEFAULT (datetime('now'))
--   * PRIMARY KEY (amendment_id, program_id)  — one row per (amendment ×
--                                               affected program). NULL
--                                               program_id rows still hold
--                                               under SQLite's NULLs-distinct
--                                               PK semantics, but populator
--                                               replaces NULL with '' to make
--                                               re-runs deterministic.
--
-- Indexes:
--   * (amendment_effective_at DESC) — time-series scans
--   * (ratio_post_to_pre DESC) WHERE ratio_post_to_pre IS NOT NULL
--     — top-correlation rollups
--   * (law_canonical_id, amendment_effective_at DESC)
--     — "what changed under 法律 X recently" lookups
--
-- Populator:
--   `scripts/etl/build_temporal_correlation.py` (NON-LLM). Walks
--   am_amendment_snapshot dated rows → am_law_reference (for
--   law_canonical_id) → entity_id_map (for jpi_programs.unified_id) →
--   jpi_adoption_records (for date-bounded counts). Re-runs are
--   idempotent (DELETE FROM am_temporal_correlation; INSERT ... in a
--   single transaction).
--
-- Idempotency:
--   CREATE TABLE / INDEX use IF NOT EXISTS. Population is full-rebuild
--   (the table is small, dated source rows ~144, so a wipe+repopulate
--   is cheaper than a per-row UPSERT and avoids stale-PK drift when
--   am_amendment_diff later joins in alongside snapshots).
--
-- DOWN:
--   See companion 154_am_temporal_correlation_rollback.sql.
--
-- Bookkeeping is recorded by entrypoint.sh autonomath self-heal loop
-- into schema_migrations(id, checksum, applied_at). Do NOT INSERT here.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_temporal_correlation (
    amendment_id              TEXT NOT NULL,
    amendment_effective_at    TEXT NOT NULL,
    law_canonical_id          TEXT NOT NULL DEFAULT '',
    program_id                TEXT NOT NULL DEFAULT '',
    adoption_count_pre30d     INTEGER NOT NULL DEFAULT 0,
    adoption_count_post30d    INTEGER NOT NULL DEFAULT 0,
    adoption_count_pre90d     INTEGER NOT NULL DEFAULT 0,
    adoption_count_post90d    INTEGER NOT NULL DEFAULT 0,
    ratio_post_to_pre         REAL,
    computed_at               TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (amendment_id, program_id)
);

CREATE INDEX IF NOT EXISTS idx_atc_effective
    ON am_temporal_correlation(amendment_effective_at DESC);

CREATE INDEX IF NOT EXISTS idx_atc_ratio
    ON am_temporal_correlation(ratio_post_to_pre DESC)
    WHERE ratio_post_to_pre IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_atc_law_effective
    ON am_temporal_correlation(law_canonical_id, amendment_effective_at DESC);
