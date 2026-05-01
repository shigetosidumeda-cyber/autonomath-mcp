#!/usr/bin/env python3
"""Bulk run B6 PDF fact extractor over `programs.source_url` PDFs.

Read-only against `data/jpintel.db`. Fetches each distinct PDF URL with the
shared polite HTTP client (UA `jpcite-research/1.0`, robots.txt enforced,
1 req/sec/host, 10 MB body cap), extracts text via pdfplumber, and feeds the
text to the existing B6 `parse_program_facts` driver. Emits one CSV row per
program (program_id, source_url, deadline, subsidy_rate, required_docs,
contact, max_amount, content_hash, confidence).

The CSV is the only output. The DB is never written. Existing parser /
test surface is not modified.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import io
import json
import logging
import sqlite3
import sys
import time
import urllib.parse
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.http import (  # noqa: E402
    PDF_MAX_BYTES,
    HttpClient,
)

PARSER_PATH = REPO_ROOT / "scripts" / "cron" / "extract_program_facts.py"
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_OUTPUT = (
    REPO_ROOT / "analysis_wave18" / "pdf_extraction_batch_2026-05-01.csv"
)
USER_AGENT = "jpcite-research/1.0 (+https://jpcite.com/about)"

_LOG = logging.getLogger("jpcite.pdf_batch")


def _load_parser() -> Any:
    spec = importlib.util.spec_from_file_location(
        "extract_program_facts_runtime", PARSER_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load parser spec at {PARSER_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def _select_pdf_programs(
    conn: sqlite3.Connection, limit: int | None
) -> list[sqlite3.Row]:
    sql = (
        "SELECT unified_id, source_url FROM programs "
        "WHERE source_url LIKE '%.pdf' "
        "ORDER BY unified_id"
    )
    if limit is not None and limit > 0:
        sql += f" LIMIT {int(limit)}"
    return list(conn.execute(sql))


def _extract_pdf_text(body: bytes) -> str:
    import pdfplumber  # local import: heavy dependency

    out: list[str] = []
    with pdfplumber.open(io.BytesIO(body)) as pdf:
        for page in pdf.pages:
            try:
                text = page.extract_text() or ""
            except Exception as exc:  # noqa: BLE001 - defensive: pdfplumber can raise broadly
                _LOG.debug("page extract failed: %s", exc)
                text = ""
            if text:
                out.append(text)
    return "\n".join(out)


_CSV_FIELDS = (
    "program_id",
    "source_url",
    "fetch_status",
    "fetch_skip_reason",
    "deadline",
    "subsidy_rate",
    "required_docs",
    "contact",
    "max_amount",
    "content_hash",
    "confidence",
    "fact_count",
    "error",
)


def _domain_of(url: str) -> str:
    return urllib.parse.urlparse(url).netloc


def _flatten(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _process_one(
    parser_mod: Any,
    http: HttpClient,
    program_id: str,
    source_url: str,
    *,
    cache_dir: Path | None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "program_id": program_id,
        "source_url": source_url,
        "fetch_status": "",
        "fetch_skip_reason": "",
        "deadline": "",
        "subsidy_rate": "",
        "required_docs": "",
        "contact": "",
        "max_amount": "",
        "content_hash": "",
        "confidence": "",
        "fact_count": 0,
        "error": "",
    }

    body: bytes | None = None
    cache_path: Path | None = None
    if cache_dir is not None:
        safe = urllib.parse.quote(source_url, safe="")[:200]
        cache_path = cache_dir / f"{safe}.pdf"
        if cache_path.exists():
            body = cache_path.read_bytes()
            row["fetch_status"] = "cache"

    if body is None:
        result = http.get(source_url, max_bytes=PDF_MAX_BYTES)
        row["fetch_status"] = str(result.status)
        if not result.ok:
            row["fetch_skip_reason"] = result.skip_reason or f"http_{result.status}"
            return row
        # Some sites return HTTP 200 with an HTML 404/landing page after a
        # redirect chain. Skip those before pdfplumber gets confused.
        ct = result.headers.get("content-type", "").lower()
        head = result.body[:4]
        if head != b"%PDF" and "pdf" not in ct:
            row["fetch_skip_reason"] = f"non_pdf_response:{ct[:60]}"
            return row
        body = result.body
        if cache_path is not None:
            try:
                cache_path.write_bytes(body)
            except OSError as exc:
                _LOG.debug("cache write failed: %s", exc)

    try:
        text = _extract_pdf_text(body)
    except Exception as exc:  # noqa: BLE001 - defensive: pdfplumber + PDF parsing
        row["error"] = f"pdf_parse_error: {exc.__class__.__name__}: {exc}"[:500]
        return row

    if not text.strip():
        row["error"] = "no_text_extracted"
        return row

    try:
        facts = parser_mod.parse_program_facts(
            text,
            source_url=source_url,
            source_domain=_domain_of(source_url),
        )
    except Exception as exc:  # noqa: BLE001 - defensive: regex profile may raise
        row["error"] = f"fact_extract_error: {exc.__class__.__name__}: {exc}"[:500]
        return row

    facts_dict = asdict(facts)
    row["deadline"] = _flatten(facts_dict.get("deadline"))
    row["subsidy_rate"] = _flatten(facts_dict.get("subsidy_rate"))
    row["required_docs"] = _flatten(facts_dict.get("required_docs"))
    row["contact"] = _flatten(facts_dict.get("contact"))
    row["max_amount"] = _flatten(facts_dict.get("max_amount"))
    row["content_hash"] = facts_dict.get("content_hash", "")
    row["confidence"] = facts_dict.get("confidence", "")

    fact_count = sum(
        1
        for key in ("deadline", "subsidy_rate", "required_docs", "contact", "max_amount")
        if facts_dict.get(key)
    )
    row["fact_count"] = fact_count
    return row


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB, help="path to jpintel.db (read-only)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="CSV output path",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="max number of programs to process (default: all)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("/tmp/jpcite_pdf_cache"),
        help="local PDF cache (preferred over network when present)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="disable filesystem PDF cache",
    )
    parser.add_argument(
        "--per-host-delay",
        type=float,
        default=1.0,
        help="seconds between requests to the same host",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=25,
        help="emit a progress line every N programs",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser_mod = _load_parser()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    cache_dir: Path | None = None
    if not args.no_cache and args.cache_dir is not None:
        cache_dir = args.cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    started_iso = datetime.now(UTC).isoformat()

    counters = {
        "total": 0,
        "ok": 0,
        "fetch_skipped": 0,
        "no_text": 0,
        "zero_facts": 0,
        "parse_error": 0,
    }

    with _connect_readonly(args.db) as conn:
        rows = _select_pdf_programs(conn, args.limit)

    _LOG.info(
        "selected programs: %d (limit=%s, cache=%s, output=%s)",
        len(rows),
        args.limit,
        cache_dir,
        args.output,
    )

    with (
        args.output.open("w", encoding="utf-8", newline="") as fh,
        HttpClient(
            user_agent=USER_AGENT,
            per_host_delay_sec=args.per_host_delay,
        ) as http,
    ):
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        writer.writeheader()

        for index, db_row in enumerate(rows, start=1):
            program_id = db_row["unified_id"]
            source_url = db_row["source_url"]
            counters["total"] += 1
            try:
                out = _process_one(
                    parser_mod,
                    http,
                    program_id,
                    source_url,
                    cache_dir=cache_dir,
                )
            except Exception as exc:  # noqa: BLE001 - row-level isolation
                _LOG.exception("unhandled row failure %s", program_id)
                out = {
                    "program_id": program_id,
                    "source_url": source_url,
                    "fetch_status": "",
                    "fetch_skip_reason": "",
                    "deadline": "",
                    "subsidy_rate": "",
                    "required_docs": "",
                    "contact": "",
                    "max_amount": "",
                    "content_hash": "",
                    "confidence": "",
                    "fact_count": 0,
                    "error": f"unhandled: {exc.__class__.__name__}: {exc}"[:500],
                }

            writer.writerow(out)
            fh.flush()

            if out.get("fetch_skip_reason") or (
                out.get("fetch_status") not in ("200", "cache", "")
            ):
                counters["fetch_skipped"] += 1
            elif out.get("error"):
                if out["error"] == "no_text_extracted":
                    counters["no_text"] += 1
                else:
                    counters["parse_error"] += 1
            elif int(out.get("fact_count") or 0) == 0:
                counters["zero_facts"] += 1
            else:
                counters["ok"] += 1

            if args.progress_every and index % args.progress_every == 0:
                elapsed = time.monotonic() - started
                rate = index / elapsed if elapsed > 0 else 0.0
                _LOG.info(
                    "progress %d/%d ok=%d skip=%d zero=%d notext=%d err=%d %.2f rps",
                    index,
                    len(rows),
                    counters["ok"],
                    counters["fetch_skipped"],
                    counters["zero_facts"],
                    counters["no_text"],
                    counters["parse_error"],
                    rate,
                )

    elapsed = time.monotonic() - started
    finished_iso = datetime.now(UTC).isoformat()
    _LOG.info(
        "done started=%s finished=%s elapsed_sec=%.1f counters=%s output=%s",
        started_iso,
        finished_iso,
        elapsed,
        counters,
        args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
