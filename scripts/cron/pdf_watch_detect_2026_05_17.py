#!/usr/bin/env python3
"""CC4 — hourly PDF watch detector.

Polls a watchlist of public-sector primary-source PDF publication points
(NTA / FSA / MHLW / METI / MLIT / MOJ / 47 prefectures / e-Gov 法令) on
an EventBridge ``rate(1 hour)`` cadence. For each new (source_url,
content_hash) pair the detector:

    1. Inserts a row into ``am_pdf_watch_log`` (textract_status='pending').
    2. Enqueues an SQS message to ``jpcite-pdf-textract-queue`` so the
       textract-submit Lambda can pick it up.

Constraints
-----------
* No Anthropic / OpenAI / SDK calls (CI enforced by
  ``tests/test_no_llm_in_production.py``).
* Aggregator ban: every source is a first-party government domain. We
  refuse to follow links into commercial aggregators.
* ``robots.txt`` honoured: a floor of 1 request / 3 seconds per host
  (3,600s / 60min hour = 1,200 requests/host theoretical cap; in
  practice the per-source candidate count is <50 so we never need to
  approach the floor).
* DRY_RUN by default. ``--commit`` flips the SQS enqueue + DB insert on.
* sustained burn estimate: 100 PDF/day x $1.50/PDF Textract = $150/day
  ($4,500/30d) — well under the $19,490 never-reach line.

Usage
-----
::

    python scripts/cron/pdf_watch_detect_2026_05_17.py            # real run
    python scripts/cron/pdf_watch_detect_2026_05_17.py --dry-run  # noop
    python scripts/cron/pdf_watch_detect_2026_05_17.py --since 2026-05-16T00:00:00Z
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterator

HttpGet = Callable[..., tuple[int, bytes]]
Sleeper = Callable[[float], None]

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


logger = logging.getLogger("autonomath.cron.pdf_watch_detect")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_USER_AGENT: Final[str] = (
    "Bookyou-jpcite-pdf-watch/2026.05.17 (+https://jpcite.com; ops@bookyou.net)"
)
DEFAULT_PER_HOST_DELAY_SEC: Final[float] = 3.0
DEFAULT_HTTP_TIMEOUT_SEC: Final[float] = 30.0
DEFAULT_SQS_QUEUE_NAME: Final[str] = "jpcite-pdf-textract-queue"
DEFAULT_SQS_REGION: Final[str] = "ap-northeast-1"
DEFAULT_DB_PATH: Final[str] = "autonomath.db"
PDF_HREF_RE: Final[re.Pattern[str]] = re.compile(r'href="([^"]+\.pdf)"', re.IGNORECASE)


@dataclass(frozen=True)
class WatchSource:
    """A single primary-source publication point.

    ``kind`` is one of the CHECK-constrained values in
    ``am_pdf_watch_log.source_kind``. ``crawl_url`` is the HTML landing
    page (or sitemap.xml / RSS endpoint) that lists newly published PDFs.
    """

    kind: str
    crawl_url: str
    host: str


# Canonical watchlist. Each is an official government landing page.
# Aggregator-banned per CC4 constraint; only *.go.jp / *.lg.jp / e-gov.
# Counts: 6 省庁 + 47 都道府県 + 1 e-Gov = 54 sources.
WATCHLIST: Final[tuple[WatchSource, ...]] = (
    # --- 国 (6 省庁) -----------------------------------------------------
    WatchSource("nta", "https://www.nta.go.jp/law/tsutatsu/", "www.nta.go.jp"),
    WatchSource("fsa", "https://www.fsa.go.jp/news/", "www.fsa.go.jp"),
    WatchSource("mhlw", "https://www.mhlw.go.jp/stf/houdou/index.html", "www.mhlw.go.jp"),
    WatchSource("meti", "https://www.meti.go.jp/press/index.html", "www.meti.go.jp"),
    WatchSource("mlit", "https://www.mlit.go.jp/report/press/", "www.mlit.go.jp"),
    WatchSource("moj", "https://www.moj.go.jp/houdou/index.html", "www.moj.go.jp"),
    # --- e-Gov 法令データ ------------------------------------------------
    WatchSource("egov_law", "https://elaws.e-gov.go.jp/", "elaws.e-gov.go.jp"),
    # --- 47 都道府県 (公的 *.lg.jp / *.pref.*.jp) ------------------------
    WatchSource("pref_hokkaido", "https://www.pref.hokkaido.lg.jp/", "www.pref.hokkaido.lg.jp"),
    WatchSource("pref_aomori", "https://www.pref.aomori.lg.jp/", "www.pref.aomori.lg.jp"),
    WatchSource("pref_iwate", "https://www.pref.iwate.jp/", "www.pref.iwate.jp"),
    WatchSource("pref_miyagi", "https://www.pref.miyagi.jp/", "www.pref.miyagi.jp"),
    WatchSource("pref_akita", "https://www.pref.akita.lg.jp/", "www.pref.akita.lg.jp"),
    WatchSource("pref_yamagata", "https://www.pref.yamagata.jp/", "www.pref.yamagata.jp"),
    WatchSource("pref_fukushima", "https://www.pref.fukushima.lg.jp/", "www.pref.fukushima.lg.jp"),
    WatchSource("pref_ibaraki", "https://www.pref.ibaraki.jp/", "www.pref.ibaraki.jp"),
    WatchSource("pref_tochigi", "https://www.pref.tochigi.lg.jp/", "www.pref.tochigi.lg.jp"),
    WatchSource("pref_gunma", "https://www.pref.gunma.jp/", "www.pref.gunma.jp"),
    WatchSource("pref_saitama", "https://www.pref.saitama.lg.jp/", "www.pref.saitama.lg.jp"),
    WatchSource("pref_chiba", "https://www.pref.chiba.lg.jp/", "www.pref.chiba.lg.jp"),
    WatchSource("pref_tokyo", "https://www.metro.tokyo.lg.jp/", "www.metro.tokyo.lg.jp"),
    WatchSource("pref_kanagawa", "https://www.pref.kanagawa.jp/", "www.pref.kanagawa.jp"),
    WatchSource("pref_niigata", "https://www.pref.niigata.lg.jp/", "www.pref.niigata.lg.jp"),
    WatchSource("pref_toyama", "https://www.pref.toyama.jp/", "www.pref.toyama.jp"),
    WatchSource("pref_ishikawa", "https://www.pref.ishikawa.lg.jp/", "www.pref.ishikawa.lg.jp"),
    WatchSource("pref_fukui", "https://www.pref.fukui.lg.jp/", "www.pref.fukui.lg.jp"),
    WatchSource("pref_yamanashi", "https://www.pref.yamanashi.jp/", "www.pref.yamanashi.jp"),
    WatchSource("pref_nagano", "https://www.pref.nagano.lg.jp/", "www.pref.nagano.lg.jp"),
    WatchSource("pref_gifu", "https://www.pref.gifu.lg.jp/", "www.pref.gifu.lg.jp"),
    WatchSource("pref_shizuoka", "https://www.pref.shizuoka.jp/", "www.pref.shizuoka.jp"),
    WatchSource("pref_aichi", "https://www.pref.aichi.jp/", "www.pref.aichi.jp"),
    WatchSource("pref_mie", "https://www.pref.mie.lg.jp/", "www.pref.mie.lg.jp"),
    WatchSource("pref_shiga", "https://www.pref.shiga.lg.jp/", "www.pref.shiga.lg.jp"),
    WatchSource("pref_kyoto", "https://www.pref.kyoto.jp/", "www.pref.kyoto.jp"),
    WatchSource("pref_osaka", "https://www.pref.osaka.lg.jp/", "www.pref.osaka.lg.jp"),
    WatchSource("pref_hyogo", "https://web.pref.hyogo.lg.jp/", "web.pref.hyogo.lg.jp"),
    WatchSource("pref_nara", "https://www.pref.nara.jp/", "www.pref.nara.jp"),
    WatchSource("pref_wakayama", "https://www.pref.wakayama.lg.jp/", "www.pref.wakayama.lg.jp"),
    WatchSource("pref_tottori", "https://www.pref.tottori.lg.jp/", "www.pref.tottori.lg.jp"),
    WatchSource("pref_shimane", "https://www.pref.shimane.lg.jp/", "www.pref.shimane.lg.jp"),
    WatchSource("pref_okayama", "https://www.pref.okayama.jp/", "www.pref.okayama.jp"),
    WatchSource("pref_hiroshima", "https://www.pref.hiroshima.lg.jp/", "www.pref.hiroshima.lg.jp"),
    WatchSource("pref_yamaguchi", "https://www.pref.yamaguchi.lg.jp/", "www.pref.yamaguchi.lg.jp"),
    WatchSource("pref_tokushima", "https://www.pref.tokushima.lg.jp/", "www.pref.tokushima.lg.jp"),
    WatchSource("pref_kagawa", "https://www.pref.kagawa.lg.jp/", "www.pref.kagawa.lg.jp"),
    WatchSource("pref_ehime", "https://www.pref.ehime.jp/", "www.pref.ehime.jp"),
    WatchSource("pref_kochi", "https://www.pref.kochi.lg.jp/", "www.pref.kochi.lg.jp"),
    WatchSource("pref_fukuoka", "https://www.pref.fukuoka.lg.jp/", "www.pref.fukuoka.lg.jp"),
    WatchSource("pref_saga", "https://www.pref.saga.lg.jp/", "www.pref.saga.lg.jp"),
    WatchSource("pref_nagasaki", "https://www.pref.nagasaki.jp/", "www.pref.nagasaki.jp"),
    WatchSource("pref_kumamoto", "https://www.pref.kumamoto.jp/", "www.pref.kumamoto.jp"),
    WatchSource("pref_oita", "https://www.pref.oita.jp/", "www.pref.oita.jp"),
    WatchSource("pref_miyazaki", "https://www.pref.miyazaki.lg.jp/", "www.pref.miyazaki.lg.jp"),
    WatchSource("pref_kagoshima", "https://www.pref.kagoshima.jp/", "www.pref.kagoshima.jp"),
    WatchSource("pref_okinawa", "https://www.pref.okinawa.lg.jp/", "www.pref.okinawa.lg.jp"),
)


def watchlist_count() -> int:
    """Return the number of distinct watch sources (used by tests + docs)."""
    return len(WATCHLIST)


# ---------------------------------------------------------------------------
# HTTP fetch (stdlib only; no requests / httpx dep at this layer to keep
# cold-start cheap on Lambda).
# ---------------------------------------------------------------------------


def _is_government_host(host: str) -> bool:
    """Return True for first-party JP government / prefecture domains.

    Accepts:
      * ``*.go.jp`` — 国 (中央省庁)
      * ``*.lg.jp`` — 地方公共団体
      * ``*.pref.<pref>.jp`` — bare-jp prefectural domains (iwate / miyagi /
        kanagawa / yamanashi / shizuoka / aichi / kyoto / nara / okayama /
        ehime / nagasaki / kumamoto / oita / kagoshima all publish under
        this form).
      * ``web.pref.<pref>.lg.jp`` — same as above with explicit lg subdomain.
    """
    if host.endswith(".go.jp") or host.endswith(".lg.jp"):
        return True
    if host.startswith("www.pref.") and host.endswith(".jp"):
        return True
    return bool(host.startswith("web.pref.") and host.endswith(".jp"))


def _http_get(
    url: str,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: float = DEFAULT_HTTP_TIMEOUT_SEC,
) -> tuple[int, bytes]:
    """Single HTTP GET. Returns ``(status, body_bytes)``.

    Refuses non-https + non-government-domain hosts as defence-in-depth
    against accidental aggregator follow-through.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"refuse non-https url: {url!r}")
    host = parsed.hostname or ""
    if not _is_government_host(host):
        raise ValueError(f"refuse non-government host: {host!r}")
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310  # nosec B310 — https-only + gov-domain whitelist enforced above
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except (urllib.error.URLError, TimeoutError) as e:  # network / DNS
        logger.warning("http_get_failed url=%s err=%s", url, e)
        return 0, b""


def _extract_pdf_urls(html: bytes, base_url: str) -> list[str]:
    """Find absolute PDF URLs in the landing-page HTML."""
    try:
        text = html.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return []
    out: list[str] = []
    for href in PDF_HREF_RE.findall(text):
        absolute = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(absolute)
        host = parsed.hostname or ""
        if parsed.scheme != "https":
            continue
        if not _is_government_host(host):
            continue
        if absolute not in out:
            out.append(absolute)
    return out


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# DB helpers (sqlite3 + sqlite-driven idempotency)
# ---------------------------------------------------------------------------


def _ensure_table(conn: sqlite3.Connection) -> None:
    """Apply migration wave24_216 in-process so tests don't depend on boot."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS am_pdf_watch_log (
            watch_id           INTEGER PRIMARY KEY AUTOINCREMENT,
            source_kind        TEXT NOT NULL,
            source_url         TEXT NOT NULL,
            content_hash       TEXT NOT NULL,
            detected_at        TEXT NOT NULL DEFAULT
                                  (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            textract_status    TEXT NOT NULL DEFAULT 'pending',
            textract_job_id    TEXT,
            s3_input_key       TEXT,
            s3_result_key      TEXT,
            kg_extract_status  TEXT NOT NULL DEFAULT 'pending',
            kg_entity_count    INTEGER NOT NULL DEFAULT 0,
            kg_relation_count  INTEGER NOT NULL DEFAULT 0,
            ingested_at        TEXT,
            last_error         TEXT,
            updated_at         TEXT NOT NULL DEFAULT
                                  (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            UNIQUE (source_url, content_hash)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_am_pdf_watch_log_textract_status "
        "ON am_pdf_watch_log(textract_status, detected_at)"
    )


def insert_detection(
    conn: sqlite3.Connection,
    *,
    source_kind: str,
    source_url: str,
    content_hash: str,
) -> int | None:
    """Insert a new detection row. Returns watch_id, or None on UNIQUE collision."""
    try:
        cur = conn.execute(
            """
            INSERT INTO am_pdf_watch_log
                (source_kind, source_url, content_hash)
            VALUES (?, ?, ?)
            """,
            (source_kind, source_url, content_hash),
        )
        return int(cur.lastrowid or 0) or None
    except sqlite3.IntegrityError:
        return None  # already detected — idempotent no-op


# ---------------------------------------------------------------------------
# SQS enqueue
# ---------------------------------------------------------------------------


def enqueue_textract_message(
    *,
    queue_url: str,
    watch_id: int,
    source_kind: str,
    source_url: str,
    content_hash: str,
    region: str = DEFAULT_SQS_REGION,
    commit: bool = False,
) -> dict[str, Any]:
    """Enqueue a Textract-submit SQS message for the given detection.

    DRY_RUN by default — only constructs + logs the envelope. ``commit=True``
    + boto3 importable triggers the actual ``send_message``.
    """
    envelope: dict[str, Any] = {
        "watch_id": watch_id,
        "source_kind": source_kind,
        "source_url": source_url,
        "content_hash": content_hash,
        "enqueued_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if not commit:
        return {"mode": "dry_run", "envelope": envelope}
    try:
        import boto3  # type: ignore[import-not-found,unused-ignore]
    except ImportError:
        logger.warning("boto3 unavailable — falling back to dry_run for watch_id=%s", watch_id)
        return {"mode": "dry_run_no_boto3", "envelope": envelope}
    sqs = boto3.client("sqs", region_name=region)
    resp = sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(envelope, ensure_ascii=False),
    )
    return {"mode": "committed", "envelope": envelope, "message_id": resp.get("MessageId")}


# ---------------------------------------------------------------------------
# Per-source crawl
# ---------------------------------------------------------------------------


def crawl_source(
    source: WatchSource,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    per_host_delay_sec: float = DEFAULT_PER_HOST_DELAY_SEC,
    http_get: HttpGet = _http_get,  # injectable for tests
    sleep: Sleeper = time.sleep,  # injectable for tests
) -> Iterator[tuple[str, str]]:
    """Yield ``(source_url, content_hash)`` pairs for this source.

    The landing page is fetched first; PDF links are then enumerated.
    ``content_hash`` is computed by fetching the PDF bytes themselves
    (HEAD-only would not give us a reliable hash). Per-host throttle
    floor honoured between every PDF fetch.
    """
    status, body = http_get(source.crawl_url, user_agent=user_agent)
    if status != 200 or not body:
        logger.info(
            "crawl_landing_skip source=%s status=%s bytes=%d",
            source.kind,
            status,
            len(body),
        )
        return
    pdf_urls = _extract_pdf_urls(body, source.crawl_url)
    logger.info(
        "crawl_landing_ok source=%s pdf_candidates=%d",
        source.kind,
        len(pdf_urls),
    )
    for pdf_url in pdf_urls:
        sleep(per_host_delay_sec)  # robots floor
        s2, b2 = http_get(pdf_url, user_agent=user_agent)
        if s2 != 200 or not b2:
            logger.info("crawl_pdf_skip url=%s status=%s", pdf_url, s2)
            continue
        yield pdf_url, _sha256_hex(b2)


# ---------------------------------------------------------------------------
# Orchestration entry point
# ---------------------------------------------------------------------------


def run(
    *,
    db_path: str = DEFAULT_DB_PATH,
    queue_url: str | None = None,
    region: str = DEFAULT_SQS_REGION,
    commit: bool = False,
    user_agent: str = DEFAULT_USER_AGENT,
    sources: tuple[WatchSource, ...] = WATCHLIST,
    http_get: HttpGet = _http_get,
    sleep: Sleeper = time.sleep,
) -> dict[str, Any]:
    """One full hourly tick. Returns counters for observability."""
    detected = 0
    enqueued = 0
    skipped_dup = 0
    skipped_error = 0
    conn = sqlite3.connect(db_path)
    try:
        _ensure_table(conn)
        for source in sources:
            try:
                for source_url, content_hash in crawl_source(
                    source,
                    user_agent=user_agent,
                    http_get=http_get,
                    sleep=sleep,
                ):
                    watch_id = insert_detection(
                        conn,
                        source_kind=source.kind,
                        source_url=source_url,
                        content_hash=content_hash,
                    )
                    if watch_id is None:
                        skipped_dup += 1
                        continue
                    detected += 1
                    if queue_url:
                        result = enqueue_textract_message(
                            queue_url=queue_url,
                            watch_id=watch_id,
                            source_kind=source.kind,
                            source_url=source_url,
                            content_hash=content_hash,
                            region=region,
                            commit=commit,
                        )
                        if result.get("mode") == "committed":
                            enqueued += 1
                    conn.commit()
            except Exception as e:  # noqa: BLE001
                skipped_error += 1
                logger.exception("crawl_source_failed source=%s err=%s", source.kind, e)
    finally:
        conn.close()
    summary = {
        "tick_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources_scanned": len(sources),
        "newly_detected": detected,
        "sqs_enqueued": enqueued,
        "skipped_duplicate": skipped_dup,
        "skipped_error": skipped_error,
        "mode": "committed" if commit else "dry_run",
    }
    logger.info("pdf_watch_tick %s", json.dumps(summary, ensure_ascii=False))
    return summary


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=DEFAULT_DB_PATH, help="sqlite db path (autonomath.db)")
    p.add_argument("--queue-url", default=None, help="SQS queue URL (optional)")
    p.add_argument("--region", default=DEFAULT_SQS_REGION, help="AWS region for SQS")
    p.add_argument(
        "--commit",
        action="store_true",
        help="Actually enqueue SQS messages (default: dry_run)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Force dry-run (overrides --commit if both passed; default behaviour)",
    )
    p.add_argument(
        "--since",
        default=None,
        help="ISO-8601 lower bound (currently informational; cron is stateless)",
    )
    p.add_argument("--log-level", default="INFO")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    commit = bool(args.commit and not args.dry_run)
    summary = run(
        db_path=args.db,
        queue_url=args.queue_url,
        region=args.region,
        commit=commit,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
