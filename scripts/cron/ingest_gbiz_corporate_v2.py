#!/usr/bin/env python3
"""gBizINFO REST API v2 — corporate_activity ingest cron driver.

DEEP_01 §1.2 entry 1 implementation. Wraps the 4 endpoints that make up
the ``gbizinfo_corporate_activity_v2`` source family:

  1. ``/v2/hojin/{n}``                    — 法人基本情報 (corporation profile)
  2. ``/v2/hojin/{n}/corporation``        — 支店 / 事業所 (branches)
  3. ``/v2/hojin/{n}/workplace``          — 雇用情報 (workplaces / employee splits)
  4. ``/v2/hojin/updateInfo/corporation?from=&to=``  — delta 更新通知

All HTTP traffic flows through ``jpintel_mcp.ingest._gbiz_rate_limiter``
(1 rps + 24h disk cache + Bookyou名義 single-token header injection).
No LLM API import (feedback_no_operator_llm_api).

Two modes:

  * **Mode A (per-houjin lookup)**: ``--houjin-bangou 8010001213708``
    fetches all 3 per-houjin endpoints for a single company.
    Used for live customer queries and Bookyou self smoke test.

  * **Mode B (delta sync)**: ``--from 2026-04-01 --to 2026-05-01``
    pulls the updateInfo/corporation feed, then re-fetches each
    listed houjin via the per-houjin endpoints. This is the cron
    monthly re-pull pattern.

Writes:
    * ``gbiz_corp_activity``         — 1 row per houjin (PRIMARY KEY houjin_bangou)
    * ``gbiz_corporation_branch``    — 1+ rows per houjin (UNIQUE branch_name+location)
    * ``gbiz_workplace``             — 1+ rows per houjin (UNIQUE workplace_name+location)
    * ``gbiz_update_log``            — 1 row per delta sync run
    * ``am_entities``                — record_kind='corporate_entity', upsert by canonical_id
    * ``am_entity_facts``            — corp.* namespace, replace-by-houjin snapshot

Exit codes:
    0  success
    1  API / auth error (RuntimeError from rate limiter, httpx errors)
    2  DB error (sqlite3.Error)

Usage:

    # Mode A — Bookyou self smoke test
    .venv/bin/python scripts/cron/ingest_gbiz_corporate_v2.py \\
        --houjin-bangou 8010001213708 --dry-run

    # Mode B — monthly delta re-pull
    .venv/bin/python scripts/cron/ingest_gbiz_corporate_v2.py \\
        --from 2026-04-01 --to 2026-05-01

References:
    tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_01_gbizinfo_ingest_activation.md §1.2
    scripts/migrations/<wave24_164>_gbiz_v2_mirror_tables.sql
    scripts/ingest_gbiz_facts.py (legacy bulk JSONL ingest, field_name namespace 共有)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path setup — make src/ importable so we can pull the rate limiter module.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

try:
    # 1 rps + 24h cache + bearer token injection.
    # IMPL-01a is creating this module concurrently; cron runs only after deploy.
    from jpintel_mcp.ingest import _gbiz_rate_limiter as _gbiz  # noqa: E402
    from jpintel_mcp.ingest._gbiz_attribution import build_attribution  # noqa: E402
except ImportError as exc:  # pragma: no cover — IMPL-01a not yet landed
    print(
        f"missing module jpintel_mcp.ingest._gbiz_rate_limiter: {exc}\n"
        f"  → ensure src/jpintel_mcp/ingest/_gbiz_rate_limiter.py is on disk\n"
        f"  → see DEEP_01 §1.4",
        file=sys.stderr,
    )
    sys.exit(1)

_LOG = logging.getLogger("autonomath.cron.ingest_gbiz_corporate_v2")

_DEFAULT_DB = Path(
    os.environ.get(
        "AUTONOMATH_DB_PATH",
        str(_REPO_ROOT / "autonomath.db"),
    )
)

# 出典: gBizINFO 利用規約 §出典表記
SOURCE_KEY = "https://info.gbiz.go.jp/"
SOURCE_DOMAIN = "info.gbiz.go.jp"
SOURCE_TOPIC = "gbizinfo"
UPSTREAM_SOURCE = "NTA Houjin Bangou Web-API"  # corp.* facts originate from NTA
CONFIDENCE = 0.95  # METI primary, fully structured JSON
NTA_PERMALINK_FMT = "https://www.houjin-bangou.nta.go.jp/henkorireki-johoto.html?selHoujinNo={}"

# 個別法令マーク image を防御的に除外 (DEEP_01 §6, ToS condition 6).
# REST API v2 には現状 image field は無いが将来の schema 追加に備える。
_IMAGE_FIELD_BLOCKLIST = {
    "law_mark_image",
    "law_mark_logo",
    "individual_law_mark",
    "image_base64",
}


class SchemaError(RuntimeError):
    """Raised when the target DB is missing tables/columns needed before fetch."""


_GBIZ_CORP_ACTIVITY_REQUIRED_COLUMNS = {
    "houjin_bangou",
    "legal_name",
    "legal_name_kana",
    "legal_name_en",
    "location",
    "postal_code",
    "representative_name",
    "representative_position",
    "business_summary",
    "business_items_json",
    "capital_stock_yen",
    "employee_number",
    "employee_male",
    "employee_female",
    "founding_year",
    "date_of_establishment",
    "close_date",
    "close_cause",
    "status",
    "company_url",
    "qualification_grade",
    "gbiz_update_date",
    "source_url",
    "fetched_at",
    "cache_age_hours",
    "upstream_source",
    "attribution_json",
    "raw_json",
}
_GBIZ_BRANCH_REQUIRED_COLUMNS = {
    "houjin_bangou",
    "branch_name",
    "branch_kana",
    "location",
    "postal_code",
    "branch_kind",
    "fetched_at",
    "raw_json",
}
_GBIZ_WORKPLACE_REQUIRED_COLUMNS = {
    "houjin_bangou",
    "workplace_name",
    "location",
    "postal_code",
    "employee_number",
    "fetched_at",
    "raw_json",
}
_GBIZ_UPDATE_LOG_REQUIRED_COLUMNS = {
    "endpoint",
    "from_date",
    "to_date",
    "record_count",
    "fetched_at",
    "next_token",
}
_AM_ENTITIES_REQUIRED_COLUMNS = {
    "canonical_id",
    "record_kind",
    "source_topic",
    "source_record_index",
    "primary_name",
    "authority_canonical",
    "confidence",
    "source_url",
    "source_url_domain",
    "fetched_at",
    "raw_json",
    "created_at",
    "updated_at",
}
_AM_ENTITY_FACTS_REQUIRED_COLUMNS = {
    "entity_id",
    "field_name",
    "field_value_text",
    "field_value_json",
    "field_value_numeric",
    "field_kind",
    "unit",
    "source_url",
}


# ---------------------------------------------------------------------------
# Helpers — value normalization (legacy mapping reuse where practical)
# ---------------------------------------------------------------------------


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


def _scrub_image_fields(rec: dict[str, Any]) -> dict[str, Any]:
    """ToS §6 個別法令マーク image を再帰的に削除して返す。"""
    if not isinstance(rec, dict):
        return rec
    cleaned: dict[str, Any] = {}
    for k, v in rec.items():
        if k in _IMAGE_FIELD_BLOCKLIST:
            continue
        if isinstance(v, dict):
            cleaned[k] = _scrub_image_fields(v)
        elif isinstance(v, list):
            cleaned[k] = [
                _scrub_image_fields(item) if isinstance(item, dict) else item for item in v
            ]
        else:
            cleaned[k] = v
    return cleaned


def _extract_houjin_numbers(body: dict[str, Any]) -> list[str]:
    """Extract corporate numbers from an updateInfo response envelope."""
    seen: set[str] = set()
    out: list[str] = []

    def add(value: Any) -> None:
        text = _trim(value)
        if text and text not in seen:
            seen.add(text)
            out.append(text)

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key in ("corporate_number", "corporateNumber", "houjin_bangou"):
                if key in value:
                    add(value.get(key))
            for child in value.values():
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(body)
    return out


def _page_count(body: dict[str, Any]) -> int:
    if not isinstance(body, dict):
        return 1
    for key in ("totalPage", "total_page", "total_pages"):
        total = _to_int(body.get(key))
        if total is not None and total > 0:
            return total
    return 1


def _gbiz_date_param(value: str) -> str:
    return value.replace("-", "") if re.match(r"^\d{4}-\d{2}-\d{2}$", value) else value


# ---------------------------------------------------------------------------
# Endpoint helpers — thin wrappers around the rate limiter.
# ---------------------------------------------------------------------------


def fetch_corporation(houjin_bangou: str, *, force_refresh: bool = False) -> dict[str, Any]:
    """GET /v2/hojin/{n} — 法人基本情報を取得。"""
    path = f"v2/hojin/{houjin_bangou}"
    body = _gbiz.get(path, force_refresh=force_refresh)
    return _scrub_image_fields(body)


def fetch_corporation_branches(
    houjin_bangou: str,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """GET /v2/hojin/{n}/corporation — 支店・事業所一覧。"""
    path = f"v2/hojin/{houjin_bangou}/corporation"
    body = _gbiz.get(path, force_refresh=force_refresh)
    return _scrub_image_fields(body)


def fetch_workplaces(houjin_bangou: str, *, force_refresh: bool = False) -> dict[str, Any]:
    """GET /v2/hojin/{n}/workplace — 事業所別 雇用情報。"""
    path = f"v2/hojin/{houjin_bangou}/workplace"
    body = _gbiz.get(path, force_refresh=force_refresh)
    return _scrub_image_fields(body)


def fetch_updates(date_from: str, date_to: str, *, page: int = 1) -> dict[str, Any]:
    """GET /v2/hojin/updateInfo/corporation?from=&to= — delta 更新通知。

    Returns the raw envelope; caller drills into the houjin list and
    fans out to per-houjin re-fetches.
    """
    path = "v2/hojin/updateInfo/corporation"
    params = {
        "from": _gbiz_date_param(date_from),
        "to": _gbiz_date_param(date_to),
        "page": str(page),
    }
    body = _gbiz.get(path, params=params, force_refresh=True)
    return _scrub_image_fields(body)


# ---------------------------------------------------------------------------
# DB upsert helpers
# ---------------------------------------------------------------------------


def _open_db(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"db not found: {path}")
    conn = sqlite3.connect(str(path), timeout=120)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA cache_size = -100000")  # ~100 MB
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn


def _canonical_cross_write_enabled() -> bool:
    return os.environ.get("GBIZINFO_CANONICAL_CROSS_WRITE_ENABLED", "false").lower() == "true"


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def _index_exists(conn: sqlite3.Connection, index_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
        (index_name,),
    ).fetchone()
    return row is not None


def _ensure_table_columns(
    conn: sqlite3.Connection,
    table_name: str,
    required_columns: set[str],
) -> None:
    if not _table_exists(conn, table_name):
        raise SchemaError(
            f"{table_name} table missing — run migration "
            "wave24_164_gbiz_v2_mirror_tables.sql first."
        )
    missing = sorted(required_columns - _table_columns(conn, table_name))
    if missing:
        raise SchemaError(f"{table_name} missing columns: {', '.join(missing)}")


def _ensure_schema(conn: sqlite3.Connection, *, canonical_enabled: bool) -> None:
    _ensure_table_columns(conn, "gbiz_corp_activity", _GBIZ_CORP_ACTIVITY_REQUIRED_COLUMNS)
    _ensure_table_columns(conn, "gbiz_corporation_branch", _GBIZ_BRANCH_REQUIRED_COLUMNS)
    _ensure_table_columns(conn, "gbiz_workplace", _GBIZ_WORKPLACE_REQUIRED_COLUMNS)
    _ensure_table_columns(conn, "gbiz_update_log", _GBIZ_UPDATE_LOG_REQUIRED_COLUMNS)
    if not _index_exists(conn, "ux_gbiz_corp_branch_identity"):
        raise SchemaError("gbiz_corporation_branch unique identity index missing")
    if not _index_exists(conn, "ux_gbiz_workplace_identity"):
        raise SchemaError("gbiz_workplace unique identity index missing")
    if canonical_enabled:
        _ensure_table_columns(conn, "am_entities", _AM_ENTITIES_REQUIRED_COLUMNS)
        _ensure_table_columns(conn, "am_entity_facts", _AM_ENTITY_FACTS_REQUIRED_COLUMNS)


def _preflight_db(db_path: Path, *, canonical_enabled: bool) -> int:
    if not db_path.parent.is_dir():
        _LOG.error("DB parent dir missing: %s", db_path.parent)
        return 1
    if not db_path.is_file():
        _LOG.error("DB file missing: %s", db_path)
        return 2
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        _ensure_schema(conn, canonical_enabled=canonical_enabled)
    except SchemaError as exc:
        _LOG.error("schema check failed before fetch: %s", exc)
        return 2
    except sqlite3.Error as exc:
        _LOG.error("DB check failed before fetch: %s", exc)
        return 1
    finally:
        conn.close()
    return 0


def _hojin_info_block(envelope: dict[str, Any]) -> dict[str, Any]:
    """gBizINFO REST v2 wraps the corporation dict under hojin_info / hojin-info.

    Defensive against minor schema variation between versions.
    """
    if not isinstance(envelope, dict):
        return {}
    for key in ("hojin_info", "hojin-info", "hojinInfo"):
        block = envelope.get(key)
        if isinstance(block, dict):
            return block
    # Sometimes the body itself is the corp dict (no wrapper).
    if "corporate_number" in envelope or "name" in envelope:
        return envelope
    return {}


def upsert_corp_activity(
    conn: sqlite3.Connection,
    houjin_bangou: str,
    corp_envelope: dict[str, Any],
    *,
    cache_age_hours: float | None,
    dry_run: bool,
) -> int:
    """gbiz_corp_activity に upsert。1 行を書き戻し new/updated 数を返す。"""
    rec = _hojin_info_block(corp_envelope)
    if not rec:
        _LOG.warning("corp_activity_skip houjin=%s reason=empty_hojin_info", houjin_bangou)
        return 0

    business_items = rec.get("business_items")
    if isinstance(business_items, list):
        business_items_json = json.dumps(business_items, ensure_ascii=False)
    else:
        business_items_json = None

    fetched_at = _now_iso()
    params = (
        houjin_bangou,
        _trim(rec.get("name")) or houjin_bangou,
        _trim(rec.get("kana")),
        _trim(rec.get("name_en")),
        _trim(rec.get("location")),
        _trim(rec.get("postal_code")),
        _trim(rec.get("representative_name")),
        _trim(rec.get("representative_position")),
        _trim(rec.get("business_summary")),
        business_items_json,
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
        _gbiz_lookup_url(houjin_bangou),
        fetched_at,
        cache_age_hours,
        UPSTREAM_SOURCE,
        _gbiz_attribution_json(houjin_bangou, fetched_at),
        json.dumps(rec, ensure_ascii=False),
    )

    if dry_run:
        return 1

    conn.execute(
        """
        INSERT INTO gbiz_corp_activity (
            houjin_bangou, legal_name, legal_name_kana, legal_name_en,
            location, postal_code, representative_name, representative_position,
            business_summary, business_items_json,
            capital_stock_yen, employee_number, employee_male, employee_female,
            founding_year, date_of_establishment, close_date, close_cause,
            status, company_url, qualification_grade, gbiz_update_date,
            source_url, fetched_at, cache_age_hours, upstream_source,
            attribution_json, raw_json
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        ON CONFLICT(houjin_bangou) DO UPDATE SET
            legal_name = excluded.legal_name,
            legal_name_kana = excluded.legal_name_kana,
            legal_name_en = excluded.legal_name_en,
            location = excluded.location,
            postal_code = excluded.postal_code,
            representative_name = excluded.representative_name,
            representative_position = excluded.representative_position,
            business_summary = excluded.business_summary,
            business_items_json = excluded.business_items_json,
            capital_stock_yen = excluded.capital_stock_yen,
            employee_number = excluded.employee_number,
            employee_male = excluded.employee_male,
            employee_female = excluded.employee_female,
            founding_year = excluded.founding_year,
            date_of_establishment = excluded.date_of_establishment,
            close_date = excluded.close_date,
            close_cause = excluded.close_cause,
            status = excluded.status,
            company_url = excluded.company_url,
            qualification_grade = excluded.qualification_grade,
            gbiz_update_date = excluded.gbiz_update_date,
            source_url = excluded.source_url,
            fetched_at = excluded.fetched_at,
            cache_age_hours = excluded.cache_age_hours,
            upstream_source = excluded.upstream_source,
            attribution_json = excluded.attribution_json,
            raw_json = excluded.raw_json
        """,
        params,
    )
    return 1


def upsert_branches(
    conn: sqlite3.Connection,
    houjin_bangou: str,
    branches_envelope: dict[str, Any],
    *,
    dry_run: bool,
) -> int:
    """gbiz_corporation_branch に bulk upsert。"""
    branches: list[dict[str, Any]] = []
    if isinstance(branches_envelope, dict):
        # Search for the array under various wrappers.
        for key in ("corporation", "branches", "corporations", "hojin_info"):
            block = branches_envelope.get(key)
            if isinstance(block, list):
                branches = [b for b in block if isinstance(b, dict)]
                break
            if isinstance(block, dict):
                inner = block.get("corporation") or block.get("branches")
                if isinstance(inner, list):
                    branches = [b for b in inner if isinstance(b, dict)]
                    break
    if not branches:
        if not dry_run:
            conn.execute(
                "DELETE FROM gbiz_corporation_branch WHERE houjin_bangou = ?",
                (houjin_bangou,),
            )
        return 0

    rows = []
    fetched_at = _now_iso()
    for br in branches:
        rows.append(
            (
                houjin_bangou,
                _trim(br.get("name") or br.get("branch_name")),
                _trim(br.get("kana") or br.get("branch_kana")),
                _trim(br.get("location")),
                _trim(br.get("postal_code")),
                _trim(br.get("kind") or br.get("branch_kind")),
                fetched_at,
                json.dumps(br, ensure_ascii=False),
            )
        )

    if dry_run:
        return len(rows)

    conn.execute(
        "DELETE FROM gbiz_corporation_branch WHERE houjin_bangou = ?",
        (houjin_bangou,),
    )
    conn.executemany(
        """
        INSERT INTO gbiz_corporation_branch (
            houjin_bangou, branch_name, branch_kana, location,
            postal_code, branch_kind, fetched_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(houjin_bangou, branch_name, location) DO UPDATE SET
            branch_kana = excluded.branch_kana,
            postal_code = excluded.postal_code,
            branch_kind = excluded.branch_kind,
            fetched_at = excluded.fetched_at,
            raw_json = excluded.raw_json
        """,
        rows,
    )
    return len(rows)


def upsert_workplaces(
    conn: sqlite3.Connection,
    houjin_bangou: str,
    workplace_envelope: dict[str, Any],
    *,
    dry_run: bool,
) -> int:
    """gbiz_workplace に bulk upsert。"""
    workplaces: list[dict[str, Any]] = []
    if isinstance(workplace_envelope, dict):
        for key in ("workplace", "workplaces", "hojin_info"):
            block = workplace_envelope.get(key)
            if isinstance(block, list):
                workplaces = [w for w in block if isinstance(w, dict)]
                break
            if isinstance(block, dict):
                inner = block.get("workplace")
                if isinstance(inner, list):
                    workplaces = [w for w in inner if isinstance(w, dict)]
                    break
    if not workplaces:
        if not dry_run:
            conn.execute(
                "DELETE FROM gbiz_workplace WHERE houjin_bangou = ?",
                (houjin_bangou,),
            )
        return 0

    rows = []
    fetched_at = _now_iso()
    for wp in workplaces:
        rows.append(
            (
                houjin_bangou,
                _trim(wp.get("name") or wp.get("workplace_name")),
                _trim(wp.get("location")),
                _trim(wp.get("postal_code")),
                _to_int(wp.get("employee_number")),
                fetched_at,
                json.dumps(wp, ensure_ascii=False),
            )
        )

    if dry_run:
        return len(rows)

    conn.execute(
        "DELETE FROM gbiz_workplace WHERE houjin_bangou = ?",
        (houjin_bangou,),
    )
    conn.executemany(
        """
        INSERT INTO gbiz_workplace (
            houjin_bangou, workplace_name, location, postal_code,
            employee_number, fetched_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(houjin_bangou, workplace_name, location) DO UPDATE SET
            postal_code = excluded.postal_code,
            employee_number = excluded.employee_number,
            fetched_at = excluded.fetched_at,
            raw_json = excluded.raw_json
        """,
        rows,
    )
    return len(rows)


def insert_update_log(
    conn: sqlite3.Connection,
    *,
    endpoint: str,
    date_from: str,
    date_to: str,
    record_count: int,
    next_token: str | None,
    dry_run: bool,
) -> None:
    """gbiz_update_log に 1 行 append。delta sync のみで呼ぶ。"""
    if dry_run:
        return
    conn.execute(
        """
        INSERT OR IGNORE INTO gbiz_update_log (
            endpoint, from_date, to_date, record_count, fetched_at, next_token
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (endpoint, date_from, date_to, record_count, _now_iso(), next_token),
    )


# ---------------------------------------------------------------------------
# am_entities + am_entity_facts cross-write (unified entity graph)
# ---------------------------------------------------------------------------


def _build_facts(
    rec: dict[str, Any],
) -> list[tuple[str, str, str | None, float | None, str | None, str | None]]:
    """Map one corp record to (field_name, field_kind, text, numeric, json, unit) tuples.

    Mirrors scripts/ingest_gbiz_facts.py::_record_to_facts so the corp.*
    namespace stays consistent across legacy bulk + new REST v2 ingest.
    """
    out: list[tuple[str, str, str | None, float | None, str | None, str | None]] = []

    def add(
        name: str,
        kind: str,
        *,
        text: str | None = None,
        numeric: float | int | None = None,
        json_value: Any = None,
        unit: str | None = None,
    ) -> None:
        if text is None and numeric is None and json_value is None:
            return
        if text is not None and not text:
            return
        out.append(
            (
                name,
                kind,
                text,
                float(numeric) if numeric is not None else None,
                json.dumps(json_value, ensure_ascii=False) if json_value is not None else None,
                unit,
            )
        )

    cn = _trim(rec.get("corporate_number"))
    if cn:
        add("houjin_bangou", "text", text=cn)
    add("corp.legal_name", "text", text=_trim(rec.get("name")))
    add("corp.legal_name_kana", "text", text=_trim(rec.get("kana")))
    add("corp.legal_name_en", "text", text=_trim(rec.get("name_en")))
    add("corp.location", "text", text=_trim(rec.get("location")))
    add("corp.postal_code", "text", text=_trim(rec.get("postal_code")))
    add("corp.representative", "text", text=_trim(rec.get("representative_name")))
    add("corp.representative_position", "text", text=_trim(rec.get("representative_position")))
    add("corp.business_summary", "text", text=_trim(rec.get("business_summary")))

    bi = rec.get("business_items")
    if isinstance(bi, list) and bi:
        clean = [str(x) for x in bi if x is not None]
        if clean:
            add("corp.business_items", "list", text=",".join(clean), json_value=clean)

    add("corp.qualification_grade", "text", text=_trim(rec.get("qualification_grade")))

    cap = _to_int(rec.get("capital_stock"))
    if cap is not None and cap > 0:
        add("corp.capital_amount", "amount", numeric=cap, unit="yen", text=str(cap))

    emp = _to_int(rec.get("employee_number"))
    if emp is not None and emp >= 0:
        add("corp.employee_count", "number", numeric=emp, unit="persons", text=str(emp))
    emp_m = _to_int(rec.get("company_size_male"))
    if emp_m is not None and emp_m >= 0:
        add("corp.employee_count_male", "number", numeric=emp_m, unit="persons", text=str(emp_m))
    emp_f = _to_int(rec.get("company_size_female"))
    if emp_f is not None and emp_f >= 0:
        add("corp.employee_count_female", "number", numeric=emp_f, unit="persons", text=str(emp_f))

    fy = _to_int(rec.get("founding_year"))
    if fy and 1800 <= fy <= 2100:
        add("corp.founded_year", "number", numeric=fy, text=str(fy))

    doe = _to_iso_date(rec.get("date_of_establishment"))
    if doe:
        add("corp.date_of_establishment", "date", text=doe)
    cd = _to_iso_date(rec.get("close_date"))
    if cd:
        add("corp.close_date", "date", text=cd)
    add("corp.close_cause", "text", text=_trim(rec.get("close_cause")))

    status = _trim(rec.get("status"))
    if status:
        add("corp.status", "enum", text=status)

    url = _trim(rec.get("company_url"))
    if url:
        add("corp.company_url", "url", text=url)

    upd = _to_iso_date(rec.get("update_date"))
    if upd:
        add("corp.gbiz_update_date", "date", text=upd)

    add("corp.gbiz_fetched_at", "date", text=_today_iso_date())

    return out


def cross_write_am_entity(
    conn: sqlite3.Connection,
    houjin_bangou: str,
    corp_envelope: dict[str, Any],
    *,
    dry_run: bool,
) -> tuple[int, int]:
    """Mirror corp record into am_entities + am_entity_facts (INSERT OR IGNORE).

    Returns (new_entity_count, new_fact_count). Numbers are over-counts
    when ON CONFLICT IGNORE silently rejects — caller treats them as
    upper-bounds for logging only.
    """
    rec = _hojin_info_block(corp_envelope)
    if not rec:
        return (0, 0)

    canonical_id = f"houjin:{houjin_bangou}"
    primary_name = _trim(rec.get("name")) or canonical_id
    source_url = NTA_PERMALINK_FMT.format(houjin_bangou)
    raw_json = json.dumps(rec, ensure_ascii=False)
    fetched_at = _today_iso_date()
    now = _now_iso()

    if dry_run:
        # Estimate fact count without writing.
        return (1, len(_build_facts(rec)))

    conn.execute(
        """
        INSERT INTO am_entities (
            canonical_id, record_kind, source_topic, source_record_index,
            primary_name, authority_canonical, confidence,
            source_url, source_url_domain, fetched_at, raw_json,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(canonical_id) DO UPDATE SET
            record_kind = excluded.record_kind,
            source_topic = excluded.source_topic,
            source_record_index = excluded.source_record_index,
            primary_name = excluded.primary_name,
            authority_canonical = excluded.authority_canonical,
            confidence = excluded.confidence,
            source_url = excluded.source_url,
            source_url_domain = excluded.source_url_domain,
            fetched_at = excluded.fetched_at,
            raw_json = excluded.raw_json,
            updated_at = excluded.updated_at
        """,
        (
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
        ),
    )

    facts = _build_facts(rec)
    if not facts:
        return (1, 0)

    conn.execute(
        """
        DELETE FROM am_entity_facts
         WHERE entity_id = ?
           AND (field_name = 'houjin_bangou' OR field_name LIKE 'corp.%')
        """,
        (canonical_id,),
    )

    fact_rows = [
        (canonical_id, name, text, jval, num, kind, unit, SOURCE_KEY)
        for (name, kind, text, num, jval, unit) in facts
    ]
    conn.executemany(
        """
        INSERT INTO am_entity_facts (
            entity_id, field_name, field_value_text,
            field_value_json, field_value_numeric,
            field_kind, unit, source_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        fact_rows,
    )
    return (1, len(fact_rows))


# ---------------------------------------------------------------------------
# Mode dispatchers
# ---------------------------------------------------------------------------


def run_mode_a(
    conn: sqlite3.Connection,
    houjin_bangou: str,
    *,
    dry_run: bool,
    force_refresh: bool = False,
    canonical_enabled: bool = False,
) -> dict[str, int]:
    """単一 法人番号 を 3 endpoint まわして mirror に書く。"""
    _LOG.info("mode_a_start houjin=%s", houjin_bangou)
    summary = {
        "processed": 0,
        "corp_activity": 0,
        "branches": 0,
        "workplaces": 0,
        "new_entities": 0,
        "new_facts": 0,
    }

    savepoint = f"gbiz_houjin_{houjin_bangou}"
    if not dry_run:
        conn.execute(f"SAVEPOINT {savepoint}")
    try:
        corp = fetch_corporation(houjin_bangou, force_refresh=force_refresh)
        cache_age = (
            float(corp.get("_cache_meta", {}).get("cache_age_hours", 0.0))
            if isinstance(corp.get("_cache_meta"), dict)
            else 0.0
        )

        summary["corp_activity"] = upsert_corp_activity(
            conn,
            houjin_bangou,
            corp,
            cache_age_hours=cache_age,
            dry_run=dry_run,
        )

        branches = fetch_corporation_branches(houjin_bangou, force_refresh=force_refresh)
        summary["branches"] = upsert_branches(conn, houjin_bangou, branches, dry_run=dry_run)

        workplaces = fetch_workplaces(houjin_bangou, force_refresh=force_refresh)
        summary["workplaces"] = upsert_workplaces(
            conn,
            houjin_bangou,
            workplaces,
            dry_run=dry_run,
        )

        if canonical_enabled:
            ne, nf = cross_write_am_entity(conn, houjin_bangou, corp, dry_run=dry_run)
            summary["new_entities"] = ne
            summary["new_facts"] = nf
        summary["processed"] = 1
    except Exception:
        if not dry_run:
            conn.execute(f"ROLLBACK TO {savepoint}")
            conn.execute(f"RELEASE {savepoint}")
        raise
    else:
        if not dry_run:
            conn.execute(f"RELEASE {savepoint}")

    _LOG.info("mode_a_done houjin=%s summary=%s", houjin_bangou, summary)
    return summary


def run_mode_b(
    conn: sqlite3.Connection,
    date_from: str,
    date_to: str,
    *,
    dry_run: bool,
    canonical_enabled: bool = False,
) -> dict[str, int]:
    """delta sync — updateInfo/corporation を引き、変更法人を再取得して書き戻す。"""
    _LOG.info("mode_b_start from=%s to=%s", date_from, date_to)
    summary = {
        "processed": 0,
        "corp_activity": 0,
        "branches": 0,
        "workplaces": 0,
        "new_entities": 0,
        "new_facts": 0,
        "delta_listed": 0,
    }

    houjin_numbers: list[str] = []
    page = 1
    total_pages = 1
    while page <= total_pages:
        update_envelope = fetch_updates(date_from, date_to, page=page)
        for number in _extract_houjin_numbers(update_envelope):
            if number not in houjin_numbers:
                houjin_numbers.append(number)
        total_pages = max(total_pages, _page_count(update_envelope))
        page += 1
        if page > 1000:
            raise RuntimeError("gbiz_delta_pagination_guard: page_over_1000")
    summary["delta_listed"] = len(houjin_numbers)

    if not dry_run:
        conn.execute("BEGIN IMMEDIATE")

    failed_houjin: list[str] = []
    for cn in houjin_numbers:
        try:
            sub = run_mode_a(
                conn,
                cn,
                dry_run=dry_run,
                force_refresh=True,
                canonical_enabled=canonical_enabled,
            )
        except Exception as exc:  # noqa: BLE001 — per-houjin error tolerated, log + continue
            _LOG.warning("delta_houjin_failed houjin=%s err=%s", cn, exc)
            failed_houjin.append(cn)
            continue
        for key in ("corp_activity", "branches", "workplaces", "new_entities", "new_facts"):
            summary[key] += sub.get(key, 0)
        summary["processed"] += sub.get("processed", 0)

    if failed_houjin:
        if not dry_run:
            conn.rollback()
        raise RuntimeError(
            "gbiz_delta_partial_failure: "
            f"failed={len(failed_houjin)} listed={len(houjin_numbers)} "
            f"processed={summary['processed']}"
        )

    insert_update_log(
        conn,
        endpoint="corporation",
        date_from=date_from,
        date_to=date_to,
        record_count=summary["processed"],
        next_token=None,
        dry_run=dry_run,
    )

    if not dry_run:
        conn.commit()

    _LOG.info("mode_b_done summary=%s", summary)
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="gBizINFO REST v2 corporate_activity ingest (DEEP_01 §1.2 #1)",
    )
    p.add_argument(
        "--houjin-bangou",
        type=str,
        default=None,
        help="Mode A: 単一 13桁 法人番号 を fetch して mirror に書く",
    )
    p.add_argument(
        "--from",
        dest="date_from",
        type=str,
        default=None,
        help="Mode B: updateInfo/corporation の from 日付 (YYYY-MM-DD)",
    )
    p.add_argument(
        "--to",
        dest="date_to",
        type=str,
        default=None,
        help="Mode B: updateInfo/corporation の to 日付 (YYYY-MM-DD)",
    )
    p.add_argument(
        "--db-path",
        "--db",
        dest="db_path",
        type=Path,
        default=_DEFAULT_DB,
        help="autonomath.db path (default: $AUTONOMATH_DB_PATH or repo-root)",
    )
    p.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="optional JSONL/plain log file path used by scheduled runners",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="DB 書込みを行わない。fetched payload count のみ log",
    )
    p.add_argument(
        "--force-refresh",
        action="store_true",
        help="Mode A でも gBizINFO 24h cache をバイパスして再取得する",
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

    # Mode validation — exclusive choice.
    if args.houjin_bangou and (args.date_from or args.date_to):
        _LOG.error("mode_conflict — --houjin-bangou と --from/--to は排他")
        return 1
    if not args.houjin_bangou and not (args.date_from and args.date_to):
        _LOG.error("mode_missing — --houjin-bangou か --from/--to のどちらかを指定")
        return 1

    # ingest_enabled gate (rollback knob — DEEP_01 §7.2)
    if os.environ.get("GBIZINFO_INGEST_ENABLED", "true").lower() == "false":
        _LOG.info("gbiz_ingest_disabled — clean shutdown via env flag")
        return 0

    canonical_enabled = _canonical_cross_write_enabled()
    db_path = Path(args.db_path)
    preflight_exit = _preflight_db(db_path, canonical_enabled=canonical_enabled)
    if preflight_exit != 0:
        return preflight_exit

    # Open DB after schema preflight so live fetch never spends API quota first.
    try:
        conn = _open_db(db_path)
    except (sqlite3.Error, SystemExit) as exc:
        _LOG.error("db_open_failed path=%s err=%s", db_path, exc)
        return 2

    succeeded = False
    try:
        if args.houjin_bangou:
            summary = run_mode_a(
                conn,
                args.houjin_bangou,
                dry_run=args.dry_run,
                force_refresh=args.force_refresh,
                canonical_enabled=canonical_enabled,
            )
        else:
            summary = run_mode_b(
                conn,
                args.date_from,
                args.date_to,
                dry_run=args.dry_run,
                canonical_enabled=canonical_enabled,
            )
        succeeded = True
    except RuntimeError as exc:
        # gbiz_rate_limit_exceeded / token missing
        _LOG.error("api_error err=%s", exc)
        conn.close()
        return 1
    except Exception as exc:  # noqa: BLE001
        # Network / parse / httpx errors land here.
        _LOG.error("ingest_failed err=%s", exc)
        conn.close()
        return 1
    finally:
        try:
            if succeeded and not args.dry_run:
                conn.commit()
        except sqlite3.Error:
            pass

    conn.close()
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
