#!/usr/bin/env python3
"""ingest_law_articles_egov.py — Ingest e-Gov 法令 API v2 articles into am_law_article.

Idempotent UPSERT (UNIQUE law_canonical_id, article_number).
Parallel-safe: BEGIN IMMEDIATE + busy_timeout=300000.

NO Anthropic API. NO LLM. e-Gov XML parse only.

Usage:
    .venv/bin/python scripts/ingest/ingest_law_articles_egov.py \\
        --egov-law-id 340AC0000000034 \\
        --canonical-id law:corporate-tax

    .venv/bin/python scripts/ingest/ingest_law_articles_egov.py \\
        --egov-law-id 340AC0000000034 \\
        --canonical-id law:corporate-tax \\
        --dry-run
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

try:
    import requests
except ImportError as exc:
    print(f"missing dep: {exc}. pip install requests", file=sys.stderr)
    sys.exit(1)


_LOG = logging.getLogger("ingest_law_articles_egov")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "autonomath.db"

BASE_URL = "https://laws.e-gov.go.jp/api/2"
USER_AGENT = "AutonoMath/0.1.0 (+https://jpcite.com)"
HTTP_TIMEOUT = 180
MAX_RETRIES = 3

ATTRIBUTION = "出典: e-Gov法令検索 (デジタル庁)"


def fetch_law_xml(law_id: str) -> bytes:
    """Fetch law XML from e-Gov v2 lawdata endpoint."""
    url = f"{BASE_URL}/law_data/{law_id}"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/xml"}
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
        except requests.RequestException as exc:
            _LOG.warning("fetch_error url=%s attempt=%d err=%s", url, attempt, exc)
            last_err = exc
            if attempt == MAX_RETRIES:
                raise
            time.sleep(2**attempt)
            continue

        if resp.status_code == 200:
            return resp.content
        if resp.status_code == 404:
            raise FileNotFoundError(f"law_id {law_id} not found (404)")
        if 500 <= resp.status_code < 600:
            _LOG.warning("fetch_5xx url=%s attempt=%d status=%d", url, attempt, resp.status_code)
            last_err = RuntimeError(f"5xx {resp.status_code}")
            if attempt == MAX_RETRIES:
                raise last_err
            time.sleep(2**attempt)
            continue
        raise RuntimeError(f"client error {resp.status_code}: {resp.text[:200]}")

    raise RuntimeError(f"fetch loop exhausted: {last_err}")


def article_num_to_sort(num_str: str) -> float:
    """'42_12_7' -> 42.012007, '1' -> 1.0, '1_2' -> 1.002 (monotonic)."""
    if not num_str:
        return 0.0
    parts = num_str.split("_")
    try:
        main = int(parts[0])
    except (ValueError, IndexError):
        return 0.0
    sort_val = float(main)
    for i, p in enumerate(parts[1:]):
        with contextlib.suppress(ValueError):
            sort_val += int(p) * (10 ** (-3 * (i + 1)))
    return sort_val


def text_recursive(elem: ET.Element) -> str:
    """Concatenate all text nodes in element subtree."""
    parts: list[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        parts.append(text_recursive(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def parse_articles(xml_bytes: bytes) -> list[dict]:
    """Parse e-Gov XML and extract <Article> elements at any depth.

    Tested on:
      - 本則 (法人税法/所得税法/etc): MainProvision > Chapter > Section > Article
      - 施行令/施行規則: same pattern
      - 附則: SupplProvision > Article
    """
    root = ET.fromstring(xml_bytes)  # nosec B314 - input is trusted gov-source XML; not user-supplied
    articles: list[dict] = []
    seen_nums: set[str] = set()
    for art in root.iter("Article"):
        num = art.get("Num")
        if not num:
            continue
        # Some addendum (附則) blocks repeat Num across separate SupplProvision
        # contexts. Track ancestor SupplProvision to disambiguate.
        # If inside SupplProvision, suffix article_number with _suppl<idx>
        # heuristic: walk ancestors via XPath-like (lxml not avail), so we
        # look for a closest SupplProvision attribute match using ET parent map.
        # ET has no parent ref; build once per call.
        if not hasattr(parse_articles, "_parent_map_cache"):
            parse_articles._parent_map_cache = None  # type: ignore
        # We don't compute parent map for performance; the dedupe relies on
        # uniqueness of (Num) within main + having additional articles in
        # 附則 typically with separate Num spaces. e-Gov XML uses Num="1"
        # inside SupplProvision attributes <SupplProvision AmendLawNum="...">,
        # which are scoped — we suffix with hash of containing block to dedupe.
        if num in seen_nums:
            # collision (likely 附則): suffix with sequential
            suffix = 2
            new_num = f"{num}_附{suffix}"
            while new_num in seen_nums:
                suffix += 1
                new_num = f"{num}_附{suffix}"
            num_final = new_num
        else:
            num_final = num
        seen_nums.add(num_final)

        title_el = art.find("ArticleTitle")
        article_title = (title_el.text or "").strip() if title_el is not None else ""
        caption_el = art.find("ArticleCaption")
        caption = (caption_el.text or "").strip() if caption_el is not None else ""
        title_combined = caption or article_title

        full_text = text_recursive(art).strip()
        full_text = re.sub(r"[ \t\r\n　]+", " ", full_text)

        articles.append(
            {
                "article_number": num_final,
                "article_number_sort": article_num_to_sort(num_final.split("_附")[0]),
                "title": title_combined,
                "text_full": full_text,
            }
        )
    return articles


def upsert_article(
    con: sqlite3.Connection,
    canonical_id: str,
    art: dict,
    source_url: str,
    fetched_at: str,
    article_kind: str = "main",
) -> None:
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute(
            """
            INSERT INTO am_law_article (
                law_canonical_id, article_number, article_number_sort,
                title, text_summary, text_full,
                source_url, source_fetched_at, article_kind
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(law_canonical_id, article_number) DO UPDATE SET
                article_number_sort = excluded.article_number_sort,
                title = excluded.title,
                text_summary = excluded.text_summary,
                text_full = excluded.text_full,
                source_url = excluded.source_url,
                source_fetched_at = excluded.source_fetched_at,
                article_kind = excluded.article_kind
        """,
            (
                canonical_id,
                art["article_number"],
                art["article_number_sort"],
                art["title"],
                art["text_full"][:500],
                art["text_full"],
                source_url,
                fetched_at,
                article_kind,
            ),
        )
        con.commit()
    except Exception:
        con.rollback()
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest e-Gov law articles into am_law_article")
    parser.add_argument("--egov-law-id", required=True, help="e-Gov law_id (e.g. 340AC0000000034)")
    parser.add_argument(
        "--canonical-id", required=True, help="am_law canonical_id (e.g. law:corporate-tax)"
    )
    parser.add_argument(
        "--db", default=str(DEFAULT_DB), help="SQLite path (default: autonomath.db)"
    )
    parser.add_argument(
        "--article-kind",
        default="main",
        choices=(
            "main",
            "suppl",
            "enforcement_order",
            "enforcement_regulation",
            "tsutatsu",
            "notice",
            "guideline",
            "appendix",
        ),
        help="article_kind label (default: main)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no write")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    print(f"[ingest_law_articles_egov] law_id={args.egov_law_id} canonical_id={args.canonical_id}")
    t0 = time.time()
    xml_bytes = fetch_law_xml(args.egov_law_id)
    t_fetch = time.time() - t0
    print(f"[fetch] {len(xml_bytes)} bytes in {t_fetch:.1f}s")

    t1 = time.time()
    articles = parse_articles(xml_bytes)
    t_parse = time.time() - t1
    print(f"[parse] {len(articles)} articles in {t_parse:.1f}s")

    if not articles:
        print("[ERROR] no articles parsed; check XML schema or law_id", file=sys.stderr)
        # Dump first 500 bytes for debug
        try:
            print("=== xml head ===", file=sys.stderr)
            print(xml_bytes[:500].decode("utf-8", errors="replace"), file=sys.stderr)
        except Exception:
            pass
        sys.exit(2)

    if args.dry_run:
        for art in articles[:5]:
            print(
                f"  num={art['article_number']:<15} title={art['title'][:30]:<30} text_len={len(art['text_full'])}"
            )
        print(f"[dry-run] would upsert {len(articles)} articles")
        return

    fetched_at = datetime.now(UTC).isoformat()
    con = sqlite3.connect(args.db, timeout=300)
    con.execute("PRAGMA busy_timeout = 300000")

    initial = con.execute(
        "SELECT COUNT(*) FROM am_law_article WHERE law_canonical_id=?", (args.canonical_id,)
    ).fetchone()[0]

    inserted = 0
    failed: list[tuple[str, str]] = []
    t2 = time.time()
    for art in articles:
        source_url = (
            f"https://laws.e-gov.go.jp/law/{args.egov_law_id}#Mp-At_{art['article_number']}"
        )
        try:
            upsert_article(
                con,
                args.canonical_id,
                art,
                source_url,
                fetched_at,
                article_kind=args.article_kind,
            )
            inserted += 1
        except Exception as e:
            failed.append((art["article_number"], str(e)))
    t_write = time.time() - t2

    final = con.execute(
        "SELECT COUNT(*) FROM am_law_article WHERE law_canonical_id=?", (args.canonical_id,)
    ).fetchone()[0]
    con.close()

    elapsed = time.time() - t0
    print("=== done ===")
    print(f"canonical_id: {args.canonical_id}")
    print(f"initial -> final: {initial} -> {final} (delta {final - initial})")
    print(f"upserted: {inserted}")
    print(f"failed: {len(failed)}")
    print(
        f"timings: fetch={t_fetch:.1f}s parse={t_parse:.1f}s write={t_write:.1f}s total={elapsed:.1f}s"
    )
    if failed:
        print("failed list (first 20):")
        for fn, fe in failed[:20]:
            print(f"  {fn}: {fe}")


if __name__ == "__main__":
    main()
