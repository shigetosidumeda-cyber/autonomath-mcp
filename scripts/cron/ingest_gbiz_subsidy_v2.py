#!/usr/bin/env python3
"""gBizINFO subsidy v2 cron driver — /v2/hojin/{n}/subsidy + /v2/hojin/updateInfo/subsidy.

Per DEEP-01 spec §1.2.2; uses the single Bookyou-issued API token at
1 rps + 24h cache TTL per the 6-condition operator agreement
(see ``docs/legal/gbizinfo_terms_compliance.md``).

Modes:
  --houjin-bangou X   per-houjin lookup       (/v2/hojin/{n}/subsidy)
  --from / --to       delta sync              (/v2/hojin/updateInfo/subsidy?from=&to=)

Mirror table: gbiz_subsidy_award (created by sibling migration
wave24_164_gbiz_v2_mirror_tables.sql).

Cross-write target: ``jpi_adoption_records`` is the canonical side
(p-portal / jGrants / 各府省 are the upstream sources); gBizINFO is the
mirror. Dedupe on (houjin_bangou, program_name, fiscal_year). Mirror
writes use UPSERT so changed upstream rows refresh the cached copy.

NO LLM API import. NO Anthropic / OpenAI / Gemini import. The cron is
pure-stdlib + httpx + the gBizINFO rate-limited client.

Exit codes:
    0  success (ran or dry-run printed counts)
    1  fetch / IO failure
    2  schema missing (run migration first)
    3  GBIZINFO_API_TOKEN missing (set in .env.local or fly secrets)
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

# Allow running as bare script: ``python scripts/cron/ingest_gbiz_subsidy_v2.py``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.ingest._gbiz_attribution import build_attribution  # noqa: E402
from jpintel_mcp.ingest._gbiz_rate_limiter import (  # noqa: E402
    GbizRateLimitedClient,
)

LOG = logging.getLogger("ingest_gbiz_subsidy_v2")
DB_PATH_DEFAULT = os.environ.get(
    "AUTONOMATH_DB_PATH",
    str(_REPO_ROOT / "autonomath.db"),
)

# Endpoint family identity — used in source_url and gbiz_update_log.
_ENDPOINT_FAMILY = "subsidy"
_API_BASE_URL = "https://info.gbiz.go.jp/hojin"
_IMAGE_FIELD_BLOCKLIST = {
    "law_mark_image",
    "law_mark_logo",
    "individual_law_mark",
    "image_base64",
}
_RECORD_SOURCE_URL_KEY = "_gbiz_fetch_source_url"


class SchemaError(RuntimeError):
    """Raised when the DB is missing tables/columns required for safe writes."""


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------
def fetch_per_houjin(
    client: GbizRateLimitedClient,
    houjin_bangou: str,
    *,
    force_refresh: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    """GET /v2/hojin/{n}/subsidy → (records, source_url)."""
    path = f"v2/hojin/{houjin_bangou}/subsidy"
    body = client.get(path, force_refresh=force_refresh)
    records = _extract_records(body, houjin_default=houjin_bangou)
    source_url = f"{_API_BASE_URL}/{path}"
    for record in records:
        record.setdefault(_RECORD_SOURCE_URL_KEY, source_url)
    LOG.info(
        "gbiz subsidy per-houjin houjin_bangou=%s records=%d",
        houjin_bangou,
        len(records),
    )
    return records, source_url


def fetch_delta(
    client: GbizRateLimitedClient, date_from: str, date_to: str
) -> tuple[list[dict[str, Any]], str]:
    """GET updateInfo/subsidy, then re-fetch each listed houjin endpoint."""
    path = "v2/hojin/updateInfo/subsidy"
    source_url = f"{_API_BASE_URL}/{path}?from={date_from}&to={date_to}"
    houjin_numbers: list[str] = []
    page = 1
    total_pages = 1
    while page <= total_pages:
        body = client.get(
            path,
            params={
                "from": _gbiz_date_param(date_from),
                "to": _gbiz_date_param(date_to),
                "page": str(page),
            },
            force_refresh=True,
        )
        for houjin_bangou in _extract_houjin_numbers(body):
            if houjin_bangou not in houjin_numbers:
                houjin_numbers.append(houjin_bangou)
        total_pages = max(total_pages, _page_count(body))
        page += 1
        if page > 1000:
            raise RuntimeError("gbiz_delta_pagination_guard: page_over_1000")

    records: list[dict[str, Any]] = []
    for houjin_bangou in houjin_numbers:
        sub_records, _ = fetch_per_houjin(
            client,
            houjin_bangou,
            force_refresh=True,
        )
        records.extend(sub_records)
    LOG.info(
        "gbiz subsidy delta from=%s to=%s notifications=%d records=%d",
        date_from,
        date_to,
        len(houjin_numbers),
        len(records),
    )
    return records, source_url


def _extract_houjin_numbers(body: dict[str, Any]) -> list[str]:
    """Extract corporate numbers from an updateInfo response envelope."""
    seen: set[str] = set()
    out: list[str] = []

    def add(value: Any) -> None:
        text = _norm_str(value)
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
        total = _norm_int(body.get(key))
        if total is not None and total > 0:
            return total
    return 1


def _gbiz_date_param(value: str) -> str:
    return value.replace("-", "") if re.match(r"^\d{4}-\d{2}-\d{2}$", value) else value


def _extract_records(body: dict[str, Any], *, houjin_default: str | None) -> list[dict[str, Any]]:
    """Normalize various gBizINFO envelope shapes into a list of records.

    The v2 envelope wraps records under ``hojin-infos[].subsidy`` (per-
    houjin mode) or under ``subsidy`` / ``hojinInfos[].subsidy`` (delta
    mode). We accept both shapes defensively so a future ToS revision
    that flattens the envelope does not silently drop rows.
    """
    out: list[dict[str, Any]] = []
    if not isinstance(body, dict):
        return out

    # Per-houjin envelope: {"hojin-infos": [{"corporate_number": "...",
    #     "subsidy": [...]}]}
    for envelope_key in ("hojin-infos", "hojinInfos"):
        infos = body.get(envelope_key)
        if isinstance(infos, list):
            for info in infos:
                if not isinstance(info, dict):
                    continue
                houjin_bangou = (
                    info.get("corporate_number") or info.get("corporateNumber") or houjin_default
                )
                rows = info.get("subsidy") or info.get("subsidies")
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, dict):
                            row.setdefault("houjin_bangou", houjin_bangou)
                            out.append(row)

    # Flat envelope: {"subsidy": [...]} (delta endpoint occasionally returns this)
    flat = body.get("subsidy") or body.get("subsidies")
    if isinstance(flat, list):
        for row in flat:
            if isinstance(row, dict):
                if houjin_default and "houjin_bangou" not in row:
                    row["houjin_bangou"] = (
                        row.get("corporate_number") or row.get("corporateNumber") or houjin_default
                    )
                out.append(row)
    return out


# ---------------------------------------------------------------------------
# DB writers
# ---------------------------------------------------------------------------
def upsert_records(
    conn: sqlite3.Connection,
    records: list[dict[str, Any]],
    source_url: str,
    fetched_at: str,
) -> dict[str, int]:
    """UPSERT into gbiz_subsidy_award + optional jpi_adoption_records cross-link.

    Returns a counts dict for stdout summary.
    """
    counts = {
        "fetched": len(records),
        "mirror_inserted": 0,
        "mirror_updated": 0,
        "canonical_inserted": 0,
        "canonical_updated": 0,
        "canonical_skipped": 0,
        "skipped_no_houjin": 0,
        "skipped_no_resource_id": 0,
    }
    for record in records:
        record = _scrub_image_fields(record)
        record_source_url = (
            _norm_str(record.pop(_RECORD_SOURCE_URL_KEY, None))
            or _norm_str(record.get("source_url"))
            or source_url
        )
        houjin_bangou = _norm_str(
            record.get("houjin_bangou")
            or record.get("corporate_number")
            or record.get("corporateNumber")
        )
        if not houjin_bangou:
            counts["skipped_no_houjin"] += 1
            continue

        # Field harvesting — gBizINFO field names per W1_A04 + spec.
        program_id = _norm_str(
            record.get("program_id") or record.get("programId") or record.get("subsidy_resource_id")
        )
        award_id = _norm_str(
            record.get("award_id")
            or record.get("awardId")
            or record.get("subsidy_resource_id")
            or record.get("resource_id")
        )
        if not award_id:
            counts["skipped_no_resource_id"] += 1
            continue

        program_name = _norm_str(
            record.get("title") or record.get("program_name") or record.get("subsidy_name")
        )
        amount_yen = _norm_int(
            record.get("amount") or record.get("amount_yen") or record.get("subsidy_amount")
        )
        award_date = _norm_str(
            record.get("date_of_approval")
            or record.get("award_date")
            or record.get("approval_date")
        )
        fiscal_year = _norm_int(
            record.get("fiscal_year") or record.get("fiscalYear") or _fy_from_date(award_date)
        )
        agency_name = _norm_str(
            record.get("government_departments")
            or record.get("agency")
            or record.get("agency_name")
        )
        upstream_source = (
            _norm_str(record.get("upstream_source"))
            or agency_name
            or "gbizinfo:upstream_unspecified"
        )

        attribution = build_attribution(
            source_url=record_source_url,
            fetched_at=fetched_at,
            upstream_source=upstream_source,
        )
        attribution_payload = attribution["_attribution"]
        attribution_json = json.dumps(
            attribution_payload,
            ensure_ascii=False,
            sort_keys=True,
        )
        raw_blob = json.dumps(
            {**record, "_attribution": attribution_payload},
            ensure_ascii=False,
            sort_keys=True,
        )

        mirror_exists = (
            conn.execute(
                """
                SELECT 1
                  FROM gbiz_subsidy_award
                 WHERE houjin_bangou = ? AND subsidy_resource_id = ?
                 LIMIT 1
                """,
                (houjin_bangou, award_id),
            ).fetchone()
            is not None
        )
        cursor = conn.execute(
            """
            INSERT INTO gbiz_subsidy_award (
                subsidy_resource_id, houjin_bangou, title, amount_yen,
                date_of_approval, government_departments, target, note,
                upstream_source, fetched_at, raw_json, program_id, fiscal_year,
                award_id, program_name, award_date, agency_name, source_url,
                attribution_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(houjin_bangou, subsidy_resource_id) DO UPDATE SET
                title = excluded.title,
                amount_yen = excluded.amount_yen,
                date_of_approval = excluded.date_of_approval,
                government_departments = excluded.government_departments,
                target = excluded.target,
                note = excluded.note,
                upstream_source = excluded.upstream_source,
                fetched_at = excluded.fetched_at,
                raw_json = excluded.raw_json,
                program_id = excluded.program_id,
                fiscal_year = excluded.fiscal_year,
                award_id = excluded.award_id,
                program_name = excluded.program_name,
                award_date = excluded.award_date,
                agency_name = excluded.agency_name,
                source_url = excluded.source_url,
                attribution_json = excluded.attribution_json
            """,
            (
                award_id,
                houjin_bangou,
                program_name,
                amount_yen,
                award_date,
                agency_name,
                _norm_str(record.get("target")),
                _norm_str(record.get("note")),
                upstream_source,
                fetched_at,
                raw_blob,
                program_id,
                fiscal_year,
                award_id,
                program_name,
                award_date,
                agency_name,
                record_source_url,
                attribution_json,
            ),
        )
        if cursor.rowcount > 0:
            if mirror_exists:
                counts["mirror_updated"] += 1
            else:
                counts["mirror_inserted"] += 1

        # Canonical cross-write — disabled by default until lineage policy is reviewed.
        # Dedupe key: (houjin_bangou, program_id_hint, round_label, announced_at).
        if not _canonical_cross_write_enabled():
            counts["canonical_skipped"] += 1
            continue
        program_id_hint = program_id or award_id
        round_label = str(fiscal_year) if fiscal_year is not None else None
        adoption_cursor = conn.execute(
            """
            UPDATE jpi_adoption_records
               SET program_name_raw = ?,
                   project_title = ?,
                   amount_granted_yen = ?,
                   source_url = ?,
                   fetched_at = ?,
                   confidence = ?
             WHERE houjin_bangou IS ?
               AND program_id_hint IS ?
               AND round_label IS ?
               AND announced_at IS ?
            """,
            (
                program_name,
                _norm_str(record.get("target")),
                amount_yen,
                record_source_url,
                fetched_at,
                0.9,
                houjin_bangou,
                program_id_hint,
                round_label,
                award_date,
            ),
        )
        if adoption_cursor.rowcount > 0:
            counts["canonical_updated"] += adoption_cursor.rowcount
            continue
        adoption_cursor = conn.execute(
            """
            INSERT INTO jpi_adoption_records (
                houjin_bangou, program_id_hint, program_name_raw, company_name_raw,
                round_label, round_number, announced_at, prefecture, municipality,
                project_title, industry_raw, industry_jsic_medium,
                amount_granted_yen, amount_project_total_yen,
                source_url, source_pdf_page, fetched_at, confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                houjin_bangou,
                program_id_hint,
                program_name,
                None,
                round_label,
                fiscal_year,
                award_date,
                None,
                None,
                _norm_str(record.get("target")),
                None,
                None,
                amount_yen,
                None,
                record_source_url,
                None,
                fetched_at,
                0.9,  # gBiz subsidy mirror confidence
            ),
        )
        if adoption_cursor.rowcount > 0:
            counts["canonical_inserted"] += 1

    return counts


def append_update_log(
    conn: sqlite3.Connection,
    *,
    endpoint: str,
    from_date: str,
    to_date: str,
    record_count: int,
    fetched_at: str,
) -> None:
    """Best-effort append into gbiz_update_log; ignored if table absent."""
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO gbiz_update_log (
                endpoint, from_date, to_date, record_count, fetched_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (endpoint, from_date, to_date, record_count, fetched_at),
        )
    except sqlite3.OperationalError as exc:
        LOG.debug("gbiz_update_log not available (%s) — skipping log append", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _norm_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        # gBiz returns government_departments as JSON array — flatten for the
        # canonical column, keep raw in raw_json.
        return ", ".join(str(v).strip() for v in value if v is not None) or None
    text = str(value).strip()
    return text or None


def _canonical_cross_write_enabled() -> bool:
    return os.environ.get("GBIZINFO_CANONICAL_CROSS_WRITE_ENABLED", "false").lower() == "true"


def _scrub_image_fields(rec: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(rec, dict):
        return rec
    cleaned: dict[str, Any] = {}
    for key, value in rec.items():
        if key in _IMAGE_FIELD_BLOCKLIST:
            continue
        if isinstance(value, dict):
            cleaned[key] = _scrub_image_fields(value)
        elif isinstance(value, list):
            cleaned[key] = [
                _scrub_image_fields(item) if isinstance(item, dict) else item for item in value
            ]
        else:
            cleaned[key] = value
    return cleaned


def _norm_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "").replace("円", "")
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _fy_from_date(date_iso: str | None) -> int | None:
    """Pull JP fiscal year (April-March) from an ISO date string."""
    if not date_iso:
        return None
    try:
        dt = datetime.fromisoformat(date_iso[:10])
    except ValueError:
        return None
    return dt.year if dt.month >= 4 else dt.year - 1


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _has_unique_index(conn: sqlite3.Connection, table: str, columns: tuple[str, ...]) -> bool:
    for index_row in conn.execute(f"PRAGMA index_list({table})"):
        if not index_row[2]:
            continue
        index_name = index_row[1]
        index_columns = tuple(
            row[2] for row in conn.execute(f"PRAGMA index_info({index_name})") if row[2]
        )
        if index_columns == columns:
            return True
    return False


def _ensure_table(conn: sqlite3.Connection, table: str) -> None:
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    if cursor.fetchone() is None:
        raise SchemaError(f"{table} table missing")


def _ensure_schema(conn: sqlite3.Connection, *, canonical_enabled: bool) -> None:
    _ensure_table(conn, "gbiz_subsidy_award")
    mirror_required = {
        "subsidy_resource_id",
        "houjin_bangou",
        "title",
        "amount_yen",
        "date_of_approval",
        "government_departments",
        "target",
        "note",
        "upstream_source",
        "fetched_at",
        "raw_json",
        "program_id",
        "fiscal_year",
        "award_id",
        "program_name",
        "award_date",
        "agency_name",
        "source_url",
        "attribution_json",
    }
    mirror_missing = sorted(mirror_required - _table_columns(conn, "gbiz_subsidy_award"))
    if mirror_missing:
        raise SchemaError("gbiz_subsidy_award missing columns: " + ", ".join(mirror_missing))
    if not _has_unique_index(
        conn,
        "gbiz_subsidy_award",
        ("houjin_bangou", "subsidy_resource_id"),
    ):
        raise SchemaError(
            "gbiz_subsidy_award missing UNIQUE index on (houjin_bangou, subsidy_resource_id)"
        )

    if not canonical_enabled:
        return

    _ensure_table(conn, "jpi_adoption_records")
    canonical_required = {
        "houjin_bangou",
        "program_id_hint",
        "program_name_raw",
        "company_name_raw",
        "round_label",
        "round_number",
        "announced_at",
        "prefecture",
        "municipality",
        "project_title",
        "industry_raw",
        "industry_jsic_medium",
        "amount_granted_yen",
        "amount_project_total_yen",
        "source_url",
        "source_pdf_page",
        "fetched_at",
        "confidence",
    }
    canonical_missing = sorted(canonical_required - _table_columns(conn, "jpi_adoption_records"))
    if canonical_missing:
        raise SchemaError("jpi_adoption_records missing columns: " + ", ".join(canonical_missing))


def _preflight_db(db_path: Path, *, canonical_enabled: bool) -> int:
    if not db_path.parent.is_dir():
        LOG.error("DB parent dir missing: %s", db_path.parent)
        return 1
    if not db_path.is_file():
        LOG.error("DB file missing: %s", db_path)
        return 2
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        _ensure_schema(conn, canonical_enabled=canonical_enabled)
    except SchemaError as exc:
        LOG.error(
            "%s — run migration wave24_164_gbiz_v2_mirror_tables.sql first "
            "(or wait for entrypoint.sh autonomath self-heal loop).",
            exc,
        )
        return 2
    except sqlite3.Error as exc:
        LOG.error("DB schema check failed: %s", exc)
        return 1
    finally:
        conn.close()
    return 0


def _write_records_atomically(
    db_path: Path,
    *,
    canonical_enabled: bool,
    records: list[dict[str, Any]],
    source_url: str,
    fetched_at: str,
    endpoint_label: str,
    from_date: str,
    to_date: str,
) -> dict[str, int]:
    if not db_path.is_file():
        raise SchemaError(f"DB file missing: {db_path}")
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        _ensure_schema(conn, canonical_enabled=canonical_enabled)
        conn.execute("BEGIN IMMEDIATE")
        try:
            counts = upsert_records(conn, records, source_url, fetched_at)
            append_update_log(
                conn,
                endpoint=endpoint_label,
                from_date=from_date,
                to_date=to_date,
                record_count=counts["fetched"],
                fetched_at=fetched_at,
            )
        except Exception:
            conn.rollback()
            raise
        conn.commit()
        return counts
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--houjin-bangou",
        help="13-digit corporate number (per-houjin lookup mode)",
    )
    parser.add_argument("--from", dest="date_from", help="Delta sync from-date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="date_to", help="Delta sync to-date (YYYY-MM-DD)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip DB writes; still fetch + print summary",
    )
    parser.add_argument(
        "--db-path",
        "--db",
        dest="db_path",
        default=DB_PATH_DEFAULT,
        help=f"autonomath.db path (default: {DB_PATH_DEFAULT})",
    )
    parser.add_argument("--log-file", type=Path, default=None)
    parser.add_argument("--verbose", action="store_true", help="DEBUG-level logging")
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Bypass the gBizINFO 24h cache in per-houjin mode",
    )
    args = parser.parse_args()

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if args.log_file is not None:
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )

    if not args.houjin_bangou and not (args.date_from and args.date_to):
        parser.error("Specify either --houjin-bangou OR both --from and --to")

    if os.environ.get("GBIZINFO_INGEST_ENABLED", "true").lower() == "false":
        LOG.warning("GBIZINFO_INGEST_ENABLED=false — clean shutdown, no work")
        return 0

    db_path = Path(args.db_path)
    canonical_enabled = _canonical_cross_write_enabled()
    if not args.dry_run:
        preflight_exit = _preflight_db(db_path, canonical_enabled=canonical_enabled)
        if preflight_exit != 0:
            return preflight_exit

    try:
        client = GbizRateLimitedClient()
    except RuntimeError as exc:
        LOG.error("token check failed: %s", exc)
        return 3

    fetched_at = datetime.now(tz=UTC).isoformat()

    if args.houjin_bangou:
        records, source_url = fetch_per_houjin(
            client,
            args.houjin_bangou,
            force_refresh=args.force_refresh,
        )
        endpoint_label = f"{_ENDPOINT_FAMILY}_per_houjin"
        from_date = args.houjin_bangou
        to_date = args.houjin_bangou
    else:
        records, source_url = fetch_delta(client, args.date_from, args.date_to)
        endpoint_label = f"{_ENDPOINT_FAMILY}_delta"
        from_date = args.date_from
        to_date = args.date_to

    if args.dry_run:
        attribution = build_attribution(
            source_url=source_url,
            fetched_at=fetched_at,
            upstream_source=endpoint_label,
        )
        summary = {
            "mode": "dry_run",
            "endpoint": endpoint_label,
            "fetched": len(records),
            "_attribution": attribution["_attribution"],
        }
        print(json.dumps(summary, ensure_ascii=False))
        LOG.info(
            "dry-run complete fetched=%d source_url=%s",
            len(records),
            source_url,
        )
        return 0

    try:
        counts = _write_records_atomically(
            db_path,
            canonical_enabled=canonical_enabled,
            records=records,
            source_url=source_url,
            fetched_at=fetched_at,
            endpoint_label=endpoint_label,
            from_date=from_date,
            to_date=to_date,
        )
    except SchemaError as exc:
        LOG.error("%s", exc)
        return 2
    except sqlite3.Error as exc:
        LOG.error("DB write failed: %s", exc)
        return 1

    summary = {
        "mode": "live",
        "endpoint": endpoint_label,
        **counts,
        "source_url": source_url,
        "fetched_at": fetched_at,
    }
    print(json.dumps(summary, ensure_ascii=False))
    LOG.info("done %s", json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
