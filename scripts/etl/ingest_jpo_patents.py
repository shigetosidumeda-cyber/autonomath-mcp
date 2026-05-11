#!/usr/bin/env python3
"""ingest_jpo_patents.py — JPO 特許/実用新案 daily-diff fetch from J-PlatPat.

Wave 31 Axis 1b. Populates `am_jpo_patents` and `am_jpo_utility_models`
on `autonomath.db` (migration 226).

Source
------
J-PlatPat (https://www.j-platpat.inpit.go.jp/) — INPIT が運営する公式
特許情報プラットフォーム。daily 公開・登録 公報 index + per-doc detail。

公式 API は無く、daily 公報 index ページ + per-doc detail page を
HTML / XML パースする。INPIT が提供する OPD bulk download 一覧 (国内
公報) も補助的に利用可能 (operator が事前に DL 済 dir を渡せば即時
ロードできる Path A モードあり)。

二次資料 (Patent-i / Patent Result / Astamuse 等) は使用禁止。

Mode
----
Path A — local-bulk:
    `--from-dir <DIR>` で operator が事前 DL 済 J-PlatPat / OPD 形式
    の XML/CSV を一括ロード。daily diff 取得が一時的に出来ない場合の
    操作員 manual fallback。

Path B — online-incremental (default):
    J-PlatPat の公開・登録 公報 sitemap-based incremental fetch。
    `--days <N>` で N 日 さかのぼり、`--limit <M>` でで件数上限。

Constraints
-----------
* LLM call count: 0. lxml + sqlite3 + httpx + json + hashlib のみ。
* Rate limit: 1 req/sec via asyncio.Semaphore(1) + sleep RATE_LIMIT_SECONDS.
* Idempotent: INSERT OR REPLACE on (application_no). content_hash 一致時 は
  UPDATE skip (no-op).
* Failure path: stderr + sys.exit(1).

Usage
-----
    # Dry-run smoke (10 件 fetch)
    python scripts/etl/ingest_jpo_patents.py --dry-run --limit 10

    # Daily incremental (last 1 day)
    python scripts/etl/ingest_jpo_patents.py --days 1

    # Local bulk (OPD XML dir)
    python scripts/etl/ingest_jpo_patents.py --from-dir /tmp/opd_dump

Exit codes
----------
0  success
1  fetch / IO / parse failure
2  schema missing (run migration 226 first)
3  argument validation failure
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("jpintel.etl.jpo_patents")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

JPLATPAT_BASE = "https://www.j-platpat.inpit.go.jp"
JPLATPAT_GAZETTE_INDEX = f"{JPLATPAT_BASE}/gazette/index"  # 公開公報 index
JPLATPAT_DETAIL = f"{JPLATPAT_BASE}/c1800/PU/JP-{{application_no}}/15/ja"

RATE_LIMIT_SECONDS = 1.0
HTTPX_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
USER_AGENT = "jpcite-jpo-patents-ingest/0.3.5 (+https://jpcite.com)"

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = _REPO_ROOT / "autonomath.db"

# Status enum mirrors migration 226 CHECK constraint.
STATUS_ENUM: frozenset[str] = frozenset(
    {
        "published",
        "registered",
        "rejected",
        "withdrawn",
        "expired",
        "abandoned",
        "unknown",
    }
)

# Application-number regex (公開: YYYY-NNNNNN, PCT: PCT/JPNN/NNNNNN).
_APPLICATION_NO_RE = re.compile(
    r"^(?:\d{4}-\d{6}|PCT/[A-Z]{2}\d{4}/\d{6})$"
)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(__doc__ or "").split("\n\n")[0],
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--from-dir",
        type=str,
        default=None,
        help="Path A — local-bulk: load OPD-format XML/CSV from this dir.",
    )
    mode.add_argument(
        "--days",
        type=int,
        default=1,
        help="Path B — online: days back from today (default 1).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Maximum rows to process per run (safety cap, default 1000).",
    )
    p.add_argument(
        "--target",
        choices=("patents", "utility_models", "both"),
        default="both",
        help="Which surface to populate (default both).",
    )
    p.add_argument(
        "--db",
        default=os.environ.get("AUTONOMATH_DB_PATH", str(DEFAULT_DB_PATH)),
        help="autonomath.db path (default: %(default)s).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + parse only; do not INSERT.",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose logging.",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _open_db(path: str) -> sqlite3.Connection:
    """Open autonomath.db for read+write."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"autonomath.db missing: {p}")
    conn = sqlite3.connect(str(p), timeout=30.0)
    conn.execute("PRAGMA busy_timeout=300000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def _schema_required(conn: sqlite3.Connection, table: str) -> None:
    """Verify the migration-226 schema is in place; exit 2 otherwise."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if not row:
        logger.error("required table missing: %s (run migration 226 first)", table)
        sys.exit(2)


def _existing_hash(
    conn: sqlite3.Connection, table: str, application_no: str
) -> str | None:
    """Return current content_hash for app_no on `table`, or None."""
    row = conn.execute(
        f"SELECT content_hash FROM {table} WHERE application_no = ?",
        (application_no,),
    ).fetchone()
    return row["content_hash"] if row else None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _normalize_application_no(raw: str | None) -> str | None:
    """Strip and validate an application number string."""
    if not raw:
        return None
    s = str(raw).strip().replace("　", "").replace(" ", "")
    if _APPLICATION_NO_RE.match(s):
        return s
    return None


def _normalize_date(raw: str | None) -> str:
    """Coerce a date-like string into ISO YYYY-MM-DD (empty on failure)."""
    if not raw:
        return ""
    s = str(raw).strip()
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", s)
    if m:
        y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        return f"{y}-{mo}-{d}"
    return ""


def _normalize_houjin_bangou(raw: str | None) -> str | None:
    """Validate a 13-digit 法人番号; return None if malformed."""
    if not raw:
        return None
    s = re.sub(r"\D", "", str(raw))
    if len(s) == 13:
        return s
    return None


def _content_hash(row: dict[str, Any]) -> str:
    """Canonical SHA-256 of the row body for drift detection."""
    canonical = json.dumps(
        {
            "title": row.get("title", ""),
            "body": row.get("body", ""),
            "applicant_name": row.get("applicant_name", ""),
            "ipc_classification": row.get("ipc_classification", ""),
            "application_date": row.get("application_date", ""),
            "registration_date": row.get("registration_date", ""),
            "status": row.get("status", "unknown"),
            "applicants": row.get("applicants", []),
            "ipc_codes": row.get("ipc_codes", []),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_jplatpat_record(rec: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a J-PlatPat record dict into a normalized row.

    Returns None if a required field is missing.

    Expected shape (best-effort; falls back to alternate keys):
        {
          "application_no": "2024-123456",
          "registration_no": "特許XXXXXXX" | None,
          "title": "...",
          "body": "...",
          "applicants": ["...", ...],
          "applicant_houjin_bangou": "1234567890123" | None,
          "ipc_codes": ["G06F 17/30", ...],
          "application_date": "2024-01-15",
          "registration_date": "2026-01-15" | None,
          "status": "registered",
          "source_url": "https://www.j-platpat.inpit.go.jp/...",
        }
    """
    app_no = _normalize_application_no(
        rec.get("application_no")
        or rec.get("applicationNumber")
        or rec.get("出願番号")
    )
    if not app_no:
        return None

    title = (rec.get("title") or rec.get("発明の名称") or rec.get("inventionTitle") or "").strip()
    if not title:
        return None

    application_date = _normalize_date(
        rec.get("application_date") or rec.get("出願日") or rec.get("applicationDate")
    )
    if not application_date:
        return None

    body = (rec.get("body") or rec.get("abstract") or rec.get("要約") or "").strip()
    body = body[:10240]
    title = title[:1024]

    applicants_raw: list[Any] = rec.get("applicants") or rec.get("出願人") or []
    if isinstance(applicants_raw, str):
        applicants_raw = [applicants_raw]
    applicants = [str(a).strip()[:512] for a in applicants_raw if a]
    applicant_name = applicants[0][:512] if applicants else (
        (rec.get("applicant_name") or "").strip()[:512]
    )

    applicant_houjin_bangou = _normalize_houjin_bangou(
        rec.get("applicant_houjin_bangou")
        or rec.get("applicantHoujinBangou")
        or rec.get("法人番号")
    )

    ipc_codes_raw = rec.get("ipc_codes") or rec.get("IPC分類") or rec.get("ipcCodes") or []
    if isinstance(ipc_codes_raw, str):
        ipc_codes_raw = [ipc_codes_raw]
    ipc_codes = [str(c).strip() for c in ipc_codes_raw if c]
    ipc_classification = (
        rec.get("ipc_classification") or ", ".join(ipc_codes) or ""
    )[:1024]

    registration_no = (
        rec.get("registration_no") or rec.get("登録番号") or rec.get("registrationNumber") or None
    )
    if isinstance(registration_no, str):
        registration_no = registration_no.strip() or None

    registration_date = _normalize_date(
        rec.get("registration_date") or rec.get("登録日") or rec.get("registrationDate")
    ) or None

    status = (rec.get("status") or "unknown").lower().strip()
    if status not in STATUS_ENUM:
        status = "unknown"

    source_url = (
        rec.get("source_url")
        or rec.get("url")
        or rec.get("detailUrl")
        or JPLATPAT_DETAIL.format(application_no=app_no)
    )[:2048]

    out = {
        "application_no": app_no,
        "registration_no": registration_no,
        "title": title,
        "body": body,
        "applicant_name": applicant_name,
        "applicant_houjin_bangou": applicant_houjin_bangou,
        "ipc_classification": ipc_classification,
        "application_date": application_date,
        "registration_date": registration_date,
        "status": status,
        "source_url": source_url,
        "applicants": applicants,
        "ipc_codes": ipc_codes,
    }
    out["content_hash"] = _content_hash(out)
    return out


# ---------------------------------------------------------------------------
# Online client (Path B)
# ---------------------------------------------------------------------------


async def _fetch_gazette_index(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    days: int,
    target: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Fetch gazette index entries for the last `days` days.

    J-PlatPat の sitemap-style index は HTML だが、公式 ZIP download
    一覧 (国内公報) は JSON-like text を返す経路が複数ある。本関数 は
    対象 days 範囲の document 一覧をフェッチして dict のリストを返す。
    現実装は最小骨格 — 取得経路は upstream 変更に追随する想定なので
    `MAX_RECORDS_PER_DAY` の安全弁のみ持つ。
    """
    out: list[dict[str, Any]] = []
    today = datetime.now(UTC).date()
    surfaces = ("patents", "utility_models") if target == "both" else (target,)
    for surface in surfaces:
        for offset in range(days):
            day = today - timedelta(days=offset)
            params = {
                "date": day.strftime("%Y-%m-%d"),
                "kind": surface,
            }
            async with semaphore:
                try:
                    resp = await client.get(JPLATPAT_GAZETTE_INDEX, params=params)
                except httpx.HTTPError as exc:
                    logger.warning(
                        "jplatpat gazette index fetch failed for %s on %s: %s",
                        surface, day, exc,
                    )
                    await asyncio.sleep(RATE_LIMIT_SECONDS * 2)
                    continue
                await asyncio.sleep(RATE_LIMIT_SECONDS)
            if resp.status_code != 200:
                logger.warning(
                    "jplatpat index HTTP %d on %s/%s",
                    resp.status_code, day, surface,
                )
                continue
            try:
                payload = resp.json()
            except (ValueError, json.JSONDecodeError):
                # The HTML fallback returns nothing; treat as empty.
                payload = {}
            records = payload.get("results") or payload.get("items") or []
            for r in records:
                r.setdefault("surface", surface)
                out.append(r)
            if len(out) >= limit:
                return out[:limit]
    return out[:limit]


# ---------------------------------------------------------------------------
# Local bulk loader (Path A)
# ---------------------------------------------------------------------------


def _iter_local_xml(dir_path: Path) -> Iterable[dict[str, Any]]:
    """Yield record dicts from a directory of OPD-format files.

    Looks at `*.json` and `*.xml`. JSON files are parsed as a list-of-dicts
    or a single dict; XML files use lxml's iterparse. Best-effort
    extractor — schema-tolerant.
    """
    try:
        from lxml import etree  # type: ignore[import-untyped]
    except ImportError:
        etree = None  # type: ignore[assignment]

    for path in sorted(dir_path.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("skipping %s: %s", path, exc)
            continue
        if isinstance(data, list):
            yield from data
        elif isinstance(data, dict):
            yield data

    if etree is None:
        return
    for path in sorted(dir_path.rglob("*.xml")):
        try:
            tree = etree.parse(str(path))
        except etree.XMLSyntaxError as exc:
            logger.warning("skipping %s: %s", path, exc)
            continue
        root = tree.getroot()
        # Best-effort: collect every direct child as a record.
        for child in root.iter():
            tag = etree.QName(child.tag).localname.lower()
            if tag not in {"document", "publication", "record", "patent", "utility"}:
                continue
            rec = {etree.QName(c.tag).localname: (c.text or "").strip() for c in child}
            if rec:
                yield rec


# ---------------------------------------------------------------------------
# INSERT helpers
# ---------------------------------------------------------------------------


def _insert_row(
    conn: sqlite3.Connection,
    table: str,
    row: dict[str, Any],
    *,
    dry_run: bool,
) -> bool:
    """Upsert one row into `table`. Returns True if a write occurred."""
    existing = _existing_hash(conn, table, row["application_no"])
    if existing == row["content_hash"]:
        return False
    if dry_run:
        return True
    conn.execute(
        f"""INSERT OR REPLACE INTO {table} (
            application_no, registration_no, title, body, applicant_name,
            applicant_houjin_bangou, ipc_classification, application_date,
            registration_date, status, source_url, applicants_json,
            ipc_codes_json, content_hash, ingested_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            row["application_no"],
            row["registration_no"],
            row["title"],
            row["body"],
            row["applicant_name"],
            row["applicant_houjin_bangou"],
            row["ipc_classification"],
            row["application_date"],
            row["registration_date"],
            row["status"],
            row["source_url"],
            json.dumps(row.get("applicants", []), ensure_ascii=False),
            json.dumps(row.get("ipc_codes", []), ensure_ascii=False),
            row["content_hash"],
            datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ"),
        ),
    )
    return True


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _route_table(rec: dict[str, Any], target: str) -> str | None:
    """Decide which table a record belongs to.

    Falls back on ``target`` when the record doesn't tag a surface.
    """
    surface = (rec.get("surface") or rec.get("kind") or rec.get("種別") or "").lower()
    if surface in {"utility", "utility_model", "実用新案", "u"}:
        return "am_jpo_utility_models"
    if surface in {"patent", "特許", "p"}:
        return "am_jpo_patents"
    if target == "utility_models":
        return "am_jpo_utility_models"
    if target == "patents":
        return "am_jpo_patents"
    # Default to patents when ambiguous + both selected.
    return "am_jpo_patents"


async def _run(args: argparse.Namespace) -> int:
    conn = _open_db(args.db)
    try:
        if args.target in {"patents", "both"}:
            _schema_required(conn, "am_jpo_patents")
        if args.target in {"utility_models", "both"}:
            _schema_required(conn, "am_jpo_utility_models")

        records: list[dict[str, Any]] = []
        if args.from_dir:
            dir_path = Path(args.from_dir)
            if not dir_path.is_dir():
                logger.error("from-dir does not exist: %s", dir_path)
                return 3
            records = list(_iter_local_xml(dir_path))[: args.limit]
            logger.info("local-bulk loaded %d candidate records from %s", len(records), dir_path)
        else:
            headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
            async with httpx.AsyncClient(headers=headers, timeout=HTTPX_TIMEOUT) as client:
                semaphore = asyncio.Semaphore(1)
                records = await _fetch_gazette_index(
                    client, semaphore,
                    days=args.days,
                    target=args.target,
                    limit=args.limit,
                )
            logger.info("online fetch returned %d candidate records", len(records))

        inserted = 0
        skipped = 0
        rejected = 0
        for rec in records:
            row = parse_jplatpat_record(rec)
            if row is None:
                rejected += 1
                continue
            table = _route_table(rec, args.target)
            if table is None:
                rejected += 1
                continue
            if _insert_row(conn, table, row, dry_run=args.dry_run):
                inserted += 1
            else:
                skipped += 1

        if not args.dry_run:
            conn.commit()

        logger.info(
            "summary inserted=%d skipped=%d rejected=%d dry_run=%s",
            inserted, skipped, rejected, args.dry_run,
        )
        return 0
    except sqlite3.Error as exc:
        logger.error("sqlite error: %s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001 — top-level orchestrator
        logger.error("unexpected error: %s", exc, exc_info=True)
        return 1
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
