-- target_db: autonomath
-- migration: 233_supplier_chain
-- generated_at: 2026-05-12
-- author: Wave 33 Axis 2c — supplier-chain bipartite precompute (jpcite 2026-05-12)
--
-- Purpose
-- -------
-- Materialize the supplier-chain edge graph anchored at each houjin:
--   houjin (anchor) → partner houjin, with link_type ∈
--     {invoice_registrant_active, invoice_registrant_revoked,
--      adoption_partner, enforcement_subject}.
--
-- Inputs (all autonomath.db, no cross-DB ATTACH):
--   * invoice_registrants (13,801 rows) — 適格事業者 active / revoked status.
--   * jpi_adoption_records (~201k rows, V4-absorbed adoption corpus) —
--     houjin × program co-mention.
--   * am_enforcement_detail (22,258 rows) — 行政処分 subject linkage.
--
-- Why precompute (not a runtime traversal)
-- ----------------------------------------
-- * On-the-fly bipartite walk is O(E^max_hops) — at max_hops=5 with E ~50
--   edges/node, that's 312M paths per request. Memory
--   `feedback_no_quick_check_on_huge_sqlite` rules out runtime full-scan.
-- * GET /v1/supplier/chain/{houjin}?max_hops=3 must return inside the
--   FastMCP 1s envelope and ¥3/req is too costly to absorb the latency.
-- * Daily refresh tolerates 24h staleness — invoice/adoption corpora
--   refresh monthly, enforcement weekly, so 24h is well under upstream
--   cadence.
--
-- Schema
-- ------
-- * chain_id              — autoincrement PRIMARY KEY.
-- * anchor_houjin_bangou  — 13-digit anchor.
-- * partner_houjin_bangou — 13-digit partner. (anchor, partner) order is
--                           directional but the cron emits both directions
--                           so traversal can start from either side.
-- * link_type             — one of 4 enum values (see CHECK).
-- * evidence_url          — primary source URL (invoice-kohyo / METI
--                           採択 PDF / 行政処分 ministry page).
-- * evidence_date         — ISO-8601 yyyy-mm-dd. NULL when the source row
--                           lacks a usable date (rare).
-- * hop_depth             — 1 = direct edge, 2..5 = transitive (computed
--                           by cron via bipartite walk). max_hops=5 cap.
-- * created_at            — when the edge was first emitted.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_supplier_chain (
    chain_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    anchor_houjin_bangou    TEXT NOT NULL,
    partner_houjin_bangou   TEXT NOT NULL,
    link_type               TEXT NOT NULL,
    evidence_url            TEXT,
    evidence_date           TEXT,
    hop_depth               INTEGER NOT NULL DEFAULT 1,
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    CONSTRAINT ck_supplier_chain_type CHECK (link_type IN (
        'invoice_registrant_active',
        'invoice_registrant_revoked',
        'adoption_partner',
        'enforcement_subject'
    )),
    CONSTRAINT ck_supplier_chain_hops CHECK (hop_depth BETWEEN 1 AND 5),
    CONSTRAINT ck_supplier_chain_bangou_len CHECK (
        length(anchor_houjin_bangou) = 13 AND length(partner_houjin_bangou) = 13
    )
);

-- Primary traversal index: GET /v1/supplier/chain/{houjin} pivots on
-- anchor_houjin_bangou and orders by hop_depth ASC.
CREATE INDEX IF NOT EXISTS idx_supplier_chain_anchor
    ON am_supplier_chain(anchor_houjin_bangou, hop_depth ASC);

-- Reverse-direction index: lets the matcher answer "who points to this
-- houjin?" without doing the full-table flip.
CREATE INDEX IF NOT EXISTS idx_supplier_chain_partner
    ON am_supplier_chain(partner_houjin_bangou, hop_depth ASC);

-- Per-link-type filter (e.g. "show me only enforcement-linked partners").
CREATE INDEX IF NOT EXISTS idx_supplier_chain_type
    ON am_supplier_chain(link_type, anchor_houjin_bangou);

-- Unique constraint on (anchor, partner, link_type, hop_depth) — INSERT OR
-- REPLACE in cron. Same pair may legitimately have multiple link_types
-- (a partner can be both adoption_partner AND invoice_registrant_active).
CREATE UNIQUE INDEX IF NOT EXISTS ux_supplier_chain_edge
    ON am_supplier_chain(
        anchor_houjin_bangou,
        partner_houjin_bangou,
        link_type,
        hop_depth
    );

-- Operator view: top anchors by chain breadth (how many partners they
-- connect to). Used for SEO landing-page selection and houjin_360
-- enrichment.
DROP VIEW IF EXISTS v_supplier_chain_breadth;
CREATE VIEW v_supplier_chain_breadth AS
SELECT
    anchor_houjin_bangou,
    COUNT(DISTINCT partner_houjin_bangou) AS partner_count,
    COUNT(DISTINCT link_type) AS link_type_count,
    MAX(hop_depth) AS deepest_hop
FROM am_supplier_chain
GROUP BY anchor_houjin_bangou
ORDER BY partner_count DESC;
