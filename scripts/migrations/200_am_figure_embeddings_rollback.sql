-- target_db: autonomath
-- migration 200_am_figure_embeddings — rollback
--
-- Drops the M3 (Lane M3 — CLIP-Japanese figure embeddings) ledger,
-- vec0 sidecar, and map bridge. Forward migration at
-- ``200_am_figure_embeddings.sql``.
--
-- Order matters: vec0 sidecar must be dropped BEFORE its companion
-- map table — the vec0 virtual table depends on no external FK, but
-- dropping the map first leaves stale figure_id references in the
-- vec rowids if any rows landed. We drop vec → map → ledger for
-- symmetry with migration 166 (``am_canonical_vec_*_rollback``).

DROP INDEX IF EXISTS ix_am_figure_embeddings_map_figure;
DROP TABLE IF EXISTS am_figure_embeddings_map;

DROP TABLE IF EXISTS am_figure_embeddings_vec;

DROP INDEX IF EXISTS ix_am_figure_embeddings_kind;
DROP INDEX IF EXISTS ix_am_figure_embeddings_pdf;
DROP INDEX IF EXISTS ix_am_figure_embeddings_source_doc;
DROP TABLE IF EXISTS am_figure_embeddings;
