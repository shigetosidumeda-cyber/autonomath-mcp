"""No-hit semantics regression scanner.

Walks a JPCIR envelope (or any deeply-nested JSON-like Python object) and
flags every ``no_hit`` observation that is **not** paired with a
``known_gaps[].code == 'no_hit_not_absence'`` (or the field-name variant
``gap_id`` / ``gap_type``) on the same packet.

Why this matters
----------------
The jpcite no-hit semantics rule (``no_hit_not_absence``) forbids ever
returning "not found" / "doesn't exist" / "safe" / "no issue" for a 0-hit
query. The structural enforcement is: every ``no_hit`` result MUST carry a
known_gap entry whose code/gap_id/gap_type is ``no_hit_not_absence``. If a
producer emits a no_hit result without that gap, this scanner emits a
:class:`Violation` so the release gate (and the operator playbook) can fail
closed.

Detection rules
---------------
The scanner walks the JSON-like object recursively. For every dict it
encounters it asks two questions:

1. **Is this dict a no-hit packet?** That is true if any of these is true:

   * ``result == "no_hit"`` (case-insensitive).
   * ``no_hit`` is a truthy boolean.
   * ``no_hit_observed`` is a truthy boolean.
   * ``status`` is ``"no_hit"`` (case-insensitive).
   * ``hits`` is an empty list AND ``checked_scope`` is present (no_hit
     observation envelope shape).

2. **Does it carry a no_hit_not_absence gap?** That is true if the dict
   (or any direct ``known_gaps`` / ``gaps`` / ``gap_coverage`` child) has
   at least one entry whose ``code`` / ``gap_id`` / ``gap_type`` /
   ``no_hit_semantics`` equals ``no_hit_not_absence``.

If (1) is true and (2) is false, a Violation is recorded at the dict's
JSON path with the packet's ``packet_id`` / ``object_id`` /
``outcome_contract_id`` (whichever is first non-null).

This is a structural check, not a wording check. The companion
:mod:`forbidden_claim` scanner handles wording.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

NO_HIT_NOT_ABSENCE_CODE: Final[str] = "no_hit_not_absence"

_NO_HIT_GAP_FIELDS: Final[tuple[str, ...]] = (
    "code",
    "gap_id",
    "gap_type",
    "no_hit_semantics",
)
_NO_HIT_GAP_CONTAINERS: Final[tuple[str, ...]] = (
    "known_gaps",
    "gaps",
    "gap_coverage",
    "gap_coverage_entries",
)
_PACKET_ID_FIELDS: Final[tuple[str, ...]] = (
    "packet_id",
    "object_id",
    "outcome_contract_id",
    "decision_id",
    "envelope_id",
    "id",
)


@dataclass(frozen=True)
class Violation:
    """One safety-scanner violation.

    Attributes
    ----------
    scanner:
        Identifier of the scanner that produced the violation
        (``"no_hit_regression"`` or ``"forbidden_claim"``).
    packet_id:
        First non-null ``packet_id`` / ``object_id`` / ``outcome_contract_id``
        we could resolve from the offending dict. May be ``"<unknown>"``.
    path:
        JSON pointer-ish path (``"$.results[2].known_gaps"``) so the operator
        can grep straight to the offending node.
    code:
        Short machine-readable reason.
    detail:
        Human-readable diagnostic.
    source:
        Absolute file path the violation came from. ``None`` for raw-object
        scans (e.g. inline pytest fixtures).
    """

    scanner: str
    packet_id: str
    path: str
    code: str
    detail: str
    source: str | None = None

    def to_dict(self) -> dict[str, str]:
        """Serialize for JSON output by :mod:`scripts.safety.scan_outputs`."""
        out: dict[str, str] = {
            "scanner": self.scanner,
            "packet_id": self.packet_id,
            "path": self.path,
            "code": self.code,
            "detail": self.detail,
        }
        if self.source is not None:
            out["source"] = self.source
        return out


def _resolve_packet_id(node: dict[str, Any]) -> str:
    for field in _PACKET_ID_FIELDS:
        value = node.get(field)
        if isinstance(value, str) and value.strip():
            return value
    return "<unknown>"


def _gap_entries(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for container in _NO_HIT_GAP_CONTAINERS:
        value = node.get(container)
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, dict):
                    yield entry


def _has_no_hit_not_absence_gap(node: dict[str, Any]) -> bool:
    # Self-declared on the same dict (the NoHitLease / Evidence shape).
    for field in _NO_HIT_GAP_FIELDS:
        if node.get(field) == NO_HIT_NOT_ABSENCE_CODE:
            return True
    # Or in any of the known_gaps / gaps / gap_coverage child arrays.
    for entry in _gap_entries(node):
        for field in _NO_HIT_GAP_FIELDS:
            if entry.get(field) == NO_HIT_NOT_ABSENCE_CODE:
                return True
    return False


def _is_no_hit_packet(node: dict[str, Any]) -> bool:
    result = node.get("result")
    if isinstance(result, str) and result.lower() == "no_hit":
        return True
    status = node.get("status")
    if isinstance(status, str) and status.lower() == "no_hit":
        return True
    if node.get("no_hit") is True:
        return True
    if node.get("no_hit_observed") is True:
        return True
    hits = node.get("hits")
    return bool(isinstance(hits, list) and len(hits) == 0 and "checked_scope" in node)


def _walk(node: Any, path: str) -> Iterator[tuple[str, dict[str, Any]]]:
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}" if path else f"$.{key}")
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            yield from _walk(item, f"{path}[{idx}]")


def scan_no_hit_regressions(
    envelope: Any,
    *,
    source: str | None = None,
) -> list[Violation]:
    """Scan an in-memory JPCIR envelope for no-hit regression violations.

    Parameters
    ----------
    envelope:
        Any JSON-like Python value (typically a dict produced by
        ``model.model_dump()`` or ``json.loads(...)`` of a packet file).
    source:
        Optional file path (carried through into the returned
        :class:`Violation` records for CLI reporting).

    Returns
    -------
    A list of :class:`Violation` records, one per offending no_hit dict.
    Empty list when the envelope is safe or contains no no_hit observations.
    """
    violations: list[Violation] = []
    for path, node in _walk(envelope, "$"):
        if not _is_no_hit_packet(node):
            continue
        if _has_no_hit_not_absence_gap(node):
            continue
        violations.append(
            Violation(
                scanner="no_hit_regression",
                packet_id=_resolve_packet_id(node),
                path=path,
                code="missing_no_hit_not_absence_gap",
                detail=(
                    "no_hit packet does not carry a known_gaps entry with "
                    f"code/gap_id/gap_type == '{NO_HIT_NOT_ABSENCE_CODE}'"
                ),
                source=source,
            )
        )
    return violations


def scan_no_hit_regressions_in_file(path: Path | str) -> list[Violation]:
    """Load a JSON file and run :func:`scan_no_hit_regressions` on it.

    A JSONDecodeError is surfaced as a single ``unparseable_json`` violation
    rather than raising — the scanner is meant to drain a directory of files
    in CI and report every problem in one pass.
    """
    file_path = Path(path)
    try:
        with file_path.open("r", encoding="utf-8") as fh:
            envelope = json.load(fh)
    except json.JSONDecodeError as exc:
        return [
            Violation(
                scanner="no_hit_regression",
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
                scanner="no_hit_regression",
                packet_id="<unreadable>",
                path="$",
                code="unreadable_file",
                detail=f"OSError: {exc}",
                source=str(file_path),
            )
        ]
    return scan_no_hit_regressions(envelope, source=str(file_path))


def violations_to_summary(violations: Iterable[Violation]) -> dict[str, Any]:
    """Pack a list of violations into the canonical CLI output shape."""
    items = list(violations)
    return {
        "scanner": "no_hit_regression",
        "violation_count": len(items),
        "violations": [v.to_dict() for v in items],
    }
