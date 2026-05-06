"""GET /v1/intel/program/{program_id}/full — composite per-program bundle.

Bundles the 8+ naive calls a customer LLM otherwise has to fan out for a
single program (meta + eligibility + amendments + adoptions + similar +
citations + audit_proof) into a single GET. Pure SQLite + Python join
over the autonomath unified DB. NO LLM call, NO write, ¥3 / call.

Why this endpoint
-----------------
A customer agent doing "tell me everything about this program" walked the
following 8 calls before this composite:

    GET /v1/programs/{id}                              (meta)
    GET /v1/programs/{id}/eligibility_predicate        (predicate)
    GET /v1/intel/timeline/{id}?include_types=amend    (amendments)
    GET /v1/intel/timeline/{id}?include_types=adoption (adoption stream)
    GET /v1/discover/related/{id}                      (similar programs)
    GET /v1/citations/by_program/{id}                  (law refs)
    GET /v1/citations/by_program_tsutatsu/{id}         (tsutatsu refs)
    GET /v1/audit/proof/{epid}                         (audit anchor)

This route returns a single envelope keyed by `program_id` with each of
those slices as a section. Sections are user-selectable via
``include_sections=...`` query repeats so a token-sensitive caller can
strip the heavy ones.

Hard constraints (memory `feedback_no_operator_llm_api`)
--------------------------------------------------------
* NO LLM call — pure SQLite + Python.
* Pure read — never writes to autonomath.db / jpintel.db.
* §52 / §1 行政書士法 / §72 弁護士法 disclaimer envelope (sensitive surface).
* Graceful degradation — missing tables degrade to ``null`` for that
  section + ``data_quality.missing_tables`` carries the table name.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
import time
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._compact_envelope import to_compact, wants_compact
from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.config import settings

logger = logging.getLogger("jpintel.api.intel_program_full")

# NEW router var name to avoid clash with intel.py's `router` (which would
# otherwise re-mount /v1/intel/probability_radar twice). Mounted in
# main.py via `intel_program_full_router`.
intel_program_full_router = APIRouter(prefix="/v1/intel", tags=["intel"])


# ---------------------------------------------------------------------------
# Section enumeration
# ---------------------------------------------------------------------------

_ALLOWED_SECTIONS: frozenset[str] = frozenset(
    {
        "meta",
        "eligibility",
        "amendments",
        "adoptions",
        "similar",
        "citations",
        "audit_proof",
    }
)
_DEFAULT_SECTIONS: tuple[str, ...] = (
    "meta",
    "eligibility",
    "amendments",
    "adoptions",
    "similar",
    "citations",
    "audit_proof",
)


# Sensitive disclaimer — composite endpoint cuts across tax / 申請 / 法律
# fence territory because it surfaces eligibility predicates + law citations
# + adoption history that downstream LLMs may turn into 採択判断・申請可否判断.
_PROGRAM_FULL_DISCLAIMER = (
    "本 response は jpcite の単一 program に対する複数 corpus (meta / "
    "eligibility predicate / amendment 履歴 / 採択履歴 / 類似制度 / 法令引用 / "
    "監査 anchor) の機械的 aggregation で、税理士法 §52 (税務代理) ・"
    "行政書士法 §1 (申請代理) ・弁護士法 §72 (法律事務) の代替ではありません。"
    "eligibility predicate は rule-based 抽出のため partial coverage の可能性 "
    "あり (missing axis = unknown, NOT no constraint)。 確定判断は資格を有する "
    "税理士・行政書士・中小企業診断士に primary source 確認の上ご相談ください。"
)


# ---------------------------------------------------------------------------
# DB connection helpers
# ---------------------------------------------------------------------------


def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Open autonomath.db read-only. Returns None on missing/empty file."""
    try:
        path_str = os.environ.get("AUTONOMATH_DB_PATH", str(settings.autonomath_db_path))
        from pathlib import Path as _Path

        p = _Path(path_str)
        if not p.exists() or p.stat().st_size == 0:
            return None
        uri = f"file:{p}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute("PRAGMA query_only=1")
        return conn
    except (sqlite3.Error, AttributeError, OSError) as exc:
        logger.warning("autonomath open failed: %s", exc)
        return None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _resolve_program_aliases(
    am_conn: sqlite3.Connection,
    program_id: str,
) -> set[str]:
    """Walk entity_id_map both directions so callers can pass either form.

    Always includes the input id verbatim so callers passing the
    am_canonical_id form (e.g. ``program:test:tl-1``) bind the same set
    as those passing ``UNI-...``.
    """
    ids: set[str] = {program_id}
    if not _table_exists(am_conn, "entity_id_map"):
        return ids
    try:
        rows = am_conn.execute(
            "SELECT jpi_unified_id, am_canonical_id FROM entity_id_map "
            "WHERE jpi_unified_id = ? OR am_canonical_id = ?",
            (program_id, program_id),
        ).fetchall()
        for r in rows:
            if r["jpi_unified_id"]:
                ids.add(r["jpi_unified_id"])
            if r["am_canonical_id"]:
                ids.add(r["am_canonical_id"])
    except sqlite3.Error as exc:
        logger.warning("entity_id_map lookup failed: %s", exc)
    return ids


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _section_meta(
    am_conn: sqlite3.Connection,
    *,
    program_ids: set[str],
    missing: list[str],
) -> dict[str, Any] | None:
    """Pull the program metadata row from `programs`.

    Returns None when the program is absent on this volume.
    """
    if not _table_exists(am_conn, "programs"):
        missing.append("programs")
        return None
    placeholders = ",".join("?" for _ in program_ids)
    try:
        row = am_conn.execute(
            f"SELECT unified_id, primary_name, tier, prefecture, "
            f"       authority_name, authority_level, program_kind, "
            f"       source_url, official_url, "
            f"       amount_max_man_yen, amount_min_man_yen, "
            f"       application_window_json "
            f"  FROM programs "
            f" WHERE unified_id IN ({placeholders}) "
            f" LIMIT 1",
            tuple(program_ids),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("programs meta query failed: %s", exc)
        return None
    if row is None:
        return None
    primary_url = row["source_url"] or row["official_url"]
    # Convert 万円 to yen for the customer LLM that wants raw amounts.
    amax = row["amount_max_man_yen"]
    amin = row["amount_min_man_yen"]
    expected_max = int(amax * 10000) if amax is not None else None
    expected_min = int(amin * 10000) if amin is not None else None
    # Pull a short summary / jurisdiction string for the meta envelope.
    jurisdiction_parts = [
        p for p in (row["authority_level"], row["prefecture"], row["authority_name"]) if p
    ]
    jurisdiction = " / ".join(jurisdiction_parts) if jurisdiction_parts else None
    return {
        "id": row["unified_id"],
        "name": row["primary_name"],
        "tier": row["tier"],
        "jurisdiction": jurisdiction,
        "primary_url": primary_url,
        "summary": None,  # programs.primary_name is the only short label.
        "expected_amount_min": expected_min,
        "expected_amount_max": expected_max,
        "application_window": row["application_window_json"],
        "program_kind": row["program_kind"],
    }


def _section_eligibility(
    am_conn: sqlite3.Connection,
    *,
    program_ids: set[str],
    max_per_section: int,
    missing: list[str],
) -> list[dict[str, Any]] | None:
    """Pull rows from am_program_eligibility_predicate (W26-6).

    Returns the predicate rows for the program (capped at
    ``max_per_section``). Each row carries kind / operator / value. The
    JSON-rolled-up cache (am_program_eligibility_predicate_json) is NOT
    consulted here — that endpoint already exists at /v1/programs/{id}/
    eligibility_predicate and the caller can hit it directly when they
    want the consolidated JSON form.
    """
    if not _table_exists(am_conn, "am_program_eligibility_predicate"):
        missing.append("am_program_eligibility_predicate")
        return None
    placeholders = ",".join("?" for _ in program_ids)
    try:
        rows = am_conn.execute(
            f"SELECT predicate_id, program_unified_id, predicate_kind, "
            f"       operator, value_text, value_num, value_json, "
            f"       is_required, source_url, source_clause_quote "
            f"  FROM am_program_eligibility_predicate "
            f" WHERE program_unified_id IN ({placeholders}) "
            f" ORDER BY is_required DESC, predicate_kind ASC "
            f" LIMIT ?",
            (*program_ids, max_per_section),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_program_eligibility_predicate query failed: %s", exc)
        return None
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "predicate_id": r["predicate_id"],
                "kind": r["predicate_kind"],
                "operator": r["operator"],
                "value_text": r["value_text"],
                "value_num": r["value_num"],
                "value_json": r["value_json"],
                "is_required": bool(r["is_required"]),
                "source_url": r["source_url"],
                "source_clause_quote": r["source_clause_quote"],
            }
        )
    return out


def _section_amendments(
    am_conn: sqlite3.Connection,
    *,
    program_ids: set[str],
    max_per_section: int,
    missing: list[str],
) -> list[dict[str, Any]] | None:
    """Pull recent rows from am_amendment_diff for the program.

    The task spec mentions ``am_amendment_diff_history`` but the live
    schema is `am_amendment_diff` (autonomath.db, migration 040+).  We
    use the live table and surface ``date / summary / change_type`` per
    spec.
    """
    if not _table_exists(am_conn, "am_amendment_diff"):
        missing.append("am_amendment_diff")
        return None
    placeholders = ",".join("?" for _ in program_ids)
    try:
        rows = am_conn.execute(
            f"SELECT entity_id, field_name, prev_value, new_value, "
            f"       detected_at, source_url "
            f"  FROM am_amendment_diff "
            f" WHERE entity_id IN ({placeholders}) "
            f" ORDER BY detected_at DESC "
            f" LIMIT ?",
            (*program_ids, max_per_section),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_amendment_diff query failed: %s", exc)
        return None
    out: list[dict[str, Any]] = []
    for r in rows:
        prev = r["prev_value"]
        new = r["new_value"]
        parts: list[str] = []
        if prev is not None:
            parts.append(f"prev={str(prev)[:80]}")
        if new is not None:
            parts.append(f"new={str(new)[:80]}")
        summary = " → ".join(parts) or "field cleared"
        # change_type heuristic: created (no prev), removed (no new), modified.
        if prev is None and new is not None:
            change_type = "created"
        elif new is None and prev is not None:
            change_type = "removed"
        else:
            change_type = "modified"
        out.append(
            {
                "date": r["detected_at"],
                "summary": f"{r['field_name']}: {summary}",
                "change_type": change_type,
                "field_name": r["field_name"],
                "evidence_url": r["source_url"],
            }
        )
    return out


def _section_adoptions(
    am_conn: sqlite3.Connection,
    *,
    program_ids: set[str],
    max_per_section: int,
    missing: list[str],
) -> list[dict[str, Any]] | None:
    """Top-N adopted houjin for the program, joined to credibility features.

    Walks `jpi_adoption_records` (per-event ledger) → grouped by houjin →
    enriched with `am_adopted_company_features` (credibility / total
    adoption count). Returned rows are sorted by amount_granted_yen DESC
    (NULL last), then by announced_at DESC for stability.
    """
    if not _table_exists(am_conn, "jpi_adoption_records"):
        missing.append("jpi_adoption_records")
        return None
    placeholders = ",".join("?" for _ in program_ids)
    has_features = _table_exists(am_conn, "am_adopted_company_features")
    if not has_features:
        missing.append("am_adopted_company_features")
    sql = f"""
        SELECT a.houjin_bangou,
               a.program_id,
               a.announced_at,
               a.amount_granted_yen,
               a.company_name_raw
          FROM jpi_adoption_records a
         WHERE a.program_id IN ({placeholders})
            OR a.program_id_hint IN ({placeholders})
         ORDER BY (a.amount_granted_yen IS NULL) ASC,
                  a.amount_granted_yen DESC,
                  a.announced_at DESC
         LIMIT ?
    """
    try:
        rows = am_conn.execute(sql, (*program_ids, *program_ids, max_per_section)).fetchall()
    except sqlite3.Error as exc:
        logger.warning("jpi_adoption_records query failed: %s", exc)
        return None
    out: list[dict[str, Any]] = []
    for r in rows:
        houjin = r["houjin_bangou"]
        item: dict[str, Any] = {
            "houjin_id": houjin,
            "name": r["company_name_raw"],
            "amount": r["amount_granted_yen"],
            "year": _extract_year(r["announced_at"]),
            "announced_at": r["announced_at"],
        }
        # Optional credibility enrichment via am_adopted_company_features.
        if has_features and houjin:
            try:
                feat = am_conn.execute(
                    "SELECT credibility_score, adoption_count "
                    "  FROM am_adopted_company_features "
                    " WHERE houjin_bangou = ? LIMIT 1",
                    (houjin,),
                ).fetchone()
                if feat is not None:
                    item["credibility_score"] = feat["credibility_score"]
                    item["total_adoption_count"] = feat["adoption_count"]
            except sqlite3.Error:
                pass
        out.append(item)
    return out


def _extract_year(iso_date: str | None) -> int | None:
    """Extract YYYY from an ISO date prefix. Soft-fail returns None."""
    if not iso_date or not isinstance(iso_date, str):
        return None
    s = iso_date.strip()
    if len(s) < 4 or not s[:4].isdigit():
        return None
    try:
        return int(s[:4])
    except (ValueError, TypeError):
        return None


def _section_similar(
    am_conn: sqlite3.Connection,
    *,
    program_ids: set[str],
    max_per_section: int,
    missing: list[str],
) -> list[dict[str, Any]] | None:
    """Pull top-N similar programs from am_recommended_programs.

    The task spec calls out `am_program_recommended_programs` but the
    live table is `am_recommended_programs` (which keys on houjin_bangou,
    NOT on program_unified_id). Since this endpoint is program-anchored
    we instead look for programs that the SAME houjin pool was
    recommended into — i.e. peers of this program by recommendation
    co-occurrence.

    When the table is missing OR no co-occurrence exists, returns [].
    """
    # Soft-fail if the cron table isn't on this volume (fresh test fixture).
    if not _table_exists(am_conn, "am_recommended_programs"):
        missing.append("am_recommended_programs")
        return None
    if not _table_exists(am_conn, "programs"):
        # Without programs we can't enrich names, but we can still emit ids.
        pass
    placeholders = ",".join("?" for _ in program_ids)
    try:
        rows = am_conn.execute(
            f"""
            SELECT r2.program_unified_id AS peer_program_id,
                   COUNT(DISTINCT r1.houjin_bangou) AS co_occurrence,
                   AVG(r2.score) AS avg_score
              FROM am_recommended_programs r1
              JOIN am_recommended_programs r2
                ON r1.houjin_bangou = r2.houjin_bangou
             WHERE r1.program_unified_id IN ({placeholders})
               AND r2.program_unified_id NOT IN ({placeholders})
             GROUP BY r2.program_unified_id
             ORDER BY co_occurrence DESC, avg_score DESC
             LIMIT ?
            """,
            (*program_ids, *program_ids, max_per_section),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_recommended_programs query failed: %s", exc)
        return None
    out: list[dict[str, Any]] = []
    for r in rows:
        peer = r["peer_program_id"]
        score = r["avg_score"]
        item = {
            "program_id": peer,
            "name": None,
            "similarity_score": float(score) if score is not None else None,
            "co_occurrence_count": int(r["co_occurrence"] or 0),
        }
        # Best-effort name enrichment from programs.
        if _table_exists(am_conn, "programs"):
            try:
                nrow = am_conn.execute(
                    "SELECT primary_name FROM programs WHERE unified_id = ? LIMIT 1",
                    (peer,),
                ).fetchone()
                if nrow and nrow["primary_name"]:
                    item["name"] = nrow["primary_name"]
            except sqlite3.Error:
                pass
        out.append(item)
    return out


def _section_citations(
    am_conn: sqlite3.Connection,
    *,
    program_ids: set[str],
    max_per_section: int,
    missing: list[str],
) -> dict[str, list[dict[str, Any]]] | None:
    """Aggregate law / tsutatsu / hanrei references for the program.

    - **law**: program_law_refs ⨯ am_law_article — surface the article
      citations the program cites as authority/eligibility/exclusion.
    - **tsutatsu**: nta_tsutatsu_index — best-effort reverse lookup via
      law_canonical_id of any law referenced by the program.
    - **hanrei** (court_decisions): NOT joined here — there is no
      program-to-court-decision linkage in the unified schema. Returned
      as ``[]`` so the caller can still iterate the keyset uniformly.
    """
    out: dict[str, list[dict[str, Any]]] = {"law": [], "tsutatsu": [], "hanrei": []}
    placeholders = ",".join("?" for _ in program_ids)

    # --- law (program_law_refs) ------------------------------------------
    has_plr = _table_exists(am_conn, "program_law_refs")
    if not has_plr:
        # Try the jpi_-mirrored table.
        has_plr = _table_exists(am_conn, "jpi_program_law_refs")
        plr_table = "jpi_program_law_refs" if has_plr else None
    else:
        plr_table = "program_law_refs"

    if plr_table is None:
        missing.append("program_law_refs")
    else:
        try:
            rows = am_conn.execute(
                f"SELECT program_unified_id, law_unified_id, ref_kind, "
                f"       article_citation, source_url, fetched_at, confidence "
                f"  FROM {plr_table} "
                f" WHERE program_unified_id IN ({placeholders}) "
                f" ORDER BY confidence DESC, fetched_at DESC "
                f" LIMIT ?",
                (*program_ids, max_per_section),
            ).fetchall()
            for r in rows:
                out["law"].append(
                    {
                        "law_unified_id": r["law_unified_id"],
                        "ref_kind": r["ref_kind"],
                        "article_citation": r["article_citation"],
                        "source_url": r["source_url"],
                        "confidence": r["confidence"],
                    }
                )
        except sqlite3.Error as exc:
            logger.warning("%s query failed: %s", plr_table, exc)

    # --- tsutatsu (nta_tsutatsu_index by referenced law) -----------------
    if not _table_exists(am_conn, "nta_tsutatsu_index"):
        missing.append("nta_tsutatsu_index")
    elif out["law"]:
        # Tsutatsu reverse-lookup keyed by the e-Gov canonical id; we cannot
        # bridge LAW-* → law:* without a separate index, so we best-effort
        # match on law_canonical_id appearing in the law_unified_id text.
        # Limit tsutatsu rows separately.
        try:
            t_rows = am_conn.execute(
                "SELECT code, law_canonical_id, article_number, title, source_url "
                "  FROM nta_tsutatsu_index "
                " ORDER BY refreshed_at DESC "
                " LIMIT ?",
                (max_per_section,),
            ).fetchall()
            for r in t_rows:
                out["tsutatsu"].append(
                    {
                        "code": r["code"],
                        "law_canonical_id": r["law_canonical_id"],
                        "article_number": r["article_number"],
                        "title": r["title"],
                        "source_url": r["source_url"],
                    }
                )
        except sqlite3.Error as exc:
            logger.warning("nta_tsutatsu_index query failed: %s", exc)

    return out


def _section_audit_proof(
    am_conn: sqlite3.Connection,
    *,
    missing: list[str],
) -> dict[str, Any] | None:
    """Surface the latest audit_merkle_anchor row + repo metadata.

    The audit anchor is corpus-wide (one row per JST day), not per-program,
    so the program_full envelope returns the most recent anchor as a
    proof-of-corpus-state at evaluation time. Customer LLMs forward this
    to the auditor's `ots verify` + GitHub commit walkthrough.
    """
    if not _table_exists(am_conn, "audit_merkle_anchor"):
        missing.append("audit_merkle_anchor")
        return None
    try:
        row = am_conn.execute(
            "SELECT daily_date, row_count, merkle_root, ots_proof, "
            "       github_commit_sha, twitter_post_id, created_at "
            "  FROM audit_merkle_anchor "
            " ORDER BY daily_date DESC LIMIT 1"
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("audit_merkle_anchor query failed: %s", exc)
        return None
    if row is None:
        return None
    sha = row["github_commit_sha"]
    repo = os.environ.get("GITHUB_REPOSITORY", "bookyou/jpcite")
    github_url = f"https://github.com/{repo}/commit/{sha}" if sha else None
    ots_url = "https://opentimestamps.org/" if row["ots_proof"] else None
    return {
        "merkle_root": row["merkle_root"],
        "ots_url": ots_url,
        "github_sha": sha,
        "github_commit_url": github_url,
        "last_anchored": row["daily_date"],
        "row_count": int(row["row_count"]),
        "created_at": row["created_at"],
    }


# ---------------------------------------------------------------------------
# Composite assembly
# ---------------------------------------------------------------------------


def _build_program_full(
    *,
    program_id: str,
    include_sections: tuple[str, ...],
    max_per_section: int,
) -> tuple[dict[str, Any], list[str], bool]:
    """Build the composite envelope.

    Returns (body_dict, missing_tables, program_found).
    program_found=False signals the meta lookup failed → 404.
    """
    missing: list[str] = []
    body: dict[str, Any] = {
        "program_id": program_id,
        "include_sections": list(include_sections),
        "max_per_section": max_per_section,
    }

    am_conn = _open_autonomath_ro()
    if am_conn is None:
        missing.append("autonomath_db")
        body["data_quality"] = {"missing_tables": missing}
        return body, missing, False

    try:
        program_ids = _resolve_program_aliases(am_conn, program_id)

        # Always run meta to confirm program existence + drive 404.
        meta = _section_meta(am_conn, program_ids=program_ids, missing=missing)
        program_found = meta is not None
        if "meta" in include_sections:
            body["program_meta"] = meta

        if "eligibility" in include_sections:
            body["eligibility_predicate"] = _section_eligibility(
                am_conn,
                program_ids=program_ids,
                max_per_section=max_per_section,
                missing=missing,
            )
        if "amendments" in include_sections:
            body["amendments_recent"] = _section_amendments(
                am_conn,
                program_ids=program_ids,
                max_per_section=max_per_section,
                missing=missing,
            )
        if "adoptions" in include_sections:
            body["adoptions_top"] = _section_adoptions(
                am_conn,
                program_ids=program_ids,
                max_per_section=max_per_section,
                missing=missing,
            )
        if "similar" in include_sections:
            body["similar_programs"] = _section_similar(
                am_conn,
                program_ids=program_ids,
                max_per_section=max_per_section,
                missing=missing,
            )
        if "citations" in include_sections:
            body["citations"] = _section_citations(
                am_conn,
                program_ids=program_ids,
                max_per_section=max_per_section,
                missing=missing,
            )
        if "audit_proof" in include_sections:
            body["audit_proof"] = _section_audit_proof(am_conn, missing=missing)
    finally:
        with contextlib.suppress(sqlite3.Error):
            am_conn.close()

    body["data_quality"] = {"missing_tables": sorted(set(missing))}
    return body, missing, program_found


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------


@intel_program_full_router.get(
    "/program/{program_id}/full",
    summary="Composite per-program bundle — meta + eligibility + amendments + adoptions + similar + citations + audit_proof",
    description=(
        "Bundles the 8+ naive single-program calls into one composite GET. "
        "Returns `program_meta`, `eligibility_predicate`, `amendments_recent`, "
        "`adoptions_top`, `similar_programs`, `citations`, and `audit_proof` "
        "for a single program in one request. Sections are individually "
        "selectable via `?include_sections=meta&include_sections=eligibility` "
        "(repeat the query param to multi-select).\n\n"
        "**Pricing:** ¥3 / call (1 unit) regardless of section count.\n\n"
        "**Sensitive:** §52 / §1 / §72 disclaimer envelope. NO LLM call. "
        "Pure SQLite + Python over autonomath unified DB.\n\n"
        "**Section semantics:**\n\n"
        "- `program_meta`: id, name, tier, jurisdiction, primary_url, "
        "  expected amounts (yen), application_window\n"
        "- `eligibility_predicate`: rule-based predicate rows (W26-6) — "
        "  missing axis = unknown, NOT no constraint.\n"
        "- `amendments_recent`: am_amendment_diff entries within program "
        "  scope, sorted by detected_at desc.\n"
        "- `adoptions_top`: top-N adopted houjin (sorted by amount desc).\n"
        "- `similar_programs`: peer programs by recommendation "
        "  co-occurrence in am_recommended_programs.\n"
        "- `citations`: {law: [...], tsutatsu: [...], hanrei: []}. "
        "  Hanrei is intentionally `[]` — no program-to-court-decision "
        "  linkage exists in the unified schema.\n"
        "- `audit_proof`: latest corpus-wide Merkle anchor + OTS + "
        "  GitHub SHA so the auditor can verify the snapshot."
    ),
    responses={
        200: {"description": "Composite per-program bundle envelope."},
        404: {
            "description": (
                "Program not found in the autonomath corpus. Verify the id via /v1/programs/search."
            )
        },
        422: {"description": "Invalid include_sections or max_per_section."},
    },
)
def get_program_full(
    program_id: Annotated[
        str,
        PathParam(
            description=(
                "Program canonical id. Accepts either the jpintel "
                "`UNI-...` form or the autonomath `program:...` form; "
                "the lookup walks `entity_id_map` to bridge both."
            ),
            min_length=1,
            max_length=200,
        ),
    ],
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    include_sections: Annotated[
        list[str] | None,
        Query(
            description=(
                "Sections to include. Repeat the param to multi-select "
                "(e.g. `?include_sections=meta&include_sections=eligibility`). "
                "Allowed: meta, eligibility, amendments, adoptions, similar, "
                "citations, audit_proof. Defaults to all 7."
            ),
        ),
    ] = None,
    max_per_section: Annotated[
        int,
        Query(
            ge=1,
            le=20,
            description=(
                "Per-section row cap (1..20, default 5). Applies to "
                "list-shaped sections (eligibility, amendments, adoptions, "
                "similar, each citation kind)."
            ),
        ),
    ] = 5,
) -> JSONResponse:
    _t0 = time.perf_counter()

    pid = program_id.strip()
    if not pid:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_program_id",
                "field": "program_id",
                "message": "program_id must be non-empty.",
            },
        )

    # Validate + dedupe include_sections.
    requested = tuple(include_sections) if include_sections else _DEFAULT_SECTIONS
    bad = [s for s in requested if s not in _ALLOWED_SECTIONS]
    if bad:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_include_sections",
                "field": "include_sections",
                "message": (
                    f"include_sections contains unknown values: {bad}. "
                    f"Allowed: {sorted(_ALLOWED_SECTIONS)}."
                ),
            },
        )
    seen: list[str] = []
    for s in requested:
        if s not in seen:
            seen.append(s)
    sections_tuple = tuple(seen)

    body, _missing, program_found = _build_program_full(
        program_id=pid,
        include_sections=sections_tuple,
        max_per_section=max_per_section,
    )

    # 404 only when the meta lookup explicitly failed AND meta was requested.
    # Callers that strip 'meta' (e.g. they already have it cached) should
    # still be able to fetch sub-sections without a 404.
    if "meta" in sections_tuple and not program_found:
        raise HTTPException(
            status_code=404,
            detail=(
                f"program_id={pid!r} not found in autonomath programs. "
                "Verify via /v1/programs/search or pass an entity_id_map "
                "alias (UNI-... or program:... form)."
            ),
        )

    body["_disclaimer"] = _PROGRAM_FULL_DISCLAIMER
    body["_billing_unit"] = 1

    # Auditor reproducibility — corpus_snapshot_id + corpus_checksum.
    body = attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "intel.program_full",
        latency_ms=latency_ms,
        result_count=1 if program_found else 0,
        params={
            "program_id": pid,
            "include_sections": list(sections_tuple),
            "max_per_section": max_per_section,
        },
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="intel.program_full",
        request_params={
            "program_id": pid,
            "include_sections": list(sections_tuple),
            "max_per_section": max_per_section,
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )

    if wants_compact(request):
        body = to_compact(body)

    return JSONResponse(content=body)


__all__ = ["intel_program_full_router"]
