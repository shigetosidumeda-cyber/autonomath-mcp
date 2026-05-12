#!/usr/bin/env python3
"""Wave 43.1.3: 民間助成財団 2,000+ 助成プログラム ETL.

Source discipline (non-negotiable, memory `feedback_no_fake_data`)
-----------------------------------------------------------------
* 公益財団協会 https://www.koeki-info.go.jp/ — 公益法人 information
  site authoritative on 公益財団 listings.
* 各 公益財団 official sites — primary domain only:
    - トヨタ財団 https://www.toyotafound.or.jp/
    - サントリー文化財団 https://www.suntory.co.jp/sfnd/
    - SOMPO 環境財団 https://www.sompo-ef.org/
    - 大林財団 https://obayashifoundation.or.jp/
    - 三菱財団 https://www.mitsubishi-zaidan.jp/
    - 日産財団 https://www.nissan-zaidan.or.jp/
    - 旭硝子財団 https://www.af-info.or.jp/
    - 公益財団法人かめのり財団 https://www.kamenori.jp/
    - 中島記念国際交流財団 https://www.nakajimafound.or.jp/
    - 公益財団法人野村財団 https://www.nomurafoundation.or.jp/
* 内閣府 NPO 公開資料 — NPO 認証 master list.
* 業界団体 — 経団連 / 商工会議所 / 同友会 公式 grant pages.

Aggregator domains BANNED:
* 助成財団検索サイト (jfc.or.jp 等の 検索サイト)
* hojyokin-portal.com
* 助成団体検索ナビ
* dataprivacy.jp, accessshop.jp, biz.stayway, noukaweb.com

CLAUDE.md / memory constraints
------------------------------
* NO LLM call — pure HTML/JSON regex + stdlib.
* NO `claude_agent_sdk` / `anthropic` / `openai` / `google.generativeai`.
* Memory `feedback_no_operator_llm_api` strictly honored.
* NO `PRAGMA quick_check` / `integrity_check` on 9.7 GB autonomath.db.
* Idempotent — INSERT OR REPLACE on (foundation_name, grant_program_name)
  unique tuple. Re-runs safe.
* Playwright fallback wire — for sites that defeat urllib (JS-rendered).

Usage
-----
    python scripts/etl/fill_programs_foundation_2x.py --dry-run
    python scripts/etl/fill_programs_foundation_2x.py --source koeki_info --max-rows 500
    python scripts/etl/fill_programs_foundation_2x.py --source all
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import re
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jpintel_mcp._jpcite_env_bridge import get_flag

logger = logging.getLogger("jpcite.etl.fill_programs_foundation_2x")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "autonomath.db"

KOEKI_BASE = "https://www.koeki-info.go.jp"
CABINET_NPO_BASE = "https://www.npo-homepage.go.jp"

# Curated 公益財団 official site list — primary domain only.
OFFICIAL_FOUNDATION_SITES: list[dict[str, str]] = [
    {"name": "公益財団法人トヨタ財団", "url": "https://www.toyotafound.or.jp/grant/", "type": "公益財団"},
    {"name": "公益財団法人サントリー文化財団", "url": "https://www.suntory.co.jp/sfnd/", "type": "公益財団"},
    {"name": "公益財団法人SOMPO環境財団", "url": "https://www.sompo-ef.org/", "type": "公益財団"},
    {"name": "公益財団法人大林財団", "url": "https://obayashifoundation.or.jp/", "type": "公益財団"},
    {"name": "公益財団法人三菱財団", "url": "https://www.mitsubishi-zaidan.jp/", "type": "公益財団"},
    {"name": "公益財団法人日産財団", "url": "https://www.nissan-zaidan.or.jp/", "type": "公益財団"},
    {"name": "公益財団法人旭硝子財団", "url": "https://www.af-info.or.jp/", "type": "公益財団"},
    {"name": "公益財団法人かめのり財団", "url": "https://www.kamenori.jp/", "type": "公益財団"},
    {"name": "公益財団法人中島記念国際交流財団", "url": "https://www.nakajimafound.or.jp/", "type": "公益財団"},
    {"name": "公益財団法人野村財団", "url": "https://www.nomurafoundation.or.jp/", "type": "公益財団"},
    {"name": "公益財団法人住友財団", "url": "https://www.sumitomo.or.jp/", "type": "公益財団"},
    {"name": "公益財団法人カシオ科学振興財団", "url": "https://casiozaidan.org/", "type": "公益財団"},
    {"name": "公益財団法人キヤノン財団", "url": "https://canon-foundation.jp/", "type": "公益財団"},
    {"name": "公益財団法人セコム科学技術振興財団", "url": "https://www.secomzaidan.jp/", "type": "公益財団"},
    {"name": "公益財団法人ホクト生物科学振興財団", "url": "https://hokto-foundation.jp/", "type": "公益財団"},
    {"name": "公益財団法人かんぽ財団", "url": "https://www.kampozaidan.or.jp/", "type": "公益財団"},
    {"name": "公益財団法人前川報恩会", "url": "https://www.mayekawa-houon.or.jp/", "type": "公益財団"},
    {"name": "公益財団法人パブリックリソース財団", "url": "https://www.public.or.jp/", "type": "公益財団"},
    {"name": "公益財団法人ヤマト福祉財団", "url": "https://www.yamato-fukushi.jp/", "type": "公益財団"},
    {"name": "公益財団法人福武教育文化振興財団", "url": "https://fukutake-foundation.jp/", "type": "公益財団"},
]

UA = "AutonoMath/0.3.5 jpcite-etl (+https://bookyou.net; info@bookyou.net)"
DEFAULT_TIMEOUT = 30
DEFAULT_DELAY = 2.0

# Aggregator domains banned per CLAUDE.md.
BANNED_HOSTS: frozenset[str] = frozenset(
    {
        "hojyokin-portal.com",
        "noukaweb.com",
        "biz.stayway",
        "accessshop.jp",
        "dataprivacy.jp",
        "助成財団検索",
        "助成団体検索ナビ",
    }
)

# Closed enum mirroring migration 250 CHECK constraints.
_VALID_FOUNDATION_TYPES: frozenset[str] = frozenset(
    {"公益財団", "一般財団", "NPO", "業界団体"}
)
_VALID_DONATION_CATEGORIES: frozenset[str] = frozenset(
    {"specified_public_interest", "public_interest", "general", "unknown"}
)
_VALID_SOURCE_KINDS: frozenset[str] = frozenset(
    {"koeki_info", "official_site", "cabinet_npo", "gyokai_dantai", "other"}
)

# Grant-theme keyword normalization. Maps free-text fragments into canonical
# themes for downstream filtering.
_THEME_KEYWORDS: dict[str, list[str]] = {
    "研究": ["研究", "学術", "サイエンス", "科学技術", "学術助成"],
    "環境": ["環境", "脱炭素", "GX", "生物多様性", "自然", "気候"],
    "国際交流": ["国際", "国際交流", "海外", "グローバル", "留学"],
    "福祉": ["福祉", "高齢", "障害", "介護", "ボランティア"],
    "教育": ["教育", "教員", "奨学", "学校", "学生"],
    "文化": ["文化", "芸術", "音楽", "美術", "演劇"],
    "地域": ["地域", "コミュニティ", "町づくり", "まちづくり", "地方創生"],
    "防災": ["防災", "復興", "震災", "減災"],
    "医療": ["医療", "看護", "保健", "公衆衛生"],
}

try:
    import certifi

    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #


def _configure_logging(verbose: bool = False) -> None:
    root = logging.getLogger("jpcite.etl.fill_programs_foundation_2x")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


# --------------------------------------------------------------------------- #
# DB helpers
# --------------------------------------------------------------------------- #


def _db_path() -> Path:
    raw = get_flag("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH")
    return Path(raw) if raw else DEFAULT_DB_PATH


def _open_rw(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-65536")
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Idempotent CREATEs mirroring migration 250 — safe re-run."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS am_program_private_foundation (
              foundation_id           INTEGER PRIMARY KEY AUTOINCREMENT,
              foundation_name         TEXT NOT NULL,
              foundation_type         TEXT NOT NULL,
              grant_program_name      TEXT,
              grant_amount_range      TEXT,
              grant_theme             TEXT,
              donation_category       TEXT NOT NULL DEFAULT 'unknown',
              application_period_json TEXT,
              source_url              TEXT,
              source_kind             TEXT,
              notes                   TEXT,
              refreshed_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_am_foundation_type "
        "ON am_program_private_foundation(foundation_type, refreshed_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_am_foundation_theme "
        "ON am_program_private_foundation(grant_theme) "
        "WHERE grant_theme IS NOT NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_am_foundation_donation "
        "ON am_program_private_foundation(donation_category, foundation_type)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_am_foundation_program "
        "ON am_program_private_foundation("
        "  foundation_name,"
        "  COALESCE(grant_program_name, '_unnamed')"
        ")"
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS am_program_private_foundation_ingest_log (
              ingest_id INTEGER PRIMARY KEY AUTOINCREMENT,
              started_at TEXT NOT NULL,
              finished_at TEXT,
              rows_seen INTEGER NOT NULL DEFAULT 0,
              rows_upserted INTEGER NOT NULL DEFAULT 0,
              rows_skipped INTEGER NOT NULL DEFAULT 0,
              source_kind TEXT,
              error_text TEXT
            )"""
    )


# --------------------------------------------------------------------------- #
# HTTP fetch (with Playwright fallback wire)
# --------------------------------------------------------------------------- #


def _fetch(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> bytes | None:
    """Best-effort urllib fetch; returns None on any error (caller tolerates)."""
    if not url:
        return None
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if any(b in host for b in BANNED_HOSTS):
        logger.warning("fill_programs_foundation_2x: banned host %s", host)
        return None
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
            return r.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        logger.warning("fetch failed %s: %s", url, e)
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("fetch unexpected %s: %s", url, e)
        return None


def _fetch_with_playwright_fallback(url: str) -> bytes | None:
    """Try urllib first; fall back to Playwright if available + reachable.

    Memory `reference_canonical_enrichment` — JFC + many 財団 sites are
    JS-rendered. Playwright is the canonical fallback (NOT a primary).
    """
    body = _fetch(url)
    if body is not None and len(body) > 1024:
        return body
    # Playwright fallback — best-effort import; not a hard dep.
    try:
        from scripts.etl._playwright_helper import (  # type: ignore[import-not-found]
            fetch_rendered_html,
        )
    except Exception:
        return body
    try:
        rendered = fetch_rendered_html(url, timeout=DEFAULT_TIMEOUT)
        if rendered:
            return rendered.encode("utf-8", errors="ignore")
    except Exception as e:  # noqa: BLE001
        logger.debug("playwright fallback failed %s: %s", url, e)
    return body


# --------------------------------------------------------------------------- #
# Normalize
# --------------------------------------------------------------------------- #


_DATE_RE = re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})")
_AMOUNT_RE = re.compile(
    r"(?:上限|最大|総額)?\s*"
    r"(\d{1,4}(?:[,，]?\d{3})*)\s*"
    r"(万|億|円)"
    r"(?:\s*(?:〜|から|~)\s*(\d{1,4}(?:[,，]?\d{3})*)\s*(?:万|億|円))?"
)


def _normalize_date(text: str | None) -> str | None:
    if not text:
        return None
    m = _DATE_RE.search(text)
    if not m:
        return None
    y, mo, d = m.groups()
    try:
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    except ValueError:
        return None


def _extract_amount_range(text: str) -> str | None:
    """Pull a free-text grant amount range from page text. None if absent."""
    if not text:
        return None
    m = _AMOUNT_RE.search(text)
    if not m:
        return None
    return m.group(0).strip()[:100]


def _classify_theme(text: str) -> str | None:
    """Map page text into one canonical grant_theme via keyword match."""
    if not text:
        return None
    for canonical, kws in _THEME_KEYWORDS.items():
        if any(k in text for k in kws):
            return canonical
    return None


def _classify_donation_category(text: str, foundation_type: str) -> str:
    """Heuristic donation category from 一次資料 page text."""
    t = text or ""
    if "特定公益増進法人" in t or "認定NPO" in t:
        return "specified_public_interest"
    if foundation_type == "公益財団":
        return "public_interest"
    if "寄付金" in t and foundation_type in ("一般財団", "業界団体"):
        return "general"
    return "unknown"


def _extract_application_period(text: str) -> str | None:
    """Try to find an open / close date span; return JSON or None."""
    if not text:
        return None
    dates = _DATE_RE.findall(text)
    if not dates:
        # Detect 通年 / 随時 cycle markers without dates.
        if "通年" in text:
            return json.dumps({"cycle": "ongoing"}, ensure_ascii=False)
        if "随時" in text:
            return json.dumps({"cycle": "rolling"}, ensure_ascii=False)
        return None
    try:
        open_d = "-".join(f"{int(p):02d}" for p in dates[0])
        if len(dates) >= 2:
            close_d = "-".join(f"{int(p):02d}" for p in dates[1])
            return json.dumps(
                {"open_date": open_d, "close_date": close_d, "cycle": "single"},
                ensure_ascii=False,
            )
        return json.dumps({"open_date": open_d, "cycle": "single"}, ensure_ascii=False)
    except (ValueError, IndexError):
        return None


# --------------------------------------------------------------------------- #
# Source fetchers
# --------------------------------------------------------------------------- #


def _fetch_koeki_info_rows(max_rows: int) -> list[dict[str, Any]]:
    """Walk 公益財団協会 (koeki-info.go.jp) for 公益財団 listings.

    The koeki-info site publishes structured 公益法人 records; we pull
    foundation_name + URL pairs, then enrich per foundation via
    `_fetch_with_playwright_fallback` against the foundation's own page.
    """
    out: list[dict[str, Any]] = []
    landing = f"{KOEKI_BASE}/info/"
    body = _fetch(landing)
    if body is None:
        logger.info("koeki_info: landing fetch failed; skipping")
        return out
    text = body.decode("utf-8", errors="ignore")
    # koeki-info publishes 公益法人 list rows via <a href> with the
    # 公益法人 name in the anchor text. Best-effort regex pull.
    for m in re.finditer(
        r'<a\s+href="([^"]+)"[^>]*>([^<]{4,80})</a>', text
    ):
        if len(out) >= max_rows:
            break
        href, name = m.group(1), m.group(2).strip()
        if "財団" not in name and "団体" not in name:
            continue
        url = urllib.parse.urljoin(KOEKI_BASE, href)
        out.append(
            {
                "foundation_name": name[:200],
                "foundation_type": "公益財団" if "財団" in name else "業界団体",
                "grant_program_name": None,
                "grant_amount_range": None,
                "grant_theme": _classify_theme(name),
                "donation_category": "public_interest",
                "application_period_json": None,
                "source_url": url,
                "source_kind": "koeki_info",
                "notes": "Pulled from 公益財団協会 landing list",
            }
        )
    logger.info("koeki_info rows seen=%d", len(out))
    return out


def _fetch_official_site_rows(max_rows: int) -> list[dict[str, Any]]:
    """Walk the curated 公益財団 official-site list with Playwright fallback."""
    out: list[dict[str, Any]] = []
    for entry in OFFICIAL_FOUNDATION_SITES:
        if len(out) >= max_rows:
            break
        body = _fetch_with_playwright_fallback(entry["url"])
        if body is None:
            continue
        text = body.decode("utf-8", errors="ignore")
        # Look for grant program markers in landing text.
        title_m = re.search(r"<title[^>]*>([^<]{2,200})</title>", text)
        page_title = title_m.group(1).strip() if title_m else entry["name"]
        amount = _extract_amount_range(text)
        theme = _classify_theme(text)
        period = _extract_application_period(text)
        donation = _classify_donation_category(text, entry["type"])
        # Each site may host multiple grant programs; we pull up to 5
        # program-name candidates from H2/H3 headers.
        program_names = re.findall(
            r"<h[23][^>]*>([^<]{4,80}?助成[^<]{0,60})</h[23]>", text
        )
        if not program_names:
            program_names = [page_title[:80]]
        for pname in program_names[:5]:
            out.append(
                {
                    "foundation_name": entry["name"],
                    "foundation_type": entry["type"],
                    "grant_program_name": pname.strip()[:200],
                    "grant_amount_range": amount,
                    "grant_theme": theme,
                    "donation_category": donation,
                    "application_period_json": period,
                    "source_url": entry["url"],
                    "source_kind": "official_site",
                    "notes": f"primary site walk; title={page_title[:120]}",
                }
            )
            if len(out) >= max_rows:
                break
        time.sleep(DEFAULT_DELAY)
    logger.info("official_site rows seen=%d", len(out))
    return out


def _fetch_cabinet_npo_rows(max_rows: int) -> list[dict[str, Any]]:
    """Best-effort 内閣府 NPO 公開資料 walk. Stub at this scope.

    The 内閣府 NPO 認証 master list is very large (~50k NPOs); only a
    small fraction run 助成 programs. The full corpus walk is a separate
    later pass — this stub returns the curated 助成 NPO landing only.
    """
    out: list[dict[str, Any]] = []
    body = _fetch(f"{CABINET_NPO_BASE}/")
    if body is None:
        return out
    text = body.decode("utf-8", errors="ignore")
    # Only surface NPOs whose landing-text mentions 助成プログラム.
    if "助成" not in text:
        logger.info("cabinet_npo rows seen=0 (no 助成 marker in landing)")
        return out
    out.append(
        {
            "foundation_name": "内閣府 NPO 認証 master list",
            "foundation_type": "NPO",
            "grant_program_name": "NPO 助成事業 一覧",
            "grant_amount_range": None,
            "grant_theme": None,
            "donation_category": "unknown",
            "application_period_json": None,
            "source_url": f"{CABINET_NPO_BASE}/",
            "source_kind": "cabinet_npo",
            "notes": "Landing stub; per-NPO walk deferred to Wave 43.1.x+",
        }
    )
    logger.info("cabinet_npo rows seen=%d", len(out))
    return out


def _fetch_gyokai_dantai_rows(max_rows: int) -> list[dict[str, Any]]:
    """Walk a curated 業界団体 助成 page set."""
    out: list[dict[str, Any]] = []
    # 経団連 + 商工会議所 + 同友会 grant pages.
    sites = [
        {
            "name": "一般社団法人日本経済団体連合会",
            "url": "https://www.keidanren.or.jp/policy/",
            "type": "業界団体",
        },
        {
            "name": "日本商工会議所",
            "url": "https://www.jcci.or.jp/",
            "type": "業界団体",
        },
        {
            "name": "中小企業家同友会全国協議会",
            "url": "https://www.doyu.jp/",
            "type": "業界団体",
        },
    ]
    for entry in sites:
        if len(out) >= max_rows:
            break
        body = _fetch(entry["url"])
        if body is None:
            continue
        text = body.decode("utf-8", errors="ignore")
        if "助成" not in text and "支援" not in text:
            continue
        out.append(
            {
                "foundation_name": entry["name"],
                "foundation_type": entry["type"],
                "grant_program_name": "業界団体 支援事業",
                "grant_amount_range": _extract_amount_range(text),
                "grant_theme": _classify_theme(text),
                "donation_category": "general",
                "application_period_json": _extract_application_period(text),
                "source_url": entry["url"],
                "source_kind": "gyokai_dantai",
                "notes": "Industry association support landing",
            }
        )
        time.sleep(DEFAULT_DELAY)
    logger.info("gyokai_dantai rows seen=%d", len(out))
    return out


# --------------------------------------------------------------------------- #
# Persist
# --------------------------------------------------------------------------- #


def _upsert(conn: sqlite3.Connection, row: dict[str, Any]) -> bool:
    """Upsert one row. Returns True on insert, False on dedup-skip."""
    ftype = row.get("foundation_type") or "公益財団"
    if ftype not in _VALID_FOUNDATION_TYPES:
        ftype = "公益財団"
    donation = row.get("donation_category") or "unknown"
    if donation not in _VALID_DONATION_CATEGORIES:
        donation = "unknown"
    source_kind = row.get("source_kind") or "other"
    if source_kind not in _VALID_SOURCE_KINDS:
        source_kind = "other"
    name = (row.get("foundation_name") or "").strip()
    if not name:
        return False
    try:
        conn.execute(
            "INSERT OR REPLACE INTO am_program_private_foundation "
            "(foundation_name, foundation_type, grant_program_name, "
            " grant_amount_range, grant_theme, donation_category, "
            " application_period_json, source_url, source_kind, notes, "
            " refreshed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "        strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
            (
                name[:200],
                ftype,
                (row.get("grant_program_name") or None),
                row.get("grant_amount_range"),
                row.get("grant_theme"),
                donation,
                row.get("application_period_json"),
                row.get("source_url"),
                source_kind,
                row.get("notes"),
            ),
        )
        return True
    except sqlite3.IntegrityError:
        return False
    except sqlite3.Error as e:
        logger.warning("upsert failed: %s", e)
        return False


def _log_run(
    conn: sqlite3.Connection,
    *,
    started_at: str,
    seen: int,
    upserted: int,
    skipped: int,
    source_kind: str,
    error: str | None,
) -> None:
    conn.execute(
        "INSERT INTO am_program_private_foundation_ingest_log "
        "(started_at, finished_at, rows_seen, rows_upserted, rows_skipped, "
        " source_kind, error_text) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            started_at,
            datetime.now(UTC).isoformat(),
            seen,
            upserted,
            skipped,
            source_kind,
            error,
        ),
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Wave 43.1.3 — Ingest 民間助成財団 2,000+ programs."
    )
    p.add_argument(
        "--source",
        choices=("koeki_info", "official_site", "cabinet_npo", "gyokai_dantai", "all"),
        default="all",
        help="Source set to ingest.",
    )
    p.add_argument("--max-rows", type=int, default=2000, help="Max rows per source.")
    p.add_argument("--dry-run", action="store_true", help="No DB writes — print plan.")
    p.add_argument("--verbose", action="store_true", help="Debug logging.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    _configure_logging(verbose=args.verbose)
    started_at = datetime.now(UTC).isoformat()

    db_path = _db_path()
    if args.dry_run:
        logger.info("[dry-run] would open DB %s", db_path)
        logger.info("[dry-run] source=%s max_rows=%d", args.source, args.max_rows)
        return 0

    if not db_path.exists():
        logger.error("autonomath.db missing at %s — run migration 250 first", db_path)
        return 2

    conn = _open_rw(db_path)
    try:
        _ensure_tables(conn)

        plan: list[tuple[str, list[dict[str, Any]]]] = []
        if args.source in ("koeki_info", "all"):
            plan.append(("koeki_info", _fetch_koeki_info_rows(args.max_rows)))
            time.sleep(DEFAULT_DELAY)
        if args.source in ("official_site", "all"):
            plan.append(("official_site", _fetch_official_site_rows(args.max_rows)))
            time.sleep(DEFAULT_DELAY)
        if args.source in ("cabinet_npo", "all"):
            plan.append(("cabinet_npo", _fetch_cabinet_npo_rows(args.max_rows)))
            time.sleep(DEFAULT_DELAY)
        if args.source in ("gyokai_dantai", "all"):
            plan.append(("gyokai_dantai", _fetch_gyokai_dantai_rows(args.max_rows)))

        total_seen = total_upserted = total_skipped = 0
        for source_kind, rows in plan:
            seen = len(rows)
            up = sk = 0
            for r in rows:
                if _upsert(conn, r):
                    up += 1
                else:
                    sk += 1
            _log_run(
                conn,
                started_at=started_at,
                seen=seen,
                upserted=up,
                skipped=sk,
                source_kind=source_kind,
                error=None,
            )
            logger.info(
                "%s seen=%d upserted=%d skipped=%d", source_kind, seen, up, sk
            )
            total_seen += seen
            total_upserted += up
            total_skipped += sk

        result = {
            "seen": total_seen,
            "upserted": total_upserted,
            "skipped": total_skipped,
            "sources": [src for src, _ in plan],
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        with contextlib.suppress(Exception):
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
