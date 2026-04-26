#!/usr/bin/env python3
"""Regenerate site/llms-full.txt with a compact program inventory appended.

Inputs:
  - data/jpintel.db  (programs table, source of truth for the FastAPI API)
  - site/llms-full.txt  (existing docs-heavy file; preserved verbatim above section)

Output (atomic write):
  - site/llms-full.txt  (preserved docs + ## All Programs (compact) section)

The compact section is a pipe-delimited inventory of every active program
(`excluded = 0` AND `tier IN ('S','A','B','C')`, matching the production search
filter — `tier='X'` is the quarantine tier and must stay excluded). It exists
so LLM crawlers (GPTBot, ClaudeBot, PerplexityBot, etc.) can ingest the full
program list without scraping 9,998 individual HTML pages.

Compact line format (UTF-8, LF):
  <unified_id> | <primary_name> | <program_kind> | <amount_max_man_yen> | <source_url> | <source_fetched_at>

Idempotent: re-running replaces the prior `## All Programs` block (and
everything below it) with a freshly queried block. Anything *above* the marker
stays intact, so docs edits in CI/manual concat are preserved.

CLI:
    uv run python scripts/regen_llms_full.py
    uv run python scripts/regen_llms_full.py --db data/jpintel.db --out site/llms-full.txt
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Marker that delimits the auto-generated compact section. Anything from this
# line onward is regenerated each run; everything above is preserved.
SECTION_MARKER = "## All Programs"

# SQL filter: tier='X' is the quarantine tier and excluded=1 is hard-deleted.
# Both must stay out of any user-facing surface (CLAUDE.md non-negotiable).
PROGRAMS_SQL = """
SELECT
    unified_id,
    primary_name,
    COALESCE(program_kind, '') AS program_kind,
    COALESCE(amount_max_man_yen, 0) AS amount_max_man_yen,
    COALESCE(source_url, '') AS source_url,
    COALESCE(source_fetched_at, '') AS source_fetched_at
FROM programs
WHERE excluded = 0
  AND tier IN ('S', 'A', 'B', 'C')
ORDER BY tier, primary_name
LIMIT 20000
"""


def _sanitize(value: str) -> str:
    """Strip characters that would break the pipe-delimited line format.

    Removes embedded `|`, CR, LF and tabs; collapses inner whitespace runs.
    Returns an empty string for None.
    """
    if value is None:
        return ""
    s = str(value)
    for bad in ("\r\n", "\r", "\n", "\t", "|"):
        s = s.replace(bad, " ")
    # Collapse runs of whitespace that the substitutions may have introduced.
    return " ".join(s.split())


def _format_amount(amount: float | int | None) -> str:
    """Format amount_max_man_yen as integer when whole, else as float."""
    if amount is None:
        return "0"
    try:
        f = float(amount)
    except (TypeError, ValueError):
        return "0"
    if f == int(f):
        return str(int(f))
    # Trim trailing zeros while keeping a single decimal place when meaningful.
    return f"{f:g}"


def fetch_programs(db_path: Path) -> list[tuple[str, ...]]:
    if not db_path.exists():
        msg = f"db not found: {db_path}"
        raise FileNotFoundError(msg)
    # Read-only via URI to avoid accidental writes.
    uri = f"file:{db_path}?mode=ro"
    with sqlite3.connect(uri, uri=True) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(PROGRAMS_SQL).fetchall()
    return rows


def build_compact_section(rows: list[sqlite3.Row]) -> str:
    """Render the ## All Programs (compact) block as a single string."""
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    count = len(rows)

    lines: list[str] = []
    lines.append(f"{SECTION_MARKER} ({count:,} entries, compact)")
    lines.append("")
    lines.append(
        "Generated daily. Source: jpintel.db. "
        "AutonoMath operates Bookyou株式会社 T8010001213708."
    )
    lines.append(
        f"Generated at: {generated_at} | Filter: excluded=0 AND tier IN (S,A,B,C) "
        "(tier='X' is the quarantine tier and is excluded)."
    )
    lines.append(
        "Format: <unified_id> | <primary_name> | <program_kind> | "
        "<amount_max_man_yen> | <source_url> | <source_fetched_at>"
    )
    lines.append(
        "amount_max_man_yen is denominated in 万円 (10,000 JPY); 0 means unspecified or none."
    )
    lines.append("")

    for row in rows:
        line = " | ".join([
            _sanitize(row["unified_id"]),
            _sanitize(row["primary_name"]),
            _sanitize(row["program_kind"]),
            _format_amount(row["amount_max_man_yen"]),
            _sanitize(row["source_url"]),
            _sanitize(row["source_fetched_at"]),
        ])
        lines.append(line)

    lines.append("")
    return "\n".join(lines)


def split_existing(text: str) -> str:
    """Return the prefix of `text` up to (but not including) the section marker.

    If the marker is not present, return the full text plus a trailing newline
    so the new section starts on its own block. Preserves any trailing
    whitespace normalization the source file had.
    """
    idx = text.find(f"\n{SECTION_MARKER}")
    if idx == -1:
        # First-run mode: append cleanly with one blank line between.
        if not text.endswith("\n"):
            text += "\n"
        if not text.endswith("\n\n"):
            text += "\n"
        return text
    # Trim trailing whitespace from the kept prefix and re-add a single blank line.
    prefix = text[: idx + 1].rstrip() + "\n\n"
    return prefix


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        os.replace(tmp_name, path)
    except Exception:
        # Best-effort cleanup of the temp file if rename failed.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/jpintel.db"),
        help="Path to jpintel.db (default: data/jpintel.db relative to cwd).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("site/llms-full.txt"),
        help="Path to llms-full.txt (default: site/llms-full.txt).",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=5 * 1024 * 1024,
        help="Refuse to write if the result exceeds this size (default: 5 MiB).",
    )
    args = parser.parse_args(argv)

    db_path: Path = args.db.resolve()
    out_path: Path = args.out.resolve()

    if not out_path.exists():
        sys.stderr.write(
            f"warn: out file does not exist, creating fresh at {out_path}\n"
        )
        existing = ""
    else:
        existing = out_path.read_text(encoding="utf-8")

    rows = fetch_programs(db_path)
    if not rows:
        sys.stderr.write("warn: programs query returned 0 rows; aborting\n")
        return 2

    section = build_compact_section(rows)
    prefix = split_existing(existing)
    new_content = prefix + section

    new_bytes = new_content.encode("utf-8")
    if len(new_bytes) > args.max_bytes:
        sys.stderr.write(
            f"error: rendered file is {len(new_bytes):,} bytes, "
            f"exceeds --max-bytes={args.max_bytes:,}\n"
        )
        return 3

    atomic_write(out_path, new_content)

    sys.stdout.write(
        f"wrote {out_path} | rows={len(rows):,} | "
        f"bytes={len(new_bytes):,} | lines={new_content.count(chr(10)) + 1:,}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
