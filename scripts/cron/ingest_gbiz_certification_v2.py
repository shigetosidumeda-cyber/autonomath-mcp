#!/usr/bin/env python3
"""gBizINFO certification v2 cron driver — /v2/hojin/{n}/certification + /v2/hojin/updateInfo/certification.

Per DEEP-01 spec §1.2.3; uses the single Bookyou-issued API token at
1 rps + 24h cache TTL per the 6-condition operator agreement
(see ``docs/legal/gbizinfo_terms_compliance.md``).

Modes:
  --houjin-bangou X   per-houjin lookup       (/v2/hojin/{n}/certification)
  --from / --to       delta sync              (/v2/hojin/updateInfo/certification?from=&to=)

Mirror table: gbiz_certification (created by sibling migration
wave24_164_gbiz_v2_mirror_tables.sql).

Cross-write target: ``am_entity_facts`` under the ``cert.*`` field_name
namespace, keyed on the corporate_entity ``houjin:<bangou>`` canonical_id.
Mirror/fact writes use UPSERT semantics for idempotency. The mirror UNIQUE
index includes nullable columns, so this script also performs a null-safe
identity lookup before insert to avoid duplicate rows when gBiz omits
date_of_approval or government_departments.

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

LOG = logging.getLogger("ingest_gbiz_certification_v2")
DB_PATH_DEFAULT = os.environ.get(
    "AUTONOMATH_DB_PATH",
    str(_REPO_ROOT / "autonomath.db"),
)

_ENDPOINT_FAMILY = "certification"
_API_BASE_URL = "https://info.gbiz.go.jp/hojin"
_FACT_NAMESPACE = "cert"
_IMAGE_FIELD_BLOCKLIST = {
    "law_mark_image",
    "law_mark_logo",
    "individual_law_mark",
    "image_base64",
}
_GBIZ_CERTIFICATION_REQUIRED_COLUMNS = {
    "houjin_bangou",
    "title",
    "category",
    "date_of_approval",
    "government_departments",
    "target",
    "upstream_source",
    "raw_json",
    "cert_id",
    "cert_name",
    "issuing_authority",
    "issued_date",
    "valid_until",
    "cert_url",
    "source_url",
    "fetched_at",
    "content_hash",
    "attribution_json",
}
_AM_ENTITY_FACTS_REQUIRED_COLUMNS = {
    "entity_id",
    "field_name",
    "field_value_text",
    "field_kind",
    "source_url",
    "created_at",
}
_GBIZ_CERTIFICATION_IDENTITY_COLUMNS = (
    "houjin_bangou",
    "title",
    "date_of_approval",
    "government_departments",
)


class SchemaError(RuntimeError):
    """Raised when the local DB has not had the gBiz mirror migration applied."""


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------
def fetch_per_houjin(
    client: GbizRateLimitedClient,
    houjin_bangou: str,
    *,
    force_refresh: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    """GET /v2/hojin/{n}/certification → (records, source_url)."""
    path = f"v2/hojin/{houjin_bangou}/certification"
    body = client.get(path, force_refresh=force_refresh)
    records = _extract_records(body, houjin_default=houjin_bangou)
    source_url = f"{_API_BASE_URL}/{path}"
    LOG.info(
        "gbiz certification per-houjin houjin_bangou=%s records=%d",
        houjin_bangou,
        len(records),
    )
    return records, source_url


def fetch_delta(
    client: GbizRateLimitedClient, date_from: str, date_to: str
) -> tuple[list[dict[str, Any]], str]:
    """GET updateInfo/certification, then re-fetch each listed houjin endpoint."""
    path = "v2/hojin/updateInfo/certification"
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
        for sub_record in sub_records:
            sub_record["_gbiz_source_url"] = sub_source_url
            records.append(sub_record)
    LOG.info(
        "gbiz certification delta from=%s to=%s notifications=%d records=%d",
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
    """Normalize gBizINFO certification envelope into a list of records."""
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
                rows = info.get("certification") or info.get("certifications")
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, dict):
                            row.setdefault("houjin_bangou", houjin_bangou)
                            out.append(row)

    flat = body.get("certification") or body.get("certifications")
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
    """UPSERT into gbiz_certification + cert.* facts."""
    counts = {
        "fetched": len(records),
        "mirror_inserted": 0,
        "mirror_updated": 0,
        "facts_inserted": 0,
        "facts_updated": 0,
        "facts_skipped": 0,
        "skipped_no_houjin": 0,
        "skipped_no_title": 0,
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

        cert_id_hint = _norm_str(record.get("cert_id") or record.get("certId"))
        cert_name = _norm_str(
            record.get("title") or record.get("cert_name") or record.get("certification_name")
        )
        if not cert_name:
            counts["skipped_no_title"] += 1
            continue

        category = _norm_str(record.get("category"))
        issuing_authority = _norm_str(
            record.get("government_departments")
            or record.get("issuing_authority")
            or record.get("agency")
        )
        upstream_source = (
            _norm_str(record.get("upstream_source"))
            or issuing_authority
            or "gbizinfo:upstream_unspecified"
        )
        issued_date = _norm_str(
            record.get("date_of_approval")
            or record.get("issued_date")
            or record.get("approval_date")
        )
        valid_until = _norm_str(
            record.get("valid_until") or record.get("validUntil") or record.get("expiry_date")
        )
        cert_url = _norm_str(
            record.get("cert_url") or record.get("source_url") or record.get("reference_url")
        )
        record_source_url = _norm_str(record.get("_gbiz_source_url")) or source_url

        attribution = build_attribution(
            source_url=record_source_url,
            fetched_at=fetched_at,
            upstream_source=upstream_source,
        )
        attribution_payload = attribution["_attribution"]
        raw_blob = json.dumps(
            {**record, "_attribution": attribution_payload},
            ensure_ascii=False,
            sort_keys=True,
        )
        content_hash = hashlib.sha256(raw_blob.encode("utf-8")).hexdigest()

        existing_id = _find_existing_certification_id(
            conn,
            houjin_bangou=houjin_bangou,
            title=cert_name,
            date_of_approval=issued_date,
            government_departments=issuing_authority,
        )
        if existing_id is None:
            cursor = _insert_gbiz_certification(
                conn,
                houjin_bangou=houjin_bangou,
                title=cert_name,
                category=category,
                date_of_approval=issued_date,
                government_departments=issuing_authority,
                target=_norm_str(record.get("target")),
                upstream_source=upstream_source,
                raw_json=raw_blob,
                cert_id=cert_id_hint,
                cert_name=cert_name,
                issuing_authority=issuing_authority,
                issued_date=issued_date,
                valid_until=valid_until,
                cert_url=cert_url,
                source_url=record_source_url,
                fetched_at=fetched_at,
                content_hash=content_hash,
                attribution_json=json.dumps(
                    attribution_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
            counts["mirror_inserted"] += 1
            if cursor.rowcount == 0:
                counts["mirror_inserted"] -= 1
                counts["mirror_updated"] += 1
        else:
            _update_gbiz_certification(
                conn,
                row_id=existing_id,
                category=category,
                date_of_approval=issued_date,
                government_departments=issuing_authority,
                target=_norm_str(record.get("target")),
                upstream_source=upstream_source,
                raw_json=raw_blob,
                cert_id=cert_id_hint,
                cert_name=cert_name,
                issuing_authority=issuing_authority,
                issued_date=issued_date,
                valid_until=valid_until,
                cert_url=cert_url,
                source_url=record_source_url,
                fetched_at=fetched_at,
                content_hash=content_hash,
                attribution_json=json.dumps(
                    attribution_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
            counts["mirror_updated"] += 1

        # Cross-write into am_entity_facts under cert.* namespace.
        if not _canonical_cross_write_enabled():
            counts["facts_skipped"] += 1
            continue
        entity_id = f"houjin:{houjin_bangou}"
        fact_rows = _build_cert_facts(
            entity_id=entity_id,
            cert_id_hint=cert_id_hint or _slug(cert_name),
            cert_name=cert_name,
            issuing_authority=issuing_authority,
            issued_date=issued_date,
            valid_until=valid_until,
            cert_url=cert_url,
            source_url=record_source_url,
        )
        for field_name, field_kind, value_text in fact_rows:
            existing_fact_id = _find_existing_fact_id(
                conn,
                entity_id=entity_id,
                field_name=field_name,
                field_value_text=value_text,
            )
            if existing_fact_id is None:
                _insert_entity_fact(
                    conn,
                    entity_id=entity_id,
                    field_name=field_name,
                    field_value_text=value_text,
                    field_kind=field_kind,
                    source_url=record_source_url,
                    created_at=fetched_at,
                )
                counts["facts_inserted"] += 1
            else:
                conn.execute(
                    """
                    UPDATE am_entity_facts
                       SET field_kind = ?,
                           source_url = ?
                     WHERE id = ?
                    """,
                    (field_kind, record_source_url, existing_fact_id),
                )
                counts["facts_updated"] += 1

    return counts


def _find_existing_certification_id(
    conn: sqlite3.Connection,
    *,
    houjin_bangou: str,
    title: str,
    date_of_approval: str | None,
    government_departments: str | None,
) -> int | None:
    """Null-safe mirror identity lookup before INSERT.

    SQLite UNIQUE indexes permit multiple NULLs, so the DB constraint alone
    cannot dedupe records where gBiz omits date_of_approval or authority.
    """
    row = conn.execute(
        """
        SELECT id
          FROM gbiz_certification
         WHERE houjin_bangou = ?
           AND title = ?
           AND COALESCE(date_of_approval, '') = COALESCE(?, '')
           AND COALESCE(government_departments, '') = COALESCE(?, '')
         ORDER BY fetched_at DESC, id DESC
         LIMIT 1
        """,
        (houjin_bangou, title, date_of_approval, government_departments),
    ).fetchone()
    return int(row[0]) if row is not None else None


def _insert_gbiz_certification(
    conn: sqlite3.Connection,
    *,
    houjin_bangou: str,
    title: str,
    category: str | None,
    date_of_approval: str | None,
    government_departments: str | None,
    target: str | None,
    upstream_source: str,
    raw_json: str,
    cert_id: str | None,
    cert_name: str,
    issuing_authority: str | None,
    issued_date: str | None,
    valid_until: str | None,
    cert_url: str | None,
    source_url: str,
    fetched_at: str,
    content_hash: str,
    attribution_json: str,
) -> sqlite3.Cursor:
    return conn.execute(
        """
        INSERT INTO gbiz_certification (
            houjin_bangou, title, category, date_of_approval,
            government_departments, target, upstream_source, raw_json,
            cert_id, cert_name, issuing_authority, issued_date,
            valid_until, cert_url, source_url, fetched_at,
            content_hash, attribution_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(houjin_bangou, title, date_of_approval, government_departments)
        DO UPDATE SET
            category = excluded.category,
            target = excluded.target,
            upstream_source = excluded.upstream_source,
            raw_json = excluded.raw_json,
            cert_id = excluded.cert_id,
            cert_name = excluded.cert_name,
            issuing_authority = excluded.issuing_authority,
            issued_date = excluded.issued_date,
            valid_until = excluded.valid_until,
            cert_url = excluded.cert_url,
            source_url = excluded.source_url,
            fetched_at = excluded.fetched_at,
            content_hash = excluded.content_hash,
            attribution_json = excluded.attribution_json
        """,
        (
            houjin_bangou,
            title,
            category,
            date_of_approval,
            government_departments,
            target,
            upstream_source,
            raw_json,
            cert_id,
            cert_name,
            issuing_authority,
            issued_date,
            valid_until,
            cert_url,
            source_url,
            fetched_at,
            content_hash,
            attribution_json,
        ),
    )


def _update_gbiz_certification(
    conn: sqlite3.Connection,
    *,
    row_id: int,
    category: str | None,
    date_of_approval: str | None,
    government_departments: str | None,
    target: str | None,
    upstream_source: str,
    raw_json: str,
    cert_id: str | None,
    cert_name: str,
    issuing_authority: str | None,
    issued_date: str | None,
    valid_until: str | None,
    cert_url: str | None,
    source_url: str,
    fetched_at: str,
    content_hash: str,
    attribution_json: str,
) -> None:
    conn.execute(
        """
        UPDATE gbiz_certification
           SET category = ?,
               date_of_approval = ?,
               government_departments = ?,
               target = ?,
               upstream_source = ?,
               raw_json = ?,
               cert_id = ?,
               cert_name = ?,
               issuing_authority = ?,
               issued_date = ?,
               valid_until = ?,
               cert_url = ?,
               source_url = ?,
               fetched_at = ?,
               content_hash = ?,
               attribution_json = ?
         WHERE id = ?
        """,
        (
            category,
            date_of_approval,
            government_departments,
            target,
            upstream_source,
            raw_json,
            cert_id,
            cert_name,
            issuing_authority,
            issued_date,
            valid_until,
            cert_url,
            source_url,
            fetched_at,
            content_hash,
            attribution_json,
            row_id,
        ),
    )


def _find_existing_fact_id(
    conn: sqlite3.Connection,
    *,
    entity_id: str,
    field_name: str,
    field_value_text: str,
) -> int | None:
    row = conn.execute(
        """
        SELECT id
          FROM am_entity_facts
         WHERE entity_id = ?
           AND field_name = ?
           AND COALESCE(field_value_text, '') = COALESCE(?, '')
         ORDER BY id DESC
         LIMIT 1
        """,
        (entity_id, field_name, field_value_text),
    ).fetchone()
    return int(row[0]) if row is not None else None


def _insert_entity_fact(
    conn: sqlite3.Connection,
    *,
    entity_id: str,
    field_name: str,
    field_value_text: str,
    field_kind: str,
    source_url: str,
    created_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO am_entity_facts (
            entity_id, field_name, field_value_text, field_kind,
            source_url, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(entity_id, field_name, COALESCE(field_value_text, ''))
        DO UPDATE SET
            field_kind = excluded.field_kind,
            source_url = excluded.source_url
        """,
        (
            entity_id,
            field_name,
            field_value_text,
            field_kind,
            source_url,
            created_at,
        ),
    )


def _build_cert_facts(
    *,
    entity_id: str,
    cert_id_hint: str,
    cert_name: str,
    issuing_authority: str | None,
    issued_date: str | None,
    valid_until: str | None,
    cert_url: str | None,
    source_url: str,
) -> list[tuple[str, str, str]]:
    """Compose (field_name, field_kind, field_value_text) tuples for cert.* facts.

    Field-name suffix uses a per-cert slug so multiple certifications on
    the same houjin do not collide in the UNIQUE index.
    """
    suffix = cert_id_hint
    rows: list[tuple[str, str, str]] = []
    rows.append((f"{_FACT_NAMESPACE}.{suffix}.title", "text", cert_name))
    if issuing_authority:
        rows.append((f"{_FACT_NAMESPACE}.{suffix}.issuing_authority", "text", issuing_authority))
    if issued_date:
        rows.append((f"{_FACT_NAMESPACE}.{suffix}.issued_date", "date", issued_date))
    if valid_until:
        rows.append((f"{_FACT_NAMESPACE}.{suffix}.valid_until", "date", valid_until))
    if cert_url:
        rows.append((f"{_FACT_NAMESPACE}.{suffix}.cert_url", "url", cert_url))
    rows.append((f"{_FACT_NAMESPACE}.{suffix}.source_url", "url", source_url))
    return rows


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
    """Lowercase, alnum-only, max 32 chars — used as field_name suffix."""
    if not text:
        return "unknown"
    cleaned = "".join(c.lower() if c.isalnum() else "_" for c in text)
    cleaned = cleaned.strip("_")
    return cleaned[:32] or "unknown"


def _preflight_database(db_path: Path) -> None:
    """Verify local DB/schema before any live gBiz fetch is attempted."""
    if not db_path.exists():
        raise FileNotFoundError(f"DB file missing: {db_path}")
    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_schema(conn)
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        ("gbiz_certification",),
    )
    if cursor.fetchone() is None:
        raise SchemaError(
            "gbiz_certification table missing — run migration "
            "wave24_164_gbiz_v2_mirror_tables.sql first."
        )
    missing = _GBIZ_CERTIFICATION_REQUIRED_COLUMNS - _table_columns(conn, "gbiz_certification")
    if missing:
        raise SchemaError("gbiz_certification missing columns: " + ", ".join(sorted(missing)))
    if not _has_unique_index(
        conn,
        "gbiz_certification",
        _GBIZ_CERTIFICATION_IDENTITY_COLUMNS,
    ):
        raise SchemaError(
            "gbiz_certification unique identity index missing: "
            + ", ".join(_GBIZ_CERTIFICATION_IDENTITY_COLUMNS)
        )
    if _canonical_cross_write_enabled():
        if not _table_exists(conn, "am_entity_facts"):
            raise SchemaError(
                "am_entity_facts table missing while canonical cross-write is enabled"
            )
        missing_facts = _AM_ENTITY_FACTS_REQUIRED_COLUMNS - _table_columns(
            conn,
            "am_entity_facts",
        )
        if missing_facts:
            raise SchemaError(
                "am_entity_facts missing columns: " + ", ".join(sorted(missing_facts))
            )
        if not _index_exists(conn, "am_entity_facts", "uq_am_facts_entity_field_text"):
            raise SchemaError(
                "am_entity_facts unique expression index missing: uq_am_facts_entity_field_text"
            )


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})")}


def _has_unique_index(
    conn: sqlite3.Connection,
    table_name: str,
    columns: tuple[str, ...],
) -> bool:
    for index_row in conn.execute(f"PRAGMA index_list({table_name})"):
        index_name = str(index_row[1])
        is_unique = bool(index_row[2])
        if not is_unique:
            continue
        index_columns = tuple(
            str(info_row[2]) for info_row in conn.execute(f"PRAGMA index_info({index_name})")
        )
        if index_columns == columns:
            return True
    return False


def _index_exists(conn: sqlite3.Connection, table_name: str, index_name: str) -> bool:
    return any(
        str(row[1]) == index_name for row in conn.execute(f"PRAGMA index_list({table_name})")
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--houjin-bangou",
        help="13-digit corporate number (per-houjin lookup mode)",
    )
    parser.add_argument("--from", dest="date_from", help="Delta from-date YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", help="Delta to-date YYYY-MM-DD")
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
    if not db_path.parent.is_dir():
        LOG.error("DB parent dir missing: %s", db_path.parent)
        return 1
    try:
        _preflight_database(db_path)
    except SchemaError as exc:
        LOG.error("schema check failed before fetch: %s", exc)
        return 2
    except (OSError, sqlite3.Error) as exc:
        LOG.error("DB check failed before fetch: %s", exc)
        return 1

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
        LOG.info("dry-run complete fetched=%d", len(records))
        return 0

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        _ensure_schema(conn)
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
    except SchemaError as exc:
        LOG.error("schema check failed before write: %s", exc)
        return 2
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
