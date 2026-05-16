"""jpcite output safety scanners.

These scanners are **file-based, no-API-call** regression gates for JPCIR
envelope output safety. They are invoked from CI (release gates), the AWS
credit-run incident response loop (§5 of
``docs/_internal/aws_jpcite_master_execution_plan_2026-05-15.md`` and §9.9 of
``docs/_internal/aws_credit_review_16_incident_stop.md``), and the launch
operator playbook.

Two complementary scanners:

* :mod:`no_hit_regression` — verifies every ``no_hit`` result inside a JPCIR
  envelope is paired with a ``known_gaps[].code = no_hit_not_absence`` so the
  ``no_hit_not_absence`` invariant cannot drift to "result not found = does
  not exist".
* :mod:`forbidden_claim` — flags forbidden English wording
  (``eligible`` / ``safe`` / ``no issue`` / ``no violation`` /
  ``permission not required`` / ``credit score`` / ``trustworthy`` /
  ``proved absent``) and Japanese equivalents
  (``問題ありません`` / ``適格`` / ``適合`` / ``許可不要`` / ``申請不要`` /
  ``免税``) inside output text. The allowed-wording set
  (``candidate_priority`` / ``public_evidence_attention`` /
  ``evidence_quality`` / ``coverage_gap`` / ``needs_review`` /
  ``not_enough_public_evidence`` / ``no_hit_not_absence`` /
  ``professional_review_caveat``) is whitelisted and must not be flagged
  even when it contains a forbidden substring.

Both scanners return structured :class:`Violation` records so a CLI / CI
runner can fail the build with a packet-level diagnostic.
"""

from __future__ import annotations

from .forbidden_claim import (
    ALLOWED_WORDING,
    FORBIDDEN_JA,
    FORBIDDEN_WORDING,
    scan_forbidden_claims,
    scan_forbidden_claims_in_file,
)
from .no_hit_regression import (
    NO_HIT_NOT_ABSENCE_CODE,
    Violation,
    scan_no_hit_regressions,
    scan_no_hit_regressions_in_file,
)

__all__ = [
    "ALLOWED_WORDING",
    "FORBIDDEN_JA",
    "FORBIDDEN_WORDING",
    "NO_HIT_NOT_ABSENCE_CODE",
    "Violation",
    "scan_forbidden_claims",
    "scan_forbidden_claims_in_file",
    "scan_no_hit_regressions",
    "scan_no_hit_regressions_in_file",
]
