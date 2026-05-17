-- target_db: autonomath
-- Lane M7 — Knowledge-graph completion predicted edges.
--
-- Stores ensemble-scored (TransE+RotatE+ComplEx+ConvE) predictions of
-- previously-absent (h, r, t) edges. Populated by the post-training
-- aggregator that joins the 4 model checkpoints, scores candidate
-- completions, and emits rows whose mean ensemble score >= 0.85.
--
-- The table is intentionally **separate from ``am_relation``** so the
-- canonical KG never silently absorbs probabilistic edges. Downstream
-- tools that wish to surface predictions must JOIN explicitly and
-- expose the ``confidence`` + ``model`` provenance to the caller.
--
-- Idempotent (CREATE IF NOT EXISTS only); safe to re-run on every boot.

CREATE TABLE IF NOT EXISTS am_relation_predicted (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    source_entity_id   TEXT NOT NULL,
    target_entity_id   TEXT NOT NULL,
    relation_type      TEXT NOT NULL,
    model              TEXT NOT NULL,      -- 'ensemble' | 'TransE' | 'RotatE' | 'ComplEx' | 'ConvE'
    score              REAL NOT NULL,
    rank_in_top_k      INTEGER,
    train_run_id       TEXT,               -- e.g. '20260517T0830Z'
    predicted_at       TEXT NOT NULL DEFAULT (datetime('now')),
    notes              TEXT,
    FOREIGN KEY (source_entity_id) REFERENCES am_entities(canonical_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_am_relation_predicted_src
    ON am_relation_predicted(source_entity_id, relation_type);

CREATE INDEX IF NOT EXISTS ix_am_relation_predicted_tgt
    ON am_relation_predicted(target_entity_id, relation_type);

CREATE INDEX IF NOT EXISTS ix_am_relation_predicted_score
    ON am_relation_predicted(score DESC);

CREATE INDEX IF NOT EXISTS ix_am_relation_predicted_model_score
    ON am_relation_predicted(model, score DESC);

-- Avoid the same (h, r, t, model) being inserted twice across re-runs.
CREATE UNIQUE INDEX IF NOT EXISTS ux_am_relation_predicted_hrtm
    ON am_relation_predicted(
        source_entity_id,
        target_entity_id,
        relation_type,
        model
    );

-- Convenience view: top-1 (h, r, t) per ensemble score, ready for
-- downstream MCP ``predict_related_entities`` lookup.
CREATE VIEW IF NOT EXISTS v_am_relation_predicted_top AS
    SELECT
        source_entity_id,
        relation_type,
        target_entity_id,
        score,
        model,
        train_run_id,
        predicted_at
      FROM am_relation_predicted
     WHERE model = 'ensemble'
       AND score >= 0.85;
