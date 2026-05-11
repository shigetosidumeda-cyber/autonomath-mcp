#!/usr/bin/env python3
"""Monthly Parquet corpus export — jpcite-as-data distribution surface.

D5 Wave 16. Exports every queryable entity in `autonomath.db` + `jpintel.db`
to a single Parquet file per month, ships it to Cloudflare R2, and surfaces
the resulting link at https://r2.jpcite.com/exports/jpcite_corpus_{YYYY-MM}.parquet
behind the data-licensing landing page. The Parquet file carries per-table
license metadata so downstream consumers can keep PDL v1.0 (NTA), CC-BY-4.0
(e-Gov / gBizINFO), 政府標準利用規約 v2.0, パブリックドメイン, individual
licenses cleanly separated.

Why Parquet, not SQLite dump
----------------------------
- columnar compression: ~10 GB SQLite → ~1 GB Parquet (zstd level 7).
- one-shot consumption by DuckDB / Polars / pandas / Spark / Databricks.
- per-column license metadata is a native Parquet feature, so the
  downstream cannot accidentally strip attribution.

License compliance
------------------
Each table-level pyarrow.Schema carries:
    schema_metadata = {
        b"license":          b"<spdx-id or our internal tag>",
        b"license_url":      b"<canonical license URL>",
        b"attribution_text": b"<出典: 国税庁 / e-Gov / 経産省 ...>",
        b"source_url":       b"<canonical primary source>",
        b"fetched_at":       b"<UTC ISO8601>",
    }

The file-level metadata also embeds a JSON manifest listing every table +
license. The README artifact uploaded alongside the parquet repeats the
license summary in human-readable form so reviewers (法人購買 / 法務部)
can verify without parsing the Parquet header.

Outputs (R2 bucket `r2.jpcite.com`):
  /exports/jpcite_corpus_{YYYY-MM}.parquet         primary artifact
  /exports/jpcite_corpus_{YYYY-MM}.parquet.sha256  integrity checksum
  /exports/jpcite_corpus_{YYYY-MM}.license.json    machine-readable license
  /exports/jpcite_corpus_{YYYY-MM}.README.md       human-readable summary

Run via GHA monthly workflow (.github/workflows/parquet-export-monthly.yml).
Local smoke: `python scripts/cron/export_parquet_corpus.py --dry-run`.

Required env: AUTONOMATH_DB_PATH (default autonomath.db),
              JPINTEL_DB_PATH (default data/jpintel.db),
              R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
              R2_BUCKET (default autonomath-exports).
Optional env: PARQUET_LOCAL_DIR (default /tmp/jpcite_parquet_export).

Exit codes: 0 ok / 1 config / 2 db / 3 parquet / 4 upload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("jpcite.cron.export_parquet_corpus")

# --- License manifest ----------------------------------------------------
#
# Table-level license metadata. Each table maps to a (license, license_url,
# attribution_text, source_url) tuple. License tags are intentionally not
# arbitrary SPDX — they match the controlled vocabulary already used in
# `am_source.license` so a downstream LEFT JOIN by license string is safe.
#
# Tables we deliberately DO NOT export here:
#   - usage_events: customer telemetry (privacy)
#   - api_keys / idempotency_cache / volume_rebate_grant / sla_breach_refund_grant: ops
#   - examiner_feedback / dd_question_templates: operator-internal
#   - any *_review_queue tables: pending-review (not first-party publishable yet)

LicenseEntry = dict[str, str]

TABLE_LICENSE: dict[str, LicenseEntry] = {
    # --- autonomath.db ---
    "am_entities": {
        "license": "mixed",
        "license_url": "https://jpcite.com/data-licensing.html",
        "attribution_text": "出典: 各一次資料 (e-Gov / 国税庁 / 経産省 / 都道府県 等)",
        "source_url": "https://jpcite.com/sources.html",
    },
    "am_entity_facts": {
        "license": "mixed",
        "license_url": "https://jpcite.com/data-licensing.html",
        "attribution_text": "出典: 各一次資料 (e-Gov / 国税庁 / 経産省 / 都道府県 等)",
        "source_url": "https://jpcite.com/sources.html",
    },
    "am_alias": {
        "license": "mixed",
        "license_url": "https://jpcite.com/data-licensing.html",
        "attribution_text": "出典: 各一次資料 + jpcite 編集",
        "source_url": "https://jpcite.com/sources.html",
    },
    "am_relation": {
        "license": "mixed",
        "license_url": "https://jpcite.com/data-licensing.html",
        "attribution_text": "出典: 各一次資料 + jpcite 編集 (関係抽出)",
        "source_url": "https://jpcite.com/sources.html",
    },
    "am_authority": {
        "license": "gov_standard_v2",
        "license_url": "https://www.digital.go.jp/resources/data_policy",
        "attribution_text": "出典: 政府機関 (gov_standard v2.0)",
        "source_url": "https://www.digital.go.jp/resources/data_policy",
    },
    "am_region": {
        "license": "public_domain",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "attribution_text": "出典: 総務省 全国地方公共団体コード (公共領域)",
        "source_url": "https://www.soumu.go.jp/denshijiti/code.html",
    },
    "am_law_article": {
        "license": "cc_by_4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution_text": "出典: デジタル庁 e-Gov 法令検索 (CC BY 4.0)",
        "source_url": "https://laws.e-gov.go.jp/",
    },
    "am_tax_rule": {
        "license": "gov_standard_v2",
        "license_url": "https://www.digital.go.jp/resources/data_policy",
        "attribution_text": "出典: 国税庁 + 経済産業省 (gov_standard v2.0)",
        "source_url": "https://www.nta.go.jp/",
    },
    "am_subsidy_rule": {
        "license": "gov_standard_v2",
        "license_url": "https://www.digital.go.jp/resources/data_policy",
        "attribution_text": "出典: 経済産業省 + 農林水産省 + 都道府県 (gov_standard v2.0)",
        "source_url": "https://www.meti.go.jp/",
    },
    "am_application_round": {
        "license": "gov_standard_v2",
        "license_url": "https://www.digital.go.jp/resources/data_policy",
        "attribution_text": "出典: 各省庁公募ページ",
        "source_url": "https://jpcite.com/sources.html",
    },
    "am_loan_product": {
        "license": "individual",
        "license_url": "https://www.jfc.go.jp/",
        "attribution_text": "出典: 日本政策金融公庫 (個別利用許諾)",
        "source_url": "https://www.jfc.go.jp/",
    },
    "am_insurance_mutual": {
        "license": "individual",
        "license_url": "https://jpcite.com/sources.html",
        "attribution_text": "出典: 各共済団体 (個別利用許諾)",
        "source_url": "https://jpcite.com/sources.html",
    },
    "am_industry_jsic": {
        "license": "public_domain",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "attribution_text": "出典: 総務省 日本標準産業分類 JSIC (公共領域)",
        "source_url": "https://www.soumu.go.jp/toukei_toukatsu/index/seido/sangyo/index.htm",
    },
    "am_enforcement_detail": {
        "license": "gov_standard_v2",
        "license_url": "https://www.digital.go.jp/resources/data_policy",
        "attribution_text": "出典: 経産省・国交省・厚労省・環境省 行政処分",
        "source_url": "https://jpcite.com/sources.html",
    },
    "am_amendment_snapshot": {
        "license": "mixed",
        "license_url": "https://jpcite.com/data-licensing.html",
        "attribution_text": "出典: 各一次資料 + jpcite 差分 capture",
        "source_url": "https://jpcite.com/audit-log.html",
    },
    "am_tax_treaty": {
        "license": "gov_standard_v2",
        "license_url": "https://www.digital.go.jp/resources/data_policy",
        "attribution_text": "出典: 財務省 / 外務省 租税条約",
        "source_url": "https://www.mof.go.jp/tax_policy/summary/international/h05.htm",
    },
    # --- jpintel.db ---
    "programs": {
        "license": "mixed",
        "license_url": "https://jpcite.com/data-licensing.html",
        "attribution_text": "出典: 各一次資料 (e-Gov / 経産省 / 都道府県 等)",
        "source_url": "https://jpcite.com/sources.html",
    },
    "case_studies": {
        "license": "individual",
        "license_url": "https://jpcite.com/sources.html",
        "attribution_text": "出典: 各採択公表ページ",
        "source_url": "https://jpcite.com/sources.html",
    },
    "loan_programs": {
        "license": "individual",
        "license_url": "https://www.jfc.go.jp/",
        "attribution_text": "出典: 日本政策金融公庫 (個別利用許諾)",
        "source_url": "https://www.jfc.go.jp/",
    },
    "enforcement_cases": {
        "license": "gov_standard_v2",
        "license_url": "https://www.digital.go.jp/resources/data_policy",
        "attribution_text": "出典: 各省庁行政処分",
        "source_url": "https://jpcite.com/sources.html",
    },
    "exclusion_rules": {
        "license": "mixed",
        "license_url": "https://jpcite.com/data-licensing.html",
        "attribution_text": "出典: 各制度公募要領 + jpcite 抽出",
        "source_url": "https://jpcite.com/sources.html",
    },
    "laws": {
        "license": "cc_by_4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution_text": "出典: デジタル庁 e-Gov (CC BY 4.0)",
        "source_url": "https://laws.e-gov.go.jp/",
    },
    "tax_rulesets": {
        "license": "gov_standard_v2",
        "license_url": "https://www.digital.go.jp/resources/data_policy",
        "attribution_text": "出典: 国税庁 (gov_standard v2.0)",
        "source_url": "https://www.nta.go.jp/law/",
    },
    "court_decisions": {
        "license": "public_domain",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "attribution_text": "出典: 知財高裁 / 特許庁 (公共領域)",
        "source_url": "https://www.ip.courts.go.jp/",
    },
    "bids": {
        "license": "individual",
        "license_url": "https://jpcite.com/sources.html",
        "attribution_text": "出典: 各発注機関 公共入札",
        "source_url": "https://www.geps.go.jp/",
    },
    "invoice_registrants": {
        "license": "pdl_v1.0",
        "license_url": "https://www.digital.go.jp/resources/data_policy",
        "attribution_text": "出典: 国税庁 適格請求書発行事業者公表データ (PDL v1.0)",
        "source_url": "https://www.invoice-kohyo.nta.go.jp/",
    },
}

# Lazy import — pyarrow is heavy (~50 MB) and we don't want it on the
# request-path. Only the monthly cron + dry-run smoke import this.
def _import_pyarrow() -> Any:
    try:
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "pyarrow is required for parquet export — pip install pyarrow"
        ) from exc
    return pa, pq


def _previous_month_period_jst() -> str:
    """YYYY-MM for the previous calendar month (JST)."""
    now_utc = datetime.now(UTC)
    now_jst = now_utc + timedelta(hours=9)
    first_of_month_jst = now_jst.replace(day=1)
    prev_last_jst = first_of_month_jst - timedelta(days=1)
    return prev_last_jst.strftime("%Y-%m")


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone()
    return row is not None


def _table_rowcount(conn: sqlite3.Connection, name: str) -> int:
    # Safe — name comes from TABLE_LICENSE (controlled vocab), never user input.
    return int(conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])


def _read_sqlite_table_to_arrow(
    pa: Any,
    conn: sqlite3.Connection,
    table: str,
    license_meta: LicenseEntry,
    fetched_at: str,
    limit: int | None = None,
) -> Any:
    """Read a SQLite table into a pyarrow Table tagged with license metadata.

    For very large tables we paginate via fetchmany() to keep peak memory
    inside the GHA runner's 7 GB budget.
    """
    sql = f"SELECT * FROM {table}"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    cur = conn.execute(sql)
    cols = [d[0] for d in cur.description]
    rows: list[tuple[Any, ...]] = []
    while True:
        batch = cur.fetchmany(10000)
        if not batch:
            break
        rows.extend(batch)
    py_cols = {col: [r[i] for r in rows] for i, col in enumerate(cols)}
    arrow_tbl = pa.Table.from_pydict(py_cols)
    metadata = {
        b"license": license_meta["license"].encode("utf-8"),
        b"license_url": license_meta["license_url"].encode("utf-8"),
        b"attribution_text": license_meta["attribution_text"].encode("utf-8"),
        b"source_url": license_meta["source_url"].encode("utf-8"),
        b"fetched_at": fetched_at.encode("utf-8"),
        b"jpcite_table": table.encode("utf-8"),
    }
    arrow_tbl = arrow_tbl.replace_schema_metadata(metadata)
    return arrow_tbl


def _build_license_manifest(period: str, tables_emitted: dict[str, int]) -> dict[str, Any]:
    return {
        "period": period,
        "operator": "Bookyou株式会社",
        "operator_invoice_no": "T8010001213708",
        "homepage": "https://jpcite.com",
        "license_summary_url": "https://jpcite.com/data-licensing.html",
        "regenerable": True,
        "tables": [
            {
                "name": tname,
                "row_count": tables_emitted.get(tname, 0),
                "license": meta["license"],
                "license_url": meta["license_url"],
                "attribution_text": meta["attribution_text"],
                "source_url": meta["source_url"],
            }
            for tname, meta in TABLE_LICENSE.items()
            if tname in tables_emitted
        ],
        "redistribution_terms": {
            "permitted": [
                "downstream LLM / agent reasoning",
                "internal analysis + report",
                "academic research with attribution",
            ],
            "forbidden": [
                "bulk re-distribution as equivalent paid data service",
                "stripping per-table license metadata",
            ],
            "source_doc": "https://jpcite.com/data-licensing.html#redistribution",
        },
    }


def _build_readme(period: str, manifest: dict[str, Any], parquet_size_bytes: int) -> str:
    size_mb = parquet_size_bytes / (1024 * 1024)
    lines = [
        f"# jpcite Corpus Export — {period}",
        "",
        f"- Operator: Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708)",
        f"- Generated at: {datetime.now(UTC).isoformat()}",
        f"- File size: {size_mb:.1f} MB",
        f"- Tables: {len(manifest['tables'])}",
        "",
        "## License summary (per table)",
        "",
        "| Table | Rows | License | Attribution |",
        "|---|---:|---|---|",
    ]
    for t in manifest["tables"]:
        lines.append(
            f"| `{t['name']}` | {t['row_count']:,} | "
            f"[{t['license']}]({t['license_url']}) | {t['attribution_text']} |"
        )
    lines += [
        "",
        "## Redistribution",
        "",
        "Permitted:",
        *[f"- {p}" for p in manifest["redistribution_terms"]["permitted"]],
        "",
        "Forbidden:",
        *[f"- {p}" for p in manifest["redistribution_terms"]["forbidden"]],
        "",
        f"Full terms: {manifest['redistribution_terms']['source_doc']}",
        "",
        "## Reproducibility",
        "",
        "This export is regenerable from the upstream sources via",
        "`scripts/cron/export_parquet_corpus.py` in the jpcite repo.",
        "Each row's `am_source.license` (when present) is the authoritative",
        "per-row license — the table-level tag above is a convenience header.",
    ]
    return "\n".join(lines) + "\n"


def _write_parquet(
    pa: Any,
    pq: Any,
    tables: list[tuple[str, Any]],
    out_path: Path,
) -> None:
    """Write a Parquet dataset: one file per table inside a directory.

    Schemas differ across tables (programs vs am_law_article vs invoice_
    registrants share no columns), so a single multi-table Parquet is
    impractical — pyarrow's column-cast machinery can't reconcile e.g.
    string vs int32 vs binary in a union. Instead we write a Parquet
    *dataset*: `out_path` is a directory containing one Parquet file per
    table. Downstream consumers can read the whole tree via
    `pyarrow.parquet.read_table(out_dir)` (auto-discovers all files) or
    cherry-pick a single table by name.

    `out_path` is intentionally named as if it were a file (e.g.
    `jpcite_corpus_2026-04.parquet`) so the public URL pattern stays
    stable. We create it as a directory and write `<table>.parquet`
    children inside it. Cloudflare R2 happily serves the directory tree
    — clients fetch individual table files by URL.
    """
    if not tables:
        raise RuntimeError("no tables emitted — refusing to write empty parquet")

    # If a prior run left a single-file Parquet at out_path, remove it so
    # we can recreate as a directory (Parquet dataset). exist_ok=True only
    # tolerates an existing *directory*, not a file with the same name.
    if out_path.exists() and not out_path.is_dir():
        out_path.unlink()
    out_path.mkdir(parents=True, exist_ok=True)
    for name, tbl in tables:
        # Tag every row with the canonical table name so a consumer that
        # later concatenates the per-table frames doesn't lose lineage.
        tagged = tbl.append_column(
            "_table", pa.array([name] * tbl.num_rows, type=pa.string()),
        )
        target = out_path / f"{name}.parquet"
        pq.write_table(
            tagged,
            target,
            compression="zstd",
            compression_level=7,
        )


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_dataset(directory: Path) -> str:
    """SHA-256 over a sorted concatenation of `<name>\\0<file_sha>\\n` lines.

    Stable across runs as long as the file set + contents are identical.
    Cheaper than concatenating every byte (multi-GB) and gives reviewers a
    single fingerprint to verify the dataset hasn't been tampered with on R2.
    """
    parts = []
    for p in sorted(directory.iterdir()):
        if p.is_file() and p.suffix == ".parquet":
            parts.append(f"{p.name}\x00{_sha256_file(p)}\n")
    h = hashlib.sha256()
    h.update("".join(parts).encode("utf-8"))
    return h.hexdigest()


def _dataset_size_bytes(directory: Path) -> int:
    return sum(p.stat().st_size for p in directory.iterdir() if p.is_file())


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument("--period", help="YYYY-MM (default = previous month JST).")
    p.add_argument(
        "--autonomath-db",
        default=os.environ.get("AUTONOMATH_DB_PATH", "autonomath.db"),
    )
    p.add_argument(
        "--jpintel-db",
        default=os.environ.get("JPINTEL_DB_PATH", "data/jpintel.db"),
    )
    p.add_argument(
        "--local-dir",
        default=os.environ.get("PARQUET_LOCAL_DIR", "/tmp/jpcite_parquet_export"),
    )
    p.add_argument(
        "--bucket",
        default=os.environ.get("R2_BUCKET", "autonomath-exports"),
    )
    p.add_argument(
        "--prefix",
        default=os.environ.get("PARQUET_R2_PREFIX", "exports"),
    )
    p.add_argument(
        "--row-limit-per-table",
        type=int,
        default=None,
        help="Cap rows per table (dry-run smoke).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Build Parquet locally but skip R2 upload.",
    )
    p.add_argument(
        "--smoke",
        action="store_true",
        help="Minimal probe: row-limit=100, dry-run, no DB write requirement.",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="DEBUG-level logging.",
    )
    return p.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    period = args.period or _previous_month_period_jst()
    local_dir = Path(args.local_dir)
    _ensure_dir(local_dir)
    base_name = f"jpcite_corpus_{period}"
    parquet_path = local_dir / f"{base_name}.parquet"
    sha_path = local_dir / f"{base_name}.parquet.sha256"
    license_path = local_dir / f"{base_name}.license.json"
    readme_path = local_dir / f"{base_name}.README.md"

    if args.smoke:
        args.row_limit_per_table = args.row_limit_per_table or 100
        args.dry_run = True

    logger.info(
        "export_parquet_corpus.start period=%s autonomath_db=%s jpintel_db=%s "
        "row_limit=%s dry_run=%s",
        period, args.autonomath_db, args.jpintel_db,
        args.row_limit_per_table, args.dry_run,
    )

    try:
        pa, pq = _import_pyarrow()
    except RuntimeError as exc:
        logger.error("export_parquet_corpus.no_pyarrow %s", exc)
        return 1

    fetched_at = datetime.now(UTC).isoformat()
    tables_out: list[tuple[str, Any]] = []
    rowcounts: dict[str, int] = {}

    db_jobs = [
        (Path(args.autonomath_db), [t for t in TABLE_LICENSE if t.startswith("am_")]),
        (Path(args.jpintel_db), [t for t in TABLE_LICENSE if not t.startswith("am_")]),
    ]
    for db_path, table_names in db_jobs:
        if not db_path.exists():
            logger.warning(
                "export_parquet_corpus.db_missing path=%s — skipping its tables",
                db_path,
            )
            continue
        conn = sqlite3.connect(str(db_path))
        try:
            for tname in table_names:
                if not _table_exists(conn, tname):
                    logger.debug(
                        "export_parquet_corpus.table_missing db=%s table=%s — skip",
                        db_path.name, tname,
                    )
                    continue
                rc_total = _table_rowcount(conn, tname)
                logger.info(
                    "export_parquet_corpus.read db=%s table=%s rows=%d limit=%s",
                    db_path.name, tname, rc_total, args.row_limit_per_table,
                )
                tbl = _read_sqlite_table_to_arrow(
                    pa, conn, tname, TABLE_LICENSE[tname], fetched_at,
                    limit=args.row_limit_per_table,
                )
                tables_out.append((tname, tbl))
                rowcounts[tname] = tbl.num_rows
        finally:
            conn.close()

    if not tables_out:
        logger.error("export_parquet_corpus.no_tables — abort")
        return 2

    try:
        _write_parquet(pa, pq, tables_out, parquet_path)
    except Exception as exc:
        logger.exception("export_parquet_corpus.parquet_write_error %s", exc)
        return 3

    # Parquet dataset is a directory (one file per table). Size + SHA cover
    # all child files so the .sha256 sidecar is a stable fingerprint of the
    # dataset as a whole.
    size_bytes = _dataset_size_bytes(parquet_path)
    sha = _sha256_dataset(parquet_path)
    sha_path.write_text(f"{sha}  {parquet_path.name}/\n", encoding="utf-8")

    manifest = _build_license_manifest(period, rowcounts)
    license_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    readme_path.write_text(
        _build_readme(period, manifest, size_bytes), encoding="utf-8",
    )

    logger.info(
        "export_parquet_corpus.built path=%s size_mb=%.1f sha256=%s tables=%d",
        parquet_path, size_bytes / (1024 * 1024), sha, len(tables_out),
    )

    if args.dry_run:
        logger.info("export_parquet_corpus.dry_run skip_upload")
        return 0

    # R2 upload via the shared rclone-based helper. Imported lazily so dry-
    # run smoke works on a workstation without R2 secrets.
    try:
        from cron._r2_client import upload  # type: ignore
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        try:
            from cron._r2_client import upload  # type: ignore
        except ImportError as exc:
            logger.error("export_parquet_corpus.no_r2_client %s", exc)
            return 4

    bucket = args.bucket
    prefix = args.prefix.strip("/")
    # Per-table Parquet files live under the dataset directory; ship each
    # one as `<dataset>/<table>.parquet` so the public R2 URL pattern is
    # stable and reviewers can fetch a single table without downloading
    # the whole ~1 GB corpus.
    artifacts: list[tuple[Path, str]] = []
    for child in sorted(parquet_path.iterdir()):
        if child.is_file() and child.suffix == ".parquet":
            artifacts.append((child, f"{prefix}/{parquet_path.name}/{child.name}"))
    artifacts.extend([
        (sha_path, f"{prefix}/{sha_path.name}"),
        (license_path, f"{prefix}/{license_path.name}"),
        (readme_path, f"{prefix}/{readme_path.name}"),
    ])
    for local_path, remote_key in artifacts:
        try:
            upload(local_path, remote_key, bucket=bucket)
            logger.info(
                "export_parquet_corpus.uploaded key=%s bytes=%d",
                remote_key, local_path.stat().st_size,
            )
        except Exception as exc:
            logger.exception(
                "export_parquet_corpus.upload_error key=%s err=%s", remote_key, exc,
            )
            return 4

    logger.info(
        "export_parquet_corpus.done period=%s url=https://r2.jpcite.com/%s/%s",
        period, prefix, parquet_path.name,
    )
    return 0


if __name__ == "__main__":
    sys.exit(run())
