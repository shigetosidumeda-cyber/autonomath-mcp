-- target_db: autonomath
-- migration: wave24_177_regulatory_citation_graph
-- generated_at: 2026-05-06
-- author: M00-F data spine DF-05 (regulatory_citation_graph)
-- idempotent: every CREATE uses IF NOT EXISTS; every DML is INSERT OR IGNORE
--
-- Purpose
-- -------
-- Capture the directed graph of legal citations across:
--   - 法令 (Acts, 政令, 省令, 告示)
--   - 通達 (NTA 法基通 / 消基通 / 所基通 / 相基通 ; 各省庁 通達)
--   - 改正 (改正法 / 改正通達 — both as nodes; the *amendment relationship*
--     is an edge, but the amending act itself is also a node)
--   - 制度要件 (program eligibility predicates that cite a 法令 / 通達)
--   - 罰則 (penalty clauses; modeled as separate nodes that link via
--     `penalty_for` edges to the substantive provision they enforce)
--
-- The W1_A22 e-Gov source profile and the DEEP-16 JLTDB context already
-- give us 28,201 `am_law_article` rows (live) and 353,278 `am_law_article`
-- rows (target) of which only 1 has `body_en` filled. This new graph
-- table is *layered above* `am_law_article` — it does not replace the
-- article-level body store. The graph nodes carry article references
-- as `canonical_name` (e.g. '法人税法 第57条' or '法基通 9-2-13') and
-- the body content stays in `am_law_article` keyed by article ID.
--
-- Two-table design
-- ----------------
-- `reg_node`      — one row per legal entity (article, 通達, 改正, 罰則,
--                   制度要件). PK = node_id.
-- `reg_edge`      — directed edges. PK = (from_node_id, to_node_id, edge_kind).
--
-- Graph traversal patterns supported (see "Graph traversal SQL helpers"
-- section in DF_05_edinet_regulatory_document.md):
--   1. "Find all amendments to 法人税法第57条 since 2020-04-01"
--      → recursive CTE on edge_kind='amends' starting from the article node.
--   2. "Show all 通達 that cite 消費税法第6条"
--      → SELECT * FROM reg_edge WHERE to_node_id = ? AND edge_kind='cites'.
--   3. "Show all 制度要件 nodes that depend on 中小企業等経営強化法"
--      → recursive CTE on edge_kind='depends_on'.
--   4. "Show all penalties enforcing this 法令"
--      → SELECT * FROM reg_edge WHERE to_node_id = ? AND edge_kind='penalty_for'.
--
-- Field semantics — reg_node
-- ---------------------------
-- node_id          PK, deterministic = sha1(kind || ':' || canonical_name)
-- kind             enum: 'law' / '通達' / '改正' / '罰則' / '制度要件'
-- canonical_name   '法人税法 第57条' / '法基通 9-2-13' / '令和7年改正令第123号' /
--                  '法人税法 第159条 (虚偽記載罪)' / '中小企業庁認定要件 (経営革新計画)'
-- source_url       primary URL (e-Gov for 法令, NTA for 通達, 官報 for 改正,
--                  各省庁 for 制度要件)
-- body_hash        SHA-256 of canonicalized 日本語 body (NULL until article body
--                  is harvested into am_law_article and then a trigger /
--                  ETL fills this in)
-- body_en_hash     SHA-256 of canonicalized 英訳 body (NULL until JLTDB harvest
--                  per DEEP-16 lands the row)
-- jurisdiction     '国' (national) / '都道府県' / '市区町村'. Default '国'.
-- effective_date   YYYY-MM-DD. NULL when unknown / superseded.
-- supersedes_node  optional self-reference; when set, this node has been
--                  replaced (e.g., 改正後 vs 改正前 same article number).
-- created_at       ISO 8601 (UTC, millisecond precision)
--
-- Field semantics — reg_edge
-- ---------------------------
-- edge_id          PK, deterministic = sha1(from || ':' || to || ':' || kind)
-- from_node_id     FK → reg_node.node_id
-- to_node_id       FK → reg_node.node_id
-- edge_kind        enum: 'cites' / 'amends' / 'supersedes' / 'depends_on' /
--                       'penalty_for'
-- confidence       REAL [0.0, 1.0]; 1.0 for hand-curated, 0.7-0.95 for ETL.
-- source_url       URL of the document where the edge was *observed*
--                  (e.g., the 通達 that cites the 法令 — its URL goes here).
-- created_at       ISO 8601 (UTC, millisecond precision)
--
-- Indexes
-- -------
-- (from_node_id, edge_kind)  — outbound graph walk
-- (to_node_id, edge_kind)    — inbound graph walk
-- (kind) on reg_node         — type-based filter
-- (effective_date) on reg_node — time-windowed amendment queries
-- (canonical_name) on reg_node — text lookup before graph walk

CREATE TABLE IF NOT EXISTS reg_node (
    node_id           TEXT NOT NULL PRIMARY KEY,
    kind              TEXT NOT NULL CHECK (kind IN (
        'law', '通達', '改正', '罰則', '制度要件'
    )),
    canonical_name    TEXT NOT NULL,
    source_url        TEXT NOT NULL,
    body_hash         TEXT,
    body_en_hash      TEXT,
    jurisdiction      TEXT NOT NULL DEFAULT '国'
                      CHECK (jurisdiction IN ('国', '都道府県', '市区町村')),
    effective_date    TEXT,
    supersedes_node   TEXT REFERENCES reg_node(node_id),
    created_at        TEXT NOT NULL
                      DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_reg_node_kind
    ON reg_node (kind);

CREATE INDEX IF NOT EXISTS idx_reg_node_effective_date
    ON reg_node (effective_date);

CREATE INDEX IF NOT EXISTS idx_reg_node_canonical_name
    ON reg_node (canonical_name);

CREATE TABLE IF NOT EXISTS reg_edge (
    edge_id        TEXT NOT NULL PRIMARY KEY,
    from_node_id   TEXT NOT NULL REFERENCES reg_node(node_id),
    to_node_id     TEXT NOT NULL REFERENCES reg_node(node_id),
    edge_kind      TEXT NOT NULL CHECK (edge_kind IN (
        'cites', 'amends', 'supersedes', 'depends_on', 'penalty_for'
    )),
    confidence     REAL NOT NULL DEFAULT 0.95
                   CHECK (confidence >= 0.0 AND confidence <= 1.0),
    source_url     TEXT NOT NULL,
    created_at     TEXT NOT NULL
                   DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (from_node_id, to_node_id, edge_kind)
);

CREATE INDEX IF NOT EXISTS idx_reg_edge_from_kind
    ON reg_edge (from_node_id, edge_kind);

CREATE INDEX IF NOT EXISTS idx_reg_edge_to_kind
    ON reg_edge (to_node_id, edge_kind);

-- View: amendment timeline. For monthly digest, "what amendments landed
-- this month" comes from this view.
CREATE VIEW IF NOT EXISTS v_reg_amendment_timeline AS
SELECT e.edge_id,
       n_from.canonical_name AS amending_doc,
       n_to.canonical_name   AS amended_doc,
       n_from.effective_date AS amendment_effective_date,
       e.source_url          AS amendment_source_url,
       e.confidence
  FROM reg_edge e
  JOIN reg_node n_from ON n_from.node_id = e.from_node_id
  JOIN reg_node n_to   ON n_to.node_id   = e.to_node_id
 WHERE e.edge_kind = 'amends';

-- View: penalty-to-provision rollup. Used by DD pack for "what penalties
-- could attach if this 法令 is breached".
CREATE VIEW IF NOT EXISTS v_reg_penalty_rollup AS
SELECT n_to.canonical_name   AS substantive_provision,
       n_from.canonical_name AS penalty_clause,
       n_from.source_url     AS penalty_source_url,
       e.confidence
  FROM reg_edge e
  JOIN reg_node n_from ON n_from.node_id = e.from_node_id
  JOIN reg_node n_to   ON n_to.node_id   = e.to_node_id
 WHERE e.edge_kind = 'penalty_for';

-- View: 制度要件 dependency surface. Used by application_strategy_pack to
-- show "this program depends on these 法令 + 通達 staying valid".
CREATE VIEW IF NOT EXISTS v_reg_program_dependencies AS
SELECT n_from.node_id        AS program_node_id,
       n_from.canonical_name AS program_requirement,
       n_to.canonical_name   AS depended_legal_doc,
       n_to.kind             AS depended_kind,
       n_to.effective_date   AS depended_effective_date,
       e.confidence
  FROM reg_edge e
  JOIN reg_node n_from ON n_from.node_id = e.from_node_id
  JOIN reg_node n_to   ON n_to.node_id   = e.to_node_id
 WHERE e.edge_kind = 'depends_on'
   AND n_from.kind  = '制度要件';
