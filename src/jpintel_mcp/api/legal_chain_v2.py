"""GET /v1/legal/chain/{program_id} — Dim B legal_chain 5-layer 因果関係追跡.

Single-call composite that returns, for one program (jpintel
``programs.unified_id``), all 5 causal layers that produced the制度's
legal existence:

    1. **budget**       — 予算成立 (該当年度の歳出予算 / 補正予算 / 概算要求)
    2. **law**          — 該当法令 article (法律 / 政令 / 省令 / 通達 / 告示)
    3. **cabinet**      — 関連 閣議決定 / 内閣府令 / 政令 (cabinet order)
    4. **enforcement**  — 行政処分 history (関連事業者 / 関連処分歴)
    5. **case**         — 該当採択事例 (similar 採択 within same 制度 family)

Each layer carries an **evidence_url** (REQUIRED, one-shot first-party
government domain — aggregators are banned by ETL discipline), a verbatim
``layer_data_json`` payload (≤ 4KB), a ≤ 200-char ``layer_summary``
verbatim source quote, and an optional ``next_layer_link`` pointer so a
downstream traverser can step layer1 → layer5 without re-querying.

Hard constraints
----------------
* NO LLM call. Pure SQLite SELECT + Python dict shaping.
* Cross-DB reads: jpintel.db (programs anchor) AND autonomath.db
  (am_legal_chain). CLAUDE.md forbids ATTACH / cross-DB JOIN, so the two
  halves are pulled separately and merged in Python.
* Sensitive surface — 弁護士法 §72 (法令解釈) + 行政書士法 §1 (官公署
  提出書類) fence injected via ``_disclaimer``. The output is a citation
  index; the customer LLM MUST relay the disclaimer verbatim.
* ``_billing_unit: 3`` (¥3/req × 3 unit = 税込 ¥9.90) — chain query is
  heavy (5 SELECTs × per-layer caps, no FTS narrowing).
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

logger = logging.getLogger("jpintel.api.legal_chain_v2")

router = APIRouter(prefix="/v1/legal", tags=["legal_chain"])


_PROGRAM_ID_RE = re.compile(r"^[A-Z]{2,5}-[0-9a-zA-Z\-_.]{1,80}$")

_LEGAL_CHAIN_DISCLAIMER = (
    "本 legal_chain は jpcite + autonomath corpus (am_legal_chain / programs / "
    "laws / am_enforcement_detail / case_studies) を一次資料 URL と共に 1 call で "
    "束ねた検索結果で、弁護士法 §72 (法令解釈) ・行政書士法 §1 (官公署提出書類) "
    "・税理士法 §52 (税務代理) のいずれの士業役務にも該当しません。掲載の予算成立 / "
    "法令 / 閣議決定 / 行政処分 / 採択事例は公表時点の情報であり、改正により現在の "
    "取扱が変更されている可能性があります。各 layer の evidence_url で原典を確認の "
    "うえ、確定判断は資格を有する弁護士・行政書士・税理士に必ずご相談ください。"
)


_ALL_LAYERS: tuple[str, ...] = (
    "budget",
    "law",
    "cabinet",
    "enforcement",
    "case",
)
_LAYER_NUM: dict[str, int] = {name: i + 1 for i, name in enumerate(_ALL_LAYERS)}
_ALL_LAYERS_SET: frozenset[str] = frozenset(_ALL_LAYERS)


_DEFAULT_MAX_PER_LAYER = 10
_HARD_MAX_PER_LAYER = 50

_SNIPPET_CHAR_CAP = 200


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


def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Open ``autonomath.db`` read-only; ``None`` when missing."""
    try:
        from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath

        return connect_autonomath()
    except (FileNotFoundError, sqlite3.Error) as exc:
        logger.warning("legal_chain_v2: autonomath.db unavailable: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("legal_chain_v2: autonomath.db open failed: %s", exc)
        return None


def _parse_include(include: list[str] | None) -> set[str]:
    """Validate ``include`` query and return canonical layer set."""
    if include is None:
        return set(_ALL_LAYERS)
    cleaned: set[str] = set()
    for raw in include:
        if not isinstance(raw, str):
            continue
        for token in raw.split(","):
            t = token.strip()
            if not t:
                continue
            if t not in _ALL_LAYERS_SET:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "error": "invalid_include_value",
                        "field": "include",
                        "message": (
                            f"include must be a subset of {sorted(_ALL_LAYERS)}; got {t!r}."
                        ),
                    },
                )
            cleaned.add(t)
    if not cleaned:
        return set(_ALL_LAYERS)
    return cleaned


def _fetch_program_row(
    conn: sqlite3.Connection,
    program_id: str,
) -> sqlite3.Row | None:
    """Resolve the anchor program. Returns None when absent."""
    if not _table_exists(conn, "programs"):
        return None
    try:
        row = conn.execute(
            "SELECT unified_id, primary_name, authority_level, authority_name, "
            "       prefecture, municipality, program_kind, official_url, tier "
            "FROM programs WHERE unified_id = ?",
            (program_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("legal_chain_v2: program lookup failed: %s", exc)
        return None
    if row is None:
        return None
    assert isinstance(row, sqlite3.Row)
    return row


def _shape_program_anchor(row: sqlite3.Row) -> dict[str, Any]:
    """Render the program row as the chain's `anchor` block."""
    return {
        "program_id": row["unified_id"],
        "primary_name": row["primary_name"],
        "authority_level": row["authority_level"],
        "authority_name": row["authority_name"],
        "prefecture": row["prefecture"],
        "municipality": row["municipality"],
        "program_kind": row["program_kind"],
        "official_url": row["official_url"],
        "tier": row["tier"],
    }


def _shape_chain_row(row: sqlite3.Row) -> dict[str, Any]:
    """Render an am_legal_chain row into the wire shape."""
    raw_data = row["layer_data_json"]
    try:
        data = json.loads(raw_data) if isinstance(raw_data, str) else (raw_data or {})
    except (json.JSONDecodeError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {"raw": str(raw_data)[:512]}
    return {
        "chain_id": row["chain_id"],
        "layer": row["layer"],
        "layer_name": row["layer_name"],
        "evidence_url": row["evidence_url"],
        "evidence_host": row["evidence_host"],
        "layer_summary": _truncate(row["layer_summary"]),
        "effective_date": row["effective_date"],
        "next_layer_link": row["next_layer_link"],
        "license": row["license"],
        "layer_data": data,
        "ingested_at": row["ingested_at"],
    }


def _fetch_pre_warmed_chain(
    am_conn: sqlite3.Connection | None,
    *,
    program_id: str,
    requested_layers: set[str],
    max_n: int,
) -> tuple[dict[str, list[dict[str, Any]]], bool]:
    """Pull pre-warmed chain rows from ``am_legal_chain``."""
    bundle: dict[str, list[dict[str, Any]]] = {layer: [] for layer in _ALL_LAYERS}
    if am_conn is None or not _table_exists(am_conn, "am_legal_chain"):
        return bundle, False
    layer_nums = sorted(_LAYER_NUM[name] for name in requested_layers)
    if not layer_nums:
        return bundle, True
    placeholders = ",".join("?" * len(layer_nums))
    sql = (
        "SELECT chain_id, anchor_program_id, layer, layer_name, evidence_url, "
        "       evidence_host, layer_data_json, layer_summary, effective_date, "
        "       next_layer_link, license, redistribute_ok, ingested_at "
        "FROM am_legal_chain "
        f"WHERE anchor_program_id = ? AND layer IN ({placeholders}) "
        "  AND redistribute_ok = 1 "
        "ORDER BY layer ASC, effective_date DESC NULLS LAST, chain_id ASC "
        "LIMIT ?"
    )
    params: list[Any] = [program_id, *layer_nums, int(max_n) * len(layer_nums)]
    try:
        rows = am_conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("legal_chain_v2: am_legal_chain query failed: %s", exc)
        return bundle, True
    per_layer_count: dict[str, int] = dict.fromkeys(_ALL_LAYERS, 0)
    for row in rows:
        name = row["layer_name"]
        if name not in _ALL_LAYERS_SET:
            continue
        if per_layer_count[name] >= max_n:
            continue
        bundle[name].append(_shape_chain_row(row))
        per_layer_count[name] += 1
    return bundle, True


def _build_coverage(
    bundle: dict[str, list[dict[str, Any]]],
    *,
    table_presence: dict[str, bool],
    pre_warmed: bool,
) -> dict[str, Any]:
    """Summary block: counts + missing surfaces + chain integrity flags."""
    counts = {layer: len(rows) for layer, rows in bundle.items()}
    total_refs = sum(counts.values())
    missing: list[str] = sorted(
        layer for layer in _ALL_LAYERS if not table_presence.get(layer, True)
    )
    weak_link_layers: list[str] = []
    for layer in _ALL_LAYERS:
        rows = bundle.get(layer, [])
        if not rows:
            continue
        if layer == "case":
            continue
        none_count = sum(1 for r in rows if not r.get("next_layer_link"))
        if pre_warmed and none_count == len(rows):
            weak_link_layers.append(layer)
    return {
        "counts": counts,
        "total_refs": total_refs,
        "missing_types": missing,
        "pre_warmed": pre_warmed,
        "weak_link_layers": weak_link_layers,
    }


@router.get(
    "/chain/{program_id}",
    summary="Dim B legal_chain 5-layer 因果関係追跡 — 1 call で chain 全体",
    description=(
        "**Dim B legal_chain v2** — 一次資料 5 layer 因果関係追跡.\n\n"
        "Returns all 5 causal layers for one program in a single call:\n\n"
        "1. **budget** — 予算成立 (該当年度 歳出 / 補正 / 概算要求)\n"
        "2. **law** — 該当法令 article (法律 / 政令 / 省令 / 通達 / 告示)\n"
        "3. **cabinet** — 関連 閣議決定 / 内閣府令 / 政令 (cabinet order)\n"
        "4. **enforcement** — 行政処分 history (関連事業者 / 関連処分歴)\n"
        "5. **case** — 該当採択事例 (similar 採択 within same 制度 family)\n\n"
        "Each layer carries **evidence_url** (REQUIRED, primary first-"
        "party government domain — aggregators are banned by ETL).\n\n"
        "**Pricing:** ¥3 / call × 3 unit = ¥9 / 9.90 incl tax "
        "(`_billing_unit: 3`). Heavy chain query.\n\n"
        "**Sensitive:** 弁護士法 §72 / 行政書士法 §1 / 税理士法 §52 "
        "fence — every response carries a `_disclaimer` envelope key."
    ),
)
def get_legal_chain(
    conn: DbDep,
    ctx: ApiContextDep,
    program_id: Annotated[
        str,
        Path(
            ...,
            description="Program id (`UNI-...` / `NTA-...` / `MUNI-...` / etc.).",
            min_length=4,
            max_length=96,
        ),
    ],
    include: Annotated[
        list[str] | None,
        Query(
            description=(
                "Subset of layers. One of "
                "`budget` / `law` / `cabinet` / `enforcement` / `case`. "
                "Default = all 5."
            ),
        ),
    ] = None,
    max_per_layer: Annotated[
        int,
        Query(
            ge=1,
            le=_HARD_MAX_PER_LAYER,
            description=(
                f"Cap per layer. Hard ceiling {_HARD_MAX_PER_LAYER} "
                f"(default {_DEFAULT_MAX_PER_LAYER})."
            ),
        ),
    ] = _DEFAULT_MAX_PER_LAYER,
) -> JSONResponse:
    """Compose the 5-layer legal chain bundle for ``program_id``."""
    _t0 = time.perf_counter()

    if not _PROGRAM_ID_RE.match(program_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"program_id must match prefix-suffix shape; got {program_id!r}",
        )
    requested = _parse_include(include)
    max_n = int(max_per_layer)

    prog_row = _fetch_program_row(conn, program_id)
    if prog_row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"program not found: {program_id}",
        )
    anchor = _shape_program_anchor(prog_row)

    am_conn = _open_autonomath_ro()
    bundle, am_present = _fetch_pre_warmed_chain(
        am_conn,
        program_id=program_id,
        requested_layers=requested,
        max_n=max_n,
    )

    presence: dict[str, bool] = dict.fromkeys(_ALL_LAYERS, am_present)
    pre_warmed = am_present and any(len(rows) > 0 for rows in bundle.values())

    coverage = _build_coverage(
        bundle,
        table_presence=presence,
        pre_warmed=pre_warmed,
    )

    body: dict[str, Any] = {
        "anchor": anchor,
        "layers": {
            "budget": bundle["budget"],
            "law": bundle["law"],
            "cabinet": bundle["cabinet"],
            "enforcement": bundle["enforcement"],
            "case": bundle["case"],
        },
        "coverage_summary": coverage,
        "_billing_unit": 3,
        "_disclaimer": _LEGAL_CHAIN_DISCLAIMER,
    }
    attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "legal.chain",
        params={
            "program_id": program_id,
            "include": sorted(requested),
            "max_per_layer": max_n,
        },
        latency_ms=latency_ms,
        result_count=coverage["total_refs"],
        quantity=3,
        strict_metering=True,
    )

    return JSONResponse(content=body, headers=snapshot_headers(conn))
