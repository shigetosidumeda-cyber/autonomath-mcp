-- jpcite credit run 2026-05 — source_receipts table DDL
--
-- target_database: jpcite_credit_2026_05
-- storage:         S3 JSONL (one JSON object per line)
-- partition_key:   source_id (per-source-family prefix, hive-style: source_id=<id>/...)
-- serde:           org.openx.data.jsonserde.JsonSerDe
-- tags:            Project=jpcite, CreditRun=2026-05, AutoStop=2026-05-29
--
-- Run once via Athena workgroup `jpcite-credit-2026-05`. Idempotent (CREATE EXTERNAL TABLE IF NOT EXISTS).
-- After landing new partitions, run:
--   MSCK REPAIR TABLE jpcite_credit_2026_05.source_receipts;
-- or add explicit partitions via ALTER TABLE ... ADD PARTITION.

CREATE EXTERNAL TABLE IF NOT EXISTS jpcite_credit_2026_05.source_receipts (
  source_id         STRING,
  claim_kind        STRING,
  source_url        STRING,
  source_fetched_at STRING,
  content_sha256    STRING,
  license_boundary  STRING,
  receipt_kind      STRING,
  support_level     STRING
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
LOCATION 's3://jpcite-credit-993693061769-202605-derived/source_receipts/'
TBLPROPERTIES (
  'classification' = 'json',
  'project'        = 'jpcite',
  'credit_run'     = '2026-05',
  'auto_stop'      = '2026-05-29',
  'contract'       = 'jpcir.source_receipt.v1'
);
