#!/usr/bin/env python3
"""ingest_inbox_law.py — e-Gov 法令本文 inbox -> am_law_article.

Walks `tools/offline/_inbox/egov_law_articles/*.jsonl`, joins each row
with its companion raw JSON dump (the e-Gov law_data API v2 payload
referenced via `body_path`), parses the structured `law_full_text`
tree into individual articles, and INSERT OR REPLACEs them into
`am_law_article` (autonomath.db).

Mapping
-------
- `e_gov_lawid` (URL `.../law_data/<law_id>?...`) is matched against
  `am_law.e_gov_lawid` to resolve the canonical_id. Rows whose law_id
  is not registered in `am_law` are skipped (logged + counted).

Dedupe
------
- Per row: (`law_canonical_id`, `article_number`) — schema UNIQUE.
- Per file: tracked via `content_hash` to avoid re-parsing identical
  payloads inside a single run.

Archival
--------
After a successful pass, processed jsonl files are moved to
`tools/offline/_inbox/_archived/egov_law_articles/<basename>` so the
next invocation does not re-ingest them. Raw body files under `raw/`
are *not* archived (they may be referenced by future delta runs).

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

_LOG = logging.getLogger("ingest_inbox_law")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "autonomath.db"
INBOX = REPO_ROOT / "tools" / "offline" / "_inbox"
SOURCE_DIR = INBOX / "egov_law_articles"
ARCHIVED_DIR = INBOX / "_archived" / "egov_law_articles"


def article_num_to_sort(num_str: str) -> float:
    """'42_12_7' -> 42.012007 (monotonic ordering key)."""
    if not num_str:
        return 0.0
    parts = num_str.split("_")
    try:
        sort_val = float(int(parts[0]))
    except (ValueError, IndexError):
        return 0.0
    for i, p in enumerate(parts[1:]):
        try:
            sort_val += int(p) * (10 ** (-3 * (i + 1)))
        except ValueError:
            pass
    return sort_val


def text_recursive(node: dict) -> str:
    """Concatenate all text under a JSON node from e-Gov law_full_text."""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    parts: list[str] = []
    for child in node.get("children", []) or []:
        if isinstance(child, str):
            parts.append(child)
        elif isinstance(child, dict):
            parts.append(text_recursive(child))
    return "".join(parts)


def _walk_articles(node: dict, out: list[dict], seen: set[str]) -> None:
    """Recurse into law_full_text tree, harvesting every Article node."""
    if not isinstance(node, dict):
        return
    if node.get("tag") == "Article":
        num = (node.get("attr") or {}).get("Num") or ""
        if num:
            num_final = num
            if num_final in seen:
                suffix = 2
                while f"{num}_附{suffix}" in seen:
                    suffix += 1
                num_final = f"{num}_附{suffix}"
            seen.add(num_final)

            title = ""
            caption = ""
            for child in node.get("children", []) or []:
                if not isinstance(child, dict):
                    continue
                tag = child.get("tag")
                if tag == "ArticleTitle":
                    title = text_recursive(child).strip()
                elif tag == "ArticleCaption":
                    caption = text_recursive(child).strip()

            full_text = re.sub(r"[\s　]+", " ", text_recursive(node)).strip()
            out.append(
                {
                    "article_number": num_final,
                    "article_number_sort": article_num_to_sort(num_final.split("_附")[0]),
                    "title": caption or title,
                    "text_full": full_text,
                }
            )
    for child in node.get("children", []) or []:
        if isinstance(child, dict):
            _walk_articles(child, out, seen)


def parse_law_payload(payload: dict) -> tuple[str | None, list[dict]]:
    """Return (e_gov_lawid, [articles]) from one e-Gov law_data JSON dump."""
    law_id = ((payload.get("law_info") or {}).get("law_id")) or None
    full_text = payload.get("law_full_text")
    articles: list[dict] = []
    if isinstance(full_text, dict):
        _walk_articles(full_text, articles, set())
    return law_id, articles


def load_canonical_map(con: sqlite3.Connection) -> dict[str, str]:
    rows = con.execute(
        "SELECT e_gov_lawid, canonical_id FROM am_law WHERE e_gov_lawid IS NOT NULL"
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def upsert_article(
    con: sqlite3.Connection,
    canonical_id: str,
    egov_law_id: str,
    art: dict,
    fetched_at: str,
) -> None:
    source_url = f"https://laws.e-gov.go.jp/law/{egov_law_id}#Mp-At_{art['article_number']}"
    con.execute(
        """
        INSERT INTO am_law_article (
            law_canonical_id, article_number, article_number_sort,
            title, text_summary, text_full,
            source_url, source_fetched_at, article_kind
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'main')
        ON CONFLICT(law_canonical_id, article_number) DO UPDATE SET
            article_number_sort = excluded.article_number_sort,
            title              = excluded.title,
            text_summary       = excluded.text_summary,
            text_full          = excluded.text_full,
            source_url         = excluded.source_url,
            source_fetched_at  = excluded.source_fetched_at
        """,
        (
            canonical_id,
            art["article_number"],
            art["article_number_sort"],
            art["title"],
            (art["text_full"] or "")[:500],
            art["text_full"],
            source_url,
            fetched_at,
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
    parser = argparse.ArgumentParser(description="Ingest egov law inbox jsonl")
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
        print("[ingest_inbox_law] no inbox files; nothing to do")
        return 0

    con = sqlite3.connect(args.db, timeout=300)
    con.execute("PRAGMA busy_timeout = 300000")
    canon_map = load_canonical_map(con)
    print(f"[ingest_inbox_law] db={args.db} files={len(files)} canonical_laws={len(canon_map)}")

    initial = con.execute("SELECT COUNT(*) FROM am_law_article").fetchone()[0]

    seen_hashes: set[str] = set()
    seen_keys: set[tuple[str, str]] = set()
    archived: list[Path] = []
    inserted = 0
    skipped_no_canonical = 0
    skipped_dup = 0
    skipped_bad = 0
    laws_seen: set[str] = set()

    t0 = time.time()
    fetched_at = datetime.now(UTC).isoformat()
    for fp in files:
        file_inserted = 0
        file_dup = 0
        file_bad = 0
        try:
            con.execute("BEGIN IMMEDIATE")
            with fp.open(encoding="utf-8") as fh:
                for line_no, line in enumerate(fh, start=1):
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
                    body_path = row.get("body_path") or ""
                    if not body_path:
                        file_bad += 1
                        continue
                    if chash and chash in seen_hashes:
                        file_dup += 1
                        continue
                    if chash:
                        seen_hashes.add(chash)

                    raw_path = REPO_ROOT / body_path
                    if not raw_path.exists():
                        # Fall back: maybe absolute
                        cand = Path(body_path)
                        if cand.exists():
                            raw_path = cand
                        else:
                            file_bad += 1
                            _LOG.debug("missing body_path: %s", body_path)
                            continue

                    try:
                        payload = json.loads(raw_path.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError) as exc:
                        _LOG.warning("body parse fail %s: %s", raw_path, exc)
                        file_bad += 1
                        continue

                    egov_id, articles = parse_law_payload(payload)
                    if not egov_id:
                        m = re.search(r"law_data/([^?/]+)", url)
                        egov_id = m.group(1) if m else None
                    if not egov_id:
                        file_bad += 1
                        continue
                    canon = canon_map.get(egov_id)
                    if not canon:
                        skipped_no_canonical += 1
                        _LOG.debug("no canonical for %s", egov_id)
                        continue
                    laws_seen.add(canon)

                    for art in articles:
                        key = (canon, art["article_number"])
                        if key in seen_keys:
                            file_dup += 1
                            continue
                        seen_keys.add(key)
                        if not args.dry_run:
                            try:
                                upsert_article(con, canon, egov_id, art, fetched_at)
                            except sqlite3.Error as exc:
                                _LOG.warning(
                                    "upsert fail %s %s: %s",
                                    canon,
                                    art["article_number"],
                                    exc,
                                )
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
        skipped_dup += file_dup
        skipped_bad += file_bad
        print(f"  [{fp.name}] articles={file_inserted} dup={file_dup} bad={file_bad}")

        if not args.dry_run and not args.no_archive:
            try:
                archive_file(fp)
                archived.append(fp)
            except OSError as exc:
                _LOG.warning("archive fail %s: %s", fp, exc)

    final = con.execute("SELECT COUNT(*) FROM am_law_article").fetchone()[0]
    con.close()

    print("=== done ===")
    print(f"files processed: {len(files)}")
    print(f"files archived:  {len(archived)}")
    print(f"laws ingested:   {len(laws_seen)}")
    print(f"articles upserted: {inserted}")
    print(f"skipped (no canonical_id mapping): {skipped_no_canonical}")
    print(f"skipped (dup or bad row):          dup={skipped_dup} bad={skipped_bad}")
    print(f"am_law_article count: {initial} -> {final} (delta {final - initial})")
    print(f"elapsed: {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
