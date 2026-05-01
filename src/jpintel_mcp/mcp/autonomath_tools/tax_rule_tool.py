"""MCP tool: get_tax_rule — structured rule lookup per 税制措置.

Separate from search_tax_incentives (free-text LIKE across all 282
tax_measure records, including invoice 35 件) because ``am_tax_rule``
is a narrow, hand-curated structured table keyed by
(tax_measure_entity_id, rule_type). It returns rate / cap /
eligibility / effective period / source per rule-option.

Customer questions answered:
  - "DX 投資減税を使いたい"  → get_tax_rule("DX投資促進税制")
      → rows: special_depreciation 30% (abolished 2025-03-31),
              credit 3% (standard) / 5% (preferred).
  - "5G投資促進税制 はまだ使える? 後継制度は?"
      → get_tax_rule("5G") → effective_until=2025-03-31,
         note='後継なし', parent canonical_status='abolished'.
  - "エンジェル税制 A型 と B型 の違い"
      → get_tax_rule("エンジェル税制 (優遇措置A)") vs (優遇措置B)
         → A: deduction 投資額-2000円 / 800万円上限
           B: credit 投資額全額 / 上限なし (対象株式譲渡益から)

Merge plan (jpintel-mcp is READ ONLY; this file drops into
``mcp_new/tools.py`` at integration time and shares the same
``_safe_tool`` / ``_db_error`` envelope).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Annotated, Any, Literal

from pydantic import Field

from jpintel_mcp.mcp.server import mcp, _READ_ONLY
from .db import connect_autonomath
from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.new.tax_rule")


RuleType = Literal[
    "credit",
    "deduction",
    "reduction",
    "special_depreciation",
    "immediate_writeoff",
    "exemption",
]


def _safe_json_loads(s: str | None, default: Any = None) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return default


def _row_to_tax_rule(row: sqlite3.Row) -> dict[str, Any]:
    """Denormalize am_tax_rule + am_entities join row to API shape."""
    return {
        "tax_measure": {
            "canonical_id": row["tax_measure_entity_id"],
            "name": row["primary_name"],
            "canonical_status": row["canonical_status"],  # active / abolished
        },
        "rule_type": row["rule_type"],
        "base_rate_pct": row["base_rate_pct"],
        "cap_yen": row["cap_yen"],
        "eligibility": _safe_json_loads(row["eligibility_cond_json"], {}),
        "combinable_with": _safe_json_loads(row["combinable_with"], []),
        "effective_period": {
            "from": row["effective_from"],
            "until": row["effective_until"],  # null => 恒久措置
        },
        "article_ref": row["article_ref"],
        "source": {
            "url": row["source_url"],
            "fetched_at": row["source_fetched_at"],
        },
        "note": row["note"],
    }


def _resolve_measure(conn: sqlite3.Connection, token: str) -> list[str]:
    """Resolve free-text name OR canonical_id to a list of canonical_ids.

    Order of resolution:
      1. Exact canonical_id match (token starts with 'tax_measure:').
      2. Exact primary_name match.
      3. LIKE primary_name (substring) — returns all matches.
    Duplicates deduped while preserving order.
    """
    if token.startswith("tax_measure:"):
        cur = conn.execute(
            "SELECT canonical_id FROM am_entities "
            "WHERE canonical_id = ? AND record_kind='tax_measure'",
            (token,),
        )
        ids = [r["canonical_id"] for r in cur.fetchall()]
        if ids:
            return ids

    # exact primary_name
    cur = conn.execute(
        "SELECT canonical_id FROM am_entities "
        "WHERE primary_name = ? AND record_kind='tax_measure'",
        (token,),
    )
    ids = [r["canonical_id"] for r in cur.fetchall()]
    if ids:
        return ids

    # LIKE fallback. Escape SQL LIKE metacharacters.
    safe = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    cur = conn.execute(
        "SELECT canonical_id FROM am_entities "
        "WHERE primary_name LIKE ? ESCAPE '\\' AND record_kind='tax_measure' "
        "ORDER BY canonical_id "
        "LIMIT 20",
        (f"%{safe}%",),
    )
    seen: set[str] = set()
    out: list[str] = []
    for r in cur.fetchall():
        cid = r["canonical_id"]
        if cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


@mcp.tool(annotations=_READ_ONLY)
def get_am_tax_rule(
    measure_name_or_id: Annotated[
        str,
        Field(
            description=(
                "tax_measure canonical_id (例: "
                "'tax_measure:12_tax_incentives:000013:DX20253_8f34f2a2dc') "
                "または primary_name / 部分名 (例: 'DX投資促進税制' / 'エンジェル税制')。"
                "部分一致は最大 20 件まで返す。"
            ),
            min_length=1,
            max_length=200,
        ),
    ],
    rule_type: Annotated[
        RuleType | None,
        Field(
            description=(
                "Filter by rule option: 'credit' (税額控除) / "
                "'deduction' (所得控除) / 'reduction' (軽減税率) / "
                "'special_depreciation' (特別償却) / "
                "'immediate_writeoff' (即時償却) / 'exemption' (非課税)."
            ),
        ),
    ] = None,
    as_of: Annotated[
        str | None,
        Field(
            description=(
                "ISO date (YYYY-MM-DD). 指定すると effective_from <= as_of "
                "AND (effective_until IS NULL OR effective_until >= as_of) "
                "で絞り込み。未指定なら全 rule 返す (廃止済みも含む)。"
            ),
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
    ] = None,
) -> dict[str, Any]:
    """[DISCOVER-TAX-RULE] Returns structured tax rule rows for a 税制措置 (rate / cap / 根拠条文 / 適用期限) from am_tax_rule. One measure can return multiple rows when both 特別償却 and 税額控除 exist. Output is search-derived; verify primary source (source_url) for filing decisions.

    WHAT: am_tax_rule から (tax_measure_entity_id, rule_type) PK の
    structured row を返す。1 つの税制で「特別償却 or 税額控除」が両方
    存在する場合は 2 行返る。

    WHEN:
      - 顧客: 「DX 投資減税を使いたい」「5G税制はまだ使える?」
        「エンジェル A型 と B型 の違い」
      - LLM: search_tax_incentives が free-text で候補を出した後、
        特定の measure_id をこの tool に渡して rate / 期限 / 条文 を
        確定させる use case がメイン。

    WHEN NOT:
      - 全税制を横断検索したい → search_tax_incentives
      - 条文内容そのもの → search_by_law
      - 補助金 → search_programs
      - 併用可能制度の全グラフ → related_programs (relation graph)

    RETURNS (envelope):
      {
        total: int,
        results: [
          {
            tax_measure: { canonical_id, name, canonical_status },
            rule_type: str,
            base_rate_pct: float|null,
            cap_yen: int|null,
            eligibility: dict,   # JSON from eligibility_cond_json
            combinable_with: [canonical_id, ...],
            effective_period: { from, until },
            article_ref: str,    # 租税特別措置法 第X条
            source: { url, fetched_at },
            note: str|null,
          }, ...
        ],
        hint?: str,              # e.g. 「該当制度は廃止済み」 (only on success)
      }

    On failure / no result, returns the canonical envelope:
      { total: 0, results: [], error: { code, message, hint, severity,
        retry_with, ... } } where ``code`` is one of ``seed_not_found``
      (measure_name_or_id did not resolve), ``no_matching_records``
      (measure resolved but no am_tax_rule rows), or ``db_unavailable``.
    """
    # ---- resolve parent measure ------------------------------------------
    conn = connect_autonomath()
    try:
        measure_ids = _resolve_measure(conn, measure_name_or_id)
    except sqlite3.Error as exc:
        logger.exception("get_tax_rule resolve failed")
        err = make_error(
            code="db_unavailable",
            message=f"resolve failed: {exc}",
            hint="autonomath.db is unreachable; retry later or fall back to search_tax_incentives.",
            retry_with=["search_tax_incentives"],
        )
        return {"total": 0, "results": [], "error": err["error"]}

    if not measure_ids:
        err = make_error(
            code="seed_not_found",
            message=f"no tax_measure matched {measure_name_or_id!r}.",
            hint=(
                "Try search_tax_incentives(query=...) first to find the "
                "canonical_id, then retry get_am_tax_rule()."
            ),
            retry_with=["search_tax_incentives"],
            suggested_tools=["search_tax_incentives"],
            field="measure_name_or_id",
            extra={"queried": measure_name_or_id},
        )
        return {"total": 0, "results": [], "error": err["error"]}

    # ---- query rules -----------------------------------------------------
    placeholders = ",".join("?" * len(measure_ids))
    params: list[Any] = list(measure_ids)
    sql = f"""
        SELECT
            r.tax_measure_entity_id,
            r.rule_type,
            r.base_rate_pct,
            r.cap_yen,
            r.eligibility_cond_json,
            r.combinable_with,
            r.effective_from,
            r.effective_until,
            r.article_ref,
            r.source_url,
            r.source_fetched_at,
            r.note,
            m.primary_name,
            m.canonical_status
          FROM am_tax_rule r
          JOIN am_entities m
            ON m.canonical_id = r.tax_measure_entity_id
         WHERE r.tax_measure_entity_id IN ({placeholders})
    """
    if rule_type is not None:
        sql += " AND r.rule_type = ? "
        params.append(rule_type)

    if as_of is not None:
        # effective_from IS NULL (= 恒久) はすべて通す
        sql += (
            " AND (r.effective_from IS NULL OR r.effective_from <= ?) "
            " AND (r.effective_until IS NULL OR r.effective_until >= ?) "
        )
        params.extend([as_of, as_of])

    sql += " ORDER BY r.tax_measure_entity_id, r.rule_type "

    try:
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
    except sqlite3.Error as exc:
        logger.exception("get_tax_rule query failed")
        err = make_error(
            code="db_unavailable",
            message=str(exc),
            hint="autonomath.db query failed; retry later or fall back to search_tax_incentives.",
            retry_with=["search_tax_incentives"],
        )
        return {"total": 0, "results": [], "error": err["error"]}

    results = [_row_to_tax_rule(r) for r in rows]

    # ---- empty-result envelope ----------------------------------------
    if not results and measure_ids:
        # The measure exists but has no am_tax_rule rows yet.
        err = make_error(
            code="no_matching_records",
            message=(
                f"{len(measure_ids)} tax_measure matched but no am_tax_rule "
                "rows found. This measure has not been structured yet."
            ),
            hint="Fall back to search_tax_incentives() and parse raw_json.",
            retry_with=["search_tax_incentives"],
            extra={"queried": measure_name_or_id, "matched_measure_ids": measure_ids},
        )
        return {"total": 0, "results": [], "error": err["error"]}

    # ---- abolished hint on successful results -------------------------
    out: dict[str, Any] = {"total": len(results), "results": results}
    abolished = [
        r["tax_measure"]["name"]
        for r in results
        if r["tax_measure"]["canonical_status"] == "abolished"
    ]
    if abolished:
        unique = sorted(set(abolished))
        out["hint"] = (
            f"注意: 次の制度は廃止済みです: {', '.join(unique)}. "
            "effective_until と note を確認してください。"
        )
    return out


# ---------------------------------------------------------------------------
# Self-test harness (not part of MCP surface).
#
#   python3 tax_rule_tool.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import pprint

    for q in [
        "DX投資促進税制",
        "5G",
        "エンジェル税制 (優遇措置A)",
        "エンジェル税制 (優遇措置B)",
        "エンジェル税制 (プレシード",
        "存在しない税制XYZ",
    ]:
        print(f"\n=== query={q!r} ===")
        res = get_am_tax_rule.fn(q)  # fn unwraps FastMCP decoration
        print(f"total={res['total']}")
        if res.get("error"):
            print(f"error.code={res['error']['code']} error.message={res['error']['message']}")
        if res.get("hint"):
            print(f"hint={res['hint']}")
        for r in res["results"][:3]:
            pprint.pprint(
                {
                    "name": r["tax_measure"]["name"],
                    "status": r["tax_measure"]["canonical_status"],
                    "rule_type": r["rule_type"],
                    "rate_pct": r["base_rate_pct"],
                    "cap_yen": r["cap_yen"],
                    "effective_until": r["effective_period"]["until"],
                    "article": r["article_ref"],
                }
            )
