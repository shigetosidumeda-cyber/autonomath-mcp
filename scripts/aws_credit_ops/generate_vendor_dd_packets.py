#!/usr/bin/env python3
"""Generate ``vendor_due_diligence_v1`` packets (Wave 53 type #3 of 5).

Vendor / counterparty due-diligence cohort. Similar to ``houjin_360`` but
re-shaped from a **risk** perspective: instead of equally weighted axes, this
packet surfaces a deterministic ``risk_score`` (0..1) keyed on:

* enforcement presence + severity (heaviest weight).
* invoice registration freshness (active / revoked / expired).
* close_date / dormancy signal from houjin_master.
* adoption activity = positive signal (offset, not main axis).
* unresolved identity (no houjin_master row) = unknown_risk penalty.

The risk_score is *descriptive* — not a credit recommendation. The disclaimer
hard-codes that pattern (税理士法 §52 / 弁護士法 §72 / 司法書士法 §3 boundaries).

Cohort
------

::

    subject = houjin_bangou (166,765 rows in houjin_master)

CLI::

    python scripts/aws_credit_ops/generate_vendor_dd_packets.py \\
        --output-prefix out/packets/vendor_due_diligence_v1/ \\
        --limit 50

Constraints
-----------

* NO LLM API calls.
* Each packet < 25 KB (top-N truncation on enforcement records).
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

# PERF-23: orjson + os.write per-packet hot path; manifest writes stay
# on stdlib ``json`` because they are one-shot + indented.
from scripts.aws_credit_ops._packet_base import (
    _dumps_compact,
    _write_bytes_fast,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

logger = logging.getLogger("generate_vendor_dd_packets")

SCHEMA_VERSION: Final[str] = "jpcir.p0.v1"
PRODUCER: Final[str] = "jpcite-ai-execution-control-plane"
PACKAGE_KIND: Final[str] = "vendor_due_diligence_v1"
MAX_PACKET_BYTES: Final[int] = 25 * 1024
PER_AXIS_RECORD_CAP: Final[int] = 5
DEFAULT_DB_PATH: Final[str] = "autonomath.db"
S3_PUT_USD_PER_1K: Final[float] = 0.005

_ENFORCEMENT_SEVERITY: Final[dict[str, str]] = {
    "license_revoke": "high",
    "fine": "high",
    "grant_refund": "high",
    "subsidy_exclude": "medium",
    "contract_suspend": "medium",
    "investigation": "low",
    "business_improvement": "low",
    "warning": "low",
}

DEFAULT_DISCLAIMER: Final[str] = (
    "本 vendor due-diligence packet は 公開コーパス由来の descriptive "
    "risk 集計です。risk_score は与信判断・取引可否の最終決定指標ではなく、"
    "個別契約は税理士・弁護士・与信会社による確認が必須です "
    "(税理士法 §52 / 弁護士法 §72 / 司法書士法 §3 boundaries)。"
)


@dataclass(frozen=True)
class PacketResult:
    houjin_bangou: str
    s3_key: str
    bytes_written: int
    risk_score: float
    risk_grade: str
    status: str


@dataclass
class RunManifest:
    started_at: str
    finished_at: str | None = None
    output_prefix: str = ""
    dry_run: bool = True
    total_houjin: int = 0
    packets_written: int = 0
    bytes_total: int = 0
    s3_put_cost_usd_estimate: float = 0.0
    risk_grade_counts: dict[str, int] = field(default_factory=dict)
    results: list[PacketResult] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "output_prefix": self.output_prefix,
            "dry_run": self.dry_run,
            "total_houjin": self.total_houjin,
            "packets_written": self.packets_written,
            "bytes_total": self.bytes_total,
            "s3_put_cost_usd_estimate": round(self.s3_put_cost_usd_estimate, 4),
            "risk_grade_counts": self.risk_grade_counts,
            "results_sample": [r.__dict__ for r in self.results[:50]],
        }


@dataclass(frozen=True)
class HoujinSummary:
    houjin_bangou: str
    name: str
    prefecture: str | None
    jsic_major: str | None
    established_date: str | None
    close_date: str | None
    total_adoptions: int
    enforcement_records: list[dict[str, Any]]
    invoice_status: str
    last_updated_nta: str | None


def _now_utc_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def _risk_grade(score: float) -> str:
    if score >= 0.80:
        return "high_risk"
    if score >= 0.55:
        return "elevated"
    if score >= 0.30:
        return "watch"
    if score >= 0.10:
        return "monitor"
    return "low_signal"


def compute_risk_score(summary: HoujinSummary) -> tuple[float, dict[str, float]]:
    components: dict[str, float] = {
        "enforcement_severity": 0.0,
        "enforcement_volume": 0.0,
        "invoice_status_penalty": 0.0,
        "close_date_penalty": 0.0,
        "adoption_offset": 0.0,
        "unknown_master_penalty": 0.0,
    }
    severity_rank = {"low": 0.10, "medium": 0.35, "high": 0.70}
    if summary.enforcement_records:
        max_sev = max(
            (
                severity_rank.get(r.get("severity", "low") or "low", 0.10)
                for r in summary.enforcement_records
            ),
            default=0.0,
        )
        components["enforcement_severity"] = float(max_sev)
        volume = min(0.30, 0.05 * len(summary.enforcement_records))
        components["enforcement_volume"] = volume

    if summary.invoice_status == "revoked":
        components["invoice_status_penalty"] = 0.30
    elif summary.invoice_status == "expired":
        components["invoice_status_penalty"] = 0.20
    elif summary.invoice_status == "not_found":
        components["invoice_status_penalty"] = 0.10

    if summary.close_date:
        components["close_date_penalty"] = 0.40

    if summary.total_adoptions > 0:
        components["adoption_offset"] = -min(0.15, 0.02 * summary.total_adoptions)

    if not summary.name:
        components["unknown_master_penalty"] = 0.10

    raw = sum(components.values())
    score = max(0.0, min(1.0, raw))
    return round(score, 4), {k: round(v, 4) for k, v in components.items()}


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def enumerate_houjin(
    conn: sqlite3.Connection,
    *,
    limit: int | None,
) -> Iterator[HoujinSummary]:
    if not _table_exists(conn, "houjin_master"):
        msg = "houjin_master not present"
        raise RuntimeError(msg)
    sql = (
        "SELECT houjin_bangou, normalized_name, prefecture, jsic_major, "
        "       established_date, close_date, total_adoptions, "
        "       last_updated_nta "
        "  FROM houjin_master "
        " ORDER BY total_adoptions DESC, houjin_bangou"
    )
    cur = conn.execute(sql)
    yielded = 0
    for row in cur:
        bangou = str(row["houjin_bangou"] or "")
        if not bangou:
            continue
        enforcement = fetch_enforcement(conn, bangou)
        invoice_status = fetch_invoice_status(conn, bangou)
        yield HoujinSummary(
            houjin_bangou=bangou,
            name=str(row["normalized_name"] or ""),
            prefecture=row["prefecture"],
            jsic_major=row["jsic_major"],
            established_date=row["established_date"],
            close_date=row["close_date"],
            total_adoptions=int(row["total_adoptions"] or 0),
            enforcement_records=enforcement,
            invoice_status=invoice_status,
            last_updated_nta=row["last_updated_nta"],
        )
        yielded += 1  # noqa: SIM113 - cannot use enumerate() due to skip-on-empty-bangou above
        if limit is not None and yielded >= limit:
            return


def fetch_enforcement(conn: sqlite3.Connection, houjin_bangou: str) -> list[dict[str, Any]]:
    if not _table_exists(conn, "am_enforcement_detail"):
        return []
    rows = conn.execute(
        "SELECT issuance_date, enforcement_kind, reason_summary, "
        "       amount_yen, issuing_authority, related_law_ref, source_url "
        "  FROM am_enforcement_detail "
        " WHERE houjin_bangou = ? "
        " ORDER BY issuance_date DESC "
        " LIMIT ?",
        (houjin_bangou, PER_AXIS_RECORD_CAP * 4),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows[:PER_AXIS_RECORD_CAP]:
        kind = str(r["enforcement_kind"] or "other")
        out.append(
            {
                "issuance_date": r["issuance_date"],
                "enforcement_kind": kind,
                "severity": _ENFORCEMENT_SEVERITY.get(kind, "low"),
                "reason_summary": r["reason_summary"],
                "amount_yen": (int(r["amount_yen"]) if r["amount_yen"] is not None else None),
                "issuing_authority": r["issuing_authority"],
                "related_law_ref": r["related_law_ref"],
                "source_url": r["source_url"],
            }
        )
    return out


def fetch_invoice_status(conn: sqlite3.Connection, houjin_bangou: str) -> str:
    if not _table_exists(conn, "jpi_invoice_registrants"):
        return "not_found"
    row = conn.execute(
        "SELECT revoked_date, expired_date, invoice_registration_number "
        "  FROM jpi_invoice_registrants "
        " WHERE houjin_bangou = ? "
        " LIMIT 1",
        (houjin_bangou,),
    ).fetchone()
    if row is None:
        return "not_found"
    if row["revoked_date"]:
        return "revoked"
    if row["expired_date"]:
        return "expired"
    if row["invoice_registration_number"]:
        return "active"
    return "inactive"


def render_packet(
    summary: HoujinSummary,
    *,
    generated_at: str,
) -> dict[str, Any]:
    risk_score, components = compute_risk_score(summary)
    grade = _risk_grade(risk_score)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "risk_score は descriptive 指標で、与信・取引判断は税理士・"
                "弁護士・与信会社の確認が必須。"
            ),
        }
    ]
    if not summary.enforcement_records and summary.invoice_status == "not_found":
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": (
                    "公開コーパス内で処分・インボイス登録ヒットなし — 「ノーリスク」を意味しません"
                ),
            }
        )
    if not summary.name:
        known_gaps.append(
            {
                "code": "identity_ambiguity_unresolved",
                "description": "normalized_name 不在 — NTA bulk pending の可能性",
            }
        )

    sources = [
        {
            "source_url": (
                f"https://www.houjin-bangou.nta.go.jp/henkorireki-johoto?id={summary.houjin_bangou}"
            ),
            "source_fetched_at": summary.last_updated_nta,
            "publisher": "NTA 法人番号公表サイト",
            "license": "pdl_v1.0",
        }
    ]
    for record in summary.enforcement_records:
        url = record.get("source_url")
        if isinstance(url, str) and url:
            sources.append(
                {
                    "source_url": url,
                    "source_fetched_at": None,
                    "publisher": "am_enforcement_detail",
                    "license": "gov_standard",
                }
            )

    package_id = f"vendor_due_diligence_v1:{summary.houjin_bangou}"
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
        "subject": {"kind": "houjin", "id": summary.houjin_bangou},
        "vendor": {
            "houjin_bangou": summary.houjin_bangou,
            "name": summary.name,
            "prefecture": summary.prefecture,
            "jsic_major": summary.jsic_major,
            "established_date": summary.established_date,
            "close_date": summary.close_date,
            "total_adoptions": summary.total_adoptions,
            "invoice_status": summary.invoice_status,
        },
        "risk": {
            "risk_score": risk_score,
            "risk_grade": grade,
            "components": components,
        },
        "enforcement_records": summary.enforcement_records,
        "sources": sources[: PER_AXIS_RECORD_CAP * 2],
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
    # PERF-23 hot path: orjson + os.write, 1 packet/file Athena contract
    # preserved.
    subject_id = envelope["subject"]["id"]
    body = _dumps_compact(envelope)
    bytes_written = len(body)
    if bytes_written > MAX_PACKET_BYTES:
        msg = f"packet {subject_id} exceeds {MAX_PACKET_BYTES}: {bytes_written}"
        raise ValueError(msg)
    if output_prefix.startswith("s3://"):
        bucket, key_prefix = _parse_s3_uri(output_prefix)
        key = f"{key_prefix.rstrip('/')}/{subject_id}.json"
        if dry_run or s3_client is None:
            local_path = local_out_dir / f"{subject_id}.json"
            local_path.parent.mkdir(parents=True, exist_ok=True)
            _write_bytes_fast(local_path, body)
            return key, bytes_written
        s3_client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")
        return key, bytes_written
    local_path = Path(output_prefix).expanduser() / f"{subject_id}.json"
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
        for summary in enumerate_houjin(conn, limit=limit):
            manifest.total_houjin += 1
            generated_at = _now_utc_iso()
            envelope = render_packet(summary, generated_at=generated_at)
            ok, errors = validate_jpcir_header(envelope)
            if not ok:
                logger.warning(
                    "schema validation failed %s: %s",
                    summary.houjin_bangou,
                    "; ".join(errors),
                )
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
            score = float(envelope["risk"]["risk_score"])
            grade = str(envelope["risk"]["risk_grade"])
            manifest.risk_grade_counts[grade] = manifest.risk_grade_counts.get(grade, 0) + 1
            manifest.results.append(
                PacketResult(
                    houjin_bangou=summary.houjin_bangou,
                    s3_key=key,
                    bytes_written=written,
                    risk_score=score,
                    risk_grade=grade,
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
            "Pre-generate vendor_due_diligence_v1 packets for 166,765 "
            "houjin_master rows with deterministic risk scoring."
        ),
    )
    p.add_argument("--output-prefix", required=True)
    p.add_argument("--db", default=DEFAULT_DB_PATH)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--local-out-dir", default="out/vendor_due_diligence_v1")
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
        "run done: houjin=%d written=%d grades=%s bytes_total=%d "
        "s3_put_usd~=%.4f manifest=%s dry_run=%s elapsed=%.1fs",
        manifest.total_houjin,
        manifest.packets_written,
        manifest.risk_grade_counts,
        manifest.bytes_total,
        manifest.s3_put_cost_usd_estimate,
        manifest_path,
        manifest.dry_run,
        elapsed,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
