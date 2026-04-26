"""Process Wave 18 残 193 ambiguous duplicate review queue (2026-04-26).

Wave 18 noise-duplicate consolidation merged 568 winners (575 loser rows
flipped to excluded=1 + exclusion_reason='duplicate_merged'). The remaining
193 entries land in data/duplicate_review_queue.jsonl because the candidate
rows share (primary_name, prefecture) but differ in source_url — the
auto-merger can't distinguish "same program, two URL variants" from
"two distinct programs that happen to share a name".

This script applies a deterministic verdict per entry using URL/domain rules:

  * MERGE   — all candidate URLs share the same domain (path differs only),
              or one of the URLs is a strict subpath of the other.
              Winner pick = same logic as Wave 17/18:
                tier asc (S<A<B<C<X) → source_fetched_at desc → uid asc.
              Losers get excluded=1, exclusion_reason='dedup_ambiguous_resolved',
              tier='X'. Winner gets merged_from JSON array of loser uids.

  * EXCLUDE — at least one candidate URL is an aggregator domain banned by
              CLAUDE.md data-hygiene clause (noukaweb / hojyokin-portal /
              biz.stayway / g_biki / mirasapo-plus aggregator pages).
              Aggregator row → excluded=1, reason='aggregator_only', tier='X'.
              Other rows in the entry are left as-is (still searchable).
              If multiple non-aggregator rows share a domain after this, they
              become a sub-MERGE in the same pass.

  * KEEP    — different domains AND no aggregator AND name suggests genuine
              variant (e.g. 令和X年度 fiscal year prefix, or kakegawa-city vs
              shizuoka-pref both being legit publishers of different angles).
              No DB mutation; entry recorded in skip log.

  * DEFER   — anything not classifiable by above rules (very ambiguous text,
              foreign domains, etc.). No mutation; logged for next wave.

Backup: data/jpintel.db.bak-dedup-review-{epoch} created before any UPDATE.
The 'dedup_ambiguous_resolved' enum code is registered in
exclusion_reason_codes prior to the first UPDATE so the tier=X enum trigger
does not abort.

Usage:
    python scripts/process_duplicate_review_2026_04_26.py --dry-run
    python scripts/process_duplicate_review_2026_04_26.py --apply
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "jpintel.db"
QUEUE_PATH = ROOT / "data" / "duplicate_review_queue.jsonl"
LOG_PATH = ROOT / "data" / "duplicate_review_decisions_2026_04_26.jsonl"

EXCLUSION_REASON_MERGE = "dedup_ambiguous_resolved"
EXCLUSION_REASON_AGGREGATOR = "aggregator_only"

# Aggregator / banned domains per CLAUDE.md and feedback_no_fake_data.
AGGREGATOR_DOMAINS = {
    "noukaweb.maff.go.jp",
    "noukaweb.jp",
    "www.noukaweb.jp",
    "hojyokin-portal.jp",
    "www.hojyokin-portal.jp",
    "biz.stayway.jp",
    "stayway.jp",
    "mirasapo-plus.go.jp",
    "www.mirasapo-plus.go.jp",
    "j-net21.smrj.go.jp",
    "j-grants-portal.smrj.go.jp",
}
# Junk / non-publisher domains (PDF reader download links etc.) — treat
# like aggregator and exclude.
JUNK_DOMAINS = {
    "get.adobe.com",
    "www.adobe.com",
    "adobe.com",
}
# Aggregator hint substrings (path-level, e.g. MAFF g_biki listing page).
AGGREGATOR_PATH_HINTS = ("g_biki", "/portal/", "/aggregator/")

# Public-suffix-aware "registered domain" extraction is overkill for our
# corpus (mostly Japanese gov + .jp/.lg.jp/.go.jp). Use a heuristic that
# strips known multi-part suffixes and the leading subdomain.
_MULTI_TLDS = (
    ".lg.jp",
    ".go.jp",
    ".or.jp",
    ".ac.jp",
    ".ad.jp",
    ".co.jp",
    ".ne.jp",
    ".gr.jp",
    ".ed.jp",
    ".pref.jp",
)


def registered_domain(host: str) -> str:
    """Best-effort eTLD+1 for the duplicate-merge heuristic.

    Examples:
      portal.shoryokuka.smrj.go.jp → smrj.go.jp
      shoryokuka.smrj.go.jp        → smrj.go.jp
      www.pref.aichi.jp            → pref.aichi.jp (lg.jp not present, fall back)
      www.pref.aichi.lg.jp         → aichi.lg.jp
      r6.jizokukahojokin.info      → jizokukahojokin.info
      keisyou-hatten.maff.go.jp    → maff.go.jp
    """
    host = (host or "").lower().strip()
    if not host:
        return ""
    # Strip known multi-part TLDs first.
    for suf in _MULTI_TLDS:
        if host.endswith(suf):
            head = host[: -len(suf)]
            parts = head.split(".")
            return parts[-1] + suf if parts else host
    # Generic eTLD+1: last 2 dot-separated labels.
    labels = host.split(".")
    if len(labels) >= 2:
        return ".".join(labels[-2:])
    return host

TIER_RANK = {"S": 0, "A": 1, "B": 2, "C": 3, "X": 4, None: 5, "": 5}

# 令和X年度 / 平成X年度 / 西暦year prefixes that mark a year-distinguished variant.
YEAR_PATTERNS = [
    re.compile(r"令和\s*(\d+)\s*年度"),
    re.compile(r"平成\s*(\d+)\s*年度"),
    re.compile(r"(20\d{2})\s*年度"),
    re.compile(r"R\s*(\d+)\s*年度"),
]


def domain_of(url: str) -> str:
    if not url:
        return ""
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def path_of(url: str) -> str:
    if not url:
        return ""
    try:
        return urlparse(url).path or ""
    except Exception:
        return ""


def is_aggregator(url: str) -> bool:
    d = domain_of(url)
    if d in AGGREGATOR_DOMAINS or d in JUNK_DOMAINS:
        return True
    p = path_of(url).lower()
    return any(hint in p for hint in AGGREGATOR_PATH_HINTS)


def years_in_name(name: str) -> set[str]:
    out: set[str] = set()
    for pat in YEAR_PATTERNS:
        for m in pat.findall(name or ""):
            out.add(str(m))
    return out


def pick_winner(rows: list[dict]) -> dict:
    """tier asc (S<A<B<C<X) → fetched_at desc → uid asc."""
    sorted_rows = sorted(rows, key=lambda r: r.get("unified_id") or "")
    sorted_rows.sort(key=lambda r: r.get("source_fetched_at") or "", reverse=True)
    sorted_rows.sort(key=lambda r: TIER_RANK.get(r.get("tier"), 99))
    return sorted_rows[0]


def fetch_rows(conn: sqlite3.Connection, uids: list[str]) -> list[dict]:
    if not uids:
        return []
    qmarks = ",".join(["?"] * len(uids))
    rows = conn.execute(
        f"""
        SELECT unified_id, primary_name, prefecture, source_url,
               tier, source_fetched_at, excluded, exclusion_reason, merged_from
        FROM programs
        WHERE unified_id IN ({qmarks})
        """,
        uids,
    ).fetchall()
    return [dict(r) for r in rows]


def classify(entry: dict, rows: list[dict]) -> tuple[str, dict]:
    """Return (verdict, payload) for an entry.

    verdict ∈ {merge, exclude, keep, defer}
    payload carries operation-specific fields:
      merge:   {winner_uid, loser_uids}
      exclude: {to_exclude_uids, remaining_after, sub_merge?:{winner_uid, loser_uids}}
      keep:    {reason}
      defer:   {reason}
    """
    name = entry.get("primary_name") or ""
    if len(rows) < 2:
        return "defer", {"reason": "fewer_than_two_active_rows"}

    # 0) Year-distinguished variants → KEEP.
    yrs = years_in_name(name)
    # If name itself encodes a single year, all rows share it; not a discriminator.
    # The discriminator is whether the URLs encode different years.
    url_year_buckets: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        url = r.get("source_url") or ""
        # crude year extraction from URL path (e.g. /2025/, /r6/, /h30/)
        m = re.search(r"/(20\d{2}|r\d{1,2}|h\d{1,2})/", url.lower())
        url_year_buckets[m.group(1) if m else ""].append(r)
    if len(url_year_buckets) > 1 and len(yrs) <= 1:
        return "keep", {"reason": "url_year_variants"}

    # 1) Aggregator scrub.
    aggr_rows = [r for r in rows if is_aggregator(r.get("source_url") or "")]
    non_aggr = [r for r in rows if not is_aggregator(r.get("source_url") or "")]
    if aggr_rows:
        # Mark aggregator rows for exclude.
        payload: dict = {
            "to_exclude_uids": [r["unified_id"] for r in aggr_rows],
            "exclusion_reason": EXCLUSION_REASON_AGGREGATOR,
            "remaining_after": [r["unified_id"] for r in non_aggr],
        }
        # If non-aggregator survivors share a domain, sub-merge them too.
        if len(non_aggr) >= 2:
            doms = {domain_of(r.get("source_url") or "") for r in non_aggr}
            if len(doms) == 1:
                winner = pick_winner(non_aggr)
                losers = [r for r in non_aggr if r["unified_id"] != winner["unified_id"]]
                payload["sub_merge"] = {
                    "winner_uid": winner["unified_id"],
                    "loser_uids": sorted(r["unified_id"] for r in losers),
                }
        return "exclude", payload

    # 2) All same exact host → MERGE.
    doms = {domain_of(r.get("source_url") or "") for r in rows}
    doms.discard("")
    if len(doms) <= 1 and doms:
        winner = pick_winner(rows)
        losers = [r for r in rows if r["unified_id"] != winner["unified_id"]]
        return "merge", {
            "winner_uid": winner["unified_id"],
            "loser_uids": sorted(r["unified_id"] for r in losers),
        }

    # 3) Same registered domain (eTLD+1) → MERGE. Catches subdomain variants
    #    like portal.shoryokuka.smrj.go.jp ≈ shoryokuka.smrj.go.jp,
    #    r6.jizokukahojokin.info ≈ jizokukahojokin.info, and
    #    keisyou-hatten.maff.go.jp ≈ www.maff.go.jp (both MAFF).
    reg_doms = {registered_domain(d) for d in doms}
    reg_doms.discard("")
    if len(reg_doms) == 1:
        winner = pick_winner(rows)
        losers = [r for r in rows if r["unified_id"] != winner["unified_id"]]
        return "merge", {
            "winner_uid": winner["unified_id"],
            "loser_uids": sorted(r["unified_id"] for r in losers),
            "merge_basis": "same_registered_domain",
        }

    # 4) Different registered domains → keep both (likely distinct publishers).
    return "keep", {
        "reason": "different_registered_domains_likely_distinct_publishers",
        "registered_domains": sorted(reg_doms),
    }


def ensure_enum_code(conn: sqlite3.Connection) -> None:
    """Register dedup_ambiguous_resolved in exclusion_reason_codes if missing."""
    row = conn.execute(
        "SELECT 1 FROM exclusion_reason_codes WHERE code = ?",
        (EXCLUSION_REASON_MERGE,),
    ).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO exclusion_reason_codes(code, description) VALUES (?, ?)",
            (
                EXCLUSION_REASON_MERGE,
                "Wave 18 review-queue ambiguous duplicate resolved by 2026-04-26 manual triage script (same domain, merged into winner)",
            ),
        )


def apply_merge(
    cur: sqlite3.Cursor,
    winner_uid: str,
    loser_uids: list[str],
    reason: str = EXCLUSION_REASON_MERGE,
) -> int:
    """Flip losers to excluded=1 + tier=X, append to winner.merged_from. Return # losers updated."""
    if not loser_uids:
        return 0
    # Mark losers; ensure tier flips to X for enum compatibility.
    n = 0
    for uid in loser_uids:
        cur.execute(
            """
            UPDATE programs
               SET excluded = 1,
                   exclusion_reason = ?,
                   tier = 'X'
             WHERE unified_id = ?
               AND excluded = 0
            """,
            (reason, uid),
        )
        n += cur.rowcount
    # Update winner.merged_from JSON
    existing = cur.execute(
        "SELECT merged_from FROM programs WHERE unified_id = ?", (winner_uid,)
    ).fetchone()
    existing_uids: list[str] = []
    if existing and existing[0]:
        try:
            parsed = json.loads(existing[0])
            if isinstance(parsed, list):
                existing_uids = [str(x) for x in parsed]
        except json.JSONDecodeError:
            pass
    combined = sorted(set(existing_uids) | set(loser_uids))
    cur.execute(
        "UPDATE programs SET merged_from = ? WHERE unified_id = ?",
        (json.dumps(combined, ensure_ascii=False), winner_uid),
    )
    return n


def apply_aggregator_exclude(
    cur: sqlite3.Cursor, uids: list[str]
) -> int:
    n = 0
    for uid in uids:
        cur.execute(
            """
            UPDATE programs
               SET excluded = 1,
                   exclusion_reason = ?,
                   tier = 'X'
             WHERE unified_id = ?
               AND excluded = 0
            """,
            (EXCLUSION_REASON_AGGREGATOR, uid),
        )
        n += cur.rowcount
    return n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.apply and not args.dry_run:
        args.dry_run = True

    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found", file=sys.stderr)
        return 1
    if not QUEUE_PATH.exists():
        print(f"ERROR: {QUEUE_PATH} not found", file=sys.stderr)
        return 1

    # Backup BEFORE opening write connection.
    if args.apply:
        ts = int(time.time())
        backup = DB_PATH.with_name(f"jpintel.db.bak-dedup-review-{ts}")
        print(f"Backing up DB → {backup}")
        shutil.copy2(DB_PATH, backup)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    cols = [r["name"] for r in conn.execute("PRAGMA table_info(programs)").fetchall()]
    if "merged_from" not in cols:
        print("ERROR: programs.merged_from column missing.", file=sys.stderr)
        return 2

    # Pre-state counts.
    pre_active, pre_excluded = conn.execute(
        "SELECT SUM(CASE WHEN excluded=0 THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN excluded=1 THEN 1 ELSE 0 END) FROM programs"
    ).fetchone()

    print(f"DB: {DB_PATH}")
    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"Pre-state: active={pre_active}, excluded={pre_excluded}")

    entries = [json.loads(line) for line in QUEUE_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"Queue size: {len(entries)}")

    # Decisions.
    decisions: list[dict] = []
    counts = defaultdict(int)
    total_losers_flagged = 0

    for entry in entries:
        uids = entry.get("uids") or []
        rows = fetch_rows(conn, uids)
        # Filter to active rows only — rows already excluded by other waves
        # (e.g. Wave 18) should not be re-touched.
        active_rows = [r for r in rows if not r.get("excluded")]
        verdict, payload = classify(entry, active_rows)
        counts[verdict] += 1
        decisions.append(
            {
                "primary_name": entry.get("primary_name"),
                "prefecture": entry.get("prefecture"),
                "uids": uids,
                "active_count": len(active_rows),
                "verdict": verdict,
                "payload": payload,
            }
        )

    print()
    print("Decision tally:")
    for k in ("merge", "exclude", "keep", "defer"):
        print(f"  {k:<8} {counts[k]}")

    if args.apply:
        cur = conn.cursor()
        cur.execute("BEGIN")
        try:
            ensure_enum_code(conn)
            for d in decisions:
                p = d["payload"]
                if d["verdict"] == "merge":
                    n = apply_merge(cur, p["winner_uid"], p["loser_uids"])
                    total_losers_flagged += n
                elif d["verdict"] == "exclude":
                    n = apply_aggregator_exclude(cur, p["to_exclude_uids"])
                    total_losers_flagged += n
                    sub = p.get("sub_merge")
                    if sub:
                        n2 = apply_merge(cur, sub["winner_uid"], sub["loser_uids"])
                        total_losers_flagged += n2
            conn.commit()
        except Exception as exc:
            conn.rollback()
            print(f"ERROR: rollback: {exc!r}", file=sys.stderr)
            return 3

        post_active, post_excluded = conn.execute(
            "SELECT SUM(CASE WHEN excluded=0 THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN excluded=1 THEN 1 ELSE 0 END) FROM programs"
        ).fetchone()
        new_dedup_rows = conn.execute(
            "SELECT COUNT(*) FROM programs WHERE exclusion_reason = ?",
            (EXCLUSION_REASON_MERGE,),
        ).fetchone()[0]
        new_aggr_rows = conn.execute(
            "SELECT COUNT(*) FROM programs WHERE excluded=1 AND exclusion_reason = ?",
            (EXCLUSION_REASON_AGGREGATOR,),
        ).fetchone()[0]
        print()
        print(f"Post-state: active={post_active}, excluded={post_excluded}")
        print(f"Rows now flagged dedup_ambiguous_resolved: {new_dedup_rows}")
        print(f"Rows now flagged aggregator_only (total): {new_aggr_rows}")
        print(f"Total rows freshly flipped this run: {total_losers_flagged}")

    # Persist decision log either way.
    LOG_PATH.write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in decisions) + "\n",
        encoding="utf-8",
    )
    print(f"Decision log → {LOG_PATH}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
