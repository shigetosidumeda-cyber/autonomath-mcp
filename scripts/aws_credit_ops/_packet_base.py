"""Shared utilities for Wave 53.2 packet generators.

Pure helpers — NO LLM, NO network side effects. Used by the 11 packet
generators landed under ``scripts/aws_credit_ops/`` for Wave 53.2:

* JPCIR envelope assembly (``jpcir_envelope``)
* JPCIR header validation (``validate_jpcir_header``)
* Known-gap enum (``KNOWN_GAP_CODES``)
* Read-only SQLite open (``open_db_ro``)
* Local / S3 upload (``upload_packet``)
* boto3 lazy import (``import_boto3``)

``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

SCHEMA_VERSION: Final[str] = "jpcir.p0.v1"
PRODUCER: Final[str] = "jpcite-ai-execution-control-plane"
MAX_PACKET_BYTES: Final[int] = 25 * 1024
S3_PUT_USD_PER_1K: Final[float] = 0.005

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


def now_utc_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def jpcir_envelope(
    *,
    package_kind: str,
    package_id: str,
    cohort_definition: dict[str, Any],
    metrics: dict[str, Any],
    body: dict[str, Any],
    sources: list[dict[str, Any]],
    known_gaps: list[dict[str, str]],
    disclaimer: str,
    generated_at: str,
) -> dict[str, Any]:
    """Build a JPCIR p0.v1 envelope.

    ``body`` is merged into the top level — caller controls naming, but the
    JPCIR header keys (``object_id``, ``object_type``, ``producer``,
    ``request_time_llm_call_performed``, ``schema_version``) are always set
    by this helper and cannot be overridden by ``body``.
    """

    envelope: dict[str, Any] = dict(body)
    envelope.update(
        {
            "object_id": package_id,
            "object_type": "packet",
            "created_at": generated_at,
            "producer": PRODUCER,
            "request_time_llm_call_performed": False,
            "schema_version": SCHEMA_VERSION,
            "package_id": package_id,
            "package_kind": package_kind,
            "generated_at": generated_at,
            "cohort_definition": cohort_definition,
            "metrics": metrics,
            "sources": sources,
            "known_gaps": known_gaps,
            "jpcite_cost_jpy": 0,
            "disclaimer": disclaimer,
        }
    )
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
    known_gaps = envelope.get("known_gaps")
    if not isinstance(known_gaps, list) or not known_gaps:
        errors.append("known_gaps must be a non-empty list")
    else:
        for entry in known_gaps:
            if not isinstance(entry, dict):
                errors.append("known_gaps entry must be a dict")
                continue
            code = entry.get("code")
            if not isinstance(code, str) or code not in KNOWN_GAP_CODES:
                errors.append(f"known_gaps code unknown: {code!r}")
    return (not errors, errors)


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


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def import_boto3() -> Any:  # pragma: no cover
    try:
        import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError as exc:
        msg = "boto3 is not installed."
        raise RuntimeError(msg) from exc
    return boto3


def parse_s3_uri(uri: str) -> tuple[str, str]:
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
    packet_id: str,
) -> tuple[str, int]:
    body = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    bytes_written = len(body)
    if bytes_written > MAX_PACKET_BYTES:
        msg = f"packet {packet_id} exceeds {MAX_PACKET_BYTES}: {bytes_written}"
        raise ValueError(msg)
    if output_prefix.startswith("s3://"):
        bucket, key_prefix = parse_s3_uri(output_prefix)
        key = f"{key_prefix.rstrip('/')}/{packet_id}.json"
        if dry_run or s3_client is None:
            local_path = local_out_dir / f"{packet_id}.json"
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(body)
            return key, bytes_written
        s3_client.put_object(
            Bucket=bucket, Key=key, Body=body, ContentType="application/json"
        )
        return key, bytes_written
    local_path = Path(output_prefix).expanduser() / f"{packet_id}.json"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(body)
    return str(local_path), bytes_written


def normalise_token(value: str | None, fallback: str = "UNKNOWN") -> str:
    if value is None:
        return fallback
    stripped = str(value).strip()
    return stripped or fallback


def safe_packet_id_segment(value: str) -> str:
    """Filesystem-safe segment for packet IDs."""

    keep = []
    for ch in str(value):
        if ch.isalnum() or ch in {"-", "_", "."}:
            keep.append(ch)
        else:
            keep.append("_")
    out = "".join(keep)
    return out[:120] if len(out) > 120 else out
