"""Glue ETL — Lane K Phase 2 packet JSON → ZSTD Parquet migration (2026-05-17).

Drives a 50-DPU PySpark job that reads a single JsonSerDe-registered packet
table from the ``jpcite_credit_2026_05`` Glue catalog and writes a
ZSTD-compressed Parquet copy to the derived bucket under
``parquet_zstd_2026_05_17/<source_table>/`` for Athena consumption. The
target table name is ``<source_table>_parquet_zstd_2026_05_17`` and is NOT
registered automatically — the existing ``jpcite-credit-derived-crawler``
recrawl picks the new prefix up on its next on-demand run, matching the
landing pattern of the PERF-3 / PERF-24 / PERF-34 athena_parquet_migrate
CTAS path.

Why a Glue Job (not a CTAS)
---------------------------
PERF-3 / PERF-24 / PERF-34 use Athena CTAS for the top-N packet tables
because the scan + write cost lives inside the workgroup BytesScannedCutoff.
Lane K is the *opposite* of that path: the goal is to **burn $230/day of
budget on sustained ETL** to absorb the AWS canary credit, NOT to land the
most-queried Parquet variants. A 50-DPU Spark cluster running ~11h/day at
``$0.44 / DPU-hr`` = ``$242/day`` is the matched cost lever, and it
exercises the Glue surface (DPU billing + Spark catalog adapter + ZSTD
Parquet write) that the Athena CTAS path bypasses.

Cost contract
-------------
``$0.44 / DPU-hour`` × ``50 DPU`` × ``T hours`` = ``$22 × T`` per job run.
A single packet table at ~2,256 rows × ~2 KB JSON = ~4.5 MB read +
ZSTD-Parquet write completes in well under 1 minute of wall clock on
50 DPU. To hit $242/day we sequentially submit ~11 hours of jobs
(``$242 / $22/hr = 11 hr``); each job is ``--timeout 10`` (minutes) so
even a worst-case stall caps at ~$3.67. Lane J monitor verifies the
realized burn against the budget cap.

Constraints honoured
--------------------
* AWS profile ``bookyou-recovery``; region ``ap-northeast-1``.
* IAM role ``jpcite-glue-crawler-role`` (already R/W on the derived bucket
  per ``infra/aws/glue/jpcite_credit_derived_crawler.json``). Glue ETL
  scripts reuse the same role since the trust + inline policy already
  cover the S3 access path; no new IAM artifact lands.
* NO LLM calls — pure Spark JSON-in / Parquet-out.
* DRY_RUN default. The driver script
  ``scripts/aws_credit_ops/run_lane_k_glue_etl.py`` invokes
  ``aws glue start-job-run`` only under ``--commit``; this file is the
  *Spark job* uploaded to S3 as the Glue Job ``ScriptLocation`` and is
  exercised by Glue, not directly.
* ``[lane:solo]`` marker per dual-CLI atomic lane convention.

CLI (Glue job arguments — passed via ``--arguments`` on start-job-run)
------------------------------------------------------------------------
* ``--source_table``  REQUIRED  source Glue table name in
  ``jpcite_credit_2026_05`` (e.g. ``packet_academic_collaboration_intensity_v1``)
* ``--target_prefix`` REQUIRED  output S3 key prefix under
  ``s3://jpcite-credit-993693061769-202605-derived/``
  (e.g. ``parquet_zstd_2026_05_17/packet_academic_collaboration_intensity_v1``)
* ``--compression``   OPTIONAL  Parquet compression codec; default ``zstd``
* ``--coalesce_partitions`` OPTIONAL  Repartition count before write;
  default ``8`` (matches typical packet table size — bigger packets can
  set 16 / 32 via job override without code change).
"""

import sys

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql.types import (
    ArrayType,
    DataType,
    MapType,
    NullType,
    StringType,
    StructField,
    StructType,
)

ARGS = getResolvedOptions(
    sys.argv,
    [
        "JOB_NAME",
        "source_table",
        "target_prefix",
        # Optional with safe defaults
        "compression",
        "coalesce_partitions",
    ],
)

DATABASE = "jpcite_credit_2026_05"
DERIVED_BUCKET = "jpcite-credit-993693061769-202605-derived"

# NOTE: `glueContext` / `spark` use mixedCase per the AWS Glue PySpark
# convention — these symbols are the canonical names in every AWS Glue
# code sample and changing them would break operator muscle memory.
# Suppress ruff N816.
sc = SparkContext()
glueContext = GlueContext(sc)  # noqa: N816
spark = glueContext.spark_session
job = Job(glueContext)
job.init(ARGS["JOB_NAME"], ARGS)

source_table = ARGS["source_table"]
target_prefix = ARGS["target_prefix"]
compression = ARGS.get("compression") or "zstd"
coalesce_n_raw = ARGS.get("coalesce_partitions") or "8"
try:
    coalesce_n = max(1, int(coalesce_n_raw))
except (TypeError, ValueError):
    coalesce_n = 8

output_s3 = f"s3://{DERIVED_BUCKET}/{target_prefix.lstrip('/').rstrip('/')}/"

# 1. Read the source JsonSerDe-registered table from the catalog.
df = glueContext.create_dynamic_frame.from_catalog(
    database=DATABASE,
    table_name=source_table,
    transformation_ctx=f"src_{source_table}",
).toDF()


def _replace_null_with_string(dtype: DataType) -> DataType:
    """Recursively replace ``NullType`` with ``StringType`` in a Spark schema.

    Parquet does not support the ``void`` (``NullType``) data type. JSON
    packets that contain a key whose value is always ``null`` across every
    row (e.g. ``source_fetched_at: null`` inside a nested struct) are
    inferred by JsonSerDe as ``void``; the Parquet writer then throws
    ``AnalysisException: Parquet data source does not support
    array<struct<...,source_fetched_at:void,...>> data type``.

    The Spark contract for this cast is well-defined: a column of
    ``NullType`` carries no values, so coercing to ``StringType`` is a
    pure schema change and preserves the (always-``null``) values.
    """

    if isinstance(dtype, NullType):
        return StringType()
    if isinstance(dtype, ArrayType):
        return ArrayType(
            _replace_null_with_string(dtype.elementType),
            containsNull=dtype.containsNull,
        )
    if isinstance(dtype, MapType):
        return MapType(
            _replace_null_with_string(dtype.keyType),
            _replace_null_with_string(dtype.valueType),
            valueContainsNull=dtype.valueContainsNull,
        )
    if isinstance(dtype, StructType):
        return StructType(
            [
                StructField(
                    f.name,
                    _replace_null_with_string(f.dataType),
                    nullable=f.nullable,
                    metadata=f.metadata,
                )
                for f in dtype.fields
            ]
        )
    return dtype


# 2. Heal the schema in place: any ``NullType`` field (Spark's name for
#    Parquet's unsupported ``void``) is recast to ``StringType``. This is
#    a no-op for the values (still all ``null``) but lets the Parquet
#    writer accept the schema. Without this every packet that has even
#    one always-null nested key (e.g. ``source_fetched_at`` inside
#    ``source_mentions``) fails the run.
healed_schema = _replace_null_with_string(df.schema)
if healed_schema != df.schema:
    healed_df = spark.createDataFrame(df.rdd, schema=healed_schema)
else:
    healed_df = df

# 3. Coalesce partitions to a sensible fan-out for the typical packet size
#    (~2K rows / ~5 MB JSON). Spark's default 200 shuffle partitions would
#    write 200 tiny Parquet files, fragmenting Athena scans; 8 partitions
#    keep files in the ~500 KB - 2 MB band which is the ZSTD sweet spot.
out_df = healed_df.coalesce(coalesce_n)

# 4. Write as ZSTD Parquet. ``mode="overwrite"`` makes the job idempotent
#    on re-run; the target prefix is uniquely date-stamped so no other
#    artifact lives there.
out_df.write.mode("overwrite").option("compression", compression).parquet(output_s3)

job.commit()
