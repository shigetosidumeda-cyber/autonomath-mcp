#!/usr/bin/env python3
"""Backfill ``programs.aliases_json`` from deterministic alias sources.

D9 improves short-query and exact-alias search without LLM calls:

* import curated program aliases from ``autonomath.db.am_alias`` via
  ``am_entities.primary_name == programs.primary_name``;
* generate conservative surface variants from the program name itself
  (parenthetical removal, year/round stripping, spacing normalization).

The script updates ``programs.aliases_json`` and keeps ``programs_fts.aliases``
in sync for touched rows.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"

ALIAS_CAP = 12
ALLOWED_ALIAS_KINDS = {
    "abbreviation",
    "canonical",
    "english",
    "kana",
    "legacy",
    "partial",
}
GENERIC_ENGLISH = {
    "grant",
    "grants",
    "loan",
    "loans",
    "program",
    "programs",
    "subsidy",
    "subsidies",
    "support",
}
COMMON_SUFFIXES = (
    "補助金",
    "助成金",
    "支援金",
    "給付金",
    "交付金",
    "支援事業",
    "促進事業",
    "モデル事業",
    "事業",
    "制度",
)
YEAR_ROUND_PATTERNS = (
    re.compile(r"令和[0-9０-９一二三四五六七八九十]+年度?"),
    re.compile(r"20[0-9]{2}(?:年度?)?"),
    re.compile(r"R[0-9]+(?:年度?)?", re.IGNORECASE),
    re.compile(r"第[0-9０-９一二三四五六七八九十]+回"),
    re.compile(r"[0-9０-９]+次締切"),
)
PARENS_RE = re.compile(r"[（(]([^（）()]{2,80})[）)]")
ASCII_JA_BOUNDARY_RE = re.compile(
    r"(?<=[A-Za-z0-9])(?=[\u3040-\u30ff\u3400-\u9fff])|"
    r"(?<=[\u3040-\u30ff\u3400-\u9fff])(?=[A-Za-z0-9])"
)


@dataclass(frozen=True)
class AliasUpdate:
    unified_id: str
    primary_name: str
    aliases: list[str]
    added_aliases: list[str]


def _connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_aliases(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(decoded, list):
        return []
    return [str(item).strip() for item in decoded if str(item).strip()]


def _json_aliases(aliases: list[str]) -> str:
    return json.dumps(aliases, ensure_ascii=False, separators=(",", ":"))


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or "")).strip()


def _alias_key(text: str) -> str:
    return _norm_text(text).lower()


def _useful_alias(alias: str, primary_name: str) -> str | None:
    alias = _norm_text(alias)
    if not alias:
        return None
    if alias.startswith(("program:", "law:", "corp:", "houjin:")):
        return None
    if alias == primary_name:
        return None
    if len(alias) < 2:
        return None
    if len(alias) > 80:
        return None
    if alias.lower() in GENERIC_ENGLISH:
        return None
    if re.fullmatch(r"[0-9０-９年度年月日 .:/_-]+", alias):
        return None
    return alias


def generate_name_aliases(primary_name: str) -> list[str]:
    """Generate conservative search variants from the program name."""
    primary_name = _norm_text(primary_name)
    candidates: list[str] = []

    no_space = re.sub(r"\s+", "", primary_name)
    if no_space != primary_name:
        candidates.append(no_space)

    spaced_ascii = ASCII_JA_BOUNDARY_RE.sub(" ", primary_name)
    if spaced_ascii != primary_name:
        candidates.append(spaced_ascii)

    for match in PARENS_RE.finditer(primary_name):
        candidates.append(match.group(1))
    without_parens = PARENS_RE.sub("", primary_name).strip()
    if without_parens and without_parens != primary_name:
        candidates.append(without_parens)

    stripped = primary_name
    for pattern in YEAR_ROUND_PATTERNS:
        stripped = pattern.sub("", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip(" -_/　")
    if stripped and stripped != primary_name:
        candidates.append(stripped)
    stripped_without_parens = without_parens
    for pattern in YEAR_ROUND_PATTERNS:
        stripped_without_parens = pattern.sub("", stripped_without_parens)
    stripped_without_parens = re.sub(r"\s+", " ", stripped_without_parens).strip(" -_/　")
    if stripped_without_parens and stripped_without_parens not in {
        primary_name,
        without_parens,
        stripped,
    }:
        candidates.append(stripped_without_parens)

    for suffix in COMMON_SUFFIXES:
        if primary_name.endswith(suffix) and len(primary_name) - len(suffix) >= 4:
            candidates.append(primary_name[: -len(suffix)].strip(" ・-_/　"))

    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        useful = _useful_alias(candidate, primary_name)
        if useful is None:
            continue
        key = _alias_key(useful)
        if key in seen:
            continue
        seen.add(key)
        out.append(useful)
    return out


def load_am_aliases_by_name(am_conn: sqlite3.Connection) -> dict[str, list[str]]:
    aliases_by_name: dict[str, list[str]] = defaultdict(list)
    rows = am_conn.execute(
        """SELECT e.primary_name, a.alias, a.alias_kind
             FROM am_alias a
             JOIN am_entities e ON e.canonical_id = a.canonical_id
            WHERE e.record_kind = 'program'
              AND a.entity_table = 'am_entities'"""
    )
    for row in rows:
        alias_kind = str(row["alias_kind"] or "")
        if alias_kind not in ALLOWED_ALIAS_KINDS:
            continue
        primary_name = _norm_text(str(row["primary_name"] or ""))
        alias = _useful_alias(str(row["alias"] or ""), primary_name)
        if not primary_name or alias is None:
            continue
        aliases_by_name[primary_name].append(alias)
    return {
        name: _dedupe_aliases(values, name)[:ALIAS_CAP]
        for name, values in aliases_by_name.items()
    }


def _dedupe_aliases(values: list[str], primary_name: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        alias = _useful_alias(value, primary_name)
        if alias is None:
            continue
        key = _alias_key(alias)
        if key in seen:
            continue
        seen.add(key)
        out.append(alias)
    return out


def collect_alias_updates(
    jp_conn: sqlite3.Connection,
    aliases_by_name: dict[str, list[str]],
    *,
    tiers: set[str],
) -> list[AliasUpdate]:
    placeholders = ",".join("?" for _ in sorted(tiers))
    rows = jp_conn.execute(
        f"""SELECT unified_id, primary_name, aliases_json
              FROM programs
             WHERE excluded = 0
               AND tier IN ({placeholders})
          ORDER BY unified_id""",
        tuple(sorted(tiers)),
    )
    updates: list[AliasUpdate] = []
    for row in rows:
        primary_name = _norm_text(str(row["primary_name"] or ""))
        existing = _parse_aliases(row["aliases_json"])
        generated = generate_name_aliases(primary_name)
        imported = aliases_by_name.get(primary_name, [])
        merged = _dedupe_aliases(existing + imported + generated, primary_name)[:ALIAS_CAP]
        if merged == _dedupe_aliases(existing, primary_name)[:ALIAS_CAP]:
            continue
        added_keys = {_alias_key(value) for value in existing}
        added = [alias for alias in merged if _alias_key(alias) not in added_keys]
        updates.append(
            AliasUpdate(
                unified_id=str(row["unified_id"]),
                primary_name=primary_name,
                aliases=merged,
                added_aliases=added,
            )
        )
    return updates


def _sync_programs_fts(
    conn: sqlite3.Connection,
    *,
    unified_id: str,
    aliases: list[str],
) -> None:
    row = conn.execute(
        "SELECT primary_name FROM programs WHERE unified_id = ?",
        (unified_id,),
    ).fetchone()
    if row is None:
        return
    fts_row = conn.execute(
        "SELECT enriched_text FROM programs_fts WHERE unified_id = ?",
        (unified_id,),
    ).fetchone()
    enriched_text = fts_row["enriched_text"] if fts_row is not None else ""
    conn.execute("DELETE FROM programs_fts WHERE unified_id = ?", (unified_id,))
    conn.execute(
        """INSERT INTO programs_fts(unified_id, primary_name, aliases, enriched_text)
           VALUES (?, ?, ?, ?)""",
        (unified_id, row["primary_name"], " ".join(aliases), enriched_text or ""),
    )


def apply_alias_updates(conn: sqlite3.Connection, updates: list[AliasUpdate]) -> int:
    updated = 0
    for update in updates:
        cur = conn.execute(
            """UPDATE programs
                  SET aliases_json = ?
                WHERE unified_id = ?""",
            (_json_aliases(update.aliases), update.unified_id),
        )
        updated += cur.rowcount
        _sync_programs_fts(
            conn,
            unified_id=update.unified_id,
            aliases=update.aliases,
        )
    return updated


def _non_empty_alias_count(conn: sqlite3.Connection, *, tiers: set[str]) -> int:
    placeholders = ",".join("?" for _ in sorted(tiers))
    return conn.execute(
        f"""SELECT COUNT(*)
              FROM programs
             WHERE excluded = 0
               AND tier IN ({placeholders})
               AND aliases_json IS NOT NULL
               AND TRIM(aliases_json) NOT IN ('', '[]')""",
        tuple(sorted(tiers)),
    ).fetchone()[0]


def backfill_program_aliases(
    jp_conn: sqlite3.Connection,
    am_conn: sqlite3.Connection,
    *,
    apply: bool,
    tiers: set[str],
) -> dict[str, Any]:
    before_non_empty = _non_empty_alias_count(jp_conn, tiers=tiers)
    aliases_by_name = load_am_aliases_by_name(am_conn)
    updates = collect_alias_updates(jp_conn, aliases_by_name, tiers=tiers)
    added_alias_counts = Counter()
    for update in updates:
        for alias in update.added_aliases:
            if alias in aliases_by_name.get(update.primary_name, []):
                added_alias_counts["am_alias"] += 1
            else:
                added_alias_counts["generated"] += 1
    updated_rows = 0
    if apply:
        with jp_conn:
            updated_rows = apply_alias_updates(jp_conn, updates)
    after_non_empty = _non_empty_alias_count(jp_conn, tiers=tiers)
    return {
        "mode": "apply" if apply else "dry_run",
        "tiers": sorted(tiers),
        "aliases_non_empty_before": before_non_empty,
        "candidate_updates": len(updates),
        "updated_rows": updated_rows,
        "aliases_non_empty_after": after_non_empty,
        "added_alias_counts": dict(sorted(added_alias_counts.items())),
        "sample_updates": [update.__dict__ for update in updates[:10]],
        "generated_at": datetime.now(UTC).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jpintel-db", type=Path, default=JPINTEL_DB)
    parser.add_argument("--autonomath-db", type=Path, default=AUTONOMATH_DB)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    parser.add_argument("--tiers", default="S,A,B,C")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    tiers = {tier.strip() for tier in args.tiers.split(",") if tier.strip()}
    with _connect(args.jpintel_db) as jp_conn, _connect(args.autonomath_db) as am_conn:
        result = backfill_program_aliases(
            jp_conn,
            am_conn,
            apply=args.apply,
            tiers=tiers,
        )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            "program aliases non-empty: "
            f"{result['aliases_non_empty_before']} -> "
            f"{result['aliases_non_empty_after']}"
        )
        print(f"candidate_updates={result['candidate_updates']}")
        print(f"updated_rows={result['updated_rows']}")
        print(f"added_alias_counts={result['added_alias_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
