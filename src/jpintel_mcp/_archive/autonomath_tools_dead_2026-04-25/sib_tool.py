"""
SIB / PFS (成果連動型民間委託契約) search tool skeleton.

AutonoMath MCP server (Wave 9+ Agent #8 additions).
Self-contained — mirror style of `acceptance_stats_tool.py` / `tax_rule_tool.py`.

Exposed:
    search_sib_contracts(
        prefecture: str | None = None,
        outcome_kpi_contains: str | None = None,
        contract_type: str | None = None,   # 'sib' | 'pfs' | 'sib_pfs_hybrid' | 'policy'
        limit: int = 10,
    ) -> dict

Returns JSON envelope:
    {
      "version": 1,
      "total": int,
      "rows": [
        {
          "canonical_id": "sib:...",
          "contract_name": "...",
          "contract_type": "sib",
          "implementing_body": "...",
          "implementing_authority": "authority:city-kobe",
          "service_provider_group": "...",
          "outcome_kpi_json": [...],
          "payment_schedule": "...",
          "contract_value_yen": 97000000,
          "period": {"start": "2017-07-01", "end": "2020-03-31"},
          "source_url": "https://www.city.../"
        },
        ...
      ]
    }

DB schema guard: am_sib_contract + am_authority. 絶対 Anthropic API を呼ばない.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DB = Path(os.environ.get(
    "AUTONOMATH_DB_PATH",
    str(_REPO_ROOT / "autonomath.db"),
))

# crude prefecture → authority prefix map for filtering
_PREF_HINTS = {
    "東京": ("authority:pref-tokyo", "authority:city-hachioji"),
    "兵庫": ("authority:pref-hyogo", "authority:city-kobe", "authority:city-takarazuka"),
    "京都": ("authority:pref-kyoto", "authority:city-kyoto", "authority:city-kameoka"),
    "広島": ("authority:pref-hiroshima", "authority:city-hiroshima"),
    "三重": ("authority:pref-mie",),
    "愛知": ("authority:pref-aichi", "authority:city-nagoya"),
    "埼玉": ("authority:pref-saitama",),
    "岩手": ("authority:pref-iwate",),
    "神奈川": ("authority:city-yokohama",),
    "福岡": ("authority:pref-fukuoka", "authority:city-fukuoka"),
    "北海道": ("authority:pref-hokkaido", "authority:hokkaido-tokachi"),
}


def _connect(db_path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    return con


def search_sib_contracts(
    prefecture: str | None = None,
    outcome_kpi_contains: str | None = None,
    contract_type: str | None = None,
    limit: int = 10,
    db_path: Path | str = DEFAULT_DB,
) -> dict[str, Any]:
    """Search SIB/PFS contracts. Returns MCP-ready envelope."""
    if not (1 <= int(limit) <= 100):
        limit = 10

    clauses: list[str] = []
    params: list[Any] = []

    if prefecture:
        hints = _PREF_HINTS.get(prefecture.strip("都道府県 "))
        if hints:
            placeholders = ",".join("?" * len(hints))
            clauses.append(f"implementing_authority IN ({placeholders})")
            params.extend(hints)
        else:
            # fallback: substring match on implementing_body
            clauses.append("implementing_body LIKE ?")
            params.append(f"%{prefecture}%")

    if contract_type:
        clauses.append("contract_type = ?")
        params.append(contract_type)

    if outcome_kpi_contains:
        clauses.append("outcome_kpi_json LIKE ?")
        params.append(f"%{outcome_kpi_contains}%")

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
        SELECT canonical_id, contract_name, contract_type,
               implementing_body, implementing_authority,
               service_provider_group, outcome_kpi_json,
               payment_schedule, contract_value_yen,
               period_start, period_end, source_url
          FROM am_sib_contract
          {where}
          ORDER BY (period_start IS NULL), period_start DESC
          LIMIT ?
    """
    params.append(limit)

    with _connect(db_path) as con:
        cur = con.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]

    # Normalize outcome_kpi_json -> list
    for r in rows:
        try:
            r["outcome_kpi_json"] = json.loads(r["outcome_kpi_json"] or "[]")
        except Exception:
            r["outcome_kpi_json"] = []
        r["period"] = {"start": r.pop("period_start"), "end": r.pop("period_end")}

    return {
        "version": 1,
        "total": len(rows),
        "rows": rows,
    }


# --- smoke test ---
if __name__ == "__main__":
    import pprint

    for kw, expect in [
        (dict(prefecture="兵庫"), "兵庫 (神戸/宝塚)"),
        (dict(outcome_kpi_contains="がん"), "がん KPI"),
        (dict(contract_type="policy"), "国 policy"),
        (dict(), "全件 top10"),
    ]:
        print(f"\n=== {expect} ({kw}) ===")
        res = search_sib_contracts(**kw, limit=3)
        pprint.pp({"total": res["total"], "ids": [r["canonical_id"] for r in res["rows"]]})
