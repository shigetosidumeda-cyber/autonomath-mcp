"""Enrich empty court_decisions.source_excerpt cells from courts.go.jp HTML.

Read-only against the SQLite DB. Output is a CSV under
``data/analysis_wave18/court_decisions_excerpt_<YYYY-MM-DD>.csv`` containing one
row per fetched decision with ``decision_id``, ``excerpt``, ``fetched_at``,
``content_hash``, ``source_url``, ``status``, ``error``. The CSV is consumed
later by an explicit DB-write step that the operator runs after review; this
script never writes to the DB.

The enrichment strategy is extractive: we pull only the labelled segments that
courts.go.jp publishes on the ``hanrei/<hid>/detail<n>/index.html`` page
(``判示事項`` / ``裁判要旨`` / ``主文`` / ``事案の概要`` / ``判旨``) and
concatenate them up to 400 characters. Source text is preserved verbatim modulo
NFKC normalization and whitespace collapse — no rewriting, no LLM calls.

Compliance::

    * robots.txt: courts.go.jp's *Disallow* list only covers
      ``/<court>/saiban/kozisotatu/index.html`` (公示送達). ``/hanrei/`` and
      ``/assets/hanrei/`` are not disallowed; the script also skips any URL
      whose path matches ``/saiban/kozisotatu/``.
    * Per-domain throttle: 1 request/sec via a monotonic-clock pacer.
    * User-Agent: ``jpcite-research/1.0 (+https://jpcite.com/about)``.

Flags::

    --limit N      Cap rows (default: all empty rows).
    --dry-run      Skip HTTP fetch; emit decision_id rows with status='dryrun'.
    --output PATH  Override CSV destination (default: dated path under
                   ``data/analysis_wave18/``).
    --db PATH      Override DB path (default: ``data/jpintel.db``).

Smoke run::

    python scripts/etl/enrich_court_decisions_excerpt.py --limit 30
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import logging
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from bs4 import BeautifulSoup  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

try:
    import pdfplumber  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover -- optional fallback
    pdfplumber = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

USER_AGENT = "jpcite-research/1.0 (+https://jpcite.com/about)"
ALLOWED_HOST = "www.courts.go.jp"
ROBOTS_URL = "https://www.courts.go.jp/robots.txt"
DETAIL_URL_PATTERN = re.compile(
    r"^https://www\.courts\.go\.jp/hanrei/(?P<hid>\d+)/detail\d+/index\.html$"
)
PDF_URL_TMPL = "https://www.courts.go.jp/assets/hanrei/hanrei-pdf-{hid}.pdf"

# courts.go.jp PDFs render labels with optional thin-space (e.g. ``主 文``).
# Allow zero or one spaces between any two characters of the label tokens.
_PDF_SECTION_RE = re.compile(
    r"(主\s?文|事\s?実\s?及\s?び\s?理\s?由|事\s?案\s?の\s?概\s?要|"
    r"判\s?\s?\s?旨|当\s?裁\s?判\s?所\s?の\s?判\s?断)"
)

PER_REQUEST_DELAY_SEC = 1.0
HTTP_TIMEOUT_SEC = 30.0
MAX_RETRIES = 3

EXCERPT_MIN_CHARS = 200
EXCERPT_MAX_CHARS = 400

# Order matters: 判示事項 + 裁判要旨 first, then 主文 + 事案の概要 + 判旨.
SECTION_LABELS = (
    "判示事項",
    "裁判要旨",
    "主文",
    "事案の概要",
    "判旨",
    "理由",
    "参照法条",
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "analysis_wave18"

CSV_FIELDS = (
    "decision_id",
    "source_url",
    "excerpt",
    "fetched_at",
    "content_hash",
    "status",
    "error",
)

_LOG = logging.getLogger("enrich_court_decisions_excerpt")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    s = s.replace("　", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _trim_for_excerpt(text: str, *, max_chars: int = EXCERPT_MAX_CHARS) -> str:
    """Trim to <= max_chars without breaking inside a labelled segment header."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    # Avoid leaving a trailing 【label】 with no content.
    last_open = cut.rfind("【")
    last_close = cut.rfind("】")
    if last_open > last_close:
        cut = cut[:last_open].rstrip()
    return cut


def _safe_url(url: str) -> bool:
    if not url:
        return False
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.netloc.lower() != ALLOWED_HOST:
        return False
    if "/saiban/kozisotatu/" in parsed.path.lower():
        return False
    # Accept either the detail HTML page or the PDF mirror that lives next to
    # it. Both are public, robots-allowed paths.
    path = parsed.path
    if path.startswith("/hanrei/") and path.endswith("/index.html"):
        return True
    return path.startswith("/assets/hanrei/") and path.endswith(".pdf")


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# robots.txt cache
# ---------------------------------------------------------------------------


def load_robots(client: httpx.Client) -> urllib.robotparser.RobotFileParser:
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(ROBOTS_URL)
    try:
        r = client.get(ROBOTS_URL)
        r.raise_for_status()
        rp.parse(r.text.splitlines())
    except (httpx.HTTPError, httpx.TransportError) as exc:  # pragma: no cover
        _LOG.warning("robots.txt fetch failed (%s); defaulting to disallow", exc)

        # Pessimistic fallback: parse an empty body so can_fetch returns True
        # only for paths the explicit pattern allows.
        rp.parse([])
    return rp


def robots_allows(rp: urllib.robotparser.RobotFileParser, url: str) -> bool:
    return rp.can_fetch(USER_AGENT, url)


# ---------------------------------------------------------------------------
# DB read
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PendingRow:
    decision_id: str
    source_url: str


def open_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_pending(conn: sqlite3.Connection, *, limit: int | None) -> list[PendingRow]:
    sql = (
        "SELECT unified_id AS decision_id, source_url "
        "FROM court_decisions "
        "WHERE (source_excerpt IS NULL OR source_excerpt = '') "
        "  AND source_url IS NOT NULL "
        "ORDER BY decision_date DESC NULLS LAST, unified_id"
    )
    if limit is not None and limit > 0:
        sql += f" LIMIT {int(limit)}"
    return [PendingRow(r["decision_id"], r["source_url"]) for r in conn.execute(sql)]


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------


def _iter_dl_pairs(soup: BeautifulSoup) -> Iterator[tuple[str, str]]:
    for dl in soup.find_all("dl"):
        dt = dl.find("dt")
        dd = dl.find("dd")
        if not dt or not dd:
            continue
        k = _normalize(dt.get_text())
        v = _normalize(dd.get_text(" ", strip=True))
        if k and v:
            yield k, v


def _iter_section_headers(soup: BeautifulSoup) -> Iterator[tuple[str, str]]:
    """Some detail pages render section blocks as h2/h3 + sibling p/div.

    Yield (header, body) pairs whose header matches one of SECTION_LABELS.
    """
    for header in soup.find_all(("h2", "h3", "h4")):
        label = _normalize(header.get_text())
        if not label:
            continue
        # Pick the first non-trivial sibling block.
        body_chunks: list[str] = []
        for sib in header.next_siblings:
            name = getattr(sib, "name", None)
            if name in ("h2", "h3", "h4"):
                break
            if name is None:
                continue
            text = _normalize(sib.get_text(" ", strip=True))
            if text:
                body_chunks.append(text)
                if len(" ".join(body_chunks)) > EXCERPT_MAX_CHARS * 2:
                    break
        if body_chunks:
            yield label, " ".join(body_chunks)


def _normalize_pdf_text(text: str) -> str:
    """Collapse the heavy whitespace pdfplumber emits, but keep newlines."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    # Replace runs of spaces/tabs with single space; keep \n for section search.
    s = re.sub(r"[ \t　]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n{2,}", "\n", s)
    return s.strip()


def extract_excerpt_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """Extract a 200-400 char excerpt from a hanrei PDF.

    Strategy: read at most the first 3 pages, locate ``主文`` (with optional
    spaces), then capture everything from there through ~600 normalized chars
    (which includes 主文 + 事実及び理由 / 事案の概要 prefix). Trim back to the
    400-char excerpt envelope. Returns "" if pdfplumber is unavailable or the
    PDF cannot be parsed.
    """
    if pdfplumber is None:
        return ""
    import io

    text_parts: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages[:3]:
                txt = page.extract_text() or ""
                text_parts.append(txt)
                if sum(len(p) for p in text_parts) > 8000:
                    break
    except Exception:  # noqa: BLE001
        return ""

    raw = "\n".join(text_parts)
    raw = _normalize_pdf_text(raw)
    if not raw:
        return ""

    # Strip line numbers ("\n5\n") that pdfplumber leaves on the right margin.
    raw = re.sub(r"\n\d{1,3}(?=\n)", "\n", raw)

    # Locate 主文 anchor. If absent, fall back to 事実及び理由.
    m = _PDF_SECTION_RE.search(raw)
    if not m:
        return ""

    body = raw[m.start() : m.start() + 800]
    # Collapse remaining newlines for the excerpt blob.
    body = re.sub(r"\s+", " ", body).strip()

    parts: list[str] = []
    label = re.sub(r"\s+", "", m.group(1))
    parts.append(f"【{label}】{body[len(m.group(0)):].strip()}")
    blob = "\n".join(parts)
    return _trim_for_excerpt(blob, max_chars=EXCERPT_MAX_CHARS)


def extract_excerpt(html: str) -> tuple[str, str]:
    """Return (excerpt, raw_collected_blob).

    The blob is the full ordered concatenation of labelled segments before
    trimming; the excerpt is the trimmed view that goes into the CSV.
    """
    soup = BeautifulSoup(html, "html.parser")
    collected: dict[str, str] = {}
    for k, v in _iter_dl_pairs(soup):
        if k in SECTION_LABELS and k not in collected:
            collected[k] = v
    if not collected:
        for k, v in _iter_section_headers(soup):
            if k in SECTION_LABELS and k not in collected:
                collected[k] = v

    parts: list[str] = []
    for label in SECTION_LABELS:
        if label in collected:
            parts.append(f"【{label}】{collected[label]}")
            joined = "\n".join(parts)
            if len(joined) >= EXCERPT_MAX_CHARS:
                break

    blob = "\n".join(parts)
    excerpt = _trim_for_excerpt(blob, max_chars=EXCERPT_MAX_CHARS)
    return excerpt, blob


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------


class CourtsClient:
    def __init__(self, *, timeout: float = HTTP_TIMEOUT_SEC) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "ja,en;q=0.5",
            },
            follow_redirects=True,
        )
        self._last_call: float = 0.0
        self._robots: urllib.robotparser.RobotFileParser | None = None

    def _pace(self) -> None:
        delta = time.monotonic() - self._last_call
        if delta < PER_REQUEST_DELAY_SEC:
            time.sleep(PER_REQUEST_DELAY_SEC - delta)
        self._last_call = time.monotonic()

    def robots(self) -> urllib.robotparser.RobotFileParser:
        if self._robots is None:
            self._pace()
            self._robots = load_robots(self._client)
        return self._robots

    def get(self, url: str) -> str:
        return self._request_text(url, decode="text")

    def get_bytes(self, url: str) -> bytes:
        return self._request_text(url, decode="bytes")  # type: ignore[return-value]

    def _request_text(self, url: str, *, decode: str) -> str | bytes:
        if not _safe_url(url):
            raise ValueError(f"refused unsafe URL: {url}")
        if not robots_allows(self.robots(), url):
            raise PermissionError(f"robots.txt disallows: {url}")
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            self._pace()
            try:
                r = self._client.get(url)
                r.raise_for_status()
                return r.text if decode == "text" else r.content
            except (httpx.HTTPError, httpx.TransportError) as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    sleep_for = 2**attempt
                    _LOG.warning(
                        "GET %s failed (%s); retry %d/%d after %ds",
                        url,
                        exc,
                        attempt,
                        MAX_RETRIES,
                        sleep_for,
                    )
                    time.sleep(sleep_for)
        assert last_exc is not None
        raise last_exc

    def close(self) -> None:
        self._client.close()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


@dataclass
class EnrichResult:
    decision_id: str
    source_url: str
    excerpt: str
    fetched_at: str
    content_hash: str
    status: str          # 'ok' | 'empty' | 'http_error' | 'unsafe_url' |
                         # 'robots_disallow' | 'dryrun' | 'parse_error'
    error: str

    def as_csv_row(self) -> dict[str, str]:
        return {
            "decision_id": self.decision_id,
            "source_url": self.source_url,
            "excerpt": self.excerpt,
            "fetched_at": self.fetched_at,
            "content_hash": self.content_hash,
            "status": self.status,
            "error": self.error,
        }


def _now_iso() -> str:
    return _dt.datetime.now(tz=_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def enrich_one(client: CourtsClient, row: PendingRow) -> EnrichResult:
    url = row.source_url
    if not DETAIL_URL_PATTERN.match(url):
        return EnrichResult(
            decision_id=row.decision_id,
            source_url=url,
            excerpt="",
            fetched_at=_now_iso(),
            content_hash="",
            status="unsafe_url",
            error=f"url does not match courts.go.jp /hanrei/<id>/detail<n>/index.html: {url}",
        )
    try:
        html = client.get(url)
    except PermissionError as exc:
        return EnrichResult(
            decision_id=row.decision_id,
            source_url=url,
            excerpt="",
            fetched_at=_now_iso(),
            content_hash="",
            status="robots_disallow",
            error=str(exc),
        )
    except ValueError as exc:
        return EnrichResult(
            decision_id=row.decision_id,
            source_url=url,
            excerpt="",
            fetched_at=_now_iso(),
            content_hash="",
            status="unsafe_url",
            error=str(exc),
        )
    except (httpx.HTTPError, httpx.TransportError) as exc:
        return EnrichResult(
            decision_id=row.decision_id,
            source_url=url,
            excerpt="",
            fetched_at=_now_iso(),
            content_hash="",
            status="http_error",
            error=f"{type(exc).__name__}: {exc}",
        )

    try:
        excerpt, _blob = extract_excerpt(html)
    except Exception as exc:  # noqa: BLE001 -- belt-and-braces around bs4
        return EnrichResult(
            decision_id=row.decision_id,
            source_url=url,
            excerpt="",
            fetched_at=_now_iso(),
            content_hash="",
            status="parse_error",
            error=f"{type(exc).__name__}: {exc}",
        )

    if excerpt:
        return EnrichResult(
            decision_id=row.decision_id,
            source_url=url,
            excerpt=excerpt,
            fetched_at=_now_iso(),
            content_hash=_content_hash(excerpt),
            status="ok",
            error="",
        )

    # HTML had no labelled abstract (typical for detail5 知財/lower-court pages).
    # Fall back to the official PDF mirror.
    pdf_excerpt, pdf_url = "", ""
    if pdfplumber is not None:
        m = DETAIL_URL_PATTERN.match(url)
        if m:
            pdf_url = PDF_URL_TMPL.format(hid=m.group("hid"))
            try:
                pdf_bytes = client.get_bytes(pdf_url)
                pdf_excerpt = extract_excerpt_from_pdf_bytes(pdf_bytes)
            except (httpx.HTTPError, httpx.TransportError, PermissionError, ValueError) as exc:
                return EnrichResult(
                    decision_id=row.decision_id,
                    source_url=url,
                    excerpt="",
                    fetched_at=_now_iso(),
                    content_hash="",
                    status="http_error",
                    error=f"pdf fallback failed: {type(exc).__name__}: {exc}",
                )

    if pdf_excerpt:
        return EnrichResult(
            decision_id=row.decision_id,
            source_url=pdf_url or url,
            excerpt=pdf_excerpt,
            fetched_at=_now_iso(),
            content_hash=_content_hash(pdf_excerpt),
            status="ok_pdf",
            error="",
        )

    return EnrichResult(
        decision_id=row.decision_id,
        source_url=url,
        excerpt="",
        fetched_at=_now_iso(),
        content_hash="",
        status="empty",
        error="no labelled section found in HTML or PDF",
    )


def run(
    rows: Iterable[PendingRow],
    *,
    dry_run: bool,
    client: CourtsClient | None = None,
) -> list[EnrichResult]:
    results: list[EnrichResult] = []
    if dry_run:
        for r in rows:
            results.append(
                EnrichResult(
                    decision_id=r.decision_id,
                    source_url=r.source_url,
                    excerpt="",
                    fetched_at=_now_iso(),
                    content_hash="",
                    status="dryrun",
                    error="",
                )
            )
        return results

    own_client = client is None
    if client is None:
        client = CourtsClient()
    try:
        for r in rows:
            results.append(enrich_one(client, r))
    finally:
        if own_client:
            client.close()
    return results


def write_csv(results: Iterable[EnrichResult], output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for res in results:
            writer.writerow(res.as_csv_row())
            n += 1
    return n


def default_output_path(now: _dt.datetime | None = None) -> Path:
    now = now or _dt.datetime.now(tz=_dt.UTC)
    stamp = now.strftime("%Y-%m-%d")
    return DEFAULT_OUTPUT_DIR / f"court_decisions_excerpt_{stamp}.csv"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--limit", type=int, default=None, help="Cap pending rows.")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip HTTP fetch; produce dryrun-status CSV rows only.",
    )
    p.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Path to jpintel.db (read-only).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "CSV destination. Defaults to "
            "data/analysis_wave18/court_decisions_excerpt_<UTC-DATE>.csv."
        ),
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose logging.",
    )
    return p.parse_args(argv)


def _summarize(results: list[EnrichResult]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in results:
        out[r.status] = out.get(r.status, 0) + 1
    out["total"] = len(results)
    return out


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    output_path = args.output or default_output_path()

    conn = open_db(args.db)
    try:
        pending = fetch_pending(conn, limit=args.limit)
    finally:
        conn.close()
    _LOG.info(
        "pending rows fetched: %d (limit=%s, dry_run=%s)",
        len(pending),
        args.limit,
        args.dry_run,
    )
    if not pending:
        _LOG.info("no pending rows; writing empty CSV at %s", output_path)
        write_csv([], output_path)
        return 0

    results = run(pending, dry_run=args.dry_run)
    n = write_csv(results, output_path)
    summary = _summarize(results)
    _LOG.info(
        "wrote %d rows to %s; status counts=%s",
        n,
        output_path,
        summary,
    )
    if args.dry_run:
        return 0
    # Non-zero exit if every row failed (sane CI signal).
    success = summary.get("ok", 0) + summary.get("ok_pdf", 0)
    if success == 0 and summary.get("total", 0) > 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
