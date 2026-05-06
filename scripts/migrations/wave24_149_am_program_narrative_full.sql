-- target_db: autonomath
-- migration wave24_149_am_program_narrative_full
--   (W20 — pre-rendered "full" narrative + 反駁 (counter-argument) bank
--    cache, distinct from the 4-section am_program_narrative shipped in
--    wave24_136.)
--
-- Why a separate table (not a column add to am_program_narrative)
-- ----------------------------------------------------------------
-- wave24_136 stores narrative content as one row per
-- (program_id × lang × section), where section ∈
-- {overview, eligibility, application_flow, pitfalls}. That schema is
-- correct for the §10.8 4-panel envelope but cannot represent a single
-- coherent prose narrative + a paired 反駁 bank without either
-- (a) overloading the `section` enum with two new values that would
--     break every CHECK / index / FTS rule wired against the 4-tuple,
-- (b) ALTERing the UNIQUE (program_id, lang, section) contract.
--
-- The W20 use case is different: pre-render exactly ONE markdown body
-- per program (ja only at first) plus a parallel 反駁 markdown bank
-- (this narrative の弱点・反論). It is keyed `program_id PRIMARY KEY`
-- (one row per program), not a triple. Mixing it into the 4-section
-- table would force `section='full'` + `section='counter'` rows that
-- violate the original CHECK constraint.
--
-- Therefore W20 lives in a sibling table, `am_program_narrative_full`.
-- The MCP `get_program_narrative` tool (Wave24 #107) keeps its
-- existing 4-section path; a new W20 fast-path checks
-- am_program_narrative_full FIRST and returns the cached row when
-- present (no LLM, no on-demand path on the operator side). Customer
-- LLM on-demand fallback is the caller's choice.
--
-- Generation pipeline
-- -------------------
-- Per `feedback_no_operator_llm_api`, jpcite operator code MUST NOT
-- import anthropic / openai / claude_agent_sdk. Population happens via
-- Claude Code subagent batch on the operator workstation:
--   1. tools/offline/generate_program_narratives.py shards the 11,601
--      tier-S/A/B/C programs into 25 batches under
--      tools/offline/_inbox/narrative/_batches/agentN.json
--   2. Operator launches 25 parallel Claude Code subagents (Max Pro
--      Plan,固定費). Each subagent reads its assigned batch JSON and
--      writes one JSONL row per program into
--      tools/offline/_inbox/narrative/{date}_{N}.jsonl
--   3. tools/offline/ingest_narrative_inbox.py validates + UPSERTs into
--      this table. CONFLICT resolution: content_hash diff ⇒ overwrite
--      and bump generated_at; same hash ⇒ no-op (idempotent re-ingest).
--
-- Schema
-- ------
-- * program_id TEXT PRIMARY KEY
--     joins to programs.unified_id (jpintel) / jpi_programs.unified_id
--     (autonomath mirror). Stored as TEXT to mirror the on-disk
--     unified_id format ('UNI-...' literals). NOT an FK because the two
--     DBs are physically merged but the 3,600+ excluded rows have a
--     different lifecycle and we never want a cascade.
-- * narrative_md       — 制度概説 markdown body (full prose)
-- * counter_arguments_md — 反駁 bank markdown (この narrative の弱点 /
--                          反論 / よくある誤解 を整理した auditor 補助)
-- * generated_at       — ISO8601 UTC, defaults to insert wall clock
-- * model_used         — subagent / model identifier (e.g.
--                        'claude-opus-4-7'); audited per row
-- * content_hash       — SHA-256 hex over narrative_md ++ '\n---\n' ++
--                        counter_arguments_md (used for cheap diff +
--                        idempotent re-ingest gate)
-- * source_program_corpus_snapshot_id — opaque trace id of the
--                        am_corpus_snapshot the subagent saw at
--                        generation time (for auditor reproducibility)
--
-- Indexes
-- -------
-- * idx_apnf_generated_at — supports 'show me the 20 oldest cached
--                            narratives' rebuild planner queries
-- * idx_apnf_model_used   — supports 'how many rows are stuck on the
--                            pre-Opus-4-7 model' migration KPIs
--
-- Idempotency
-- -----------
-- * CREATE TABLE IF NOT EXISTS  — re-apply on every Fly boot (entrypoint
--   §4) is a no-op
-- * CREATE INDEX IF NOT EXISTS  — same
-- * No data inserted in this migration; rows are populated by W20 batch.
--
-- DOWN: see companion `wave24_149_am_program_narrative_full_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_program_narrative_full (
    program_id                          TEXT PRIMARY KEY,
    narrative_md                        TEXT NOT NULL,
    counter_arguments_md                TEXT,
    generated_at                        TEXT NOT NULL DEFAULT (datetime('now')),
    model_used                          TEXT,
    content_hash                        TEXT,
    source_program_corpus_snapshot_id   TEXT
);

CREATE INDEX IF NOT EXISTS idx_apnf_generated_at
    ON am_program_narrative_full(generated_at);

CREATE INDEX IF NOT EXISTS idx_apnf_model_used
    ON am_program_narrative_full(model_used);
