"""prerequisite_chain — R5 前提認定 chain MCP tool (2026-04-25).

Surfaces the multi-step prerequisites that gate a target 補助金 / 制度,
so callers can see *what認定 / 計画 / 登録 must be obtained first* + the
acquisition cost (preparation_time_days + preparation_cost_yen).

Schema source (autonomath.db):

  am_prerequisite_bundle (795 rows / 135 programs / 1.6% coverage)
    bundle_id              INTEGER PRIMARY KEY
    program_entity_id      TEXT  — target program canonical_id
    prerequisite_kind      TEXT  — id / doc / cert / plan / membership / agency_relation
    prerequisite_name      TEXT  — human-readable Japanese name
    required_or_optional   TEXT  — required / optional_for_score / sometimes_required
    preparation_time_days  INT   — avg 8d, max 60d
    preparation_cost_yen   INTEGER — avg ¥1,566, max ¥150,000
    related_canonical_id   TEXT  — link back to a peer entity (currently NULL on 100%)
    obtain_url             TEXT  — official acquisition portal URL
    rationale_text         TEXT  — why it matters (acceptance impact, 加点, etc.)
    generated_at           TEXT

Coverage honesty (景表法 fence):
  Only 135/8,203 programs have a curated bundle today. The tool ALWAYS
  surfaces ``data_quality.coverage_pct = 1.6`` so the caller / LLM never
  treats an empty chain as authoritative. If the target is outside the
  1.6% bucket, we return an EMPTY ``prerequisite_chain`` PLUS the
  coverage caveat — silent miss is forbidden.

Recursion: ``related_canonical_id`` is NULL on every row at present, so
the chain is depth-1 (direct prereqs) regardless of the requested
``depth`` parameter. We retain ``depth`` for forward compatibility +
emit a warning when ``depth>5`` since R5 design flagged "deeper than 5
hops is not realistic" (cumulative time > 180d / cost > ¥1M).

Customer questions answered:
  - 「ものづくり補助金で加点を取るには、どの認定が要る?」
  - 「事業再構築補助金を申請する前に取る前提認定は?その取得時間と費用は?」
  - 「3 段階の chain を踏まないと申請できない補助金は?」

Returns canonical envelope::

  {
    program_id: str,
    prerequisite_chain: [
      {
        kind: "cert" | "plan" | "id" | "doc" | "membership" | "agency_relation",
        name: str,
        required_or_optional: "required" | "optional_for_score" | "sometimes_required",
        preparation_time_days: int|null,
        preparation_cost_yen: int|null,
        obtain_url: str|null,
        rationale: str|null,
        related_canonical_id: str|null,
        depth: int,                 # currently always 1 (recursion data not present)
      }, ...
    ],
    total_preparation_time_days: int,
    total_preparation_cost_yen: int,
    realistic: bool,                 # depth>5 OR sum(time)>180d OR sum(cost)>1_000_000
    warnings: list[str],
    data_quality: {
      coverage_pct: 1.6,             # constant — surfaced unconditionally
      programs_with_bundle: 135,
      programs_total: 8203,
      recursion_resolvable: false,   # related_canonical_id is NULL on 100% of rows
    },
    _disclaimer: "<景表法 + 一次資料 advisory>",
    total: int, limit: int, offset: int, results: [...]  # envelope keys
  }
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.prerequisite_chain")

# ---------------------------------------------------------------------------
# Coverage constants. These reflect the live am_prerequisite_bundle state
# at 2026-04-25 (R5 verify): 795 rows / 135 programs over an 8,203-program
# corpus = 1.6%. Surfaced unconditionally so the LLM cannot treat an empty
# chain as authoritative — silent miss is fraud-risk (景表法 fence).
# Update these if the bundle is materially expanded (recompute via
#   SELECT COUNT(*), COUNT(DISTINCT program_entity_id) FROM am_prerequisite_bundle
# and the program total via
#   SELECT COUNT(*) FROM am_entities WHERE record_kind='program').
# ---------------------------------------------------------------------------
_BUNDLE_TOTAL_PROGRAMS = 135
_PROGRAMS_TOTAL_CORPUS = 8203
_COVERAGE_PCT = round(100.0 * _BUNDLE_TOTAL_PROGRAMS / _PROGRAMS_TOTAL_CORPUS, 1)

# Realism thresholds. From the R5 design doc (analysis_wave18):
#   depth>5             → "現実的でない" warning
#   sum(time) > 180d    → "半年以上の準備は事業計画として現実的でない"
#   sum(cost) > 1M¥     → "前提取得だけで 100 万円超は不採算"
_DEPTH_LIMIT = 5
_REALISTIC_TIME_LIMIT_DAYS = 180
_REALISTIC_COST_LIMIT_YEN = 1_000_000

_DISCLAIMER = (
    "本 response は am_prerequisite_bundle (135 programs / 1.6% coverage) "
    "に基づきます。残り 98.4% の programs は前提認定情報未収録のため "
    "「該当なし」≠「前提なし」です。最終的な申請要件は一次資料 (obtain_url / "
    "公募要領) と専門家 (税理士 / 行政書士 / 中小企業診断士) 確認を優先してください。"
)


def _prerequisite_chain_impl(
    target_program_id: str,
    depth: int = 3,
) -> dict[str, Any]:
    """Pure-Python core. Split out so tests can call it directly without
    going through the @mcp.tool wrapper.
    """
    # ---- arg validation ----
    if (
        not target_program_id
        or not isinstance(target_program_id, str)
        or not target_program_id.strip()
    ):
        return make_error(
            code="missing_required_arg",
            message="target_program_id is required (non-empty canonical program ID).",
            hint=(
                "Pass a `program:…` canonical ID. Use search_programs to "
                "discover the correct ID for a free-text query."
            ),
            field="target_program_id",
            retry_with=["search_programs"],
        )
    target_program_id = target_program_id.strip()

    if not isinstance(depth, int):
        return make_error(
            code="out_of_range",
            message=f"depth must be int (got {type(depth).__name__}).",
            field="depth",
        )
    if depth < 1:
        depth = 1
    if depth > 10:
        depth = 10  # hard cap — realism warning fires at >5

    # ---- subsystem gate ----
    if not settings.prerequisite_chain_enabled:
        return make_error(
            code="subsystem_unavailable",
            message=("prerequisite_chain disabled (AUTONOMATH_PREREQUISITE_CHAIN_ENABLED=0)."),
            hint=(
                "Operator has temporarily disabled prerequisite chain "
                "evaluation. Use search_certifications to enumerate "
                "认定 candidates manually."
            ),
            retry_with=["search_certifications", "search_programs"],
        )

    # ---- DB open ----
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

    # ---- query bundle rows ----
    try:
        rows = conn.execute(
            """
            SELECT prerequisite_kind, prerequisite_name, required_or_optional,
                   preparation_time_days, preparation_cost_yen,
                   related_canonical_id, obtain_url, rationale_text
              FROM am_prerequisite_bundle
             WHERE program_entity_id = ?
             ORDER BY
               CASE required_or_optional
                 WHEN 'required'             THEN 0
                 WHEN 'sometimes_required'   THEN 1
                 WHEN 'optional_for_score'   THEN 2
                 ELSE 3
               END,
               CASE prerequisite_kind
                 WHEN 'cert'              THEN 0
                 WHEN 'plan'              THEN 1
                 WHEN 'membership'        THEN 2
                 WHEN 'agency_relation'   THEN 3
                 WHEN 'id'                THEN 4
                 WHEN 'doc'               THEN 5
                 ELSE 6
               END,
               bundle_id
            """,
            (target_program_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.exception("prerequisite_chain query failed")
        return make_error(
            code="db_unavailable",
            message=f"am_prerequisite_bundle query failed: {exc}",
            retry_with=["search_programs"],
        )

    # ---- build chain entries ----
    # related_canonical_id is currently NULL on 100% of rows, so recursion
    # is dormant — every emitted entry has depth=1. Recursion-ready join:
    # if related_canonical_id is non-empty AND depth>1, recurse with the
    # related id as the new target. We honor that ladder defensively even
    # though no current row triggers it; future bundle expansion (R5 W1
    # gating doc) will populate the column for cert→plan chains and the
    # tool keeps working without code changes.
    seen: set[str] = {target_program_id}
    chain: list[dict[str, Any]] = []
    queue: list[tuple[str, int, list[sqlite3.Row]]] = [(target_program_id, 1, rows)]
    recursion_resolvable = False
    realistic_recursion_depth = min(depth, _DEPTH_LIMIT + 1)

    while queue:
        _src_id, cur_depth, cur_rows = queue.pop(0)
        next_targets: list[str] = []
        for r in cur_rows:
            related = (r["related_canonical_id"] or "").strip() or None
            if related:
                recursion_resolvable = True
            chain.append(
                {
                    "kind": r["prerequisite_kind"],
                    "name": r["prerequisite_name"],
                    "required_or_optional": r["required_or_optional"],
                    "preparation_time_days": r["preparation_time_days"],
                    "preparation_cost_yen": r["preparation_cost_yen"],
                    "obtain_url": r["obtain_url"],
                    "rationale": r["rationale_text"],
                    "related_canonical_id": related,
                    "depth": cur_depth,
                }
            )
            if related and cur_depth < realistic_recursion_depth and related not in seen:
                next_targets.append(related)
                seen.add(related)

        # Recurse one ladder rung. Bundles for the related ids are queried
        # in a single batched IN(...) so we do not N+1 the DB even if a
        # future row count grows. Empty result (no bundle for the related
        # id) is fine — the chain just stops at that node.
        if next_targets:
            placeholders = ",".join(["?"] * len(next_targets))
            try:
                next_rows_flat = conn.execute(
                    f"""
                    SELECT program_entity_id, prerequisite_kind,
                           prerequisite_name, required_or_optional,
                           preparation_time_days, preparation_cost_yen,
                           related_canonical_id, obtain_url, rationale_text
                      FROM am_prerequisite_bundle
                     WHERE program_entity_id IN ({placeholders})
                     ORDER BY program_entity_id, bundle_id
                    """,
                    next_targets,
                ).fetchall()
            except sqlite3.Error:
                logger.exception("prerequisite_chain recursion query failed")
                next_rows_flat = []

            grouped: dict[str, list[sqlite3.Row]] = {}
            for nr in next_rows_flat:
                grouped.setdefault(nr["program_entity_id"], []).append(nr)
            for tid in next_targets:
                child_rows = grouped.get(tid, [])
                if child_rows:
                    queue.append((tid, cur_depth + 1, child_rows))

    # ---- aggregates + warnings ----
    total_time_days = sum((e["preparation_time_days"] or 0) for e in chain)
    total_cost_yen = sum((e["preparation_cost_yen"] or 0) for e in chain)

    warnings: list[str] = []
    if depth > _DEPTH_LIMIT:
        warnings.append(
            f"depth={depth} は {_DEPTH_LIMIT} 段を超えています — 5 段超の "
            "前提 chain は実務上現実的ではありません (累積準備時間・費用が "
            "事業計画の射程を超える)。"
        )
    if total_time_days > _REALISTIC_TIME_LIMIT_DAYS:
        warnings.append(
            f"累積準備日数 {total_time_days} 日は {_REALISTIC_TIME_LIMIT_DAYS} 日を超過 — "
            "半年以上の前提取得は事業計画として再考を推奨。"
        )
    if total_cost_yen > _REALISTIC_COST_LIMIT_YEN:
        warnings.append(
            f"累積準備費用 ¥{total_cost_yen:,} は ¥{_REALISTIC_COST_LIMIT_YEN:,} を超過 — "
            "前提取得だけで 100 万円超は採算性要再検討。"
        )

    realistic = (
        depth <= _DEPTH_LIMIT
        and total_time_days <= _REALISTIC_TIME_LIMIT_DAYS
        and total_cost_yen <= _REALISTIC_COST_LIMIT_YEN
    )

    # ---- coverage caveat (always surfaced) ----
    data_quality: dict[str, Any] = {
        "coverage_pct": _COVERAGE_PCT,
        "programs_with_bundle": _BUNDLE_TOTAL_PROGRAMS,
        "programs_total": _PROGRAMS_TOTAL_CORPUS,
        "recursion_resolvable": recursion_resolvable,
    }
    if not chain:
        data_quality["caveat"] = (
            f"{target_program_id} is outside the curated bundle "
            f"({_BUNDLE_TOTAL_PROGRAMS}/{_PROGRAMS_TOTAL_CORPUS} = "
            f"{_COVERAGE_PCT}% coverage). Empty chain ≠ no prerequisites — "
            "consult 公募要領 / obtain_url for primary-source verification."
        )

    out: dict[str, Any] = {
        "program_id": target_program_id,
        "prerequisite_chain": chain,
        "total_preparation_time_days": total_time_days,
        "total_preparation_cost_yen": total_cost_yen,
        "realistic": realistic,
        "warnings": warnings,
        "data_quality": data_quality,
        "_disclaimer": _DISCLAIMER,
        # Envelope keys so paginated-shape consumers also work.
        "total": len(chain),
        "limit": 100,
        "offset": 0,
        "results": chain,
    }
    return out


# ---------------------------------------------------------------------------
# MCP tool registration. Gated by AUTONOMATH_PREREQUISITE_CHAIN_ENABLED so
# the operator can flip the surface off without redeploying.
# ---------------------------------------------------------------------------
if settings.prerequisite_chain_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def prerequisite_chain(
        target_program_id: Annotated[
            str,
            Field(
                description=(
                    "Target program canonical_id (e.g. "
                    "`program:04_program_documents:000000:23_25d25bdfe8`). "
                    "Use search_programs to resolve a free-text query first."
                ),
            ),
        ],
        depth: Annotated[
            int,
            Field(
                ge=1,
                le=10,
                description=(
                    "Recursion depth. 1 = direct prerequisites only. "
                    ">5 emits a `現実的でない` warning. Hard cap 10."
                ),
            ),
        ] = 3,
    ) -> dict[str, Any]:
        """[R5-PREREQUISITE-CHAIN] Returns curated prerequisite chain for a program (認定 / 計画 / 登録) with preparation_time_days + preparation_cost_yen. Coverage is partial (135/8,203 programs = 1.6%); empty chain ≠ no prerequisites — verify primary source (公募要領 / obtain_url).

        WHAT: ``am_prerequisite_bundle`` (795 rows / 135 programs / 1.6%
        coverage) を起点に、対象 program の前提取得物を kind 別 (cert /
        plan / membership / agency_relation / id / doc) に列挙し、
        ``preparation_time_days`` + ``preparation_cost_yen`` を集計。
        ``related_canonical_id`` が解決済の rung は ``depth`` 分まで再帰
        (現状 100% NULL のため depth=1 化、forward-compat)。

        WHEN:
          - 「ものづくり補助金で加点を取るために要る認定は?」
          - 「事業再構築補助金、申請前に何を整える?(認定・登録・会員)」
          - 「前提取得だけで何ヶ月 / いくら掛かるか?」

        WHEN NOT:
          - 補助金そのものの探索 → search_programs
          - 認定の詳細仕様 → search_certifications + get_program
          - 適格・除外判定 → rule_engine_check
          - tax 措置の sunset → list_tax_sunset_alerts

        RETURNS (envelope):
          {
            program_id: str,
            prerequisite_chain: [
              { kind, name, required_or_optional, preparation_time_days,
                preparation_cost_yen, obtain_url, rationale,
                related_canonical_id, depth }, ...
            ],
            total_preparation_time_days: int,
            total_preparation_cost_yen: int,
            realistic: bool,                # depth<=5 AND time<=180d AND cost<=¥1M
            warnings: [ str, ... ],         # depth>5 / time / cost cliffs
            data_quality: {
              coverage_pct: 1.6,            # surfaced unconditionally
              programs_with_bundle: 135,
              programs_total: 8203,
              recursion_resolvable: bool,
              caveat?: str                  # present when chain is empty
            },
            _disclaimer: str                # 一次資料 / 専門家 advisory
          }

        DATA QUALITY HONESTY: 1.6% coverage means 98.4% of programs have
        no curated bundle yet. The tool ALWAYS surfaces
        ``data_quality.coverage_pct`` so an empty chain is never read as
        authoritative — silent miss is forbidden under 景表法 / 消費者
        契約法 fences (see feedback_no_fake_data).

        CHAIN:
          ← `search_programs` supplies target_program_id.
          → `search_certifications(name)` for cert spec depth.
          → `rule_engine_check(program_id, applicant_profile)` for
            adjudication once prerequisites are obtained.
        """
        return _prerequisite_chain_impl(
            target_program_id=target_program_id,
            depth=depth,
        )


# ---------------------------------------------------------------------------
# Self-test harness (not part of the MCP surface).
#
#   .venv/bin/python -m jpintel_mcp.mcp.autonomath_tools.prerequisite_chain_tool
# ---------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import pprint

    samples = [
        # 1) ものづくり補助金 23次 — 10 prereqs incl. 経営革新計画 認定.
        {
            "target_program_id": "program:04_program_documents:000000:23_25d25bdfe8",
            "depth": 3,
        },
        # 2) Outside-coverage program — empty chain + caveat surfaced.
        {
            "target_program_id": "program:nonexistent:000000",
            "depth": 3,
        },
        # 3) Excessive depth — warning fires.
        {
            "target_program_id": "program:04_program_documents:000000:23_25d25bdfe8",
            "depth": 7,
        },
    ]
    for s in samples:
        print(f"\n=== {s} ===")
        res = _prerequisite_chain_impl(**s)
        pprint.pprint(
            {
                "chain_len": len(res.get("prerequisite_chain", [])),
                "total_time_days": res.get("total_preparation_time_days"),
                "total_cost_yen": res.get("total_preparation_cost_yen"),
                "realistic": res.get("realistic"),
                "warnings": res.get("warnings"),
                "coverage_pct": res.get("data_quality", {}).get("coverage_pct"),
            }
        )
