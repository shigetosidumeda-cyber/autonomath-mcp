#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, or scripts/etl/.
"""Offline alias generator for `programs.aliases_json` backfill (D9).

Operator-only offline script. Not callable from production runtime. NO LLM
API usage — pure deterministic Python on top of `pykakasi` (already in
`pyproject.toml [project.optional-dependencies][site]`).

Background
----------
At the 2026-04-30 audit, `programs.aliases_json` is empty for ~99.6 % of
rows (S=96.8 %, C=99.8 %). That column is the single biggest drag on the
evidence_score across every tier. Filling it is purely mechanical: each
entity has well-known surface-form variants (kana ↔ kanji, full-width ↔
half-width digits, ministry abbreviations, particle drops) that the
runtime currently has to discover at query time via the trigram FTS5
tokenizer — a known false-positive source (see CLAUDE.md gotchas).

This script reads `data/jpintel.db` **read-only** and produces a CSV (one
row per program × suggested aliases list). It does **NOT** write to any
SQLite database. A separate operator CLI (the "OTHER CLI" referenced in
the task description) is responsible for applying the CSV back into the
DB after a sanity review pass — keeping write authority in one place per
the schema_guard convention.

Output schema (CSV, UTF-8 with BOM for Excel safety)
----------------------------------------------------
    program_id,primary_name,aliases_json,n_aliases,methods

* `program_id`  — `programs.unified_id`
* `primary_name` — verbatim
* `aliases_json` — JSON array (UTF-8) of suggested alias surface forms.
                   Up to 8 strings (`MAX_ALIASES`). Empty array if no
                   variants generated.
* `n_aliases`   — convenience integer for spreadsheet filtering
* `methods`    — comma-separated list of which generation rules fired
                  (`hira`, `kata`, `width`, `abbrev`, `particle_drop`,
                  `bracket_strip`)

Generation rules (ordered, dedup against primary_name + each other)
-----------------------------------------------------------------
1. **kanji → ひらがな** via `pykakasi.convert()` `hira` join. Adds the
   pure-hiragana reading. Useful for mobile IME users typing reads, and
   for rows with rare-kanji ministry names.
2. **kanji → カタカナ** via `pykakasi.convert()` `kana` join. Useful for
   rows where the source reproduced the original press-release in
   katakana.
3. **全角英数 ↔ 半角英数 normalisation**. Programs in the 2024 batches
   often carry their FY year (Ｒ６, ２０２４, ＦＹ２０２４) in full-width.
   Add the half-width form (R6, 2024, FY2024) and vice versa. Implemented
   purely via `str.translate()` — no external dep.
4. **Ministry / authority abbreviation expansion**. Hard-coded 30-entry
   dict (operator-curated, conservative). e.g. `経済産業省 → 経産省`,
   `中小企業庁 → 中企庁`, `日本政策金融公庫 → 日本公庫`. Both directions
   (long ↔ short) when the long form appears as a substring.
5. **Particle / suffix drop**. e.g. `〜の補助金 → 〜補助金`,
   `〜に関する助成金 → 〜助成金`. A small whitelist of high-precision
   transformations only — never rewrite arbitrary substrings.
6. **Bracket / annotation strip**. Programs prefixed with
   `【女性活躍推進課】`, `[5/7〆]`, `MUN-462187-002_霧島市_…`, etc. carry
   non-name decoration. Strip any leading `【…】`, `[…]`, `（…）`, and
   any `MUN-/PREF-/JIM-…_` ID prefix (`scripts/generate_program_pages.py`
   already does the trailing variant for slugs; we mirror it here).

Dedup + cap
-----------
* Whitespace-trimmed, NFKC-normalised when comparing.
* Drop any candidate equal to `primary_name` (case-insensitive ASCII).
* Cap at `MAX_ALIASES = 8` per program (operator-tunable). Earlier rules
  (1, 2, 3) take priority because they are the highest-coverage.

Usage
-----
    # Smoke test (no DB write, prints first 5 programs to stdout):
    uv run python tools/offline/generate_aliases.py --limit 5 --dry-run

    # Full run, write CSV (no DB write):
    uv run python tools/offline/generate_aliases.py \
        --output analysis_wave18/aliases_backfill_2026-05-01.csv

    # Restrict to currently-empty rows only (recommended for backfill):
    uv run python tools/offline/generate_aliases.py --only-empty \
        --output analysis_wave18/aliases_backfill_2026-05-01.csv

Flags
-----
    --jpintel-db PATH   override DB path (default: data/jpintel.db, read-only)
    --output PATH       CSV output path (default: analysis_wave18/aliases_backfill_<DATE>.csv)
    --limit N           process only first N rows
    --dry-run           print to stdout, do not write CSV
    --only-empty        only process rows where current aliases_json is empty/null
    --max-aliases K     cap aliases per program (default 8; task spec)

What this script does NOT do
----------------------------
* Does NOT write back to `data/jpintel.db` or `autonomath.db`.
  Apply the CSV via the dedicated apply CLI when ready.
* Does NOT call any LLM API. CI guard `tests/test_no_llm_in_production.py`
  excludes `tools/offline/`, but this script avoids LLM imports anyway.
* Does NOT overwrite `programs.aliases_json` directly. Operator review of
  the CSV is the gate.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "analysis_wave18"

LOG = logging.getLogger("generate_aliases")

# Per-program cap. Task spec: "1 entity あたり最大 8 個".
MAX_ALIASES = 8


# ---------------------------------------------------------------------------
# Hand-curated ministry / authority abbreviation pairs.
# Format: (long_form, short_form). Both directions are emitted when the long
# form appears in primary_name. Conservative — only forms in mainstream JP
# administrative use. NOT a translation dictionary; do NOT add EN aliases here
# (those live in batch_translate_corpus.py).
# ---------------------------------------------------------------------------
ABBREV_PAIRS: list[tuple[str, str]] = [
    # 中央省庁 (略称はメディア・通達で広く流通)
    ("経済産業省", "経産省"),
    ("厚生労働省", "厚労省"),
    ("文部科学省", "文科省"),
    ("国土交通省", "国交省"),
    ("農林水産省", "農水省"),
    ("環境省", "環境省"),  # no abbrev — kept for symmetry; will dedup
    ("総務省", "総務省"),
    ("財務省", "財務省"),
    ("外務省", "外務省"),
    ("法務省", "法務省"),
    ("防衛省", "防衛省"),
    # 庁
    ("中小企業庁", "中企庁"),
    ("特許庁", "特許庁"),
    ("国税庁", "国税庁"),
    ("消費者庁", "消費者庁"),
    ("デジタル庁", "デジ庁"),
    ("林野庁", "林野庁"),
    ("水産庁", "水産庁"),
    ("文化庁", "文化庁"),
    ("観光庁", "観光庁"),
    # 公庫・機構 (固有略称が定着)
    ("日本政策金融公庫", "日本公庫"),
    ("中小企業基盤整備機構", "中小機構"),
    ("独立行政法人中小企業基盤整備機構", "中小機構"),
    ("新エネルギー・産業技術総合開発機構", "NEDO"),
    ("産業技術総合研究所", "産総研"),
    ("科学技術振興機構", "JST"),
    ("情報処理推進機構", "IPA"),
    ("日本貿易振興機構", "ジェトロ"),
    # 補助金 / 制度名でよくある冗長表記の刈り込み
    ("小規模事業者持続化補助金", "持続化補助金"),
    ("ものづくり・商業・サービス生産性向上促進補助金", "ものづくり補助金"),
    ("事業再構築補助金", "再構築補助金"),
    ("IT導入補助金", "IT補助金"),
]


# ---------------------------------------------------------------------------
# Particle / suffix drop transformations. Each entry is (regex, replacement).
# Applied in order; the first match that produces a different surface than
# the input is kept as a candidate.
# ---------------------------------------------------------------------------
PARTICLE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # 「〜の補助金」→「〜補助金」
    (re.compile(r"の補助金$"), "補助金"),
    (re.compile(r"の助成金$"), "助成金"),
    (re.compile(r"の交付金$"), "交付金"),
    (re.compile(r"の奨励金$"), "奨励金"),
    (re.compile(r"の支援金$"), "支援金"),
    (re.compile(r"に関する補助金$"), "補助金"),
    (re.compile(r"に関する助成金$"), "助成金"),
    (re.compile(r"に係る補助金$"), "補助金"),
    # 「〜事業（補助金）」→「〜事業補助金」  括弧除去
    (re.compile(r"事業（補助金）$"), "事業補助金"),
    (re.compile(r"事業\(補助金\)$"), "事業補助金"),
    # トレーリング「等」「について」「のお知らせ」削除
    (re.compile(r"について$"), ""),
    (re.compile(r"のお知らせ$"), ""),
    (re.compile(r"等$"), ""),
]


# ---------------------------------------------------------------------------
# Bracket / annotation strip. Removes leading 【…】 [...] (...) and any
# leading municipal / prefectural ID prefix (PREF-… / MUN-… / JIM-… / etc.)
# that is appended in operator-side enrichment.
# ---------------------------------------------------------------------------
LEADING_BRACKET_RE = re.compile(r"^(?:[【】「-』\[\(（].*?[】」』\)\]）]\s*)+")
LEADING_ID_RE = re.compile(r"^(?:PREF|MUN|JIM|GOV)-[A-Z0-9_\-]+_[^_]+_")
LEADING_DEADLINE_RE = re.compile(r"^【\d+/\d+〆?】\s*")


# ---------------------------------------------------------------------------
# pykakasi loader (lazy, single-instance).
# ---------------------------------------------------------------------------


def _load_kakasi():
    """Lazy pykakasi loader. Exits with code 2 if pykakasi missing.

    Production runtime tolerates pykakasi absence (graceful slug fallback in
    `src/jpintel_mcp/utils/slug.py`); offline backfill cannot — without
    kakasi, rules 1 & 2 are no-ops which would defeat the script's purpose.
    """
    try:
        import pykakasi  # type: ignore[import-untyped]
    except ImportError:
        LOG.error(
            'pykakasi is required for kana generation. Install with: pip install -e ".[site]"'
        )
        sys.exit(2)
    return pykakasi.kakasi()


# ---------------------------------------------------------------------------
# Width normalisation (full-width ↔ half-width ASCII).
# Implemented manually because `unicodedata.normalize('NFKC')` collapses too
# aggressively (also normalises e.g. ㈱ → (株), 全角 kana → 半角 kana) — we
# only want digits + ASCII letters.
# ---------------------------------------------------------------------------
_FW_DIGITS = "０１２３４５６７８９"
_HW_DIGITS = "0123456789"
_FW_LETTERS = (
    "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"
)
_HW_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_FW_TO_HW = str.maketrans(_FW_DIGITS + _FW_LETTERS, _HW_DIGITS + _HW_LETTERS)
_HW_TO_FW = str.maketrans(_HW_DIGITS + _HW_LETTERS, _FW_DIGITS + _FW_LETTERS)


def _has_fullwidth_alnum(text: str) -> bool:
    return any(c in _FW_DIGITS or c in _FW_LETTERS for c in text)


def _has_halfwidth_alnum(text: str) -> bool:
    return any(c.isascii() and c.isalnum() for c in text)


# ---------------------------------------------------------------------------
# Per-rule generators. Each returns a list of candidate strings (may be empty).
# ---------------------------------------------------------------------------


def gen_hira(name: str, kks) -> list[str]:
    parts = kks.convert(name)
    hira = "".join(p.get("hira", "") for p in parts).strip()
    if not hira or hira == name:
        return []
    return [hira]


def gen_kata(name: str, kks) -> list[str]:
    parts = kks.convert(name)
    kana = "".join(p.get("kana", "") for p in parts).strip()
    if not kana or kana == name:
        return []
    return [kana]


def gen_width(name: str) -> list[str]:
    """Emit a half-width form (if name has any 全角英数) and / or a
    full-width form (if name has any half-width 英数). Both directions
    aid IME-driven search (e.g. user types `R6` → match Ｒ６; or types
    `Ｒ６` → match `R6`)."""
    out: list[str] = []
    if _has_fullwidth_alnum(name):
        cand = name.translate(_FW_TO_HW)
        if cand and cand != name:
            out.append(cand)
    if _has_halfwidth_alnum(name):
        cand = name.translate(_HW_TO_FW)
        if cand and cand != name:
            out.append(cand)
    return out


def gen_abbrev(name: str) -> list[str]:
    """Replace any long-form ministry / authority substring with its short
    form (and emit the long-form expansion of any short form found). Each
    pair fires at most once per direction."""
    out: list[str] = []
    seen_subs: set[tuple[str, str]] = set()
    for long_form, short_form in ABBREV_PAIRS:
        if long_form == short_form:
            continue
        if long_form in name and (long_form, short_form) not in seen_subs:
            cand = name.replace(long_form, short_form)
            if cand and cand != name:
                out.append(cand)
                seen_subs.add((long_form, short_form))
        # Only expand short → long when the short isn't already a substring
        # of the long (avoids 環境省 → 環境省 noop and 観光庁 → 観光庁
        # trivial loops).
        if (
            short_form in name
            and (short_form, long_form) not in seen_subs
            and short_form != long_form
            and short_form not in long_form
        ):
            cand = name.replace(short_form, long_form)
            if cand and cand != name:
                out.append(cand)
                seen_subs.add((short_form, long_form))
    return out


def gen_particle_drop(name: str) -> list[str]:
    out: list[str] = []
    for pat, repl in PARTICLE_PATTERNS:
        cand = pat.sub(repl, name)
        if cand and cand != name:
            out.append(cand)
    return out


def gen_bracket_strip(name: str) -> list[str]:
    """Strip leading 【…】 (…) [...] decoration and any operator-injected ID
    prefix. Returns the stripped form once, only if it actually changes."""
    cur = name
    cur = LEADING_DEADLINE_RE.sub("", cur)
    cur = LEADING_ID_RE.sub("", cur)
    # repeat bracket strip in case of nested 【…】[...] decoration
    for _ in range(3):
        new = LEADING_BRACKET_RE.sub("", cur).strip()
        if new == cur:
            break
        cur = new
    cur = cur.strip()
    if cur and cur != name.strip():
        return [cur]
    return []


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _norm_for_dedup(text: str) -> str:
    """Casefold + whitespace-trim for dedup comparison (does NOT modify
    the surface form we emit — only used for set-membership checks).

    Deliberately does NOT NFKC-normalise: NFKC collapses 全角 → 半角 so a
    full-width Ｒ６ candidate would be dedup'd against a half-width R6
    candidate, defeating the explicit width-rule output. The runtime FTS5
    layer already does its own normalisation; we want the raw width
    variants on the alias surface so non-FTS exact-match paths
    (e.g. case_studies.alias join) hit either form."""
    return text.strip().casefold()


def generate_for_name(
    name: str, kks, max_aliases: int = MAX_ALIASES
) -> tuple[list[str], list[str]]:
    """Return (aliases, methods_fired).

    Pure function. Caller passes the kakasi handle (pre-loaded) so this is
    safe to call in tight loops without re-initialising the dict.
    """
    if not name:
        return [], []

    seen: set[str] = {_norm_for_dedup(name)}
    aliases: list[str] = []
    methods_fired: list[str] = []

    # Order matters: high-coverage / cheap-to-trust rules first so that
    # when MAX_ALIASES caps the list, we keep the most useful ones.
    rules: list[tuple[str, callable]] = [
        ("bracket_strip", lambda: gen_bracket_strip(name)),
        ("particle_drop", lambda: gen_particle_drop(name)),
        ("abbrev", lambda: gen_abbrev(name)),
        ("width", lambda: gen_width(name)),
        ("hira", lambda: gen_hira(name, kks)),
        ("kata", lambda: gen_kata(name, kks)),
    ]

    for method, fn in rules:
        try:
            candidates = fn()
        except Exception as exc:  # noqa: BLE001 — rule must never fail the run
            LOG.warning("rule=%s failed for name=%r: %s", method, name, exc)
            continue
        fired = False
        for cand in candidates:
            cand = cand.strip()
            if not cand:
                continue
            key = _norm_for_dedup(cand)
            if key in seen:
                continue
            seen.add(key)
            aliases.append(cand)
            fired = True
            if len(aliases) >= max_aliases:
                break
        if fired and method not in methods_fired:
            methods_fired.append(method)
        if len(aliases) >= max_aliases:
            break

    return aliases, methods_fired


def iter_programs(
    jpintel_db: Path, only_empty: bool, limit: int | None
) -> Iterable[tuple[str, str, str | None]]:
    """Yield (unified_id, primary_name, current_aliases_json) read-only.

    Read-only mode is enforced via SQLite URI `?mode=ro` so any accidental
    write attempt fails fast (matches CLAUDE.md / autonomath.db isolation
    posture)."""
    uri = f"file:{jpintel_db}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        sql = (
            "SELECT unified_id, primary_name, aliases_json "
            "  FROM programs "
            " WHERE primary_name IS NOT NULL "
            "   AND primary_name != ''"
        )
        if only_empty:
            sql += " AND (aliases_json IS NULL OR aliases_json = ''       OR aliases_json = '[]')"
        sql += " ORDER BY unified_id"
        if limit:
            sql += f" LIMIT {int(limit)}"
        for row in conn.execute(sql):
            yield (row["unified_id"], row["primary_name"], row["aliases_json"])
    finally:
        conn.close()


def write_csv(rows: list[dict], out_path: Path) -> None:
    """Write the alias-backfill CSV at out_path. UTF-8-with-BOM so Excel +
    Numbers render Japanese without re-encoding."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["program_id", "primary_name", "aliases_json", "n_aliases", "methods"])
        for r in rows:
            w.writerow(
                [
                    r["program_id"],
                    r["primary_name"],
                    json.dumps(r["aliases"], ensure_ascii=False),
                    len(r["aliases"]),
                    ",".join(r["methods"]),
                ]
            )


def print_dry_run(rows: list[dict]) -> None:
    """Render the CSV-equivalent rows + a stats summary to stdout."""
    print("program_id\tprimary_name\taliases_json\tn_aliases\tmethods")
    for r in rows:
        print(
            f"{r['program_id']}\t{r['primary_name']}\t"
            f"{json.dumps(r['aliases'], ensure_ascii=False)}\t"
            f"{len(r['aliases'])}\t{','.join(r['methods'])}"
        )


def summary_stats(rows: list[dict]) -> dict:
    """Aggregate counts + per-method tally + alias-count histogram."""
    total = len(rows)
    with_any = sum(1 for r in rows if r["aliases"])
    n_aliases = [len(r["aliases"]) for r in rows]
    avg = (sum(n_aliases) / total) if total else 0.0
    method_count: dict[str, int] = {}
    for r in rows:
        for m in r["methods"]:
            method_count[m] = method_count.get(m, 0) + 1
    histogram: dict[int, int] = {}
    for n in n_aliases:
        histogram[n] = histogram.get(n, 0) + 1
    return {
        "total_programs": total,
        "with_at_least_one_alias": with_any,
        "with_at_least_one_alias_pct": (round(100 * with_any / total, 2) if total else 0.0),
        "avg_aliases_per_program": round(avg, 3),
        "max_aliases_per_program": max(n_aliases) if n_aliases else 0,
        "method_fire_count": method_count,
        "alias_count_histogram": dict(sorted(histogram.items())),
    }


def default_output_path() -> Path:
    today = date.today().isoformat()
    return DEFAULT_OUTPUT_DIR / f"aliases_backfill_{today}.csv"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    p.add_argument(
        "--jpintel-db",
        type=Path,
        default=DEFAULT_JPINTEL_DB,
        help="Path to jpintel.db (read-only opened)",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="CSV output path (default: analysis_wave18/aliases_backfill_<DATE>.csv)",
    )
    p.add_argument("--limit", type=int, default=None, help="Process only first N rows")
    p.add_argument("--dry-run", action="store_true", help="Print to stdout instead of writing CSV")
    p.add_argument(
        "--only-empty",
        action="store_true",
        help="Only process rows where aliases_json is NULL/''/'[]'",
    )
    p.add_argument(
        "--max-aliases",
        type=int,
        default=MAX_ALIASES,
        help=f"Cap aliases per program (default {MAX_ALIASES})",
    )
    p.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if not args.jpintel_db.exists():
        LOG.error("DB not found: %s", args.jpintel_db)
        return 2

    kks = _load_kakasi()

    rows: list[dict] = []
    for unified_id, primary_name, _current in iter_programs(
        args.jpintel_db, only_empty=args.only_empty, limit=args.limit
    ):
        aliases, methods = generate_for_name(primary_name, kks, max_aliases=args.max_aliases)
        rows.append(
            {
                "program_id": unified_id,
                "primary_name": primary_name,
                "aliases": aliases,
                "methods": methods,
            }
        )

    stats = summary_stats(rows)
    LOG.info("scanned %d programs", stats["total_programs"])
    LOG.info(
        "with_at_least_one_alias=%d (%.2f%%) avg=%.3f max=%d",
        stats["with_at_least_one_alias"],
        stats["with_at_least_one_alias_pct"],
        stats["avg_aliases_per_program"],
        stats["max_aliases_per_program"],
    )
    LOG.info("method_fire_count=%s", stats["method_fire_count"])
    LOG.info("alias_count_histogram=%s", stats["alias_count_histogram"])

    if args.dry_run:
        print_dry_run(rows)
    else:
        out_path = args.output or default_output_path()
        write_csv(rows, out_path)
        LOG.info("wrote %d rows -> %s", len(rows), out_path)
        # Also drop a small sidecar JSON with the aggregate stats so a
        # downstream apply-CLI can sanity-check counts before bulk INSERT.
        stats_path = out_path.with_suffix(".stats.json")
        stats_path.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        LOG.info("wrote stats -> %s", stats_path)

    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entry
    sys.exit(main())
