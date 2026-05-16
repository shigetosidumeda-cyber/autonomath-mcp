-- jpcite credit run 2026-05 — known_gaps table DDL
--
-- target_database: jpcite_credit_2026_05
-- storage:         S3 JSONL (one JSON object per line)
-- partition_key:   run_id
-- serde:           org.openx.data.jsonserde.JsonSerDe
-- tags:            Project=jpcite, CreditRun=2026-05, AutoStop=2026-05-29
--
-- known_gaps is the断定禁止境界 ledger. gap_code is constrained to the
-- 7-code JPCIR enum (csv_input_not_evidence_safe, source_receipt_incomplete,
-- pricing_or_cap_unconfirmed, no_hit_not_absence, professional_review_required,
-- freshness_stale_or_unknown, identity_ambiguity_unresolved). Athena
-- enforcement is by query convention; schema is the kind that lets the
-- 7-enum CHECK live at write time.

CREATE EXTERNAL TABLE IF NOT EXISTS jpcite_credit_2026_05.known_gaps (
  gap_code     STRING,
  packet_id    STRING,
  subject_kind STRING,
  subject_id   STRING,
  severity     STRING,
  notes        STRING
)
PARTITIONED BY (
  run_id STRING
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
WITH SERDEPROPERTIES (
  'ignore.malformed.json' = 'true'
)
STORED AS INPUTFORMAT 'org.apache.hadoop.mapred.TextInputFormat'
OUTPUTFORMAT 'org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat'
LOCATION 's3://jpcite-credit-993693061769-202605-derived/known_gaps/'
TBLPROPERTIES (
  'classification' = 'json',
  'project'        = 'jpcite',
  'credit_run'     = '2026-05',
  'auto_stop'      = '2026-05-29',
  'contract'       = 'jpcir.known_gaps.v1',
  -- PERF-38 (2026-05-17): partition projection. See object_manifest.sql
  -- for the rationale + invariant ("must always WHERE run_id = ...").
  -- Eliminates Glue GetPartitions hop on the断定禁止境界 ledger reads.
  'projection.enabled'    = 'true',
  'projection.run_id.type' = 'injected'
);
