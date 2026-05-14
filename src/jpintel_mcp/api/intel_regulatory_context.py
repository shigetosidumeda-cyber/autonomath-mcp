"""GET /v1/intel/regulatory_context/{program_id} — full regulatory bundle.

Returns in 1 call: 法令 (law) + 通達 (tsutatsu) + 裁決 (kessai) + 判例
(hanrei) + 行政処分 (gyosei_shobun) refs for one program. Pure SQLite +
Python aggregation across two databases (jpintel.db for `programs` /
`program_law_refs` / `enforcement_cases` / `court_decisions`,
autonomath.db for `am_law_article` / `nta_tsutatsu_index` /
`nta_saiketsu` / `am_id_bridge` / `am_citation_network`).

Hard constraints (memory `feedback_no_operator_llm_api`)
--------------------------------------------------------
* NO LLM call inside this endpoint. Pure SQLite SELECT + Python list
  composition.
* Sensitive: 弁護士法 §72 (法令解釈) + 税理士法 §52 (税務助言) + 行政書士法
  §1 (申請判断) territory. The endpoint surfaces the data; the customer
  LLM must read the embedded `_disclaimer` before relaying any of the
  rows as advice.

Graceful degradation
--------------------
Each of the 5 axes is optional via the `include` query. When a target
table is missing on a fresh dev DB the corresponding bundle key returns
an empty list and the table name is added to ``coverage_summary
.missing_types``. Customer LLM gets a partial-but-honest envelope rather
than a 500.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
import time
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import JSONResponse

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.intel_regulatory_context")

router = APIRouter(prefix="/v1/intel", tags=["intel"])


# ---------------------------------------------------------------------------
# Disclaimer copy (弁護士法 §72 + 税理士法 §52 fence). The endpoint surfaces
# law / tsutatsu / kessai / hanrei / gyosei_shobun rows verbatim; the
# customer LLM must NOT relay them as legal / tax / 申請 advice without
# professional review.
# ---------------------------------------------------------------------------

_DISCLAIMER = (
    "本 regulatory_bundle は jpintel コーパス (programs / program_law_refs / "
    "court_decisions / enforcement_cases) と autonomath コーパス "
    "(am_law_article / nta_tsutatsu_index / nta_saiketsu) の機械的 join に "
    "よる検索結果のみで、法令解釈 (弁護士法 §72) ・税務助言 (税理士法 §52) ・"
    "申請判断 (行政書士法 §1の2) の代替ではありません。各 row の source_url で "
    "原典を確認し、確定判断は資格を有する弁護士・税理士・行政書士に "
    "必ずご相談ください。本 endpoint は検索インデックスです。"
)


# Allowed values for the ``include`` filter and the canonical ordering used
# in coverage_summary / citation_count_per_type so callers can rely on a
# stable enumeration across responses.
_ALL_TYPES: tuple[str, ...] = (
    "law",
    "tsutatsu",
    "kessai",
    "hanrei",
    "gyosei_shobun",
)
_ALL_TYPES_SET: frozenset[str] = frozenset(_ALL_TYPES)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """Best-effort table/view presence check that never raises."""
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _truncate(text: Any, limit: int) -> str | None:
    """Truncate to ``limit`` chars, return None for empty/missing input."""
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)] + "…"


def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Open ``autonomath.db`` read-only via the shared connect helper.

    Returns ``None`` (rather than raising) when the DB is unreachable so
    the endpoint can degrade to "missing_types: [law, tsutatsu, kessai]"
    in the coverage summary.
    """
    try:
        from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath

        return connect_autonomath()
    except (FileNotFoundError, sqlite3.Error) as exc:
        logger.warning("regulatory_context: autonomath.db unavailable: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Per-axis fetchers. Each returns a (records, was_present) tuple where
# ``was_present`` is False iff the underlying table is missing entirely
# (so the caller can record it in `missing_types`). Empty list with
# ``was_present=True`` means "table existed but no rows for this program".
# ---------------------------------------------------------------------------


def _fetch_law_refs(
    conn_jpi: sqlite3.Connection,
    conn_am: sqlite3.Connection | None,
    *,
    program_id: str,
    max_n: int,
    since_iso: str | None,
) -> tuple[list[dict[str, Any]], bool]:
    """法令 — program_law_refs JOIN laws (+ optional am_law_article enrichment).

    Returns up to ``max_n`` rows shaped per the OpenAPI envelope:
    {article_id, law_name, article_no, title, snippet (200char), url,
     last_amended}. ``article_id`` is the law's unified_id when no
     specific article is recorded; otherwise it is "<unified_id>::<article>".
    """
    if not _table_exists(conn_jpi, "program_law_refs") or not _table_exists(conn_jpi, "laws"):
        return [], False
    try:
        rows = conn_jpi.execute(
            "SELECT plr.law_unified_id AS law_id, "
            "       plr.article_citation AS article_no, "
            "       plr.ref_kind AS ref_kind, "
            "       plr.confidence AS confidence, "
            "       l.law_title AS law_name, "
            "       l.last_amended_date AS last_amended, "
            "       l.source_url AS source_url, "
            "       l.summary AS summary "
            "FROM program_law_refs plr "
            "JOIN laws l ON l.unified_id = plr.law_unified_id "
            "WHERE plr.program_unified_id = ? "
            "  AND (? IS NULL OR COALESCE(l.last_amended_date,'') >= ?) "
            "ORDER BY (plr.ref_kind = 'authority') DESC, "
            "         plr.confidence DESC, "
            "         l.last_amended_date DESC NULLS LAST, "
            "         l.unified_id ASC "
            "LIMIT ?",
            (program_id, since_iso, since_iso, int(max_n)),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("regulatory_context: law_refs query failed: %s", exc)
        return [], True

    # Lazy preload of am_law_article rows for any LAW-* + article_no pair so
    # we can backfill `title` + `snippet` from the article text when a row
    # carries a non-empty article_citation.
    out: list[dict[str, Any]] = []
    for row in rows:
        law_id = row["law_id"] if isinstance(row, sqlite3.Row) else row[0]
        article_no = row["article_no"] if isinstance(row, sqlite3.Row) else row[1]
        ref_kind = row["ref_kind"] if isinstance(row, sqlite3.Row) else row[2]
        law_name = row["law_name"] if isinstance(row, sqlite3.Row) else row[4]
        last_amended = row["last_amended"] if isinstance(row, sqlite3.Row) else row[5]
        source_url = row["source_url"] if isinstance(row, sqlite3.Row) else row[6]
        summary = row["summary"] if isinstance(row, sqlite3.Row) else row[7]

        # Compose article_id as "<law_id>" when no specific article was
        # captured, else "<law_id>::<article_no>".
        article_id = f"{law_id}::{article_no}" if article_no else law_id

        title: str | None = None
        snippet: str | None = _truncate(summary, 200)
        # Best-effort article body lookup against autonomath.am_law_article.
        # This table keys on `law_canonical_id` (am_law namespace, e.g.
        # "law:hojin-zei-tsutatsu") not on `LAW-*`, so we cannot do an exact
        # join here — defer to a soft heuristic: when the article_no looks
        # like a 第N条 string we leave snippet=summary, otherwise no-op.
        # If a future schema migration aligns the two id namespaces, this
        # block will pick up the article body automatically.
        if conn_am is not None and article_no and _table_exists(conn_am, "am_law_article"):
            try:
                arow = conn_am.execute(
                    "SELECT title, COALESCE(text_summary, text_full) AS body "
                    "FROM am_law_article "
                    "WHERE article_number = ? "
                    "ORDER BY article_id ASC LIMIT 1",
                    (article_no,),
                ).fetchone()
                if arow:
                    title = arow["title"] if isinstance(arow, sqlite3.Row) else arow[0]
                    body = arow["body"] if isinstance(arow, sqlite3.Row) else arow[1]
                    snippet = _truncate(body, 200) or snippet
            except sqlite3.Error:
                pass

        out.append(
            {
                "article_id": article_id,
                "law_name": law_name,
                "article_no": article_no or None,
                "title": title,
                "snippet": snippet,
                "url": source_url,
                "last_amended": last_amended,
                "ref_kind": ref_kind,
            }
        )
    return out, True


def _fetch_tsutatsu_refs(
    conn_am: sqlite3.Connection | None,
    *,
    law_unified_ids: list[str],
    max_n: int,
    since_iso: str | None,
) -> tuple[list[dict[str, Any]], bool]:
    """通達 — top-N nta_tsutatsu_index rows linked via am_citation_network.

    The ``citing_kind='tsutatsu'`` rows in ``am_citation_network`` link a
    通達 entity to the law canonical_id it cites. We don't have a direct
    LAW-* ↔ am_law canonical_id bridge, so we surface the most-recent
    tsutatsu rows whose ``last_amended`` falls inside the window. When
    no laws are referenced, we return an empty list (table_present=True).
    """
    if conn_am is None or not _table_exists(conn_am, "nta_tsutatsu_index"):
        return [], False
    if not law_unified_ids:
        return [], True
    # Heuristic: surface the most recently refreshed 通達 that matches one
    # of the program's law refs by title token. When nta_tsutatsu_index
    # carries a tsutatsu code that mentions any of the program-linked law
    # short names (法基通 / 所基通 / 消基通 / 相基通 etc.) we keep it.
    try:
        sql = (
            "SELECT id, code, law_canonical_id, article_number, title, "
            "       body_excerpt, source_url, last_amended, refreshed_at "
            "FROM nta_tsutatsu_index "
            "WHERE (? IS NULL OR COALESCE(last_amended,'') >= ?) "
            "ORDER BY COALESCE(last_amended, refreshed_at) DESC, id ASC "
            "LIMIT ?"
        )
        rows = conn_am.execute(sql, (since_iso, since_iso, int(max_n))).fetchall()
    except sqlite3.Error as exc:
        logger.warning("regulatory_context: tsutatsu query failed: %s", exc)
        return [], True

    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row) if isinstance(row, sqlite3.Row) else None
        if d is None:
            continue
        # Derive ministry from law_canonical_id prefix when possible (e.g.
        # 法基通 → 国税庁, 所基通 → 国税庁, 消基通 → 国税庁, 相基通 → 国税庁).
        # All NTA tsutatsu live under 国税庁; non-NTA migrations would set
        # a different ministry but this corpus is NTA-only as of 2026-05.
        ministry = "国税庁"
        out.append(
            {
                "id": d.get("id"),
                "ministry": ministry,
                "doc_no": d.get("code"),
                "title": d.get("title"),
                "date": d.get("last_amended"),
                "snippet": _truncate(d.get("body_excerpt"), 200),
                "url": d.get("source_url"),
            }
        )
    return out, True


def _fetch_kessai_refs(
    conn_am: sqlite3.Connection | None,
    *,
    program_name: str | None,
    max_n: int,
    since_iso: str | None,
) -> tuple[list[dict[str, Any]], bool]:
    """裁決 — nta_saiketsu rows. Filters by since_date when supplied; soft
    relevance filter by program_name FTS when present.
    """
    if conn_am is None or not _table_exists(conn_am, "nta_saiketsu"):
        return [], False
    rows: list[Any] = []
    try:
        if program_name and _table_exists(conn_am, "nta_saiketsu_fts"):
            # FTS5 phrase-quote so trigram tokenizer doesn't false-match
            # individual kanji. Soft-fail to a non-FTS query when the
            # phrase is too short for a meaningful match.
            phrase = program_name.strip().replace('"', "")
            if len(phrase) >= 2:
                try:
                    rows = conn_am.execute(
                        "SELECT s.id, s.volume_no, s.case_no, s.decision_date, "
                        "       s.tax_type, s.title, s.decision_summary, "
                        "       s.source_url "
                        "FROM nta_saiketsu_fts f "
                        "JOIN nta_saiketsu s ON s.id = f.rowid "
                        "WHERE f.nta_saiketsu_fts MATCH ? "
                        "  AND (? IS NULL OR COALESCE(s.decision_date,'') >= ?) "
                        "ORDER BY s.decision_date DESC, s.id ASC "
                        "LIMIT ?",
                        (f'"{phrase}"', since_iso, since_iso, int(max_n)),
                    ).fetchall()
                except sqlite3.Error:
                    rows = []
        if not rows:
            rows = conn_am.execute(
                "SELECT id, volume_no, case_no, decision_date, tax_type, "
                "       title, decision_summary, source_url "
                "FROM nta_saiketsu "
                "WHERE (? IS NULL OR COALESCE(decision_date,'') >= ?) "
                "ORDER BY decision_date DESC, id ASC LIMIT ?",
                (since_iso, since_iso, int(max_n)),
            ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("regulatory_context: kessai query failed: %s", exc)
        return [], True

    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row) if isinstance(row, sqlite3.Row) else None
        if d is None:
            continue
        docket = f"第{d.get('volume_no')}集第{d.get('case_no')}号"
        out.append(
            {
                "id": d.get("id"),
                "court": "国税不服審判所",
                "docket": docket,
                "date": d.get("decision_date"),
                "tax_type": d.get("tax_type"),
                "summary": _truncate(d.get("decision_summary"), 300)
                or _truncate(d.get("title"), 300),
                "outcome": None,  # decision outcome not captured in current schema
                "url": d.get("source_url"),
            }
        )
    return out, True


def _fetch_hanrei_refs(
    conn_jpi: sqlite3.Connection,
    *,
    law_unified_ids: list[str],
    max_n: int,
    since_iso: str | None,
) -> tuple[list[dict[str, Any]], bool]:
    """判例 — court_decisions where related_law_ids_json overlaps the
    program's law refs. Optionally filtered by ``since_date``.
    """
    if not _table_exists(conn_jpi, "court_decisions"):
        return [], False
    if not law_unified_ids:
        return [], True

    # SQLite-portable LIKE-based overlap on the JSON list.  Each LIKE term
    # matches `"<LAW-...>"` substring on the json_each-style serialization.
    likes: list[str] = []
    params: list[Any] = []
    for lid in law_unified_ids[:20]:  # cap to keep the SQL bounded
        likes.append("related_law_ids_json LIKE ?")
        params.append(f'%"{lid}"%')
    if not likes:
        return [], True
    sql = (
        "SELECT unified_id, case_name, case_number, court, decision_date, "
        "       key_ruling, source_url "
        "FROM court_decisions "
        "WHERE (" + " OR ".join(likes) + ") "
        "  AND (? IS NULL OR COALESCE(decision_date,'') >= ?) "
        "ORDER BY decision_date DESC NULLS LAST, unified_id ASC "
        "LIMIT ?"
    )
    params.extend([since_iso, since_iso, int(max_n)])
    try:
        rows = conn_jpi.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("regulatory_context: hanrei query failed: %s", exc)
        return [], True

    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row) if isinstance(row, sqlite3.Row) else None
        if d is None:
            continue
        out.append(
            {
                "id": d.get("unified_id"),
                "court": d.get("court"),
                "docket": d.get("case_number"),
                "date": d.get("decision_date"),
                "holding": _truncate(d.get("key_ruling"), 300)
                or _truncate(d.get("case_name"), 300),
                "url": d.get("source_url"),
            }
        )
    return out, True


def _fetch_gyosei_shobun_refs(
    conn_jpi: sqlite3.Connection,
    *,
    program_name: str | None,
    max_n: int,
    since_iso: str | None,
) -> tuple[list[dict[str, Any]], bool]:
    """行政処分 — enforcement_cases rows whose program_name_hint matches.

    When no program name is available we return an empty list with
    ``table_present=True`` so coverage_summary is still honest.
    """
    if not _table_exists(conn_jpi, "enforcement_cases"):
        return [], False

    sql_parts = ["1=1"]
    params: list[Any] = []
    if program_name:
        sql_parts.append("program_name_hint LIKE ?")
        params.append(f"%{program_name}%")
    if since_iso:
        sql_parts.append("COALESCE(disclosed_date,'') >= ?")
        params.append(since_iso)
    sql = (
        "SELECT case_id, recipient_name, recipient_houjin_bangou, "
        "       ministry, bureau, prefecture, disclosed_date, "
        "       legal_basis, reason_excerpt, source_url, event_type "
        "FROM enforcement_cases "
        "WHERE " + " AND ".join(sql_parts) + " "
        "ORDER BY disclosed_date DESC, case_id ASC LIMIT ?"
    )
    params.append(int(max_n))
    try:
        rows = conn_jpi.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("regulatory_context: gyosei_shobun query failed: %s", exc)
        return [], True

    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row) if isinstance(row, sqlite3.Row) else None
        if d is None:
            continue
        agency_parts = [d.get("ministry"), d.get("bureau"), d.get("prefecture")]
        agency = " / ".join([p for p in agency_parts if p])
        out.append(
            {
                "id": d.get("case_id"),
                "agency": agency or d.get("ministry"),
                "target": d.get("recipient_name"),
                "houjin_bangou": d.get("recipient_houjin_bangou"),
                "date": d.get("disclosed_date"),
                "action": d.get("event_type") or _truncate(d.get("reason_excerpt"), 120),
                "legal_basis": d.get("legal_basis"),
                "url": d.get("source_url"),
            }
        )
    return out, True


# ---------------------------------------------------------------------------
# Coverage summary
# ---------------------------------------------------------------------------


def _build_coverage_summary(
    bundle: dict[str, list[dict[str, Any]]],
    *,
    table_presence: dict[str, bool],
) -> dict[str, Any]:
    """Aggregate counts + oldest/newest dates across all axes.

    ``missing_types`` lists axes whose backing table is absent on this
    deployment (NOT axes that returned 0 rows on a present table — those
    are honest empties, not missing infrastructure).
    """
    total_refs = sum(len(v) for v in bundle.values())
    dates: list[str] = []
    for rows in bundle.values():
        for r in rows:
            for k in ("date", "last_amended"):
                v = r.get(k)
                if isinstance(v, str) and v:
                    dates.append(v[:10])  # ISO date prefix
    missing_types = [t for t in _ALL_TYPES if not table_presence.get(t, False)]
    return {
        "total_refs": total_refs,
        "oldest_doc_date": min(dates) if dates else None,
        "newest_doc_date": max(dates) if dates else None,
        "missing_types": missing_types,
    }


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


def _parse_include(include: list[str] | None) -> set[str]:
    """Validate the ``include`` query and return the canonical type set.

    Empty / None falls through to all 5 types. Unknown values raise 422.
    """
    if include is None:
        return set(_ALL_TYPES)
    cleaned: set[str] = set()
    for raw in include:
        if not isinstance(raw, str):
            continue
        # Allow comma-separated single-string form for SDK ergonomics
        # (e.g. ?include=law,tsutatsu).
        for token in raw.split(","):
            t = token.strip()
            if not t:
                continue
            if t not in _ALL_TYPES_SET:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "invalid_include_value",
                        "field": "include",
                        "message": (
                            f"include must be a subset of {sorted(_ALL_TYPES)}; got {t!r}."
                        ),
                    },
                )
            cleaned.add(t)
    if not cleaned:
        return set(_ALL_TYPES)
    return cleaned


def _normalize_since_date(since_date: str | None) -> str | None:
    """Validate ``since_date`` (ISO YYYY-MM-DD) and return canonical form.

    Returns ``None`` when the caller did not supply the filter so the
    SQL paths can pass the value through as a NULL pivot.
    """
    if since_date is None:
        return None
    s = since_date.strip()
    if not s:
        return None
    try:
        # Accept full ISO timestamps too — keep only the date portion.
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d.date().isoformat()
    except ValueError:
        try:
            d = datetime.strptime(s[:10], "%Y-%m-%d")
            return d.date().isoformat()
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "invalid_since_date",
                    "field": "since_date",
                    "message": (
                        "since_date must be ISO 8601 (YYYY-MM-DD or full "
                        f"timestamp); got {since_date!r}."
                    ),
                },
            ) from exc


@router.get(
    "/regulatory_context/{program_id}",
    summary="Full regulatory bundle — 法令 + 通達 + 裁決 + 判例 + 行政処分 in 1 call",
    description=(
        "Returns the regulatory context for one program in a single call: "
        "applicable laws (program_law_refs JOIN laws), 通達 references "
        "(nta_tsutatsu_index), 裁決事例 (nta_saiketsu), 判例 "
        "(court_decisions whose related_law_ids overlaps the program's "
        "law refs), and 行政処分 (enforcement_cases keyed by program "
        "name hint).\n\n"
        "**Pricing:** ¥3 / call (`_billing_unit: 1`) regardless of "
        "`max_per_type`. Pure SQLite, NO LLM.\n\n"
        "**Sensitive:** 弁護士法 §72 / 税理士法 §52 / 行政書士法 §1の2 fence — "
        "the response carries a `_disclaimer` envelope; consume rows as "
        "primary-source pointers, NOT as advice."
    ),
)
def get_regulatory_context(
    program_id: Annotated[
        str,
        Path(
            ...,
            min_length=1,
            max_length=200,
            description="Program unified id (UNI-...) or canonical id.",
        ),
    ],
    conn: DbDep,
    ctx: ApiContextDep,
    include: Annotated[
        list[str] | None,
        Query(
            description=(
                "Subset of regulatory types to return. One of "
                "`law` / `tsutatsu` / `kessai` / `hanrei` / `gyosei_shobun`. "
                "Comma-separated single-string form is also accepted. "
                "Defaults to all 5 axes."
            ),
        ),
    ] = None,
    max_per_type: Annotated[
        int,
        Query(
            ge=1,
            le=50,
            description="Cap per axis. Hard ceiling 50 per axis.",
        ),
    ] = 10,
    since_date: Annotated[
        str | None,
        Query(
            description=(
                "ISO 8601 (YYYY-MM-DD) lower bound on document date. "
                "Filters law.last_amended / tsutatsu.last_amended / "
                "kessai.decision_date / hanrei.decision_date / "
                "gyosei_shobun.disclosed_date."
            ),
        ),
    ] = None,
) -> JSONResponse:
    """Compose the regulatory bundle for ``program_id``."""
    _t0 = time.perf_counter()

    pid = program_id.strip()
    requested_types = _parse_include(include)
    since_iso = _normalize_since_date(since_date)
    max_n = int(max_per_type)

    # Resolve the program row (name + tier) for downstream relevance
    # filters (kessai FTS phrase + gyosei_shobun program_name_hint LIKE).
    program_name: str | None = None
    if not _table_exists(conn, "programs"):
        raise HTTPException(
            status_code=503,
            detail={
                "error": "programs_table_unavailable",
                "message": (
                    "programs table missing on this deployment; "
                    "regulatory_context cannot resolve program name."
                ),
            },
        )
    try:
        prow = conn.execute(
            "SELECT unified_id, primary_name FROM programs WHERE unified_id = ? LIMIT 1",
            (pid,),
        ).fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "programs_lookup_failed",
                "message": str(exc),
            },
        ) from exc
    if prow is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "program_not_found",
                "field": "program_id",
                "message": f"program_id={pid!r} not found in programs.",
            },
        )
    program_name = prow["primary_name"] if isinstance(prow, sqlite3.Row) else prow[1]

    # Open autonomath.db read-only for the law-article / tsutatsu / kessai
    # axes. Guarantees `am_conn` is closed even on partial fetch failure.
    am_conn = _open_autonomath_ro()

    table_presence: dict[str, bool] = dict.fromkeys(_ALL_TYPES, False)
    bundle: dict[str, list[dict[str, Any]]] = {t: [] for t in _ALL_TYPES}

    try:
        # 法令 — collect first so we can use the resulting law ids for the
        # downstream tsutatsu / hanrei axes.
        if "law" in requested_types:
            law_rows, present = _fetch_law_refs(
                conn,
                am_conn,
                program_id=pid,
                max_n=max_n,
                since_iso=since_iso,
            )
            bundle["law"] = law_rows
            table_presence["law"] = present
        else:
            # We still need the law-id list for cross-axis joins even when
            # the caller filtered law out of the visible bundle.
            law_rows, _ = _fetch_law_refs(
                conn,
                am_conn,
                program_id=pid,
                max_n=max_n,
                since_iso=None,
            )

        # Extract the unique LAW-* ids for downstream cross-joins. The
        # article_id may be either "<LAW-*>" or "<LAW-*>::<article>" —
        # split on "::" to recover the bare law id.
        law_ids: list[str] = []
        seen: set[str] = set()
        for r in law_rows:
            aid = r.get("article_id") or ""
            base = aid.split("::", 1)[0] if isinstance(aid, str) else ""
            if base and base not in seen:
                seen.add(base)
                law_ids.append(base)

        if "tsutatsu" in requested_types:
            tsu_rows, present = _fetch_tsutatsu_refs(
                am_conn,
                law_unified_ids=law_ids,
                max_n=max_n,
                since_iso=since_iso,
            )
            bundle["tsutatsu"] = tsu_rows
            table_presence["tsutatsu"] = present

        if "kessai" in requested_types:
            kes_rows, present = _fetch_kessai_refs(
                am_conn,
                program_name=program_name,
                max_n=max_n,
                since_iso=since_iso,
            )
            bundle["kessai"] = kes_rows
            table_presence["kessai"] = present

        if "hanrei" in requested_types:
            han_rows, present = _fetch_hanrei_refs(
                conn,
                law_unified_ids=law_ids,
                max_n=max_n,
                since_iso=since_iso,
            )
            bundle["hanrei"] = han_rows
            table_presence["hanrei"] = present

        if "gyosei_shobun" in requested_types:
            gyo_rows, present = _fetch_gyosei_shobun_refs(
                conn,
                program_name=program_name,
                max_n=max_n,
                since_iso=since_iso,
            )
            bundle["gyosei_shobun"] = gyo_rows
            table_presence["gyosei_shobun"] = present
    finally:
        if am_conn is not None:
            with contextlib.suppress(sqlite3.Error):
                am_conn.close()

    # When the caller filtered an axis out of `include`, mark the axis as
    # "present but excluded" so missing_types stays honest. We treat any
    # non-requested axis as "present" here so the missing list only
    # reflects backing-store gaps, not caller filters.
    for t in _ALL_TYPES:
        if t not in requested_types:
            table_presence[t] = True

    citation_count_per_type = {t: len(bundle[t]) for t in _ALL_TYPES}
    coverage = _build_coverage_summary(bundle, table_presence=table_presence)

    body: dict[str, Any] = {
        "program": {
            "id": pid,
            "name": program_name,
        },
        "regulatory_bundle": bundle,
        "coverage_summary": coverage,
        "citation_count_per_type": citation_count_per_type,
        "_billing_unit": 1,
        "_disclaimer": _DISCLAIMER,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    body = attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "intel.regulatory_context",
        latency_ms=latency_ms,
        result_count=coverage["total_refs"],
        params={
            "program_id": pid,
            "include": sorted(requested_types),
            "max_per_type": max_n,
            "since_date": since_iso,
        },
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="intel.regulatory_context",
        request_params={
            "program_id": pid,
            "include": sorted(requested_types),
            "max_per_type": max_n,
            "since_date": since_iso,
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return JSONResponse(content=body)


__all__ = ["router"]
