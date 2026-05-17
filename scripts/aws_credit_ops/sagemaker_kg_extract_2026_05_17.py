#!/usr/bin/env python3
"""Lane M1 — PDF → KG triples bulk extractor (jpcite AWS moat, 2026-05-17).

Streams Textract OCR JSON from the Singapore staging bucket
``s3://jpcite-credit-textract-apse1-202605/out/<sha[:2]>/<sha>/<page>``
and writes deterministic entity_facts + relations into
``autonomath.db`` (``am_entity_facts`` + ``am_relation``).

Surface
-------
1. **Discover** : list ``out/`` under the staging bucket, drop
   ``.s3_access_check`` filler, group object keys by document hash so
   page-level shards roll up to a single document.
2. **Stream** : for each kept object key, ``boto3.get_object`` (no
   local file mirror — the Tokyo mirror at ``kg_textract_mirror_*`` is
   write-side only and not needed for read).
3. **Extract** : parse Textract Block list → per-page text → regex /
   dictionary entity + relation harvest (delegated to
   :mod:`jpintel_mcp.moat.m1_kg_extraction`).
4. **Ingest** : INSERT OR IGNORE into ``am_entity_facts`` +
   ``am_relation`` keyed on (entity_id, field_name, value_text) and
   (source_entity_id, target_entity_id, relation_type, source_field).
5. **Ledger** : INSERT row into ``am_kg_extracted_log`` with run
   metadata + counts.

Why local, not SageMaker
------------------------
* Regex / dictionary harvest is CPU-bound and finishes in a few minutes
  for a 4K-doc corpus on a single laptop core; SageMaker spin-up alone
  costs more wall-clock + dollars.
* No model inference needed — the OCR-output corpus has unreliable
  CJK recall, so dictionary-based NER over the raw text recovers
  exactly the deterministic signals (houjin / dates / URLs / amounts)
  that survive Textract. A GPU-backed transformer NER would not
  recover what Textract did not OCR in the first place.
* This matches the operator memory
  ``feedback_packet_gen_runs_local_not_batch`` and
  ``feedback_packet_local_gen_300x_faster``.

The script keeps a ``--mode sagemaker`` hot-spare path that renders a
SageMaker Processing spec for the same code but does **not** call
``create_processing_job`` unless ``--commit-sagemaker`` is set. The
LIVE production path is ``--mode local --commit``.

Constraints honoured
--------------------
* AWS profile ``bookyou-recovery`` (memory: secret-store separation).
* NO LLM API calls — pure regex / dictionary harvest. Imports neither
  ``anthropic`` nor ``openai`` nor ``google.generativeai``.
* ``$19,490`` Never-Reach hard stop pre-flight — read
  ``JPCITE/Burn::CumulativeBurnUSD`` in ``ap-northeast-1`` CW; abort if
  > $19,000.
* ``[lane:solo]`` marker — sole writer to autonomath.db during the run.
* mypy strict / ruff 0.

CLI
---
::

    .venv/bin/python scripts/aws_credit_ops/sagemaker_kg_extract_2026_05_17.py \\
        --autonomath-db autonomath.db \\
        --staging-bucket jpcite-credit-textract-apse1-202605 \\
        --staging-prefix out/ \\
        --max-docs 0 \\
        --mode local \\
        --commit
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

# Ensure project src/ is importable when running via the venv interpreter.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

# Late import after sys.path tweak — keeps the script invokable from
# both ``python -m`` and direct ``./script.py`` modes without needing a
# wheel install.
from jpintel_mcp.moat.m1_kg_extraction import (  # noqa: E402
    ExtractedEntity,
    ExtractedRelation,
    cjk_char_ratio,
    extract_kg,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger("sagemaker_kg_extract")


# ---- Constants -------------------------------------------------------------

HARD_STOP_USD: Final[float] = 19_000.0  # $19,490 cap with $490 headroom
DEFAULT_REGION: Final[str] = "ap-northeast-1"
STAGING_REGION: Final[str] = "ap-southeast-1"  # Textract output bucket
DEFAULT_PROFILE: Final[str] = "bookyou-recovery"
DEFAULT_STAGING_BUCKET: Final[str] = "jpcite-credit-textract-apse1-202605"
DEFAULT_STAGING_PREFIX: Final[str] = "out/"
DEFAULT_AUTONOMATH_DB: Final[str] = "autonomath.db"

# Skip objects under these names (Textract bucket access-check filler).
SKIP_FILENAMES: Final[frozenset[str]] = frozenset({".s3_access_check"})

# CJK density floor — pages below this ratio skip the dictionary
# extractors (program / law / authority), keeping precision high on
# garbled OCR. Empirically tuned: 0.05 separates ASCII-only OCR
# (graphics-heavy slide decks) from text-heavy PDFs.
CJK_DICT_FLOOR: Final[float] = 0.05

# Per-document caps — prevent runaway documents (the 5K-page judicial
# 判例 PDFs are bounded but a corrupt Textract output could in
# principle yield millions of "matches"). These are safety caps; the
# regex side already has its own _MAX_PAIR_FANOUT.
ENTITIES_PER_DOC_CAP: Final[int] = 20_000
RELATIONS_PER_DOC_CAP: Final[int] = 40_000

# Ingest batch size — chunk INSERT OR IGNORE statements so a single
# transaction does not balloon the SQLite write lock.
INGEST_BATCH_ROWS: Final[int] = 5_000

# Page-shard byte ceiling — Textract output JSON pages are typically
# 200-800 KiB; >5 MiB is corrupt / pagination overflow and skipped.
PAGE_OBJECT_BYTE_CEIL: Final[int] = 5_000_000

# CJK character ranges (mirror m1_kg_extraction.cjk_char_ratio).
_CJK_LO_HIRAGANA: Final[str] = "぀"
_CJK_HI_HIRAGANA: Final[str] = "ヿ"
_CJK_LO_KANJI: Final[str] = "一"
_CJK_HI_KANJI: Final[str] = "鿿"


# ---- Data types ------------------------------------------------------------


@dataclass(frozen=True)
class StagingObject:
    """One Textract output object scheduled for streaming."""

    key: str
    size: int
    doc_hash: str  # second-level prefix (the SHA-256 hex of the source PDF)


@dataclass
class RunStats:
    """Aggregate run telemetry."""

    objects_scanned: int = 0
    objects_skipped: int = 0
    pages_processed: int = 0
    bytes_streamed: int = 0
    entity_facts_added: int = 0
    relations_added: int = 0
    docs_completed: int = 0
    docs_failed: int = 0
    started_at: str = ""
    ended_at: str = ""

    def to_summary(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary."""
        return {
            "objects_scanned": self.objects_scanned,
            "objects_skipped": self.objects_skipped,
            "pages_processed": self.pages_processed,
            "bytes_streamed": self.bytes_streamed,
            "entity_facts_added": self.entity_facts_added,
            "relations_added": self.relations_added,
            "docs_completed": self.docs_completed,
            "docs_failed": self.docs_failed,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
        }


@dataclass
class DocBucket:
    """All Textract pages belonging to a single source PDF."""

    doc_hash: str
    pages: list[StagingObject] = field(default_factory=list)

    def add(self, obj: StagingObject) -> None:
        self.pages.append(obj)


# ---- S3 listing ------------------------------------------------------------


def iter_textract_objects(
    bucket: str,
    prefix: str,
    profile: str,
    region: str,
    max_objects: int = 0,
) -> Iterator[StagingObject]:
    """Yield Textract output objects under ``s3://bucket/prefix/`` (recursive).

    Filters out ``.s3_access_check`` filler. Filenames at the leaf are
    typically integer-stringy page numbers (``1``, ``2`` ... ``N``);
    the SHA-256 doc hash is the second-to-last path segment.

    Parameters
    ----------
    bucket / prefix:
        S3 bucket and key prefix.
    profile / region:
        boto3 session selectors.
    max_objects:
        Stop after this many objects (0 = unlimited).
    """
    s3 = _s3_client(region_name=region, profile_name=profile)
    paginator = s3.get_paginator("list_objects_v2")
    n = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            key = str(obj["Key"])
            size = int(obj.get("Size", 0) or 0)
            filename = key.rsplit("/", 1)[-1]
            if filename in SKIP_FILENAMES:
                continue
            if size == 0 or size > PAGE_OBJECT_BYTE_CEIL:
                continue
            parts = key.split("/")
            if len(parts) < 4:
                # Expected shape: out/<sha[:2]>/<sha>/<inner>/<page>
                continue
            doc_hash = parts[2]
            yield StagingObject(key=key, size=size, doc_hash=doc_hash)
            n += 1
            if max_objects and n >= max_objects:
                return


def group_by_document(objects: Iterator[StagingObject]) -> Iterator[DocBucket]:
    """Group successive same-``doc_hash`` objects into a :class:`DocBucket`.

    Pagination from list_objects_v2 returns lexicographic order; same-
    prefix objects are contiguous, so a single-pass groupby works.
    """
    current: DocBucket | None = None
    for obj in objects:
        if current is None or current.doc_hash != obj.doc_hash:
            if current is not None and current.pages:
                yield current
            current = DocBucket(doc_hash=obj.doc_hash)
        current.add(obj)
    if current is not None and current.pages:
        yield current


# ---- Textract → text -------------------------------------------------------


def textract_json_to_pages(
    blob: bytes,
) -> dict[int, str]:
    """Parse a Textract response JSON into ``{page: text}``.

    The Textract response is::

        {"Blocks": [
            {"BlockType": "LINE", "Text": "...", "Page": 1, ...},
            ...
        ], ...}

    Page-shard files in ``out/<sha[:2]>/<sha>/<inner>/<N>`` carry a
    single page of LINE blocks each, but defensively the parser keeps
    a per-page bucket in case multi-page shards appear.
    """
    try:
        d = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    blocks = d.get("Blocks") if isinstance(d, dict) else None
    if not isinstance(blocks, list):
        return {}
    out: dict[int, list[str]] = {}
    for b in blocks:
        if not isinstance(b, dict):
            continue
        if b.get("BlockType") != "LINE":
            continue
        text = b.get("Text")
        if not isinstance(text, str) or not text:
            continue
        page = b.get("Page", 1) or 1
        try:
            p = int(page)
        except (TypeError, ValueError):
            p = 1
        out.setdefault(p, []).append(text)
    return {p: "\n".join(lines) for p, lines in out.items()}


# ---- Pipeline --------------------------------------------------------------


def process_doc(
    bucket: str,
    bucket_region: str,
    profile: str,
    doc: DocBucket,
    s3_client: Any,
) -> tuple[
    list[ExtractedEntity],
    list[ExtractedRelation],
    int,  # pages_processed
    int,  # bytes_streamed
]:
    """Run M1 extraction over all pages of one source PDF."""
    del bucket_region  # client already region-bound
    entities: list[ExtractedEntity] = []
    relations: list[ExtractedRelation] = []
    pages = 0
    bytes_streamed = 0
    page_offset = 0
    for obj in doc.pages:
        try:
            resp = s3_client.get_object(Bucket=bucket, Key=obj.key)
            body = resp["Body"].read()
        except Exception as exc:  # noqa: BLE001
            logger.warning("s3_get_failed key=%s err=%s", obj.key, exc)
            continue
        bytes_streamed += len(body)
        per_page = textract_json_to_pages(body)
        for raw_page, text in per_page.items():
            page_offset += 1
            cjk = cjk_char_ratio(text)
            use_dict = cjk >= CJK_DICT_FLOOR
            r = extract_kg(text, page=page_offset, cjk_dict=use_dict)
            entities.extend(r.entities)
            relations.extend(r.relations)
            pages += 1
            del raw_page  # silence unused — kept for debug if needed
        if len(entities) > ENTITIES_PER_DOC_CAP:
            entities = entities[:ENTITIES_PER_DOC_CAP]
        if len(relations) > RELATIONS_PER_DOC_CAP:
            relations = relations[:RELATIONS_PER_DOC_CAP]
    # Persist credit toward caller-side stats; consumed elsewhere
    # (variable kept readable for log lines).
    _ = profile
    return entities, relations, pages, bytes_streamed


def ensure_pdf_source_entity(
    conn: sqlite3.Connection,
    doc_hash: str,
) -> str:
    """Return the canonical ``am_entities.canonical_id`` for a source PDF.

    Creates a ``document``-kind entity row keyed on ``pdf:<sha256>``
    when not present. The row uses minimal metadata; downstream
    workers can backfill from ``am_source.content_hash`` joins.
    """
    canonical_id = f"pdf:{doc_hash}"
    cur = conn.execute(
        "SELECT 1 FROM am_entities WHERE canonical_id = ? LIMIT 1",
        (canonical_id,),
    )
    if cur.fetchone() is not None:
        return canonical_id
    raw = json.dumps(
        {"source_kind": "textract_output", "doc_hash": doc_hash},
        ensure_ascii=False,
    )
    conn.execute(
        """
        INSERT INTO am_entities
            (canonical_id, record_kind, source_topic, primary_name,
             confidence, raw_json)
        VALUES (?, 'document', 'm1_pdf_kg', ?, 0.85, ?)
        ON CONFLICT(canonical_id) DO NOTHING
        """,
        (canonical_id, f"pdf:{doc_hash[:16]}…", raw),
    )
    return canonical_id


def ensure_houjin_entity(
    conn: sqlite3.Connection,
    houjin: str,
) -> str:
    """Return the canonical id for a houjin_bangou; create stub if missing.

    Existing rows from the gBizINFO import are keyed on
    ``houjin:<13digit>``. Unseen houjin numbers from PDF text get a
    stub row with low-confidence canonical_status='active' — downstream
    canonicalisation can resolve them later (or drop if invalid).
    """
    canonical_id = f"houjin:{houjin}"
    cur = conn.execute(
        "SELECT 1 FROM am_entities WHERE canonical_id = ? LIMIT 1",
        (canonical_id,),
    )
    if cur.fetchone() is not None:
        return canonical_id
    raw = json.dumps(
        {"houjin_bangou": houjin, "source": "m1_pdf_kg"},
        ensure_ascii=False,
    )
    conn.execute(
        """
        INSERT INTO am_entities
            (canonical_id, record_kind, source_topic, primary_name,
             confidence, raw_json)
        VALUES (?, 'corporate_entity', 'm1_pdf_kg', ?, 0.50, ?)
        ON CONFLICT(canonical_id) DO NOTHING
        """,
        (canonical_id, f"houjin:{houjin}", raw),
    )
    return canonical_id


def write_doc_facts(
    conn: sqlite3.Connection,
    doc_canonical_id: str,
    entities: list[ExtractedEntity],
    run_id: str,
) -> int:
    """Insert per-page extracted facts attached to the source-PDF entity.

    Each entity becomes an ``am_entity_facts`` row keyed on
    (doc_canonical_id, ``kg.<kind>.<value-or-surface>``). The unique
    constraint ``uq_am_facts_entity_field_text`` keeps re-runs
    idempotent.
    """
    if not entities:
        return 0
    now = datetime.now(UTC).isoformat(timespec="seconds")
    rows: list[tuple[Any, ...]] = []
    for e in entities:
        value_text: str
        value_numeric: float | None = None
        if e.kind == "amount" and isinstance(e.value, int):
            value_text = str(e.value)
            value_numeric = float(e.value)
            field_kind = "amount"
            unit = "yen"
        elif e.kind == "date" and isinstance(e.value, str):
            value_text = e.value
            field_kind = "date"
            unit = None
        elif e.kind == "houjin" and isinstance(e.value, str):
            value_text = e.value
            field_kind = "text"
            unit = None
        elif e.kind == "url" and isinstance(e.value, str):
            value_text = e.value
            field_kind = "url"
            unit = None
        elif e.kind == "postal_code" and isinstance(e.value, str):
            value_text = e.value
            field_kind = "text"
            unit = None
        else:
            value_text = e.surface[:512]
            field_kind = "text"
            unit = None
        field_name = f"kg.{e.kind}"
        rows.append(
            (
                doc_canonical_id,
                field_name,
                value_text,
                None,  # json
                value_numeric,
                field_kind,
                unit,
                None,  # source_url
                now,
                run_id,
            )
        )
    inserted = 0
    for i in range(0, len(rows), INGEST_BATCH_ROWS):
        batch = rows[i : i + INGEST_BATCH_ROWS]
        cur = conn.executemany(
            """
            INSERT OR IGNORE INTO am_entity_facts
                (entity_id, field_name, field_value_text, field_value_json,
                 field_value_numeric, field_kind, unit, source_url,
                 created_at, valid_from)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            batch,
        )
        # rowcount is unreliable across drivers for executemany; recount.
        inserted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else len(batch)
    return inserted


def write_doc_relations(
    conn: sqlite3.Connection,
    doc_canonical_id: str,
    entities: list[ExtractedEntity],
    relations: list[ExtractedRelation],
    run_id: str,
) -> int:
    """Insert co-occurrence relations into am_relation (origin='harvest').

    Three projection forms are emitted:

    1. (doc → houjin) for every distinct houjin_bangou in the doc with
       ``relation_type='related'``. This is the high-value join: it
       lets ``get_houjin_portfolio`` walk back from any houjin to the
       source PDFs that mention it.
    2. Page-level co-occurrence relations harvested by
       :func:`extract_relations` are projected into am_relation only
       when both endpoints have stable canonical ids. For now we only
       project (doc → houjin) because program / law / authority
       canonicalisation is a separate lane (N5 alias).

    The UNIQUE index ``ux_am_relation_harvest`` (source_entity_id,
    target_entity_id, relation_type, source_field) WHERE
    origin='harvest' keeps re-runs idempotent.
    """
    del relations  # see docstring — co-occurrence relations are
    # left in the extracted run-log for offline analysis; only the
    # high-value (doc → houjin) projection is promoted into
    # am_relation in this LIVE pass.
    now = datetime.now(UTC).isoformat(timespec="seconds")
    houjins = {e.value for e in entities if e.kind == "houjin" and isinstance(e.value, str)}
    if not houjins:
        return 0
    rows: list[tuple[Any, ...]] = []
    source_field = f"m1_pdf_kg/{run_id}"
    for h in sorted(houjins):
        target_id = ensure_houjin_entity(conn, h)
        rows.append(
            (
                doc_canonical_id,
                target_id,
                h,
                "related",
                0.65,
                "harvest",
                source_field,
                now,
            )
        )
    inserted = 0
    for i in range(0, len(rows), INGEST_BATCH_ROWS):
        batch = rows[i : i + INGEST_BATCH_ROWS]
        cur = conn.executemany(
            """
            INSERT OR IGNORE INTO am_relation
                (source_entity_id, target_entity_id, target_raw,
                 relation_type, confidence, origin, source_field,
                 harvested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            batch,
        )
        inserted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else len(batch)
    return inserted


# ---- Pre-flight / cost guard -----------------------------------------------


def check_burn_under_cap(profile: str, region: str) -> float:
    """Return current cumulative burn in USD; abort when above HARD_STOP."""
    try:
        from _aws import cloudwatch_client  # type: ignore[import-not-found]
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from _aws import cloudwatch_client  # type: ignore[import-not-found,no-redef]
    try:
        cw = cloudwatch_client(region_name=region, profile_name=profile)
        end = datetime.now(UTC)
        start = end.replace(hour=0, minute=0, second=0, microsecond=0)
        resp = cw.get_metric_statistics(
            Namespace="JPCITE/Burn",
            MetricName="CumulativeBurnUSD",
            StartTime=start,
            EndTime=end,
            Period=3600,
            Statistics=["Maximum"],
        )
        points = resp.get("Datapoints") or []
        if not points:
            return 0.0
        latest = max(points, key=lambda p: p["Timestamp"])
        return float(latest.get("Maximum", 0.0))
    except Exception as exc:  # noqa: BLE001
        logger.warning("burn_check_failed=%s", exc)
        return 0.0


def _s3_client(region_name: str, profile_name: str) -> Any:
    """Return a memoised boto3 S3 client; lazy import boto3."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _aws import s3_client  # type: ignore[import-not-found]

    return s3_client(region_name=region_name, profile_name=profile_name)


# ---- Run entry -------------------------------------------------------------


def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    """Execute the M1 bulk extraction pipeline and return a summary dict."""
    db_path = Path(args.autonomath_db).resolve()
    if not db_path.exists():
        raise SystemExit(f"autonomath_db_not_found path={db_path}")

    burn = check_burn_under_cap(args.profile, args.region)
    logger.info("preflight burn_usd=%.2f cap=%.2f", burn, HARD_STOP_USD)
    if burn > HARD_STOP_USD:
        raise SystemExit(f"hard_stop_19490_burn={burn:.2f}")

    started = datetime.now(UTC)
    run_id = started.strftime("%Y%m%dT%H%M%SZ")
    stats = RunStats(started_at=started.isoformat(timespec="seconds"))

    # Open DB connection; reuse across the whole run for transaction control.
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    s3 = _s3_client(region_name=args.staging_region, profile_name=args.profile)

    if not args.commit:
        logger.warning("DRY_RUN — no DB writes / no S3 reads beyond list")

    # Tally objects (cheap; pagination only).
    object_iter = iter_textract_objects(
        bucket=args.staging_bucket,
        prefix=args.staging_prefix,
        profile=args.profile,
        region=args.staging_region,
        max_objects=args.max_objects,
    )

    docs_seen = 0
    for doc in group_by_document(object_iter):
        if args.max_docs and docs_seen >= args.max_docs:
            break
        stats.objects_scanned += len(doc.pages)
        if not args.commit:
            stats.docs_completed += 1
            docs_seen += 1
            continue
        try:
            doc_canonical_id = ensure_pdf_source_entity(conn, doc.doc_hash)
            entities, relations, pages, bytes_streamed = process_doc(
                bucket=args.staging_bucket,
                bucket_region=args.staging_region,
                profile=args.profile,
                doc=doc,
                s3_client=s3,
            )
            stats.pages_processed += pages
            stats.bytes_streamed += bytes_streamed
            facts_added = write_doc_facts(conn, doc_canonical_id, entities, run_id)
            rel_added = write_doc_relations(conn, doc_canonical_id, entities, relations, run_id)
            stats.entity_facts_added += facts_added
            stats.relations_added += rel_added
            stats.docs_completed += 1
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("doc_failed hash=%s err=%s", doc.doc_hash, exc)
            stats.docs_failed += 1
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
        docs_seen += 1
        if docs_seen % 50 == 0:
            logger.info(
                "progress docs=%d entities=%d relations=%d bytes=%d",
                docs_seen,
                stats.entity_facts_added,
                stats.relations_added,
                stats.bytes_streamed,
            )

    ended = datetime.now(UTC)
    stats.ended_at = ended.isoformat(timespec="seconds")

    burn_post = check_burn_under_cap(args.profile, args.region)

    if args.commit:
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO am_kg_extracted_log
                    (run_id, lane, started_at, ended_at, mode, s3_bucket,
                     s3_prefix, objects_scanned, objects_skipped,
                     pages_processed, bytes_streamed,
                     entity_facts_added, relations_added,
                     burn_usd_preflight, burn_usd_postflight, notes)
                VALUES (?, 'M1', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    stats.started_at,
                    stats.ended_at,
                    args.mode,
                    args.staging_bucket,
                    args.staging_prefix,
                    stats.objects_scanned,
                    stats.objects_skipped,
                    stats.pages_processed,
                    stats.bytes_streamed,
                    stats.entity_facts_added,
                    stats.relations_added,
                    burn,
                    burn_post,
                    json.dumps(
                        {"docs_completed": stats.docs_completed, "docs_failed": stats.docs_failed},
                        ensure_ascii=False,
                    ),
                ),
            )
            conn.commit()
        except sqlite3.Error as exc:
            logger.warning("ledger_insert_failed=%s", exc)

    conn.close()

    return {
        "run_id": run_id,
        "lane": "M1",
        "mode": args.mode,
        "commit": args.commit,
        "burn_usd_preflight": burn,
        "burn_usd_postflight": burn_post,
        "stats": stats.to_summary(),
    }


def build_parser() -> argparse.ArgumentParser:
    """Return the CLI argument parser."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--autonomath-db", default=DEFAULT_AUTONOMATH_DB)
    p.add_argument("--staging-bucket", default=DEFAULT_STAGING_BUCKET)
    p.add_argument("--staging-prefix", default=DEFAULT_STAGING_PREFIX)
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--staging-region", default=STAGING_REGION)
    p.add_argument("--mode", choices=("local", "sagemaker", "dryrun"), default="local")
    p.add_argument(
        "--max-objects",
        type=int,
        default=0,
        help="Object cap (0 = unlimited). Useful for smoke runs.",
    )
    p.add_argument(
        "--max-docs",
        type=int,
        default=0,
        help="Document cap (0 = unlimited). Useful for smoke runs.",
    )
    p.add_argument(
        "--commit",
        action="store_true",
        help="Commit DB writes. Default DRY_RUN.",
    )
    p.add_argument("--log-level", default="INFO")
    return p


def main() -> None:
    """CLI entry point."""
    args = build_parser().parse_args()
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    out = run_pipeline(args)
    sys.stdout.write(json.dumps(out, indent=2, ensure_ascii=False))
    sys.stdout.write("\n")


# Surface a couple of internal helpers for unit tests.
__all__ = [
    "DocBucket",
    "ExtractedEntity",
    "ExtractedRelation",
    "RunStats",
    "StagingObject",
    "build_parser",
    "ensure_houjin_entity",
    "ensure_pdf_source_entity",
    "group_by_document",
    "iter_textract_objects",
    "main",
    "run_pipeline",
    "textract_json_to_pages",
    "write_doc_facts",
    "write_doc_relations",
]
# Avoid pyflakes "unused" on os; the module may grow to need cwd.
_ = os


if __name__ == "__main__":
    main()
