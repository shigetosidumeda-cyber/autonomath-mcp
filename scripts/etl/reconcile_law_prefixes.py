#!/usr/bin/env python3
"""Reconcile A1 law identifiers and populate program_law_refs.

This is an offline, deterministic stitch:

* ``autonomath.db.am_relation`` keeps graph-facing ``law:*`` targets.
* ``data/jpintel.db.program_law_refs`` keeps API-facing ``LAW-*`` FKs.

No network. No LLM. Re-runnable via ``INSERT OR IGNORE`` and exact-id
updates.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"

_ARTICLE_TAIL_RE = re.compile(
    r"(?:第[0-9一二三四五六七八九十百千〇零]+条"
    r"(?:の[0-9一二三四五六七八九十百千〇零]+)?"
    r"(?:第[0-9一二三四五六七八九十百千〇零]+項)?"
    r"|第[0-9一二三四五六七八九十百千〇零]+項)$"
)


@dataclass(frozen=True)
class ProgramLawRef:
    program_unified_id: str
    law_unified_id: str
    ref_kind: str
    article_citation: str
    source_url: str
    fetched_at: str
    confidence: float


def _connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _norm_key(text: str | None) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\s+", "", text).strip()


def normalize_law_prefix(text: str) -> str:
    """Normalize a raw law prefix while dropping tail article citations."""
    normalized = unicodedata.normalize("NFKC", text or "").strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = _ARTICLE_TAIL_RE.sub("", normalized).strip()
    return re.sub(r"\s+", "", normalized)


def build_law_prefix_index(rows: Iterable[dict[str, Any]]) -> dict[str, str]:
    """Build an exact law-title/short-title index, excluding ambiguities."""
    buckets: dict[str, set[str]] = {}
    for row in rows:
        law_id = str(row.get("unified_id") or "")
        if not law_id.startswith("LAW-"):
            continue
        for value in (
            row.get("law_title"),
            *(str(row.get("law_short_title") or "").split(",")),
        ):
            key = normalize_law_prefix(str(value or ""))
            if key:
                buckets.setdefault(key, set()).add(law_id)
    return {
        key: next(iter(values))
        for key, values in buckets.items()
        if len(values) == 1
    }


def reconcile_law_prefixes(
    refs: Iterable[dict[str, Any]],
    laws: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve free-text law prefixes into unambiguous ``LAW-*`` ids."""
    index = build_law_prefix_index(laws)
    resolved: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for ref in refs:
        raw = str(ref.get("law_prefix") or "")
        law_id = index.get(normalize_law_prefix(raw))
        if law_id is None:
            unresolved.append({**ref, "unresolved_reason": "no_unambiguous_law"})
            continue
        resolved.append({**ref, "law_unified_id": law_id})
    return resolved, unresolved


def _law_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(
        f"SELECT unified_id, law_title, law_short_title, source_url FROM {table}"
    )]


def _jpi_law_indexes(conn: sqlite3.Connection) -> tuple[dict[str, str], dict[str, str]]:
    by_lawid: dict[str, str] = {}
    by_title = build_law_prefix_index(_law_rows(conn, "jpi_laws"))
    for row in conn.execute("SELECT unified_id, source_url FROM jpi_laws"):
        lawid = str(row["source_url"] or "").rstrip("/").split("/")[-1]
        if lawid:
            by_lawid[lawid] = row["unified_id"]
    return by_lawid, by_title


def _jpintel_law_indexes(
    conn: sqlite3.Connection,
) -> tuple[set[str], dict[str, str], dict[str, str], dict[str, str]]:
    law_ids: set[str] = set()
    source_url_by_id: dict[str, str] = {}
    by_lawid: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    for row in conn.execute(
        "SELECT unified_id, law_title, law_short_title, source_url FROM laws"
    ):
        data = dict(row)
        rows.append(data)
        law_ids.add(row["unified_id"])
        source_url_by_id[row["unified_id"]] = row["source_url"]
        lawid = str(row["source_url"] or "").rstrip("/").split("/")[-1]
        if lawid:
            by_lawid[lawid] = row["unified_id"]
    return law_ids, by_lawid, build_law_prefix_index(rows), source_url_by_id


def _relation_target_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        row["target_entity_id"]: row["n"]
        for row in conn.execute(
            """SELECT target_entity_id, COUNT(*) AS n
                 FROM am_relation
                WHERE relation_type='references_law'
                  AND target_entity_id LIKE 'law:%'
             GROUP BY target_entity_id"""
        )
    }


def _am_law_to_law_index(
    am_conn: sqlite3.Connection,
    *,
    lawid_to_law: dict[str, str],
    title_to_law: dict[str, str],
) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in am_conn.execute(
        """SELECT canonical_id, canonical_name, short_name, e_gov_lawid
             FROM am_law"""
    ):
        law_id = lawid_to_law.get(row["e_gov_lawid"] or "")
        if law_id is None:
            for value in (row["canonical_name"], row["short_name"]):
                law_id = title_to_law.get(normalize_law_prefix(value or ""))
                if law_id:
                    break
        if law_id:
            out[row["canonical_id"]] = law_id
    return out


def _law_to_am_law_mapping(am_conn: sqlite3.Connection) -> dict[str, str]:
    by_lawid, _by_title = _jpi_law_indexes(am_conn)
    existing_counts = _relation_target_counts(am_conn)
    mapping: dict[str, str] = {}
    for row in am_conn.execute(
        """SELECT DISTINCT r.target_entity_id AS old_id, jl.source_url
             FROM am_relation r
             JOIN jpi_laws jl ON jl.unified_id = r.target_entity_id
            WHERE r.relation_type='references_law'
              AND r.target_entity_id LIKE 'LAW-%'"""
    ):
        lawid = str(row["source_url"] or "").rstrip("/").split("/")[-1]
        if not by_lawid.get(lawid):
            continue
        candidates = [dict(r) for r in am_conn.execute(
            """SELECT canonical_id, status
                 FROM am_law
                WHERE e_gov_lawid = ?""",
            (lawid,),
        )]
        if not candidates:
            continue
        candidates.sort(
            key=lambda c: (
                -existing_counts.get(c["canonical_id"], 0),
                c["status"] != "active",
                "-rev-" in c["canonical_id"],
                c["canonical_id"],
            )
        )
        mapping[row["old_id"]] = candidates[0]["canonical_id"]
    return mapping


def _harvest_collision_count(
    conn: sqlite3.Connection,
    mapping: dict[str, str],
) -> int:
    collisions = 0
    for old_id, new_id in mapping.items():
        rows = conn.execute(
            """SELECT id, source_entity_id, relation_type, source_field, origin
                 FROM am_relation
                WHERE relation_type='references_law'
                  AND target_entity_id = ?""",
            (old_id,),
        )
        for row in rows:
            if row["origin"] != "harvest":
                continue
            duplicate = conn.execute(
                """SELECT id
                     FROM am_relation
                    WHERE origin='harvest'
                      AND source_entity_id = ?
                      AND COALESCE(target_entity_id, '') = COALESCE(?, '')
                      AND relation_type = ?
                      AND COALESCE(source_field, '') = COALESCE(?, '')
                    LIMIT 1""",
                (
                    row["source_entity_id"],
                    new_id,
                    row["relation_type"],
                    row["source_field"],
                ),
            ).fetchone()
            if duplicate and duplicate["id"] != row["id"]:
                collisions += 1
    return collisions


def reconcile_am_relation_targets(
    conn: sqlite3.Connection,
    *,
    apply: bool,
) -> dict[str, Any]:
    before_rows = conn.execute(
        """SELECT COUNT(*)
             FROM am_relation
            WHERE relation_type='references_law'
              AND target_entity_id LIKE 'LAW-%'"""
    ).fetchone()[0]
    before_distinct = conn.execute(
        """SELECT COUNT(DISTINCT target_entity_id)
             FROM am_relation
            WHERE relation_type='references_law'
              AND target_entity_id LIKE 'LAW-%'"""
    ).fetchone()[0]
    mapping = _law_to_am_law_mapping(conn)
    collisions = _harvest_collision_count(conn, mapping)
    if collisions:
        raise RuntimeError(f"would collide with ux_am_relation_harvest: {collisions}")

    changed = 0
    if apply and mapping:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for old_id, new_id in mapping.items():
                cur = conn.execute(
                    """UPDATE am_relation
                          SET target_entity_id = ?
                        WHERE relation_type='references_law'
                          AND target_entity_id = ?""",
                    (new_id, old_id),
                )
                changed += cur.rowcount
            fk_errors = conn.execute("PRAGMA foreign_key_check(am_relation)").fetchall()
            if fk_errors:
                raise RuntimeError(f"foreign_key_check failed: {fk_errors[:3]}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    after_distinct = conn.execute(
        """SELECT COUNT(DISTINCT target_entity_id)
             FROM am_relation
            WHERE relation_type='references_law'
              AND target_entity_id LIKE 'LAW-%'"""
    ).fetchone()[0]
    return {
        "law_prefix_rows_before": before_rows,
        "law_prefix_distinct_before": before_distinct,
        "mapped_distinct": len(mapping),
        "updated_rows": changed if apply else before_rows,
        "law_prefix_distinct_after": after_distinct,
    }


def build_program_law_refs(
    am_conn: sqlite3.Connection,
    jp_conn: sqlite3.Connection,
) -> list[ProgramLawRef]:
    program_ids = {
        row["unified_id"]
        for row in jp_conn.execute("SELECT unified_id FROM programs")
    }
    law_ids, lawid_to_law, title_to_law, law_source_urls = _jpintel_law_indexes(jp_conn)
    am_law_to_law = _am_law_to_law_index(
        am_conn,
        lawid_to_law=lawid_to_law,
        title_to_law=title_to_law,
    )
    now = datetime.now(UTC).isoformat(timespec="seconds")
    refs: dict[tuple[str, str, str, str], ProgramLawRef] = {}
    rows = am_conn.execute(
        """SELECT r.source_entity_id, r.target_entity_id, r.target_raw,
                  r.confidence, e.source_url, e.fetched_at, m.jpi_unified_id
             FROM am_relation r
             JOIN entity_id_map m ON m.am_canonical_id = r.source_entity_id
        LEFT JOIN am_entities e ON e.canonical_id = r.source_entity_id
            WHERE r.relation_type='references_law'
              AND r.source_entity_id LIKE 'program:%'
              AND m.jpi_unified_id LIKE 'UNI-%'"""
    )
    for row in rows:
        program_id = row["jpi_unified_id"]
        if program_id not in program_ids:
            continue
        law_id = None
        target_id = row["target_entity_id"] or ""
        if target_id.startswith("LAW-") and target_id in law_ids:
            law_id = target_id
        elif target_id.startswith("law:"):
            law_id = am_law_to_law.get(target_id)
        if law_id is None and row["target_raw"]:
            law_id = title_to_law.get(normalize_law_prefix(row["target_raw"]))
        if law_id is None or law_id not in law_ids:
            continue

        source_url = row["source_url"] or law_source_urls.get(law_id) or ""
        if not source_url:
            continue
        confidence = float(row["confidence"] or 0.75)
        confidence = max(0.0, min(confidence, 1.0))
        ref = ProgramLawRef(
            program_unified_id=program_id,
            law_unified_id=law_id,
            ref_kind="reference",
            article_citation="",
            source_url=source_url,
            fetched_at=row["fetched_at"] or now,
            confidence=confidence,
        )
        key = (
            ref.program_unified_id,
            ref.law_unified_id,
            ref.ref_kind,
            ref.article_citation,
        )
        prev = refs.get(key)
        if prev is None or ref.confidence > prev.confidence:
            refs[key] = ref
    return sorted(refs.values(), key=lambda r: (r.program_unified_id, r.law_unified_id))


def insert_program_law_refs(
    conn: sqlite3.Connection,
    refs: Iterable[ProgramLawRef],
    *,
    apply: bool,
) -> dict[str, int]:
    before = conn.execute("SELECT COUNT(*) FROM program_law_refs").fetchone()[0]
    refs = list(refs)
    inserted = 0
    if apply and refs:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for ref in refs:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO program_law_refs
                       (program_unified_id, law_unified_id, ref_kind,
                        article_citation, source_url, fetched_at, confidence)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        ref.program_unified_id,
                        ref.law_unified_id,
                        ref.ref_kind,
                        ref.article_citation,
                        ref.source_url,
                        ref.fetched_at,
                        ref.confidence,
                    ),
                )
                inserted += cur.rowcount
            fk_errors = conn.execute(
                "PRAGMA foreign_key_check(program_law_refs)"
            ).fetchall()
            if fk_errors:
                raise RuntimeError(f"foreign_key_check failed: {fk_errors[:3]}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    after = conn.execute("SELECT COUNT(*) FROM program_law_refs").fetchone()[0]
    return {
        "program_law_refs_before": before,
        "candidate_refs": len(refs),
        "inserted_refs": inserted,
        "program_law_refs_after": after,
    }


def run(
    *,
    autonomath_db: Path,
    jpintel_db: Path,
    apply: bool,
) -> dict[str, Any]:
    with _connect(autonomath_db) as am_conn, _connect(jpintel_db) as jp_conn:
        am_summary = reconcile_am_relation_targets(am_conn, apply=apply)
        refs = build_program_law_refs(am_conn, jp_conn)
        plr_summary = insert_program_law_refs(jp_conn, refs, apply=apply)
        return {
            "mode": "apply" if apply else "dry_run",
            "autonomath_db": str(autonomath_db),
            "jpintel_db": str(jpintel_db),
            **am_summary,
            **plr_summary,
            "sample_refs": [asdict(ref) for ref in refs[:5]],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--autonomath-db", type=Path, default=AUTONOMATH_DB)
    parser.add_argument("--jpintel-db", type=Path, default=JPINTEL_DB)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    summary = run(
        autonomath_db=args.autonomath_db,
        jpintel_db=args.jpintel_db,
        apply=args.apply,
    )
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        for key, value in summary.items():
            if key != "sample_refs":
                print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
