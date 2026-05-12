-- target_db: autonomath
-- migration: 271_rule_tree
-- generated_at: 2026-05-12
-- author: Wave 47 — Dim K (rule_tree_branching) storage layer
-- idempotent: every CREATE uses IF NOT EXISTS; no DESTRUCTIVE DML.
--
-- Purpose
-- -------
-- Persists the rule-tree definitions consumed by /v1/rule_tree/evaluate
-- (src/jpintel_mcp/api/rule_tree_eval.py, Dim K). The REST surface itself
-- stays purely functional (caller posts the tree inline) but production
-- agents need a curated catalogue of named, versioned trees they can
-- evaluate by reference: 補助金適格性 / 業法 fence / 投資条件 / 採択 /
-- DD 5 canonical trees seeded by scripts/etl/seed_rule_tree_definitions.py.
--
-- Pattern
-- -------
-- Tree definition is stored as a single JSON blob (tree_def_json) keyed by
-- a stable (tree_id, version) tuple. Editing a tree means INSERTing a new
-- version row; the eval surface picks the latest committed version (or a
-- pinned one if the caller specifies). Each evaluation is logged into
-- am_rule_tree_eval_log with an input_hash (sha256 of canonicalised
-- input) + the result_path so downstream forensics can replay or audit a
-- past decision without re-running the eval.
--
-- Why two tables (not one)
-- ------------------------
-- - am_rule_trees: the catalogue. Small (≤ low thousands of rows over
--   time). Read-heavy; indexed by tree_id + version.
-- - am_rule_tree_eval_log: the audit trail. Append-only, grows linearly
--   with traffic. Indexed by tree_id + created_at for time-window queries.
-- Mixing definition + log on a single table would force a scan over every
-- past eval each time the catalogue is loaded.
--
-- ¥3/req billing posture
-- ----------------------
-- /v1/rule_tree/evaluate stays at 1 metered unit regardless of tree depth
-- (the per-call invariant documented in rule_tree_eval.py). The eval-log
-- side table is internal — no customer-facing read path here.
--
-- Retention
-- ---------
-- am_rule_trees: indefinite (catalogue, source-of-truth for past decisions).
-- am_rule_tree_eval_log: 90-day rolling window swept by dlq_drain.py
-- cleanup pass; failed/aborted evals retained 180d for post-mortem.
--
-- §52 / §47条の2 / §72 / §1 disclaimer parity is enforced by the REST
-- surface envelope (_disclaimer field), not at the SQL layer.

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_rule_trees (
    row_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tree_id           TEXT NOT NULL,                       -- e.g. 'subsidy_eligibility_v1'
    version           INTEGER NOT NULL DEFAULT 1
                      CHECK (version >= 1),
    tree_def_json     TEXT NOT NULL,                       -- canonical JSON tree def
    source_doc_id     TEXT,                                -- Dim O citation anchor
    description       TEXT,
    domain            TEXT,                                -- subsidy / gyouhou_fence / etc.
    status            TEXT NOT NULL DEFAULT 'committed'    -- committed / draft / retired
                      CHECK (status IN ('committed','draft','retired')),
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (tree_id, version)
);

CREATE INDEX IF NOT EXISTS idx_am_rule_trees_tree_version
    ON am_rule_trees(tree_id, version DESC);

CREATE INDEX IF NOT EXISTS idx_am_rule_trees_domain_status
    ON am_rule_trees(domain, status);

-- Helper view: latest committed version per tree_id (used by eval surface).
DROP VIEW IF EXISTS v_rule_trees_latest;
CREATE VIEW v_rule_trees_latest AS
SELECT
    tree_id,
    MAX(version)        AS latest_version,
    COUNT(*)            AS total_versions
FROM am_rule_trees
WHERE status = 'committed'
GROUP BY tree_id;

-- Per-eval audit trail.
CREATE TABLE IF NOT EXISTS am_rule_tree_eval_log (
    eval_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tree_id           TEXT NOT NULL,
    tree_version      INTEGER,                             -- nullable for inline-tree evals
    input_hash        TEXT NOT NULL,                       -- sha256 of canonicalised input
    result            TEXT NOT NULL                        -- pass / fail / conditional / error
                      CHECK (result IN ('pass','fail','conditional','error')),
    result_path       TEXT NOT NULL DEFAULT '[]',          -- JSON array of node_ids
    latency_ms        INTEGER NOT NULL DEFAULT 0
                      CHECK (latency_ms >= 0),
    error_message     TEXT,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_am_rule_tree_eval_log_tree_time
    ON am_rule_tree_eval_log(tree_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_rule_tree_eval_log_input_hash
    ON am_rule_tree_eval_log(input_hash);

COMMIT;
