"""Packet-level ``known_gaps`` inventory (A8).

The composer in ``services/evidence_packet.py`` builds a packet
envelope and stamps a ``quality.known_gaps`` field. Historically that
field held a small set of upstream-failure codes (e.g.
``compat_matrix_unavailable``). This module adds **packet-shape**
gap detection on top: it walks the already-composed envelope and
reports honest data-thinness signals from the records themselves.

Design contract
---------------

* **No live I/O.** Pure ``dict -> list[dict]`` transform.
* **No LLM.** Deterministic Python only — safe under the
  ``tests/test_no_llm_in_production.py`` guard.
* **Fact-only messages.** Each gap message states what is missing or
  thin; we do not infer *why* and we do not propose fixes.
* **Returns dicts** of the shape::

      {"kind": str, "message": str, "affected_records": [str, ...]}

  ``affected_records`` is a deduplicated list of ``entity_id`` values.
  Empty list means the gap is envelope-level (no specific record).

Detected kinds (closed enum)
----------------------------

``not_found_in_local_mirror``
    A ``record_kind == 'structured_miss'`` row was emitted (the
    composer could not find the asked-for entity in the local mirror).

``lookup_status_unknown``
    A ``lookup`` block carries an explicit ``status == 'unknown'``
    (or ``'mirror_unavailable'``) — we know we did not check.

``houjin_bangou_unverified``
    A ``houjin_bangou`` value appears on a record but no positive
    structured match (invoice_registrant / enforcement / adoption_record)
    backs it up — the number is reported but not verified against the
    local mirror.

``source_url_quality``
    A record carries ``source_url`` that is either NULL/empty, not
    HTTP(S), or HTTP (not HTTPS).

``source_stale``
    A record carries an explicit ``last_verified`` / ``fetched_at`` /
    ``source_fetched_at`` ISO timestamp older than 90 days.

``low_confidence``
    A record's facts include any ``confidence < 0.5`` value, OR the
    record itself carries ``confidence < 0.5``.

This module never raises on shape drift: malformed inputs simply
yield no gaps.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

__all__ = [
    "STALE_THRESHOLD_DAYS",
    "LOW_CONFIDENCE_THRESHOLD",
    "detect_gaps",
]

#: Records whose verification timestamp is older than this many days
#: surface as ``source_stale``. 90d matches the freshness_bucket
#: vocabulary in ``evidence_packet._freshness_bucket``.
STALE_THRESHOLD_DAYS: int = 90

#: Confidence floor below which a fact (or record) flags as low.
LOW_CONFIDENCE_THRESHOLD: float = 0.5

#: lookup.status values that mean "we did not (or could not) check".
_UNKNOWN_LOOKUP_STATUSES: frozenset[str] = frozenset(
    {"unknown", "mirror_unavailable"},
)

#: lookup.status values that mean "we checked, no local hit". Surfaces
#: as the ``not_found_in_local_mirror`` gap.
_NOT_FOUND_LOOKUP_STATUSES: frozenset[str] = frozenset(
    {"not_found_in_local_mirror"},
)

#: Record kinds whose presence in records[] proves a structured miss
#: occurred (the composer's own honesty signal).
_STRUCTURED_MISS_KINDS: frozenset[str] = frozenset({"structured_miss"})

#: Record kinds that, when carrying a houjin_bangou, count as a
#: positive verification of that 法人番号.
_HOUJIN_VERIFYING_KINDS: frozenset[str] = frozenset(
    {
        "invoice_registrant",
        "enforcement",
        "enforcement_case",
        "adoption_record",
    },
)


def detect_gaps(packet: dict[str, Any]) -> list[dict[str, Any]]:
    """Inspect a composed evidence packet and return gap reports.

    Parameters
    ----------
    packet
        A dict matching the evidence_packet envelope shape (must carry
        a ``records`` list; everything else is optional).

    Returns
    -------
    list[dict]
        One entry per detected gap kind, with affected records listed.
        At most one dict per ``kind`` — repeated detections within the
        same packet collapse into a single entry whose
        ``affected_records`` accumulates the entity_ids.
    """
    if not isinstance(packet, dict):
        return []
    records = packet.get("records")
    if not isinstance(records, list):
        records = []

    # kind -> ordered, deduplicated list of entity_ids
    bucket: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}

    def add(kind: str, entity_id: str | None) -> None:
        # Normalise entity_id for dedup; "" is a legitimate "envelope-level"
        # signal but we don't store empty strings in affected_records.
        key = "" if not entity_id else str(entity_id)
        existing = seen.setdefault(kind, set())
        if key in existing:
            return
        existing.add(key)
        target = bucket.setdefault(kind, [])
        if key:
            target.append(key)

    now = datetime.now(UTC)
    stale_cutoff = now - timedelta(days=STALE_THRESHOLD_DAYS)

    for rec in records:
        if not isinstance(rec, dict):
            continue
        eid = _safe_entity_id(rec)

        # 1. structured_miss → not_found_in_local_mirror
        if rec.get("record_kind") in _STRUCTURED_MISS_KINDS:
            add("not_found_in_local_mirror", eid)

        # 2. lookup.status unknown / mirror_unavailable
        lookup = rec.get("lookup")
        if isinstance(lookup, dict):
            status = _coerce_text(lookup.get("status"))
            if status in _UNKNOWN_LOOKUP_STATUSES:
                add("lookup_status_unknown", eid)
            # also catch the explicit "checked but missing" path so the
            # caller can distinguish missed-from-no-mirror in audit
            elif status in _NOT_FOUND_LOOKUP_STATUSES:
                add("not_found_in_local_mirror", eid)

        # 3. houjin_bangou present but not positively verified
        houjin = _coerce_text(rec.get("houjin_bangou"))
        if houjin and rec.get("record_kind") not in _HOUJIN_VERIFYING_KINDS:
            # If the same record IS a verifier (e.g. invoice_registrant)
            # we trust it. Otherwise the bangou is not anchored.
            add("houjin_bangou_unverified", eid)

        # 4. source_url quality (NULL, non-http, or http-only)
        if _is_source_url_thin(rec.get("source_url")):
            add("source_url_quality", eid)

        # 5. last_verified / fetched_at older than threshold
        if _is_record_stale(rec, stale_cutoff):
            add("source_stale", eid)

        # 6. low confidence (record-level OR any fact-level)
        if _has_low_confidence(rec):
            add("low_confidence", eid)

    return _materialize(bucket)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_entity_id(rec: dict[str, Any]) -> str | None:
    eid = rec.get("entity_id")
    if eid is None:
        return None
    text = str(eid).strip()
    return text or None


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _is_source_url_thin(value: Any) -> bool:
    """Return True if the source_url is missing or not HTTPS.

    HTTP-only counts as thin (the corpus has been migrated to HTTPS;
    a residual HTTP URL is a quality regression).
    """
    text = _coerce_text(value)
    if not text:
        return True
    lowered = text.lower()
    if not lowered.startswith(("http://", "https://")):
        # not a URL at all (e.g. "see brochure")
        return True
    return lowered.startswith("http://")


def _is_record_stale(rec: dict[str, Any], cutoff: datetime) -> bool:
    """Inspect known timestamp fields on the record. ``True`` only when
    a parseable timestamp predates the cutoff. Missing timestamps do
    NOT mark a record as stale (the absence is a different signal).
    """
    for key in (
        "last_verified",
        "last_verified_at",
        "source_last_verified",
        "source_fetched_at",
        "fetched_at",
    ):
        ts = _parse_iso(rec.get(key))
        if ts is None:
            continue
        # The first parseable timestamp wins. If fresh, callers should NOT
        # examine sibling timestamps (avoids re-flagging a record where one
        # source rolled forward but a sibling is stale — packet-level
        # gap is "this record's authoritative timestamp is stale").
        return ts < cutoff
    return False


def _parse_iso(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    # Trim trailing Z and tolerate "YYYY-MM-DD" shorthand.
    text = text.removesuffix("Z")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _has_low_confidence(rec: dict[str, Any]) -> bool:
    """Detect ``confidence < 0.5`` on the record itself or any of its facts.

    A record with no confidence signal at all is NOT flagged here —
    that is a separate "no-signal" condition, and we deliberately
    avoid false positives on record kinds that legitimately omit
    confidence (e.g. structured citation rows).
    """
    rec_conf = _coerce_float(rec.get("confidence"))
    if rec_conf is not None and rec_conf < LOW_CONFIDENCE_THRESHOLD:
        return True
    facts = rec.get("facts")
    if isinstance(facts, list):
        for f in facts:
            if not isinstance(f, dict):
                continue
            fc = _coerce_float(f.get("confidence"))
            if fc is not None and fc < LOW_CONFIDENCE_THRESHOLD:
                return True
    return False


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):  # bool is int subclass; reject explicitly
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_KIND_MESSAGES: dict[str, str] = {
    "not_found_in_local_mirror": (
        "ローカルミラーに該当エントリが見つかりませんでした。"
        "公式の不在を意味するものではありません。"
    ),
    "lookup_status_unknown": (
        "lookup.status が unknown / mirror_unavailable で、"
        "ローカル確認が完了していません。"
    ),
    "houjin_bangou_unverified": (
        "法人番号が記録上に存在しますが、ローカルの登録"
        "(インボイス・行政処分・採択) で実在検証されていません。"
    ),
    "source_url_quality": (
        "source_url が NULL、または HTTPS 化されていません。"
    ),
    "source_stale": (
        f"last_verified が {STALE_THRESHOLD_DAYS} 日以上前です。"
    ),
    "low_confidence": (
        f"confidence が {LOW_CONFIDENCE_THRESHOLD} を下回るレコードまたは"
        "fact が存在します。"
    ),
}


def _materialize(bucket: dict[str, list[str]]) -> list[dict[str, Any]]:
    """Stable ordering: by the closed-enum order in ``_KIND_MESSAGES``."""
    out: list[dict[str, Any]] = []
    for kind in _KIND_MESSAGES:
        if kind not in bucket:
            continue
        out.append(
            {
                "kind": kind,
                "message": _KIND_MESSAGES[kind],
                "affected_records": list(bucket[kind]),
            }
        )
    return out
