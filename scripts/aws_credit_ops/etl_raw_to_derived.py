#!/usr/bin/env python3
"""Post-job ETL: raw JSONL → derived Parquet (Athena-queryable).

This module is the bridge between the AWS Batch ``jpcite-crawler`` job
output (JSONL artifacts in ``s3://jpcite-credit-993693061769-202605-raw/``)
and the Glue Data Catalog tables in
``s3://jpcite-credit-993693061769-202605-derived/`` that
``jpcite-credit-2026-05`` Athena workgroup queries.

Flow per ``--job-prefix J0X_<slug>``:

1. List ``s3://<raw_bucket>/J0X_<slug>/`` and discover the canonical
   JSONL artifacts:

       object_manifest.jsonl     -> Glue table ``object_manifest``
       source_receipts.jsonl     -> Glue table ``source_receipts``
       claim_refs.jsonl          -> Glue table ``claim_refs``
       known_gaps.jsonl          -> Glue table ``known_gaps``

   A missing artifact is reported as ``status=missing_in_raw`` but does
   not abort the run; ``object_manifest.jsonl`` is the only required
   artifact (every job emits it). Raw bin files under ``raw/`` are
   ignored — they are the SHA-pinned source bodies, not analytic rows.

2. For each present artifact:

   * Read every line, JSON-decode, drop malformed rows.
   * Normalise the row to the Glue DDL schema (column subset; complex
     fields like ``extras`` / ``provenance`` are flattened to JSON
     strings so Athena's openx JsonSerDe — and pyarrow Parquet — both
     read them without bespoke nested-typing).
   * Build a ``pyarrow.Table`` with an explicit schema (the DDL's
     column types) so downstream Athena Parquet readers do not need to
     guess.
   * Write the Parquet to
     ``s3://<derived_bucket>/<artifact_kind>/job_prefix=J0X_<slug>/run_id=<run_id>/data.parquet``
     using snappy compression. The hive-style partition layout means
     Athena ``MSCK REPAIR TABLE`` auto-discovers new partitions without
     explicit ``ALTER TABLE ADD PARTITION`` calls. ``<run_id>`` is
     discovered from the raw ``run_manifest.json`` (canonical) or falls
     back to a UTC timestamp when absent.

3. Optionally trigger the ``jpcite-credit-derived-crawler`` Glue crawler
   at the end (``--trigger-crawler``; default off) so the new Parquet
   files become visible to Athena. The crawler is configured for
   ``CRAWL_NEW_FOLDERS_ONLY`` so a re-run only registers new run_id
   partitions.

CLI::

    python scripts/aws_credit_ops/etl_raw_to_derived.py \\
        --job-prefix J01_source_profile_sweep \\
        [--raw-bucket jpcite-credit-993693061769-202605-raw] \\
        [--derived-bucket jpcite-credit-993693061769-202605-derived] \\
        [--run-id 20260516T120000Z] \\
        [--trigger-crawler] \\
        [--commit]

``--commit`` is the dual of ``DRY_RUN=1``: it lifts the dry-run guard
and lets the script actually write Parquet to the derived bucket +
optionally call ``glue:StartCrawler``. Default is dry-run.

Constraints
-----------
* **NO LLM API calls.** Pure pyarrow + boto3. The CI guard
  ``tests/test_no_llm_in_production.py`` enforces this.
* **DRY_RUN default.** No S3 PUTs and no ``glue:StartCrawler`` call
  unless ``--commit`` is passed.
* **Schema pinned to Glue DDL.** Column lists below mirror
  ``infra/aws/glue/jpcite_credit_2026_05_*.sql``. New columns must land
  in BOTH the DDL and ``ARTIFACT_SCHEMAS`` below.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger("etl_raw_to_derived")

# ---------------------------------------------------------------------------
# Constants (mirror infra/aws/glue/*.sql DDL + the canonical bucket names)
# ---------------------------------------------------------------------------

DEFAULT_RAW_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-raw"
DEFAULT_DERIVED_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"
DEFAULT_GLUE_CRAWLER: Final[str] = "jpcite-credit-derived-crawler"
DEFAULT_REGION: Final[str] = "ap-northeast-1"

#: Canonical Glue table -> ordered column tuple. Mirrors the four
#: ``infra/aws/glue/jpcite_credit_2026_05_*.sql`` DDL files.
#: Every value is the Athena (string-cast-safe) column name in the
#: order pyarrow should write to Parquet. ``run_id`` is the partition
#: key — it lives in the S3 path, NOT the row schema.
ARTIFACT_SCHEMAS: Final[dict[str, tuple[str, ...]]] = {
    "object_manifest": (
        "s3_key",
        "content_sha256",
        "content_length",
        "content_type",
        "fetched_at",
        "source_id",
        "retention_class",
    ),
    "source_receipts": (
        "source_id",
        "claim_kind",
        "source_url",
        "source_fetched_at",
        "content_sha256",
        "license_boundary",
        "receipt_kind",
        "support_level",
    ),
    "claim_refs": (
        "claim_id",
        "subject_kind",
        "subject_id",
        "claim_kind",
        "value",
        "source_receipt_ids",
        "confidence",
    ),
    "known_gaps": (
        "gap_code",
        "packet_id",
        "subject_kind",
        "subject_id",
        "severity",
        "notes",
    ),
}

#: ``artifact_kind`` -> raw bucket filename. The crawler emits these
#: canonical names from ``docker/jpcite-crawler/entrypoint.py``; any new
#: artifact added there must also land here AND in ``ARTIFACT_SCHEMAS``.
ARTIFACT_FILENAMES: Final[dict[str, str]] = {
    "object_manifest": "object_manifest.jsonl",
    "source_receipts": "source_receipts.jsonl",
    "claim_refs": "claim_refs.jsonl",
    "known_gaps": "known_gaps.jsonl",
}

#: ``object_manifest`` is required; the other three are optional (a
#: crawl-only job may not emit ``claim_refs`` and ``known_gaps`` until
#: its receipt-assembly downstream lands).
REQUIRED_ARTIFACTS: Final[frozenset[str]] = frozenset({"object_manifest"})

#: Column-level type hints for pyarrow Parquet write. Mirrors the DDL:
#: BIGINT -> int64, DOUBLE -> float64, ARRAY<STRING> -> list<string>,
#: everything else -> string. Missing keys default to string so callers
#: do not have to enumerate every column.
_INT64_COLUMNS: Final[frozenset[str]] = frozenset({"content_length"})
_FLOAT64_COLUMNS: Final[frozenset[str]] = frozenset({"confidence"})
_LIST_STRING_COLUMNS: Final[frozenset[str]] = frozenset({"source_receipt_ids"})


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class S3Uri:
    """Parsed ``s3://<bucket>/<key>`` URI."""

    bucket: str
    key: str

    @classmethod
    def parse(cls, uri: str) -> S3Uri:
        if not uri.startswith("s3://"):
            msg = f"expected s3://... URI, got {uri!r}"
            raise ValueError(msg)
        rest = uri[len("s3://") :]
        bucket, _, key = rest.partition("/")
        return cls(bucket=bucket, key=key)

    def __str__(self) -> str:
        return f"s3://{self.bucket}/{self.key}" if self.key else f"s3://{self.bucket}"


@dataclass
class ArtifactReport:
    """Per-artifact ETL result for the run manifest."""

    artifact_kind: str
    status: str  # "written" | "missing_in_raw" | "empty" | "schema_drift" | "dry_run"
    raw_uri: str | None = None
    derived_uri: str | None = None
    raw_row_count: int = 0
    derived_row_count: int = 0
    malformed_row_count: int = 0
    drift_columns: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "artifact_kind": self.artifact_kind,
            "status": self.status,
            "raw_uri": self.raw_uri,
            "derived_uri": self.derived_uri,
            "raw_row_count": self.raw_row_count,
            "derived_row_count": self.derived_row_count,
            "malformed_row_count": self.malformed_row_count,
            "drift_columns": list(self.drift_columns),
        }


@dataclass
class RunReport:
    """Aggregate ETL ledger for the job."""

    job_prefix: str
    run_id: str
    raw_bucket: str
    derived_bucket: str
    dry_run: bool
    started_at: str
    finished_at: str | None = None
    artifacts: list[ArtifactReport] = field(default_factory=list)
    crawler_triggered: bool = False
    crawler_name: str | None = None
    crawler_status: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "job_prefix": self.job_prefix,
            "run_id": self.run_id,
            "raw_bucket": self.raw_bucket,
            "derived_bucket": self.derived_bucket,
            "dry_run": self.dry_run,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "artifacts": [a.to_json() for a in self.artifacts],
            "crawler_triggered": self.crawler_triggered,
            "crawler_name": self.crawler_name,
            "crawler_status": self.crawler_status,
        }


# ---------------------------------------------------------------------------
# JSONL reader
# ---------------------------------------------------------------------------


def read_jsonl_from_s3(
    *,
    bucket: str,
    key: str,
    s3_client: Any,
) -> tuple[list[dict[str, Any]], int]:
    """Read a JSONL object and return ``(rows, malformed_count)``.

    Each non-empty line is parsed as JSON; malformed lines are counted
    but otherwise dropped. ``NoSuchKey`` propagates so the orchestrator
    can surface ``status=missing_in_raw``.
    """

    obj = s3_client.get_object(Bucket=bucket, Key=key)
    body = obj["Body"].read()
    text = body.decode("utf-8") if isinstance(body, bytes) else str(body)
    rows: list[dict[str, Any]] = []
    malformed = 0
    for line in text.splitlines():
        line_stripped = line.strip()
        if not line_stripped:
            continue
        try:
            parsed = json.loads(line_stripped)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
        else:
            malformed += 1
    return rows, malformed


# ---------------------------------------------------------------------------
# Schema normalisation
# ---------------------------------------------------------------------------


def normalise_row(
    row: dict[str, Any],
    *,
    artifact_kind: str,
) -> dict[str, Any]:
    """Project ``row`` onto the Glue DDL column set for ``artifact_kind``.

    Behaviour:
    - Columns not present in the row default to ``None``.
    - Columns of type BIGINT (``content_length``) cast int-likes to int.
    - Columns of type DOUBLE (``confidence``) cast to float.
    - ``source_receipt_ids`` becomes ``list[str]`` (anything iterable of
      strings; non-iterables wrap to a single-element list).
    - Everything else gets ``str(...)`` for safe Athena openx JsonSerDe
      compatibility; ``None`` stays ``None`` so columns can be nullable.

    Returns a dict with EXACTLY the columns declared in
    :data:`ARTIFACT_SCHEMAS` — extra row fields are dropped. Schema
    drift (a column the DDL declares but the row never carries) is
    handled at the table-build layer, not here.
    """

    if artifact_kind not in ARTIFACT_SCHEMAS:
        msg = f"unknown artifact_kind={artifact_kind!r}"
        raise ValueError(msg)
    columns = ARTIFACT_SCHEMAS[artifact_kind]
    out: dict[str, Any] = {}
    for col in columns:
        raw_value = row.get(col)
        out[col] = _cast_value(col, raw_value)
    return out


def _cast_value(col: str, value: Any) -> Any:
    """Cast a raw row value to the Glue DDL type for ``col``."""

    if value is None:
        return None
    if col in _INT64_COLUMNS:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if col in _FLOAT64_COLUMNS:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if col in _LIST_STRING_COLUMNS:
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, (str, bytes)):
            return [value.decode() if isinstance(value, bytes) else value]
        try:
            return [str(v) for v in value]
        except TypeError:
            return [str(value)]
    if isinstance(value, (dict, list)):
        # Flatten nested structures to JSON strings — Athena openx
        # JsonSerDe + Parquet readers both tolerate string columns; we
        # do not want pyarrow to infer a struct because the schema may
        # drift across rows.
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


# ---------------------------------------------------------------------------
# Parquet write (pyarrow gate)
# ---------------------------------------------------------------------------


def build_arrow_table(
    rows: list[dict[str, Any]],
    *,
    artifact_kind: str,
) -> Any:
    """Build a ``pyarrow.Table`` from normalised rows with explicit schema.

    Raises ``ImportError`` if pyarrow is not available (the caller is
    responsible for falling back to JSONL or surfacing the error).
    """

    import pyarrow as pa  # type: ignore[import-not-found,import-untyped,unused-ignore]

    columns = ARTIFACT_SCHEMAS[artifact_kind]
    fields: list[Any] = []
    for col in columns:
        if col in _INT64_COLUMNS:
            fields.append(pa.field(col, pa.int64()))
        elif col in _FLOAT64_COLUMNS:
            fields.append(pa.field(col, pa.float64()))
        elif col in _LIST_STRING_COLUMNS:
            fields.append(pa.field(col, pa.list_(pa.string())))
        else:
            fields.append(pa.field(col, pa.string()))
    schema = pa.schema(fields)
    if not rows:
        # Empty table with the pinned schema so Athena can still read
        # the partition (no rows but the column shape is correct).
        return pa.Table.from_pylist([], schema=schema)
    return pa.Table.from_pylist(rows, schema=schema)


def write_parquet_to_s3(
    table: Any,
    *,
    bucket: str,
    key: str,
    s3_client: Any,
) -> str:
    """Serialise a ``pyarrow.Table`` to Parquet (snappy) and PUT to S3."""

    import io

    import pyarrow.parquet as pq  # type: ignore[import-not-found,import-untyped,unused-ignore]

    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")  # type: ignore[no-untyped-call]
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=buf.getvalue(),
        ContentType="application/x-parquet",
    )
    return f"s3://{bucket}/{key}"


# ---------------------------------------------------------------------------
# run_id resolution
# ---------------------------------------------------------------------------


def resolve_run_id(
    *,
    raw_bucket: str,
    job_prefix: str,
    s3_client: Any,
    override: str | None = None,
) -> str:
    """Resolve the partition-key ``run_id`` for the job.

    Priority:
    1. CLI ``--run-id`` override.
    2. ``run_manifest.json`` at ``s3://<raw_bucket>/<job_prefix>/run_manifest.json``
       (``run_id`` field).
    3. UTC timestamp ``YYYYMMDDTHHMMSSZ`` as a last-resort default so
       the script never silently overwrites a previous partition.
    """

    if override:
        return override
    manifest_key = f"{job_prefix.rstrip('/')}/run_manifest.json"
    try:
        obj = s3_client.get_object(Bucket=raw_bucket, Key=manifest_key)
    except Exception:  # noqa: BLE001 — boto3 surfaces NoSuchKey/ClientError
        return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    body = obj["Body"].read()
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    if isinstance(data, dict):
        candidate = data.get("run_id")
        if isinstance(candidate, str) and candidate:
            return candidate
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Glue crawler trigger
# ---------------------------------------------------------------------------


def trigger_glue_crawler(
    *,
    crawler_name: str,
    glue_client: Any,
) -> str:
    """Call ``glue:StartCrawler`` and return the resulting state.

    Re-raises any non-``CrawlerRunningException`` failure. A crawler
    that is already running is treated as success (``"already_running"``)
    because the crawler is configured ``CRAWL_NEW_FOLDERS_ONLY`` and
    will pick up our partition on its next loop.
    """

    try:
        glue_client.start_crawler(Name=crawler_name)
    except Exception as exc:  # noqa: BLE001 — boto3 ClientError subclass
        if "CrawlerRunningException" in str(type(exc).__name__) or "already running" in str(exc).lower():
            return "already_running"
        raise
    return "started"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def etl_one_artifact(
    *,
    artifact_kind: str,
    job_prefix: str,
    run_id: str,
    raw_bucket: str,
    derived_bucket: str,
    dry_run: bool,
    s3_client: Any,
) -> ArtifactReport:
    """ETL a single artifact: read JSONL, normalise, write Parquet.

    Returns an :class:`ArtifactReport` with the per-artifact ledger.
    Never raises on a missing artifact — surfaces ``status=missing_in_raw``
    so the orchestrator can decide whether to fail the run.
    """

    filename = ARTIFACT_FILENAMES[artifact_kind]
    raw_key = f"{job_prefix.rstrip('/')}/{filename}"
    raw_uri = f"s3://{raw_bucket}/{raw_key}"
    report = ArtifactReport(artifact_kind=artifact_kind, status="written", raw_uri=raw_uri)

    try:
        rows, malformed = read_jsonl_from_s3(
            bucket=raw_bucket, key=raw_key, s3_client=s3_client
        )
    except Exception as exc:  # noqa: BLE001 — boto3 NoSuchKey path
        # Differentiate "not found" from genuine failure for the operator.
        msg_lower = str(exc).lower()
        if "nosuchkey" in msg_lower or "not found" in msg_lower or "404" in msg_lower:
            report.status = "missing_in_raw"
            return report
        raise

    report.raw_row_count = len(rows)
    report.malformed_row_count = malformed
    if not rows:
        report.status = "empty"
        return report

    normalised = [normalise_row(r, artifact_kind=artifact_kind) for r in normalise_iter(rows)]
    report.derived_row_count = len(normalised)

    derived_key = (
        f"{artifact_kind}/job_prefix={job_prefix.rstrip('/')}"
        f"/run_id={run_id}/data.parquet"
    )
    report.derived_uri = f"s3://{derived_bucket}/{derived_key}"

    if dry_run:
        report.status = "dry_run"
        return report

    table = build_arrow_table(normalised, artifact_kind=artifact_kind)
    write_parquet_to_s3(
        table,
        bucket=derived_bucket,
        key=derived_key,
        s3_client=s3_client,
    )
    return report


def normalise_iter(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter ``rows`` to dicts only (defensive — read_jsonl_from_s3 already does this).

    Kept as a separate function so tests can inject malformed input
    without needing a fake S3.
    """

    return [r for r in rows if isinstance(r, dict)]


def run_etl(
    *,
    job_prefix: str,
    raw_bucket: str = DEFAULT_RAW_BUCKET,
    derived_bucket: str = DEFAULT_DERIVED_BUCKET,
    run_id_override: str | None = None,
    trigger_crawler: bool = False,
    crawler_name: str = DEFAULT_GLUE_CRAWLER,
    dry_run: bool = True,
    s3_client: Any | None = None,
    glue_client: Any | None = None,
    clock: Callable[[], datetime] | None = None,
) -> RunReport:
    """Drive the ETL for every artifact under ``job_prefix``.

    Returns the :class:`RunReport` so callers can inspect the run
    without re-reading the run-manifest. Never raises on a missing
    optional artifact; ``object_manifest`` missing is also reported
    (not raised) so the operator can decide a follow-up.
    """

    now = (clock or _utc_now)()
    if s3_client is None:
        s3_client = _boto3_client("s3")
    run_id = resolve_run_id(
        raw_bucket=raw_bucket,
        job_prefix=job_prefix,
        s3_client=s3_client,
        override=run_id_override,
    )

    report = RunReport(
        job_prefix=job_prefix,
        run_id=run_id,
        raw_bucket=raw_bucket,
        derived_bucket=derived_bucket,
        dry_run=dry_run,
        started_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    for artifact_kind in ARTIFACT_SCHEMAS:
        artifact_report = etl_one_artifact(
            artifact_kind=artifact_kind,
            job_prefix=job_prefix,
            run_id=run_id,
            raw_bucket=raw_bucket,
            derived_bucket=derived_bucket,
            dry_run=dry_run,
            s3_client=s3_client,
        )
        report.artifacts.append(artifact_report)
        if (
            artifact_kind in REQUIRED_ARTIFACTS
            and artifact_report.status == "missing_in_raw"
        ):
            logger.error(
                "etl: required artifact %s missing under s3://%s/%s/",
                artifact_kind,
                raw_bucket,
                job_prefix,
            )

    if trigger_crawler and not dry_run:
        if glue_client is None:
            glue_client = _boto3_client("glue")
        try:
            state = trigger_glue_crawler(
                crawler_name=crawler_name, glue_client=glue_client
            )
            report.crawler_triggered = True
            report.crawler_name = crawler_name
            report.crawler_status = state
        except Exception as exc:  # noqa: BLE001 — surface ClientError to operator
            report.crawler_triggered = False
            report.crawler_name = crawler_name
            report.crawler_status = f"failed: {exc}"
    elif trigger_crawler:
        report.crawler_triggered = False
        report.crawler_name = crawler_name
        report.crawler_status = "dry_run_skipped"

    report.finished_at = (clock or _utc_now)().strftime("%Y-%m-%dT%H:%M:%SZ")
    return report


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _boto3_client(service: str) -> Any:  # pragma: no cover - trivial shim
    try:
        import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError as exc:
        msg = (
            "boto3 is not installed. Install it in the operator environment "
            "(pip install boto3) before running etl_raw_to_derived."
        )
        raise RuntimeError(msg) from exc
    return boto3.client(service, region_name=DEFAULT_REGION)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "ETL: raw JSONL (J0X) → derived Parquet (Athena-queryable). "
            "DRY_RUN default — pass --commit to actually write."
        )
    )
    parser.add_argument(
        "--job-prefix",
        required=True,
        help="J0X folder name under the raw bucket (e.g. J01_source_profile_sweep)",
    )
    parser.add_argument(
        "--raw-bucket",
        default=DEFAULT_RAW_BUCKET,
        help=f"raw bucket name (default: {DEFAULT_RAW_BUCKET})",
    )
    parser.add_argument(
        "--derived-bucket",
        default=DEFAULT_DERIVED_BUCKET,
        help=f"derived bucket name (default: {DEFAULT_DERIVED_BUCKET})",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="run_id partition key override (default: resolved from run_manifest.json)",
    )
    parser.add_argument(
        "--trigger-crawler",
        action="store_true",
        help=f"call glue:StartCrawler on {DEFAULT_GLUE_CRAWLER} at the end",
    )
    parser.add_argument(
        "--crawler-name",
        default=DEFAULT_GLUE_CRAWLER,
        help=f"Glue crawler name (default: {DEFAULT_GLUE_CRAWLER})",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="actually write Parquet + (optionally) trigger crawler. Default is dry-run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the run report as JSON to stdout instead of human-readable",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parse_args(argv)
    dry_run = not args.commit and os.environ.get("DRY_RUN", "1") != "0"
    report = run_etl(
        job_prefix=args.job_prefix,
        raw_bucket=args.raw_bucket,
        derived_bucket=args.derived_bucket,
        run_id_override=args.run_id,
        trigger_crawler=args.trigger_crawler,
        crawler_name=args.crawler_name,
        dry_run=dry_run,
    )
    if args.json:
        sys.stdout.write(json.dumps(report.to_json(), ensure_ascii=False, indent=2))
        sys.stdout.write("\n")
    else:
        _print_human_report(report)
    # Exit non-zero if any required artifact is missing in raw — that
    # is an operational signal, not a transient transient error.
    for art in report.artifacts:
        if art.artifact_kind in REQUIRED_ARTIFACTS and art.status == "missing_in_raw":
            return 2
    return 0


def _print_human_report(report: RunReport) -> None:
    sys.stdout.write(
        f"[etl] job_prefix={report.job_prefix} run_id={report.run_id} "
        f"dry_run={report.dry_run}\n"
    )
    for art in report.artifacts:
        sys.stdout.write(
            f"[etl]   {art.artifact_kind:<16} status={art.status:<16} "
            f"raw_rows={art.raw_row_count} derived_rows={art.derived_row_count} "
            f"malformed={art.malformed_row_count}\n"
        )
    if report.crawler_triggered or report.crawler_status:
        sys.stdout.write(
            f"[etl] crawler={report.crawler_name} "
            f"triggered={report.crawler_triggered} status={report.crawler_status}\n"
        )


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
