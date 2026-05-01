#!/usr/bin/env python3
"""Build a local-only B6 PDF extraction inventory and shard plan.

This report does not fetch PDFs, call external APIs, or mutate SQLite. It reads
local program tables and local filesystem metadata, then emits candidate PDF
sources plus domain-exclusive command strings for a later extraction run.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shlex
import sqlite3
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_ANALYSIS_DIR = REPO_ROOT / "analysis_wave18"
DEFAULT_RUN_DATE = "2026-05-01"
DEFAULT_JSON_OUTPUT = DEFAULT_ANALYSIS_DIR / f"pdf_extraction_inventory_{DEFAULT_RUN_DATE}.json"
DEFAULT_CSV_OUTPUT = DEFAULT_ANALYSIS_DIR / f"pdf_extraction_inventory_{DEFAULT_RUN_DATE}.csv"

PYTHON_RUNNER = ".venv/bin/python"
PDF_BATCH_SCRIPT = "scripts/etl/run_program_pdf_extraction_batch.py"
TEXT_PARSER_SCRIPT = "scripts/cron/extract_program_facts.py"
DEFAULT_SHARDS = 4
DEFAULT_SAMPLE_LIMIT = 25
DEFAULT_PER_HOST_DELAY_SEC = 1.0
DEFAULT_CACHE_DIR = Path("/tmp/jpcite_pdf_cache")
DEFAULT_TEMP_DB_DIR = Path("/tmp")

PARSER_PROFILE = "grant_env_content"
PARSER_FIELDS = ("deadline", "subsidy_rate", "required_docs", "contact", "max_amount")
APPLICATION_FORM_FIELDS = ("required_docs", "contact")

PDF_URL_RE = re.compile(r"https?://[^\s\"'<>]+?\.pdf(?:[?#][^\s\"'<>]*)?", re.IGNORECASE)

CSV_FIELDS = [
    "shard_id",
    "source_table",
    "source_column",
    "source_kind",
    "program_id",
    "program_name",
    "source_ref",
    "normalized_ref",
    "ref_type",
    "domain",
    "profile_hint",
    "parser_supported",
    "likely_fields",
    "local_file_exists",
    "local_file_path",
    "matched_local_paths",
    "batch_processable",
]

TARGET_TABLES: dict[str, dict[str, Any]] = {
    "programs": {
        "kind": "program",
        "id": ("unified_id", "program_id", "id"),
        "name": ("primary_name", "program_name", "name", "title"),
        "url": ("source_url", "official_url", "source_mentions_json"),
        "context": (
            "primary_name",
            "authority_name",
            "program_kind",
            "source_url",
            "official_url",
        ),
    },
    "jpi_programs": {
        "kind": "program",
        "id": ("unified_id", "program_id", "id"),
        "name": ("primary_name", "program_name", "name", "title"),
        "url": ("source_url", "official_url", "source_mentions_json"),
        "context": (
            "primary_name",
            "authority_name",
            "program_kind",
            "source_url",
            "official_url",
        ),
    },
    "program_documents": {
        "kind": "program_document",
        "id": ("id",),
        "name": ("program_name", "primary_name", "name", "title"),
        "url": ("form_url_direct", "completion_example_url", "source_url"),
        "context": ("program_name", "form_name", "form_type", "form_format", "source_excerpt"),
    },
    "jpi_program_documents": {
        "kind": "program_document",
        "id": ("id",),
        "name": ("program_name", "primary_name", "name", "title"),
        "url": ("form_url_direct", "completion_example_url", "source_url"),
        "context": ("program_name", "form_name", "form_type", "form_format", "source_excerpt"),
    },
    "new_program_candidates": {
        "kind": "new_program_candidate",
        "id": ("id",),
        "name": ("candidate_name", "program_name", "name", "title"),
        "url": ("source_url", "source_pdf_page"),
        "context": (
            "candidate_name",
            "mentioned_in",
            "ministry",
            "program_kind_hint",
            "policy_background_excerpt",
            "source_url",
            "source_pdf_page",
        ),
    },
}

EXCLUDED_LOCAL_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "_archive",
    "node_modules",
}


@dataclass(frozen=True)
class SourceSchema:
    table: str
    kind: str
    id_column: str | None
    name_column: str | None
    url_columns: tuple[str, ...]
    context_columns: tuple[str, ...]


@dataclass(frozen=True)
class PdfCandidate:
    source_table: str
    source_column: str
    source_kind: str
    program_id: str
    program_name: str
    source_ref: str
    normalized_ref: str
    ref_type: str
    domain: str
    profile_hint: str
    parser_supported: bool
    likely_fields: tuple[str, ...]
    local_file_exists: bool
    local_file_path: str
    matched_local_paths: tuple[str, ...]
    batch_processable: bool
    shard_id: str = ""


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


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({_qident(table)})").fetchall()
    )


def _choose_column(columns: set[str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def discover_source_schemas(conn: sqlite3.Connection) -> list[SourceSchema]:
    schemas: list[SourceSchema] = []
    for table, spec in TARGET_TABLES.items():
        if not _table_exists(conn, table):
            continue
        columns = _table_columns(conn, table)
        column_set = set(columns)
        url_columns = tuple(column for column in spec["url"] if column in column_set)
        if not url_columns:
            continue
        schemas.append(
            SourceSchema(
                table=table,
                kind=str(spec["kind"]),
                id_column=_choose_column(column_set, tuple(spec["id"])),
                name_column=_choose_column(column_set, tuple(spec["name"])),
                url_columns=url_columns,
                context_columns=tuple(
                    column for column in spec["context"] if column in column_set
                ),
            )
        )
    return schemas


def _looks_like_json(value: str) -> bool:
    stripped = value.strip()
    return (stripped.startswith("{") and stripped.endswith("}")) or (
        stripped.startswith("[") and stripped.endswith("]")
    )


def _iter_string_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        if _looks_like_json(value):
            try:
                loaded = json.loads(value)
            except json.JSONDecodeError:
                return [value]
            return _iter_string_values(loaded)
        return [value]
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(_iter_string_values(item))
        return out
    if isinstance(value, list | tuple):
        out = []
        for item in value:
            out.extend(_iter_string_values(item))
        return out
    return [str(value)]


def _clean_ref(value: str) -> str:
    return value.strip().rstrip(").,;、。）」』】]")


def extract_pdf_references(value: Any) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for text in _iter_string_values(value):
        remote_matches = [_clean_ref(match.group(0)) for match in PDF_URL_RE.finditer(text)]
        without_remote = PDF_URL_RE.sub(" ", text)
        local_matches: list[str] = []
        for token in re.split(r"[\s\"'<>]+", without_remote):
            cleaned = _clean_ref(token)
            if cleaned.startswith("file://"):
                local_matches.append(cleaned)
                continue
            if "://" in cleaned:
                continue
            if not cleaned.lower().endswith(".pdf"):
                continue
            if "/" in cleaned or "\\" in cleaned:
                local_matches.append(cleaned)
        for ref in [*remote_matches, *local_matches]:
            if ref and ref not in seen:
                seen.add(ref)
                refs.append(ref)
    return refs


def _is_remote_ref(ref: str) -> bool:
    return urllib.parse.urlsplit(ref).scheme.lower() in {"http", "https"}


def _domain(ref: str) -> str:
    if not _is_remote_ref(ref):
        return ""
    return (urllib.parse.urlsplit(ref).hostname or "").lower().rstrip(".")


def _normalize_remote_ref(ref: str) -> str:
    parts = urllib.parse.urlsplit(ref)
    return urllib.parse.urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path,
            parts.query,
            "",
        )
    )


def _resolve_local_ref(ref: str, *, local_root: Path) -> Path:
    if ref.startswith("file://"):
        parsed = urllib.parse.urlsplit(ref)
        path = Path(urllib.parse.unquote(parsed.path))
    else:
        path = Path(ref).expanduser()
    if not path.is_absolute():
        path = local_root / path
    return path


def _normalize_ref(ref: str, *, local_root: Path) -> tuple[str, str, str, bool]:
    if _is_remote_ref(ref):
        normalized = _normalize_remote_ref(ref)
        return normalized, "remote_url", _domain(normalized), False
    local_path = _resolve_local_ref(ref, local_root=local_root)
    exists = local_path.exists()
    return str(local_path), "local_file", "", exists


def _pdf_basename(ref: str) -> str:
    if _is_remote_ref(ref):
        path = urllib.parse.urlsplit(ref).path
    else:
        path = urllib.parse.urlsplit(ref).path if ref.startswith("file://") else ref
    name = Path(urllib.parse.unquote(path)).name
    return name.lower() if name.lower().endswith(".pdf") else ""


def _profile_hint(source_kind: str, context: str) -> str:
    lowered = context.lower()
    if re.search(r"(申請書|様式|form|application)", lowered) and source_kind == "program_document":
        return "application_form_candidate"
    if re.search(
        r"(公募要領|募集要領|募集|公募|要領|手引|補助|助成|grant|subsidy|guideline|outline|youryou|koubo)",
        lowered,
    ):
        return PARSER_PROFILE
    if source_kind in {"program", "new_program_candidate"}:
        return PARSER_PROFILE
    return "unknown_pdf_profile"


def _likely_fields(profile_hint: str) -> tuple[str, ...]:
    if profile_hint == PARSER_PROFILE:
        return PARSER_FIELDS
    if profile_hint == "application_form_candidate":
        return APPLICATION_FORM_FIELDS
    return ()


def _row_context(row: sqlite3.Row, columns: tuple[str, ...]) -> str:
    return " ".join(str(row[column] or "") for column in columns)


def _candidate_query(schema: SourceSchema) -> str:
    selected = {
        column
        for column in (
            schema.id_column,
            schema.name_column,
            *schema.url_columns,
            *schema.context_columns,
        )
        if column is not None
    }
    select_clause = ", ".join(_qident(column) for column in sorted(selected))
    predicates = " OR ".join(
        f"lower(coalesce({_qident(column)}, '')) LIKE '%.pdf%'"
        for column in schema.url_columns
    )
    return (
        f"SELECT {select_clause} FROM {_qident(schema.table)} "
        f"WHERE {predicates} ORDER BY 1"
    )


def collect_pdf_candidates(
    conn: sqlite3.Connection,
    *,
    local_root: Path,
) -> tuple[list[PdfCandidate], list[SourceSchema]]:
    schemas = discover_source_schemas(conn)
    candidates: list[PdfCandidate] = []
    seen_row_refs: set[tuple[str, str, str, str]] = set()

    for schema in schemas:
        for row in conn.execute(_candidate_query(schema)).fetchall():
            program_id = str(row[schema.id_column] if schema.id_column else "") or ""
            program_name = str(row[schema.name_column] if schema.name_column else "") or ""
            context = f"{program_name} {_row_context(row, schema.context_columns)}"
            for column in schema.url_columns:
                for ref in extract_pdf_references(row[column]):
                    normalized, ref_type, domain, exists = _normalize_ref(
                        ref,
                        local_root=local_root,
                    )
                    row_key = (schema.table, column, program_id, normalized)
                    if row_key in seen_row_refs:
                        continue
                    seen_row_refs.add(row_key)
                    profile = _profile_hint(schema.kind, f"{context} {column} {ref}")
                    fields = _likely_fields(profile)
                    local_file_path = normalized if ref_type == "local_file" else ""
                    candidates.append(
                        PdfCandidate(
                            source_table=schema.table,
                            source_column=column,
                            source_kind=schema.kind,
                            program_id=program_id,
                            program_name=program_name,
                            source_ref=ref,
                            normalized_ref=normalized,
                            ref_type=ref_type,
                            domain=domain,
                            profile_hint=profile,
                            parser_supported=profile == PARSER_PROFILE,
                            likely_fields=fields,
                            local_file_exists=exists,
                            local_file_path=local_file_path,
                            matched_local_paths=(),
                            batch_processable=(
                                schema.kind == "program"
                                and column == "source_url"
                                and ref_type == "remote_url"
                            ),
                        )
                    )
    return candidates, schemas


def discover_local_pdf_files(local_root: Path) -> list[Path]:
    if not local_root.exists():
        return []
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(local_root):
        dirnames[:] = [
            name for name in dirnames if name not in EXCLUDED_LOCAL_DIRS and not name.endswith(".egg-info")
        ]
        for filename in filenames:
            if filename.lower().endswith(".pdf"):
                files.append(Path(dirpath) / filename)
    return sorted(files, key=lambda path: str(path))


def attach_local_file_matches(
    candidates: list[PdfCandidate],
    local_files: list[Path],
) -> list[PdfCandidate]:
    by_basename: dict[str, list[str]] = defaultdict(list)
    for path in local_files:
        by_basename[path.name.lower()].append(str(path))

    out: list[PdfCandidate] = []
    for candidate in candidates:
        matched = tuple(sorted(by_basename.get(_pdf_basename(candidate.normalized_ref), [])))
        if candidate.ref_type == "local_file" and candidate.local_file_path:
            matched = tuple(sorted({*matched, candidate.local_file_path}))
        out.append(
            PdfCandidate(
                **{
                    **asdict(candidate),
                    "matched_local_paths": matched,
                }
            )
        )
    return out


def _duration(seconds: int) -> str:
    if seconds <= 0:
        return "0s"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def _domain_counts(candidates: list[PdfCandidate]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if candidate.ref_type != "remote_url" or not candidate.domain:
            continue
        entry = grouped.setdefault(
            candidate.domain,
            {
                "domain": candidate.domain,
                "candidate_rows": 0,
                "unique_sources": set(),
                "batch_processable_rows": 0,
            },
        )
        entry["candidate_rows"] += 1
        entry["unique_sources"].add(candidate.normalized_ref)
        if candidate.batch_processable:
            entry["batch_processable_rows"] += 1

    rows: list[dict[str, Any]] = []
    for entry in grouped.values():
        unique_sources = entry["unique_sources"]
        rows.append(
            {
                "domain": entry["domain"],
                "candidate_rows": int(entry["candidate_rows"]),
                "unique_source_count": len(unique_sources),
                "batch_processable_rows": int(entry["batch_processable_rows"]),
            }
        )
    return sorted(rows, key=lambda item: (-int(item["unique_source_count"]), str(item["domain"])))


def build_domain_exclusive_shards(
    domain_counts: list[dict[str, Any]],
    *,
    shard_count: int = DEFAULT_SHARDS,
) -> list[dict[str, Any]]:
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    buckets = [
        {
            "shard_id": str(index + 1),
            "domains": [],
            "candidate_rows": 0,
            "unique_source_count": 0,
            "batch_processable_rows": 0,
        }
        for index in range(shard_count)
    ]
    for domain in domain_counts:
        bucket = min(
            buckets,
            key=lambda item: (
                int(item["unique_source_count"]),
                int(item["candidate_rows"]),
                int(item["shard_id"]),
            ),
        )
        bucket["domains"].append(str(domain["domain"]))
        bucket["candidate_rows"] += int(domain["candidate_rows"])
        bucket["unique_source_count"] += int(domain["unique_source_count"])
        bucket["batch_processable_rows"] += int(domain["batch_processable_rows"])

    shards: list[dict[str, Any]] = []
    for bucket in buckets:
        if not bucket["domains"]:
            continue
        domains = sorted(str(domain) for domain in bucket["domains"])
        shards.append(
            {
                "shard_id": bucket["shard_id"],
                "domain_count": len(domains),
                "domains": domains,
                "candidate_rows": int(bucket["candidate_rows"]),
                "unique_source_count": int(bucket["unique_source_count"]),
                "batch_processable_rows": int(bucket["batch_processable_rows"]),
                "serial_lower_bound_seconds_at_1_req_per_sec": int(
                    bucket["unique_source_count"]
                ),
                "serial_lower_bound_duration_at_1_req_per_sec": _duration(
                    int(bucket["unique_source_count"])
                ),
            }
        )
    return shards


def assign_candidate_shards(
    candidates: list[PdfCandidate],
    shards: list[dict[str, Any]],
) -> list[PdfCandidate]:
    domain_to_shard = {
        domain: str(shard["shard_id"])
        for shard in shards
        for domain in shard["domains"]
    }
    assigned: list[PdfCandidate] = []
    for candidate in candidates:
        shard_id = domain_to_shard.get(candidate.domain, "local")
        assigned.append(PdfCandidate(**{**asdict(candidate), "shard_id": shard_id}))
    return assigned


def _materialize_command_code() -> str:
    return (
        "import csv,sqlite3,sys;"
        "from pathlib import Path;"
        "csv_path,shard_id,out_db=sys.argv[1:4];"
        "rows=[r for r in csv.DictReader(open(csv_path,encoding='utf-8')) "
        "if r.get('shard_id')==shard_id and r.get('batch_processable')=='true'];"
        "p=Path(out_db);p.unlink(missing_ok=True);"
        "conn=sqlite3.connect(out_db);"
        "conn.execute('CREATE TABLE programs(unified_id TEXT, source_url TEXT)');"
        "conn.executemany('INSERT INTO programs(unified_id, source_url) VALUES (?, ?)', "
        "[(r.get('program_id') or '', r.get('source_ref') or '') for r in rows]);"
        "conn.commit();conn.close();"
        "print(f'materialized {len(rows)} B6 rows into {out_db}')"
    )


def build_shard_run_command(
    *,
    shard_id: str,
    db_path: Path,
    csv_output: Path,
    result_dir: Path,
    run_date: str,
    python_runner: str = PYTHON_RUNNER,
    batch_script: str = PDF_BATCH_SCRIPT,
    temp_db_dir: Path = DEFAULT_TEMP_DB_DIR,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    per_host_delay_sec: float = DEFAULT_PER_HOST_DELAY_SEC,
) -> str:
    temp_db = temp_db_dir / f"jpcite_pdf_extraction_shard_{int(shard_id):02d}_{run_date}.db"
    output = result_dir / f"pdf_extraction_batch_shard_{int(shard_id):02d}_{run_date}.csv"
    code = _materialize_command_code()
    materialize = " ".join(
        [
            shlex.quote(python_runner),
            "-c",
            shlex.quote(code),
            shlex.quote(str(csv_output)),
            shlex.quote(shard_id),
            shlex.quote(str(temp_db)),
        ]
    )
    run_batch = " ".join(
        shlex.quote(arg)
        for arg in (
            python_runner,
            batch_script,
            "--db",
            str(temp_db),
            "--output",
            str(output),
            "--cache-dir",
            str(cache_dir),
            "--per-host-delay",
            str(per_host_delay_sec),
            "--progress-every",
            "25",
        )
    )
    source_env = f"JPINTEL_SOURCE_DB={shlex.quote(str(db_path))}"
    return f"{source_env} {materialize} && {run_batch}"


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items()))


def _candidate_row(candidate: PdfCandidate) -> dict[str, str]:
    return {
        "shard_id": candidate.shard_id,
        "source_table": candidate.source_table,
        "source_column": candidate.source_column,
        "source_kind": candidate.source_kind,
        "program_id": candidate.program_id,
        "program_name": candidate.program_name,
        "source_ref": candidate.source_ref,
        "normalized_ref": candidate.normalized_ref,
        "ref_type": candidate.ref_type,
        "domain": candidate.domain,
        "profile_hint": candidate.profile_hint,
        "parser_supported": "true" if candidate.parser_supported else "false",
        "likely_fields": ",".join(candidate.likely_fields),
        "local_file_exists": "true" if candidate.local_file_exists else "false",
        "local_file_path": candidate.local_file_path,
        "matched_local_paths": json.dumps(list(candidate.matched_local_paths), ensure_ascii=False),
        "batch_processable": "true" if candidate.batch_processable else "false",
    }


def collect_pdf_extraction_inventory(
    conn: sqlite3.Connection,
    *,
    db_path: Path = DEFAULT_DB,
    local_root: Path = REPO_ROOT,
    analysis_dir: Path = DEFAULT_ANALYSIS_DIR,
    csv_output: Path = DEFAULT_CSV_OUTPUT,
    run_date: str = DEFAULT_RUN_DATE,
    shard_count: int = DEFAULT_SHARDS,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
    python_runner: str = PYTHON_RUNNER,
    batch_script: str = PDF_BATCH_SCRIPT,
    temp_db_dir: Path = DEFAULT_TEMP_DB_DIR,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    per_host_delay_sec: float = DEFAULT_PER_HOST_DELAY_SEC,
) -> dict[str, Any]:
    if sample_limit < 0:
        raise ValueError("sample_limit must be non-negative")
    if per_host_delay_sec < 1.0:
        raise ValueError("per_host_delay_sec must be at least 1.0")

    candidates, schemas = collect_pdf_candidates(conn, local_root=local_root)
    local_files = discover_local_pdf_files(local_root)
    candidates = attach_local_file_matches(candidates, local_files)
    domain_counts = _domain_counts(candidates)
    shards = build_domain_exclusive_shards(domain_counts, shard_count=shard_count)
    candidates = assign_candidate_shards(candidates, shards)

    by_profile = Counter(candidate.profile_hint for candidate in candidates)
    by_field = Counter(
        field for candidate in candidates for field in candidate.likely_fields
    )
    by_table = Counter(candidate.source_table for candidate in candidates)
    by_column = Counter(
        f"{candidate.source_table}.{candidate.source_column}" for candidate in candidates
    )
    unique_sources = {candidate.normalized_ref for candidate in candidates}
    unique_remote_sources = {
        candidate.normalized_ref for candidate in candidates if candidate.ref_type == "remote_url"
    }
    unique_local_sources = {
        candidate.normalized_ref for candidate in candidates if candidate.ref_type == "local_file"
    }
    matched_local_paths = {
        path for candidate in candidates for path in candidate.matched_local_paths
    }

    shard_commands = []
    for shard in shards:
        run_command = build_shard_run_command(
            shard_id=str(shard["shard_id"]),
            db_path=db_path,
            csv_output=csv_output,
            result_dir=analysis_dir,
            run_date=run_date,
            python_runner=python_runner,
            batch_script=batch_script,
            temp_db_dir=temp_db_dir,
            cache_dir=cache_dir,
            per_host_delay_sec=per_host_delay_sec,
        )
        shard_commands.append({**shard, "run_command": run_command})

    candidate_rows = [_candidate_row(candidate) for candidate in candidates]
    candidate_rows.sort(
        key=lambda row: (
            row["shard_id"],
            row["domain"],
            row["source_table"],
            row["program_id"],
            row["normalized_ref"],
        )
    )

    return {
        "report": "b6_pdf_extraction_inventory",
        "generated_at": _utc_now(),
        "run_date": run_date,
        "report_only": True,
        "mutates_db": False,
        "network_fetch_performed": False,
        "external_api_calls": False,
        "inputs": {
            "database": str(db_path),
            "local_root": str(local_root),
            "analysis_dir": str(analysis_dir),
            "csv_output": str(csv_output),
        },
        "read_mode": {
            "sqlite_mode": "read-only/query-only",
            "filesystem_scan_only": True,
            "pdf_bytes_read": False,
            "pdf_text_extracted": False,
        },
        "source_schemas": [asdict(schema) for schema in schemas],
        "parser_scripts": {
            "text_fact_parser": {
                "path": TEXT_PARSER_SCRIPT,
                "exists": (REPO_ROOT / TEXT_PARSER_SCRIPT).exists(),
                "supported_profiles": [
                    {"profile": PARSER_PROFILE, "fields": list(PARSER_FIELDS)}
                ],
            },
            "pdf_batch_runner": {
                "path": batch_script,
                "exists": (REPO_ROOT / batch_script).exists(),
                "note": (
                    "Runner may fetch PDFs when executed later. This inventory only emits "
                    "command strings and did not execute it."
                ),
            },
        },
        "totals": {
            "candidate_pdf_rows": len(candidates),
            "unique_pdf_sources": len(unique_sources),
            "remote_pdf_candidate_rows": sum(
                1 for candidate in candidates if candidate.ref_type == "remote_url"
            ),
            "unique_remote_pdf_sources": len(unique_remote_sources),
            "local_pdf_candidate_rows": sum(
                1 for candidate in candidates if candidate.ref_type == "local_file"
            ),
            "unique_local_pdf_sources": len(unique_local_sources),
            "local_pdf_candidate_rows_existing": sum(
                1
                for candidate in candidates
                if candidate.ref_type == "local_file" and candidate.local_file_exists
            ),
            "local_pdf_files_seen_under_root": len(local_files),
            "local_pdf_files_relevant_by_reference_or_basename": len(matched_local_paths),
            "batch_processable_candidate_rows": sum(
                1 for candidate in candidates if candidate.batch_processable
            ),
            "batch_processable_unique_sources": len(
                {
                    candidate.normalized_ref
                    for candidate in candidates
                    if candidate.batch_processable
                }
            ),
        },
        "domains": domain_counts,
        "profile_counts": _counter_dict(by_profile),
        "likely_extractable_field_counts": _counter_dict(by_field),
        "source_table_counts": _counter_dict(by_table),
        "source_column_counts": _counter_dict(by_column),
        "local_files": {
            "scan_root": str(local_root),
            "total_pdf_files_seen": len(local_files),
            "relevant_pdf_files_seen": sorted(matched_local_paths),
            "sample_pdf_files_seen": [str(path) for path in local_files[:sample_limit]],
        },
        "shard_plan": {
            "strategy": (
                "Domain-exclusive greedy shards over remote PDF sources. Commands are "
                "strings only; the inventory did not execute them."
            ),
            "shard_count": len(shards),
            "requested_shard_count": shard_count,
            "domain_exclusive": True,
            "per_host_delay_sec_for_later_runner": per_host_delay_sec,
            "shards": shard_commands,
        },
        "candidate_rows": candidate_rows,
        "sample_candidate_rows": candidate_rows[:sample_limit],
        "csv_fields": CSV_FIELDS,
        "completion_status": {
            "B6": "inventory_and_plan_only",
            "complete": False,
            "reason": (
                "This step counted local PDF candidates and planned shards only; it did "
                "not fetch PDFs, extract PDF text, or promote parsed facts."
            ),
        },
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
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in report["candidate_rows"]:
            writer.writerow({field: row[field] for field in CSV_FIELDS})


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--local-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--analysis-dir", type=Path, default=DEFAULT_ANALYSIS_DIR)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV_OUTPUT)
    parser.add_argument("--run-date", default=DEFAULT_RUN_DATE)
    parser.add_argument("--shards", type=int, default=DEFAULT_SHARDS)
    parser.add_argument("--sample-limit", type=int, default=DEFAULT_SAMPLE_LIMIT)
    parser.add_argument("--python-runner", default=PYTHON_RUNNER)
    parser.add_argument("--batch-script", default=PDF_BATCH_SCRIPT)
    parser.add_argument("--temp-db-dir", type=Path, default=DEFAULT_TEMP_DB_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--per-host-delay-sec", type=float, default=DEFAULT_PER_HOST_DELAY_SEC)
    parser.add_argument("--json", action="store_true", help="print full JSON to stdout")
    parser.add_argument("--no-write", action="store_true", help="do not write JSON/CSV outputs")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    with _connect_readonly(args.db) as conn:
        report = collect_pdf_extraction_inventory(
            conn,
            db_path=args.db,
            local_root=args.local_root,
            analysis_dir=args.analysis_dir,
            csv_output=args.csv_output,
            run_date=args.run_date,
            shard_count=args.shards,
            sample_limit=args.sample_limit,
            python_runner=args.python_runner,
            batch_script=args.batch_script,
            temp_db_dir=args.temp_db_dir,
            cache_dir=args.cache_dir,
            per_host_delay_sec=args.per_host_delay_sec,
        )

    if not args.no_write:
        write_json_report(report, args.json_output)
        write_csv_report(report, args.csv_output)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        totals = report["totals"]
        print(f"json_output={args.json_output}")
        print(f"csv_output={args.csv_output}")
        print(f"candidate_pdf_rows={totals['candidate_pdf_rows']}")
        print(f"unique_pdf_sources={totals['unique_pdf_sources']}")
        print(f"unique_remote_pdf_sources={totals['unique_remote_pdf_sources']}")
        print(f"local_pdf_candidate_rows={totals['local_pdf_candidate_rows']}")
        print(f"shard_count={report['shard_plan']['shard_count']}")
        print("completion_status=inventory_and_plan_only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
