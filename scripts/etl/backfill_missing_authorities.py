#!/usr/bin/env python3
"""Backfill reviewed legacy authority IDs referenced by ``am_entities``.

D3 closes orphan authority references caused by older hyphen-style IDs such as
``authority:city-kobe`` while preserving the entity history.  The script only
inserts a reviewed allowlist and reports any unexpected orphan IDs separately.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"


@dataclass(frozen=True)
class AuthoritySeed:
    canonical_id: str
    canonical_name: str
    canonical_en: str | None
    level: str
    parent_id: str | None
    region_code: str | None
    website: str | None = None
    note: str = "D3 reviewed legacy authority id."


AUTHORITY_SEEDS: tuple[AuthoritySeed, ...] = (
    AuthoritySeed(
        "authority:city-fukuoka",
        "福岡市",
        "Fukuoka City",
        "designated_city",
        "authority:pref:fukuoka",
        "40130",
    ),
    AuthoritySeed(
        "authority:city-hachioji",
        "八王子市",
        "Hachioji City",
        "municipality",
        "authority:pref:tokyo",
        "13201",
    ),
    AuthoritySeed(
        "authority:city-hiroshima",
        "広島市",
        "Hiroshima City",
        "designated_city",
        "authority:pref:hiroshima",
        "34100",
    ),
    AuthoritySeed(
        "authority:city-kameoka",
        "亀岡市",
        "Kameoka City",
        "municipality",
        "authority:pref:kyoto",
        "26206",
    ),
    AuthoritySeed(
        "authority:city-kobe",
        "神戸市",
        "Kobe City",
        "designated_city",
        "authority:pref:hyogo",
        "28100",
    ),
    AuthoritySeed(
        "authority:city-nagoya",
        "名古屋市",
        "Nagoya City",
        "designated_city",
        "authority:pref:aichi",
        "23100",
    ),
    AuthoritySeed(
        "authority:city-takarazuka",
        "宝塚市",
        "Takarazuka City",
        "municipality",
        "authority:pref:hyogo",
        "28214",
    ),
    AuthoritySeed(
        "authority:city-yokohama",
        "横浜市",
        "Yokohama City",
        "designated_city",
        "authority:pref:kanagawa",
        "14100",
    ),
    AuthoritySeed(
        "authority:hokkaido-tokachi",
        "北海道十勝総合振興局",
        "Hokkaido Tokachi General Subprefectural Bureau",
        "division",
        "authority:pref:hokkaido",
        None,
        "https://www.tokachi.pref.hokkaido.lg.jp/",
    ),
    AuthoritySeed(
        "authority:jsbri",
        "小規模事業者持続化補助金事務局",
        "Jizokuka Subsidy Secretariat",
        "private_semi",
        "authority:meti-chusho",
        None,
    ),
    AuthoritySeed(
        "authority:pref-aichi",
        "愛知県",
        "Aichi Prefecture",
        "prefecture",
        None,
        None,
    ),
    AuthoritySeed(
        "authority:pref-fukuoka",
        "福岡県",
        "Fukuoka Prefecture",
        "prefecture",
        None,
        None,
    ),
    AuthoritySeed(
        "authority:pref-hiroshima",
        "広島県",
        "Hiroshima Prefecture",
        "prefecture",
        None,
        None,
    ),
    AuthoritySeed(
        "authority:pref-iwate",
        "岩手県",
        "Iwate Prefecture",
        "prefecture",
        None,
        None,
    ),
    AuthoritySeed(
        "authority:pref-kyoto",
        "京都府",
        "Kyoto Prefecture",
        "prefecture",
        None,
        None,
    ),
    AuthoritySeed(
        "authority:pref-mie",
        "三重県",
        "Mie Prefecture",
        "prefecture",
        None,
        None,
    ),
    AuthoritySeed(
        "authority:pref-saitama",
        "埼玉県",
        "Saitama Prefecture",
        "prefecture",
        None,
        None,
    ),
)


def _connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def orphan_authority_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT e.authority_canonical AS canonical_id, COUNT(*) AS ref_count
          FROM am_entities e
          LEFT JOIN am_authority a
                 ON a.canonical_id = e.authority_canonical
         WHERE e.authority_canonical IS NOT NULL
           AND a.canonical_id IS NULL
      GROUP BY e.authority_canonical
      ORDER BY e.authority_canonical
        """
    )
    return {str(row["canonical_id"]): int(row["ref_count"]) for row in rows}


def collect_missing_seed_authorities(
    conn: sqlite3.Connection,
) -> tuple[list[AuthoritySeed], dict[str, int], list[str]]:
    orphan_counts = orphan_authority_counts(conn)
    seed_by_id = {seed.canonical_id: seed for seed in AUTHORITY_SEEDS}
    missing = [seed for seed in AUTHORITY_SEEDS if seed.canonical_id in orphan_counts]
    unknown = sorted(set(orphan_counts) - set(seed_by_id))
    return missing, orphan_counts, unknown


def insert_authorities(
    conn: sqlite3.Connection,
    seeds: list[AuthoritySeed],
) -> int:
    updated = 0
    for seed in seeds:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO am_authority(
                canonical_id,
                canonical_name,
                canonical_en,
                level,
                parent_id,
                region_code,
                website,
                note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                seed.canonical_id,
                seed.canonical_name,
                seed.canonical_en,
                seed.level,
                seed.parent_id,
                seed.region_code,
                seed.website,
                seed.note,
            ),
        )
        updated += cur.rowcount
    return updated


def backfill_missing_authorities(
    conn: sqlite3.Connection,
    *,
    apply: bool,
) -> dict[str, Any]:
    missing, before_counts, unknown_before = collect_missing_seed_authorities(conn)
    level_counts = Counter(seed.level for seed in missing)
    inserted_rows = 0
    if apply:
        with conn:
            inserted_rows = insert_authorities(conn, missing)
    _missing_after, after_counts, unknown_after = collect_missing_seed_authorities(conn)
    return {
        "mode": "apply" if apply else "dry_run",
        "known_orphan_authorities_before": len(missing),
        "known_orphan_refs_before": sum(before_counts.get(seed.canonical_id, 0) for seed in missing),
        "unknown_orphan_authorities_before": unknown_before,
        "inserted_rows": inserted_rows,
        "orphan_authorities_after": len(after_counts),
        "orphan_refs_after": sum(after_counts.values()),
        "unknown_orphan_authorities_after": unknown_after,
        "level_counts": dict(sorted(level_counts.items())),
        "sample_insertions": [asdict(seed) for seed in missing[:10]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=AUTONOMATH_DB)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    with _connect(args.db) as conn:
        result = backfill_missing_authorities(conn, apply=args.apply)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"known_orphan_authorities_before={result['known_orphan_authorities_before']}")
        print(f"inserted_rows={result['inserted_rows']}")
        print(f"orphan_authorities_after={result['orphan_authorities_after']}")
        print(f"orphan_refs_after={result['orphan_refs_after']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
