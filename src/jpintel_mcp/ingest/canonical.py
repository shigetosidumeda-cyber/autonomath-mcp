"""Ingest Autonomath canonical data into jpintel SQLite.

Source of truth:
- unified_registry.json -> programs table (+ fts)
- canonical/enriched/*.json -> programs.enriched_json
- agri/exclusion_rules.json -> exclusion_rules table

Run: python -m jpintel_mcp.ingest.canonical
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import orjson

from jpintel_mcp.api.vocab import _normalize_authority_level, _normalize_prefecture
from jpintel_mcp.config import settings
from jpintel_mcp.db.session import connect, init_db

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

logger = logging.getLogger("jpintel.ingest")


def _json_dump(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, (list, dict)):
        if not v:
            return None
        return str(orjson.dumps(v).decode("utf-8"))
    return str(orjson.dumps(v).decode("utf-8"))


def _flatten_enriched_text(enriched: dict[str, Any]) -> str:
    """Flatten enriched JSON to a single searchable blob for FTS.

    We keep primitive values joined with spaces. Keeps the text compact
    but makes FTS find real content (not just names).
    """
    out: list[str] = []

    def walk(v: Any) -> None:
        if v is None:
            return
        if isinstance(v, str):
            s = v.strip()
            if s:
                out.append(s)
        elif isinstance(v, (int, float)):
            out.append(str(v))
        elif isinstance(v, list):
            for item in v:
                walk(item)
        elif isinstance(v, dict):
            for k, item in v.items():
                if isinstance(k, str):
                    out.append(k)
                walk(item)

    walk(enriched)
    return "\n".join(out)


def _load_enriched(enriched_dir: Path, unified_id: str) -> dict[str, Any] | None:
    p = enriched_dir / f"{unified_id}.json"
    if not p.is_file():
        return None
    try:
        parsed = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("invalid_json enriched=%s", p)
        return None
    return parsed if isinstance(parsed, dict) else None


def _compute_source_checksum(enriched: dict[str, Any] | None, entry: dict[str, Any]) -> str:
    """Stable short sha256 of enriched + canonical fields that drive the record.

    Truncated to 16 hex chars to keep rows compact. Uses sort_keys so semantic
    equality across ingests yields identical checksums.
    """
    payload: dict[str, Any] = {
        "enriched": enriched if enriched is not None else None,
        "primary_name": entry.get("primary_name"),
        "official_url": entry.get("official_url"),
        "amount_max_man_yen": entry.get("amount_max_man_yen"),
        "amount_min_man_yen": entry.get("amount_min_man_yen"),
        "subsidy_rate": entry.get("subsidy_rate"),
        "tier": entry.get("tier"),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _extract_source_url(enriched: dict[str, Any] | None, entry: dict[str, Any]) -> str | None:
    """Pick the best available source URL for lineage.

    Priority: enriched.official_url -> enriched.primary_source -> entry.official_url.
    Accepts both string and {"url": "..."} shapes for primary_source.
    """
    if enriched:
        u = enriched.get("official_url")
        if isinstance(u, str) and u.strip():
            return u.strip()
        ps = enriched.get("primary_source")
        if isinstance(ps, str) and ps.strip():
            return ps.strip()
        if isinstance(ps, dict):
            inner = ps.get("url")
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
    u = entry.get("official_url")
    if isinstance(u, str) and u.strip():
        return u.strip()
    return None


def _ingest_programs(conn: sqlite3.Connection, registry: dict[str, Any], enriched_dir: Path) -> int:
    programs = registry.get("programs", {})
    if not programs:
        raise RuntimeError("unified_registry.json has no 'programs' dict")

    # Preserve prior lineage so unchanged records keep their fetched_at timestamp.
    prior: dict[str, tuple[str | None, str | None, str | None]] = {}
    for row in conn.execute(
        "SELECT unified_id, source_url, source_fetched_at, source_checksum FROM programs"
    ):
        prior[row["unified_id"]] = (
            row["source_url"],
            row["source_fetched_at"],
            row["source_checksum"],
        )

    conn.execute("DELETE FROM programs")
    conn.execute("DELETE FROM programs_fts")

    now = datetime.now(UTC).isoformat()
    inserted = 0

    for uid, entry in programs.items():
        if not isinstance(entry, dict):
            continue

        enriched = _load_enriched(enriched_dir, uid)
        enriched_text = _flatten_enriched_text(enriched) if enriched else ""

        source_url = _extract_source_url(enriched, entry)
        new_checksum = _compute_source_checksum(enriched, entry)

        prev = prior.get(uid)
        if prev and prev[2] == new_checksum and prev[1]:
            # Same content -> keep the original fetched_at to reflect
            # "when we first saw this exact payload".
            source_fetched_at = prev[1]
            source_checksum = prev[2]
        else:
            source_fetched_at = now
            source_checksum = new_checksum

        conn.execute(
            """INSERT INTO programs (
                unified_id, primary_name, aliases_json,
                authority_level, authority_name, prefecture, municipality,
                program_kind, official_url,
                amount_max_man_yen, amount_min_man_yen, subsidy_rate,
                trust_level, tier, coverage_score, gap_to_tier_s_json, a_to_j_coverage_json,
                excluded, exclusion_reason,
                crop_categories_json, equipment_category,
                target_types_json, funding_purpose_json,
                amount_band, application_window_json,
                enriched_json, source_mentions_json,
                source_url, source_fetched_at, source_checksum,
                updated_at
            ) VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )""",
            (
                uid,
                entry.get("primary_name") or "",
                _json_dump(entry.get("aliases") or []),
                # Canonicalize at write time so search filters never miss
                # rows due to JP/EN drift (e.g. "国" stored vs `authority_level=national`
                # filter). API boundary already canonicalizes input; this
                # closes the loop on the storage side. See api/vocab.py.
                _normalize_authority_level(entry.get("authority_level")),
                entry.get("authority_name"),
                _normalize_prefecture(entry.get("prefecture")),
                entry.get("municipality"),
                entry.get("program_kind"),
                entry.get("official_url"),
                entry.get("amount_max_man_yen"),
                entry.get("amount_min_man_yen"),
                entry.get("subsidy_rate"),
                entry.get("trust_level"),
                entry.get("tier"),
                entry.get("coverage_score"),
                _json_dump(entry.get("gap_to_tier_s") or []),
                _json_dump(entry.get("a_to_j_coverage") or {}),
                1 if entry.get("excluded") else 0,
                entry.get("exclusion_reason"),
                _json_dump(entry.get("crop_categories") or []),
                entry.get("equipment_category"),
                _json_dump(entry.get("target_types") or []),
                _json_dump(entry.get("funding_purpose") or []),
                entry.get("amount_band"),
                _json_dump(entry.get("application_window")),
                _json_dump(enriched) if enriched else None,
                _json_dump(entry.get("source_mentions") or []),
                source_url,
                source_fetched_at,
                source_checksum,
                now,
            ),
        )

        aliases = entry.get("aliases") or []
        conn.execute(
            "INSERT INTO programs_fts(unified_id, primary_name, aliases, enriched_text) VALUES (?,?,?,?)",
            (
                uid,
                entry.get("primary_name") or "",
                " / ".join(a for a in aliases if isinstance(a, str)),
                enriched_text,
            ),
        )

        inserted += 1
        if inserted % 500 == 0:
            logger.info("ingested %d programs", inserted)

    return inserted


def _ingest_exclusion_rules(conn: sqlite3.Connection, rules_path: Path) -> int:
    if not rules_path.is_file():
        logger.warning("exclusion_rules.json not found at %s", rules_path)
        return 0

    data = json.loads(rules_path.read_text(encoding="utf-8"))
    rules = data.get("rules", {})

    conn.execute("DELETE FROM exclusion_rules")
    inserted = 0

    for rid, rule in rules.items():
        if not isinstance(rule, dict):
            continue
        base_keys = {
            "rule_id",
            "kind",
            "severity",
            "program_a",
            "program_b",
            "program_b_group",
            "description",
            "source_notes",
            "source_urls",
        }
        extra = {k: v for k, v in rule.items() if k not in base_keys}

        conn.execute(
            """INSERT INTO exclusion_rules (
                rule_id, kind, severity, program_a, program_b,
                program_b_group_json, description, source_notes,
                source_urls_json, extra_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                rule.get("rule_id") or rid,
                rule.get("kind") or "unknown",
                rule.get("severity"),
                rule.get("program_a"),
                rule.get("program_b"),
                _json_dump(rule.get("program_b_group") or []),
                rule.get("description"),
                rule.get("source_notes"),
                _json_dump(rule.get("source_urls") or []),
                _json_dump(extra),
            ),
        )
        inserted += 1

    return inserted


def _write_meta(
    conn: sqlite3.Connection,
    programs_count: int,
    rules_count: int,
    data_as_of: str | None,
) -> None:
    now = datetime.now(UTC).isoformat()
    rows = [
        ("total_programs", str(programs_count)),
        ("total_exclusion_rules", str(rules_count)),
        ("last_ingested_at", now),
    ]
    if data_as_of:
        rows.append(("data_as_of", data_as_of))
    for k, v in rows:
        conn.execute(
            """INSERT INTO meta(key, value, updated_at) VALUES (?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (k, v, now),
        )


def run() -> int:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    reg_path = settings.autonomath_registry
    enriched_dir = settings.autonomath_enriched_dir
    rules_path = settings.autonomath_exclusion_rules

    if not reg_path.is_file():
        logger.error("unified_registry.json missing at %s", reg_path)
        return 2

    logger.info("init_db %s", settings.db_path)
    init_db()

    logger.info("loading registry %s", reg_path)
    registry = json.loads(reg_path.read_text(encoding="utf-8"))
    data_as_of = (registry.get("_meta") or {}).get("generated_at") or (
        registry.get("_meta") or {}
    ).get("last_updated")

    conn = connect()
    try:
        conn.execute("BEGIN")
        p_count = _ingest_programs(conn, registry, enriched_dir)
        r_count = _ingest_exclusion_rules(conn, rules_path)
        _write_meta(conn, p_count, r_count, data_as_of)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    logger.info("done programs=%d exclusion_rules=%d", p_count, r_count)
    print(f"ingested programs={p_count} exclusion_rules={r_count}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
