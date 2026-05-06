"""Match placeholder program IDs in research/non_agri_exclusions_draft.json
to real ``unified_id``s from the ``programs`` table in data/jpintel.db.

Heuristic stack (per placeholder token):
  1. Direct lookup — if the placeholder is already a ``UNI-xxx`` string that
     exists in ``programs``, accept (confidence 1.0).
  2. Manual keyword map (PLACEHOLDER_TO_KEYWORD) — each known placeholder is
     mapped to one or more regex-ish patterns against ``primary_name``. First
     hit wins at confidence 0.8.
  3. Fuzzy match (``difflib.get_close_matches``) on normalized primary names
     + aliases. Accept only when ratio >= 0.5, scored 0.5.

Confidence threshold to accept a match: 0.7. Anything below is marked
unmatched.

Condition tags (not programs) are hard-coded in CONDITION_TAGS and marked
with ``skip_reason: condition_state`` so they never try to match.

Writes:
  research/non_agri_matched.json     — draft rules with unified_id + confidence
  research/non_agri_unmatched.md     — report of unmatched placeholders
"""

from __future__ import annotations

import difflib
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "jpintel.db"
DRAFT_PATH = ROOT / "research" / "non_agri_exclusions_draft.json"
MATCHED_OUT = ROOT / "research" / "non_agri_matched.json"
UNMATCHED_OUT = ROOT / "research" / "non_agri_unmatched.md"

CONFIDENCE_THRESHOLD = 0.7


# Condition tags — states/flags that are NOT programs.
# These should never match; rules that reference these need a schema extension.
CONDITION_TAGS: set[str] = {
    # duplicate-self markers
    "it-hojo-2025-tsujyo-dup",
    "mono-hojo-22-ji-dup-plan",
    "ryouritsu-jujuan-sentakuken-seido-dup",
    "koyou-kankei-josei-any-dup",
    "seisansei-suite-any-minashi-dup",
    # state / condition flags
    "dismissal-or-wage-cut",
    "hojokin-de-hofuku-sareta-bubun",
    "pre-issue-date-contracts",
    "new-establishment-less-1y",
    "zero-employee",
    "taxable-income-15oku-plus",
    "minashi-daikigyou-owned",
    "keiei-shokei-not-within-5y",
    "gyoumu-kaizen-past-drop",
    "jizokuka-past-report-pending",
    "jizokuka-sotsugyo-done",
    "jigyo-saikouchiku-canceled",
    "jigyoka-joukyo-chizaiken-houkoku",
    "jigyoka-joukyo-houkoku-keiei-hikitsugi",
    "ma-fa-chukai-same-rep",
    "shouhizei-kanpukin",
    "tokyo-sogyo-josei-past-recipient",
    # "national umbrella" tokens (refer to "any other national subsidy", no single program)
    "national-other-subsidy",
    "national-other-subsidy-same-expense",
    "national-other-subsidy-same-subject",
    "national-other-subsidy-or-similar",
    "national-or-local-same-expense",
    "national-sogyo-josei-same-cost",
    # synthetic aggregates (not a single program)
    "seisansei-revol-same-object",
    "seisansei-revol-suite-16m",
    "seisansei-suite-16m",
    "seisansei-suite-3y-2x",
    "seisansei-suite-unsettled",
    "seisansei-suite-any",
    "it-hojo-2023-2024-process",
    "mono-hojo-past-2x-3y",
    # process/role tokens
    "it-hojo-2025-support-vendor",
    "it-hojo-2025-recipient",
    "ma14-experts-or-pmi",
    # medical/insurance umbrella tokens
    "medical-care-insurance-payment",
    "iryou-hoken",
    "kaigo-hoken",
    "kotei-kaitori",
    # prerequisite tokens (not programs)
    "nintei-keiei-kakushin-shien-kikan",
    "nintei-keiei-kakushin-shien-kikan-kakunin",
    "nintei-keiei-kakushin-shien-kikan-or-kinyu",
    "shokokai-shoukoukaigisho-shien-keikakusho",
    "keieiryoku-koujou-keikaku-nintei",
    "sentan-setsubi-donyu-keikaku-nintei",
    # tax credit pairings (may be programs, but opaque ref)
    "other-tokubetsu-shoukyaku-or-koujo",
    # Tokyo programs not present in DB
    "tokyo-shoutengai-shoukei-shien",
    "tokyo-wakate-joseileader",
    "tokyo-shoten-wakate-josei",
    # koyou umbrella / not-individual-program
    "koyou-kankei-josei-any",
    # ikuji umbrella
    "ikukyu-kyufu-kojin",
    # kanko-jinzai-busoku (観光地人材不足) is a JTA program — not in programs table; mark as unmatchable
    "kanko-jinzai-busoku",
}


# Manual keyword map: placeholder -> list of regex patterns against primary_name.
# First match wins at confidence 0.8. Prefer the most specific pattern first.
PLACEHOLDER_TO_KEYWORD: dict[str, list[str]] = {
    # IT
    "it-hojo-2025-tsujyo": [r"^IT導入補助金$", r"IT導入補助金", r"デジタル化・AI導入補助金"],
    "it-hojo-2024-tsujyo": [r"IT導入補助金2024", r"^IT導入補助金$", r"IT導入補助金"],
    "it-hojo-2024-fukususha": [r"IT導入補助金2024.*複数", r"IT導入補助金2024", r"IT導入補助金"],
    "it-hojo-cybersec-otasuke": [
        r"IT導入補助金2024（セキュリティ対策推進枠）",
        r"IT導入補助金.*セキュリティ",
    ],
    # Monozukuri
    "mono-hojo-22-ji": [
        r"ものづくり・商業・サービス生産性向上促進補助金$",
        r"^ものづくり補助金$",
        r"^ものづくり補助金（一般型）$",
        r"ものづくり補助金",
    ],
    "mono-hojo": [
        r"ものづくり・商業・サービス生産性向上促進補助金$",
        r"^ものづくり補助金$",
        r"ものづくり補助金",
    ],
    # Saikouchiku
    "jigyo-saikouchiku-13": [
        r"^事業再構築補助金$",
        r"事業再構築補助金（成長枠）",
        r"事業再構築補助金",
    ],
    "jigyo-saikouchiku": [r"^事業再構築補助金$", r"事業再構築補助金"],
    # Shoryokuka
    "shoryokuka-ippan-5": [r"中小企業省力化投資補助金（一般型）", r"中小企業省力化投資補助金"],
    "shoryokuka-ippan": [r"中小企業省力化投資補助金（一般型）", r"中小企業省力化投資補助金"],
    # Shinjigyou
    "shinjigyou-shinshutsu-2": [
        r"中小企業新事業進出補助金",
        r"^新事業進出補助金$",
        r"新事業進出補助金",
    ],
    "shinjigyou-shinshutsu": [r"中小企業新事業進出補助金", r"新事業進出補助金"],
    # Jizokuka
    "jizokuka-ippan-tsujyo-19": [
        r"小規模事業者持続化補助金（一般型 通常枠）",
        r"小規模事業者持続化補助金",
    ],
    "jizokuka-ippan-tsujyo": [
        r"小規模事業者持続化補助金（一般型 通常枠）",
        r"小規模事業者持続化補助金",
    ],
    "jizokuka-ippan": [r"小規模事業者持続化補助金（一般型 通常枠）", r"小規模事業者持続化補助金"],
    "jizokuka-sogyo-3": [r"小規模事業者持続化補助金"],
    "jizokuka-sogyo": [r"小規模事業者持続化補助金"],
    # M&A
    "ma14-succession": [r"事業承継・M&A補助金"],
    "ma14-experts": [r"事業承継・M&A補助金"],
    "ma14-pmi": [r"事業承継・M&A補助金"],
    # Seicho kasoku
    "seicho-kasoku": [r"中小企業成長加速化補助金"],
    # Koyou
    "koyouchousei-kyuugyou": [r"^雇用調整助成金$"],
    "career-up-seisyain": [r"キャリアアップ助成金（正社員化コース）", r"^キャリアアップ助成金$"],
    "career-up-shougai-shuusyokusha": [r"キャリアアップ助成金（障害者正社員化コース）"],
    "ryouritsu-shusseji-dai1shu": [
        r"両立支援等助成金（出生時両立支援コース）",
        r"両立支援等助成金",
    ],
    "ryouritsu-shusseji-dai2shu": [
        r"両立支援等助成金（出生時両立支援コース）",
        r"両立支援等助成金",
    ],
    "ryouritsu-ikuji-kyugyou-shien": [
        r"両立支援等助成金（育児休業等支援コース）",
        r"両立支援等助成金",
    ],
    "ryouritsu-ikukyu-shutokuji": [
        r"両立支援等助成金（育児休業等支援コース）",
        r"両立支援等助成金",
    ],
    "ryouritsu-jujuan-sentakuken-seido": [r"両立支援等助成金"],
    "sangyo-koyou-antei-sangyourenkei": [r"産業雇用安定助成金（産業連携人材確保等支援コース）"],
    "trial-koyou-ippan": [
        r"トライアル雇用助成金（一般トライアルコース）",
        r"^トライアル雇用助成金$",
    ],
    "tokuteikyuushokusha-koyou-kaihatsu": [
        r"^特定求職者雇用開発助成金$",
        r"特定求職者雇用開発助成金",
    ],
    "gyoumu-kaizen-r8": [r"^業務改善助成金$"],
    # Tax
    "chusho-kyoka-zeisei": [r"^中小企業経営強化税制$"],
    "chusho-toushi-sokushin-zeisei": [r"^中小企業投資促進税制$"],
    "chinage-sokushin-zeisei-chusho": [r"賃上げ促進税制"],
    "kenkyukaihatsu-zeigaku-koujo": [r"研究開発税制"],
    "kotei-shisan-tokurei-sentan": [r"先端設備等導入計画"],
    # Tokyo
    "tokyo-sogyo-josei-r8": [r"東京都創業助成事業"],
}


def normalize(s: str) -> str:
    """Normalize for fuzzy match: lowercase, strip punctuation/whitespace."""
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"[\s　\(\)（）\[\]【】,．、。・]+", "", s)
    return s


def load_programs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT unified_id, primary_name, aliases_json FROM programs").fetchall()
    programs: list[dict[str, Any]] = []
    for uid, name, aliases_json in rows:
        aliases: list[str] = []
        if aliases_json:
            try:
                parsed = json.loads(aliases_json)
                if isinstance(parsed, list):
                    aliases = [a for a in parsed if isinstance(a, str)]
            except json.JSONDecodeError:
                pass
        programs.append(
            {
                "unified_id": uid,
                "primary_name": name or "",
                "aliases": aliases,
                "normalized": normalize(name or ""),
                "alias_normalized": [normalize(a) for a in aliases],
            }
        )
    return programs


def match_placeholder(
    placeholder: str,
    programs: list[dict[str, Any]],
    unified_id_set: set[str],
) -> tuple[str | None, float, str]:
    """Return (unified_id or None, confidence, method).

    method: one of "direct", "keyword", "fuzzy", "condition", "no_match".
    """
    if not placeholder:
        return None, 0.0, "no_match"

    # Condition tags short-circuit
    if placeholder in CONDITION_TAGS:
        return None, 0.0, "condition"

    # 1. Direct UNI-xxx lookup
    if placeholder.startswith("UNI-") and placeholder in unified_id_set:
        return placeholder, 1.0, "direct"

    # 2. Manual keyword map
    patterns = PLACEHOLDER_TO_KEYWORD.get(placeholder)
    if patterns:
        for pat in patterns:
            regex = re.compile(pat)
            # First: try to match "primary_name anchored" (exact match) — prefer shorter names
            exact_hits: list[dict[str, Any]] = []
            for p in programs:
                if regex.search(p["primary_name"]):
                    exact_hits.append(p)
            if exact_hits:
                # Prefer shortest primary_name (most canonical: avoid prefectural overlays)
                exact_hits.sort(key=lambda p: (len(p["primary_name"]), p["unified_id"]))
                return exact_hits[0]["unified_id"], 0.8, "keyword"

    # 3. Fuzzy match on primary_name
    # Use placeholder tokens split on hyphen as a synthetic query
    tokens = placeholder.split("-")
    joined = "".join(tokens).lower()
    name_to_uid: dict[str, str] = {}
    candidates: list[str] = []
    for p in programs:
        if not p["normalized"]:
            continue
        candidates.append(p["normalized"])
        name_to_uid.setdefault(p["normalized"], p["unified_id"])
    close = difflib.get_close_matches(joined, candidates, n=1, cutoff=0.5)
    if close:
        return name_to_uid[close[0]], 0.5, "fuzzy"

    return None, 0.0, "no_match"


def main() -> int:
    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}", file=sys.stderr)
        return 1
    if not DRAFT_PATH.exists():
        print(f"Draft not found: {DRAFT_PATH}", file=sys.stderr)
        return 1

    draft = json.loads(DRAFT_PATH.read_text(encoding="utf-8"))
    print(f"loaded {len(draft)} draft rules")

    conn = sqlite3.connect(str(DB_PATH))
    try:
        programs = load_programs(conn)
        unified_id_set = {p["unified_id"] for p in programs}
        print(f"loaded {len(programs)} programs from DB")

        matched_out: list[dict[str, Any]] = []
        unmatched: dict[str, dict[str, Any]] = {}  # placeholder -> details

        per_rule_stats = {"fully_matched": 0, "partial": 0, "none": 0}

        for rule in draft:
            new_rule = dict(rule)  # shallow copy

            a_placeholder = rule.get("program_a") or ""
            b_placeholder = rule.get("program_b") or ""

            a_uid, a_conf, a_method = match_placeholder(a_placeholder, programs, unified_id_set)
            b_uid, b_conf, b_method = match_placeholder(b_placeholder, programs, unified_id_set)

            # Replace IDs if a confident match exists; otherwise keep the placeholder.
            new_rule["program_a"] = a_uid if (a_conf >= CONFIDENCE_THRESHOLD) else a_placeholder
            new_rule["program_b"] = b_uid if (b_conf >= CONFIDENCE_THRESHOLD) else b_placeholder
            new_rule["match_confidence_a"] = a_conf
            new_rule["match_confidence_b"] = b_conf
            new_rule["match_method_a"] = a_method
            new_rule["match_method_b"] = b_method

            # Track stats
            a_ok = a_conf >= CONFIDENCE_THRESHOLD
            b_ok = b_conf >= CONFIDENCE_THRESHOLD
            if a_ok and b_ok:
                per_rule_stats["fully_matched"] += 1
            elif a_ok or b_ok:
                per_rule_stats["partial"] += 1
            else:
                per_rule_stats["none"] += 1

            # Log unmatched placeholders
            for ph, conf, method in (
                (a_placeholder, a_conf, a_method),
                (b_placeholder, b_conf, b_method),
            ):
                if not ph:
                    continue
                if conf >= CONFIDENCE_THRESHOLD:
                    continue
                entry = unmatched.setdefault(
                    ph,
                    {
                        "placeholder": ph,
                        "rules": [],
                        "skip_reason": None,
                    },
                )
                entry["rules"].append(
                    {
                        "rule_id": rule.get("rule_id", "?"),
                        "desc": (rule.get("description") or "")[:160],
                    }
                )
                if method == "condition" and entry["skip_reason"] is None:
                    entry["skip_reason"] = "condition_state"

            matched_out.append(new_rule)

        MATCHED_OUT.write_text(
            json.dumps(matched_out, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {MATCHED_OUT}")

        # Write unmatched report
        lines: list[str] = [
            "# Non-agri exclusion — unmatched placeholders",
            "",
            f"Generated by `scripts/match_non_agri_ids.py`. Placeholders that could not be resolved to a `unified_id` with confidence >= {CONFIDENCE_THRESHOLD}.",
            "",
            f"Total unique unmatched placeholders: **{len(unmatched)}**",
            "",
            "| Placeholder | Reason | First rule | Description (truncated) |",
            "|-------------|--------|------------|--------------------------|",
        ]
        for ph in sorted(unmatched.keys()):
            entry = unmatched[ph]
            reason = entry["skip_reason"] or "no_match"
            first = entry["rules"][0] if entry["rules"] else {"rule_id": "?", "desc": ""}
            desc_clean = (first["desc"] or "").replace("|", "/").replace("\n", " ")
            lines.append(f"| `{ph}` | {reason} | `{first['rule_id']}` | {desc_clean} |")
        lines.append("")
        lines.append("## Per-rule outcome summary")
        lines.append("")
        lines.append(
            f"- Fully matched (both program_a AND program_b >= {CONFIDENCE_THRESHOLD}): **{per_rule_stats['fully_matched']}**"
        )
        lines.append(f"- Partially matched (one side resolved): **{per_rule_stats['partial']}**")
        lines.append(f"- Neither side matched: **{per_rule_stats['none']}**")
        lines.append("")
        UNMATCHED_OUT.write_text("\n".join(lines), encoding="utf-8")
        print(f"wrote {UNMATCHED_OUT}")

        # stdout summary
        print()
        print(f"fully matched rules: {per_rule_stats['fully_matched']}")
        print(f"partial matches:     {per_rule_stats['partial']}")
        print(f"unmatched rules:     {per_rule_stats['none']}")
        print(f"unique unmatched placeholders: {len(unmatched)}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
