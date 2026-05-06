#!/usr/bin/env python3
"""Unified HuggingFace publish workflow for the 4 jpcite datasets.

Datasets handled:

  - laws-jp              (jpintel.db: laws)
  - invoice-registrants  (jpintel.db: invoice_registrants, PII redaction for kojin)
  - statistics-estat     (autonomath.db: am_entities WHERE record_kind='statistic'
                          + e-Stat domain filter)
  - corp-enforcement     (jpintel.db: enforcement_cases UNION
                          autonomath.db: am_enforcement_detail)

Pipeline per dataset:

  1. SELECT rows from the source DB (read-only) using a dataset-specific query.
  2. Drop rows with `license` in {'unknown', 'proprietary'} (E1 launch gate).
  3. Drop rows whose `source_id` / `source_url` is on the E1 license_review_queue
     blacklist (`analysis_wave18/license_review_queue.csv`).
  4. For invoice-registrants: redact `kojin` (sole_proprietor) full address down
     to prefecture (E2 aggregation gate — sole-proprietor addresses are PII).
  5. Run the `hf_export_safety_gate` checks (invoice/enforcement go through the
     k=5 aggregate gate where appropriate; row-level kept only when license is
     proven public-domain or PDL/CC-BY/gov_standard).
  6. Write `dist/hf-datasets/<dataset>/data.parquet`, copy
     `research/hf_datasets/<dataset>/README.md`, and emit
     `dataset_infos.json` (HF v2 metadata).
  7. With `--dry-run` (default) stop here. With `--push` AND `HF_TOKEN` env,
     call `huggingface_hub.upload_folder()`.

LLM API calls are forbidden by repo policy and not used here (pure SQLite + pandas
+ huggingface_hub on push only).
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from shutil import copyfile
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
ETL_DIR = REPO_ROOT / "scripts" / "etl"
if str(ETL_DIR) not in sys.path:
    sys.path.insert(0, str(ETL_DIR))

from hf_export_safety_gate import (  # noqa: E402
    BLOCKED_LICENSES,
    HfExport,
    HfExportSafetyError,
    assert_hf_export_safe,
)

DEFAULT_JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "dist" / "hf-datasets"
README_ROOT = REPO_ROOT / "research" / "hf_datasets"
LICENSE_BLACKLIST_CSV = REPO_ROOT / "analysis_wave18" / "license_review_queue.csv"

HF_NAMESPACE = "bookyou"
SCHEMA_VERSION = "publish_hf_datasets.v1"


# ----------------------------------------------------------------------------
# Dataset specs
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class DatasetSpec:
    name: str  # short slug; matches HF repo path under bookyou/
    title: str  # human-readable title
    primary_db: str  # 'jpintel' or 'autonomath'
    license: str
    citation: str
    description: str


DATASETS: dict[str, DatasetSpec] = {
    "laws-jp": DatasetSpec(
        name="laws-jp",
        title="Japanese Laws (e-Gov mirror)",
        primary_db="jpintel",
        license="cc-by-4.0",
        citation=(
            "Bookyou Co., Ltd. (2026). Japanese Laws (e-Gov mirror). "
            "https://huggingface.co/datasets/bookyou/laws-jp"
        ),
        description=(
            "Mirror of Japanese national statutes from e-Gov 法令検索. "
            "Maintained by Bookyou株式会社 (T8010001213708)."
        ),
    ),
    "invoice-registrants": DatasetSpec(
        name="invoice-registrants",
        title="Japan Invoice Registrants (NTA mirror)",
        primary_db="jpintel",
        license="cc-by-4.0",
        citation=(
            "Bookyou Co., Ltd. (2026). Japan Invoice Registrants (NTA mirror). "
            "https://huggingface.co/datasets/bookyou/invoice-registrants. "
            "Source: 国税庁 適格請求書発行事業者公表サイト (PDL v1.0)."
        ),
        description=(
            "Mirror of the National Tax Agency 適格請求書発行事業者 registry. "
            "Sole-proprietor (kojin) addresses are reduced to prefecture (PII)."
        ),
    ),
    "statistics-estat": DatasetSpec(
        name="statistics-estat",
        title="e-Stat Japan Government Statistics (mirror)",
        primary_db="autonomath",
        license="cc-by-4.0",
        citation=(
            "Bookyou Co., Ltd. (2026). e-Stat Japan Government Statistics (mirror). "
            "https://huggingface.co/datasets/bookyou/statistics-estat. "
            "Source: 政府統計の総合窓口 e-Stat (政府標準利用規約 v2.0)."
        ),
        description=(
            "Catalog mirror of e-Stat 統計表 entries. Metadata + provenance only; "
            "full per-observation series via the live API."
        ),
    ),
    "corp-enforcement": DatasetSpec(
        name="corp-enforcement",
        title="Japan Corporate Administrative Actions",
        primary_db="jpintel",  # primary; also reads autonomath
        license="cc-by-4.0",
        citation=(
            "Bookyou Co., Ltd. (2026). Japan Corporate Administrative Actions. "
            "https://huggingface.co/datasets/bookyou/corp-enforcement"
        ),
        description=(
            "Union of jpintel enforcement_cases + autonomath am_enforcement_detail. "
            "Primary-source-cited; aggregator records excluded."
        ),
    ),
}


# ----------------------------------------------------------------------------
# License blacklist (E1)
# ----------------------------------------------------------------------------


def load_blacklist(csv_path: Path) -> tuple[set[str], set[str]]:
    """Return (source_id_set, source_url_set) from license_review_queue.csv."""
    if not csv_path.exists():
        return set(), set()
    source_ids: set[str] = set()
    source_urls: set[str] = set()
    with csv_path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            sid = (row.get("source_id") or "").strip()
            surl = (row.get("source_url") or "").strip()
            if sid:
                source_ids.add(sid)
            if surl:
                source_urls.add(surl)
    return source_ids, source_urls


# ----------------------------------------------------------------------------
# Read-only DB helpers
# ----------------------------------------------------------------------------


def open_readonly(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ----------------------------------------------------------------------------
# Per-dataset query + post-processing
# ----------------------------------------------------------------------------


LAWS_QUERY = """
SELECT
    unified_id           AS law_id,
    law_title            AS law_name,
    law_number           AS law_num,
    law_type             AS law_type,
    summary              AS body_text_summary,
    full_text_url        AS body_text_url,
    enforced_date        AS effective_date,
    last_amended_date    AS last_amended_date,
    CASE
        WHEN revision_status = 'repealed' THEN 1
        ELSE 0
    END                  AS repealed,
    source_url           AS source_url,
    fetched_at           AS fetched_at,
    'cc_by_4.0'          AS license
FROM laws
WHERE source_url IS NOT NULL
  AND TRIM(source_url) <> ''
ORDER BY unified_id
"""


INVOICE_QUERY = """
SELECT
    invoice_registration_number AS registration_number,
    normalized_name             AS name,
    address_normalized          AS address,
    prefecture                  AS prefecture,
    CASE
        WHEN registrant_kind = 'corporation'    THEN 'houjin'
        WHEN registrant_kind = 'sole_proprietor' THEN 'kojin'
        ELSE 'other'
    END                         AS type,
    houjin_bangou               AS corporate_number,
    registered_date             AS registered_date,
    revoked_date                AS deregistered_date_or_null,
    CASE
        WHEN revoked_date IS NULL AND expired_date IS NULL THEN 1
        ELSE 0
    END                         AS is_active,
    source_url                  AS source_url,
    fetched_at                  AS fetched_at,
    'pdl_v1.0'                  AS license
FROM invoice_registrants
WHERE revoked_date IS NULL
  AND expired_date IS NULL
  AND source_url IS NOT NULL
  AND TRIM(source_url) <> ''
ORDER BY invoice_registration_number
"""


# e-Stat catalog rows: am_entities filtered to record_kind='statistic' and
# e-Stat domain. raw_json holds dataset-specific fields; we only emit the
# stable columns + a JSON sidecar for callers who want detail.
ESTAT_QUERY = """
SELECT
    e.canonical_id      AS entity_id,
    e.primary_name      AS title_jp,
    e.source_url        AS source_url,
    e.source_url_domain AS source_domain,
    e.source_topic      AS source_topic,
    e.fetched_at        AS fetched_at,
    e.confidence        AS confidence,
    e.raw_json          AS raw_json,
    COALESCE(s.license, 'gov_standard_v2.0') AS license,
    s.source_type       AS source_type,
    s.first_seen        AS source_first_seen,
    s.last_verified     AS source_last_verified
FROM am_entities e
LEFT JOIN am_source s ON s.source_url = e.source_url
WHERE e.record_kind = 'statistic'
  AND (e.source_url_domain LIKE '%e-stat%' OR e.source_url_domain LIKE '%estat%')
  AND e.source_url IS NOT NULL
  AND TRIM(e.source_url) <> ''
ORDER BY e.canonical_id
"""


# corp-enforcement piece A: enforcement_cases from jpintel.db
ENFORCEMENT_JPINTEL_QUERY = """
SELECT
    case_id                       AS case_id,
    recipient_houjin_bangou       AS corporate_number_or_null,
    recipient_name                AS company_name,
    LOWER(COALESCE(ministry, ''))                    AS authority_id,
    ministry                      AS authority_name,
    'national'                    AS authority_level,
    COALESCE(event_type, 'other') AS action_type,
    disclosed_date                AS action_date,
    NULL                          AS effective_from,
    disclosed_until               AS effective_until,
    legal_basis                   AS legal_basis,
    reason_excerpt                AS reason_summary,
    amount_yen                    AS amount_yen,
    prefecture                    AS prefecture,
    NULL                          AS industry_jsic_major,
    source_url                    AS source_url,
    'web_page'                    AS source_doc_kind,
    disclosed_until               AS disclosed_until,
    fetched_at                    AS fetched_at,
    confidence                    AS confidence,
    'gov_standard_v2.0'           AS license,
    'jpintel.enforcement_cases'   AS source_table
FROM enforcement_cases
WHERE source_url IS NOT NULL
  AND TRIM(source_url) <> ''
"""


# corp-enforcement piece B: am_enforcement_detail from autonomath.db
ENFORCEMENT_AUTONOMATH_QUERY = """
SELECT
    'AM-' || d.enforcement_id     AS case_id,
    d.houjin_bangou               AS corporate_number_or_null,
    d.target_name                 AS company_name,
    LOWER(COALESCE(d.issuing_authority, '')) AS authority_id,
    d.issuing_authority           AS authority_name,
    'national'                    AS authority_level,
    COALESCE(d.enforcement_kind, 'other') AS action_type,
    d.issuance_date               AS action_date,
    d.exclusion_start             AS effective_from,
    d.exclusion_end               AS effective_until,
    d.related_law_ref             AS legal_basis,
    d.reason_summary              AS reason_summary,
    d.amount_yen                  AS amount_yen,
    NULL                          AS prefecture,
    NULL                          AS industry_jsic_major,
    d.source_url                  AS source_url,
    'web_page'                    AS source_doc_kind,
    NULL                          AS disclosed_until,
    d.source_fetched_at           AS fetched_at,
    NULL                          AS confidence,
    COALESCE(s.license, 'gov_standard_v2.0') AS license,
    'autonomath.am_enforcement_detail' AS source_table
FROM am_enforcement_detail d
LEFT JOIN am_source s ON s.source_url = d.source_url
WHERE d.source_url IS NOT NULL
  AND TRIM(d.source_url) <> ''
"""


def _filter_by_license(df: pd.DataFrame) -> pd.DataFrame:
    if "license" not in df.columns:
        return df
    mask = df["license"].astype(str).str.lower().isin(BLOCKED_LICENSES)
    return df.loc[~mask].copy()


def _filter_by_url_blacklist(df: pd.DataFrame, blacklist_urls: set[str]) -> pd.DataFrame:
    if not blacklist_urls or "source_url" not in df.columns:
        return df
    mask = df["source_url"].astype(str).isin(blacklist_urls)
    return df.loc[~mask].copy()


def _redact_kojin_address(df: pd.DataFrame) -> pd.DataFrame:
    """E2 aggregation gate: sole-proprietor (kojin) full address is PII.

    Reduce to prefecture only; null-out detailed address. Houjin rows stay full.
    """
    if "type" not in df.columns:
        return df
    df = df.copy()
    is_kojin = df["type"].astype(str) == "kojin"
    if "address" in df.columns:
        df.loc[is_kojin, "address"] = df.loc[is_kojin, "prefecture"].fillna("")
    return df


def _coerce_numeric(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _coerce_int_nullable(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    return df


# ----------------------------------------------------------------------------
# Reader functions
# ----------------------------------------------------------------------------


def read_laws(
    jpintel_db: Path,
    blacklist_urls: set[str],
    limit: int | None,
) -> tuple[pd.DataFrame, list[HfExport]]:
    query = LAWS_QUERY
    if limit:
        query = query + f"\nLIMIT {int(limit)}"
    conn = open_readonly(jpintel_db)
    try:
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()
    df = _filter_by_url_blacklist(df, blacklist_urls)
    df = _filter_by_license(df)
    df = _coerce_int_nullable(df, ["repealed"])
    return df, [HfExport(table="laws", query=query)]


def read_invoice(
    jpintel_db: Path,
    blacklist_urls: set[str],
    limit: int | None,
) -> tuple[pd.DataFrame, list[HfExport]]:
    query = INVOICE_QUERY
    if limit:
        query = query + f"\nLIMIT {int(limit)}"
    conn = open_readonly(jpintel_db)
    try:
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()
    df = _filter_by_url_blacklist(df, blacklist_urls)
    df = _filter_by_license(df)
    df = _redact_kojin_address(df)
    df = _coerce_int_nullable(df, ["is_active"])
    return df, [HfExport(table="invoice_registrants_safe", query=query)]


def read_estat(
    autonomath_db: Path,
    blacklist_urls: set[str],
    limit: int | None,
) -> tuple[pd.DataFrame, list[HfExport]]:
    query = ESTAT_QUERY
    if limit:
        query = query + f"\nLIMIT {int(limit)}"
    conn = open_readonly(autonomath_db)
    try:
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()
    df = _filter_by_url_blacklist(df, blacklist_urls)
    df = _filter_by_license(df)
    df = _coerce_numeric(df, ["confidence"])
    return df, [HfExport(table="estat_catalog", query=query)]


def read_enforcement(
    jpintel_db: Path,
    autonomath_db: Path,
    blacklist_urls: set[str],
    limit: int | None,
) -> tuple[pd.DataFrame, list[HfExport]]:
    queries: list[HfExport] = []

    half_limit_clause = ""
    if limit:
        half = max(1, int(limit) // 2)
        half_limit_clause = f"\nLIMIT {half}"

    qa = ENFORCEMENT_JPINTEL_QUERY + half_limit_clause
    qb = ENFORCEMENT_AUTONOMATH_QUERY + half_limit_clause

    conn_a = open_readonly(jpintel_db)
    try:
        df_a = pd.read_sql_query(qa, conn_a)
    finally:
        conn_a.close()

    conn_b = open_readonly(autonomath_db)
    try:
        df_b = pd.read_sql_query(qb, conn_b)
    finally:
        conn_b.close()

    queries.append(HfExport(table="enforcement_cases_safe", query=qa))
    queries.append(HfExport(table="am_enforcement_detail_safe", query=qb))

    df = pd.concat([df_a, df_b], ignore_index=True)
    df = _filter_by_url_blacklist(df, blacklist_urls)
    df = _filter_by_license(df)
    df = _coerce_numeric(df, ["confidence"])
    df = _coerce_int_nullable(df, ["amount_yen"])
    return df, queries


READERS = {
    "laws-jp": read_laws,
    "invoice-registrants": read_invoice,
    "statistics-estat": read_estat,
    "corp-enforcement": read_enforcement,
}


# ----------------------------------------------------------------------------
# Output writers
# ----------------------------------------------------------------------------


def _hf_features_from_frame(df: pd.DataFrame) -> dict[str, dict[str, str]]:
    """Approximate HF Features dict (datasets v2 metadata).

    Maps pandas dtypes to HF "Value" types. Good enough for `dataset_infos.json`
    consumers; HF will recompute on actual upload regardless.
    """
    out: dict[str, dict[str, str]] = {}
    for col in df.columns:
        dtype = df[col].dtype
        if pd.api.types.is_integer_dtype(dtype):
            hf_type = "int64"
        elif pd.api.types.is_float_dtype(dtype):
            hf_type = "float64"
        elif pd.api.types.is_bool_dtype(dtype):
            hf_type = "bool"
        else:
            hf_type = "string"
        out[col] = {"dtype": hf_type, "_type": "Value"}
    return out


def _avg_row_size_estimate(df: pd.DataFrame, parquet_bytes: int) -> int:
    if df.empty:
        return 0
    return int(parquet_bytes / max(1, len(df)))


def _fmt_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def write_outputs(
    spec: DatasetSpec,
    df: pd.DataFrame,
    out_dir: Path,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    """Write parquet + README + dataset_infos.json. Returns manifest dict."""
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = out_dir / "data.parquet"

    df.to_parquet(parquet_path, engine="pyarrow", compression="snappy", index=False)
    parquet_bytes = parquet_path.stat().st_size

    # README copy
    readme_src = README_ROOT / spec.name / "README.md"
    if readme_src.exists():
        copyfile(readme_src, out_dir / "README.md")
        readme_copied = True
    else:
        readme_copied = False

    # dataset_infos.json (HF v2)
    repo_id = f"{HF_NAMESPACE}/{spec.name}"
    features = _hf_features_from_frame(df)
    dataset_infos = {
        repo_id: {
            "description": spec.description,
            "citation": spec.citation,
            "homepage": "https://jpcite.com",
            "license": spec.license,
            "features": features,
            "splits": {
                "train": {
                    "name": "train",
                    "num_bytes": parquet_bytes,
                    "num_examples": int(len(df)),
                    "dataset_name": spec.name,
                }
            },
            "download_size": parquet_bytes,
            "dataset_size": parquet_bytes,
            "size_in_bytes": parquet_bytes * 2,
            "version": {"version_str": "1.0.0", "major": 1, "minor": 0, "patch": 0},
        }
    }
    (out_dir / "dataset_infos.json").write_text(
        json.dumps(dataset_infos, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "dataset": spec.name,
        "hf_repo_id": repo_id,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "dry_run": bool(dry_run),
        "rows": int(len(df)),
        "parquet_bytes": parquet_bytes,
        "avg_row_bytes": _avg_row_size_estimate(df, parquet_bytes),
        "license": spec.license,
        "readme_copied": readme_copied,
        "out_dir": str(out_dir),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


# ----------------------------------------------------------------------------
# Push
# ----------------------------------------------------------------------------


def push_to_hf(out_dir: Path, repo_id: str, *, token: str) -> str:
    """Call huggingface_hub.upload_folder() and return the commit URL."""
    from huggingface_hub import HfApi  # imported lazily; only needed for push.

    api = HfApi(token=token)
    api.create_repo(
        repo_id=repo_id,
        repo_type="dataset",
        exist_ok=True,
        private=False,
    )
    info = api.upload_folder(
        folder_path=str(out_dir),
        repo_id=repo_id,
        repo_type="dataset",
        commit_message=f"Publish {repo_id} via scripts/publish_hf_datasets.py",
    )
    return str(info)


# ----------------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------------


def _print_sample_row(df: pd.DataFrame) -> None:
    if df.empty:
        print("  sample row: <empty frame>")
        return
    sample = df.iloc[0].to_dict()
    safe: dict[str, Any] = {}
    for k, v in sample.items():
        if isinstance(v, str) and len(v) > 220:
            safe[k] = v[:200] + "...(truncated)"
        else:
            safe[k] = None if pd.isna(v) and not isinstance(v, (list, dict)) else v
    print("  sample row (1):")
    for k, v in safe.items():
        print(f"    {k}: {v!r}")


def run_one(
    name: str,
    *,
    jpintel_db: Path,
    autonomath_db: Path,
    output_root: Path,
    blacklist_urls: set[str],
    limit: int | None,
    dry_run: bool,
    push: bool,
    skip_safety_gate: bool,
) -> dict[str, Any]:
    if name not in DATASETS:
        raise SystemExit(f"unknown dataset: {name}; choose from {sorted(DATASETS)}")
    spec = DATASETS[name]
    out_dir = output_root / spec.name

    print(f"\n=== {spec.name} ({spec.title}) ===")
    print(f"  source DB:  primary={spec.primary_db}")
    print(f"  output dir: {out_dir}")
    print(f"  mode:       {'PUSH' if push else 'DRY-RUN'}; limit={limit or 'all'}")

    if name == "laws-jp":
        df, exports = read_laws(jpintel_db, blacklist_urls, limit)
    elif name == "invoice-registrants":
        df, exports = read_invoice(jpintel_db, blacklist_urls, limit)
    elif name == "statistics-estat":
        df, exports = read_estat(autonomath_db, blacklist_urls, limit)
    elif name == "corp-enforcement":
        df, exports = read_enforcement(jpintel_db, autonomath_db, blacklist_urls, limit)
    else:  # pragma: no cover
        raise SystemExit(f"no reader for {name}")

    print(f"  rows after license + blacklist filter: {len(df):,}")

    # Optional safety gate. Each query is checked against its own DB:
    #   - jpintel-source queries (laws, invoice, jpintel enforcement)
    #     run against jpintel.db.
    #   - autonomath-source queries (e-Stat, am_enforcement_detail)
    #     run against autonomath.db.
    # The gate is conservative: it flags ANY row-level identifier on
    # enforcement/invoice tables. Our dataset cards declare row-level
    # disclosure under the source license (PDL v1.0 for NTA, gov_standard
    # for 行政処分), so we WARN on dry-run and only RAISE on --push.
    if not skip_safety_gate and exports:
        gate_failures: list[str] = []
        for ex in exports:
            # Rebuild without trailing LIMIT so k-anon counts on full set.
            q_full = ex.query.split("\nLIMIT ")[0]
            target = jpintel_db
            if "am_enforcement_detail" in ex.table or "estat_catalog" in ex.table:
                target = autonomath_db
            try:
                conn = open_readonly(target)
                try:
                    assert_hf_export_safe(conn, [HfExport(table=ex.table, query=q_full)])
                finally:
                    conn.close()
            except (HfExportSafetyError, sqlite3.Error) as exc:
                gate_failures.append(f"{ex.table}: {type(exc).__name__}: {exc}")
        if gate_failures:
            if push:
                raise HfExportSafetyError([])  # let upstream details show
            for failure in gate_failures:
                print(f"  safety_gate: WARN — {failure}")
        else:
            print("  safety_gate: passed")

    manifest = write_outputs(spec, df, out_dir, dry_run=not push)

    print(f"  rows written:  {manifest['rows']:,}")
    print(
        f"  parquet bytes: {manifest['parquet_bytes']:,} ({_fmt_bytes(manifest['parquet_bytes'])})"
    )
    print(f"  avg row bytes: {manifest['avg_row_bytes']:,}")
    _print_sample_row(df)

    if push:
        import os

        token = os.environ.get("HF_TOKEN", "").strip()
        if not token:
            raise SystemExit("--push requires HF_TOKEN env var")
        repo_id = manifest["hf_repo_id"]
        print(f"  pushing to {repo_id} ...")
        commit = push_to_hf(out_dir, repo_id, token=token)
        manifest["push"] = {"repo_id": repo_id, "commit_info": commit}
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"  push complete: {commit}")
    else:
        print("  (dry-run) parquet/README/dataset_infos.json staged; no push.")

    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        action="append",
        choices=sorted(DATASETS) + ["all"],
        help="dataset slug; repeatable, or 'all'",
    )
    parser.add_argument("--jpintel-db", type=Path, default=DEFAULT_JPINTEL_DB)
    parser.add_argument("--autonomath-db", type=Path, default=DEFAULT_AUTONOMATH_DB)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--blacklist-csv",
        type=Path,
        default=LICENSE_BLACKLIST_CSV,
        help="E1 license_review_queue.csv path",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="row cap for smoke export; --dry-run friendly",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="do not push to HF (default)",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="push to HF Hub (requires HF_TOKEN); turns OFF dry-run",
    )
    parser.add_argument(
        "--skip-safety-gate",
        action="store_true",
        help="skip the hf_export_safety_gate checks (use only for diagnostics)",
    )
    args = parser.parse_args(argv)

    targets = args.dataset or ["all"]
    if "all" in targets:
        targets = list(DATASETS)

    push = bool(args.push)
    if push:
        # explicit push overrides dry-run
        args.dry_run = False

    blacklist_ids, blacklist_urls = load_blacklist(args.blacklist_csv)
    print(
        f"Loaded license_review_queue.csv blacklist: "
        f"{len(blacklist_ids)} source_ids, {len(blacklist_urls)} source_urls "
        f"({args.blacklist_csv})"
    )

    manifests: list[dict[str, Any]] = []
    for name in targets:
        manifests.append(
            run_one(
                name,
                jpintel_db=args.jpintel_db,
                autonomath_db=args.autonomath_db,
                output_root=args.output_root,
                blacklist_urls=blacklist_urls,
                limit=args.limit,
                dry_run=args.dry_run,
                push=push,
                skip_safety_gate=args.skip_safety_gate,
            )
        )

    print("\n=== SUMMARY ===")
    for m in manifests:
        print(
            f"  {m['dataset']:22s} {m['rows']:>9,} rows  "
            f"{_fmt_bytes(m['parquet_bytes']):>10s}  "
            f"avg {m['avg_row_bytes']:>6,} B/row  "
            f"{'PUSHED' if m.get('push') else 'staged'}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
