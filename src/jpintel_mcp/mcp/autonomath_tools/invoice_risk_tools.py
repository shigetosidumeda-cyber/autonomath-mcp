"""invoice_risk_tools — MCP wrappers for the R8 invoice-risk REST surface.

Three tools surface ``api/invoice_risk.py`` to the MCP cohort:

  - ``invoice_risk_lookup``       — single T-number → risk score
  - ``invoice_risk_batch``        — bulk (max 100) T-numbers → risk scores
  - ``houjin_invoice_status``     — 法人番号 → invoice + risk envelope

Same logic as the REST handlers (the implementation is shared via the
``api.invoice_risk`` module's ``_compose_risk`` function), exposed under
the MCP cohort gate. NO LLM call inside; pure SQL + Python heuristic.

Gating
------

``AUTONOMATH_INVOICE_RISK_ENABLED`` defaults to ``1`` (ON). Setting it to
``0`` removes the three tools from ``mcp.list_tools()`` so the launch
manifest can hold at 151 until the next intentional bump.

Sensitivity
-----------

risk_score brushes against 仕入税額控除 / 消費税法 §30 territory; every
result therefore carries a ``_disclaimer`` 税理士法 §52 fence.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.invoice_risk")

# Env-gated registration (default ON). Flip to "0" for one-flag rollback.
_ENABLED = os.environ.get("AUTONOMATH_INVOICE_RISK_ENABLED", "1") == "1"

# Batch cap mirror — keep in lockstep with api/invoice_risk.py::_BATCH_MAX.
_BATCH_MAX = 100


# ---------------------------------------------------------------------------
# DB helpers — invoice_registrants + houjin_master live in jpintel.db.
# ---------------------------------------------------------------------------


def _jpintel_db_path() -> Path:
    raw = os.environ.get("JPINTEL_DB_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[5] / "data" / "jpintel.db"


def _open_db() -> sqlite3.Connection | dict[str, Any]:
    """Open jpintel.db read-only, returning a conn or error envelope."""
    p = _jpintel_db_path()
    if not p.exists():
        return make_error(
            code="db_unavailable",
            message=f"jpintel.db missing: {p}",
            hint="Check JPINTEL_DB_PATH and that the volume is mounted.",
        )
    try:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"jpintel.db open failed: {exc}",
        )


# ---------------------------------------------------------------------------
# Implementations — delegate scoring to api.invoice_risk so a single source
# of truth governs the score taxonomy. The MCP wrappers ONLY adapt the
# envelope shape (results[] + total + _billing_unit + _disclaimer).
# ---------------------------------------------------------------------------


def _import_compose() -> Any:
    """Lazy import to keep MCP import-time cheap and avoid circular ref."""
    # `--no-implicit-reexport` mypy mode rejects underscored names crossing
    # module boundaries unless re-exported via `__all__`. We deliberately
    # depend on internal helpers here (single-source-of-truth for the risk
    # taxonomy + regex) — silencing per-line is the smallest patch.
    from jpintel_mcp.api.invoice_risk import (  # type: ignore[attr-defined]
        _DISCLAIMER_RISK,
        _REG_NUMBER_RE,
        _compose_risk,
        _fetch_houjin_master,
        _fetch_invoice_by_houjin,
        _fetch_invoice_row,
    )

    return {
        "compose": _compose_risk,
        "fetch_invoice": _fetch_invoice_row,
        "fetch_master": _fetch_houjin_master,
        "fetch_by_houjin": _fetch_invoice_by_houjin,
        "regex": _REG_NUMBER_RE,
        "disclaimer": _DISCLAIMER_RISK,
    }


def _single_lookup_impl(tnum: str) -> dict[str, Any]:
    """Single-T-number lookup. Returns the canonical envelope shape."""
    helpers = _import_compose()
    if not isinstance(tnum, str) or not helpers["regex"].match(tnum.strip()):
        return make_error(
            code="invalid_input",
            message="invoice_registration_number must match '^T\\d{13}$'",
            field="invoice_registration_number",
        )
    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db
    try:
        invoice_row = helpers["fetch_invoice"](conn, tnum.strip())
        master_row = (
            helpers["fetch_master"](conn, invoice_row["houjin_bangou"])
            if invoice_row is not None
            else None
        )
        risk = helpers["compose"](tnum.strip(), invoice_row, master_row)
        return {
            "total": 1,
            "limit": 1,
            "offset": 0,
            "results": [risk.model_dump()],
            "_disclaimer": helpers["disclaimer"],
            "_billing_unit": 1,
            "_next_calls": [
                {
                    "tool": "get_houjin_360_am",
                    "args": {
                        "houjin_bangou": (
                            invoice_row["houjin_bangou"] if invoice_row is not None else None
                        ),
                    },
                    "rationale": (
                        "houjin 360° (gBizINFO + 採択 + 行政処分) で 与信判断材料を補強。"
                    ),
                    "compound_mult": 1.5,
                }
            ]
            if invoice_row is not None and invoice_row["houjin_bangou"]
            else [],
        }
    finally:
        conn.close()


def _batch_lookup_impl(tnums: list[str]) -> dict[str, Any]:
    """Batch (max 100). Per-item error string when shape rejects."""
    if not isinstance(tnums, list) or not tnums:
        return make_error(
            code="missing_required_arg",
            message="tnums must be a non-empty list of T-numbers.",
            field="tnums",
        )
    if len(tnums) > _BATCH_MAX:
        return make_error(
            code="out_of_range",
            message=f"tnums length {len(tnums)} exceeds batch cap {_BATCH_MAX}.",
            field="tnums",
        )
    helpers = _import_compose()
    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db
    items: list[dict[str, Any]] = []
    try:
        for raw in tnums:
            tnum = (raw or "").strip() if isinstance(raw, str) else ""
            if not helpers["regex"].match(tnum):
                items.append(
                    {
                        "invoice_registration_number": tnum,
                        "risk": None,
                        "error": "invoice_registration_number must match '^T\\d{13}$'",
                    }
                )
                continue
            invoice_row = helpers["fetch_invoice"](conn, tnum)
            master_row = (
                helpers["fetch_master"](conn, invoice_row["houjin_bangou"])
                if invoice_row is not None
                else None
            )
            risk = helpers["compose"](tnum, invoice_row, master_row)
            items.append(
                {
                    "invoice_registration_number": tnum,
                    "risk": risk.model_dump(),
                    "error": None,
                }
            )
        return {
            "total": len(items),
            "limit": _BATCH_MAX,
            "offset": 0,
            "results": items,
            "_disclaimer": helpers["disclaimer"],
            "_billing_unit": 1,  # 1 metered call regardless of batch size
            "_next_calls": [],
        }
    finally:
        conn.close()


def _houjin_status_impl(bangou: str) -> dict[str, Any]:
    """法人番号 → invoice_status. Returns a single-item canonical envelope."""
    if not isinstance(bangou, str) or not bangou.strip().isdigit() or len(bangou.strip()) != 13:
        return make_error(
            code="invalid_input",
            message="bangou must be 13 digits.",
            field="bangou",
        )
    bangou = bangou.strip()
    helpers = _import_compose()
    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db
    try:
        invoice_row = helpers["fetch_by_houjin"](conn, bangou)
        master_row = helpers["fetch_master"](conn, bangou)

        if invoice_row is not None:
            risk = helpers["compose"](
                invoice_row["invoice_registration_number"],
                invoice_row,
                master_row,
            )
            payload = risk.model_dump()
            payload["houjin_bangou"] = bangou
        else:
            # No T-number on file. Synthesize a block-band envelope so the
            # caller LLM can render it with the same shape branch.
            synthetic = f"T{bangou}"
            risk = helpers["compose"](synthetic, None, master_row)
            payload = risk.model_dump()
            payload["houjin_bangou"] = bangou
            payload["invoice_registration_number"] = None
            payload["registered"] = False
            payload["rationale"] = (
                "この法人番号には適格請求書発行事業者番号が登録されていません。"
                "仕入税額控除の前提を満たしません。"
            )

        return {
            "total": 1,
            "limit": 1,
            "offset": 0,
            "results": [payload],
            "_disclaimer": helpers["disclaimer"],
            "_billing_unit": 1,
            "_next_calls": [
                {
                    "tool": "invoice_risk_lookup",
                    "args": {"tnum": invoice_row["invoice_registration_number"]}
                    if invoice_row is not None
                    else {},
                    "rationale": ("T 番号レベルで再 lookup し、risk_score の根拠を再確認。"),
                    "compound_mult": 1.3,
                }
            ]
            if invoice_row is not None
            else [],
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# MCP tool registration. Gated by AUTONOMATH_INVOICE_RISK_ENABLED + the
# global AUTONOMATH_ENABLED gate (autonomath_tools/__init__.py imports this
# module unconditionally, so we re-check the flag here).
# ---------------------------------------------------------------------------
if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def invoice_risk_lookup(
        tnum: Annotated[
            str,
            Field(
                description=("適格事業者番号 (T + 13 数字). 例 'T8010001213708'."),
                pattern=r"^T\d{13}$",
            ),
        ],
    ) -> dict[str, Any]:
        """[R8-INVOICE-RISK] T-number 単発 risk lookup. invoice_registrants × houjin_master を機械的照合し、0-100 score + tax_credit_eligible boolean + 6 ヶ月 / 1 年経過 heuristic で risk_band (clear / caution / verify / block) を返す。NO LLM。§52 fence on 仕入税額控除 territory。"""
        return _single_lookup_impl(tnum=tnum)

    @mcp.tool(annotations=_READ_ONLY)
    def invoice_risk_batch(
        tnums: Annotated[
            list[str],
            Field(
                description=(f"List of 適格事業者番号 (T + 13 数字), max {_BATCH_MAX} per call."),
                min_length=1,
                max_length=_BATCH_MAX,
            ),
        ],
    ) -> dict[str, Any]:
        """[R8-INVOICE-RISK] T-number 一括 risk lookup (最大 100 件 / 1 metered call)。各 item は invoice_risk_lookup と同じ envelope shape (risk={…} or error="…")。経理 fan-out で取引先一覧を 1 call で scoring する用途。NO LLM。§52 fence。"""
        return _batch_lookup_impl(tnums=tnums)

    @mcp.tool(annotations=_READ_ONLY)
    def houjin_invoice_status(
        bangou: Annotated[
            str,
            Field(
                description="13-digit 法人番号 (T 接頭辞なし).",
                pattern=r"^\d{13}$",
            ),
        ],
    ) -> dict[str, Any]:
        """[R8-INVOICE-RISK] 法人番号 → 適格事業者番号 resolve + risk envelope。invoice_registrants 側で houjin_bangou が見つからない場合は invoice_registration_number=null + registered=False + score=100 (block) を返す。NO LLM。§52 fence。"""
        return _houjin_status_impl(bangou=bangou)
