"""CSV renderer (RFC 4180 + UTF-8 BOM for Excel-JP) — ``?format=csv``.

Wire shape:
  Row 0 (comment): ``# 税理士法 §52: 本データは税務助言ではありません``
  Row 1 (header):  unified_id, source_url, source_fetched_at, license,
                   primary_name|law_title|case_title|<other>, … (rest of
                   the row keys, deterministic order)
  Row 2..N        : data

UTF-8 BOM ('\\ufeff') prepended so Excel-JP opens the file as UTF-8 instead
of mojibake — the BOM is invisible to csv parsers (the `csv` stdlib treats
the BOM byte as data on the first cell only when present, but our
``test_round_trip`` fixture strips it explicitly via ``utf-8-sig``).

The leading ``# 税理士法 §52`` row is **not** RFC-4180-compliant in the
strictest sense (RFC 4180 has no comment escape) but is universally
accepted by Excel, LibreOffice, pandas (with ``comment='#'``), and Google
Sheets. The round-trip test parses the file with ``utf-8-sig`` + skiprows=1
so the disclaimer travels visibly to the human user without breaking
machine consumers.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from fastapi.responses import Response

from jpintel_mcp.api._format_dispatch import (
    BRAND_FOOTER,
    DISCLAIMER_HEADER_VALUE,
    DISCLAIMER_JA,
)

# Required columns surfaced first so the operator's "did the lineage make
# the trip?" eyeball check is a glance, not a horizontal scroll.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "unified_id",
    "source_url",
    "source_fetched_at",
    "license",
)


def _column_order(rows: list[dict[str, Any]]) -> list[str]:
    """Deterministic union-of-keys column order.

    Required columns lead. Remaining keys are sorted alphabetically so a
    re-render with the same data always produces a byte-identical body
    (matters for cache hashes, snapshot tests).
    """
    keys: set[str] = set()
    for r in rows:
        keys.update(r.keys())
    rest = sorted(k for k in keys if k not in REQUIRED_COLUMNS)
    return [*REQUIRED_COLUMNS, *rest]


def render_csv(rows: list[dict[str, Any]], meta: dict[str, Any]) -> Response:
    """Serialize ``rows`` to a UTF-8-BOM CSV with §52 + lineage columns."""
    columns = _column_order(rows)

    buf = io.StringIO()
    # newline='' prevents csv from doubling \r\n on Windows.
    writer = csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)

    # Comment row 0 — single cell. csv quoting kicks in so the literal
    # `#` does not collide with column-1 data when re-parsed.
    writer.writerow([f"# {DISCLAIMER_JA}"])
    # Comment row 1 — brand + license summary so an offline copy is still
    # source-attributable.
    writer.writerow([f"# {BRAND_FOOTER} | {meta.get('license_summary', '')}"])
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_csv_cell(row.get(c)) for c in columns])

    body = "﻿" + buf.getvalue()
    filename = f"{meta.get('filename_stem', 'autonomath_export')}.csv"
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-AutonoMath-Disclaimer": DISCLAIMER_HEADER_VALUE,
            "X-AutonoMath-Format": "csv",
        },
    )


def _csv_cell(v: Any) -> str:
    """Coerce a value into a CSV-safe string.

    Lists / dicts are JSON-encoded inline (so a ``target_types: ["sme",
    "sole_proprietor"]`` field round-trips as ``["sme", "sole_proprietor"]``
    in the cell rather than mangled str(). Booleans flatten to lowercase.
    None becomes empty string.
    """
    import json

    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    return str(v)
