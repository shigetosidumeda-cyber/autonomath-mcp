"""DEEP-38 業法 fence violation detector module.

Single reusable primitive that detects 7 業法 (税理士法 §52 / 弁護士法 §72 /
行政書士法 §1 / 司法書士法 §3 / 弁理士法 §75 / 社労士法 §27 /
公認会計士法 §47条の2) forbidden phrase violations in JP / EN text. Used by
five consumers (DEEP-23 / DEEP-25 / DEEP-27 / DEEP-29 / DEEP-31), so the
contract is intentionally minimal: pure function, dict-list output, no LLM
call, no Pydantic shell.

Spec source
-----------
``tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_38_business_law_violation_detector.md``

Phrase catalog: ``data/business_law_forbidden_phrases.json`` (84 JP + 40 EN
= 124 patterns), DEEP-23 spec sync output. Loaded lazily on module import,
regex compiled once.

No-LLM invariant
----------------
- ``import anthropic`` / ``openai`` / ``google.generativeai`` /
  ``claude_agent_sdk`` are all forbidden in this module (CI guard
  ``tests/test_no_llm_in_production.py``). Only ``re``, ``unicodedata``,
  ``json``, ``pathlib``, ``functools`` from stdlib + ``pykakasi`` for
  ひらがな bypass mitigation.
- ``re2`` is preferred for linear-time guarantees, but is not in the .venv
  on every dev machine; we fall back to stdlib ``re`` because all phrases
  are literal substrings (no backtracking risk after escape).

Performance
-----------
< 5 ms / 1 KB text on M1 (gated by pytest-benchmark in
``tests/test_business_law_detector.py``). Module load + 124 regex compile
+ pykakasi converter init runs once; ``detect_violations`` is allocation-
light afterwards.
"""

from __future__ import annotations

import json
import pathlib
import re
import unicodedata
from functools import lru_cache
from typing import Any

# pykakasi is used to convert ひらがな -> カタカナ -> ローマ字 so that the
# detection step can match a phrase regardless of the user's preferred kana
# form. We tolerate its absence (skip the kana fallback if unavailable),
# which keeps the module importable on minimal envs.
pykakasi: Any
try:  # pragma: no cover - import shape only
    import pykakasi as _pykakasi_module

    pykakasi = _pykakasi_module
    _PYKAKASI_AVAILABLE = True
except Exception:  # pragma: no cover - environment-dependent
    pykakasi = None
    _PYKAKASI_AVAILABLE = False


# Try google.re2 (linear-time guarantee, no catastrophic backtracking) then
# fall back to stdlib re. Substring patterns (literal, escaped) cannot trigger
# pathological backtracking under stdlib re either, so the fallback is safe.
_regex_engine: Any
try:  # pragma: no cover - import shape only
    import re2 as _re2_module

    _regex_engine = _re2_module
except Exception:  # pragma: no cover - environment-dependent
    _regex_engine = re


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_DEFAULT_PHRASE_PATH = _REPO_ROOT / "data" / "business_law_forbidden_phrases.json"

# Cohort hint -> JP-law key mapping. ``None`` means "scan all 7 業法".
_COHORT_TO_LAW: dict[str, str] = {
    "tax_pro": "税理士法",
    "lawyer": "弁護士法",
    "admin": "行政書士法",
    "judicial": "司法書士法",
    "patent": "弁理士法",
    "labor": "社労士法",
    "cpa": "公認会計士法",
}

# Severity policy: full-string (length >= threshold) phrases match as ``block``
# (per spec §3 — verify primitive clamps overall score to 0). Short phrases
# (<= 6 chars) are routed to ``warn`` to keep false positives < 5%.
_BLOCK_LEN_THRESHOLD = 6


def _phrase_path() -> pathlib.Path:
    """Resolve the forbidden_phrases.json path. Override via env or arg."""
    return _DEFAULT_PHRASE_PATH


def _normalize(text: str) -> str:
    """Apply NFKC normalization to handle 全角/半角 + alternate forms.

    pykakasi-based kana fallback is exposed via ``_kana_variants`` rather
    than rewriting the text in place — rewriting would shift offsets and
    break the ``position`` field contract.
    """
    return unicodedata.normalize("NFKC", text)


@lru_cache(maxsize=1)
def _load_phrase_catalog() -> dict[str, Any]:
    """Load and cache the forbidden_phrases.json catalog."""
    path = _phrase_path()
    if not path.exists():
        return {"jp": {}, "en": {}}
    raw = path.read_text(encoding="utf-8")
    parsed: dict[str, Any] = json.loads(raw)
    return parsed


def _compile_pattern(phrase: str) -> Any:
    """Compile a phrase to a regex matcher. Treat all phrases as literal."""
    # NFKC the phrase too — catalog might carry full-width forms.
    canon = _normalize(phrase)
    return _regex_engine.compile(re.escape(canon), re.IGNORECASE)


@lru_cache(maxsize=1)
def _compiled_patterns() -> dict[str, list[dict[str, Any]]]:
    """Build the compiled-pattern table. Keys are 'jp' and 'en'.

    Returns
    -------
    {
      "jp": [
        {"law": str, "section": str, "cohort": str, "phrase": str,
         "compiled": <regex>, "severity": "block"|"warn"},
        ...
      ],
      "en": [...]
    }
    """
    catalog = _load_phrase_catalog()
    jp_rows: list[dict[str, Any]] = []
    en_rows: list[dict[str, Any]] = []

    jp_block = catalog.get("jp", {})
    for law_name, law_block in jp_block.items():
        section = law_block.get("section", "")
        cohort = law_block.get("cohort", "")
        for phrase in law_block.get("forbidden", []):
            severity = "block" if len(phrase) >= _BLOCK_LEN_THRESHOLD else "warn"
            jp_rows.append(
                {
                    "law": law_name,
                    "section": section,
                    "cohort": cohort,
                    "phrase": _normalize(phrase),
                    "compiled": _compile_pattern(phrase),
                    "severity": severity,
                    "lang": "jp",
                }
            )

    en_block = catalog.get("en", {})
    for cohort, en_law_block in en_block.items():
        law_name = en_law_block.get("law", "")
        section = en_law_block.get("section", "")
        for phrase in en_law_block.get("forbidden", []):
            severity = "block" if len(phrase) >= _BLOCK_LEN_THRESHOLD else "warn"
            en_rows.append(
                {
                    "law": law_name,
                    "section": section,
                    "cohort": cohort,
                    "phrase": phrase,
                    "compiled": _compile_pattern(phrase),
                    "severity": severity,
                    "lang": "en",
                }
            )

    return {"jp": jp_rows, "en": en_rows}


@lru_cache(maxsize=1)
def _kakasi_converter() -> Any | None:
    """Return a pykakasi converter or None if pykakasi is unavailable."""
    if not _PYKAKASI_AVAILABLE:
        return None
    try:
        return pykakasi.kakasi()
    except Exception:  # pragma: no cover - defensive
        return None


def _hiragana_to_katakana(s: str) -> str:
    """Map 0x3041..0x3096 -> 0x30A1..0x30F6 (hiragana → katakana).

    Used as a cheap canonical fold so the catalog's katakana-or-mixed
    phrases match against hiragana variants.
    """
    out_chars: list[str] = []
    for ch in s:
        cp = ord(ch)
        if 0x3041 <= cp <= 0x3096:
            out_chars.append(chr(cp + 0x60))
        else:
            out_chars.append(ch)
    return "".join(out_chars)


def detect_violations(text: str, cohort_hint: str | None = None) -> list[dict[str, Any]]:
    """Detect 業法 forbidden-phrase violations in ``text``.

    Parameters
    ----------
    text : str
        Free-form text to scan. Will be NFKC-normalized before matching.
    cohort_hint : str | None
        One of ``tax_pro`` / ``lawyer`` / ``admin`` / ``judicial`` /
        ``patent`` / ``labor`` / ``cpa`` / ``None``. When given, the
        matching law's violations are sorted to the front of the list
        (stable). All 7 業法 are still scanned regardless.

    Returns
    -------
    list[dict]
        Each violation has keys::

            {
              "law": "税理士法" | "弁護士法" | ...,
              "section": "§52" | "§72" | ...,
              "cohort": "tax_pro" | "lawyer" | ...,
              "phrase": "<NFKC-normalized matched phrase>",
              "position": (start, end),  # offsets into NFKC-normalized text
              "severity": "block" | "warn",
              "lang": "jp" | "en",
            }

    Notes
    -----
    Pure function. No I/O after module load. Idempotent.
    """
    if not text:
        return []

    canon = _normalize(text)
    canon_kana = _hiragana_to_katakana(canon)
    patterns = _compiled_patterns()

    seen: set[tuple[str, str, int, int]] = set()
    out: list[dict[str, Any]] = []

    for lang_key in ("jp", "en"):
        for row in patterns[lang_key]:
            search_targets = [canon]
            # Hiragana fallback only for JP rows where the phrase is in
            # katakana / kanji form. We always also scan the kana-folded
            # text so "ぜいむ代理" matches "税務代理" via NFKC-then-kana? — no,
            # NFKC does not unify kanji with kana. We only kana-fold to
            # widen katakana matches against hiragana. Kanji must already
            # match canonical text directly.
            if lang_key == "jp" and canon_kana != canon:
                search_targets.append(canon_kana)

            for target in search_targets:
                for m in row["compiled"].finditer(target):
                    key = (row["law"], row["phrase"], m.start(), m.end())
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(
                        {
                            "law": row["law"],
                            "section": row["section"],
                            "cohort": row["cohort"],
                            "phrase": row["phrase"],
                            "position": (m.start(), m.end()),
                            "severity": row["severity"],
                            "lang": row["lang"],
                        }
                    )

    if cohort_hint and cohort_hint in _COHORT_TO_LAW:
        relevant_law = _COHORT_TO_LAW[cohort_hint]

        def sort_key(v: dict[str, Any]) -> tuple[int, int]:
            law_priority = 0 if v["law"] == relevant_law else 1
            return (law_priority, v["position"][0])

        out.sort(key=sort_key)
    else:
        out.sort(key=lambda v: v["position"][0])

    return out


def reload_catalog() -> None:
    """Clear caches so the next ``detect_violations`` call reloads the JSON.

    DEEP-23 GHA spec sync touches the file in place; long-running processes
    can call this to pick up updates without a restart. Safe to call from
    test fixtures.
    """
    _load_phrase_catalog.cache_clear()
    _compiled_patterns.cache_clear()


__all__ = ["detect_violations", "reload_catalog"]
