"""refresh_fact_signatures_v2 — Dim F bulk re-signature ETL.

Wave 46 dim 19 SFGH booster (2026-05-12)
========================================

Bulk refresh path that COMPLEMENTS the weekly cron at
``scripts/cron/refresh_fact_signatures_weekly.py``. Where the cron
walks every ``extracted_fact`` row to detect pending re-signs, this
ETL exposes a subject-scoped bulk refresh so an ops user can re-sign
all facts attached to one ``subject_kind`` + ``subject_id`` pair in
a single transaction (e.g. after a corpus migration that touched all
facts about a particular houjin_id).

This is a thin orchestration shim: it re-uses ``_canonical_payload``,
``_load_private_key`` and ``_sign_and_upsert`` from the weekly cron
so the canonical byte form NEVER diverges between the two paths.

CLI
---
    python scripts/etl/refresh_fact_signatures_v2.py \
        --subject-kind houjin --subject-id 1234567890123 \
        [--max-rows N] [--dry-run]

Constraints
-----------
* **NO LLM call.** Pure cryptography stdlib Ed25519 + SQLite UPSERT,
  same constraint as the weekly cron.
* **Idempotent.** Re-running on a converged subject yields zero writes.
* **No huge-DB scan.** The subject filter is indexed on
  ``extracted_fact(subject_kind, subject_id)`` so the SELECT bounds the
  walk regardless of corpus size — sidesteps the 9.7 GB autonomath.db
  full-scan footgun (feedback_no_quick_check_on_huge_sqlite).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from typing import Any

# We re-use the canonical helpers from the weekly cron so the byte form
# of the signed payload NEVER diverges. Import is by file path because
# scripts/ is not packaged.
_HERE = os.path.dirname(os.path.abspath(__file__))
_CRON_DIR = os.path.join(os.path.dirname(_HERE), "cron")
sys.path.insert(0, _CRON_DIR)

try:
    from refresh_fact_signatures_weekly import (  # type: ignore[import-not-found]  # noqa: F401  — `_canonical_payload` re-exported for callers
        DEFAULT_KEY_ID,
        _canonical_payload,
        _current_snapshot_id,
        _load_private_key,
        _resolve_db_path,
        _sign_and_upsert,
    )
except ImportError as exc:  # pragma: no cover — fail loud at startup
    raise SystemExit(
        f"refresh_fact_signatures_v2: cannot import weekly cron helpers "
        f"({exc}); ensure refresh_fact_signatures_weekly.py is on sys.path"
    ) from exc

_log = logging.getLogger("jpcite.etl.refresh_fact_signatures_v2")

CHUNK = 5_000


def _walk_subject_facts(
    conn: sqlite3.Connection,
    subject_kind: str,
    subject_id: str,
    max_rows: int | None,
) -> list[sqlite3.Row]:
    """Indexed walk of facts under one subject pair.

    Uses the (subject_kind, subject_id) index, returns rows that EITHER
    have no signature yet OR have a stale signature (signed_at <
    last_modified). Caller iterates this once per ETL run.
    """
    pending: list[sqlite3.Row] = []
    cursor = ""
    while True:
        batch = conn.execute(
            "SELECT f.fact_id, f.subject_kind, f.subject_id, "
            "f.field_name, f.field_kind, f.value_text, f.value_number, "
            "f.value_date, f.source_document_id, f.last_modified "
            "FROM extracted_fact f "
            "LEFT JOIN am_fact_signature s ON s.fact_id = f.fact_id "
            "WHERE f.subject_kind = ? "
            "  AND f.subject_id   = ? "
            "  AND f.fact_id > ? "
            "  AND ("
            "    s.fact_id IS NULL "
            "    OR (f.last_modified IS NOT NULL "
            "        AND f.last_modified > s.signed_at)"
            "  ) "
            "ORDER BY f.fact_id ASC LIMIT ?",
            (subject_kind, subject_id, cursor, CHUNK),
        ).fetchall()
        if not batch:
            break
        pending.extend(batch)
        cursor = batch[-1]["fact_id"]
        if max_rows is not None and len(pending) >= max_rows:
            return pending[:max_rows]
    return pending


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bulk re-sign all facts under one (subject_kind, subject_id)."
    )
    parser.add_argument("--subject-kind", required=True,
                        help="e.g. houjin / program / law")
    parser.add_argument("--subject-id", required=True,
                        help="e.g. houjin_master.houjin_id (13 digit)")
    parser.add_argument("--max-rows", type=int, default=None,
                        help="cap rows processed in one run")
    parser.add_argument("--dry-run", action="store_true",
                        help="walk + sign without committing UPSERTs")
    parser.add_argument("--key-id", default=DEFAULT_KEY_ID,
                        help="key_id label for am_fact_signature column")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    db_path = _resolve_db_path()
    _log.info(
        "refresh_fact_signatures_v2: db=%s subject=(%s,%s) dry_run=%s",
        db_path, args.subject_kind, args.subject_id, args.dry_run,
    )

    private_key: Any = _load_private_key()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        snapshot_id = _current_snapshot_id(conn)
        rows = _walk_subject_facts(
            conn, args.subject_kind, args.subject_id, args.max_rows,
        )
        if not rows:
            print(json.dumps({
                "status": "ok",
                "pending": 0,
                "signed": 0,
                "subject_kind": args.subject_kind,
                "subject_id": args.subject_id,
            }))
            return 0
        signed = _sign_and_upsert(
            conn, rows, private_key, snapshot_id, args.key_id, args.dry_run,
        )
        if not args.dry_run:
            conn.commit()
        print(json.dumps({
            "status": "ok",
            "pending": len(rows),
            "signed": signed,
            "subject_kind": args.subject_kind,
            "subject_id": args.subject_id,
            "dry_run": args.dry_run,
        }))
        return 0
    except sqlite3.Error as exc:
        _log.error("DB error: %s", exc)
        return 2
    finally:
        conn.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
