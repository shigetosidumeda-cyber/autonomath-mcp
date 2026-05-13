#!/usr/bin/env python3
"""Wave 43.1.1 - 市町村 1,700+ subsidy ETL v2.

Walks the canonical 自治体 seed list (``data/municipalities_canonical.json``
if present, otherwise ``data/municipality_seed_urls.json``) in parallel
via httpx with concurrency 15 and Playwright fallback, extracts 補助金 /
助成金 / 融資 sections, and upserts derived rows into
``am_program_source_municipality_v2`` (migration 248) in autonomath.db.

Constraints:
* LLM calls = 0. Pure regex / sqlite3 / httpx / Playwright.
* Aggregator banlist (noukaweb / hojyokin-portal / biz.stayway / etc.).
* 1次資料 only (.lg.jp / .go.jp / metro.tokyo / pref/city/town/village.*.jp).
* Playwright fallback via scripts.etl._playwright_helper.fetch_with_fallback.
* No 9.7 GB full-scan op against autonomath.db.
* Idempotent: UNIQUE(program_id, municipality_code, source_url).

Usage:
    python scripts/etl/fill_programs_municipality_2x.py
    python scripts/etl/fill_programs_municipality_2x.py --dry-run --limit 10
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from jpintel_mcp._jpcite_env_bridge import get_flag  # noqa: E402
from scripts.etl._playwright_helper import fetch_with_fallback  # noqa: E402

logger = logging.getLogger("jpcite.etl.fill_programs_municipality_2x")

GLOBAL_CONCURRENCY = 15
HTTPX_TIMEOUT_S = 30.0
USER_AGENT = "jpcite-etl-municipality-2x/0.1 (+https://jpcite.com/cron-policy)"

AGGREGATOR_BANLIST: tuple[str, ...] = (
    "noukaweb",
    "hojyokin-portal",
    "biz.stayway",
    "stayway.jp",
    "subsidies-japan",
    "jgrant-aggregator",
    "nikkei.com",
    "prtimes.jp",
    "wikipedia.org",
)

ALLOWED_SUFFIXES: tuple[str, ...] = (".lg.jp", ".go.jp", "metro.tokyo")
ALLOWED_NETLOC_PATTERNS: tuple[str, ...] = ("pref.", "city.", "town.", "village.")

GRANT_TYPE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("補助金", "補助金"),
    ("助成金", "助成金"),
    ("融資", "融資"),
    ("貸付", "融資"),
    ("利子補給", "融資"),
)

PROGRAM_KEYWORDS = ("補助", "助成", "融資", "貸付", "支援金", "給付金")

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = _REPO_ROOT / "data" / "autonomath.db"
DEFAULT_SEED_CANONICAL = _REPO_ROOT / "data" / "municipalities_canonical.json"
DEFAULT_SEED_FALLBACK = _REPO_ROOT / "data" / "municipality_seed_urls.json"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--db",
        default=get_flag("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH", str(DEFAULT_DB_PATH)),
    )
    p.add_argument("--seed", default=None)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def is_aggregator_url(url: str) -> bool:
    """Return True if URL netloc matches any banned aggregator substring."""
    try:
        netloc = urlparse(url).netloc.lower()
    except (ValueError, AttributeError):
        return True
    if not netloc:
        return True
    return any(banned in netloc for banned in AGGREGATOR_BANLIST)


def is_allowed_municipality_url(url: str) -> bool:
    """Return True if URL netloc points at a 1次資料 自治体 domain."""
    if is_aggregator_url(url):
        return False
    try:
        netloc = urlparse(url).netloc.lower()
    except (ValueError, AttributeError):
        return False
    if not netloc:
        return False
    for suffix in ALLOWED_SUFFIXES:
        if netloc.endswith(suffix) or suffix in netloc:
            return True
    if netloc.endswith(".jp"):
        for prefix in ALLOWED_NETLOC_PATTERNS:
            if prefix in netloc:
                return True
    return False


def _resolve_seed_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    if DEFAULT_SEED_CANONICAL.exists():
        return DEFAULT_SEED_CANONICAL
    return DEFAULT_SEED_FALLBACK


def _muni_code_to_5digit(raw: str) -> str:
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 5:
        return digits
    if len(digits) == 6:
        return digits[:5]
    return ""


def _prefecture_code(muni_code5: str) -> str:
    return muni_code5[:2] if len(muni_code5) >= 2 else ""


def load_seed(path: Path) -> list[dict[str, Any]]:
    """Load and lightly validate the seed JSON."""
    if not path.exists():
        raise FileNotFoundError(f"seed JSON missing: {path}")
    with path.open("r", encoding="utf-8") as fh:
        rows = json.load(fh)
    if not isinstance(rows, list):
        raise ValueError(f"seed JSON must be a list, got {type(rows).__name__}")
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = row.get("subsidy_url") or row.get("source_url") or ""
        raw_code = str(row.get("muni_code") or row.get("municipality_code") or "")
        code5 = _muni_code_to_5digit(raw_code)
        if not url or not code5:
            continue
        if is_aggregator_url(url):
            raise ValueError(f"aggregator URL in seed (banned): {url}")
        if not is_allowed_municipality_url(url):
            logger.debug("seed row skipped (non-allowlisted netloc): %s", url)
            continue
        out.append(
            {
                "pref": row.get("pref") or "",
                "muni_code": code5,
                "muni_name": row.get("muni_name") or "",
                "muni_type": row.get("muni_type") or "regular",
                "subsidy_url": url,
            }
        )
    return out


_SECTION_RX = re.compile(
    r"(?P<title>[^\n\r]{4,120}?(?:補助金|助成金|融資|貸付|利子補給))",
)


def classify_grant_type(text: str) -> str:
    """Return one of {'補助金','助成金','融資','その他'} for a snippet."""
    for needle, grant in GRANT_TYPE_PATTERNS:
        if needle in text:
            return grant
    return "その他"


def looks_like_program(text: str) -> bool:
    return any(kw in text for kw in PROGRAM_KEYWORDS)


def extract_programs(body: str, source_url: str) -> list[dict[str, str]]:
    """Pull candidate program rows from an already-fetched page body."""
    if not body or not looks_like_program(body):
        return []
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for m in _SECTION_RX.finditer(body):
        title = m.group("title").strip()
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title, "grant_type": classify_grant_type(title)})
        if len(out) >= 50:
            break
    _ = source_url
    return out


def derive_program_id(municipality_code: str, source_url: str, title: str) -> str:
    """Compute a stable, reproducible program_id."""
    h = hashlib.sha256(f"{source_url}|{title}".encode()).hexdigest()[:10]
    return f"muni:{municipality_code}:{h}"


def _open_db(path: str, *, allow_missing: bool = False) -> sqlite3.Connection:
    p = Path(path)
    if not p.exists():
        if allow_missing:
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(p))
            conn.row_factory = sqlite3.Row
            return conn
        raise FileNotFoundError(f"autonomath.db missing: {p}")
    conn = sqlite3.connect(str(p), timeout=30.0)
    conn.execute("PRAGMA busy_timeout=300000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    # CRITICAL: never quick_check a 9.7 GB DB at boot.
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    mig = _REPO_ROOT / "scripts" / "migrations" / "248_program_source_municipality_v2.sql"
    if mig.exists():
        conn.executescript(mig.read_text(encoding="utf-8"))


def _upsert_bridge(
    conn: sqlite3.Connection,
    *,
    program_id: str,
    municipality_code: str,
    grant_type: str,
    prefecture_code: str,
    source_url: str,
    fetched_at: str,
) -> str:
    cur = conn.execute(
        "SELECT id FROM am_program_source_municipality_v2 "
        " WHERE program_id = ? AND municipality_code = ? AND source_url = ?",
        (program_id, municipality_code, source_url),
    )
    row = cur.fetchone()
    if row:
        conn.execute(
            "UPDATE am_program_source_municipality_v2 "
            "   SET last_verified = ?, grant_type = ? WHERE id = ?",
            (fetched_at, grant_type, row["id"]),
        )
        return "updated"
    conn.execute(
        "INSERT INTO am_program_source_municipality_v2 "
        "  (program_id, municipality_code, grant_type, prefecture_code, "
        "   source_url, source_fetched_at, last_verified) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            program_id,
            municipality_code,
            grant_type,
            prefecture_code,
            source_url,
            fetched_at,
            fetched_at,
        ),
    )
    return "inserted"


async def _process_one(
    seed_row: dict[str, Any],
    *,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    url = seed_row["subsidy_url"]
    out: dict[str, Any] = {
        "muni_code": seed_row["muni_code"],
        "pref_code": _prefecture_code(seed_row["muni_code"]),
        "subsidy_url": url,
        "candidates": [],
        "error": None,
    }
    if is_aggregator_url(url):
        out["error"] = "aggregator_refused"
        return out
    async with semaphore:
        try:
            result = await fetch_with_fallback(url, timeout_s=HTTPX_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001
            out["error"] = f"fetch_exception:{type(exc).__name__}"
            return out
    if not result or not result.text:
        out["error"] = result.error if result else "fetch_empty"
        return out
    out["candidates"] = extract_programs(result.text, url)
    return out


async def run_async(args: argparse.Namespace) -> int:
    seed_path = _resolve_seed_path(args.seed)
    try:
        seed_rows = load_seed(seed_path)
    except ValueError as exc:
        logger.error("seed guardrail violation: %s", exc)
        return 2
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1
    if args.limit and args.limit > 0:
        seed_rows = seed_rows[: args.limit]
    logger.info("seed: %s rows from %s", len(seed_rows), seed_path)

    started = datetime.now(UTC).isoformat()
    sem = asyncio.Semaphore(GLOBAL_CONCURRENCY)
    tasks = [_process_one(r, semaphore=sem) for r in seed_rows]
    results = await asyncio.gather(*tasks)

    inserted = 0
    updated = 0
    refused = 0
    errors = 0
    program_rows: list[dict[str, str]] = []
    for res in results:
        if res["error"] == "aggregator_refused":
            refused += 1
            continue
        if res["error"]:
            errors += 1
            continue
        muni = res["muni_code"]
        pref = res["pref_code"]
        url = res["subsidy_url"]
        for cand in res["candidates"]:
            pid = derive_program_id(muni, url, cand["title"])
            program_rows.append(
                {
                    "program_id": pid,
                    "municipality_code": muni,
                    "grant_type": cand["grant_type"],
                    "prefecture_code": pref,
                    "source_url": url,
                }
            )

    if args.dry_run:
        logger.info("DRY RUN - %s bridge rows", len(program_rows))
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "municipalities_seen": len(seed_rows),
                    "bridge_rows_candidate": len(program_rows),
                    "aggregator_refused": refused,
                    "fetch_errors": errors,
                },
                ensure_ascii=False,
            )
        )
        return 0

    fetched_at = datetime.now(UTC).isoformat()
    conn = _open_db(args.db, allow_missing=True)
    try:
        _ensure_schema(conn)
        with conn:
            for row in program_rows:
                outcome = _upsert_bridge(conn, fetched_at=fetched_at, **row)
                if outcome == "inserted":
                    inserted += 1
                else:
                    updated += 1
            conn.execute(
                "INSERT INTO am_program_source_municipality_v2_run_log "
                "  (started_at, finished_at, municipalities_seen, "
                "   programs_inserted, programs_updated, aggregator_refused, "
                "   fetch_errors, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    started,
                    fetched_at,
                    len(seed_rows),
                    inserted,
                    updated,
                    refused,
                    errors,
                    "wave43_1_1",
                ),
            )
    finally:
        conn.close()

    logger.info(
        "done: inserted=%s updated=%s refused=%s errors=%s", inserted, updated, refused, errors
    )
    print(
        json.dumps(
            {
                "dry_run": False,
                "municipalities_seen": len(seed_rows),
                "bridge_rows_inserted": inserted,
                "bridge_rows_updated": updated,
                "aggregator_refused": refused,
                "fetch_errors": errors,
            },
            ensure_ascii=False,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        level=logging.DEBUG if args.verbose else logging.INFO,
    )
    started_at = time.monotonic()
    try:
        rc = asyncio.run(run_async(args))
    except KeyboardInterrupt:
        return 130
    elapsed = time.monotonic() - started_at
    logger.info("elapsed: %.2fs", elapsed)
    return rc


if __name__ == "__main__":
    sys.exit(main())
