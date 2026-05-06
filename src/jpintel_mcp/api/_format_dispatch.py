"""Output format dispatcher for ``?format=X`` query-param diversification.

A single entry point — :func:`render` — takes a normalized search-result body
plus a format flag and returns a starlette Response in the chosen wire shape.
Six formats are wired:

    json (default)        — passthrough to JSONResponse
    csv                   — RFC 4180 + UTF-8 BOM (Excel-JP)
    xlsx                  — openpyxl write_only stream
    md                    — Jinja2 Markdown report
    ics                   — RFC 5545 calendar (one VEVENT per next_deadline)
    docx-application      — python-docx 申請書 boilerplate (POST only)
    csv-freee             — accounting CSV (UTF-8)
    csv-mf                — accounting CSV (UTF-8 BOM, MoneyForward)
    csv-yayoi             — accounting CSV (Shift_JIS, 弥生会計)

Cost model: every non-default format is **¥3/req predictable** — the
billing layer charges per request, not per row. Exception: the
``docx-application`` renderer is per-request *and* per-row at ¥3 because it
runs python-docx template rendering (CPU-bound) and one document per row is
the natural unit of work for that surface. The dispatcher does not enforce
billing — that is :mod:`jpintel_mcp.api.cost` and the route handler — but it
does set ``X-AutonoMath-Format`` so the meter can attribute correctly.

Disclaimer trace: every response carries::

    X-AutonoMath-Disclaimer: 税理士法§52(税務助言不可)/弁護士法§72/個別判断は士業確認必須

so a downstream auditor can grep request logs and confirm §52 was relayed
even when the body is binary (XLSX / DOCX). Renderers MUST also embed §52
inline in a format-appropriate way.

The dispatcher is the only public seam between handlers and renderers — do
not import the per-format modules directly from a route file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse

from jpintel_mcp.api._license_gate import (
    LicenseGateError,
    annotate_attribution,
    assert_no_blocked,
)

if TYPE_CHECKING:
    from starlette.responses import Response

# ---------------------------------------------------------------------------
# Public format flag (kept literal so handler `Query(...)` annotations type
# narrow correctly).
# ---------------------------------------------------------------------------

FormatFlag = Literal[
    "json",
    "csv",
    "xlsx",
    "md",
    "ics",
    "docx-application",
    "csv-freee",
    "csv-mf",
    "csv-yayoi",
]

SUPPORTED_FORMATS: tuple[str, ...] = (
    "json",
    "csv",
    "xlsx",
    "md",
    "ics",
    "docx-application",
    "csv-freee",
    "csv-mf",
    "csv-yayoi",
)

# §52 — single source of truth. Every renderer pulls from here.
DISCLAIMER_JA = (
    "税理士法 §52: 本データは税務助言ではありません。"
    "個別具体的な判断は税理士・行政書士・弁護士にご確認ください。"
)
# HTTP header values must be Latin-1 per RFC 7230 §3.2.4 (Starlette enforces
# latin-1.encode at write time). Keep the disclaimer header ASCII so it
# survives every reverse proxy + access-log path; the body / sheet / CSV
# embeds the JA / 漢字 form so the human-readable disclaimer is still
# present at format level. The full JA form is mirrored in
# ``X-AutonoMath-Disclaimer-Ja*`` using RFC 8187 ``filename*`` style so an
# auditor can recover the kanji disclaimer from the header trace too.
DISCLAIMER_HEADER_VALUE = (
    "Tax-Advisor-Act-S52 (no-tax-advice) / Lawyer-Act-S72 / consult-licensed-professional"
)
DISCLAIMER_HEADER_VALUE_JA_RFC8187 = (
    "utf-8''"
    "%E7%A8%8E%E7%90%86%E5%A3%AB%E6%B3%95%C2%A752"
    "(%E7%A8%8E%E5%8B%99%E5%8A%A9%E8%A8%80%E4%B8%8D%E5%8F%AF)"
    "/%E5%BC%81%E8%AD%B7%E5%A3%AB%E6%B3%95%C2%A772"
    "/%E5%80%8B%E5%88%A5%E5%88%A4%E6%96%AD%E3%81%AF%E5%A3%AB%E6%A5%AD"
    "%E7%A2%BA%E8%AA%8D%E5%BF%85%E9%A0%88"
)
BRAND_FOOTER = "jpcite / Bookyou株式会社"


# ---------------------------------------------------------------------------
# Result-row normalization.
# ---------------------------------------------------------------------------


def _coerce_row(row: Any) -> dict[str, Any]:
    """Return a plain dict for one search-result row.

    Accepts pydantic v2 models (``model_dump``), pydantic v1 models
    (``dict``), or already-flat dicts. Anything else is rejected with a
    500 — the dispatcher is downstream of the route's response builder so
    a stray non-dict row is a developer bug, not a user error.
    """
    if isinstance(row, dict):
        return row
    if hasattr(row, "model_dump"):
        return row.model_dump(mode="json")
    if hasattr(row, "dict"):
        return row.dict()
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"format dispatcher cannot serialize row of type {type(row).__name__}",
    )


def _normalize_rows(results: list[Any]) -> list[dict[str, Any]]:
    """Flatten a list of pydantic models / dicts into list[dict].

    Also injects a stable ``license`` + ``source_fetched_at`` key on every
    row so downstream renderers do not have to special-case missing
    columns. The keys are inserted **only when absent** — when the row
    already provides them (laws.fetched_at vs programs.source_fetched_at)
    we leave the original alone.
    """
    out: list[dict[str, Any]] = []
    for r in results:
        d = _coerce_row(r)
        # The various models surface fetched-at under different names.
        # Materialize a unified field so renderers can rely on it.
        if "source_fetched_at" not in d:
            if d.get("fetched_at") is not None:
                d["source_fetched_at"] = d["fetched_at"]
            elif d.get("source_fetched_at") is None:
                d["source_fetched_at"] = None
        if "license" not in d:
            d["license"] = d.get("license", None)
        out.append(d)
    return out


def _default_meta(meta: dict[str, Any] | None) -> dict[str, Any]:
    """Apply default lineage fields to a meta dict.

    Required keys downstream renderers rely on:
      - ``filename_stem`` — base for Content-Disposition
      - ``endpoint``      — short tag for telemetry / brand string
      - ``license_summary`` — short license rollup (e-Gov CC-BY 4.0 + 国税庁 PDL …)
      - ``brand``         — defaults to BRAND_FOOTER
      - ``disclaimer``    — defaults to DISCLAIMER_JA
    """
    m = dict(meta or {})
    m.setdefault("filename_stem", "autonomath_export")
    m.setdefault("endpoint", "autonomath")
    m.setdefault(
        "license_summary",
        "e-Gov 法令データ: CC-BY 4.0 / 国税庁 適格請求書事業者: PDL v1.0 / "
        "その他: 各 source_url 参照",
    )
    m.setdefault("brand", BRAND_FOOTER)
    m.setdefault("disclaimer", DISCLAIMER_JA)
    return m


# ---------------------------------------------------------------------------
# Dispatch.
# ---------------------------------------------------------------------------


def render(
    results: list[Any] | dict[str, Any],
    format_: str | None,
    meta: dict[str, Any] | None = None,
) -> Response:
    """Render ``results`` in the chosen ``format_`` and return a Response.

    ``results`` accepts either:
      - a flat ``list[Row]`` (Row = dict | pydantic model), OR
      - a wrapped ``{"total":..., "results":[...], ...}`` dict — when wrapped
        we lift ``results`` and merge the remaining envelope into ``meta``
        so the renderer still sees the count / pagination fields.

    ``format_`` of ``None`` or ``"json"`` returns the original JSON envelope
    unchanged so existing JSON consumers are untouched.

    Unknown formats raise 400 — silent fallthrough to JSON would mask the
    typo and the user would never get the expected file.
    """
    fmt = (format_ or "json").lower()

    if fmt not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"unknown format '{format_}'. Supported: {', '.join(SUPPORTED_FORMATS)}"),
        )

    # Lift wrapped envelope.
    if isinstance(results, dict) and "results" in results:
        envelope = results
        rows_raw = envelope.get("results", [])
        merged_meta = dict(meta or {})
        for k, v in envelope.items():
            if k != "results":
                merged_meta.setdefault(k, v)
        meta = merged_meta
        results = rows_raw  # noqa: PLW0128 — intentional rebind

    rows = _normalize_rows(list(results))
    meta_out = _default_meta(meta)

    if fmt == "json":
        # Preserve the pre-format envelope shape so JSON callers see no
        # behavioral change. We re-wrap if the caller originally passed
        # a list.
        if "total" in meta_out:
            body = {
                "total": meta_out.get("total", len(rows)),
                "limit": meta_out.get("limit"),
                "offset": meta_out.get("offset"),
                "results": rows,
            }
        else:
            body = {"results": rows}
        json_headers = {
            "X-AutonoMath-Disclaimer": DISCLAIMER_HEADER_VALUE,
            "X-AutonoMath-Format": "json",
        }
        if meta_out.get("corpus_snapshot_id"):
            json_headers["X-Corpus-Snapshot-Id"] = str(meta_out["corpus_snapshot_id"])
        if meta_out.get("corpus_checksum"):
            json_headers["X-Corpus-Checksum"] = str(meta_out["corpus_checksum"])
        return JSONResponse(content=body, headers=json_headers)

    try:
        assert_no_blocked(rows)
    except LicenseGateError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    rows = [annotate_attribution(row) for row in rows]

    # Lazy imports — keeps the cold path light when a request stays JSON
    # (the openpyxl / python-docx / jinja2 stacks are non-trivial).
    if fmt == "csv":
        from jpintel_mcp.api.formats.csv import render_csv

        resp = render_csv(rows, meta_out)
    elif fmt == "xlsx":
        from jpintel_mcp.api.formats.xlsx import render_xlsx

        resp = render_xlsx(rows, meta_out)
    elif fmt == "md":
        from jpintel_mcp.api.formats.md import render_md

        resp = render_md(rows, meta_out)
    elif fmt == "ics":
        from jpintel_mcp.api.formats.ics import render_ics

        resp = render_ics(rows, meta_out)
    elif fmt == "docx-application":
        from jpintel_mcp.api.formats.docx_application import render_docx_application

        resp = render_docx_application(rows, meta_out)
    elif fmt in ("csv-freee", "csv-mf", "csv-yayoi"):
        from jpintel_mcp.api.formats.accounting_csv import render_accounting_csv

        resp = render_accounting_csv(rows, meta_out, vendor=fmt)
    else:
        # Unreachable — SUPPORTED_FORMATS membership already enforced above,
        # but keep an exhaustive guard so a future enum addition without a
        # branch fails loudly.
        raise HTTPException(  # pragma: no cover
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(f"format '{fmt}' is in SUPPORTED_FORMATS but no renderer is wired"),
        )

    # Defense-in-depth: mirror corpus snapshot identity to response headers
    # at the dispatcher level so a future route forgetting to do it manually
    # still emits the auditor-grep pair. Route handlers already inject the
    # same headers; setting them here is idempotent.
    if meta_out.get("corpus_snapshot_id"):
        resp.headers["X-Corpus-Snapshot-Id"] = str(meta_out["corpus_snapshot_id"])
    if meta_out.get("corpus_checksum"):
        resp.headers["X-Corpus-Checksum"] = str(meta_out["corpus_checksum"])
    return resp


__all__ = [
    "BRAND_FOOTER",
    "DISCLAIMER_HEADER_VALUE",
    "DISCLAIMER_JA",
    "SUPPORTED_FORMATS",
    "FormatFlag",
    "render",
]
