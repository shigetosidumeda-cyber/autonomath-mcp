#!/usr/bin/env python3
"""Upgrade safe public-sector program URLs from http:// to https://.

D4 intentionally only touches domains that are safe to canonicalize without a
live probe: ``*.go.jp``, ``*.lg.jp``, and ``*.metro.tokyo.*``.  Commercial /
association domains remain unchanged.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import urllib.parse
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
URL_COLUMNS = ("source_url", "official_url")


@dataclass(frozen=True)
class UrlUpgrade:
    unified_id: str
    column: str
    old_url: str
    new_url: str
    host: str


def _connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def is_safe_public_host(host: str | None) -> bool:
    host = (host or "").lower()
    return (
        host.endswith(".go.jp")
        or host.endswith(".lg.jp")
        or ".metro.tokyo." in host
    )


def upgrade_url(url: str | None) -> tuple[str | None, str | None]:
    if not url:
        return None, None
    try:
        parsed = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return None, None
    if parsed.scheme.lower() != "http":
        return None, None
    host = (parsed.hostname or "").lower()
    if not is_safe_public_host(host):
        return None, None
    upgraded = urllib.parse.urlunsplit(
        ("https", parsed.netloc, parsed.path, parsed.query, parsed.fragment)
    )
    return upgraded, host


def collect_url_upgrades(conn: sqlite3.Connection) -> list[UrlUpgrade]:
    upgrades: list[UrlUpgrade] = []
    for column in URL_COLUMNS:
        rows = conn.execute(
            f"""SELECT unified_id, {column} AS url
                  FROM programs
                 WHERE {column} LIKE 'http://%'
              ORDER BY unified_id"""
        )
        for row in rows:
            new_url, host = upgrade_url(row["url"])
            if new_url is None or host is None:
                continue
            upgrades.append(
                UrlUpgrade(
                    unified_id=str(row["unified_id"]),
                    column=column,
                    old_url=str(row["url"]),
                    new_url=new_url,
                    host=host,
                )
            )
    return upgrades


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return column in {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def apply_url_upgrades(conn: sqlite3.Connection, upgrades: list[UrlUpgrade]) -> int:
    has_corrected_at = _has_column(conn, "programs", "source_url_corrected_at")
    corrected_at = datetime.now(UTC).isoformat()
    updated = 0
    for upgrade in upgrades:
        sets = [f"{upgrade.column} = ?"]
        params: list[Any] = [upgrade.new_url]
        if upgrade.column == "source_url" and has_corrected_at:
            sets.append("source_url_corrected_at = ?")
            params.append(corrected_at)
        params.extend([upgrade.unified_id, upgrade.old_url])
        cur = conn.execute(
            f"""UPDATE programs
                   SET {', '.join(sets)}
                 WHERE unified_id = ?
                   AND {upgrade.column} = ?""",
            params,
        )
        updated += cur.rowcount
    return updated


def remaining_safe_http_urls(conn: sqlite3.Connection) -> dict[str, int]:
    out: dict[str, int] = {}
    for column in URL_COLUMNS:
        count = 0
        rows = conn.execute(
            f"SELECT {column} AS url FROM programs WHERE {column} LIKE 'http://%'"
        )
        for row in rows:
            _new_url, host = upgrade_url(row["url"])
            if host is not None:
                count += 1
        out[column] = count
    return out


def backfill_program_https_urls(
    conn: sqlite3.Connection,
    *,
    apply: bool,
) -> dict[str, Any]:
    before_remaining = remaining_safe_http_urls(conn)
    upgrades = collect_url_upgrades(conn)
    host_counts = Counter(upgrade.host for upgrade in upgrades)
    column_counts = Counter(upgrade.column for upgrade in upgrades)
    updated_cells = 0
    if apply:
        with conn:
            updated_cells = apply_url_upgrades(conn, upgrades)
    after_remaining = remaining_safe_http_urls(conn)
    return {
        "mode": "apply" if apply else "dry_run",
        "candidate_updates": len(upgrades),
        "updated_cells": updated_cells,
        "before_remaining_safe_http": before_remaining,
        "after_remaining_safe_http": after_remaining,
        "column_counts": dict(sorted(column_counts.items())),
        "host_counts": dict(sorted(host_counts.items())),
        "sample_updates": [asdict(upgrade) for upgrade in upgrades[:10]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=JPINTEL_DB)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    with _connect(args.db) as conn:
        result = backfill_program_https_urls(conn, apply=args.apply)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"candidate_updates={result['candidate_updates']}")
        print(f"updated_cells={result['updated_cells']}")
        print(f"after_remaining_safe_http={result['after_remaining_safe_http']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
