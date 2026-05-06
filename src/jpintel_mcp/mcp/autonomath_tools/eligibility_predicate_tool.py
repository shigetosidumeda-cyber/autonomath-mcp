"""get_program_eligibility_predicate — machine-readable eligibility cache.

Returns the JSON predicate cached in
``am_program_eligibility_predicate_json`` (autonomath.db, migration 164)
for one program. Customer LLMs can evaluate "does program X cover corp Y?"
via simple boolean logic over the predicate object instead of re-reading
公募要領 prose every query — drops per-evaluation token cost.

Why this is its own tool (not folded into search_*):
  * The predicate is **per-program** and **stable across queries**, so a
    customer that already has a program_id from search_programs / similar
    can fan out N predicate fetches and evaluate locally.
  * The shape is a single JSON blob optimized for the LLM, distinct from
    the row-per-predicate ``am_program_eligibility_predicate`` table
    (wave24_137) which targets SQL filter UIs.

Predicate shape (all axes optional; missing key = unknown, NOT "no
constraint"):
    {
      "industries_jsic":      ["A","D"],          -- JSIC major letters
      "prefectures":          ["大阪府"],          -- Japanese names
      "prefecture_jis":       ["27"],             -- 2-digit JIS codes
      "municipalities":       ["大阪市"],
      "capital_max_yen":      300000000,
      "employee_max":         300,
      "min_business_years":   1,
      "target_entity_types":  ["corporation", "sole_proprietor"],
      "crop_categories":      ["facility_vegetable"],
      "funding_purposes":     ["設備投資"],
      "certifications_any_of":["中小企業者"],
      "age":                  {"min": null, "max": 67},
      "raw_constraints":      ["original sentence", ...]
    }
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.new.eligibility_predicate")


def _safe_json_loads(blob: str | None) -> Any:
    if not blob:
        return None
    try:
        return json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return None


@mcp.tool(annotations=_READ_ONLY)
def get_program_eligibility_predicate(
    program_id: Annotated[
        str,
        Field(
            description=(
                "jpi_programs.unified_id (例: 'UNI-75690a3d74'). "
                "search_programs / list_open_programs などの結果から取得。"
            ),
            min_length=4,
            max_length=64,
        ),
    ],
    include_raw_constraints: Annotated[
        bool,
        Field(
            description=(
                "True で raw_constraints (regex 抽出失敗の生 text) を含める。"
                "False で軽量 envelope のみ返す (token 節約用)。"
            ),
        ),
    ] = True,
) -> dict[str, Any]:
    """[ELIGIBILITY] Returns a structured eligibility predicate for one program so the customer LLM can evaluate fit (industry/prefecture/capital/employees/age/crop/cert) with boolean logic instead of re-reading 公募要領. Predicate is search-derived from jpi_programs corpus snapshot (migration 164); a missing axis means "unknown", NOT "no constraint" — verify primary source (source_url) before final eligibility decision.

    WHAT: SELECT predicate_json FROM am_program_eligibility_predicate_json
          WHERE program_id = ?  → return parsed predicate object.

    WHEN:
      - 「この補助金、当社 (大阪府, 製造業, 資本金1000万, 従業員10名) で受けられる?」
      - N programs を customer 側で並列に判定するとき (LLM token 節約)
      - 営業 funnel での自動 pre-screen

    WHEN NOT:
      - narrative 説明が欲しい → search_programs / get_program_abstract
      - 全件 filter したい (capital >= X 等) → wave24_137 の row 構造側
      - LLM 抽出済 v2 がほしい → 別 wave で公開 (extraction_method='llm_extracted')

    RETURNS (envelope):
      {
        program_id: str,
        program_name: str,             # joined from jpi_programs
        predicate: { industries_jsic, prefectures, capital_max_yen, ... },
        extraction_method: 'rule_based' | 'llm_extracted' | 'manual',
        confidence: float,             # 0.0..1.0
        extracted_at: str,             # ISO timestamp
        source_program_corpus_snapshot_id: str|null,
        notes: [str],                  # interpretation hints for the LLM
      }

    Returns the canonical error envelope (``code='no_matching_records'``)
    when program_id is unknown.
    """

    sql = """
        SELECT pred.program_id,
               pred.predicate_json,
               pred.extraction_method,
               pred.confidence,
               pred.extracted_at,
               pred.source_program_corpus_snapshot_id,
               prog.primary_name
          FROM am_program_eligibility_predicate_json pred
          LEFT JOIN jpi_programs prog
            ON prog.unified_id = pred.program_id
         WHERE pred.program_id = ?
         LIMIT 1
    """

    try:
        conn = connect_autonomath()
        row = conn.execute(sql, (program_id,)).fetchone()
    except (sqlite3.Error, FileNotFoundError) as exc:
        logger.exception("get_program_eligibility_predicate query failed")
        err = make_error(
            code="db_unavailable",
            message=str(exc),
            hint="autonomath.db unreachable; retry shortly.",
            retry_with=["search_programs"],
        )
        return {
            "program_id": program_id,
            "program_name": None,
            "predicate": {},
            "extraction_method": None,
            "confidence": None,
            "extracted_at": None,
            "source_program_corpus_snapshot_id": None,
            "notes": [],
            "error": err["error"],
        }

    if row is None:
        err = make_error(
            code="no_matching_records",
            message=f"no predicate cached for program_id={program_id!r}",
            hint=(
                "Verify program_id via search_programs / list_open_programs. "
                "If the program exists but has no predicate row, the corpus "
                "snapshot may pre-date migration 164 — re-run "
                "scripts/etl/extract_eligibility_predicate.py."
            ),
            retry_with=["search_programs", "get_program_abstract"],
        )
        return {
            "program_id": program_id,
            "program_name": None,
            "predicate": {},
            "extraction_method": None,
            "confidence": None,
            "extracted_at": None,
            "source_program_corpus_snapshot_id": None,
            "notes": [],
            "error": err["error"],
        }

    predicate = _safe_json_loads(row["predicate_json"]) or {}
    if not include_raw_constraints and "raw_constraints" in predicate:
        predicate = {k: v for k, v in predicate.items() if k != "raw_constraints"}

    notes = [
        "missing_axis_means_unknown — absent key does NOT mean no constraint",
        "verify_primary_source_before_filing — predicate is search-derived",
    ]
    method = row["extraction_method"]
    if method == "rule_based":
        notes.append(
            "rule_based extraction: regex over jpi_programs.enriched_json — "
            "expect partial coverage, confidence reflects axis density"
        )

    return {
        "program_id": row["program_id"],
        "program_name": row["primary_name"],
        "predicate": predicate,
        "extraction_method": method,
        "confidence": row["confidence"],
        "extracted_at": row["extracted_at"],
        "source_program_corpus_snapshot_id": row["source_program_corpus_snapshot_id"],
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Self-test (not on MCP surface).
#
#   .venv/bin/python -m jpintel_mcp.mcp.autonomath_tools.eligibility_predicate_tool
# ---------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import pprint
    import sys

    pid = sys.argv[1] if len(sys.argv) > 1 else "UNI-75690a3d74"
    res = get_program_eligibility_predicate(pid)
    pprint.pprint(res)
