#!/usr/bin/env python3
"""Build review-only license-label proposals for official B11/B12 rows.

This script reads local SQLite only and never updates the database. It emits
CSV/JSON queues for finance/procurement rows whose source domains map to a
repo-established license rule, especially public official domains that should
be reviewed before any row-level license fill.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "autonomath.db"
DEFAULT_CSV = (
    REPO_ROOT / "analysis_wave18" / "official_license_label_proposals_2026-05-01.csv"
)
DEFAULT_JSON = (
    REPO_ROOT / "analysis_wave18" / "official_license_label_proposals_2026-05-01.json"
)

BLOCKED_OR_UNSET_LICENSES = {"", "unknown", "proprietary"}
PUBLIC_LICENSES = {"pdl_v1.0", "cc_by_4.0", "gov_standard_v2.0", "public_domain"}
LICENSE_ALIASES = {
    "gov-standard": "gov_standard_v2.0",
    "gov_standard": "gov_standard_v2.0",
    "government-standard": "gov_standard_v2.0",
    "government_standard": "gov_standard_v2.0",
    "pdl": "pdl_v1.0",
    "public data license": "pdl_v1.0",
    "cc-by-4.0": "cc_by_4.0",
    "cc-by": "cc_by_4.0",
}

FINANCE_TERMS = (
    "loan",
    "finance",
    "guarantee",
    "kinyu",
    "yushi",
    "融資",
    "貸付",
    "信用保証",
    "保証協会",
    "日本政策金融公庫",
    "日本公庫",
    "セーフティネット保証",
)
FINANCE_SIGNAL_COLUMNS = (
    "primary_name",
    "program_name",
    "authority_name",
    "provider",
    "program_kind",
    "official_url",
    "source_url",
)
SOURCE_TARGET_TERMS = (
    "p-portal.go.jp",
    "maff.go.jp/j/supply",
    "jfc.go.jp/n/finance",
    "chusho.meti.go.jp/kinyu",
    "zenshinhoren.or.jp",
    "cgc-",
)

CSV_FIELDS = [
    "task",
    "table_name",
    "entity_id",
    "id_column",
    "source_id",
    "source_url",
    "domain",
    "current_license",
    "proposed_license",
    "confidence",
    "reason",
    "review_required",
]


@dataclass(frozen=True)
class LicenseRule:
    pattern: re.Pattern[str]
    proposed_license: str
    confidence: float
    reason: str


@dataclass(frozen=True)
class SourceLicense:
    source_id: str
    license: str
    domain: str


@dataclass(frozen=True)
class CandidateTable:
    table_name: str
    task: str
    id_columns: tuple[str, ...]
    url_columns: tuple[str, ...]
    finance_filter: bool = False


# Mirrors repo-established public/proprietary domain stance from
# scripts/fill_license.py, with B11/B12 target hosts made explicit.
LICENSE_RULES: tuple[LicenseRule, ...] = (
    LicenseRule(
        re.compile(r"(^|\.)nta\.go\.jp$"),
        "pdl_v1.0",
        0.98,
        "NTA domain is hardcoded as PDL v1.0 in repo license rules",
    ),
    LicenseRule(
        re.compile(r"(^|\.)(elaws\.e-gov|laws\.e-gov|e-gov)\.go\.jp$"),
        "cc_by_4.0",
        0.96,
        "e-Gov law domains are hardcoded as CC-BY 4.0 in repo license rules",
    ),
    LicenseRule(
        re.compile(r"(^|\.)(info\.)?gbiz\.go\.jp$"),
        "cc_by_4.0",
        0.96,
        "gBizINFO domains are hardcoded as CC-BY 4.0 in repo license rules",
    ),
    LicenseRule(
        re.compile(r"(^|\.)courts\.go\.jp$"),
        "public_domain",
        0.97,
        "court domains are hardcoded as public_domain in repo license rules",
    ),
    LicenseRule(
        re.compile(r"(^|\.)(jstage\.jst|jst)\.go\.jp$"),
        "proprietary",
        0.90,
        "JST/J-STAGE domains are hardcoded as proprietary in repo license rules",
    ),
    LicenseRule(
        re.compile(r"(^|\.)zenshinhoren\.or\.jp$"),
        "proprietary",
        0.86,
        "zenshinhoren.or.jp is .or.jp and existing local source rows are proprietary",
    ),
    LicenseRule(
        re.compile(r"(^|\.)jfc\.go\.jp$"),
        "gov_standard_v2.0",
        0.96,
        "JFC domain is hardcoded as gov_standard_v2.0 in repo license rules",
    ),
    LicenseRule(
        re.compile(r"(^|\.)p-portal\.go\.jp$"),
        "gov_standard_v2.0",
        0.94,
        "government procurement portal is a .go.jp B11 official source",
    ),
    LicenseRule(
        re.compile(
            r"(^|\.)(maff|meti|mhlw|mlit|env|cao|kantei|mof|mext|soumu)\.go\.jp$"
        ),
        "gov_standard_v2.0",
        0.95,
        "ministry .go.jp domains are hardcoded as gov_standard_v2.0 in repo license rules",
    ),
    LicenseRule(
        re.compile(r"\.lg\.jp$"),
        "gov_standard_v2.0",
        0.90,
        "local-government .lg.jp domains are hardcoded as gov_standard_v2.0",
    ),
    LicenseRule(
        re.compile(r"(^|\.)pref\.[a-z]+\.jp$"),
        "gov_standard_v2.0",
        0.88,
        "prefecture domains are hardcoded as gov_standard_v2.0 in repo license rules",
    ),
    LicenseRule(
        re.compile(r"(^|\.)city\.[a-z.]+\.jp$"),
        "gov_standard_v2.0",
        0.88,
        "city domains are hardcoded as gov_standard_v2.0 in repo license rules",
    ),
    LicenseRule(
        re.compile(r"\.metro\.tokyo\.jp$"),
        "gov_standard_v2.0",
        0.88,
        "Tokyo metropolitan domains are hardcoded as gov_standard_v2.0",
    ),
    LicenseRule(
        re.compile(r"\.go\.jp$"),
        "gov_standard_v2.0",
        0.87,
        "generic .go.jp catch-all is hardcoded as gov_standard_v2.0",
    ),
    LicenseRule(
        re.compile(r"\.or\.jp$"),
        "proprietary",
        0.80,
        ".or.jp catch-all is hardcoded as proprietary in repo license rules",
    ),
    LicenseRule(
        re.compile(r"\.co\.jp$"),
        "proprietary",
        0.80,
        ".co.jp catch-all is hardcoded as proprietary in repo license rules",
    ),
)

CANDIDATE_TABLES = (
    CandidateTable(
        table_name="jpi_bids",
        task="B11",
        id_columns=("unified_id", "id"),
        url_columns=("source_url", "official_url", "notice_url", "url"),
    ),
    CandidateTable(
        table_name="bids",
        task="B11",
        id_columns=("unified_id", "id"),
        url_columns=("source_url", "official_url", "notice_url", "url"),
    ),
    CandidateTable(
        table_name="jpi_loan_programs",
        task="B12",
        id_columns=("id", "unified_id"),
        url_columns=("official_url", "source_url", "url"),
    ),
    CandidateTable(
        table_name="loan_programs",
        task="B12",
        id_columns=("id", "unified_id"),
        url_columns=("official_url", "source_url", "url"),
    ),
    CandidateTable(
        table_name="jpi_programs",
        task="B12",
        id_columns=("unified_id", "id"),
        url_columns=("source_url", "official_url", "url"),
        finance_filter=True,
    ),
    CandidateTable(
        table_name="programs",
        task="B12",
        id_columns=("unified_id", "id"),
        url_columns=("source_url", "official_url", "url"),
        finance_filter=True,
    ),
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({_quote_ident(table)})")}


def _first_existing(columns: set[str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _row_keys(row: sqlite3.Row) -> tuple[str, ...]:
    return tuple(str(key) for key in dict(row))


def _row_value(row: sqlite3.Row, column: str | None) -> str:
    if not column or column not in _row_keys(row):
        return ""
    value = row[column]
    if value is None:
        return ""
    return str(value).strip()


def _normalize_license(value: str | None) -> str:
    cleaned = (value or "").strip().lower()
    return LICENSE_ALIASES.get(cleaned, cleaned)


def _domain_from_url(source_url: str) -> str:
    text = source_url.strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if not parsed.netloc and text.startswith("www."):
        parsed = urlparse(f"https://{text}")
    return (parsed.hostname or parsed.netloc).lower()


def _domain_for_row(source_url: str, stored_domain: str = "") -> str:
    return stored_domain.strip().lower() or _domain_from_url(source_url)


def classify_domain(domain: str) -> tuple[str, float, str] | None:
    normalized = domain.strip().lower()
    if not normalized:
        return None
    for rule in LICENSE_RULES:
        if rule.pattern.search(normalized):
            return rule.proposed_license, rule.confidence, rule.reason
    return None


def classify_source_url(source_url: str, stored_domain: str = "") -> tuple[str, float, str] | None:
    return classify_domain(_domain_for_row(source_url, stored_domain))


def _source_license_index(conn: sqlite3.Connection) -> dict[str, SourceLicense]:
    if not _table_exists(conn, "am_source"):
        return {}
    columns = _columns(conn, "am_source")
    if not {"id", "source_url"} <= columns:
        return {}
    license_expr = "license" if "license" in columns else "NULL AS license"
    domain_expr = "domain" if "domain" in columns else "NULL AS domain"
    rows = conn.execute(
        f"""
        SELECT id, source_url, {license_expr}, {domain_expr}
          FROM am_source
         WHERE source_url IS NOT NULL
           AND TRIM(CAST(source_url AS TEXT)) != ''
        """
    )
    index: dict[str, SourceLicense] = {}
    for row in rows:
        source_url = str(row["source_url"]).strip()
        if not source_url:
            continue
        index[source_url] = SourceLicense(
            source_id=str(row["id"]),
            license=str(row["license"] or "").strip(),
            domain=str(row["domain"] or "").strip().lower(),
        )
    return index


def _has_finance_signal(row: sqlite3.Row, source_url: str) -> bool:
    # NTA tax-answer rows can contain "貸付" in a non-finance-program sense
    # (for example tax treatment of lent assets). Keep B12 scoped to finance
    # and guarantee program sources, while classify_source_url still supports
    # PDL for explicit review calls and future PDL finance sources.
    if "nta.go.jp" in source_url.lower():
        return False

    text = source_url.lower()
    for key in _row_keys(row):
        if key not in FINANCE_SIGNAL_COLUMNS:
            continue
        value = row[key]
        if value is not None:
            text += " " + str(value).lower()
    if any(term.lower() in text for term in FINANCE_TERMS):
        return True
    return any(term in source_url.lower() for term in SOURCE_TARGET_TERMS[2:])


def _is_target_source_manifest_row(source_url: str, domain: str) -> bool:
    text = f"{source_url} {domain}".lower()
    return any(term in text for term in SOURCE_TARGET_TERMS)


def _license_column(columns: set[str]) -> str | None:
    for candidate in ("license", "source_license", "license_id", "license_status"):
        if candidate in columns:
            return candidate
    for column in sorted(columns):
        if "license" in column.lower():
            return column
    return None


def _proposal_reason(
    *,
    domain: str,
    proposed_license: str,
    rule_reason: str,
    current_license: str,
    table_has_license_column: bool,
    source_license: SourceLicense | None,
) -> str:
    parts = [f"{domain} matched {proposed_license}: {rule_reason}"]
    if not table_has_license_column:
        parts.append("row table has no row-level license column")
    if current_license:
        parts.append(f"current_license={current_license}")
    else:
        parts.append("current_license is blank or unavailable")
    if source_license is not None:
        source_value = source_license.license or "blank"
        parts.append(f"am_source[{source_license.source_id}] license={source_value}")
    parts.append("review-only proposal; no DB update performed")
    return "; ".join(parts)


def _proposal_from_parts(
    *,
    task: str,
    table_name: str,
    entity_id: str,
    id_column: str,
    source_id: str,
    source_url: str,
    domain: str,
    current_license: str,
    proposed_license: str,
    confidence: float,
    reason: str,
) -> dict[str, Any]:
    return {
        "task": task,
        "table_name": table_name,
        "entity_id": entity_id,
        "id_column": id_column,
        "source_id": source_id,
        "source_url": source_url,
        "domain": domain,
        "current_license": current_license,
        "proposed_license": proposed_license,
        "confidence": round(confidence, 3),
        "reason": reason,
        "review_required": True,
    }


def _needs_proposal(
    *,
    current_license: str,
    proposed_license: str,
    table_has_license_column: bool,
) -> bool:
    normalized_current = _normalize_license(current_license)
    if not table_has_license_column:
        return True
    if normalized_current != proposed_license:
        return True
    return normalized_current in BLOCKED_OR_UNSET_LICENSES


def _collect_from_candidate_table(
    conn: sqlite3.Connection,
    spec: CandidateTable,
    source_index: dict[str, SourceLicense],
) -> list[dict[str, Any]]:
    if not _table_exists(conn, spec.table_name):
        return []

    columns = _columns(conn, spec.table_name)
    id_column = _first_existing(columns, spec.id_columns)
    url_column = _first_existing(columns, spec.url_columns)
    if url_column is None:
        return []
    license_column = _license_column(columns)
    table_has_license_column = license_column is not None

    rows = conn.execute(f"SELECT * FROM {_quote_ident(spec.table_name)}")
    proposals: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        source_url = _row_value(row, url_column)
        if not source_url:
            continue
        if spec.finance_filter and not _has_finance_signal(row, source_url):
            continue

        source_license = source_index.get(source_url)
        domain = _domain_for_row(source_url, source_license.domain if source_license else "")
        classified = classify_domain(domain)
        if classified is None:
            continue

        proposed_license, confidence, rule_reason = classified
        current_license = _row_value(row, license_column)
        if not current_license and source_license is not None:
            current_license = source_license.license

        if not _needs_proposal(
            current_license=current_license,
            proposed_license=proposed_license,
            table_has_license_column=table_has_license_column,
        ):
            continue

        entity_id = _row_value(row, id_column)
        key = (spec.table_name, entity_id, source_url)
        if key in seen:
            continue
        seen.add(key)
        proposals.append(
            _proposal_from_parts(
                task=spec.task,
                table_name=spec.table_name,
                entity_id=entity_id,
                id_column=id_column or "",
                source_id=source_license.source_id if source_license else "",
                source_url=source_url,
                domain=domain,
                current_license=current_license,
                proposed_license=proposed_license,
                confidence=confidence,
                reason=_proposal_reason(
                    domain=domain,
                    proposed_license=proposed_license,
                    rule_reason=rule_reason,
                    current_license=current_license,
                    table_has_license_column=table_has_license_column,
                    source_license=source_license,
                ),
            )
        )
    return proposals


def _collect_from_source_manifest(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "am_source"):
        return []
    columns = _columns(conn, "am_source")
    if not {"id", "source_url"} <= columns:
        return []
    license_column = "license" if "license" in columns else None
    domain_column = "domain" if "domain" in columns else None
    rows = conn.execute("SELECT * FROM am_source")
    proposals: list[dict[str, Any]] = []
    for row in rows:
        source_url = _row_value(row, "source_url")
        domain = _domain_for_row(source_url, _row_value(row, domain_column))
        if not source_url or not _is_target_source_manifest_row(source_url, domain):
            continue
        classified = classify_domain(domain)
        if classified is None:
            continue
        proposed_license, confidence, rule_reason = classified
        current_license = _row_value(row, license_column)
        if not _needs_proposal(
            current_license=current_license,
            proposed_license=proposed_license,
            table_has_license_column=license_column is not None,
        ):
            continue
        source_license = SourceLicense(
            source_id=_row_value(row, "id"),
            license=current_license,
            domain=domain,
        )
        proposals.append(
            _proposal_from_parts(
                task="B11/B12-source",
                table_name="am_source",
                entity_id=_row_value(row, "id"),
                id_column="id",
                source_id=_row_value(row, "id"),
                source_url=source_url,
                domain=domain,
                current_license=current_license,
                proposed_license=proposed_license,
                confidence=confidence,
                reason=_proposal_reason(
                    domain=domain,
                    proposed_license=proposed_license,
                    rule_reason=rule_reason,
                    current_license=current_license,
                    table_has_license_column=license_column is not None,
                    source_license=source_license,
                ),
            )
        )
    return proposals


def collect_license_label_proposals(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    source_index = _source_license_index(conn)
    proposals: list[dict[str, Any]] = []
    for spec in CANDIDATE_TABLES:
        proposals.extend(_collect_from_candidate_table(conn, spec, source_index))
    proposals.extend(_collect_from_source_manifest(conn))
    proposals.sort(
        key=lambda row: (
            str(row["task"]),
            str(row["table_name"]),
            str(row["domain"]),
            str(row["entity_id"]),
            str(row["source_url"]),
        )
    )
    return proposals


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_task = Counter(str(row["task"]) for row in rows)
    by_table = Counter(str(row["table_name"]) for row in rows)
    by_proposed = Counter(str(row["proposed_license"]) for row in rows)
    by_current = Counter(str(row["current_license"] or "<blank>") for row in rows)
    public_from_blocked = sum(
        1
        for row in rows
        if row["proposed_license"] in PUBLIC_LICENSES
        and _normalize_license(str(row["current_license"])) in BLOCKED_OR_UNSET_LICENSES
        and row["review_required"] is True
    )
    return {
        "proposal_rows": len(rows),
        "review_required_rows": sum(1 for row in rows if row["review_required"] is True),
        "public_from_blocked_or_unset_review_rows": public_from_blocked,
        "by_task": dict(sorted(by_task.items())),
        "by_table": dict(sorted(by_table.items())),
        "by_current_license": dict(sorted(by_current.items())),
        "by_proposed_license": dict(sorted(by_proposed.items())),
    }


def build_report(conn: sqlite3.Connection, *, db_path: Path | None = None) -> dict[str, Any]:
    rows = collect_license_label_proposals(conn)
    return {
        "ok": True,
        "complete": False,
        "generated_at": _utc_now(),
        "database": str(db_path) if db_path is not None else "",
        "read_mode": {
            "sqlite_only": True,
            "network_fetch_performed": False,
            "db_mutation_performed": False,
        },
        "completion_status": {
            "B11": "review_queue_only",
            "B12": "review_queue_only",
            "complete": False,
        },
        "summary": _summary(rows),
        "rows": rows,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            out = dict(row)
            out["review_required"] = "true" if row["review_required"] else "false"
            writer.writerow(out)


def _write_json(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_report_outputs(
    report: dict[str, Any],
    *,
    csv_output: Path,
    json_output: Path,
) -> None:
    _write_csv(csv_output, list(report["rows"]))
    report["outputs"] = {
        "csv": str(csv_output),
        "json": str(json_output),
    }
    _write_json(json_output, report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--json", action="store_true", help="Print the report summary as JSON")
    args = parser.parse_args(argv)

    with _connect_readonly(args.db) as conn:
        report = build_report(conn, db_path=args.db)
    write_report_outputs(report, csv_output=args.csv_output, json_output=args.json_output)

    if args.json:
        print(
            json.dumps(
                {
                    "ok": report["ok"],
                    "complete": report["complete"],
                    "outputs": report["outputs"],
                    "summary": report["summary"],
                    "completion_status": report["completion_status"],
                    "read_mode": report["read_mode"],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        summary = report["summary"]
        print(f"proposal_rows={summary['proposal_rows']}")
        print(f"review_required_rows={summary['review_required_rows']}")
        print(f"by_task={summary['by_task']}")
        print(f"by_proposed_license={summary['by_proposed_license']}")
        print(f"csv_output={report['outputs']['csv']}")
        print(f"json_output={report['outputs']['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
