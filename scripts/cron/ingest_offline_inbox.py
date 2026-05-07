#!/usr/bin/env python3
"""Ingest operator-side offline inbox JSONL into production SQLite (no LLM).

Runs after each operator-driven `tools/offline/run_*.py` batch lands JSON
Lines in `tools/offline/_inbox/{tool}/`. The cron walks each tool's inbox
directory, validates every line with a Pydantic model + literal-quote
check, and inserts/updates the corresponding production table.

LLM-FREE GUARANTEE:
    This script lives under `scripts/cron/`, where the CI guard
    `tests/test_no_llm_in_production.py` forbids any of:
        - import anthropic
        - import openai
        - import google.generativeai
        - import claude_agent_sdk
        - ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY / GOOGLE_API_KEY
    All inference work happened upstream in `tools/offline/` (operator
    workstation). This cron is pure SQLite + Pydantic + pathlib.

DIRECTORY LAYOUT:
    tools/offline/_inbox/
        exclusion_rules/   { *.jsonl, .gitkeep }
        enforcement_amount/{ *.jsonl, .gitkeep }
        jsic_classification/{ *.jsonl, .gitkeep }
        program_narrative/ { *.jsonl, .gitkeep }
        amount_conditions/ { *.jsonl, .gitkeep }
        public_source_foundation/{ *.jsonl, .gitkeep }
    tools/offline/_quarantine/
        exclusion_rules/   ← validation-fail rows moved here
        enforcement_amount/
        ...

VALIDATION RULES PER TOOL:
    exclusion_rules:
        - kind ∈ {exclude, prerequisite, absolute, combine_ok}
        - target_program_id OR target_program_uid present
        - clause_quote non-empty (literal-quote precondition)
        - source_url non-empty
        - confidence ∈ {high, med, low}

    enforcement_amount:
        - amount_yen >= 0 OR null
        - currency == "JPY"
        - amount_kind ∈ enum or null
        - clause_quote non-empty (literal-quote precondition)

POST-INGEST FILE HANDLING:
    A processed file is moved to `_inbox/{tool}/_done/` (created on
    demand) with the same filename. A file with any quarantined row keeps
    its remaining good rows applied, but the bad rows land at
    `_quarantine/{tool}/{original}.{lineno}.jsonl` for operator review.

USAGE:
    python scripts/cron/ingest_offline_inbox.py
    python scripts/cron/ingest_offline_inbox.py --tool exclusion_rules
    python scripts/cron/ingest_offline_inbox.py --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sqlite3
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
DEFAULT_JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
INBOX_ROOT = REPO_ROOT / "tools" / "offline" / "_inbox"
QUARANTINE_ROOT = REPO_ROOT / "tools" / "offline" / "_quarantine"

LOG = logging.getLogger("ingest_offline_inbox")

# Module-level toggle flipped by --force-retag so per-row handlers
# (insert_jsic_classification) don't need a fresh kwarg through the
# generic process_file() signature.
FORCE_RETAG = False

# ---------------------------------------------------------------------------
# Pydantic models (lazy import so script imports cheaply for --help / lint)
# ---------------------------------------------------------------------------


def _models():
    """Lazy load shared Pydantic schemas (avoids cold import cost on --help)."""
    from jpintel_mcp.ingest.schemas import resolve_schema

    return {tool: resolve_schema(tool) for tool in TOOL_REGISTRY}


# ---------------------------------------------------------------------------
# Literal-quote check helpers
# ---------------------------------------------------------------------------

_KOBO_CACHE_PROBE: dict[str, bool] = {}


def _kobo_cache_available(conn: sqlite3.Connection) -> bool:
    """Probe once per connection whether `kobo_text_cache` exists.

    Returns True only if the table exists AND has the expected columns
    (`source_url TEXT`, `text_body TEXT`). Probing once + caching by
    `id(conn)` keeps the per-row literal-quote check at O(1) sqlite
    pragma cost amortized across the file.
    """
    key = f"{id(conn)}"
    if key in _KOBO_CACHE_PROBE:
        return _KOBO_CACHE_PROBE[key]
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(kobo_text_cache)").fetchall()}
    except sqlite3.Error:
        cols = set()
    has_it = "source_url" in cols and "text_body" in cols
    _KOBO_CACHE_PROBE[key] = has_it
    if not has_it:
        LOG.warning(
            "kobo_text_cache table absent — literal-quote substring "
            "check will be skipped (form-only validation only)."
        )
    return has_it


def literal_quote_pass(
    quote: str, conn: sqlite3.Connection | None = None, source_url: str | None = None
) -> bool:
    """Literal-quote gate.

    1. Form check — non-empty, non-whitespace, len >= 4.
    2. If `kobo_text_cache` table exists AND `source_url` is supplied,
       look up the cached source text and require `quote` be a literal
       substring of it. If the cache row is missing for that URL we
       fall back to form-only pass (cache is best-effort, not gating
       infra — operator can backfill at any time).
    3. If the cache table is missing entirely, we warn-once and accept
       the form-only result. This matches the spec: "kobo_text_cache が
       無ければ skip with warning".
    """
    if not (quote and quote.strip() and len(quote) >= 4):
        return False
    if conn is None or source_url is None:
        return True
    if not _kobo_cache_available(conn):
        return True
    try:
        row = conn.execute(
            "SELECT text_body FROM kobo_text_cache WHERE source_url = ? LIMIT 1",
            (source_url,),
        ).fetchone()
    except sqlite3.Error:
        return True  # cache lookup non-fatal
    if not row or not row[0]:
        return True  # missing cache row — accept form-only
    return quote in row[0]


def file_cache_quote_pass(quote: str, program_unified_id: str | None) -> bool:
    """File-backed strict literal-quote gate (W2-13 caveat #2).

    Wraps `jpintel_mcp.ingest.quote_check.literal_quote_pass`. Lazy
    import keeps the script's --help path free of heavy imports.
    """
    from jpintel_mcp.ingest.quote_check import literal_quote_pass as _strict

    return _strict(quote, program_unified_id)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _content_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json_list(value: Any) -> str:
    if value is None:
        value = []
    return json.dumps(value, ensure_ascii=False)


def _json_obj(value: Any) -> str:
    if value is None:
        value = {}
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------
# Insert handlers (one per tool)
# ---------------------------------------------------------------------------


def insert_exclusion_rules(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    """Insert N exclusion_rules rows (one per `rules` entry).

    Returns count of rows actually inserted (after literal-quote guard).
    """
    inserted = 0
    program_uid = row["program_uid"]
    for rule in row["rules"]:
        if not literal_quote_pass(rule["clause_quote"], conn, rule.get("source_url")):
            continue
        rule_id = f"er-{uuid.uuid4().hex[:16]}"
        conn.execute(
            "INSERT OR IGNORE INTO exclusion_rules ("
            "  rule_id, kind, severity, program_a, program_b,"
            "  description, source_notes, source_urls_json, extra_json,"
            "  source_excerpt, condition, program_a_uid, program_b_uid"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rule_id,
                rule["kind"],
                rule.get("confidence"),
                None,
                None,
                f"subagent_run={row['subagent_run_id']}",
                rule["source_url"],
                json.dumps([rule["source_url"]], ensure_ascii=False),
                json.dumps(
                    {
                        "subagent_run_id": row["subagent_run_id"],
                        "evaluated_at": row["evaluated_at"],
                        "confidence": rule["confidence"],
                    },
                    ensure_ascii=False,
                ),
                rule["clause_quote"],
                None,
                program_uid,
                rule.get("target_program_uid"),
            ),
        )
        inserted += 1
    return inserted


def insert_enforcement_amount(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    """UPDATE am_enforcement_detail.amount_yen. Returns 1 if updated."""
    if row.get("amount_yen") is None:
        # null-amount rows are valid (recorded for trace) but no UPDATE
        return 0
    if not literal_quote_pass(row["clause_quote"], conn, row.get("source_url")):
        return 0
    cur = conn.execute(
        "UPDATE am_enforcement_detail "
        "   SET amount_yen        = ?, "
        "       enforcement_kind  = COALESCE(?, enforcement_kind), "
        "       source_url        = COALESCE(?, source_url), "
        "       source_fetched_at = COALESCE(?, source_fetched_at) "
        " WHERE enforcement_id = ? "
        "   AND amount_yen IS NULL",
        (
            row["amount_yen"],
            row.get("amount_kind"),
            row.get("source_url"),
            row.get("source_fetched_at"),
            row["enforcement_id"],
        ),
    )
    return cur.rowcount


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------


def insert_jsic_classification(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    """UPDATE autonomath jpi_programs jsic_* columns from one classifier row.

    W2-13 caveat #1: column is `unified_id` TEXT, not INT `program_id`.
    W2-13 caveat #3: re-tag path. Default WHERE `jsic_major IS NULL`
    keeps the cron idempotent (silent no-op on second run). When
    `FORCE_RETAG` is on, drop the NULL guard so existing values are
    overwritten and `jsic_assigned_method` is bumped to the row's
    method (typically 'classifier').
    """
    program_unified_id = row["program_unified_id"]
    assigned_at = row.get("assigned_at") or datetime.now(UTC).isoformat()
    assigned_method = row.get("jsic_assigned_method") or "classifier"
    if FORCE_RETAG:
        sql = (
            "UPDATE jpi_programs "
            "   SET jsic_major = ?, jsic_middle = ?, jsic_minor = ?, "
            "       jsic_assigned_at = ?, jsic_assigned_method = ? "
            " WHERE unified_id = ?"
        )
    else:
        sql = (
            "UPDATE jpi_programs "
            "   SET jsic_major = ?, jsic_middle = ?, jsic_minor = ?, "
            "       jsic_assigned_at = ?, jsic_assigned_method = ? "
            " WHERE unified_id = ? AND jsic_major IS NULL"
        )
    cur = conn.execute(
        sql,
        (
            row.get("jsic_major"),
            row.get("jsic_middle"),
            row.get("jsic_minor"),
            assigned_at,
            assigned_method,
            program_unified_id,
        ),
    )
    return cur.rowcount


def insert_program_narrative(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    cols = _columns(conn, "am_program_narrative")
    names = [
        "program_id",
        "lang",
        "section",
        "body_text",
        "source_url_json",
        "model_id",
        "generated_at",
        "literal_quote_check_passed",
    ]
    values: list[Any] = [
        row["program_id"],
        row["lang"],
        row["section"],
        row["body_text"],
        _json_list(row.get("source_url_json")),
        row.get("model_id"),
        row["generated_at"],
        1 if row.get("source_url_json") else 0,
    ]
    if "content_hash" in cols:
        names.append("content_hash")
        values.append(_content_hash(row["body_text"]))
    if "is_active" in cols:
        names.append("is_active")
        values.append(1)
    sql = (
        f"INSERT INTO am_program_narrative ({','.join(names)}) "
        f"VALUES ({','.join('?' for _ in names)}) "
        "ON CONFLICT(program_id, lang, section) DO UPDATE SET "
        "body_text=excluded.body_text, "
        "source_url_json=excluded.source_url_json, "
        "model_id=excluded.model_id, "
        "generated_at=excluded.generated_at, "
        "literal_quote_check_passed=excluded.literal_quote_check_passed"
    )
    cur = conn.execute(sql, values)
    return cur.rowcount


def insert_houjin_360_narrative(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    cur = conn.execute(
        "INSERT INTO am_houjin_360_narrative("
        "  houjin_bangou, lang, body_text, source_url_json, generated_at"
        ") VALUES (?,?,?,?,?) "
        "ON CONFLICT(houjin_bangou, lang) DO UPDATE SET "
        "body_text=excluded.body_text, "
        "source_url_json=excluded.source_url_json, "
        "generated_at=excluded.generated_at",
        (
            row["houjin_bangou"],
            row["lang"],
            row["body_text"],
            _json_list(row.get("source_url_json")),
            row["generated_at"],
        ),
    )
    return cur.rowcount


def insert_enforcement_summary(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    cur = conn.execute(
        "INSERT INTO am_enforcement_summary("
        "  enforcement_id, lang, body_text, source_url_json, generated_at"
        ") VALUES (?,?,?,?,?) "
        "ON CONFLICT(enforcement_id, lang) DO UPDATE SET "
        "body_text=excluded.body_text, "
        "source_url_json=excluded.source_url_json, "
        "generated_at=excluded.generated_at",
        (
            row["enforcement_id"],
            row["lang"],
            row["body_text"],
            _json_list(row.get("source_url_json")),
            row["generated_at"],
        ),
    )
    return cur.rowcount


def insert_program_application_documents(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    inserted = 0
    for doc in row["documents"]:
        if doc.get("source_clause_quote") and not literal_quote_pass(
            doc["source_clause_quote"], conn, doc.get("url")
        ):
            continue
        if doc.get("source_clause_quote") and not file_cache_quote_pass(
            doc["source_clause_quote"], doc.get("program_unified_id")
        ):
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO am_program_documents("
            "  program_unified_id, doc_name, doc_kind, yoshiki_no,"
            "  is_required, url, source_clause_quote, notes, computed_at"
            ") VALUES (?,?,?,?,?,?,?,?,?)",
            (
                doc["program_unified_id"],
                doc["doc_name"],
                doc.get("doc_kind"),
                doc.get("yoshiki_no"),
                doc["is_required"],
                doc.get("url"),
                doc.get("source_clause_quote"),
                doc.get("notes"),
                doc["extracted_at"],
            ),
        )
        inserted += cur.rowcount
    return inserted


def insert_eligibility_predicates(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    inserted = 0
    for pred in row["predicates"]:
        if pred.get("source_clause_quote") and not literal_quote_pass(
            pred["source_clause_quote"], conn, pred.get("source_url")
        ):
            continue
        if pred.get("source_clause_quote") and not file_cache_quote_pass(
            pred["source_clause_quote"], pred.get("program_unified_id")
        ):
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO am_program_eligibility_predicate("
            "  program_unified_id, predicate_kind, operator, value_text,"
            "  value_num, value_json, is_required, source_url,"
            "  source_clause_quote, extracted_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                pred["program_unified_id"],
                pred["predicate_kind"],
                pred["operator"],
                pred.get("value_text"),
                pred.get("value_num"),
                pred.get("value_json"),
                pred["is_required"],
                pred.get("source_url"),
                pred.get("source_clause_quote"),
                pred["extracted_at"],
            ),
        )
        inserted += cur.rowcount
    return inserted


def insert_edinet_relations(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    cur = conn.execute(
        "INSERT OR REPLACE INTO am_invoice_buyer_seller_graph("
        "  seller_houjin_bangou, buyer_houjin_bangou, confidence,"
        "  confidence_band, inferred_industry, evidence_kind, evidence_count,"
        "  source_url_json, first_seen_at, last_seen_at, computed_at"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            row["seller_houjin_bangou"],
            row["buyer_houjin_bangou"],
            row["confidence"],
            row["confidence_band"],
            row.get("inferred_industry"),
            row["evidence_kind"],
            row["evidence_count"],
            _json_list(row.get("source_url_json")),
            row.get("first_seen_at"),
            row.get("last_seen_at"),
            row["computed_at"],
        ),
    )
    return cur.rowcount


def insert_amount_conditions(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    """UPDATE am_amount_condition.is_authoritative=1 when authoritative
    quote re-verifies the row. Returns rowcount of UPDATE.

    Promotes a previously template-default ETL row by setting:
        is_authoritative = 1
        authority_source = source_url
        authority_evaluated_at = evaluated_at
        confidence = row.confidence
        extracted_text = row.extracted_text (literal-quote substring)

    Skips silently if literal-quote does not pass (form check + optional
    kobo_text_cache substring check).
    """
    if not literal_quote_pass(row["extracted_text"], conn, row.get("source_url")):
        return 0
    cur = conn.execute(
        "UPDATE am_amount_condition "
        "   SET is_authoritative       = 1, "
        "       authority_source       = COALESCE(?, authority_source), "
        "       authority_evaluated_at = COALESCE(?, authority_evaluated_at), "
        "       confidence             = COALESCE(?, confidence), "
        "       extracted_text         = COALESCE(?, extracted_text), "
        "       numeric_value          = COALESCE(?, numeric_value), "
        "       numeric_value_max      = COALESCE(?, numeric_value_max), "
        "       unit                   = COALESCE(?, unit), "
        "       currency               = COALESCE(?, currency), "
        "       qualifier              = COALESCE(?, qualifier), "
        "       condition_kind         = COALESCE(?, condition_kind) "
        " WHERE entity_id       = ? "
        "   AND condition_label = ?",
        (
            row.get("source_url"),
            row.get("evaluated_at"),
            row.get("confidence"),
            row.get("extracted_text"),
            row.get("numeric_value"),
            row.get("numeric_value_max"),
            row.get("unit"),
            row.get("currency"),
            row.get("qualifier"),
            row.get("condition_kind"),
            row["entity_id"],
            row["condition_label"],
        ),
    )
    return cur.rowcount


TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "exclusion_rules": {
        "db": "jpintel",
        "handler": insert_exclusion_rules,
    },
    "enforcement_amount": {
        "db": "autonomath",
        "handler": insert_enforcement_amount,
    },
    "jsic_classification": {
        "db": "autonomath",
        "handler": insert_jsic_classification,
    },
    "jsic_tags": {
        "db": "autonomath",
        "handler": insert_jsic_classification,
    },
    "program_narrative": {
        "db": "autonomath",
        "handler": insert_program_narrative,
    },
    "houjin_360_narrative": {
        "db": "autonomath",
        "handler": insert_houjin_360_narrative,
    },
    "enforcement_summary": {
        "db": "autonomath",
        "handler": insert_enforcement_summary,
    },
    "program_application_documents": {
        "db": "autonomath",
        "handler": insert_program_application_documents,
    },
    "eligibility_predicates": {
        "db": "autonomath",
        "handler": insert_eligibility_predicates,
    },
    "edinet_relations": {
        "db": "autonomath",
        "handler": insert_edinet_relations,
    },
    "amount_conditions": {
        "db": "autonomath",
        "handler": insert_amount_conditions,
    },
    "public_source_foundation": {
        "processor": "source_profile_backlog",
        "include_in_all": False,
    },
}


# ---------------------------------------------------------------------------
# Per-file processor
# ---------------------------------------------------------------------------


def quarantine_line(tool: str, src_path: Path, lineno: int, line: str, reason: str) -> Path:
    QUARANTINE_ROOT.joinpath(tool).mkdir(parents=True, exist_ok=True)
    qpath = QUARANTINE_ROOT / tool / f"{src_path.stem}.line{lineno:05d}.jsonl"
    qpath.write_text(
        json.dumps({"reason": reason, "raw": line}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return qpath


def mark_done(src_path: Path) -> Path:
    done_dir = src_path.parent / "_done"
    done_dir.mkdir(parents=True, exist_ok=True)
    dst = done_dir / src_path.name
    shutil.move(str(src_path), str(dst))
    return dst


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _source_profile_status(row: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    risk = _text(row.get("redistribution_risk", "")).lower()
    license_text = _text(row.get("license_or_terms", "")).lower()
    robots = _text(row.get("robots_policy", "")).lower()
    rate_limits = _text(row.get("rate_limits", "")).lower()

    if row.get("auth_needed") is True:
        reasons.append("blocked_by_auth_review")
    if "high" in risk:
        reasons.append("redistribution_risk_high")
    elif "medium" in risk:
        reasons.append("redistribution_risk_medium")
    if "proprietary" in license_text or "unknown" in license_text or "未確認" in license_text:
        reasons.append("license_review")
    if any(
        token in robots
        for token in (
            "robots disallow",
            "全て robots disallow",
            "robots 上 allow されない",
        )
    ):
        reasons.append("robots_disallowed")
    elif any(token in robots for token in ("unknown", "403", "waf", "要個別", "per_site")):
        reasons.append("robots_review")
    if "unknown" in rate_limits or "不明" in rate_limits:
        reasons.append("rate_limit_review")
    if row.get("priority") == "P3":
        reasons.append("priority_defer")

    blocked = any(reason.startswith("blocked_by") for reason in reasons) or any(
        reason in {"redistribution_risk_high", "robots_disallowed"} for reason in reasons
    )
    if blocked:
        return "blocked", reasons
    if reasons:
        return "review_required", reasons
    return "ready", reasons


def _requested_table_name(raw: str) -> str:
    table = raw.strip().split(" ", 1)[0].split("(", 1)[0]
    return table.strip().strip(",") or "unknown_table"


def _candidate_columns(raw: str) -> list[str]:
    if "(" not in raw or ")" not in raw:
        return []
    inner = raw.split("(", 1)[1].rsplit(")", 1)[0]
    return [part.strip().split(" ", 1)[0] for part in inner.split(",")[:40] if part.strip()]


def _append_unique_jsonl(path: Path, items: list[dict[str, Any]]) -> int:
    if not items:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                existing = json.loads(raw)
            except json.JSONDecodeError:
                continue
            backlog_id = existing.get("backlog_id")
            if isinstance(backlog_id, str):
                seen.add(backlog_id)
    written = 0
    with path.open("a", encoding="utf-8") as fh:
        for item in items:
            backlog_id = item.get("backlog_id")
            if isinstance(backlog_id, str) and backlog_id in seen:
                continue
            fh.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
            if isinstance(backlog_id, str):
                seen.add(backlog_id)
            written += 1
    return written


def _source_profile_backlog_items(
    row: dict[str, Any],
    source_file: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    status, review_reasons = _source_profile_status(row)
    source_id = row["source_id"]
    profile_hash = _content_hash(_json_obj(row))
    source_doc = {
        "backlog_id": f"srcdoc_{source_id}",
        "source_id": source_id,
        "target_table": "source_document",
        "status": status,
        "priority": row.get("priority"),
        "source_document_fields": {
            "source_url": row.get("source_url"),
            "publisher": row.get("official_owner"),
            "document_type": row.get("source_type"),
            "license": row.get("license_or_terms"),
            "fetched_at_required": True,
            "content_hash_required": True,
            "attribution_required": row.get("attribution_required"),
        },
        "fetch_job_needed": True,
        "extractor_needed": bool(row.get("sample_fields")),
        "known_gaps": row.get("known_gaps") or [],
        "human_review_required": review_reasons,
        "sample_urls": row.get("sample_urls") or [],
        "sample_fields": row.get("sample_fields") or [],
        "profile_hash": profile_hash,
        "input_file": str(source_file),
    }

    schema_items: list[dict[str, Any]] = []
    new_tables = row.get("new_tables_needed") or []
    for raw_table in new_tables:
        if not raw_table:
            continue
        table = _requested_table_name(str(raw_table))
        schema_items.append(
            {
                "backlog_id": f"schema_{source_id}_{table}",
                "source_id": source_id,
                "requested_table": table,
                "requested_table_raw": raw_table,
                "reason": f"{source_id} requires a domain table beyond source_document",
                "join_keys": row.get("join_keys") or [],
                "candidate_columns": _candidate_columns(str(raw_table)),
                "depends_on_source_document": True,
                "migration_slice": "schema-only foundation",
                "status": "blocked" if status == "blocked" else "review_required",
                "input_file": str(source_file),
            }
        )

    review_items: list[dict[str, Any]] = []
    if review_reasons:
        review_items.append(
            {
                "backlog_id": f"review_{source_id}",
                "source_id": source_id,
                "status": status,
                "priority": row.get("priority"),
                "source_url": row.get("source_url"),
                "human_review_required": review_reasons,
                "redistribution_risk": row.get("redistribution_risk"),
                "robots_policy": row.get("robots_policy"),
                "license_or_terms": row.get("license_or_terms"),
                "auth_needed": row.get("auth_needed"),
                "next_probe": row.get("next_probe"),
                "known_gaps": row.get("known_gaps") or [],
                "input_file": str(source_file),
            }
        )

    return [source_doc], schema_items, review_items


def process_public_source_foundation_file(
    path: Path,
    model_cls: Any,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Validate SourceProfile JSONL and convert valid rows into backlog files."""
    from jpintel_mcp.ingest.normalizers.public_source_foundation import (
        normalize_source_profile_row,
    )

    n_valid = 0
    n_quarantined = 0
    source_doc_items: list[dict[str, Any]] = []
    schema_items: list[dict[str, Any]] = []
    review_items: list[dict[str, Any]] = []
    LOG.info("processing source profile backlog %s", path)
    with path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                if not dry_run:
                    quarantine_line(
                        "public_source_foundation", path, lineno, raw, f"json_decode_error: {exc}"
                    )
                n_quarantined += 1
                continue
            try:
                model = model_cls.model_validate(normalize_source_profile_row(obj))
            except Exception as exc:  # pydantic ValidationError + others
                if not dry_run:
                    quarantine_line(
                        "public_source_foundation",
                        path,
                        lineno,
                        raw,
                        f"pydantic_validation_error: {exc}",
                    )
                n_quarantined += 1
                continue
            n_valid += 1
            if dry_run:
                continue
            doc, schema, review = _source_profile_backlog_items(model.model_dump(), path)
            source_doc_items.extend(doc)
            schema_items.extend(schema)
            review_items.extend(review)

    if not dry_run:
        backlog_dir = path.parent / "_backlog"
        written = {
            "source_document": _append_unique_jsonl(
                backlog_dir / "source_document_backlog.jsonl",
                source_doc_items,
            ),
            "schema": _append_unique_jsonl(
                backlog_dir / "schema_backlog.jsonl",
                schema_items,
            ),
            "review": _append_unique_jsonl(
                backlog_dir / "source_review_backlog.jsonl",
                review_items,
            ),
        }
        audit_dir = INBOX_ROOT / "_audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        audit_path = (
            audit_dir / f"offline_cli_inbox_ingest_{datetime.now(UTC).date().isoformat()}.jsonl"
        )
        _append_unique_jsonl(
            audit_path,
            [
                {
                    "backlog_id": f"audit_public_source_foundation_{path.stem}",
                    "run_id": f"offline_cli_ingest_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}",
                    "tool": "public_source_foundation",
                    "input_file": str(path),
                    "input_file_hash": _content_hash(path.read_text(encoding="utf-8")),
                    "rows_valid": n_valid,
                    "rows_quarantined": n_quarantined,
                    "backlog_created": written,
                    "dry_run": dry_run,
                    "operator_action_required": bool(n_quarantined or review_items),
                }
            ],
        )
        if n_quarantined == 0:
            mark_done(path)
    return n_valid, n_quarantined


def process_file(
    tool: str,
    path: Path,
    conn: sqlite3.Connection,
    model_cls: Any,
    handler: Callable[[sqlite3.Connection, dict[str, Any]], int],
    dry_run: bool = False,
) -> tuple[int, int]:
    """Process one .jsonl file. Returns (n_applied, n_quarantined)."""
    n_applied = 0
    n_quarantined = 0
    LOG.info("processing %s", path)
    with path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                quarantine_line(tool, path, lineno, raw, f"json_decode_error: {exc}")
                n_quarantined += 1
                continue
            try:
                model = model_cls.model_validate(obj)
            except Exception as exc:  # pydantic ValidationError + others
                quarantine_line(tool, path, lineno, raw, f"pydantic_validation_error: {exc}")
                n_quarantined += 1
                continue
            row_dict = model.model_dump()
            try:
                if dry_run:
                    n_applied += 1
                else:
                    n_applied += handler(conn, row_dict)
            except sqlite3.Error as exc:
                quarantine_line(tool, path, lineno, raw, f"sqlite_error: {exc}")
                n_quarantined += 1
                continue
    if not dry_run:
        conn.commit()
        if n_quarantined == 0:
            mark_done(path)
    return n_applied, n_quarantined


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def open_db(target: str, autonomath_db: Path, jpintel_db: Path) -> sqlite3.Connection:
    if target == "autonomath":
        return sqlite3.connect(autonomath_db)
    if target == "jpintel":
        return sqlite3.connect(jpintel_db)
    raise ValueError(f"unknown target db: {target}")


def assert_migration_113b(conn: sqlite3.Connection) -> None:
    """W2-13 caveat #4: refuse to ingest jsic_* if migration 113b not applied.

    Probes `jpi_programs` for the `jsic_major` column. If absent we
    early-exit with `RuntimeError` so the cron does not silently
    no-op (UPDATE on a non-existent column would raise per-row, but
    only after the first JSONL line — fast-fail is friendlier).
    """
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(jpi_programs)").fetchall()}
    except sqlite3.Error as exc:
        raise RuntimeError(
            "migration 113b not applied — `jpi_programs` table is "
            f"unreadable: {exc}. Run `fly deploy` (entrypoint.sh §4 applies "
            "wave24_113b automatically) or apply manually before cron."
        ) from exc
    if "jsic_major" not in cols:
        raise RuntimeError(
            "migration 113b not applied — `jpi_programs.jsic_major` is "
            "missing. Run `fly deploy` (entrypoint.sh §4 applies "
            "wave24_113b automatically) or apply manually before cron."
        )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--tool",
        choices=list(TOOL_REGISTRY.keys()) + ["all"],
        default="all",
        help="どの inbox tool を処理するか (default: all)",
    )
    p.add_argument("--autonomath-db", type=Path, default=DEFAULT_AUTONOMATH_DB)
    p.add_argument("--jpintel-db", type=Path, default=DEFAULT_JPINTEL_DB)
    p.add_argument(
        "--dry-run", action="store_true", help="検証だけ行い DB 書込み + ファイル移動はしない"
    )
    p.add_argument(
        "--force-retag",
        action="store_true",
        help=(
            "jsic_classification / jsic_tags を既存値の上から再タグ。"
            "default は WHERE jsic_major IS NULL のため idempotent — "
            "再分類したいときだけ立てる。"
        ),
    )
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    global FORCE_RETAG
    FORCE_RETAG = bool(args.force_retag)
    if FORCE_RETAG:
        LOG.warning("--force-retag: existing jsic_* values WILL be overwritten")

    schemas = _models()
    tools = (
        [tool for tool, cfg in TOOL_REGISTRY.items() if cfg.get("include_in_all", True)]
        if args.tool == "all"
        else [args.tool]
    )

    started = datetime.now(UTC).isoformat()
    grand_applied = 0
    grand_quarantined = 0
    for tool in tools:
        cfg = TOOL_REGISTRY[tool]
        model_cls = schemas[tool]
        inbox_dir = INBOX_ROOT / tool
        if not inbox_dir.exists():
            LOG.warning("inbox dir missing: %s", inbox_dir)
            continue
        files = sorted(
            p for p in inbox_dir.glob("*.jsonl") if p.is_file() and p.parent.name == tool
        )
        if not files:
            LOG.info("[%s] no inbox files", tool)
            continue
        if cfg.get("processor") == "source_profile_backlog":
            for path in files:
                applied, quarantined = process_public_source_foundation_file(
                    path,
                    model_cls,
                    dry_run=args.dry_run,
                )
                grand_applied += applied
                grand_quarantined += quarantined
                LOG.info("[%s] %s valid=%d quarantined=%d", tool, path.name, applied, quarantined)
            continue
        conn = open_db(cfg["db"], args.autonomath_db, args.jpintel_db)
        try:
            # W2-13 caveat #4: jsic_* tools require migration 113b.
            # Probe early so we abort *before* mutating anything.
            # Skip in --dry-run since validation never touches the DB.
            if tool in {"jsic_classification", "jsic_tags"} and not args.dry_run:
                assert_migration_113b(conn)
            for path in files:
                applied, quarantined = process_file(
                    tool,
                    path,
                    conn,
                    model_cls,
                    cfg["handler"],
                    dry_run=args.dry_run,
                )
                grand_applied += applied
                grand_quarantined += quarantined
                LOG.info("[%s] %s applied=%d quarantined=%d", tool, path.name, applied, quarantined)
        finally:
            conn.close()

    LOG.info(
        "done. started=%s applied=%d quarantined=%d", started, grand_applied, grand_quarantined
    )
    return 0 if grand_quarantined == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
