-- target_db: autonomath
-- migration: 273_rule_tree_v2_chain
-- generated_at: 2026-05-12
-- author: Wave 47 — Dim M (rule_tree v2 chain extension)
-- idempotent: every CREATE uses IF NOT EXISTS; no DESTRUCTIVE DML.
--
-- Purpose
-- -------
-- Extends Dim K (PR #152, mig 271 — single rule-tree catalogue) with
-- two production-grade capabilities required for agent-side chained
-- compliance / DD / underwriting workflows:
--
--   1. **Chain (tree → tree)**: an ordered sequence of tree_ids where
--      the *output* of tree N (path + classification + extracted facts)
--      feeds the *input* of tree N+1. A chain is a single deterministic
--      forensics object so the agent can replay a "補助金 → 業法 → DD"
--      decision as one auditable artefact.
--
--   2. **Version history**: a per-tree append-only audit trail of every
--      committed definition change (definition_hash + changed_at +
--      change_note) so the team can diff "what changed between v3 and v4"
--      and replay an old decision under the exact tree definition that
--      produced it.
--
-- Both layers are additive — they do not edit ``am_rule_trees`` (mig 271)
-- schema. PR #152 stays the schema authority for tree definitions; this
-- migration only references ``am_rule_trees.tree_id`` semantically (via
-- TEXT columns) rather than via SQL FK so a chain row can survive a
-- tree-row retirement (the retired def is recoverable via the version
-- history join).
--
-- Pattern
-- -------
-- - ``am_rule_tree_chain``: catalogue of named chains, ordered_tree_ids
--   stored as JSON array of (tree_id, version_pin?) tuples so we can
--   either follow latest or pin a specific tree version.
-- - ``am_rule_tree_version_history``: append-only changelog. Every time
--   ``am_rule_trees`` gets a new version row, the ETL writes one row
--   here with the canonical-JSON sha256 of the new definition.
--
-- Why not extend ``am_rule_trees`` directly?
-- ------------------------------------------
-- mig 271 is in production (PR #152 merged). Touching its schema would
-- require a DDL migration on the live ``autonomath.db`` (9.7 GB) which
-- violates ``feedback_no_quick_check_on_huge_sqlite`` (boot-time risk).
-- Two side tables are pure-additive: zero impact on PR #152's eval
-- kernel + zero risk during boot.
--
-- ¥3/req billing posture
-- ----------------------
-- A chain eval (composed_tools/eval_rule_chain wrapper) collapses N
-- tree evals into 1 metered ¥3/req unit per Dim P (composable_tools).
-- The storage layer here just makes that composition replayable.
--
-- Retention
-- ---------
-- am_rule_tree_chain: indefinite (catalogue).
-- am_rule_tree_version_history: indefinite (we never want to lose
-- forensic evidence of an old tree definition).
--
-- §52 / §47条の2 / §72 / §1 disclaimer parity is enforced by the REST
-- envelope on top, not this SQL layer.

PRAGMA foreign_keys = ON;

BEGIN;

-- 1) Chain catalogue: ordered list of tree_ids forming a decision pipeline.
CREATE TABLE IF NOT EXISTS am_rule_tree_chain (
    chain_id            TEXT PRIMARY KEY,                    -- e.g. 'subsidy_then_gyouhou_then_dd_v1'
    description         TEXT,
    domain              TEXT,                                 -- subsidy_pipeline / dd_pipeline / etc.
    ordered_tree_ids    TEXT NOT NULL,                        -- JSON array [{"tree_id":..,"version_pin":..|null,"carry_keys":[...]} ...]
    source_doc_id       TEXT,                                 -- Dim O citation anchor for the chain itself
    status              TEXT NOT NULL DEFAULT 'committed'     -- committed / draft / retired
                        CHECK (status IN ('committed','draft','retired')),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_am_rule_tree_chain_domain_status
    ON am_rule_tree_chain(domain, status);

-- 2) Per-tree append-only definition history (one row per committed version).
-- definition_hash = sha256(canonical JSON of tree_def_json) for tamper-evidence.
CREATE TABLE IF NOT EXISTS am_rule_tree_version_history (
    history_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tree_id             TEXT NOT NULL,                        -- matches am_rule_trees.tree_id (no SQL FK by design)
    version_seq         INTEGER NOT NULL                       -- matches am_rule_trees.version
                        CHECK (version_seq >= 1),
    definition_hash     TEXT NOT NULL,                        -- sha256 hex of canonicalised tree_def_json
    change_note         TEXT,                                  -- human-readable diff summary
    changed_by          TEXT,                                  -- operator id / ETL run id
    changed_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (tree_id, version_seq)
);

CREATE INDEX IF NOT EXISTS idx_am_rule_tree_version_history_tree_seq
    ON am_rule_tree_version_history(tree_id, version_seq DESC);

CREATE INDEX IF NOT EXISTS idx_am_rule_tree_version_history_hash
    ON am_rule_tree_version_history(definition_hash);

-- Helper view: latest tracked version per tree_id (parallels v_rule_trees_latest
-- but driven by the history rows, so it works even when am_rule_trees was
-- retired/rebuilt at runtime).
DROP VIEW IF EXISTS v_rule_tree_version_history_latest;
CREATE VIEW v_rule_tree_version_history_latest AS
SELECT
    tree_id,
    MAX(version_seq)    AS latest_seq,
    COUNT(*)            AS total_history_rows
FROM am_rule_tree_version_history
GROUP BY tree_id;

COMMIT;
