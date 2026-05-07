#!/usr/bin/env python3
"""HuggingFace dataset export: pre-computed embeddings (jpcite/embeddings-jp).

Exports the `am_entities_vec` (sqlite-vec) embedding table joined with
`am_entities` metadata + `am_source` license/provenance to a single
parquet shard suitable for direct ingestion into FAISS / chroma / pgvector.

Why publish embeddings (vs. raw text only):
  - Existing HF datasets (laws-jp / invoice-registrants / statistics-estat /
    corp-enforcement) are raw text. RAG developers must run the embedder
    themselves before they can prototype.
  - Shipping pre-computed `intfloat/multilingual-e5-small` (384-d) vectors
    lets a developer `pip install datasets faiss-cpu` and have a working
    Japanese-public-program semantic index in <60 lines of code.
  - Each row carries `source_url` + `content_hash` + `fetched_at`, so
    downstream apps can prove freshness and re-fetch for audit.
  - The live `api.jpcite.com` endpoint (¥3 / req metered) is the streaming
    path; this dataset is the static snapshot path. Same upstream pipeline.

Filter rules (fail-closed):
  - License must be in {pdl_v1.0, cc_by_4.0, gov_standard_v2.0, public_domain}.
    Rows whose ONLY backing source is `proprietary` or `unknown` are dropped
    (matches `scripts/etl/hf_export_safety_gate.py:BLOCKED_LICENSES`).
  - Embedded rows must exist in BOTH `am_entities` (metadata) AND
    `am_entities_vec` (vector). Missing-one-side rows are dropped silently.
  - `record_kind` defaults to ALL non-PII kinds:
        program, law, authority, tax_measure, certification,
        case_study, statistic, enforcement, adoption,
        corporate_entity (NTA invoice register PDL v1.0),
        invoice_registrant (excluded by default — sensitive PII surface).
    Override with --record-kinds.
  - `primary_name` must be non-empty.

Outputs (under --output, default dist/hf-datasets/embeddings-jp/):
  - data.parquet  — single shard, columns:
      entity_id (string)
      record_kind (string, dictionary-encoded)
      primary_name (string)
      summary (string, may be empty)
      embedding (fixed_size_list[float32, 384])
      source_url (string)
      source_url_domain (string)
      content_hash (string, sha256)
      fetched_at (string, ISO 8601)
      license (string, one of the 4 allowed)
      snapshot_id (string, e.g. 2026-04)
  - manifest.json — row_count, file_size, checksum, model name, dim,
    record_kind histogram, license histogram

Usage:
  uv run python scripts/etl/export_hf_embeddings.py --limit 1000 --dry-run
  uv run python scripts/etl/export_hf_embeddings.py
  uv run python scripts/etl/export_hf_embeddings.py --push --dataset bookyou/embeddings-jp
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sqlite3
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq
import sqlite_vec  # type: ignore

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "autonomath.db"
DEFAULT_OUTPUT = REPO_ROOT / "dist" / "hf-datasets" / "embeddings-jp"

EMBED_MODEL = "intfloat/multilingual-e5-small"
EMBED_DIM = 384

# Mirrors hf_export_safety_gate.py
ALLOWED_LICENSES = ("pdl_v1.0", "cc_by_4.0", "gov_standard_v2.0", "public_domain")

# By default, exclude the two PII-heaviest record_kinds:
#   - invoice_registrant: contains 個人事業主 names; redistribution requires
#     PDL v1.0 attribution conformance which is best handled by the
#     dedicated `bookyou/invoice-registrants` dataset, not bundled here.
#   - document: 1 row, edge case.
DEFAULT_RECORD_KINDS = (
    "program",
    "law",
    "authority",
    "tax_measure",
    "certification",
    "case_study",
    "statistic",
    "enforcement",
    "adoption",
    "corporate_entity",
)

EXTRACT_QUERY = """
SELECT
  e.canonical_id        AS entity_id,
  e.record_kind         AS record_kind,
  e.primary_name        AS primary_name,
  e.source_url          AS source_url,
  e.source_url_domain   AS source_url_domain,
  e.fetched_at          AS fetched_at,
  s.content_hash        AS content_hash,
  s.license             AS license
FROM am_entities_vec_rowids r
JOIN am_entities e
  ON e.canonical_id = r.id
JOIN am_entity_source es
  ON es.entity_id = e.canonical_id
JOIN am_source s
  ON s.id = es.source_id
WHERE s.license IN ({allowed})
  AND e.primary_name IS NOT NULL
  AND TRIM(e.primary_name) <> ''
  AND e.record_kind IN ({kinds})
GROUP BY e.canonical_id
"""


def open_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    # Read-only by convention (CLAUDE constraint). We don't BEGIN / COMMIT.
    return conn


def fetch_embedding(conn: sqlite3.Connection, entity_id: str) -> list[float] | None:
    """Pull the 384-d float32 vector for one canonical_id.

    `am_entities_vec` is a vec0 virtual table; we read the BLOB from the
    underlying chunked storage via `embedding` column projection.
    """
    row = conn.execute(
        "SELECT embedding FROM am_entities_vec WHERE canonical_id = ?",
        (entity_id,),
    ).fetchone()
    if row is None:
        return None
    blob: bytes = row[0]
    if len(blob) != EMBED_DIM * 4:
        return None
    return list(struct.unpack(f"{EMBED_DIM}f", blob))


def get_summary(conn: sqlite3.Connection, entity_id: str) -> str:
    """Best-effort 1-line summary from am_entity_facts.

    Picks the first present field among `summary`, `description`, `purpose`,
    `overview` (preserves null-safety; returns "" if none).
    """
    row = conn.execute(
        """
        SELECT field_value_text
        FROM am_entity_facts
        WHERE entity_id = ?
          AND field_name IN ('summary','description','purpose','overview')
          AND field_value_text IS NOT NULL
        ORDER BY
          CASE field_name
            WHEN 'summary' THEN 1
            WHEN 'description' THEN 2
            WHEN 'purpose' THEN 3
            WHEN 'overview' THEN 4
          END
        LIMIT 1
        """,
        (entity_id,),
    ).fetchone()
    if row is None:
        return ""
    txt = row[0] or ""
    # Trim aggressive whitespace; keep single-line for parquet hygiene.
    return " ".join(txt.split())


def iter_rows(
    conn: sqlite3.Connection,
    record_kinds: tuple[str, ...],
    limit: int | None,
) -> Iterator[dict]:
    allowed = ",".join(f"'{lic}'" for lic in ALLOWED_LICENSES)
    kinds = ",".join(f"'{k}'" for k in record_kinds)
    query = EXTRACT_QUERY.format(allowed=allowed, kinds=kinds)
    if limit is not None:
        query += f" LIMIT {int(limit)}"

    cur = conn.execute(query)
    n_seen = 0
    n_kept = 0
    for meta in cur:
        n_seen += 1
        emb = fetch_embedding(conn, meta["entity_id"])
        if emb is None:
            continue
        summary = get_summary(conn, meta["entity_id"])
        n_kept += 1
        yield {
            "entity_id": meta["entity_id"],
            "record_kind": meta["record_kind"],
            "primary_name": meta["primary_name"],
            "summary": summary,
            "embedding": emb,
            "source_url": meta["source_url"] or "",
            "source_url_domain": meta["source_url_domain"] or "",
            "content_hash": meta["content_hash"] or "",
            "fetched_at": meta["fetched_at"] or "",
            "license": meta["license"],
        }
    sys.stderr.write(f"[iter_rows] candidates={n_seen} written={n_kept}\n")


def build_arrow_table(rows: list[dict], snapshot_id: str) -> pa.Table:
    """Build the pyarrow Table with FixedSizeList for the embedding column."""
    if not rows:
        raise SystemExit("no rows to write — check filters / DB state")

    # Add snapshot_id to every row (constant for one export).
    for r in rows:
        r["snapshot_id"] = snapshot_id

    schema = pa.schema(
        [
            ("entity_id", pa.string()),
            ("record_kind", pa.dictionary(pa.int32(), pa.string())),
            ("primary_name", pa.string()),
            ("summary", pa.string()),
            ("embedding", pa.list_(pa.float32(), EMBED_DIM)),
            ("source_url", pa.string()),
            ("source_url_domain", pa.string()),
            ("content_hash", pa.string()),
            ("fetched_at", pa.string()),
            ("license", pa.string()),
            ("snapshot_id", pa.string()),
        ]
    )

    columns = {name: [] for name in schema.names}
    for r in rows:
        for name in schema.names:
            columns[name].append(r[name])

    arrays = []
    for field in schema:
        if field.name == "embedding":
            arrays.append(pa.array(columns[field.name], type=field.type))
        else:
            arrays.append(pa.array(columns[field.name], type=field.type))
    return pa.Table.from_arrays(arrays, schema=schema)


def write_parquet(table: pa.Table, out_path: Path) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        table,
        out_path,
        compression="zstd",  # smaller than snappy on float vectors
        compression_level=3,
    )
    return out_path.stat().st_size


def write_manifest(
    out_path: Path,
    parquet_path: Path,
    parquet_size: int,
    rows: list[dict],
    snapshot_id: str,
) -> None:
    sha = hashlib.sha256(parquet_path.read_bytes()).hexdigest()
    manifest = {
        "dataset": "bookyou/embeddings-jp",
        "snapshot_id": snapshot_id,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "embedding_model": EMBED_MODEL,
        "embedding_dim": EMBED_DIM,
        "row_count": len(rows),
        "parquet_file": parquet_path.name,
        "parquet_size_bytes": parquet_size,
        "parquet_sha256": sha,
        "license": "cc-by-4.0",
        "record_kind_histogram": dict(Counter(r["record_kind"] for r in rows)),
        "license_histogram": dict(Counter(r["license"] for r in rows)),
        "domain_top_10": dict(
            Counter(r["source_url_domain"] for r in rows if r["source_url_domain"]).most_common(10)
        ),
    }
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap rows for smoke export (e.g. --limit 1000)",
    )
    ap.add_argument(
        "--record-kinds",
        nargs="+",
        default=list(DEFAULT_RECORD_KINDS),
        choices=[
            "program",
            "law",
            "authority",
            "adoption",
            "enforcement",
            "tax_measure",
            "certification",
            "document",
            "case_study",
            "statistic",
            "region",
            "industry",
            "corporate_entity",
            "invoice_registrant",
        ],
    )
    ap.add_argument(
        "--snapshot-id",
        default=dt.date.today().strftime("%Y-%m"),
        help="Snapshot tag (default: YYYY-MM today, e.g. 2026-04)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Build parquet but do NOT write final files (in-memory only)",
    )
    ap.add_argument(
        "--push",
        action="store_true",
        help="After export, upload to HuggingFace (requires HF_TOKEN env)",
    )
    ap.add_argument(
        "--dataset",
        default="bookyou/embeddings-jp",
        help="HF dataset repo id (only used with --push)",
    )
    args = ap.parse_args()

    db_path: Path = args.db
    out_dir: Path = args.output

    if not db_path.exists():
        print(f"ERROR: DB not found: {db_path}", file=sys.stderr)
        return 1

    print(f"Source DB:    {db_path}")
    print(f"Output dir:   {out_dir}")
    print(f"Snapshot:     {args.snapshot_id}")
    print(f"Model:        {EMBED_MODEL} ({EMBED_DIM}-d)")
    print(f"Record kinds: {','.join(args.record_kinds)}")
    if args.limit:
        print(f"Row cap:      {args.limit}")
    if args.dry_run:
        print("Mode:         DRY RUN (no files written)")
    print()

    conn = open_db(db_path)
    try:
        rows = list(iter_rows(conn, tuple(args.record_kinds), args.limit))
    finally:
        conn.close()

    if not rows:
        print("ERROR: no rows extracted — check filter / DB", file=sys.stderr)
        return 1

    table = build_arrow_table(rows, args.snapshot_id)

    print(f"  rows extracted: {len(rows):,}")
    print("  schema:")
    for f in table.schema:
        print(f"    {f.name:24s} {f.type}")
    print()

    if args.dry_run:
        # Estimate parquet size by writing to /tmp and reading size.
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        size = write_parquet(table, tmp_path)
        print(f"  parquet (dry): {fmt_bytes(size)} -> {tmp_path}")
        # Sample row preview
        sample = rows[0].copy()
        sample["embedding"] = f"<{EMBED_DIM} float32, head={sample['embedding'][:3]}>"
        print(f"  sample row:    {json.dumps(sample, ensure_ascii=False)[:300]}...")
        return 0

    parquet_path = out_dir / "data.parquet"
    parquet_size = write_parquet(table, parquet_path)
    manifest_path = out_dir / "manifest.json"
    write_manifest(manifest_path, parquet_path, parquet_size, rows, args.snapshot_id)

    print(f"  data.parquet:  {fmt_bytes(parquet_size)}  ({parquet_path})")
    print(f"  manifest.json: {manifest_path}")

    if args.push:
        try:
            from huggingface_hub import HfApi  # type: ignore
        except ImportError:
            print(
                "ERROR: huggingface_hub not installed; pip install huggingface_hub", file=sys.stderr
            )
            return 1
        import os

        token = os.environ.get("HF_TOKEN")
        if not token:
            print("ERROR: HF_TOKEN env var not set", file=sys.stderr)
            return 1
        api = HfApi(token=token)
        api.upload_folder(
            folder_path=str(out_dir),
            repo_id=args.dataset,
            repo_type="dataset",
            commit_message=f"snapshot {args.snapshot_id} ({len(rows)} rows, {EMBED_MODEL})",
        )
        print(f"  pushed:        https://huggingface.co/datasets/{args.dataset}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
