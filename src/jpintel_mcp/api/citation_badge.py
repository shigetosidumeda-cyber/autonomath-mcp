"""DEEP-27 citation badge widget — REST surface (CL-08).

Two endpoints back the `jpcite verified` 1-line copy-paste badge:

  * ``GET /widget/badge.svg?request_id={UUID}`` → 120×20 SVG, 4 states
    (`verified` / `expired` / `invalid` / `boundary_warn`). The SVG is
    generated in-process from a tiny template — no Cairo, no Pillow —
    so it ships with the API container and stays serverless. In
    production this Python path is mirrored by a Cloudflare Workers
    handler reading the same `citation_log` rows from a read-only KV
    snapshot; the Python version is the canonical surface for tests +
    Fly fallback.
  * ``GET /citation/{request_id}`` → Markdown page rendering the
    `citation_log` row + `source_receipt` block + `identity_confidence`
    score + `amendment_lineage` chain + 業法 disclaimer envelope +
    audit_seal digest. Same content is published as a static MD page
    on Cloudflare Pages at receipt-creation time; the API path is
    available for the build hook plus dynamic preview.

Hard constraints (memory ``feedback_no_operator_llm_api`` +
``feedback_no_priority_question`` + ``feedback_organic_only_no_ads``)
--------------------------------------------------------------------
* NO LLM call inside this module. Pure regex / SQLite / string
  formatting. The CI guard ``tests/test_no_llm_in_production.py``
  enforces zero ``anthropic`` / ``openai`` / ``google.generativeai`` /
  ``claude_agent_sdk`` imports under ``src/jpintel_mcp/api/``.
* No paid acquisition surface — the badge is free; the originating
  ¥3 metered call mints the receipt that backs it.
* No tier badge / `Pro` / `Starter` copy. Only the four state strings
  above.

Scrubber (APPI fence)
---------------------
Patterns redacted from `answer_text` before INSERT and before MD
render are kept INLINE in this module so the migration documentation
(`scripts/migrations/wave24_183_citation_log.sql`) and the runtime
agree on a single source of truth. Whitelisted (NOT redacted):
法人番号 (13 digits, public NTA), 郵便番号 (7 digits prefix only),
都道府県 / 市区町村 names. The SVG `alt` text is the static literal
``"jpcite verified"`` — never embeds PII or program names.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import sqlite3
import uuid
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi import Path as FPath

logger = logging.getLogger("jpintel.api.citation_badge")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VerifiedStatus = Literal["verified", "expired", "invalid", "boundary_warn"]
_VALID_STATUSES: frozenset[str] = frozenset({"verified", "expired", "invalid", "boundary_warn"})

# Aggregator banlist mirrored from `_verifier.py` so the badge enforcement
# stays in lock-step with DEEP-25. Reused for citation MD source rejection.
AGGREGATOR_HOSTS: frozenset[str] = frozenset(
    {
        "noukaweb.com",
        "hojyokin-portal.jp",
        "biz.stayway.jp",
        "stayway.jp",
        "subsidist.jp",
    }
)

# Default disclaimer envelope (DEEP-23). The badge `<title>` carries this
# text so screen readers + tooltip render the §52 fence inline. The
# customer-facing tool that minted the receipt may emit a more specific
# envelope — when that arrives via `_disclaimer.envelope_id` the static
# MD page will render the per-tool string. The SVG keeps the universal
# default so a single `badge.svg` does not need per-tool branching.
DISCLAIMER_JA = (
    "本表示は jpcite による参照確認のみを示し、税務・法律・登記の判断や代理を意味しません。"
    "§52 (税理士法) / §47条の2 (弁護士法) / §72 (司法書士法) fence。"
)
DISCLAIMER_EN = (
    "This badge indicates a corpus citation only and does not constitute "
    "tax, legal, or judicial-scrivener advice or representation. "
    "§52 / §47-2 / §72 fence."
)

# UUIDv4 hex+dash regex. We accept both bare 32-char hex (uuid.uuid4().hex)
# and the canonical 8-4-4-4-12 form so the badge URL stays human-friendly.
_UUID_RE = re.compile(
    r"^(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)


# ---------------------------------------------------------------------------
# PII scrubber (APPI fence) — inline so migration + runtime stay in sync
# ---------------------------------------------------------------------------

# Order matters: longer / more-specific tokens first.
_SCRUBBER_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # 個人マイナンバー (12 digits, no separator). 法人番号 = 13 桁 so this
    # bounded regex never collides.
    (re.compile(r"(?<!\d)\d{12}(?!\d)"), "[マイナンバー]"),
    # クレジットカード (4-4-4-4 or 16 digit run).
    (
        re.compile(r"(?<!\d)\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}(?!\d)"),
        "[カード番号]",
    ),
    # 電話番号 — ASCII hyphen variants. Bounded with digit lookbehind /
    # lookahead so a bare houjin (13 digit) does not collapse.
    (
        re.compile(
            r"(?<!\d)"
            r"(?:"
            r"\+?81[-\s]\d{1,4}[-\s.]\d{1,4}[-\s.]\d{3,4}"
            r"|0\d{1,4}[-\s.]\d{1,4}[-\s.]\d{3,4}"
            r"|0[789]0\d{8}"
            r")"
            r"(?!\d)"
        ),
        "[電話番号]",
    ),
    # email
    (re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}"), "[email]"),
    # 番地 — three-segment digit-hyphen run that follows (within the
    # nearest 15 chars) a 都道府県 / 市区町村 / 区 / 町 / 村 token. The
    # block name itself (e.g. 小日向) sits between, so the lookbehind
    # is widened to match 番地 patterns embedded in real addresses.
    # Strictly digit-hyphen-digit-hyphen-digit (canonical_id uses
    # colons, not hyphens, so canonical_ids are never scrubbed).
    (
        re.compile(r"(?<=[都道府県市区町村])[^\d\n]{0,15}\d+-\d+-\d+"),
        "[番地]",
    ),
)

# Forbidden-phrase patterns surfaced by `boundary_warn` cron — the same
# regex set is used both as a server-side reject filter for `answer_text`
# and as the customer-page crawler signal. Source: DEEP-23 fence list +
# memory `feedback_autonomath_fraud_risk`.
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "確実に採択",
    "100%採択",
    "判断します",
    "申告します",
    "代理します",
    "保証します",
)


def scrub(text: str) -> str:
    """Redact PII from a free-text payload before persistence + render.

    Returns a NEW string; the input is never mutated. ``None`` input
    returns the empty string. The ``answer_text`` column is bounded at
    4 KB by the SQLite CHECK constraint — we DO NOT truncate here so a
    too-long input surfaces as a 422 from the upstream caller, never
    silently discarded.
    """
    if not text:
        return ""
    out = text
    for pat, repl in _SCRUBBER_PATTERNS:
        out = pat.sub(repl, out)
    return out


def has_forbidden_phrase(text: str) -> bool:
    """Return True iff `text` carries any DEEP-23 forbidden phrase.

    Used by the upstream insert path to refuse a `verified` initial
    state for an answer that already carries a fence violation —
    such rows land as `boundary_warn` immediately rather than waiting
    for the weekly cron downgrade.
    """
    if not text:
        return False
    return any(p in text for p in FORBIDDEN_PHRASES)


def reject_aggregator_urls(urls: list[str]) -> list[str]:
    """Drop aggregator-banned URLs from a citation source list.

    Returns the FILTERED list. The caller decides whether to refuse the
    write or continue with a partial source list. Memory
    `feedback_autonomath_fraud_risk` requires aggregator links never
    be persisted as a citation source.
    """
    out: list[str] = []
    for u in urls or []:
        try:
            host = (urlparse(u).hostname or "").lower()
        except Exception:  # noqa: BLE001 — defensive, malformed URL
            continue
        if host in AGGREGATOR_HOSTS:
            continue
        out.append(u)
    return out


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _open_autonomath() -> sqlite3.Connection | None:
    """Open autonomath.db. Returns None if file missing — the badge
    endpoint then renders the `invalid` state rather than 500ing.
    """
    try:
        from jpintel_mcp.config import settings

        path = os.environ.get("AUTONOMATH_DB_PATH", str(settings.autonomath_db_path))
    except Exception:  # noqa: BLE001 — defensive in test env
        path = os.environ.get("AUTONOMATH_DB_PATH", "")

    if not path or not os.path.exists(path):
        return None

    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        logger.debug("autonomath.db open failed: %s", exc)
        return None


def _ttl_status(row: sqlite3.Row) -> VerifiedStatus:
    """Compute the rendered status for a row.

    If the row's ttl_days has elapsed since `created_at`, return
    `expired` regardless of the stored `verified_status` (the cron may
    not have run yet on the latest read).
    """
    stored = (row["verified_status"] or "verified").lower()
    if stored not in _VALID_STATUSES:
        return "invalid"
    try:
        ttl = int(row["ttl_days"] or 90)
    except (TypeError, ValueError):
        ttl = 90
    # Compare via SQL `julianday()` math — caller passes the raw row,
    # we recompute here with a tiny in-memory connection so this fn is
    # pure-Python testable. The `created_at` column is stored as
    # ISO 8601 in autonomath.db (datetime('now') default).
    try:
        scratch = sqlite3.connect(":memory:")
        cur = scratch.execute(
            "SELECT (julianday('now') - julianday(?)) > ?",
            (row["created_at"], ttl),
        )
        elapsed = bool(cur.fetchone()[0])
        scratch.close()
    except sqlite3.Error:
        elapsed = False
    if elapsed and stored != "invalid":
        return "expired"
    return stored  # type: ignore[return-value]


def _fetch_row(request_id: str) -> sqlite3.Row | None:
    """Return the citation_log row or None.

    Accepts either bare-hex (`uuid.uuid4().hex`) or canonical-dashed
    UUIDv4. Both shapes are normalized to the form actually in the
    table (whichever the upstream insert chose to write).
    """
    if not _UUID_RE.match(request_id.lower()):
        return None
    conn = _open_autonomath()
    if conn is None:
        return None
    try:
        # Try the literal first.
        row = conn.execute(
            "SELECT request_id, api_key_id, answer_text, source_urls, "
            "       created_at, verified_status, ttl_days "
            "FROM citation_log WHERE request_id = ?",
            (request_id.lower(),),
        ).fetchone()
        if row is not None:
            return row
        # Try the alternate shape (dashed <-> hex).
        if "-" in request_id:
            alt = request_id.replace("-", "").lower()
        else:
            rid = request_id.lower()
            alt = f"{rid[0:8]}-{rid[8:12]}-{rid[12:16]}-{rid[16:20]}-{rid[20:32]}"
        row = conn.execute(
            "SELECT request_id, api_key_id, answer_text, source_urls, "
            "       created_at, verified_status, ttl_days "
            "FROM citation_log WHERE request_id = ?",
            (alt,),
        ).fetchone()
        return row
    except sqlite3.Error as exc:
        logger.debug("citation_log fetch degraded: %s", exc)
        return None
    finally:
        with contextlib.suppress(Exception):  # noqa: BLE001
            conn.close()


# ---------------------------------------------------------------------------
# SVG generation (pure string format — no Cairo / Pillow / external)
# ---------------------------------------------------------------------------

# Color palette — kept WCAG AA contrast compliant against the badge's
# label background. The 4 states map to a green / grey / red / amber
# bar following GitHub-style shields.io conventions so the badge feels
# native on a 税理士事務所 article page.
_STATE_COLORS: dict[str, dict[str, str]] = {
    "verified": {"bg": "#3fb950", "label": "jpcite", "value": "verified ✓"},
    "expired": {"bg": "#8b949e", "label": "jpcite", "value": "expired"},
    "invalid": {"bg": "#da3633", "label": "jpcite", "value": "invalid ✕"},
    "boundary_warn": {
        "bg": "#d29922",
        "label": "jpcite",
        "value": "boundary !",
    },
}


def render_badge_svg(state: str, *, language: str = "ja") -> str:
    """Render the 120×20 badge SVG for a given state.

    `state` MUST be one of the 4 valid strings; anything else is
    coerced to `invalid` so a typo'd query string never bypasses the
    fence by falling through to the `verified` default.
    """
    s = state if state in _STATE_COLORS else "invalid"
    palette = _STATE_COLORS[s]
    title_text = DISCLAIMER_JA if language == "ja" else DISCLAIMER_EN
    # Static layout: 60px label + 60px value, total 120×20. The <title>
    # element is what most browsers render as a tooltip on hover and
    # what screen readers read aloud — the disclaimer envelope rides
    # there so APPI / 業法 fence text reaches the customer's user.
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'width="120" height="20" role="img" '
        f'aria-label="jpcite verified ({s})">'
        f"<title>{title_text}</title>"
        '<linearGradient id="g" x2="0" y2="100%">'
        '<stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
        '<stop offset="1" stop-opacity=".1"/></linearGradient>'
        '<rect rx="3" width="120" height="20" fill="#555"/>'
        f'<rect rx="3" x="60" width="60" height="20" fill="{palette["bg"]}"/>'
        '<rect rx="3" width="120" height="20" fill="url(#g)"/>'
        '<g fill="#fff" text-anchor="middle" '
        'font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">'
        f'<text x="30" y="14">{palette["label"]}</text>'
        f'<text x="90" y="14">{palette["value"]}</text>'
        "</g></svg>"
    )


# ---------------------------------------------------------------------------
# Static MD render (citation page) — no Jinja, pure f-string
# ---------------------------------------------------------------------------


def _disclaimer_block(language: str) -> str:
    if language == "en":
        return f"> {DISCLAIMER_EN}\n"
    return f"> {DISCLAIMER_JA}\n"


def _render_sources(source_urls_json: str) -> str:
    try:
        urls = json.loads(source_urls_json or "[]")
    except json.JSONDecodeError:
        urls = []
    if not isinstance(urls, list) or not urls:
        return "_(出典なし)_\n"
    out: list[str] = []
    for u in urls:
        if not isinstance(u, str):
            continue
        # Reject aggregator URLs even at render time. Defense-in-depth:
        # an aggregator that slips past the insert path STILL never
        # surfaces on the public citation page.
        try:
            host = (urlparse(u).hostname or "").lower()
        except Exception:  # noqa: BLE001
            host = ""
        if host in AGGREGATOR_HOSTS:
            out.append(f"- ~~{u}~~ _(aggregator — banned, see ban list)_")
            continue
        out.append(f"- {u}")
    return "\n".join(out) + "\n"


def render_citation_md(
    *,
    request_id: str,
    row: sqlite3.Row | None,
    language: str = "ja",
    identity_confidence: float | None = None,
    amendment_lineage: list[dict[str, Any]] | None = None,
    source_receipt: dict[str, Any] | None = None,
    audit_seal: dict[str, Any] | None = None,
) -> str:
    """Render the static MD page for `jpcite.com/citation/{request_id}`.

    `row` may be None — the static MD path then surfaces an `invalid`
    citation page that is still link-safe (no 500). The caller
    (Cloudflare Pages build hook) substitutes live `source_receipt` /
    `identity_confidence` / `amendment_lineage` / `audit_seal` blocks
    at render time; those are passed in here as plain dicts so this
    function stays pure (no DB JOIN inside).
    """
    if row is None:
        title = "jpcite citation — invalid"
        body = (
            f"# {title}\n\n"
            f"**request_id**: `{request_id}`\n\n"
            f"_(該当する citation_log row がありません。badge は invalid 状態で表示されます。)_\n\n"
            + _disclaimer_block(language)
        )
        return body

    state = _ttl_status(row)
    answer = scrub(row["answer_text"] or "")
    sources_md = _render_sources(row["source_urls"] or "[]")

    # identity_confidence (Wave 22 cross_check_jurisdiction output) — the
    # caller may pass `None` when the upstream tool did not run that
    # surface. Static template still renders the row so the schema is
    # stable across pages.
    ic_str = f"{identity_confidence:.3f}" if isinstance(identity_confidence, float) else "N/A"

    lineage_md = ""
    if amendment_lineage:
        lineage_md = "\n".join(
            f"- {entry.get('effective_from', '????-??-??')}: {entry.get('summary', '')}"
            for entry in amendment_lineage
            if isinstance(entry, dict)
        )
    else:
        lineage_md = "_(時系列改正情報は未取得)_"

    receipt_md = ""
    if source_receipt and isinstance(source_receipt, dict):
        items: list[str] = []
        for src in source_receipt.get("sources", []) or []:
            if not isinstance(src, dict):
                continue
            items.append(
                f"- url: {src.get('url', '')}  \n"
                f"  retrieved_at: {src.get('retrieved_at', '')}  \n"
                f"  content_hash: {src.get('content_hash', '')}"
            )
        receipt_md = "\n".join(items) if items else "_(receipt 未取得)_"
    else:
        receipt_md = "_(receipt 未取得)_"

    seal_md = ""
    if audit_seal and isinstance(audit_seal, dict):
        seal_md = (
            f"- call_id: `{audit_seal.get('call_id', '')}`\n"
            f"- ts: `{audit_seal.get('ts', '')}`\n"
            f"- query_hash: `{audit_seal.get('query_hash', '')}`\n"
            f"- response_hash: `{audit_seal.get('response_hash', '')}`\n"
            f"- hmac: `{audit_seal.get('hmac', '')}`"
        )
    else:
        seal_md = "_(audit_seal 未連携)_"

    title = "jpcite citation"
    return (
        f"# {title}\n\n"
        f"**request_id**: `{request_id}`  \n"
        f"**verified_status**: `{state}`  \n"
        f"**created_at**: `{row['created_at']}`  \n"
        f"**ttl_days**: {row['ttl_days']}\n\n"
        f"## 1. Original answer (scrubbed)\n\n"
        f"```\n{answer}\n```\n\n"
        f"## 2. Source receipt\n\n"
        f"{sources_md}\n"
        f"{receipt_md}\n\n"
        f"## 3. Identity confidence (Wave 22)\n\n"
        f"`identity_confidence = {ic_str}`\n\n"
        f"## 4. Amendment lineage\n\n"
        f"{lineage_md}\n\n"
        f"## 5. Audit seal (mig 089)\n\n"
        f"{seal_md}\n\n"
        f"## 6. Disclaimer envelope\n\n"
        f"{_disclaimer_block(language)}"
        f"\n## 7. Verify this citation\n\n"
        f"`POST /v1/verify/answer` (DEEP-25). "
        f"Pass `request_id` + `expected_seal` to re-validate this row.\n"
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["citation_badge"])


@router.get(
    "/widget/badge.svg",
    responses={
        200: {"content": {"image/svg+xml": {}}},
    },
)
def badge_svg(
    request_id: Annotated[
        str,
        Query(
            min_length=32,
            max_length=36,
            description="UUIDv4 request id minted by the originating call.",
        ),
    ],
    language: Annotated[
        str,
        Query(pattern=r"^(ja|en)$"),
    ] = "ja",
) -> Response:
    """SVG endpoint backing the `<img src=...>` badge.

    Always returns 200 with an SVG body — even for `invalid` /
    `expired` / unknown ids. A 404 here would break the customer
    page's image render and (worse) leak whether a given UUID is in
    the DB; returning the `invalid` SVG keeps the surface uniform
    while still telling the customer's viewer the badge is dead.
    """
    rid_norm = request_id.lower()
    if not _UUID_RE.match(rid_norm):
        svg = render_badge_svg("invalid", language=language)
        return Response(
            content=svg,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=300"},
        )

    row = _fetch_row(rid_norm)
    if row is None:
        svg = render_badge_svg("invalid", language=language)
        return Response(
            content=svg,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=300"},
        )

    state = _ttl_status(row)
    svg = render_badge_svg(state, language=language)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/citation/{request_id}", response_class=Response)
def citation_page(
    request_id: Annotated[
        str,
        FPath(
            min_length=32,
            max_length=36,
            description="UUIDv4 request id minted by the originating call.",
        ),
    ],
    language: Annotated[
        str,
        Query(pattern=r"^(ja|en)$"),
    ] = "ja",
) -> Response:
    """Markdown citation page backing `jpcite.com/citation/{REQUEST_ID}`.

    Returns 200 with `text/markdown; charset=utf-8` regardless of
    whether the row exists — the body for an unknown id surfaces the
    `invalid` block, link-safe by construction.

    Raises 422 from the path validator only when the path segment
    cannot be a UUIDv4 at all (length / character class). This route
    deliberately does not 404 on missing rows so a customer-page that
    publishes a bad badge id still resolves to a non-broken link.
    """
    if not _UUID_RE.match(request_id.lower()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_request_id",
                "developer_message": "request_id must be a UUIDv4 (32-hex or canonical 8-4-4-4-12).",
            },
        )

    row = _fetch_row(request_id)
    md = render_citation_md(
        request_id=request_id,
        row=row,
        language=language,
    )
    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ---------------------------------------------------------------------------
# Helper for the originating tool's `_disclaimer.cite_html_snippet`
# ---------------------------------------------------------------------------


def cite_html_snippet(request_id: str) -> str:
    """Return the 1-line HTML the customer pastes into their article.

    The originating MCP tool's response envelope embeds this string
    under `_disclaimer.cite_html_snippet` so the 税理士 / consultant
    can copy verbatim without leaving the editor. Pure formatter — no
    DB call.
    """
    rid = request_id.lower().replace("-", "")
    return (
        f'<a href="https://jpcite.com/citation/{rid}" '
        'data-jpcite-verified="true">'
        f'<img src="https://widget.jpcite.com/badge.svg?request_id={rid}" '
        'alt="jpcite verified" width="120" height="20" />'
        "</a>"
    )


def mint_request_id() -> str:
    """Return a fresh UUIDv4 hex (32 chars, no dashes).

    Used by the originating tool path to produce the canonical id that
    flows into `citation_log.request_id` + the badge URL + the static
    MD page. Not exported in the router but importable from
    `verify.py` / future Wave-25 wiring.
    """
    return uuid.uuid4().hex
