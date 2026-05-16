#!/usr/bin/env python3
"""Static HTML preview generator for jpcite paid packets (JPCIR envelope).

Renders a single JPCIR envelope JSON into a self-contained ``preview.html``
page so that:

1. AI agents can crawl + understand the packet structure (no JS).
2. Search engines can index the public information.
3. Humans can verify the artifact at
   ``https://jpcite.com/packets/<package_id>/preview.html``.

Pipeline
--------
1. Load the JPCIR JSON envelope from a local path or an ``s3://...`` URI.
2. Pre-render: invoke :func:`safety_scanners.scan_forbidden_claims` and
   refuse to render if violations exist (exit code 2). This keeps a §3.3
   "no eligible / safe / no issue" wording leak from reaching the static
   surface.
3. Sanitize: as a defence-in-depth, every text leaf is also run through
   :func:`sanitize_text` which masks the forbidden wording set with the
   neutral phrase ``[redacted_forbidden_wording]`` before HTML escape.
4. Render: build a self-contained HTML document — no external CSS, no JS,
   no images, ~5-15 KB per page. Sections is the only place we touch
   markdown; the renderer is a strict subset (headings, paragraphs,
   bullets, bold/italic, inline code) so we never need a markdown lib.

CLI
---

.. code-block:: text

    python scripts/aws_credit_ops/render_packet_preview.py \\
        <packet_json_path_or_s3_uri> \\
        --out site/packets/<id>/preview.html

S3 URIs require ``boto3`` to be installed; local paths do not. The
``--out`` directory is auto-created.

Constraints
-----------
* **NO LLM API calls.** Pure templating + safety-scanner pre-pass.
* **DO NOT include "eligible / safe / no issue / no violation / permission
  not required / credit score / trustworthy / proved absent" / Japanese
  equivalents** in rendered output. Pre-render scanner refuses the file
  when those appear; the inline sanitizer masks anything the scanner
  missed.
* **mypy strict + ruff 0**.
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

import argparse
import contextlib
import html
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from jpintel_mcp.safety_scanners import (
    FORBIDDEN_JA,
    FORBIDDEN_WORDING,
    Violation,
    scan_forbidden_claims,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

logger = logging.getLogger("render_packet_preview")

PREVIEW_SCHEMA_VERSION: Final[str] = "jpcite.packet_preview.v1"

#: Neutral replacement phrase used by :func:`sanitize_text`. Any forbidden
#: substring that survives the scanner is masked with this placeholder
#: before HTML escape. The phrase is deliberately conspicuous so an
#: operator review can grep it out of generated pages.
REDACTION_PLACEHOLDER: Final[str] = "[redacted_forbidden_wording]"

#: 7-enum known_gap codes per §1.3 of the master plan. Surfaced as a
#: human-readable label next to each gap row.
KNOWN_GAP_LABELS: Final[dict[str, str]] = {
    "csv_input_not_evidence_safe": "CSV 入力は証拠扱いしない",
    "source_receipt_incomplete": "出典 receipt 不完全",
    "pricing_or_cap_unconfirmed": "金額/上限 未確認",
    "no_hit_not_absence": "no_hit は不在を意味しない",
    "professional_review_required": "専門家確認が必要",
    "freshness_stale_or_unknown": "鮮度 stale / unknown",
    "identity_ambiguity_unresolved": "同一性 ambiguity 未解消",
}

#: Footer disclaimer (per master plan §1, fallback when envelope omits one).
DEFAULT_DISCLAIMER: Final[str] = (
    "jpcite は情報検索・根拠確認の補助に徹し、個別具体的な税務・法律・"
    "申請・監査・登記・労務・知財・労基の判断は行いません。"
)

# ---------------------------------------------------------------------------
# Loader: local path or s3:// URI
# ---------------------------------------------------------------------------


def _import_boto3() -> Any:  # pragma: no cover - trivial import shim
    """Lazy boto3 import so the test suite can run without the SDK."""

    try:
        import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError as exc:
        msg = (
            "boto3 is not installed. Install boto3 in the operator environment "
            "(pip install boto3) before passing an s3:// URI to "
            "render_packet_preview."
        )
        raise RuntimeError(msg) from exc
    return boto3


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    """Parse ``s3://bucket/key/path.json`` into ``(bucket, key)``."""

    if not uri.startswith("s3://"):
        msg = f"not an s3 URI: {uri!r}"
        raise ValueError(msg)
    rest = uri[len("s3://") :]
    if "/" not in rest:
        msg = f"s3 URI missing key: {uri!r}"
        raise ValueError(msg)
    bucket, _slash, key = rest.partition("/")
    if not bucket or not key:
        msg = f"s3 URI bucket/key empty: {uri!r}"
        raise ValueError(msg)
    return bucket, key


def load_packet(source: str | Path) -> dict[str, Any]:
    """Load a JPCIR envelope from a local path or an ``s3://`` URI.

    Returns the parsed dict; raises :class:`ValueError` when the payload
    is not a JSON object at the top level.
    """

    if isinstance(source, str) and source.startswith("s3://"):
        bucket, key = _parse_s3_uri(source)
        # PERF-35: prefer the shared client pool so the 200-500 ms boto3
        # cold-start tax is paid once per ``(service, region)`` per
        # process across every preview render. Falls back to the legacy
        # ``_import_boto3`` path when the pool module is unavailable.
        try:
            from scripts.aws_credit_ops._aws import get_client
        except ImportError:
            boto3 = _import_boto3()
            s3 = boto3.client("s3")
        else:
            s3 = get_client("s3")
        response = s3.get_object(Bucket=bucket, Key=key)
        body = response["Body"].read()
        raw = body.encode("utf-8") if isinstance(body, str) else bytes(body)
        parsed = json.loads(raw)
    else:
        path = Path(source)
        with path.open("r", encoding="utf-8") as fh:
            parsed = json.load(fh)
    if not isinstance(parsed, dict):
        msg = f"JPCIR envelope must be a JSON object at the top level; got {type(parsed).__name__}"
        raise ValueError(msg)
    return parsed


# ---------------------------------------------------------------------------
# Sanitizer (defence-in-depth, runs AFTER pre-render scanner)
# ---------------------------------------------------------------------------


def sanitize_text(text: str) -> str:
    """Mask forbidden wording substrings with :data:`REDACTION_PLACEHOLDER`.

    Called by :func:`escape_text` before HTML escape. We rely on the
    pre-render scanner :func:`scan_forbidden_claims` to fail the run when
    forbidden wording is present, but the sanitizer is the last-line
    defence against a future loophole (e.g. a producer adds a new field
    name that the scanner does not yet walk).

    English matching is case-insensitive. Japanese matching is case-less
    by nature.
    """

    sanitized = text
    for phrase in FORBIDDEN_WORDING:
        pattern = re.compile(re.escape(phrase), flags=re.IGNORECASE)
        sanitized = pattern.sub(REDACTION_PLACEHOLDER, sanitized)
    for phrase in FORBIDDEN_JA:
        sanitized = sanitized.replace(phrase, REDACTION_PLACEHOLDER)
    return sanitized


def escape_text(text: str | None) -> str:
    """Sanitize + HTML-escape a string. ``None`` becomes empty."""

    if text is None:
        return ""
    return html.escape(sanitize_text(text), quote=True)


# ---------------------------------------------------------------------------
# Strict Markdown subset renderer for sections[].body
# ---------------------------------------------------------------------------

_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_BULLET_RE: Final[re.Pattern[str]] = re.compile(r"^[-*+]\s+(.+?)\s*$")
_BOLD_RE: Final[re.Pattern[str]] = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE: Final[re.Pattern[str]] = re.compile(r"\*([^*]+)\*")
_CODE_RE: Final[re.Pattern[str]] = re.compile(r"`([^`]+)`")
_HTML_TAG_RE: Final[re.Pattern[str]] = re.compile(r"<[^>]+>")


def _strip_inline_html(text: str) -> str:
    """Strip raw HTML tags from a markdown line.

    The renderer accepts a strict subset — bold / italic / code — and any
    HTML tag in the source is treated as user-provided and stripped out so
    we cannot leak ``<script>`` or any other dangerous markup.
    """

    return _HTML_TAG_RE.sub("", text)


def _inline_md_to_html(text: str) -> str:
    """Convert a single line of strict-subset markdown to safe HTML.

    Order: strip raw HTML → escape → re-apply bold/italic/code as HTML
    tags via marker substitution. We do the substitution AFTER HTML
    escape so the markdown delimiters cannot be smuggled through escape.
    """

    stripped = _strip_inline_html(text)
    # Strip any sentinel control character that appears in the raw input
    # so a producer cannot inject HTML by typing SOH/STX directly. This
    # runs BEFORE we apply our own sentinels.
    stripped = stripped.replace("", "").replace("", "")
    # Apply markdown delimiters as sentinel-wrapped tokens BEFORE HTML
    # escape so the `*` / `**` / backtick characters are detected on the
    # raw input (escape leaves ASCII punctuation alone, but going first
    # keeps the regex obviously honest).
    marked = _BOLD_RE.sub(r"b\1/b", stripped)
    marked = _ITALIC_RE.sub(r"i\1/i", marked)
    marked = _CODE_RE.sub(r"code\1/code", marked)
    sanitized = sanitize_text(marked)
    escaped = html.escape(sanitized, quote=True)
    return (
        escaped.replace("b", "<strong>")
        .replace("/b", "</strong>")
        .replace("i", "<em>")
        .replace("/i", "</em>")
        .replace("code", "<code>")
        .replace("/code", "</code>")
    )


def render_markdown(body: str) -> str:
    """Render a strict-subset markdown body to HTML.

    Supported:

    * ``# h1`` .. ``###### h6`` headings (each on its own line)
    * ``- bullet`` / ``* bullet`` / ``+ bullet`` bullet lists
    * Paragraphs (blank-line separated)
    * Inline ``**bold**``, ``*italic*``, ``` `code` ``` (one-line)

    Anything else (tables, links, raw HTML) is rendered as a paragraph
    with the raw tokens stripped and HTML-escaped — so a producer cannot
    inject arbitrary markup through a section body.
    """

    if not body:
        return ""
    lines = body.replace("\r\n", "\n").split("\n")
    html_parts: list[str] = []
    paragraph_buffer: list[str] = []
    bullet_buffer: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph_buffer:
            return
        joined = " ".join(paragraph_buffer).strip()
        if joined:
            html_parts.append(f"<p>{_inline_md_to_html(joined)}</p>")
        paragraph_buffer.clear()

    def flush_bullets() -> None:
        if not bullet_buffer:
            return
        items_html = "".join(f"<li>{_inline_md_to_html(item)}</li>" for item in bullet_buffer)
        html_parts.append(f"<ul>{items_html}</ul>")
        bullet_buffer.clear()

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            flush_paragraph()
            flush_bullets()
            continue
        heading_match = _HEADING_RE.match(line)
        if heading_match is not None:
            flush_paragraph()
            flush_bullets()
            level = min(len(heading_match.group(1)), 6)
            # Section bodies render under a `<h2>` for the section title,
            # so subordinate headings start at h3 to keep the document
            # hierarchy honest.
            level_html = max(3, level + 2)
            html_parts.append(
                f"<h{level_html}>{_inline_md_to_html(heading_match.group(2))}</h{level_html}>"
            )
            continue
        bullet_match = _BULLET_RE.match(line)
        if bullet_match is not None:
            flush_paragraph()
            bullet_buffer.append(bullet_match.group(1))
            continue
        flush_bullets()
        paragraph_buffer.append(line.strip())
    flush_paragraph()
    flush_bullets()
    return "\n".join(html_parts)


# ---------------------------------------------------------------------------
# HTML builders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SourceRow:
    source_url: str | None
    source_fetched_at: str | None
    publisher: str | None
    license_label: str | None


def _build_source_rows(envelope: dict[str, Any]) -> list[_SourceRow]:
    raw_sources = envelope.get("sources") or []
    rows: list[_SourceRow] = []
    if not isinstance(raw_sources, list):
        return rows
    for src in raw_sources:
        if not isinstance(src, dict):
            continue
        rows.append(
            _SourceRow(
                source_url=_coerce_optional_str(src.get("source_url")),
                source_fetched_at=_coerce_optional_str(src.get("source_fetched_at")),
                publisher=_coerce_optional_str(src.get("publisher")),
                license_label=_coerce_optional_str(src.get("license")),
            )
        )
    return rows


def _coerce_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _is_safe_http_url(url: str | None) -> bool:
    """Return True only for ``http://`` / ``https://`` URLs.

    Anything else (``javascript:``, ``data:``, ``file:``, relative paths)
    is rendered as plain text, never as an anchor href.
    """

    if not url:
        return False
    lower = url.strip().lower()
    return lower.startswith("http://") or lower.startswith("https://")


def _render_link_or_text(url: str | None) -> str:
    if _is_safe_http_url(url):
        # ``url`` is non-None here.
        assert url is not None  # noqa: S101 - narrowed by _is_safe_http_url
        safe = escape_text(url)
        return f'<a href="{safe}" rel="nofollow noopener">{safe}</a>'
    if url is None or not url.strip():
        return '<span class="muted">(出典 URL 未収録)</span>'
    return escape_text(url)


def _render_sources_table(envelope: dict[str, Any]) -> str:
    rows = _build_source_rows(envelope)
    if not rows:
        return '<section id="sources"><h2>出典 (sources)</h2><p class="muted">出典は登録されていません。</p></section>'  # noqa: E501
    body_rows: list[str] = []
    for r in rows:
        body_rows.append(
            "<tr>"
            f"<td>{_render_link_or_text(r.source_url)}</td>"
            f"<td>{escape_text(r.source_fetched_at)}</td>"
            f"<td>{escape_text(r.publisher)}</td>"
            f"<td>{escape_text(r.license_label)}</td>"
            "</tr>"
        )
    return (
        '<section id="sources">'
        "<h2>出典 (sources)</h2>"
        "<table>"
        "<thead><tr>"
        '<th scope="col">source_url</th>'
        '<th scope="col">source_fetched_at</th>'
        '<th scope="col">publisher</th>'
        '<th scope="col">license</th>'
        "</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
        "</section>"
    )


def _render_records_table(envelope: dict[str, Any]) -> str:
    raw_records = envelope.get("records") or []
    if not isinstance(raw_records, list) or not raw_records:
        return ""
    # Collect the union of dict keys across records to drive the header.
    keys: list[str] = []
    seen: set[str] = set()
    for rec in raw_records:
        if not isinstance(rec, dict):
            continue
        for k in rec:
            if k not in seen:
                seen.add(k)
                keys.append(k)
    if not keys:
        return ""
    header_cells = "".join(f'<th scope="col">{escape_text(k)}</th>' for k in keys)
    body_rows: list[str] = []
    for rec in raw_records:
        if not isinstance(rec, dict):
            continue
        cells: list[str] = []
        for k in keys:
            value = rec.get(k)
            cells.append(f"<td>{_format_record_cell(value)}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    return (
        '<section id="records">'
        "<h2>レコード (records)</h2>"
        "<table>"
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
        "</section>"
    )


def _format_record_cell(value: Any) -> str:
    if value is None:
        return '<span class="muted">—</span>'
    if isinstance(value, str):
        return _render_link_or_text(value) if _is_safe_http_url(value) else escape_text(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return escape_text(str(value))
    if isinstance(value, (list, dict)):
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return f"<code>{escape_text(rendered)}</code>"
    return escape_text(str(value))


def _render_sections(envelope: dict[str, Any]) -> str:
    raw_sections = envelope.get("sections") or []
    if not isinstance(raw_sections, list) or not raw_sections:
        return ""
    parts: list[str] = []
    for sec in raw_sections:
        if not isinstance(sec, dict):
            continue
        title = _coerce_optional_str(sec.get("title")) or _coerce_optional_str(
            sec.get("section_id"),
        )
        body = (
            _coerce_optional_str(sec.get("body"))
            or _coerce_optional_str(
                sec.get("section_body"),
            )
            or ""
        )
        section_id = _coerce_optional_str(sec.get("section_id")) or ""
        anchor = re.sub(r"[^A-Za-z0-9_-]+", "-", section_id).strip("-").lower()
        if anchor:
            heading = (
                f'<h2 id="section-{html.escape(anchor, quote=True)}">{escape_text(title)}</h2>'
            )
        else:
            heading = f"<h2>{escape_text(title)}</h2>"
        body_html = render_markdown(body) if body else ""
        if not body_html and not title:
            continue
        parts.append(f"<section>{heading}{body_html}</section>")
    if not parts:
        return ""
    return '<section id="sections-root">' + "".join(parts) + "</section>"


def _render_known_gaps(envelope: dict[str, Any]) -> str:
    raw_gaps = envelope.get("known_gaps") or []
    if not isinstance(raw_gaps, list) or not raw_gaps:
        return (
            '<section id="known-gaps">'
            "<h2>既知ギャップ (known_gaps)</h2>"
            '<p class="muted">登録された既知ギャップはありません。</p>'
            "</section>"
        )
    items: list[str] = []
    for gap in raw_gaps:
        if not isinstance(gap, dict):
            continue
        code = _coerce_optional_str(gap.get("code")) or ""
        description = _coerce_optional_str(gap.get("description")) or ""
        label = KNOWN_GAP_LABELS.get(code, "")
        items.append(
            "<li>"
            f"<code>{escape_text(code)}</code>"
            f"{' — ' + escape_text(label) if label else ''}"
            f"{'<br>' + escape_text(description) if description else ''}"
            "</li>"
        )
    if not items:
        return ""
    return (
        '<section id="known-gaps">'
        "<h2>既知ギャップ (known_gaps)</h2>"
        f"<ul>{''.join(items)}</ul>"
        "</section>"
    )


def _coverage_grade(envelope: dict[str, Any]) -> str:
    raw = envelope.get("coverage")
    if isinstance(raw, dict):
        grade = _coerce_optional_str(raw.get("coverage_grade"))
        if grade:
            return grade
    grade_flat = _coerce_optional_str(envelope.get("coverage_grade"))
    if grade_flat:
        return grade_flat
    return "—"


def _coverage_score(envelope: dict[str, Any]) -> str:
    raw = envelope.get("coverage")
    if isinstance(raw, dict):
        score_obj = raw.get("coverage_score")
        if isinstance(score_obj, (int, float)):
            return f"{float(score_obj):.3f}"
    score_flat = envelope.get("coverage_score")
    if isinstance(score_flat, (int, float)):
        return f"{float(score_flat):.3f}"
    return "—"


def _render_header(envelope: dict[str, Any]) -> str:
    package_id = _coerce_optional_str(envelope.get("package_id")) or "—"
    package_kind = _coerce_optional_str(envelope.get("package_kind")) or "—"
    generated_at = _coerce_optional_str(envelope.get("generated_at")) or "—"
    subject = envelope.get("subject")
    subject_kind = "—"
    subject_id = "—"
    if isinstance(subject, dict):
        subject_kind = _coerce_optional_str(subject.get("kind")) or "—"
        subject_id = _coerce_optional_str(subject.get("id")) or "—"
    coverage_grade = _coverage_grade(envelope)
    coverage_score = _coverage_score(envelope)
    return (
        "<header>"
        '<p class="eyebrow">jpcite packet preview</p>'
        f"<h1>{escape_text(package_id)}</h1>"
        '<dl class="meta">'
        f"<dt>package_kind</dt><dd>{escape_text(package_kind)}</dd>"
        f"<dt>subject.kind</dt><dd>{escape_text(subject_kind)}</dd>"
        f"<dt>subject.id</dt><dd>{escape_text(subject_id)}</dd>"
        f"<dt>generated_at</dt><dd>{escape_text(generated_at)}</dd>"
        f"<dt>coverage_grade</dt><dd>{escape_text(coverage_grade)}</dd>"
        f"<dt>coverage_score</dt><dd>{escape_text(coverage_score)}</dd>"
        "</dl>"
        "</header>"
    )


def _render_footer(envelope: dict[str, Any]) -> str:
    cost = envelope.get("jpcite_cost_jpy")
    tokens_saved = envelope.get("estimated_tokens_saved")
    sources = envelope.get("sources") or []
    source_count = envelope.get("source_count")
    if not isinstance(source_count, int):
        source_count = len(sources) if isinstance(sources, list) else 0
    disclaimer = _coerce_optional_str(envelope.get("disclaimer")) or DEFAULT_DISCLAIMER
    cost_str = f"¥{int(cost):,}" if isinstance(cost, (int, float)) else "—"
    tokens_str = f"{int(tokens_saved):,} tokens" if isinstance(tokens_saved, (int, float)) else "—"
    return (
        "<footer>"
        '<dl class="rollup">'
        f"<dt>jpcite_cost_jpy</dt><dd>{escape_text(cost_str)}</dd>"
        f"<dt>estimated_tokens_saved</dt><dd>{escape_text(tokens_str)}</dd>"
        f"<dt>source_count</dt><dd>{escape_text(str(source_count))}</dd>"
        "</dl>"
        f'<p class="disclaimer">{escape_text(disclaimer)}</p>'
        '<p class="schema">'
        f"schema_version: {escape_text(PREVIEW_SCHEMA_VERSION)}"
        "</p>"
        "</footer>"
    )


# Inline CSS kept tiny so the page stays under the 15 KB ceiling. Static
# values only — no JS, no external resources.
_BASE_STYLE: Final[str] = (
    "body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;"
    "max-width:960px;margin:2rem auto;padding:0 1rem;color:#222;"
    "line-height:1.55}"
    "header .eyebrow{color:#666;text-transform:uppercase;"
    "letter-spacing:.05em;font-size:.8rem;margin:0}"
    "h1{margin:.25rem 0 1rem;font-size:1.7rem}"
    "h2{margin-top:2rem;font-size:1.25rem;"
    "border-bottom:1px solid #ddd;padding-bottom:.25rem}"
    "h3{margin-top:1.5rem;font-size:1.05rem}"
    "dl.meta,dl.rollup{display:grid;grid-template-columns:max-content 1fr;"
    "column-gap:1rem;row-gap:.25rem}"
    "dl dt{font-weight:600;color:#444}dl dd{margin:0}"
    "table{border-collapse:collapse;width:100%;margin:.5rem 0}"
    "th,td{border:1px solid #ddd;padding:.4rem .6rem;text-align:left;"
    "vertical-align:top;font-size:.92rem}"
    "th{background:#f5f5f5}"
    "code{background:#f1f1f1;padding:.05rem .25rem;border-radius:3px;"
    "font-size:.92em}"
    ".muted{color:#888}"
    "footer{margin-top:3rem;padding-top:1rem;border-top:1px solid #ddd;"
    "color:#444;font-size:.9rem}"
    "footer .disclaimer{margin:1rem 0 .25rem}"
    "footer .schema{font-family:monospace;color:#888;margin:0}"
)


def build_html(envelope: dict[str, Any]) -> str:
    """Build the full preview HTML document for a JPCIR envelope.

    Caller is responsible for invoking :func:`scan_forbidden_claims`
    BEFORE this function (and refusing to render on violation). The
    sanitizer is still applied per-leaf as defence in depth.
    """

    package_id = _coerce_optional_str(envelope.get("package_id")) or "packet"
    title = f"jpcite packet preview — {package_id}"
    parts = [
        "<!DOCTYPE html>",
        '<html lang="ja">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta name="robots" content="index,follow">',
        '<meta name="generator" content="jpcite render_packet_preview.py">',
        f"<title>{escape_text(title)}</title>",
        f"<style>{_BASE_STYLE}</style>",
        "</head>",
        "<body>",
        "<main>",
        _render_header(envelope),
        _render_sources_table(envelope),
        _render_records_table(envelope),
        _render_sections(envelope),
        _render_known_gaps(envelope),
        _render_footer(envelope),
        "</main>",
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(part for part in parts if part != "")


# ---------------------------------------------------------------------------
# Top-level entrypoint
# ---------------------------------------------------------------------------


class ForbiddenWordingError(RuntimeError):
    """Raised when :func:`scan_forbidden_claims` returns at least one
    violation. The exit code from :func:`main` is 2 in this case.
    """

    def __init__(self, violations: Sequence[Violation]) -> None:
        super().__init__(f"forbidden-claim violations: {len(violations)} hit(s)")
        self.violations: tuple[Violation, ...] = tuple(violations)


def render_packet(
    envelope: dict[str, Any],
    *,
    source: str | None = None,
) -> str:
    """Pre-scan + render. Raises :class:`ForbiddenWordingError` on violation."""

    violations = scan_forbidden_claims(envelope, source=source)
    if violations:
        raise ForbiddenWordingError(violations)
    return build_html(envelope)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse CLI arguments."""

    p = argparse.ArgumentParser(
        description=(
            "Render a JPCIR envelope JSON into a static preview.html. "
            "Refuses to render if forbidden-claim wording is present."
        ),
    )
    p.add_argument(
        "source",
        help=(
            "Local path to the JPCIR JSON, or an s3://bucket/key URI "
            "(boto3 required for the latter)."
        ),
    )
    p.add_argument(
        "--out",
        required=True,
        help=(
            "Local path to write the preview.html. Parent directories are "
            "created. The file is overwritten if it already exists."
        ),
    )
    return p.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code.

    Exit codes
    ----------
    * 0: success
    * 1: I/O or parse failure
    * 2: forbidden-claim wording detected (rendering refused)
    """

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv if argv is not None else sys.argv[1:])
    source: str = args.source
    out_path = Path(args.out)
    try:
        envelope = load_packet(source)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.error("failed to load packet from %r: %s", source, exc)
        return 1
    try:
        html_text = render_packet(envelope, source=source)
    except ForbiddenWordingError as exc:
        logger.error(
            "refused to render %r: %d forbidden-claim violation(s) detected",
            source,
            len(exc.violations),
        )
        for v in exc.violations:
            logger.error(
                "  packet_id=%s path=%s code=%s detail=%s",
                v.packet_id,
                v.path,
                v.code,
                v.detail,
            )
        return 2
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_text, encoding="utf-8")
    size_bytes = len(html_text.encode("utf-8"))
    logger.info(
        "rendered preview: %s (size=%d bytes, %.1f KB)",
        out_path,
        size_bytes,
        size_bytes / 1024.0,
    )
    return 0


def _utc_now_iso() -> str:  # pragma: no cover - convenience
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def _silence_unused_iterable() -> None:  # pragma: no cover
    """Touch ``Iterable`` so the TYPE_CHECKING import is not stripped by
    aggressive lint rules.
    """

    with contextlib.suppress(Exception):
        _: Iterable[int] = ()  # noqa: F841


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
