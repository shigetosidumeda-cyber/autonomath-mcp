#!/usr/bin/env python3
"""Backfill ``am_entity_facts.source_id`` for program facts.

A6 stitches sparse program facts to the existing ``am_source`` graph without
network or LLM calls.  The resolver is deterministic and ordered by evidence:

1. fact ``source_url`` exact/normalized match to ``am_source.source_url``
2. entity ``source_url`` exact/normalized match
3. unambiguous entity-level ``am_entity_source`` edge
4. optional ranked entity-level fallback for multi-source entities

The ranked fallback is explicit because it is inherited provenance, not a true
field-level citation.  A6's >=80k target is only reachable with this fallback
on the current corpus.
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

PRIMARY_ROLE_TOKENS = ("primary", "official", "source_url", "am_entities.source_url")


@dataclass(frozen=True)
class FactCandidate:
    fact_id: int
    entity_id: str
    fact_source_url: str | None
    entity_source_url: str | None


@dataclass(frozen=True)
class EntitySourceCandidate:
    source_id: int
    role: str
    source_field: str | None


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
    query = parsed.query
    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


def _build_source_maps(
    conn: sqlite3.Connection,
) -> tuple[dict[str, int], dict[str, int]]:
    exact: dict[str, int] = {}
    normalized_buckets: dict[str, set[int]] = defaultdict(set)
    for row in conn.execute("SELECT id, source_url FROM am_source"):
        source_url = str(row["source_url"] or "").strip()
        if not source_url:
            continue
        source_id = int(row["id"])
        exact[source_url] = source_id
        norm = normalize_source_url(source_url)
        if norm:
            normalized_buckets[norm].add(source_id)
    normalized = {
        key: next(iter(values))
        for key, values in normalized_buckets.items()
        if len(values) == 1
    }
    return exact, normalized


def _load_entity_source_candidates(
    conn: sqlite3.Connection,
) -> dict[str, list[EntitySourceCandidate]]:
    out: dict[str, list[EntitySourceCandidate]] = defaultdict(list)
    rows = conn.execute(
        """SELECT es.entity_id, es.source_id, es.role, es.source_field
             FROM am_entity_source es
             JOIN am_entities e ON e.canonical_id = es.entity_id
             JOIN am_source s ON s.id = es.source_id
            WHERE e.record_kind = 'program'
         ORDER BY es.entity_id, es.source_id, es.role"""
    )
    for row in rows:
        out[str(row["entity_id"])].append(
            EntitySourceCandidate(
                source_id=int(row["source_id"]),
                role=str(row["role"] or ""),
                source_field=row["source_field"],
            )
        )
    return dict(out)


def _role_priority(candidate: EntitySourceCandidate) -> tuple[int, int, int]:
    label = f"{candidate.role} {candidate.source_field or ''}".lower()
    is_primary = any(token in label for token in PRIMARY_ROLE_TOKENS)
    has_source_field = bool(candidate.source_field)
    return (
        0 if is_primary else 1,
        0 if has_source_field else 1,
        candidate.source_id,
    )


def _unique_source_id(candidates: Iterable[EntitySourceCandidate]) -> int | None:
    values = {candidate.source_id for candidate in candidates}
    if len(values) == 1:
        return next(iter(values))
    return None


def _unique_primary_source_id(candidates: Iterable[EntitySourceCandidate]) -> int | None:
    primary_values = {
        candidate.source_id
        for candidate in candidates
        if _role_priority(candidate)[0] == 0
    }
    if len(primary_values) == 1:
        return next(iter(primary_values))
    return None


def _ranked_source_id(candidates: list[EntitySourceCandidate]) -> int | None:
    if not candidates:
        return None
    return sorted(candidates, key=_role_priority)[0].source_id


def _resolve_url(
    url: str | None,
    *,
    exact_sources: dict[str, int],
    normalized_sources: dict[str, int],
) -> tuple[int | None, str | None]:
    if not url:
        return None, None
    raw = url.strip()
    if raw in exact_sources:
        return exact_sources[raw], "exact"
    norm = normalize_source_url(raw)
    if norm and norm in normalized_sources:
        return normalized_sources[norm], "normalized"
    return None, None


def resolve_fact_source(
    fact: FactCandidate,
    *,
    exact_sources: dict[str, int],
    normalized_sources: dict[str, int],
    entity_sources: dict[str, list[EntitySourceCandidate]],
    allow_ranked_fallback: bool,
) -> SourceAssignment | None:
    for url, prefix in (
        (fact.fact_source_url, "fact_source_url"),
        (fact.entity_source_url, "entity_source_url"),
    ):
        source_id, match_kind = _resolve_url(
            url,
            exact_sources=exact_sources,
            normalized_sources=normalized_sources,
        )
        if source_id is not None and match_kind is not None:
            return SourceAssignment(
                fact_id=fact.fact_id,
                entity_id=fact.entity_id,
                source_id=source_id,
                method=f"{prefix}_{match_kind}",
            )

    candidates = entity_sources.get(fact.entity_id, [])
    source_id = _unique_source_id(candidates)
    if source_id is not None:
        return SourceAssignment(
            fact_id=fact.fact_id,
            entity_id=fact.entity_id,
            source_id=source_id,
            method="entity_source_unambiguous",
        )
    source_id = _unique_primary_source_id(candidates)
    if source_id is not None:
        return SourceAssignment(
            fact_id=fact.fact_id,
            entity_id=fact.entity_id,
            source_id=source_id,
            method="entity_source_unique_primary",
        )
    if allow_ranked_fallback:
        source_id = _ranked_source_id(candidates)
        if source_id is not None:
            return SourceAssignment(
                fact_id=fact.fact_id,
                entity_id=fact.entity_id,
                source_id=source_id,
                method="entity_source_ranked_fallback",
            )
    return None


def collect_program_fact_assignments(
    conn: sqlite3.Connection,
    *,
    allow_ranked_fallback: bool,
    limit: int | None = None,
) -> list[SourceAssignment]:
    exact_sources, normalized_sources = _build_source_maps(conn)
    entity_sources = _load_entity_source_candidates(conn)
    sql = (
        """SELECT f.id AS fact_id, f.entity_id, f.source_url AS fact_source_url,
                  e.source_url AS entity_source_url
             FROM am_entity_facts f
             JOIN am_entities e ON e.canonical_id = f.entity_id
            WHERE e.record_kind = 'program'
              AND f.source_id IS NULL
         ORDER BY f.id"""
    )
    params: list[object] = []
    if limit is not None and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)

    assignments: list[SourceAssignment] = []
    for row in conn.execute(sql, params):
        fact = FactCandidate(
            fact_id=int(row["fact_id"]),
            entity_id=str(row["entity_id"]),
            fact_source_url=row["fact_source_url"],
            entity_source_url=row["entity_source_url"],
        )
        assignment = resolve_fact_source(
            fact,
            exact_sources=exact_sources,
            normalized_sources=normalized_sources,
            entity_sources=entity_sources,
            allow_ranked_fallback=allow_ranked_fallback,
        )
        if assignment is not None:
            assignments.append(assignment)
    return assignments


def apply_assignments(
    conn: sqlite3.Connection,
    assignments: Iterable[SourceAssignment],
) -> int:
    rows = [(assignment.source_id, assignment.fact_id) for assignment in assignments]
    if not rows:
        return 0
    cur = conn.executemany(
        """UPDATE am_entity_facts
              SET source_id = ?
            WHERE id = ?
              AND source_id IS NULL""",
        rows,
    )
    return cur.rowcount


def backfill_program_fact_source_ids(
    conn: sqlite3.Connection,
    *,
    apply: bool,
    allow_ranked_fallback: bool,
    limit: int | None = None,
) -> dict[str, object]:
    before_program_with_source = conn.execute(
        """SELECT COUNT(*)
             FROM am_entity_facts f
             JOIN am_entities e ON e.canonical_id = f.entity_id
            WHERE e.record_kind = 'program'
              AND f.source_id IS NOT NULL"""
    ).fetchone()[0]
    before_program_null = conn.execute(
        """SELECT COUNT(*)
             FROM am_entity_facts f
             JOIN am_entities e ON e.canonical_id = f.entity_id
            WHERE e.record_kind = 'program'
              AND f.source_id IS NULL"""
    ).fetchone()[0]
    assignments = collect_program_fact_assignments(
        conn,
        allow_ranked_fallback=allow_ranked_fallback,
        limit=limit,
    )
    method_counts = Counter(assignment.method for assignment in assignments)
    updated_rows = 0
    if apply:
        with conn:
            updated_rows = apply_assignments(conn, assignments)
    after_program_with_source = conn.execute(
        """SELECT COUNT(*)
             FROM am_entity_facts f
             JOIN am_entities e ON e.canonical_id = f.entity_id
            WHERE e.record_kind = 'program'
              AND f.source_id IS NOT NULL"""
    ).fetchone()[0]
    after_program_null = conn.execute(
        """SELECT COUNT(*)
             FROM am_entity_facts f
             JOIN am_entities e ON e.canonical_id = f.entity_id
            WHERE e.record_kind = 'program'
              AND f.source_id IS NULL"""
    ).fetchone()[0]
    return {
        "mode": "apply" if apply else "dry_run",
        "allow_ranked_fallback": allow_ranked_fallback,
        "program_facts_with_source_before": before_program_with_source,
        "program_facts_without_source_before": before_program_null,
        "candidate_assignments": len(assignments),
        "updated_rows": updated_rows,
        "program_facts_with_source_after": after_program_with_source,
        "program_facts_without_source_after": after_program_null,
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
    parser.add_argument(
        "--allow-ranked-fallback",
        action="store_true",
        help=(
            "Allow deterministic inheritance from multi-source entity rows. "
            "Required to reach the A6 >=80k program-fact target."
        ),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    with _connect(args.db) as conn:
        result = backfill_program_fact_source_ids(
            conn,
            apply=args.apply,
            allow_ranked_fallback=args.allow_ranked_fallback,
            limit=args.limit,
        )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            "program fact source_id: "
            f"{result['program_facts_with_source_before']} -> "
            f"{result['program_facts_with_source_after']}"
        )
        print(f"candidate_assignments={result['candidate_assignments']}")
        print(f"updated_rows={result['updated_rows']}")
        print(f"method_counts={result['method_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
