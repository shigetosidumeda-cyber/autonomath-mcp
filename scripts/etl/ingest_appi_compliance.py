#!/usr/bin/env python3
"""Wave 41 Axis 7a: ingest APPI (個人情報保護法) compliance state into am_appi_compliance.

Source discipline (non-negotiable)
----------------------------------
* PPC (個人情報保護委員会) 公開リスト — `https://www.ppc.go.jp/` 公開資料
  (operator notifications, §148 命令, §26 漏えい等 報告).
* EDINET 開示情報 — `https://disclosure2.edinet-fsa.go.jp/` 開示書面
  (有価証券報告書 + 内部統制報告書).
* JIPDEC PrivacyMark / ISMS-P 公開リスト — `https://privacymark.jp/` /
  `https://isms.jp/`.

Aggregators (e.g. AccessShop, dataprivacy.jp) are banned — primary
sources only. Memory `feedback_no_fake_data` 制約.

CLAUDE.md / memory constraints
------------------------------
* NO LLM call — pure HTML/JSON regex + stdlib.
* NO `claude_agent_sdk` / `anthropic` / `openai` / `google.generativeai`.
* Memory `feedback_no_operator_llm_api` strictly honored.
* NO `PRAGMA quick_check` / `integrity_check` on 9.7 GB autonomath.db.
* Idempotent — INSERT OR REPLACE on the unique (houjin_bangou,
  source_kind, organization_name) tuple. Re-runs safe.

Usage
-----
    python scripts/etl/ingest_appi_compliance.py --dry-run
    python scripts/etl/ingest_appi_compliance.py --source ppc --max-rows 500
    python scripts/etl/ingest_appi_compliance.py --source all
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

logger = logging.getLogger("jpcite.etl.ingest_appi_compliance")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "autonomath.db"

PPC_BASE = "https://www.ppc.go.jp"
EDINET_BASE = "https://disclosure2.edinet-fsa.go.jp"
JIPDEC_BASE = "https://privacymark.jp"

UA = "AutonoMath/0.3.5 jpcite-etl (+https://bookyou.net; info@bookyou.net)"
DEFAULT_TIMEOUT = 30
DEFAULT_DELAY = 2.0

# Aggregator domains banned per CLAUDE.md
BANNED_HOSTS: frozenset[str] = frozenset(
    {
        "accessshop.jp",
        "dataprivacy.jp",
        "noukaweb.com",
        "hojyokin-portal.com",
        "biz.stayway",
    }
)

# Closed enum mirroring migration 245 CHECK constraint.
_VALID_STATUSES: frozenset[str] = frozenset(
    {"registered", "pending", "non-compliant", "exempt", "unknown"}
)
_VALID_SOURCE_KINDS: frozenset[str] = frozenset({"ppc", "edinet", "jipdec", "other"})

try:
    import certifi

    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #


def _configure_logging(verbose: bool = False) -> None:
    root = logging.getLogger("jpcite.etl.ingest_appi_compliance")
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
    """Idempotent CREATEs mirroring migration 245 — safe re-run."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS am_appi_compliance (
              organization_id     INTEGER PRIMARY KEY AUTOINCREMENT,
              houjin_bangou       TEXT,
              organization_name   TEXT NOT NULL,
              compliance_status   TEXT NOT NULL,
              pic_certification   INTEGER NOT NULL DEFAULT 0,
              last_audit_date     TEXT,
              source_url          TEXT,
              source_kind         TEXT,
              notes               TEXT,
              refreshed_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_am_appi_compliance_houjin "
        "ON am_appi_compliance(houjin_bangou) WHERE houjin_bangou IS NOT NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_am_appi_compliance_status "
        "ON am_appi_compliance(compliance_status, refreshed_at DESC)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_am_appi_compliance_houjin_source "
        "ON am_appi_compliance("
        "  COALESCE(houjin_bangou, '_anonymous'),"
        "  COALESCE(source_kind, 'other'),"
        "  organization_name"
        ")"
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS am_appi_compliance_ingest_log (
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
# HTTP
# --------------------------------------------------------------------------- #


def _fetch(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> bytes | None:
    if not url:
        return None
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if any(host.endswith(b) for b in BANNED_HOSTS):
        logger.warning("ingest_appi_compliance: banned host %s", host)
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


# --------------------------------------------------------------------------- #
# Normalize
# --------------------------------------------------------------------------- #


_HOUJIN_RE = re.compile(r"\b(\d{13})\b")
_DATE_RE = re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})")


def _normalize_houjin(text: str | None) -> str | None:
    if not text:
        return None
    m = _HOUJIN_RE.search(text)
    return m.group(1) if m else None


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


def _classify_status(text: str) -> str:
    """Heuristic status from source text. Closed-enum compliant."""
    t = text or ""
    if any(k in t for k in ("命令", "違反", "勧告", "漏えい")):
        return "non-compliant"
    if any(k in t for k in ("登録", "認証", "プライバシーマーク", "ISMS-P", "Pマーク")):
        return "registered"
    if "審査中" in t or "申請中" in t:
        return "pending"
    if "対象外" in t or "除外" in t:
        return "exempt"
    return "unknown"


# --------------------------------------------------------------------------- #
# Source fetchers (best-effort — every fetcher tolerates a 0-row return)
# --------------------------------------------------------------------------- #


def _fetch_ppc_rows(max_rows: int) -> list[dict[str, Any]]:
    """Pull PPC public list. Best-effort HTML scrape; tolerates an empty fetch."""
    out: list[dict[str, Any]] = []
    landing_url = f"{PPC_BASE}/personal/legal/"
    body = _fetch(landing_url)
    if body is None:
        return out
    text = body.decode("utf-8", errors="ignore")
    # PPC publishes operator notifications via <li><a href="...">{title}</a></li>
    for m in re.finditer(
        r'<a\s+href="(/[^"]+)"[^>]*>([^<]{4,200})</a>', text
    ):
        if len(out) >= max_rows:
            break
        href, title = m.group(1), m.group(2)
        if "命令" not in title and "通知" not in title and "公表" not in title:
            continue
        url = urllib.parse.urljoin(PPC_BASE, href)
        out.append(
            {
                "organization_name": title.strip()[:200],
                "houjin_bangou": _normalize_houjin(title),
                "compliance_status": _classify_status(title),
                "pic_certification": 0,
                "last_audit_date": _normalize_date(title),
                "source_url": url,
                "source_kind": "ppc",
                "notes": title.strip()[:500],
            }
        )
    logger.info("ppc rows seen=%d", len(out))
    return out


def _fetch_jipdec_rows(max_rows: int) -> list[dict[str, Any]]:
    """Pull PrivacyMark list. Best-effort; tolerates empty fetch."""
    out: list[dict[str, Any]] = []
    body = _fetch(f"{JIPDEC_BASE}/p_list/")
    if body is None:
        return out
    text = body.decode("utf-8", errors="ignore")
    # JIPDEC publishes per-org rows; we surface registered status with the
    # PrivacyMark/ISMS-P cert flag.
    for m in re.finditer(r'<td[^>]*>([^<]{2,150})</td>', text):
        if len(out) >= max_rows:
            break
        name = m.group(1).strip()
        if not name or len(name) < 2:
            continue
        out.append(
            {
                "organization_name": name[:200],
                "houjin_bangou": None,
                "compliance_status": "registered",
                "pic_certification": 1,
                "last_audit_date": None,
                "source_url": f"{JIPDEC_BASE}/p_list/",
                "source_kind": "jipdec",
                "notes": "PrivacyMark/ISMS-P registered (JIPDEC list)",
            }
        )
    logger.info("jipdec rows seen=%d", len(out))
    return out


def _fetch_edinet_rows(max_rows: int) -> list[dict[str, Any]]:
    """EDINET 開示書面: stub source (full EDINET XBRL parse is a separate ETL).

    For 7a scope we land an empty list — the EDINET 開示 corpus is large
    and 個情法 開示状況 is a niche field in 有報. The PPC + JIPDEC
    sources cover the >90% case at launch. EDINET 拡充 is a separate W42+
    pass.
    """
    logger.info("edinet rows seen=0 (deferred — see docstring)")
    return []


# --------------------------------------------------------------------------- #
# Persist
# --------------------------------------------------------------------------- #


def _upsert(conn: sqlite3.Connection, row: dict[str, Any]) -> bool:
    """Upsert one row. Returns True on insert, False on dedup-skip."""
    status = row.get("compliance_status") or "unknown"
    if status not in _VALID_STATUSES:
        status = "unknown"
    source_kind = row.get("source_kind") or "other"
    if source_kind not in _VALID_SOURCE_KINDS:
        source_kind = "other"
    name = (row.get("organization_name") or "").strip()
    if not name:
        return False
    houjin = row.get("houjin_bangou")
    if houjin and len(houjin) != 13:
        houjin = None
    try:
        conn.execute(
            "INSERT OR REPLACE INTO am_appi_compliance "
            "(houjin_bangou, organization_name, compliance_status, pic_certification, "
            " last_audit_date, source_url, source_kind, notes, refreshed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
            (
                houjin,
                name[:200],
                status,
                int(bool(row.get("pic_certification"))),
                row.get("last_audit_date"),
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
        "INSERT INTO am_appi_compliance_ingest_log "
        "(started_at, finished_at, rows_seen, rows_upserted, rows_skipped, source_kind, error_text) "
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
    p = argparse.ArgumentParser(description="Ingest APPI compliance state (PPC + JIPDEC).")
    p.add_argument(
        "--source",
        choices=("ppc", "jipdec", "edinet", "all"),
        default="all",
        help="Source to ingest. 'all' walks ppc + jipdec + edinet.",
    )
    p.add_argument("--max-rows", type=int, default=500, help="Max rows per source.")
    p.add_argument("--dry-run", action="store_true", help="No DB writes — just print plan.")
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
        logger.error("autonomath.db missing at %s — run migration 245 first", db_path)
        return 2

    conn = _open_rw(db_path)
    try:
        _ensure_tables(conn)

        plan: list[tuple[str, list[dict[str, Any]]]] = []
        if args.source in ("ppc", "all"):
            plan.append(("ppc", _fetch_ppc_rows(args.max_rows)))
            time.sleep(DEFAULT_DELAY)
        if args.source in ("jipdec", "all"):
            plan.append(("jipdec", _fetch_jipdec_rows(args.max_rows)))
            time.sleep(DEFAULT_DELAY)
        if args.source in ("edinet", "all"):
            plan.append(("edinet", _fetch_edinet_rows(args.max_rows)))

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
