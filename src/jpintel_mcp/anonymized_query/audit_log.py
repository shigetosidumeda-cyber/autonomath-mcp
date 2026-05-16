"""Append-only JSONL audit log for dim N anonymized queries.

Each anonymized query call writes exactly one JSON line to
``logs/anonymized_query_audit.jsonl`` (or the caller-supplied path).
The row captures **only**:

    * Wall-clock timestamp (UTC ISO-8601 with ``Z`` suffix).
    * SHA-256 hash of the cohort filter triple (industry / region /
      size). NEVER the raw filter values — pre-hashing is the
      compliance gate, not the redact step.
    * Redact policy version string from :mod:`pii_redact`.
    * Cohort size (post k-anonymity check, so an audit reader can
      confirm the floor held).
    * Outcome reason code (from
      :class:`anonymized_query.k_anonymity.KAnonymityResult`).
    * List of PII pattern ids redacted from the text path (set, not raw
      counts, so a frequency-based reidentification attack on the audit
      log itself is not possible).

Compliance properties
---------------------
* **Append-only.** The file is opened in ``"a"`` mode every call. The
  process never seeks or rewrites prior rows. This makes truncation /
  tampering detectable by a post-hoc audit (line N suddenly missing).
* **Atomic line write.** We compose the full JSON string + ``"\\n"``
  in memory and issue a single ``write()`` call. POSIX guarantees
  same-process writes <PIPE_BUF (4 KB+) are atomic, and a dim N audit
  line is ~200 bytes, well under that bound.
* **No raw PII.** The redact step happens *before* this module is
  called; we accept already-hashed identifiers and pattern-id lists. A
  caller passing raw houjin_bangou would trip the
  :func:`write_audit_entry` validator and raise ``ValueError``.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

# Default location for the audit log. Lives at repo-root ``logs/`` so
# Fly volume + GHA runner + dev shell all share a stable path. Callers
# can override via :func:`write_audit_entry(path=...)`.
DEFAULT_AUDIT_LOG_PATH: Final[Path] = Path("logs") / "anonymized_query_audit.jsonl"

# Sanity bounds — if a caller passes a non-hex hash or a suspiciously
# short string we reject it before write so the audit log can never
# accidentally absorb a raw 法人番号.
_HEX64_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_VALID_REASONS: Final[frozenset[str]] = frozenset(
    {"ok", "cohort_too_small", "negative_cohort", "invalid_filter", "redact_violation"}
)


def cohort_hash(industry: str | None, region: str | None, size: str | None) -> str:
    """Deterministic SHA-256 hash of the cohort filter triple.

    ``None`` filter slots are normalized to the empty string so a
    ``(industry="A", region=None, size=None)`` cohort hashes
    consistently across calls. The leading ``"dim-n:"`` namespace tag
    keeps these hashes domain-separated from any other SHA-256 use in
    the repo.
    """
    raw = "dim-n:{}|{}|{}".format(industry or "", region or "", size or "")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """One audit log row.

    Attributes
    ----------
    ts:
        UTC ISO-8601 timestamp (``2026-05-16T12:34:56.789Z``).
    cohort_hash:
        SHA-256 of ``(industry, region, size)`` — see :func:`cohort_hash`.
    redact_policy_version:
        Version string from :data:`pii_redact.REDACT_POLICY_VERSION`.
    cohort_size:
        Integer count after k-anonymity check.
    reason:
        Stable reason code (see :data:`_VALID_REASONS`).
    pii_hits:
        Sorted, deduplicated list of PII pattern ids that fired during
        text redact. Empty list when no text redact ran. Sorting makes
        the field stable for log diffing.
    """

    ts: str
    cohort_hash: str
    redact_policy_version: str
    cohort_size: int
    reason: str
    pii_hits: list[str] = field(default_factory=list)

    def to_jsonl(self) -> str:
        """Serialize to a single newline-terminated JSON line.

        ``ensure_ascii=False`` is intentional — the audit log lives on a
        Japanese-locale-friendly volume, and we want human auditors to
        read the few non-redacted fields (reason / pattern ids) without
        a JSON-escape decoder pass. The pii_hits list is already
        ASCII (pattern ids are English snake_case), so the option only
        matters if a future field carries 漢字.
        """
        payload = asdict(self)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"


def _utc_now_iso() -> str:
    """UTC timestamp with millisecond precision + trailing ``Z``."""
    now = datetime.now(tz=UTC)
    # Strip the trailing ``+00:00`` and re-append ``Z`` for the
    # canonical agent-facing format used elsewhere in the repo.
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _validate_inputs(
    cohort_hash_hex: str,
    redact_policy_version: str,
    cohort_size: int,
    reason: str,
    pii_hits: list[str],
) -> None:
    """Reject malformed audit inputs **before** opening the log file.

    The audit log is the compliance receipt — if we cannot fully
    validate the payload we refuse to write rather than emit a
    partially-valid row that could mask a real violation.
    """
    if not _HEX64_RE.match(cohort_hash_hex):
        raise ValueError(
            "cohort_hash must be 64 lowercase hex chars (SHA-256); "
            "pass the result of cohort_hash(...) — never a raw 法人番号."
        )
    if not redact_policy_version or not isinstance(redact_policy_version, str):
        raise ValueError("redact_policy_version must be a non-empty string")
    if not isinstance(cohort_size, int) or isinstance(cohort_size, bool):
        raise ValueError("cohort_size must be int (bool not allowed)")
    if reason not in _VALID_REASONS:
        raise ValueError(
            f"reason {reason!r} not in {_VALID_REASONS}; add to the set deliberately."
        )
    for hit in pii_hits:
        if not isinstance(hit, str) or not hit:
            raise ValueError("pii_hits entries must be non-empty pattern id strings")


def write_audit_entry(
    *,
    cohort_hash_hex: str,
    redact_policy_version: str,
    cohort_size: int,
    reason: str,
    pii_hits: list[str] | None = None,
    path: Path | str | None = None,
) -> AuditEntry:
    """Append one validated audit row to the JSONL log.

    Parameters
    ----------
    cohort_hash_hex:
        Lowercase hex SHA-256 of the cohort filter triple. Produce via
        :func:`cohort_hash` so the namespace tag stays consistent.
    redact_policy_version:
        :data:`pii_redact.REDACT_POLICY_VERSION` at the time the call
        ran. Capturing the version (not just "true / false") lets a
        future auditor replay the exact redact rule.
    cohort_size:
        Final cohort size **after** k-anonymity check. For rejected
        small cohorts pass the original size so the auditor can confirm
        the floor held; the row's ``reason`` will be ``cohort_too_small``.
    reason:
        One of :data:`_VALID_REASONS`. Adding a new reason is a code
        change — the validator rejects unknown values to prevent
        free-text drift in the audit log.
    pii_hits:
        Optional list of PII pattern ids that fired. Deduplicated and
        sorted before persistence so the on-disk format is stable.
    path:
        Optional override of :data:`DEFAULT_AUDIT_LOG_PATH`. Useful for
        per-test isolation (``tmp_path`` fixture).

    Returns
    -------
    AuditEntry
        The row exactly as persisted. Use ``.to_jsonl()`` if a caller
        needs to mirror it elsewhere.

    Raises
    ------
    ValueError
        On any input validation failure (see :func:`_validate_inputs`).
    OSError
        If the log file cannot be opened for append. The audit log is
        compliance-critical, so we surface the OS error rather than
        swallowing it.
    """
    pii_hits_norm: list[str] = sorted(set(pii_hits or []))
    _validate_inputs(
        cohort_hash_hex=cohort_hash_hex,
        redact_policy_version=redact_policy_version,
        cohort_size=cohort_size,
        reason=reason,
        pii_hits=pii_hits_norm,
    )
    entry = AuditEntry(
        ts=_utc_now_iso(),
        cohort_hash=cohort_hash_hex,
        redact_policy_version=redact_policy_version,
        cohort_size=cohort_size,
        reason=reason,
        pii_hits=pii_hits_norm,
    )
    out_path = Path(path) if path is not None else DEFAULT_AUDIT_LOG_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Append-only — see module docstring. ``"a"`` opens at EOF on every
    # call; we never seek backwards.
    with out_path.open("a", encoding="utf-8") as fh:
        fh.write(entry.to_jsonl())
        # ``flush`` so a crash between calls does not lose the line we
        # just emitted. We do *not* fsync — that would tank latency on
        # Fly volumes and the kernel write-back window is acceptable for
        # an APPI audit trail (we have additional ETL replay on top).
        fh.flush()
        # ``fsync`` can fail on certain filesystems (tmpfs, some network
        # mounts in CI). The ``flush`` above already guarantees the line
        # is in the kernel buffer; we accept the fsync failure rather
        # than abort the response path.
        with contextlib.suppress(OSError):
            os.fsync(fh.fileno())
    return entry


def read_audit_entries(path: Path | str | None = None) -> list[dict[str, Any]]:
    """Read back the audit log as a list of dicts.

    Convenience for tests and post-hoc auditing. NOT intended for the
    response hot path — large log files should be streamed.
    """
    out_path = Path(path) if path is not None else DEFAULT_AUDIT_LOG_PATH
    if not out_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with out_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parsed: dict[str, Any] = json.loads(line)
            rows.append(parsed)
    return rows


__all__ = [
    "AuditEntry",
    "DEFAULT_AUDIT_LOG_PATH",
    "cohort_hash",
    "read_audit_entries",
    "write_audit_entry",
]
