-- target_db: autonomath
-- migration: 233_supplier_chain
-- generated_at: 2026-05-12
-- author: Wave 33 Axis 2c — supplier-chain bipartite precompute (jpcite 2026-05-12)
--
-- Purpose
-- -------
-- Materialize supplier-chain edge graph anchored at each houjin across
-- 4 link_type: invoice_registrant_active / invoice_registrant_revoked /
-- adoption_partner / enforcement_subject. Inputs: invoice_registrants
-- (13,801) + jpi_adoption_records (~201k) + am_enforcement_detail (22,258).
-- Cron emits direct edges (hop_depth=1) and BFS-walks up to max_hops=5.
--
-- Why precompute (not a runtime traversal)
-- ----------------------------------------
-- O(E^max_hops) on the fly = 312M paths at max_hops=5; per-call would
-- never fit FastMCP 1s + ¥3/req cost. Daily refresh tolerates 24h
-- staleness — upstream corpora refresh monthly/weekly.

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

CREATE INDEX IF NOT EXISTS idx_supplier_chain_anchor
    ON am_supplier_chain(anchor_houjin_bangou, hop_depth ASC);
CREATE INDEX IF NOT EXISTS idx_supplier_chain_partner
    ON am_supplier_chain(partner_houjin_bangou, hop_depth ASC);
CREATE INDEX IF NOT EXISTS idx_supplier_chain_type
    ON am_supplier_chain(link_type, anchor_houjin_bangou);
CREATE UNIQUE INDEX IF NOT EXISTS ux_supplier_chain_edge
    ON am_supplier_chain(
        anchor_houjin_bangou,
        partner_houjin_bangou,
        link_type,
        hop_depth
    );

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
