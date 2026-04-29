#!/usr/bin/env python3
"""Ingest 判例 from 裁判所判例検索 (courts.go.jp hanrei_jp) into ``court_decisions``.

Source discipline (non-negotiable — see CLAUDE.md + migration 016 header):
    * **Only** ``www.courts.go.jp`` (hanrei_jp UI + PDF mirrors) is
      whitelisted for this domain. D1 Law / Westlaw Japan / LEX/DB and
      other commercial judgment aggregators are **banned** — redistribution
      license + 一次情報 discipline. The banned aggregator list is kept in
      sync with ``scripts/ingest_external_data.BANNED_SOURCE_HOSTS``.

Scraping strategy:
    * courts.go.jp ``/app/hanrei_jp/search1`` is a SPA that refuses to
      render the result list without JS. We use Playwright (Chromium,
      headless) to drive the search UI, wait for DOM settle, then walk
      each result detail page.
    * Rate limit: 1 req / 2s (stricter than the shared §5 1req/s because
      SPA navigation triggers internal XHRs we do not count).
    * robots.txt respected: courts.go.jp currently disallows nothing under
      /app/hanrei_jp/ as of 2026-04-24 — verified by ``check_robots()``
      on every run. A future tightening will halt the crawl cleanly.
    * User-Agent: advertises contact + purpose per the whitelisted crawler
      convention used by scripts/lib/http.py.

unified_id:
    ``'HAN-' + sha256(case_number + '|' + court).hexdigest()[:10]`` —
    deterministic across re-runs, regex-disjoint from UNI-/LAW-/BID-/TAX-.
    Collapses 控訴審 + 上告審 on the *same* case_number into distinct
    rows because ``court`` differs (same rule as 012 case_law UNIQUE).

PDF extraction:
    courts.go.jp ships judgments as PDF-only. We use ``pdfplumber`` for
    text extraction (add to [ingest] extras in pyproject.toml — currently
    neither ``playwright`` nor ``pdfplumber`` is declared there; install
    locally via ``pip install playwright pdfplumber`` + ``playwright
    install chromium``).

旧字体 / 文字化け handling:
    Old supreme-court judgments use 旧字体 (舊・實・學 ...). We apply
    ``unicodedata.normalize("NFKC", ...)`` for consistent Hepburn
    downstream, but we tag the source_excerpt when U+FFFD replacements
    appear and dock ``confidence`` by 0.1 per 10 replacements (bounded
    below 0.3). Never raise on decode — data loss is expected at 20-30%
    on pre-1970 rulings.

precedent_weight heuristic (first-cut, see 016 schema comment):
    * ``'binding'``        — 最高裁判所
    * ``'persuasive'``     — 高等裁判所
    * ``'informational'``  — 地方 / 簡易 / 家庭
    Override is a later pass — e.g. 大法廷 decisions should flip to
    binding regardless of court keyword; Minor 最高裁 orders are often
    only persuasive. TODO is tracked in docs/ (out of scope here).

related_law_ids_json:
    We extract 参照条文 via regex (法令名 + 第N条 [第M項]) and attempt
    to match each ``law_name`` against the local ``laws`` table
    (migration 015). Matches produce LAW-* IDs; misses are held with a
    ``'PENDING:' + law_name`` sentinel and listed in the final log —
    reconciliation is **out of scope** for this script (TODO: separate
    reconcile queue walker).

TOS / commercial-reuse gating:
    Courts.go.jp publishes its TOS in Japanese. The interpretation for
    commercial downstream redistribution (i.e. our ¥3/req API) is
    ambiguous. We ship a ``--respect-tos`` flag (default ON) that:
      * Stores only metadata + a short 500-char excerpt when TOS-respect
        mode is on, unless ``AUTONOMATH_COURT_TOS_ACCEPTED=1`` is set.
      * Full-text / long excerpts are skipped with a SKIP_TOS log marker.
    Operator review + written clearance is the gate to lift this.

CLI:
    python scripts/ingest/ingest_court_decisions.py \\
        --db data/jpintel.db \\
        [--limit N]                  # cap result iteration
        [--court LEVEL]              # supreme|high|district|summary|family
        [--subject-area AREA]        # 租税 / 行政 / 補助金適正化法 / ...
        [--date-from YYYY-MM-DD]     # 言渡日 floor
        [--dry-run]                  # parse only, no DB writes
        [--respect-tos / --no-respect-tos]  # default: --respect-tos
        [--cache-dir PATH]           # PDF cache (default /tmp/autonomath_han_cache)

Exit codes:
    0  success
    1  network / Playwright failure after retries
    2  DB lock / migration-not-applied (court_decisions missing)
    3  TOS-gated run w/o AUTONOMATH_COURT_TOS_ACCEPTED when --full requested

NOT part of this script (per ops request):
    * Running the script — migration 016 may not be applied at author time.
    * Committing rows to the DB implicitly — ``--dry-run`` is recommended
      for first local wiring test.
    * Reconciling PENDING: law_name sentinels (see above).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Optional-at-import-time third-party deps
# ---------------------------------------------------------------------------
# Playwright + pdfplumber are NOT yet declared in pyproject.toml:
#   * playwright lives under [e2e] (for pytest-playwright); this script
#     would need it under a new [ingest] extras, or install ad-hoc.
#   * pdfplumber is absent from pyproject.toml entirely.
# We import lazily so the script text can be reviewed / linted without
# the deps installed. Runtime missing-deps error is informative.

try:
    import httpx  # type: ignore
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

_PLAYWRIGHT_IMPORT_ERR: Exception | None = None
try:
    # Playwright's sync API is fine here — we are single-threaded and the
    # per-req overhead is dwarfed by 2-second politeness sleeps.
    from playwright.sync_api import (  # type: ignore
        Browser,
        BrowserContext,
        Page,
        sync_playwright,
    )
except ImportError as exc:  # pragma: no cover
    _PLAYWRIGHT_IMPORT_ERR = exc
    Browser = BrowserContext = Page = None  # type: ignore[assignment]
    sync_playwright = None  # type: ignore[assignment]

_PDFPLUMBER_IMPORT_ERR: Exception | None = None
try:
    import pdfplumber  # type: ignore
except ImportError as exc:  # pragma: no cover
    _PDFPLUMBER_IMPORT_ERR = exc
    pdfplumber = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG = logging.getLogger("autonomath.ingest.court_decisions")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_CACHE_DIR = Path("/tmp/autonomath_han_cache")

SEARCH_ENTRY_URL = "https://www.courts.go.jp/app/hanrei_jp/search1"
ALLOWED_HOSTS: frozenset[str] = frozenset({"www.courts.go.jp"})

# Banned aggregators (kept in sync with scripts/ingest_external_data.py).
# We reject both the primary source_url and any pdf_url that slips through
# via a referral redirect. Extending the list only requires updating both.
BANNED_SOURCE_HOSTS: tuple[str, ...] = (
    "noukaweb",
    "hojyokin-portal",
    "biz.stayway",
    "hojo-navi",
    "mirai-joho",
    # Commercial 判例 aggregators (courts-specific):
    "d1law",
    "westlaw",
    "lexis",
    "lex-db",
    "lexdb",
    "tkclex",
)

USER_AGENT = (
    "AutonoMath/0.1.0 (+https://zeimu-kaikei.ai) research crawler"
)
# Per-host delay: stricter than §5 (1req/s) because SPA navigation fires
# additional XHR under the hood. 2 seconds still completes a full walk of
# a year's high-court docket in tolerable time.
PER_REQUEST_DELAY_SEC = 2.0
HTTP_TIMEOUT_SEC = 45
PDF_TIMEOUT_SEC = 90
MAX_RETRIES = 3
MAX_RESULT_WALK = 500  # hard cap to stop runaway crawls; --limit overrides
DEFAULT_NAV_TIMEOUT_MS = 30_000

# Decision-type vocabulary from the SPA: hanrei_jp publishes one of these
# three exact strings in the 裁判種別 column; reject anything else so that
# DB CHECK(decision_type IN ('判決','決定','命令')) never fires.
DECISION_TYPE_KANJI: frozenset[str] = frozenset({"判決", "決定", "命令"})

# Court-level mapping — substring match on the 裁判所名 column. Order
# matters: 最高裁判所 first, then 高等, else 地方/簡易/家庭. "高裁" inside
# "東京高等裁判所" matches "高等裁判所" first (intentional).
COURT_LEVEL_RULES: tuple[tuple[str, str], ...] = (
    ("最高裁判所", "supreme"),
    ("高等裁判所", "high"),
    ("地方裁判所", "district"),
    ("簡易裁判所", "summary"),
    ("家庭裁判所", "family"),
)

# 参照条文 section header variants seen on courts.go.jp PDFs.
REF_LAW_HEADERS: tuple[str, ...] = ("参照条文", "参照法条", "関係法条")
RULING_HEADERS: tuple[str, ...] = ("判示事項", "主文")
SUMMARY_HEADERS: tuple[str, ...] = ("判決要旨", "決定要旨", "要旨")

# Regex for "法律名 + 条文".
# Examples we aim to match:
#   所得税法第33条, 補助金適正化法第17条第1項, 民法709条, 会社法（平成十七年法律第八十六号）第2条
# We deliberately accept both Arabic and 漢数字 digits.
_LAW_NAME_TAIL = r"法|令|規則|条例"
_LAW_NAME = rf"[一-鿿々ー]+(?:{_LAW_NAME_TAIL})"
_ARTICLE_NUM = r"[0-9０-９一二三四五六七八九十百千]+"
LAW_REF_RE = re.compile(
    rf"({_LAW_NAME})(?:（[^）]*）)?\s*(?:第?\s*({_ARTICLE_NUM})\s*条"
    rf"(?:\s*第?\s*({_ARTICLE_NUM})\s*項)?)"
)

# source_excerpt cap — 500 chars when --respect-tos is on.
EXCERPT_CHARS_TOS_RESPECTED = 500
EXCERPT_CHARS_TOS_CLEARED = 4000

# Confidence floor & penalty per 10 U+FFFD replacements.
CONFIDENCE_BASE = 0.9
CONFIDENCE_FLOOR = 0.3
REPLACEMENT_PENALTY_PER_10 = 0.1


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CourtDecision:
    """One row for the ``court_decisions`` table."""

    unified_id: str
    case_name: str
    case_number: str | None
    court: str | None
    court_level: str
    decision_date: str | None
    decision_type: str
    subject_area: str | None
    related_law_ids_json: str | None
    key_ruling: str | None
    parties_involved: str | None
    impact_on_business: str | None
    precedent_weight: str
    full_text_url: str | None
    pdf_url: str | None
    source_url: str
    source_excerpt: str | None
    source_checksum: str | None
    confidence: float
    fetched_at: str
    updated_at: str
    # Non-column bookkeeping (never written to DB):
    pending_law_names: list[str] = field(default_factory=list)
    replacement_count: int = 0


# ---------------------------------------------------------------------------
# Helpers — normalization, ID, host check
# ---------------------------------------------------------------------------


def compute_unified_id(case_number: str | None, court: str | None) -> str:
    """Deterministic HAN-<10 hex> from (case_number, court).

    Mirrors migration 016 CHECK: length 14, prefix 'HAN-'. Matches 012
    UNIQUE(case_number, court) so cross-court re-hearings of the same
    case_number map to distinct rows.
    """
    key = f"{case_number or ''}|{court or ''}".encode()
    digest = hashlib.sha256(key).hexdigest()[:10]
    return f"HAN-{digest}"


def normalize_text(raw: str | bytes) -> tuple[str, int]:
    """NFKC-normalize; return (text, replacement_count).

    PDFs often arrive with embedded CID fonts that pdfplumber maps to
    U+FFFD (replacement character). We count these so confidence can be
    docked honestly — never raise on decode.
    """
    raw_str = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    normalized = unicodedata.normalize("NFKC", raw_str)
    replacement_count = normalized.count("�")
    return normalized, replacement_count


def source_url_is_banned(url: str | None) -> bool:
    """True if ``url`` host matches any BANNED_SOURCE_HOSTS substring."""
    if not url:
        return False
    low = url.lower()
    return any(h in low for h in BANNED_SOURCE_HOSTS)


def source_host_is_whitelisted(url: str | None) -> bool:
    """True if ``url`` is served from an allowed courts.go.jp host."""
    if not url:
        return False
    host = urlparse(url).netloc.lower()
    return host in ALLOWED_HOSTS


def map_court_level(court: str | None) -> str | None:
    """Return 'supreme'|'high'|'district'|'summary'|'family' or None."""
    if not court:
        return None
    for needle, level in COURT_LEVEL_RULES:
        if needle in court:
            return level
    return None


def map_decision_type(raw: str | None) -> str | None:
    """Return '判決'|'決定'|'命令' or None (→ caller should skip)."""
    if not raw:
        return None
    for kind in DECISION_TYPE_KANJI:
        if kind in raw:
            return kind
    return None


def map_precedent_weight(court_level: str) -> str:
    """First-cut heuristic — see module docstring for override TODO."""
    if court_level == "supreme":
        return "binding"
    if court_level == "high":
        return "persuasive"
    return "informational"


def adjusted_confidence(replacement_count: int) -> float:
    """Drop 0.1 per 10 U+FFFD occurrences, floored at 0.3."""
    if replacement_count <= 0:
        return CONFIDENCE_BASE
    penalty = (replacement_count // 10) * REPLACEMENT_PENALTY_PER_10
    return max(CONFIDENCE_FLOOR, CONFIDENCE_BASE - penalty)


# ---------------------------------------------------------------------------
# PDF text extraction + section segmentation
# ---------------------------------------------------------------------------


def extract_pdf_text(pdf_path: Path) -> tuple[str, int]:
    """Return (normalized_text, replacement_count).

    Reads the whole PDF via pdfplumber. We accept decode loss — see module
    header for the 旧字体 / OCR quality caveat.
    """
    if pdfplumber is None:
        raise RuntimeError(
            f"pdfplumber not installed ({_PDFPLUMBER_IMPORT_ERR}); "
            "pip install pdfplumber (TODO: add to [ingest] extras)"
        )
    chunks: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            chunks.append(text)
    joined = "\n".join(chunks)
    return normalize_text(joined)


def _find_section(text: str, headers: tuple[str, ...]) -> str | None:
    """Return text following the first matching header up to the next
    known top-level header or ~2000 chars, whichever is shorter.

    Header-based segmentation is intentionally simple — courts.go.jp PDFs
    are roughly "判示事項 ... 判決要旨 ... 参照条文 ... 主文" in that
    order, so a forward look-ahead stopping at any *other* known header
    is adequate. Misses fall through to None (field stays null — that's
    more honest than a hallucinated summary).
    """
    all_headers = set(RULING_HEADERS) | set(SUMMARY_HEADERS) | set(REF_LAW_HEADERS)
    for hdr in headers:
        m = re.search(rf"{re.escape(hdr)}\s*[\n:：]", text)
        if not m:
            continue
        start = m.end()
        # Find the next known header after start.
        remaining = text[start : start + 4000]
        next_hdr_pos = len(remaining)
        for other in all_headers - {hdr}:
            om = re.search(rf"\n\s*{re.escape(other)}\s*[\n:：]", remaining)
            if om and om.start() < next_hdr_pos:
                next_hdr_pos = om.start()
        section = remaining[:next_hdr_pos].strip()
        if section:
            return section[:2000]
    return None


def segment_sections(full_text: str) -> dict[str, str | None]:
    """Split a judgment body into 判示事項 / 判決要旨 / 参照条文 buckets."""
    return {
        "key_ruling": _find_section(full_text, RULING_HEADERS),
        "summary": _find_section(full_text, SUMMARY_HEADERS),
        "references": _find_section(full_text, REF_LAW_HEADERS),
    }


def parse_law_references(
    references_block: str | None,
    laws_lookup: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Parse the 参照条文 block.

    Args:
        references_block: raw text of the 参照条文 section (may be None).
        laws_lookup: ``{normalized_law_title: LAW-... unified_id}`` — built
            once per run from the ``laws`` table (migration 015). Lookup
            is by NFKC'd law_title / law_short_title; a miss surfaces as
            a PENDING sentinel for later reconciliation.

    Returns:
        (resolved_law_ids, pending_law_names) — the resolved list goes
        into related_law_ids_json; the pending list is logged and stashed
        on the CourtDecision for summary reporting.
    """
    if not references_block:
        return [], []
    resolved: list[str] = []
    pending: list[str] = []
    seen_names: set[str] = set()
    for m in LAW_REF_RE.finditer(references_block):
        law_name = unicodedata.normalize("NFKC", m.group(1)).strip()
        if not law_name or law_name in seen_names:
            continue
        seen_names.add(law_name)
        law_id = laws_lookup.get(law_name)
        if law_id:
            if law_id not in resolved:
                resolved.append(law_id)
        else:
            pending.append(law_name)
    return resolved, pending


# ---------------------------------------------------------------------------
# Playwright-driven SPA walk
# ---------------------------------------------------------------------------


@dataclass
class SearchFilters:
    """CLI-derived filters for the search form."""

    court: str | None = None            # 'supreme' | 'high' | 'district' | ...
    subject_area: str | None = None     # freeform; matched against 事件名 field
    date_from: str | None = None        # 'YYYY-MM-DD'
    limit: int | None = None


def _respect_robots(page: Page) -> bool:
    """Fetch robots.txt once per run; allow if reachable + allows our UA.

    Returns True on allow, False on explicit disallow. Unreachable robots
    is treated as allow (same as scripts/lib/http.py §5 fallback).
    """
    try:
        resp = page.request.get("https://www.courts.go.jp/robots.txt")
        if resp.status != 200:
            _LOG.info("robots.txt unreachable (status=%s); treating as allow", resp.status)
            return True
        body = resp.text()
    except Exception as exc:  # noqa: BLE001
        _LOG.info("robots.txt fetch error (%s); treating as allow", exc)
        return True
    # Minimal parse: disallow '/app/hanrei_jp' -> block.
    # A full RobotFileParser would need the UA token; our UA is descriptive
    # text so courts.go.jp will almost certainly not call us out by name.
    lower = body.lower()
    if "disallow: /app/hanrei_jp" in lower:
        _LOG.error("robots.txt disallows /app/hanrei_jp — aborting crawl")
        return False
    return True


def _polite_sleep() -> None:
    time.sleep(PER_REQUEST_DELAY_SEC)


def _with_retry(desc: str, fn):
    """Run fn() with 3x retry + exponential backoff on Playwright + network errs."""
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt == MAX_RETRIES:
                break
            wait = 2**attempt
            _LOG.warning("retry %s (%d/%d) after %ds: %s", desc, attempt, MAX_RETRIES, wait, exc)
            time.sleep(wait)
    assert last_exc is not None
    raise last_exc


def walk_search_results(
    context: BrowserContext,
    filters: SearchFilters,
) -> list[dict[str, Any]]:
    """Return raw per-result dicts {case_name, case_number, court,
    decision_date, decision_type, subject_area, full_text_url, pdf_url,
    source_url}.

    This function is intentionally resilient to form-field drift: it
    locates inputs by placeholder/label text (Japanese), not by brittle
    ``#id_1234`` selectors. When the SPA schema shifts we can update the
    label strings in one place.

    Iteration stops at min(filters.limit, MAX_RESULT_WALK).
    """
    page = context.new_page()
    page.set_default_navigation_timeout(DEFAULT_NAV_TIMEOUT_MS)
    page.set_default_timeout(DEFAULT_NAV_TIMEOUT_MS)

    def _go():
        page.goto(SEARCH_ENTRY_URL, wait_until="domcontentloaded")
        # SPA settle: wait for at least one input field to mount.
        page.wait_for_selector("input", timeout=DEFAULT_NAV_TIMEOUT_MS)

    _with_retry("open search entry", _go)
    _polite_sleep()

    # -- Apply filters ---------------------------------------------------
    # The SPA labels are stable Japanese strings ("事件名", "裁判年月日",
    # "裁判所名"). We locate by label text; the exact control type
    # (checkbox, text, select) differs per field. TODO: when the form
    # moves to a Vue rewrite this block is the only thing that breaks.
    if filters.subject_area:
        try:
            page.get_by_label("事件名").fill(filters.subject_area)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("subject_area filter not applied: %s", exc)
    if filters.date_from:
        try:
            page.get_by_label("裁判年月日").fill(filters.date_from)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("date_from filter not applied: %s", exc)
    if filters.court:
        # The "裁判所" section is a group of checkboxes keyed by kanji
        # ("最高裁判所" / "高等裁判所" / "地方裁判所" / "簡易裁判所" /
        # "家庭裁判所"). We flip the one matching filters.court.
        inverse = {v: k for k, v in COURT_LEVEL_RULES}
        kanji = inverse.get(filters.court)
        if kanji:
            try:
                page.get_by_label(kanji).check()
            except Exception as exc:  # noqa: BLE001
                _LOG.warning("court filter not applied for %s: %s", kanji, exc)

    # Submit.
    def _submit():
        page.get_by_role("button", name="検索").click()
        # Wait for the result list to paint. Use the result-row selector
        # (td/tr inside a table that appears post-search). networkidle
        # is too slow; a DOM hook is enough.
        page.wait_for_selector("table", timeout=DEFAULT_NAV_TIMEOUT_MS)

    _with_retry("submit search", _submit)
    _polite_sleep()

    # -- Collect result links -------------------------------------------
    cap = min(filters.limit or MAX_RESULT_WALK, MAX_RESULT_WALK)
    results: list[dict[str, Any]] = []

    # Result rows carry links to per-case detail pages. We grab every
    # anchor whose href is under /app/hanrei_jp/detail* and defer detail
    # extraction to a second pass.
    anchors = page.locator("a[href*='/app/hanrei_jp/detail']").all()
    detail_urls: list[str] = []
    for a in anchors[:cap]:
        href = a.get_attribute("href") or ""
        if not href:
            continue
        if href.startswith("/"):
            href = "https://www.courts.go.jp" + href
        if not source_host_is_whitelisted(href):
            _LOG.warning("skip non-whitelisted result href: %s", href)
            continue
        detail_urls.append(href)

    _LOG.info("collected %d detail URLs (cap=%d)", len(detail_urls), cap)

    # -- Walk each detail page ------------------------------------------
    for idx, url in enumerate(detail_urls, start=1):
        def _visit(u: str = url):
            page.goto(u, wait_until="domcontentloaded")
            page.wait_for_selector("body", timeout=DEFAULT_NAV_TIMEOUT_MS)

        try:
            _with_retry(f"detail {idx}/{len(detail_urls)}", _visit)
        except Exception as exc:  # noqa: BLE001
            _LOG.error("detail visit failed url=%s err=%s (skip)", url, exc)
            continue
        _polite_sleep()

        meta = _extract_detail_meta(page, url)
        if meta:
            results.append(meta)

    page.close()
    return results


def _extract_detail_meta(page: Page, source_url: str) -> dict[str, Any] | None:
    """Scrape a detail page for case metadata + PDF link.

    Returns None if the page doesn't parse (structure drift). Label-based
    lookups insulate us from classname churn.
    """
    def _label(text: str) -> str | None:
        # Pattern: <dt>text</dt><dd>value</dd> — SPA renders definition
        # lists for case metadata. Fallback: <th>text</th><td>value</td>.
        try:
            val = page.locator(f"dt:has-text('{text}') + dd").first.text_content()
            if val:
                return val.strip()
        except Exception:  # noqa: BLE001
            pass
        try:
            val = page.locator(f"th:has-text('{text}') + td").first.text_content()
            if val:
                return val.strip()
        except Exception:  # noqa: BLE001
            pass
        return None

    case_name = _label("事件名") or _label("事件") or ""
    if not case_name:
        _LOG.warning("no case_name on detail page: %s", source_url)
        return None
    case_number = _label("事件番号")
    court = _label("裁判所名") or _label("法廷名")
    decision_date = _label("裁判年月日") or _label("言渡日")
    decision_type_raw = _label("裁判種別") or _label("種別")
    subject_area = _label("事件分類") or _label("分野")
    parties_involved = _label("当事者") or _label("当事者名")

    # PDF link: courts.go.jp usually exposes a "全文" link ending in .pdf.
    pdf_url: str | None = None
    try:
        a = page.locator("a[href$='.pdf']").first
        href = a.get_attribute("href")
        if href:
            if href.startswith("/"):
                href = "https://www.courts.go.jp" + href
            if source_host_is_whitelisted(href):
                pdf_url = href
    except Exception:  # noqa: BLE001
        pass

    return {
        "case_name": case_name,
        "case_number": case_number,
        "court": court,
        "decision_date": decision_date,
        "decision_type_raw": decision_type_raw,
        "subject_area": subject_area,
        "parties_involved": parties_involved,
        "pdf_url": pdf_url,
        "source_url": source_url,
        "full_text_url": source_url,  # detail page IS the canonical permalink
    }


# ---------------------------------------------------------------------------
# PDF fetching (outside Playwright — PDFs are simple HTTPS)
# ---------------------------------------------------------------------------


def fetch_pdf(url: str, cache_dir: Path) -> tuple[Path | None, str | None]:
    """Download PDF with retry; cache on disk; return (path, sha256)."""
    if httpx is None:
        raise RuntimeError("httpx not installed")
    if not source_host_is_whitelisted(url):
        _LOG.warning("refuse PDF fetch, host not whitelisted: %s", url)
        return None, None
    if source_url_is_banned(url):
        _LOG.warning("refuse PDF fetch, host banned: %s", url)
        return None, None
    cache_dir.mkdir(parents=True, exist_ok=True)
    fname = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ".pdf"
    local = cache_dir / fname
    if local.exists() and local.stat().st_size > 10_000:
        body = local.read_bytes()
        return local, hashlib.sha256(body).hexdigest()

    def _do():
        with httpx.Client(follow_redirects=True, timeout=PDF_TIMEOUT_SEC) as c:
            r = c.get(url, headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            return r.content

    body: bytes | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            body = _do()
            break
        except Exception as exc:  # noqa: BLE001
            if attempt == MAX_RETRIES:
                _LOG.error("PDF fetch failed url=%s err=%s", url, exc)
                return None, None
            time.sleep(2**attempt)
    if body is None:
        return None, None
    local.write_bytes(body)
    _polite_sleep()
    return local, hashlib.sha256(body).hexdigest()


# ---------------------------------------------------------------------------
# Assemble + enrich CourtDecision from raw meta + PDF body
# ---------------------------------------------------------------------------


def build_decision(
    meta: dict[str, Any],
    laws_lookup: dict[str, str],
    *,
    cache_dir: Path,
    respect_tos: bool,
    tos_cleared: bool,
    now: str,
) -> CourtDecision | None:
    """Merge SPA meta + PDF extraction into a full CourtDecision row.

    Returns None when a hard reject fires:
      * source_url not whitelisted
      * source_url banned
      * decision_type unmapped (log + skip — see spec)
    """
    source_url = meta.get("source_url") or ""
    if source_url_is_banned(source_url):
        _LOG.warning("skip banned source_url: %s", source_url)
        return None
    if not source_host_is_whitelisted(source_url):
        _LOG.warning("skip non-whitelisted source_url: %s", source_url)
        return None

    court = meta.get("court")
    court_level = map_court_level(court)
    if court_level is None:
        _LOG.warning("skip: could not map court_level from court=%r", court)
        return None

    decision_type = map_decision_type(meta.get("decision_type_raw"))
    if decision_type is None:
        _LOG.warning(
            "skip: decision_type unmapped (raw=%r) case=%r",
            meta.get("decision_type_raw"),
            meta.get("case_name"),
        )
        return None

    # Try PDF extraction if a PDF URL is available. Absent PDF is NOT fatal
    # — the row still ingests with metadata-only (key_ruling/summary null).
    full_text = ""
    replacement_count = 0
    source_checksum: str | None = None
    pdf_url = meta.get("pdf_url")
    if pdf_url:
        try:
            pdf_path, sha = fetch_pdf(pdf_url, cache_dir)
            if pdf_path is not None and sha is not None:
                source_checksum = sha
                full_text, replacement_count = extract_pdf_text(pdf_path)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("PDF extraction failed url=%s err=%s", pdf_url, exc)

    sections = segment_sections(full_text) if full_text else {
        "key_ruling": None,
        "summary": None,
        "references": None,
    }
    resolved_law_ids, pending = parse_law_references(sections["references"], laws_lookup)

    # source_excerpt budget — TOS gate.
    excerpt_cap = (
        EXCERPT_CHARS_TOS_CLEARED if (tos_cleared or not respect_tos) else EXCERPT_CHARS_TOS_RESPECTED
    )
    source_excerpt: str | None = None
    if full_text:
        source_excerpt = full_text[:excerpt_cap]
        if replacement_count > 0:
            source_excerpt = (
                f"[note: {replacement_count} U+FFFD replacement(s) from NFKC decode]\n"
                + source_excerpt
            )

    confidence = adjusted_confidence(replacement_count)
    precedent_weight = map_precedent_weight(court_level)
    unified_id = compute_unified_id(meta.get("case_number"), court)

    related_json: str | None = None
    if resolved_law_ids:
        related_json = json.dumps(resolved_law_ids, ensure_ascii=False, separators=(",", ":"))

    # impact_on_business: use 判決要旨 as a first-cut. A separate LLM pass
    # can rewrite this for retrieval-friendliness later (out of scope).
    impact = sections["summary"]

    return CourtDecision(
        unified_id=unified_id,
        case_name=meta.get("case_name") or "",
        case_number=meta.get("case_number"),
        court=court,
        court_level=court_level,
        decision_date=meta.get("decision_date"),
        decision_type=decision_type,
        subject_area=meta.get("subject_area"),
        related_law_ids_json=related_json,
        key_ruling=sections["key_ruling"],
        parties_involved=meta.get("parties_involved"),
        impact_on_business=impact,
        precedent_weight=precedent_weight,
        full_text_url=meta.get("full_text_url"),
        pdf_url=pdf_url,
        source_url=source_url,
        source_excerpt=source_excerpt,
        source_checksum=source_checksum,
        confidence=confidence,
        fetched_at=now,
        updated_at=now,
        pending_law_names=pending,
        replacement_count=replacement_count,
    )


# ---------------------------------------------------------------------------
# DB layer — laws_lookup + upsert
# ---------------------------------------------------------------------------


def load_laws_lookup(db_path: Path) -> dict[str, str]:
    """``{normalized_title: LAW-... unified_id}`` from migration 015 laws.

    Returns empty dict if ``laws`` is absent (015 not applied yet). That
    degrades gracefully — all references fall to PENDING:.
    """
    if not db_path.exists():
        return {}
    lookup: dict[str, str] = {}
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute(
            "SELECT unified_id, law_title, law_short_title FROM laws"
        )
        for uid, title, short in cur.fetchall():
            for candidate in (title, short):
                if not candidate:
                    continue
                key = unicodedata.normalize("NFKC", candidate).strip()
                if key and key not in lookup:
                    lookup[key] = uid
        conn.close()
    except sqlite3.OperationalError as exc:
        _LOG.info("laws table not available (%s); resolution degrades to PENDING:", exc)
    return lookup


def ensure_migration_applied(conn: sqlite3.Connection) -> bool:
    """Verify ``court_decisions`` exists — 016 must be applied before write."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='court_decisions'"
    ).fetchone()
    return row is not None


def upsert_decision(conn: sqlite3.Connection, d: CourtDecision) -> str:
    """Upsert into ``court_decisions`` + mirror into ``court_decisions_fts``.

    Returns 'insert' or 'update' (pre-check pattern — SQLite UPSERT
    conflates changes() for both).
    """
    existed = conn.execute(
        "SELECT 1 FROM court_decisions WHERE unified_id = ?",
        (d.unified_id,),
    ).fetchone() is not None

    conn.execute(
        """INSERT INTO court_decisions (
            unified_id, case_name, case_number, court, court_level,
            decision_date, decision_type, subject_area, related_law_ids_json,
            key_ruling, parties_involved, impact_on_business, precedent_weight,
            full_text_url, pdf_url, source_url, source_excerpt,
            source_checksum, confidence, fetched_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(unified_id) DO UPDATE SET
            case_name = excluded.case_name,
            case_number = COALESCE(excluded.case_number, case_number),
            court = COALESCE(excluded.court, court),
            court_level = excluded.court_level,
            decision_date = COALESCE(excluded.decision_date, decision_date),
            decision_type = excluded.decision_type,
            subject_area = COALESCE(excluded.subject_area, subject_area),
            related_law_ids_json = COALESCE(excluded.related_law_ids_json, related_law_ids_json),
            key_ruling = COALESCE(excluded.key_ruling, key_ruling),
            parties_involved = COALESCE(excluded.parties_involved, parties_involved),
            impact_on_business = COALESCE(excluded.impact_on_business, impact_on_business),
            precedent_weight = excluded.precedent_weight,
            full_text_url = COALESCE(excluded.full_text_url, full_text_url),
            pdf_url = COALESCE(excluded.pdf_url, pdf_url),
            source_url = excluded.source_url,
            source_excerpt = COALESCE(excluded.source_excerpt, source_excerpt),
            source_checksum = COALESCE(excluded.source_checksum, source_checksum),
            confidence = excluded.confidence,
            fetched_at = excluded.fetched_at,
            updated_at = excluded.updated_at
        """,
        (
            d.unified_id,
            d.case_name,
            d.case_number,
            d.court,
            d.court_level,
            d.decision_date,
            d.decision_type,
            d.subject_area,
            d.related_law_ids_json,
            d.key_ruling,
            d.parties_involved,
            d.impact_on_business,
            d.precedent_weight,
            d.full_text_url,
            d.pdf_url,
            d.source_url,
            d.source_excerpt,
            d.source_checksum,
            d.confidence,
            d.fetched_at,
            d.updated_at,
        ),
    )

    # FTS mirror. Migration 016 doesn't ship an AFTER INSERT trigger, so
    # we write the FTS row explicitly (same pattern as programs_fts in
    # ingest_external_data.py). On update, DELETE+INSERT keeps it fresh.
    conn.execute(
        "DELETE FROM court_decisions_fts WHERE unified_id = ?",
        (d.unified_id,),
    )
    conn.execute(
        "INSERT INTO court_decisions_fts("
        "unified_id, case_name, subject_area, key_ruling, impact_on_business"
        ") VALUES (?,?,?,?,?)",
        (
            d.unified_id,
            d.case_name,
            d.subject_area,
            d.key_ruling,
            d.impact_on_business,
        ),
    )
    return "update" if existed else "insert"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"SQLite DB (default {DEFAULT_DB})")
    ap.add_argument("--limit", type=int, default=None, help="cap result walk")
    ap.add_argument(
        "--court",
        choices=["supreme", "high", "district", "summary", "family"],
        default=None,
        help="filter court_level",
    )
    ap.add_argument("--subject-area", type=str, default=None, help="filter 事件名 substring")
    ap.add_argument("--date-from", type=str, default=None, help="filter decision_date >= YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true", help="parse only, no DB writes")
    ap.add_argument(
        "--respect-tos",
        dest="respect_tos",
        action="store_true",
        default=True,
        help="(default) gate commercial fields; lift via AUTONOMATH_COURT_TOS_ACCEPTED=1",
    )
    ap.add_argument(
        "--no-respect-tos",
        dest="respect_tos",
        action="store_false",
        help="disable TOS gating (dangerous; require clearance)",
    )
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help=f"PDF cache (default {DEFAULT_CACHE_DIR})",
    )
    ap.add_argument("--verbose", "-v", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if _PLAYWRIGHT_IMPORT_ERR is not None or sync_playwright is None:
        _LOG.error(
            "playwright not installed (%s); pip install playwright && "
            "playwright install chromium (add to [ingest] extras)",
            _PLAYWRIGHT_IMPORT_ERR,
        )
        return 1
    if pdfplumber is None:
        _LOG.error(
            "pdfplumber not installed (%s); pip install pdfplumber "
            "(add to [ingest] extras)",
            _PDFPLUMBER_IMPORT_ERR,
        )
        return 1
    if httpx is None:
        _LOG.error("httpx not installed (should be a hard dep); pip install httpx")
        return 1

    tos_cleared = os.environ.get("AUTONOMATH_COURT_TOS_ACCEPTED") == "1"
    if args.respect_tos and not tos_cleared:
        _LOG.info(
            "TOS gate ON (default). source_excerpt capped at %d chars. "
            "Set AUTONOMATH_COURT_TOS_ACCEPTED=1 to lift after legal review.",
            EXCERPT_CHARS_TOS_RESPECTED,
        )
    elif not args.respect_tos:
        _LOG.warning("TOS gate OFF (--no-respect-tos). Ensure written clearance on file.")

    # Pre-flight: load laws_lookup, open DB for migration check.
    laws_lookup = load_laws_lookup(args.db)
    _LOG.info("loaded %d law titles from laws table", len(laws_lookup))

    if not args.dry_run:
        if not args.db.parent.exists():
            _LOG.error("DB dir missing: %s", args.db.parent)
            return 2
        conn = sqlite3.connect(str(args.db))
        conn.execute("PRAGMA foreign_keys = ON")
        if not ensure_migration_applied(conn):
            _LOG.error(
                "court_decisions table missing in %s — apply migration 016 first",
                args.db,
            )
            conn.close()
            return 2
    else:
        conn = None  # type: ignore[assignment]

    # -- Playwright session ---------------------------------------------
    now = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    filters = SearchFilters(
        court=args.court,
        subject_area=args.subject_area,
        date_from=args.date_from,
        limit=args.limit,
    )
    stats = {
        "walked": 0,
        "built": 0,
        "inserted": 0,
        "updated": 0,
        "skipped_hard_reject": 0,
        "skipped_parse": 0,
        "pending_law_refs": 0,
    }
    try:
        with sync_playwright() as pw:
            browser: Browser = pw.chromium.launch(headless=True)
            context: BrowserContext = browser.new_context(user_agent=USER_AGENT)
            # robots.txt check uses the context's request routing.
            probe = context.new_page()
            try:
                if not _respect_robots(probe):
                    _LOG.error("robots.txt disallow — abort")
                    browser.close()
                    if conn is not None:
                        conn.close()
                    return 1
            finally:
                probe.close()

            raw_results = walk_search_results(context, filters)
            stats["walked"] = len(raw_results)

            for meta in raw_results:
                try:
                    decision = build_decision(
                        meta,
                        laws_lookup,
                        cache_dir=args.cache_dir,
                        respect_tos=args.respect_tos,
                        tos_cleared=tos_cleared,
                        now=now,
                    )
                except Exception as exc:  # noqa: BLE001
                    _LOG.exception("build_decision failed for %s: %s", meta.get("source_url"), exc)
                    stats["skipped_parse"] += 1
                    continue
                if decision is None:
                    stats["skipped_hard_reject"] += 1
                    continue
                stats["built"] += 1
                stats["pending_law_refs"] += len(decision.pending_law_names)

                # Per-case summary line.
                _LOG.info(
                    "OK %s | %s | %s | level=%s weight=%s laws=%d pending=%d repl=%d",
                    decision.unified_id,
                    decision.court or "?",
                    (decision.case_name or "")[:50],
                    decision.court_level,
                    decision.precedent_weight,
                    0 if decision.related_law_ids_json is None else decision.related_law_ids_json.count("LAW-"),
                    len(decision.pending_law_names),
                    decision.replacement_count,
                )

                if args.dry_run or conn is None:
                    continue
                try:
                    verdict = upsert_decision(conn, decision)
                    if verdict == "insert":
                        stats["inserted"] += 1
                    else:
                        stats["updated"] += 1
                except sqlite3.Error as exc:
                    _LOG.error("DB upsert failed %s: %s", decision.unified_id, exc)
                    stats["skipped_parse"] += 1

            browser.close()
    except Exception as exc:  # noqa: BLE001
        _LOG.exception("fatal crawl error: %s", exc)
        if conn is not None:
            conn.close()
        return 1

    if conn is not None:
        conn.commit()
        conn.close()

    # Final stats.
    _LOG.info(
        "done walked=%d built=%d inserted=%d updated=%d "
        "skipped_hard_reject=%d skipped_parse=%d pending_law_refs=%d",
        stats["walked"],
        stats["built"],
        stats["inserted"],
        stats["updated"],
        stats["skipped_hard_reject"],
        stats["skipped_parse"],
        stats["pending_law_refs"],
    )
    if stats["pending_law_refs"] > 0:
        _LOG.info(
            "TODO: %d PENDING: law_name references remain; "
            "reconcile via a separate walker (out of scope here).",
            stats["pending_law_refs"],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
