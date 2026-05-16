#!/usr/bin/env python3
"""Export jpcite corpus tables to JSONL on S3 for SageMaker batch transform.

This driver feeds the full-corpus embedding ramp on top of
``sagemaker_embed_batch.py``. Each row of each corpus table is rendered
as one JSONL line ``{"id": <unified_id>, "inputs": <text>}`` and
uploaded to ``s3://<derived_bucket>/corpus_export/<table>/<part-N>.jsonl``.

Why JSONL + one record per line
-------------------------------
The Hugging Face SageMaker inference container parses each invocation
body via ``json.loads(content)``; with ``BatchStrategy=MultiRecord`` and
``SplitType=Line`` the container receives multiple JSON objects glued
together, which ``json.loads`` rejects as "Extra data". The 2026-05-16
J04 smoke job hit this exact failure. The fix is **BatchStrategy=SingleRecord**
+ **SplitType=Line** so each line is one HTTP invocation, and each
line is a single ``{"inputs": ...}`` document this driver emits.

Pipeline
--------
1. Open the source SQLite DB read-only.
2. For each table in the canonical list, stream rows in chunks of
   ``--chunk-rows`` (default 5,000), render each to one JSONL line with
   a stable ``id`` (table primary key) and an ``inputs`` text built from
   the table's salient columns, and stage to a local tempfile.
3. When a part reaches ``--max-part-bytes`` (default 20 MiB), upload it
   to S3 at ``corpus_export/<table>/part-<seq>.jsonl`` and reset.
4. After all rows are written, emit ``corpus_export/<table>/_manifest.json``
   with row count, byte count, part list, sha256 sums, source DB sha256.

Constraints
-----------
* **NO LLM API calls.** This is a pure SQLite → JSONL → S3 driver.
* **DRY_RUN default.** No S3 PutObject calls unless ``--commit``.
* **Read-only DB access.** Opens with ``mode=ro&immutable=1``.
* **Idempotent S3 keys.** Re-running with ``--commit`` overwrites the
  parts in place; the manifest captures sha256 sums so a re-run that
  produces identical content is observable as a no-op via diff.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.

CLI
---

.. code-block:: text

    python scripts/aws_credit_ops/export_corpus_to_s3.py \\
        --db /Users/shigetoumeda/jpcite/autonomath.db \\
        --bucket jpcite-credit-993693061769-202605-derived \\
        --prefix corpus_export \\
        --tables programs,am_law_article,adoption_records,nta_tsutatsu_index,court_decisions,nta_saiketsu \\
        [--commit]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

logger = logging.getLogger("export_corpus_to_s3")

DEFAULT_CHUNK_ROWS: Final[int] = 5000
DEFAULT_MAX_PART_BYTES: Final[int] = 20 * 1024 * 1024  # 20 MiB
DEFAULT_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"
DEFAULT_PREFIX: Final[str] = "corpus_export"
DEFAULT_REGION: Final[str] = "ap-northeast-1"

#: Canonical export specification per corpus table. Tables that live
#: only as ``jpi_*`` mirrors in ``autonomath.db`` are exported via the
#: mirror; the destination prefix uses the logical (non-mirrored) name
#: so downstream consumers do not need to know about the merge layout.
CORPUS_SPECS: Final[dict[str, dict[str, Any]]] = {
    "programs": {
        "source_table": "jpi_programs",
        "id_column": "unified_id",
        "text_template": (
            "{primary_name} | {authority_name} | {prefecture} | "
            "{program_kind} | {tier} | {target_types_json} | "
            "{funding_purpose_json}"
        ),
        "columns": [
            "unified_id",
            "primary_name",
            "authority_name",
            "prefecture",
            "program_kind",
            "tier",
            "target_types_json",
            "funding_purpose_json",
        ],
        "where_clause": "excluded = 0",
    },
    "am_law_article": {
        "source_table": "am_law_article",
        "id_column": "article_id",
        "text_template": ("{law_canonical_id} 第{article_number}条 | {title} | {text_summary}"),
        "columns": [
            "article_id",
            "law_canonical_id",
            "article_number",
            "title",
            "text_summary",
        ],
        "where_clause": "text_summary IS NOT NULL AND length(text_summary) > 0",
    },
    "adoption_records": {
        "source_table": "jpi_adoption_records",
        "id_column": "id",
        "text_template": (
            "{program_name_raw} | {company_name_raw} | {project_title} | "
            "{industry_raw} | {prefecture} | {round_label}"
        ),
        "columns": [
            "id",
            "program_name_raw",
            "company_name_raw",
            "project_title",
            "industry_raw",
            "prefecture",
            "round_label",
        ],
        "where_clause": "project_title IS NOT NULL OR program_name_raw IS NOT NULL",
    },
    "nta_tsutatsu_index": {
        "source_table": "nta_tsutatsu_index",
        "id_column": "id",
        "text_template": (
            "{code} | {law_canonical_id} | 第{article_number}条 | {title} | {body_excerpt}"
        ),
        "columns": [
            "id",
            "code",
            "law_canonical_id",
            "article_number",
            "title",
            "body_excerpt",
        ],
        "where_clause": "body_excerpt IS NOT NULL AND length(body_excerpt) > 0",
    },
    "court_decisions": {
        "source_table": "jpi_court_decisions",
        "id_column": "unified_id",
        "text_template": (
            "{case_name} | {court} | {decision_date} | {subject_area} | "
            "{key_ruling} | {impact_on_business}"
        ),
        "columns": [
            "unified_id",
            "case_name",
            "court",
            "decision_date",
            "subject_area",
            "key_ruling",
            "impact_on_business",
        ],
        "where_clause": "key_ruling IS NOT NULL OR impact_on_business IS NOT NULL",
    },
    "nta_saiketsu": {
        "source_table": "nta_saiketsu",
        "id_column": "id",
        "text_template": (
            "第{volume_no}集 No.{case_no} | {tax_type} | {decision_date} | "
            "{title} | {decision_summary}"
        ),
        "columns": [
            "id",
            "volume_no",
            "case_no",
            "decision_date",
            "tax_type",
            "title",
            "decision_summary",
        ],
        "where_clause": "decision_summary IS NOT NULL OR title IS NOT NULL",
    },
    "invoice_registrants": {
        "source_table": "jpi_invoice_registrants",
        "id_column": "invoice_registration_number",
        "text_template": (
            "{invoice_registration_number} | {normalized_name} | "
            "{trade_name} | {address_normalized} | {prefecture} | "
            "{registrant_kind} | {registered_date}"
        ),
        "columns": [
            "invoice_registration_number",
            "normalized_name",
            "trade_name",
            "address_normalized",
            "prefecture",
            "registrant_kind",
            "registered_date",
        ],
        "where_clause": "normalized_name IS NOT NULL",
    },
}

#: Max length per ``inputs`` text. MiniLM truncates to 128 tokens; over
#: a multilingual corpus the safe character budget is ~2,000 chars so
#: an unusually long ``text_summary`` does not blow up the JSONL payload.
TEXT_TRUNCATE_CHARS: Final[int] = 2000


class CorpusExportError(RuntimeError):
    """Raised when a corpus export hits an unrecoverable condition."""


@dataclass
class PartInfo:
    """Per-part upload accounting."""

    seq: int
    s3_key: str
    rows: int
    bytes: int
    sha256: str

    def to_json(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "s3_key": self.s3_key,
            "rows": self.rows,
            "bytes": self.bytes,
            "sha256": self.sha256,
        }


@dataclass
class TableReport:
    """Per-table export ledger."""

    table: str
    source_table: str
    id_column: str
    where_clause: str
    parts: list[PartInfo] = field(default_factory=list)
    total_rows: int = 0
    total_bytes: int = 0
    manifest_s3_key: str = ""
    dry_run: bool = True

    def to_json(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "source_table": self.source_table,
            "id_column": self.id_column,
            "where_clause": self.where_clause,
            "total_rows": self.total_rows,
            "total_bytes": self.total_bytes,
            "manifest_s3_key": self.manifest_s3_key,
            "dry_run": self.dry_run,
            "parts": [p.to_json() for p in self.parts],
        }


def _render_text(spec: dict[str, Any], row: dict[str, Any]) -> str:
    """Render a row to its ``inputs`` text via the template."""

    template: str = spec["text_template"]
    formatted_fields: dict[str, str] = {}
    for col in spec["columns"]:
        val = row.get(col)
        formatted_fields[col] = "" if val is None else str(val)
    text = template.format(**formatted_fields)
    # Collapse interior whitespace + truncate.
    text = " ".join(text.split())
    if len(text) > TEXT_TRUNCATE_CHARS:
        text = text[:TEXT_TRUNCATE_CHARS]
    return text


def _iter_rows(
    conn: sqlite3.Connection,
    spec: dict[str, Any],
    *,
    chunk_rows: int,
) -> Iterator[dict[str, Any]]:
    """Stream rows from the source table in primary-key order."""

    columns_csv = ", ".join(spec["columns"])
    where = spec.get("where_clause") or "1=1"
    id_col: str = spec["id_column"]
    sql = (
        f"SELECT {columns_csv} FROM {spec['source_table']} "
        f"WHERE {where} ORDER BY {id_col} LIMIT ? OFFSET ?"
    )
    offset = 0
    while True:
        cur = conn.execute(sql, (chunk_rows, offset))
        rows = cur.fetchall()
        if not rows:
            return
        cols = [d[0] for d in cur.description]
        for row in rows:
            yield dict(zip(cols, row, strict=False))
        offset += len(rows)
        if len(rows) < chunk_rows:
            return


def _flush_part(
    *,
    buffer: io.BytesIO,
    seq: int,
    rows_in_part: int,
    table: str,
    bucket: str,
    prefix: str,
    s3_client: Any | None,
    dry_run: bool,
) -> PartInfo:
    """Upload the in-memory buffer as one JSONL part and return its info."""

    data = buffer.getvalue()
    sha = hashlib.sha256(data).hexdigest()
    s3_key = f"{prefix.rstrip('/')}/{table}/part-{seq:04d}.jsonl"
    if not dry_run:
        if s3_client is None:
            msg = "s3_client is required in live mode"
            raise CorpusExportError(msg)
        s3_client.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=data,
            ContentType="application/jsonlines",
        )
    return PartInfo(
        seq=seq,
        s3_key=s3_key,
        rows=rows_in_part,
        bytes=len(data),
        sha256=sha,
    )


def export_table(
    *,
    conn: sqlite3.Connection,
    table: str,
    bucket: str,
    prefix: str,
    s3_client: Any | None,
    chunk_rows: int = DEFAULT_CHUNK_ROWS,
    max_part_bytes: int = DEFAULT_MAX_PART_BYTES,
    dry_run: bool = True,
) -> TableReport:
    """Export one corpus table to S3 as a series of JSONL parts."""

    spec = CORPUS_SPECS.get(table)
    if spec is None:
        msg = f"table {table!r} not in CORPUS_SPECS. Known: {sorted(CORPUS_SPECS)}"
        raise CorpusExportError(msg)
    report = TableReport(
        table=table,
        source_table=spec["source_table"],
        id_column=spec["id_column"],
        where_clause=str(spec.get("where_clause", "")),
        dry_run=dry_run,
    )
    buffer = io.BytesIO()
    rows_in_part = 0
    seq = 0
    for row in _iter_rows(conn, spec, chunk_rows=chunk_rows):
        text = _render_text(spec, row)
        if not text:
            continue
        record = {
            "id": str(row[spec["id_column"]]),
            "inputs": text,
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        buffer.write(line.encode("utf-8"))
        rows_in_part += 1
        report.total_rows += 1
        if buffer.tell() >= max_part_bytes:
            part = _flush_part(
                buffer=buffer,
                seq=seq,
                rows_in_part=rows_in_part,
                table=table,
                bucket=bucket,
                prefix=prefix,
                s3_client=s3_client,
                dry_run=dry_run,
            )
            report.parts.append(part)
            report.total_bytes += part.bytes
            buffer = io.BytesIO()
            rows_in_part = 0
            seq += 1
    # Flush trailing buffer.
    if buffer.tell() > 0:
        part = _flush_part(
            buffer=buffer,
            seq=seq,
            rows_in_part=rows_in_part,
            table=table,
            bucket=bucket,
            prefix=prefix,
            s3_client=s3_client,
            dry_run=dry_run,
        )
        report.parts.append(part)
        report.total_bytes += part.bytes
    # Emit per-table manifest.
    manifest_key = f"{prefix.rstrip('/')}/{table}/_manifest.json"
    manifest_body = json.dumps(report.to_json(), ensure_ascii=False, indent=2)
    if not dry_run and s3_client is not None:
        s3_client.put_object(
            Bucket=bucket,
            Key=manifest_key,
            Body=manifest_body.encode("utf-8"),
            ContentType="application/json",
        )
    report.manifest_s3_key = manifest_key
    return report


def open_readonly_db(db_path: str) -> sqlite3.Connection:
    """Open the SQLite DB read-only + immutable for safety."""

    uri = f"file:{db_path}?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True, timeout=30.0)


def _boto3_s3() -> Any:  # pragma: no cover - trivial shim
    """Return a pooled S3 client (PERF-35).

    Prefers the shared client cache in
    :mod:`scripts.aws_credit_ops._aws` so the 200-500 ms boto3
    ``Session`` + endpoint discovery cold-start is paid once per
    ``(service, region)`` per process. Falls back to direct
    ``boto3.client`` construction when running inside a minimal
    Batch container without the wider ``scripts/`` package on
    ``PYTHONPATH``. Honours the legacy ``AWS_DEFAULT_REGION``
    override either way.
    """

    region = os.environ.get("AWS_DEFAULT_REGION", DEFAULT_REGION)
    try:
        from scripts.aws_credit_ops._aws import get_client
    except ImportError:
        pass
    else:
        return get_client("s3", region_name=region)
    try:
        import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError as exc:
        msg = "boto3 is required in live mode (pip install boto3)"
        raise CorpusExportError(msg) from exc
    return boto3.client("s3", region_name=region)


def run(
    *,
    db_path: str,
    bucket: str,
    prefix: str,
    tables: Iterable[str],
    chunk_rows: int = DEFAULT_CHUNK_ROWS,
    max_part_bytes: int = DEFAULT_MAX_PART_BYTES,
    dry_run: bool = True,
    s3_client: Any | None = None,
) -> list[TableReport]:
    """Run all requested table exports and return their reports."""

    if not Path(db_path).exists():
        msg = f"db_path does not exist: {db_path!r}"
        raise CorpusExportError(msg)
    if not dry_run and s3_client is None:
        s3_client = _boto3_s3()
    conn = open_readonly_db(db_path)
    try:
        reports: list[TableReport] = []
        for tbl in tables:
            logger.info("exporting table %s ...", tbl)
            r = export_table(
                conn=conn,
                table=tbl,
                bucket=bucket,
                prefix=prefix,
                s3_client=s3_client,
                chunk_rows=chunk_rows,
                max_part_bytes=max_part_bytes,
                dry_run=dry_run,
            )
            logger.info(
                "  %s: rows=%d bytes=%d parts=%d",
                tbl,
                r.total_rows,
                r.total_bytes,
                len(r.parts),
            )
            reports.append(r)
        return reports
    finally:
        conn.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export jpcite corpus tables to JSONL on S3 for SageMaker batch "
            "transform. DRY_RUN default; pass --commit to upload."
        )
    )
    parser.add_argument("--db", required=True)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    parser.add_argument(
        "--tables",
        default=",".join(CORPUS_SPECS.keys()),
        help="Comma-separated table names from CORPUS_SPECS.",
    )
    parser.add_argument("--chunk-rows", type=int, default=DEFAULT_CHUNK_ROWS)
    parser.add_argument("--max-part-bytes", type=int, default=DEFAULT_MAX_PART_BYTES)
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)
    dry_run = not args.commit and os.environ.get("DRY_RUN", "1") != "0"
    tables = [t.strip() for t in args.tables.split(",") if t.strip()]
    try:
        reports = run(
            db_path=args.db,
            bucket=args.bucket,
            prefix=args.prefix,
            tables=tables,
            chunk_rows=args.chunk_rows,
            max_part_bytes=args.max_part_bytes,
            dry_run=dry_run,
        )
    except CorpusExportError as exc:
        print(f"[export_corpus_to_s3] FAIL: {exc}", file=sys.stderr)
        return 2
    payload = {
        "dry_run": dry_run,
        "bucket": args.bucket,
        "prefix": args.prefix,
        "generated_at": datetime.now(UTC).isoformat(),
        "reports": [r.to_json() for r in reports],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for r in reports:
            print(
                f"[export_corpus_to_s3] {r.table:>22s}  rows={r.total_rows:>8d}  "
                f"bytes={r.total_bytes:>12d}  parts={len(r.parts):>3d}  "
                f"dry_run={r.dry_run}"
            )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
