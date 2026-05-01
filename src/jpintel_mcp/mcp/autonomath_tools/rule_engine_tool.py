"""rule_engine_check — R9 unified rule engine MCP tool (2026-04-25).

Consolidates 6 rule corpora previously consumed by 4 disjoint tools into a
single ``rule_engine_check(program_id, applicant_profile, alongside_programs)``
surface. Reads from the view ``am_unified_rule`` (migration 064) which UNION
ALLs:

  jpi_exclusion_rules    181 rows (125 exclude / 17 prerequisite / 15 absolute / 24 misc)
  am_compat_matrix    48,815 rows (compat 21,985 / incompat 3,064 / case 18,917 / unknown 4,849)
  am_combo_calculator     56 rows (legal stacking patterns)
  am_subsidy_rule         44 rows (per-program rate / cap)
  am_tax_rule            145 rows (per-measure rate / cap / period)
  am_validation_rule       6 rows (generic predicates)

Total: 49,247 rule rows behind one tool. The compat_matrix corpus has
4,849 rows with compat_status='unknown' that have not been manually
triaged — those rows surface as judgment='unknown' rather than allow/deny.

Precedence (per R9 §3, hard-coded; first DENY wins, but conflict surfaces):
  1. absolute       (exclusion_rules, kind=absolute)
  2. exclude        (exclusion_rules, kind=exclude)
  3. prerequisite   (exclusion_rules, kind=prerequisite)
  4. compat:incompatible
  5. compat:case_by_case
  6. compat:compatible
  7. combo          (combo_calculator)
  8. subsidy / tax  (informational)
  9. validation     (generic predicates — currently scope=intake only)

Conflict semantics:
  If exclusion_rules.kind=exclude says A+B is forbidden but
  am_compat_matrix.compat_status=compatible says it's OK for the same pair,
  return error.code='rules_conflict' with BOTH rule_ids — never silently
  merge (景表法 fence; see feedback_autonomath_fraud_risk).

Coverage honesty:
  exclusion_rules.program_a uses human Japanese names ("IT導入補助金2025…")
  while am_compat_matrix uses "program:…" canonical IDs. The join is
  currently 0/60 (P0.2 manual mapping pending). The response surfaces
  data_quality.exclusion_join_coverage_pct so callers see the partial
  recall transparently rather than receiving silent misses (this is the
  exact failure mode flagged in feedback_no_fake_data).
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp._http_fallback import (  # === S3 HTTP FALLBACK ===
    detect_fallback_mode_autonomath,
    remote_only_error,
)
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.rule_engine")

# ---------------------------------------------------------------------------
# Precedence ladder. Tuple: (kind_pattern, verdict_when_matched)
# `verdict_when_matched` is the string we emit when this rung fires; "deny"
# halts the cascade unless we already emitted "deny" from a lower rung
# (then we have a conflict).
# ---------------------------------------------------------------------------
_PRECEDENCE: tuple[tuple[str, str], ...] = (
    ("absolute",            "deny"),     # rung 1
    ("exclude",             "deny"),     # rung 2 (covers all exclude:* sub-kinds)
    ("prerequisite",        "deny"),     # rung 3 — prerequisite NOT met = deny
    ("compat:incompatible", "deny"),     # rung 4
    ("compat:case_by_case", "review"),   # rung 5
    ("compat:compatible",   "allow"),    # rung 6
    ("compat:unknown",      "unknown"),  # rung 6.5 (the 4,849-row untriaged bucket)
    ("combo",               "allow"),    # rung 7 — combo presence = legal stacking
    ("subsidy",             "info"),     # rung 8
    ("tax",                 "info"),     # rung 8
    ("validation",          "info"),     # rung 9
)


def _kind_matches(rung: str, actual: str) -> bool:
    """Strict prefix match. Special-case `exclude` to absorb `exclude:*` subkinds
    (the view stores e.g. `exclude:conditional_reduction` for non-absolute
    exclusion variants).
    """
    if rung == "exclude":
        return actual == "exclude" or actual.startswith("exclude:")
    return actual == rung


def _compute_coverage_pct(conn: sqlite3.Connection) -> float:
    """exclusion_join_coverage_pct: fraction of distinct exclusion.program_a
    values that resolve to a compat_matrix.program_a_id. Returns a float
    in [0, 100], rounded to 1 decimal.
    """
    try:
        row = conn.execute(
            """
            SELECT
              CAST(SUM(CASE WHEN program_a IN (
                  SELECT DISTINCT program_a_id FROM am_compat_matrix
              ) THEN 1 ELSE 0 END) AS REAL) AS hit,
              COUNT(DISTINCT program_a) AS denom
            FROM (SELECT DISTINCT program_a FROM jpi_exclusion_rules WHERE program_a IS NOT NULL)
            """
        ).fetchone()
    except sqlite3.Error:
        return 0.0
    denom = row["denom"] or 0
    if not denom:
        return 0.0
    return round(100.0 * (row["hit"] or 0) / denom, 1)


def _fetch_rules_for_pair(
    conn: sqlite3.Connection,
    program_id: str,
    pair_id: str | None,
) -> list[sqlite3.Row]:
    """Return all unified-rule rows where (scope_program_id, pair_program_id)
    overlap the requested pair, in either direction. NULL pair on either side
    is matched too (single-program rules: subsidy / tax / validation /
    absolute / single-program-prerequisite).
    """
    if pair_id is None:
        sql = """
            SELECT rule_id, source_table, scope_program_id, pair_program_id,
                   kind, severity, message_ja, source_url
              FROM am_unified_rule
             WHERE scope_program_id = ?
                OR scope_program_id IS NULL
            """
        return conn.execute(sql, (program_id,)).fetchall()
    sql = """
        SELECT rule_id, source_table, scope_program_id, pair_program_id,
               kind, severity, message_ja, source_url
          FROM am_unified_rule
         WHERE (scope_program_id = ? AND (pair_program_id = ? OR pair_program_id IS NULL))
            OR (scope_program_id = ? AND (pair_program_id = ? OR pair_program_id IS NULL))
            OR scope_program_id IS NULL
        """
    return conn.execute(
        sql, (program_id, pair_id, pair_id, program_id)
    ).fetchall()


def _verdict_for_rule(kind: str) -> str | None:
    """Map a rule's `kind` to its verdict label, or None if outside ladder."""
    for rung, verdict in _PRECEDENCE:
        if _kind_matches(rung, kind):
            return verdict
    return None


def _is_pair_specific(
    row: sqlite3.Row | dict[str, Any],
    program_id: str,
    pair_id: str | None,
) -> bool:
    """True iff this rule's scope+pair tuple binds to the requested
    (program_id, pair_id) pair, in either direction.

    For a specific pair query, only pair-specific rules drive the verdict.
    Global-scope (NULL scope) rules and single-program rules are kept in the
    trace but downgraded to `info` so they don't override the specific pair.
    """
    sp = row["scope_program_id"]
    pp = row["pair_program_id"]
    if pair_id is None:
        # caller asked about a single program; pair-specific = scope matches and pair is NULL
        return sp == program_id and pp is None
    return (
        (sp == program_id and pp == pair_id)
        or (sp == pair_id and pp == program_id)
    )


def _evidence_row(
    row: sqlite3.Row | dict[str, Any],
    program_id: str,
    pair_id: str | None,
) -> dict[str, Any]:
    """Project a unified-rule row into the response evidence shape.

    Effect-downgrade rules (景表法 fence — never silently merge):

    1. A deny verdict from a GLOBAL-scope non-absolute exclude rule
       (scope IS NULL, kind LIKE 'exclude%') is meta-policy advisory and
       surfaces as `info` rather than `deny`. Example: 補助金等適正化法 17 条.
    2. When a specific pair is queried, rules that are NOT pair-specific
       (combo / global compat / single-program subsidy / tax / validation)
       are downgraded to `info` so they don't override the pair-specific
       verdict. They remain in the evidence trace for transparency.
    """
    raw_verdict = _verdict_for_rule(row["kind"]) or "info"
    effect = raw_verdict
    sp = row["scope_program_id"]
    kind = row["kind"]
    # Rule 1: global non-absolute deny → info.
    if raw_verdict == "deny" and sp is None and kind != "absolute":
        effect = "info"
    # Rule 2: when querying a specific pair, downgrade non-pair-specific
    # deny / allow / review verdicts so the pair-specific verdict wins.
    if pair_id is not None and not _is_pair_specific(row, program_id, pair_id):
        if raw_verdict in ("deny", "allow", "review", "unknown") and kind != "absolute":
            effect = "info"
    return {
        "rule_id": row["rule_id"],
        "rule_kind": row["kind"],
        "source": row["source_table"],
        "scope_program_id": row["scope_program_id"],
        "pair_program_id": row["pair_program_id"],
        "severity": row["severity"],
        "message_ja": row["message_ja"],
        "source_url": row["source_url"],
        "effect": effect,
    }


# ---------------------------------------------------------------------------
# Tool definition.
# ---------------------------------------------------------------------------


def _rule_engine_check_impl(
    program_id: str,
    applicant_profile: dict[str, Any] | None = None,
    alongside_programs: list[str] | None = None,
) -> dict[str, Any]:
    """Pure-Python core. Split out from the @mcp.tool wrapper so tests can
    call it directly without the FastMCP decoration shell.
    """
    if not program_id or not isinstance(program_id, str) or not program_id.strip():
        return make_error(
            code="missing_required_arg",
            message="program_id is required (non-empty unified or canonical ID).",
            hint="Pass a `program:…` / `certification:…` / `loan:…` / `tax_measure_…` ID, or a unified human-name token from jpi_exclusion_rules.",
            field="program_id",
            retry_with=["search_programs", "search_certifications"],
        )

    program_id = program_id.strip()
    along: list[str] = [s.strip() for s in (alongside_programs or []) if s and s.strip()]

    try:
        conn = connect_autonomath()
    except FileNotFoundError as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db missing: {exc}",
            hint="Ensure autonomath.db is present at the repo root or AUTONOMATH_DB_PATH.",
            retry_with=["search_programs"],
        )
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db open failed: {exc}",
            retry_with=["search_programs"],
        )

    coverage_pct = _compute_coverage_pct(conn)

    evidence: list[dict[str, Any]] = []
    seen_rule_ids: set[str] = set()
    pairs_to_check: list[str | None] = list(along) if along else [None]

    try:
        for pair_id in pairs_to_check:
            rows = _fetch_rules_for_pair(conn, program_id, pair_id)
            for row in rows:
                if row["rule_id"] in seen_rule_ids:
                    continue
                seen_rule_ids.add(row["rule_id"])
                if _verdict_for_rule(row["kind"]) is None:
                    continue  # outside the precedence ladder; ignore
                evidence.append(_evidence_row(row, program_id, pair_id))
    except sqlite3.Error as exc:
        logger.exception("rule_engine_check query failed")
        return make_error(
            code="db_unavailable",
            message=f"unified-rule query failed: {exc}",
            retry_with=["check_exclusions", "search_tax_incentives"],
        )

    # ---- Precedence resolution ----
    # Group evidence by verdict label. Ladder runs deny → review → allow → unknown → info.
    verdict_groups: dict[str, list[dict[str, Any]]] = {}
    for ev in evidence:
        verdict_groups.setdefault(ev["effect"], []).append(ev)

    deny_rules = verdict_groups.get("deny", [])
    allow_rules = verdict_groups.get("allow", [])
    review_rules = verdict_groups.get("review", [])
    unknown_rules = verdict_groups.get("unknown", [])
    info_rules = verdict_groups.get("info", [])

    # Conflict detection: if both deny and allow rules apply to the SAME
    # ordered pair (program_id, pair_id), return rules_conflict — never
    # silently merge. We compare the pair tuple from each evidence entry.
    if deny_rules and allow_rules and along:
        def _pair_key(ev: dict[str, Any]) -> tuple[str, str] | None:
            sp = ev.get("scope_program_id")
            pp = ev.get("pair_program_id")
            if sp and pp:
                return tuple(sorted([sp, pp]))  # type: ignore[return-value]
            return None

        deny_pairs = {p for p in (_pair_key(e) for e in deny_rules) if p}
        allow_pairs = {p for p in (_pair_key(e) for e in allow_rules) if p}
        conflict_pairs = deny_pairs & allow_pairs
        if conflict_pairs:
            err = make_error(
                code="rules_conflict",
                message=(
                    f"contradictory rule verdicts for program pair: "
                    f"{len(deny_rules)} deny vs {len(allow_rules)} allow."
                ),
                hint="Force human review before applying. Both rule_ids are listed in evidence; do not silently pick one.",
                retry_with=["check_exclusions"],
            )
            err["judgment"] = "conflict"
            err["evidence"] = deny_rules + allow_rules
            err["data_quality"] = {
                "exclusion_join_coverage_pct": coverage_pct,
                "rules_evaluated": len(evidence),
                "rules_total_corpus": 49247,
            }
            err["_disclaimer"] = (
                "Rule verdicts contradict — human (社労士 / 税理士 / 弁護士) "
                "review required. Auto-resolution refused per 景表法 fence."
            )
            return err

    # No conflict → apply ladder.
    if deny_rules:
        judgment = "deny"
    elif review_rules:
        judgment = "review"
    elif allow_rules:
        judgment = "allow"
    elif unknown_rules:
        judgment = "unknown"
    elif info_rules:
        # only informational rules fired (subsidy / tax / validation) — the
        # caller's pair was not directly covered by any deny/allow corpus.
        judgment = "unknown"
    else:
        judgment = "unknown"

    # Confidence heuristic:
    #   1.0 if a deny fired (deny is rule-driven, no joining needed)
    #   0.9 if pure allow
    #   0.7 if review (case_by_case)
    #   0.4 if unknown but corpus had unknown rows
    #   0.2 if no relevant rules at all
    if judgment == "deny":
        confidence = 1.0
    elif judgment == "allow":
        confidence = 0.9
    elif judgment == "review":
        confidence = 0.7
    elif unknown_rules:
        confidence = 0.4
    elif info_rules:
        confidence = 0.3
    else:
        confidence = 0.2

    # Build reason for unknown verdicts (transparency).
    reason: str | None = None
    if judgment == "unknown":
        if unknown_rules:
            reason = (
                f"compat_matrix has compat_status='unknown' for this pair "
                f"({len(unknown_rules)} rows). The 4,849-row unknown bucket "
                f"is pending manual triage."
            )
        elif info_rules:
            reason = (
                "Only informational rules (subsidy/tax/validation) fired; "
                "no exclude/compat verdict in any corpus."
            )
        else:
            reason = (
                f"No matching rule across 49,247 rows. "
                f"exclusion_join_coverage_pct={coverage_pct}% — partial "
                f"recall, manual ID mapping pending (P0.2)."
            )

    out: dict[str, Any] = {
        "judgment": judgment,
        "program_id": program_id,
        "alongside_programs": along,
        "evidence": evidence,
        "confidence": confidence,
        "data_quality": {
            "exclusion_join_coverage_pct": coverage_pct,
            "rules_evaluated": len(evidence),
            "rules_total_corpus": 49247,
        },
        "_disclaimer": (
            "Rule verdicts are derived from primary-source corpora "
            "(noukaweb / monodukuri-hojo / mhlw 等). Not legal/tax advice — "
            "for binding interpretation consult 社労士 / 税理士 / 弁護士. "
            "exclusion_join_coverage<100% means partial recall — silent miss is possible."
        ),
        "total": len(evidence),
        "limit": 100,
        "offset": 0,
        "results": evidence,  # alias so paginated-envelope consumers also work
    }
    if reason:
        out["reason"] = reason
    return out


# Only register the tool when the gate is on. The legacy
# `combined_compliance_check` / `check_exclusions` tools remain registered
# elsewhere (server.py) for compatibility — they will be deprecated post-launch.
if settings.rule_engine_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def rule_engine_check(
        program_id: Annotated[
            str,
            Field(
                description=(
                    "The primary program / certification / tax measure ID to evaluate. "
                    "Accepts `program:…` / `certification:…` / `loan:…` / `tax_measure_…` "
                    "canonical IDs as well as the human-name tokens used by "
                    "jpi_exclusion_rules (e.g. 'keiei-kaishi-shikin')."
                ),
            ),
        ],
        applicant_profile: Annotated[
            dict[str, Any] | None,
            Field(
                default=None,
                description=(
                    "Optional applicant context (prefecture / industry_jsic / "
                    "annual_revenue_yen / business_type). Reserved for future "
                    "validation_rule predicate evaluation; currently not used "
                    "for filtering — present for forward compatibility."
                ),
            ),
        ] = None,
        alongside_programs: Annotated[
            list[str] | None,
            Field(
                default=None,
                description=(
                    "Other program IDs the applicant intends to apply for "
                    "alongside `program_id`. The engine evaluates pairwise "
                    "compat / exclusion rules across all (program_id, alongside[i]) pairs."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """[R9-UNIFIED-RULE-ENGINE] Returns rule evaluation result + applicable law citations across 6 corpora (49,247 rows): exclusion + compat_matrix (48,815 rows, of which 4,849 are 'unknown' status) + combo + subsidy + tax + validation. Output is search-derived; verify primary source for business decisions.

        WHAT: Runs the precedence ladder (absolute → exclude → prerequisite →
        compat:incompatible → compat:case_by_case → compat:compatible → combo →
        subsidy/tax → validation) over the unified view ``am_unified_rule`` and
        returns a single verdict + per-rule trace. First DENY wins, BUT
        contradictions between corpora surface as ``error.code='rules_conflict'``
        with both rule_ids — never silently merged.

        WHEN:
          - 「program A と program B を併給できる?」(pairwise compat)
          - 「この補助金、申請して大丈夫?(他制度との衝突は?)」
          - Pairwise compat lookup against the compat_matrix corpus.
          - Replace the 5 disjoint legacy tools (check_exclusions /
            combined_compliance_check / get_am_tax_rule / search_certifications /
            list_open_programs) with one call.

        WHEN NOT:
          - Free-text discovery → use search_programs first, then pass the
            resulting program_id here.
          - The full ruleset list of all 49,247 rows (no program filter) →
            this tool requires a program_id.

        RETURNS:
          {
            judgment: "allow" | "deny" | "review" | "unknown" | "conflict",
            program_id: str,
            alongside_programs: list[str],
            evidence: [
              {
                rule_id, rule_kind, source ∈ {jpi_exclusion_rules,
                am_compat_matrix, am_combo_calculator, am_subsidy_rule,
                am_tax_rule, am_validation_rule},
                scope_program_id, pair_program_id, severity, message_ja,
                source_url, effect ∈ {deny, allow, review, unknown, info}
              }, ...
            ],
            confidence: 0.0-1.0,
            data_quality: {
              exclusion_join_coverage_pct: float (0-100, currently 0% pending
                                                   P0.2 manual mapping),
              rules_evaluated: int,
              rules_total_corpus: 49247
            },
            reason?: str (when judgment=unknown — explains why),
            _disclaimer: str (景表法 fence + 社労士/税理士/弁護士 advisory),
            error?: { code: "rules_conflict", evidence: [both rules] }
          }

        DATA QUALITY HONESTY: jpi_exclusion_rules.program_a uses Japanese
        human names while am_compat_matrix uses canonical IDs. Cross-corpus
        join coverage is currently ~0% (60 distinct human names, 0 mapped).
        The response surfaces ``data_quality.exclusion_join_coverage_pct`` so
        callers see partial recall transparently rather than receiving silent
        misses (景表法 / fraud-risk fence).

        CHAIN:
          ← `search_programs` / `search_certifications` supply program_id.
          → `get_program(unified_id)` for the program detail view.
          → `get_am_tax_rule(measure)` for tax_rule depth.
          → Use `check_exclusions` (legacy) only when this tool returns
            error.code='subsystem_unavailable' or for backward compatibility.
        """
        # === S3 HTTP FALLBACK ===
        # No REST endpoint mirrors rule_engine_check today — the
        # 49,247-row evaluator is local-DB only. Surface remote_only so
        # the caller is told to install the full DB (clone) instead of
        # silently returning "unknown" with no evidence.
        if detect_fallback_mode_autonomath():
            return remote_only_error("rule_engine_check")
        # === END S3 HTTP FALLBACK ===
        return _rule_engine_check_impl(
            program_id=program_id,
            applicant_profile=applicant_profile,
            alongside_programs=alongside_programs,
        )


# ---------------------------------------------------------------------------
# Self-test harness (not part of the MCP surface).
#
#   .venv/bin/python -m jpintel_mcp.mcp.autonomath_tools.rule_engine_tool
# ---------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import pprint

    samples = [
        # 1) Unknown bucket — caller passes a program_id with no rule coverage.
        {
            "program_id": "program:nonexistent:000000",
            "alongside_programs": None,
        },
        # 2) Pair from compat_matrix — incompat case.
        {
            "program_id": "program:04_program_documents:000000:23_25d25bdfe8",
            "alongside_programs": [
                "program:04_program_documents:000016:IT2026_b030eaea36",
            ],
        },
        # 3) Pair from compat_matrix — compatible case.
        {
            "program_id": "program:04_program_documents:000000:23_25d25bdfe8",
            "alongside_programs": [
                "program:04_program_documents:000084:fb855051af",
            ],
        },
    ]
    for s in samples:
        print(f"\n=== {s} ===")
        res = _rule_engine_check_impl(**s)  # type: ignore[arg-type]
        pprint.pprint({
            "judgment": res.get("judgment"),
            "confidence": res.get("confidence"),
            "evidence_count": len(res.get("evidence", [])),
            "reason": res.get("reason"),
            "data_quality": res.get("data_quality"),
        })
