#!/usr/bin/env python3
"""Wave 35 Axis 5 — review queue exporter + promote tool.

Operator workflow:
  1. --export → CSV of pending translation candidates.
  2. Operator inspects rows + edits `operator_decision` column to
     'promote' or 'reject'.
  3. --import → applies decisions back into DB; 'promote' writes
     candidate text into body_<lang> column.

ABSOLUTE: never auto-translate. Operator decision required.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent

LOG = logging.getLogger("translate_review_queue")
DEFAULT_AUTONOMATH_DB = os.environ.get(
    "AUTONOMATH_DB_PATH", str(_REPO / "autonomath.db"))
DEFAULT_JPINTEL_DB = os.environ.get(
    "JPINTEL_DB_PATH", str(_REPO / "data" / "jpintel.db"))

CSV_COLUMNS = (
    "source_db", "queue_id", "target_kind", "canonical_or_unified_id",
    "article_id", "target_lang", "field_name", "candidate_text",
    "candidate_source_url", "candidate_license", "similarity_score",
    "model_name", "operator_decision", "operator_notes",
)


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ")


def _export_autonomath(conn: sqlite3.Connection) -> list[dict]:
    try:
        rows = list(conn.execute(
            "SELECT queue_id, target_kind, canonical_id, article_id, "
            "       target_lang, field_name, candidate_text, "
            "       candidate_source_url, candidate_license, "
            "       similarity_score, model_name, operator_decision, "
            "       operator_notes "
            "FROM am_law_translation_review_queue "
            "WHERE operator_decision IS NULL OR operator_decision = 'pending'"
        ))
    except sqlite3.Error as exc:
        LOG.warning("autonomath export failed: %s", exc)
        return []
    out = []
    for r in rows:
        out.append({
            "source_db": "autonomath",
            "queue_id": r["queue_id"],
            "target_kind": r["target_kind"],
            "canonical_or_unified_id": r["canonical_id"],
            "article_id": r["article_id"] or "",
            "target_lang": r["target_lang"],
            "field_name": r["field_name"],
            "candidate_text": (r["candidate_text"] or "")[:4000],
            "candidate_source_url": r["candidate_source_url"] or "",
            "candidate_license": r["candidate_license"] or "",
            "similarity_score": r["similarity_score"] or "",
            "model_name": r["model_name"] or "",
            "operator_decision": r["operator_decision"] or "pending",
            "operator_notes": r["operator_notes"] or "",
        })
    return out


def _export_jpintel(conn: sqlite3.Connection) -> list[dict]:
    try:
        rows = list(conn.execute(
            "SELECT queue_id, unified_id, target_lang, field_name, "
            "       candidate_text, candidate_source_url, "
            "       candidate_license, similarity_score, model_name, "
            "       operator_decision, operator_notes "
            "FROM programs_translation_review_queue "
            "WHERE operator_decision IS NULL OR operator_decision = 'pending'"
        ))
    except sqlite3.Error as exc:
        LOG.warning("jpintel export failed: %s", exc)
        return []
    out = []
    for r in rows:
        out.append({
            "source_db": "jpintel",
            "queue_id": r["queue_id"],
            "target_kind": "program",
            "canonical_or_unified_id": r["unified_id"],
            "article_id": "",
            "target_lang": r["target_lang"],
            "field_name": r["field_name"],
            "candidate_text": (r["candidate_text"] or "")[:4000],
            "candidate_source_url": r["candidate_source_url"] or "",
            "candidate_license": r["candidate_license"] or "",
            "similarity_score": r["similarity_score"] or "",
            "model_name": r["model_name"] or "",
            "operator_decision": r["operator_decision"] or "pending",
            "operator_notes": r["operator_notes"] or "",
        })
    return out


def cmd_export(args: argparse.Namespace) -> int:
    aconn = _connect(args.autonomath_db) if Path(args.autonomath_db).exists() else None
    jconn = _connect(args.jpintel_db) if Path(args.jpintel_db).exists() else None
    rows: list[dict] = []
    if aconn is not None:
        rows.extend(_export_autonomath(aconn))
        aconn.close()
    if jconn is not None:
        rows.extend(_export_jpintel(jconn))
        jconn.close()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print(json.dumps({"ok": True, "exported": len(rows), "out": str(out_path)}))
    return 0


def _apply_autonomath(conn: sqlite3.Connection, row: dict, decision: str) -> None:
    qid = row["queue_id"]
    now = _now()
    conn.execute(
        "UPDATE am_law_translation_review_queue "
        "SET operator_decision = ?, operator_decision_at = ?, operator_notes = ? "
        "WHERE queue_id = ?",
        (decision, now, row.get("operator_notes", ""), qid),
    )
    if decision != "promote":
        return
    lang = row["target_lang"]
    if lang not in ("en", "zh", "ko"):
        return
    kind = row["target_kind"]
    canonical = row["canonical_or_unified_id"]
    text = row["candidate_text"]
    src_url = row["candidate_source_url"]
    if kind == "law":
        col = f"body_{lang}"
        url_col = f"body_{lang}_source_url"
        fetched_col = f"body_{lang}_fetched_at"
        conn.execute(
            f"UPDATE am_law SET {col} = ?, {url_col} = ?, {fetched_col} = ? "
            f"WHERE canonical_id = ?",
            (text, src_url, now, canonical),
        )
    elif kind == "article":
        try:
            aid = int(row.get("article_id") or 0)
        except (TypeError, ValueError):
            return
        col = f"body_{lang}"
        url_col = f"body_{lang}_source_url"
        fetched_col = f"body_{lang}_fetched_at"
        conn.execute(
            f"UPDATE am_law_article SET {col} = ?, {url_col} = ?, {fetched_col} = ? "
            f"WHERE article_id = ?",
            (text, src_url, now, aid),
        )


def _apply_jpintel(conn: sqlite3.Connection, row: dict, decision: str) -> None:
    qid = row["queue_id"]
    now = _now()
    conn.execute(
        "UPDATE programs_translation_review_queue "
        "SET operator_decision = ?, operator_decision_at = ?, operator_notes = ? "
        "WHERE queue_id = ?",
        (decision, now, row.get("operator_notes", ""), qid),
    )
    if decision != "promote":
        return
    unified = row["canonical_or_unified_id"]
    field = row["field_name"]
    text = row["candidate_text"]
    src_url = row["candidate_source_url"]
    col_map = {"title": "title_en", "summary": "summary_en", "eligibility": "eligibility_en"}
    col = col_map.get(field)
    if col is None:
        return
    conn.execute(
        f"UPDATE programs SET {col} = ?, source_url_en = ?, "
        f"translation_fetched_at = ?, translation_status = 'partial' "
        f"WHERE unified_id = ?",
        (text, src_url, now, unified),
    )


def cmd_import(args: argparse.Namespace) -> int:
    in_path = Path(args.in_path)
    if not in_path.exists():
        print(json.dumps({"ok": False, "error": "input file missing"}))
        return 2
    aconn = _connect(args.autonomath_db) if Path(args.autonomath_db).exists() else None
    jconn = _connect(args.jpintel_db) if Path(args.jpintel_db).exists() else None
    promoted = {"autonomath": 0, "jpintel": 0}
    rejected = {"autonomath": 0, "jpintel": 0}
    with in_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            decision = (row.get("operator_decision") or "").strip()
            if decision not in ("promote", "reject"):
                continue
            src = row.get("source_db", "")
            if src == "autonomath" and aconn is not None:
                _apply_autonomath(aconn, row, decision)
                if decision == "promote":
                    promoted["autonomath"] += 1
                else:
                    rejected["autonomath"] += 1
            elif src == "jpintel" and jconn is not None:
                _apply_jpintel(jconn, row, decision)
                if decision == "promote":
                    promoted["jpintel"] += 1
                else:
                    rejected["jpintel"] += 1
    if aconn is not None:
        aconn.commit()
        aconn.close()
    if jconn is not None:
        jconn.commit()
        jconn.close()
    print(json.dumps({"ok": True, "promoted": promoted, "rejected": rejected}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--autonomath-db", default=DEFAULT_AUTONOMATH_DB)
    parser.add_argument("--jpintel-db", default=DEFAULT_JPINTEL_DB)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--export", action="store_true")
    group.add_argument("--import", dest="do_import", action="store_true")
    parser.add_argument("--out", default="/tmp/translate_review.csv")
    parser.add_argument("--in", dest="in_path", default="/tmp/translate_review.csv")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    if args.export:
        return cmd_export(args)
    if args.do_import:
        return cmd_import(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
