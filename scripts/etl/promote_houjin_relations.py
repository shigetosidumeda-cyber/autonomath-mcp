#!/usr/bin/env python3
"""Promote raw_json.houjin_bangou into corporate-entity graph edges.

A2 schema-compatible interpretation:

* Current ``am_relation`` has no ``source_kind`` / ``target_kind`` columns.
* Corporate typing is represented by the target node
  ``am_entities(record_kind='corporate_entity', canonical_id='houjin:<13d>')``.
* Each non-corporate entity carrying ``raw_json.houjin_bangou`` gets a
  deterministic ``related`` edge to that corporate node.

No network. No LLM. Re-runnable through ``ux_am_relation_harvest``.
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
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
_HOUJIN_RE = re.compile(r"^\d{13}$")


@dataclass(frozen=True)
class HoujinEdge:
    source_entity_id: str
    target_entity_id: str
    target_raw: str
    relation_type: str
    confidence: float
    source_field: str


def normalize_houjin_bangou(value: Any) -> str | None:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if text.startswith("T") and len(text) >= 14:
        text = text[1:]
    digits = "".join(ch for ch in text if ch.isdigit())
    if _HOUJIN_RE.match(digits):
        return digits
    return None


def extract_houjin_bangou(raw_json: str | None) -> str | None:
    try:
        data = json.loads(raw_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    for key in (
        "houjin_bangou",
        "recipient_houjin_bangou",
        "corporate_number",
        "invoice_registration_number",
        "t_number",
    ):
        value = data.get(key)
        if value:
            bangou = normalize_houjin_bangou(value)
            if bangou:
                return bangou
    return None


def collect_houjin_edges(conn: sqlite3.Connection) -> list[HoujinEdge]:
    corporate_ids = {
        row["canonical_id"]
        for row in conn.execute(
            """SELECT canonical_id
                 FROM am_entities
                WHERE record_kind='corporate_entity'
                  AND canonical_id LIKE 'houjin:%'"""
        )
    }
    edges: dict[tuple[str, str], HoujinEdge] = {}
    rows = conn.execute(
        """SELECT canonical_id, raw_json
             FROM am_entities
            WHERE record_kind != 'corporate_entity'
              AND raw_json LIKE '%houjin_bangou%'"""
    )
    for row in rows:
        bangou = extract_houjin_bangou(row["raw_json"])
        if bangou is None:
            continue
        target_id = f"houjin:{bangou}"
        if target_id not in corporate_ids:
            continue
        source_id = row["canonical_id"]
        if source_id == target_id:
            continue
        edges[(source_id, target_id)] = HoujinEdge(
            source_entity_id=source_id,
            target_entity_id=target_id,
            target_raw=bangou,
            relation_type="related",
            confidence=0.95,
            source_field="harvest:raw_json.houjin_bangou",
        )
    return sorted(edges.values(), key=lambda e: (e.source_entity_id, e.target_entity_id))


def existing_houjin_edge_count(conn: sqlite3.Connection) -> int:
    return conn.execute(
        """SELECT COUNT(*)
             FROM am_relation r
             JOIN am_entities t ON t.canonical_id = r.target_entity_id
            WHERE t.record_kind='corporate_entity'"""
    ).fetchone()[0]


def insert_edges(
    conn: sqlite3.Connection,
    edges: list[HoujinEdge],
    *,
    apply: bool,
) -> dict[str, int]:
    before = existing_houjin_edge_count(conn)
    inserted = 0
    skipped = 0
    if apply and edges:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        conn.execute("BEGIN IMMEDIATE")
        try:
            for edge in edges:
                try:
                    cur = conn.execute(
                        """INSERT INTO am_relation
                           (source_entity_id, target_entity_id, target_raw,
                            relation_type, confidence, origin, source_field,
                            harvested_at)
                           VALUES (?, ?, ?, ?, ?, 'harvest', ?, ?)""",
                        (
                            edge.source_entity_id,
                            edge.target_entity_id,
                            edge.target_raw,
                            edge.relation_type,
                            edge.confidence,
                            edge.source_field,
                            now,
                        ),
                    )
                    inserted += cur.rowcount
                except sqlite3.IntegrityError as exc:
                    if "UNIQUE" in str(exc):
                        skipped += 1
                    else:
                        raise
            fk_errors = conn.execute("PRAGMA foreign_key_check(am_relation)").fetchall()
            if fk_errors:
                raise RuntimeError(f"foreign_key_check failed: {fk_errors[:3]}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    after = existing_houjin_edge_count(conn)
    return {
        "corporate_edge_count_before": before,
        "candidate_edges": len(edges),
        "inserted_edges": inserted,
        "skipped_duplicates": skipped,
        "corporate_edge_count_after": after,
    }


def run(*, db_path: Path, apply: bool) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        edges = collect_houjin_edges(conn)
        summary = insert_edges(conn, edges, apply=apply)
        return {
            "mode": "apply" if apply else "dry_run",
            "db": str(db_path),
            **summary,
            "sample_edges": [asdict(edge) for edge in edges[:5]],
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=AUTONOMATH_DB)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    summary = run(db_path=args.db, apply=args.apply)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        for key, value in summary.items():
            if key != "sample_edges":
                print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
