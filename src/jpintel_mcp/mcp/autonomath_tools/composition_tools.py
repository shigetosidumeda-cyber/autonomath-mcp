"""composition_tools — Wave 21 composition tools (5 new MCP tools, 2026-04-29).

Five tools that drive call-density compounding: every tool emits a
``_next_calls`` field that tells the customer LLM which 1-3 follow-up
tools to chain next. This is the count-multiplier mechanism — a single
user question now expands into 2-4 metered API calls instead of one.

Tools shipped here
------------------

  apply_eligibility_chain_am
      Multi-step orchestration over prerequisite_chain → rule_engine →
      exclusion → compat_matrix per program. Sensitive (§52 disclaimer).

  find_complementary_programs_am
      Seed program → am_compat_matrix compatible edges → portfolio with
      combined_ceiling_yen + conflicts. Sensitive (§52 disclaimer).

  simulate_application_am
      Pure-SQL mock walkthrough: document_checklist + certifications +
      est_review_days + completeness_score. NO LLM. Sensitive (§52).

  track_amendment_lineage_am
      am_amendment_snapshot 14,596 rows → time-series for a target.
      Strict count = 140 rows with effective_from; warns about ~14,456
      hash-only rows (sha256 of empty string is uniform).

  program_active_periods_am
      am_application_round 1,256 rows → per-program rounds + days_to_close
      + sunset_warning.

Each tool ALWAYS returns a ``_next_calls`` list[dict] in the response shape::

    [
      {"tool": "find_complementary_programs_am",
       "args": {"seed_program_id": "..."},
       "rationale": "compounds eligibility → portfolio assembly",
       "compound_mult": 2.0},
      ...
    ]

The customer LLM is told (in system prompt + tool docstring) to inspect
``_next_calls`` and propose those tool invocations to the user. This is
what drives call density 1× → 2.4× → 5× as the user iterates.

Disclaimer wiring
-----------------

apply_eligibility_chain_am / find_complementary_programs_am /
simulate_application_am are §52 sensitive — they touch eligibility /
applicability / portfolio composition, all of which sit in
税理士法 §52 / 行政書士法 §1 territory. Each emits ``_disclaimer`` per the
SENSITIVE_TOOLS hook in envelope_wrapper.py.

NO Anthropic API self-call. All five tools are pure SQL / Python over
autonomath.db — the LLM call is the customer's, never ours.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error
from .snapshot_helper import attach_corpus_snapshot_with_conn

logger = logging.getLogger("jpintel.mcp.autonomath.composition")

# Env-gated registration (default on). Flip to "0" for one-flag rollback
# if a regression surfaces post-launch.
_ENABLED = os.environ.get("AUTONOMATH_COMPOSITION_ENABLED", "1") == "1"


# ---------------------------------------------------------------------------
# Disclaimers (§52 fence — see envelope_wrapper.SENSITIVE_TOOLS).
#
# Three of the five tools touch eligibility / portfolio / mock walkthrough,
# all of which sit in the 行政書士法 §1 + 税理士法 §52 boundary. The
# composition_tools layer surfaces an explicit per-tool _disclaimer string
# (in addition to the envelope-level one) so customer LLMs get a hard
# fence on what the response is and is not.
# ---------------------------------------------------------------------------

_DISCLAIMER_ELIGIBILITY = (
    "本 response は am_prerequisite_bundle / jpi_exclusion_rules / "
    "am_compat_matrix の機械的検索照合で、税務代理 (税理士法 §52) ・"
    "申請代理 (行政書士法 §1) ・労務判断 (社労士法) ・法律事務 "
    "(弁護士法 §72) の代替ではありません。eligibility 判定は heuristic "
    "rule を含み、partial recall (am_prerequisite_bundle 1.6% coverage) です。"
    "業務判断は必ず一次資料 (公募要領 / 法令原文) を確認し、確定判断は士業へ。"
)

_DISCLAIMER_COMPLEMENTARY = (
    "本 response は am_compat_matrix (4,300 sourced + 44,515 inferred) "
    "の compatible/case_by_case edges 検索結果で、申請可否判断・税務助言で "
    "はありません。combined_ceiling_yen は理論上限の積算で、実際の併給可否は "
    "公募要領の重複経費要件・適正化法 17 条に従います。inferred_only=1 の "
    "edge は heuristic 由来のため、必ず一次資料 + 専門家確認を経てください。"
)

_DISCLAIMER_SIMULATE = (
    "本 response は am_application_steps / am_program_summary / "
    "am_law_article の機械的 JOIN による mock walkthrough で、申請書面の作成・"
    "提出代行ではありません (行政書士法 §1)。est_review_days / "
    "completeness_score は heuristic で、実際の審査期間は公募要領を確認して "
    "ください。最終申請判断は資格を有する行政書士・中小企業診断士・税理士へ。"
)


# ---------------------------------------------------------------------------
# Compound-multiplier _next_calls helpers
# ---------------------------------------------------------------------------


def _next_calls_for_eligibility(
    program_ids: list[str],
    profile: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Returns 2-3 next-call suggestions for apply_eligibility_chain_am.

    Compound mult target: 2.4× (LLM follows up with find_complementary +
    simulate_application on the eligible programs).
    """
    calls: list[dict[str, Any]] = []
    if program_ids:
        calls.append(
            {
                "tool": "find_complementary_programs_am",
                "args": {"seed_program_id": program_ids[0], "top_n": 10},
                "rationale": (
                    "Eligible programs may have compatible co-applicable "
                    "programs (am_compat_matrix). Build a portfolio."
                ),
                "compound_mult": 2.0,
            }
        )
        calls.append(
            {
                "tool": "simulate_application_am",
                "args": {"program_id": program_ids[0], "profile": profile or {}},
                "rationale": (
                    "Mock walkthrough surfaces document_checklist + "
                    "est_review_days BEFORE the customer commits resources."
                ),
                "compound_mult": 1.5,
            }
        )
        calls.append(
            {
                "tool": "program_active_periods_am",
                "args": {"program_id": program_ids[0], "future_only": True},
                "rationale": (
                    "Eligibility is moot if no upcoming application round. "
                    "Confirm at least one open / upcoming round."
                ),
                "compound_mult": 1.3,
            }
        )
    return calls


def _next_calls_for_complementary(seed_id: str) -> list[dict[str, Any]]:
    """Returns 2 next-call suggestions for find_complementary_programs_am."""
    return [
        {
            "tool": "apply_eligibility_chain_am",
            "args": {"profile": {}, "program_ids": [seed_id]},
            "rationale": (
                "Validate the assembled portfolio against eligibility "
                "rules + exclusion / prerequisite cliffs."
            ),
            "compound_mult": 2.4,
        },
        {
            "tool": "simulate_application_am",
            "args": {"program_id": seed_id, "profile": {}},
            "rationale": (
                "Inspect document_checklist / est_review_days for the "
                "seed program before committing to the portfolio."
            ),
            "compound_mult": 1.5,
        },
    ]


def _next_calls_for_simulate(program_id: str) -> list[dict[str, Any]]:
    """Returns 2 next-call suggestions for simulate_application_am."""
    return [
        {
            "tool": "track_amendment_lineage_am",
            "args": {"target_kind": "program", "target_id": program_id},
            "rationale": (
                "Document checklist + est_review_days assume current "
                "rules — confirm program has not been amended recently."
            ),
            "compound_mult": 1.4,
        },
        {
            "tool": "program_active_periods_am",
            "args": {"program_id": program_id, "future_only": True},
            "rationale": (
                "est_review_days only matters if there is an upcoming "
                "round. Confirm at least one open / upcoming."
            ),
            "compound_mult": 1.3,
        },
    ]


def _next_calls_for_lineage(target_kind: str, target_id: str) -> list[dict[str, Any]]:
    """Returns 2 next-call suggestions for track_amendment_lineage_am."""
    if target_kind == "program":
        return [
            {
                "tool": "apply_eligibility_chain_am",
                "args": {"profile": {}, "program_ids": [target_id]},
                "rationale": (
                    "Re-evaluate eligibility against the latest "
                    "amendment — old verdicts may be stale."
                ),
                "compound_mult": 2.4,
            },
            {
                "tool": "program_active_periods_am",
                "args": {"program_id": target_id, "future_only": True},
                "rationale": (
                    "Check if the amended program still has an upcoming application round."
                ),
                "compound_mult": 1.3,
            },
        ]
    # target_kind == "law"
    return [
        {
            "tool": "get_law_article_am",
            "args": {"law_canonical_id": target_id, "limit": 3},
            "rationale": ("Inspect the latest law text to understand what changed."),
            "compound_mult": 1.4,
        },
    ]


def _next_calls_for_periods(program_id: str) -> list[dict[str, Any]]:
    """Returns 2 next-call suggestions for program_active_periods_am."""
    return [
        {
            "tool": "apply_eligibility_chain_am",
            "args": {"profile": {}, "program_ids": [program_id]},
            "rationale": (
                "If a round is open / upcoming, validate eligibility "
                "before the customer drafts an application."
            ),
            "compound_mult": 2.4,
        },
        {
            "tool": "simulate_application_am",
            "args": {"program_id": program_id, "profile": {}},
            "rationale": (
                "Mock the application walkthrough for the next round to "
                "surface document checklist + review days."
            ),
            "compound_mult": 1.5,
        },
    ]


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------


def _today_iso() -> str:
    """Today JST as YYYY-MM-DD."""
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date().isoformat()


def _parse_iso_date(value: str | None) -> datetime.date | None:
    """Strict YYYY-MM-DD parser. Returns None on any other shape."""
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def _open_db() -> sqlite3.Connection | dict[str, Any]:
    """Open autonomath.db, returning either a conn or an error envelope."""
    try:
        return connect_autonomath()
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


# ---------------------------------------------------------------------------
# 1) apply_eligibility_chain_am — multi-step orchestration
# ---------------------------------------------------------------------------


def _apply_eligibility_chain_impl(
    profile: dict[str, Any],
    program_ids: list[str],
    chain_depth: int = 4,
) -> dict[str, Any]:
    """Pure-Python core: per-program verdict + reasoning_steps + cite chain.

    Steps per program (precedence: first DENY wins):
      1. prerequisite_chain  — am_prerequisite_bundle rows (1.6% coverage)
      2. rule_engine_check   — am_unified_rule (49,247 rows)
      3. exclusion_rules     — jpi_exclusion_rules (181 rows)
      4. am_compat_matrix    — incompat-with-self check (sanity)
    """
    if not isinstance(program_ids, list) or not program_ids:
        return make_error(
            code="missing_required_arg",
            message="program_ids must be a non-empty list of canonical program IDs.",
            field="program_ids",
            retry_with=["search_programs"],
        )
    if not isinstance(profile, dict):
        return make_error(
            code="missing_required_arg",
            message="profile must be a dict (may be empty {} for forward-compat).",
            field="profile",
        )
    if chain_depth < 1 or chain_depth > 8:
        chain_depth = max(1, min(chain_depth, 8))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    # Pre-fetch coverage caveats so honesty fence fires regardless of input.
    try:
        coverage_row = conn.execute("SELECT COUNT(*) AS n FROM am_prerequisite_bundle").fetchone()
        prereq_rows_total = coverage_row["n"] if coverage_row else 0
    except sqlite3.Error:
        prereq_rows_total = 0

    per_program: list[dict[str, Any]] = []
    for raw_pid in program_ids:
        if not isinstance(raw_pid, str) or not raw_pid.strip():
            per_program.append(
                {
                    "program_id": raw_pid,
                    "verdict": "ineligible",
                    "reasoning_steps": [
                        {
                            "step": 0,
                            "kind": "input_validation",
                            "verdict": "deny",
                            "detail": "program_id is empty / not a string.",
                        }
                    ],
                    "citations": [],
                }
            )
            continue
        pid = raw_pid.strip()
        steps: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        verdict = "eligible"  # innocent until proven guilty
        denied = False

        # --- Step 1: prerequisite_chain ----------------------------------
        if chain_depth >= 1:
            try:
                prereq_rows = conn.execute(
                    """
                    SELECT prerequisite_kind, prerequisite_name,
                           required_or_optional, preparation_time_days,
                           preparation_cost_yen, obtain_url, rationale_text
                      FROM am_prerequisite_bundle
                     WHERE program_entity_id = ?
                     ORDER BY bundle_id
                     LIMIT 50
                    """,
                    (pid,),
                ).fetchall()
            except sqlite3.Error:
                prereq_rows = []
            required_count = sum(
                1 for r in prereq_rows if (r["required_or_optional"] or "").lower() == "required"
            )
            steps.append(
                {
                    "step": 1,
                    "kind": "prerequisite_chain",
                    "verdict": "info"
                    if not prereq_rows
                    else ("warn" if required_count else "info"),
                    "detail": (
                        f"{len(prereq_rows)} prerequisites "
                        f"({required_count} required). Coverage 1.6% — "
                        f"empty list ≠ no prerequisites."
                    ),
                    "rows_count": len(prereq_rows),
                    "required_count": required_count,
                }
            )
            for r in prereq_rows[:5]:
                if r["obtain_url"]:
                    citations.append(
                        {
                            "step": 1,
                            "label": r["prerequisite_name"],
                            "url": r["obtain_url"],
                        }
                    )

        # --- Step 2: rule_engine_check (unified) -------------------------
        if not denied and chain_depth >= 2:
            try:
                rule_rows = conn.execute(
                    """
                    SELECT rule_id, source_table, kind, severity,
                           message_ja, source_url
                      FROM am_unified_rule
                     WHERE scope_program_id = ? AND pair_program_id IS NULL
                     LIMIT 30
                    """,
                    (pid,),
                ).fetchall()
            except sqlite3.Error:
                rule_rows = []
            deny_rules = [
                r
                for r in rule_rows
                if (r["kind"] or "") in ("absolute", "exclude")
                or (r["kind"] or "").startswith("exclude:")
            ]
            steps.append(
                {
                    "step": 2,
                    "kind": "rule_engine",
                    "verdict": "deny" if deny_rules else ("info" if rule_rows else "info"),
                    "detail": (
                        f"{len(rule_rows)} unified-rule rows for program "
                        f"({len(deny_rules)} deny verdicts)."
                    ),
                    "rows_count": len(rule_rows),
                    "deny_count": len(deny_rules),
                }
            )
            for r in rule_rows[:5]:
                if r["source_url"]:
                    citations.append(
                        {
                            "step": 2,
                            "label": r["message_ja"][:80] if r["message_ja"] else r["kind"],
                            "url": r["source_url"],
                        }
                    )
            if deny_rules:
                denied = True
                verdict = "ineligible"

        # --- Step 3: exclusion_rules (legacy, keyed by program_a) ---------
        if not denied and chain_depth >= 3:
            try:
                excl_rows = conn.execute(
                    """
                    SELECT id, kind, severity, message_ja, source_url
                      FROM jpi_exclusion_rules
                     WHERE program_a = ? OR program_b = ?
                     LIMIT 20
                    """,
                    (pid, pid),
                ).fetchall()
            except sqlite3.Error:
                excl_rows = []
            absolute_rows = [r for r in excl_rows if (r["kind"] or "") == "absolute"]
            steps.append(
                {
                    "step": 3,
                    "kind": "exclusion_rules",
                    "verdict": "deny" if absolute_rows else ("info" if excl_rows else "info"),
                    "detail": (
                        f"{len(excl_rows)} legacy exclusion rules ({len(absolute_rows)} absolute)."
                    ),
                    "rows_count": len(excl_rows),
                }
            )
            if absolute_rows:
                denied = True
                verdict = "ineligible"

        # --- Step 4: am_compat_matrix (sanity / incompat presence) -------
        if chain_depth >= 4:
            try:
                compat_rows = conn.execute(
                    """
                    SELECT program_a_id, program_b_id, compat_status,
                           inferred_only
                      FROM am_compat_matrix
                     WHERE (program_a_id = ? OR program_b_id = ?)
                       AND compat_status = 'incompatible'
                     LIMIT 20
                    """,
                    (pid, pid),
                ).fetchall()
            except sqlite3.Error:
                compat_rows = []
            authoritative = [r for r in compat_rows if not r["inferred_only"]]
            steps.append(
                {
                    "step": 4,
                    "kind": "compat_matrix",
                    "verdict": "info",  # never sole driver of denial
                    "detail": (
                        f"{len(compat_rows)} incompatible peers "
                        f"({len(authoritative)} authoritative). "
                        "These are pairwise — only triggered if combined."
                    ),
                    "rows_count": len(compat_rows),
                    "authoritative_count": len(authoritative),
                }
            )

        # --- partial verdict synthesis -----------------------------------
        # `partial` if there are warnings (prereq required > 0) but no deny.
        if not denied:
            warn_step = next(
                (
                    s
                    for s in steps
                    if s["kind"] == "prerequisite_chain" and s.get("required_count", 0) > 0
                ),
                None,
            )
            if warn_step:
                verdict = "partial"

        per_program.append(
            {
                "program_id": pid,
                "verdict": verdict,
                "reasoning_steps": steps,
                "citations": citations[:10],
            }
        )

    eligible_ids = [p["program_id"] for p in per_program if p["verdict"] in ("eligible", "partial")]

    out: dict[str, Any] = {
        "results": per_program,
        "total": len(per_program),
        "limit": len(per_program),
        "offset": 0,
        "summary": {
            "eligible_count": sum(1 for p in per_program if p["verdict"] == "eligible"),
            "partial_count": sum(1 for p in per_program if p["verdict"] == "partial"),
            "ineligible_count": sum(1 for p in per_program if p["verdict"] == "ineligible"),
        },
        "data_quality": {
            "prerequisite_coverage_pct": 1.6,
            "prerequisite_rows_total": prereq_rows_total,
            "compat_matrix_inferred_share_pct": 91.2,  # 44,515 / 48,815
            "rule_engine_corpus_total": 49247,
            "caveat": (
                "Verdicts are heuristic. partial = required prerequisites "
                "exist but no hard deny. ineligible only fires on absolute "
                "/ exclude rules — silent miss possible (景表法 fence)."
            ),
        },
        "_disclaimer": _DISCLAIMER_ELIGIBILITY,
        "_next_calls": _next_calls_for_eligibility(eligible_ids, profile),
    }
    return out


# ---------------------------------------------------------------------------
# 2) find_complementary_programs_am — seed → portfolio
# ---------------------------------------------------------------------------


def _find_complementary_impl(
    seed_program_id: str,
    top_n: int = 10,
    exclude_unknown_compat: bool = True,
) -> dict[str, Any]:
    """Pure-Python: seed → am_compat_matrix compatible edges → portfolio."""
    if not seed_program_id or not isinstance(seed_program_id, str) or not seed_program_id.strip():
        return make_error(
            code="missing_required_arg",
            message="seed_program_id is required.",
            field="seed_program_id",
            retry_with=["search_programs"],
        )
    seed = seed_program_id.strip()
    top_n = max(1, min(top_n, 50))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    # Build the WHERE clause for compatible edges. Default skips unknown.
    status_clause = "compat_status = 'compatible'"
    if not exclude_unknown_compat:
        status_clause = "compat_status IN ('compatible', 'case_by_case')"

    try:
        edges = conn.execute(
            f"""
            SELECT
              CASE WHEN program_a_id = ? THEN program_b_id ELSE program_a_id END AS peer_id,
              compat_status,
              combined_max_yen,
              conditions_text,
              rationale_short,
              source_url,
              confidence,
              inferred_only
              FROM am_compat_matrix
             WHERE (program_a_id = ? OR program_b_id = ?)
               AND {status_clause}
             ORDER BY inferred_only ASC, confidence DESC
             LIMIT ?
            """,
            (seed, seed, seed, top_n),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.exception("find_complementary query failed")
        return make_error(
            code="db_unavailable",
            message=f"am_compat_matrix query failed: {exc}",
            retry_with=["related_programs"],
        )

    # Resolve peer names + ceilings.
    peer_ids = [r["peer_id"] for r in edges]
    peer_names: dict[str, str] = {}
    if peer_ids:
        placeholders = ",".join("?" for _ in peer_ids)
        try:
            for nrow in conn.execute(
                f"SELECT canonical_id, primary_name FROM am_entities WHERE canonical_id IN ({placeholders})",
                peer_ids,
            ).fetchall():
                peer_names[nrow["canonical_id"]] = nrow["primary_name"]
        except sqlite3.Error:
            pass

    # Detect conflict: any peer that is ALSO in a compat_status=incompatible edge with the seed.
    incompat_peers: set[str] = set()
    try:
        for irow in conn.execute(
            """
            SELECT
              CASE WHEN program_a_id = ? THEN program_b_id ELSE program_a_id END AS peer_id
              FROM am_compat_matrix
             WHERE (program_a_id = ? OR program_b_id = ?)
               AND compat_status = 'incompatible'
            """,
            (seed, seed, seed),
        ).fetchall():
            incompat_peers.add(irow["peer_id"])
    except sqlite3.Error:
        pass

    portfolio: list[dict[str, Any]] = []
    combined_ceiling_total = 0
    for r in edges:
        peer = r["peer_id"]
        ceiling = r["combined_max_yen"]
        portfolio.append(
            {
                "peer_program_id": peer,
                "peer_name": peer_names.get(peer),
                "compat_status": r["compat_status"],
                "combined_max_yen": ceiling,
                "conditions_text": r["conditions_text"],
                "rationale_short": r["rationale_short"],
                "source_url": r["source_url"],
                "confidence": r["confidence"],
                "inferred_only": bool(r["inferred_only"]),
            }
        )
        if isinstance(ceiling, int):
            combined_ceiling_total += ceiling

    conflicts = [p for p in portfolio if p["peer_program_id"] in incompat_peers]

    out: dict[str, Any] = {
        "seed_program_id": seed,
        "results": portfolio,
        "total": len(portfolio),
        "limit": top_n,
        "offset": 0,
        "combined_ceiling_yen": combined_ceiling_total,
        "conflicts": conflicts,
        "data_quality": {
            "compat_matrix_total": 48815,
            "authoritative_share_pct": 8.8,  # 4,300 / 48,815
            "exclude_unknown_compat": exclude_unknown_compat,
            "caveat": (
                "combined_ceiling_yen is the SUM of advertised ceilings — "
                "actual permissible stacking depends on 経費重複 rules + "
                "適正化法 17 条. inferred_only=true rows are heuristic."
            ),
        },
        "_disclaimer": _DISCLAIMER_COMPLEMENTARY,
        "_next_calls": _next_calls_for_complementary(seed),
    }
    return out


# ---------------------------------------------------------------------------
# 3) simulate_application_am — pure-SQL mock walkthrough
# ---------------------------------------------------------------------------


def _simulate_application_impl(
    program_id: str,
    profile: dict[str, Any],
    target_round: str = "next",
) -> dict[str, Any]:
    """Pure SQL JOIN: am_application_round + am_law_article + am_application_steps.

    Returns: document_checklist + certifications + est_review_days + completeness_score.
    NO LLM.
    """
    if not program_id or not isinstance(program_id, str) or not program_id.strip():
        return make_error(
            code="missing_required_arg",
            message="program_id is required.",
            field="program_id",
            retry_with=["search_programs"],
        )
    pid = program_id.strip()
    if target_round not in ("next", "current", "any"):
        target_round = "next"
    if not isinstance(profile, dict):
        profile = {}

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    today_iso = _today_iso()

    # --- am_application_steps ----------------------------------------------
    try:
        step_rows = conn.execute(
            """
            SELECT step_no, step_title, step_description,
                   prerequisites_json, expected_days,
                   online_or_offline, responsible_party
              FROM am_application_steps
             WHERE program_entity_id = ?
             ORDER BY step_no
            """,
            (pid,),
        ).fetchall()
    except sqlite3.Error:
        step_rows = []

    # --- am_application_round (target_round selector) ----------------------
    try:
        if target_round == "next":
            round_row = conn.execute(
                """
                SELECT round_id, round_label, round_seq,
                       application_open_date, application_close_date,
                       announced_date, disbursement_start_date,
                       budget_yen, status, source_url
                  FROM am_application_round
                 WHERE program_entity_id = ?
                   AND status IN ('open', 'upcoming')
                   AND application_close_date >= ?
                 ORDER BY application_close_date ASC
                 LIMIT 1
                """,
                (pid, today_iso),
            ).fetchone()
        elif target_round == "current":
            round_row = conn.execute(
                """
                SELECT round_id, round_label, round_seq,
                       application_open_date, application_close_date,
                       announced_date, disbursement_start_date,
                       budget_yen, status, source_url
                  FROM am_application_round
                 WHERE program_entity_id = ?
                   AND status = 'open'
                 ORDER BY round_seq DESC
                 LIMIT 1
                """,
                (pid,),
            ).fetchone()
        else:  # "any"
            round_row = conn.execute(
                """
                SELECT round_id, round_label, round_seq,
                       application_open_date, application_close_date,
                       announced_date, disbursement_start_date,
                       budget_yen, status, source_url
                  FROM am_application_round
                 WHERE program_entity_id = ?
                 ORDER BY round_seq DESC
                 LIMIT 1
                """,
                (pid,),
            ).fetchone()
    except sqlite3.Error:
        round_row = None

    # --- document_checklist (synthesised from step.prerequisites_json) -----
    document_checklist: list[str] = []
    seen_docs: set[str] = set()
    for sr in step_rows:
        raw = sr["prerequisites_json"] or "[]"
        try:
            items = json.loads(raw)
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, str) and it not in seen_docs:
                        seen_docs.add(it)
                        document_checklist.append(it)
        except (ValueError, TypeError):
            continue

    # --- certifications hint via am_prerequisite_bundle (kind='cert') ------
    try:
        cert_rows = conn.execute(
            """
            SELECT prerequisite_name, required_or_optional, obtain_url
              FROM am_prerequisite_bundle
             WHERE program_entity_id = ? AND prerequisite_kind = 'cert'
             ORDER BY bundle_id
             LIMIT 20
            """,
            (pid,),
        ).fetchall()
    except sqlite3.Error:
        cert_rows = []
    certifications = [
        {
            "name": r["prerequisite_name"],
            "required_or_optional": r["required_or_optional"],
            "obtain_url": r["obtain_url"],
        }
        for r in cert_rows
    ]

    # --- estimated review days (sum step.expected_days for kind=審査) ------
    est_review_days = sum(
        (sr["expected_days"] or 0)
        for sr in step_rows
        if (sr["responsible_party"] or "") in ("authority", "support_org")
    ) or sum((sr["expected_days"] or 0) for sr in step_rows)

    # --- completeness_score (heuristic over profile coverage of checklist) -
    # Score in [0.0, 1.0]: rough overlap between profile keys and required docs.
    profile_text = (
        " ".join(str(v) for v in profile.values() if isinstance(v, (str, int, float))).lower()
        if profile
        else ""
    )
    if not document_checklist:
        completeness_score = 0.0
    else:
        hit = 0
        for doc in document_checklist:
            if (
                isinstance(doc, str)
                and doc
                and any(tok in profile_text for tok in [doc[:4].lower(), doc[-4:].lower()])
            ):
                hit += 1
        completeness_score = round(hit / len(document_checklist), 2)

    # --- law article references (best-effort via raw_json snapshot) --------
    try:
        prog_row = conn.execute(
            "SELECT raw_json FROM am_entities WHERE canonical_id = ?",
            (pid,),
        ).fetchone()
    except sqlite3.Error:
        prog_row = None
    law_refs: list[dict[str, Any]] = []
    if prog_row and prog_row["raw_json"]:
        try:
            raw = json.loads(prog_row["raw_json"])
            law_canon = raw.get("law_canonical_id") or raw.get("law_relation")
            if law_canon and isinstance(law_canon, str):
                la = conn.execute(
                    """
                    SELECT article_number, title, source_url
                      FROM am_law_article
                     WHERE law_canonical_id = ?
                     LIMIT 5
                    """,
                    (law_canon,),
                ).fetchall()
                law_refs = [
                    {
                        "article_number": r["article_number"],
                        "title": r["title"],
                        "source_url": r["source_url"],
                    }
                    for r in la
                ]
        except (ValueError, TypeError, sqlite3.Error):
            pass

    out: dict[str, Any] = {
        "program_id": pid,
        "target_round": target_round,
        "round": (
            {
                "round_id": round_row["round_id"],
                "round_label": round_row["round_label"],
                "application_open_date": round_row["application_open_date"],
                "application_close_date": round_row["application_close_date"],
                "status": round_row["status"],
                "source_url": round_row["source_url"],
                "days_to_close": (
                    (
                        datetime.date.fromisoformat(round_row["application_close_date"][:10])
                        - datetime.date.fromisoformat(today_iso)
                    ).days
                    if round_row["application_close_date"]
                    and len(round_row["application_close_date"]) >= 10
                    else None
                ),
            }
            if round_row
            else None
        ),
        "steps": [
            {
                "step_no": sr["step_no"],
                "step_title": sr["step_title"],
                "step_description": sr["step_description"],
                "expected_days": sr["expected_days"],
                "online_or_offline": sr["online_or_offline"],
                "responsible_party": sr["responsible_party"],
            }
            for sr in step_rows
        ],
        "document_checklist": document_checklist[:30],
        "certifications": certifications,
        "law_references": law_refs,
        "est_review_days": est_review_days,
        "completeness_score": completeness_score,
        "data_quality": {
            "steps_count": len(step_rows),
            "checklist_size": len(document_checklist),
            "round_resolved": round_row is not None,
            "caveat": (
                "completeness_score is a heuristic overlap between profile "
                "keys and the document_checklist surface tokens. "
                "est_review_days = sum(step.expected_days where "
                "responsible_party=authority|support_org)."
            ),
        },
        "_disclaimer": _DISCLAIMER_SIMULATE,
        "_next_calls": _next_calls_for_simulate(pid),
        # Envelope shape for paginated consumers.
        "results": [
            {
                "step_no": sr["step_no"],
                "step_title": sr["step_title"],
                "expected_days": sr["expected_days"],
            }
            for sr in step_rows
        ],
        "total": len(step_rows),
        "limit": len(step_rows) or 1,
        "offset": 0,
    }
    return out


# ---------------------------------------------------------------------------
# 4) track_amendment_lineage_am — am_amendment_snapshot time-series
# ---------------------------------------------------------------------------


def _track_amendment_lineage_impl(
    target_kind: str,
    target_id: str,
    since: str | None = None,
) -> dict[str, Any]:
    """Pure SQL: am_amendment_snapshot time-series for a target."""
    if target_kind not in ("law", "program"):
        return make_error(
            code="invalid_enum",
            message=f"target_kind must be 'law' or 'program' (got {target_kind!r}).",
            field="target_kind",
        )
    if not target_id or not isinstance(target_id, str) or not target_id.strip():
        return make_error(
            code="missing_required_arg",
            message="target_id is required.",
            field="target_id",
        )
    tid = target_id.strip()

    since_date = None
    if since:
        since_date = _parse_iso_date(since)
        if since_date is None:
            return make_error(
                code="invalid_date_format",
                message=f"since={since!r} did not parse as ISO YYYY-MM-DD.",
                field="since",
            )

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    # The am_amendment_snapshot table is keyed on entity_id (canonical_id).
    # For target_kind='law' we still query that table because law canonical_ids
    # are entities too; we just enforce it with a record_kind sanity guard.
    try:
        kind_row = conn.execute(
            "SELECT record_kind FROM am_entities WHERE canonical_id = ?",
            (tid,),
        ).fetchone()
    except sqlite3.Error:
        kind_row = None

    if kind_row is None:
        out_empty: dict[str, Any] = {
            "target_kind": target_kind,
            "target_id": tid,
            "results": [],
            "total": 0,
            "limit": 1,
            "offset": 0,
            "strict_count": 0,
            "hash_only_count": 0,
            "warnings": [],
            "data_quality": {
                "target_resolved": False,
                "snapshot_corpus_total": 14596,
                "rows_with_effective_from_corpus_total": 140,
                "uniform_empty_hash_share_pct": 82.3,
                "caveat": (
                    f"target_id {tid!r} was not found in am_entities; "
                    "returned a graceful empty lineage envelope."
                ),
            },
            "_billing_unit": 1,
            "_next_calls": [],
        }
        return attach_corpus_snapshot_with_conn(conn, out_empty)

    actual_kind = kind_row["record_kind"]
    if target_kind == "law" and actual_kind != "law":
        return make_error(
            code="invalid_enum",
            message=(
                f"target_id {tid!r} has record_kind={actual_kind!r}, "
                f"not 'law'. Pass target_kind='program' or fix target_id."
            ),
            field="target_id",
        )
    if target_kind == "program" and actual_kind != "program":
        return make_error(
            code="invalid_enum",
            message=(
                f"target_id {tid!r} has record_kind={actual_kind!r}, "
                f"not 'program'. Pass target_kind='law' or fix target_id."
            ),
            field="target_id",
        )

    # --- pull snapshots ----------------------------------------------------
    sql = """
        SELECT snapshot_id, version_seq, observed_at, effective_from,
               effective_until, amount_max_yen, subsidy_rate_max,
               eligibility_hash, summary_hash, source_url, source_fetched_at
          FROM am_amendment_snapshot
         WHERE entity_id = ?
         ORDER BY version_seq ASC, observed_at ASC
    """
    try:
        rows = conn.execute(sql, (tid,)).fetchall()
    except sqlite3.Error as exc:
        logger.exception("amendment_snapshot query failed")
        return make_error(
            code="db_unavailable",
            message=f"am_amendment_snapshot query failed: {exc}",
        )

    # Filter by since if provided. We compare against effective_from when
    # that field is non-empty AND parses; otherwise observed_at.
    timeline: list[dict[str, Any]] = []
    strict_count = 0  # rows with effective_from
    hash_only_count = 0  # rows where eligibility_hash and summary_hash exist
    for r in rows:
        ef_raw = r["effective_from"]
        ef_parsed = _parse_iso_date(ef_raw) if ef_raw else None
        if since_date is not None:
            # Use ef_parsed if available, fall back to observed_at date.
            cmp_date = ef_parsed
            if cmp_date is None:
                cmp_date = _parse_iso_date(r["observed_at"])
            if cmp_date is not None and cmp_date < since_date:
                continue
        if ef_parsed is not None:
            strict_count += 1
        if r["eligibility_hash"] or r["summary_hash"]:
            hash_only_count += 1
        timeline.append(
            {
                "snapshot_id": r["snapshot_id"],
                "version_seq": r["version_seq"],
                "observed_at": r["observed_at"],
                "effective_from": ef_raw,
                "effective_from_parsed": (ef_parsed.isoformat() if ef_parsed else None),
                "effective_until": r["effective_until"],
                "amount_max_yen": r["amount_max_yen"],
                "subsidy_rate_max": r["subsidy_rate_max"],
                "eligibility_hash": (
                    r["eligibility_hash"][:16] + "..." if r["eligibility_hash"] else None
                ),
                "summary_hash": (r["summary_hash"][:16] + "..." if r["summary_hash"] else None),
                "source_url": r["source_url"],
                "source_fetched_at": r["source_fetched_at"],
            }
        )

    warnings: list[str] = []
    # CLAUDE.md gotcha + memory `feedback_no_fake_data`:
    # eligibility_hash is uniform sha256(empty string) on 12,014/14,596 rows.
    # We always surface this honesty caveat.
    if hash_only_count and strict_count == 0:
        warnings.append(
            "All snapshots are hash-only (no effective_from). "
            "eligibility_hash is uniform sha256-of-empty on 12,014/14,596 "
            "rows — time-series is structurally fake. Verify primary source."
        )
    if strict_count > 0 and strict_count < len(timeline):
        warnings.append(
            f"Only {strict_count}/{len(timeline)} rows have parseable "
            "effective_from. Mixed reliability — treat un-dated rows as advisory."
        )

    out: dict[str, Any] = {
        "target_kind": target_kind,
        "target_id": tid,
        "results": timeline,
        "total": len(timeline),
        "limit": len(timeline) or 1,
        "offset": 0,
        "strict_count": strict_count,
        "hash_only_count": hash_only_count,
        "warnings": warnings,
        "data_quality": {
            "snapshot_corpus_total": 14596,
            "rows_with_effective_from_corpus_total": 140,
            "uniform_empty_hash_share_pct": 82.3,  # 12,014 / 14,596
            "caveat": (
                "am_amendment_snapshot 14,596 rows: only 140 carry "
                "effective_from + ~14,456 are hash-only. eligibility_hash "
                "is uniform sha256-of-empty on 82.3% — time-series fence."
            ),
        },
        "_next_calls": _next_calls_for_lineage(target_kind, tid),
    }
    return out


# ---------------------------------------------------------------------------
# 5) program_active_periods_am — am_application_round per-program rounds
# ---------------------------------------------------------------------------


def _program_active_periods_impl(
    program_id: str,
    future_only: bool = False,
) -> dict[str, Any]:
    """Pure SQL: am_application_round → rounds + days_to_close + sunset_warning."""
    if not program_id or not isinstance(program_id, str) or not program_id.strip():
        return make_error(
            code="missing_required_arg",
            message="program_id is required.",
            field="program_id",
            retry_with=["search_programs"],
        )
    pid = program_id.strip()

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    today_iso = _today_iso()
    today_date = datetime.date.fromisoformat(today_iso)

    sql = """
        SELECT round_id, round_label, round_seq,
               application_open_date, application_close_date,
               announced_date, disbursement_start_date,
               budget_yen, status, source_url, source_fetched_at
          FROM am_application_round
         WHERE program_entity_id = ?
    """
    params: list[Any] = [pid]
    if future_only:
        sql += " AND (application_close_date IS NULL  OR application_close_date >= ?)"
        params.append(today_iso)
    sql += " ORDER BY round_seq ASC, application_close_date ASC"

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.exception("application_round query failed")
        return make_error(
            code="db_unavailable",
            message=f"am_application_round query failed: {exc}",
        )

    rounds: list[dict[str, Any]] = []
    soonest_close: datetime.date | None = None
    open_count = 0
    upcoming_count = 0
    closed_count = 0
    for r in rows:
        close_raw = r["application_close_date"]
        close_date = _parse_iso_date(close_raw) if close_raw else None
        days_to_close: int | None = None
        if close_date is not None:
            days_to_close = (close_date - today_date).days
            if days_to_close >= 0 and (soonest_close is None or close_date < soonest_close):
                soonest_close = close_date

        status = (r["status"] or "").lower()
        if status == "open":
            open_count += 1
        elif status == "upcoming":
            upcoming_count += 1
        elif status == "closed":
            closed_count += 1

        rounds.append(
            {
                "round_id": r["round_id"],
                "round_label": r["round_label"],
                "round_seq": r["round_seq"],
                "application_open_date": r["application_open_date"],
                "application_close_date": close_raw,
                "days_to_close": days_to_close,
                "announced_date": r["announced_date"],
                "disbursement_start_date": r["disbursement_start_date"],
                "budget_yen": r["budget_yen"],
                "status": r["status"],
                "source_url": r["source_url"],
                "source_fetched_at": r["source_fetched_at"],
            }
        )

    sunset_warning: str | None = None
    if open_count == 0 and upcoming_count == 0 and closed_count > 0:
        sunset_warning = (
            "No open or upcoming rounds — only closed ones. Program may "
            "have sunset. Verify on source_url + check program_lifecycle."
        )
    elif soonest_close is not None and (soonest_close - today_date).days <= 14 and open_count > 0:
        sunset_warning = (
            f"Soonest close in {(soonest_close - today_date).days} days "
            f"({soonest_close.isoformat()}). Urgent — confirm "
            "applicant readiness."
        )

    out: dict[str, Any] = {
        "program_id": pid,
        "results": rounds,
        "total": len(rounds),
        "limit": len(rounds) or 1,
        "offset": 0,
        "open_count": open_count,
        "upcoming_count": upcoming_count,
        "closed_count": closed_count,
        "soonest_close_date": (soonest_close.isoformat() if soonest_close else None),
        "sunset_warning": sunset_warning,
        "data_quality": {
            "rounds_corpus_total": 1256,
            "future_only_filter": future_only,
            "caveat": (
                "Status reflects am_application_round.status as of last "
                "fetch — verify on source_url before applicant commits. "
                "Some programs use rolling intake (no close_date)."
            ),
        },
        "_next_calls": _next_calls_for_periods(pid),
    }
    return out


# ---------------------------------------------------------------------------
# MCP tool registration. Gated by AUTONOMATH_COMPOSITION_ENABLED + the global
# AUTONOMATH_ENABLED (which is checked at the package __init__.py boundary).
# Each @mcp.tool docstring is ≤ 400 chars per Wave 21 spec.
# ---------------------------------------------------------------------------
if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def apply_eligibility_chain_am(
        profile: Annotated[
            dict[str, Any],
            Field(
                description=(
                    "Applicant profile (prefecture / industry_jsic / "
                    "annual_revenue_yen / business_type). Empty {} OK."
                ),
            ),
        ],
        program_ids: Annotated[
            list[str],
            Field(
                description=(
                    "Canonical program IDs to evaluate (e.g. ['program:base:71f6029070', ...])."
                ),
                min_length=1,
                max_length=20,
            ),
        ],
        chain_depth: Annotated[
            int,
            Field(
                ge=1,
                le=8,
                description=(
                    "Chain depth (1=prereq only, 4=full pipeline including "
                    "compat_matrix). Default 4."
                ),
            ),
        ] = 4,
    ) -> dict[str, Any]:
        """Multi-step eligibility orchestration over prerequisite_chain → rule_engine_check → exclusion_rules → am_compat_matrix per program. Returns per-program verdict (eligible / partial / ineligible) + reasoning_steps + cite chain. Heuristic; verify primary source. §52 sensitive."""
        return _apply_eligibility_chain_impl(
            profile=profile,
            program_ids=program_ids,
            chain_depth=chain_depth,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def find_complementary_programs_am(
        seed_program_id: Annotated[
            str,
            Field(
                description=("Seed program canonical_id. Use search_programs first."),
            ),
        ],
        top_n: Annotated[
            int,
            Field(
                ge=1,
                le=50,
                description="Max peers to return (default 10).",
            ),
        ] = 10,
        exclude_unknown_compat: Annotated[
            bool,
            Field(
                description=(
                    "If True (default), only compat_status='compatible'. "
                    "If False, also include 'case_by_case'."
                ),
            ),
        ] = True,
    ) -> dict[str, Any]:
        """Seed program → am_compat_matrix compatible edges → portfolio with combined_ceiling_yen + conflicts. authoritative_share_pct surfaced. inferred_only=true edges are heuristic. §52 sensitive — verify 経費重複 + 適正化法 17 条 before stacking."""
        return _find_complementary_impl(
            seed_program_id=seed_program_id,
            top_n=top_n,
            exclude_unknown_compat=exclude_unknown_compat,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def simulate_application_am(
        program_id: Annotated[
            str,
            Field(description="Target program canonical_id."),
        ],
        profile: Annotated[
            dict[str, Any],
            Field(
                description=("Applicant profile dict — used for completeness_score."),
            ),
        ],
        target_round: Annotated[
            str,
            Field(
                description=(
                    "Which round to simulate against: "
                    "'next' (soonest open/upcoming), "
                    "'current' (latest open), 'any' (latest by seq). "
                    "Default 'next'."
                ),
            ),
        ] = "next",
    ) -> dict[str, Any]:
        """Pure-SQL mock walkthrough: am_application_steps + am_prerequisite_bundle + am_application_round + am_law_article. Returns document_checklist + certifications + est_review_days + completeness_score. NO LLM. §52 sensitive — not a substitute for 行政書士 §1 申請代理."""
        return _simulate_application_impl(
            program_id=program_id,
            profile=profile,
            target_round=target_round,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def track_amendment_lineage_am(
        target_kind: Annotated[
            str,
            Field(
                description="'law' or 'program'.",
            ),
        ],
        target_id: Annotated[
            str,
            Field(description="Canonical_id of the law or program."),
        ],
        since: Annotated[
            str | None,
            Field(
                description=(
                    "Optional ISO YYYY-MM-DD lower bound. Filters by "
                    "effective_from when present, else observed_at."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """am_amendment_snapshot time-series for a target (14,596 rows; only 140 carry effective_from). Returns timeline + strict_count (with effective_from) + hash_only_count + warnings. eligibility_hash is uniform sha256-of-empty on 82.3% — time-series fence surfaced."""
        return _track_amendment_lineage_impl(
            target_kind=target_kind,
            target_id=target_id,
            since=since,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def program_active_periods_am(
        program_id: Annotated[
            str,
            Field(description="Target program canonical_id."),
        ],
        future_only: Annotated[
            bool,
            Field(
                description=(
                    "If True, only rounds with close_date >= today JST. "
                    "Default False (returns all rounds)."
                ),
            ),
        ] = False,
    ) -> dict[str, Any]:
        """am_application_round (1,256 rows) per-program rounds + days_to_close + sunset_warning. Returns open_count / upcoming_count / closed_count + soonest_close_date. sunset_warning fires when only closed rounds exist OR close < 14 days away."""
        return _program_active_periods_impl(
            program_id=program_id,
            future_only=future_only,
        )


# ---------------------------------------------------------------------------
# Self-test harness (not part of the MCP surface).
#
#   .venv/bin/python -m jpintel_mcp.mcp.autonomath_tools.composition_tools
# ---------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import pprint

    print("\n=== apply_eligibility_chain_am ===")
    res = _apply_eligibility_chain_impl(
        profile={"prefecture": "東京", "industry_jsic": "C"},
        program_ids=[
            "program:base:71f6029070",
            "program:base:3b5ec4f12e",
        ],
    )
    pprint.pprint(
        {
            "summary": res.get("summary"),
            "verdicts": [(p["program_id"], p["verdict"]) for p in res.get("results", [])],
            "next_calls_count": len(res.get("_next_calls", [])),
        }
    )

    print("\n=== find_complementary_programs_am ===")
    res = _find_complementary_impl(
        seed_program_id="program:04_program_documents:000000:23_25d25bdfe8",
        top_n=5,
    )
    pprint.pprint(
        {
            "total": res.get("total"),
            "combined_ceiling_yen": res.get("combined_ceiling_yen"),
            "conflicts_count": len(res.get("conflicts", [])),
            "next_calls_count": len(res.get("_next_calls", [])),
        }
    )

    print("\n=== simulate_application_am ===")
    res = _simulate_application_impl(
        program_id="program:base:71f6029070",
        profile={"prefecture": "東京", "登記簿謄本": "ok"},
        target_round="next",
    )
    pprint.pprint(
        {
            "round_resolved": res.get("data_quality", {}).get("round_resolved"),
            "checklist_size": len(res.get("document_checklist", [])),
            "completeness_score": res.get("completeness_score"),
            "est_review_days": res.get("est_review_days"),
            "next_calls_count": len(res.get("_next_calls", [])),
        }
    )

    print("\n=== track_amendment_lineage_am ===")
    res = _track_amendment_lineage_impl(
        target_kind="program",
        target_id="program:107_robotics_automation_industry:000010:RDAI_c0b043fca5",
    )
    pprint.pprint(
        {
            "total": res.get("total"),
            "strict_count": res.get("strict_count"),
            "warnings": res.get("warnings"),
            "next_calls_count": len(res.get("_next_calls", [])),
        }
    )

    print("\n=== program_active_periods_am ===")
    res = _program_active_periods_impl(
        program_id="program:base:71f6029070",
        future_only=True,
    )
    pprint.pprint(
        {
            "open_count": res.get("open_count"),
            "upcoming_count": res.get("upcoming_count"),
            "soonest_close_date": res.get("soonest_close_date"),
            "sunset_warning": res.get("sunset_warning"),
            "next_calls_count": len(res.get("_next_calls", [])),
        }
    )
