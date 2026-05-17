"""CC4 Lambda — Textract OCR → KG entity/relation extract.

Triggered by ``jpcite-pdf-textract-completion`` SNS (Textract job
completion event). For each completed Textract job:

    1. Loads the OCR result from S3 (``jpcite-credit-textract-apse1-202605/out/...``).
    2. Joins text blocks into a paragraph stream.
    3. Runs spaCy ``ja_core_news_lg`` NER on each paragraph (no LLM).
    4. Heuristic relation extraction (entity-pair within sentence
       boundary + verb-gov edge). Pure rule-based; no LLM.
    5. Inserts ``am_entity_facts`` + ``am_relation`` rows; idempotent
       per ``content_hash`` (re-runs are no-ops).
    6. Updates ``am_pdf_watch_log``: kg_extract_status='completed',
       kg_entity_count, kg_relation_count, ingested_at.

Idempotency
-----------
The content_hash + watch_id pair is the dedup key. Re-trigger inserts
zero new facts (UNIQUE constraint on (content_hash, entity_text, entity_label)).

Constraints
-----------
- NO LLM API. spaCy is a deterministic NER model.
- mypy strict; ruff 0.
- Cost: spaCy CPU inference is free; only S3 GET + DynamoDB-style
  writes are billed. Estimated $0.001 / PDF.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DEFAULT_STAGE_BUCKET: Final[str] = os.environ.get(
    "JPCITE_PDF_WATCH_STAGE_BUCKET", "jpcite-credit-textract-apse1-202605"
)
DEFAULT_TEXTRACT_REGION: Final[str] = os.environ.get("JPCITE_TEXTRACT_REGION", "ap-southeast-1")
DEFAULT_DB_PATH: Final[str] = os.environ.get("JPCITE_AUTONOMATH_DB", "/var/task/autonomath.db")
DEFAULT_SPACY_MODEL: Final[str] = os.environ.get("JPCITE_SPACY_MODEL", "ja_core_news_lg")
DEFAULT_MAX_TEXT_BYTES: Final[int] = 5_000_000  # 5 MB hard cap

# Light-weight verb stem set used for relation extraction when sudachi /
# spaCy is unavailable in the Lambda runtime (test environments).
_VERB_HINTS: Final[tuple[str, ...]] = (
    "認め",
    "定め",
    "公表",
    "規定",
    "適用",
    "施行",
    "改正",
    "新設",
    "廃止",
    "創設",
    "対象",
    "支給",
)


def _enabled() -> bool:
    return os.environ.get("JPCITE_PDF_WATCH_ENABLED", "false").lower() == "true"


# ---------------------------------------------------------------------------
# Textract result parser
# ---------------------------------------------------------------------------


def _parse_textract_blocks(blocks: list[dict[str, Any]]) -> list[str]:
    """Join LINE blocks into a paragraph stream."""
    lines: list[str] = []
    for b in blocks:
        if b.get("BlockType") != "LINE":
            continue
        text = b.get("Text") or ""
        if text.strip():
            lines.append(text.strip())
    # Coalesce consecutive lines into paragraphs separated by blank lines.
    paragraphs: list[str] = []
    buf: list[str] = []
    for ln in lines:
        if not ln:
            if buf:
                paragraphs.append("".join(buf))
                buf = []
            continue
        buf.append(ln)
        if ln.endswith("。") or ln.endswith("."):
            paragraphs.append("".join(buf))
            buf = []
    if buf:
        paragraphs.append("".join(buf))
    return paragraphs


# ---------------------------------------------------------------------------
# spaCy NER (with regex fallback)
# ---------------------------------------------------------------------------

_spacy_nlp: Any | None = None


def _load_spacy() -> Any | None:
    """Lazy-load spaCy model. Returns None if unavailable."""
    global _spacy_nlp
    if _spacy_nlp is not None:
        return _spacy_nlp
    try:
        import spacy  # type: ignore[import-not-found,unused-ignore]
    except ImportError:
        return None
    try:
        _spacy_nlp = spacy.load(DEFAULT_SPACY_MODEL)
    except Exception as e:  # noqa: BLE001
        logger.warning("spacy_load_failed model=%s err=%s", DEFAULT_SPACY_MODEL, e)
        return None
    return _spacy_nlp


# Regex fallback patterns — narrow, deterministic, no false-positive
# explosions. Match Japanese law/program/yen/date entities.
_REGEX_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("MONEY", re.compile(r"\d{1,3}(?:,\d{3})*(?:円|万円|億円)")),
    ("DATE", re.compile(r"令和\s*\d+年\s*\d+月\s*\d+日")),
    ("DATE", re.compile(r"平成\s*\d+年\s*\d+月\s*\d+日")),
    ("DATE", re.compile(r"\d{4}年\s*\d+月\s*\d+日")),
    ("PROGRAM", re.compile(r"[一-鿿]+(?:補助金|助成金|交付金|給付金)")),
    ("LAW", re.compile(r"[一-鿿]+(?:法|令|規則|通達|告示)")),
    ("PERCENT", re.compile(r"\d+(?:\.\d+)?\s*%")),
)


def _extract_entities(text: str) -> list[tuple[str, str]]:
    """Return ``(entity_label, entity_text)`` pairs found in ``text``.

    Tries spaCy first; falls back to regex when unavailable. Both paths
    are LLM-free.
    """
    out: list[tuple[str, str]] = []
    nlp = _load_spacy()
    if nlp is not None:
        try:
            doc = nlp(text)
            for ent in doc.ents:
                out.append((ent.label_, ent.text))
            if out:
                return out
        except Exception as e:  # noqa: BLE001
            logger.warning("spacy_pipeline_failed err=%s", e)
    # Regex fallback
    seen: set[tuple[str, str]] = set()
    for label, pat in _REGEX_PATTERNS:
        for m in pat.finditer(text):
            key = (label, m.group(0))
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out


def _extract_relations(text: str, entities: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
    """Return ``(subject, verb, object)`` triples.

    Pure rule-based: pair entities within the same sentence when a
    ``_VERB_HINTS`` token sits between them.
    """
    relations: list[tuple[str, str, str]] = []
    sentences = re.split(r"(?<=[。．\.])", text)
    for sent in sentences:
        ents_in_sent = [e for e in entities if e[1] in sent]
        if len(ents_in_sent) < 2:
            continue
        for verb in _VERB_HINTS:
            if verb not in sent:
                continue
            subj = ents_in_sent[0][1]
            obj = ents_in_sent[-1][1]
            if subj != obj:
                relations.append((subj, verb, obj))
            break
    return relations


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _ensure_ner_tables(conn: sqlite3.Connection) -> None:
    """Idempotent CREATE for am_entity_facts + am_relation (KG sink)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS am_entity_facts (
            fact_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            content_hash TEXT NOT NULL,
            watch_id     INTEGER,
            entity_label TEXT NOT NULL,
            entity_text  TEXT NOT NULL,
            source_url   TEXT,
            extracted_at TEXT NOT NULL DEFAULT
                          (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            UNIQUE (content_hash, entity_label, entity_text)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS am_relation (
            relation_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            content_hash TEXT NOT NULL,
            watch_id     INTEGER,
            subject      TEXT NOT NULL,
            verb         TEXT NOT NULL,
            object       TEXT NOT NULL,
            source_url   TEXT,
            extracted_at TEXT NOT NULL DEFAULT
                          (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            UNIQUE (content_hash, subject, verb, object)
        )
        """
    )


def _insert_facts(
    conn: sqlite3.Connection,
    *,
    content_hash: str,
    watch_id: int,
    source_url: str,
    entities: Iterable[tuple[str, str]],
    relations: Iterable[tuple[str, str, str]],
) -> tuple[int, int]:
    """Insert facts + relations idempotently. Returns ``(entity_count, relation_count)``."""
    entity_count = 0
    for label, text in entities:
        try:
            conn.execute(
                """
                INSERT INTO am_entity_facts
                    (content_hash, watch_id, entity_label, entity_text, source_url)
                VALUES (?, ?, ?, ?, ?)
                """,
                (content_hash, watch_id, label, text, source_url),
            )
            entity_count += 1
        except sqlite3.IntegrityError:
            pass  # dedup hit
    relation_count = 0
    for subj, verb, obj in relations:
        try:
            conn.execute(
                """
                INSERT INTO am_relation
                    (content_hash, watch_id, subject, verb, object, source_url)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (content_hash, watch_id, subj, verb, obj, source_url),
            )
            relation_count += 1
        except sqlite3.IntegrityError:
            pass
    return entity_count, relation_count


def _flip_watch_log(
    conn: sqlite3.Connection,
    *,
    watch_id: int,
    entity_count: int,
    relation_count: int,
    status: str = "completed",
    last_error: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE am_pdf_watch_log
           SET kg_extract_status  = ?,
               kg_entity_count    = ?,
               kg_relation_count  = ?,
               ingested_at        = strftime('%Y-%m-%dT%H:%M:%SZ','now'),
               last_error         = ?,
               updated_at         = strftime('%Y-%m-%dT%H:%M:%SZ','now')
         WHERE watch_id = ?
        """,
        (status, entity_count, relation_count, last_error, watch_id),
    )


# ---------------------------------------------------------------------------
# Lambda entry
# ---------------------------------------------------------------------------


def _process_completion(
    *,
    watch_id: int,
    content_hash: str,
    source_url: str,
    textract_blocks: list[dict[str, Any]],
    db_path: str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    paragraphs = _parse_textract_blocks(textract_blocks)
    text = "\n".join(paragraphs)[:DEFAULT_MAX_TEXT_BYTES]
    entities = _extract_entities(text)
    relations = _extract_relations(text, entities)

    conn = sqlite3.connect(db_path, timeout=5.0)
    try:
        _ensure_ner_tables(conn)
        ec, rc = _insert_facts(
            conn,
            content_hash=content_hash,
            watch_id=watch_id,
            source_url=source_url,
            entities=entities,
            relations=relations,
        )
        _flip_watch_log(
            conn,
            watch_id=watch_id,
            entity_count=ec,
            relation_count=rc,
            status="completed",
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "watch_id": watch_id,
        "content_hash": content_hash,
        "entities_inserted": ec,
        "relations_inserted": rc,
        "paragraphs_parsed": len(paragraphs),
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """SNS-triggered Lambda entry.

    The SNS message body is the Textract completion envelope. Standard
    Textract notification payload contains ``JobId`` + ``Status``; we
    fetch the actual blocks via ``GetDocumentAnalysis``.
    """
    boto3: Any
    try:
        import boto3  # type: ignore[import-not-found,unused-ignore,no-redef]
    except ImportError:
        boto3 = None
    commit_mode = _enabled() and boto3 is not None

    summaries: list[dict[str, Any]] = []
    for rec in event.get("Records", []):
        try:
            sns_body = rec.get("Sns", {}).get("Message", "{}")
            envelope = json.loads(sns_body) if isinstance(sns_body, str) else sns_body
            job_id = envelope.get("JobId", "")
            status = envelope.get("Status", "")
            job_tag = envelope.get("JobTag", "")
            if not job_id or status != "SUCCEEDED":
                summaries.append({"mode": "skipped", "job_id": job_id, "status": status})
                continue
            try:
                watch_id = int(job_tag.split("-")[-1])
            except ValueError:
                summaries.append({"mode": "skipped", "reason": "bad_job_tag", "job_tag": job_tag})
                continue
            if not commit_mode:
                summaries.append({"mode": "dry_run", "job_id": job_id, "watch_id": watch_id})
                continue
            assert boto3 is not None
            textract = boto3.client("textract", region_name=DEFAULT_TEXTRACT_REGION)
            blocks: list[dict[str, Any]] = []
            next_token: str | None = None
            while True:
                kwargs: dict[str, Any] = {"JobId": job_id}
                if next_token:
                    kwargs["NextToken"] = next_token
                resp = textract.get_document_analysis(**kwargs)
                blocks.extend(resp.get("Blocks", []))
                next_token = resp.get("NextToken")
                if not next_token:
                    break
            # The SQS-submit step set content_hash from the JobTag's
            # corresponding DB row; re-read the DB to get it.
            conn = sqlite3.connect(DEFAULT_DB_PATH, timeout=5.0)
            try:
                row = conn.execute(
                    "SELECT content_hash, source_url   FROM am_pdf_watch_log WHERE watch_id = ?",
                    (watch_id,),
                ).fetchone()
            finally:
                conn.close()
            if not row:
                summaries.append({"mode": "skipped", "reason": "watch_id_not_found"})
                continue
            content_hash, source_url = row[0], row[1]
            summaries.append(
                _process_completion(
                    watch_id=watch_id,
                    content_hash=content_hash,
                    source_url=source_url,
                    textract_blocks=blocks,
                )
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("kg_record_failed err=%s", e)
            summaries.append({"mode": "failed", "error": str(e)})
    return {
        "tick_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "processed": len(summaries),
        "mode": "committed" if commit_mode else "dry_run",
        "summaries": summaries,
    }
