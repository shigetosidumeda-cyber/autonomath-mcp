#!/usr/bin/env python3
"""ingest_inbox_tsutatsu.py — 国税庁 通達 inbox -> nta_tsutatsu_index.

Walks `tools/offline/_inbox/nta_tsutatsu_full/*.jsonl`, splits each
row's `extracted_text` into individual treatise articles by detecting
the canonical "(キャプション) N-N-N 本文..." pattern (with full-width
minus U+FF0D), and INSERT OR REPLACEs each article into
`nta_tsutatsu_index` using `code` as the unique key.

URL prefix => law_canonical_id mapping
--------------------------------------
- /law/tsutatsu/kihon/hojin/  -> law:hojin-zei-tsutatsu  (法基通-)
- /law/tsutatsu/kihon/shotoku/-> law:shotoku-zei-tsutatsu (所基通-)
- /law/tsutatsu/kihon/shohi/  -> law:shohi-zei-tsutatsu  (消基通-)
Other prefixes are skipped (logged + counted) so we never write a row
with an unknown law_canonical_id (the table requires NOT NULL FK).

Dedupe
------
- Per row: `code` is UNIQUE on the table; INSERT OR REPLACE handles it.
- Per file: tracked via `content_hash` to avoid double-parsing the same
  source URL across agent shards in the same run.

Archival
--------
After a successful run, processed jsonl files are moved to
`tools/offline/_inbox/_archived/nta_tsutatsu_full/<basename>`.

NO LLM, NO Anthropic API. Pure stdlib + sqlite3.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

_LOG = logging.getLogger("ingest_inbox_tsutatsu")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "autonomath.db"
INBOX = REPO_ROOT / "tools" / "offline" / "_inbox"
SOURCE_DIR = INBOX / "nta_tsutatsu_full"
ARCHIVED_DIR = INBOX / "_archived" / "nta_tsutatsu_full"

# URL path prefix -> (law_canonical_id, code_prefix)
PREFIX_MAP: list[tuple[str, str, str]] = [
    ("/law/tsutatsu/kihon/hojin/", "law:hojin-zei-tsutatsu", "法基通"),
    ("/law/tsutatsu/kihon/shotoku/", "law:shotoku-zei-tsutatsu", "所基通"),
    ("/law/tsutatsu/kihon/shohi/", "law:shohi-zei-tsutatsu", "消基通"),
    ("/law/tsutatsu/kihon/sozoku/", "law:sozoku-zei-tsutatsu", "相基通"),
    ("/law/tsutatsu/kihon/inshi/", "law:inshi-zei-tsutatsu", "印基通"),
]

# Article code: e.g. "1－1－1", "9－2", "13－2－3" with U+FF0D / U+2212 / hyphen
SEP_CHARS = "−－‐‑-"
CODE_RE = re.compile(rf"(\d+(?:[{SEP_CHARS}]\d+){{1,4}})")
# Capture (title in parens) followed by code body
ARTICLE_RE = re.compile(
    rf"[（(]([^（）()]{{1,80}})[）)]\s*" rf"(\d+(?:[{SEP_CHARS}]\d+){{1,4}})\s*"
)


def normalize_code(raw: str) -> str:
    """Normalize separator chars in a code to ASCII '-'."""
    out = raw
    for ch in SEP_CHARS:
        out = out.replace(ch, "-")
    return out


def resolve_mapping(url: str) -> tuple[str, str] | None:
    """Return (law_canonical_id, code_prefix) for URL or None."""
    for path_prefix, canon, code_prefix in PREFIX_MAP:
        if path_prefix in url:
            return canon, code_prefix
    return None


def split_articles(text: str) -> list[tuple[str, str, str]]:
    """Yield (title, raw_code, body) tuples from one tsutatsu page text."""
    matches = list(ARTICLE_RE.finditer(text))
    if not matches:
        return []
    out: list[tuple[str, str, str]] = []
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        raw_code = m.group(2)
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        body = re.sub(r"[\s　]+", " ", body)
        if body:
            out.append((title, raw_code, body))
    return out


def upsert_tsutatsu(
    con: sqlite3.Connection,
    *,
    code: str,
    law_canonical_id: str,
    article_number: str,
    title: str,
    body_excerpt: str,
    source_url: str,
    refreshed_at: str,
) -> None:
    con.execute(
        """
        INSERT INTO nta_tsutatsu_index (
            code, law_canonical_id, article_number, title,
            body_excerpt, source_url, refreshed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            law_canonical_id = excluded.law_canonical_id,
            article_number   = excluded.article_number,
            title            = excluded.title,
            body_excerpt     = excluded.body_excerpt,
            source_url       = excluded.source_url,
            refreshed_at     = excluded.refreshed_at
        """,
        (
            code,
            law_canonical_id,
            article_number,
            title,
            body_excerpt[:500],
            source_url,
            refreshed_at,
        ),
    )


def list_inbox_files() -> list[Path]:
    if not SOURCE_DIR.exists():
        return []
    return sorted(p for p in SOURCE_DIR.glob("*.jsonl") if p.is_file())


def archive_file(src: Path) -> None:
    ARCHIVED_DIR.mkdir(parents=True, exist_ok=True)
    dst = ARCHIVED_DIR / src.name
    if dst.exists():
        dst = ARCHIVED_DIR / f"{src.stem}.{int(time.time())}.jsonl"
    shutil.move(str(src), str(dst))


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest nta tsutatsu inbox")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit-files", type=int, default=0)
    parser.add_argument("--no-archive", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    files = list_inbox_files()
    if args.limit_files:
        files = files[: args.limit_files]
    if not files:
        print("[ingest_inbox_tsutatsu] no inbox files; nothing to do")
        return 0

    con = sqlite3.connect(args.db, timeout=300)
    con.execute("PRAGMA busy_timeout = 300000")
    initial = con.execute("SELECT COUNT(*) FROM nta_tsutatsu_index").fetchone()[0]
    print(f"[ingest_inbox_tsutatsu] db={args.db} files={len(files)}")

    seen_hashes: set[str] = set()
    seen_codes: set[str] = set()
    archived: list[Path] = []
    inserted = 0
    skipped_no_mapping = 0
    skipped_dup_hash = 0
    skipped_dup_code = 0
    skipped_bad = 0

    t0 = time.time()
    refreshed_at = datetime.now(UTC).isoformat()
    for fp in files:
        file_inserted = 0
        file_bad = 0
        try:
            con.execute("BEGIN IMMEDIATE")
            with fp.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        file_bad += 1
                        continue

                    chash = row.get("content_hash") or ""
                    url = row.get("url") or ""
                    text = row.get("extracted_text") or ""
                    if not url or not text:
                        file_bad += 1
                        continue
                    if chash and chash in seen_hashes:
                        skipped_dup_hash += 1
                        continue
                    if chash:
                        seen_hashes.add(chash)

                    mapping = resolve_mapping(url)
                    if not mapping:
                        skipped_no_mapping += 1
                        _LOG.debug("no canonical mapping for url=%s", url)
                        continue
                    canon, code_prefix = mapping

                    for title, raw_code, body in split_articles(text):
                        article_number = normalize_code(raw_code)
                        code = f"{code_prefix}-{article_number}"
                        if code in seen_codes:
                            skipped_dup_code += 1
                            continue
                        seen_codes.add(code)
                        if not args.dry_run:
                            try:
                                upsert_tsutatsu(
                                    con,
                                    code=code,
                                    law_canonical_id=canon,
                                    article_number=article_number,
                                    title=title,
                                    body_excerpt=body,
                                    source_url=url,
                                    refreshed_at=refreshed_at,
                                )
                            except sqlite3.Error as exc:
                                _LOG.warning("upsert fail %s: %s", code, exc)
                                file_bad += 1
                                continue
                        file_inserted += 1

            if args.dry_run:
                con.rollback()
            else:
                con.commit()
        except Exception:
            con.rollback()
            raise

        inserted += file_inserted
        skipped_bad += file_bad
        print(f"  [{fp.name}] codes={file_inserted} bad={file_bad}")

        if not args.dry_run and not args.no_archive:
            try:
                archive_file(fp)
                archived.append(fp)
            except OSError as exc:
                _LOG.warning("archive fail %s: %s", fp, exc)

    final = con.execute("SELECT COUNT(*) FROM nta_tsutatsu_index").fetchone()[0]
    con.close()

    print("=== done ===")
    print(f"files processed: {len(files)}")
    print(f"files archived:  {len(archived)}")
    print(f"codes upserted:  {inserted}")
    print(f"skipped (no url->canonical mapping): {skipped_no_mapping}")
    print(f"skipped (dup content_hash):          {skipped_dup_hash}")
    print(f"skipped (dup code in run):           {skipped_dup_code}")
    print(f"skipped (bad row):                    {skipped_bad}")
    print(f"nta_tsutatsu_index: {initial} -> {final} (delta {final - initial})")
    print(f"elapsed: {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
