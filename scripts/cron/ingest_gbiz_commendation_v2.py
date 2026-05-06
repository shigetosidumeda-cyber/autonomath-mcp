#!/usr/bin/env python3
"""gBizINFO commendation v2 cron driver — /v2/hojin/{n}/commendation + /v2/hojin/updateInfo/commendation.

Per DEEP-01 spec §1.2.4; uses the single Bookyou-issued API token at
1 rps + 24h cache TTL per the 6-condition operator agreement
(see ``docs/legal/gbizinfo_terms_compliance.md``).

Modes:
  --houjin-bangou X   per-houjin lookup       (/v2/hojin/{n}/commendation)
  --from / --to       delta sync              (/v2/hojin/updateInfo/commendation?from=&to=)

Mirror table: gbiz_commendation (created by sibling migration
wave24_164_gbiz_v2_mirror_tables.sql).

Cross-write target: ``am_entity_facts`` under the ``award.*`` field_name
namespace, keyed on the corporate_entity ``houjin:<bangou>`` canonical_id.
Mirror/fact writes update existing rows and canonicalize nullable identity
parts before insert so SQLite UNIQUE indexes can suppress duplicates.

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

# Allow running as bare script.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.ingest._gbiz_attribution import build_attribution  # noqa: E402
from jpintel_mcp.ingest._gbiz_rate_limiter import (  # noqa: E402
    GbizRateLimitedClient,
)

LOG = logging.getLogger("ingest_gbiz_commendation_v2")
DB_PATH_DEFAULT = os.environ.get(
    "AUTONOMATH_DB_PATH",
    str(_REPO_ROOT / "autonomath.db"),
)

_ENDPOINT_FAMILY = "commendation"
_API_BASE_URL = "https://info.gbiz.go.jp/hojin"
_FACT_NAMESPACE = "award"
_NULL_IDENTITY_PART = ""
_IMAGE_FIELD_BLOCKLIST = {
    "law_mark_image",
    "law_mark_logo",
    "individual_law_mark",
    "image_base64",
}


class SchemaError(RuntimeError):
    """Required gBiz mirror schema is not available."""


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------
def fetch_per_houjin(
    client: GbizRateLimitedClient,
    houjin_bangou: str,
    *,
    force_refresh: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    """GET /v2/hojin/{n}/commendation → (records, source_url)."""
    path = f"v2/hojin/{houjin_bangou}/commendation"
    body = client.get(path, force_refresh=force_refresh)
    records = _extract_records(body, houjin_default=houjin_bangou)
    source_url = f"{_API_BASE_URL}/{path}"
    LOG.info(
        "gbiz commendation per-houjin houjin_bangou=%s records=%d",
        houjin_bangou,
        len(records),
    )
    return records, source_url


def fetch_delta(
    client: GbizRateLimitedClient, date_from: str, date_to: str
) -> tuple[list[dict[str, Any]], str]:
    """GET updateInfo/commendation, then re-fetch each listed houjin endpoint."""
    path = "v2/hojin/updateInfo/commendation"
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
        sub_records, sub_source_url = fetch_per_houjin(
            client,
            houjin_bangou,
            force_refresh=True,
        )
        for record in sub_records:
            record.setdefault("_gbiz_source_url", sub_source_url)
        records.extend(sub_records)
    LOG.info(
        "gbiz commendation delta from=%s to=%s notifications=%d records=%d",
        date_from,
        date_to,
        len(houjin_numbers),
        len(records),
    )
    return records, source_url


def _extract_houjin_numbers(body: dict[str, Any]) -> list[str]:
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
        total = _to_int(body.get(key))
        if total is not None and total > 0:
            return total
    return 1


def _gbiz_date_param(value: str) -> str:
    return value.replace("-", "") if re.match(r"^\d{4}-\d{2}-\d{2}$", value) else value


def _to_int(value: Any) -> int | None:
    if value is None or value == "" or value == "-":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_records(body: dict[str, Any], *, houjin_default: str | None) -> list[dict[str, Any]]:
    """Normalize gBizINFO commendation envelope into a list of records."""
    out: list[dict[str, Any]] = []
    if not isinstance(body, dict):
        return out

    for envelope_key in ("hojin-infos", "hojinInfos"):
        infos = body.get(envelope_key)
        if isinstance(infos, list):
            for info in infos:
                if not isinstance(info, dict):
                    continue
                houjin_bangou = (
                    info.get("corporate_number") or info.get("corporateNumber") or houjin_default
                )
                rows = info.get("commendation") or info.get("commendations")
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, dict):
                            row.setdefault("houjin_bangou", houjin_bangou)
                            out.append(row)

    flat = body.get("commendation") or body.get("commendations")
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
    """Upsert into gbiz_commendation + award.* facts."""
    counts = {
        "fetched": len(records),
        "mirror_inserted": 0,
        "mirror_updated": 0,
        "facts_inserted": 0,
        "facts_updated": 0,
        "facts_skipped": 0,
        "skipped_duplicate_records": 0,
        "skipped_no_houjin": 0,
        "skipped_no_title": 0,
    }
    seen_record_keys: set[tuple[str, str, str, str]] = set()
    for record in records:
        record = _scrub_image_fields(record)
        houjin_bangou = _norm_str(
            record.get("houjin_bangou")
            or record.get("corporate_number")
            or record.get("corporateNumber")
        )
        if not houjin_bangou:
            counts["skipped_no_houjin"] += 1
            continue

        award_id_hint = _norm_str(record.get("award_id") or record.get("awardId"))
        award_name = _norm_str(
            record.get("title") or record.get("award_name") or record.get("commendation_name")
        )
        if not award_name:
            counts["skipped_no_title"] += 1
            continue

        category = _norm_str(record.get("category"))
        award_date = _unique_identity_part(
            record.get("date_of_commendation")
            or record.get("award_date")
            or record.get("date_of_approval")
        )
        granting_authority = _unique_identity_part(
            record.get("government_departments")
            or record.get("granting_authority")
            or record.get("agency")
        )
        record_key = (houjin_bangou, award_name, award_date, granting_authority)
        if record_key in seen_record_keys:
            counts["skipped_duplicate_records"] += 1
            continue
        seen_record_keys.add(record_key)

        upstream_source = (
            _norm_str(record.get("upstream_source"))
            or _norm_str(granting_authority)
            or "gbizinfo:upstream_unspecified"
        )
        record_source_url = _record_source_url(record, fallback=source_url)

        attribution = build_attribution(
            source_url=record_source_url,
            fetched_at=fetched_at,
            upstream_source=upstream_source,
        )
        attribution_payload = attribution["_attribution"]
        attribution_json = json.dumps(attribution_payload, ensure_ascii=False, sort_keys=True)
        raw_blob = json.dumps(
            {**record, "_attribution": attribution_payload},
            ensure_ascii=False,
            sort_keys=True,
        )

        update_cursor = conn.execute(
            """
            UPDATE gbiz_commendation
               SET category = ?,
                   date_of_commendation = ?,
                   government_departments = ?,
                   target = ?,
                   upstream_source = ?,
                   fetched_at = ?,
                   raw_json = ?,
                   award_id = ?,
                   award_name = ?,
                   award_date = ?,
                   granting_authority = ?,
                   source_url = ?,
                   attribution_json = ?
             WHERE houjin_bangou = ?
               AND title = ?
               AND COALESCE(date_of_commendation, ?) = ?
               AND COALESCE(government_departments, ?) = ?
            """,
            (
                category,
                award_date,
                granting_authority,
                _norm_str(record.get("target")),
                upstream_source,
                fetched_at,
                raw_blob,
                award_id_hint,
                award_name,
                award_date,
                granting_authority,
                record_source_url,
                attribution_json,
                houjin_bangou,
                award_name,
                _NULL_IDENTITY_PART,
                award_date,
                _NULL_IDENTITY_PART,
                granting_authority,
            ),
        )
        if update_cursor.rowcount > 0:
            counts["mirror_updated"] += update_cursor.rowcount
        else:
            cursor = conn.execute(
                """
                INSERT INTO gbiz_commendation (
                    houjin_bangou, title, category, date_of_commendation,
                    government_departments, target, upstream_source,
                    fetched_at, raw_json, award_id, award_name, award_date,
                    granting_authority, source_url, attribution_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(houjin_bangou, title, date_of_commendation, government_departments)
                DO UPDATE SET
                    category = excluded.category,
                    target = excluded.target,
                    upstream_source = excluded.upstream_source,
                    fetched_at = excluded.fetched_at,
                    raw_json = excluded.raw_json,
                    award_id = excluded.award_id,
                    award_name = excluded.award_name,
                    award_date = excluded.award_date,
                    granting_authority = excluded.granting_authority,
                    source_url = excluded.source_url,
                    attribution_json = excluded.attribution_json
                """,
                (
                    houjin_bangou,
                    award_name,
                    category,
                    award_date,
                    granting_authority,
                    _norm_str(record.get("target")),
                    upstream_source,
                    fetched_at,
                    raw_blob,
                    award_id_hint,
                    award_name,
                    award_date,
                    granting_authority,
                    record_source_url,
                    attribution_json,
                ),
            )
            if cursor.rowcount > 0:
                counts["mirror_inserted"] += 1

        # Cross-write into am_entity_facts under award.* namespace.
        if not _canonical_cross_write_enabled():
            counts["facts_skipped"] += 1
            continue
        entity_id = f"houjin:{houjin_bangou}"
        fact_rows = _build_award_facts(
            entity_id=entity_id,
            award_id_hint=_award_fact_suffix(
                award_id_hint=award_id_hint,
                award_name=award_name,
                award_date=award_date,
                granting_authority=granting_authority,
            ),
            award_name=award_name,
            category=category,
            award_date=award_date,
            granting_authority=_norm_str(granting_authority),
            source_url=record_source_url,
        )
        for field_name, field_kind, value_text in fact_rows:
            fact_status = _upsert_fact(
                conn,
                entity_id=entity_id,
                field_name=field_name,
                field_kind=field_kind,
                value_text=value_text,
                source_url=record_source_url,
                fetched_at=fetched_at,
            )
            if fact_status == "inserted":
                counts["facts_inserted"] += 1
            elif fact_status == "updated":
                counts["facts_updated"] += 1

    return counts


def _build_award_facts(
    *,
    entity_id: str,
    award_id_hint: str,
    award_name: str,
    category: str | None,
    award_date: str | None,
    granting_authority: str | None,
    source_url: str,
) -> list[tuple[str, str, str]]:
    suffix = award_id_hint
    rows: list[tuple[str, str, str]] = []
    rows.append((f"{_FACT_NAMESPACE}.{suffix}.title", "text", award_name))
    if category:
        rows.append((f"{_FACT_NAMESPACE}.{suffix}.category", "text", category))
    if award_date:
        rows.append((f"{_FACT_NAMESPACE}.{suffix}.award_date", "date", award_date))
    if granting_authority:
        rows.append((f"{_FACT_NAMESPACE}.{suffix}.granting_authority", "text", granting_authority))
    rows.append((f"{_FACT_NAMESPACE}.{suffix}.source_url", "url", source_url))
    return rows


def _upsert_fact(
    conn: sqlite3.Connection,
    *,
    entity_id: str,
    field_name: str,
    field_kind: str,
    value_text: str,
    source_url: str,
    fetched_at: str,
) -> str:
    update_cursor = conn.execute(
        """
        UPDATE am_entity_facts
           SET field_value_text = ?,
               field_kind = ?,
               source_url = ?,
               created_at = ?
         WHERE entity_id = ?
           AND field_name = ?
        """,
        (value_text, field_kind, source_url, fetched_at, entity_id, field_name),
    )
    if update_cursor.rowcount > 0:
        return "updated"

    insert_cursor = conn.execute(
        """
        INSERT OR IGNORE INTO am_entity_facts (
            entity_id, field_name, field_value_text, field_kind,
            source_url, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (entity_id, field_name, value_text, field_kind, source_url, fetched_at),
    )
    if insert_cursor.rowcount > 0:
        return "inserted"
    return "ignored"


def append_update_log(
    conn: sqlite3.Connection,
    *,
    endpoint: str,
    from_date: str,
    to_date: str,
    record_count: int,
    fetched_at: str,
) -> None:
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
        return ", ".join(str(v).strip() for v in value if v is not None) or None
    text = str(value).strip()
    return text or None


def _unique_identity_part(value: Any) -> str:
    return _norm_str(value) or _NULL_IDENTITY_PART


def _record_source_url(record: dict[str, Any], *, fallback: str) -> str:
    return _norm_str(record.get("_gbiz_source_url")) or fallback


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


def _slug(text: str | None) -> str:
    if not text:
        return "unknown"
    cleaned = "".join(c.lower() if c.isalnum() else "_" for c in text)
    cleaned = cleaned.strip("_")
    return cleaned[:32] or "unknown"


def _award_fact_suffix(
    *,
    award_id_hint: str | None,
    award_name: str,
    award_date: str,
    granting_authority: str,
) -> str:
    if award_id_hint:
        return _slug(award_id_hint)
    identity = "|".join(
        part for part in (award_name, award_date, granting_authority) if part != _NULL_IDENTITY_PART
    )
    return _slug(identity)


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    cursor = conn.execute(f"PRAGMA table_info({table_name})")
    return {str(row[1]) for row in cursor.fetchall()}


def _has_unique_index(
    conn: sqlite3.Connection,
    table_name: str,
    expected_columns: tuple[str, ...],
) -> bool:
    for index_row in conn.execute(f"PRAGMA index_list({table_name})"):
        if not int(index_row[2]):
            continue
        index_name = str(index_row[1])
        columns = tuple(str(row[2]) for row in conn.execute(f"PRAGMA index_info({index_name})"))
        if columns == expected_columns:
            return True
    return False


def _ensure_schema(conn: sqlite3.Connection) -> None:
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        ("gbiz_commendation",),
    )
    if cursor.fetchone() is None:
        raise SchemaError(
            "gbiz_commendation table missing — run migration "
            "wave24_164_gbiz_v2_mirror_tables.sql first."
        )
    required_columns = {
        "houjin_bangou",
        "title",
        "category",
        "date_of_commendation",
        "government_departments",
        "target",
        "upstream_source",
        "fetched_at",
        "raw_json",
        "award_id",
        "award_name",
        "award_date",
        "granting_authority",
        "source_url",
        "attribution_json",
    }
    missing_columns = sorted(required_columns - _table_columns(conn, "gbiz_commendation"))
    if missing_columns:
        raise SchemaError(
            "gbiz_commendation columns missing "
            f"({', '.join(missing_columns)}) — run migration "
            "wave24_164_gbiz_v2_mirror_tables.sql first."
        )
    if not _has_unique_index(
        conn,
        "gbiz_commendation",
        ("houjin_bangou", "title", "date_of_commendation", "government_departments"),
    ):
        raise SchemaError(
            "gbiz_commendation unique identity index missing — run migration "
            "wave24_164_gbiz_v2_mirror_tables.sql first."
        )
    if _canonical_cross_write_enabled():
        facts_columns = _table_columns(conn, "am_entity_facts")
        required_fact_columns = {
            "entity_id",
            "field_name",
            "field_value_text",
            "field_kind",
            "source_url",
            "created_at",
        }
        missing_fact_columns = sorted(required_fact_columns - facts_columns)
        if missing_fact_columns:
            raise SchemaError(
                "am_entity_facts columns missing "
                f"({', '.join(missing_fact_columns)}) while cross-write is enabled."
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--houjin-bangou")
    parser.add_argument("--from", dest="date_from")
    parser.add_argument("--to", dest="date_to")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db-path", "--db", dest="db_path", default=DB_PATH_DEFAULT)
    parser.add_argument("--log-file", type=Path, default=None)
    parser.add_argument("--verbose", action="store_true")
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
        LOG.warning("GBIZINFO_INGEST_ENABLED=false — clean shutdown")
        return 0

    conn: sqlite3.Connection | None = None
    db_path = Path(args.db_path)
    if not db_path.parent.is_dir():
        LOG.error("DB parent dir missing: %s", db_path.parent)
        return 1
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        _ensure_schema(conn)
    except SchemaError as exc:
        LOG.error("schema check failed before fetch: %s", exc)
        if conn is not None:
            conn.close()
        return 2
    except sqlite3.Error as exc:
        LOG.error("DB check failed before fetch: %s", exc)
        if conn is not None:
            conn.close()
        return 1

    try:
        client = GbizRateLimitedClient()
    except RuntimeError as exc:
        LOG.error("token check failed: %s", exc)
        if conn is not None:
            conn.close()
        return 3

    fetched_at = datetime.now(tz=UTC).isoformat()

    try:
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
    except Exception as exc:
        LOG.error("fetch failed: %s", exc)
        if conn is not None:
            conn.close()
        return 1

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
        LOG.info("dry-run complete fetched=%d", len(records))
        conn.close()
        return 0

    assert conn is not None
    try:
        with conn:
            counts = upsert_records(conn, records, source_url, fetched_at)
            append_update_log(
                conn,
                endpoint=endpoint_label,
                from_date=from_date,
                to_date=to_date,
                record_count=counts["fetched"],
                fetched_at=fetched_at,
            )
    finally:
        conn.close()

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
