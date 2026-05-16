"""Shared CLI runner for Wave 53.2 packet generators.

Provides ``run_generator`` which handles argparse, dry-run gating, manifest
writing and per-packet upload accounting so each individual packet generator
can stay focused on its SQL + envelope render.

``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import sqlite3
import sys
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.aws_credit_ops._packet_base import (
    S3_PUT_USD_PER_1K,
    import_boto3,
    now_utc_iso,
    open_db_ro,
    upload_packet,
    validate_jpcir_header,
)


@dataclass(frozen=True)
class PacketResult:
    packet_id: str
    s3_key: str
    bytes_written: int
    rows: int
    status: str


@dataclass
class RunManifest:
    started_at: str
    finished_at: str | None = None
    output_prefix: str = ""
    dry_run: bool = True
    packets_seen: int = 0
    packets_written: int = 0
    packets_skipped_empty: int = 0
    bytes_total: int = 0
    s3_put_cost_usd_estimate: float = 0.0
    results: list[PacketResult] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "output_prefix": self.output_prefix,
            "dry_run": self.dry_run,
            "packets_seen": self.packets_seen,
            "packets_written": self.packets_written,
            "packets_skipped_empty": self.packets_skipped_empty,
            "bytes_total": self.bytes_total,
            "s3_put_cost_usd_estimate": round(self.s3_put_cost_usd_estimate, 4),
            "results_sample": [r.__dict__ for r in self.results[:50]],
        }


# A render function takes the cohort/row dict and returns
# ``(packet_id, envelope, rows_in_packet)``. ``rows_in_packet`` is the
# meaningful payload count used to decide skip-empty.
RenderFn = Callable[[dict[str, Any], str], tuple[str, dict[str, Any], int]]
AggregateFn = Callable[..., Iterable[dict[str, Any]]]


def build_argparser(*, package_kind: str, default_db: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=f"Pre-generate {package_kind} packets ([lane:solo])"
    )
    p.add_argument("--output-prefix", required=True)
    p.add_argument("--db", default=default_db)
    p.add_argument("--jpintel-db", default="data/jpintel.db")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--local-out-dir", default=f"out/{package_kind}")
    p.add_argument("--commit", action="store_true")
    p.add_argument("--manifest-out", default=None)
    return p


def run_generator(
    *,
    argv: Sequence[str] | None,
    package_kind: str,
    default_db: str,
    aggregate: AggregateFn,
    render: RenderFn,
    needs_jpintel: bool = False,
    logger_name: str | None = None,
) -> int:
    logger = logging.getLogger(logger_name or f"generate_{package_kind}")
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    args = build_argparser(
        package_kind=package_kind, default_db=default_db
    ).parse_args(list(argv) if argv is not None else sys.argv[1:])
    dry_run = not args.commit
    if os.environ.get("DRY_RUN") == "0" and not args.commit:
        logger.warning("DRY_RUN=0 set but --commit missing — staying in dry-run.")

    manifest = RunManifest(
        started_at=now_utc_iso(),
        output_prefix=str(args.output_prefix),
        dry_run=dry_run,
    )
    s3_client: Any | None = None
    if str(args.output_prefix).startswith("s3://") and not dry_run:
        s3_client = import_boto3().client("s3")

    primary_path = Path(args.db)
    jpintel_path = Path(args.jpintel_db)
    local_out_dir = Path(args.local_out_dir)
    local_out_dir.mkdir(parents=True, exist_ok=True)
    started_t = time.perf_counter()
    primary_conn: sqlite3.Connection | None = None
    jpintel_conn: sqlite3.Connection | None = None
    try:
        primary_conn = open_db_ro(primary_path)
        if needs_jpintel:
            jpintel_conn = open_db_ro(jpintel_path)
        rows_iter: Iterator[dict[str, Any]] = iter(
            aggregate(
                primary_conn=primary_conn,
                jpintel_conn=jpintel_conn,
                limit=int(args.limit) if args.limit is not None else None,
            )
        )
        for row in rows_iter:
            manifest.packets_seen += 1
            generated_at = now_utc_iso()
            packet_id, envelope, rows_in_packet = render(row, generated_at)
            ok, errors = validate_jpcir_header(envelope)
            if not ok:
                logger.warning(
                    "schema validation failed %s: %s", packet_id, "; ".join(errors)
                )
                continue
            if rows_in_packet <= 0:
                manifest.packets_skipped_empty += 1
                continue
            key, written = upload_packet(
                envelope=envelope,
                output_prefix=str(args.output_prefix),
                dry_run=dry_run,
                s3_client=s3_client,
                local_out_dir=local_out_dir,
                packet_id=packet_id,
            )
            manifest.packets_written += 1
            manifest.bytes_total += written
            manifest.results.append(
                PacketResult(
                    packet_id=packet_id,
                    s3_key=key,
                    bytes_written=written,
                    rows=rows_in_packet,
                    status="dry_run" if dry_run else "written",
                )
            )
    except RuntimeError as exc:
        logger.error("run failed: %s", exc)
        return 1
    finally:
        if primary_conn is not None:
            with contextlib.suppress(sqlite3.Error):
                primary_conn.close()
        if jpintel_conn is not None:
            with contextlib.suppress(sqlite3.Error):
                jpintel_conn.close()

    manifest.s3_put_cost_usd_estimate = (
        manifest.packets_written / 1000.0
    ) * S3_PUT_USD_PER_1K
    manifest.finished_at = now_utc_iso()

    manifest_path = (
        Path(args.manifest_out)
        if args.manifest_out is not None
        else local_out_dir / "run_manifest.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest.to_json(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    elapsed = time.perf_counter() - started_t
    logger.info(
        "run done: seen=%d written=%d empty=%d bytes_total=%d "
        "s3_put_usd~=%.4f manifest=%s dry_run=%s elapsed=%.1fs",
        manifest.packets_seen,
        manifest.packets_written,
        manifest.packets_skipped_empty,
        manifest.bytes_total,
        manifest.s3_put_cost_usd_estimate,
        manifest_path,
        manifest.dry_run,
        elapsed,
    )
    return 0
