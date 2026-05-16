-- jpcite credit run 2026-05 — claim_refs table DDL
--
-- target_database: jpcite_credit_2026_05
-- storage:         S3 JSONL (one JSON object per line)
-- partition_key:   run_id (each crawl run lands a fresh partition)
-- serde:           org.openx.data.jsonserde.JsonSerDe
-- tags:            Project=jpcite, CreditRun=2026-05, AutoStop=2026-05-29
--
-- claim_refs is the AI-facing fact ledger. Each row carries the minimal
-- (subject_kind, subject_id, claim_kind, value) tuple plus the receipts
-- that support it. Note: source_receipt_ids is an ARRAY<STRING> so
-- Athena queries should unnest via UNNEST(source_receipt_ids) for joins
-- against source_receipts.

CREATE EXTERNAL TABLE IF NOT EXISTS jpcite_credit_2026_05.claim_refs (
  claim_id           STRING,
  subject_kind       STRING,
  subject_id         STRING,
  claim_kind         STRING,
  value              STRING,
  source_receipt_ids ARRAY<STRING>,
  confidence         DOUBLE
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
LOCATION 's3://jpcite-credit-993693061769-202605-derived/claim_refs/'
TBLPROPERTIES (
  'classification' = 'json',
  'project'        = 'jpcite',
  'credit_run'     = '2026-05',
  'auto_stop'      = '2026-05-29',
  'contract'       = 'jpcir.claim_ref.v1',
  -- PERF-38 (2026-05-17): partition projection. See object_manifest.sql
  -- for the rationale. claim_refs is the AI-facing fact ledger; every
  -- agent-facing lookup hit Glue catalog before this lands.
  'projection.enabled'    = 'true',
  'projection.run_id.type' = 'injected'
);
