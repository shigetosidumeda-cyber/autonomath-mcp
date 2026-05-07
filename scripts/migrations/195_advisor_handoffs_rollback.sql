-- target_db: jpintel
-- rollback: 195_advisor_handoffs
--
-- Offline rollback only. This drops the handoff event ledger and handoff
-- table, then removes the additive advisor_referrals columns when the local
-- SQLite build supports ALTER TABLE DROP COLUMN (SQLite >= 3.35).
-- Export advisor_handoffs/advisor_handoff_events first if audit history must
-- be retained.

PRAGMA foreign_keys = ON;

DROP TRIGGER IF EXISTS trg_advisors_no_lawyer_percent_update;
DROP TRIGGER IF EXISTS trg_advisors_no_lawyer_percent_insert;
DROP TRIGGER IF EXISTS trg_advisors_houjin_digits_update;
DROP TRIGGER IF EXISTS trg_advisors_houjin_digits_insert;

DROP INDEX IF EXISTS idx_advisor_handoff_events_name;
DROP INDEX IF EXISTS idx_advisor_handoff_events_handoff;
DROP TABLE IF EXISTS advisor_handoff_events;

ALTER TABLE advisor_referrals DROP COLUMN evidence_digest;
ALTER TABLE advisor_referrals DROP COLUMN source_packet_id;
ALTER TABLE advisor_referrals DROP COLUMN source_artifact_id;
ALTER TABLE advisor_referrals DROP COLUMN handoff_id;

DROP INDEX IF EXISTS idx_advisor_handoffs_created;
DROP INDEX IF EXISTS idx_advisor_handoffs_houjin;
DROP INDEX IF EXISTS idx_advisor_handoffs_token;
DROP TABLE IF EXISTS advisor_handoffs;
