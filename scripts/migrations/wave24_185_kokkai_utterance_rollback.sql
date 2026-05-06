-- target_db: autonomath
-- rollback: wave24_185_kokkai_utterance
-- WARNING: drops kokkai_utterance / shingikai_minutes / regulatory_signal
-- audit history. Only run after exporting to R2 backup.

DROP INDEX IF EXISTS ix_signal_law_detected;
DROP TABLE IF EXISTS regulatory_signal;

DROP INDEX IF EXISTS ix_shingikai_council_date;
DROP TABLE IF EXISTS shingikai_minutes;

DROP INDEX IF EXISTS ix_kokkai_committee_date;
DROP INDEX IF EXISTS ix_kokkai_date;
DROP TABLE IF EXISTS kokkai_utterance;
