#!/usr/bin/env python3
"""Report-only adoption -> program join gap analyzer.

B7 preflight helper. It reads local SQLite databases, inspects the available
schemas, finds adoption rows whose current program join is missing/unknown, and
tests deterministic normalization strategies against the program corpus. It
does not update either database.
"""

from __future__ import annotations

import argparse
import csv
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
DEFAULT_ADOPTION_DB = REPO_ROOT / "autonomath.db"
DEFAULT_PROGRAM_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_JSON_OUTPUT = (
    REPO_ROOT / "analysis_wave18" / "adoption_program_join_gaps_2026-05-01.json"
)
DEFAULT_CSV_OUTPUT = (
    REPO_ROOT / "analysis_wave18" / "adoption_program_join_gaps_2026-05-01.csv"
)

DEFAULT_TIERS = ("S", "A", "B", "C")
DEFAULT_MAX_GROUPS = 2_000
DEFAULT_SAMPLE_LIMIT = 25
DEFAULT_RECOMMENDATION_LIMIT = 200

ADOPTION_TABLE_HINTS = (
    "jpi_adoption_records",
    "adoption_records",
)
PROGRAM_TABLE_HINTS = (
    "programs",
    "jpi_programs",
)
ADOPTION_NAME_COLUMNS = (
    "program_name_raw",
    "program_name",
    "program_title",
    "subsidy_name",
    "program_id_hint",
)
PROGRAM_NAME_COLUMNS = (
    "primary_name",
    "program_name",
    "name",
    "title",
)
PROGRAM_ID_COLUMNS = (
    "unified_id",
    "program_id",
    "id",
    "canonical_id",
)

PARENS_RE = re.compile(r"[（(【\[]([^（）()【】\[\]]{1,120})[）)】\]]")
FISCAL_ROUND_PATTERNS = (
    re.compile(r"(?:令和|平成|昭和)\s*[0-9０-９元一二三四五六七八九十]+\s*(?:年度?)?"),
    re.compile(r"(?:19|20)[0-9０-９]{2}\s*(?:年度?)?"),
    re.compile(r"\b(?:R|H|S)\s*[0-9０-９]+\s*(?:年度?)?", re.IGNORECASE),
    re.compile(r"第\s*[0-9０-９一二三四五六七八九十]+\s*(?:回|次|期|弾|回公募)"),
    re.compile(r"[0-9０-９一二三四五六七八九十]+\s*(?:次|回)\s*(?:公募|締切)"),
    re.compile(r"\s*(?:前期|後期|上期|下期|春期|夏期|秋期|冬期)\s*$"),
)
GRANT_SUFFIX_REPLACEMENTS = (
    ("補助金事業", "補助金"),
    ("助成金事業", "助成金"),
    ("支援金事業", "支援金"),
    ("交付金事業", "交付金"),
    ("補助金制度", "補助金"),
    ("助成金制度", "助成金"),
    ("支援金制度", "支援金"),
    ("交付金制度", "交付金"),
    ("補助事業", "補助金"),
    ("助成事業", "助成金"),
    ("支援事業", "支援金"),
    ("交付事業", "交付金"),
    ("奨励事業", "奨励金"),
)


class SchemaSelectionError(RuntimeError):
    """Raised when a local SQLite DB does not contain a usable table shape."""


@dataclass(frozen=True)
class AdoptionSchema:
    table: str
    id_column: str | None
    name_column: str
    program_id_column: str | None
    match_method_column: str | None
    match_score_column: str | None
    prefecture_column: str | None
    amount_column: str | None
    company_column: str | None
    source_url_column: str | None
    columns: tuple[str, ...]


@dataclass(frozen=True)
class ProgramSchema:
    table: str
    id_column: str
    name_column: str
    aliases_column: str | None
    prefecture_column: str | None
    tier_column: str | None
    excluded_column: str | None
    columns: tuple[str, ...]


@dataclass(frozen=True)
class UnmatchedGroup:
    raw_name: str
    prefecture: str | None
    rows: int


@dataclass(frozen=True)
class ProgramSurface:
    program_id: str
    primary_name: str
    matched_surface: str
    surface_type: str
    prefecture: str | None
    tier: str | None


@dataclass(frozen=True)
class StrategyVariant:
    strategy: str
    variant: str
    key_mode: str


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _qident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _all_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [str(row["name"]) for row in rows if not str(row["name"]).startswith("sqlite_")]


def _table_columns(conn: sqlite3.Connection, table: str) -> tuple[str, ...]:
    try:
        return tuple(
            str(row["name"]) for row in conn.execute(f"PRAGMA table_info({_qident(table)})")
        )
    except sqlite3.OperationalError:
        return ()


def _choose_column(columns: set[str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _table_row_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {_qident(table)}").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row[0] or 0) if row is not None else 0


def _table_hint_score(table: str, hints: tuple[str, ...], keyword: str) -> int:
    if table in hints:
        return 200 - (hints.index(table) * 10)
    if keyword in table:
        return 25
    return 0


def inspect_adoption_schema(conn: sqlite3.Connection) -> AdoptionSchema:
    """Select the best adoption table/columns from the actual local schema."""
    best: tuple[int, str, tuple[str, ...], str] | None = None
    for table in _all_tables(conn):
        if table.endswith(("_fts", "_fts_config", "_fts_content", "_fts_data", "_fts_idx")):
            continue
        columns = _table_columns(conn, table)
        column_set = set(columns)
        name_column = _choose_column(column_set, ADOPTION_NAME_COLUMNS)
        if name_column is None:
            continue
        row_count = _table_row_count(conn, table)
        score = _table_hint_score(table, ADOPTION_TABLE_HINTS, "adoption")
        score += 50 if "program_id" in column_set else 0
        score += 10 if "program_id_match_method" in column_set else 0
        score += 100 if row_count > 0 else 0
        if best is None or score > best[0]:
            best = (score, table, columns, name_column)
    if best is None:
        raise SchemaSelectionError("no adoption-like table with a program-name column found")

    _, table, columns, name_column = best
    column_set = set(columns)
    return AdoptionSchema(
        table=table,
        id_column=_choose_column(column_set, ("id", "rowid")),
        name_column=name_column,
        program_id_column=_choose_column(
            column_set,
            ("program_id", "program_unified_id", "matched_program_id"),
        ),
        match_method_column=_choose_column(
            column_set,
            ("program_id_match_method", "match_method", "program_match_method"),
        ),
        match_score_column=_choose_column(
            column_set,
            ("program_id_match_score", "match_score", "program_match_score"),
        ),
        prefecture_column=_choose_column(column_set, ("prefecture", "pref", "todofuken")),
        amount_column=_choose_column(
            column_set,
            ("amount_granted_yen", "grant_amount_yen", "amount_yen"),
        ),
        company_column=_choose_column(
            column_set,
            ("company_name_raw", "company_name", "recipient_name", "houjin_name"),
        ),
        source_url_column=_choose_column(column_set, ("source_url", "url")),
        columns=columns,
    )


def inspect_program_schema(conn: sqlite3.Connection) -> ProgramSchema:
    """Select the best program table/columns from the actual local schema."""
    best: tuple[int, str, tuple[str, ...], str, str] | None = None
    for table in _all_tables(conn):
        if table.endswith(("_fts", "_fts_config", "_fts_content", "_fts_data", "_fts_idx")):
            continue
        columns = _table_columns(conn, table)
        column_set = set(columns)
        id_column = _choose_column(column_set, PROGRAM_ID_COLUMNS)
        name_column = _choose_column(column_set, PROGRAM_NAME_COLUMNS)
        if id_column is None or name_column is None:
            continue
        row_count = _table_row_count(conn, table)
        score = _table_hint_score(table, PROGRAM_TABLE_HINTS, "program")
        score += 25 if "aliases_json" in column_set else 0
        score += 10 if "excluded" in column_set else 0
        score += 100 if row_count > 0 else 0
        if best is None or score > best[0]:
            best = (score, table, columns, id_column, name_column)
    if best is None:
        raise SchemaSelectionError("no program-like table with id/name columns found")

    _, table, columns, id_column, name_column = best
    column_set = set(columns)
    return ProgramSchema(
        table=table,
        id_column=id_column,
        name_column=name_column,
        aliases_column=_choose_column(column_set, ("aliases_json", "aliases", "alias_json")),
        prefecture_column=_choose_column(column_set, ("prefecture", "pref", "todofuken")),
        tier_column=_choose_column(column_set, ("tier", "quality_tier")),
        excluded_column=_choose_column(column_set, ("excluded", "is_excluded")),
        columns=columns,
    )


def _norm_display(text: str | None) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", str(text))
    return re.sub(r"\s+", " ", normalized).strip(" \t\r\n　-_/")


def _key_exact(text: str | None) -> str:
    return "".join(_norm_display(text).lower().split())


def _without_punctuation(text: str | None) -> str:
    value = _norm_display(text).lower()
    chars: list[str] = []
    for char in value:
        if char.isspace():
            continue
        category = unicodedata.category(char)
        if category[0] in {"P", "S"}:
            continue
        chars.append(char)
    return "".join(chars)


def _key_for(text: str, key_mode: str) -> str:
    if key_mode == "punctuationless":
        return _without_punctuation(text)
    return _key_exact(text)


def _dedupe_variants(strategy: str, values: list[str], key_mode: str) -> list[StrategyVariant]:
    out: list[StrategyVariant] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        display = _norm_display(value)
        key = _key_for(display, key_mode)
        if not display or not key:
            continue
        marker = (key_mode, key)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(StrategyVariant(strategy=strategy, variant=display, key_mode=key_mode))
    return out


def _strip_parenthetical_values(text: str) -> list[str]:
    text = _norm_display(text)
    values = [match.group(1) for match in PARENS_RE.finditer(text)]
    outside = PARENS_RE.sub("", text).strip(" -_/　")
    if outside and outside != text:
        values.insert(0, outside)
    return values


def _strip_fiscal_round(text: str) -> str:
    value = _norm_display(text)
    for pattern in FISCAL_ROUND_PATTERNS:
        value = pattern.sub("", value)
    return re.sub(r"\s+", " ", value).strip(" -_/　")


def _grant_suffix_variants(text: str) -> list[str]:
    value = _norm_display(text)
    variants: list[str] = []
    for old, new in GRANT_SUFFIX_REPLACEMENTS:
        if value.endswith(old) and len(value) > len(old) + 2:
            variants.append(value[: -len(old)] + new)
    return variants


def generate_strategy_variants(raw_name: str) -> list[StrategyVariant]:
    """Return deterministic match variants for one adoption program name."""
    base = _norm_display(raw_name)
    variants: list[StrategyVariant] = []
    variants.extend(_dedupe_variants("exact_normalized", [base], "exact"))
    variants.extend(
        _dedupe_variants("strip_parentheses", _strip_parenthetical_values(base), "exact")
    )
    variants.extend(
        _dedupe_variants("strip_fiscal_year_round", [_strip_fiscal_round(base)], "exact")
    )
    variants.extend(_dedupe_variants("strip_punctuation", [base], "punctuationless"))
    variants.extend(
        _dedupe_variants("grant_suffix_variants", _grant_suffix_variants(base), "exact")
    )

    combined_values: list[str] = [_strip_fiscal_round(base)]
    for parenthetical_value in _strip_parenthetical_values(base):
        combined_values.append(_strip_fiscal_round(parenthetical_value))
    for suffix_value in _grant_suffix_variants(_strip_fiscal_round(base)):
        combined_values.append(suffix_value)
    variants.extend(_dedupe_variants("combined_aggressive", combined_values, "exact"))
    variants.extend(
        _dedupe_variants("combined_aggressive_punctuationless", combined_values, "punctuationless")
    )

    out: list[StrategyVariant] = []
    seen: set[tuple[str, str, str]] = set()
    raw_exact_key = _key_exact(base)
    for variant in variants:
        if variant.strategy != "exact_normalized" and _key_for(variant.variant, variant.key_mode) == raw_exact_key:
            continue
        marker = (variant.strategy, variant.key_mode, _key_for(variant.variant, variant.key_mode))
        if marker in seen:
            continue
        seen.add(marker)
        out.append(variant)
    return out


def _parse_aliases(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw).strip()
    if not text:
        return []
    try:
        decoded = json.loads(text)
    except (TypeError, ValueError):
        return [part.strip() for part in re.split(r"[,;\n]", text) if part.strip()]
    if isinstance(decoded, list):
        return [str(item).strip() for item in decoded if str(item).strip()]
    return []


def _load_program_surfaces(
    conn: sqlite3.Connection,
    schema: ProgramSchema,
    *,
    tiers: tuple[str, ...],
) -> tuple[list[ProgramSurface], dict[str, Any]]:
    select_columns = [
        schema.id_column,
        schema.name_column,
    ]
    optional_columns = [
        schema.aliases_column,
        schema.prefecture_column,
        schema.tier_column,
        schema.excluded_column,
    ]
    for column in optional_columns:
        if column is not None and column not in select_columns:
            select_columns.append(column)
    sql = (
        "SELECT "
        + ", ".join(_qident(column) for column in select_columns)
        + f" FROM {_qident(schema.table)}"
    )
    where: list[str] = [
        f"{_qident(schema.name_column)} IS NOT NULL",
        f"TRIM(CAST({_qident(schema.name_column)} AS TEXT)) <> ''",
    ]
    params: list[Any] = []
    if schema.excluded_column is not None:
        where.append(
            f"({_qident(schema.excluded_column)} IS NULL OR {_qident(schema.excluded_column)} = 0)"
        )
    if schema.tier_column is not None and tiers:
        where.append(f"{_qident(schema.tier_column)} IN ({','.join('?' for _ in tiers)})")
        params.extend(tiers)
    sql += " WHERE " + " AND ".join(where)

    surfaces: list[ProgramSurface] = []
    loaded_program_ids: set[str] = set()
    for row in conn.execute(sql, params):
        program_id = str(row[schema.id_column] or "").strip()
        primary_name = _norm_display(str(row[schema.name_column] or ""))
        if not program_id or not primary_name:
            continue
        loaded_program_ids.add(program_id)
        prefecture = (
            _norm_display(str(row[schema.prefecture_column] or ""))
            if schema.prefecture_column is not None
            else ""
        )
        tier = str(row[schema.tier_column] or "").strip() if schema.tier_column else ""
        surfaces.append(
            ProgramSurface(
                program_id=program_id,
                primary_name=primary_name,
                matched_surface=primary_name,
                surface_type="primary_name",
                prefecture=prefecture or None,
                tier=tier or None,
            )
        )
        if schema.aliases_column is not None:
            for alias in _parse_aliases(row[schema.aliases_column]):
                alias = _norm_display(alias)
                if not alias or _key_exact(alias) == _key_exact(primary_name):
                    continue
                surfaces.append(
                    ProgramSurface(
                        program_id=program_id,
                        primary_name=primary_name,
                        matched_surface=alias,
                        surface_type="alias",
                        prefecture=prefecture or None,
                        tier=tier or None,
                    )
                )

    metadata = {
        "program_rows_loaded": len(loaded_program_ids),
        "program_surfaces_loaded": len(surfaces),
        "tier_filter": list(tiers),
    }
    return surfaces, metadata


def _build_surface_index(
    surfaces: list[ProgramSurface],
) -> dict[str, dict[str, list[ProgramSurface]]]:
    exact: dict[str, list[ProgramSurface]] = defaultdict(list)
    punctuationless: dict[str, list[ProgramSurface]] = defaultdict(list)
    seen_exact: set[tuple[str, str, str]] = set()
    seen_punct: set[tuple[str, str, str]] = set()
    for surface in surfaces:
        exact_key = _key_exact(surface.matched_surface)
        punct_key = _without_punctuation(surface.matched_surface)
        exact_marker = (exact_key, surface.program_id, surface.matched_surface)
        punct_marker = (punct_key, surface.program_id, surface.matched_surface)
        if exact_key and exact_marker not in seen_exact:
            exact[exact_key].append(surface)
            seen_exact.add(exact_marker)
        if punct_key and punct_marker not in seen_punct:
            punctuationless[punct_key].append(surface)
            seen_punct.add(punct_marker)
    return {
        "exact": dict(exact),
        "punctuationless": dict(punctuationless),
    }


def _unclear_join_where(schema: AdoptionSchema) -> str:
    if schema.program_id_column is None:
        return "1 = 1"
    program_id = _qident(schema.program_id_column)
    parts = [
        f"{program_id} IS NULL",
        f"TRIM(CAST({program_id} AS TEXT)) = ''",
    ]
    if schema.match_method_column is not None:
        method = _qident(schema.match_method_column)
        parts.append(f"LOWER(TRIM(CAST({method} AS TEXT))) = 'unknown'")
    return "(" + " OR ".join(parts) + ")"


def _present_name_where(schema: AdoptionSchema) -> str:
    name = _qident(schema.name_column)
    return f"{name} IS NOT NULL AND TRIM(CAST({name} AS TEXT)) <> ''"


def _count_scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0] or 0) if row is not None else 0


def _current_method_counts(
    conn: sqlite3.Connection,
    schema: AdoptionSchema,
) -> list[dict[str, Any]]:
    if schema.match_method_column is None:
        return []
    method = _qident(schema.match_method_column)
    rows = conn.execute(
        f"""SELECT COALESCE(NULLIF(TRIM(CAST({method} AS TEXT)), ''), '(missing)') AS method,
                  COUNT(*) AS rows
             FROM {_qident(schema.table)}
         GROUP BY method
         ORDER BY rows DESC, method"""
    ).fetchall()
    return [{"method": str(row["method"]), "rows": int(row["rows"])} for row in rows]


def _unmatched_groups(
    conn: sqlite3.Connection,
    schema: AdoptionSchema,
    *,
    max_groups: int,
) -> list[UnmatchedGroup]:
    name = _qident(schema.name_column)
    prefecture_sql = (
        _qident(schema.prefecture_column) if schema.prefecture_column is not None else "NULL"
    )
    rows = conn.execute(
        f"""SELECT TRIM(CAST({name} AS TEXT)) AS raw_name,
                  NULLIF(TRIM(CAST({prefecture_sql} AS TEXT)), '') AS prefecture,
                  COUNT(*) AS rows
             FROM {_qident(schema.table)}
            WHERE {_unclear_join_where(schema)}
              AND {_present_name_where(schema)}
         GROUP BY raw_name, prefecture
         ORDER BY rows DESC, raw_name, prefecture
            LIMIT ?""",
        (max_groups,),
    ).fetchall()
    return [
        UnmatchedGroup(
            raw_name=str(row["raw_name"]),
            prefecture=str(row["prefecture"]) if row["prefecture"] else None,
            rows=int(row["rows"]),
        )
        for row in rows
    ]


def _unmatched_group_count(conn: sqlite3.Connection, schema: AdoptionSchema) -> int:
    name = _qident(schema.name_column)
    prefecture_sql = (
        _qident(schema.prefecture_column) if schema.prefecture_column is not None else "NULL"
    )
    return _count_scalar(
        conn,
        f"""SELECT COUNT(*)
              FROM (
                SELECT 1
                  FROM {_qident(schema.table)}
                 WHERE {_unclear_join_where(schema)}
                   AND {_present_name_where(schema)}
              GROUP BY TRIM(CAST({name} AS TEXT)),
                       NULLIF(TRIM(CAST({prefecture_sql} AS TEXT)), '')
              )""",
    )


def _top_unmatched_names(groups: list[UnmatchedGroup], limit: int = 25) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for group in groups:
        counts[group.raw_name] += group.rows
    return [
        {"program_name_raw": name, "rows": rows}
        for name, rows in counts.most_common(limit)
    ]


def _sample_unmatched_rows(
    conn: sqlite3.Connection,
    schema: AdoptionSchema,
    *,
    sample_limit: int,
) -> list[dict[str, Any]]:
    selected = [
        column
        for column in (
            schema.id_column,
            schema.name_column,
            schema.company_column,
            schema.prefecture_column,
            schema.amount_column,
            schema.program_id_column,
            schema.match_method_column,
            schema.match_score_column,
            schema.source_url_column,
        )
        if column is not None
    ]
    select_sql = ", ".join(_qident(column) for column in selected)
    order_column = schema.id_column or schema.name_column
    rows = conn.execute(
        f"""SELECT {select_sql}
             FROM {_qident(schema.table)}
            WHERE {_unclear_join_where(schema)}
         ORDER BY {_qident(order_column)}
            LIMIT ?""",
        (sample_limit,),
    ).fetchall()
    return [
        {
            column: row[column]
            for column in selected
        }
        for row in rows
    ]


def _tier_rank(tier: str | None) -> int:
    return {"S": 0, "A": 1, "B": 2, "C": 3, "X": 4, None: 5, "": 5}.get(tier, 6)


def _candidate_rank(
    candidate: ProgramSurface,
    adoption_prefecture: str | None,
) -> tuple[int, int, int, str]:
    if adoption_prefecture and candidate.prefecture:
        pref_rank = 0 if adoption_prefecture == candidate.prefecture else 2
    elif adoption_prefecture and not candidate.prefecture:
        pref_rank = 1
    elif not adoption_prefecture and not candidate.prefecture:
        pref_rank = 0
    else:
        pref_rank = 1
    surface_rank = 0 if candidate.surface_type == "primary_name" else 1
    return (pref_rank, _tier_rank(candidate.tier), surface_rank, candidate.program_id)


def _candidate_semantic_rank(
    candidate: ProgramSurface,
    adoption_prefecture: str | None,
) -> tuple[int, int, int]:
    rank = _candidate_rank(candidate, adoption_prefecture)
    return rank[:3]


def _dedupe_candidate_surfaces(candidates: list[ProgramSurface]) -> list[ProgramSurface]:
    out: dict[str, ProgramSurface] = {}
    for candidate in candidates:
        existing = out.get(candidate.program_id)
        if existing is None or (
            existing.surface_type != "primary_name" and candidate.surface_type == "primary_name"
        ):
            out[candidate.program_id] = candidate
    return list(out.values())


def _candidate_dict(candidate: ProgramSurface) -> dict[str, Any]:
    return {
        "program_id": candidate.program_id,
        "primary_name": candidate.primary_name,
        "matched_surface": candidate.matched_surface,
        "surface_type": candidate.surface_type,
        "prefecture": candidate.prefecture,
        "tier": candidate.tier,
    }


def _strategy_priority(strategy: str) -> int:
    order = {
        "exact_normalized": 0,
        "strip_fiscal_year_round": 1,
        "strip_parentheses": 2,
        "grant_suffix_variants": 3,
        "strip_punctuation": 4,
        "combined_aggressive": 5,
        "combined_aggressive_punctuationless": 6,
    }
    return order.get(strategy, 99)


def _analyze_groups(
    groups: list[UnmatchedGroup],
    surface_index: dict[str, dict[str, list[ProgramSurface]]],
    *,
    recommendation_limit: int,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]], list[dict[str, Any]]]:
    strategy_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "groups_tested": 0,
            "rows_tested": 0,
            "groups_with_candidates": 0,
            "rows_with_candidates": 0,
            "clear_groups": 0,
            "clear_rows": 0,
            "ambiguous_groups": 0,
            "ambiguous_rows": 0,
            "candidate_program_links": 0,
        }
    )
    candidate_rows: list[dict[str, Any]] = []
    recommendations_by_key: dict[tuple[str, str, str | None], dict[str, Any]] = {}

    for group in groups:
        variants = generate_strategy_variants(group.raw_name)
        best_for_group: dict[str, Any] | None = None
        per_group_strategy: dict[str, dict[str, Any]] = {}
        strategies_seen = {variant.strategy for variant in variants}
        for strategy in strategies_seen:
            strategy_counts[strategy]["groups_tested"] += 1
            strategy_counts[strategy]["rows_tested"] += group.rows

        for variant in variants:
            key = _key_for(variant.variant, variant.key_mode)
            candidates = _dedupe_candidate_surfaces(
                surface_index.get(variant.key_mode, {}).get(key, [])
            )
            if not candidates:
                continue
            ranked = sorted(
                candidates,
                key=lambda candidate: _candidate_rank(candidate, group.prefecture),
            )
            first_rank = _candidate_semantic_rank(ranked[0], group.prefecture)
            clear_match = len(ranked) == 1 or (
                len(ranked) > 1
                and first_rank < _candidate_semantic_rank(ranked[1], group.prefecture)
            )
            status = per_group_strategy.setdefault(
                variant.strategy,
                {"candidate_program_links": 0, "has_clear_match": False},
            )
            status["candidate_program_links"] += len(ranked)
            status["has_clear_match"] = bool(status["has_clear_match"] or clear_match)

            row = {
                "program_name_raw": group.raw_name,
                "prefecture": group.prefecture,
                "unmatched_rows": group.rows,
                "strategy": variant.strategy,
                "variant": variant.variant,
                "key_mode": variant.key_mode,
                "candidate_count": len(ranked),
                "clear_match": clear_match,
                "candidates": [_candidate_dict(candidate) for candidate in ranked[:10]],
            }
            candidate_rows.append(row)

            recommendation = {
                "alias": group.raw_name,
                "unmatched_rows": group.rows,
                "prefecture": group.prefecture,
                "recommended_program_id": ranked[0].program_id,
                "recommended_primary_name": ranked[0].primary_name,
                "matched_surface": ranked[0].matched_surface,
                "strategy": variant.strategy,
                "variant": variant.variant,
                "candidate_count": len(ranked),
                "review_required": not clear_match,
                "reason": (
                    f"raw adoption name matches '{variant.variant}' after "
                    f"{variant.strategy}"
                ),
            }
            if best_for_group is None or (
                recommendation["review_required"],
                _strategy_priority(str(recommendation["strategy"])),
                int(recommendation["candidate_count"]),
            ) < (
                best_for_group["review_required"],
                _strategy_priority(str(best_for_group["strategy"])),
                int(best_for_group["candidate_count"]),
            ):
                best_for_group = recommendation

        if best_for_group is not None:
            key = (
                str(best_for_group["alias"]),
                str(best_for_group["recommended_program_id"]),
                (
                    str(best_for_group["prefecture"])
                    if best_for_group["prefecture"] is not None
                    else None
                ),
            )
            existing = recommendations_by_key.get(key)
            if existing is None or int(best_for_group["unmatched_rows"]) > int(
                existing["unmatched_rows"]
            ):
                recommendations_by_key[key] = best_for_group

        for strategy, status in per_group_strategy.items():
            counts = strategy_counts[strategy]
            counts["groups_with_candidates"] += 1
            counts["rows_with_candidates"] += group.rows
            counts["candidate_program_links"] += int(status["candidate_program_links"])
            if status["has_clear_match"]:
                counts["clear_groups"] += 1
                counts["clear_rows"] += group.rows
            else:
                counts["ambiguous_groups"] += 1
                counts["ambiguous_rows"] += group.rows

    candidate_rows.sort(
        key=lambda row: (
            -int(row["unmatched_rows"]),
            _strategy_priority(str(row["strategy"])),
            str(row["program_name_raw"]),
            str(row["variant"]),
        )
    )
    recommendations = sorted(
        recommendations_by_key.values(),
        key=lambda row: (
            bool(row["review_required"]),
            -int(row["unmatched_rows"]),
            _strategy_priority(str(row["strategy"])),
            str(row["alias"]),
            str(row["recommended_program_id"]),
        ),
    )[:recommendation_limit]
    return candidate_rows, dict(strategy_counts), recommendations


def collect_adoption_program_join_gaps(
    adoption_conn: sqlite3.Connection,
    program_conn: sqlite3.Connection | None = None,
    *,
    tiers: tuple[str, ...] = DEFAULT_TIERS,
    max_groups: int = DEFAULT_MAX_GROUPS,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
    recommendation_limit: int = DEFAULT_RECOMMENDATION_LIMIT,
) -> dict[str, Any]:
    """Collect the B7 report without mutating SQLite."""
    if program_conn is None:
        program_conn = adoption_conn
    adoption_schema = inspect_adoption_schema(adoption_conn)
    program_schema = inspect_program_schema(program_conn)

    adoption_total = _count_scalar(
        adoption_conn,
        f"SELECT COUNT(*) FROM {_qident(adoption_schema.table)}",
    )
    unclear_where = _unclear_join_where(adoption_schema)
    unmatched_total = _count_scalar(
        adoption_conn,
        f"SELECT COUNT(*) FROM {_qident(adoption_schema.table)} WHERE {unclear_where}",
    )
    named_unmatched = _count_scalar(
        adoption_conn,
        f"""SELECT COUNT(*) FROM {_qident(adoption_schema.table)}
             WHERE {unclear_where} AND {_present_name_where(adoption_schema)}""",
    )
    blank_unmatched = unmatched_total - named_unmatched
    unmatched_group_count = _unmatched_group_count(adoption_conn, adoption_schema)
    groups = _unmatched_groups(adoption_conn, adoption_schema, max_groups=max_groups)

    surfaces, program_metadata = _load_program_surfaces(
        program_conn,
        program_schema,
        tiers=tiers,
    )
    surface_index = _build_surface_index(surfaces)
    candidate_rows, strategy_counts, recommendations = _analyze_groups(
        groups,
        surface_index,
        recommendation_limit=recommendation_limit,
    )

    return {
        "generated_at": _utc_now(),
        "report_only": True,
        "mutates_db": False,
        "schema": {
            "adoption": {
                "table": adoption_schema.table,
                "id_column": adoption_schema.id_column,
                "name_column": adoption_schema.name_column,
                "program_id_column": adoption_schema.program_id_column,
                "match_method_column": adoption_schema.match_method_column,
                "match_score_column": adoption_schema.match_score_column,
                "prefecture_column": adoption_schema.prefecture_column,
                "amount_column": adoption_schema.amount_column,
                "company_column": adoption_schema.company_column,
                "source_url_column": adoption_schema.source_url_column,
                "columns": list(adoption_schema.columns),
            },
            "program": {
                "table": program_schema.table,
                "id_column": program_schema.id_column,
                "name_column": program_schema.name_column,
                "aliases_column": program_schema.aliases_column,
                "prefecture_column": program_schema.prefecture_column,
                "tier_column": program_schema.tier_column,
                "excluded_column": program_schema.excluded_column,
                "columns": list(program_schema.columns),
            },
        },
        "totals": {
            "adoption_rows": adoption_total,
            "current_matched_rows": adoption_total - unmatched_total,
            "current_unmatched_rows": unmatched_total,
            "current_unmatched_named_rows": named_unmatched,
            "current_unmatched_blank_name_rows": blank_unmatched,
            "unmatched_name_pref_groups_available": unmatched_group_count,
            "unmatched_name_pref_groups_analyzed": len(groups),
            **program_metadata,
            "program_exact_keys": len(surface_index["exact"]),
            "program_punctuationless_keys": len(surface_index["punctuationless"]),
            "candidate_rows": len(candidate_rows),
            "recommended_alias_additions": len(recommendations),
            "recommended_alias_review_required": sum(
                1 for item in recommendations if item["review_required"]
            ),
        },
        "current_match_methods": _current_method_counts(adoption_conn, adoption_schema),
        "candidate_counts_by_strategy": strategy_counts,
        "top_unmatched_names": _top_unmatched_names(groups),
        "sample_unmatched_rows": _sample_unmatched_rows(
            adoption_conn,
            adoption_schema,
            sample_limit=sample_limit,
        ),
        "strategy_candidates": candidate_rows[:200],
        "recommended_alias_additions": recommendations,
        "notes": [
            "Report is read-only and does not mutate adoption or program tables.",
            "Rows with NULL/blank program_id or program_id_match_method='unknown' count as current unmatched.",
            "review_required=true means multiple program rows share the best deterministic match rank.",
        ],
    }


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_recommendations_csv(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "alias",
        "unmatched_rows",
        "prefecture",
        "recommended_program_id",
        "recommended_primary_name",
        "matched_surface",
        "strategy",
        "variant",
        "candidate_count",
        "review_required",
        "reason",
    ]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in report.get("recommended_alias_additions", []):
            writer.writerow({field: row.get(field) for field in fieldnames})


def _split_tiers(raw: str) -> tuple[str, ...]:
    tiers = tuple(part.strip() for part in raw.split(",") if part.strip())
    return tiers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adoption-db", type=Path, default=DEFAULT_ADOPTION_DB)
    parser.add_argument("--program-db", type=Path, default=DEFAULT_PROGRAM_DB)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV_OUTPUT)
    parser.add_argument("--tiers", default=",".join(DEFAULT_TIERS))
    parser.add_argument("--max-groups", type=int, default=DEFAULT_MAX_GROUPS)
    parser.add_argument("--sample-limit", type=int, default=DEFAULT_SAMPLE_LIMIT)
    parser.add_argument(
        "--recommendation-limit",
        type=int,
        default=DEFAULT_RECOMMENDATION_LIMIT,
    )
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--write-csv", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    tiers = _split_tiers(args.tiers)
    with _connect_readonly(args.adoption_db) as adoption_conn:
        if args.program_db.resolve() == args.adoption_db.resolve():
            report = collect_adoption_program_join_gaps(
                adoption_conn,
                adoption_conn,
                tiers=tiers,
                max_groups=args.max_groups,
                sample_limit=args.sample_limit,
                recommendation_limit=args.recommendation_limit,
            )
        else:
            with _connect_readonly(args.program_db) as program_conn:
                report = collect_adoption_program_join_gaps(
                    adoption_conn,
                    program_conn,
                    tiers=tiers,
                    max_groups=args.max_groups,
                    sample_limit=args.sample_limit,
                    recommendation_limit=args.recommendation_limit,
                )

    report["inputs"] = {
        "adoption_db": str(args.adoption_db),
        "program_db": str(args.program_db),
    }

    if args.write_report:
        write_report(report, args.json_output)
    if args.write_csv:
        write_recommendations_csv(report, args.csv_output)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        totals = report["totals"]
        print(f"adoption_rows={totals['adoption_rows']}")
        print(f"current_unmatched_rows={totals['current_unmatched_rows']}")
        print(f"current_unmatched_named_rows={totals['current_unmatched_named_rows']}")
        print(f"candidate_rows={totals['candidate_rows']}")
        print(f"recommended_alias_additions={totals['recommended_alias_additions']}")
        print(
            "recommended_alias_review_required="
            f"{totals['recommended_alias_review_required']}"
        )
        if args.write_report:
            print(f"json_output={args.json_output}")
        if args.write_csv:
            print(f"csv_output={args.csv_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
