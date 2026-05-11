-- target_db: autonomath
-- rollback for 234_budget_to_subsidy_chain
-- Axis 3d 予算 → 補助金 announce chain — drop the table + meta marker.
-- The `programs.triggered_by_budget_id` column ALTER is irreversible in SQLite
-- without a table rebuild; we leave the column in place after rollback so
-- production data is not destroyed. The unused column is harmless.

DROP INDEX IF EXISTS ix_budget_subsidy_chain_announce;
DROP INDEX IF EXISTS ix_budget_subsidy_chain_program;
DROP INDEX IF EXISTS ix_budget_subsidy_chain_budget;
DROP TABLE IF EXISTS am_budget_subsidy_chain;
DROP TABLE IF EXISTS am_budget_subsidy_chain_meta;
