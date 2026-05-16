"""Forbidden-claim wording scanner.

Scans every text-bearing leaf inside a JPCIR envelope (sections + records +
strings recursively) for forbidden wording and Japanese equivalents.

Forbidden English (case-insensitive, per master plan §5 and
``aws_credit_review_16_incident_stop.md`` §9.9):

    eligible
    safe
    no issue
    no violation
    permission not required
    credit score
    trustworthy
    proved absent

Allowed wording (whitelisted, must not be flagged even when a forbidden
substring overlaps):

    candidate_priority
    public_evidence_attention
    evidence_quality
    coverage_gap
    needs_review
    not_enough_public_evidence
    no_hit_not_absence
    professional_review_caveat

Forbidden Japanese (per memory ``feedback_no_fake_data`` adjacent — these
strings are forbidden when emitted as a **final claim** in agent-facing
text):

    問題ありません
    適格
    適合
    許可不要
    申請不要
    免税

Notes
-----
* ``該当なし`` alone is **NOT** forbidden — it is the canonical Japanese
  rendering of ``no_hit`` and is OK provided the surrounding envelope sets
  a ``known_gaps[].code = no_hit_not_absence`` (the structural check lives
  in :mod:`no_hit_regression`).
* Substring matching is intentional. We do **not** require word-boundary
  matching because Japanese has no word delimiter and because the English
  forbidden list is a deny-by-default surface. We protect false positives
  via the whitelist sweep that runs BEFORE matching: each whitelist phrase
  is masked out of the candidate text so e.g. ``no_hit_not_absence`` does
  not trip on the ``not_enough_public_evidence`` -> ``not`` pattern.
* All matching is case-insensitive for English. Japanese is naturally
  case-less but is matched as-is (no fold-width / katakana-hiragana
  normalization — those are separate concerns handled upstream in the
  composer).
* This scanner walks the envelope shape used by :mod:`no_hit_regression`
  so the same CLI runner can drain a directory in one pass.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from .no_hit_regression import Violation, _resolve_packet_id, _walk

if TYPE_CHECKING:
    from collections.abc import Iterable

FORBIDDEN_WORDING: Final[tuple[str, ...]] = (
    "eligible",
    "safe",
    "no issue",
    "no violation",
    "permission not required",
    "credit score",
    "trustworthy",
    "proved absent",
)

ALLOWED_WORDING: Final[tuple[str, ...]] = (
    "candidate_priority",
    "public_evidence_attention",
    "evidence_quality",
    "coverage_gap",
    "needs_review",
    "not_enough_public_evidence",
    "no_hit_not_absence",
    "professional_review_caveat",
)

# Japanese forbidden list. Order matters: longer phrases first so the
# whitelist masking does not eat a shorter prefix before the longer one
# has been tested. (Empirically only relevant for the English set, but we
# keep the convention for Japanese too.)
FORBIDDEN_JA: Final[tuple[str, ...]] = (
    "問題ありません",
    "許可不要",
    "申請不要",
    "適格",
    "適合",
    "免税",
)

# Field names that carry agent-facing text. We scan the values of these
# fields; nested structures are still walked recursively, so a
# ``sections[].body`` chain hits this list at the leaf.
_TEXT_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "body",
        "claim_text",
        "description",
        "detail",
        "explanation",
        "headline",
        "label",
        "message",
        "narrative",
        "note",
        "rationale",
        "reason",
        "reason_not_to_buy",
        "reason_to_buy",
        "recommendation",
        "section_body",
        "section_text",
        "subtitle",
        "summary",
        "text",
        "title",
    }
)

# Identifier-style field names — strings here are slugs / hashes / IDs, not
# agent-facing prose. We exempt them from English forbidden-wording scans
# (``packet_id="safe-001"`` should NOT match ``safe``). Japanese forbidden
# phrases are still scanned because Japanese in an identifier field is itself
# a defect (identifiers must be ASCII-slug).
_IDENTIFIER_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "claim_ref_id",
        "consent_id",
        "decision_id",
        "envelope_id",
        "evidence_id",
        "gap_id",
        "id",
        "incident_id",
        "lease_id",
        "object_id",
        "outcome_contract_id",
        "packet_id",
        "policy_decision_id",
        "receipt_id",
        "record_id",
        "run_id",
        "schema_version",
        "source_family_id",
        "source_id",
        "token_id",
    }
)


def _is_identifier_field(field_name: str | None) -> bool:
    if field_name is None:
        return False
    if field_name in _IDENTIFIER_FIELD_NAMES:
        return True
    # Heuristic: any field ending in ``_id`` is an identifier — covers
    # producer-defined IDs we did not enumerate above.
    return field_name.endswith("_id")


def _mask_whitelist(text: str) -> str:
    """Mask every allowed-wording phrase so its substring cannot match.

    We replace each occurrence with a same-length placeholder so subsequent
    substring math on the returned string keeps positional information
    intact (useful if we ever decide to surface column offsets).
    """
    masked = text
    for phrase in ALLOWED_WORDING:
        # Use a regex with IGNORECASE so the masking matches the same
        # case-folding semantics as the forbidden sweep.
        pattern = re.compile(re.escape(phrase), flags=re.IGNORECASE)
        masked = pattern.sub(" " * len(phrase), masked)
    return masked


def _find_forbidden_english(text: str) -> list[str]:
    masked = _mask_whitelist(text)
    masked_lower = masked.lower()
    hits: list[str] = []
    for phrase in FORBIDDEN_WORDING:
        if phrase in masked_lower:
            hits.append(phrase)
    return hits


def _find_forbidden_japanese(text: str) -> list[str]:
    hits: list[str] = []
    for phrase in FORBIDDEN_JA:
        if phrase in text:
            hits.append(phrase)
    return hits


def _iter_text_leaves(
    node: Any,
    path: str,
    field_name: str | None = None,
) -> Iterable[tuple[str, str, str | None]]:
    """Yield ``(path, text, field_name)`` for every string leaf.

    We yield strings everywhere — but a downstream caller can use the
    ``field_name`` to decide whether to treat the match as a "final claim"
    (text-bearing fields) versus an identifier (``packet_id`` etc.). For
    forbidden-wording we scan *everything* — identifier strings rarely
    contain English prose, and false-positive risk is dominated by the
    whitelist sweep, not by which field we scan.
    """
    if isinstance(node, str):
        yield path, node, field_name
        return
    if isinstance(node, dict):
        for key, value in node.items():
            sub_path = f"{path}.{key}" if path else f"$.{key}"
            yield from _iter_text_leaves(value, sub_path, key)
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            yield from _iter_text_leaves(item, f"{path}[{idx}]", field_name)


def _packet_id_at(envelope: Any, path: str) -> str:
    """Resolve the nearest packet_id by walking the envelope and matching
    on the prefix of ``path``.

    We use the longest-prefix dict that has a packet_id-style field.
    """
    best_match = "<unknown>"
    for sub_path, node in _walk(envelope, "$"):
        if not path.startswith(sub_path):
            continue
        candidate = _resolve_packet_id(node)
        if candidate != "<unknown>":
            best_match = candidate
    return best_match


def scan_forbidden_claims(
    envelope: Any,
    *,
    source: str | None = None,
) -> list[Violation]:
    """Scan an in-memory JPCIR envelope for forbidden-claim wording.

    Returns a flat list of :class:`Violation` (one per ``(path, phrase)``
    pair). The ``packet_id`` is resolved to the nearest containing dict
    that carries one of ``packet_id`` / ``object_id`` / ``outcome_contract_id``.
    """
    violations: list[Violation] = []
    for path, text, field_name in _iter_text_leaves(envelope, "$"):
        # English forbidden wording is only flagged on prose-bearing fields,
        # not on identifier slugs (``packet_id``, ``object_id``, ``*_id``).
        # Japanese forbidden phrases are flagged everywhere — Japanese in an
        # identifier field is itself a defect.
        en_hits: list[str] = (
            [] if _is_identifier_field(field_name) else _find_forbidden_english(text)
        )
        ja_hits = _find_forbidden_japanese(text)
        if not en_hits and not ja_hits:
            continue
        packet_id = _packet_id_at(envelope, path)
        for phrase in en_hits:
            violations.append(
                Violation(
                    scanner="forbidden_claim",
                    packet_id=packet_id,
                    path=path,
                    code="forbidden_english_wording",
                    detail=(
                        f"forbidden English phrase '{phrase}' found in "
                        f"field '{field_name or '<root>'}'"
                    ),
                    source=source,
                )
            )
        for phrase in ja_hits:
            violations.append(
                Violation(
                    scanner="forbidden_claim",
                    packet_id=packet_id,
                    path=path,
                    code="forbidden_japanese_wording",
                    detail=(
                        f"forbidden Japanese phrase '{phrase}' found in "
                        f"field '{field_name or '<root>'}'"
                    ),
                    source=source,
                )
            )
    return violations


def scan_forbidden_claims_in_file(path: Path | str) -> list[Violation]:
    """Load a JSON file and run :func:`scan_forbidden_claims` on it.

    Mirrors :func:`no_hit_regression.scan_no_hit_regressions_in_file`: a
    parse error becomes a single ``unparseable_json`` violation rather
    than an exception.
    """
    file_path = Path(path)
    try:
        with file_path.open("r", encoding="utf-8") as fh:
            envelope = json.load(fh)
    except json.JSONDecodeError as exc:
        return [
            Violation(
                scanner="forbidden_claim",
                packet_id="<unparseable>",
                path="$",
                code="unparseable_json",
                detail=f"JSONDecodeError: {exc}",
                source=str(file_path),
            )
        ]
    except OSError as exc:
        return [
            Violation(
                scanner="forbidden_claim",
                packet_id="<unreadable>",
                path="$",
                code="unreadable_file",
                detail=f"OSError: {exc}",
                source=str(file_path),
            )
        ]
    return scan_forbidden_claims(envelope, source=str(file_path))


# Convenience re-export, for symmetry with no_hit_regression's text matchers.
__all__ = [
    "ALLOWED_WORDING",
    "FORBIDDEN_JA",
    "FORBIDDEN_WORDING",
    "_TEXT_FIELD_NAMES",
    "scan_forbidden_claims",
    "scan_forbidden_claims_in_file",
]
