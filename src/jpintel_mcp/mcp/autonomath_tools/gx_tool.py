"""Wave 13 #1 MCP tool stub: search_gx_programs.

This file is a *proposed* addition to
`src/jpintel_mcp/mcp/server.py`. It is NOT wired into production — the
Wave 13 brief explicitly forbids touching production files. To apply:

    1.  Merge the `from jpintel_mcp.db.session import connect` import if not
        present (it already is in server.py).
    2.  Append the decorated function below just before the `def run() -> None`
        block near the bottom of server.py.
    3.  Run `pytest tests/mcp/` to confirm.

The tool is read-only, queries am_entities rows with canonical_id matching
'program:gx:%' populated by `ingest/gx_seed/ingest.py`. It joins
am_amount_condition and am_application_round for eligibility_quick_summary.

Returned keys:
    canonical_id, program_name, theme, agency, program_kind,
    amount_max_yen, subsidy_rate,
    currently_open_rounds[], past_rounds_count,
    target_types[], eligibility_quick_summary,
    source_url
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
DB_PATH = Path(os.environ.get(
    "AUTONOMATH_DB_PATH",
    str(_REPO_ROOT / "autonomath.db"),
))

VALID_THEMES = {"ghg_reduction", "ev", "renewable", "zeb_zeh", "carbon_credit"}
VALID_COMPANY_SIZES = {"sme", "large", "midsize", "individual", "municipality", "farmer"}

# 日本語表現 -> target_types raw tokens we injected
COMPANY_SIZE_TO_TOKENS = {
    "sme": ["中小企業"],
    "midsize": ["中堅企業"],
    "large": ["大企業"],
    "individual": ["個人"],
    "municipality": ["自治体"],
    "farmer": ["農業者"],
}


def _connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _classify_eligibility(raw: dict[str, Any]) -> str:
    """Build a 1-line quick summary string from raw_json + amount."""
    target = raw.get("target_types") or []
    desc = raw.get("eligibility_summary") or ""
    rate = raw.get("subsidy_rate")
    amax = raw.get("amount_max_yen")
    parts: list[str] = []
    if target:
        parts.append(f"対象: {'・'.join(target)}")
    if rate is not None:
        parts.append(f"補助率 {rate*100:.1f}%")
    if amax is not None:
        parts.append(f"上限 {int(amax):,}円")
    if desc:
        parts.append(desc[:80])
    return " / ".join(parts)


def _get_open_rounds(conn: sqlite3.Connection, cid: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT round_label, application_open_date, application_close_date, status
           FROM am_application_round
           WHERE program_entity_id = ?
             AND status IN ('open', 'upcoming')
           ORDER BY round_seq DESC LIMIT 3""",
        (cid,),
    ).fetchall()
    return [dict(r) for r in rows]


def _count_past_rounds(conn: sqlite3.Connection, cid: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM am_application_round WHERE program_entity_id=? AND status='closed'",
        (cid,),
    ).fetchone()
    return int(row[0]) if row else 0


def search_gx_programs(
    theme: str = "ghg_reduction",
    region: str | None = None,
    company_size: str | None = None,
    limit: int = 20,
    db_path: Path | str = DB_PATH,
) -> list[dict[str, Any]]:
    """Search GX/EV/再エネ/ZEB-ZEH/carbon_credit curated programs.

    Args:
        theme: One of {'ghg_reduction', 'ev', 'renewable', 'zeb_zeh', 'carbon_credit'}.
        region: Optional region_code filter (e.g. '01' for 北海道). Currently unused
                for nationally applicable GX programs — kept for forward-compat.
        company_size: One of {'sme','midsize','large','individual','municipality','farmer'}.
                      Filters by target_types intersection.
        limit: Max rows to return.
        db_path: override for tests.

    Returns:
        List of dicts with canonical_id, program_name, theme, agency, program_kind,
        amount_max_yen, subsidy_rate, currently_open_rounds, past_rounds_count,
        target_types, eligibility_quick_summary, source_url.

    Raises:
        ValueError on unknown theme / company_size.
    """
    if theme not in VALID_THEMES:
        raise ValueError(f"unknown theme: {theme!r}; expected one of {sorted(VALID_THEMES)}")
    if company_size is not None and company_size not in VALID_COMPANY_SIZES:
        raise ValueError(f"unknown company_size: {company_size!r}")

    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """SELECT e.canonical_id, e.primary_name, e.source_url,
                      e.authority_canonical, e.raw_json
               FROM am_entities e
               WHERE e.canonical_id LIKE 'program:gx:%'
                 AND json_extract(e.raw_json, '$.gx_theme') = ?
               ORDER BY e.canonical_id
               LIMIT ?""",
            (theme, limit * 3),  # we'll post-filter for company_size
        ).fetchall()

        results: list[dict[str, Any]] = []
        for r in rows:
            raw = json.loads(r["raw_json"])
            target_types = raw.get("target_types") or []

            if company_size:
                toks = COMPANY_SIZE_TO_TOKENS[company_size]
                if not any(t in target_types for t in toks):
                    continue

            cid = r["canonical_id"]
            item = {
                "canonical_id": cid,
                "program_name": r["primary_name"],
                "theme": theme,
                "agency": raw.get("authority_slug"),
                "authority_canonical": r["authority_canonical"],
                "program_kind": raw.get("program_kind"),
                "amount_max_yen": raw.get("amount_max_yen"),
                "subsidy_rate": raw.get("subsidy_rate"),
                "target_types": target_types,
                "currently_open_rounds": _get_open_rounds(conn, cid),
                "past_rounds_count": _count_past_rounds(conn, cid),
                "eligibility_quick_summary": _classify_eligibility(raw),
                "source_url": r["source_url"],
                "references_law": raw.get("references_law") or [],
            }
            results.append(item)
            if len(results) >= limit:
                break
        return results
    finally:
        conn.close()


def list_themes(db_path: Path | str = DB_PATH) -> dict[str, int]:
    """Helper: return theme -> count for coverage reporting."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """SELECT json_extract(raw_json, '$.gx_theme') AS theme, COUNT(*) AS cnt
               FROM am_entities
               WHERE canonical_id LIKE 'program:gx:%'
               GROUP BY theme"""
        ).fetchall()
        return {r["theme"]: r["cnt"] for r in rows if r["theme"]}
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    theme = sys.argv[1] if len(sys.argv) > 1 else "ev"
    for row in search_gx_programs(theme=theme, limit=5):
        print(row["canonical_id"], "|", row["program_name"])
        print("  ", row["eligibility_quick_summary"])
        print("  open:", row["currently_open_rounds"])
