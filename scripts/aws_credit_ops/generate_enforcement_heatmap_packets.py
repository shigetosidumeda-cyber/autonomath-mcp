#!/usr/bin/env python3
"""Generate ``enforcement_industry_heatmap_v1`` cohort packets.

Wave 53 packet type #1 of 5 — 行政処分 × 業種 × 地域 heatmap. One packet per
``(prefecture, jsic_major)`` cohort cell (47 × 22 = 1,034 design ceiling;
observed cohort is sparse — natural distribution lands ~700-900 non-empty
cells). The packet rolls up:

* counts by ``enforcement_kind`` (8-kind enum).
* counts by severity band (low / medium / high; mirrors houjin_360 weights).
* top-K named houjin_bangou (capped) so the agent can drill down.
* law_ref overlap (rolled up from ``related_law_ref``).

Each packet is a JPCIR envelope (``request_time_llm_call_performed=false``)
that stays under ``MAX_PACKET_BYTES`` via top-N truncation. The cross-source
join is Python-side over ``am_enforcement_detail`` + ``houjin_master``.

Cohort definition
-----------------

::

    cohort = (prefecture × jsic_major)

* ``prefecture``  — ``houjin_master.prefecture`` UPPER or 'UNKNOWN'.
* ``jsic_major``  — ``houjin_master.jsic_major`` A..V or 'UNKNOWN'.

CLI::

    python scripts/aws_credit_ops/generate_enforcement_heatmap_packets.py \\
        --output-prefix out/packets/enforcement_industry_heatmap_v1/ \\
        --limit 50

Constraints
-----------

* NO LLM API calls. Pure SQLite + Python aggregation.
* Each packet < 25 KB (top-N truncation enforced).
* DRY_RUN default — ``--commit`` flips to live S3 PUT when output is s3://.
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

# PERF-23: roll out the PERF-11 orjson + os.write hot-path pattern. The
# per-packet serialize + write goes through ``_packet_base._dumps_compact``
# (orjson under the hood with a stdlib fallback) and ``_write_bytes_fast``
# (single-syscall ``os.open`` + ``os.write`` + ``os.close``). Manifest /
# ledger writes stay on stdlib ``json`` — those are one-shot, indented,
# and not on the hot path.
from scripts.aws_credit_ops._packet_base import (
    _dumps_compact,
    _write_bytes_fast,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

logger = logging.getLogger("generate_enforcement_heatmap_packets")

SCHEMA_VERSION: Final[str] = "jpcir.p0.v1"
PRODUCER: Final[str] = "jpcite-ai-execution-control-plane"
PACKAGE_KIND: Final[str] = "enforcement_industry_heatmap_v1"
MAX_PACKET_BYTES: Final[int] = 25 * 1024
PER_AXIS_RECORD_CAP: Final[int] = 10
DEFAULT_DB_PATH: Final[str] = "autonomath.db"
DEFAULT_DERIVED_BUCKET: Final[str] = "jpcite-credit-993693061769-202605-derived"
S3_PUT_USD_PER_1K: Final[float] = 0.005

_SEVERITY_HIGH: Final[frozenset[str]] = frozenset({"license_revoke", "fine", "grant_refund"})
_SEVERITY_MEDIUM: Final[frozenset[str]] = frozenset({"subsidy_exclude", "contract_suspend"})

KNOWN_GAP_CODES: Final[frozenset[str]] = frozenset(
    {
        "csv_input_not_evidence_safe",
        "source_receipt_incomplete",
        "pricing_or_cap_unconfirmed",
        "no_hit_not_absence",
        "professional_review_required",
        "freshness_stale_or_unknown",
        "identity_ambiguity_unresolved",
    }
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 enforcement heatmap packet は am_enforcement_detail × houjin_master "
    "の公開コーパス集計です。個別事業者の与信・取引判断は税理士・弁護士・"
    "金融機関の確認が必須です。tier B 以下の業種別カウントは標本誤差の "
    "影響を強く受けるため、参照値として扱ってください。"
)


@dataclass(frozen=True)
class PacketResult:
    """Per-cohort outcome."""

    cohort_id: str
    s3_key: str
    bytes_written: int
    total_enforcements: int
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
    prefecture: str
    jsic_major: str
    total_enforcements: int
    by_kind: dict[str, int]
    by_severity: dict[str, int]
    top_houjin: list[dict[str, Any]]
    law_refs: list[str]
    freshest_issuance: str | None
    distinct_authorities: int

    @property
    def cohort_id(self) -> str:
        return f"{self.prefecture}.{self.jsic_major}"


def _now_utc_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def _classify_severity(kind: str) -> str:
    if kind in _SEVERITY_HIGH:
        return "high"
    if kind in _SEVERITY_MEDIUM:
        return "medium"
    return "low"


def _normalise(value: str | None, fallback: str = "UNKNOWN") -> str:
    if value is None:
        return fallback
    stripped = str(value).strip().upper()
    return stripped or fallback


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def aggregate_cohorts(
    conn: sqlite3.Connection,
    *,
    limit: int | None,
) -> Iterator[CohortRow]:
    """Aggregate ``(prefecture, jsic_major)`` cohorts from enforcement × houjin."""

    if not _table_exists(conn, "am_enforcement_detail"):
        return
    if not _table_exists(conn, "houjin_master"):
        logger.warning("houjin_master missing — cohort packet quality will be degraded.")

    agg: dict[
        tuple[str, str],
        dict[str, Any],
    ] = {}

    # Single join — enforcement on the left, houjin_master on the right so we
    # always emit every enforcement row even when houjin_master rolls in late.
    sql = (
        "SELECT e.houjin_bangou, e.enforcement_kind, e.issuance_date, "
        "       e.issuing_authority, e.related_law_ref, e.reason_summary, "
        "       e.amount_yen, e.target_name, "
        "       h.prefecture, h.jsic_major "
        "  FROM am_enforcement_detail e "
        "  LEFT JOIN houjin_master h "
        "       ON h.houjin_bangou = e.houjin_bangou "
        " WHERE e.issuance_date IS NOT NULL"
    )
    for row in conn.execute(sql):
        pref = _normalise(row["prefecture"])
        jsic = _normalise(row["jsic_major"])
        key = (pref, jsic)
        bucket = agg.setdefault(
            key,
            {
                "total": 0,
                "by_kind": {},
                "by_severity": {"low": 0, "medium": 0, "high": 0},
                "houjin_counts": {},
                "law_refs": set(),
                "authorities": set(),
                "freshest": None,
            },
        )
        kind = str(row["enforcement_kind"] or "other")
        severity = _classify_severity(kind)
        bucket["total"] += 1
        bucket["by_kind"][kind] = int(bucket["by_kind"].get(kind, 0)) + 1
        bucket["by_severity"][severity] += 1

        bangou = row["houjin_bangou"]
        if isinstance(bangou, str) and bangou:
            counts = bucket["houjin_counts"]
            current = counts.get(
                bangou,
                {"count": 0, "target_name": row["target_name"], "max_severity": "low"},
            )
            current["count"] = int(current["count"]) + 1
            sev_rank = {"low": 1, "medium": 2, "high": 3}
            if sev_rank[severity] > sev_rank[current["max_severity"]]:
                current["max_severity"] = severity
            counts[bangou] = current

        law_ref = row["related_law_ref"]
        if isinstance(law_ref, str) and law_ref.strip():
            bucket["law_refs"].add(law_ref.strip())
        authority = row["issuing_authority"]
        if isinstance(authority, str) and authority.strip():
            bucket["authorities"].add(authority.strip())
        issuance = row["issuance_date"]
        cur_freshest = bucket["freshest"]
        if isinstance(issuance, str) and (cur_freshest is None or issuance > str(cur_freshest)):
            bucket["freshest"] = issuance

    for emitted, ((pref, jsic), bucket) in enumerate(sorted(agg.items())):
        houjin_top = sorted(
            ({"houjin_bangou": b, **v} for b, v in bucket["houjin_counts"].items()),
            key=lambda d: int(d["count"]),
            reverse=True,
        )[:PER_AXIS_RECORD_CAP]
        yield CohortRow(
            prefecture=pref,
            jsic_major=jsic,
            total_enforcements=int(bucket["total"]),
            by_kind=dict(bucket["by_kind"]),
            by_severity=dict(bucket["by_severity"]),
            top_houjin=houjin_top,
            law_refs=sorted(bucket["law_refs"])[:PER_AXIS_RECORD_CAP],
            freshest_issuance=bucket["freshest"],
            distinct_authorities=len(bucket["authorities"]),
        )
        if limit is not None and (emitted + 1) >= limit:
            return


def render_packet(cohort: CohortRow, *, generated_at: str) -> dict[str, Any]:
    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "業種別集計は標本効果あり。個別与信判断は税理士・弁護士・金融機関の一次確認が必須。"
            ),
        }
    ]
    if cohort.total_enforcements == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": (
                    "このコホートで処分が観測されないことは「処分ゼロ」を意味"
                    "しません。所管官庁の確認が必要です。"
                ),
            }
        )
    if cohort.freshest_issuance is None:
        known_gaps.append(
            {
                "code": "freshness_stale_or_unknown",
                "description": "freshest_issuance_date 不明 — 鮮度確認不可。",
            }
        )

    sources = [
        {
            "source_url": "https://www.maff.go.jp/j/keiei/",  # MAFF enforcement listings
            "source_fetched_at": None,
            "publisher": "am_enforcement_detail (jpcite corpus)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.houjin-bangou.nta.go.jp/",
            "source_fetched_at": None,
            "publisher": "NTA 法人番号公表サイト",
            "license": "pdl_v1.0",
        },
    ]

    package_id = f"enforcement_industry_heatmap_v1:{cohort.cohort_id}"
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
            "cohort_id": cohort.cohort_id,
            "prefecture": cohort.prefecture,
            "jsic_major": cohort.jsic_major,
        },
        "metrics": {
            "total_enforcements": cohort.total_enforcements,
            "by_kind": cohort.by_kind,
            "by_severity": cohort.by_severity,
            "distinct_authorities": cohort.distinct_authorities,
        },
        "top_houjin": cohort.top_houjin,
        "law_refs": cohort.law_refs,
        "freshest_issuance": cohort.freshest_issuance,
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
        msg = "boto3 is not installed. Install boto3 before running with --commit on s3:// targets."
        raise RuntimeError(msg) from exc
    return boto3


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        msg = f"not an s3 URI: {uri!r}"
        raise ValueError(msg)
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
    # PERF-23 hot path: ``_dumps_compact`` (orjson, 5-10x stdlib json)
    # + ``_write_bytes_fast`` (single-syscall O_WRONLY|O_CREAT|O_TRUNC),
    # 1 packet/file Athena contract preserved.
    cohort_id = envelope["cohort_definition"]["cohort_id"]
    body = _dumps_compact(envelope)
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
            _write_bytes_fast(local_path, body)
            return key, bytes_written
        s3_client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")
        return key, bytes_written

    local_path = Path(output_prefix).expanduser() / f"{cohort_id}.json"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    _write_bytes_fast(local_path, body)
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
    manifest = RunManifest(started_at=_now_utc_iso(), output_prefix=output_prefix, dry_run=dry_run)
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
                    "schema validation failed %s: %s",
                    cohort.cohort_id,
                    "; ".join(errors),
                )
                continue
            if cohort.total_enforcements == 0:
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
                    cohort_id=cohort.cohort_id,
                    s3_key=key,
                    bytes_written=written,
                    total_enforcements=cohort.total_enforcements,
                    status="dry_run" if dry_run else "written",
                )
            )
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()

    manifest.s3_put_cost_usd_estimate = (manifest.packets_written / 1000.0) * S3_PUT_USD_PER_1K
    manifest.finished_at = _now_utc_iso()
    return manifest


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Pre-generate enforcement_industry_heatmap_v1 packets for the "
            "(prefecture × jsic_major) cohort cross-product."
        ),
    )
    p.add_argument("--output-prefix", required=True)
    p.add_argument("--db", default=DEFAULT_DB_PATH)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--local-out-dir", default="out/enforcement_industry_heatmap_v1")
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
