"""Transparency endpoints — public trust signals.

Two read-only endpoints, both public (no auth, no AnonIpLimitDep), backing
site/data-freshness.html and site/transparency.html:

  GET /v1/am/data-freshness
      Per-dataset row counts + newest fetched_at + license + ministry.
      Aggregated across the 9 jpi_* datasets in autonomath.db. Stale-status
      flags (fresh / stale_30d / stale_90d) are computed server-side so the
      page doesn't ship business rules into the browser.

  GET /v1/am/programs/{program_id}/sources
      Per-record cite chain for one programs row. Joins am_entity_source
      onto am_source so callers can see every primary URL we used to
      compose the row, plus per-URL license + first_seen + last_verified.

Both endpoints are intentionally CORS-open (Access-Control-Allow-Origin: *)
because the static pages live on jpcite.com and call api.jpcite.com
from JS. The handlers issue zero writes, hold no state, and return ASCII-
clean JSON. A 30-second in-process cache absorbs landing-page bursts.

Design notes:
- No coupling to autonomath.py (the other agent owns that file). This
  file lands its own router and main.py mounts it under /v1/am/* alongside
  the existing autonomath_router.
- Read-only sqlite via mode=ro URI; we deliberately do not reuse
  jpintel_mcp.db.session.connect() because that targets jpintel.db whereas
  the data we expose lives in autonomath.db (the post-merge unified DB).
- Stale thresholds: > 30 days = stale_30d (yellow), > 90 days = stale_90d
  (red). These mirror docs/data_hygiene.md and the _health_deep thresholds.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi import Path as PathParam

from jpintel_mcp.config import settings

router = APIRouter(prefix="/v1/am", tags=["transparency", "trust"])


# ---- dataset registry --------------------------------------------------------
# Ordered so the response shape is stable across calls (and across redeploys).
# Each entry: (dataset name, jpi_* table, fetched-at column, license, source
# ministry / authority). fetched_at column varies by table — laws / court /
# bids / invoice_registrants / tax_rulesets use `fetched_at`, programs uses
# `source_fetched_at`, case_studies / loan_programs use `fetched_at`,
# enforcement_cases uses `fetched_at`. NULL-safe MAX() handles missing rows.
_DATASETS: tuple[tuple[str, str, str, str, str], ...] = (
    ("programs", "jpi_programs", "source_fetched_at", "gov_standard_v2.0",
     "経済産業省 / 中小企業庁 / 各都道府県"),
    ("case_studies", "jpi_case_studies", "fetched_at", "gov_standard_v2.0",
     "農林水産省 / METI / JST"),
    ("loan_programs", "jpi_loan_programs", "fetched_at", "proprietary",
     "日本政策金融公庫 (公開ページのみ)"),
    ("enforcement_cases", "jpi_enforcement_cases", "fetched_at",
     "gov_standard_v2.0",
     "国土交通省 / 厚生労働省 / 環境省 / 都道府県"),
    ("laws", "jpi_laws", "fetched_at", "cc_by_4.0", "デジタル庁 e-Gov 法令"),
    ("court_decisions", "jpi_court_decisions", "fetched_at", "public_domain",
     "知的財産高等裁判所 / 特許庁 / 公開判決"),
    ("bids", "jpi_bids", "fetched_at", "proprietary",
     "NEXCO / JR / UR / 各発注機関"),
    ("invoice_registrants", "jpi_invoice_registrants", "fetched_at",
     "pdl_v1.0", "国税庁 適格請求書発行事業者公表"),
    ("tax_rulesets", "jpi_tax_rulesets", "fetched_at", "public_domain",
     "国税庁 通達"),
)


# ---- helpers -----------------------------------------------------------------
def _open_ro(path: Path) -> sqlite3.Connection:
    """Open autonomath.db read-only via URI to avoid creating an empty file."""
    uri = f"file:{path}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=2.0)
    con.row_factory = sqlite3.Row
    return con


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


def _utcnow_iso() -> str:
    return _utcnow().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(val: str | None) -> _dt.datetime | None:
    if not val:
        return None
    s = val.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = _dt.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.UTC)
        return dt
    except ValueError:
        try:
            d = _dt.date.fromisoformat(val[:10])
            return _dt.datetime.combine(d, _dt.time.min, tzinfo=_dt.UTC)
        except Exception:  # noqa: BLE001
            return None


def _staleness(days: int | None) -> str:
    if days is None:
        return "unknown"
    if days > 90:
        return "stale_90d"
    if days > 30:
        return "stale_30d"
    return "fresh"


# ---- 30-second response cache ------------------------------------------------
# Aggregating 9 SELECT MAX(fetched_at) + COUNT(*) per call against an 8 GB DB
# is cheap (each is index-only) but landing-page traffic bursts make a 30s
# cache worth the minimal staleness window.
_CACHE: dict[str, Any] = {"ts": 0.0, "doc": None}
_CACHE_TTL: float = 30.0


def _build_freshness_doc(now: _dt.datetime | None = None) -> dict[str, Any]:
    """Compose the per-dataset freshness document. Pure helper, testable."""
    now = now or _utcnow()
    db = settings.autonomath_db_path
    rows: list[dict[str, Any]] = []
    if not db.exists():
        return {
            "datasets": [],
            "generated_at": _utcnow_iso(),
            "note": "autonomath.db missing on this node",
        }
    with _open_ro(db) as con:
        for name, table, fa_col, license_, source in _DATASETS:
            try:
                count_row = con.execute(
                    f"SELECT COUNT(*) AS n FROM {table}"
                ).fetchone()
                fetched_row = con.execute(
                    f"SELECT MAX({fa_col}) AS fa FROM {table}"
                ).fetchone()
                count = int(count_row["n"]) if count_row else 0
                fetched = (fetched_row["fa"] if fetched_row else None) or None
            except sqlite3.Error as e:
                rows.append({
                    "name": name,
                    "row_count": 0,
                    "last_fetched_at": None,
                    "days_ago": None,
                    "staleness": "unknown",
                    "license": license_,
                    "source": source,
                    "error": str(e),
                })
                continue
            dt = _parse_iso(fetched)
            days_ago = max(0, int((now - dt).total_seconds() // 86400)) if dt else None
            rows.append({
                "name": name,
                "row_count": count,
                "last_fetched_at": dt.date().isoformat() if dt else None,
                "days_ago": days_ago,
                "staleness": _staleness(days_ago),
                "license": license_,
                "source": source,
            })
    return {
        "datasets": rows,
        "generated_at": _utcnow_iso(),
    }


@router.get("/data-freshness")
async def data_freshness() -> dict[str, Any]:
    """Public per-dataset freshness snapshot (no auth).

    Cached 30 s in-process; the page polls every 5 minutes by default. The
    response shape is intentionally simple so the static page can render it
    with a few lines of vanilla JS without a parser:

        {
          "datasets": [
            {"name": "programs", "row_count": 13578,
             "last_fetched_at": "2026-04-25", "days_ago": 4,
             "staleness": "fresh",
             "license": "gov_standard_v2.0",
             "source": "経済産業省 / 中小企業庁 / 各都道府県"},
            ...
          ],
          "generated_at": "2026-04-29T01:23:45Z"
        }
    """
    now_mono = time.monotonic()
    if (
        _CACHE["doc"] is not None
        and now_mono - _CACHE["ts"] < _CACHE_TTL
    ):
        return _CACHE["doc"]
    doc = _build_freshness_doc()
    _CACHE["ts"] = now_mono
    _CACHE["doc"] = doc
    return doc


# ---- per-program cite chain --------------------------------------------------
@router.get("/programs/{program_id}/sources")
async def program_sources(
    program_id: str = PathParam(..., min_length=1, max_length=120),
) -> dict[str, Any]:
    """Per-program cite chain — every primary URL used to compose the row.

    Joins am_entity_source × am_source for the entity matching this
    program's unified_id (looked up via entity_id_map). Returns:

        {
          "program_id": "UNI-...",
          "entity_id": "AM-...",
          "name": "...",
          "sources": [
            {"source_url": "https://...", "source_type": "primary",
             "domain": "meti.go.jp", "license": "gov_standard_v2.0",
             "is_pdf": false, "first_seen": "2026-03-12",
             "last_verified": "2026-04-25",
             "role": "primary_source", "source_field": "official_url"},
            ...
          ],
          "generated_at": "2026-04-29T01:23:45Z"
        }

    Returns 404 if the program is unknown to either jpi_programs or
    entity_id_map. Cite-chain transparency is the differentiator vs
    aggregator sites — we publish every URL, no opaque "scraped from
    multiple sources" claims.
    """
    db = settings.autonomath_db_path
    if not db.exists():
        raise HTTPException(status_code=503, detail="db missing")
    with _open_ro(db) as con:
        # Resolve unified_id → primary_name (the canonical column name on
        # jpi_programs; the ergonomic alias `name` is exposed in the
        # response JSON for caller convenience).
        prog = con.execute(
            "SELECT unified_id, primary_name, source_url "
            "FROM jpi_programs WHERE unified_id = ? LIMIT 1",
            (program_id,),
        ).fetchone()
        if prog is None:
            raise HTTPException(status_code=404, detail="program not found")

        # Look up the canonical am entity. entity_id_map maps jpi_unified_id
        # to am canonical_id; ~46% of programs have a mapping at present
        # (see CLAUDE.md / v_program_full coverage). When unmapped we still
        # return the row's source_url as a single entry so callers always
        # get something concrete back.
        ent = con.execute(
            "SELECT am_canonical_id FROM entity_id_map "
            "WHERE jpi_unified_id = ? LIMIT 1",
            (program_id,),
        ).fetchone()

        sources: list[dict[str, Any]] = []
        entity_id: str | None = None
        if ent is not None:
            entity_id = ent["am_canonical_id"]
            cur = con.execute(
                "SELECT s.source_url, s.source_type, s.domain, s.license, "
                "       s.is_pdf, s.first_seen, s.last_verified, "
                "       es.role, es.source_field "
                "FROM am_entity_source es "
                "JOIN am_source s ON s.id = es.source_id "
                "WHERE es.entity_id = ? "
                "ORDER BY s.source_type ASC, s.last_verified DESC, s.id ASC",
                (entity_id,),
            )
            for r in cur:
                sources.append({
                    "source_url": r["source_url"],
                    "source_type": r["source_type"],
                    "domain": r["domain"],
                    "license": r["license"] or "unknown",
                    "is_pdf": bool(r["is_pdf"]),
                    "first_seen": (r["first_seen"] or "")[:10] or None,
                    "last_verified": (r["last_verified"] or "")[:10] or None,
                    "role": r["role"],
                    "source_field": r["source_field"],
                })

        # Fallback: a program with no entity-mapped sources still has a
        # source_url on the row itself. Surfacing it preserves the
        # invariant that "every program has at least one citable URL"
        # (or honestly says we have none).
        if not sources and prog["source_url"]:
            sources.append({
                "source_url": prog["source_url"],
                "source_type": "primary",
                "domain": None,
                "license": "unknown",
                "is_pdf": False,
                "first_seen": None,
                "last_verified": None,
                "role": "primary_source",
                "source_field": "source_url",
            })

    return {
        "program_id": program_id,
        "entity_id": entity_id,
        "name": prog["primary_name"],
        "sources": sources,
        "generated_at": _utcnow_iso(),
    }
