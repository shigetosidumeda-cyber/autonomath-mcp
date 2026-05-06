#!/usr/bin/env python3
"""W30 follow-up: pre-compute composite output for the W30-2/3/4 endpoints.

What it does:
  Pre-computes the composite envelope returned by the W30-2 (program 360),
  W30-3 (houjin 360), and W30-4 (profile match) endpoints for the heaviest
  subjects, then writes one row per (subject_kind, subject_id) into
  am_actionable_answer_cache (migration 168). The endpoint hot path then
  returns the cached JSON verbatim instead of re-running the 5-7 way join.

Why precompute:
  The composite envelope is a deterministic function of the corpus
  snapshot. For the top S/A tier programs, the high-verification houjin
  rows, and the popular profile match shapes, the same 5-7 way join is
  re-executed on every request. Pre-warming flips that to a single
  primary-key SELECT against am_actionable_answer_cache.

Selection:
  * subject_kind='program' — top 100 jpi_programs WHERE excluded=0 AND
    tier IN ('S','A'), ordered by tier ASC then unified_id (stable).
  * subject_kind='houjin'  — top 100 corporate entities by adoption
    verification count >= 3 (jpi_adoption_records GROUP BY houjin_bangou),
    ordered by adoption count DESC then bangou (stable).
  * subject_kind='match'   — top 100 am_profile_match rows ordered by
    total_match_count DESC then profile_hash (stable).

Constraints:
  * No Anthropic / claude / SDK calls. Pure SQLite + standard library.
  * Read-only on autonomath.db for source rows; the cache table itself
    is opened with a separate write connection (single-table writes).
  * Idempotent — INSERT OR REPLACE on (subject_kind, subject_id).

Usage:
    python scripts/cron/precompute_actionable_cache.py            # full run
    python scripts/cron/precompute_actionable_cache.py --dry-run  # log only
    python scripts/cron/precompute_actionable_cache.py --top 50
    python scripts/cron/precompute_actionable_cache.py --kind program
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("autonomath.cron.precompute_actionable_cache")

DEFAULT_TOP_N = 100
SUBJECT_KINDS = ("program", "houjin", "match")

# §52 disclaimer (mirrored from api/houjin.py / api/programs.py — populator
# stamps it into the cached envelope so the cache hit returns identical bytes
# to the on-demand path).
_DISCLAIMER = (
    "本情報は税務助言ではありません。jpcite は公的機関 (gBizINFO・国税庁・"
    "会計検査院 等) が公表する企業情報を検索・整理して提供するサービスで、"
    "税理士法 §52 に基づき個別具体的な税務判断・与信判断は行いません。"
    "個別案件は資格を有する税理士・公認会計士に必ずご相談ください。"
)
_NAMAYOKE_CAVEAT = (
    "本データは公開情報の名寄せ結果です。法人番号は一意ですが、商号変更・合併・"
    "事業譲渡 等のイベント前後では同一番号の下に異なる時点の情報が混在する場合"
    "があります。最新の登記情報は法務局・gBizINFO 一次サイトでご確認ください。"
)

_MAX_FACTS = 50
_MAX_RECENT_ADOPTIONS = 5
_MAX_RECENT_ENFORCEMENTS = 5
_AMOUNT_CONDITION_UNVERIFIED_GAP = "unverified_amount_conditions_excluded"
_AMOUNT_CONDITION_TIER_MISSING_GAP = "amount_condition_quality_tier_missing"


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #


def _configure_logging(verbose: bool = False) -> None:
    root = logging.getLogger("autonomath.cron.precompute_actionable_cache")
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


def _autonomath_db_path() -> Path:
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    # Match production layout: repo-root /autonomath.db. The
    # data/autonomath.db placeholder is 0 bytes per CLAUDE.md.
    return Path(__file__).resolve().parents[2] / "autonomath.db"


def _open_autonomath_rw(db_path: Path) -> sqlite3.Connection:
    """Open a writable connection. We INSERT OR REPLACE into one table only —
    the rest of the script never writes outside am_actionable_answer_cache.
    """
    conn = sqlite3.connect(str(db_path), timeout=15.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-65536")
    except sqlite3.OperationalError:
        pass
    return conn


def _compute_corpus_snapshot_id(conn: sqlite3.Connection) -> str:
    """Stable corpus snapshot id for cache invalidation.

    Cheap heuristic: latest am_amendment_diff.detected_at when present,
    else MAX(fetched_at) across am_entities. Falls back to today's UTC date
    so the populator always stamps a deterministic value.
    """
    try:
        row = conn.execute("SELECT MAX(detected_at) FROM am_amendment_diff").fetchone()
        if row and row[0]:
            return str(row[0])
    except sqlite3.OperationalError:
        pass
    try:
        row = conn.execute("SELECT MAX(fetched_at) FROM am_entities").fetchone()
        if row and row[0]:
            return str(row[0])
    except sqlite3.OperationalError:
        pass
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load_verified_amount_conditions(
    conn: sqlite3.Connection, program_entity_id: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return only customer-safe amount conditions plus any omission gap codes."""
    amount_conditions: list[dict[str, Any]] = []
    known_gaps: list[str] = []
    try:
        rows = conn.execute(
            """SELECT condition_label, percentage, fixed_yen,
                      rate_range_low, rate_range_high
                 FROM am_amount_condition
                WHERE entity_id = ?
                  AND quality_tier = 'verified'
                LIMIT 10""",
            (program_entity_id,),
        ).fetchall()
        for r in rows:
            amount_conditions.append(
                {
                    "label": r["condition_label"],
                    "percentage": r["percentage"],
                    "fixed_yen": r["fixed_yen"],
                    "rate_low": r["rate_range_low"],
                    "rate_high": r["rate_range_high"],
                }
            )

        (unverified_count,) = conn.execute(
            """SELECT COUNT(*)
                 FROM am_amount_condition
                WHERE entity_id = ?
                  AND COALESCE(quality_tier, 'unknown') != 'verified'""",
            (program_entity_id,),
        ).fetchone()
        if int(unverified_count or 0) > 0:
            known_gaps.append(_AMOUNT_CONDITION_UNVERIFIED_GAP)
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        if "quality_tier" in message:
            known_gaps.append(_AMOUNT_CONDITION_TIER_MISSING_GAP)
        elif "am_amount_condition" not in message:
            logger.warning("am_amount_condition verified gate failed: %s", exc)
    return amount_conditions, known_gaps


# --------------------------------------------------------------------------- #
# Composer: program 360 (W30-2)
# --------------------------------------------------------------------------- #


def _build_program_envelope(
    conn: sqlite3.Connection, unified_id: str, snapshot_id: str
) -> dict[str, Any] | None:
    """Compose the program 360 envelope from jpi_programs + adjuncts.

    Pure SQLite reads; no LLM. Mirrors the on-demand SQL JOIN performed by
    the W30-2 endpoint so a cache hit and a cache miss return the same shape.
    """
    prog = conn.execute(
        """SELECT unified_id, primary_name, tier, authority_level, authority_name,
                  prefecture, municipality, program_kind, official_url,
                  amount_max_man_yen, amount_min_man_yen, subsidy_rate, subsidy_rate_text,
                  trust_level, coverage_score, target_types_json, funding_purpose_json,
                  amount_band, application_window_json, enriched_json,
                  source_mentions_json, source_url, source_fetched_at,
                  source_checksum, updated_at
             FROM jpi_programs
            WHERE unified_id = ?""",
        (unified_id,),
    ).fetchone()
    if prog is None:
        return None

    # Parse JSON columns defensively (NULL / invalid -> None / [] / {}).
    def _j_list(raw: Any) -> list[Any]:
        if not raw:
            return []
        try:
            v = json.loads(raw)
            return v if isinstance(v, list) else []
        except (TypeError, ValueError):
            return []

    def _j_obj(raw: Any) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else {}
        except (TypeError, ValueError):
            return {}

    program_entity_id = f"program:{unified_id}"

    # Application rounds rollup (next + recent past).
    rounds: list[dict[str, Any]] = []
    try:
        for r in conn.execute(
            """SELECT round_label, application_open_date, application_close_date,
                      announced_date, status
                 FROM am_application_round
                WHERE program_entity_id = ?
                ORDER BY COALESCE(application_close_date, application_open_date, '') DESC
                LIMIT 5""",
            (program_entity_id,),
        ).fetchall():
            rounds.append(
                {
                    "round_label": r["round_label"],
                    "open": r["application_open_date"],
                    "close": r["application_close_date"],
                    "announced": r["announced_date"],
                    "status": r["status"],
                }
            )
    except sqlite3.OperationalError:
        rounds = []

    # Amount conditions (subsidy/loan rate matrix) — customer surface only
    # exposes values whose extraction has been explicitly verified.
    amount_conditions, amount_known_gaps = _load_verified_amount_conditions(conn, program_entity_id)

    # Adoption rollup (jpi_adoption_records — soft FK by program_unified_id).
    n_adoptions = 0
    try:
        (n_adoptions,) = conn.execute(
            "SELECT COUNT(*) FROM jpi_adoption_records WHERE program_unified_id = ?",
            (unified_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        n_adoptions = 0

    body: dict[str, Any] = {
        "subject_kind": "program",
        "subject_id": unified_id,
        "basic": {
            "unified_id": prog["unified_id"],
            "primary_name": prog["primary_name"],
            "tier": prog["tier"],
            "authority_level": prog["authority_level"],
            "authority_name": prog["authority_name"],
            "prefecture": prog["prefecture"],
            "municipality": prog["municipality"],
            "program_kind": prog["program_kind"],
            "official_url": prog["official_url"],
        },
        "amounts": {
            "amount_max_man_yen": prog["amount_max_man_yen"],
            "amount_min_man_yen": prog["amount_min_man_yen"],
            "subsidy_rate": prog["subsidy_rate"],
            "subsidy_rate_text": prog["subsidy_rate_text"],
            "amount_band": prog["amount_band"],
            "conditions": amount_conditions,
        },
        "targeting": {
            "target_types": _j_list(prog["target_types_json"]),
            "funding_purpose": _j_list(prog["funding_purpose_json"]),
        },
        "lifecycle": {
            "application_window": _j_obj(prog["application_window_json"]),
            "rounds_recent": rounds,
        },
        "adoption_rollup": {
            "total": int(n_adoptions),
        },
        "enriched": _j_obj(prog["enriched_json"]),
        "source_mentions": _j_obj(prog["source_mentions_json"]),
        "provenance": {
            "source_url": prog["source_url"],
            "source_fetched_at": prog["source_fetched_at"],
            "source_checksum": prog["source_checksum"],
            "updated_at": prog["updated_at"],
            "trust_level": prog["trust_level"],
            "coverage_score": prog["coverage_score"],
        },
        "_disclaimer": _DISCLAIMER,
        "corpus_snapshot_id": snapshot_id,
        "_cache_meta": {
            "precomputed": True,
            "basis_table": "am_actionable_answer_cache",
        },
    }
    if amount_known_gaps:
        body["quality"] = {"known_gaps": amount_known_gaps}
    return body


# --------------------------------------------------------------------------- #
# Composer: houjin 360 (W30-3) — mirrors api/houjin.py::_build_houjin_360
# --------------------------------------------------------------------------- #


def _build_houjin_envelope(
    conn: sqlite3.Connection, bangou: str, snapshot_id: str
) -> dict[str, Any] | None:
    canonical_id = f"houjin:{bangou}"

    entity_row = conn.execute(
        """SELECT canonical_id, primary_name, source_url, fetched_at, confidence
             FROM am_entities
            WHERE canonical_id = ?
              AND record_kind = 'corporate_entity'""",
        (canonical_id,),
    ).fetchone()

    fact_rows = conn.execute(
        """SELECT field_name, field_value_text, field_value_numeric, unit, field_kind
             FROM am_entity_facts
            WHERE entity_id = ?
            ORDER BY field_name
            LIMIT ?""",
        (canonical_id, _MAX_FACTS),
    ).fetchall()

    invoice_row = conn.execute(
        """SELECT invoice_registration_number, registered_date, revoked_date,
                  expired_date, prefecture, registrant_kind
             FROM jpi_invoice_registrants
            WHERE houjin_bangou = ?
            LIMIT 1""",
        (bangou,),
    ).fetchone()

    (n_adoptions,) = conn.execute(
        "SELECT COUNT(*) FROM jpi_adoption_records WHERE houjin_bangou = ?",
        (bangou,),
    ).fetchone()
    recent_adoptions: list[dict[str, Any]] = []
    if n_adoptions:
        for r in conn.execute(
            """SELECT program_name_raw, round_label, announced_at,
                      amount_granted_yen, source_url
                 FROM jpi_adoption_records
                WHERE houjin_bangou = ?
                ORDER BY COALESCE(announced_at, '') DESC
                LIMIT ?""",
            (bangou, _MAX_RECENT_ADOPTIONS),
        ).fetchall():
            recent_adoptions.append(
                {
                    "program_name": r["program_name_raw"],
                    "round_label": r["round_label"],
                    "announced_at": r["announced_at"],
                    "amount_granted_yen": r["amount_granted_yen"],
                    "source_url": r["source_url"],
                }
            )

    n_enforcements = 0
    recent_enforcements: list[dict[str, Any]] = []
    try:
        (n_enforcements,) = conn.execute(
            "SELECT COUNT(*) FROM am_enforcement_detail WHERE houjin_bangou = ?",
            (bangou,),
        ).fetchone()
        if n_enforcements:
            for r in conn.execute(
                """SELECT enforcement_kind, issuing_authority, issuance_date,
                          amount_yen, reason_summary, source_url
                     FROM am_enforcement_detail
                    WHERE houjin_bangou = ?
                    ORDER BY issuance_date DESC
                    LIMIT ?""",
                (bangou, _MAX_RECENT_ENFORCEMENTS),
            ).fetchall():
                recent_enforcements.append(
                    {
                        "enforcement_kind": r["enforcement_kind"],
                        "issuing_authority": r["issuing_authority"],
                        "issuance_date": r["issuance_date"],
                        "amount_yen": r["amount_yen"],
                        "reason_summary": r["reason_summary"],
                        "source_url": r["source_url"],
                    }
                )
    except sqlite3.OperationalError:
        n_enforcements = 0

    if (
        entity_row is None
        and not fact_rows
        and invoice_row is None
        and not n_adoptions
        and not n_enforcements
    ):
        return None

    corp_facts: dict[str, Any] = {}
    fact_count = 0
    for r in fact_rows:
        fname = r["field_name"]
        if fname == "houjin_bangou":
            continue
        value = (
            r["field_value_numeric"]
            if r["field_value_numeric"] is not None
            else r["field_value_text"]
        )
        corp_facts[fname] = {"value": value, "unit": r["unit"], "kind": r["field_kind"]}
        fact_count += 1

    def _pluck(name: str) -> Any:
        f = corp_facts.get(name)
        return f["value"] if f else None

    basic = {
        "houjin_bangou": bangou,
        "name": entity_row["primary_name"] if entity_row else _pluck("corp.legal_name"),
        "name_kana": _pluck("corp.legal_name_kana"),
        "name_en": _pluck("corp.legal_name_en"),
        "address": _pluck("corp.location"),
        "prefecture": _pluck("corp.prefecture"),
        "municipality": _pluck("corp.municipality"),
        "postal_code": _pluck("corp.postal_code"),
        "founded_date": _pluck("corp.date_of_establishment"),
        "representative": _pluck("corp.representative"),
        "company_url": _pluck("corp.company_url"),
        "industry_jsic_major": _pluck("corp.jsic_major"),
        "industry_raw": _pluck("corp.industry_raw"),
        "employee_count": _pluck("corp.employee_count"),
        "capital_yen": _pluck("corp.capital_amount"),
        "business_summary": _pluck("corp.business_summary"),
        "status": _pluck("corp.status"),
    }

    invoice_block: dict[str, Any] | None = None
    if invoice_row is not None:
        invoice_block = {
            "invoice_registration_number": invoice_row["invoice_registration_number"],
            "registered_date": invoice_row["registered_date"],
            "revoked_date": invoice_row["revoked_date"],
            "expired_date": invoice_row["expired_date"],
            "prefecture": invoice_row["prefecture"],
            "registrant_kind": invoice_row["registrant_kind"],
        }

    body: dict[str, Any] = {
        "subject_kind": "houjin",
        "subject_id": bangou,
        "basic": basic,
        "corp_facts": corp_facts,
        "fact_count": fact_count,
        "invoice_registration": invoice_block,
        "adoptions": {
            "total": int(n_adoptions),
            "recent": recent_adoptions,
        },
        "enforcement": {
            "total": int(n_enforcements),
            "recent": recent_enforcements,
        },
        "provenance": {
            "canonical_id": canonical_id,
            "primary_source": entity_row["source_url"] if entity_row else None,
            "fetched_at": entity_row["fetched_at"] if entity_row else None,
            "confidence": entity_row["confidence"] if entity_row else None,
            "data_origin": "gBizINFO + 国税庁適格事業者公表サイト + 会計検査院",
        },
        "_disclaimer": _DISCLAIMER,
        "_namayoke_caveat": _NAMAYOKE_CAVEAT,
        "corpus_snapshot_id": snapshot_id,
        "_cache_meta": {
            "precomputed": True,
            "basis_table": "am_actionable_answer_cache",
        },
    }
    return body


# --------------------------------------------------------------------------- #
# Composer: profile match (W30-4)
# --------------------------------------------------------------------------- #


def _build_match_envelope(
    conn: sqlite3.Connection, profile_hash: str, snapshot_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT profile_hash, industry_jsic, company_size, prefecture_code,
                  purpose, top10_program_ids, top10_scores, total_match_count,
                  reason_summary, generated_at
             FROM am_profile_match
            WHERE profile_hash = ?""",
        (profile_hash,),
    ).fetchone()
    if row is None:
        return None

    try:
        program_ids = json.loads(row["top10_program_ids"]) if row["top10_program_ids"] else []
    except (TypeError, ValueError):
        program_ids = []
    try:
        scores = json.loads(row["top10_scores"]) if row["top10_scores"] else []
    except (TypeError, ValueError):
        scores = []

    # Resolve top10 program names + tiers in one IN-clause SELECT (cap 10).
    program_details: list[dict[str, Any]] = []
    if program_ids:
        ids = [str(pid) for pid in program_ids[:10]]
        placeholders = ",".join("?" for _ in ids)
        try:
            for r in conn.execute(
                f"""SELECT unified_id, primary_name, tier, program_kind,
                          authority_level, prefecture, official_url,
                          amount_max_man_yen
                     FROM jpi_programs
                    WHERE unified_id IN ({placeholders})""",
                ids,
            ).fetchall():
                program_details.append(
                    {
                        "unified_id": r["unified_id"],
                        "primary_name": r["primary_name"],
                        "tier": r["tier"],
                        "program_kind": r["program_kind"],
                        "authority_level": r["authority_level"],
                        "prefecture": r["prefecture"],
                        "official_url": r["official_url"],
                        "amount_max_man_yen": r["amount_max_man_yen"],
                    }
                )
        except sqlite3.OperationalError:
            program_details = []

    # Re-order detail rows to match top10_program_ids ordering.
    by_id = {d["unified_id"]: d for d in program_details}
    ordered = [by_id[pid] for pid in program_ids[:10] if pid in by_id]
    # Pair with scores by index.
    for i, det in enumerate(ordered):
        if i < len(scores):
            det["match_score"] = scores[i]

    body: dict[str, Any] = {
        "subject_kind": "match",
        "subject_id": profile_hash,
        "profile": {
            "profile_hash": row["profile_hash"],
            "industry_jsic": row["industry_jsic"],
            "company_size": row["company_size"],
            "prefecture_code": row["prefecture_code"],
            "purpose": row["purpose"],
        },
        "top_matches": ordered,
        "total_match_count": row["total_match_count"],
        "reason_summary": row["reason_summary"],
        "generated_at": row["generated_at"],
        "_disclaimer": _DISCLAIMER,
        "corpus_snapshot_id": snapshot_id,
        "_cache_meta": {
            "precomputed": True,
            "basis_table": "am_actionable_answer_cache",
        },
    }
    return body


# --------------------------------------------------------------------------- #
# Selectors
# --------------------------------------------------------------------------- #


def _select_top_programs(conn: sqlite3.Connection, top_n: int) -> list[str]:
    rows = conn.execute(
        """SELECT unified_id
             FROM jpi_programs
            WHERE excluded = 0 AND tier IN ('S', 'A')
            ORDER BY tier ASC, unified_id ASC
            LIMIT ?""",
        (top_n,),
    ).fetchall()
    return [r["unified_id"] for r in rows]


def _select_top_houjin(conn: sqlite3.Connection, top_n: int) -> list[str]:
    rows = conn.execute(
        """SELECT houjin_bangou, COUNT(*) AS n
             FROM jpi_adoption_records
            WHERE houjin_bangou IS NOT NULL AND houjin_bangou != ''
            GROUP BY houjin_bangou
            HAVING n >= 3
            ORDER BY n DESC, houjin_bangou ASC
            LIMIT ?""",
        (top_n,),
    ).fetchall()
    return [r["houjin_bangou"] for r in rows]


def _select_top_matches(conn: sqlite3.Connection, top_n: int) -> list[str]:
    try:
        rows = conn.execute(
            """SELECT profile_hash
                 FROM am_profile_match
                ORDER BY COALESCE(total_match_count, 0) DESC, profile_hash ASC
                LIMIT ?""",
            (top_n,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [r["profile_hash"] for r in rows]


# --------------------------------------------------------------------------- #
# Writer
# --------------------------------------------------------------------------- #


def _upsert_cache_row(
    conn: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_id: str,
    body: dict[str, Any],
    snapshot_id: str,
) -> int:
    blob = json.dumps(body, ensure_ascii=False, sort_keys=True)
    conn.execute(
        """INSERT OR REPLACE INTO am_actionable_answer_cache
             (subject_kind, subject_id, output_json, output_byte_size,
              generated_at, corpus_snapshot_id)
           VALUES (?, ?, ?, ?, datetime('now'), ?)""",
        (subject_kind, subject_id, blob, len(blob.encode("utf-8")), snapshot_id),
    )
    return len(blob.encode("utf-8"))


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def run(
    *,
    top_n: int = DEFAULT_TOP_N,
    kinds: tuple[str, ...] = SUBJECT_KINDS,
    dry_run: bool = False,
) -> dict[str, Any]:
    db_path = _autonomath_db_path()
    if not db_path.exists():
        logger.error("autonomath.db not found at %s", db_path)
        return {"ok": False, "reason": "db_missing", "db_path": str(db_path)}

    conn = _open_autonomath_rw(db_path)
    try:
        snapshot_id = _compute_corpus_snapshot_id(conn)
        logger.info("snapshot_id=%s db=%s", snapshot_id, db_path)

        result: dict[str, Any] = {
            "ok": True,
            "snapshot_id": snapshot_id,
            "dry_run": dry_run,
            "kinds": {},
        }

        if "program" in kinds:
            ids = _select_top_programs(conn, top_n)
            logger.info("program: selected %d candidates", len(ids))
            built = 0
            skipped = 0
            total_bytes = 0
            for uid in ids:
                envelope = _build_program_envelope(conn, uid, snapshot_id)
                if envelope is None:
                    skipped += 1
                    continue
                if not dry_run:
                    total_bytes += _upsert_cache_row(
                        conn,
                        subject_kind="program",
                        subject_id=uid,
                        body=envelope,
                        snapshot_id=snapshot_id,
                    )
                else:
                    total_bytes += len(
                        json.dumps(envelope, ensure_ascii=False, sort_keys=True).encode("utf-8")
                    )
                built += 1
            result["kinds"]["program"] = {
                "candidates": len(ids),
                "built": built,
                "skipped": skipped,
                "total_bytes": total_bytes,
            }

        if "houjin" in kinds:
            ids = _select_top_houjin(conn, top_n)
            logger.info("houjin: selected %d candidates", len(ids))
            built = 0
            skipped = 0
            total_bytes = 0
            for bangou in ids:
                envelope = _build_houjin_envelope(conn, bangou, snapshot_id)
                if envelope is None:
                    skipped += 1
                    continue
                if not dry_run:
                    total_bytes += _upsert_cache_row(
                        conn,
                        subject_kind="houjin",
                        subject_id=bangou,
                        body=envelope,
                        snapshot_id=snapshot_id,
                    )
                else:
                    total_bytes += len(
                        json.dumps(envelope, ensure_ascii=False, sort_keys=True).encode("utf-8")
                    )
                built += 1
            result["kinds"]["houjin"] = {
                "candidates": len(ids),
                "built": built,
                "skipped": skipped,
                "total_bytes": total_bytes,
            }

        if "match" in kinds:
            ids = _select_top_matches(conn, top_n)
            logger.info("match: selected %d candidates", len(ids))
            built = 0
            skipped = 0
            total_bytes = 0
            for ph in ids:
                envelope = _build_match_envelope(conn, ph, snapshot_id)
                if envelope is None:
                    skipped += 1
                    continue
                if not dry_run:
                    total_bytes += _upsert_cache_row(
                        conn,
                        subject_kind="match",
                        subject_id=ph,
                        body=envelope,
                        snapshot_id=snapshot_id,
                    )
                else:
                    total_bytes += len(
                        json.dumps(envelope, ensure_ascii=False, sort_keys=True).encode("utf-8")
                    )
                built += 1
            result["kinds"]["match"] = {
                "candidates": len(ids),
                "built": built,
                "skipped": skipped,
                "total_bytes": total_bytes,
            }

        # Final cache row count + size, post-write.
        if not dry_run:
            cnt_row = conn.execute(
                """SELECT subject_kind, COUNT(*) AS n,
                          COALESCE(SUM(output_byte_size), 0) AS bytes_total
                     FROM am_actionable_answer_cache
                    GROUP BY subject_kind"""
            ).fetchall()
            result["cache_state"] = {
                r["subject_kind"]: {"rows": r["n"], "bytes": r["bytes_total"]} for r in cnt_row
            }
            (total_rows,) = conn.execute(
                "SELECT COUNT(*) FROM am_actionable_answer_cache"
            ).fetchone()
            result["cache_total_rows"] = total_rows

        return result
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--top", type=int, default=DEFAULT_TOP_N)
    ap.add_argument(
        "--kind",
        choices=SUBJECT_KINDS,
        action="append",
        default=None,
        help="restrict to one or more subject kinds (default: all 3)",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    _configure_logging(args.verbose)

    kinds = tuple(args.kind) if args.kind else SUBJECT_KINDS
    result = run(top_n=args.top, kinds=kinds, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
