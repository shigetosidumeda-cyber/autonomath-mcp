"""Output format renderers for ``?format=X`` query param dispatch.

Per-format modules under this package each expose a ``render(results, meta)``
function returning a starlette Response. The shared dispatcher in
``jpintel_mcp.api._format_dispatch`` is the single entry point — handlers
should never import these renderer modules directly.

License / disclaimer hygiene:
  - Every renderer is required to surface the §52 disclaimer
    (税理士法 §52 — 本データは税務助言ではありません) verbatim somewhere
    structurally appropriate for the format (CSV header comment row, XLSX
    _meta sheet, Markdown footer fenced block, ICS X-WR-CALDESC, DOCX
    cover, accounting-CSV comment row).
  - Every renderer must preserve unified_id / source_url / license /
    source_fetched_at on each row so the round-trip parser can reconstruct
    the lineage.

The accounting-CSV variants (csv-freee / csv-mf / csv-yayoi) all live in
``accounting_csv.py`` because they share encoding + 備考-pack logic and
diverge only on a single per-vendor column-name table.
"""

__all__: list[str] = []
