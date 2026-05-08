"""GET /v1/tax_rules/{rule_id}/full_chain — 税制×法令×通達×裁決×判例 chain.

Single-call composite that returns, for one ``tax_rulesets`` row, every
primary-source citation surface that interprets the same tax measure:

    1. **税制 (rule)**         — ``tax_rulesets`` (jpintel.db, 50 rows live)
    2. **根拠条文 (laws)**     — ``laws`` joined via the ruleset's
                                  ``related_law_ids_json`` (jpintel.db,
                                  9,484 metadata records; article references
                                  where available, body/article coverage
                                  varies by record)
    3. **通達 (tsutatsu)**     — ``nta_tsutatsu_index`` (autonomath.db,
                                  ~3,221 rows)
    4. **裁決事例 (saiketsu)** — ``nta_saiketsu`` (autonomath.db, ~140 rows
                                  公表 from 国税不服審判所)
    5. **判例 (hanrei)**       — ``court_decisions`` (jpintel.db,
                                  2,065 rows) whose ``related_law_ids_json``
                                  overlaps the ruleset's law refs
    6. **改正履歴 (history)**  — older rulesets that share the same
                                  ``ruleset_name`` (current row's predecessors
                                  by effective_from descending)

The shape mirrors ``intel_regulatory_context`` for a program but is keyed
to a 税制 (TAX-* unified_id) instead of a program. The result lets a
customer LLM render "this tax measure / its statutes / how the tax
authority interprets them via 通達 / how 国税不服審判所 ruled in 裁決 /
how courts ruled in 判例 / what older versions of the rule looked like"
in one ¥3 call — what the user calls 「この税制を巡る解釈一式」.

Hard constraints
----------------
* NO LLM call. Pure SQLite SELECT + Python dict shaping.
* Cross-DB reads: jpintel.db (DbDep) AND autonomath.db (RO connect helper).
  CLAUDE.md forbids ATTACH / cross-DB JOIN, so the two halves are pulled
  separately and merged in Python.
* Sensitive surface — 税理士法 §52 (税務助言) + 弁護士法 §72 (法令解釈) +
  公認会計士法 §47条の2 (監査・意見表明) fence injected via ``_disclaimer``.
  The output is a citation index. The customer LLM MUST relay the
  disclaimer verbatim.
* `_billing_unit: 1` flat regardless of how many citation rows surface.

Graceful degradation
--------------------
Each axis returns ``[]`` with the table name appended to
``coverage_summary.missing_types`` when the underlying table is missing
(fresh dev DB / autonomath.db absent). The endpoint never 500s on a
missing axis.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query, status
from fastapi.responses import JSONResponse

from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot, snapshot_headers
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.tax_chain")

router = APIRouter(prefix="/v1/tax_rules", tags=["tax_rules"])


# ---------------------------------------------------------------------------
# Constants & disclaimer
# ---------------------------------------------------------------------------

_UNIFIED_ID_RE = re.compile(r"^TAX-[0-9a-f]{10}$")

# 税理士法 §52 + 弁護士法 §72 + 公認会計士法 §47条の2 fence. The chain
# surfaces 規定 / 法令 / 通達 / 裁決 / 判例 verbatim — a downstream LLM
# must relay this disclaimer when presenting the bundle.
_TAX_CHAIN_DISCLAIMER = (
    "本 full_chain は jpcite corpus (tax_rulesets / laws / court_decisions) と "
    "autonomath corpus (nta_tsutatsu_index / nta_saiketsu) を一次資料 URL と共に "
    "1 call で束ねた検索結果で、税理士法 §52 (税務代理) ・弁護士法 §72 (法令解釈) ・"
    "公認会計士法 §47条の2 (監査・意見表明) のいずれの士業役務にも該当しません。"
    "掲載の通達・裁決・判例は公表時点の解釈であり、改正により現在の取扱が変更されている"
    "可能性があります。各 row の source_url で原典を確認のうえ、確定判断は資格を有する"
    "税理士・弁護士に必ずご相談ください。"
)


# Canonical axis ordering used by ``coverage_summary.missing_types`` and the
# response body's section iteration. Stable across responses.
_ALL_AXES: tuple[str, ...] = (
    "laws",
    "tsutatsu",
    "saiketsu",
    "hanrei",
    "history",
)
_ALL_AXES_SET: frozenset[str] = frozenset(_ALL_AXES)


# Hard caps per axis. Defends the autonomath.db read budget on a 9.4 GB DB
# that already takes 256 MB cache + 2 GB mmap per connection.
_DEFAULT_MAX_PER_AXIS = 10
_HARD_MAX_PER_AXIS = 50


# Snippet length cap so the bundle stays inside the customer LLM's context
# window even when 50 rows stack up across 5 axes.
_SNIPPET_CHAR_CAP = 220


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """Best-effort table presence check — never raises."""
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _truncate(text: Any, limit: int = _SNIPPET_CHAR_CAP) -> str | None:
    """Trim a freeform string to ``limit`` chars, returning None for empty."""
    if text is None:
        return None
    s = re.sub(r"\s+", " ", str(text)).strip()
    if not s:
        return None
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)] + "…"


def _parse_law_ids(raw: Any) -> list[str]:
    """Decode ``related_law_ids_json`` into a typed list[str]; tolerant."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    out: list[str] = []
    for x in parsed:
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
    return out


def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Open ``autonomath.db`` read-only; ``None`` when missing.

    Returning None (rather than raising) lets the endpoint degrade to
    "missing_types: [tsutatsu, saiketsu]" in coverage_summary instead of
    500ing when the dev / CI DB is absent.
    """
    try:
        from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath

        return connect_autonomath()
    except (FileNotFoundError, sqlite3.Error) as exc:
        logger.warning("tax_chain: autonomath.db unavailable: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001 — never let DB open break the call
        logger.warning("tax_chain: autonomath.db open failed: %s", exc)
        return None


def _parse_include(include: list[str] | None) -> set[str]:
    """Validate ``include`` query and return canonical axis set."""
    if include is None:
        return set(_ALL_AXES)
    cleaned: set[str] = set()
    for raw in include:
        if not isinstance(raw, str):
            continue
        # SDK ergonomics: also accept comma-separated single-string form.
        for token in raw.split(","):
            t = token.strip()
            if not t:
                continue
            if t not in _ALL_AXES_SET:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "error": "invalid_include_value",
                        "field": "include",
                        "message": (f"include must be a subset of {sorted(_ALL_AXES)}; got {t!r}."),
                    },
                )
            cleaned.add(t)
    if not cleaned:
        return set(_ALL_AXES)
    return cleaned


# ---------------------------------------------------------------------------
# Per-axis fetchers (jpintel.db side)
# ---------------------------------------------------------------------------


def _fetch_rule_row(
    conn: sqlite3.Connection,
    rule_id: str,
) -> sqlite3.Row | None:
    """Pull the canonical tax_ruleset row. Returns None when absent."""
    if not _table_exists(conn, "tax_rulesets"):
        return None
    try:
        row = conn.execute(
            "SELECT * FROM tax_rulesets WHERE unified_id = ?",
            (rule_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("tax_chain: rule lookup failed: %s", exc)
        return None
    if row is None:
        return None
    # sqlite3.Cursor.fetchone() is typed Any; narrow explicitly so mypy is
    # happy and runtime callers see a sqlite3.Row.
    assert isinstance(row, sqlite3.Row)
    return row


def _shape_rule_row(row: sqlite3.Row) -> dict[str, Any]:
    """Render a tax_ruleset row as the chain's `rule` block."""
    return {
        "unified_id": row["unified_id"],
        "ruleset_name": row["ruleset_name"],
        "tax_category": row["tax_category"],
        "ruleset_kind": row["ruleset_kind"],
        "effective_from": row["effective_from"],
        "effective_until": row["effective_until"],
        "rate_or_amount": row["rate_or_amount"],
        "calculation_formula": row["calculation_formula"],
        "filing_requirements": row["filing_requirements"],
        "eligibility_conditions": row["eligibility_conditions"],
        "authority": row["authority"],
        "authority_url": row["authority_url"],
        "source_url": row["source_url"],
        "fetched_at": row["fetched_at"],
        "updated_at": row["updated_at"],
    }


def _fetch_laws(
    conn: sqlite3.Connection,
    *,
    law_ids: list[str],
    max_n: int,
) -> tuple[list[dict[str, Any]], bool]:
    """根拠条文 — laws keyed by the ruleset's related_law_ids_json.

    Returns ``(rows, was_present)`` where ``was_present=False`` means the
    ``laws`` table is missing on this DB. Honest empty list otherwise.
    """
    if not _table_exists(conn, "laws"):
        return [], False
    if not law_ids:
        return [], True

    # Bound the IN list defensively. JSON predicates may have been seeded
    # with article-level free text in lieu of LAW-* unified_ids; we filter
    # to canonical-shape ids here and surface the rest as best-effort
    # citation strings on the response (no DB resolution).
    canonical_ids = [lid for lid in law_ids if isinstance(lid, str) and lid.startswith("LAW-")]
    if not canonical_ids:
        # Fall back to a name-LIKE search — the seed data sometimes
        # carries readable strings like '消費税法第37条' in lieu of LAW-*.
        likes: list[str] = []
        params: list[Any] = []
        for lid in law_ids[:8]:
            if not isinstance(lid, str):
                continue
            likes.append("(law_title LIKE ? OR law_short_title LIKE ?)")
            params.extend([f"%{lid}%", f"%{lid}%"])
        if not likes:
            return [], True
        sql = (
            "SELECT unified_id, law_number, law_title, law_short_title, "
            "       law_type, ministry, last_amended_date, full_text_url, "
            "       summary, source_url, fetched_at "
            "FROM laws "
            f"WHERE {' OR '.join(likes)} "
            "ORDER BY (revision_status = 'current') DESC, "
            "         last_amended_date DESC, unified_id ASC "
            "LIMIT ?"
        )
        params.append(int(max_n))
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            logger.warning("tax_chain: laws name-LIKE failed: %s", exc)
            return [], True
    else:
        placeholders = ",".join("?" * len(canonical_ids[:20]))
        sql = (
            "SELECT unified_id, law_number, law_title, law_short_title, "
            "       law_type, ministry, last_amended_date, full_text_url, "
            "       summary, source_url, fetched_at "
            "FROM laws "
            f"WHERE unified_id IN ({placeholders}) "
            "ORDER BY (revision_status = 'current') DESC, "
            "         last_amended_date DESC, unified_id ASC "
            "LIMIT ?"
        )
        try:
            rows = conn.execute(sql, [*canonical_ids[:20], int(max_n)]).fetchall()
        except sqlite3.Error as exc:
            logger.warning("tax_chain: laws IN-list query failed: %s", exc)
            return [], True

    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "unified_id": row["unified_id"],
                "law_number": row["law_number"],
                "law_title": row["law_title"],
                "law_short_title": row["law_short_title"],
                "law_type": row["law_type"],
                "ministry": row["ministry"],
                "last_amended_date": row["last_amended_date"],
                "url": row["full_text_url"] or row["source_url"],
                "snippet": _truncate(row["summary"]),
                "fetched_at": row["fetched_at"],
            }
        )
    return out, True


def _fetch_hanrei(
    conn: sqlite3.Connection,
    *,
    law_ids: list[str],
    rule_name: str,
    max_n: int,
) -> tuple[list[dict[str, Any]], bool]:
    """判例 — court_decisions where related_law_ids_json overlaps + name token match.

    OR-joined predicates so a 判例 that cites the ruleset's LAW-* by id OR
    that mentions the ruleset's name keywords surfaces. Never raises.
    """
    if not _table_exists(conn, "court_decisions"):
        return [], False

    parts: list[str] = []
    params: list[Any] = []
    if law_ids:
        likes = ["related_law_ids_json LIKE ?" for _ in law_ids[:8]]
        parts.append("(" + " OR ".join(likes) + ")")
        params.extend([f'%"{lid}"%' for lid in law_ids[:8]])
    tokens = [t for t in re.findall(r"[一-龯]{2,}", rule_name or "") if len(t) >= 2]
    if tokens:
        likes_kw = ["(case_name LIKE ? OR key_ruling LIKE ?)" for _ in tokens[:4]]
        parts.append("(" + " OR ".join(likes_kw) + ")")
        for t in tokens[:4]:
            params.extend([f"%{t}%", f"%{t}%"])
    if not parts:
        return [], True

    sql = (
        "SELECT unified_id, case_name, case_number, court, court_level, "
        "       decision_date, decision_type, key_ruling, precedent_weight, "
        "       full_text_url, source_url, fetched_at "
        "FROM court_decisions "
        f"WHERE {' OR '.join(parts)} "
        "ORDER BY (precedent_weight = 'binding') DESC, "
        "         (precedent_weight = 'persuasive') DESC, "
        "         decision_date DESC NULLS LAST, unified_id ASC "
        "LIMIT ?"
    )
    params.append(int(max_n))
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("tax_chain: hanrei query failed: %s", exc)
        return [], True

    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "unified_id": row["unified_id"],
                "case_name": row["case_name"],
                "case_number": row["case_number"],
                "court": row["court"],
                "court_level": row["court_level"],
                "decision_date": row["decision_date"],
                "decision_type": row["decision_type"],
                "precedent_weight": row["precedent_weight"],
                "key_ruling_snippet": _truncate(row["key_ruling"]),
                "url": row["full_text_url"] or row["source_url"],
                "fetched_at": row["fetched_at"],
            }
        )
    return out, True


def _fetch_history(
    conn: sqlite3.Connection,
    *,
    rule_row: sqlite3.Row,
    max_n: int,
) -> tuple[list[dict[str, Any]], bool]:
    """改正履歴 — sibling tax_rulesets that share the same ruleset_name.

    The ``tax_rulesets`` table does not carry an explicit "predecessor_id"
    column; instead, sibling rows for the same measure differ only in
    ``effective_from`` / ``effective_until``. We surface every sibling
    EXCEPT the requested one, oldest-first, so a customer LLM can render
    "this measure was first introduced on YYYY-MM-DD and amended on …".
    """
    if not _table_exists(conn, "tax_rulesets"):
        return [], False
    try:
        rows = conn.execute(
            "SELECT unified_id, ruleset_name, effective_from, effective_until, "
            "       rate_or_amount, source_url, updated_at "
            "FROM tax_rulesets "
            "WHERE ruleset_name = ? AND unified_id != ? "
            "ORDER BY effective_from ASC, unified_id ASC "
            "LIMIT ?",
            (rule_row["ruleset_name"], rule_row["unified_id"], int(max_n)),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("tax_chain: history query failed: %s", exc)
        return [], True

    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "unified_id": row["unified_id"],
                "ruleset_name": row["ruleset_name"],
                "effective_from": row["effective_from"],
                "effective_until": row["effective_until"],
                "rate_or_amount": row["rate_or_amount"],
                "url": row["source_url"],
                "updated_at": row["updated_at"],
            }
        )
    return out, True


# ---------------------------------------------------------------------------
# Per-axis fetchers (autonomath.db side)
# ---------------------------------------------------------------------------


def _fetch_tsutatsu(
    am_conn: sqlite3.Connection | None,
    *,
    rule_name: str,
    max_n: int,
) -> tuple[list[dict[str, Any]], bool]:
    """通達 — nta_tsutatsu_index keyed by name token LIKE on title.

    Title tokens come from the ruleset_name kanji compounds. The tsutatsu
    corpus uses ``law:hojin-zei-tsutatsu`` style canonical ids, not LAW-*,
    so name-matching is the only honest bridge without a hand-curated
    crosswalk.
    """
    if am_conn is None:
        return [], False
    if not _table_exists(am_conn, "nta_tsutatsu_index"):
        return [], False
    tokens = [t for t in re.findall(r"[一-龯]{2,}", rule_name or "") if len(t) >= 2]
    if not tokens:
        return [], True
    likes = ["title LIKE ?" for _ in tokens[:6]]
    sql = (
        "SELECT id, code, law_canonical_id, article_number, title, "
        "       body_excerpt, source_url, last_amended, refreshed_at "
        "FROM nta_tsutatsu_index "
        f"WHERE {' OR '.join(likes)} "
        "ORDER BY refreshed_at DESC, id ASC "
        "LIMIT ?"
    )
    params: list[Any] = [f"%{t}%" for t in tokens[:6]]
    params.append(int(max_n))
    try:
        rows = am_conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("tax_chain: tsutatsu query failed: %s", exc)
        return [], True

    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "id": row["id"],
                "code": row["code"],
                "law_canonical_id": row["law_canonical_id"],
                "article_number": row["article_number"],
                "title": row["title"],
                "body_excerpt": _truncate(row["body_excerpt"]),
                "url": row["source_url"],
                "last_amended": row["last_amended"],
                "refreshed_at": row["refreshed_at"],
            }
        )
    return out, True


def _fetch_saiketsu(
    am_conn: sqlite3.Connection | None,
    *,
    rule_name: str,
    tax_category: str | None,
    max_n: int,
) -> tuple[list[dict[str, Any]], bool]:
    """裁決事例 — nta_saiketsu (公表) keyed by name token + tax_type filter.

    ``tax_category`` is mapped to nta_saiketsu's ``tax_type`` heuristically
    (consumption -> 消費税, corporate -> 法人税, income -> 所得税,
    inheritance -> 相続税). Other categories fall through with no tax_type
    filter so the search is purely token-based.
    """
    if am_conn is None:
        return [], False
    if not _table_exists(am_conn, "nta_saiketsu"):
        return [], False
    tokens = [t for t in re.findall(r"[一-龯]{2,}", rule_name or "") if len(t) >= 2]
    if not tokens:
        return [], True

    tax_type_filter: str | None = None
    if tax_category in ("consumption",):
        tax_type_filter = "消費税"
    elif tax_category in ("corporate",):
        tax_type_filter = "法人税"
    elif tax_category in ("income",):
        tax_type_filter = "所得税"
    elif tax_category in ("inheritance",):
        tax_type_filter = "相続税"

    likes = ["(title LIKE ? OR decision_summary LIKE ?)" for _ in tokens[:4]]
    where_parts = ["(" + " OR ".join(likes) + ")"]
    params: list[Any] = []
    for t in tokens[:4]:
        params.extend([f"%{t}%", f"%{t}%"])
    if tax_type_filter is not None:
        where_parts.append("tax_type = ?")
        params.append(tax_type_filter)

    sql = (
        "SELECT id, volume_no, case_no, decision_date, fiscal_period, "
        "       tax_type, title, decision_summary, source_url, ingested_at "
        "FROM nta_saiketsu "
        f"WHERE {' AND '.join(where_parts)} "
        "ORDER BY decision_date DESC NULLS LAST, id ASC "
        "LIMIT ?"
    )
    params.append(int(max_n))
    try:
        rows = am_conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("tax_chain: saiketsu query failed: %s", exc)
        return [], True

    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "id": row["id"],
                "volume_no": row["volume_no"],
                "case_no": row["case_no"],
                "decision_date": row["decision_date"],
                "fiscal_period": row["fiscal_period"],
                "tax_type": row["tax_type"],
                "title": row["title"],
                "decision_summary_snippet": _truncate(row["decision_summary"]),
                "url": row["source_url"],
                "ingested_at": row["ingested_at"],
            }
        )
    return out, True


# ---------------------------------------------------------------------------
# Coverage summary
# ---------------------------------------------------------------------------


def _build_coverage(
    bundle: dict[str, list[dict[str, Any]]],
    *,
    table_presence: dict[str, bool],
) -> dict[str, Any]:
    """Aggregate per-axis counts + missing tables.

    `missing_types` lists axes whose backing table is absent. `axis_counts`
    is a stable dict keyed by canonical axis name so callers can rely on
    every key being present even when the count is 0.
    """
    counts: dict[str, int] = {axis: len(bundle.get(axis, [])) for axis in _ALL_AXES}
    total_refs = sum(counts.values())
    missing = [axis for axis in _ALL_AXES if not table_presence.get(axis, False)]
    return {
        "total_refs": total_refs,
        "axis_counts": counts,
        "missing_types": missing,
    }


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/{rule_id}/full_chain",
    summary="税制 + 法令 + 通達 + 裁決 + 判例 + 改正履歴 を 1 call で取得",
    description=(
        "Returns the full interpretive chain around one tax_ruleset "
        "(`TAX-<10 hex>`) in a single call:\n\n"
        "1. **rule** — the tax_rulesets row itself (規定本文 + 計算式 + "
        "提出要件)\n"
        "2. **laws** — laws table joined via the ruleset's "
        "`related_law_ids_json`\n"
        "3. **tsutatsu** — `nta_tsutatsu_index` rows whose title matches "
        "the ruleset name kanji tokens\n"
        "4. **saiketsu** — `nta_saiketsu` (国税不服審判所 公表裁決事例) "
        "rows whose title / summary matches\n"
        "5. **hanrei** — `court_decisions` whose `related_law_ids_json` "
        "overlaps the ruleset's law refs OR whose `case_name` / "
        "`key_ruling` matches name tokens\n"
        "6. **history** — sibling tax_rulesets with the same "
        "`ruleset_name` (改正履歴)\n\n"
        "**Pricing:** ¥3 / call (`_billing_unit: 1`) regardless of "
        "`max_per_axis`. Pure SQLite, NO LLM.\n\n"
        "**Sensitive:** 税理士法 §52 / 弁護士法 §72 / 公認会計士法 §47条の2 "
        "fence — every response carries a `_disclaimer` envelope key. "
        "LLM agents MUST relay the disclaimer verbatim to end users."
    ),
)
def get_tax_full_chain(
    conn: DbDep,
    ctx: ApiContextDep,
    rule_id: Annotated[
        str,
        Path(
            ...,
            description="Tax ruleset id (`TAX-<10 lowercase hex>`).",
            min_length=14,
            max_length=14,
        ),
    ],
    include: Annotated[
        list[str] | None,
        Query(
            description=(
                "Subset of axes to return. One of "
                "`laws` / `tsutatsu` / `saiketsu` / `hanrei` / `history`. "
                "Comma-separated single-string form is also accepted "
                "(e.g. `?include=laws,hanrei`). Default = all 5."
            ),
        ),
    ] = None,
    max_per_axis: Annotated[
        int,
        Query(
            ge=1,
            le=_HARD_MAX_PER_AXIS,
            description=(
                f"Cap per axis. Hard ceiling {_HARD_MAX_PER_AXIS} "
                f"(default {_DEFAULT_MAX_PER_AXIS})."
            ),
        ),
    ] = _DEFAULT_MAX_PER_AXIS,
) -> JSONResponse:
    """Compose the full chain bundle for ``rule_id``."""
    _t0 = time.perf_counter()

    # --- 422 validation ----------------------------------------------------
    if not _UNIFIED_ID_RE.match(rule_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"rule_id must match TAX-<10 lowercase hex>, got {rule_id!r}",
        )
    requested = _parse_include(include)
    max_n = int(max_per_axis)

    # --- 404 on missing rule ----------------------------------------------
    rule_row = _fetch_rule_row(conn, rule_id)
    if rule_row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"tax_ruleset not found: {rule_id}",
        )
    rule = _shape_rule_row(rule_row)
    rule_name = str(rule["ruleset_name"] or "")
    tax_category = rule["tax_category"]
    law_ids = _parse_law_ids(rule_row["related_law_ids_json"])

    # --- per-axis pulls ---------------------------------------------------
    bundle: dict[str, list[dict[str, Any]]] = {axis: [] for axis in _ALL_AXES}
    presence: dict[str, bool] = dict.fromkeys(_ALL_AXES, True)

    if "laws" in requested:
        rows, present = _fetch_laws(conn, law_ids=law_ids, max_n=max_n)
        bundle["laws"] = rows
        presence["laws"] = present

    if "hanrei" in requested:
        rows, present = _fetch_hanrei(conn, law_ids=law_ids, rule_name=rule_name, max_n=max_n)
        bundle["hanrei"] = rows
        presence["hanrei"] = present

    if "history" in requested:
        rows, present = _fetch_history(conn, rule_row=rule_row, max_n=max_n)
        bundle["history"] = rows
        presence["history"] = present

    # autonomath axes share one connection
    needs_am = bool({"tsutatsu", "saiketsu"} & requested)
    am_conn = _open_autonomath_ro() if needs_am else None

    if "tsutatsu" in requested:
        rows, present = _fetch_tsutatsu(am_conn, rule_name=rule_name, max_n=max_n)
        bundle["tsutatsu"] = rows
        presence["tsutatsu"] = present

    if "saiketsu" in requested:
        rows, present = _fetch_saiketsu(
            am_conn,
            rule_name=rule_name,
            tax_category=tax_category,
            max_n=max_n,
        )
        bundle["saiketsu"] = rows
        presence["saiketsu"] = present

    # autonomath connection is thread-local & shared — do NOT close.

    coverage = _build_coverage(bundle, table_presence=presence)

    # --- response body ----------------------------------------------------
    body: dict[str, Any] = {
        "rule": rule,
        "laws": bundle["laws"],
        "tsutatsu": bundle["tsutatsu"],
        "saiketsu": bundle["saiketsu"],
        "hanrei": bundle["hanrei"],
        "history": bundle["history"],
        "coverage_summary": coverage,
        "_billing_unit": 1,
        "_disclaimer": _TAX_CHAIN_DISCLAIMER,
    }
    attach_corpus_snapshot(body, conn)

    # --- usage event ------------------------------------------------------
    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "tax_rules.full_chain",
        params={
            "rule_id": rule_id,
            "include": sorted(requested),
            "max_per_axis": max_n,
        },
        latency_ms=latency_ms,
        result_count=coverage["total_refs"],
        strict_metering=True,
    )

    return JSONResponse(content=body, headers=snapshot_headers(conn))
