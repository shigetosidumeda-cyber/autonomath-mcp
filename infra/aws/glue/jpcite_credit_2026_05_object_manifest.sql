-- jpcite credit run 2026-05 — object_manifest table DDL
--
-- target_database: jpcite_credit_2026_05
-- storage:         S3 JSONL (one JSON object per line, JSONL canonical)
--                  NOTE: plan spec also lists `object_manifest.parquet` for
--                        large runs. Use a parallel ALTER TABLE …
--                        SET LOCATION variant or create a parquet-backed
--                        sibling table once a job emits parquet. JSON is
--                        the v0 default so this DDL targets JSONL.
-- partition_key:   run_id
-- serde:           org.openx.data.jsonserde.JsonSerDe
-- tags:            Project=jpcite, CreditRun=2026-05, AutoStop=2026-05-29

CREATE EXTERNAL TABLE IF NOT EXISTS jpcite_credit_2026_05.object_manifest (
  s3_key          STRING,
  content_sha256  STRING,
  content_length  BIGINT,
  content_type    STRING,
  fetched_at      STRING,
  source_id       STRING,
  retention_class STRING
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
LOCATION 's3://jpcite-credit-993693061769-202605-derived/object_manifest/'
TBLPROPERTIES (
  'classification' = 'json',
  'project'        = 'jpcite',
  'credit_run'     = '2026-05',
  'auto_stop'      = '2026-05-29',
  'contract'       = 'jpcir.object_manifest.v1',
  -- PERF-38 (2026-05-17): partition projection. The run_id partition
  -- key is opaque (per-crawl ULID/UUID set by the writer) so
  -- `projection.run_id.type = injected` makes Athena trust the value
  -- coming from the WHERE clause without round-tripping Glue
  -- `GetPartitions`. Eliminates the MSCK REPAIR loop and removes the
  -- Glue catalog hop from every query — typical hot-path speedup
  -- 200ms-2s per query on tables with hundreds of partitions.
  -- Query MUST always filter `WHERE run_id = '...'` (no full-table
  -- scans) — Athena returns an empty result when run_id is omitted.
  'projection.enabled'   = 'true',
  'projection.run_id.type' = 'injected'
);
