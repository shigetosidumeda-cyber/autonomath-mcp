#!/usr/bin/env python3
"""Propose B5 court source_excerpt backfills from local SQLite text only.

Report-only helper. It scans local court-like SQLite tables for rows whose
``source_excerpt`` cell is empty, derives a proposed excerpt only from columns
already present in the same row, and emits review artifacts. It never crawls and
never mutates source databases.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_JSON_OUTPUT = (
    REPO_ROOT / "analysis_wave18" / "court_source_excerpt_proposals_2026-05-01.json"
)
DEFAULT_CSV_OUTPUT = REPO_ROOT / "analysis_wave18" / "court_source_excerpt_proposals_2026-05-01.csv"

PROPOSAL_COLUMNS = [
    "table",
    "row_id",
    "source_url",
    "current_excerpt",
    "proposed_excerpt",
    "confidence",
    "reason",
    "review_required",
]

COURT_TABLE_TOKENS = (
    "court",
    "courts",
    "hanrei",
    "saiban",
    "judgment",
    "judgement",
    "case_law",
)
COURT_SCHEMA_TERMS = {
    "case_name",
    "case_number",
    "court",
    "court_name",
    "court_level",
    "decision_date",
    "decision_type",
    "judgment_date",
    "judgement_date",
    "hanrei_id",
    "docket_number",
    "source_url",
    "source_excerpt",
}
EXCLUDED_TABLE_MARKERS = (
    "_archive",
    "_embedding",
    "_fts",
    "_vec",
)
EXCLUDED_TABLE_SUFFIXES = (
    "_config",
    "_content",
    "_data",
    "_docsize",
    "_idx",
)
ROW_ID_PRIORITY = (
    "unified_id",
    "decision_id",
    "court_id",
    "hanrei_id",
    "case_id",
    "id",
    "case_number",
)
SOURCE_URL_PRIORITY = (
    "source_url",
    "full_text_url",
    "pdf_url",
    "url",
    "href",
    "link",
)
SOURCE_TEXT_PRIORITY = (
    "source_text",
    "source_body",
    "body_text",
    "full_text",
    "decision_text",
    "judgment_text",
    "judgement_text",
    "pdf_text",
    "raw_text",
    "text_body",
    "detail_text",
    "content_text",
    "html_text",
    "ocr_text",
    "excerpt",
    "source_quote",
    "quote",
)
SUMMARY_TEXT_PRIORITY = (
    "key_ruling",
    "impact_on_business",
    "case_summary",
    "summary",
    "description",
    "overview",
    "parties_involved",
)
TEXT_NAME_EXCLUDE_TOKENS = (
    "checksum",
    "confidence",
    "date",
    "fetched",
    "id",
    "source_excerpt",
    "updated",
    "url",
)
SECTION_LABELS = (
    "判示事項",
    "裁判要旨",
    "主文",
    "事案の概要",
    "判旨",
    "当裁判所の判断",
    "事実及び理由",
    "理由",
    "参照法条",
)
SECTION_RE = re.compile(
    r"(?:【)?(" + "|".join(re.escape(label) for label in SECTION_LABELS) + r")(?:】)?\s*[:：]?\s*"
)
MAX_EXCERPT_CHARS = 400
MIN_USABLE_CHARS = 20
MIN_LABELLED_CHARS = 6


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    declared_type: str
    pk: bool


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT name
          FROM sqlite_master
         WHERE type = 'table'
         ORDER BY name
        """
    ).fetchall()
    return [str(row["name"]) for row in rows]


def _column_info(conn: sqlite3.Connection, table: str) -> list[ColumnInfo]:
    return [
        ColumnInfo(
            name=str(row["name"]),
            declared_type=str(row["type"] or ""),
            pk=bool(row["pk"]),
        )
        for row in conn.execute(f"PRAGMA table_info({_quote_ident(table)})")
    ]


def _normalize(text: Any) -> str:
    if text is None:
        return ""
    normalized = unicodedata.normalize("NFKC", str(text))
    normalized = normalized.replace("\u3000", " ")
    return re.sub(r"\s+", " ", normalized).strip()


def _trim_excerpt(text: str, *, max_chars: int = MAX_EXCERPT_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rstrip()
    last_open = cut.rfind("【")
    last_close = cut.rfind("】")
    if last_open > last_close:
        cut = cut[:last_open].rstrip()
    return cut


def _is_excluded_table(table: str) -> bool:
    lower = table.lower()
    return (
        lower.startswith("sqlite_")
        or any(marker in lower for marker in EXCLUDED_TABLE_MARKERS)
        or any(lower.endswith(suffix) for suffix in EXCLUDED_TABLE_SUFFIXES)
    )


def _is_text_column(column: ColumnInfo) -> bool:
    declared = column.declared_type.upper()
    return not any(token in declared for token in ("BLOB", "BOOL", "INT", "NUM", "REAL"))


def _name_map(columns: list[ColumnInfo]) -> dict[str, str]:
    return {column.name.lower(): column.name for column in columns}


def _is_court_like_table(table: str, columns: list[ColumnInfo]) -> bool:
    if _is_excluded_table(table):
        return False
    names = {column.name.lower() for column in columns}
    if "source_excerpt" not in names:
        return False
    if any(token in table.lower() for token in COURT_TABLE_TOKENS):
        return True
    if names & {"court", "court_name", "court_level"} and names & {"case_name", "case_number"}:
        return True
    return len(names & COURT_SCHEMA_TERMS) >= 4


def _first_existing(names: dict[str, str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in names:
            return names[candidate]
    return None


def _ordered_existing(names: dict[str, str], candidates: tuple[str, ...]) -> list[str]:
    return [names[candidate] for candidate in candidates if candidate in names]


def _source_url_column(columns: list[ColumnInfo]) -> str | None:
    names = _name_map(columns)
    priority = _first_existing(names, SOURCE_URL_PRIORITY)
    if priority:
        return priority
    for column in columns:
        lower = column.name.lower()
        if "url" in lower or lower.endswith(("href", "link", "uri")):
            return column.name
    return None


def _row_id_column(columns: list[ColumnInfo]) -> str | None:
    pk_columns = [column.name for column in columns if column.pk]
    if len(pk_columns) == 1:
        return pk_columns[0]
    names = _name_map(columns)
    return _first_existing(names, ROW_ID_PRIORITY)


def _candidate_text_columns(columns: list[ColumnInfo]) -> tuple[list[str], list[str]]:
    names = _name_map(columns)
    source_columns = _ordered_existing(names, SOURCE_TEXT_PRIORITY)
    summary_columns = _ordered_existing(names, SUMMARY_TEXT_PRIORITY)
    source_seen = set(source_columns)
    summary_seen = set(summary_columns)

    for column in columns:
        lower = column.name.lower()
        if lower in source_seen or lower in summary_seen:
            continue
        if not _is_text_column(column):
            continue
        if any(token in lower for token in TEXT_NAME_EXCLUDE_TOKENS):
            continue
        if lower.endswith("_text") or lower in {"text", "content", "body", "raw"}:
            source_columns.append(column.name)
            source_seen.add(lower)

    return source_columns, summary_columns


def _labelled_excerpt(text: str) -> str | None:
    matches = list(SECTION_RE.finditer(text))
    if not matches:
        return None

    parts: list[str] = []
    seen_labels: set[str] = set()
    for index, match in enumerate(matches):
        label = match.group(1)
        if label in seen_labels:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = _normalize(text[start:end])
        if len(body) < MIN_LABELLED_CHARS:
            continue
        parts.append(f"【{label}】{body}")
        seen_labels.add(label)
        if len("\n".join(parts)) >= MAX_EXCERPT_CHARS:
            break

    if not parts:
        return None
    return _trim_excerpt("\n".join(parts))


def _plain_excerpt(text: str) -> str | None:
    normalized = _normalize(text)
    if len(normalized) < MIN_USABLE_CHARS:
        return None
    return _trim_excerpt(normalized)


def _best_text_value(row: sqlite3.Row, columns: list[str]) -> tuple[str | None, str | None]:
    for column in columns:
        value = _normalize(row[column])
        if len(value) >= MIN_USABLE_CHARS:
            return column, value
    return None, None


def _proposal_from_row(
    *,
    table: str,
    row: sqlite3.Row,
    row_id_key: str,
    source_url_key: str | None,
    source_columns: list[str],
    summary_columns: list[str],
) -> dict[str, Any]:
    source_url = _normalize(row[source_url_key]) if source_url_key else ""
    current_excerpt = _normalize(row["source_excerpt"])
    row_id = _normalize(row[row_id_key])

    source_column, source_text = _best_text_value(row, source_columns)
    if source_text:
        labelled = _labelled_excerpt(source_text)
        if labelled:
            confidence = 0.92
            review_required = False
            reason = f"proposed from local {source_column} labelled court text"
            proposed_excerpt = labelled
        else:
            confidence = 0.78
            review_required = True
            reason = f"proposed from local {source_column} text; no court section labels found"
            proposed_excerpt = _plain_excerpt(source_text) or ""

        if not source_url:
            confidence = min(confidence, 0.65)
            review_required = True
            reason += "; source_url is missing"
        return {
            "table": table,
            "row_id": row_id,
            "source_url": source_url,
            "current_excerpt": current_excerpt,
            "proposed_excerpt": proposed_excerpt,
            "confidence": round(confidence, 2),
            "reason": reason,
            "review_required": review_required,
        }

    summary_column, summary_text = _best_text_value(row, summary_columns)
    if summary_text:
        return {
            "table": table,
            "row_id": row_id,
            "source_url": source_url,
            "current_excerpt": current_excerpt,
            "proposed_excerpt": _plain_excerpt(summary_text) or "",
            "confidence": 0.45,
            "reason": (
                f"proposed from local {summary_column} summary text; "
                "not source-verbatim and requires review"
            ),
            "review_required": True,
        }

    return {
        "table": table,
        "row_id": row_id,
        "source_url": source_url,
        "current_excerpt": current_excerpt,
        "proposed_excerpt": "",
        "confidence": 0.0,
        "reason": "unavailable: no usable local source text or summary text columns on this row",
        "review_required": True,
    }


def _select_missing_rows(
    conn: sqlite3.Connection,
    table: str,
    *,
    columns: list[ColumnInfo],
    limit: int | None,
) -> list[sqlite3.Row]:
    row_id_column = _row_id_column(columns)
    source_url_column = _source_url_column(columns)
    source_columns, summary_columns = _candidate_text_columns(columns)
    select_columns = ["source_excerpt"]
    if row_id_column:
        select_columns.append(row_id_column)
    if source_url_column:
        select_columns.append(source_url_column)
    select_columns.extend(source_columns)
    select_columns.extend(summary_columns)

    deduped_columns = list(dict.fromkeys(select_columns))
    select_sql = ", ".join(_quote_ident(column) for column in deduped_columns)
    order_column = row_id_column or source_url_column or "source_excerpt"
    sql = (
        f"SELECT {select_sql} FROM {_quote_ident(table)} "
        "WHERE source_excerpt IS NULL OR TRIM(CAST(source_excerpt AS TEXT)) = '' "
        f"ORDER BY {_quote_ident(order_column)}"
    )
    params: tuple[int, ...] = ()
    if limit is not None and limit > 0:
        sql += " LIMIT ?"
        params = (limit,)
    return list(conn.execute(sql, params))


def build_excerpt_proposals(
    db_paths: list[Path],
    *,
    limit_per_table: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    scanned_tables: list[dict[str, Any]] = []
    missing_tables: list[dict[str, str]] = []

    for db_path in db_paths:
        with _connect_readonly(db_path) as conn:
            for table in _table_names(conn):
                columns = _column_info(conn, table)
                if not _is_court_like_table(table, columns):
                    continue
                row_id_column = _row_id_column(columns)
                source_url_column = _source_url_column(columns)
                source_columns, summary_columns = _candidate_text_columns(columns)
                rows = _select_missing_rows(
                    conn,
                    table,
                    columns=columns,
                    limit=limit_per_table,
                )
                scanned_tables.append(
                    {
                        "database": str(db_path),
                        "table": table,
                        "missing_source_excerpt_rows": len(rows),
                        "row_id_column": row_id_column,
                        "source_url_column": source_url_column,
                        "source_text_columns": source_columns,
                        "summary_text_columns": summary_columns,
                    }
                )
                if not row_id_column:
                    missing_tables.append(
                        {
                            "database": str(db_path),
                            "table": table,
                            "reason": "no stable row id column detected",
                        }
                    )
                row_id_key = row_id_column or "source_excerpt"
                for row in rows:
                    proposals.append(
                        _proposal_from_row(
                            table=table,
                            row=row,
                            row_id_key=row_id_key,
                            source_url_key=source_url_column,
                            source_columns=source_columns,
                            summary_columns=summary_columns,
                        )
                    )

    metadata = {
        "databases": [str(path) for path in db_paths],
        "scanned_tables": scanned_tables,
        "tables_without_stable_row_id": missing_tables,
    }
    proposals.sort(
        key=lambda item: (
            item["table"],
            bool(item["proposed_excerpt"]),
            str(item["row_id"]),
            str(item["source_url"]),
        )
    )
    return proposals, metadata


def build_proposal_report(
    db_paths: list[Path],
    *,
    limit_per_table: int | None = None,
) -> dict[str, Any]:
    proposals, metadata = build_excerpt_proposals(db_paths, limit_per_table=limit_per_table)
    proposed = sum(1 for row in proposals if row["proposed_excerpt"])
    unavailable = len(proposals) - proposed
    return {
        "generated_at": _utc_now(),
        "report_only": True,
        "read_mode": {
            "sqlite_only": True,
            "network_fetch_performed": False,
            "db_mutation_performed": False,
        },
        "proposal_columns": PROPOSAL_COLUMNS,
        "source": metadata,
        "totals": {
            "rows_missing_source_excerpt": len(proposals),
            "proposed": proposed,
            "unavailable": unavailable,
            "review_required": sum(1 for row in proposals if row["review_required"]),
            "tables": len(metadata["scanned_tables"]),
        },
        "proposals": proposals,
        "completion_status": {
            "B5": "proposal_only",
            "complete": False,
        },
        "notes": [
            "Review-only source_excerpt proposal; no SQLite tables are updated.",
            "Proposals are extracted only from local SQLite row text.",
            "Rows without usable local text are retained with confidence 0.0 and an unavailable reason.",
        ],
    }


def write_json_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PROPOSAL_COLUMNS)
        writer.writeheader()
        for row in report.get("proposals", []):
            writer.writerow(
                {
                    **{field: row.get(field) for field in PROPOSAL_COLUMNS},
                    "confidence": f"{float(row['confidence']):.2f}",
                }
            )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        action="append",
        dest="dbs",
        type=Path,
        help="SQLite database to inspect. Repeat for multiple DBs. Defaults to data/jpintel.db.",
    )
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV_OUTPUT)
    parser.add_argument("--limit-per-table", type=int, default=None)
    parser.add_argument("--no-write-json", action="store_true")
    parser.add_argument("--no-write-csv", action="store_true")
    parser.add_argument("--json", action="store_true", help="print full JSON report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    db_paths = args.dbs or [DEFAULT_DB]
    report = build_proposal_report(db_paths, limit_per_table=args.limit_per_table)

    if not args.no_write_json:
        write_json_report(report, args.json_output)
    if not args.no_write_csv:
        write_csv_report(report, args.csv_output)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        totals = report["totals"]
        print(f"rows_missing_source_excerpt={totals['rows_missing_source_excerpt']}")
        print(f"proposed={totals['proposed']}")
        print(f"unavailable={totals['unavailable']}")
        print(f"review_required={totals['review_required']}")
        print(f"tables={totals['tables']}")
        if not args.no_write_json:
            print(f"json_output={args.json_output}")
        if not args.no_write_csv:
            print(f"csv_output={args.csv_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
