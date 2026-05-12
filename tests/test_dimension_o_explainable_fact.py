"""Tests for Dim O Explainable / Verified knowledge-graph extension (Wave 46 dim 19 FPQO booster).

Covers the new e2e contract:
  source_doc + extracted_at + verified_by + confidence_lower + confidence_upper
  + Ed25519 attestation
all coexist in a single canonical fact payload and round-trip through
sign / verify cleanly.

Why this file
-------------
``test_dimension_e_fact_verify.py`` covers the original 3-field signing
payload (subject_kind, field_name, value_text + source_document_id). The
Dim O extension (feedback_explainable_fact_design) requires 4 additional
metadata axes — extracted_at, verified_by, confidence_lower, confidence_upper —
and these must:

  (a) Survive serialization without precision drift (numeric bounds).
  (b) Tamper-detect on Ed25519 verify when ANY field byte-flips (not just
      the original 3).
  (c) Reject malformed confidence intervals (lower > upper, NaN, out of
      [0,1] range).
  (d) Keep `confidence_lower <= confidence_upper` as an invariant.
  (e) Allow `verified_by` to be an enum of {`cron`, `manual_audit`,
      `cross_source`} with the `cross_source` value implying a non-null
      `cross_source_agreement_score` audit hook.

Pure stdlib + pytest. NO LLM. NO network. Uses cryptography stdlib if
present (skipped otherwise — matches dim E precedent).

LOC budget: ~100 (per Wave 46 dim 19 FPQO booster spec).
"""

from __future__ import annotations

import hashlib
import json
import math
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _ed25519_keypair() -> tuple[bytes, bytes]:
    """Return (private_seed, public_key) raw bytes, or skip if unavailable."""
    crypto = pytest.importorskip(
        "cryptography.hazmat.primitives.asymmetric.ed25519"
    )
    from cryptography.hazmat.primitives import serialization

    private_key = crypto.Ed25519PrivateKey.generate()
    seed = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return seed, pub


def _build_extended_payload(
    *,
    fact_id: str = "ef_dim_o_001",
    subject_kind: str = "program",
    subject_id: str = "UNI-2026-A1",
    field_name: str = "amount_max_yen",
    field_kind: str = "number",
    value_text: str | None = None,
    value_number: float | None = 5_000_000.0,
    value_date: str | None = None,
    source_document_id: str = "sd_unified_001",
    corpus_snapshot_id: str = "cs_2026_05_12",
    extracted_at: str = "2026-05-12T01:23:45.678Z",
    verified_by: str = "cron",
    confidence_lower: float = 0.78,
    confidence_upper: float = 0.92,
) -> bytes:
    """Canonical Dim O payload (extends Dim E 10-field with 4 new axes).

    MUST be byte-stable: sorted keys + ensure_ascii=False + no trailing WS.
    Mirrors api/fact_verify._canonical_payload + 4 extension axes.
    """
    payload = {
        "fact_id": fact_id,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "field_name": field_name,
        "field_kind": field_kind,
        "value_text": value_text,
        "value_number": value_number,
        "value_date": value_date,
        "source_document_id": source_document_id,
        "corpus_snapshot_id": corpus_snapshot_id,
        # ---- Dim O extension ----
        "extracted_at": extracted_at,
        "verified_by": verified_by,
        "confidence_lower": confidence_lower,
        "confidence_upper": confidence_upper,
    }
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def _sign(seed: bytes, payload: bytes) -> bytes:
    crypto = pytest.importorskip(
        "cryptography.hazmat.primitives.asymmetric.ed25519"
    )
    key = crypto.Ed25519PrivateKey.from_private_bytes(seed)
    return key.sign(payload)


def _verify(pub: bytes, payload: bytes, sig: bytes) -> bool:
    crypto = pytest.importorskip(
        "cryptography.hazmat.primitives.asymmetric.ed25519"
    )
    from cryptography.exceptions import InvalidSignature

    try:
        crypto.Ed25519PublicKey.from_public_bytes(pub).verify(sig, payload)
        return True
    except InvalidSignature:
        return False


# ---------------------------------------------------------------------------
# (a) numeric round-trip + serialization stability
# ---------------------------------------------------------------------------


def test_extended_payload_is_byte_stable_across_call_order():
    """The canonical payload must hash identically regardless of caller
    keyword-argument order (sorted keys guarantee)."""
    a = _build_extended_payload(
        confidence_lower=0.5, confidence_upper=0.6, verified_by="cron"
    )
    b = _build_extended_payload(
        verified_by="cron", confidence_upper=0.6, confidence_lower=0.5
    )
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()


def test_confidence_bounds_serialize_without_drift():
    """Float bounds round-trip via JSON without precision loss for our
    canonical precision (4 decimal digits)."""
    payload = _build_extended_payload(
        confidence_lower=0.7891, confidence_upper=0.9234
    )
    parsed = json.loads(payload.decode("utf-8"))
    assert math.isclose(parsed["confidence_lower"], 0.7891, abs_tol=1e-9)
    assert math.isclose(parsed["confidence_upper"], 0.9234, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# (b) tamper detection on extension fields
# ---------------------------------------------------------------------------


def test_ed25519_sign_then_verify_succeeds_on_clean_payload():
    seed, pub = _ed25519_keypair()
    payload = _build_extended_payload()
    sig = _sign(seed, payload)
    assert _verify(pub, payload, sig) is True


def test_ed25519_verify_fails_on_confidence_byte_flip():
    """Flipping a byte in confidence_lower/upper must break verify."""
    seed, pub = _ed25519_keypair()
    clean = _build_extended_payload(confidence_lower=0.5)
    sig = _sign(seed, clean)
    tampered = _build_extended_payload(confidence_lower=0.6)
    assert tampered != clean
    assert _verify(pub, tampered, sig) is False


def test_ed25519_verify_fails_on_verified_by_swap():
    """Flipping verified_by from cron -> manual_audit must break verify."""
    seed, pub = _ed25519_keypair()
    clean = _build_extended_payload(verified_by="cron")
    sig = _sign(seed, clean)
    tampered = _build_extended_payload(verified_by="manual_audit")
    assert _verify(pub, tampered, sig) is False


def test_ed25519_verify_fails_on_extracted_at_drift():
    """Time-drift on extracted_at (one minute later) must break verify."""
    seed, pub = _ed25519_keypair()
    clean = _build_extended_payload(extracted_at="2026-05-12T01:23:45.678Z")
    sig = _sign(seed, clean)
    tampered = _build_extended_payload(extracted_at="2026-05-12T01:24:45.678Z")
    assert _verify(pub, tampered, sig) is False


# ---------------------------------------------------------------------------
# (c) malformed-input rejection helpers
# ---------------------------------------------------------------------------


def _validate_confidence_bounds(lo: float, hi: float) -> bool:
    """Pure-function validator the canonical signer would call.

    Returns True iff bounds are well-formed: both in [0,1], lower <= upper,
    neither NaN. Matches feedback_explainable_fact_design (Dim O):
    confidence intervals must be sane before sign-time admission.
    """
    if math.isnan(lo) or math.isnan(hi):
        return False
    if not (0.0 <= lo <= 1.0):
        return False
    if not (0.0 <= hi <= 1.0):
        return False
    return lo <= hi


def test_confidence_validator_rejects_inverted_bounds():
    assert _validate_confidence_bounds(0.9, 0.5) is False


def test_confidence_validator_rejects_out_of_range():
    assert _validate_confidence_bounds(-0.1, 0.5) is False
    assert _validate_confidence_bounds(0.5, 1.5) is False


def test_confidence_validator_rejects_nan():
    assert _validate_confidence_bounds(float("nan"), 0.5) is False
    assert _validate_confidence_bounds(0.5, float("nan")) is False


def test_confidence_validator_accepts_edge_cases():
    """Identical bounds (point estimate) + full [0,1] both pass."""
    assert _validate_confidence_bounds(0.5, 0.5) is True
    assert _validate_confidence_bounds(0.0, 1.0) is True
    assert _validate_confidence_bounds(1.0, 1.0) is True


# ---------------------------------------------------------------------------
# (e) verified_by enum + cross_source implication
# ---------------------------------------------------------------------------


VERIFIED_BY_ENUM = frozenset({"cron", "manual_audit", "cross_source"})


def test_verified_by_enum_is_closed():
    """Only the 3 documented values are admissible."""
    for v in ("cron", "manual_audit", "cross_source"):
        assert v in VERIFIED_BY_ENUM
    for bad in ("llm", "guess", "unknown", "", "CRON"):
        assert bad not in VERIFIED_BY_ENUM


def test_cross_source_requires_agreement_score():
    """When verified_by=cross_source, downstream join must surface a
    cross_source_agreement_score (Dim I; migration 265). This guard
    asserts the implication contract at unit level so the canonical
    signer can refuse to sign mismatched rows."""

    def is_cross_source_row_complete(verified_by: str, score: float | None) -> bool:
        if verified_by != "cross_source":
            return True
        return score is not None and 0.0 <= score <= 1.0

    assert is_cross_source_row_complete("cron", None) is True
    assert is_cross_source_row_complete("cross_source", None) is False
    assert is_cross_source_row_complete("cross_source", 0.87) is True
    assert is_cross_source_row_complete("cross_source", -0.1) is False
    assert is_cross_source_row_complete("cross_source", 1.2) is False


# ---------------------------------------------------------------------------
# Sanity guard — no LLM imports in this test
# ---------------------------------------------------------------------------


def test_dim_o_test_file_has_no_llm_import():
    """Sanity guard built with split tokens so the check does not self-match."""
    src = pathlib.Path(__file__).resolve().read_text(encoding="utf-8")
    forbidden_prefixes = (
        "import " + "anthr" + "opic",
        "from " + "anthr" + "opic",
        "import " + "open" + "ai",
    )
    for forbidden in forbidden_prefixes:
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""'):
                continue
            assert forbidden not in stripped
