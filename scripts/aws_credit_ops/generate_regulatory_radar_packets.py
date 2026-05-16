#!/usr/bin/env python3
"""Generate ``regulatory_change_radar_v1`` packets (Wave 53 type #4 of 5).

業種別 (JSIC major) × 会計年度 (fiscal_year) の法令変更 radar。Pre-render of
``am_amendment_diff`` rolled up against ``programs.jsic_major`` association
(via ``am_entities`` mapping when available). The fiscal_year axis is
extracted from ``detected_at`` (Japanese FY = April-to-March).

Cohort
------

::

    cohort = (jsic_major × fiscal_year)

JSIC major = A..V (22 categories incl. UNKNOWN); fiscal_year = up to 12
recent FYs. Design ceiling 22 × 12 = 264 cells, observed typically ~150-200
non-empty cells.

CLI::

    python scripts/aws_credit_ops/generate_regulatory_radar_packets.py \\
        --output-prefix out/packets/regulatory_change_radar_v1/ \\
        --limit 50

Constraints
-----------

* NO LLM API calls.
* Each packet < 25 KB (top-N truncation on amendment samples).
* DRY_RUN default — ``--commit`` flips to live S3 PUT.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

logger = logging.getLogger("generate_regulatory_radar_packets")

SCHEMA_VERSION: Final[str] = "jpcir.p0.v1"
PRODUCER: Final[str] = "jpcite-ai-execution-control-plane"
PACKAGE_KIND: Final[str] = "regulatory_change_radar_v1"
MAX_PACKET_BYTES: Final[int] = 25 * 1024
PER_AXIS_RECORD_CAP: Final[int] = 10
DEFAULT_DB_PATH: Final[str] = "autonomath.db"
S3_PUT_USD_PER_1K: Final[float] = 0.005

# Severity inference on field_name heuristics — kept conservative so we never
# over-claim a change that's actually metadata noise.
_HIGH_IMPACT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "eligibility_text",
        "eligibility_hash",
        "amount_max_yen",
        "amount_min_yen",
        "subsidy_rate",
        "deadline",
        "application_close_date",
        "official_url",
    }
)
_MEDIUM_IMPACT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "primary_name",
        "industry_jsic_medium",
        "industry_jsic_major",
        "target_profile",
        "authority_name",
    }
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 regulatory change radar packet は am_amendment_diff を業種 × 会計"
    "年度で集計した descriptive 指標です。個別制度の適用判断は所管官庁"
    "公示・税理士・行政書士の確認が必須です (税理士法 §52 / 行政書士法 §1の2"
    " boundaries)。"
)


@dataclass(frozen=True)
class PacketResult:
    cohort_id: str
    s3_key: str
    bytes_written: int
    total_amendments: int
    status: str


@dataclass
class RunManifest:
    started_at: str
    finished_at: str | None = None
    output_prefix: str = ""
    dry_run: bool = True
    total_cohorts: int = 0
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
            "total_cohorts": self.total_cohorts,
            "packets_written": self.packets_written,
            "packets_skipped_empty": self.packets_skipped_empty,
            "bytes_total": self.bytes_total,
            "s3_put_cost_usd_estimate": round(self.s3_put_cost_usd_estimate, 4),
            "results_sample": [r.__dict__ for r in self.results[:50]],
        }


@dataclass(frozen=True)
class CohortRow:
    jsic_major: str
    fiscal_year: str
    total_amendments: int
    by_impact: dict[str, int]
    by_field: dict[str, int]
    top_amendments: list[dict[str, Any]]
    freshest_detected_at: str | None
    distinct_entities: int


def _now_utc_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def _fiscal_year_from_iso(detected_at: str | None) -> str:
    if not isinstance(detected_at, str) or len(detected_at) < 7:
        return ""
    year_str = detected_at[:4]
    month_str = detected_at[5:7]
    if not (year_str.isdigit() and month_str.isdigit()):
        return ""
    year = int(year_str)
    month = int(month_str)
    fy = year - 1 if month < 4 else year
    return f"FY{fy}"


def _classify_field(field_name: str) -> str:
    if field_name in _HIGH_IMPACT_FIELDS:
        return "high"
    if field_name in _MEDIUM_IMPACT_FIELDS:
        return "medium"
    return "low"


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def build_entity_jsic_map(conn: sqlite3.Connection) -> dict[str, str]:
    """Map ``am_entities.canonical_id`` (program kind) → JSIC major.

    Uses raw_json `industry_jsic_major` when present, falls back to the JSIC
    major derived from `industry_jsic_medium[:1]`. Entities without any JSIC
    signal map to 'UNKNOWN'.
    """

    out: dict[str, str] = {}
    if not _table_exists(conn, "am_entities"):
        return out
    sql = (
        "SELECT canonical_id, "
        "       UPPER(COALESCE("
        "         json_extract(raw_json, '$.industry_jsic_major'), "
        "         SUBSTR(json_extract(raw_json, '$.industry_jsic_medium'),1,1), "
        "         'UNKNOWN'"
        "       )) AS jsic_major "
        "  FROM am_entities "
        " WHERE record_kind = 'program'"
    )
    with contextlib.suppress(sqlite3.Error):
        for row in conn.execute(sql):
            cid = row["canonical_id"]
            jm = row["jsic_major"]
            if isinstance(cid, str) and isinstance(jm, str) and jm:
                out[cid] = jm or "UNKNOWN"
    return out


def aggregate_cohorts(
    conn: sqlite3.Connection,
    *,
    limit: int | None,
) -> Iterator[CohortRow]:
    if not _table_exists(conn, "am_amendment_diff"):
        return
    entity_jsic = build_entity_jsic_map(conn)

    agg: dict[
        tuple[str, str],
        dict[str, Any],
    ] = {}

    sql = (
        "SELECT entity_id, field_name, prev_value, new_value, detected_at, "
        "       source_url "
        "  FROM am_amendment_diff "
        " WHERE detected_at IS NOT NULL"
    )
    for row in conn.execute(sql):
        entity_id = str(row["entity_id"] or "")
        jsic = entity_jsic.get(entity_id, "UNKNOWN")
        fy = _fiscal_year_from_iso(row["detected_at"])
        if not fy:
            continue
        key = (jsic, fy)
        bucket = agg.setdefault(
            key,
            {
                "total": 0,
                "by_impact": {"high": 0, "medium": 0, "low": 0},
                "by_field": {},
                "samples": [],
                "freshest": None,
                "entities": set(),
            },
        )
        field_name = str(row["field_name"] or "")
        impact = _classify_field(field_name)
        bucket["total"] += 1
        bucket["by_impact"][impact] = int(bucket["by_impact"][impact]) + 1
        bucket["by_field"][field_name] = int(bucket["by_field"].get(field_name, 0)) + 1
        bucket["entities"].add(entity_id)
        detected = row["detected_at"]
        cur_freshest = bucket["freshest"]
        if isinstance(detected, str) and (
            cur_freshest is None or detected > str(cur_freshest)
        ):
            bucket["freshest"] = detected
        if len(bucket["samples"]) < PER_AXIS_RECORD_CAP and impact != "low":
            bucket["samples"].append(
                {
                    "entity_id": entity_id,
                    "field_name": field_name,
                    "impact": impact,
                    "detected_at": detected,
                    "prev_value": (
                        str(row["prev_value"])[:200]
                        if row["prev_value"] is not None
                        else None
                    ),
                    "new_value": (
                        str(row["new_value"])[:200]
                        if row["new_value"] is not None
                        else None
                    ),
                    "source_url": row["source_url"],
                }
            )

    for emitted, ((jsic, fy), bucket) in enumerate(sorted(agg.items())):
        yield CohortRow(
            jsic_major=jsic,
            fiscal_year=fy,
            total_amendments=int(bucket["total"]),
            by_impact=dict(bucket["by_impact"]),
            by_field=dict(
                sorted(
                    bucket["by_field"].items(),
                    key=lambda kv: int(kv[1]),
                    reverse=True,
                )[:PER_AXIS_RECORD_CAP]
            ),
            top_amendments=bucket["samples"],
            freshest_detected_at=bucket["freshest"],
            distinct_entities=len(bucket["entities"]),
        )
        if limit is not None and (emitted + 1) >= limit:
            return


def render_packet(cohort: CohortRow, *, generated_at: str) -> dict[str, Any]:
    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "field_name 単位の impact 分類はヒューリスティックです。実際の"
                "事業者影響度は所管官庁公示・税理士・行政書士の確認が必要。"
            ),
        }
    ]
    if cohort.total_amendments == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": (
                    "このコホートで法令変更が観測されないことは"
                    "「変更ゼロ」を意味しません。一次官報・所管官庁の確認が必要。"
                ),
            }
        )
    if cohort.freshest_detected_at is None:
        known_gaps.append(
            {
                "code": "freshness_stale_or_unknown",
                "description": "freshest_detected_at 不明 — 鮮度確認不可。",
            }
        )

    sources = [
        {
            "source_url": "https://elaws.e-gov.go.jp/",
            "source_fetched_at": None,
            "publisher": "e-Gov 法令検索",
            "license": "cc_by_4.0",
        },
        {
            "source_url": "https://www.kanpo.go.jp/",
            "source_fetched_at": None,
            "publisher": "官報",
            "license": "gov_standard",
        },
    ]

    cohort_id = f"{cohort.jsic_major}.{cohort.fiscal_year}"
    package_id = f"regulatory_change_radar_v1:{cohort_id}"
    envelope: dict[str, Any] = {
        "object_id": package_id,
        "object_type": "packet",
        "created_at": generated_at,
        "producer": PRODUCER,
        "request_time_llm_call_performed": False,
        "schema_version": SCHEMA_VERSION,
        "package_id": package_id,
        "package_kind": PACKAGE_KIND,
        "generated_at": generated_at,
        "cohort_definition": {
            "cohort_id": cohort_id,
            "jsic_major": cohort.jsic_major,
            "fiscal_year": cohort.fiscal_year,
        },
        "metrics": {
            "total_amendments": cohort.total_amendments,
            "by_impact": cohort.by_impact,
            "by_field": cohort.by_field,
            "distinct_entities": cohort.distinct_entities,
        },
        "top_amendments": cohort.top_amendments,
        "freshest_detected_at": cohort.freshest_detected_at,
        "sources": sources,
        "known_gaps": known_gaps,
        "jpcite_cost_jpy": 0,
        "disclaimer": DEFAULT_DISCLAIMER,
    }
    return envelope


def validate_jpcir_header(envelope: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(envelope.get("object_id"), str) or not envelope["object_id"]:
        errors.append("object_id missing")
    if envelope.get("object_type") != "packet":
        errors.append("object_type must be packet")
    if envelope.get("producer") != PRODUCER:
        errors.append("producer mismatch")
    if envelope.get("request_time_llm_call_performed") is not False:
        errors.append("request_time_llm_call_performed must be false")
    if envelope.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version mismatch")
    return (not errors, errors)


def _import_boto3() -> Any:  # pragma: no cover
    try:
        import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError as exc:
        msg = "boto3 not installed"
        raise RuntimeError(msg) from exc
    return boto3


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    rest = uri[len("s3://") :]
    bucket, _slash, key = rest.partition("/")
    return bucket, key


def upload_packet(
    *,
    envelope: dict[str, Any],
    output_prefix: str,
    dry_run: bool,
    s3_client: Any | None,
    local_out_dir: Path,
) -> tuple[str, int]:
    cohort_id = envelope["cohort_definition"]["cohort_id"]
    body = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    bytes_written = len(body)
    if bytes_written > MAX_PACKET_BYTES:
        msg = f"packet {cohort_id} exceeds {MAX_PACKET_BYTES}: {bytes_written}"
        raise ValueError(msg)
    if output_prefix.startswith("s3://"):
        bucket, key_prefix = _parse_s3_uri(output_prefix)
        key = f"{key_prefix.rstrip('/')}/{cohort_id}.json"
        if dry_run or s3_client is None:
            local_path = local_out_dir / f"{cohort_id}.json"
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(body)
            return key, bytes_written
        s3_client.put_object(
            Bucket=bucket, Key=key, Body=body, ContentType="application/json"
        )
        return key, bytes_written
    local_path = Path(output_prefix).expanduser() / f"{cohort_id}.json"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(body)
    return str(local_path), bytes_written


def open_db_ro(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists() or db_path.stat().st_size == 0:
        msg = f"database not found or empty: {db_path}"
        raise RuntimeError(msg)
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute("PRAGMA query_only=1")
        conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def run(
    *,
    db_path: Path,
    output_prefix: str,
    limit: int | None,
    dry_run: bool,
    local_out_dir: Path,
) -> RunManifest:
    manifest = RunManifest(
        started_at=_now_utc_iso(), output_prefix=output_prefix, dry_run=dry_run
    )
    s3_client: Any | None = None
    if output_prefix.startswith("s3://") and not dry_run:
        s3_client = _import_boto3().client("s3")

    conn = open_db_ro(db_path)
    try:
        for cohort in aggregate_cohorts(conn, limit=limit):
            manifest.total_cohorts += 1
            generated_at = _now_utc_iso()
            envelope = render_packet(cohort, generated_at=generated_at)
            ok, errors = validate_jpcir_header(envelope)
            if not ok:
                logger.warning(
                    "schema validation failed: %s",
                    "; ".join(errors),
                )
                continue
            if cohort.total_amendments == 0:
                manifest.packets_skipped_empty += 1
                continue
            key, written = upload_packet(
                envelope=envelope,
                output_prefix=output_prefix,
                dry_run=dry_run,
                s3_client=s3_client,
                local_out_dir=local_out_dir,
            )
            manifest.packets_written += 1
            manifest.bytes_total += written
            manifest.results.append(
                PacketResult(
                    cohort_id=envelope["cohort_definition"]["cohort_id"],
                    s3_key=key,
                    bytes_written=written,
                    total_amendments=cohort.total_amendments,
                    status="dry_run" if dry_run else "written",
                )
            )
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()

    manifest.s3_put_cost_usd_estimate = (
        manifest.packets_written / 1000.0
    ) * S3_PUT_USD_PER_1K
    manifest.finished_at = _now_utc_iso()
    return manifest


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Pre-generate regulatory_change_radar_v1 packets for the "
            "(jsic_major × fiscal_year) cohort cross-product."
        ),
    )
    p.add_argument("--output-prefix", required=True)
    p.add_argument("--db", default=DEFAULT_DB_PATH)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--local-out-dir", default="out/regulatory_change_radar_v1")
    p.add_argument("--commit", action="store_true")
    p.add_argument("--manifest-out", default=None)
    return p.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv if argv is not None else sys.argv[1:])
    dry_run = not args.commit
    if os.environ.get("DRY_RUN") == "0" and not args.commit:
        logger.warning("DRY_RUN=0 set but --commit missing — staying in dry-run.")
    db_path = Path(args.db)
    local_out_dir = Path(args.local_out_dir)
    local_out_dir.mkdir(parents=True, exist_ok=True)
    started_t = time.perf_counter()
    try:
        manifest = run(
            db_path=db_path,
            output_prefix=str(args.output_prefix),
            limit=int(args.limit) if args.limit is not None else None,
            dry_run=dry_run,
            local_out_dir=local_out_dir,
        )
    except RuntimeError as exc:
        logger.error("run failed: %s", exc)
        return 1

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
        "run done: cohorts=%d written=%d empty=%d bytes_total=%d "
        "s3_put_usd~=%.4f manifest=%s dry_run=%s elapsed=%.1fs",
        manifest.total_cohorts,
        manifest.packets_written,
        manifest.packets_skipped_empty,
        manifest.bytes_total,
        manifest.s3_put_cost_usd_estimate,
        manifest_path,
        manifest.dry_run,
        elapsed,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
