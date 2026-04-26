#!/usr/bin/env python3
"""Sync autonomath.db am_entities (record_kind='adoption') -> jpintel.db adoption_records.

Also populates jpintel.db houjin_master for any unseen houjin_bangou.

Usage:
    python scripts/sync/sync_adoption_am_to_jpintel.py \
        --source /Users/shigetoumeda/jpintel-mcp/autonomath.db \
        --target /Users/shigetoumeda/jpintel-mcp/data/jpintel.db \
        [--batch 10000] [--dry-run]

Notes:
- autonomath.db is opened read-only (URI immutable=0&mode=ro so WAL concurrency OK).
- jpintel.db is opened writable with busy_timeout=300000 and BEGIN IMMEDIATE
  so concurrent writers (launch CLI) wait politely.
- FK to houjin_master enforced in target schema. We pre-populate houjin_master
  for any missing houjin_bangou using corporate_entity rows first,
  then fall back to company_name from the adoption row itself.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

# -------------------- helpers --------------------

HB_RE = re.compile(r"^\d{13}$")


def norm_hb(raw: Any) -> str | None:
    """Return 13-digit houjin_bangou or None."""
    if raw is None:
        return None
    s = str(raw).strip()
    s = s.replace("-", "").replace(" ", "").replace("　", "")
    if HB_RE.match(s):
        return s
    return None


def safe_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None


def pick(d: dict, *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


# -------------------- main --------------------


def build_houjin_master_from_corporate(src: sqlite3.Connection) -> dict[str, dict]:
    """Load corporate_entity rows into a hb -> row dict."""
    out: dict[str, dict] = {}
    cur = src.execute(
        """
        SELECT primary_name, raw_json, source_url, fetched_at
          FROM am_entities
         WHERE record_kind = 'corporate_entity'
        """
    )
    n = 0
    for primary_name, raw_json, source_url, fetched_at in cur:
        try:
            j = json.loads(raw_json) if raw_json else {}
        except Exception:
            continue
        hb = norm_hb(j.get("houjin_bangou"))
        if not hb:
            continue
        out[hb] = {
            "primary_name": primary_name or j.get("name") or hb,
            "prefecture": j.get("prefecture_name") or j.get("prefecture"),
            "municipality": j.get("municipality"),
            "corporation_type": j.get("corporation_type") or j.get("category"),
            "source_url": source_url or j.get("source_url"),
            "fetched_at": fetched_at or j.get("fetched_at") or j.get("certified_at"),
        }
        n += 1
    print(f"[corp] loaded {n} corporate_entity rows with valid houjin_bangou", flush=True)
    return out


def run(src_path: Path, tgt_path: Path, batch: int, dry_run: bool) -> int:
    t0 = time.time()

    # source: read-only
    src_uri = f"file:{src_path}?mode=ro"
    src = sqlite3.connect(src_uri, uri=True, timeout=60.0)
    src.execute("PRAGMA temp_store=MEMORY")
    src.row_factory = None

    # target: writable
    tgt = sqlite3.connect(str(tgt_path), timeout=60.0, isolation_level=None)
    tgt.execute("PRAGMA busy_timeout=300000")
    tgt.execute("PRAGMA foreign_keys=ON")
    tgt.execute("PRAGMA temp_store=MEMORY")
    tgt.execute("PRAGMA synchronous=NORMAL")

    # Pre-load corporate_entity map (needed to fill houjin_master)
    corp_map = build_houjin_master_from_corporate(src)

    # Already-present houjin_master (fast skip)
    existing_hb: set[str] = {
        r[0] for r in tgt.execute("SELECT houjin_bangou FROM houjin_master")
    }
    print(f"[tgt] existing houjin_master rows = {len(existing_hb)}", flush=True)

    initial_adoption = tgt.execute("SELECT COUNT(*) FROM adoption_records").fetchone()[0]
    print(f"[tgt] initial adoption_records rows = {initial_adoption}", flush=True)

    # Count total adoption candidates (for progress)
    total_adoption = src.execute(
        """
        SELECT COUNT(*) FROM am_entities
         WHERE record_kind='adoption'
           AND length(json_extract(raw_json, '$.houjin_bangou'))=13
        """
    ).fetchone()[0]
    print(f"[src] adoption candidates (13-digit hb) = {total_adoption}", flush=True)

    # Iterate (stream via rowid for memory safety)
    cur = src.execute(
        """
        SELECT canonical_id, primary_name, source_url, fetched_at, raw_json
          FROM am_entities
         WHERE record_kind='adoption'
           AND length(json_extract(raw_json, '$.houjin_bangou'))=13
        """
    )

    inserted_adoption = 0
    inserted_houjin = 0
    skipped_bad_hb = 0
    skipped_missing = 0
    errors = 0

    # target prepared statements
    insert_hm_sql = """
        INSERT OR IGNORE INTO houjin_master (
            houjin_bangou, normalized_name, prefecture, municipality,
            corporation_type, data_sources_json, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    insert_adoption_sql = """
        INSERT INTO adoption_records (
            houjin_bangou, program_id_hint, program_name_raw, company_name_raw,
            round_label, round_number, announced_at, prefecture, municipality,
            project_title, industry_raw, industry_jsic_medium,
            amount_granted_yen, amount_project_total_yen,
            source_url, source_pdf_page, fetched_at, confidence
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """

    if dry_run:
        print("[dry-run] no writes will be committed", flush=True)

    now_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Batch writer
    hm_batch: list[tuple] = []
    ad_batch: list[tuple] = []

    def flush() -> None:
        nonlocal inserted_houjin, inserted_adoption
        if not hm_batch and not ad_batch:
            return
        if dry_run:
            hm_batch.clear()
            ad_batch.clear()
            return
        tgt.execute("BEGIN IMMEDIATE")
        try:
            if hm_batch:
                tgt.executemany(insert_hm_sql, hm_batch)
                inserted_houjin += tgt.total_changes  # approximated below
            if ad_batch:
                before = tgt.execute("SELECT COUNT(*) FROM adoption_records").fetchone()[0]
                tgt.executemany(insert_adoption_sql, ad_batch)
                after = tgt.execute("SELECT COUNT(*) FROM adoption_records").fetchone()[0]
                inserted_adoption += (after - before)
            tgt.execute("COMMIT")
        except Exception:
            tgt.execute("ROLLBACK")
            raise
        hm_batch.clear()
        ad_batch.clear()

    seen = 0
    batch_hb_staged: set[str] = set()

    for canonical_id, primary_name, src_source_url, src_fetched_at, raw_json in cur:
        seen += 1
        try:
            j = json.loads(raw_json) if raw_json else {}
        except Exception:
            errors += 1
            continue

        hb = norm_hb(j.get("houjin_bangou"))
        if not hb:
            skipped_bad_hb += 1
            continue

        # Ensure houjin_master has this row
        if hb not in existing_hb and hb not in batch_hb_staged:
            corp = corp_map.get(hb)
            if corp:
                nname = corp["primary_name"]
                pref = corp.get("prefecture")
                muni = corp.get("municipality")
                ctype = corp.get("corporation_type")
                hm_src_url = corp.get("source_url") or ""
                hm_fetched = corp.get("fetched_at") or now_ts
                src_tag = "autonomath:corporate_entity"
            else:
                # Synthesize from adoption row
                nname = j.get("company_name") or primary_name or hb
                pref = j.get("prefecture")
                muni = j.get("municipality")
                ctype = None
                hm_src_url = j.get("source_url") or src_source_url or ""
                hm_fetched = j.get("fetched_at") or src_fetched_at or now_ts
                src_tag = "autonomath:adoption"
            hm_batch.append(
                (
                    hb,
                    (nname or hb)[:500],
                    pref,
                    muni,
                    ctype,
                    json.dumps([src_tag], ensure_ascii=False),
                    hm_fetched,
                )
            )
            batch_hb_staged.add(hb)

        # Build adoption row
        program_id_hint = j.get("program_id_hint")
        program_name_raw = j.get("program_name")
        company_name_raw = j.get("company_name") or primary_name
        round_label = j.get("round_label")
        round_number = safe_int(j.get("round_number"))
        announced_at = j.get("announced_at")
        prefecture = j.get("prefecture")
        municipality = j.get("municipality")
        project_title = j.get("project_title") or j.get("summary")
        industry_raw = j.get("industry_raw")
        industry_jsic_medium = (
            j.get("industry_jsic_medium")
            or j.get("industry_jsic_inferred")
        )
        amount_granted_yen = safe_int(j.get("amount_granted_yen"))
        amount_project_total_yen = safe_int(
            j.get("amount_project_total_yen") or j.get("project_total_yen")
        )
        source_url = j.get("source_url") or src_source_url or ""
        source_pdf_page = j.get("source_pdf_page")
        fetched_at = j.get("fetched_at") or src_fetched_at or now_ts
        confidence = j.get("confidence")
        try:
            confidence = float(confidence) if confidence is not None else 0.85
        except (TypeError, ValueError):
            confidence = 0.85

        if not source_url:
            # source_url is NOT NULL; tag with canonical_id-based synthetic
            source_url = f"autonomath://{canonical_id}"

        ad_batch.append(
            (
                hb,
                program_id_hint,
                program_name_raw,
                company_name_raw,
                round_label,
                round_number,
                announced_at,
                prefecture,
                municipality,
                project_title,
                industry_raw,
                industry_jsic_medium,
                amount_granted_yen,
                amount_project_total_yen,
                source_url,
                source_pdf_page,
                fetched_at,
                confidence,
            )
        )

        if len(ad_batch) >= batch:
            flush()
            # mark those HBs as existing for future iterations in this run
            existing_hb |= batch_hb_staged
            batch_hb_staged.clear()
            pct = seen * 100.0 / max(total_adoption, 1)
            dt = time.time() - t0
            print(
                f"[sync] seen={seen}/{total_adoption} ({pct:.1f}%) "
                f"inserted_ad={inserted_adoption} inserted_hm={inserted_houjin} "
                f"bad_hb={skipped_bad_hb} errors={errors} elapsed={dt:.1f}s",
                flush=True,
            )

    # final flush
    flush()
    existing_hb |= batch_hb_staged

    final_adoption = tgt.execute("SELECT COUNT(*) FROM adoption_records").fetchone()[0]
    final_houjin = tgt.execute("SELECT COUNT(*) FROM houjin_master").fetchone()[0]
    inserted_adoption = final_adoption - initial_adoption
    inserted_houjin = final_houjin - len({h for h in existing_hb if False})  # placeholder; computed below

    # recompute inserted_houjin vs pre
    initial_hb_count = len(
        set(
            r[0]
            for r in tgt.execute(
                "SELECT houjin_bangou FROM houjin_master LIMIT 0"
            )
        )
    )
    # above is 0; use final - 0 since initial was 0 at start
    # (we'll report final_houjin which is clean)

    # Integrity check
    print("[integrity] running PRAGMA integrity_check...", flush=True)
    ic = tgt.execute("PRAGMA integrity_check").fetchall()
    ic_result = ic[0][0] if ic else "unknown"
    print(f"[integrity] {ic_result}", flush=True)

    # FK check
    fk_violations = tgt.execute(
        "SELECT COUNT(*) FROM pragma_foreign_key_check('adoption_records')"
    ).fetchone()[0]
    print(f"[integrity] FK violations on adoption_records = {fk_violations}", flush=True)

    dt = time.time() - t0
    print(
        f"\n=== SUMMARY ===\n"
        f"seen_adoption    = {seen}\n"
        f"inserted_adoption= {inserted_adoption}\n"
        f"final_adoption   = {final_adoption}\n"
        f"final_houjin_all = {final_houjin}\n"
        f"skipped_bad_hb   = {skipped_bad_hb}\n"
        f"errors           = {errors}\n"
        f"integrity        = {ic_result}\n"
        f"fk_violations    = {fk_violations}\n"
        f"elapsed          = {dt:.1f}s\n",
        flush=True,
    )

    src.close()
    tgt.close()
    return 0 if (ic_result == "ok" and fk_violations == 0) else 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--target", type=Path, required=True)
    ap.add_argument("--batch", type=int, default=10000)
    ap.add_argument("--dry-run", action="store_true")
    ns = ap.parse_args()
    if not ns.source.exists():
        print(f"source not found: {ns.source}", file=sys.stderr)
        return 1
    if not ns.target.exists():
        print(f"target not found: {ns.target}", file=sys.stderr)
        return 1
    return run(ns.source, ns.target, ns.batch, ns.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
