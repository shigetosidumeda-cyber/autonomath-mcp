"""funding_stack_tools — Funding Stack Checker MCP tool (no LLM).

Plan reference: ``docs/_internal/value_maximization_plan_no_llm_api.md`` §8.4.

Single tool ``check_funding_stack_am`` that wraps
``jpintel_mcp.services.funding_stack_checker.FundingStackChecker`` and
returns a stack verdict + per-pair envelope. Pure SQLite + Python, NO
LLM call.

Billing
-------

The MCP-side tool currently bills as a single tool invocation regardless
of pair count (mirrors how prerequisite_chain / rule_engine_check etc.
ship). The REST endpoint at ``/v1/funding_stack/check`` charges per pair
via ``log_usage(quantity=N)`` for callers that prefer the pay-per-pair
model.

Disclaimer
----------

The wrapped service surfaces ``_disclaimer`` in both the per-pair
``StackVerdict`` and the aggregate ``StackResult``. The MCP envelope is
the ``StackResult.to_dict()`` shape so callers always see the disclaimer
at the top level — non-LLM rule engines often miss exception cases that
humans must catch (景表法 / 消費者契約法 fence).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.autonomath_tools.error_envelope import make_error
from jpintel_mcp.mcp.server import _READ_ONLY, mcp
from jpintel_mcp.services.funding_stack_checker import FundingStackChecker

logger = logging.getLogger("jpintel.mcp.autonomath.funding_stack")

# Env-gate matches the rest of autonomath_tools: default ON, flip "0" to
# disable without redeploy. Pairs with the global AUTONOMATH_ENABLED gate
# (checked at the package __init__ boundary).
_ENABLED = get_flag("JPCITE_FUNDING_STACK_ENABLED", "AUTONOMATH_FUNDING_STACK_ENABLED", "1") == "1"

# Practical UX limit. C(5, 2) = 10 pairs aligns with the REST endpoint cap
# (api/funding_stack.py::_MAX_PROGRAMS) so MCP and REST surfaces never
# disagree on what "too many programs" means.
_MAX_PROGRAMS = 5
_MAX_PAIRS_DEFAULT = 10
_MAX_PAIRS_HARD_CAP = 10


# Module-level checker singleton. Built lazily on first call so importing
# this module never opens the DBs (fast startup + cheap test imports).
_checker: FundingStackChecker | None = None


def _get_checker() -> FundingStackChecker | None:
    """Return the cached checker, or None if a DB asset is missing."""

    global _checker
    if _checker is None:
        try:
            _checker = FundingStackChecker(
                jpintel_db=settings.db_path,
                autonomath_db=settings.autonomath_db_path,
            )
        except FileNotFoundError as exc:
            logger.warning(
                "funding_stack checker init failed: %s (jpintel=%s, autonomath=%s)",
                exc,
                settings.db_path,
                settings.autonomath_db_path,
            )
            return None
    return _checker


def _reset_checker() -> None:
    """Drop the cached checker. Called by tests after monkeypatching paths."""

    global _checker
    _checker = None


def _check_funding_stack_impl(
    program_ids: list[str],
    max_pairs: int = _MAX_PAIRS_DEFAULT,
) -> dict[str, Any]:
    """Pure-Python core. Split out so tests can call it directly without
    going through the @mcp.tool wrapper.
    """
    if not isinstance(program_ids, list) or not program_ids:
        return make_error(
            code="missing_required_arg",
            message="program_ids は最低 1 件以上の string のリストです。",
            hint=(
                "Pass at least 2 program ids to evaluate a stack. A single "
                "id returns an `unknown` envelope."
            ),
            field="program_ids",
        )
    if len(program_ids) > _MAX_PROGRAMS:
        return make_error(
            code="out_of_range",
            message=(
                f"program_ids は最大 {_MAX_PROGRAMS} 件までです (received {len(program_ids)})。"
            ),
            hint=(
                f"C({_MAX_PROGRAMS}, 2) = {_MAX_PAIRS_HARD_CAP} pairs is the "
                "billable + UX limit. Split into smaller stacks."
            ),
            field="program_ids",
        )
    if not isinstance(max_pairs, int):
        return make_error(
            code="out_of_range",
            message="max_pairs は int 型である必要があります。",
            field="max_pairs",
        )
    if max_pairs < 1:
        max_pairs = 1
    if max_pairs > _MAX_PAIRS_HARD_CAP:
        max_pairs = _MAX_PAIRS_HARD_CAP

    checker = _get_checker()
    if checker is None:
        return make_error(
            code="db_unavailable",
            message=(
                "funding_stack checker のデータソースが見つかりません。"
                "autonomath.db / data/jpintel.db のいずれかが欠落しています。"
            ),
            hint="AUTONOMATH_DB_PATH / JPINTEL_DB_PATH 環境変数を確認してください。",
        )

    result = checker.check_stack(program_ids)
    body = result.to_dict()

    # Honour max_pairs as a defensive truncation. check_stack should already
    # produce <= C(5, 2) = 10 pairs, but if a caller asks for fewer (e.g.
    # max_pairs=3 to debug) we trim and surface a warning so the strictness
    # roll-up stays honest.
    pairs = body.get("pairs", [])
    if len(pairs) > max_pairs:
        body = dict(body)
        body["pairs"] = pairs[:max_pairs]
        body.setdefault("warnings", []).append(
            {
                "code": "pairs_truncated",
                "message": (
                    f"{len(pairs)} 件の pair のうち先頭 {max_pairs} 件のみを "
                    "返します。all_pairs_status は省略した pair の verdict を "
                    "考慮した値であることに注意してください。"
                ),
            }
        )
        body["total_pairs"] = max_pairs

    # Match the canonical search-envelope shape so downstream search-shape
    # consumers (which look for `total / limit / offset / results`) work
    # without special-casing this tool.
    body.setdefault("total", len(body.get("pairs", [])))
    body.setdefault("limit", _MAX_PAIRS_HARD_CAP)
    body.setdefault("offset", 0)
    body.setdefault("results", body.get("pairs", []))
    return body


# ---------------------------------------------------------------------------
# MCP tool registration. Gated by AUTONOMATH_FUNDING_STACK_ENABLED + the
# global AUTONOMATH_ENABLED.
# ---------------------------------------------------------------------------
if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def check_funding_stack_am(
        program_ids: Annotated[
            list[str],
            Field(
                description=(
                    "List of program identifiers to evaluate as a stack. "
                    f"Max {_MAX_PROGRAMS} programs (C(N,2) = up to "
                    f"{_MAX_PAIRS_HARD_CAP} pairs). Each id should be a "
                    "canonical `program:...` id, a `unified_id`, or a "
                    "primary_name — the underlying matcher accepts whatever "
                    "the curated rule corpora used as keys."
                ),
                min_length=1,
                max_length=_MAX_PROGRAMS,
            ),
        ],
        max_pairs: Annotated[
            int,
            Field(
                ge=1,
                le=_MAX_PAIRS_HARD_CAP,
                description=(
                    f"Maximum number of pair entries to return (default "
                    f"{_MAX_PAIRS_DEFAULT}, hard cap {_MAX_PAIRS_HARD_CAP})."
                ),
            ),
        ] = _MAX_PAIRS_DEFAULT,
    ) -> dict[str, Any]:
        """[FUNDING-STACK-AM] Returns a deterministic 制度併用可否 verdict (compatible / incompatible / requires_review / unknown) per pair + aggregate, by joining am_compat_matrix with exclusion_rules. NO LLM. Each response carries `_disclaimer`. Verify primary source.

        WHAT: For each C(N, 2) pair (max C(5, 2) = 10) we look up
        ``am_compat_matrix`` (43,966 rows; 4,300 sourced + 39,000+ heuristic)
        and ``exclusion_rules`` (181 rows; 125 exclude + 17 prerequisite +
        15 absolute + 24 other) and emit a verdict + ``rule_chain``.
        ``all_pairs_status`` rolls up to the strictest verdict
        (incompatible > requires_review > unknown > compatible).

        WHEN:
          - "IT導入補助金 と 事業再構築補助金 と ものづくり補助金 を併用できる?"
          - 「補助金ポートフォリオを 3 件組むと、どこかで一括併用禁止に
            ぶつからないか?」
          - 「前提認定 chain で人手確認が必要な組合せは?」

        WHEN NOT:
          - 個別 program の探索 → search_programs
          - 1 制度の前提認定詳細 → prerequisite_chain
          - 同一経費 / 重複受給以外の rule (補助率上限など) → rule_engine_check

        RETURNS (envelope):
          {
            program_ids: list[str],
            all_pairs_status: "compatible" | "incompatible" | "requires_review" | "unknown",
            pairs: [
              {
                program_a, program_b,
                verdict: ...,
                confidence: 0.0..1.0,
                rule_chain: [
                  {source: "am_compat_matrix" | "exclusion_rules" | ...,
                   rule_text, weight, ...},
                  ...
                ],
                _disclaimer: str
              },
              ...
            ],
            blockers: list[ {program_a, program_b, rule_chain} ],
            warnings: list[ {program_a, program_b, rule_chain} ],
            _disclaimer: str,    # 一次資料 / 専門家 advisory (mandatory)
            total, limit, offset, results  # search-envelope mirror
          }

        DATA QUALITY HONESTY: am_compat_matrix の 22,290 sourced 行のみ
        ``confidence=1.0`` で確定する。残り 41,943 行は heuristic で
        ``confidence`` は 0.3 以下に減点される。`_disclaimer` フィールドは
        必須 — 非 LLM rule engine は curate コーパスに 100% 依拠するため、
        収録漏れや公募回ごとの細則差を取りこぼし得る。
        """

        return _check_funding_stack_impl(
            program_ids=list(program_ids),
            max_pairs=max_pairs,
        )


__all__ = [
    "_check_funding_stack_impl",
    "_reset_checker",
]
