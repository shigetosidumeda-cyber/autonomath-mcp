#!/usr/bin/env python3
"""Wave 20 — revalidate `am_amount_condition.quality_tier`.

Background:
    `am_amount_condition` holds 250,946 rows. ~99.8% of the rows with
    `fixed_yen` populated have an EMPTY `extracted_text`, meaning we
    have NO literal source-string evidence for the value. ~96.4% sit
    in 8 ceiling buckets that match the broken-ETL template-default
    values (¥500K / ¥2M / ¥3.5M / ¥4.5M / ¥12.5M / ¥15M / ¥70M / ¥90M).

    Migration 150 added a 3-tier `quality_tier` column and seeded it
    with a static rule pass (verified > template_default > unknown).
    This script does a SECOND pass that detects ADDITIONAL template
    defaults beyond the 8 hardcoded buckets — any fixed_yen value with
    a count >= TEMPLATE_BUCKET_MIN_COUNT and an empty extracted_text
    population is treated as a template-default cluster.

    The script also normalises 'verified' rows: a row counts as
    verified ONLY if `extracted_text` literally contains the
    `fixed_yen` formatted as a Japanese number (digits or 万円 form).
    Hits where extracted_text exists but does NOT mention the value
    are demoted from 'verified' to 'unknown' to avoid surfacing rows
    where the extracted text describes a different field (e.g. a rate
    blurb stored in an amount row).

Rules (final state):
    rule 1: fixed_yen sits in the dynamic template-default cluster
            (count >= TEMPLATE_BUCKET_MIN_COUNT AND <0.5% of bucket
            rows have non-empty extracted_text)
        -> 'template_default'
    rule 2: extracted_text contains the fixed_yen literally (yen
            string OR 万円 string OR 億円 string)
        -> 'verified'
    rule 3: anything else
        -> 'unknown'

Read/Write:
    READ am_amount_condition (id, fixed_yen, extracted_text,
                              template_default, quality_tier).
    WRITE am_amount_condition (quality_tier) only. No row creation /
          deletion. Bulk UPDATE in batches of UPDATE_BATCH_SIZE.

Idempotency:
    Running the script twice in a row is safe and converges on the
    same final distribution. The script logs (initial, final) tier
    counts so the operator can diff manually.

Usage:
    python3 scripts/etl/revalidate_amount_conditions.py
    python3 scripts/etl/revalidate_amount_conditions.py --dry-run
    python3 scripts/etl/revalidate_amount_conditions.py --report-out path

Outputs (when --report-out is set):
    Markdown report with the bucket cluster, rule-hit counts, and
    final tier distribution. Default report path is
    `docs/_internal/W20_AMOUNT_VALIDATION_REPORT.md`.

NO LLM calls. NO API calls. Pure SQLite + Python.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = Path(
    os.environ.get(
        "AUTONOMATH_DB_PATH",
        str(_REPO_ROOT / "autonomath.db"),
    )
)
DEFAULT_REPORT = _REPO_ROOT / "docs" / "_internal" / "W20_AMOUNT_VALIDATION_REPORT.md"

# A `fixed_yen` value qualifies as a dynamic template-default cluster
# if at least this many rows share it AND the within-bucket rate of
# non-empty extracted_text is below TEMPLATE_BUCKET_TEXT_RATIO. The
# numbers are deliberately conservative — we'd rather leave a real
# popular round amount as 'unknown' than misclassify it as template.
TEMPLATE_BUCKET_MIN_COUNT = 200
TEMPLATE_BUCKET_TEXT_RATIO = 0.005  # 0.5%

UPDATE_BATCH_SIZE = 5000


# ---------------------------------------------------------------------------
# Tier computation helpers


def detect_template_buckets(conn: sqlite3.Connection) -> list[tuple[int, int, int]]:
    """Return [(fixed_yen, total_count, with_text_count), ...] for every
    bucket that meets the TEMPLATE_BUCKET_MIN_COUNT threshold.

    This is a single GROUP BY scan, ordered by total_count DESC so the
    report shows the largest clusters first.
    """
    rows = conn.execute(
        """
        SELECT fixed_yen,
               COUNT(*) AS total_n,
               SUM(CASE WHEN extracted_text IS NOT NULL
                         AND TRIM(extracted_text) != ''
                        THEN 1 ELSE 0 END) AS text_n
          FROM am_amount_condition
         WHERE fixed_yen IS NOT NULL
         GROUP BY fixed_yen
        HAVING COUNT(*) >= ?
         ORDER BY total_n DESC
        """,
        (TEMPLATE_BUCKET_MIN_COUNT,),
    ).fetchall()
    return [(int(r[0]), int(r[1]), int(r[2] or 0)) for r in rows]


def template_bucket_set(buckets: list[tuple[int, int, int]]) -> set[int]:
    """Return the subset of bucket fixed_yen values that meet BOTH
    the count threshold AND the within-bucket extracted_text scarcity
    threshold. These are the values we treat as template-default.
    """
    out: set[int] = set()
    for yen, total, with_text in buckets:
        ratio = (with_text / total) if total else 0.0
        if ratio < TEMPLATE_BUCKET_TEXT_RATIO:
            out.add(yen)
    return out


# Match the fixed_yen literally inside extracted_text. We accept three
# common Japanese expressions. Conservative: we do NOT try to parse
# 千円 / 円 commas / wide-numeral variants (those exist but are noisy
# enough that fuzzy match would over-credit the verified tier).


def _yen_appears_in_text(yen: int, text: str) -> bool:
    """Return True iff `text` mentions `yen` literally as digits, in
    万 form (yen / 10000), or in 億 form (yen / 100000000). Comma and
    half-width digit normalisation are handled by `re.search`."""
    if not text:
        return False
    norm = text.replace(",", "")
    # Plain digit match (e.g. "5000000" or "5000000円").
    if re.search(rf"\b{yen}\b", norm):
        return True
    # 万円 form — only emit if yen is a whole multiple of 10,000.
    if yen % 10000 == 0:
        man = yen // 10000
        if re.search(rf"\b{man}\s*万", norm):
            return True
    # 億円 form — only emit if yen is a whole multiple of 100,000,000.
    if yen % 100_000_000 == 0:
        oku = yen // 100_000_000
        if re.search(rf"\b{oku}\s*億", norm):
            return True
    return False


# ---------------------------------------------------------------------------
# Bulk reclassification


def _tier_distribution(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT quality_tier, COUNT(*) FROM am_amount_condition GROUP BY quality_tier"
    ).fetchall()
    return {str(r[0]): int(r[1]) for r in rows}


def reclassify(conn: sqlite3.Connection, dry_run: bool = False) -> dict[str, int]:
    """Walk every row and assign quality_tier.

    Returns a counters dict for the report.
    """
    buckets = detect_template_buckets(conn)
    template_set = template_bucket_set(buckets)

    cur = conn.execute(
        """
        SELECT id, fixed_yen, extracted_text
          FROM am_amount_condition
        """
    )

    new_assignments: list[tuple[str, int]] = []
    counters = {
        "verified": 0,
        "template_default": 0,
        "unknown": 0,
        "bucket_count": len(template_set),
    }

    for row_id, fixed_yen, extracted_text in cur:
        text = (extracted_text or "").strip()
        tier = "unknown"

        # rule 2 (verified) takes priority over rule 1 — if we can
        # literally match the value in source text, we trust it even
        # when the value happens to land in a template bucket.
        if text and fixed_yen is not None and _yen_appears_in_text(int(fixed_yen), text):
            tier = "verified"
        elif fixed_yen is not None and int(fixed_yen) in template_set:
            tier = "template_default"
        else:
            tier = "unknown"

        counters[tier] += 1
        new_assignments.append((tier, int(row_id)))

    if dry_run:
        return counters

    # Bulk UPDATE in batches.
    cursor = conn.cursor()
    for offset in range(0, len(new_assignments), UPDATE_BATCH_SIZE):
        batch = new_assignments[offset : offset + UPDATE_BATCH_SIZE]
        cursor.executemany(
            "UPDATE am_amount_condition SET quality_tier = ? WHERE id = ?",
            batch,
        )
    conn.commit()
    return counters


# ---------------------------------------------------------------------------
# Reporting


def write_report(
    path: Path,
    initial: dict[str, int],
    final: dict[str, int],
    counters: dict[str, int],
    buckets: list[tuple[int, int, int]],
    template_set: set[int],
    db_path: Path,
    dry_run: bool,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    total = sum(final.values()) or 1
    now = datetime.now(UTC).isoformat()

    bucket_lines: list[str] = []
    for yen, total_n, text_n in buckets:
        ratio = (text_n / total_n) if total_n else 0.0
        is_tpl = "yes" if yen in template_set else "no"
        bucket_lines.append(
            f"| {yen:>11,} | {total_n:>9,} | {text_n:>5,} | {ratio * 100:6.3f}% | {is_tpl} |"
        )
    bucket_table = "\n".join(bucket_lines) if bucket_lines else "| (none) | | | | |"

    body = f"""# W20 — am_amount_condition Quality-Tier Validation Report

- Generated: `{now}`
- DB: `{db_path}`
- Mode: `{"DRY-RUN (no UPDATE issued)" if dry_run else "APPLIED"}`
- Migration applied: `150_am_amount_condition_quality_tier.sql`
- Script: `scripts/etl/revalidate_amount_conditions.py`

## Why

`am_amount_condition` holds 250,946 rows; the majority were filled by a
broken ETL pass that copied the program ceiling into every per-record
row (¥500K / ¥2M / and 6 other round-number buckets). Surfacing those
values via the ¥3/req metered API would create 詐欺 risk under
景表法 / 消費者契約法. Migration 150 added a 3-tier `quality_tier`
column. This script reclassifies every row by:

1. **verified** — `extracted_text` literally contains the `fixed_yen`
   as digits, 万 form, or 億 form.
2. **template_default** — `fixed_yen` belongs to a dynamic
   template-bucket cluster (count >= {TEMPLATE_BUCKET_MIN_COUNT} AND
   non-empty-extracted_text rate < {TEMPLATE_BUCKET_TEXT_RATIO * 100:.1f}%).
3. **unknown** — anything else (NULL fixed_yen, sparse one-off values,
   or rows whose extracted_text does not mention the value).

The surface side filters `quality_tier = 'verified'` for customer-facing
output. `template_default` and `unknown` rows remain on disk for audit
but are NOT exposed via the metered API.

## Tier distribution

| Tier               | Before script | After script | Share |
|--------------------|--------------:|-------------:|------:|
| verified           | {initial.get("verified", 0):>13,} | {final.get("verified", 0):>12,} | {final.get("verified", 0) / total * 100:5.2f}% |
| template_default   | {initial.get("template_default", 0):>13,} | {final.get("template_default", 0):>12,} | {final.get("template_default", 0) / total * 100:5.2f}% |
| unknown            | {initial.get("unknown", 0):>13,} | {final.get("unknown", 0):>12,} | {final.get("unknown", 0) / total * 100:5.2f}% |
| **TOTAL**          | {sum(initial.values()):>13,} | {total:>12,} | 100.00% |

## Detected template-default buckets

`fixed_yen` values with count >= {TEMPLATE_BUCKET_MIN_COUNT} rows, sorted by
size. The `with_text` column counts rows in that bucket whose
`extracted_text` is non-empty. Buckets where `with_text/total <
{TEMPLATE_BUCKET_TEXT_RATIO * 100:.1f}%` are flagged as template defaults.

| fixed_yen | total_n | with_text | text_ratio | template? |
|----------:|--------:|----------:|-----------:|:---------:|
{bucket_table}

Total template buckets flagged: **{counters.get("bucket_count", 0)}**.

## API filter convention

Surface tools (current and future) MUST filter:

```sql
SELECT ... FROM am_amount_condition
 WHERE quality_tier = 'verified'
   -- AND (whatever else)
```

The legacy `template_default = 0` filter is now a SUBSET of the new
filter (every row with template_default=0 is either verified or
unknown). The new filter is stricter and safer.

## Operator next actions

1. Increase `verified` share by extracting `extracted_text` from source
   PDFs/HTML in `tools/offline/` (operator-LLM, NOT runtime). Each such
   re-extraction promotes a row from `unknown` -> `verified` for free.
2. Re-run this script monthly (or via a cron) to catch newly-emerged
   template buckets after fresh ingest waves.
3. Wire the API filter into any new tool that joins `am_amount_condition`
   (see `src/jpintel_mcp/mcp/autonomath_tools/gx_tool.py` for the
   reference convention).
"""
    path.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help="autonomath.db path")
    p.add_argument("--dry-run", action="store_true", help="no UPDATE issued")
    p.add_argument(
        "--report-out",
        type=Path,
        default=DEFAULT_REPORT,
        help="markdown report destination (set '' to skip)",
    )
    args = p.parse_args(argv)

    if not args.db.exists():
        print(f"FATAL: db not found: {args.db}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(args.db))
    conn.row_factory = sqlite3.Row
    try:
        initial = _tier_distribution(conn)
        buckets = detect_template_buckets(conn)
        tpl_set = template_bucket_set(buckets)
        counters = reclassify(conn, dry_run=args.dry_run)
        final = _tier_distribution(conn)
    finally:
        conn.close()

    print(f"buckets_flagged={counters['bucket_count']}")
    print("tier_before: " + ", ".join(f"{k}={v}" for k, v in sorted(initial.items())))
    print("tier_after:  " + ", ".join(f"{k}={v}" for k, v in sorted(final.items())))
    if args.dry_run:
        planned = {k: counters[k] for k in ("verified", "template_default", "unknown")}
        print(
            "tier_planned (dry-run): " + ", ".join(f"{k}={v}" for k, v in sorted(planned.items()))
        )

    if args.report_out and str(args.report_out):
        write_report(
            args.report_out,
            initial=initial,
            final=final,
            counters=counters,
            buckets=buckets,
            template_set=tpl_set,
            db_path=args.db,
            dry_run=args.dry_run,
        )
        print(f"report_written: {args.report_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
