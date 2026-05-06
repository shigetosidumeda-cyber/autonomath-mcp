#!/usr/bin/env python3
"""gBizINFO procurement v2 cron driver — /v2/hojin/{n}/procurement + /v2/hojin/updateInfo/procurement.

Per DEEP-01 spec §1.2.5; uses the single Bookyou-issued API token at
1 rps + 24h cache TTL per the 6-condition operator agreement
(see ``docs/legal/gbizinfo_terms_compliance.md``).

Modes:
  --houjin-bangou X   per-houjin lookup       (/v2/hojin/{n}/procurement)
  --from / --to       delta sync              (/v2/hojin/updateInfo/procurement?from=&to=)

Mirror table: gbiz_procurement (created by sibling migration
wave24_164_gbiz_v2_mirror_tables.sql).

Cross-write target: ``bids`` is the canonical p-portal side; gBizINFO
is the mirror. Dedupe on ``procurement_resource_id`` mapped onto the
canonical ``unified_id`` (BID-<10 lowercase hex>) — when an upstream
gBizINFO record carries a procurement_resource_id that hashes to an
existing bids.unified_id, the canonical row is left untouched and only
the mirror gbiz_procurement row is recorded. Mirror rows use UPSERT so
fresh upstream values replace stale snapshots on re-runs.

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
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from datetime import UTC
except ImportError:  # pragma: no cover - Python < 3.11 CLI compatibility.
    from datetime import timezone

    UTC = timezone.utc  # noqa: UP017

# Allow running as bare script.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.ingest._gbiz_attribution import build_attribution  # noqa: E402
from jpintel_mcp.ingest._gbiz_rate_limiter import (  # noqa: E402
    GbizRateLimitedClient,
)

LOG = logging.getLogger("ingest_gbiz_procurement_v2")
DB_PATH_DEFAULT = os.environ.get(
    "AUTONOMATH_DB_PATH",
    str(_REPO_ROOT / "autonomath.db"),
)

_ENDPOINT_FAMILY = "procurement"
_API_BASE_URL = "https://info.gbiz.go.jp/hojin"
_INTERNAL_SOURCE_URL_FIELD = "_gbiz_source_url"
_IMAGE_FIELD_BLOCKLIST = {
    "law_mark_image",
    "law_mark_logo",
    "individual_law_mark",
    "image_base64",
}
_GBIZ_PROCUREMENT_REQUIRED_COLUMNS = {
    "procurement_resource_id",
    "houjin_bangou",
    "title",
    "amount_yen",
    "date_of_order",
    "government_departments",
    "note",
    "upstream_source",
    "raw_json",
    "agency",
    "contract_date",
    "contract_amount_yen",
    "subject",
    "procedure_type",
    "source_url",
    "fetched_at",
    "content_hash",
    "attribution_json",
}
_BIDS_REQUIRED_COLUMNS = {
    "unified_id",
    "bid_title",
    "bid_kind",
    "procuring_entity",
    "procuring_houjin_bangou",
    "ministry",
    "prefecture",
    "program_id_hint",
    "announcement_date",
    "question_deadline",
    "bid_deadline",
    "decision_date",
    "budget_ceiling_yen",
    "awarded_amount_yen",
    "winner_name",
    "winner_houjin_bangou",
    "participant_count",
    "bid_description",
    "eligibility_conditions",
    "classification_code",
    "source_url",
    "source_excerpt",
    "source_checksum",
    "confidence",
    "fetched_at",
    "updated_at",
}


class SchemaError(RuntimeError):
    """Required DB schema is absent or too old for this ingest."""


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------
def fetch_per_houjin(
    client: GbizRateLimitedClient,
    houjin_bangou: str,
    *,
    force_refresh: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    """GET /v2/hojin/{n}/procurement → (records, source_url)."""
    path = f"v2/hojin/{houjin_bangou}/procurement"
    body = client.get(path, force_refresh=force_refresh)
    records = _extract_records(body, houjin_default=houjin_bangou)
    source_url = f"{_API_BASE_URL}/{path}"
    records = _tag_records_with_source_url(records, source_url)
    LOG.info(
        "gbiz procurement per-houjin houjin_bangou=%s records=%d",
        houjin_bangou,
        len(records),
    )
    return records, source_url


def fetch_delta(
    client: GbizRateLimitedClient, date_from: str, date_to: str
) -> tuple[list[dict[str, Any]], str]:
    """GET updateInfo/procurement, then re-fetch each listed houjin endpoint."""
    path = "v2/hojin/updateInfo/procurement"
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
        sub_records, _source_url = fetch_per_houjin(
            client,
            houjin_bangou,
            force_refresh=True,
        )
        records.extend(sub_records)
    LOG.info(
        "gbiz procurement delta from=%s to=%s notifications=%d records=%d",
        date_from,
        date_to,
        len(houjin_numbers),
        len(records),
    )
    return records, source_url


def _tag_records_with_source_url(
    records: list[dict[str, Any]],
    source_url: str,
) -> list[dict[str, Any]]:
    tagged: list[dict[str, Any]] = []
    for record in records:
        tagged_record = dict(record)
        tagged_record[_INTERNAL_SOURCE_URL_FIELD] = source_url
        tagged.append(tagged_record)
    return tagged


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
        total = _norm_int(body.get(key))
        if total is not None and total > 0:
            return total
    return 1


def _gbiz_date_param(value: str) -> str:
    return value.replace("-", "") if re.match(r"^\d{4}-\d{2}-\d{2}$", value) else value


def _extract_records(body: dict[str, Any], *, houjin_default: str | None) -> list[dict[str, Any]]:
    """Normalize gBizINFO procurement envelope into a list of records."""
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
                rows = info.get("procurement") or info.get("procurements")
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, dict):
                            row.setdefault("houjin_bangou", houjin_bangou)
                            out.append(row)

    flat = body.get("procurement") or body.get("procurements")
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
    """UPSERT into gbiz_procurement + optional bids cross-link.

    bids is the canonical p-portal side; gBizINFO is the mirror. We only
    insert into bids when no row with the derived unified_id exists yet
    (the cross-link is INSERT OR IGNORE on bids.unified_id).
    """
    counts = {
        "fetched": len(records),
        "mirror_inserted": 0,
        "mirror_updated": 0,
        "canonical_inserted": 0,
        "canonical_skipped": 0,
        "skipped_no_houjin": 0,
        "skipped_no_resource_id": 0,
    }
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

        procurement_resource_id = _norm_str(
            record.get("procurement_resource_id")
            or record.get("procurementResourceId")
            or record.get("resource_id")
            or record.get("id")
        )
        if not procurement_resource_id:
            counts["skipped_no_resource_id"] += 1
            continue

        title = _norm_str(
            record.get("title") or record.get("subject") or record.get("procurement_name")
        )
        amount_yen = _norm_int(
            record.get("amount")
            or record.get("amount_yen")
            or record.get("contract_amount_yen")
            or record.get("contract_amount")
        )
        contract_date = _norm_str(
            record.get("date_of_order") or record.get("contract_date") or record.get("orderDate")
        )
        agency = _norm_str(
            record.get("government_departments") or record.get("agency") or record.get("ministry")
        )
        procedure_type = _norm_str(
            record.get("procedure_type")
            or record.get("procedureType")
            or record.get("contract_method")
        )
        subject = _norm_str(record.get("subject")) or title
        upstream_source = _norm_str(record.get("upstream_source")) or agency or "p-portal"
        record_source_url = _record_source_url(record, source_url)

        attribution = build_attribution(
            source_url=record_source_url,
            fetched_at=fetched_at,
            upstream_source=upstream_source,
        )
        attribution_payload = attribution["_attribution"]
        raw_record = _strip_internal_fields(record)
        raw_blob = json.dumps(
            {**raw_record, "_attribution": attribution_payload},
            ensure_ascii=False,
            sort_keys=True,
        )
        content_hash = hashlib.sha256(
            json.dumps(raw_record, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

        conn.execute("SAVEPOINT gbiz_procurement_record")
        try:
            mirror_existed = (
                conn.execute(
                    """
                    SELECT 1
                      FROM gbiz_procurement
                     WHERE procurement_resource_id = ?
                     LIMIT 1
                    """,
                    (procurement_resource_id,),
                ).fetchone()
                is not None
            )
            conn.execute(
                """
                INSERT INTO gbiz_procurement (
                    procurement_resource_id, houjin_bangou, title, amount_yen,
                    date_of_order, government_departments, note,
                    upstream_source, raw_json, agency, contract_date,
                    contract_amount_yen, subject, procedure_type,
                    source_url, fetched_at, content_hash, attribution_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(procurement_resource_id) DO UPDATE SET
                    houjin_bangou = excluded.houjin_bangou,
                    title = excluded.title,
                    amount_yen = excluded.amount_yen,
                    date_of_order = excluded.date_of_order,
                    government_departments = excluded.government_departments,
                    note = excluded.note,
                    upstream_source = excluded.upstream_source,
                    raw_json = excluded.raw_json,
                    agency = excluded.agency,
                    contract_date = excluded.contract_date,
                    contract_amount_yen = excluded.contract_amount_yen,
                    subject = excluded.subject,
                    procedure_type = excluded.procedure_type,
                    source_url = excluded.source_url,
                    fetched_at = excluded.fetched_at,
                    content_hash = excluded.content_hash,
                    attribution_json = excluded.attribution_json
                """,
                (
                    procurement_resource_id,
                    houjin_bangou,
                    title,
                    amount_yen,
                    contract_date,
                    agency,
                    _norm_str(record.get("note")),
                    upstream_source,
                    raw_blob,
                    agency,
                    contract_date,
                    amount_yen,
                    subject,
                    procedure_type,
                    record_source_url,
                    fetched_at,
                    content_hash,
                    json.dumps(attribution_payload, ensure_ascii=False, sort_keys=True),
                ),
            )

            # Canonical cross-write into bids — disabled by default until lineage policy is reviewed.
            # Derive unified_id from procurement_resource_id for stable dedupe.
            if not _canonical_cross_write_enabled():
                counts["canonical_skipped"] += 1
            else:
                unified_id = _derive_unified_id(procurement_resource_id)
                bid_kind = _map_procedure_to_bid_kind(procedure_type)
                bid_cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO bids (
                        unified_id, bid_title, bid_kind, procuring_entity,
                        procuring_houjin_bangou, ministry, prefecture,
                        program_id_hint, announcement_date, question_deadline,
                        bid_deadline, decision_date, budget_ceiling_yen,
                        awarded_amount_yen, winner_name, winner_houjin_bangou,
                        participant_count, bid_description, eligibility_conditions,
                        classification_code, source_url, source_excerpt,
                        source_checksum, confidence, fetched_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        unified_id,
                        title or procurement_resource_id,
                        bid_kind,
                        agency or "未掲載",
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        contract_date,
                        None,
                        amount_yen,
                        None,  # winner_name — gBiz often omits, leaves blank
                        houjin_bangou,
                        None,
                        None,
                        None,
                        None,
                        record_source_url,
                        None,
                        None,
                        0.85,  # gBiz procurement mirror confidence
                        fetched_at,
                        fetched_at,
                    ),
                )
                if bid_cursor.rowcount > 0:
                    counts["canonical_inserted"] += 1
                else:
                    counts["canonical_skipped"] += 1
        except Exception:
            conn.execute("ROLLBACK TO SAVEPOINT gbiz_procurement_record")
            conn.execute("RELEASE SAVEPOINT gbiz_procurement_record")
            raise
        else:
            conn.execute("RELEASE SAVEPOINT gbiz_procurement_record")

        if mirror_existed:
            counts["mirror_updated"] += 1
        else:
            counts["mirror_inserted"] += 1

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


def _canonical_cross_write_enabled() -> bool:
    return os.environ.get("GBIZINFO_CANONICAL_CROSS_WRITE_ENABLED", "false").lower() == "true"


def _record_source_url(record: dict[str, Any], default_source_url: str) -> str:
    return (
        _norm_str(record.get(_INTERNAL_SOURCE_URL_FIELD))
        or _norm_str(record.get("source_url"))
        or default_source_url
    )


def _strip_internal_fields(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key != _INTERNAL_SOURCE_URL_FIELD}


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


def _derive_unified_id(procurement_resource_id: str) -> str:
    """Map procurement_resource_id → BID-<10 lowercase hex>.

    ``bids.unified_id`` enforces a CHECK constraint length(unified_id) = 14
    AND substr(unified_id,1,4) = 'BID-' (see migration 017_bids.sql).
    Stable hash so re-runs collapse onto the same canonical row.
    """
    digest = hashlib.sha256(procurement_resource_id.encode("utf-8")).hexdigest()
    return f"BID-{digest[:10]}"


def _map_procedure_to_bid_kind(procedure_type: str | None) -> str:
    """Coerce free-text procedure_type into the bids.bid_kind enum."""
    if not procedure_type:
        return "open"
    text = procedure_type.lower()
    if "随意" in procedure_type or "negotiat" in text:
        return "negotiated"
    if "指名" in procedure_type or "select" in text:
        return "selective"
    if "公募" in procedure_type or "kobo" in text or "subsidy" in text:
        return "kobo_subsidy"
    return "open"


def _ensure_schema(conn: sqlite3.Connection) -> None:
    _ensure_table_columns(
        conn,
        "gbiz_procurement",
        _GBIZ_PROCUREMENT_REQUIRED_COLUMNS,
    )
    if _canonical_cross_write_enabled():
        _ensure_table_columns(conn, "bids", _BIDS_REQUIRED_COLUMNS)


def _ensure_table_columns(
    conn: sqlite3.Connection,
    table_name: str,
    required_columns: set[str],
) -> None:
    table_exists = (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        is not None
    )
    if not table_exists:
        raise SchemaError(
            f"{table_name} table missing; run wave24_164_gbiz_v2_mirror_tables.sql first."
        )

    actual_columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}
    missing_columns = sorted(required_columns - actual_columns)
    if missing_columns:
        raise SchemaError(f"{table_name} schema missing columns: {', '.join(missing_columns)}")


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

    db_path = Path(args.db_path)
    conn: sqlite3.Connection | None = None
    try:
        if not args.dry_run:
            if not db_path.parent.is_dir():
                LOG.error("DB parent dir missing: %s", db_path.parent)
                return 1
            if not db_path.exists():
                LOG.error("DB file missing: %s", db_path)
                return 2
            try:
                conn = sqlite3.connect(str(db_path))
                conn.execute("PRAGMA foreign_keys = ON")
                _ensure_schema(conn)
            except SchemaError as exc:
                LOG.error("schema check failed before fetch: %s", exc)
                return 2
            except sqlite3.Error as exc:
                LOG.error("DB check failed before fetch: %s", exc)
                return 1

        try:
            client = GbizRateLimitedClient()
        except RuntimeError as exc:
            LOG.error("token check failed: %s", exc)
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
            return 0

        if conn is None:
            LOG.error("DB connection was not initialized")
            return 1

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
        except sqlite3.Error as exc:
            LOG.error("DB write failed: %s", exc)
            return 1
    finally:
        if conn is not None:
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
