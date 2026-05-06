-- target_db: autonomath
-- migration wave24_133_am_invoice_buyer_seller_graph (MASTER_PLAN_v1
-- 章 10.2.8 — 取引相手推論 graph)
--
-- Why this exists:
--   `infer_invoice_buyer_seller` (#104, sensitive=YES) returns
--   "given houjin X, who are X's likely sellers / buyers based on
--   public-source signals". The graph is built offline by
--   `scripts/etl/precompute_invoice_buyer_seller.py` from public
--   adoption joint records, supplier disclosures, and 適格事業者
--   list cross-references. Inference confidence is graded so
--   downstream tools can filter low-confidence edges.
--
-- Schema:
--   * seller_houjin_bangou TEXT NOT NULL
--   * buyer_houjin_bangou  TEXT NOT NULL
--   * confidence REAL NOT NULL              — 0..1
--   * confidence_band TEXT NOT NULL         — 'high'|'medium'|'low'
--   * inferred_industry TEXT                — buyer industry guess
--   * evidence_kind TEXT NOT NULL           — 'public_disclosure'|'joint_adoption'|
--                                             'supplier_list'|'co_filing'|'press_release'
--   * evidence_count INTEGER NOT NULL DEFAULT 1
--   * source_url_json TEXT                  — JSON list of citations
--   * first_seen_at TEXT
--   * last_seen_at TEXT
--   * computed_at TEXT NOT NULL DEFAULT (datetime('now'))
--   * CHECK(seller_houjin_bangou != buyer_houjin_bangou)
--                                          -- no self-trade rows
--   * UNIQUE(seller_houjin_bangou, buyer_houjin_bangou, evidence_kind)
--
--   The seller != buyer CHECK keeps the graph free of self-loops
--   (a houjin trading with itself is uninteresting and would
--   inflate counts).
--
-- Indexes:
--   * (seller_houjin_bangou) — outgoing-edge scan ("who does X sell to").
--   * (buyer_houjin_bangou)  — incoming-edge scan.
--   * (confidence DESC)      — high-confidence-first global scan.
--
-- Idempotency:
--   CREATE * IF NOT EXISTS, UNIQUE makes `INSERT OR REPLACE`
--   the safe upsert for the cron.
--
-- DOWN:
--   See companion `wave24_133_am_invoice_buyer_seller_graph_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_invoice_buyer_seller_graph (
    edge_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_houjin_bangou TEXT NOT NULL,
    buyer_houjin_bangou  TEXT NOT NULL,
    confidence           REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    confidence_band      TEXT NOT NULL CHECK (confidence_band IN ('high','medium','low')),
    inferred_industry    TEXT,
    evidence_kind        TEXT NOT NULL CHECK (evidence_kind IN (
                            'public_disclosure','joint_adoption','supplier_list',
                            'co_filing','press_release'
                         )),
    evidence_count       INTEGER NOT NULL DEFAULT 1,
    source_url_json      TEXT,
    first_seen_at        TEXT,
    last_seen_at         TEXT,
    computed_at          TEXT NOT NULL DEFAULT (datetime('now')),
    -- No self-loops: a houjin trading with itself is uninteresting.
    CHECK (seller_houjin_bangou != buyer_houjin_bangou),
    UNIQUE (seller_houjin_bangou, buyer_houjin_bangou, evidence_kind)
);

CREATE INDEX IF NOT EXISTS idx_aibsg_seller
    ON am_invoice_buyer_seller_graph(seller_houjin_bangou);

CREATE INDEX IF NOT EXISTS idx_aibsg_buyer
    ON am_invoice_buyer_seller_graph(buyer_houjin_bangou);

CREATE INDEX IF NOT EXISTS idx_aibsg_confidence
    ON am_invoice_buyer_seller_graph(confidence DESC);
