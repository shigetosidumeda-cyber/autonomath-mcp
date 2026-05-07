#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, or scripts/etl/.
"""B13 prefecture / municipality offline back-fill extractor.

Read-only scan of `programs.primary_name` + `programs.source_url` to recover
the (prefecture, municipality) pair for the 9.5k+ rows that are currently
NULL. Writes a CSV diff for an operator to review; never touches the DB.

Detection inputs
----------------
1. `am_region` (autonomath.db, 1,966 rows) -- canonical 5-digit JIS region
   codes for 47 prefectures, 20 designated cities, 171 designated wards,
   1727 ordinary municipalities. Loaded into in-memory tries/sets so no
   external IO past startup.
2. Hand-curated `pref.<romaji>.lg.jp` and 23-ku TLD map for URL signal.

Confidence (per row)
--------------------
- high   : prefecture+municipality found in BOTH name and URL signals (or
           name match plus an unambiguous municipality whose 5-digit code
           pins down exactly one prefecture).
- medium : single signal (name only, or URL only) yields a unique result.
- low    : URL points only to a national domain (.go.jp / pref-less .lg.jp)
           AND the name itself names a prefecture or 全国. The CSV operator
           still gets a value, but the gate downstream may want to require
           `confidence != 'low'` before propagating to the live DB.

Usage
-----
    uv run python tools/offline/extract_prefecture_municipality.py \\
        --db data/jpintel.db \\
        --region-db autonomath.db \\
        --out analysis_wave18/prefecture_municipality_backfill_2026-05-01.csv

Flags
-----
    --limit N   Process only the first N programs (default: all).
    --dry-run   Print stats but do not write the CSV.
    --only-missing  Skip rows that already have BOTH prefecture and municipality.
                    Defaults to True; pass --all-rows to override.
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from collections.abc import Iterable

# ---------------------------------------------------------------------------
# Static data: prefecture aliases, romaji map for URL signal, ward alias rules.
# ---------------------------------------------------------------------------

# Romaji used in `pref.<romaji>.lg.jp` style URLs. Matches `am_region.name_en`
# but lower-cased; verified against the 47 rows of am_region (prefecture).
PREF_ROMAJI: dict[str, str] = {
    "hokkaido": "北海道",
    "aomori": "青森県",
    "iwate": "岩手県",
    "miyagi": "宮城県",
    "akita": "秋田県",
    "yamagata": "山形県",
    "fukushima": "福島県",
    "ibaraki": "茨城県",
    "tochigi": "栃木県",
    "gunma": "群馬県",
    "saitama": "埼玉県",
    "chiba": "千葉県",
    "tokyo": "東京都",
    "kanagawa": "神奈川県",
    "niigata": "新潟県",
    "toyama": "富山県",
    "ishikawa": "石川県",
    "fukui": "福井県",
    "yamanashi": "山梨県",
    "nagano": "長野県",
    "gifu": "岐阜県",
    "shizuoka": "静岡県",
    "aichi": "愛知県",
    "mie": "三重県",
    "shiga": "滋賀県",
    "kyoto": "京都府",
    "osaka": "大阪府",
    "hyogo": "兵庫県",
    "nara": "奈良県",
    "wakayama": "和歌山県",
    "tottori": "鳥取県",
    "shimane": "島根県",
    "okayama": "岡山県",
    "hiroshima": "広島県",
    "yamaguchi": "山口県",
    "tokushima": "徳島県",
    "kagawa": "香川県",
    "ehime": "愛媛県",
    "kochi": "高知県",
    "fukuoka": "福岡県",
    "saga": "佐賀県",
    "nagasaki": "長崎県",
    "kumamoto": "熊本県",
    "oita": "大分県",
    "miyazaki": "宮崎県",
    "kagoshima": "鹿児島県",
    "okinawa": "沖縄県",
}
ROMAJI_PREF: dict[str, str] = {v: k for k, v in PREF_ROMAJI.items()}

# Tokyo 23 wards: am_region rows 13101..13123. Codes/names verified in DB.
TOKYO_23_WARDS: tuple[str, ...] = (
    "千代田区",
    "中央区",
    "港区",
    "新宿区",
    "文京区",
    "台東区",
    "墨田区",
    "江東区",
    "品川区",
    "目黒区",
    "大田区",
    "世田谷区",
    "渋谷区",
    "中野区",
    "杉並区",
    "豊島区",
    "北区",
    "荒川区",
    "板橋区",
    "練馬区",
    "足立区",
    "葛飾区",
    "江戸川区",
)
# Bare-ku names that ALSO occur as designated wards in other prefectures
# (中央区, 北区, etc.). We cannot resolve these without a prefecture anchor,
# so they only match when an explicit prefecture/city signal is present.
AMBIGUOUS_BARE_WARDS: frozenset[str] = frozenset(
    {
        "中央区",
        "北区",
        "南区",
        "西区",
        "東区",
        "緑区",
        "港区",
    }
)

# Prefecture-name regex: longest match first (北海道 before 北).
PREF_PATTERN = re.compile(
    "(" + "|".join(re.escape(p) for p in sorted(PREF_ROMAJI.values(), key=len, reverse=True)) + ")"
)

# Municipality match: "<chars>市" / "<chars>町" / "<chars>村" / "<chars>区".
# Allowed leading chars: CJK ideographs, hiragana, katakana, but NOT the
# prefecture suffix characters (都/道/府/県) -- those would let a candidate
# like '東京都中央区' swallow the prefecture marker. Each candidate is
# validated against am_region, so the broad class never invents a place.
# 北海道 is the one prefecture name with 道; we strip prefectures from the
# name in extract_from_name before running this regex, so the 道 exclusion
# never blocks a real muni search.
MUNI_PATTERN = re.compile(r"([一-鿿々ヶケぁ-んァ-ヴー]{1,8}[市町村区])")


# ---------------------------------------------------------------------------
# Region table: load am_region into hierarchy lookup structures.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegionEntry:
    code: str
    name_ja: str
    level: str  # prefecture / designated_city / designated_ward / municipality
    parent_code: str | None


@dataclass
class RegionIndex:
    """In-memory views of am_region used by the matcher."""

    pref_codes: set[str]
    pref_by_name: dict[str, str]  # name_ja -> region_code
    name_to_pref: dict[str, set[str]]  # muni name_ja -> {pref_code, ...}
    designated_cities: dict[str, str]  # city name_ja -> pref_code (e.g. 札幌市 -> 01)
    designated_wards: dict[str, dict[str, str]]
    # designated_wards[parent_city_name] -> {ward_name: pref_code}

    @classmethod
    def load(cls, region_db_path: Path) -> RegionIndex:
        if not region_db_path.exists():
            raise FileNotFoundError(f"am_region source not found: {region_db_path}")
        # `immutable=1` skips WAL journal touching when another process has
        # autonomath.db open in WAL mode (the live API on this workstation
        # holds a connection). Pure read-only path; no journal is created.
        con = sqlite3.connect(f"file:{region_db_path}?mode=ro&immutable=1", uri=True)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                "SELECT region_code, name_ja, region_level, parent_code FROM am_region"
            ).fetchall()
        finally:
            con.close()

        entries = [
            RegionEntry(r["region_code"], r["name_ja"], r["region_level"], r["parent_code"])
            for r in rows
        ]
        by_code = {e.code: e for e in entries}

        pref_codes: set[str] = {e.code[:2] for e in entries if e.level == "prefecture"}
        pref_by_name: dict[str, str] = {
            e.name_ja: e.code for e in entries if e.level == "prefecture"
        }

        name_to_pref: dict[str, set[str]] = defaultdict(set)
        designated_cities: dict[str, str] = {}
        designated_wards: dict[str, dict[str, str]] = defaultdict(dict)

        for e in entries:
            if e.level in ("municipality", "designated_city"):
                name_to_pref[e.name_ja].add(e.code[:2])
            if e.level == "designated_city":
                designated_cities[e.name_ja] = e.code[:2]
            if e.level == "designated_ward" and e.parent_code:
                parent = by_code.get(e.parent_code)
                if parent:
                    # Strip "札幌市" prefix from "札幌市中央区" so the ward can be
                    # matched alone when the parent city is known from context.
                    bare = e.name_ja
                    if bare.startswith(parent.name_ja):
                        bare = bare[len(parent.name_ja) :]
                    designated_wards[parent.name_ja][bare] = e.code[:2]
                    # Also register the full form so name-scan still hits.
                    name_to_pref[e.name_ja].add(e.code[:2])

        # Tokyo 23 wards: every ward name-key is unique under 東京都, but bare
        # 中央区/北区/etc. clash with designated cities elsewhere. Register the
        # 23 wards explicitly, but only consume them when 東京都 anchored.
        # (We tag this in extract_from_name via TOKYO_23_WARDS.)

        return cls(
            pref_codes=pref_codes,
            pref_by_name=pref_by_name,
            name_to_pref=name_to_pref,
            designated_cities=designated_cities,
            designated_wards=designated_wards,
        )


# ---------------------------------------------------------------------------
# Extraction logic.
# ---------------------------------------------------------------------------


@dataclass
class Extracted:
    prefecture: str | None = None
    municipality: str | None = None
    source: str = ""  # "name", "url", "name+url", or ""

    @property
    def signal(self) -> str:
        return self.source


def _domain_parts(url: str | None) -> list[str]:
    if not url:
        return []
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return []
    return [p.lower() for p in host.split(".") if p]


def extract_from_url(url: str | None, idx: RegionIndex) -> Extracted:
    """Read prefecture + municipality from the URL hostname.

    Patterns:
        pref.<romaji>.lg.jp           -> prefecture
        city.<romaji>.<pref>.[lg.]jp  -> municipality + prefecture
        city.<romaji>.lg.jp           -> municipality (pref unknown)
        town.<romaji>.<pref>.lg.jp    -> municipality + prefecture
        www.<romaji>.lg.jp            -> sometimes city (rare)

    We only assert prefecture from URL when the romaji literal is in the
    canonical 47-romaji table; everything else stays None to avoid invented
    place names.
    """
    out = Extracted()
    parts = _domain_parts(url)
    if not parts:
        return out

    # Strip trailing public suffix (.jp / .lg.jp / .go.jp).
    # Only the last 2-3 labels matter for our match.
    for i, label in enumerate(parts):
        if label == "pref" and i + 1 < len(parts):
            cand = parts[i + 1]
            if cand in PREF_ROMAJI:
                out.prefecture = PREF_ROMAJI[cand]
                out.source = "url"
                return out
        if label in ("city", "town", "vill", "village") and i + 1 < len(parts):
            # city.<name>.<pref>.lg.jp -- pref is the next-next label only if
            # it is a romaji prefecture key. Otherwise fall through.
            after = parts[i + 1 :]
            for j in range(len(after)):
                cand = after[j]
                if cand in PREF_ROMAJI:
                    out.prefecture = PREF_ROMAJI[cand]
                    out.source = "url"
                    break
            # We do NOT invent a Japanese municipality from romaji here. If
            # the URL gives us a prefecture but no match against am_region,
            # leave municipality None.
            return out

    return out


def extract_from_name(
    name: str | None, idx: RegionIndex, url_prefecture: str | None = None
) -> Extracted:
    """Pull prefecture + municipality from the program name.

    Strategy:
        1. If name contains an explicit prefecture (北海道..沖縄県), record it.
        2. Scan for <name>市/町/村/区. Reject candidates whose stem is NOT in
           am_region (so '事業区' or '対象区域' do not fabricate a place).
        3. If multiple municipalities of the same name exist (中央区 etc.),
           only accept when the prefecture is already pinned by step 1 or by
           the URL.
        4. 23-ku of Tokyo are accepted only when 東京都 (or tokyo URL) is
           known, since the bare ku names alone are ambiguous.
    """
    out = Extracted()
    if not name:
        return out

    # Step 1: prefecture mention.
    pref_match = PREF_PATTERN.search(name)
    name_pref: str | None = pref_match.group(1) if pref_match else None
    if name_pref:
        out.prefecture = name_pref

    # Effective prefecture for muni disambiguation: prefer name signal, then URL.
    eff_pref = name_pref or url_prefecture
    eff_pref_code = idx.pref_by_name[eff_pref][:2] if eff_pref in idx.pref_by_name else None

    # Step 2: municipality scan. Strip the prefecture itself from the search
    # text so '東京都中央区' yields '中央区' (a bare 23-ku) rather than the
    # composite '東京都中央区' which is not in am_region.
    search_text = name
    if name_pref:
        search_text = search_text.replace(name_pref, " ")

    candidates = MUNI_PATTERN.findall(search_text)
    # Try longest candidates first: longer strings are less likely to be a
    # spurious match like "事業区".
    candidates.sort(key=len, reverse=True)

    chosen: str | None = None
    for cand in candidates:
        # Designated-ward bare form ("中央区") under a known designated city
        # parent in the same name? E.g. "札幌市中央区" sets 札幌市 first, then
        # 中央区 is its ward. We handle the joint form explicitly.
        if eff_pref == "東京都" and cand in TOKYO_23_WARDS:
            chosen = cand
            break

        # 23-ku without a Tokyo anchor is rejected.
        if cand in TOKYO_23_WARDS and eff_pref != "東京都":
            continue

        # Bare ambiguous ku (中央区/北区...) without a prefecture anchor: skip.
        if cand in AMBIGUOUS_BARE_WARDS and eff_pref_code is None:
            continue

        # Must exist in am_region.
        prefs = idx.name_to_pref.get(cand)
        if not prefs:
            continue

        if len(prefs) == 1:
            (only_pref_code,) = prefs
            chosen = cand
            if not out.prefecture:
                # Anchor prefecture from a uniquely-named muni.
                # Look up name_ja for that pref code via reverse map.
                for pn, pc in idx.pref_by_name.items():
                    if pc[:2] == only_pref_code:
                        out.prefecture = pn
                        break
            break

        if eff_pref_code and eff_pref_code in prefs:
            chosen = cand
            break
        # Multiple prefectures, no anchor -> skip silently.

    if chosen:
        out.municipality = chosen

    if out.prefecture or out.municipality:
        out.source = "name"
    return out


def merge(name_ext: Extracted, url_ext: Extracted) -> tuple[Extracted, str]:
    """Combine name and URL signals, return (merged, confidence)."""
    pref = name_ext.prefecture or url_ext.prefecture
    muni = name_ext.municipality or url_ext.municipality

    sources = []
    if name_ext.prefecture or name_ext.municipality:
        sources.append("name")
    if url_ext.prefecture or url_ext.municipality:
        sources.append("url")

    merged = Extracted(prefecture=pref, municipality=muni, source="+".join(sources))

    # Confidence rubric.
    if "name" in sources and "url" in sources:
        # Cross-check: if both name and URL claim a prefecture and they agree,
        # 'high'. If they disagree, downgrade to 'medium' and prefer name.
        if name_ext.prefecture and url_ext.prefecture and name_ext.prefecture != url_ext.prefecture:
            confidence = "medium"
            merged.prefecture = name_ext.prefecture
        else:
            confidence = "high"
    elif sources:
        confidence = "medium"
    else:
        confidence = "low"

    if pref == "全国" or (pref is None and muni is None):
        confidence = "low"

    return merged, confidence


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def iter_programs(db_path: Path, only_missing: bool, limit: int | None) -> Iterable[sqlite3.Row]:
    # immutable=1: see RegionIndex.load comment. Read-only across the scan.
    con = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    try:
        sql = "SELECT unified_id, primary_name, source_url, prefecture, municipality FROM programs"
        if only_missing:
            sql += (
                " WHERE (prefecture IS NULL OR prefecture = '')"
                "    OR (municipality IS NULL OR municipality = '')"
            )
        if limit:
            sql += f" LIMIT {int(limit)}"
        yield from con.execute(sql)
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default="data/jpintel.db",
        help="Path to jpintel.db (read-only). Default: data/jpintel.db",
    )
    parser.add_argument(
        "--region-db",
        default="autonomath.db",
        help="DB containing am_region. Default: autonomath.db",
    )
    parser.add_argument(
        "--out",
        default="analysis_wave18/prefecture_municipality_backfill_2026-05-01.csv",
        help="Output CSV path.",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--all-rows",
        action="store_true",
        help="Scan every program, not only those with NULL prefecture/municipality.",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db).resolve()
    region_db_path = Path(args.region_db).resolve()
    out_path = Path(args.out).resolve()

    if not db_path.exists():
        print(f"ERROR: programs DB not found: {db_path}", file=sys.stderr)
        return 2

    idx = RegionIndex.load(region_db_path)

    rows: list[dict[str, str]] = []
    stats = Counter()
    confidence_dist = Counter()

    for row in iter_programs(db_path, only_missing=not args.all_rows, limit=args.limit):
        url_ext = extract_from_url(row["source_url"], idx)
        name_ext = extract_from_name(row["primary_name"], idx, url_prefecture=url_ext.prefecture)
        merged, confidence = merge(name_ext, url_ext)

        stats["total_scanned"] += 1
        if merged.prefecture:
            stats["prefecture_extracted"] += 1
        if merged.municipality:
            stats["municipality_extracted"] += 1
        if merged.prefecture or merged.municipality:
            stats["any_extracted"] += 1
        confidence_dist[confidence] += 1

        # Skip writing rows where we have nothing new to offer.
        cur_pref = row["prefecture"] or ""
        cur_muni = row["municipality"] or ""
        if (merged.prefecture in (None, "", cur_pref)) and (
            merged.municipality in (None, "", cur_muni)
        ):
            continue

        rows.append(
            {
                "program_id": row["unified_id"],
                "primary_name": row["primary_name"] or "",
                "source_url": row["source_url"] or "",
                "current_prefecture": cur_pref,
                "extracted_prefecture": merged.prefecture or "",
                "current_municipality": cur_muni,
                "extracted_municipality": merged.municipality or "",
                "confidence": confidence,
            }
        )

    print("--- B13 prefecture/municipality back-fill scan ---")
    print(f"  total_scanned       = {stats['total_scanned']}")
    print(f"  prefecture_extracted= {stats['prefecture_extracted']}")
    print(f"  municipality_extracted={stats['municipality_extracted']}")
    print(f"  any_extracted       = {stats['any_extracted']}")
    print(f"  rows_for_csv        = {len(rows)}")
    print("  confidence:")
    for c in ("high", "medium", "low"):
        print(f"    {c:6s} = {confidence_dist[c]}")

    if args.dry_run:
        print("(--dry-run: CSV NOT written)")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "program_id",
        "primary_name",
        "source_url",
        "current_prefecture",
        "extracted_prefecture",
        "current_municipality",
        "extracted_municipality",
        "confidence",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print(f"  wrote {len(rows)} rows -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
