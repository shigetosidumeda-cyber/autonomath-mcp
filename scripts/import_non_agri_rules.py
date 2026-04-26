"""Import non-agri exclusion rules into data/jpintel.db.

Reads research/non_agri_matched.json and INSERT OR IGNOREs the subset where
BOTH program_a and program_b have match confidence >= 0.7 AND both reference
real unified_ids (i.e., not placeholder condition tags).

Idempotent: re-running does not duplicate because rule_id is the PRIMARY KEY
and we use INSERT OR IGNORE.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "jpintel.db"
MATCHED_PATH = ROOT / "research" / "non_agri_matched.json"

CONFIDENCE_THRESHOLD = 0.7


def main() -> int:
    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}", file=sys.stderr)
        return 1
    if not MATCHED_PATH.exists():
        print(
            f"matched file not found: {MATCHED_PATH}\n"
            "Run scripts/match_non_agri_ids.py first.",
            file=sys.stderr,
        )
        return 1

    rules = json.loads(MATCHED_PATH.read_text(encoding="utf-8"))
    print(f"loaded {len(rules)} rules from {MATCHED_PATH}")

    conn = sqlite3.connect(str(DB_PATH))
    try:
        # Validate exclusion_rules exists
        (tbl,) = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='exclusion_rules'"
        ).fetchone()
        if not tbl:
            print("exclusion_rules table missing — run migrations first", file=sys.stderr)
            return 1

        (before_count,) = conn.execute(
            "SELECT COUNT(*) FROM exclusion_rules"
        ).fetchone()
        print(f"exclusion_rules rows before: {before_count}")

        # Build set of valid unified_ids for a sanity check
        valid_uids = {
            row[0]
            for row in conn.execute("SELECT unified_id FROM programs").fetchall()
        }

        imported = 0
        skipped_low_conf = 0
        skipped_not_uid = 0
        skipped_missing_in_db = 0
        skipped_self_mutex = 0
        already_present = 0

        for rule in rules:
            rule_id = rule.get("rule_id")
            if not rule_id:
                continue

            a = rule.get("program_a")
            b = rule.get("program_b")
            conf_a = float(rule.get("match_confidence_a") or 0.0)
            conf_b = float(rule.get("match_confidence_b") or 0.0)

            if conf_a < CONFIDENCE_THRESHOLD or conf_b < CONFIDENCE_THRESHOLD:
                skipped_low_conf += 1
                continue

            # Both must look like UNI-xxx unified_ids (direct/keyword/fuzzy all
            # leave the program_a/program_b populated with a UNI-xxx string)
            if not (isinstance(a, str) and isinstance(b, str)):
                skipped_not_uid += 1
                continue
            if not (a.startswith("UNI-") and b.startswith("UNI-")):
                skipped_not_uid += 1
                continue

            if a not in valid_uids or b not in valid_uids:
                skipped_missing_in_db += 1
                continue

            # Skip self-mutex (A == B). These are same-program sub-frame mutexes
            # that cannot be represented in the current 2-column schema without
            # firing on single-program selection. Defer to W3 schema extension.
            if a == b:
                skipped_self_mutex += 1
                continue

            # Check existing
            (exists,) = conn.execute(
                "SELECT COUNT(*) FROM exclusion_rules WHERE rule_id = ?",
                (rule_id,),
            ).fetchone()
            if exists:
                already_present += 1
                continue

            # Build a clean extra_json: merge original extra_json with match metadata
            extra = dict(rule.get("extra_json") or {})
            extra["match_confidence_a"] = conf_a
            extra["match_confidence_b"] = conf_b
            extra["match_method_a"] = rule.get("match_method_a")
            extra["match_method_b"] = rule.get("match_method_b")
            extra["source"] = "non_agri_draft_2026_04_22"

            program_b_group_json = rule.get("program_b_group_json") or []
            source_urls_json = rule.get("source_urls_json") or []

            conn.execute(
                """INSERT OR IGNORE INTO exclusion_rules(
                    rule_id, kind, severity, program_a, program_b,
                    program_b_group_json, description, source_notes,
                    source_urls_json, extra_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    rule_id,
                    rule.get("kind") or "absolute",
                    rule.get("severity") or "critical",
                    a,
                    b,
                    json.dumps(program_b_group_json, ensure_ascii=False),
                    rule.get("description") or "",
                    rule.get("source_notes") or "",
                    json.dumps(source_urls_json, ensure_ascii=False),
                    json.dumps(extra, ensure_ascii=False),
                ),
            )
            imported += 1

        conn.commit()

        (after_count,) = conn.execute(
            "SELECT COUNT(*) FROM exclusion_rules"
        ).fetchone()

        print()
        print(f"imported:                 {imported}")
        print(f"already present (skip):   {already_present}")
        print(f"skipped (low confidence): {skipped_low_conf}")
        print(f"skipped (not UNI-xxx):    {skipped_not_uid}")
        print(f"skipped (uid not in DB):  {skipped_missing_in_db}")
        print(f"skipped (self-mutex A=B): {skipped_self_mutex}")
        print()
        print(f"exclusion_rules rows after: {after_count} (delta +{after_count - before_count})")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
