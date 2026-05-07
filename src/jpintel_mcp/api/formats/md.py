"""Markdown renderer (GitHub-Flavored pipe table) — ``?format=md``.

Wire shape::

    > **税理士法 §52**: 本データは税務助言ではありません。個別具体的な
    > 判断は税理士・行政書士・弁護士にご確認ください。
    >
    > _出典: e-Gov 法令データ CC-BY 4.0 / 国税庁 PDL v1.0 / jpcite
    > Bookyou株式会社 T8010001213708_

    | unified_id | source_url | source_fetched_at | license | … |
    | --- | --- | --- | --- | --- |
    | PROG-… | https://… | 2026-04-29T03:00:00+09:00 | cc_by_4.0 | … |

Pipe-table cells escape ``|`` as ``\\|`` and rewrite ``\\n`` -> ``<br>`` so a
single row stays inside its cell when pasted into Slack / GitHub Issues
(both renderers honour <br> inside table cells).

Why no Jinja2: the template surface here is a 6-line block-quote + a
pipe table — the inline ``str.join`` + ``"|"``-glue idiom is shorter
than wiring a template loader and immune to template-injection from
arbitrary row content. Jinja2 is in pyproject.toml for the static-site
generator; we deliberately do not pull it in for a 30-line renderer.
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import Response

from jpintel_mcp.api._format_dispatch import (
    BRAND_FOOTER,
    DISCLAIMER_HEADER_VALUE,
    DISCLAIMER_JA,
)

REQUIRED_COLUMNS: tuple[str, ...] = (
    "unified_id",
    "source_url",
    "source_fetched_at",
    "license",
)


def _column_order(rows: list[dict[str, Any]]) -> list[str]:
    """Deterministic union-of-keys column order (required cols lead)."""
    keys: set[str] = set()
    for r in rows:
        keys.update(r.keys())
    rest = sorted(k for k in keys if k not in REQUIRED_COLUMNS)
    return [*REQUIRED_COLUMNS, *rest]


def _md_cell(v: Any) -> str:
    """Pipe-table-safe cell.

    - ``|`` -> ``\\|`` so the cell does not split.
    - ``\\n`` -> ``<br>`` so multi-line strings stay inside a single row.
    - lists/dicts JSON-encode inline.
    - None -> empty string.
    """
    import json

    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, dict)):
        v = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    s = str(v)
    s = s.replace("|", "\\|").replace("\r\n", "\n").replace("\n", "<br>")
    return s


def render_md(rows: list[dict[str, Any]], meta: dict[str, Any]) -> Response:
    """Render ``rows`` to a GitHub-Flavored Markdown report."""
    columns = _column_order(rows)

    lines: list[str] = []
    # Block-quote disclaimer + brand. Each line starts with `>` so the
    # whole block renders as a quoted callout in GitHub / Slack.
    # DISCLAIMER_JA already begins with "税理士法 §52: …" so we strip the
    # leading "税理士法 §52: " before re-emitting under the bold header,
    # otherwise the MD reads "> **税理士法 §52**: 税理士法 §52: …" which is
    # the legal text twice.
    _disclaimer_body = DISCLAIMER_JA
    _lead = "税理士法 §52: "
    if _disclaimer_body.startswith(_lead):
        _disclaimer_body = _disclaimer_body[len(_lead) :]
    lines.append(f"> **税理士法 §52**: {_disclaimer_body}")
    lines.append(">")
    lines.append(f"> _出典: {meta.get('license_summary', '')} / {BRAND_FOOTER}_")
    if meta.get("endpoint"):
        lines.append(f"> _endpoint: `{meta['endpoint']}` / rows: {len(rows)}_")
    lines.append("")

    # Pipe-table header.
    lines.append("| " + " | ".join(_md_cell(c) for c in columns) + " |")
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in rows:
        lines.append("| " + " | ".join(_md_cell(row.get(c)) for c in columns) + " |")

    body = "\n".join(lines) + "\n"
    filename = f"{meta.get('filename_stem', 'autonomath_export')}.md"
    return Response(
        content=body.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-AutonoMath-Disclaimer": DISCLAIMER_HEADER_VALUE,
            "X-AutonoMath-Format": "md",
        },
    )
