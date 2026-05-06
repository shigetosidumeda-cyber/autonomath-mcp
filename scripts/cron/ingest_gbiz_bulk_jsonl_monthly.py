#!/usr/bin/env python3
"""gBizINFO 月次 bulk ZIP cold-start + 月次 refresh ingest.

DEEP_01 §1.2 entry 6 implementation. Pulls the authenticated bulk ZIP
from ``https://info.gbiz.go.jp/hojin/DownloadTop`` and stream-extracts
the embedded JSONL files into the 5 mirror tables (corp_activity +
branches + workplaces; subsidy / cert / commendation / procurement
ingest is owned by the sibling delta scripts, not this one).

Hard constraints (re-read before editing):

  * **Bookyou名義 single token** (DEEP_01 §条件1) — auth uses the same
    bearer header as the REST clients via ``_gbiz_rate_limiter``.
  * **Raw ZIP は再配布禁止** (DEEP_01 §6 / out-of-scope §8) — this
    script keeps the ZIP locally only for digest dedupe; jpcite never
    exposes a "download our gBiz mirror" endpoint.
  * **個別法令マーク image を除外** (DEEP_01 §6 / ToS condition 6) —
    field blocklist drops `_image|_logo|_mark|_base64` fields before
    they hit the DB.
  * **5M 件を memory に載せない** — uses ``zipfile.ZipFile.open`` +
    line-buffered ``io.TextIOWrapper`` so each JSONL line is parsed
    individually and discarded after batch flush.
  * **Idempotent** — ``INSERT OR IGNORE`` everywhere. Re-running on
    the same month no-ops at row-level.
  * **No LLM API import** (feedback_no_operator_llm_api).

Steps:

  1. Auth-gated download — uses bearer token via ``_gbiz_rate_limiter``
     httpx client with the same X-hojinInfo-api-token header.
  2. SHA-256 digest verification — log to ``<output_dir>/digest.log``,
     skip ingest if digest matches a previous run (idempotent re-run).
  3. Stream-extract — ``zipfile.ZipFile`` opens each member without
     decompressing the whole archive into memory.
  4. Reuse legacy field mapping — ``map_corp_facts`` ported from
     ``scripts/ingest_gbiz_facts.py`` so the corp.* namespace is
     consistent across legacy bulk + REST v2 + bulk v2 paths.
  5. Drop image fields per DEEP_01 §6.
  6. Batch INSERT in chunks of 1000 to gbiz_corp_activity / branches /
     workplaces + am_entities / am_entity_facts.
  7. Log every 10,000 lines processed (rate, totals, ETA).
  8. Write ``<yyyy-mm>/MANIFEST.json`` on completion (counts + digest +
     duration + records written per table).

CLI:
    --zip-url        default https://info.gbiz.go.jp/hojin/DownloadTop
    --output-dir     default /data/_gbiz_bulk/<yyyy-mm> on Fly,
                     else tools/offline/_inbox/_gbiz_bulk/<yyyy-mm>
    --keep-zip       boolean (default False — local dedupe only)
    --dry-run        no DB writes, log totals only
    --db-path        default $AUTONOMATH_DB_PATH or repo-root autonomath.db

Exit codes:
    0  success
    1  download / auth / parse error
    2  DB error
    3  digest mismatch / ZIP corrupt

References:
    tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_01_gbizinfo_ingest_activation.md §1.2 #6
    scripts/ingest_gbiz_facts.py — legacy one-shot, field_name namespace 共有
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import re
import sqlite3
import sys
import time
import zipfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Path setup — make src/ + scripts/ importable.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
_SCRIPTS = _REPO_ROOT / "scripts"
for _p in (_SRC, _SCRIPTS):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    from jpintel_mcp.ingest import _gbiz_rate_limiter as _gbiz  # noqa: E402
    from jpintel_mcp.ingest._gbiz_attribution import build_attribution  # noqa: E402
except ImportError as exc:  # pragma: no cover — IMPL-01a not yet landed
    print(
        f"missing module jpintel_mcp.ingest._gbiz_rate_limiter: {exc}",
        file=sys.stderr,
    )
    sys.exit(1)

# Reuse legacy field mapping. _record_to_facts maps a raw gBiz JSONL
# record into the (field_name, field_kind, ...) tuples we INSERT into
# am_entity_facts. We re-export it as map_corp_facts for clarity.
try:
    from ingest_gbiz_facts import _record_to_facts as map_corp_facts  # noqa: E402
except ImportError as exc:  # pragma: no cover
    print(
        f"failed to import legacy mapping from scripts/ingest_gbiz_facts.py: {exc}",
        file=sys.stderr,
    )
    sys.exit(1)

_LOG = logging.getLogger("autonomath.cron.ingest_gbiz_bulk_jsonl_monthly")

_DEFAULT_DB = Path(
    os.environ.get(
        "AUTONOMATH_DB_PATH",
        str(_REPO_ROOT / "autonomath.db"),
    )
)
_DEFAULT_ZIP_URL = "https://info.gbiz.go.jp/hojin/DownloadTop"

SOURCE_KEY = "https://info.gbiz.go.jp/"
SOURCE_DOMAIN = "info.gbiz.go.jp"
SOURCE_TOPIC = "gbizinfo_bulk"
UPSTREAM_SOURCE = "NTA Houjin Bangou Web-API"
CONFIDENCE = 0.95
NTA_PERMALINK_FMT = "https://www.houjin-bangou.nta.go.jp/henkorireki-johoto.html?selHoujinNo={}"

# DEEP_01 §6 — drop any field matching this regex before ingest.
_IMAGE_FIELD_RE = re.compile(r"_image|_logo|_mark|_base64", re.IGNORECASE)

# Batch size — INSERT OR IGNORE chunk size for the 3 mirror tables +
# am_entities / am_entity_facts. 1000 keeps memory footprint < 50 MB
# even with ~21 facts per record.
_BATCH_SIZE = 1000

# Progress log cadence.
_PROGRESS_INTERVAL = 10_000


# ---------------------------------------------------------------------------
# Output dir resolution
# ---------------------------------------------------------------------------


def _default_output_dir() -> Path:
    """Fly volume → /data/_gbiz_bulk/<yyyy-mm>/, else local _inbox path."""
    yyyymm = datetime.now(tz=UTC).strftime("%Y-%m")
    if Path("/data").is_dir():
        return Path("/data/_gbiz_bulk") / yyyymm
    return _REPO_ROOT / "tools" / "offline" / "_inbox" / "_gbiz_bulk" / yyyymm


# ---------------------------------------------------------------------------
# Image-field scrubbing (DEEP_01 §6)
# ---------------------------------------------------------------------------


def _scrub_images(rec: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `rec` with all `_image|_logo|_mark|_base64` fields removed."""
    if not isinstance(rec, dict):
        return rec
    out: dict[str, Any] = {}
    for k, v in rec.items():
        if _IMAGE_FIELD_RE.search(k):
            continue
        if isinstance(v, dict):
            out[k] = _scrub_images(v)
        elif isinstance(v, list):
            out[k] = [_scrub_images(item) if isinstance(item, dict) else item for item in v]
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Download + digest verification
# ---------------------------------------------------------------------------


def _download_zip(url: str, target: Path) -> Path:
    """Download the bulk ZIP to `target`. Auth via _gbiz_rate_limiter token.

    We bypass the json-decode / cache_meta wrapper of `_gbiz.get` because
    this is a binary stream, not a JSON envelope. We DO reuse the bearer
    header so the 1-token原則 stays intact.
    """
    import httpx  # noqa: PLC0415 — local import, not always needed.

    target.parent.mkdir(parents=True, exist_ok=True)
    headers = getattr(_gbiz, "_HEADER", {"Accept": "application/octet-stream"})
    token = os.environ.get("GBIZINFO_API_TOKEN")
    if token and "X-hojinInfo-api-token" not in headers:
        headers = dict(headers)
        headers["X-hojinInfo-api-token"] = token

    _LOG.info("zip_download_start url=%s target=%s", url, target)
    started = time.monotonic()
    bytes_written = 0
    with (
        httpx.Client(timeout=600.0, follow_redirects=True) as client,
        client.stream("GET", url, headers=headers) as resp,
    ):
        if resp.status_code == 401 or resp.status_code == 403:
            raise RuntimeError(
                f"gbiz_bulk_auth_failed status={resp.status_code} — "
                "token rejected; verify GBIZINFO_API_TOKEN and 申請承認"
            )
        if resp.status_code == 429:
            raise RuntimeError("gbiz_bulk_rate_limit_exceeded — fail fast for manual review")
        resp.raise_for_status()
        with target.open("wb") as fh:
            for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                if chunk:
                    fh.write(chunk)
                    bytes_written += len(chunk)
    elapsed = time.monotonic() - started
    _LOG.info(
        "zip_download_done bytes=%d elapsed=%.1fs path=%s",
        bytes_written,
        elapsed,
        target,
    )
    return target


def _sha256(path: Path) -> str:
    """Stream SHA-256 — never loads the ZIP into memory."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_digest_log(log_path: Path) -> set[str]:
    """Read previously-seen digests so re-runs on the same ZIP no-op."""
    seen: set[str] = set()
    if not log_path.exists():
        return seen
    try:
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                d = row.get("sha256")
                if d:
                    seen.add(d)
            except json.JSONDecodeError:
                continue
    except OSError as exc:
        _LOG.warning("digest_log_read_failed path=%s err=%s", log_path, exc)
    return seen


def _append_digest_log(log_path: Path, digest: str, zip_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "sha256": digest,
        "zip_path": str(zip_path),
        "fetched_at": datetime.now(tz=UTC).isoformat(),
    }
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# JSONL streaming from inside the ZIP
# ---------------------------------------------------------------------------


def _iter_jsonl_lines(zip_path: Path) -> Iterator[dict[str, Any]]:
    """Yield each JSONL record from inside the ZIP without loading whole file.

    Handles the case where the ZIP contains multiple .jsonl members.
    Lines that fail JSON parse are logged and skipped (not raised).
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = [m for m in zf.namelist() if m.endswith((".jsonl", ".json", ".ndjson"))]
        if not members:
            # Some bulk distributions ship a flat JSON array; fall back.
            members = [m for m in zf.namelist() if not m.endswith("/")]
        _LOG.info("zip_members count=%d names=%s", len(members), members[:5])
        for member in members:
            with (
                zf.open(member, "r") as raw,
                io.TextIOWrapper(raw, encoding="utf-8", errors="replace") as fh,
            ):
                if member.endswith(".json") and not member.endswith((".jsonl", ".ndjson")):
                    try:
                        yield from _iter_json_records(json.load(fh))
                    except json.JSONDecodeError as exc:
                        _LOG.warning("json_skip member=%s err=%s", member, exc)
                    continue
                for lineno, line in enumerate(fh, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield from _iter_json_records(json.loads(line))
                    except json.JSONDecodeError as exc:
                        _LOG.warning(
                            "jsonl_skip member=%s lineno=%d err=%s",
                            member,
                            lineno,
                            exc,
                        )
                        continue


def _iter_json_records(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield item


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _open_db(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"db not found: {path}")
    conn = sqlite3.connect(str(path), timeout=300)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA cache_size = -200000")  # ~200 MB
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn


def _now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")


def _today_iso_date() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%d")


def _gbiz_lookup_url(houjin_bangou: str) -> str:
    return f"https://info.gbiz.go.jp/hojin/ichiran?hojinBango={houjin_bangou}"


def _gbiz_attribution_json(houjin_bangou: str, fetched_at: str) -> str:
    attribution = build_attribution(
        source_url=_gbiz_lookup_url(houjin_bangou),
        fetched_at=fetched_at,
        upstream_source=UPSTREAM_SOURCE,
    )["_attribution"]
    return json.dumps(attribution, ensure_ascii=False)


def _trim(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s == "-":
        return None
    return s


def _to_int(value: Any) -> int | None:
    if value is None or value == "" or value == "-":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_iso_date(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s == "-":
        return None
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return None


# ---------------------------------------------------------------------------
# Batch buffers + flush
# ---------------------------------------------------------------------------


class _Batches:
    """Mutable holder for per-table row buffers + counters."""

    def __init__(self) -> None:
        self.corp_activity: list[tuple[Any, ...]] = []
        self.branches: list[tuple[Any, ...]] = []
        self.workplaces: list[tuple[Any, ...]] = []
        self.entities: list[tuple[Any, ...]] = []
        self.facts: list[tuple[Any, ...]] = []

        self.counts = {
            "corp_activity": 0,
            "branches": 0,
            "workplaces": 0,
            "entities": 0,
            "facts": 0,
        }

    def maybe_flush(
        self,
        conn: sqlite3.Connection | None,
        *,
        dry_run: bool,
        force: bool = False,
    ) -> None:
        if (
            not force
            and len(self.corp_activity) < _BATCH_SIZE
            and len(self.branches) < _BATCH_SIZE * 2
            and len(self.workplaces) < _BATCH_SIZE * 2
            and len(self.entities) < _BATCH_SIZE
            and len(self.facts) < _BATCH_SIZE * 21
        ):
            return

        # Update counts first so dry-run also reports.
        self.counts["corp_activity"] += len(self.corp_activity)
        self.counts["branches"] += len(self.branches)
        self.counts["workplaces"] += len(self.workplaces)
        self.counts["entities"] += len(self.entities)
        self.counts["facts"] += len(self.facts)

        if dry_run or conn is None:
            self._reset()
            return

        if self.corp_activity:
            conn.executemany(
                """
                INSERT OR IGNORE INTO gbiz_corp_activity (
                    houjin_bangou, legal_name, legal_name_kana, legal_name_en,
                    location, postal_code, representative_name, representative_position,
                    business_summary, business_items_json,
                    capital_stock_yen, employee_number, employee_male, employee_female,
                    founding_year, date_of_establishment, close_date, close_cause,
                    status, company_url, qualification_grade, gbiz_update_date,
                    source_url, fetched_at, cache_age_hours, upstream_source,
                    attribution_json, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self.corp_activity,
            )
        if self.branches:
            conn.executemany(
                """
                INSERT OR IGNORE INTO gbiz_corporation_branch (
                    houjin_bangou, branch_name, branch_kana, location,
                    postal_code, branch_kind, fetched_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self.branches,
            )
        if self.workplaces:
            conn.executemany(
                """
                INSERT OR IGNORE INTO gbiz_workplace (
                    houjin_bangou, workplace_name, location, postal_code,
                    employee_number, fetched_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                self.workplaces,
            )
        if self.entities:
            conn.executemany(
                """
                INSERT OR IGNORE INTO am_entities (
                    canonical_id, record_kind, source_topic, source_record_index,
                    primary_name, authority_canonical, confidence,
                    source_url, source_url_domain, fetched_at, raw_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self.entities,
            )
        if self.facts:
            conn.executemany(
                """
                INSERT OR IGNORE INTO am_entity_facts (
                    entity_id, field_name, field_value_text,
                    field_value_json, field_value_numeric,
                    field_kind, unit, source_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self.facts,
            )

        conn.commit()
        self._reset()

    def _reset(self) -> None:
        self.corp_activity = []
        self.branches = []
        self.workplaces = []
        self.entities = []
        self.facts = []


# ---------------------------------------------------------------------------
# Row builders — same shape as ingest_gbiz_corporate_v2.py
# ---------------------------------------------------------------------------


def _build_corp_activity_row(rec: dict[str, Any], cn: str) -> tuple[Any, ...] | None:
    bi = rec.get("business_items")
    bi_json = json.dumps(bi, ensure_ascii=False) if isinstance(bi, list) else None
    fetched_at = _now_iso()
    return (
        cn,
        _trim(rec.get("name")) or cn,
        _trim(rec.get("kana")),
        _trim(rec.get("name_en")),
        _trim(rec.get("location")),
        _trim(rec.get("postal_code")),
        _trim(rec.get("representative_name")),
        _trim(rec.get("representative_position")),
        _trim(rec.get("business_summary")),
        bi_json,
        _to_int(rec.get("capital_stock")),
        _to_int(rec.get("employee_number")),
        _to_int(rec.get("company_size_male")),
        _to_int(rec.get("company_size_female")),
        _to_int(rec.get("founding_year")),
        _to_iso_date(rec.get("date_of_establishment")),
        _to_iso_date(rec.get("close_date")),
        _trim(rec.get("close_cause")),
        _trim(rec.get("status")),
        _trim(rec.get("company_url")),
        _trim(rec.get("qualification_grade")),
        _to_iso_date(rec.get("update_date")),
        _gbiz_lookup_url(cn),
        fetched_at,
        None,  # cache_age_hours — bulk path is a fresh fetch
        UPSTREAM_SOURCE,
        _gbiz_attribution_json(cn, fetched_at),
        json.dumps(rec, ensure_ascii=False),
    )


def _build_entity_row(rec: dict[str, Any], cn: str) -> tuple[Any, ...]:
    canonical_id = f"houjin:{cn}"
    primary_name = _trim(rec.get("name")) or canonical_id
    source_url = NTA_PERMALINK_FMT.format(cn)
    raw_json = json.dumps(rec, ensure_ascii=False)
    fetched_at = _today_iso_date()
    now = _now_iso()
    return (
        canonical_id,
        "corporate_entity",
        SOURCE_TOPIC,
        None,
        primary_name,
        None,
        CONFIDENCE,
        source_url,
        SOURCE_DOMAIN,
        fetched_at,
        raw_json,
        now,
        now,
    )


# ---------------------------------------------------------------------------
# MANIFEST.json writer
# ---------------------------------------------------------------------------


def _write_manifest(
    output_dir: Path,
    *,
    digest: str,
    zip_path: Path | None,
    counts: dict[str, int],
    duration_seconds: float,
    dry_run: bool,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "fetched_at": _now_iso(),
        "yyyy_mm": datetime.now(tz=UTC).strftime("%Y-%m"),
        "zip_sha256": digest,
        "zip_path": str(zip_path) if zip_path else None,
        "row_counts": counts,
        "duration_seconds": round(duration_seconds, 2),
        "dry_run": dry_run,
        "source": {
            "source_url": SOURCE_KEY,
            "publisher": "経済産業省",
            "license": "政府標準利用規約 第2.0版 (CC BY 4.0 互換)",
            "license_url": "https://help.info.gbiz.go.jp/hc/ja/articles/4795140981406",
        },
    }
    path = output_dir / "MANIFEST.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _LOG.info("manifest_written path=%s", path)
    return path


# ---------------------------------------------------------------------------
# Main ingest loop
# ---------------------------------------------------------------------------


def ingest_zip(
    *,
    zip_path: Path,
    db_path: Path,
    dry_run: bool,
) -> dict[str, int]:
    """Stream-extract `zip_path`, batch-INSERT into all 5 mirror tables."""
    conn: sqlite3.Connection | None = None
    if not dry_run:
        try:
            conn = _open_db(db_path)
        except (sqlite3.Error, SystemExit) as exc:
            _LOG.error("db_open_failed path=%s err=%s", db_path, exc)
            raise

    batches = _Batches()
    processed = 0
    skipped_no_cn = 0
    started = time.monotonic()

    try:
        for raw_rec in _iter_jsonl_lines(zip_path):
            rec = _scrub_images(raw_rec)
            cn = _trim(rec.get("corporate_number"))
            if not cn:
                skipped_no_cn += 1
                processed += 1
                continue

            # 1) gbiz_corp_activity row.
            row = _build_corp_activity_row(rec, cn)
            if row is not None:
                batches.corp_activity.append(row)

            # 2) gbiz_corporation_branch (if record carries a branches list).
            branches_list = rec.get("corporation") or rec.get("branches")
            if isinstance(branches_list, list):
                fetched_at = _now_iso()
                for br in branches_list:
                    if not isinstance(br, dict):
                        continue
                    batches.branches.append(
                        (
                            cn,
                            _trim(br.get("name") or br.get("branch_name")),
                            _trim(br.get("kana") or br.get("branch_kana")),
                            _trim(br.get("location")),
                            _trim(br.get("postal_code")),
                            _trim(br.get("kind") or br.get("branch_kind")),
                            fetched_at,
                            json.dumps(br, ensure_ascii=False),
                        )
                    )

            # 3) gbiz_workplace.
            wp_list = rec.get("workplace") or rec.get("workplaces")
            if isinstance(wp_list, list):
                fetched_at = _now_iso()
                for wp in wp_list:
                    if not isinstance(wp, dict):
                        continue
                    batches.workplaces.append(
                        (
                            cn,
                            _trim(wp.get("name") or wp.get("workplace_name")),
                            _trim(wp.get("location")),
                            _trim(wp.get("postal_code")),
                            _to_int(wp.get("employee_number")),
                            fetched_at,
                            json.dumps(wp, ensure_ascii=False),
                        )
                    )

            # 4) am_entities + am_entity_facts cross-write.
            batches.entities.append(_build_entity_row(rec, cn))
            for f in map_corp_facts(rec):
                batches.facts.append(
                    (
                        f"houjin:{cn}",
                        f["field_name"],
                        f["field_value_text"],
                        f["field_value_json"],
                        f["field_value_numeric"],
                        f["field_kind"],
                        f["unit"],
                        SOURCE_KEY,
                    )
                )

            processed += 1
            batches.maybe_flush(conn, dry_run=dry_run)

            if processed % _PROGRESS_INTERVAL == 0:
                elapsed = time.monotonic() - started
                rate = processed / max(elapsed, 1e-9)
                _LOG.info(
                    "progress lines=%d skipped_no_cn=%d corp_activity=%d "
                    "branches=%d workplaces=%d entities=%d facts=%d "
                    "rate=%.0f/s elapsed=%.1fs",
                    processed,
                    skipped_no_cn,
                    batches.counts["corp_activity"],
                    batches.counts["branches"],
                    batches.counts["workplaces"],
                    batches.counts["entities"],
                    batches.counts["facts"],
                    rate,
                    elapsed,
                )

        # Final flush.
        batches.maybe_flush(conn, dry_run=dry_run, force=True)
    finally:
        if conn is not None:
            with suppress(sqlite3.Error):
                conn.commit()
            conn.close()

    elapsed = time.monotonic() - started
    counts = dict(batches.counts)
    counts["processed"] = processed
    counts["skipped_no_corporate_number"] = skipped_no_cn
    counts["elapsed_seconds"] = round(elapsed, 2)

    _LOG.info("ingest_done counts=%s", counts)
    return counts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="gBizINFO bulk ZIP cold-start + monthly refresh ingest",
    )
    p.add_argument(
        "--zip-url",
        type=str,
        default=_DEFAULT_ZIP_URL,
        help=f"認証付き bulk ZIP の URL (default: {_DEFAULT_ZIP_URL})",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="ZIP / digest log / MANIFEST.json の出力先 (default: /data 優先)",
    )
    p.add_argument(
        "--keep-zip",
        action="store_true",
        help="ZIP をローカル保持 (再配布禁止: §6)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="DB 書込みなし。行数だけ log",
    )
    p.add_argument(
        "--db-path",
        "--db",
        dest="db_path",
        type=Path,
        default=_DEFAULT_DB,
        help="autonomath.db path (default: $AUTONOMATH_DB_PATH または repo-root)",
    )
    p.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="optional JSONL/plain log file path used by scheduled runners",
    )
    p.add_argument(
        "--zip-path",
        type=Path,
        default=None,
        help="(testing) ダウンロード済 ZIP path を指定して download step を skip",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if args.log_file is not None:
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        handlers=handlers,
        force=True,
    )

    # Rollback knob — DEEP_01 §7.2.
    if os.environ.get("GBIZINFO_INGEST_ENABLED", "true").lower() == "false":
        _LOG.info("gbiz_ingest_disabled — clean shutdown via env flag")
        return 0

    output_dir: Path = args.output_dir or _default_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    digest_log = output_dir / "digest.log"

    started = time.monotonic()

    # 1) Acquire ZIP — download or use --zip-path.
    zip_path: Path
    try:
        if args.zip_path:
            zip_path = args.zip_path
            if not zip_path.exists():
                _LOG.error("zip_not_found path=%s", zip_path)
                return 1
        else:
            zip_path = output_dir / f"gbiz_bulk_{datetime.now(tz=UTC).strftime('%Y%m%d')}.zip"
            _download_zip(args.zip_url, zip_path)
    except RuntimeError as exc:
        _LOG.error("download_failed err=%s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001
        _LOG.error("download_failed err=%s", exc)
        return 1

    # 2) Verify ZIP digest, dedupe against previous runs.
    try:
        digest = _sha256(zip_path)
    except OSError as exc:
        _LOG.error("digest_compute_failed path=%s err=%s", zip_path, exc)
        return 3
    _LOG.info("zip_digest sha256=%s path=%s", digest, zip_path)

    seen = _read_digest_log(digest_log)
    if digest in seen:
        _LOG.info("zip_digest_already_ingested digest=%s — no-op", digest)
        # Still write MANIFEST so the cron has a stable artifact.
        _write_manifest(
            output_dir,
            digest=digest,
            zip_path=zip_path if args.keep_zip else None,
            counts={"processed": 0, "skipped_idempotent": 1},
            duration_seconds=time.monotonic() - started,
            dry_run=args.dry_run,
        )
        if not args.keep_zip and not args.zip_path:
            with suppress(OSError):
                zip_path.unlink()
        return 0

    # 3-7) Stream-extract + batch INSERT.
    try:
        counts = ingest_zip(
            zip_path=zip_path,
            db_path=args.db_path,
            dry_run=args.dry_run,
        )
    except sqlite3.Error as exc:
        _LOG.error("db_error err=%s", exc)
        return 2
    except (zipfile.BadZipFile, OSError) as exc:
        _LOG.error("zip_corrupt err=%s", exc)
        return 3
    except Exception as exc:  # noqa: BLE001
        _LOG.error("ingest_failed err=%s", exc)
        return 1

    # 8) Persist digest + MANIFEST + cleanup.
    if not args.dry_run:
        _append_digest_log(digest_log, digest, zip_path)
    duration = time.monotonic() - started
    _write_manifest(
        output_dir,
        digest=digest,
        zip_path=zip_path if args.keep_zip else None,
        counts=counts,
        duration_seconds=duration,
        dry_run=args.dry_run,
    )

    if not args.keep_zip and not args.zip_path:
        try:
            zip_path.unlink()
            _LOG.info("zip_deleted path=%s (--keep-zip not set)", zip_path)
        except OSError as exc:
            _LOG.warning("zip_delete_failed path=%s err=%s", zip_path, exc)

    print(json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
