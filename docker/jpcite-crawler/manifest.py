"""Manifest writers for jpcite-crawler AWS Batch jobs.

Emits the canonical jpcite contract artifacts defined in
``docs/_internal/aws_credit_data_acquisition_jobs_agent.md`` §1.2 and
``docs/_internal/aws_credit_review_08_artifact_manifest_schema.md`` §4:

    run_manifest.json
    object_manifest.jsonl         (and object_manifest.parquet when pyarrow is available)
    source_receipts.jsonl
    source_profile_delta.jsonl
    known_gaps.jsonl
    quarantine.jsonl

All writers are append-only and JSON-canonical: sorted keys, ``\\n``
separators, no insignificant whitespace. The same row, written twice,
produces the same SHA-256 — required by the artifact_manifest gate (G02
checksum verification).
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

# Stdlib JSON encoder configured for canonical output. Sorted keys and
# compact separators guarantee a stable byte sequence for SHA-256.
_JSON_KWARGS: dict[str, Any] = {
    "ensure_ascii": False,
    "sort_keys": True,
    "separators": (",", ":"),
}


def _utc_now_iso() -> str:
    """RFC 3339 UTC timestamp suitable for source_receipts.last_verified_at."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def canonical_dumps(obj: Mapping[str, Any] | list[Any]) -> str:
    """Canonical JSON encode (sorted keys, compact separators)."""
    return json.dumps(obj, **_JSON_KWARGS)


def sha256_bytes(data: bytes) -> str:
    """Hex SHA-256 of ``data``. Always prefixed with ``sha256:``."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """SHA-256 of UTF-8 encoded text."""
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    """SHA-256 of an on-disk file (streamed in 1 MiB chunks)."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


@dataclass
class JobContext:
    """Per-run context shared by every artifact writer.

    Fields map 1:1 onto the ``run_manifest.json`` envelope and the
    ``provenance`` block on each artifact row.
    """

    run_id: str
    job_id: str
    source_id: str
    output_bucket: str
    output_prefix: str
    container_image_digest: str = ""
    code_ref: str = "git:jpcite-crawler@0.1.0"
    started_at: str = field(default_factory=_utc_now_iso)


class JsonlWriter:
    """Append-only JSONL writer with canonical encoding + row count."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")
        self.row_count: int = 0

    def write(self, row: Mapping[str, Any]) -> None:
        self._fh.write(canonical_dumps(row))
        self._fh.write("\n")
        self.row_count += 1

    def write_many(self, rows: Iterable[Mapping[str, Any]]) -> None:
        for row in rows:
            self.write(row)

    def close(self) -> None:
        try:
            self._fh.flush()
            self._fh.close()
        except Exception:
            pass

    def __enter__(self) -> JsonlWriter:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def write_run_manifest(
    path: Path,
    ctx: JobContext,
    *,
    status: str,
    input_count: int,
    output_count: int,
    failure_count: int,
    accepted_count: int,
    known_gap_count: int,
    stop_reason: str | None = None,
    cost_estimate_usd: float | None = None,
    extras: Mapping[str, Any] | None = None,
) -> None:
    """Emit ``run_manifest.json`` for this job.

    Matches the schema in
    ``aws_credit_review_08_artifact_manifest_schema.md`` §3 with the
    minimal fields each AWS Batch run needs to be traceable + auditable.
    """

    finished_at = _utc_now_iso()
    payload: dict[str, Any] = {
        "schema_id": "jpcite.aws_credit.run_manifest",
        "schema_version": "2026-05-15",
        "run_id": ctx.run_id,
        "job_id": ctx.job_id,
        "source_id": ctx.source_id,
        "project": "jpcite",
        "purpose": "geo_first_artifact_factory",
        "mode": "temporary_aws_credit_run",
        "request_time_llm_call_performed": False,
        "started_at": ctx.started_at,
        "finished_at": finished_at,
        "status": status,
        "input_count": input_count,
        "output_count": output_count,
        "failure_count": failure_count,
        "accepted_count": accepted_count,
        "known_gap_count": known_gap_count,
        "stop_reason": stop_reason,
        "cost_estimate_usd": cost_estimate_usd,
        "output_uri": (
            f"s3://{ctx.output_bucket}/{ctx.output_prefix.rstrip('/')}/"
        ),
        "provenance": {
            "code_ref": ctx.code_ref,
            "container_image_digest": ctx.container_image_digest,
        },
    }
    if extras:
        payload["extras"] = dict(extras)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_dumps(payload) + "\n", encoding="utf-8")


def build_object_manifest_row(
    *,
    artifact_id: str,
    ctx: JobContext,
    artifact_kind: str,
    s3_uri: str,
    format_: str,
    record_count: int,
    byte_size: int,
    sha256: str,
    license_boundary: str,
    retention_class: str = "repo_candidate_public",
    privacy_class: str = "public_safe",
    data_class: str = "public_official",
    terms_status: str = "verified",
    repo_import_decision: str = "candidate",
    quality_gate_status: str = "pass",
    blocking_issue_count: int = 0,
    warning_count: int = 0,
    extras: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct one ``artifact_manifest.jsonl`` row (review_08 §4)."""

    row: dict[str, Any] = {
        "schema_id": "jpcite.aws_credit.artifact_manifest",
        "schema_version": "2026-05-15",
        "artifact_id": artifact_id,
        "run_id": ctx.run_id,
        "job_id": ctx.job_id,
        "source_id": ctx.source_id,
        "artifact_kind": artifact_kind,
        "data_class": data_class,
        "privacy_class": privacy_class,
        "license_boundary": license_boundary,
        "terms_status": terms_status,
        "retention_class": retention_class,
        "s3_uri": s3_uri,
        "format": format_,
        "record_count": record_count,
        "byte_size": byte_size,
        "checksums": {"sha256": sha256},
        "provenance": {
            "code_ref": ctx.code_ref,
            "container_image_digest": ctx.container_image_digest,
            "created_at": _utc_now_iso(),
        },
        "quality": {
            "gate_status": quality_gate_status,
            "blocking_issue_count": blocking_issue_count,
            "warning_count": warning_count,
        },
        "repo_import": {
            "decision": repo_import_decision,
            "public_publish_allowed": False,
            "requires_human_review": True,
        },
    }
    if extras:
        row["extras"] = dict(extras)
    return row


def build_source_receipt_row(
    *,
    ctx: JobContext,
    receipt_id: str,
    source_url: str,
    content_hash: str,
    license_boundary: str,
    freshness_bucket: str = "within_7d",
    receipt_kind: str = "positive_source",
    support_level: str = "direct",
    used_in: list[str] | None = None,
    claim_refs: list[str] | None = None,
    known_gaps: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Construct one ``source_receipts.jsonl`` row (review_08 §6.3)."""

    now = _utc_now_iso()
    return {
        "source_receipt_id": receipt_id,
        "receipt_kind": receipt_kind,
        "source_id": ctx.source_id,
        "source_url": source_url,
        "source_fetched_at": now,
        "last_verified_at": now,
        "content_hash": content_hash,
        "source_checksum": content_hash,
        "corpus_snapshot_id": f"corpus-{time.strftime('%Y-%m-%d', time.gmtime())}",
        "license_boundary": license_boundary,
        "terms_status": "verified",
        "freshness_bucket": freshness_bucket,
        "verification_status": "verified",
        "support_level": support_level,
        "retrieval_method": "http_get",
        "used_in": list(used_in or []),
        "claim_refs": list(claim_refs or []),
        "known_gaps": list(known_gaps or []),
    }


def build_known_gap_row(
    *,
    gap_id: str,
    severity: str = "review",
    scope: str = "source",
    affected_records: list[str] | None = None,
    source_receipt_ids: list[str] | None = None,
    message: str = "",
    agent_instruction: str = "",
    human_followup: str = "",
    blocks_final_answer: bool = False,
) -> dict[str, Any]:
    """Construct one ``known_gaps.jsonl`` row (review_08 §6.6).

    Canonical gap enum lives in the source-of-truth doc; this helper does
    not validate the enum so new jobs can experiment, but downstream
    G12/G14 gates will reject unknown codes.
    """

    return {
        "gap_id": gap_id,
        "severity": severity,
        "scope": scope,
        "affected_records": list(affected_records or []),
        "source_receipt_ids": list(source_receipt_ids or []),
        "message": message,
        "agent_instruction": agent_instruction,
        "human_followup": human_followup,
        "blocks_final_answer": blocks_final_answer,
    }


def maybe_write_object_manifest_parquet(
    jsonl_path: Path,
    parquet_path: Path,
) -> bool:
    """Convert ``object_manifest.jsonl`` to parquet when pyarrow is present.

    Returns True on success, False if pyarrow is missing or the JSONL
    is empty. Failure is non-fatal: the JSONL row is always emitted and
    pyarrow is only an optimization for downstream Athena/Glue jobs.
    """

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except Exception:
        return False

    if not jsonl_path.exists() or jsonl_path.stat().st_size == 0:
        return False

    rows: list[dict[str, Any]] = []
    with jsonl_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not rows:
        return False

    # pyarrow infers the schema. For stable downstream Athena queries the
    # caller can pin an explicit schema in a future revision.
    table = pa.Table.from_pylist(rows)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(parquet_path), compression="snappy")  # type: ignore[no-untyped-call]
    return True
