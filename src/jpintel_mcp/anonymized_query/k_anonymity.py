"""k-anonymity floor enforcement for dim N anonymized queries.

The k=5 floor is a **module constant**, not a query parameter and not an
env var. Per ``feedback_anonymized_query_pii_redact``::

    "k=5 hard cap は初期から enforce"
    "個情法逸脱は事業終焉なので k=5 hard cap 絶対"

Bumping the floor (e.g. to k=10 for a stricter cohort) is a code change
+ PR review, not runtime config. Lowering it is forbidden — a regression
would expose single-entity rows under the guise of "anonymized" output.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# Module constant. Treat as a literal-typed Final so mypy --strict flags
# accidental rebinds (e.g. K_ANONYMITY_MIN = 3) at call sites.
K_ANONYMITY_MIN: Final[int] = 5


@dataclass(frozen=True, slots=True)
class KAnonymityResult:
    """Outcome of a k-anonymity check.

    Attributes
    ----------
    ok:
        ``True`` iff ``cohort_size >= K_ANONYMITY_MIN``.
    reason:
        Stable machine-readable reason code (``cohort_too_small`` /
        ``negative_cohort`` / ``ok``). Suitable for surfacing to clients
        and for joining against the audit log.
    cohort_size:
        The integer evaluated. Echoed back for log convenience.
    """

    ok: bool
    reason: str
    cohort_size: int


def check_k_anonymity(cohort_size: int, *, floor: int = K_ANONYMITY_MIN) -> KAnonymityResult:
    """Verify a cohort meets the k-anonymity floor.

    Parameters
    ----------
    cohort_size:
        Number of underlying entities aggregated. Must be an ``int``.
    floor:
        Optional override **for raising the floor only**. The check
        rejects any value below :data:`K_ANONYMITY_MIN` with a
        ``ValueError`` so a caller cannot silently drop below the
        compliance floor at runtime.

    Returns
    -------
    KAnonymityResult
        The structured result. Inspect ``.ok`` for the gate decision;
        ``.reason`` is stable for the audit log.

    Raises
    ------
    ValueError
        If ``floor < K_ANONYMITY_MIN`` (compliance regression guard).
    TypeError
        If ``cohort_size`` is not an ``int``.
    """
    if not isinstance(cohort_size, int) or isinstance(cohort_size, bool):
        # Note: ``bool`` is an ``int`` subclass in Python, so we exclude
        # it explicitly — a stray ``True`` would otherwise be treated as
        # a 1-entity cohort and pass our type check.
        raise TypeError(
            f"cohort_size must be int (got {type(cohort_size).__name__})",
        )
    if floor < K_ANONYMITY_MIN:
        raise ValueError(
            f"k-anonymity floor cannot be lowered below {K_ANONYMITY_MIN} "
            f"(got {floor}); see feedback_anonymized_query_pii_redact "
            "for the absolute floor rationale.",
        )
    if cohort_size < 0:
        return KAnonymityResult(ok=False, reason="negative_cohort", cohort_size=cohort_size)
    if cohort_size < floor:
        return KAnonymityResult(ok=False, reason="cohort_too_small", cohort_size=cohort_size)
    return KAnonymityResult(ok=True, reason="ok", cohort_size=cohort_size)


__all__ = ["K_ANONYMITY_MIN", "KAnonymityResult", "check_k_anonymity"]
