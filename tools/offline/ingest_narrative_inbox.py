#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, or scripts/etl/.
"""W20 ingest narrative JSONL inbox into autonomath.am_program_narrative_full.

PURPOSE (migration wave24_149_am_program_narrative_full):
    Validate JSONL rows produced by the 25-shard subagent batch and
    UPSERT them into `am_program_narrative_full`. CONFLICT resolution:
        same content_hash  → no-op (idempotent re-ingest, no row write)
        diff content_hash  → overwrite narrative_md / counter_arguments_md
                             / model_used / content_hash and bump
                             generated_at

NO LLM IMPORT. Pure SQLite + jsonschema-shaped manual validation.

WORKFLOW:
    1. operator: tools/offline/dispatch_narrative_batches.sh
                  → dispatches 25 Claude Code subagents
    2. each subagent writes JSONL to
                  tools/offline/_inbox/narrative/{date}_agent{NN}.jsonl
    3. operator: python tools/offline/ingest_narrative_inbox.py
                  [--inbox tools/offline/_inbox/narrative]
                  [--db autonomath.db]
                  [--dry-run] [--keep-files]

VALIDATION RULES (per row):
    * program_id           non-empty TEXT, must exist in jpintel.programs
    * narrative_md         len >= 600, non-whitespace
    * counter_arguments_md len >= 200, non-whitespace
    * content_hash         lowercase hex sha-256 (64 chars), recomputed
                           and compared against (narrative_md + '\n---\n'
                           + counter_arguments_md). Mismatch → quarantine.
    * model_used           non-empty (subagent identifier)
    * generated_at         parseable ISO8601 (best-effort; we accept the
                           string as-is, only fail on completely empty)

POST-INGEST FILE HANDLING:
    A processed JSONL file (zero quarantines) is moved to
    `_inbox/narrative/_done/`. With any quarantines, the file stays put
    and the bad lines are written to `_quarantine/narrative_full/`.

Sibling cron `scripts/cron/ingest_offline_inbox.py` handles other tools
(program_narrative 4-section, exclusion_rules, etc.). We deliberately
do NOT add `narrative_full` to that cron because:
  (a) the subagent batch is operator-driven and one-shot, not nightly
  (b) we do not want a stale `_inbox/narrative/` half-written file to
      get auto-ingested by a routine cron mid-run
  (c) the W20 schema is keyed program_id PRIMARY KEY (not the 3-tuple
      contract of am_program_narrative), so it shares 0 SQL with the
      sibling cron's program_narrative handler
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
DEFAULT_JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_INBOX = Path(__file__).resolve().parent / "_inbox" / "narrative"
QUARANTINE_DIR = Path(__file__).resolve().parent / "_quarantine" / "narrative_full"

MIN_NARRATIVE_LEN = 600
MIN_COUNTER_LEN = 200
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
TABLE = "am_program_narrative_full"

UPSERT_SQL = f"""
    INSERT INTO {TABLE} (
        program_id,
        narrative_md,
        counter_arguments_md,
        generated_at,
        model_used,
        content_hash,
        source_program_corpus_snapshot_id
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(program_id) DO UPDATE SET
        narrative_md = excluded.narrative_md,
        counter_arguments_md = excluded.counter_arguments_md,
        generated_at = excluded.generated_at,
        model_used = excluded.model_used,
        content_hash = excluded.content_hash,
        source_program_corpus_snapshot_id = excluded.source_program_corpus_snapshot_id
    WHERE {TABLE}.content_hash IS NULL
       OR {TABLE}.content_hash != excluded.content_hash
"""


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def expected_hash(narrative_md: str, counter_arguments_md: str) -> str:
    payload = (narrative_md + "\n---\n" + counter_arguments_md).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_known_program_ids(jpintel_db: Path) -> set[str]:
    if not jpintel_db.exists():
        return set()
    conn = sqlite3.connect(f"file:{jpintel_db}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT unified_id FROM programs").fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows if r[0]}


def validate_row(row: dict[str, Any], known_pids: set[str] | None) -> str | None:
    """Return None on OK, or a string reason on validation failure."""
    pid = row.get("program_id")
    if not pid or not isinstance(pid, str):
        return "missing_or_non_string_program_id"
    if known_pids is not None and pid not in known_pids:
        return f"unknown_program_id:{pid}"
    nm = row.get("narrative_md", "")
    if not isinstance(nm, str) or not nm.strip():
        return "narrative_md_empty"
    if len(nm) < MIN_NARRATIVE_LEN:
        return f"narrative_md_too_short:{len(nm)}<{MIN_NARRATIVE_LEN}"
    cm = row.get("counter_arguments_md", "")
    if not isinstance(cm, str) or not cm.strip():
        return "counter_arguments_md_empty"
    if len(cm) < MIN_COUNTER_LEN:
        return f"counter_arguments_md_too_short:{len(cm)}<{MIN_COUNTER_LEN}"
    mu = row.get("model_used", "")
    if not isinstance(mu, str) or not mu.strip():
        return "model_used_empty"
    ch = row.get("content_hash", "")
    if not isinstance(ch, str) or not HEX64_RE.match(ch):
        return (
            f"content_hash_not_sha256_hex:{ch[:16] if isinstance(ch, str) else type(ch).__name__}"
        )
    expected = expected_hash(nm, cm)
    if ch != expected:
        return f"content_hash_mismatch:claimed={ch[:12]}..,expected={expected[:12]}.."
    ga = row.get("generated_at", "")
    if not isinstance(ga, str) or not ga.strip():
        return "generated_at_empty"
    return None


def quarantine_line(src_path: Path, lineno: int, raw: str, reason: str) -> Path:
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    qpath = QUARANTINE_DIR / f"{src_path.stem}.line{lineno:05d}.jsonl"
    qpath.write_text(
        json.dumps({"reason": reason, "raw": raw}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return qpath


def mark_done(src_path: Path) -> Path:
    done_dir = src_path.parent / "_done"
    done_dir.mkdir(parents=True, exist_ok=True)
    dst = done_dir / src_path.name
    shutil.move(str(src_path), str(dst))
    return dst


def process_file(
    path: Path,
    conn: sqlite3.Connection,
    known_pids: set[str] | None,
    *,
    dry_run: bool,
    keep_files: bool,
) -> tuple[int, int, int]:
    """Returns (n_applied, n_noop, n_quarantined)."""
    n_applied = 0
    n_noop = 0
    n_quarantined = 0
    with path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                quarantine_line(path, lineno, raw, f"json_decode_error: {exc}")
                n_quarantined += 1
                continue
            reason = validate_row(row, known_pids)
            if reason:
                quarantine_line(path, lineno, raw, reason)
                n_quarantined += 1
                continue
            if dry_run:
                n_applied += 1
                continue
            try:
                cur = conn.execute(
                    UPSERT_SQL,
                    (
                        row["program_id"],
                        row["narrative_md"],
                        row["counter_arguments_md"],
                        row["generated_at"],
                        row["model_used"],
                        row["content_hash"],
                        row.get("source_program_corpus_snapshot_id"),
                    ),
                )
            except sqlite3.Error as exc:
                quarantine_line(path, lineno, raw, f"sqlite_error: {exc}")
                n_quarantined += 1
                continue
            if cur.rowcount > 0:
                n_applied += 1
            else:
                # Same content_hash already present → idempotent no-op.
                n_noop += 1
    if not dry_run:
        conn.commit()
        if n_quarantined == 0 and not keep_files:
            mark_done(path)
    return n_applied, n_noop, n_quarantined


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--inbox",
        default=str(DEFAULT_INBOX),
        help=f"Inbox directory containing *.jsonl (default {DEFAULT_INBOX}).",
    )
    p.add_argument(
        "--db",
        default=str(DEFAULT_AUTONOMATH_DB),
        help=f"autonomath.db path (default {DEFAULT_AUTONOMATH_DB}).",
    )
    p.add_argument(
        "--jpintel-db",
        default=str(DEFAULT_JPINTEL_DB),
        help="jpintel.db path (read-only, used for program_id existence check).",
    )
    p.add_argument(
        "--no-pid-check",
        action="store_true",
        help="Skip program_id existence check against jpintel.programs.",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--keep-files",
        action="store_true",
        help="Do not move processed files to _done/ on success.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    inbox = Path(args.inbox)
    db = Path(args.db)
    if not inbox.exists():
        print(f"ERROR: inbox not found: {inbox}", file=sys.stderr)
        return 2
    if not db.exists():
        print(f"ERROR: autonomath db not found: {db}", file=sys.stderr)
        return 2

    files = sorted(p for p in inbox.glob("*.jsonl") if p.is_file())
    if not files:
        print(f"# no *.jsonl in {inbox} — nothing to ingest")
        return 0

    known_pids: set[str] | None = None
    if not args.no_pid_check:
        known_pids = load_known_program_ids(Path(args.jpintel_db))
        print(f"# loaded {len(known_pids):,} known program_ids from jpintel.db")

    conn = sqlite3.connect(db)
    # Confirm the target table exists; refuse with a clear message if not.
    has_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (TABLE,),
    ).fetchone()
    if not has_table:
        print(
            f"ERROR: table {TABLE} missing in {db}. "
            f"Run migration wave24_149_am_program_narrative_full first "
            f"(applied automatically on Fly boot via entrypoint.sh §4).",
            file=sys.stderr,
        )
        conn.close()
        return 2

    print("=" * 78)
    print("# ingest_narrative_inbox.py  (W20 / migration 149)")
    print(f"# inbox     : {inbox}")
    print(f"# db        : {db}")
    print(f"# files     : {len(files)}")
    print(f"# dry_run   : {args.dry_run}")
    print(f"# started   : {utc_now_iso()}")
    print("=" * 78)

    grand_applied = 0
    grand_noop = 0
    grand_quarantined = 0
    try:
        for f in files:
            applied, noop, quar = process_file(
                f,
                conn,
                known_pids,
                dry_run=args.dry_run,
                keep_files=args.keep_files,
            )
            grand_applied += applied
            grand_noop += noop
            grand_quarantined += quar
            print(f"  {f.name:<40} applied={applied:>5} noop={noop:>5} quarantined={quar:>5}")
    finally:
        conn.close()

    print("=" * 78)
    print(
        f"# total: applied={grand_applied:,}  noop={grand_noop:,}  "
        f"quarantined={grand_quarantined:,}"
    )
    if grand_quarantined:
        print(f"# quarantined rows under: {QUARANTINE_DIR}")
    return 0 if grand_quarantined == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
