#!/usr/bin/env python3
"""End-to-end JPCIR run artifact validator (8 invariants).

Walks a credit-run artifact tree (local directory **or** ``s3://...`` prefix)
and verifies that **every** invariant required for a Wave 50 RC1 ledger to
be considered "production-grade evidence" passes in a single pass.

The 8 invariants (each maps to one section of
``docs/_internal/aws_credit_data_acquisition_jobs_agent.md`` §1.2-§1.3 and
the master plan §5 / §9.9 safety gates):

1.  **schema_conformance** -- every JSON record matches its JPCIR schema
    (jsonschema Draft 2020-12). Discovery is driven by either the
    ``schema`` / ``schema_name`` / ``jpcir_schema`` hint in
    ``object_manifest.jsonl`` rows, or by filename convention
    (``source_receipts.jsonl`` -> ``source_receipt`` schema, etc.).
2.  **sha256_integrity** -- for every object listed in
    ``object_manifest.jsonl`` with a ``sha256`` field, the SHA-256 digest
    of the actual file payload matches that field.
3.  **source_receipt_consistency** -- every ``claim_refs.jsonl`` row's
    ``receipt_ids`` (also accepts the alias ``source_receipt_ids``)
    references at least one row in ``source_receipts.jsonl``; dangling
    receipt IDs become a violation.
4.  **known_gap_enum** -- every ``known_gaps.jsonl`` row's ``code`` /
    ``gap_id`` / ``gap_type`` field is one of the 7 canonical enum values
    (``csv_input_not_evidence_safe``, ``source_receipt_incomplete``,
    ``pricing_or_cap_unconfirmed``, ``no_hit_not_absence``,
    ``professional_review_required``, ``freshness_stale_or_unknown``,
    ``identity_ambiguity_unresolved``).
5.  **license_boundary_defined** -- every distinct ``source_family_id``
    referenced from receipts / object_manifest has a ``license`` (free
    enum: ``pdl_v1.0`` / ``cc_by_4.0`` / ``gov_standard`` / ``public_domain``
    / ``proprietary`` etc.) declared either on the receipt row, or on a
    sidecar ``license_boundary.json`` / ``source_licenses.json`` map.
6.  **freshness_within_window** -- every receipt's ``observed_at`` (or
    ``extracted_at`` / ``last_verified``) age relative to ``run_manifest
    .json``'s ``run_started_at`` is within the per-source-family
    staleness TTL (default 30 days, override via
    ``--staleness-ttl-days``).
7.  **no_hit_not_absence** -- every ``no_hit`` observation in any record
    is paired with a ``known_gaps[].code == 'no_hit_not_absence'`` on the
    same dict (delegates to :func:`safety_scanners.scan_no_hit_regressions`).
8.  **forbidden_claim_absence** -- no record / section in any artifact
    carries forbidden English wording (``eligible`` / ``safe`` / ``no
    issue`` / ``no violation`` / ``permission not required`` / ``credit
    score`` / ``trustworthy`` / ``proved absent``) nor forbidden Japanese
    wording (``問題ありません`` / ``適格`` / ``適合`` / ``許可不要`` /
    ``申請不要`` / ``免税``). Delegates to
    :func:`safety_scanners.scan_forbidden_claims`.

CLI::

    python scripts/aws_credit_ops/validate_run_artifacts.py <prefix>
                                                    [--schemas-dir PATH]
                                                    [--staleness-ttl-days N]
                                                    [--json]
                                                    [--license-map PATH]

``<prefix>`` is either a local directory (e.g.
``out/raw/J01_source_profile/``) or an ``s3://...`` URI (e.g.
``s3://jpcite-credit-...-raw/J01/``). ``s3://`` requires boto3 in the
operator environment; local paths do not.

Exit codes:

* ``0`` -- every invariant PASS.
* ``1`` -- one or more invariants FAIL (violation detail printed to
  stdout / JSON).
* ``2`` -- internal error (could not read prefix, missing schemas,
  unreadable object manifest, etc.).

Non-negotiable invariants of the script itself:

* **No LLM API calls.** Pure jsonschema + Python.
* **Read-only.** No S3 writes, no file writes (besides stdout / stderr).
* ``[lane:solo]`` per CLAUDE.md dual-CLI lane convention.

Wave 50 supplement (2026-05-16).
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import jsonschema  # type: ignore[import-untyped]
from jsonschema import Draft202012Validator

from jpintel_mcp.safety_scanners import (
    scan_forbidden_claims,
    scan_no_hit_regressions,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

logger = logging.getLogger("validate_run_artifacts")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Canonical schema registry directory (under repo root).
DEFAULT_SCHEMAS_DIR: Final[Path] = Path("schemas/jpcir")

#: Per master plan §1.3 -- the only 7 valid ``known_gaps[].code`` enum values.
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

#: Default per-source-family staleness TTL (days). Overridable via CLI flag.
DEFAULT_STALENESS_TTL_DAYS: Final[int] = 30

#: Per-family override (in days). Keep this aligned with
#: ``docs/_internal/aws_credit_data_acquisition_jobs_agent.md`` §1.4.
SOURCE_FAMILY_TTL_DAYS: Final[dict[str, int]] = {
    "egov_law": 90,
    "nta_houjin": 30,
    "nta_invoice": 30,
    "jgrants": 14,
    "ministry_pdf": 60,
    "gbizinfo": 60,
}

#: Standard artifact filenames produced by every J0?_*  Batch job (mirrors
#: ``aggregate_run_ledger.ARTIFACT_FILES``). The validator skips any name
#: that isn't on this list when discovering JSONL files for cross-ref.
STANDARD_JSONL_FILES: Final[tuple[str, ...]] = (
    "object_manifest.jsonl",
    "source_receipts.jsonl",
    "claim_refs.jsonl",
    "known_gaps.jsonl",
    "quarantine.jsonl",
)

#: Mapping of filename suffix -> schema name. Lets us auto-discover schema
#: per record without requiring an ``object_manifest`` hint on every row.
FILENAME_TO_SCHEMA: Final[dict[str, str]] = {
    "source_receipts.jsonl": "source_receipt",
    "claim_refs.jsonl": "claim_ref",
    "known_gaps.jsonl": "known_gap",
}

#: The 8 invariant IDs reported in :class:`ValidationReport`. Order is
#: stable so downstream consumers can pin against it.
INVARIANT_IDS: Final[tuple[str, ...]] = (
    "schema_conformance",
    "sha256_integrity",
    "source_receipt_consistency",
    "known_gap_enum",
    "license_boundary_defined",
    "freshness_within_window",
    "no_hit_not_absence",
    "forbidden_claim_absence",
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    """One invariant violation."""

    invariant: str
    code: str
    detail: str
    source: str | None = None
    path: str | None = None

    def to_dict(self) -> dict[str, str]:
        out: dict[str, str] = {
            "invariant": self.invariant,
            "code": self.code,
            "detail": self.detail,
        }
        if self.source is not None:
            out["source"] = self.source
        if self.path is not None:
            out["path"] = self.path
        return out


@dataclass
class ValidationReport:
    """Per-invariant pass/fail rollup."""

    prefix: str
    invariants: dict[str, bool] = field(default_factory=dict)
    violations: list[Violation] = field(default_factory=list)

    def record(self, invariant: str, *, passed: bool) -> None:
        # Once a False is set we never overwrite it back to True -- a single
        # violation collapses the invariant to FAIL.
        prior = self.invariants.get(invariant)
        self.invariants[invariant] = bool(passed) and bool(prior if prior is not None else True)

    def add_violation(self, v: Violation) -> None:
        self.violations.append(v)
        self.record(v.invariant, passed=False)

    @property
    def all_pass(self) -> bool:
        return all(self.invariants.get(inv, False) for inv in INVARIANT_IDS)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prefix": self.prefix,
            "invariants": {inv: self.invariants.get(inv, False) for inv in INVARIANT_IDS},
            "violation_count": len(self.violations),
            "violations": [v.to_dict() for v in self.violations],
            "all_pass": self.all_pass,
        }


# ---------------------------------------------------------------------------
# Filesystem / S3 source adapter
# ---------------------------------------------------------------------------


class ArtifactSource:
    """Pull payloads (bytes) by relative filename.

    The validator only needs ``read(relative_name) -> bytes | None`` and
    ``list_relative_names() -> Iterable[str]``. Both local paths and S3
    prefixes implement the same surface.
    """

    def read(self, relative_name: str) -> bytes | None:  # pragma: no cover
        raise NotImplementedError

    def list_relative_names(self) -> Iterable[str]:  # pragma: no cover
        raise NotImplementedError

    @property
    def display_prefix(self) -> str:  # pragma: no cover
        raise NotImplementedError


class LocalDirSource(ArtifactSource):
    """Local-directory backed artifact source."""

    def __init__(self, base: Path) -> None:
        self._base = base.resolve()

    def read(self, relative_name: str) -> bytes | None:
        full = self._base / relative_name
        if not full.exists() or not full.is_file():
            return None
        return full.read_bytes()

    def list_relative_names(self) -> Iterable[str]:
        if not self._base.exists():
            return
        for file_path in sorted(self._base.rglob("*")):
            if file_path.is_file():
                yield str(file_path.relative_to(self._base))

    @property
    def display_prefix(self) -> str:
        return str(self._base)


class S3PrefixSource(ArtifactSource):
    """S3-prefix backed artifact source (uses boto3 lazily)."""

    def __init__(self, bucket: str, prefix: str, s3_client: Any | None = None) -> None:
        self._bucket = bucket
        self._prefix = prefix if prefix.endswith("/") else f"{prefix}/"
        self._s3 = s3_client

    def _client(self) -> Any:
        if self._s3 is not None:
            return self._s3
        try:
            import boto3  # type: ignore[import-not-found]
        except ImportError as exc:
            msg = (
                "boto3 is not installed. Install in the operator environment "
                "(pip install boto3) before running validate_run_artifacts "
                "against an s3:// prefix, or pass a local path instead."
            )
            raise RuntimeError(msg) from exc
        self._s3 = boto3.client("s3")
        return self._s3

    def read(self, relative_name: str) -> bytes | None:
        key = f"{self._prefix}{relative_name}"
        try:
            response = self._client().get_object(Bucket=self._bucket, Key=key)
        except Exception as exc:  # noqa: BLE001 -- soft 404 detection
            error_code = ""
            with contextlib.suppress(AttributeError):
                error_code = str(exc.response.get("Error", {}).get("Code", ""))  # type: ignore[attr-defined]
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

    def list_relative_names(self) -> Iterable[str]:
        s3 = self._client()
        continuation: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self._bucket, "Prefix": self._prefix}
            if continuation is not None:
                kwargs["ContinuationToken"] = continuation
            response = s3.list_objects_v2(**kwargs)
            for row in response.get("Contents", []) or []:
                key = row.get("Key")
                if isinstance(key, str) and key.startswith(self._prefix):
                    yield key[len(self._prefix) :]
            if response.get("IsTruncated"):
                continuation = response.get("NextContinuationToken")
                if continuation is None:
                    return
            else:
                return

    @property
    def display_prefix(self) -> str:
        return f"s3://{self._bucket}/{self._prefix}"


def build_source(prefix: str) -> ArtifactSource:
    """Resolve a CLI prefix into a concrete :class:`ArtifactSource`."""
    if prefix.startswith("s3://"):
        body = prefix[len("s3://") :]
        if "/" not in body:
            msg = f"Malformed s3 URI (missing key portion): {prefix!r}"
            raise ValueError(msg)
        bucket, key_part = body.split("/", 1)
        return S3PrefixSource(bucket=bucket, prefix=key_part)
    return LocalDirSource(Path(prefix))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_jsonl(payload: bytes) -> list[dict[str, Any]]:
    """Parse a JSONL payload into a list of dicts (skip blank / non-dict)."""
    rows: list[dict[str, Any]] = []
    if not payload:
        return rows
    for raw_line in payload.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            # Skip non-JSON lines silently here; schema validator will flag
            # them via the schema_conformance invariant.
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def parse_json_object(payload: bytes) -> dict[str, Any]:
    """Parse a JSON object payload (returns empty dict on empty input)."""
    if not payload:
        return {}
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        msg = f"Expected JSON object, got {type(parsed).__name__}"
        raise ValueError(msg)
    return parsed


def hash_payload(payload: bytes) -> str:
    """Return the hex SHA-256 digest of ``payload``."""
    return hashlib.sha256(payload).hexdigest()


def parse_iso8601(value: str) -> dt.datetime | None:
    """Best-effort ISO 8601 parser. Returns None on failure."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    # Normalize trailing Z to +00:00 so fromisoformat accepts it.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


def load_schemas(schemas_dir: Path) -> dict[str, Draft202012Validator]:
    """Load every ``*.schema.json`` under ``schemas_dir`` into a validator map.

    The map key is the schema name (e.g. ``"source_receipt"``), derived
    from the filename by stripping the ``.schema.json`` suffix.
    """
    out: dict[str, Draft202012Validator] = {}
    if not schemas_dir.exists() or not schemas_dir.is_dir():
        msg = f"Schemas directory not found: {schemas_dir}"
        raise FileNotFoundError(msg)
    for path in sorted(schemas_dir.glob("*.schema.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            msg = f"Unparseable schema {path}: {exc}"
            raise ValueError(msg) from exc
        name = path.name[: -len(".schema.json")]
        out[name] = Draft202012Validator(payload)
    if not out:
        msg = f"No *.schema.json files found in {schemas_dir}"
        raise FileNotFoundError(msg)
    return out


# ---------------------------------------------------------------------------
# Invariant checks
# ---------------------------------------------------------------------------


def _schema_name_for_row(
    *,
    filename: str,
    row: dict[str, Any],
    object_manifest_lookup: dict[str, str],
) -> str | None:
    """Return the schema name that should validate ``row`` (or None to skip).

    Lookup precedence:

    1. row-level ``schema`` / ``schema_name`` / ``jpcir_schema`` field
    2. object_manifest hint keyed by filename (object_manifest can name a
       schema for the whole file via ``schema`` / ``schema_name``)
    3. filename convention (``source_receipts.jsonl`` ->
       ``source_receipt``)
    """
    for field_name in ("schema", "schema_name", "jpcir_schema"):
        value = row.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if filename in object_manifest_lookup:
        return object_manifest_lookup[filename]
    return FILENAME_TO_SCHEMA.get(filename)


def _object_manifest_schema_hints(
    rows: Iterable[dict[str, Any]],
) -> dict[str, str]:
    """Build a {filename -> schema_name} hint map from object_manifest rows."""
    out: dict[str, str] = {}
    for row in rows:
        filename = row.get("filename") or row.get("name") or row.get("path") or row.get("key")
        if not isinstance(filename, str) or not filename.strip():
            continue
        # Normalize a leading prefix path (e.g. "J01/source_receipts.jsonl")
        # into the trailing component (matches our per-prefix layout).
        if "/" in filename:
            filename = filename.rsplit("/", 1)[-1]
        for field_name in ("schema", "schema_name", "jpcir_schema"):
            value = row.get(field_name)
            if isinstance(value, str) and value.strip():
                out[filename] = value.strip()
                break
    return out


def check_schema_conformance(
    *,
    source: ArtifactSource,
    schemas: dict[str, Draft202012Validator],
    object_manifest_rows: list[dict[str, Any]],
    file_rows: dict[str, list[dict[str, Any]]],
) -> list[Violation]:
    """Invariant 1: every JSON row validates against its JPCIR schema."""
    violations: list[Violation] = []
    object_manifest_lookup = _object_manifest_schema_hints(object_manifest_rows)
    # Validate the JSONL files we explicitly know about.
    for filename, rows in file_rows.items():
        for idx, row in enumerate(rows):
            schema_name = _schema_name_for_row(
                filename=filename,
                row=row,
                object_manifest_lookup=object_manifest_lookup,
            )
            if schema_name is None:
                continue
            validator = schemas.get(schema_name)
            if validator is None:
                violations.append(
                    Violation(
                        invariant="schema_conformance",
                        code="unknown_schema",
                        detail=(
                            f"row references schema {schema_name!r} but no "
                            f"validator was loaded from --schemas-dir"
                        ),
                        source=filename,
                        path=f"row[{idx}]",
                    )
                )
                continue
            errors = sorted(validator.iter_errors(row), key=lambda e: e.path)
            for err in errors:
                violations.append(
                    Violation(
                        invariant="schema_conformance",
                        code="schema_violation",
                        detail=f"{schema_name}: {err.message}",
                        source=filename,
                        path=f"row[{idx}].{'/'.join(str(p) for p in err.path)}",
                    )
                )
    return violations


def check_sha256_integrity(
    *,
    source: ArtifactSource,
    object_manifest_rows: list[dict[str, Any]],
) -> list[Violation]:
    """Invariant 2: file SHA-256 matches the manifest digest."""
    violations: list[Violation] = []
    for row_idx, row in enumerate(object_manifest_rows):
        expected = row.get("sha256") or row.get("sha_256") or row.get("hash")
        if not isinstance(expected, str) or not expected.strip():
            continue
        filename = row.get("filename") or row.get("name") or row.get("path") or row.get("key")
        if not isinstance(filename, str) or not filename.strip():
            violations.append(
                Violation(
                    invariant="sha256_integrity",
                    code="manifest_missing_filename",
                    detail="object_manifest row has sha256 but no filename/name/path/key",
                    source="object_manifest.jsonl",
                    path=f"row[{row_idx}]",
                )
            )
            continue
        relative = filename.rsplit("/", 1)[-1] if "/" in filename else filename
        payload = source.read(relative)
        if payload is None:
            violations.append(
                Violation(
                    invariant="sha256_integrity",
                    code="file_missing",
                    detail=(
                        f"object_manifest references {relative!r} but the file "
                        "was not found in the prefix"
                    ),
                    source="object_manifest.jsonl",
                    path=f"row[{row_idx}]",
                )
            )
            continue
        actual = hash_payload(payload)
        if actual.lower() != expected.lower():
            violations.append(
                Violation(
                    invariant="sha256_integrity",
                    code="sha256_mismatch",
                    detail=(
                        f"sha256 mismatch for {relative!r}: "
                        f"manifest={expected[:12]}… actual={actual[:12]}…"
                    ),
                    source="object_manifest.jsonl",
                    path=f"row[{row_idx}]",
                )
            )
    return violations


def check_source_receipt_consistency(
    *,
    source_receipts: list[dict[str, Any]],
    claim_refs: list[dict[str, Any]],
) -> list[Violation]:
    """Invariant 3: every claim_ref.receipt_ids row links to a real receipt."""
    receipt_ids: set[str] = set()
    for row in source_receipts:
        rid = row.get("receipt_id") or row.get("source_receipt_id") or row.get("id")
        if isinstance(rid, str) and rid.strip():
            receipt_ids.add(rid)
    violations: list[Violation] = []
    for idx, row in enumerate(claim_refs):
        # Support both the JPCIR-canonical "receipt_ids" and the legacy
        # "source_receipt_ids" alias.
        refs = row.get("receipt_ids") or row.get("source_receipt_ids")
        if refs is None:
            continue
        if not isinstance(refs, list):
            violations.append(
                Violation(
                    invariant="source_receipt_consistency",
                    code="receipt_ids_not_list",
                    detail=f"claim_ref.receipt_ids is not a list: {type(refs).__name__}",
                    source="claim_refs.jsonl",
                    path=f"row[{idx}].receipt_ids",
                )
            )
            continue
        for ref in refs:
            if not isinstance(ref, str) or not ref.strip():
                violations.append(
                    Violation(
                        invariant="source_receipt_consistency",
                        code="receipt_id_blank",
                        detail="claim_ref.receipt_ids contains blank/non-string",
                        source="claim_refs.jsonl",
                        path=f"row[{idx}].receipt_ids",
                    )
                )
                continue
            if ref not in receipt_ids:
                violations.append(
                    Violation(
                        invariant="source_receipt_consistency",
                        code="dangling_receipt_id",
                        detail=(
                            f"claim_ref references receipt_id {ref!r} not "
                            "present in source_receipts.jsonl"
                        ),
                        source="claim_refs.jsonl",
                        path=f"row[{idx}].receipt_ids",
                    )
                )
    return violations


def check_known_gap_enum(
    *,
    known_gaps: list[dict[str, Any]],
) -> list[Violation]:
    """Invariant 4: every gap row's code/gap_id/gap_type is in the 7-enum."""
    violations: list[Violation] = []
    for idx, row in enumerate(known_gaps):
        # The aggregator + scanners look at any of these three field names.
        code = (
            row.get("code")
            or row.get("gap_id")
            or row.get("gap_type")
            or row.get("no_hit_semantics")
        )
        if not isinstance(code, str) or not code.strip():
            violations.append(
                Violation(
                    invariant="known_gap_enum",
                    code="missing_gap_code",
                    detail="known_gaps row has no code/gap_id/gap_type",
                    source="known_gaps.jsonl",
                    path=f"row[{idx}]",
                )
            )
            continue
        if code not in KNOWN_GAP_CODES:
            violations.append(
                Violation(
                    invariant="known_gap_enum",
                    code="invalid_gap_code",
                    detail=(
                        f"gap code {code!r} is not one of the 7 valid codes: "
                        f"{sorted(KNOWN_GAP_CODES)}"
                    ),
                    source="known_gaps.jsonl",
                    path=f"row[{idx}]",
                )
            )
    return violations


def check_license_boundary_defined(
    *,
    source_receipts: list[dict[str, Any]],
    object_manifest_rows: list[dict[str, Any]],
    license_map: dict[str, str] | None,
) -> list[Violation]:
    """Invariant 5: every distinct source_family_id has a license declared."""
    sidecar = license_map or {}
    families: set[str] = set()
    for row in source_receipts:
        fam = row.get("source_family_id") or row.get("source_family")
        if isinstance(fam, str) and fam.strip():
            families.add(fam.strip())
    for row in object_manifest_rows:
        fam = row.get("source_family_id") or row.get("source_family")
        if isinstance(fam, str) and fam.strip():
            families.add(fam.strip())
    violations: list[Violation] = []
    # For each family, license must be declared either on a receipt row,
    # an object_manifest row, or the sidecar map.
    for family in sorted(families):
        if family in sidecar and str(sidecar[family]).strip():
            continue
        receipt_license = _first_field_for_family(
            source_receipts,
            family=family,
            keys=("license", "license_id", "data_license"),
        )
        manifest_license = _first_field_for_family(
            object_manifest_rows,
            family=family,
            keys=("license", "license_id", "data_license"),
        )
        if receipt_license is None and manifest_license is None:
            violations.append(
                Violation(
                    invariant="license_boundary_defined",
                    code="license_undeclared",
                    detail=(
                        f"source_family_id={family!r} has no license declared "
                        "on receipts, object_manifest, or sidecar license_map"
                    ),
                    source="source_receipts.jsonl",
                )
            )
    return violations


def _first_field_for_family(
    rows: Iterable[dict[str, Any]],
    *,
    family: str,
    keys: Sequence[str],
) -> str | None:
    for row in rows:
        fam = row.get("source_family_id") or row.get("source_family")
        if fam != family:
            continue
        for key in keys:
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def check_freshness_within_window(
    *,
    source_receipts: list[dict[str, Any]],
    run_manifest: dict[str, Any],
    default_ttl_days: int,
) -> list[Violation]:
    """Invariant 6: receipt age <= per-family staleness TTL."""
    reference: dt.datetime | None = None
    for key in ("run_started_at", "run_start_at", "generated_at", "created_at"):
        value = run_manifest.get(key)
        if isinstance(value, str):
            reference = parse_iso8601(value)
            if reference is not None:
                break
    if reference is None:
        reference = dt.datetime.now(dt.UTC)
    violations: list[Violation] = []
    for idx, row in enumerate(source_receipts):
        observed: dt.datetime | None = None
        for key in ("observed_at", "extracted_at", "last_verified", "fetched_at"):
            value = row.get(key)
            if isinstance(value, str):
                observed = parse_iso8601(value)
                if observed is not None:
                    break
        if observed is None:
            # No timestamp present -- mark as stale unknown.
            violations.append(
                Violation(
                    invariant="freshness_within_window",
                    code="missing_observed_at",
                    detail="source_receipt has no observed_at/extracted_at/last_verified",
                    source="source_receipts.jsonl",
                    path=f"row[{idx}]",
                )
            )
            continue
        family = row.get("source_family_id") or row.get("source_family") or ""
        ttl_days = SOURCE_FAMILY_TTL_DAYS.get(str(family), default_ttl_days)
        age_days = (reference - observed).total_seconds() / 86400.0
        if age_days > ttl_days:
            violations.append(
                Violation(
                    invariant="freshness_within_window",
                    code="receipt_stale",
                    detail=(
                        f"source_family_id={family!r} observed_at is {age_days:.1f}d old "
                        f"vs ttl {ttl_days}d"
                    ),
                    source="source_receipts.jsonl",
                    path=f"row[{idx}]",
                )
            )
    return violations


def check_no_hit_not_absence(
    *,
    file_rows: dict[str, list[dict[str, Any]]],
    json_blobs: dict[str, dict[str, Any]],
) -> list[Violation]:
    """Invariant 7: every no_hit observation carries no_hit_not_absence gap."""
    violations: list[Violation] = []
    for filename, rows in file_rows.items():
        for idx, row in enumerate(rows):
            for sub in scan_no_hit_regressions(row, source=filename):
                violations.append(
                    Violation(
                        invariant="no_hit_not_absence",
                        code=sub.code,
                        detail=sub.detail,
                        source=filename,
                        path=f"row[{idx}]{sub.path[1:] if sub.path.startswith('$') else sub.path}",
                    )
                )
    for filename, blob in json_blobs.items():
        for sub in scan_no_hit_regressions(blob, source=filename):
            violations.append(
                Violation(
                    invariant="no_hit_not_absence",
                    code=sub.code,
                    detail=sub.detail,
                    source=filename,
                    path=sub.path,
                )
            )
    return violations


def check_forbidden_claim_absence(
    *,
    file_rows: dict[str, list[dict[str, Any]]],
    json_blobs: dict[str, dict[str, Any]],
) -> list[Violation]:
    """Invariant 8: no forbidden English/Japanese wording in records."""
    violations: list[Violation] = []
    for filename, rows in file_rows.items():
        for idx, row in enumerate(rows):
            for sub in scan_forbidden_claims(row, source=filename):
                violations.append(
                    Violation(
                        invariant="forbidden_claim_absence",
                        code=sub.code,
                        detail=sub.detail,
                        source=filename,
                        path=f"row[{idx}]{sub.path[1:] if sub.path.startswith('$') else sub.path}",
                    )
                )
    for filename, blob in json_blobs.items():
        for sub in scan_forbidden_claims(blob, source=filename):
            violations.append(
                Violation(
                    invariant="forbidden_claim_absence",
                    code=sub.code,
                    detail=sub.detail,
                    source=filename,
                    path=sub.path,
                )
            )
    return violations


# ---------------------------------------------------------------------------
# Top-level validator
# ---------------------------------------------------------------------------


def validate_run_artifacts(
    *,
    source: ArtifactSource,
    schemas: dict[str, Draft202012Validator],
    license_map: dict[str, str] | None = None,
    staleness_ttl_days: int = DEFAULT_STALENESS_TTL_DAYS,
) -> ValidationReport:
    """Run all 8 invariants and return a :class:`ValidationReport`."""
    report = ValidationReport(prefix=source.display_prefix)
    # Initialize every invariant to PASS; checks downgrade to FAIL as they
    # find violations.
    for inv in INVARIANT_IDS:
        report.record(inv, passed=True)

    # ---- Load primary artifact files (best-effort; missing files become
    # violations on the relevant invariant).
    run_manifest_payload = source.read("run_manifest.json")
    try:
        run_manifest = parse_json_object(run_manifest_payload or b"")
    except (json.JSONDecodeError, ValueError) as exc:
        report.add_violation(
            Violation(
                invariant="schema_conformance",
                code="run_manifest_unparseable",
                detail=f"run_manifest.json could not be parsed: {exc}",
                source="run_manifest.json",
            )
        )
        run_manifest = {}

    object_manifest_rows = parse_jsonl(source.read("object_manifest.jsonl") or b"")
    source_receipts = parse_jsonl(source.read("source_receipts.jsonl") or b"")
    claim_refs = parse_jsonl(source.read("claim_refs.jsonl") or b"")
    known_gaps = parse_jsonl(source.read("known_gaps.jsonl") or b"")
    quarantine_rows = parse_jsonl(source.read("quarantine.jsonl") or b"")

    file_rows: dict[str, list[dict[str, Any]]] = {
        "source_receipts.jsonl": source_receipts,
        "claim_refs.jsonl": claim_refs,
        "known_gaps.jsonl": known_gaps,
        "quarantine.jsonl": quarantine_rows,
        "object_manifest.jsonl": object_manifest_rows,
    }
    json_blobs: dict[str, dict[str, Any]] = {"run_manifest.json": run_manifest}

    # ---- Invariant 1: schema_conformance
    # run_manifest header (if it carries a JPCIR header subobject).
    header_payload = run_manifest.get("jpcir_header") or run_manifest.get("header")
    if isinstance(header_payload, dict):
        header_validator = schemas.get("jpcir_header")
        if header_validator is not None:
            for err in sorted(header_validator.iter_errors(header_payload), key=lambda e: e.path):
                report.add_violation(
                    Violation(
                        invariant="schema_conformance",
                        code="schema_violation",
                        detail=f"jpcir_header: {err.message}",
                        source="run_manifest.json",
                        path=f"header.{'/'.join(str(p) for p in err.path)}",
                    )
                )
    for v in check_schema_conformance(
        source=source,
        schemas=schemas,
        object_manifest_rows=object_manifest_rows,
        file_rows=file_rows,
    ):
        report.add_violation(v)

    # ---- Invariant 2: sha256_integrity
    for v in check_sha256_integrity(source=source, object_manifest_rows=object_manifest_rows):
        report.add_violation(v)

    # ---- Invariant 3: source_receipt_consistency
    for v in check_source_receipt_consistency(
        source_receipts=source_receipts,
        claim_refs=claim_refs,
    ):
        report.add_violation(v)

    # ---- Invariant 4: known_gap_enum
    for v in check_known_gap_enum(known_gaps=known_gaps):
        report.add_violation(v)

    # ---- Invariant 5: license_boundary_defined
    sidecar_payload = source.read("license_boundary.json") or source.read("source_licenses.json")
    sidecar: dict[str, str] = dict(license_map or {})
    if sidecar_payload:
        try:
            sidecar_data = json.loads(sidecar_payload)
        except json.JSONDecodeError:
            sidecar_data = {}
        if isinstance(sidecar_data, dict):
            for key, value in sidecar_data.items():
                if isinstance(key, str) and isinstance(value, str):
                    sidecar[key] = value
    for v in check_license_boundary_defined(
        source_receipts=source_receipts,
        object_manifest_rows=object_manifest_rows,
        license_map=sidecar,
    ):
        report.add_violation(v)

    # ---- Invariant 6: freshness_within_window
    for v in check_freshness_within_window(
        source_receipts=source_receipts,
        run_manifest=run_manifest,
        default_ttl_days=staleness_ttl_days,
    ):
        report.add_violation(v)

    # ---- Invariant 7: no_hit_not_absence
    for v in check_no_hit_not_absence(file_rows=file_rows, json_blobs=json_blobs):
        report.add_violation(v)

    # ---- Invariant 8: forbidden_claim_absence
    for v in check_forbidden_claim_absence(file_rows=file_rows, json_blobs=json_blobs):
        report.add_violation(v)

    return report


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------


def render_text_report(report: ValidationReport) -> str:
    """Render a human-friendly text report (used in non-JSON mode)."""
    lines: list[str] = []
    lines.append("==== jpcite JPCIR run validator ====")
    lines.append(f"prefix : {report.prefix}")
    lines.append("")
    lines.append("Invariant summary:")
    width = max(len(inv) for inv in INVARIANT_IDS)
    for inv in INVARIANT_IDS:
        ok = report.invariants.get(inv, False)
        lines.append(f"  {inv:<{width}}  {'PASS' if ok else 'FAIL'}")
    lines.append("")
    if report.violations:
        lines.append(f"Violations ({len(report.violations)}):")
        for v in report.violations:
            base = f"  - [{v.invariant}] {v.code}: {v.detail}"
            extras: list[str] = []
            if v.source is not None:
                extras.append(f"source={v.source}")
            if v.path is not None:
                extras.append(f"path={v.path}")
            if extras:
                base = f"{base} ({', '.join(extras)})"
            lines.append(base)
    else:
        lines.append("No violations.")
    lines.append("")
    lines.append("OVERALL: " + ("PASS (exit 0)" if report.all_pass else "FAIL (exit 1)"))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse CLI arguments."""
    p = argparse.ArgumentParser(
        description=(
            "Validate an end-to-end JPCIR run artifact tree against the 8 "
            "invariants (schema, sha, xref, gap-enum, license, freshness, "
            "no-hit, forbidden-claim)."
        ),
    )
    p.add_argument(
        "prefix",
        help="Local directory or s3://bucket/prefix containing the run artifacts.",
    )
    p.add_argument(
        "--schemas-dir",
        default=str(DEFAULT_SCHEMAS_DIR),
        help=f"Directory of *.schema.json files (default: {DEFAULT_SCHEMAS_DIR}).",
    )
    p.add_argument(
        "--staleness-ttl-days",
        type=int,
        default=DEFAULT_STALENESS_TTL_DAYS,
        help=(
            f"Default freshness TTL in days for source families not in the "
            f"per-family table (default: {DEFAULT_STALENESS_TTL_DAYS})."
        ),
    )
    p.add_argument(
        "--license-map",
        default=None,
        help=(
            "Optional path to a JSON file with {source_family_id -> license} "
            "overrides (merged with any in-prefix license_boundary.json)."
        ),
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Print the report as JSON (single line per invariant) instead of text.",
    )
    return p.parse_args(list(argv))


def load_license_map(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    payload = Path(path).read_text(encoding="utf-8")
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        msg = f"license-map JSON must be an object, got {type(parsed).__name__}"
        raise ValueError(msg)
    out: dict[str, str] = {}
    for key, value in parsed.items():
        if isinstance(key, str) and isinstance(value, str):
            out[key] = value
    return out


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv if argv is not None else sys.argv[1:])
    try:
        source = build_source(args.prefix)
        schemas = load_schemas(Path(args.schemas_dir))
        license_map = load_license_map(args.license_map)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        logger.error("validator setup failed: %s", exc)
        return 2

    try:
        report = validate_run_artifacts(
            source=source,
            schemas=schemas,
            license_map=license_map,
            staleness_ttl_days=args.staleness_ttl_days,
        )
    except (jsonschema.exceptions.SchemaError, OSError) as exc:
        logger.error("validation aborted: %s", exc)
        return 2

    if args.json:
        sys.stdout.write(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(render_text_report(report))

    return 0 if report.all_pass else 1


if __name__ == "__main__":  # pragma: no cover - thin shim
    sys.exit(main())
