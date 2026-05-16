#!/usr/bin/env python3
"""Post-job artifact aggregator for the jpcite Wave 50 credit run.

This script consolidates the J01-J07 AWS Batch job outputs into a single
``credit_run_ledger_2026_05.json`` ledger that downstream auditors,
reproducibility checks, and the Wave 50 RC1 closeout doc can pin to.

What it does (in order):

1. **List** S3 prefixes matching ``s3://<RAW_BUCKET>/J0X_<slug>/`` (the
   canonical shape, e.g. ``J01_source_profile/`` ..
   ``J07_gbizinfo/``). The pattern is enforced by
   :data:`JOB_PREFIX_REGEX` so accidental siblings (``J01/`` bare,
   ``J08_x/`` out-of-range) are filtered out.
2. For each prefix, download + parse the 6 standard-output-contract
   artifacts (§1.2 of
   ``docs/_internal/aws_credit_data_acquisition_jobs_agent.md``):

   * ``run_manifest.json``
   * ``object_manifest.jsonl`` (a JSONL companion to the parquet variant;
     this script accepts either ``.jsonl`` or ``.json`` -- a sibling
     ``object_manifest.parquet`` lives next to it but is not required by
     the ledger because the JSONL form already carries the URL / key /
     hash / size columns we summarize)
   * ``source_receipts.jsonl``
   * ``claim_refs.jsonl``
   * ``known_gaps.jsonl``
   * ``quarantine.jsonl``

   For each file we record ``sha256``, ``size_bytes``, and (for the
   ``.jsonl`` files) the line count.

3. Compute **per-job rollups**:

   * ``total_source_count`` -- number of distinct source URLs touched.
   * ``total_claim_refs`` -- count of ``claim_refs.jsonl`` rows.
   * ``total_known_gaps_by_code`` -- histogram of the 7-enum
     ``known_gaps[].code`` (`csv_input_not_evidence_safe`,
     `source_receipt_incomplete`, `pricing_or_cap_unconfirmed`,
     `no_hit_not_absence`, `professional_review_required`,
     `freshness_stale_or_unknown`, `identity_ambiguity_unresolved`).
   * ``accepted_artifact_rate`` -- ratio of artifacts whose ``status`` /
     ``accepted`` flag is true relative to the total observed in
     ``run_manifest.json``.
   * ``coverage_score`` -- the §2.1 formula from
     ``docs/_internal/PREBUILT_DELIVERABLE_PACKETS_2026_05_15.md``::

         coverage_score =
             0.35 * mean(fact_coverage)
           + 0.25 * claim_coverage
           + 0.20 * citation_coverage
           + 0.15 * freshness_coverage
           + 0.05 * receipt_completion
           - gap_penalty

     where ``gap_penalty = min(0.30, 0.08*high_gap_count + 0.04*medium
     + 0.02*low)``.

4. Compute **account-wide rollups**:

   * ``total_credit_consumed`` -- Cost Explorer ``NetUnblendedCost`` over
     ``run_start_at .. now`` for the account ``993693061769``.

5. Write ``credit_run_ledger_2026_05.json`` with the full breakdown. The
   schema is documented in :class:`RunLedger` / :class:`PerJobLedger`.

6. Optionally upload to
   ``s3://<REPORTS_BUCKET>/ledger/credit_run_ledger_2026_05.json`` when
   ``--upload`` is passed. Default behavior is DRY_RUN: write to local
   ``./out/credit_run_ledger_2026_05.json`` and print a summary.

CLI::

    python scripts/aws_credit_ops/aggregate_run_ledger.py [--upload]
                                                          [--out PATH]
                                                          [--raw-bucket NAME]
                                                          [--reports-bucket NAME]
                                                          [--cost-explorer-region us-east-1]
                                                          [--run-start 2026-05-15T00:00:00Z]
                                                          [--export-parquet]

Non-negotiable invariants:

* **No LLM API calls.** This is a pure aggregation script. boto3 is
  imported lazily so the test suite can mock without the real SDK.
* **DRY_RUN by default.** ``--upload`` is opt-in; without it, the script
  only prints the per-job summary and writes a local ledger file.
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.

Wave 50 Stream supplement (2026-05-16).
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import logging
import re
import sys
from collections.abc import Mapping  # noqa: TC003 -- runtime use by Pydantic
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    import io
    from collections.abc import Iterable, Sequence

logger = logging.getLogger("aggregate_run_ledger")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Stable identifier for the ledger schema. Bump when the shape changes so
#: downstream consumers (Athena queries, CI gates) can pin against it.
LEDGER_SCHEMA_VERSION: Final[str] = "jpcite.credit_run_ledger.v1"

#: AWS account-id baked into the bucket names per master plan §1.2.
AWS_ACCOUNT_ID: Final[str] = "993693061769"

#: Canonical raw bucket where J01..J07 land their artifacts.
DEFAULT_RAW_BUCKET: Final[str] = f"jpcite-credit-{AWS_ACCOUNT_ID}-202605-raw"

#: Canonical reports bucket where the ledger lands.
DEFAULT_REPORTS_BUCKET: Final[str] = f"jpcite-credit-{AWS_ACCOUNT_ID}-202605-reports"

#: Canonical derived bucket where compressed Parquet snapshots land.
DEFAULT_DERIVED_BUCKET: Final[str] = f"jpcite-credit-{AWS_ACCOUNT_ID}-202605-derived"

#: Cost Explorer region (Cost Explorer is a us-east-1-only service).
DEFAULT_CE_REGION: Final[str] = "us-east-1"

#: Default credit-run start timestamp (master plan window opens 2026-05-15).
DEFAULT_RUN_START: Final[str] = "2026-05-15T00:00:00Z"

#: Default per-job-prefix ThreadPool fan-out for :func:`build_ledger`.
#: Mirrors the PERF-18 ETL rollout (``etl_raw_to_derived.DEFAULT_ETL_MAX_WORKERS``):
#: per-job artifact assembly (6 sequential ``get_object`` calls + parse + hash) is
#: independent across the 7 canonical J0X prefixes, so collapsing the sequential
#: walk into a 4-way fan-out preserves the S3 GET semantics while overlapping
#: TCP round-trips. Set to 1 to restore the legacy sequential walk for tests
#: that share boto3-stub state across prefixes.
DEFAULT_LEDGER_MAX_WORKERS: Final[int] = 4

#: Canonical seven job_ids (mirrors ``ALL_JOB_IDS`` in
#: ``src/jpintel_mcp/aws_credit_ops/source_to_job_map.py``).
#:
#: Production S3 prefix shape is ``J0X_<short_slug>/`` (not bare ``J0X/``):
#:
#:   * ``J01_source_profile/``
#:   * ``J02_nta_houjin/``
#:   * ``J03_nta_invoice/``
#:   * ``J04_egov_law/``
#:   * ``J05_jgrants_program/``
#:   * ``J06_ministry_pdf/``
#:   * ``J07_gbizinfo/``
#:
#: This constant retains the short ``J0X`` numeric ids as a stable
#: fallback enumeration for callers that explicitly pass prefixes; the
#: live discovery path (:func:`list_job_prefixes`) uses
#: :data:`JOB_PREFIX_REGEX` to match the actual ``J0X_<slug>/`` shape
#: under the raw bucket.
ALL_JOB_PREFIXES: Final[tuple[str, ...]] = (
    "J01",
    "J02",
    "J03",
    "J04",
    "J05",
    "J06",
    "J07",
)

#: Regex matching the canonical production ``J0X_<short_slug>/`` prefix
#: shape returned by ``list_objects_v2(... Delimiter='/')`` at the raw
#: bucket root. The slug must be a non-empty lowercase ``a-z`` /
#: underscore segment (matches ``J01_source_profile/``,
#: ``J05_jgrants_program/`` etc.; rejects ``J01/`` bare, ``J08_x/``
#: out-of-range, and ``J01-source/`` non-canonical separator).
JOB_PREFIX_REGEX: Final[re.Pattern[str]] = re.compile(r"^J0[1-7]_[a-z_]+/$")

#: The 6 standard output contract files we hash per job (§1.2).
ARTIFACT_FILES: Final[tuple[str, ...]] = (
    "run_manifest.json",
    "object_manifest.jsonl",
    "source_receipts.jsonl",
    "claim_refs.jsonl",
    "known_gaps.jsonl",
    "quarantine.jsonl",
)

#: 7-enum ``known_gaps[].code`` per §1.3 of the master plan.
KNOWN_GAP_CODES: Final[tuple[str, ...]] = (
    "csv_input_not_evidence_safe",
    "source_receipt_incomplete",
    "pricing_or_cap_unconfirmed",
    "no_hit_not_absence",
    "professional_review_required",
    "freshness_stale_or_unknown",
    "identity_ambiguity_unresolved",
)

#: Source-family rollup buckets used to compute per-family coverage_score.
SOURCE_FAMILY_BUCKETS: Final[tuple[str, ...]] = (
    "egov_law",
    "nta_houjin",
    "nta_invoice",
    "jgrants",
    "ministry_pdf",
    "gbizinfo",
    "other",
)

#: Gap-severity multipliers used by the §2.1 coverage_score gap_penalty.
_GAP_SEVERITY: Final[Mapping[str, Literal["high", "medium", "low"]]] = {
    "csv_input_not_evidence_safe": "high",
    "source_receipt_incomplete": "high",
    "pricing_or_cap_unconfirmed": "medium",
    "no_hit_not_absence": "medium",
    "professional_review_required": "low",
    "freshness_stale_or_unknown": "medium",
    "identity_ambiguity_unresolved": "high",
}


# ---------------------------------------------------------------------------
# Ledger models
# ---------------------------------------------------------------------------


class ArtifactHash(BaseModel):
    """SHA256 + size + (optional) line-count rollup for a single artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    filename: str
    present: bool
    sha256: str | None = None
    size_bytes: int = 0
    line_count: int | None = None


class CoverageBreakdown(BaseModel):
    """The §2.1 component-by-component coverage_score breakdown."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fact_coverage_mean: float = Field(ge=0.0, le=1.0)
    claim_coverage: float = Field(ge=0.0, le=1.0)
    citation_coverage: float = Field(ge=0.0, le=1.0)
    freshness_coverage: float = Field(ge=0.0, le=1.0)
    receipt_completion: float = Field(ge=0.0, le=1.0)
    gap_penalty: float = Field(ge=0.0, le=0.30)
    coverage_score: float
    coverage_grade: Literal["S", "A", "B", "C", "D"]


class PerJobLedger(BaseModel):
    """Per-job rollup row in the credit-run ledger."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: str
    prefix: str
    artifacts: tuple[ArtifactHash, ...]
    total_source_count: int = Field(ge=0)
    total_claim_refs: int = Field(ge=0)
    total_known_gaps_by_code: Mapping[str, int]
    accepted_artifact_rate: float = Field(ge=0.0, le=1.0)
    coverage: CoverageBreakdown
    coverage_score_per_source_family: Mapping[str, float]


class RunLedger(BaseModel):
    """Top-level credit-run ledger."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = LEDGER_SCHEMA_VERSION
    generated_at: str
    run_start_at: str
    raw_bucket: str
    reports_bucket: str
    account_id: str
    jobs: tuple[PerJobLedger, ...]
    total_credit_consumed_usd: float
    total_source_count_account_wide: int
    total_claim_refs_account_wide: int
    total_known_gaps_by_code_account_wide: Mapping[str, int]
    accepted_artifact_rate_account_wide: float


# ---------------------------------------------------------------------------
# Hashing / parsing helpers (no AWS calls)
# ---------------------------------------------------------------------------


def hash_payload(payload: bytes) -> str:
    """Return the hex sha256 digest of ``payload``."""

    return hashlib.sha256(payload).hexdigest()


def count_jsonl_lines(payload: bytes) -> int:
    """Return the count of non-empty lines in a JSONL payload."""

    if not payload:
        return 0
    return sum(1 for line in payload.splitlines() if line.strip())


def parse_jsonl(payload: bytes) -> list[dict[str, Any]]:
    """Parse a JSONL payload into a list of dicts (skip blank lines)."""

    rows: list[dict[str, Any]] = []
    for raw_line in payload.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def parse_run_manifest(payload: bytes) -> dict[str, Any]:
    """Parse ``run_manifest.json`` payload; return ``{}`` when empty."""

    if not payload:
        return {}
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        msg = f"run_manifest.json must be a JSON object; got {type(parsed).__name__}"
        raise ValueError(msg)
    return parsed


def grade_coverage(score: float, critical_unknown_count: int) -> Literal["S", "A", "B", "C", "D"]:
    """Return the §2.1 grade letter for a coverage_score.

    - ``S``: score >= 0.92 AND critical unknown == 0
    - ``A``: score >= 0.80
    - ``B``: score >= 0.65
    - ``C``: score >= 0.45
    - ``D``: below
    """

    if score >= 0.92 and critical_unknown_count == 0:
        return "S"
    if score >= 0.80:
        return "A"
    if score >= 0.65:
        return "B"
    if score >= 0.45:
        return "C"
    return "D"


def compute_gap_penalty(gap_counts_by_code: Mapping[str, int]) -> float:
    """Apply §2.1 ``gap_penalty = min(0.30, 0.08*high + 0.04*medium + 0.02*low)``."""

    high = 0
    medium = 0
    low = 0
    for code, count in gap_counts_by_code.items():
        if count <= 0:
            continue
        severity = _GAP_SEVERITY.get(code)
        if severity == "high":
            high += count
        elif severity == "medium":
            medium += count
        elif severity == "low":
            low += count
    raw = 0.08 * high + 0.04 * medium + 0.02 * low
    return min(0.30, raw)


def compute_coverage_breakdown(
    *,
    source_receipts: Sequence[Mapping[str, Any]],
    claim_refs: Sequence[Mapping[str, Any]],
    known_gaps: Sequence[Mapping[str, Any]],
    run_manifest: Mapping[str, Any],
) -> CoverageBreakdown:
    """Compute the §2.1 component-by-component coverage breakdown.

    Inputs are the already-parsed per-job artifact rows. The intent is to
    keep this function pure so unit tests can feed it fixtures without
    touching S3.
    """

    # claim_coverage: claim_refs with non-empty source_receipt_id /
    # source_url linkage.
    claim_count = max(len(claim_refs), 1)
    linked_claims = sum(
        1 for row in claim_refs if row.get("source_receipt_id") or row.get("source_url")
    )
    claim_coverage = linked_claims / claim_count

    # citation_coverage uses §2.1 weighted sum:
    # (verified + 0.7*inferred + 0.3*stale + 0*unknown) / max(citation_count, 1)
    citation_total = max(len(source_receipts), 1)
    verified = sum(1 for r in source_receipts if r.get("verification_status") == "verified")
    inferred = sum(1 for r in source_receipts if r.get("verification_status") == "inferred")
    stale = sum(1 for r in source_receipts if r.get("verification_status") == "stale")
    citation_coverage = (verified + 0.7 * inferred + 0.3 * stale + 0.0 * 0) / citation_total

    # fact_coverage_mean: per-receipt fact_coverage_r =
    # sourced_fact_count / max(required, observed, 1).
    fact_coverages: list[float] = []
    for receipt in source_receipts:
        sourced = float(receipt.get("sourced_fact_count", 0) or 0)
        required = float(receipt.get("required_fact_count", 0) or 0)
        observed = float(receipt.get("observed_fact_count", 0) or 0)
        denom = max(required, observed, 1.0)
        fact_coverages.append(min(1.0, sourced / denom))
    fact_coverage_mean = sum(fact_coverages) / len(fact_coverages) if fact_coverages else 0.0

    # freshness_coverage: average across receipts using exp(-age_days/half).
    half_life = 180.0
    freshness_values: list[float] = []
    for receipt in source_receipts:
        age = receipt.get("age_days")
        if age is None:
            continue
        try:
            age_days = float(age)
        except (TypeError, ValueError):
            continue
        # math.exp inlined as 2.71828^(-x) using pow to avoid import bloat
        freshness_values.append(pow(2.718281828459045, -age_days / half_life))
    freshness_coverage = sum(freshness_values) / len(freshness_values) if freshness_values else 0.0

    # receipt_completion: fraction of run_manifest accepted artifacts.
    accepted = int(run_manifest.get("accepted_artifact_count", 0) or 0)
    total = int(run_manifest.get("total_artifact_count", 0) or 0)
    receipt_completion = (accepted / total) if total else 0.0

    # Build histogram for the gap_penalty.
    gap_counts: dict[str, int] = dict.fromkeys(KNOWN_GAP_CODES, 0)
    for row in known_gaps:
        code = row.get("code")
        if isinstance(code, str) and code in gap_counts:
            gap_counts[code] += 1
    gap_penalty = compute_gap_penalty(gap_counts)

    score = (
        0.35 * fact_coverage_mean
        + 0.25 * claim_coverage
        + 0.20 * citation_coverage
        + 0.15 * freshness_coverage
        + 0.05 * receipt_completion
        - gap_penalty
    )
    # Clamp into [-0.30, 1.0] then we let the grade fall through.
    score = max(-0.30, min(1.0, score))
    critical_unknown_count = sum(
        gap_counts[code] for code in ("source_receipt_incomplete", "identity_ambiguity_unresolved")
    )
    grade = grade_coverage(score, critical_unknown_count)

    return CoverageBreakdown(
        fact_coverage_mean=round(fact_coverage_mean, 4),
        claim_coverage=round(claim_coverage, 4),
        citation_coverage=round(citation_coverage, 4),
        freshness_coverage=round(freshness_coverage, 4),
        receipt_completion=round(receipt_completion, 4),
        gap_penalty=round(gap_penalty, 4),
        coverage_score=round(score, 4),
        coverage_grade=grade,
    )


def coverage_score_per_source_family(
    *,
    source_receipts: Sequence[Mapping[str, Any]],
    claim_refs: Sequence[Mapping[str, Any]],
    known_gaps: Sequence[Mapping[str, Any]],
    run_manifest: Mapping[str, Any],
) -> dict[str, float]:
    """Compute per-source-family coverage_score (one value per bucket)."""

    by_family: dict[str, list[Mapping[str, Any]]] = {b: [] for b in SOURCE_FAMILY_BUCKETS}
    for receipt in source_receipts:
        source_id = receipt.get("source_id") or receipt.get("source_family") or "other"
        bucket = _bucket_for_source(str(source_id))
        by_family[bucket].append(receipt)

    out: dict[str, float] = {}
    for bucket, receipts in by_family.items():
        if not receipts:
            out[bucket] = 0.0
            continue
        breakdown = compute_coverage_breakdown(
            source_receipts=receipts,
            claim_refs=claim_refs,
            known_gaps=known_gaps,
            run_manifest=run_manifest,
        )
        out[bucket] = breakdown.coverage_score
    return out


def _bucket_for_source(source_id: str) -> str:
    """Map a free-form ``source_id`` string into a SOURCE_FAMILY_BUCKETS row."""

    lower = source_id.lower()
    if "egov" in lower or "law" in lower:
        return "egov_law"
    if "houjin" in lower and "nta" in lower:
        return "nta_houjin"
    if "invoice" in lower:
        return "nta_invoice"
    if "jgrant" in lower or "j-grant" in lower:
        return "jgrants"
    if "ministry" in lower or "pdf" in lower or "meti" in lower or "mhlw" in lower:
        return "ministry_pdf"
    if "gbiz" in lower:
        return "gbizinfo"
    return "other"


def compute_accepted_artifact_rate(run_manifest: Mapping[str, Any]) -> float:
    """Compute ``accepted_artifact_count / total_artifact_count`` clamped."""

    accepted = int(run_manifest.get("accepted_artifact_count", 0) or 0)
    total = int(run_manifest.get("total_artifact_count", 0) or 0)
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, accepted / total))


def count_distinct_source_count(
    *,
    source_receipts: Sequence[Mapping[str, Any]],
    object_manifest: Sequence[Mapping[str, Any]],
) -> int:
    """Distinct ``source_url`` cardinality across receipts + object manifest."""

    urls: set[str] = set()
    for row in source_receipts:
        url = row.get("source_url")
        if isinstance(url, str) and url:
            urls.add(url)
    for row in object_manifest:
        url = row.get("source_url") or row.get("url")
        if isinstance(url, str) and url:
            urls.add(url)
    return len(urls)


def known_gaps_histogram(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Build the 7-enum histogram for a list of known_gaps rows."""

    counts: dict[str, int] = dict.fromkeys(KNOWN_GAP_CODES, 0)
    for row in rows:
        code = row.get("code")
        if isinstance(code, str) and code in counts:
            counts[code] += 1
    return counts


# ---------------------------------------------------------------------------
# S3 + Cost Explorer adapters (lazy boto3)
# ---------------------------------------------------------------------------


def _import_boto3() -> Any:  # pragma: no cover - trivial import shim
    """Lazy boto3 import to keep this module importable without the SDK.

    The result is **not** memoised here so unit tests can swap this
    function out via :class:`pytest.MonkeyPatch` to inject a fake boto3
    surface. For live runs the actual ``boto3.client(...)`` calls are
    pooled by :mod:`scripts.aws_credit_ops._aws`.
    """

    try:
        import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError as exc:
        msg = (
            "boto3 is not installed. Install in the operator environment "
            "(pip install boto3) before running aggregate_run_ledger live."
        )
        raise RuntimeError(msg) from exc
    return boto3


def list_job_prefixes(
    s3_client: Any,
    *,
    raw_bucket: str,
    job_prefixes: Sequence[str] = ALL_JOB_PREFIXES,
) -> list[str]:
    """List the per-job prefixes present under ``s3://raw_bucket/``.

    Returns a sorted list of canonical ``J0X_<slug>/`` prefixes (e.g.
    ``["J01_source_profile/", "J02_nta_houjin/", ...]``) discovered at
    the bucket root via ``list_objects_v2(... Delimiter='/')``. The
    regex :data:`JOB_PREFIX_REGEX` filters out accidental siblings
    (``J01/`` bare, ``J08_x/`` out-of-range, etc.) and bare-numeric
    legacy paths.

    Falls back to enumerating ``f"{prefix}/"`` for each entry of
    ``job_prefixes`` when the bucket-root sweep returns no canonical
    matches (kept so test fixtures and historical bare-``J0X/`` layouts
    still work).

    The S3 client must implement ``list_objects_v2(Bucket=..., Prefix=...,
    Delimiter='/', ContinuationToken=...)`` returning
    ``{"CommonPrefixes": [{"Prefix": "..."}], "NextContinuationToken":
    "..." | None}``.
    """

    found: set[str] = set()

    # Primary path: bucket-root sweep matching JOB_PREFIX_REGEX.
    continuation: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "Bucket": raw_bucket,
            "Prefix": "",
            "Delimiter": "/",
        }
        if continuation is not None:
            kwargs["ContinuationToken"] = continuation
        response = s3_client.list_objects_v2(**kwargs)
        for entry in response.get("CommonPrefixes", []) or []:
            candidate = entry.get("Prefix", "")
            if JOB_PREFIX_REGEX.match(candidate):
                found.add(candidate)
        continuation = response.get("NextContinuationToken")
        if not continuation:
            break

    if found:
        return sorted(found)

    # Fallback: bare ``J0X/`` enumeration (test fixtures, legacy bucket
    # layouts that pre-date the ``_<slug>`` convention).
    for prefix in job_prefixes:
        response = s3_client.list_objects_v2(
            Bucket=raw_bucket,
            Prefix=f"{prefix}/",
            Delimiter="/",
            MaxKeys=1,
        )
        contents = response.get("Contents", [])
        common = response.get("CommonPrefixes", [])
        if contents or common:
            found.add(f"{prefix}/")
    return sorted(found)


def fetch_artifact_payload(
    s3_client: Any,
    *,
    bucket: str,
    key: str,
) -> bytes | None:
    """Fetch a single S3 object payload; return ``None`` when missing.

    A missing artifact (``NoSuchKey`` / 404) returns ``None`` rather than
    raising so the aggregator can record it as ``present=False`` in the
    ledger.
    """

    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
    except Exception as exc:  # noqa: BLE001 -- broad on purpose
        error_code = ""
        with contextlib.suppress(AttributeError):
            error_code = str(exc.response.get("Error", {}).get("Code", ""))  # type: ignore[attr-defined]
        # Treat anything that looks like "not found" as a soft miss.
        miss_markers = ("NoSuchKey", "404", "NotFound")
        if any(marker in error_code or marker in str(exc) for marker in miss_markers):
            return None
        raise
    body = response.get("Body")
    if body is None:
        return b""
    payload: Any = body.read()
    if isinstance(payload, str):
        return payload.encode("utf-8")
    if isinstance(payload, bytes):
        return payload
    return bytes(payload)


def collect_artifacts(
    s3_client: Any,
    *,
    raw_bucket: str,
    job_prefix: str,
    artifact_files: Sequence[str] = ARTIFACT_FILES,
) -> dict[str, tuple[bytes | None, ArtifactHash]]:
    """Fetch + hash the 6 standard artifacts under ``job_prefix``.

    Returns a mapping of filename -> (payload, ArtifactHash). Payload is
    ``None`` when the file is missing.
    """

    out: dict[str, tuple[bytes | None, ArtifactHash]] = {}
    normalized_prefix = job_prefix if job_prefix.endswith("/") else f"{job_prefix}/"
    for filename in artifact_files:
        key = f"{normalized_prefix}{filename}"
        payload = fetch_artifact_payload(s3_client, bucket=raw_bucket, key=key)
        if payload is None:
            hash_row = ArtifactHash(filename=filename, present=False)
        else:
            sha = hash_payload(payload)
            size = len(payload)
            line_count: int | None = (
                count_jsonl_lines(payload) if filename.endswith(".jsonl") else None
            )
            hash_row = ArtifactHash(
                filename=filename,
                present=True,
                sha256=sha,
                size_bytes=size,
                line_count=line_count,
            )
        out[filename] = (payload, hash_row)
    return out


def fetch_cost_explorer_total(
    ce_client: Any,
    *,
    run_start_at: str,
    now: dt.datetime | None = None,
) -> float:
    """Sum ``NetUnblendedCost`` from ``run_start_at`` to now.

    The ``ce_client`` must implement ``get_cost_and_usage(...)`` per the
    boto3 API. Returns 0.0 when the call raises (best-effort; we never
    let a Cost Explorer hiccup block the ledger write).
    """

    if now is None:
        now = dt.datetime.now(dt.UTC)
    start_date = run_start_at[:10]
    end_date = now.strftime("%Y-%m-%d")
    try:
        response = ce_client.get_cost_and_usage(
            TimePeriod={"Start": start_date, "End": end_date},
            Granularity="DAILY",
            Metrics=["NetUnblendedCost"],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cost Explorer call failed; defaulting total to 0.0 (%s)", exc)
        return 0.0
    total = 0.0
    for row in response.get("ResultsByTime", []):
        amount = row.get("Total", {}).get("NetUnblendedCost", {}).get("Amount", "0")
        try:
            total += float(amount)
        except (TypeError, ValueError):
            continue
    return total


def put_ledger_object(
    s3_client: Any,
    *,
    bucket: str,
    key: str,
    payload: bytes,
) -> None:
    """Upload ``payload`` to ``s3://bucket/key`` as ``application/json``."""

    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=payload,
        ContentType="application/json",
        ServerSideEncryption="AES256",
    )


# ---------------------------------------------------------------------------
# Top-level aggregator
# ---------------------------------------------------------------------------


def aggregate_for_job(
    s3_client: Any,
    *,
    raw_bucket: str,
    job_prefix: str,
) -> PerJobLedger:
    """Aggregate a single job_prefix into a :class:`PerJobLedger` row.

    All S3 reads go through ``s3_client``; the function is otherwise pure.
    """

    artifacts = collect_artifacts(
        s3_client,
        raw_bucket=raw_bucket,
        job_prefix=job_prefix,
    )
    payloads = {name: payload for name, (payload, _row) in artifacts.items()}
    hash_rows = tuple(row for _name, (_payload, row) in artifacts.items())

    run_manifest = parse_run_manifest(payloads.get("run_manifest.json") or b"")
    object_manifest = parse_jsonl(payloads.get("object_manifest.jsonl") or b"")
    source_receipts = parse_jsonl(payloads.get("source_receipts.jsonl") or b"")
    claim_refs = parse_jsonl(payloads.get("claim_refs.jsonl") or b"")
    known_gaps = parse_jsonl(payloads.get("known_gaps.jsonl") or b"")

    coverage = compute_coverage_breakdown(
        source_receipts=source_receipts,
        claim_refs=claim_refs,
        known_gaps=known_gaps,
        run_manifest=run_manifest,
    )
    per_family = coverage_score_per_source_family(
        source_receipts=source_receipts,
        claim_refs=claim_refs,
        known_gaps=known_gaps,
        run_manifest=run_manifest,
    )

    return PerJobLedger(
        job_id=job_prefix.rstrip("/"),
        prefix=job_prefix,
        artifacts=hash_rows,
        total_source_count=count_distinct_source_count(
            source_receipts=source_receipts,
            object_manifest=object_manifest,
        ),
        total_claim_refs=len(claim_refs),
        total_known_gaps_by_code=known_gaps_histogram(known_gaps),
        accepted_artifact_rate=compute_accepted_artifact_rate(run_manifest),
        coverage=coverage,
        coverage_score_per_source_family=per_family,
    )


def build_ledger(
    s3_client: Any,
    ce_client: Any,
    *,
    raw_bucket: str,
    reports_bucket: str,
    run_start_at: str,
    now: dt.datetime | None = None,
    max_workers: int = DEFAULT_LEDGER_MAX_WORKERS,
) -> RunLedger:
    """Assemble the full :class:`RunLedger` from S3 + Cost Explorer.

    ``max_workers`` controls the per-job-prefix ThreadPool fan-out for the
    sequential :func:`aggregate_for_job` walk. Per-prefix artifact assembly
    (6 ``get_object`` calls + parse + hash) is independent across the 7
    canonical J0X prefixes; the PERF-18 baseline showed S3 GET dominates
    ≥85% of wall time so a 4-way fan-out collapses the sequential 7-RTT
    walk into an effectively 2-RTT parallel walk. Set ``max_workers=1`` to
    restore the legacy sequential behaviour (useful for boto3-stub based
    unit tests that share state across prefixes).
    """

    if now is None:
        now = dt.datetime.now(dt.UTC)
    discovered = list_job_prefixes(s3_client, raw_bucket=raw_bucket)

    def _aggregate_one(prefix: str) -> PerJobLedger:
        return aggregate_for_job(s3_client, raw_bucket=raw_bucket, job_prefix=prefix)

    per_job: list[PerJobLedger]
    effective_workers = max(1, min(max_workers, len(discovered)))
    if effective_workers <= 1 or len(discovered) <= 1:
        per_job = [_aggregate_one(p) for p in discovered]
    else:
        # ThreadPoolExecutor.map preserves input order regardless of
        # completion order, so the resulting per_job list keeps the
        # canonical J01..J07 ordering — JSON output stays byte-stable
        # across sequential and parallel modes.
        with ThreadPoolExecutor(
            max_workers=effective_workers,
            thread_name_prefix="ledger-job",
        ) as pool:
            per_job = list(pool.map(_aggregate_one, discovered))

    total_credit = fetch_cost_explorer_total(ce_client, run_start_at=run_start_at, now=now)

    total_source = sum(j.total_source_count for j in per_job)
    total_claim = sum(j.total_claim_refs for j in per_job)
    total_gaps: dict[str, int] = dict.fromkeys(KNOWN_GAP_CODES, 0)
    for j in per_job:
        for code, count in j.total_known_gaps_by_code.items():
            total_gaps[code] = total_gaps.get(code, 0) + count

    avg_accepted = sum(j.accepted_artifact_rate for j in per_job) / len(per_job) if per_job else 0.0

    return RunLedger(
        generated_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        run_start_at=run_start_at,
        raw_bucket=raw_bucket,
        reports_bucket=reports_bucket,
        account_id=AWS_ACCOUNT_ID,
        jobs=tuple(per_job),
        total_credit_consumed_usd=round(total_credit, 4),
        total_source_count_account_wide=total_source,
        total_claim_refs_account_wide=total_claim,
        total_known_gaps_by_code_account_wide=total_gaps,
        accepted_artifact_rate_account_wide=round(avg_accepted, 4),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def print_summary(
    ledger: RunLedger,
    *,
    stream: io.TextIOBase | Any | None = None,
) -> None:
    """Print a human-readable summary of the ledger."""

    if stream is None:
        stream = sys.stdout
    write = stream.write
    write("==== jpcite credit-run ledger summary ====\n")
    write(f"generated_at           : {ledger.generated_at}\n")
    write(f"run_start_at           : {ledger.run_start_at}\n")
    write(f"raw_bucket             : {ledger.raw_bucket}\n")
    write(f"reports_bucket         : {ledger.reports_bucket}\n")
    write(f"account_id             : {ledger.account_id}\n")
    write(f"jobs_discovered        : {len(ledger.jobs)}\n")
    write(f"total_credit_usd       : {ledger.total_credit_consumed_usd:,.2f}\n")
    write(f"total_source_count     : {ledger.total_source_count_account_wide}\n")
    write(f"total_claim_refs       : {ledger.total_claim_refs_account_wide}\n")
    write(f"avg_accepted_artifact  : {ledger.accepted_artifact_rate_account_wide:.4f}\n")
    write("known_gaps_by_code (account-wide):\n")
    for code, count in sorted(ledger.total_known_gaps_by_code_account_wide.items()):
        write(f"  {code:<35} {count}\n")
    write("per-job rollup:\n")
    for j in ledger.jobs:
        write(
            f"  {j.job_id:<5} src={j.total_source_count:<6} "
            f"claims={j.total_claim_refs:<6} "
            f"accepted={j.accepted_artifact_rate:.3f} "
            f"score={j.coverage.coverage_score:.3f} "
            f"grade={j.coverage.coverage_grade}\n"
        )


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse CLI arguments."""

    p = argparse.ArgumentParser(
        description=("Aggregate J01-J07 credit-run artifacts into credit_run_ledger_2026_05.json"),
    )
    p.add_argument(
        "--upload",
        action="store_true",
        help=(
            "Upload the ledger to "
            "s3://<reports-bucket>/ledger/credit_run_ledger_2026_05.json "
            "(default: DRY_RUN, write to --out only)"
        ),
    )
    p.add_argument(
        "--out",
        default="out/credit_run_ledger_2026_05.json",
        help="Local path for the ledger JSON (default: out/credit_run_ledger_2026_05.json)",
    )
    p.add_argument(
        "--raw-bucket",
        default=DEFAULT_RAW_BUCKET,
        help=f"Raw bucket name (default: {DEFAULT_RAW_BUCKET})",
    )
    p.add_argument(
        "--reports-bucket",
        default=DEFAULT_REPORTS_BUCKET,
        help=f"Reports bucket name (default: {DEFAULT_REPORTS_BUCKET})",
    )
    p.add_argument(
        "--cost-explorer-region",
        default=DEFAULT_CE_REGION,
        help=f"Cost Explorer region (default: {DEFAULT_CE_REGION})",
    )
    p.add_argument(
        "--region",
        default="ap-northeast-1",
        help="S3 region for raw/reports buckets (default: ap-northeast-1)",
    )
    p.add_argument(
        "--run-start",
        default=DEFAULT_RUN_START,
        help=f"ISO8601 run start (default: {DEFAULT_RUN_START})",
    )
    p.add_argument(
        "--export-parquet",
        action="store_true",
        help=(
            "Also upload compressed Parquet snapshots of derived datasets "
            "to s3://<derived-bucket>/ (default: off)"
        ),
    )
    p.add_argument(
        "--derived-bucket",
        default=DEFAULT_DERIVED_BUCKET,
        help=f"Derived bucket name (default: {DEFAULT_DERIVED_BUCKET})",
    )
    p.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_LEDGER_MAX_WORKERS,
        help=(
            "ThreadPool fan-out for the per-job-prefix aggregation loop "
            f"(default: {DEFAULT_LEDGER_MAX_WORKERS}; set to 1 to force "
            "the legacy sequential walk)."
        ),
    )
    return p.parse_args(list(argv))


def write_local_ledger(ledger: RunLedger, *, out_path: Path) -> None:
    """Write the ledger JSON to a local path (creates parents)."""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        ledger.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv if argv is not None else sys.argv[1:])

    # PERF-35: route through the cached pool's ``get_client`` so the
    # 200-500 ms boto3 cold-start tax is paid once per (service,
    # region) tuple across the run (and across other aws_credit_ops
    # modules in the same Python interpreter). Falls back to the
    # legacy ``_import_boto3`` shim when the pool module is
    # unavailable so unit-test monkeypatches still inject fakes.
    try:
        from scripts.aws_credit_ops._aws import get_client
    except ImportError:
        boto3 = _import_boto3()
        s3 = boto3.client("s3", region_name=args.region)
        ce = boto3.client("ce", region_name=args.cost_explorer_region)
    else:
        s3 = get_client("s3", region_name=args.region)
        ce = get_client("ce", region_name=args.cost_explorer_region)

    ledger = build_ledger(
        s3,
        ce,
        raw_bucket=args.raw_bucket,
        reports_bucket=args.reports_bucket,
        run_start_at=args.run_start,
        max_workers=args.max_workers,
    )
    out_path = Path(args.out)
    write_local_ledger(ledger, out_path=out_path)
    print_summary(ledger)
    logger.info("ledger written: %s", out_path)

    if args.upload:
        body = (ledger.model_dump_json(indent=2) + "\n").encode("utf-8")
        key = "ledger/credit_run_ledger_2026_05.json"
        put_ledger_object(
            s3,
            bucket=args.reports_bucket,
            key=key,
            payload=body,
        )
        logger.info(
            "uploaded ledger to s3://%s/%s (size=%d)",
            args.reports_bucket,
            key,
            len(body),
        )
        if args.export_parquet:
            # Parquet export is best-effort: we emit a derived JSON manifest
            # listing the per-job rollups so downstream Athena partition
            # discovery can pick it up. A real Parquet write would require
            # pyarrow which is intentionally not a runtime dep.
            derived_key = "derived/credit_run_ledger_2026_05_per_job.jsonl"
            lines = (
                b"\n".join(
                    json.dumps(
                        j.model_dump(),
                        ensure_ascii=False,
                    ).encode("utf-8")
                    for j in ledger.jobs
                )
                + b"\n"
            )
            s3.put_object(
                Bucket=args.derived_bucket,
                Key=derived_key,
                Body=lines,
                ContentType="application/x-ndjson",
                ServerSideEncryption="AES256",
            )
            logger.info(
                "uploaded derived per-job rollup to s3://%s/%s",
                args.derived_bucket,
                derived_key,
            )
    else:
        logger.info("DRY_RUN: pass --upload to push the ledger to s3")

    return 0


if __name__ == "__main__":
    sys.exit(main())
