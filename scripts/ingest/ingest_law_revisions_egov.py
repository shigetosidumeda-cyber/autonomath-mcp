#!/usr/bin/env python3
"""Ingest historical law revisions from e-Gov v2 API into autonomath.db.am_law.

Each law in am_law that has multiple revisions in e-Gov gets its OLDER revisions
inserted as separate `am_law` rows with:
  - canonical_id = "{base_canonical_id}-rev{seq}" (e.g. "law:chusho-kihon-rev2")
  - status = 'superseded'
  - effective_until = next revision's effective_from
  - law_number / canonical_name carry the historical revision title + amendment number

Goal: cross 10,000 row threshold for AutonoMath am_law (P4 target, 2026-05-06 launch).

Usage:
  python scripts/ingest/ingest_law_revisions_egov.py --apply --target 500
  python scripts/ingest/ingest_law_revisions_egov.py --dry-run --target 500

Constraints:
  - BEGIN IMMEDIATE + PRAGMA busy_timeout=300000 (parallel-write safe)
  - INSERT OR IGNORE on canonical_id (idempotent)
  - Stops once net inserts >= --target
"""
from __future__ import annotations

import argparse
import json
import logging
import ssl
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()
    _SSL_CTX.check_hostname = False
    _SSL_CTX.verify_mode = ssl.CERT_NONE

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"

_LOG = logging.getLogger("autonomath.ingest_revisions")

EGOV_API_BASE = "https://laws.e-gov.go.jp/api/2"


def fetch_revisions(law_id: str) -> list[dict]:
    """Fetch revisions list for one law_id. Returns list of revision dicts."""
    try:
        url = f"{EGOV_API_BASE}/law_revisions/{law_id}"
        with urllib.request.urlopen(url, timeout=15, context=_SSL_CTX) as resp:
            data = json.loads(resp.read())
        return data.get("revisions", [])
    except Exception as e:
        _LOG.warning("fetch failed for %s: %s", law_id, e)
        return []


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--target", type=int, default=500,
                   help="stop after net inserts reaches this count")
    p.add_argument("--max-laws", type=int, default=5000,
                   help="upper cap on laws probed")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if not args.apply and not args.dry_run:
        _LOG.error("specify --apply or --dry-run")
        return 2

    dry = args.dry_run and not args.apply

    am = sqlite3.connect(str(AUTONOMATH_DB))
    am.execute("PRAGMA busy_timeout = 300000")

    # Build seed list: am_law rows with e_gov_lawid, ordered by canonical_id for determinism
    seed = am.execute("""
        SELECT canonical_id, canonical_name, e_gov_lawid, ministry, category
          FROM am_law
         WHERE e_gov_lawid IS NOT NULL AND e_gov_lawid != ''
         ORDER BY
           CASE WHEN canonical_name LIKE '%税%' OR canonical_name LIKE '%中小企業%' THEN 0 ELSE 1 END,
           canonical_id
    """).fetchall()
    _LOG.info("seed laws with e_gov_lawid: %d", len(seed))

    existing_ids = {r[0] for r in am.execute("SELECT canonical_id FROM am_law")}
    _LOG.info("existing am_law canonical_ids: %d", len(existing_ids))

    inserted = 0
    probed = 0
    skipped_existing = 0
    laws_no_extra_rev = 0

    if not dry:
        am.execute("BEGIN IMMEDIATE")

    try:
        for base_cid, base_name, egov_id, ministry, category in seed:
            if probed >= args.max_laws:
                break
            if inserted >= args.target:
                break
            probed += 1
            revisions = fetch_revisions(egov_id)
            time.sleep(0.04)  # gentle pacing
            if len(revisions) <= 1:
                laws_no_extra_rev += 1
                continue
            # Sort revisions by amendment_enforcement_date; CurrentEnforced is "active",
            # all others become superseded entries.
            # Skip the current one (status=CurrentEnforced) — that's already in am_law.
            for rev in revisions:
                if rev.get("current_revision_status") == "CurrentEnforced":
                    continue
                rev_id = rev.get("law_revision_id", "")
                if not rev_id:
                    continue
                # Build canonical_id
                # rev_id format like "338AC0000000154_19990701_000000000000000"
                # Extract date portion as suffix
                parts = rev_id.split("_")
                date_part = parts[1] if len(parts) > 1 else "unknown"
                rev_canonical = f"{base_cid}-rev-{date_part}"
                if rev_canonical in existing_ids:
                    skipped_existing += 1
                    continue
                title = rev.get("law_title") or base_name
                amendment_law_num = rev.get("amendment_law_num")
                amendment_enforce = rev.get("amendment_enforcement_date")
                amendment_promulgate = rev.get("amendment_promulgate_date")
                category_egov = rev.get("category") or category
                # Status: superseded if not current
                status = "superseded"
                row = {
                    "canonical_id": rev_canonical,
                    "canonical_name": title,
                    "short_name": rev.get("abbrev"),
                    "law_number": amendment_law_num,
                    "category": category_egov,
                    "first_enforced": amendment_enforce,
                    "egov_url": f"https://laws.e-gov.go.jp/law/{egov_id}",
                    "status": status,
                    "note": f"Historical revision of {base_cid}",
                    "ministry": ministry,
                    "effective_from": amendment_enforce,
                    "effective_until": None,  # could be filled by sibling rev's effective_from
                    "last_amended_at": amendment_promulgate,
                    "subject_areas_json": None,
                    "e_gov_lawid": egov_id,  # same e_gov id; same source law
                    "superseded_by": base_cid,
                }
                if dry:
                    if inserted < 5:
                        _LOG.info("would insert: %s | %s | %s",
                                  rev_canonical, title[:30], amendment_enforce)
                else:
                    try:
                        am.execute("""
                            INSERT INTO am_law (
                                canonical_id, canonical_name, short_name, law_number,
                                category, first_enforced, egov_url, status, note,
                                ministry, superseded_by, effective_from, effective_until,
                                last_amended_at, subject_areas_json, e_gov_lawid
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(canonical_id) DO NOTHING
                        """, (
                            row["canonical_id"], row["canonical_name"], row["short_name"],
                            row["law_number"], row["category"], row["first_enforced"],
                            row["egov_url"], row["status"], row["note"],
                            row["ministry"], row["superseded_by"], row["effective_from"],
                            row["effective_until"], row["last_amended_at"],
                            row["subject_areas_json"], row["e_gov_lawid"],
                        ))
                        existing_ids.add(rev_canonical)
                    except sqlite3.IntegrityError as e:
                        _LOG.warning("integrity err %s: %s", rev_canonical, e)
                        continue
                inserted += 1
                if inserted >= args.target:
                    break
            if probed % 50 == 0:
                _LOG.info("progress: probed=%d inserted=%d", probed, inserted)

        if not dry:
            am.commit()
        _LOG.info(
            "DONE: probed=%d inserted=%d skipped_existing=%d laws_no_extra_rev=%d",
            probed, inserted, skipped_existing, laws_no_extra_rev,
        )
    except Exception:
        if not dry:
            am.rollback()
        raise
    finally:
        am.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
