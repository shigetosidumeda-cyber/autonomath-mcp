-- target_db: autonomath
-- migration 070_programs_active_at_v2 (O4 — three-axis effective + application window view)
--
-- Materializes `programs_active_at_v2`: a single read-shape that exposes the
-- THREE temporal axes a customer needs in one row:
--   1. effective window         (am_amendment_snapshot.effective_from / _until)
--   2. application_open window  (am_application_round.application_open_date <= now)
--   3. application_close window (am_application_round.application_close_date > now)
--
-- Why a view (not a tool-only join):
--   - SQL is the source of truth so the MCP tool, REST endpoint, and ad-hoc
--     `sqlite3` debug queries see the same predicates.
--   - The view is parameter-free; per-request `as_of` / `application_close_by`
--     filtering happens in WHERE clauses on top of this view.
--
-- Honesty caveat (per O4 analysis 2026-04-25):
--   - `am_amendment_snapshot.effective_from` is filled on only 140 / 14,596 rows.
--     For the other 14,456 rows we fall back to `am_entities.fetched_at` so the
--     row is not silently excluded; the view exposes which source was used via
--     `effective_from_source` so callers can disclaim.
--   - `eligibility_hash` is uniform across (v1, v2) for 100% of pairs — we still
--     use the LATEST version_seq for the snapshot join because that is the
--     correct point-in-time semantics; the time-series fakeness is a separate
--     concern surfaced via `_lifecycle_caveat` at the API layer.
--
-- DOWN: not provided — view is read-only and dropping it does not
-- corrupt write paths.

PRAGMA foreign_keys = ON;

DROP VIEW IF EXISTS programs_active_at_v2;

CREATE VIEW programs_active_at_v2 AS
SELECT
    p.canonical_id                                                       AS unified_id,
    p.primary_name                                                       AS primary_name,
    json_extract(p.raw_json, '$.tier')                                   AS tier,
    json_extract(p.raw_json, '$.prefecture')                             AS prefecture,
    p.authority_canonical                                                AS authority_canonical,
    -- application_round side (one row per program; LEFT JOIN so programs
    -- without any round stay visible — they will not match application_*
    -- filters but still match pure effective filters).
    ar.round_id                                                          AS application_round_id,
    ar.round_label                                                       AS application_round_label,
    ar.application_open_date                                             AS application_open_date,
    ar.application_close_date                                            AS application_close_date,
    ar.status                                                            AS application_status,
    -- amendment_snapshot side (latest version_seq per entity).
    s.snapshot_id                                                        AS amendment_snapshot_id,
    s.version_seq                                                        AS amendment_version_seq,
    s.effective_from                                                     AS effective_from,
    s.effective_until                                                    AS effective_until,
    -- Provenance hint: callers must NOT assume effective_from is authoritative
    -- when source = 'fetched_at_fallback'. See migration header.
    CASE
        WHEN s.effective_from IS NOT NULL THEN 'amendment_snapshot'
        WHEN p.fetched_at IS NOT NULL     THEN 'fetched_at_fallback'
        ELSE                                   'unknown'
    END                                                                  AS effective_from_source,
    -- Computed booleans for `as_of = now` (callers can override via SQL filter).
    CASE
        WHEN COALESCE(s.effective_from, p.fetched_at, '0000-01-01') <= datetime('now')
         AND (s.effective_until IS NULL OR datetime('now') < s.effective_until)
        THEN 1 ELSE 0
    END                                                                  AS is_effective_now,
    CASE
        WHEN ar.application_open_date IS NOT NULL
         AND ar.application_open_date <= datetime('now')
         AND (ar.application_close_date IS NULL
              OR datetime('now') < ar.application_close_date)
        THEN 1 ELSE 0
    END                                                                  AS is_application_open_now
FROM am_entities p
LEFT JOIN am_application_round ar
    ON ar.program_entity_id = p.canonical_id
LEFT JOIN am_amendment_snapshot s
    ON s.entity_id    = p.canonical_id
   AND s.version_seq  = (
        SELECT MAX(version_seq)
          FROM am_amendment_snapshot
         WHERE entity_id = p.canonical_id
       )
WHERE p.record_kind = 'program'
  AND p.canonical_status = 'active';
