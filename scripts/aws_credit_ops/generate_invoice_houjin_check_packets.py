#!/usr/bin/env python3
"""Generate ``invoice_houjin_cross_check_v1`` packets (Wave 53 type #2 of 5).

One packet per invoice_registrant row, cross-source-checking the T 番号 record
against ``houjin_master`` for name / address / prefecture / 取消・失効 status
agreement. Surface the agreement breakdown so an agent can route based on
"インボイス登録あり & 法人番号レコード一致" vs "登録あり / 法人番号未収録"
vs "登録あり / 名前不一致" without re-running the join.

Cohort definition
-----------------

::

    subject = invoice_registration_number (T + 13 digits)

CLI::

    python scripts/aws_credit_ops/generate_invoice_houjin_check_packets.py \\
        --output-prefix out/packets/invoice_houjin_cross_check_v1/ \\
        --limit 50

Constraints
-----------

* NO LLM API calls.
* Each packet < 25 KB (single invoice + matching houjin record).
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

# PERF-23: roll out the PERF-11 orjson + os.write hot-path pattern. Per
# packet serialize + write goes through ``_packet_base._dumps_compact``
# (orjson) + ``_write_bytes_fast`` (single-syscall write). Manifest and
# ledger writes stay on stdlib ``json`` — those are one-shot, indented,
# and not on the hot path.
from scripts.aws_credit_ops._packet_base import (
    _dumps_compact,
    _write_bytes_fast,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

logger = logging.getLogger("generate_invoice_houjin_check_packets")

SCHEMA_VERSION: Final[str] = "jpcir.p0.v1"
PRODUCER: Final[str] = "jpcite-ai-execution-control-plane"
PACKAGE_KIND: Final[str] = "invoice_houjin_cross_check_v1"
MAX_PACKET_BYTES: Final[int] = 25 * 1024
DEFAULT_DB_PATH: Final[str] = "autonomath.db"
S3_PUT_USD_PER_1K: Final[float] = 0.005

DEFAULT_DISCLAIMER: Final[str] = (
    "本 invoice cross-check packet は jpi_invoice_registrants × houjin_master "
    "の名寄せ結果。一致/不一致の判定は normalised string 比較で、与信・取引"
    "信頼性の最終判断は税理士・弁護士の確認が必要です。"
)


@dataclass(frozen=True)
class PacketResult:
    invoice_registration_number: str
    s3_key: str
    bytes_written: int
    agreement_grade: str
    status: str


@dataclass
class RunManifest:
    started_at: str
    finished_at: str | None = None
    output_prefix: str = ""
    dry_run: bool = True
    total_invoices: int = 0
    packets_written: int = 0
    bytes_total: int = 0
    s3_put_cost_usd_estimate: float = 0.0
    agreement_grade_counts: dict[str, int] = field(default_factory=dict)
    results: list[PacketResult] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "output_prefix": self.output_prefix,
            "dry_run": self.dry_run,
            "total_invoices": self.total_invoices,
            "packets_written": self.packets_written,
            "bytes_total": self.bytes_total,
            "s3_put_cost_usd_estimate": round(self.s3_put_cost_usd_estimate, 4),
            "agreement_grade_counts": self.agreement_grade_counts,
            "results_sample": [r.__dict__ for r in self.results[:50]],
        }


@dataclass(frozen=True)
class InvoiceRow:
    invoice_registration_number: str
    houjin_bangou: str | None
    invoice_name: str
    invoice_address: str | None
    invoice_prefecture: str | None
    registered_date: str
    revoked_date: str | None
    expired_date: str | None
    registrant_kind: str
    last_updated_nta: str | None
    source_url: str


@dataclass(frozen=True)
class HoujinRow:
    houjin_bangou: str
    normalized_name: str
    address_normalized: str | None
    prefecture: str | None
    corporation_type: str | None
    established_date: str | None
    close_date: str | None
    last_updated_nta: str | None


def _now_utc_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def _norm(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _infer_invoice_status(row: InvoiceRow) -> str:
    if row.revoked_date:
        return "revoked"
    if row.expired_date:
        return "expired"
    return "active"


def compute_agreement(
    invoice: InvoiceRow, houjin: HoujinRow | None
) -> tuple[dict[str, str | bool], str]:
    """Return ``({field: agreement_state}, grade)``."""

    if houjin is None:
        return (
            {
                "houjin_master_present": False,
                "name_match": "no_houjin",
                "prefecture_match": "no_houjin",
                "address_match": "no_houjin",
                "close_date_consistency": "no_houjin",
            },
            "D",
        )

    invoice_name = _norm(invoice.invoice_name)
    houjin_name = _norm(houjin.normalized_name)
    name_match: str
    if invoice_name and houjin_name and invoice_name == houjin_name:
        name_match = "exact"
    elif (
        invoice_name
        and houjin_name
        and (invoice_name in houjin_name or houjin_name in invoice_name)
    ):
        name_match = "partial"
    else:
        name_match = "mismatch"

    invoice_pref = _norm(invoice.invoice_prefecture)
    houjin_pref = _norm(houjin.prefecture)
    if invoice_pref and houjin_pref and invoice_pref == houjin_pref:
        pref_match = "exact"
    elif not invoice_pref or not houjin_pref:
        pref_match = "missing"
    else:
        pref_match = "mismatch"

    invoice_addr = _norm(invoice.invoice_address)
    houjin_addr = _norm(houjin.address_normalized)
    if invoice_addr and houjin_addr and invoice_addr == houjin_addr:
        addr_match = "exact"
    elif (
        invoice_addr
        and houjin_addr
        and (invoice_addr in houjin_addr or houjin_addr in invoice_addr)
    ):
        addr_match = "partial"
    elif not invoice_addr or not houjin_addr:
        addr_match = "missing"
    else:
        addr_match = "mismatch"

    # close_date consistency — invoice cannot be active if houjin is closed.
    invoice_active = invoice.revoked_date is None and invoice.expired_date is None
    close_consistency = "inconsistent" if houjin.close_date and invoice_active else "consistent"

    agreement: dict[str, str | bool] = {
        "houjin_master_present": True,
        "name_match": name_match,
        "prefecture_match": pref_match,
        "address_match": addr_match,
        "close_date_consistency": close_consistency,
    }

    score = 0
    if name_match == "exact":
        score += 3
    elif name_match == "partial":
        score += 1
    if pref_match == "exact":
        score += 2
    elif pref_match == "missing":
        score += 1
    if addr_match == "exact":
        score += 2
    elif addr_match in {"partial", "missing"}:
        score += 1
    if close_consistency == "consistent":
        score += 1

    grade: str
    if score >= 8:
        grade = "S"
    elif score >= 6:
        grade = "A"
    elif score >= 4:
        grade = "B"
    elif score >= 2:
        grade = "C"
    else:
        grade = "D"
    return agreement, grade


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def enumerate_invoices(
    conn: sqlite3.Connection,
    *,
    limit: int | None,
) -> Iterator[InvoiceRow]:
    if not _table_exists(conn, "jpi_invoice_registrants"):
        msg = "jpi_invoice_registrants table missing"
        raise RuntimeError(msg)
    sql = (
        "SELECT invoice_registration_number, houjin_bangou, normalized_name, "
        "       address_normalized, prefecture, registered_date, "
        "       revoked_date, expired_date, registrant_kind, "
        "       last_updated_nta, source_url "
        "  FROM jpi_invoice_registrants "
        " ORDER BY invoice_registration_number"
    )
    cur = conn.execute(sql)
    for yielded, row in enumerate(cur):
        yield InvoiceRow(
            invoice_registration_number=str(row["invoice_registration_number"]),
            houjin_bangou=row["houjin_bangou"],
            invoice_name=str(row["normalized_name"] or ""),
            invoice_address=row["address_normalized"],
            invoice_prefecture=row["prefecture"],
            registered_date=str(row["registered_date"] or ""),
            revoked_date=row["revoked_date"],
            expired_date=row["expired_date"],
            registrant_kind=str(row["registrant_kind"] or "other"),
            last_updated_nta=row["last_updated_nta"],
            source_url=str(row["source_url"] or ""),
        )
        if limit is not None and (yielded + 1) >= limit:
            return


def fetch_houjin(conn: sqlite3.Connection, houjin_bangou: str) -> HoujinRow | None:
    if not _table_exists(conn, "houjin_master"):
        return None
    row = conn.execute(
        "SELECT houjin_bangou, normalized_name, address_normalized, "
        "       prefecture, corporation_type, established_date, "
        "       close_date, last_updated_nta "
        "  FROM houjin_master WHERE houjin_bangou = ?",
        (houjin_bangou,),
    ).fetchone()
    if row is None:
        return None
    return HoujinRow(
        houjin_bangou=row["houjin_bangou"],
        normalized_name=str(row["normalized_name"] or ""),
        address_normalized=row["address_normalized"],
        prefecture=row["prefecture"],
        corporation_type=row["corporation_type"],
        established_date=row["established_date"],
        close_date=row["close_date"],
        last_updated_nta=row["last_updated_nta"],
    )


def render_packet(
    invoice: InvoiceRow,
    houjin: HoujinRow | None,
    *,
    generated_at: str,
) -> dict[str, Any]:
    agreement, grade = compute_agreement(invoice, houjin)
    invoice_status = _infer_invoice_status(invoice)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "name / address 比較は normalised 文字列一致のみ。法人実在性・"
                "支配株主構成・最新通知の最終確認は税理士・弁護士による。"
            ),
        }
    ]
    if houjin is None:
        known_gaps.append(
            {
                "code": "identity_ambiguity_unresolved",
                "description": (
                    "対応する houjin_master row 不在 — sole_proprietor or NTA bulk pending"
                ),
            }
        )
    if invoice_status != "active":
        known_gaps.append(
            {
                "code": "source_receipt_incomplete",
                "description": f"invoice status={invoice_status} — 取引可否要確認",
            }
        )

    sources = [
        {
            "source_url": invoice.source_url or "https://www.invoice-kohyo.nta.go.jp/",
            "source_fetched_at": invoice.last_updated_nta,
            "publisher": "NTA invoice registry",
            "license": "pdl_v1.0",
        }
    ]
    if invoice.houjin_bangou:
        sources.append(
            {
                "source_url": (
                    "https://www.houjin-bangou.nta.go.jp/henkorireki-johoto?id="
                    + str(invoice.houjin_bangou)
                ),
                "source_fetched_at": (houjin.last_updated_nta if houjin is not None else None),
                "publisher": "NTA 法人番号公表サイト",
                "license": "pdl_v1.0",
            }
        )

    package_id = f"invoice_houjin_cross_check_v1:{invoice.invoice_registration_number}"
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
        "subject": {
            "kind": "invoice_registration_number",
            "id": invoice.invoice_registration_number,
        },
        "invoice": {
            "invoice_registration_number": invoice.invoice_registration_number,
            "houjin_bangou": invoice.houjin_bangou,
            "normalized_name": invoice.invoice_name,
            "address_normalized": invoice.invoice_address,
            "prefecture": invoice.invoice_prefecture,
            "registered_date": invoice.registered_date,
            "revoked_date": invoice.revoked_date,
            "expired_date": invoice.expired_date,
            "registrant_kind": invoice.registrant_kind,
            "status": invoice_status,
        },
        "houjin": (
            {
                "houjin_bangou": houjin.houjin_bangou,
                "normalized_name": houjin.normalized_name,
                "address_normalized": houjin.address_normalized,
                "prefecture": houjin.prefecture,
                "corporation_type": houjin.corporation_type,
                "established_date": houjin.established_date,
                "close_date": houjin.close_date,
            }
            if houjin is not None
            else None
        ),
        "agreement": agreement,
        "agreement_grade": grade,
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
        msg = "boto3 is not installed"
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
        for invoice in enumerate_invoices(conn, limit=limit):
            manifest.total_invoices += 1
            houjin = fetch_houjin(conn, invoice.houjin_bangou) if invoice.houjin_bangou else None
            generated_at = _now_utc_iso()
            envelope = render_packet(invoice, houjin, generated_at=generated_at)
            ok, errors = validate_jpcir_header(envelope)
            if not ok:
                logger.warning(
                    "schema validation failed %s: %s",
                    invoice.invoice_registration_number,
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
            grade = str(envelope["agreement_grade"])
            manifest.agreement_grade_counts[grade] = (
                manifest.agreement_grade_counts.get(grade, 0) + 1
            )
            manifest.results.append(
                PacketResult(
                    invoice_registration_number=invoice.invoice_registration_number,
                    s3_key=key,
                    bytes_written=written,
                    agreement_grade=grade,
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
            "Pre-generate invoice_houjin_cross_check_v1 packets for the "
            "13,801 invoice_registrants (plus the 4M-row monthly bulk)."
        ),
    )
    p.add_argument("--output-prefix", required=True)
    p.add_argument("--db", default=DEFAULT_DB_PATH)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--local-out-dir", default="out/invoice_houjin_cross_check_v1")
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
        "run done: invoices=%d written=%d grades=%s bytes_total=%d "
        "s3_put_usd~=%.4f manifest=%s dry_run=%s elapsed=%.1fs",
        manifest.total_invoices,
        manifest.packets_written,
        manifest.agreement_grade_counts,
        manifest.bytes_total,
        manifest.s3_put_cost_usd_estimate,
        manifest_path,
        manifest.dry_run,
        elapsed,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
