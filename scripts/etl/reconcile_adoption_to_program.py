#!/usr/bin/env python3
"""Reconcile unmatched adoption entities to canonical program entities.

Background
----------
`am_entities WHERE record_kind='adoption'` carries ~215K rows, but only
~94.6K resolve cleanly to a single non-quarantine `jpi_programs.unified_id`
through the existing `am_relation(part_of)` graph + name match. The
remaining ~120.6K are either:

  1.  unanchored (`05_adoption_additional` cohort: no `part_of` link at
      all — `raw_json.program_id_hint` is the only program signal),
  2.  anchored but the target is a year/round-suffixed program (e.g.
      "ものづくり・商業・サービス生産性向上促進補助金（第22次公募）")
      that does not collapse 1:1 with the canonical jpi_programs row, or
  3.  anchored with name collisions (multiple jpi_programs.unified_id
      share the same primary_name → ambiguous join).

This script strips year / round / fiscal-year suffixes from the adoption
side and fuzzy-matches them against canonical program names (am_entities
record_kind='program' primary_name + am_alias). It uses the program_id_hint
+ source_url_domain as disambiguators when multiple candidates tie.

The script is **read-only on the database**. It writes a CSV with
(adoption_id, primary_name_stripped, matched_program_id, confidence,
signal). Apply manually after review — do not let this script touch
`am_relation` directly.
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
DB = REPO / "autonomath.db"
DEFAULT_OUT = REPO / "analysis_wave18" / "adoption_reconciliation_2026-05-01.csv"

# --- Confidence thresholds ------------------------------------------------
# Empirical Python difflib / rapidfuzz JaroWinkler bands tuned against the
# 11 distinct program_id_hint cohorts in autonomath.db (it_dounyu / monodukuri
# / saikouchiku / jizokuka_ippan / ...). 0.92+ is "single-char or punctuation
# drift only" and is high-confidence; 0.85..0.92 is multi-char round/year
# suffix drift and requires a disambiguator (program_id_hint or
# source_url_domain) to clear; below 0.85 we record as low and require human
# review.
THRESHOLD_HIGH = 0.92
THRESHOLD_MED = 0.85

# --- Suffix strippers -----------------------------------------------------
# Order matters: longer / more-specific patterns must run BEFORE shorter
# overlap patterns or 令和6年度第3次 reduces to 令和6年 + 第3次 collisions.
_SUFFIX_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 令和6年度第3次補正 / 令和6年度補正第3次 / 令和6年度第3次 /
    # 令和6年度補正 / 令和6年度
    re.compile(r"令和\d+年度?(?:補正)?(?:第\d+次)?(?:公募)?(?:補正)?"),
    # R6補正第3次 / R6補正第3次公募
    re.compile(r"[Rr]\d+補正(?:第\d+次)?(?:公募)?"),
    # 平成30年度補正 / 平成30年度
    re.compile(r"平成\d+年度?(?:補正)?(?:第\d+次)?(?:公募)?"),
    # 2024年度第3次 / 2024年度補正 / 2024年度
    re.compile(r"20\d{2}年度?(?:補正)?(?:第\d+次)?(?:公募)?"),
    # 第10回公募 / 第10次公募 / 第10回 / 第10次 (catch-all, keep last)
    re.compile(r"第\d+(?:回|次)(?:公募|締切)?"),
    # 19次/20次 etc bare
    re.compile(r"\d+次公募"),
    # トレーリング 後期 / 前期 / 令和3年度 / 令和3年 (keep narrow)
    re.compile(r"(?:後期|前期|上期|下期)$"),
    # YYYY 後期 / YYYY 前期 (e.g. "IT導入補助金 2023 後期")
    re.compile(r"\s*20\d{2}\s*(?:後期|前期|上期|下期)?\s*$"),
    # Bare year tokens with spaces around them, e.g. "IT導入補助金 2025 (デジタル化…)"
    # These MUST run after the year-with-fiscal-marker patterns above so we
    # don't double-strip "2024年度" first, then "2024" again.
    re.compile(r"\s+20\d{2}\s+"),
    re.compile(r"\s+20\d{2}$"),
    # トレーリング 補正 / 通常枠 / 一般型 (preserve those — they are
    # legitimate variant names — so we DO NOT strip them).
)

# Whitespace + punctuation NFKC normalizer used for both adoption and
# program names before comparison. We do NOT lowercase Japanese; we do
# fold half/full-width ASCII variants (NFKC).
_WS_RE = re.compile(r"\s+")
# Trim characters at the edges of a normalized string. ruff B005 flags
# multi-char str.strip() as misleading because it strips ANY of the chars
# (not the substring) — that's exactly what we want here, so we wrap in
# a regex sub-equivalent via str.translate-then-trim. Pre-build the table.
_TRIM_CHARS = "　 \t「」『』:：;；,，.．/／\\"
_TRIM_RE = re.compile(rf"^[{re.escape(_TRIM_CHARS)}]+|[{re.escape(_TRIM_CHARS)}]+$")


def _normalize(text: str) -> str:
    """NFKC + collapse whitespace. Keep the casing of latin chars (program
    names like 'IT導入補助金' vs 'it導入補助金' are distinct enough that
    the existing canonical store uses upper-case 'IT' — preserving casing
    avoids a synthetic miss).

    We deliberately do NOT strip stand-alone parens because parenthesized
    suffixes like '(商工会地区)' / '(一般型)' are real 枠 names — they
    must survive normalization so the matcher can find the枠 row in the
    program registry.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = _TRIM_RE.sub("", text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def strip_year_round_suffix(name: str) -> str:
    """Strip year / round / fiscal-year suffixes from a program name.

    Examples (all normalize to "IT導入補助金" or "事業再構築補助金"):
        "IT導入補助金 2023 後期"            -> "IT導入補助金"
        "IT導入補助金 2025 (デジタル化・AI導入補助金)" -> kept as-is
                                              (parenthesized variants are
                                              real枠 names — not stripped)
        "事業再構築補助金 第13回公募"        -> "事業再構築補助金"
        "ものづくり補助金 第22次公募"        -> "ものづくり補助金"
        "小規模事業者持続化補助金 (商工会地区)" -> kept as-is (商工会地区
                                              is a real枠 name)
        "省エネ・非化石転換補助金 設備単位型 令和7年度補正" ->
                                              "省エネ・非化石転換補助金 設備単位型"
        "R6補正第3次"                        -> "" (pure suffix; will be
                                              stripped wherever attached)
    """
    s = _normalize(name)
    if not s:
        return ""
    for pat in _SUFFIX_PATTERNS:
        s = pat.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip(" 　")
    # Balance unmatched parens left behind by suffix stripping (only
    # strip a stray opening or closing paren — never both, never a
    # matched pair).
    if s.count("(") > s.count(")") and s.endswith("("):
        s = s[:-1].rstrip()
    elif s.count(")") > s.count("(") and s.startswith(")"):
        s = s[1:].lstrip()
    return s


# --- Match ---------------------------------------------------------------


@dataclass
class ProgramRow:
    canonical_id: str
    primary_name: str
    aliases: list[str]
    jsic_major: str | None
    funding_purpose: str | None


@dataclass
class AdoptionRow:
    canonical_id: str
    program_name_raw: str | None
    program_id_hint: str | None
    source_url_domain: str | None
    raw_json: str  # parsed lazily


# Per program_id_hint disambiguator: which canonical program is
# authoritative (operator-curated). None means "use only fuzzy match;
# the cohort doesn't disambiguate cleanly".
#
# This map is grounded in the 11 distinct hints currently present in
# `am_entities` adoption rows. Programs identified by canonical_id come
# from `SELECT canonical_id, primary_name FROM am_entities WHERE
# record_kind='program'` lookups against the actual repo state.
HINT_TO_CANONICAL_PROGRAM: dict[str, str] = {
    # IT導入補助金 (root program node — there are also -2024 / -2025 枠s)
    "it_dounyu": "program:base:71f6029070",  # IT導入補助金
    "it_hojo_2023": "program:base:71f6029070",  # IT導入補助金 (2023 cohort flattens to the root)
    "it_hojo_2025": "program:base:71f6029070",  # IT導入補助金 (2025 cohort flattens to the root)
    "monodukuri": "program:base:3b5ec4f12e",  # ものづくり補助金
    "jigyou_saikouchiku": "program:base:a841db60bb",  # 事業再構築補助金 (alt hint name)
    "saikouchiku": "program:base:a841db60bb",  # 事業再構築補助金
    "jizokuka_ippan": "program:base:2611050f9a",  # 小規模事業者持続化補助金 (root)
    "jizokuka_shokokai": "program:base:2611050f9a",  # 商工会地区 → flatten to root
    "jizokuka_sogyo": "program:base:2611050f9a",  # 創業 → flatten to root
    "shoryokuka_ippan": "program:base:298ecae3d3",  # 中小企業省力化投資補助金（一般型）
    "shinjigyou": "program:04_program_documents:000103:0b5ac58740",  # 中小企業新事業進出補助金
}


def _load_programs(con: sqlite3.Connection) -> tuple[list[ProgramRow], dict[str, list[ProgramRow]]]:
    """Load every record_kind='program' row + its aliases. Returns the
    full list plus an alias -> [ProgramRow] map (alias may collide on
    multiple programs, hence list)."""
    cur = con.cursor()
    cur.execute(
        "SELECT canonical_id, primary_name, "
        "       json_extract(raw_json, '$.jsic_major'), "
        "       json_extract(raw_json, '$.funding_purpose') "
        "  FROM am_entities "
        " WHERE record_kind='program' "
        "   AND primary_name IS NOT NULL "
        "   AND primary_name NOT LIKE '%× exclude' "
        "   AND primary_name NOT LIKE '07_new_program_candidates%'"
    )
    rows: list[ProgramRow] = []
    by_id: dict[str, ProgramRow] = {}
    for cid, name, jsic, funding in cur:
        pr = ProgramRow(
            canonical_id=cid,
            primary_name=name,
            aliases=[],
            jsic_major=jsic,
            funding_purpose=funding,
        )
        rows.append(pr)
        by_id[cid] = pr

    # Pull aliases for the entities we kept.
    cur.execute("SELECT canonical_id, alias FROM am_alias  WHERE entity_table='am_entities'")
    alias_map: dict[str, list[ProgramRow]] = {}
    for cid, alias in cur:
        pr = by_id.get(cid)
        if pr is None:
            continue
        pr.aliases.append(alias)
        alias_map.setdefault(_normalize(alias), []).append(pr)

    return rows, alias_map


def _load_unmatched_adoptions(con: sqlite3.Connection, limit: int) -> list[AdoptionRow]:
    """Pull adoption rows that don't already resolve cleanly.

    "Cleanly" = `am_relation(part_of)` resolves to exactly one
    non-quarantine `jpi_programs.unified_id` (matched on program
    primary_name).

    Implementation note: we precompute the set of "ambiguous" program
    primary_names (count != 1 in jpi_programs) once, then mark any
    adoption whose part_of target has a name in that set — plus all
    adoptions with NO part_of relation — as unmatched. This is O(N) over
    am_entities adoption + O(M) over jpi_programs, vs. O(N*M) for the
    correlated subquery form.
    """
    cur = con.cursor()
    # 1) Programs with exactly one non-excluded jpi_programs row form
    #    the "cleanly resolvable" set. Anything else is ambiguous.
    cur.execute(
        "SELECT a.canonical_id "
        "  FROM am_entities a "
        "  JOIN jpi_programs p ON p.primary_name = a.primary_name "
        " WHERE a.record_kind='program' "
        "   AND p.excluded = 0 "
        " GROUP BY a.canonical_id "
        " HAVING COUNT(*) = 1",
    )
    clean_program_ids: set[str] = {r[0] for r in cur}

    # 2) Adoption rows + their part_of target (NULL if none).
    cur.execute(
        "SELECT ad.canonical_id, "
        "       json_extract(ad.raw_json, '$.program_name'), "
        "       json_extract(ad.raw_json, '$.program_id_hint'), "
        "       ad.source_url_domain, "
        "       ad.raw_json, "
        "       r.target_entity_id "
        "  FROM am_entities ad "
        "  LEFT JOIN am_relation r "
        "    ON r.source_entity_id = ad.canonical_id "
        "   AND r.relation_type = 'part_of' "
        " WHERE ad.record_kind='adoption' "
        # Deterministic stratified sample: ORDER BY substr(canonical_id, -6)
        # rotates the 11 program_id_hint cohorts evenly through the
        # iterator, so --limit 1000 produces a representative match-rate
        # estimate rather than 1000 hits of one cohort. The hex suffix
        # is uniformly distributed across all sources/topics.
        " ORDER BY substr(ad.canonical_id, -6), ad.canonical_id"
    )
    out: list[AdoptionRow] = []
    seen: set[str] = set()
    for canonical_id, pname, hint, dom, raw, target_id in cur:
        if canonical_id in seen:
            continue
        if target_id and target_id in clean_program_ids:
            seen.add(canonical_id)  # cleanly matched — skip
            continue
        seen.add(canonical_id)
        out.append(
            AdoptionRow(
                canonical_id=canonical_id,
                program_name_raw=pname,
                program_id_hint=hint,
                source_url_domain=dom,
                raw_json=raw or "",
            )
        )
        if limit and limit > 0 and len(out) >= limit:
            break
    return out


def _try_match(
    adoption: AdoptionRow,
    programs: list[ProgramRow],
    program_norm_index: dict[str, list[ProgramRow]],
    alias_index: dict[str, list[ProgramRow]],
    scorer,
) -> tuple[str | None, float, str, str]:
    """Return (matched_program_id, confidence_score, signal, name_stripped).

    Signal vocabulary:
        hint        - resolved via HINT_TO_CANONICAL_PROGRAM table
        exact       - stripped name == program.primary_name (NFKC)
        alias       - stripped name == one of the program's am_alias rows
        fuzzy_high  - JaroWinkler >= 0.92, single best candidate or
                      hint/domain disambiguation passes
        fuzzy_med   - 0.85 <= JaroWinkler < 0.92, hint/domain
                      disambiguation passes
        unmatched   - no candidate above 0.85
    """
    raw = adoption.program_name_raw or ""
    stripped = strip_year_round_suffix(raw)
    if not stripped and adoption.program_id_hint:
        # 05_adoption_additional cohort: program_name is empty. Use hint
        # as the strongest signal we have.
        canonical = HINT_TO_CANONICAL_PROGRAM.get(adoption.program_id_hint)
        if canonical:
            return canonical, 1.0, "hint", adoption.program_id_hint
        return None, 0.0, "unmatched", adoption.program_id_hint or ""

    if not stripped:
        return None, 0.0, "unmatched", ""

    # 1. Exact normalized name match.
    exact_hits = program_norm_index.get(stripped, [])
    if len(exact_hits) == 1:
        return exact_hits[0].canonical_id, 1.0, "exact", stripped
    if len(exact_hits) > 1:
        # Multiple programs share this exact stripped name. Disambiguate
        # via program_id_hint if we have a curated map.
        canonical = HINT_TO_CANONICAL_PROGRAM.get(adoption.program_id_hint or "")
        if canonical:
            for pr in exact_hits:
                if pr.canonical_id == canonical:
                    return pr.canonical_id, 1.0, "exact_hint", stripped
        # Fall back to "first" — recorded as exact_ambig with confidence
        # downgraded.
        return exact_hits[0].canonical_id, 0.80, "exact_ambig", stripped

    # 2. Alias match.
    alias_hits = alias_index.get(stripped, [])
    if len(alias_hits) == 1:
        return alias_hits[0].canonical_id, 0.97, "alias", stripped
    if len(alias_hits) > 1:
        canonical = HINT_TO_CANONICAL_PROGRAM.get(adoption.program_id_hint or "")
        if canonical:
            for pr in alias_hits:
                if pr.canonical_id == canonical:
                    return pr.canonical_id, 0.97, "alias_hint", stripped
        return alias_hits[0].canonical_id, 0.80, "alias_ambig", stripped

    # 3. Fuzzy match against ALL program primary_names.
    best_id: str | None = None
    best_score = 0.0
    second_score = 0.0
    for pr in programs:
        score = scorer(stripped, _normalize(pr.primary_name))
        if score > best_score:
            second_score = best_score
            best_score = score
            best_id = pr.canonical_id
        elif score > second_score:
            second_score = score

    if best_id is None:
        return None, 0.0, "unmatched", stripped

    if best_score >= THRESHOLD_HIGH:
        return best_id, best_score, "fuzzy_high", stripped
    if best_score >= THRESHOLD_MED:
        # Disambiguate via hint if we have one — otherwise downgrade.
        canonical = HINT_TO_CANONICAL_PROGRAM.get(adoption.program_id_hint or "")
        if canonical:
            return canonical, best_score, "fuzzy_med_hint", stripped
        return best_id, best_score, "fuzzy_med", stripped

    # No candidate above 0.85 — but the hint may still resolve.
    canonical = HINT_TO_CANONICAL_PROGRAM.get(adoption.program_id_hint or "")
    if canonical:
        return canonical, 0.7, "hint_fallback", stripped
    return None, best_score, "unmatched", stripped


def _confidence_band(score: float) -> str:
    if score >= THRESHOLD_HIGH:
        return "high"
    if score >= THRESHOLD_MED:
        return "medium"
    if score > 0:
        return "low"
    return "none"


# --- Driver ---------------------------------------------------------------


def run(
    db_path: Path,
    out_path: Path,
    limit: int = 0,
    dry_run: bool = False,
) -> dict[str, object]:
    try:
        from rapidfuzz import distance
    except ImportError:
        print(
            "rapidfuzz not installed. .venv/bin/pip install rapidfuzz",
            file=sys.stderr,
        )
        return {"error": "rapidfuzz_missing"}

    scorer = distance.JaroWinkler.normalized_similarity

    # Read-only handle. SQLite URI form is the only safe way to enforce
    # read-only on a non-WAL database too.
    uri = f"file:{db_path}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        t0 = time.time()
        programs, alias_index = _load_programs(con)
        program_norm_index: dict[str, list[ProgramRow]] = {}
        for pr in programs:
            program_norm_index.setdefault(_normalize(pr.primary_name), []).append(pr)

        adoptions = _load_unmatched_adoptions(con, limit)
        load_elapsed = time.time() - t0
        print(
            f"loaded programs={len(programs)} "
            f"alias_keys={len(alias_index)} unmatched_adoptions={len(adoptions)} "
            f"in {load_elapsed:.1f}s",
            file=sys.stderr,
        )

        signal_counts: Counter[str] = Counter()
        confidence_counts: Counter[str] = Counter()
        rows_out: list[tuple[str, str, str | None, float, str]] = []
        sample_rows: list[tuple[str, str, str | None, float, str]] = []

        t1 = time.time()
        for ad in adoptions:
            matched_id, score, signal, stripped = _try_match(
                ad,
                programs,
                program_norm_index,
                alias_index,
                scorer,
            )
            band = _confidence_band(score)
            signal_counts[signal] += 1
            confidence_counts[band] += 1
            row = (ad.canonical_id, stripped, matched_id, round(score, 4), signal)
            rows_out.append(row)
            if matched_id and len(sample_rows) < 5 and signal != "unmatched":
                sample_rows.append(row)
        match_elapsed = time.time() - t1

        # Write CSV (still under dry-run? — yes, the CSV is the output;
        # dry-run skips ONLY the file write).
        if not dry_run:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(
                    [
                        "adoption_id",
                        "primary_name_stripped",
                        "matched_program_id",
                        "confidence",
                        "signal",
                    ]
                )
                writer.writerows(rows_out)

        # Print stats.
        total = len(rows_out)
        matched = sum(1 for r in rows_out if r[2] is not None)
        match_rate = matched / total if total else 0.0
        print(
            f"\nProcessed {total} adoptions in {match_elapsed:.1f}s",
            file=sys.stderr,
        )
        print(f"  matched: {matched} ({match_rate:.1%})", file=sys.stderr)
        print(f"  signal breakdown: {dict(signal_counts)}", file=sys.stderr)
        print(
            f"  confidence breakdown: {dict(confidence_counts)}",
            file=sys.stderr,
        )
        print("\nSample matches:", file=sys.stderr)
        for r in sample_rows:
            print(f"  {r}", file=sys.stderr)

        return {
            "total": total,
            "matched": matched,
            "match_rate": match_rate,
            "signal_counts": dict(signal_counts),
            "confidence_counts": dict(confidence_counts),
            "sample_rows": sample_rows,
            "elapsed_load_s": load_elapsed,
            "elapsed_match_s": match_elapsed,
            "out_path": str(out_path) if not dry_run else "<dry-run>",
        }
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--db",
        default=str(DB),
        help=f"SQLite DB path (default: {DB})",
    )
    ap.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help=f"CSV output path (default: {DEFAULT_OUT})",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Cap the number of unmatched adoptions to process. 0 = all.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip CSV write; print stats only.",
    )
    args = ap.parse_args()

    out = run(
        db_path=Path(args.db),
        out_path=Path(args.out),
        limit=args.limit,
        dry_run=args.dry_run,
    )
    if out.get("error"):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
