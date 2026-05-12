-- target_db: autonomath
-- migration: 285_fact_signature_v2 (rollback)
-- author: Wave 47 Phase 2 tick#6 — Dim F fact_signature extension rollback
--
-- Rollback drops ONLY the Dim F multi-attestation + revocation tables
-- introduced by mig 285. Mig 262 (am_fact_signature) is NEVER touched —
-- it remains the operator-internal "latest sig pointer" and survives
-- this rollback intact. Irreversible for any rows already inserted;
-- intended for non-production / dev re-runs.

BEGIN;

DROP VIEW  IF EXISTS v_am_fact_sig_v2_attestation_active;

DROP INDEX IF EXISTS uq_am_fact_sig_v2_rev_signature;
DROP INDEX IF EXISTS idx_am_fact_sig_v2_rev_class;
DROP INDEX IF EXISTS idx_am_fact_sig_v2_rev_signature;
DROP TABLE IF EXISTS am_fact_signature_v2_revocation_log;

DROP INDEX IF EXISTS uq_am_fact_sig_v2_att_triplet;
DROP INDEX IF EXISTS idx_am_fact_sig_v2_att_keyid;
DROP INDEX IF EXISTS idx_am_fact_sig_v2_att_signer;
DROP INDEX IF EXISTS idx_am_fact_sig_v2_att_fact;
DROP TABLE IF EXISTS am_fact_signature_v2_attestation;

COMMIT;
