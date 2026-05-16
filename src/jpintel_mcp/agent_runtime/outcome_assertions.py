"""Outcome verifier — assertion DSL for paid-packet invariants.

Wave 59 Stream H. Lets an agent verify that an outcome they bought actually
matches what they paid for. Five testable invariants live here, each as a
pure-Python predicate over a JPCIR p0.v1 envelope:

* ``schema_present`` — Evidence + Citation + OutcomeContract fields must exist.
* ``known_gaps_valid`` — every ``known_gaps[].code`` is from the 7-enum.
* ``packet_size_within_band`` — payload bytes fit the price band ceiling
  (¥300 → 8 KB, ¥600 → 16 KB, ¥900 → 25 KB).
* ``citation_uri_valid`` — every source URI parses + uses ``https`` or ``s3``.
* ``packet_freshness`` — ``extracted_at`` (or ``observed_at`` / ``generated_at``
  fallback chain) is newer than 90 days ago.

All assertions are **deterministic** and call **no LLM**. They are pure schema /
value checks over the JPCIR envelope so they can be wired into a daily CI step
without paying any inference cost.

``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal
from urllib.parse import urlparse

#: JPCIR p0.v1 schema marker — mirrors ``scripts/aws_credit_ops/_packet_base.py``.
SCHEMA_VERSION: Final[str] = "jpcir.p0.v1"

#: Canonical 7-enum for ``known_gaps[].code`` values. Mirrors
#: ``scripts/aws_credit_ops/_packet_base.KNOWN_GAP_CODES`` (kept verbatim — both
#: the packet generators and the verifier consume the same enum).
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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Price-band → maximum payload bytes. Mirrors
#: ``CostPreviewPriceBands`` (light=¥300 → 8 KB, mid=¥600 → 16 KB,
#: heavy=¥900 → 25 KB). ``free=¥0`` packets are previews and capped at 8 KB.
PRICE_BAND_MAX_BYTES: Final[dict[int, int]] = {
    0: 8 * 1024,
    300: 8 * 1024,
    600: 16 * 1024,
    900: 25 * 1024,
}

#: Allowed schemes for citation / source URIs.
ALLOWED_CITATION_SCHEMES: Final[frozenset[str]] = frozenset({"https", "s3"})

#: Maximum age before a packet is considered stale.
PACKET_MAX_AGE_DAYS: Final[int] = 90

#: 5-assertion DSL — exact set of assertion types supported.
ASSERTION_TYPES: Final[frozenset[str]] = frozenset(
    {
        "schema_present",
        "known_gaps_valid",
        "packet_size_within_band",
        "citation_uri_valid",
        "packet_freshness",
    }
)

AssertionType = Literal[
    "schema_present",
    "known_gaps_valid",
    "packet_size_within_band",
    "citation_uri_valid",
    "packet_freshness",
]


# ---------------------------------------------------------------------------
# Result + Spec dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AssertionResult:
    """One assertion outcome on one packet."""

    assertion_type: str
    passed: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "assertion_type": self.assertion_type,
            "passed": self.passed,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class AssertionSpec:
    """Per-outcome assertion specification — loaded from JSON."""

    outcome_id: str
    assertions: tuple[str, ...]
    expected_price_jpy: int
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.outcome_id:
            msg = "outcome_id is required"
            raise ValueError(msg)
        if not self.assertions:
            msg = f"outcome {self.outcome_id} must declare at least one assertion"
            raise ValueError(msg)
        unknown = sorted(set(self.assertions) - ASSERTION_TYPES)
        if unknown:
            msg = f"unknown assertion types: {unknown}"
            raise ValueError(msg)
        if self.expected_price_jpy not in PRICE_BAND_MAX_BYTES:
            msg = (
                f"expected_price_jpy must be one of "
                f"{sorted(PRICE_BAND_MAX_BYTES)}: got {self.expected_price_jpy}"
            )
            raise ValueError(msg)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome_id": self.outcome_id,
            "assertions": list(self.assertions),
            "expected_price_jpy": self.expected_price_jpy,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AssertionSpec:
        assertions = data.get("assertions")
        if not isinstance(assertions, list):
            msg = "assertions must be a list"
            raise TypeError(msg)
        return cls(
            outcome_id=str(data["outcome_id"]),
            assertions=tuple(str(a) for a in assertions),
            expected_price_jpy=int(data["expected_price_jpy"]),
            notes=str(data.get("notes", "")),
        )


@dataclass(frozen=True)
class PacketVerification:
    """Full verifier output for one packet."""

    packet_id: str
    outcome_id: str
    s3_key: str
    results: tuple[AssertionResult, ...]
    all_passed: bool = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "all_passed",
            all(r.passed for r in self.results),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "outcome_id": self.outcome_id,
            "s3_key": self.s3_key,
            "all_passed": self.all_passed,
            "results": [r.to_dict() for r in self.results],
        }


# ---------------------------------------------------------------------------
# Assertion implementations
# ---------------------------------------------------------------------------


def _assert_schema_present(envelope: dict[str, Any]) -> AssertionResult:
    """Verify JPCIR header + minimum body fields are present.

    Required keys mirror ``contracts.JpcirHeader`` + the body fields every
    packet writer emits (``cohort_definition`` or ``body``, ``sources``,
    ``known_gaps`` — the Evidence / Citation / OutcomeContract dimensions).
    """

    missing: list[str] = []
    required_header = [
        "object_id",
        "object_type",
        "producer",
        "request_time_llm_call_performed",
        "schema_version",
    ]
    for key in required_header:
        if key not in envelope:
            missing.append(key)

    if envelope.get("schema_version") != SCHEMA_VERSION:
        return AssertionResult(
            assertion_type="schema_present",
            passed=False,
            reason=f"schema_version mismatch: {envelope.get('schema_version')!r}",
        )
    if envelope.get("request_time_llm_call_performed") is not False:
        return AssertionResult(
            assertion_type="schema_present",
            passed=False,
            reason="request_time_llm_call_performed must be false",
        )

    # Citation / Evidence / OutcomeContract dimensions:
    # * sources[] = the Citation dimension
    # * known_gaps[] = the Evidence support_state dimension
    # * package_id / package_kind = the OutcomeContract dimension
    if not isinstance(envelope.get("sources"), list):
        missing.append("sources")
    if not isinstance(envelope.get("known_gaps"), list):
        missing.append("known_gaps")
    if not envelope.get("package_id") and not envelope.get("object_id"):
        missing.append("package_id|object_id")

    if missing:
        return AssertionResult(
            assertion_type="schema_present",
            passed=False,
            reason=f"missing keys: {sorted(set(missing))}",
        )
    return AssertionResult(assertion_type="schema_present", passed=True)


def _assert_known_gaps_valid(envelope: dict[str, Any]) -> AssertionResult:
    known_gaps = envelope.get("known_gaps")
    if not isinstance(known_gaps, list) or not known_gaps:
        return AssertionResult(
            assertion_type="known_gaps_valid",
            passed=False,
            reason="known_gaps must be a non-empty list",
        )
    bad: list[str] = []
    for entry in known_gaps:
        if not isinstance(entry, dict):
            bad.append(f"non-dict entry: {entry!r}")
            continue
        code = entry.get("code")
        if not isinstance(code, str) or code not in KNOWN_GAP_CODES:
            bad.append(f"invalid code: {code!r}")
    if bad:
        return AssertionResult(
            assertion_type="known_gaps_valid",
            passed=False,
            reason="; ".join(bad[:5]),
        )
    return AssertionResult(assertion_type="known_gaps_valid", passed=True)


def _assert_packet_size_within_band(
    envelope: dict[str, Any], expected_price_jpy: int
) -> AssertionResult:
    cap = PRICE_BAND_MAX_BYTES.get(expected_price_jpy)
    if cap is None:
        return AssertionResult(
            assertion_type="packet_size_within_band",
            passed=False,
            reason=f"unsupported price band: ¥{expected_price_jpy}",
        )
    body = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    size = len(body)
    if size > cap:
        return AssertionResult(
            assertion_type="packet_size_within_band",
            passed=False,
            reason=f"packet {size} bytes exceeds band cap {cap} (¥{expected_price_jpy})",
        )
    return AssertionResult(
        assertion_type="packet_size_within_band",
        passed=True,
        reason=f"{size}/{cap} bytes",
    )


def _iter_citation_uris(envelope: dict[str, Any]) -> list[str]:
    """Pull every citation-style URI out of a JPCIR envelope.

    Looks under ``sources[]`` for ``source_url`` / ``url`` / ``uri`` keys.
    """

    sources = envelope.get("sources")
    if not isinstance(sources, list):
        return []
    out: list[str] = []
    for src in sources:
        if not isinstance(src, dict):
            continue
        for key in ("source_url", "url", "uri", "source_uri"):
            val = src.get(key)
            if isinstance(val, str) and val:
                out.append(val)
    return out


def _assert_citation_uri_valid(envelope: dict[str, Any]) -> AssertionResult:
    uris = _iter_citation_uris(envelope)
    if not uris:
        return AssertionResult(
            assertion_type="citation_uri_valid",
            passed=False,
            reason="no citation URIs found under sources[]",
        )
    bad: list[str] = []
    for raw in uris:
        try:
            parsed = urlparse(raw)
        except ValueError as exc:
            bad.append(f"unparseable: {raw!r} ({exc})")
            continue
        if parsed.scheme not in ALLOWED_CITATION_SCHEMES:
            bad.append(f"bad scheme: {raw!r}")
            continue
        if not parsed.netloc and parsed.scheme != "s3":
            bad.append(f"missing netloc: {raw!r}")
            continue
    if bad:
        return AssertionResult(
            assertion_type="citation_uri_valid",
            passed=False,
            reason="; ".join(bad[:5]),
        )
    return AssertionResult(
        assertion_type="citation_uri_valid",
        passed=True,
        reason=f"{len(uris)} URIs OK",
    )


def _extract_freshness_iso(envelope: dict[str, Any]) -> str | None:
    """Find a freshness timestamp on the envelope.

    Looks at body-level ``extracted_at``, ``observed_at``, ``generated_at``,
    and then ``created_at``. Also inspects ``sources[*].observed_at``.
    """

    for key in ("extracted_at", "observed_at", "generated_at", "created_at"):
        val = envelope.get(key)
        if isinstance(val, str) and val:
            return val
    sources = envelope.get("sources")
    if isinstance(sources, list):
        for src in sources:
            if not isinstance(src, dict):
                continue
            val = src.get("observed_at") or src.get("extracted_at")
            if isinstance(val, str) and val:
                return val
    return None


def _assert_packet_freshness(
    envelope: dict[str, Any], *, now: datetime | None = None
) -> AssertionResult:
    now = now or datetime.now(tz=UTC)
    raw = _extract_freshness_iso(envelope)
    if raw is None:
        return AssertionResult(
            assertion_type="packet_freshness",
            passed=False,
            reason="no freshness timestamp on envelope",
        )
    try:
        # Accept "Z" suffix as UTC; ``fromisoformat`` requires "+00:00" before 3.11.
        normalised = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
        observed = datetime.fromisoformat(normalised)
    except ValueError as exc:
        return AssertionResult(
            assertion_type="packet_freshness",
            passed=False,
            reason=f"unparseable timestamp {raw!r}: {exc}",
        )
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    age = now - observed
    if age > timedelta(days=PACKET_MAX_AGE_DAYS):
        return AssertionResult(
            assertion_type="packet_freshness",
            passed=False,
            reason=f"packet age {age.days}d > {PACKET_MAX_AGE_DAYS}d",
        )
    return AssertionResult(
        assertion_type="packet_freshness",
        passed=True,
        reason=f"age {age.days}d",
    )


# ---------------------------------------------------------------------------
# Verifier entry point
# ---------------------------------------------------------------------------


def run_assertion(
    assertion_type: str,
    envelope: dict[str, Any],
    *,
    expected_price_jpy: int,
    now: datetime | None = None,
) -> AssertionResult:
    """Dispatch one assertion against one envelope."""

    if assertion_type == "schema_present":
        return _assert_schema_present(envelope)
    if assertion_type == "known_gaps_valid":
        return _assert_known_gaps_valid(envelope)
    if assertion_type == "packet_size_within_band":
        return _assert_packet_size_within_band(envelope, expected_price_jpy)
    if assertion_type == "citation_uri_valid":
        return _assert_citation_uri_valid(envelope)
    if assertion_type == "packet_freshness":
        return _assert_packet_freshness(envelope, now=now)
    msg = f"unknown assertion type: {assertion_type!r}"
    raise ValueError(msg)


def verify_packet(
    *,
    envelope: dict[str, Any],
    spec: AssertionSpec,
    s3_key: str = "",
    now: datetime | None = None,
) -> PacketVerification:
    """Run all assertions in ``spec`` against one packet envelope."""

    results: list[AssertionResult] = []
    for assertion_type in spec.assertions:
        results.append(
            run_assertion(
                assertion_type,
                envelope,
                expected_price_jpy=spec.expected_price_jpy,
                now=now,
            )
        )
    package_id = envelope.get("package_id") or envelope.get("object_id") or "unknown"
    return PacketVerification(
        packet_id=str(package_id),
        outcome_id=spec.outcome_id,
        s3_key=s3_key,
        results=tuple(results),
    )


__all__ = [
    "ALLOWED_CITATION_SCHEMES",
    "ASSERTION_TYPES",
    "AssertionResult",
    "AssertionSpec",
    "AssertionType",
    "PACKET_MAX_AGE_DAYS",
    "PRICE_BAND_MAX_BYTES",
    "PacketVerification",
    "run_assertion",
    "verify_packet",
]
