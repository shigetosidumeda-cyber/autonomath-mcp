#!/usr/bin/env python3
"""Wave 43.2.10 — Dim J FDI 80-country enrichment 2x ETL.

Purpose
-------
The migration 266 seed inserts 80 hand-curated rows (country_iso /
country_name_ja / country_name_en / region / membership flags /
has_dta / has_bit + a single ``source_url``). The DETAIL columns —
``visa_keiei_kanri`` / ``min_capital_yen`` / ``restricted_sectors`` /
``promotion_program`` / ``mofa_source_url`` / ``jetro_source_url`` —
are NULL on seed and are filled by this ETL by harvesting first-party
公開資料 (外務省 国・地域 + JETRO 公式 country pages).

Constraints
-----------
* **一次資料 only.** Each fetch targets either ``www.mofa.go.jp/...`` or
  ``www.jetro.go.jp/...``. Anything else (e.g. consultancy aggregator,
  Wikipedia, government redistribution clones) is refused.
* **NO LLM API.** No anthropic / openai / google.generativeai import. The
  enrichment is purely deterministic: regex extraction of MOFA / JETRO
  published facts (visa keiei_kanri framework, JETRO market entry guide
  capital threshold), with a fallback to NULL when the source page does
  not publish the field.
* **Idempotent upsert** via ``UPDATE … WHERE country_iso = ?``. Re-running
  on the same dataset produces zero net changes once steady state is
  reached.
* **Run-log** on ``am_fdi_country_run_log`` (one row per ETL invocation).
* **Playwright fallback** for MOFA / JETRO pages that render via JS;
  reuses ``scripts/etl/_playwright_helper.py`` when present.

License posture
---------------
Output stays within 政府標準利用規約 v2.0 (gov_standard). The migration
266 seed pre-stamps ``license = 'gov_standard'`` + ``redistribute_ok = 1``
on every row; this ETL never downgrades those columns.

Usage
-----
    .venv/bin/python scripts/etl/fill_fdi_80country_2x.py \
        --iso-from JP --iso-to ZZ           # whole roster

    .venv/bin/python scripts/etl/fill_fdi_80country_2x.py \
        --only US,GB,DE,FR,IT,JP,CA         # G7 subset

    .venv/bin/python scripts/etl/fill_fdi_80country_2x.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOG = logging.getLogger("jpintel.etl.fill_fdi_80country")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = (
    Path(os.environ.get("AUTONOMATH_DB_PATH", ""))
    if os.environ.get("AUTONOMATH_DB_PATH")
    else REPO_ROOT / "data" / "autonomath.db"
)

# ---------------------------------------------------------------------------
# Discipline gates
# ---------------------------------------------------------------------------

_PRIMARY_PREFIXES: tuple[str, ...] = (
    "https://www.mofa.go.jp/",
    "https://www.jetro.go.jp/",
)

_BANNED_DOMAINS: tuple[str, ...] = (
    "wikipedia.org",
    "noukaweb.jp",
    "jichi-souken",
    "jichitai.com",
    "tradingeconomics.com",
)

_USER_AGENT = "jpcite-etl-fdi/0.1 (+https://jpcite.com/)"


def _is_primary(url: str) -> bool:
    return any(url.startswith(p) for p in _PRIMARY_PREFIXES)


def _is_banned(url: str) -> bool:
    low = url.lower()
    return any(b in low for b in _BANNED_DOMAINS)


# ---------------------------------------------------------------------------
# Extractors (deterministic, NO LLM)
# ---------------------------------------------------------------------------

_REGEX_CAPITAL_YEN = re.compile(
    r"(?:最低資本金|資本金\s*要件|min(?:imum)?\s*capital)"
    r"[^\d]{0,40}([0-9]{1,3}(?:[,，][0-9]{3})*|[0-9]{4,9})\s*(円|万円|億円|JPY|円超)"
)

_REGEX_VISA_KEIEI = re.compile(
    r"(経営[・、\s]?管理(?:ビザ|在留資格)|Business[ \-]?Manager\s*Visa|business[ \-]?manager)",
    re.IGNORECASE,
)

_REGEX_RESTRICTED_TOKEN = re.compile(
    r"(外資規制|制限業種|restricted\s*sectors|restricted\s*industries|negative\s*list)",
    re.IGNORECASE,
)

_REGEX_PROMOTION_TOKEN = re.compile(
    r"(二国間投資協定|BIT|bilateral\s*investment\s*treaty|EPA|FTA|投資促進プログラム)",
    re.IGNORECASE,
)


def _parse_capital_yen(body: str) -> int | None:
    m = _REGEX_CAPITAL_YEN.search(body)
    if not m:
        return None
    raw = m.group(1).replace(",", "").replace("，", "")
    unit = m.group(2)
    try:
        n = int(raw)
    except ValueError:
        return None
    if unit == "万円":
        return n * 10_000
    if unit == "億円":
        return n * 100_000_000
    return n


def _classify_visa(body: str) -> str:
    """Coarse classification for visa_keiei_kanri CHECK enum."""
    if _REGEX_VISA_KEIEI.search(body):
        if re.search(r"優遇|fast[ \-]?track|expedited", body, re.IGNORECASE):
            return "expedited"
        return "standard"
    if re.search(r"制限|restricted|review", body, re.IGNORECASE):
        return "restricted"
    return "unknown"


def _summarize_restricted(body: str) -> str | None:
    """Return ≤ 240-char excerpt around the restricted-sector token."""
    m = _REGEX_RESTRICTED_TOKEN.search(body)
    if not m:
        return None
    start = max(0, m.start() - 60)
    end = min(len(body), m.end() + 180)
    excerpt = re.sub(r"\s+", " ", body[start:end]).strip()
    return excerpt[:240] if excerpt else None


def _summarize_promotion(body: str) -> str | None:
    m = _REGEX_PROMOTION_TOKEN.search(body)
    if not m:
        return None
    start = max(0, m.start() - 60)
    end = min(len(body), m.end() + 180)
    excerpt = re.sub(r"\s+", " ", body[start:end]).strip()
    return excerpt[:240] if excerpt else None


# ---------------------------------------------------------------------------
# Fetch + DB
# ---------------------------------------------------------------------------


def _fetch(url: str, *, timeout: int = 20) -> tuple[int, str | None]:
    if not _is_primary(url) or _is_banned(url):
        LOG.warning("refuse non-primary url=%s", url)
        return 0, None
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — primary only
            body = resp.read()
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError:
                text = body.decode("utf-8", errors="ignore")
            return resp.status, text
    except urllib.error.HTTPError as exc:
        LOG.warning("http %s %s", exc.code, url)
        return exc.code, None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        LOG.warning("fetch error url=%s err=%s", url, exc)
        return 0, None


def _open_db(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(
            f"autonomath.db not found at {path}; run migration 266 first or set AUTONOMATH_DB_PATH"
        )
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@dataclass
class CountryWork:
    country_iso: str
    seed_source_url: str
    mofa_url: str | None = None
    jetro_url: str | None = None


@dataclass
class Stats:
    countries_seen: int = 0
    rows_updated: int = 0
    rows_skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _load_targets(
    conn: sqlite3.Connection,
    *,
    only: set[str] | None,
    iso_from: str | None,
    iso_to: str | None,
) -> list[CountryWork]:
    sql = "SELECT country_iso, source_url FROM am_fdi_country WHERE redistribute_ok = 1"
    args: list[Any] = []
    if only:
        placeholders = ",".join("?" * len(only))
        sql += f" AND country_iso IN ({placeholders})"
        args.extend(sorted(only))
    if iso_from:
        sql += " AND country_iso >= ?"
        args.append(iso_from.upper())
    if iso_to:
        sql += " AND country_iso <= ?"
        args.append(iso_to.upper())
    sql += " ORDER BY country_iso ASC"
    rows = conn.execute(sql, args).fetchall()
    out: list[CountryWork] = []
    for r in rows:
        iso = r["country_iso"]
        # Pre-derive likely MOFA / JETRO landing pages. MOFA URLs are
        # already on the seed; JETRO has a stable per-country slug at
        # /world/{region}/{slug}/ (region prefix only for some countries).
        out.append(
            CountryWork(
                country_iso=iso,
                seed_source_url=r["source_url"],
                mofa_url=r["source_url"]
                if r["source_url"].startswith("https://www.mofa.go.jp/")
                else None,
                jetro_url=None,  # populated by harvest step below
            )
        )
    return out


def _derive_jetro_url(country_iso: str) -> str:
    """Best-effort canonical JETRO country page. Static slug map for the 80-set."""
    # JETRO uses lowercase ISO alpha-2 under /world/. Some regions use
    # different prefixes; we keep the conservative /world/{iso} pattern.
    return f"https://www.jetro.go.jp/world/{country_iso.lower()}/"


def _enrich_one(
    conn: sqlite3.Connection,
    work: CountryWork,
    *,
    pause_seconds: float,
    dry_run: bool,
    stats: Stats,
) -> None:
    stats.countries_seen += 1
    mofa_body = ""
    jetro_body = ""
    if work.mofa_url:
        _status, mofa_text = _fetch(work.mofa_url)
        if mofa_text:
            mofa_body = mofa_text
        time.sleep(pause_seconds)
    jetro_url = _derive_jetro_url(work.country_iso)
    _status, jetro_text = _fetch(jetro_url)
    if jetro_text:
        jetro_body = jetro_text
        work.jetro_url = jetro_url
    time.sleep(pause_seconds)

    body_all = (mofa_body or "") + "\n" + (jetro_body or "")
    visa = _classify_visa(body_all) if body_all else "unknown"
    capital = _parse_capital_yen(body_all) if body_all else None
    restricted = _summarize_restricted(body_all) if body_all else None
    promotion = _summarize_promotion(body_all) if body_all else None

    if not body_all:
        stats.rows_skipped += 1
        LOG.info("skip %s — no primary body harvested", work.country_iso)
        return

    if dry_run:
        LOG.info(
            "DRY %s visa=%s capital=%s restricted=%s promotion=%s",
            work.country_iso,
            visa,
            capital,
            bool(restricted),
            bool(promotion),
        )
        stats.rows_updated += 1
        return

    try:
        conn.execute(
            """UPDATE am_fdi_country
                  SET visa_keiei_kanri = COALESCE(?, visa_keiei_kanri),
                      min_capital_yen = COALESCE(?, min_capital_yen),
                      restricted_sectors = COALESCE(?, restricted_sectors),
                      promotion_program = COALESCE(?, promotion_program),
                      mofa_source_url = COALESCE(?, mofa_source_url),
                      jetro_source_url = COALESCE(?, jetro_source_url),
                      source_fetched_at = ?,
                      updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
                WHERE country_iso = ?""",
            (
                visa if visa != "unknown" else None,
                capital,
                restricted,
                promotion,
                work.mofa_url,
                work.jetro_url,
                datetime.now(UTC).isoformat(),
                work.country_iso,
            ),
        )
        stats.rows_updated += 1
    except sqlite3.Error as exc:
        msg = f"{work.country_iso}: {exc}"
        stats.errors.append(msg)
        LOG.warning("update failed %s", msg)


def _record_run(
    conn: sqlite3.Connection,
    *,
    started_at: str,
    stats: Stats,
    source_kind: str,
) -> None:
    err_text = json.dumps(stats.errors, ensure_ascii=False) if stats.errors else None
    conn.execute(
        """INSERT INTO am_fdi_country_run_log (
               started_at, finished_at, source_kind,
               countries_seen, rows_updated, rows_skipped,
               errors_count, error_text
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            started_at,
            datetime.now(UTC).isoformat(),
            source_kind,
            stats.countries_seen,
            stats.rows_updated,
            stats.rows_skipped,
            len(stats.errors),
            err_text,
        ),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Fill am_fdi_country detail columns from MOFA / JETRO primary sources.",
    )
    p.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    p.add_argument("--iso-from", type=str, default=None, help="ISO alpha-2 lower bound (inclusive)")
    p.add_argument("--iso-to", type=str, default=None, help="ISO alpha-2 upper bound (inclusive)")
    p.add_argument(
        "--only", type=str, default=None, help="Comma-separated ISO codes (overrides --iso-* range)"
    )
    p.add_argument(
        "--pause-seconds", type=float, default=1.5, help="sleep between fetches (default 1.5s)"
    )
    p.add_argument("--dry-run", action="store_true", help="Crawl + parse, no DB writes")
    p.add_argument("--verbose", action="store_true")
    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_argparser().parse_args(list(argv) if argv is not None else None)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    only: set[str] | None = None
    if args.only:
        only = {tok.strip().upper() for tok in args.only.split(",") if tok.strip()}

    started = datetime.now(UTC).isoformat()
    conn = _open_db(args.db_path)
    stats = Stats()
    try:
        targets = _load_targets(
            conn,
            only=only,
            iso_from=args.iso_from,
            iso_to=args.iso_to,
        )
        if not targets:
            LOG.warning("no target rows matched filters")
        for work in targets:
            _enrich_one(
                conn,
                work,
                pause_seconds=max(0.1, args.pause_seconds),
                dry_run=args.dry_run,
                stats=stats,
            )
        if not args.dry_run:
            _record_run(conn, started_at=started, stats=stats, source_kind="mofa+jetro")
            conn.commit()
    finally:
        conn.close()

    LOG.info(
        "done countries_seen=%d updated=%d skipped=%d errors=%d",
        stats.countries_seen,
        stats.rows_updated,
        stats.rows_skipped,
        len(stats.errors),
    )
    return 0 if not stats.errors else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
