#!/usr/bin/env python3
"""Populate ``program_law_refs`` + ``laws`` (jpintel.db) bridge tables.

Wave 22-10 (2026-05-05) follow-up. The W22 audit confirmed that:

* ``program_law_refs`` and ``laws`` (canonical jpintel.db bridge) were
  both 0 rows.
* ``am_law`` (autonomath.db, 10,125 rows) and ``am_law_reference``
  (autonomath.db, 5,523 rows) hold the raw program ↔ law citations the
  ingest layer captured.
* The W22 manifest ``docs/_internal/W22_NEW_LAW_PROGRAM_LINKS.tsv`` enumerates
  the 82 laws whose new article ingest in W21-1 affects programs (1,118
  refs / 789 distinct programs).

This script lifts that subset into the canonical jpintel.db bridge so
that the live MCP tool ``trace_program_law_chain`` (which walks
``program_law_refs`` → ``laws``) can return non-empty chains for
production traffic. Pure SQL + Python; **no LLM call**.

Mapping rules
-------------
laws.unified_id (LAW-<10 lowercase hex>)
    Deterministic: ``"LAW-" + sha1(am_law.canonical_id).hexdigest()[:10]``.
    Stable across re-runs.

program_law_refs.program_unified_id
    Resolved via ``entity_id_map`` (autonomath.db) when available.
    Programs without a mirror map row are skipped (~89 / 1,118 refs at
    W22 snapshot — they have no jpi_programs row to anchor to).

program_law_refs.ref_kind
    'authority' if ``source_field`` matches ``%basis%`` / ``%authority%`` /
    ``%root_law%`` / ``%law_basis%``; 'reference' otherwise.

program_law_refs.article_citation
    ``article + paragraph + sub_item`` joined; empty string if all NULL
    (the PRIMARY KEY tolerates empty string but not NULL).

program_law_refs.source_url
    am_law.egov_url when present, else
    ``"https://laws.e-gov.go.jp/search/elawsSearch/elaws_search/lsg0100/"``
    as the catalog fallback (per W22 ingest convention).

Idempotent: ``INSERT OR IGNORE`` on both tables.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
JPINTEL_DB = REPO_ROOT / "jpintel.db"
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
W22_TSV = REPO_ROOT / "docs" / "_internal" / "W22_NEW_LAW_PROGRAM_LINKS.tsv"

EGOV_FALLBACK_URL = "https://laws.e-gov.go.jp/search/elawsSearch/elaws_search/lsg0100/"


def derive_law_unified_id(canonical_id: str) -> str:
    """Deterministic LAW-<10 hex> from am_law.canonical_id."""
    h = hashlib.sha1(canonical_id.encode("utf-8")).hexdigest()[:10]
    return f"LAW-{h}"


def classify_ref_kind(source_field: str | None) -> str:
    if not source_field:
        return "reference"
    sf = source_field.lower()
    authority_markers = (
        "basis",
        "authority",
        "root_law",
        "law_basis",
        "parent_law",
    )
    if any(m in sf for m in authority_markers):
        return "authority"
    return "reference"


def build_article_citation(article: str | None, paragraph: str | None, sub_item: str | None) -> str:
    parts = [p for p in (article, paragraph, sub_item) if p]
    return "".join(parts)


def map_law_type(category: str | None, status: str | None) -> str:
    """Map am_law.category → laws.law_type enum (best-effort)."""
    cat = (category or "").lower()
    if "政令" in (category or ""):
        return "cabinet_order"
    if "省令" in (category or ""):
        return "ministerial_ordinance"
    if "規則" in (category or ""):
        return "rule"
    if "告示" in (category or ""):
        return "notice"
    if "通達" in (category or "") or "guideline" in cat:
        return "guideline"
    return "act"


def map_revision_status(status: str | None) -> str:
    s = (status or "active").lower()
    if s in ("repealed", "廃止"):
        return "repealed"
    if s in ("superseded", "amended"):
        return "superseded"
    return "current"


def load_w22_law_ids() -> list[str]:
    if not W22_TSV.exists():
        print(f"[error] missing {W22_TSV}", file=sys.stderr)
        sys.exit(2)
    ids: list[str] = []
    for line in W22_TSV.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) < 2:
            continue
        ids.append(parts[0].strip())
    return ids


def populate(dry_run: bool = False, verbose: bool = False) -> tuple[int, int, int, int]:
    """Returns (laws_before, laws_after, plr_before, plr_after)."""
    if not JPINTEL_DB.exists():
        print(f"[error] missing {JPINTEL_DB}", file=sys.stderr)
        sys.exit(2)
    if not AUTONOMATH_DB.exists():
        print(f"[error] missing {AUTONOMATH_DB}", file=sys.stderr)
        sys.exit(2)

    law_ids = load_w22_law_ids()
    if verbose:
        print(f"[info] W22 law universe: {len(law_ids)} laws")

    am_conn = sqlite3.connect(AUTONOMATH_DB)
    am_conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(law_ids))

    # Pull law metadata for the 82 W22 laws.
    am_law_rows = am_conn.execute(
        f"SELECT canonical_id, canonical_name, short_name, law_number, "
        f"category, first_enforced, egov_url, status, ministry, "
        f"effective_from, effective_until, last_amended_at, "
        f"subject_areas_json, e_gov_lawid "
        f"FROM am_law WHERE canonical_id IN ({placeholders})",
        law_ids,
    ).fetchall()
    if verbose:
        print(f"[info] am_law rows resolved: {len(am_law_rows)} / {len(law_ids)}")

    # Pull program ↔ law refs in scope, joined to entity_id_map.
    ref_rows = am_conn.execute(
        f"""SELECT lr.entity_id, lr.law_canonical_id, lr.article,
                   lr.paragraph, lr.sub_item, lr.source_field,
                   lr.evidence_text, eim.jpi_unified_id
            FROM am_law_reference lr
            JOIN entity_id_map eim ON eim.am_canonical_id = lr.entity_id
            WHERE lr.entity_id LIKE 'program:%'
              AND lr.law_canonical_id IN ({placeholders})""",
        law_ids,
    ).fetchall()
    if verbose:
        print(f"[info] mapped program-law refs: {len(ref_rows)}")

    am_conn.close()

    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    jp_conn = sqlite3.connect(JPINTEL_DB)
    jp_conn.row_factory = sqlite3.Row
    laws_before = jp_conn.execute("SELECT COUNT(*) FROM laws").fetchone()[0]
    plr_before = jp_conn.execute("SELECT COUNT(*) FROM program_law_refs").fetchone()[0]

    if dry_run:
        jp_conn.close()
        # Project the would-be after counts (assume IGNORE = 0 conflicts).
        return (laws_before, laws_before + len(am_law_rows), plr_before, plr_before + len(ref_rows))

    # Insert into laws.
    canonical_to_unified: dict[str, str] = {}
    laws_to_insert = []
    for r in am_law_rows:
        cid = r["canonical_id"]
        uid = derive_law_unified_id(cid)
        canonical_to_unified[cid] = uid
        laws_to_insert.append(
            (
                uid,
                r["law_number"] or "未指定",
                r["canonical_name"],
                r["short_name"],
                map_law_type(r["category"], r["status"]),
                r["ministry"],
                r["first_enforced"],
                r["effective_from"],
                r["last_amended_at"],
                map_revision_status(r["status"]),
                None,  # superseded_by_law_id (resolve later)
                None,  # article_count
                r["egov_url"] or EGOV_FALLBACK_URL,
                None,  # summary
                r["subject_areas_json"],
                r["egov_url"] or EGOV_FALLBACK_URL,  # source_url
                None,  # source_checksum
                0.95,
                now_iso,
                now_iso,
            )
        )
    jp_conn.executemany(
        """INSERT OR IGNORE INTO laws (
            unified_id, law_number, law_title, law_short_title, law_type,
            ministry, promulgated_date, enforced_date, last_amended_date,
            revision_status, superseded_by_law_id, article_count,
            full_text_url, summary, subject_areas_json,
            source_url, source_checksum, confidence, fetched_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        laws_to_insert,
    )

    # Insert into program_law_refs. Dedupe by PK in advance because
    # multiple raw refs may collapse to the same (program, law, kind, citation).
    seen: set[tuple[str, str, str, str]] = set()
    plr_to_insert = []
    skipped_unmapped_law = 0
    for r in ref_rows:
        prog_uid = r["jpi_unified_id"]
        law_uid = canonical_to_unified.get(r["law_canonical_id"])
        if not prog_uid or not law_uid:
            skipped_unmapped_law += 1
            continue
        ref_kind = classify_ref_kind(r["source_field"])
        citation = build_article_citation(r["article"], r["paragraph"], r["sub_item"])
        key = (prog_uid, law_uid, ref_kind, citation)
        if key in seen:
            continue
        seen.add(key)
        plr_to_insert.append(
            (
                prog_uid,
                law_uid,
                ref_kind,
                citation,
                EGOV_FALLBACK_URL,  # source_url - we lifted from inbox, not a live page
                now_iso,
                0.85,  # slightly below default (heuristic ref_kind classification)
            )
        )
    jp_conn.executemany(
        """INSERT OR IGNORE INTO program_law_refs (
            program_unified_id, law_unified_id, ref_kind, article_citation,
            source_url, fetched_at, confidence
        ) VALUES (?,?,?,?,?,?,?)""",
        plr_to_insert,
    )
    jp_conn.commit()

    laws_after = jp_conn.execute("SELECT COUNT(*) FROM laws").fetchone()[0]
    plr_after = jp_conn.execute("SELECT COUNT(*) FROM program_law_refs").fetchone()[0]
    jp_conn.close()

    if verbose:
        print(f"[info] dedupe collapse: {len(ref_rows)} → {len(plr_to_insert)}")
        print(f"[info] skipped (no law map): {skipped_unmapped_law}")

    return laws_before, laws_after, plr_before, plr_after


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    laws_before, laws_after, plr_before, plr_after = populate(
        dry_run=args.dry_run, verbose=args.verbose
    )
    print(f"laws:             {laws_before} -> {laws_after}")
    print(f"program_law_refs: {plr_before} -> {plr_after}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
