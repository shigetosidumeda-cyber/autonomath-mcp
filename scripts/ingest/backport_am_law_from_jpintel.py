#!/usr/bin/env python3
"""Back-port jpintel.db `laws` → autonomath.db `am_law` (T-11d reconciliation).

See eval: analysis_wave18/data_collection_log/p1_eval_law_backport.md

Purpose:
  1. Extend am_law (249 → ~750) with 500 laws from jpintel.db in business-critical
     domains (tax/SME/labor/environment/agriculture).
  2. Fix e_gov_lawid digit mistakes in existing am_law rows (jpintel ground truth).

Constraints:
  * 2 DB open, NO ATTACH.
  * jpintel.db opened read-only.
  * autonomath.db write under BEGIN IMMEDIATE, busy_timeout=300000.
  * No external API / network (Anthropic API prohibited per CLAUDE.md constraint).
  * Existing am_law rows preserved — INSERT OR IGNORE on canonical_id collision.
  * Slug generation uses pykakasi (Hepburn) + Japanese keyword heuristics.
  * Deterministic: re-run is idempotent.

CLI:
  python scripts/ingest/backport_am_law_from_jpintel.py --dry-run
  python scripts/ingest/backport_am_law_from_jpintel.py --apply
  python scripts/ingest/backport_am_law_from_jpintel.py --apply --limit 500
  python scripts/ingest/backport_am_law_from_jpintel.py --fix-egov-only
"""

from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

try:
    import pykakasi
except ImportError:
    print("missing dep: pykakasi. pip install pykakasi", file=sys.stderr)
    sys.exit(1)

_LOG = logging.getLogger("autonomath.backport_am_law")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"

# -----------------------------------------------------------------------------
# Kanji → arabic conversion for law_number normalization
# -----------------------------------------------------------------------------

_K2A_DIGIT = {
    "〇": 0,
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def kanji_to_int(s: str) -> int:
    """Convert Japanese kanji numeral to int (supports 〇-千万 range)."""
    digits: list[tuple[str, int]] = []
    for ch in s:
        if ch in _K2A_DIGIT:
            digits.append(("d", _K2A_DIGIT[ch]))
        elif ch == "十":
            digits.append(("十", 10))
        elif ch == "百":
            digits.append(("百", 100))
        elif ch == "千":
            digits.append(("千", 1000))
        elif ch == "万":
            digits.append(("万", 10000))
    val, current_block, i = 0, 0, 0
    while i < len(digits):
        kind, v = digits[i]
        if kind == "d":
            if i + 1 < len(digits) and digits[i + 1][0] in ("十", "百", "千"):
                current_block += v * digits[i + 1][1]
                i += 2
            elif i + 1 < len(digits) and digits[i + 1][0] == "万":
                current_block += v
                val += current_block * 10000
                current_block = 0
                i += 2
            else:
                current_block += v
                i += 1
        elif kind in ("十", "百", "千"):
            current_block += v  # bare 十 = 10
            i += 1
        elif kind == "万":
            if current_block == 0:
                current_block = 1
            val += current_block * 10000
            current_block = 0
            i += 1
    val += current_block
    return val


def normalize_law_number(s: str | None) -> str | None:
    """'昭和四十年法律第三十四号' → '昭和40年法律第34号'."""
    if not s:
        return s
    m = re.match(r"^(令和|平成|昭和|大正|明治)([〇零一二三四五六七八九十百千]+)年(.+)$", s)
    if not m:
        return s
    era, year_k, rest = m.group(1), m.group(2), m.group(3)
    try:
        year = kanji_to_int(year_k)
    except Exception:
        return s

    def repl(m2: re.Match[str]) -> str:
        try:
            return f"第{kanji_to_int(m2.group(1))}号"
        except Exception:
            return m2.group(0)

    rest2 = re.sub(r"第([〇零一二三四五六七八九十百千万]+)号", repl, rest)
    return f"{era}{year}年{rest2}"


# -----------------------------------------------------------------------------
# Slug generation (Hepburn + keyword heuristics)
# -----------------------------------------------------------------------------

_KKS = pykakasi.kakasi()

# common legal term abbreviations that make slugs more distinctive/human-readable
_SLUG_OVERRIDES = {
    # none pre-specified; rely on first-N tokens of law_title
}

# strip trailing legal suffixes before slugification to get clean keyword
_SUFFIX_STRIPS = (
    "等に関する法律",
    "に関する法律",
    "等に関する政令",
    "に関する政令",
    "等に関する命令",
    "に関する命令",
    "等に関する省令",
    "に関する省令",
    "に関する特別措置法",
    "特別措置法",
)


def _strip_brackets(s: str) -> str:
    """Remove anything inside 〈〉() in legal title."""
    return re.sub(r"[（(].+?[)）]", "", s).strip()


def title_to_slug(title: str, max_tokens: int = 3) -> str:
    """Convert Japanese law title to Hepburn-slug (lowercase, hyphen-separated).

    Examples:
        中小企業基本法 → 'chusho-kihon'
        食料・農業・農村基本法 → 'shokuryo-nogyo-noson'
        関税法 → 'kanzei'
    """
    t = _strip_brackets(title)
    # strip boilerplate suffix
    for suf in _SUFFIX_STRIPS:
        if t.endswith(suf):
            t = t[: -len(suf)]
            break
    # also strip bare 法/令/規則 if the remaining stem is >=2 chars
    for suf in ("施行令", "施行規則"):
        if t.endswith(suf) and len(t) > len(suf) + 1:
            t = t[: -len(suf)]
    # tokenise via pykakasi
    tokens: list[str] = []
    for tok in _KKS.convert(t):
        orig = tok["orig"]
        heb = tok["hepburn"].lower()
        if not heb or not heb.isascii():
            continue
        # skip pure-ASCII separators, punctuation, digits
        if not re.match(r"^[a-z]+$", heb):
            continue
        # skip helper particles that result in 1-char meaningless token
        if len(heb) <= 1:
            continue
        # strip long vowels (ou/uu) that pykakasi leaves literal — keep first form
        heb = heb.replace("uu", "u").replace("oo", "o").replace("ou", "o")
        tokens.append(heb)
        if len(tokens) >= max_tokens:
            break
    if not tokens:
        # fallback to keyword from raw title if kanji only
        return "law-unknown"
    return "-".join(tokens)


# -----------------------------------------------------------------------------
# Category inference from title
# -----------------------------------------------------------------------------

_CATEGORY_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"税|関税|印紙|酒税|たばこ|登録免許|地方税|租税条約"), "税制"),
    (re.compile(r"中小企業|商工|下請"), "産業政策"),
    (re.compile(r"労働|雇用|安全衛生|労災|最低賃金"), "労働"),
    (re.compile(r"省エネ|エネルギー|温暖化|温室効果|脱炭素|水素"), "環境"),
    (re.compile(r"廃棄物|リサイクル|資源|循環"), "環境"),
    (re.compile(r"農業|農地|食料|漁業|林業|農林|畜産|農村"), "農業"),
    (re.compile(r"商工会"), "産業政策"),
    (re.compile(r"建設|建築|都市計画|道路|河川|港湾"), "建設"),
    (re.compile(r"医療|医薬|薬事|健康|福祉|介護|年金"), "保健"),
    (re.compile(r"消費者|景品表示|特定商取引|消費生活"), "消費者"),
    (re.compile(r"観光|旅行|ホテル|旅館"), "観光"),
    (re.compile(r"運輸|交通|航空|船舶|鉄道|港湾"), "運輸"),
    (re.compile(r"情報|通信|電気通信|放送|電波"), "情報"),
    (re.compile(r"金融|銀行|保険|証券"), "金融"),
    (re.compile(r"教育|学校|学術"), "教育"),
    (re.compile(r"文化|文化財|博物館|著作"), "文化"),
]


def infer_category(title: str) -> str:
    for pat, cat in _CATEGORY_KEYWORDS:
        if pat.search(title):
            return cat
    return ""


# -----------------------------------------------------------------------------
# Ministry inference (best-effort — limited info from jpintel)
# -----------------------------------------------------------------------------

_MINISTRY_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"関税|国税|財務|税"), "mof-nta"),
    (re.compile(r"中小企業|商工|産業|経済"), "meti"),
    (re.compile(r"労働|雇用|健康|医療|介護|年金|厚生|薬"), "mhlw"),
    (re.compile(r"農業|農地|食料|漁業|林業|農林|畜産|農村"), "maff"),
    (re.compile(r"環境|廃棄物|リサイクル|温暖化|温室"), "moe"),
    (re.compile(r"建設|建築|道路|都市計画|河川|港湾|運輸|航空|鉄道|住宅"), "mlit"),
    (re.compile(r"教育|学校|学術|文化"), "mext"),
    (re.compile(r"情報|通信|電気通信|放送"), "soumu"),
    (re.compile(r"金融|銀行|証券"), "fsa"),
    (re.compile(r"消費者|景品表示"), "caa"),
    (re.compile(r"個人情報"), "ppc"),
]


def infer_ministry(title: str) -> str | None:
    for pat, m in _MINISTRY_KEYWORDS:
        if pat.search(title):
            return m
    return None


# -----------------------------------------------------------------------------
# e-Gov LawID extraction from URL
# -----------------------------------------------------------------------------

_URL_ID_RE = re.compile(r"/law/([A-Za-z0-9]+)$")


def extract_egov_id(full_text_url: str | None) -> str | None:
    if not full_text_url:
        return None
    m = _URL_ID_RE.search(full_text_url)
    return m.group(1) if m else None


# -----------------------------------------------------------------------------
# Selection query
# -----------------------------------------------------------------------------

SELECT_CANDIDATES_SQL = """
SELECT unified_id, law_title, law_number, law_type, ministry,
       enforced_date, promulgated_date, last_amended_date,
       revision_status, full_text_url, source_url
FROM laws
ORDER BY
  CASE WHEN law_type='act' THEN 0
       WHEN law_type='cabinet_order' THEN 1
       ELSE 2 END,
  CASE WHEN revision_status='current' THEN 0 ELSE 1 END,
  CASE WHEN (law_title LIKE '%税%' OR law_title LIKE '%中小企業%') THEN 0 ELSE 1 END,
  enforced_date DESC
LIMIT ?;
"""


# -----------------------------------------------------------------------------
# e_gov_lawid digit-mistake detector
# -----------------------------------------------------------------------------


def find_egov_digit_fixes(
    jp: sqlite3.Connection, am: sqlite3.Connection
) -> list[tuple[str, str, str, str]]:
    """Return list of (canonical_id, canonical_name, wrong_egov_id, correct_egov_id).

    Match by normalized-law-number first; verify via title exact match against jpintel.
    Only returns title-exact matches — ambiguous cases are skipped (logged separately).
    """
    jp_rows = jp.execute("""
        SELECT unified_id, law_title, law_number, full_text_url
          FROM laws
         WHERE revision_status = 'current'
    """).fetchall()
    # build lookup: (normalized_law_number, title) -> egov_id
    title_num_to_id: dict[tuple[str, str], str] = {}
    for uid, title, lno, url in jp_rows:
        egov = extract_egov_id(url)
        if not egov:
            continue
        nlno = normalize_law_number(lno) or ""
        title_num_to_id[(nlno, title)] = egov
    # also pure-title lookup for fallback
    title_only: dict[str, list[str]] = {}
    for uid, title, lno, url in jp_rows:
        egov = extract_egov_id(url)
        if egov:
            title_only.setdefault(title, []).append(egov)

    mismatches = []
    for r in am.execute("""
        SELECT canonical_id, canonical_name, law_number, e_gov_lawid
          FROM am_law
         WHERE e_gov_lawid IS NOT NULL AND e_gov_lawid != ''
    """):
        cid, title, am_lno, am_id = r
        # probe 1: exact normalized lno + title
        correct = title_num_to_id.get((am_lno or "", title))
        if correct is None:
            # probe 2: title-only (only when single candidate)
            cands = title_only.get(title, [])
            if len(cands) == 1:
                correct = cands[0]
        if correct and correct != am_id:
            mismatches.append((cid, title, am_id, correct))
    return mismatches


# -----------------------------------------------------------------------------
# Main back-port logic
# -----------------------------------------------------------------------------


def run_backport(limit: int, dry_run: bool) -> tuple[int, int, int]:
    """Return (inserted, skipped_dup_canonical, skipped_dup_egov)."""
    jp = sqlite3.connect(f"file:{JPINTEL_DB}?mode=ro", uri=True)
    jp.row_factory = sqlite3.Row
    am = sqlite3.connect(str(AUTONOMATH_DB))
    am.execute("PRAGMA busy_timeout = 300000")

    # fetch existing am_law canonical_ids and e_gov_lawids
    existing_slugs = {row[0] for row in am.execute("SELECT canonical_id FROM am_law")}
    existing_egov = {
        row[0]
        for row in am.execute(
            "SELECT e_gov_lawid FROM am_law WHERE e_gov_lawid IS NOT NULL AND e_gov_lawid != ''"
        )
    }
    _LOG.info(
        "am_law existing: canonical_id=%d, e_gov_lawid=%d", len(existing_slugs), len(existing_egov)
    )

    rows = jp.execute(SELECT_CANDIDATES_SQL, (limit,)).fetchall()
    _LOG.info("jp candidates fetched: %d", len(rows))

    # build de-dup: generate slugs, skip those already in am_law (via e_gov_lawid first, then slug)
    to_insert: list[dict[str, Any]] = []
    slug_seen: set[str] = set(existing_slugs)
    skipped_egov = 0
    skipped_slug = 0

    for r in rows:
        egov = extract_egov_id(r["full_text_url"])
        if egov and egov in existing_egov:
            skipped_egov += 1
            continue
        title = r["law_title"]
        base_slug = title_to_slug(title)
        slug = f"law:{base_slug}"
        suffix = 2
        while slug in slug_seen:
            slug = f"law:{base_slug}_{suffix}"
            suffix += 1
            if suffix > 100:
                break
        if slug in slug_seen:
            # Fall back to unified_id-suffix for guaranteed uniqueness
            slug = f"law:{base_slug}-{r['unified_id'].lower()}"
        if slug in slug_seen:
            skipped_slug += 1
            continue
        slug_seen.add(slug)
        # status mapping
        status = "active" if r["revision_status"] == "current" else r["revision_status"]
        to_insert.append(
            {
                "canonical_id": slug,
                "canonical_name": title,
                "short_name": None,
                "law_number": normalize_law_number(r["law_number"]),
                "category": infer_category(title),
                "first_enforced": r["enforced_date"],
                "egov_url": r["full_text_url"],
                "status": status,
                "note": None,
                "ministry": infer_ministry(title),
                "effective_from": r["enforced_date"],
                "last_amended_at": r["last_amended_date"],
                "subject_areas_json": None,
                "e_gov_lawid": egov,
            }
        )

    _LOG.info(
        "prepared insert: %d (skipped egov-dup=%d, slug-conflict=%d)",
        len(to_insert),
        skipped_egov,
        skipped_slug,
    )

    if dry_run:
        # sample 10
        for row in to_insert[:10]:
            _LOG.info(
                "sample INSERT: %s | %s | %s | %s | %s",
                row["canonical_id"],
                row["canonical_name"][:30],
                row["law_number"],
                row["category"],
                row["e_gov_lawid"],
            )
        jp.close()
        am.close()
        return (len(to_insert), skipped_egov, skipped_slug)

    # apply
    try:
        am.execute("BEGIN IMMEDIATE")
        inserted = 0
        for row in to_insert:
            try:
                am.execute(
                    """
                    INSERT INTO am_law (
                        canonical_id, canonical_name, short_name, law_number,
                        category, first_enforced, egov_url, status, note,
                        ministry, effective_from, last_amended_at,
                        subject_areas_json, e_gov_lawid
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(canonical_id) DO NOTHING
                """,
                    (
                        row["canonical_id"],
                        row["canonical_name"],
                        row["short_name"],
                        row["law_number"],
                        row["category"],
                        row["first_enforced"],
                        row["egov_url"],
                        row["status"],
                        row["note"],
                        row["ministry"],
                        row["effective_from"],
                        row["last_amended_at"],
                        row["subject_areas_json"],
                        row["e_gov_lawid"],
                    ),
                )
                if am.total_changes > inserted:
                    inserted += 1
            except sqlite3.IntegrityError as e:
                _LOG.warning("IntegrityError for %s: %s", row["canonical_id"], e)
        am.commit()
        _LOG.info("inserted: %d rows", inserted)
    except Exception:
        am.rollback()
        raise
    finally:
        jp.close()
        am.close()

    return (len(to_insert), skipped_egov, skipped_slug)


def run_egov_fix(dry_run: bool) -> tuple[int, int]:
    """Return (mismatches_found, fixed)."""
    jp = sqlite3.connect(f"file:{JPINTEL_DB}?mode=ro", uri=True)
    am = sqlite3.connect(str(AUTONOMATH_DB))
    am.execute("PRAGMA busy_timeout = 300000")

    mismatches = find_egov_digit_fixes(jp, am)
    _LOG.info("e_gov_lawid mismatches found: %d", len(mismatches))

    for cid, title, wrong, correct in mismatches:
        _LOG.info("  %s | %s | %s -> %s", cid, title[:25], wrong, correct)

    if dry_run or not mismatches:
        jp.close()
        am.close()
        return (len(mismatches), 0)

    try:
        am.execute("BEGIN IMMEDIATE")
        fixed = 0
        for cid, title, wrong, correct in mismatches:
            am.execute(
                "UPDATE am_law SET e_gov_lawid = ? WHERE canonical_id = ? AND e_gov_lawid = ?",
                (correct, cid, wrong),
            )
            if am.total_changes > fixed:
                fixed += 1
        am.commit()
        _LOG.info("e_gov_lawid fixed: %d", fixed)
    except Exception:
        am.rollback()
        raise
    finally:
        jp.close()
        am.close()

    return (len(mismatches), fixed)


def verify_post(expected_min: int) -> dict[str, Any]:
    """Final verification after mutation. Reopens autonomath.db read-only."""
    am = sqlite3.connect(f"file:{AUTONOMATH_DB}?mode=ro", uri=True)
    stats = {}
    stats["am_law_count"] = am.execute("SELECT COUNT(*) FROM am_law").fetchone()[0]
    stats["am_law_with_egov"] = am.execute(
        "SELECT COUNT(*) FROM am_law WHERE e_gov_lawid IS NOT NULL AND e_gov_lawid != ''"
    ).fetchone()[0]
    stats["am_law_with_ministry"] = am.execute(
        "SELECT COUNT(*) FROM am_law WHERE ministry IS NOT NULL AND ministry != ''"
    ).fetchone()[0]
    stats["orphan_ref"] = am.execute("""
        SELECT COUNT(*) FROM am_law_reference
         WHERE law_canonical_id IS NOT NULL
           AND law_canonical_id NOT IN (SELECT canonical_id FROM am_law)
    """).fetchone()[0]
    ok = am.execute("PRAGMA integrity_check").fetchone()[0]
    stats["integrity_check"] = ok
    am.close()
    stats["meets_target"] = stats["am_law_count"] >= expected_min
    return stats


# -----------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="print without writing")
    p.add_argument("--apply", action="store_true", help="write to am_law")
    p.add_argument("--limit", type=int, default=500, help="max rows to back-port")
    p.add_argument(
        "--fix-egov-only", action="store_true", help="only run the e_gov_lawid digit-mistake pass"
    )
    p.add_argument("--backport-only", action="store_true", help="only run the back-port pass")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if not args.dry_run and not args.apply:
        _LOG.error("specify --dry-run or --apply")
        return 2

    dry = args.dry_run and not args.apply

    run_backport_flag = not args.fix_egov_only
    run_fix_flag = not args.backport_only

    backport_stats = None
    fix_stats = None
    if run_backport_flag:
        backport_stats = run_backport(args.limit, dry_run=dry)
    if run_fix_flag:
        fix_stats = run_egov_fix(dry_run=dry)

    if not dry:
        stats = verify_post(expected_min=650)
        _LOG.info("POST STATS: %s", stats)
    if backport_stats:
        _LOG.info("backport_stats: to_insert=%d, skipped_egov=%d, skipped_slug=%d", *backport_stats)
    if fix_stats:
        _LOG.info("fix_stats: found=%d, fixed=%d", *fix_stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
