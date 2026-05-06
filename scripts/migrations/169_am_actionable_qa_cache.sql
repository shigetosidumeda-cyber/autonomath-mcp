-- target_db: autonomath
-- migration 169_am_actionable_qa_cache
--
-- Wave 30-5: pre-rendered actionable Q/A cache for the top-N intent classes
-- × top-N input combinations (subsidy_search × pref × industry,
-- eligibility_check × program × houjin_size, amendment_diff × program,
-- citation_pack × program). The earlier W28-5 instrumentation measured
-- 0% cache-hit on the on-demand composite path because the actual user
-- intents arrive as parameter shapes, not as (subject_kind, subject_id)
-- — which is what migration 168's am_actionable_answer_cache covers.
-- This new layer keys by (intent_class, sha256(canonical-json input))
-- so the lookup pattern matches how the customer LLM phrases queries.
--
-- Why a SEPARATE table from migration 168:
--   * 168's am_actionable_answer_cache is keyed (subject_kind, subject_id)
--     — fits 360-style composite envelope reads.
--   * This table is keyed (cache_key, intent_class, input_hash) — fits
--     intent×input shape reads (subsidy_search by pref+industry, etc.).
--   * Mixing the two in one table would force every populator + lookup
--     path to disambiguate kind vs intent and would conflate two distinct
--     cache invalidation cadences (168 = corpus snapshot bump,
--     169 = corpus snapshot bump OR intent template bump).
--
-- Schema:
--   cache_key             TEXT PRIMARY KEY  -- "{intent_class}:{input_hash}"
--   intent_class          TEXT NOT NULL     -- one of subsidy_search /
--                                              eligibility_check /
--                                              amendment_diff / citation_pack
--   input_hash            TEXT NOT NULL     -- sha256-hex of canonical-json(input_dict)
--   rendered_answer_json  TEXT NOT NULL     -- compact envelope (json.dumps)
--   rendered_at           INTEGER NOT NULL  -- unix epoch seconds, populator-stamped
--   hit_count             INTEGER NOT NULL DEFAULT 0
--   corpus_snapshot_id    TEXT NOT NULL     -- for invalidation across snapshot bumps
--
--   idx_am_actionable_intent_hash on (intent_class, input_hash)
--     — secondary lookup path: when the customer LLM has split the cache
--     key by `:` themselves, this lets us hit the row by composite without
--     the up-front cache_key concat.
--   idx_am_actionable_rendered_at on (rendered_at DESC)
--     — sweep / age-out path: nightly populator REPLACEs older rows; the
--     index lets `SELECT ... ORDER BY rendered_at DESC LIMIT N` stay O(N).
--
-- Lookup contract (api/intel_actionable.py):
--   GET  /v1/intel/actionable/{cache_key}
--     SELECT rendered_answer_json FROM am_actionable_qa_cache
--      WHERE cache_key = ?
--     -> on hit: UPDATE hit_count = hit_count + 1, return envelope
--     -> on miss: 404
--   POST /v1/intel/actionable/lookup  body={intent_class, input_dict}
--     server: input_hash = sha256_hex(canonical_json(input_dict))
--             cache_key  = f"{intent_class}:{input_hash}"
--     SELECT rendered_answer_json FROM am_actionable_qa_cache
--      WHERE cache_key = ?
--     -> on hit: UPDATE hit_count++, return envelope
--     -> on miss: 404 with {_not_cached: true, intent_class, input_hash}
--
-- Idempotency:
--   * CREATE TABLE / INDEX IF NOT EXISTS — entrypoint.sh §4 self-heal
--     re-runs on every Fly boot are safe.
--   * Populator (scripts/cron/precompute_actionable_answers.py) uses
--     INSERT OR REPLACE on cache_key so the same row can be re-warmed
--     across corpus snapshots without uniqueness violations.
--
-- Search-surface impact: NONE. Derived cache only; no first-party data.
--   Consumers MUST tolerate 404 (cache miss) by falling through to the
--   on-demand composer — never mask a fresh row with a stale cache hit.
--
-- DOWN: companion file *_rollback.sql drops the table + indexes.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_actionable_qa_cache (
  cache_key             TEXT PRIMARY KEY,
  intent_class          TEXT NOT NULL,
  input_hash            TEXT NOT NULL,
  rendered_answer_json  TEXT NOT NULL,
  rendered_at           INTEGER NOT NULL,
  hit_count             INTEGER NOT NULL DEFAULT 0,
  corpus_snapshot_id    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_am_actionable_intent_hash
  ON am_actionable_qa_cache(intent_class, input_hash);

CREATE INDEX IF NOT EXISTS idx_am_actionable_rendered_at
  ON am_actionable_qa_cache(rendered_at DESC);

-- Bookkeeping is recorded by entrypoint.sh §4 self-heal loop into
-- schema_migrations(id, checksum, applied_at). Do NOT INSERT here.
