"""list_tax_sunset_alerts — V1 feature #11 (dd_v4_05 / v8 P3-J).

Returns 税制優遇 measures whose ``effective_until`` falls within the next
``days_until`` days. ``only_critical=True`` filters to the cliff dates
identified in the dd_v4_05 audit (notably 2027-03-31 with 29 rules) plus
the other 12月大綱-driven concentration buckets.

Schema source: ``am_tax_rule`` (PK = tax_measure_entity_id + rule_type) is
the single hand-curated structured table. ``effective_until`` is set on 57
rows out of the population. We JOIN ``am_entities`` for the parent
``primary_name`` / ``canonical_status`` so the agent sees the human-readable
measure name, not just the canonical_id.

Customer questions answered:
  - 「来年度どの税制優遇が消えるか」
  - 「事業計画 cliff alert: 2027/3/31 で何が切れるか」
  - 「今年中 (365日) に廃止される措置リストは?」

Returns the canonical envelope with ``cliff_dates`` concentration buckets
so the LLM can spot 大綱-driven sunset clusters without re-aggregating.
"""

from __future__ import annotations

import datetime
import logging
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.new.sunset")

# 大綱-driven cliff concentration buckets observed in the 2026-04-25 audit
# (dd_v4_05). 2027-03-31 holds 29 rules; the other dates are smaller but
# still policy-driven (年度末 / 年末) sunset clusters that historically
# trigger 延長 / 廃止 decisions in the 12月大綱.
_CRITICAL_CLIFF_DATES: frozenset[str] = frozenset({
    "2025-03-31",
    "2025-12-31",
    "2026-03-31",
    "2026-12-31",
    "2027-03-31",
    "2027-12-31",
    "2028-03-31",
})


@mcp.tool(annotations=_READ_ONLY)
def list_tax_sunset_alerts(
    days_until: Annotated[
        int,
        Field(
            ge=1,
            le=1825,
            description=(
                "今日から N 日以内に effective_until を迎える税制措置を列挙 "
                "(default 365 = 1年, max 1825 = 5年)。"
            ),
        ),
    ] = 365,
    only_critical: Annotated[
        bool,
        Field(
            description=(
                "12月大綱-driven cliff dates (年度末 3/31 / 年末 12/31) "
                "に該当する rule のみ返す。False なら全 expiring rule。"
            ),
        ),
    ] = False,
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=500,
            description=(
                "返却する sunset alert 行の最大件数. Range [1, 500]. Default 100. "
                "earliest expiring 順. summary 用は 20-50, 全列挙は 200-500 が現実的."
            ),
        ),
    ] = 100,
) -> dict[str, Any]:
    """[TIMELINE-TAX] 税制優遇の sunset (effective_until) calendar — N 日以内に切れる措置 + 大綱 cliff buckets を 1 コール。

    WHAT: ``am_tax_rule.effective_until`` が today..today+days_until に入る
    rule を ``am_entities`` (parent measure) と JOIN して返す。同じ
    measure が複数 rule_type を持つ場合は別行 (= 別 rule) として返す。

    WHEN:
      - 「来年度どの税制優遇が消えるか?」
      - 「2027-03-31 cliff の影響範囲は?」(only_critical=True で絞れる)
      - 事業計画 / 投資判断における sunset alert

    WHEN NOT:
      - 全税制 list が欲しい → search_tax_incentives
      - 特定 rule の詳細 → get_am_tax_rule(measure_name_or_id)
      - 廃止後の後継制度 → get_am_tax_rule + ``note`` フィールド参照

    RETURNS (envelope):
      {
        total: int,
        results: [
          {
            measure: { canonical_id, name, canonical_status },
            rule_type: str,                # credit / deduction / ...
            base_rate_pct: float|null,
            cap_yen: int|null,
            effective_from: str|null,
            effective_until: str,          # YYYY-MM-DD
            days_remaining: int,
            article_ref: str|null,
            source_url: str,
            note: str|null,
            is_critical_cliff: bool,
          }, ...
        ],
        cliff_dates: { "2027-03-31": 29, ... },  # bucket counts (within window)
        data_as_of: str,                          # today JST ISO date
        filter_applied: { days_until, only_critical, limit },
      }

    On failure / empty result returns the canonical error envelope
    (``code`` ∈ {``no_matching_records``, ``db_unavailable``}) with
    ``retry_with`` pointing back to ``search_tax_incentives``.

    0 件の場合は `hint` (再検索の提案) と `retry_with` (関連 tool 候補) を返します。
    """
    # JST today (autonomath canonical timezone for sunset calendars). Fly.io
    # machines run UTC, so a naive date.today() drifts 9h: a 適用期限 of
    # 2027-03-31 would be marked past on 2027-04-01 02:00 JST. Use JST pivot.
    today = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=9)).date()
    cutoff = today + datetime.timedelta(days=days_until)

    sql = """
        SELECT
            r.tax_measure_entity_id,
            r.rule_type,
            r.base_rate_pct,
            r.cap_yen,
            r.effective_from,
            r.effective_until,
            r.article_ref,
            r.source_url,
            r.note,
            m.primary_name,
            m.canonical_status
          FROM am_tax_rule r
          JOIN am_entities m
            ON m.canonical_id = r.tax_measure_entity_id
         WHERE r.effective_until IS NOT NULL
           AND r.effective_until BETWEEN ? AND ?
         ORDER BY r.effective_until ASC, m.primary_name ASC, r.rule_type ASC
         LIMIT ?
    """

    try:
        conn = connect_autonomath()
        rows = conn.execute(sql, (today.isoformat(), cutoff.isoformat(), limit)).fetchall()
    except (sqlite3.Error, FileNotFoundError) as exc:
        logger.exception("list_tax_sunset_alerts query failed")
        err = make_error(
            code="db_unavailable",
            message=str(exc),
            hint=(
                "autonomath.db unreachable; retry later or fall back to "
                "search_tax_incentives() and inspect raw_json.effective_until."
            ),
            retry_with=["search_tax_incentives"],
        )
        return {
            "total": 0,
            "results": [],
            "cliff_dates": {},
            "data_as_of": today.isoformat(),
            "filter_applied": {
                "days_until": days_until,
                "only_critical": only_critical,
                "limit": limit,
            },
            "error": err["error"],
        }

    results: list[dict[str, Any]] = []
    cliff_buckets: dict[str, int] = {}
    for row in rows:
        eu = row["effective_until"]
        is_critical = eu in _CRITICAL_CLIFF_DATES
        if only_critical and not is_critical:
            continue
        try:
            days_rem = (datetime.date.fromisoformat(eu) - today).days
        except (TypeError, ValueError):
            days_rem = None
        cliff_buckets[eu] = cliff_buckets.get(eu, 0) + 1
        results.append({
            "measure": {
                "canonical_id": row["tax_measure_entity_id"],
                "name": row["primary_name"],
                "canonical_status": row["canonical_status"],
            },
            "rule_type": row["rule_type"],
            "base_rate_pct": row["base_rate_pct"],
            "cap_yen": row["cap_yen"],
            "effective_from": row["effective_from"],
            "effective_until": eu,
            "days_remaining": days_rem,
            "article_ref": row["article_ref"],
            "source_url": row["source_url"],
            "note": row["note"],
            "is_critical_cliff": is_critical,
        })

    out: dict[str, Any] = {
        "total": len(results),
        "results": results,
        "cliff_dates": dict(sorted(cliff_buckets.items())),
        "data_as_of": today.isoformat(),
        "filter_applied": {
            "days_until": days_until,
            "only_critical": only_critical,
            "limit": limit,
        },
    }

    if not results:
        err = make_error(
            code="no_matching_records",
            message=(
                f"no am_tax_rule rows expire within {days_until} days "
                f"(today={today.isoformat()}, cutoff={cutoff.isoformat()}"
                f"{', only_critical=True' if only_critical else ''})."
            ),
            hint=(
                "Try widening days_until (e.g. 730 = 2年) or set "
                "only_critical=False. Use search_tax_incentives() for the "
                "full list of 税制優遇."
            ),
            retry_with=["search_tax_incentives"],
        )
        out["error"] = err["error"]

    return out


# ---------------------------------------------------------------------------
# Self-test harness (not part of MCP surface).
#
#   .venv/bin/python -m jpintel_mcp.mcp.autonomath_tools.sunset_tool
# ---------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import pprint

    for kw in (
        {"days_until": 365, "only_critical": False, "limit": 5},
        {"days_until": 730, "only_critical": True, "limit": 10},
        {"days_until": 1825, "only_critical": False, "limit": 200},
    ):
        print(f"\n=== {kw} ===")
        res = list_tax_sunset_alerts(**kw)  # @mcp.tool returns the bare function
        print(f"total={res['total']}, cliff_dates={res['cliff_dates']}")
        for r in res["results"][:3]:
            pprint.pprint({
                "name": r["measure"]["name"],
                "status": r["measure"]["canonical_status"],
                "rule_type": r["rule_type"],
                "until": r["effective_until"],
                "days_remaining": r["days_remaining"],
                "is_critical": r["is_critical_cliff"],
            })
