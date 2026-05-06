"""DEEP-18 identity_confidence floor — provisional calculator (DEEP-64 calibration).

Spec source
-----------
``tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_18_identity_confidence_floor.md``

This module implements the DEEP-18 score function in pure Python so that the
DEEP-64 1,200-entry golden set can drive accuracy assertions before the
canonical ``db/identity_confidence.py`` module lands. Only stdlib imports —
NO LLM API. Once DEEP-18 is wired into ``db/`` the calibration tests in
``tests/test_identity_confidence_golden.py`` will swap their import target
without touching the fixture or assertions.

Score table (DEEP-18 §1)
------------------------

| query_kind            | bangou_exact | kana_eq | legal_form | addr_eq | score |
|-----------------------|--------------|---------|------------|---------|-------|
| houjin_bangou_exact   | True         | -       | -          | -       | 1.00  |
| kana_normalized       | False        | True    | True       | True    | 0.95  |
| legal_form_variant    | False        | True    | True       | False   | 0.92  |
| partial_with_address  | False        | True    | False      | True    | 0.85  |
| partial_only          | False        | True    | False      | False   | 0.65  |
| alias_only            | False        | False   | False      | False   | 0.55  |

Default floor: 0.75. Sensitive-tool floors: 0.80-0.90 (DEEP-18 §1 seed).

No-LLM invariant
----------------

Only ``unicodedata`` + ``re`` from stdlib. Any anthropic/openai/google import
here is a regression caught by ``tests/test_no_llm_in_production.py``.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# DEEP-18 §1 axis score table — the 6 query_kind values are the calibration
# axes for DEEP-64. Each axis has a single canonical score.
AXIS_SCORE: dict[str, float] = {
    "houjin_bangou_exact": 1.00,
    "kana_normalized": 0.95,
    "legal_form_variant": 0.92,
    "partial_with_address": 0.85,
    "partial_only": 0.65,
    "alias_only": 0.55,
}

# DEEP-18 §1 seed floor table.
DEFAULT_FLOOR = 0.75
SENSITIVE_FLOORS: dict[str, float] = {
    "search_invoice_by_houjin_partial": 0.90,
    "check_enforcement_am": 0.90,
    "get_houjin_360_am": 0.90,
    "list_edinet_disclosures": 0.85,
    "search_corporate_entities": 0.80,
    "houjin_master_resolve": 0.75,
}

# Legal-form variants — used both for normalization in axis 3 and for the
# generator producing the DEEP-64 fixture. Kana variants are included so
# axis 2 (kana_normalized) can fold legal-form prefixes when one side is
# rendered in hiragana / katakana while the other is in kanji.
LEGAL_FORM_TOKENS: tuple[str, ...] = (
    "株式会社",
    "(株)",
    "(株)",
    "㈱",
    "合同会社",
    "(同)",
    "(同)",
    "㈿",
    "有限会社",
    "(有)",
    "(有)",
    "㈲",
    "合資会社",
    "(資)",
    "(資)",
    "合名会社",
    "(名)",
    "(名)",
    "一般社団法人",
    "一般財団法人",
    "公益社団法人",
    "公益財団法人",
    "社会福祉法人",
    "学校法人",
    "宗教法人",
    "医療法人",
    "特定非営利活動法人",
    "NPO法人",
)

# Kana renderings of the same legal forms — applied AFTER kana_fold (so
# katakana form is canonical). Listed longest-first so substrings are
# stripped predictably.
LEGAL_FORM_TOKENS_KANA: tuple[str, ...] = (
    "トクテイヒエイリカツドウホウジン",
    "イッパンザイダンホウジン",
    "イッパンシャダンホウジン",
    "コウエキザイダンホウジン",
    "コウエキシャダンホウジン",
    "シャカイフクシホウジン",
    "ガッコウホウジン",
    "シュウキョウホウジン",
    "イリョウホウジン",
    "カブシキガイシャ",
    "ゴウドウガイシャ",
    "ユウゲンガイシャ",
    "ゴウシガイシャ",
    "ゴウメイガイシャ",
    "NPOホウジン",
)

_HOUJIN_BANGOU_RE = re.compile(r"^\d{13}$")


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def normalize_text(s: str) -> str:
    """NFKC + lower + strip — single canonical form for comparison."""
    if s is None:
        return ""
    return unicodedata.normalize("NFKC", str(s)).strip().lower()


def strip_legal_form(s: str) -> str:
    """Drop legal-form prefix/suffix tokens, return bare brand string.

    Strips both kanji forms and kana renderings of the same forms so the
    output is symmetric across hiragana / katakana / kanji inputs.
    """
    out = s
    for token in LEGAL_FORM_TOKENS:
        out = out.replace(token, "")
    return out.strip()


def strip_legal_form_kana(s: str) -> str:
    """Strip kana legal-form tokens (apply AFTER kana_fold)."""
    out = s
    for token in LEGAL_FORM_TOKENS_KANA:
        out = out.replace(token.lower(), "")
        out = out.replace(token, "")
    return out.strip()


def kana_fold(s: str) -> str:
    """Hiragana <-> Katakana fold, half-width <-> full-width via NFKC.

    Pure stdlib (unicodedata.normalize). For the 1,200-entry calibration
    fixture this is enough — production code will use jaconv.
    """
    n = unicodedata.normalize("NFKC", s)
    out = []
    for ch in n:
        cp = ord(ch)
        # Hiragana U+3041..U+3096 -> Katakana U+30A1..U+30F6
        if 0x3041 <= cp <= 0x3096:
            out.append(chr(cp + 0x60))
        else:
            out.append(ch)
    return "".join(out).lower().strip()


def is_valid_houjin_bangou(s: str) -> bool:
    return bool(_HOUJIN_BANGOU_RE.match(str(s).strip()))


# ---------------------------------------------------------------------------
# Axis detection + score
# ---------------------------------------------------------------------------


def detect_axis(
    query: str,
    candidate: dict[str, Any],
) -> str:
    """Map a (query, candidate) pair to one of 6 DEEP-18 axes.

    candidate keys (any subset, all optional):
      - houjin_bangou: 13-digit string
      - houjin_name:   raw company name
      - address_match: bool (whether query+candidate carry the same prefecture+municipality)
      - alias_only:    bool (alias-table hit, not name-match)

    Resolution order matches DEEP-18 §1 priority:
      1. houjin_bangou_exact (both sides 13-digit, identical)
      2. alias_only (explicit alias-table hit, no name overlap)
      3. kana_normalized (kana fold equal AFTER stripping legal form, addr_match=True)
      4. legal_form_variant (kana fold equal AFTER stripping legal form, addr_match=False)
      5. partial_with_address (substring match + addr_match=True)
      6. partial_only (substring match + addr_match=False)
    """
    q = normalize_text(query)
    cand_bangou = (candidate.get("houjin_bangou") or "").strip()
    cand_name = normalize_text(candidate.get("houjin_name") or "")
    addr_match = bool(candidate.get("address_match"))
    alias_only_flag = bool(candidate.get("alias_only"))

    # Axis 1: 13-digit on both sides + identical
    if is_valid_houjin_bangou(q) and is_valid_houjin_bangou(cand_bangou):
        if q == cand_bangou:
            return "houjin_bangou_exact"

    # Axis 6: explicit alias_only flag
    if alias_only_flag:
        return "alias_only"

    if not cand_name:
        return "alias_only"

    # Compare bare brand (legal form stripped) under kana fold.
    # Two-pass strip: strip kanji legal forms BEFORE kana fold, kana legal
    # forms AFTER kana fold. This catches mixed-script inputs like
    # 「カブシキガイシャ + brand」 (axis 2 hiragana/halfwidth) and
    # 「(株) + brand」 (axis 3) symmetrically.
    q_bare = strip_legal_form_kana(kana_fold(strip_legal_form(q)))
    c_bare = strip_legal_form_kana(kana_fold(strip_legal_form(cand_name)))

    if q_bare and c_bare and q_bare == c_bare:
        # whole-name equal modulo legal form + kana
        if addr_match:
            return "kana_normalized"
        return "legal_form_variant"

    # Substring (partial) match
    if q_bare and c_bare and (q_bare in c_bare or c_bare in q_bare):
        if addr_match:
            return "partial_with_address"
        return "partial_only"

    return "alias_only"


def score(query: str, candidate: dict[str, Any]) -> tuple[float, str, dict[str, Any]]:
    """Return (score, axis, axes_dict) per DEEP-18 §1 table.

    axes_dict mirrors the schema in migration wave24_185_identity_confidence_floor.sql
    (column ``axes_json``).
    """
    axis = detect_axis(query, candidate)
    s = AXIS_SCORE[axis]

    cand_bangou = (candidate.get("houjin_bangou") or "").strip()
    cand_name = normalize_text(candidate.get("houjin_name") or "")
    q = normalize_text(query)
    q_bare = strip_legal_form_kana(kana_fold(strip_legal_form(q)))
    c_bare = strip_legal_form_kana(kana_fold(strip_legal_form(cand_name)))

    legal_form_active = (
        strip_legal_form(q) != q
        or strip_legal_form(cand_name) != cand_name
        or strip_legal_form_kana(kana_fold(q)) != kana_fold(q)
        or strip_legal_form_kana(kana_fold(cand_name)) != kana_fold(cand_name)
    )

    axes_dict: dict[str, Any] = {
        "bangou_exact": is_valid_houjin_bangou(q)
        and is_valid_houjin_bangou(cand_bangou)
        and q == cand_bangou,
        "kana_eq": bool(q_bare and c_bare and q_bare == c_bare),
        "legal_form_variant": bool(q_bare and c_bare and q_bare == c_bare)
        and legal_form_active,
        "addr_eq": bool(candidate.get("address_match")),
        "alias_only": axis == "alias_only",
    }
    return s, axis, axes_dict


def gate(
    tool_name: str,
    candidates: list[tuple[str, dict[str, Any]]],
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """Apply tool-specific floor. Returns (kept, dropped, gaps)."""
    floor = SENSITIVE_FLOORS.get(tool_name, DEFAULT_FLOOR)
    kept: list[dict[str, Any]] = []
    dropped = 0
    for query, cand in candidates:
        s, axis, axes_dict = score(query, cand)
        if s >= floor:
            kept.append(
                {
                    **cand,
                    "_identity_confidence": s,
                    "_identity_axes": axes_dict,
                    "_identity_axis": axis,
                }
            )
        else:
            dropped += 1
    gaps: list[str] = []
    if dropped:
        gaps.append(f"{dropped} low confidence matches excluded (floor={floor:.2f})")
    return kept, dropped, gaps


__all__ = [
    "AXIS_SCORE",
    "DEFAULT_FLOOR",
    "LEGAL_FORM_TOKENS",
    "LEGAL_FORM_TOKENS_KANA",
    "SENSITIVE_FLOORS",
    "detect_axis",
    "gate",
    "is_valid_houjin_bangou",
    "kana_fold",
    "normalize_text",
    "score",
    "strip_legal_form",
    "strip_legal_form_kana",
]
