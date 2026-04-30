-- target_db: jpintel
-- migration 112_alias_candidates_queue
--
-- Why: weekly cron `alias_dict_expansion.py` mines `empty_search_log` (mig 062)
-- for queries that returned 0 results, normalizes them via pykakasi, and
-- compares against the existing alias dictionary (`am_alias` 335,605 rows
-- + `_AUTHORITY_LEVEL_ALIASES` / `_PREFECTURE_ALIASES` / `_JSIC_ALIASES`
-- in `api/vocab.py`). The proposals land here for operator review BEFORE
-- they touch `am_alias` — production write 必ず review 後 (Plan §8.7).
--
-- Lives in jpintel.db so the cron can JOIN against `empty_search_log`
-- without cross-DB ATTACH (architecture forbids cross-DB JOIN). The
-- review CLI (`jpintel_mcp.loops.alias_review`) is the ONLY surface that
-- writes to `am_alias` in autonomath.db; the queue itself never auto-promotes.
--
-- Idempotent: every CREATE uses IF NOT EXISTS. Safe to re-run on every
-- boot via entrypoint.sh §4 (jpintel target lands via migrate.py — this
-- file's IF NOT EXISTS posture survives both code paths).

CREATE TABLE IF NOT EXISTS alias_candidates_queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  candidate_alias TEXT NOT NULL,
  canonical_term TEXT NOT NULL,
  match_score REAL NOT NULL,
  empty_query_count INTEGER NOT NULL,
  first_seen TIMESTAMP NOT NULL,
  last_seen TIMESTAMP NOT NULL,
  status TEXT DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
  reviewed_at TIMESTAMP,
  reviewer TEXT,
  UNIQUE(candidate_alias, canonical_term)
);

CREATE INDEX IF NOT EXISTS idx_alias_candidates_status
    ON alias_candidates_queue(status);
