#!/usr/bin/env python3
"""Backfill e-Stat industry fact provenance from existing ``am_source`` rows.

B9 is intentionally local and deterministic: it does not fetch, probe, or call
LLMs.  It only assigns ``am_entity_facts.source_id`` for facts belonging to the
e-Stat industry distribution corpus when the parent entity URL resolves to one
existing e-Stat ``am_source`` row.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
ESTAT_INDUSTRY_TOPIC = "18_estat_industry_distribution"
ESTAT_DOMAIN_SUFFIX = "e-stat.go.jp"
DEFAULT_BATCH_SIZE = 1000


@dataclass(frozen=True)
class EstatFactCandidate:
    fact_id: int
    entity_id: str
    entity_source_url: str | None
    entity_source_domain: str | None


@dataclass(frozen=True)
class SourceAssignment:
    fact_id: int
    entity_id: str
    source_id: int
    method: str


def _connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _require_schema(conn: sqlite3.Connection) -> None:
    required = {
        "am_source": {"id", "source_url", "domain"},
        "am_entities": {
            "canonical_id",
            "record_kind",
            "source_topic",
            "source_url",
            "source_url_domain",
        },
        "am_entity_facts": {"id", "entity_id", "source_id"},
    }
    missing: dict[str, list[str]] = {}
    for table, columns in required.items():
        table_columns = _table_columns(conn, table)
        table_missing = sorted(columns - table_columns)
        if table_missing:
            missing[table] = table_missing
    if missing:
        raise SystemExit(f"database missing expected columns: {missing}")


def normalize_source_url(url: str | None) -> str | None:
    """Return a conservative URL key for equality matching."""
    if not url:
        return None
    raw = url.strip()
    if not raw:
        return None
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError:
        return raw
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return raw
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = urllib.parse.unquote(parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urllib.parse.urlunsplit((scheme, netloc, path, parsed.query, ""))


def normalize_domain(domain: str | None) -> str | None:
    if not domain:
        return None
    value = domain.strip().lower()
    if value.startswith("www."):
        value = value[4:]
    return value or None


def is_estat_domain(domain: str | None) -> bool:
    normalized = normalize_domain(domain)
    return bool(normalized and normalized == ESTAT_DOMAIN_SUFFIX)


def _domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return None
    return normalize_domain(parsed.netloc)


def _build_estat_source_maps(
    conn: sqlite3.Connection,
) -> tuple[dict[str, int], dict[str, int]]:
    exact: dict[str, int] = {}
    normalized_buckets: dict[str, set[int]] = defaultdict(set)
    rows = conn.execute(
        """SELECT id, source_url, domain
             FROM am_source
            WHERE source_url LIKE '%e-stat.go.jp%'
               OR domain LIKE '%e-stat.go.jp%'"""
    )
    for row in rows:
        source_url = str(row["source_url"] or "").strip()
        source_domain = row["domain"] or _domain_from_url(source_url)
        if not source_url or not is_estat_domain(source_domain):
            continue
        source_id = int(row["id"])
        exact[source_url] = source_id
        normalized = normalize_source_url(source_url)
        if normalized:
            normalized_buckets[normalized].add(source_id)
    normalized = {
        key: next(iter(values)) for key, values in normalized_buckets.items() if len(values) == 1
    }
    return exact, normalized


def _resolve_source(
    candidate: EstatFactCandidate,
    *,
    exact_sources: dict[str, int],
    normalized_sources: dict[str, int],
) -> SourceAssignment | None:
    if not is_estat_domain(candidate.entity_source_domain):
        return None
    source_url = (candidate.entity_source_url or "").strip()
    if not source_url:
        return None
    if source_url in exact_sources:
        return SourceAssignment(
            fact_id=candidate.fact_id,
            entity_id=candidate.entity_id,
            source_id=exact_sources[source_url],
            method="entity_source_url_exact",
        )
    normalized = normalize_source_url(source_url)
    if normalized and normalized in normalized_sources:
        return SourceAssignment(
            fact_id=candidate.fact_id,
            entity_id=candidate.entity_id,
            source_id=normalized_sources[normalized],
            method="entity_source_url_normalized",
        )
    return None


def collect_estat_fact_assignments(
    conn: sqlite3.Connection,
    *,
    limit: int | None = None,
) -> list[SourceAssignment]:
    exact_sources, normalized_sources = _build_estat_source_maps(conn)
    sql = """SELECT f.id AS fact_id,
                  f.entity_id,
                  e.source_url AS entity_source_url,
                  e.source_url_domain AS entity_source_domain
             FROM am_entity_facts f
             JOIN am_entities e ON e.canonical_id = f.entity_id
            WHERE e.record_kind = 'statistic'
              AND e.source_topic = ?
              AND f.source_id IS NULL
         ORDER BY f.id"""
    params: list[object] = [ESTAT_INDUSTRY_TOPIC]
    if limit is not None and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)

    assignments: list[SourceAssignment] = []
    for row in conn.execute(sql, params):
        assignment = _resolve_source(
            EstatFactCandidate(
                fact_id=int(row["fact_id"]),
                entity_id=str(row["entity_id"]),
                entity_source_url=row["entity_source_url"],
                entity_source_domain=row["entity_source_domain"],
            ),
            exact_sources=exact_sources,
            normalized_sources=normalized_sources,
        )
        if assignment is not None:
            assignments.append(assignment)
    return assignments


def apply_assignments(
    conn: sqlite3.Connection,
    assignments: Iterable[SourceAssignment],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    rows = [(assignment.source_id, assignment.fact_id) for assignment in assignments]
    if not rows:
        return 0
    updated = 0
    step = max(1, batch_size)
    for start in range(0, len(rows), step):
        batch = rows[start : start + step]
        with conn:
            cur = conn.executemany(
                """UPDATE am_entity_facts
                      SET source_id = ?
                    WHERE id = ?
                      AND source_id IS NULL""",
                batch,
            )
            updated += cur.rowcount
    return updated


def _count_estat_facts(conn: sqlite3.Connection, *, with_source: bool) -> int:
    operator = "IS NOT NULL" if with_source else "IS NULL"
    return int(
        conn.execute(
            f"""SELECT COUNT(*)
                  FROM am_entity_facts f
                  JOIN am_entities e ON e.canonical_id = f.entity_id
                 WHERE e.record_kind = 'statistic'
                   AND e.source_topic = ?
                   AND f.source_id {operator}""",
            (ESTAT_INDUSTRY_TOPIC,),
        ).fetchone()[0]
    )


def backfill_estat_fact_provenance(
    conn: sqlite3.Connection,
    *,
    apply: bool,
    limit: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, object]:
    _require_schema(conn)
    before_with_source = _count_estat_facts(conn, with_source=True)
    before_without_source = _count_estat_facts(conn, with_source=False)
    assignments = collect_estat_fact_assignments(conn, limit=limit)
    method_counts = Counter(assignment.method for assignment in assignments)
    updated_rows = 0
    if apply:
        updated_rows = apply_assignments(conn, assignments, batch_size=batch_size)
    after_with_source = _count_estat_facts(conn, with_source=True)
    after_without_source = _count_estat_facts(conn, with_source=False)
    return {
        "mode": "apply" if apply else "dry_run",
        "source_topic": ESTAT_INDUSTRY_TOPIC,
        "limit": limit,
        "batch_size": batch_size,
        "estat_facts_with_source_before": before_with_source,
        "estat_facts_without_source_before": before_without_source,
        "candidate_assignments": len(assignments),
        "updated_rows": updated_rows,
        "estat_facts_with_source_after": after_with_source,
        "estat_facts_without_source_after": after_without_source,
        "method_counts": dict(sorted(method_counts.items())),
        "sample_assignments": [asdict(row) for row in assignments[:10]],
        "generated_at": datetime.now(UTC).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=AUTONOMATH_DB)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    with _connect(args.db) as conn:
        result = backfill_estat_fact_provenance(
            conn,
            apply=args.apply,
            limit=args.limit,
            batch_size=args.batch_size,
        )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            "e-Stat industry fact source_id: "
            f"{result['estat_facts_with_source_before']} -> "
            f"{result['estat_facts_with_source_after']}"
        )
        print(f"candidate_assignments={result['candidate_assignments']}")
        print(f"updated_rows={result['updated_rows']}")
        print(f"remaining_null={result['estat_facts_without_source_after']}")
        print(f"method_counts={result['method_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
