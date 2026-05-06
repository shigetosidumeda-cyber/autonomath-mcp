#!/usr/bin/env python3
"""Backfill am_source.license using domain-based mapping.

Prereq: migration 049_provenance_strengthen.sql must be applied
(adds license column + CHECK trigger).

Usage:
    python scripts/fill_license.py --dry-run    # show per-license counts only
    python scripts/fill_license.py --apply      # write UPDATEs in single tx
    python scripts/fill_license.py --apply --force  # overwrite non-NULL too

Default behavior is idempotent: rows with license already set are skipped
unless --force is passed. domain extraction failures and rules misses
get license='unknown'.

License vocabulary (CHECK-enforced by migration 049):
    pdl_v1.0           — NTA bulk (法人番号 / 適格請求書, 2026-04-24 確認)
    cc_by_4.0          — e-Gov 法令系, gBizINFO
    gov_standard_v2.0  — 政府標準利用規約 v2.0 (省庁全般 / 公庫 / .lg.jp / .go.jp catch-all)
    public_domain      — 裁判所判例
    proprietary        — JST/J-STAGE 等 配信制限
    unknown            — domain 抽出失敗 or rules 不該当
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

_LOG = logging.getLogger("autonomath.fill_license")

# domain pattern → license. Order matters: most-specific first.
LICENSE_RULES: list[tuple[re.Pattern[str], str]] = [
    # --- NTA bulk: PDL v1.0 (2026-04-24 直接確認) ---
    (re.compile(r"(^|\.)nta\.go\.jp$"), "pdl_v1.0"),
    # --- e-Gov 法令系: CC-BY 4.0 ---
    (re.compile(r"(^|\.)elaws\.e-gov\.go\.jp$"), "cc_by_4.0"),
    (re.compile(r"(^|\.)laws\.e-gov\.go\.jp$"), "cc_by_4.0"),
    (re.compile(r"(^|\.)e-gov\.go\.jp$"), "cc_by_4.0"),
    # --- gBizINFO: CC-BY 4.0 ---
    (re.compile(r"(^|\.)info\.gbiz\.go\.jp$"), "cc_by_4.0"),
    (re.compile(r"(^|\.)gbiz\.go\.jp$"), "cc_by_4.0"),
    # --- 裁判所: public domain ---
    (re.compile(r"(^|\.)courts\.go\.jp$"), "public_domain"),
    # --- JST: 配信制限 (proprietary) ---
    (re.compile(r"(^|\.)jstage\.jst\.go\.jp$"), "proprietary"),
    (re.compile(r"(^|\.)jst\.go\.jp$"), "proprietary"),
    # --- 主要省庁: 政府標準利用規約 v2.0 ---
    (re.compile(r"(^|\.)maff\.go\.jp$"), "gov_standard_v2.0"),
    (re.compile(r"(^|\.)meti\.go\.jp$"), "gov_standard_v2.0"),
    (re.compile(r"(^|\.)mhlw\.go\.jp$"), "gov_standard_v2.0"),
    (re.compile(r"(^|\.)mlit\.go\.jp$"), "gov_standard_v2.0"),
    (re.compile(r"(^|\.)env\.go\.jp$"), "gov_standard_v2.0"),
    (re.compile(r"(^|\.)cao\.go\.jp$"), "gov_standard_v2.0"),
    (re.compile(r"(^|\.)kantei\.go\.jp$"), "gov_standard_v2.0"),
    (re.compile(r"(^|\.)mof\.go\.jp$"), "gov_standard_v2.0"),
    (re.compile(r"(^|\.)mext\.go\.jp$"), "gov_standard_v2.0"),
    (re.compile(r"(^|\.)soumu\.go\.jp$"), "gov_standard_v2.0"),
    # --- 公庫 ---
    (re.compile(r"(^|\.)jfc\.go\.jp$"), "gov_standard_v2.0"),
    # --- 都道府県・政令市の .lg.jp はデフォ政府標準 ---
    (re.compile(r"\.lg\.jp$"), "gov_standard_v2.0"),
    # --- 自治体の素 .jp (一部は lg.jp に未移行): www.pref.* / www.city.* / *.metro.tokyo.* ---
    (re.compile(r"(^|\.)pref\.[a-z]+\.jp$"), "gov_standard_v2.0"),
    (re.compile(r"(^|\.)city\.[a-z\.]+\.jp$"), "gov_standard_v2.0"),
    (re.compile(r"\.metro\.tokyo\.jp$"), "gov_standard_v2.0"),
    # --- 一般 .go.jp catch-all (上記を漏れた行政機関) ---
    (re.compile(r"\.go\.jp$"), "gov_standard_v2.0"),
    # --- .or.jp / .co.jp (民間業界団体・株式会社): 配信規約 individual → proprietary ---
    (re.compile(r"\.or\.jp$"), "proprietary"),
    (re.compile(r"\.co\.jp$"), "proprietary"),
]

LICENSE_VALUES = {
    "pdl_v1.0",
    "cc_by_4.0",
    "gov_standard_v2.0",
    "public_domain",
    "proprietary",
    "unknown",
}


def _configure_logging() -> None:
    root = logging.getLogger("autonomath.fill_license")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _default_db_path() -> Path:
    env = os.environ.get("AUTONOMATH_DB_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "autonomath.db"


def _extract_domain(source_url: str | None, stored_domain: str | None) -> str | None:
    """Return lowercased hostname. Prefer stored am_source.domain when present."""
    if stored_domain:
        d = stored_domain.strip().lower()
        if d:
            return d
    if not source_url:
        return None
    try:
        host = urlparse(source_url).hostname
    except (ValueError, TypeError):
        return None
    if not host:
        return None
    return host.lower()


def classify_domain(domain: str | None) -> str:
    """Map a domain to a license value. Returns 'unknown' on miss."""
    if not domain:
        return "unknown"
    for pattern, license_value in LICENSE_RULES:
        if pattern.search(domain):
            return license_value
    return "unknown"


def _verify_schema(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(am_source)").fetchall()}
    if "license" not in cols:
        raise SystemExit(
            "am_source.license column is missing. Apply migration 049 first:\n"
            "  python scripts/migrate.py --db autonomath.db"
        )
    if "source_url" not in cols:
        raise SystemExit("am_source.source_url column not found — schema unexpected.")


def _classify_all(
    conn: sqlite3.Connection, *, force: bool
) -> tuple[Counter[str], list[tuple[str, int]]]:
    """Walk every am_source row, return (counter, updates).

    updates is a list of (license_value, id) for rows that need UPDATE.
    Skips rows whose license is already set unless force=True.
    """
    counter: Counter[str] = Counter()
    updates: list[tuple[str, int]] = []
    rows = conn.execute("SELECT id, source_url, domain, license FROM am_source")
    for row_id, source_url, stored_domain, current_license in rows:
        domain = _extract_domain(source_url, stored_domain)
        license_value = classify_domain(domain)
        counter[license_value] += 1
        if not force and current_license is not None:
            continue
        if current_license == license_value:
            # already correct, no-op
            continue
        updates.append((license_value, row_id))
    return counter, updates


def _print_counts(label: str, counter: Counter[str]) -> None:
    total = sum(counter.values())
    print(f"\n=== {label} (total {total:,}) ===")
    for license_value in sorted(LICENSE_VALUES):
        n = counter.get(license_value, 0)
        pct = (n / total * 100) if total else 0.0
        print(f"  {license_value:<20s} {n:>8,d}  ({pct:5.1f}%)")


def _sample_unknown(conn: sqlite3.Connection, limit: int = 20) -> None:
    rows = conn.execute(
        "SELECT domain, COUNT(*) c FROM am_source GROUP BY domain ORDER BY c DESC"
    ).fetchall()
    seen: list[tuple[str | None, int]] = []
    for domain, c in rows:
        if classify_domain(domain) == "unknown":
            seen.append((domain, c))
            if len(seen) >= limit:
                break
    if not seen:
        print("\n(no unknown-classified domains)")
        return
    print(f"\nTop {len(seen)} unknown-classified domains:")
    for domain, c in seen:
        print(f"  {c:>6,d}  {domain or '(NULL)'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=_default_db_path(),
        help="SQLite DB path (default: autonomath.db beside repo root).",
    )
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dry-run", action="store_true", help="Print classification breakdown only.")
    grp.add_argument(
        "--apply", action="store_true", help="Execute UPDATEs in a single transaction."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite rows whose license is already non-NULL (default: skip).",
    )
    parser.add_argument(
        "--show-unknown",
        action="store_true",
        help="After classification, print top domains that fell through to 'unknown'.",
    )
    args = parser.parse_args()

    _configure_logging()

    if not args.db.exists():
        raise SystemExit(f"DB not found: {args.db}")

    conn = sqlite3.connect(str(args.db))
    try:
        _verify_schema(conn)
        counter, updates = _classify_all(conn, force=args.force)

        _print_counts("classification of all rows", counter)
        print(f"\nrows that need UPDATE (force={args.force}): {len(updates):,}")

        if args.show_unknown:
            _sample_unknown(conn)

        if args.dry_run:
            print("\n[dry-run] no changes written.")
            return 0

        if not updates:
            print("\nnothing to update — all rows already match.")
            return 0

        # --apply path: single transaction
        _LOG.info("applying %d UPDATEs in single transaction…", len(updates))
        try:
            conn.execute("BEGIN")
            conn.executemany(
                "UPDATE am_source SET license = ? WHERE id = ?",
                updates,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        _LOG.info("commit ok.")

        # post-state breakdown
        post = Counter(
            dict(
                conn.execute(
                    "SELECT COALESCE(license, '<NULL>'), COUNT(*) FROM am_source GROUP BY license"
                ).fetchall()
            )
        )
        _print_counts("post-UPDATE state", post)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
