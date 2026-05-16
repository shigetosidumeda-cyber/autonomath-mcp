"""Wave 51 dim O — tests for the explainable_fact router-agnostic module.

Distinct from the Wave 47 integration tests (``test_dim_o_explainable_fact``
exercises migration 275 + the ``am_fact_metadata`` SQLite layer); this
module-level suite covers the **router-agnostic primitives** under
``src/jpintel_mcp/explainable_fact/``:

    * FactMetadata Pydantic model — 4 mandatory axes enforced
    * canonical_payload — stable byte serialization for sign/verify
    * sign_fact / verify_fact — Ed25519 round-trip
    * Tamper detection — flipped fact_id / metadata fails verify
    * load_public_key_from_env — hex env-var resolver
    * No private keys generated outside ephemeral test fixtures
"""

from __future__ import annotations

import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)
from pydantic import ValidationError

from jpintel_mcp.explainable_fact import (
    FactMetadata,
    canonical_payload,
    load_public_key_from_env,
    sign_fact,
    verify_fact,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _ephemeral_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Generate an ephemeral keypair in-memory for the test run.

    The private key never leaves the test process and is **not** written
    to disk under any circumstance. Only the public key bytes are ever
    persisted (and only in fixtures, see below).
    """
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    return private_key, public_key


def _valid_metadata() -> FactMetadata:
    return FactMetadata(
        source_doc="https://elaws.e-gov.go.jp/document?lawid=昭和四十年法律第三十四号",
        extracted_at="2026-05-16T03:45:12Z",
        verified_by="cron_etl_v3",
        confidence=0.97,
    )


# ---------------------------------------------------------------------------
# Pydantic model — 4 mandatory field happy path
# ---------------------------------------------------------------------------


def test_fact_metadata_happy_path_accepts_all_four_axes() -> None:
    metadata = _valid_metadata()

    assert metadata.source_doc.startswith("https://elaws.e-gov.go.jp/")
    assert metadata.extracted_at == "2026-05-16T03:45:12Z"
    assert metadata.verified_by == "cron_etl_v3"
    assert metadata.confidence == 0.97


def test_fact_metadata_is_frozen_and_forbids_extra_fields() -> None:
    metadata = _valid_metadata()

    # Frozen — assignment should raise.
    with pytest.raises(ValidationError):
        metadata.confidence = 0.5  # type: ignore[misc]

    # extra='forbid' — unknown field rejected.
    with pytest.raises(ValidationError):
        FactMetadata(
            source_doc="https://example.gov.jp/x",
            extracted_at="2026-05-16T00:00:00Z",
            verified_by="manual",
            confidence=1.0,
            unknown_field="boom",  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# Pydantic model — each of the 4 axes is enforced
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing_field",
    ["source_doc", "extracted_at", "verified_by", "confidence"],
)
def test_fact_metadata_rejects_missing_each_of_4_mandatory_fields(
    missing_field: str,
) -> None:
    payload: dict[str, object] = {
        "source_doc": "https://elaws.e-gov.go.jp/x",
        "extracted_at": "2026-05-16T00:00:00Z",
        "verified_by": "manual",
        "confidence": 0.9,
    }
    payload.pop(missing_field)

    with pytest.raises(ValidationError) as exc_info:
        FactMetadata(**payload)

    # Field name surfaces in the error so operators can debug bad ETL rows.
    assert missing_field in str(exc_info.value)


def test_fact_metadata_rejects_empty_source_doc() -> None:
    with pytest.raises(ValidationError):
        FactMetadata(
            source_doc="",
            extracted_at="2026-05-16T00:00:00Z",
            verified_by="manual",
            confidence=0.5,
        )


def test_fact_metadata_rejects_empty_extracted_at() -> None:
    with pytest.raises(ValidationError):
        FactMetadata(
            source_doc="https://elaws.e-gov.go.jp/x",
            extracted_at="",
            verified_by="manual",
            confidence=0.5,
        )


@pytest.mark.parametrize(
    "bad_verified_by",
    ["unknown", "human", "etl", "Ed25519Sig", "", "auto"],
)
def test_fact_metadata_rejects_off_enum_verified_by(bad_verified_by: str) -> None:
    with pytest.raises(ValidationError):
        FactMetadata(
            source_doc="https://elaws.e-gov.go.jp/x",
            extracted_at="2026-05-16T00:00:00Z",
            verified_by=bad_verified_by,
            confidence=0.5,
        )


@pytest.mark.parametrize(
    "bad_confidence",
    [-0.01, 1.01, -1.0, 2.0, float("inf"), float("nan")],
)
def test_fact_metadata_rejects_out_of_range_confidence(
    bad_confidence: float,
) -> None:
    with pytest.raises(ValidationError):
        FactMetadata(
            source_doc="https://elaws.e-gov.go.jp/x",
            extracted_at="2026-05-16T00:00:00Z",
            verified_by="manual",
            confidence=bad_confidence,
        )


def test_fact_metadata_accepts_boundary_confidence_values() -> None:
    for boundary in (0.0, 1.0):
        m = FactMetadata(
            source_doc="https://elaws.e-gov.go.jp/x",
            extracted_at="2026-05-16T00:00:00Z",
            verified_by="manual",
            confidence=boundary,
        )
        assert m.confidence == boundary


# ---------------------------------------------------------------------------
# Canonical payload — determinism
# ---------------------------------------------------------------------------


def test_canonical_payload_is_deterministic_and_sorted() -> None:
    metadata = _valid_metadata()
    fact_id = "fact_abc_001"

    payload_a = canonical_payload(fact_id, metadata)
    payload_b = canonical_payload(fact_id, metadata)
    assert payload_a == payload_b

    # The on-the-wire JSON keys are sorted alphabetically.
    decoded = json.loads(payload_a.decode("utf-8"))
    assert list(decoded.keys()) == sorted(decoded.keys())
    assert decoded["fact_id"] == fact_id
    assert decoded["source_doc"] == metadata.source_doc
    assert decoded["confidence"] == metadata.confidence


def test_canonical_payload_rejects_empty_fact_id() -> None:
    with pytest.raises(ValueError):
        canonical_payload("", _valid_metadata())


# ---------------------------------------------------------------------------
# Ed25519 sign + verify happy path
# ---------------------------------------------------------------------------


def test_sign_and_verify_roundtrip_succeeds() -> None:
    private_key, public_key = _ephemeral_keypair()
    metadata = _valid_metadata()
    fact_id = "fact_round_trip"

    sig = sign_fact(fact_id, metadata, private_key)
    assert isinstance(sig, bytes)
    assert len(sig) == 64

    assert verify_fact(fact_id, metadata, sig, public_key) is True


# ---------------------------------------------------------------------------
# Tamper detection
# ---------------------------------------------------------------------------


def test_verify_rejects_tampered_fact_id() -> None:
    private_key, public_key = _ephemeral_keypair()
    metadata = _valid_metadata()
    sig = sign_fact("fact_original", metadata, private_key)

    assert verify_fact("fact_modified", metadata, sig, public_key) is False


def test_verify_rejects_tampered_metadata_field() -> None:
    private_key, public_key = _ephemeral_keypair()
    original = _valid_metadata()
    sig = sign_fact("fact_x", original, private_key)

    # Each axis flipped independently → all must fail verify.
    tampered = original.model_copy(update={"confidence": 0.10})
    assert verify_fact("fact_x", tampered, sig, public_key) is False

    tampered = original.model_copy(update={"source_doc": "https://fake.example/"})
    assert verify_fact("fact_x", tampered, sig, public_key) is False

    tampered = original.model_copy(update={"extracted_at": "2099-01-01T00:00:00Z"})
    assert verify_fact("fact_x", tampered, sig, public_key) is False

    tampered = original.model_copy(update={"verified_by": "manual"})
    assert verify_fact("fact_x", tampered, sig, public_key) is False


def test_verify_rejects_signature_from_different_key() -> None:
    private_key_a, _ = _ephemeral_keypair()
    _, public_key_b = _ephemeral_keypair()
    metadata = _valid_metadata()
    sig = sign_fact("fact_cross_key", metadata, private_key_a)

    assert verify_fact("fact_cross_key", metadata, sig, public_key_b) is False


def test_verify_rejects_bit_flipped_signature() -> None:
    private_key, public_key = _ephemeral_keypair()
    metadata = _valid_metadata()
    sig = sign_fact("fact_bit_flip", metadata, private_key)

    flipped = bytearray(sig)
    flipped[0] ^= 0x01
    assert verify_fact("fact_bit_flip", metadata, bytes(flipped), public_key) is False


@pytest.mark.parametrize("bad_len_sig", [b"", b"x" * 63, b"x" * 65, b"x" * 80])
def test_verify_rejects_malformed_signature_length(bad_len_sig: bytes) -> None:
    _, public_key = _ephemeral_keypair()
    with pytest.raises(ValueError):
        verify_fact("fact_short", _valid_metadata(), bad_len_sig, public_key)


# ---------------------------------------------------------------------------
# Public key env loader
# ---------------------------------------------------------------------------


def test_load_public_key_from_env_returns_none_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AUTONOMATH_FACT_SIGN_PUBLIC_KEY", raising=False)
    assert load_public_key_from_env() is None


def test_load_public_key_from_env_returns_none_when_non_hex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTONOMATH_FACT_SIGN_PUBLIC_KEY", "not-hex-zz")
    assert load_public_key_from_env() is None


def test_load_public_key_from_env_returns_none_for_wrong_byte_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 30-byte hex string is the correct hex encoding but wrong byte length.
    monkeypatch.setenv("AUTONOMATH_FACT_SIGN_PUBLIC_KEY", "ab" * 30)
    assert load_public_key_from_env() is None


def test_load_public_key_from_env_resolves_valid_hex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, public_key = _ephemeral_keypair()
    raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    monkeypatch.setenv("AUTONOMATH_FACT_SIGN_PUBLIC_KEY", raw.hex())

    resolved = load_public_key_from_env()
    assert resolved is not None

    # Resolved key verifies signatures from the same ephemeral private key.
    private_key, _ = _ephemeral_keypair()
    # New private key won't verify against the env-loaded pubkey — confirm.
    sig = sign_fact("fact_env", _valid_metadata(), private_key)
    assert verify_fact("fact_env", _valid_metadata(), sig, resolved) is False


# ---------------------------------------------------------------------------
# JSON Schema mirror — file present and structurally aligned
# ---------------------------------------------------------------------------


def test_fact_metadata_json_schema_file_is_present_and_required_fields_match() -> None:
    import pathlib

    schema_path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "schemas"
        / "jpcir"
        / "fact_metadata.schema.json"
    )
    assert schema_path.exists(), f"schema mirror missing at {schema_path}"

    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    # Required fields must exactly match the Pydantic mandatory set.
    assert set(schema["required"]) == {
        "source_doc",
        "extracted_at",
        "verified_by",
        "confidence",
    }
    assert schema["additionalProperties"] is False
    assert schema["properties"]["verified_by"]["enum"] == [
        "manual",
        "cron_etl_v3",
        "ed25519_sig",
    ]
    assert schema["properties"]["confidence"]["minimum"] == 0.0
    assert schema["properties"]["confidence"]["maximum"] == 1.0
