#!/usr/bin/env python3
"""Wave 41 — Schema.org ``Dataset`` JSON-LD emitter (Context pillar +1 cell).

Emits Schema.org ``Dataset`` JSON-LD blocks for the four primary jpcite
corpora — programs / laws / cases / enforcement — at the relevant
``site/`` roots so agent crawlers + Google Dataset Search + agent
context loaders can discover the corpus shape without parsing 14,472
HTML pages.

WAI-ARIA describedby
--------------------
Each Dataset payload includes an ``identifier`` and ``additionalProperty``
list keyed by ``ariaDescribedBy`` referencing the corresponding site-root
HTML id.

Output files (idempotent):
  - ``site/_data/dataset_jsonld_programs.json``
  - ``site/_data/dataset_jsonld_laws.json``
  - ``site/_data/dataset_jsonld_cases.json``
  - ``site/_data/dataset_jsonld_enforcement.json``
  - ``site/_data/dataset_jsonld_aggregate.json`` (root, with hasPart)
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys
from datetime import datetime, timezone

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = REPO_ROOT / "site"
DATA_OUT = SITE / "_data"
JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"

FALLBACK_COUNTS = {
    "programs_searchable": 11601,
    "programs_total": 14472,
    "cases": 2286,
    "loans": 108,
    "enforcement": 1185,
    "laws_fulltext": 6493,
    "laws_catalog": 9484,
    "tax_rulesets": 50,
    "court_decisions": 2065,
    "bids": 362,
    "invoice_registrants": 13801,
}


def _safe_count(db: sqlite3.Connection, sql: str) -> int | None:
    try:
        cur = db.execute(sql)
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else None
    except (sqlite3.Error, ValueError):
        return None


def _read_counts() -> dict[str, int]:
    counts = dict(FALLBACK_COUNTS)
    if not JPINTEL_DB.exists():
        return counts
    try:
        db = sqlite3.connect(f"file:{JPINTEL_DB}?mode=ro", uri=True, timeout=2.0)
    except sqlite3.Error:
        return counts
    try:
        c = _safe_count(db, "SELECT COUNT(*) FROM programs WHERE COALESCE(excluded,0)=0 AND tier IN ('S','A','B','C')")
        if c is not None and c > 0:
            counts["programs_searchable"] = c
        c = _safe_count(db, "SELECT COUNT(*) FROM programs")
        if c is not None and c > 0:
            counts["programs_total"] = c
        c = _safe_count(db, "SELECT COUNT(*) FROM case_studies")
        if c is not None and c > 0:
            counts["cases"] = c
        c = _safe_count(db, "SELECT COUNT(*) FROM enforcement_cases")
        if c is not None and c > 0:
            counts["enforcement"] = c
        c = _safe_count(db, "SELECT COUNT(*) FROM laws")
        if c is not None and c > 0:
            counts["laws_catalog"] = c
    finally:
        db.close()
    return counts


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _publisher_node() -> dict:
    return {
        "@type": "Organization",
        "@id": "https://jpcite.com/#publisher",
        "name": "Bookyou株式会社",
        "url": "https://jpcite.com/",
        "identifier": "T8010001213708",
    }


def _license_url() -> str:
    return "https://jpcite.com/data-licensing"


def build_programs_dataset(counts: dict[str, int]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "@id": "https://jpcite.com/#dataset-programs",
        "name": "jpcite — 日本の補助金・融資・税制・認定 制度データセット",
        "description": (
            f"日本の公的制度 {counts['programs_searchable']:,} 件 / "
            f"カタログ {counts['programs_total']:,} 件。"
            "一次資料 URL + fetched_at 付き。"
        ),
        "url": "https://jpcite.com/programs/",
        "identifier": "jpcite-programs",
        "keywords": ["補助金", "融資", "税制", "認定", "subsidy", "Japan"],
        "isAccessibleForFree": True,
        "license": _license_url(),
        "publisher": _publisher_node(),
        "creator": {"@id": "https://jpcite.com/#publisher"},
        "spatialCoverage": {"@type": "Country", "name": "日本"},
        "inLanguage": ["ja", "en"],
        "datePublished": "2025-12-01",
        "dateModified": _now_iso(),
        "variableMeasured": [
            {"@type": "PropertyValue", "name": "searchable_programs", "value": counts["programs_searchable"]},
            {"@type": "PropertyValue", "name": "total_programs", "value": counts["programs_total"]},
        ],
        "distribution": [
            {"@type": "DataDownload", "encodingFormat": "application/json",
             "contentUrl": "https://api.jpcite.com/v1/programs", "description": "REST API"},
        ],
        "additionalProperty": [
            {"@type": "PropertyValue", "name": "ariaDescribedBy", "value": "programs-main"},
            {"@type": "PropertyValue", "name": "agentReadable", "value": True},
        ],
    }


def build_laws_dataset(counts: dict[str, int]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "@id": "https://jpcite.com/#dataset-laws",
        "name": "jpcite — e-Gov 法令全文 + カタログ データセット",
        "description": (
            f"e-Gov 由来の法令全文 {counts['laws_fulltext']:,} 本 + "
            f"カタログ {counts['laws_catalog']:,} 本。"
        ),
        "url": "https://jpcite.com/laws/",
        "identifier": "jpcite-laws",
        "keywords": ["法令", "e-Gov", "law", "Japan"],
        "isAccessibleForFree": True,
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "publisher": _publisher_node(),
        "creator": {"@id": "https://jpcite.com/#publisher"},
        "spatialCoverage": {"@type": "Country", "name": "日本"},
        "inLanguage": ["ja", "en"],
        "datePublished": "2025-12-01",
        "dateModified": _now_iso(),
        "variableMeasured": [
            {"@type": "PropertyValue", "name": "laws_fulltext", "value": counts["laws_fulltext"]},
            {"@type": "PropertyValue", "name": "laws_catalog", "value": counts["laws_catalog"]},
        ],
        "distribution": [
            {"@type": "DataDownload", "encodingFormat": "application/json",
             "contentUrl": "https://api.jpcite.com/v1/laws", "description": "REST API"},
        ],
        "additionalProperty": [
            {"@type": "PropertyValue", "name": "ariaDescribedBy", "value": "laws-main"},
            {"@type": "PropertyValue", "name": "agentReadable", "value": True},
        ],
    }


def build_cases_dataset(counts: dict[str, int]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "@id": "https://jpcite.com/#dataset-cases",
        "name": "jpcite — 採択事例・判例 データセット",
        "description": (
            f"補助金採択事例 {counts['cases']:,} 件 + 判例 {counts['court_decisions']:,} 件。"
        ),
        "url": "https://jpcite.com/cases/",
        "identifier": "jpcite-cases",
        "keywords": ["採択事例", "判例", "case-study", "Japan"],
        "isAccessibleForFree": True,
        "license": _license_url(),
        "publisher": _publisher_node(),
        "creator": {"@id": "https://jpcite.com/#publisher"},
        "spatialCoverage": {"@type": "Country", "name": "日本"},
        "inLanguage": ["ja"],
        "datePublished": "2025-12-01",
        "dateModified": _now_iso(),
        "variableMeasured": [
            {"@type": "PropertyValue", "name": "case_studies", "value": counts["cases"]},
            {"@type": "PropertyValue", "name": "court_decisions", "value": counts["court_decisions"]},
        ],
        "distribution": [
            {"@type": "DataDownload", "encodingFormat": "application/json",
             "contentUrl": "https://api.jpcite.com/v1/cases", "description": "REST API"},
        ],
        "additionalProperty": [
            {"@type": "PropertyValue", "name": "ariaDescribedBy", "value": "cases-main"},
            {"@type": "PropertyValue", "name": "agentReadable", "value": True},
        ],
    }


def build_enforcement_dataset(counts: dict[str, int]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "@id": "https://jpcite.com/#dataset-enforcement",
        "name": "jpcite — 行政処分・取消事例 データセット",
        "description": (
            f"補助金交付決定取消 / 業務停止 / 業務改善命令 等 {counts['enforcement']:,} 件。"
        ),
        "url": "https://jpcite.com/enforcement/",
        "identifier": "jpcite-enforcement",
        "keywords": ["行政処分", "enforcement", "Japan"],
        "isAccessibleForFree": True,
        "license": _license_url(),
        "publisher": _publisher_node(),
        "creator": {"@id": "https://jpcite.com/#publisher"},
        "spatialCoverage": {"@type": "Country", "name": "日本"},
        "inLanguage": ["ja"],
        "datePublished": "2025-12-01",
        "dateModified": _now_iso(),
        "variableMeasured": [
            {"@type": "PropertyValue", "name": "enforcement_cases", "value": counts["enforcement"]},
        ],
        "distribution": [
            {"@type": "DataDownload", "encodingFormat": "application/json",
             "contentUrl": "https://api.jpcite.com/v1/enforcement", "description": "REST API"},
        ],
        "additionalProperty": [
            {"@type": "PropertyValue", "name": "ariaDescribedBy", "value": "enforcement-main"},
            {"@type": "PropertyValue", "name": "agentReadable", "value": True},
        ],
    }


def build_aggregate_dataset(counts: dict[str, int]) -> dict:
    """Root-level aggregate Dataset with hasPart referencing sub-datasets."""
    sub_ids = [
        "https://jpcite.com/#dataset-programs",
        "https://jpcite.com/#dataset-laws",
        "https://jpcite.com/#dataset-cases",
        "https://jpcite.com/#dataset-enforcement",
    ]
    return {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "@id": "https://jpcite.com/#dataset-aggregate",
        "name": "jpcite — 日本の制度データセット (aggregate)",
        "description": (
            "補助金・融資・税制・認定・採択事例・判例・行政処分を統合した "
            "AI agent 向け一次資料データセット。"
        ),
        "url": "https://jpcite.com/",
        "identifier": "jpcite-aggregate",
        "keywords": ["Japan", "AI-agent-context", "primary-source-citation"],
        "isAccessibleForFree": True,
        "license": _license_url(),
        "publisher": _publisher_node(),
        "creator": {"@id": "https://jpcite.com/#publisher"},
        "spatialCoverage": {"@type": "Country", "name": "日本"},
        "inLanguage": ["ja", "en"],
        "datePublished": "2025-12-01",
        "dateModified": _now_iso(),
        "hasPart": [{"@id": sid} for sid in sub_ids],
        "variableMeasured": [
            {"@type": "PropertyValue", "name": "searchable_programs", "value": counts["programs_searchable"]},
            {"@type": "PropertyValue", "name": "laws_fulltext", "value": counts["laws_fulltext"]},
            {"@type": "PropertyValue", "name": "case_studies", "value": counts["cases"]},
            {"@type": "PropertyValue", "name": "enforcement_cases", "value": counts["enforcement"]},
        ],
        "additionalProperty": [
            {"@type": "PropertyValue", "name": "ariaDescribedBy", "value": "main-content"},
            {"@type": "PropertyValue", "name": "agentReadable", "value": True},
            {"@type": "PropertyValue", "name": "subDatasetCount", "value": len(sub_ids)},
        ],
    }


OUT_TARGETS: dict[str, str] = {
    "dataset_jsonld_programs.json": "programs",
    "dataset_jsonld_laws.json": "laws",
    "dataset_jsonld_cases.json": "cases",
    "dataset_jsonld_enforcement.json": "enforcement",
    "dataset_jsonld_aggregate.json": "aggregate",
}


def write_all(out_dir: pathlib.Path) -> dict[str, pathlib.Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = _read_counts()
    builders = {
        "programs": lambda: build_programs_dataset(counts),
        "laws": lambda: build_laws_dataset(counts),
        "cases": lambda: build_cases_dataset(counts),
        "enforcement": lambda: build_enforcement_dataset(counts),
        "aggregate": lambda: build_aggregate_dataset(counts),
    }
    written: dict[str, pathlib.Path] = {}
    for filename, key in OUT_TARGETS.items():
        path = out_dir / filename
        payload = builders[key]()
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written[key] = path
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default=str(DATA_OUT))
    args = ap.parse_args(argv)
    out_dir = pathlib.Path(args.out_dir)
    written = write_all(out_dir)
    for key, path in written.items():
        print(f"[ok] {key}: {path.relative_to(REPO_ROOT)} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
