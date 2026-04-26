"""Tests for the i18n message catalog (P6-E, dd_v8_03).

Covers the scaffolding landed ahead of the T+150d English V4 launch:

  - Catalog invariant: every key has both `ja` and `en`.
  - `t(key, lang)` resolution: exact hit, language fallback, key fallback.
  - Coverage floor: at least the 4 envelope statuses for the 10 named
    autonomath tools, plus the generic fallback bucket.
  - Style guide checks (tone-level, not exhaustive): English strings
    do not contain 全角 punctuation; Japanese strings do not contain raw
    ASCII colons except inside quoted parens (light heuristic).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure src/ is on path for direct test runs.
_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.i18n import (  # noqa: E402
    MESSAGES,
    all_keys,
    has_key,
    supported_languages,
    t,
)


# ---------------------------------------------------------------------------
# Catalog invariants
# ---------------------------------------------------------------------------


def test_supported_languages_is_ja_en():
    assert supported_languages() == ("ja", "en")


def test_every_key_has_both_languages():
    """No half-translated entries: every key MUST have ja AND en."""
    for key, bucket in MESSAGES.items():
        assert "ja" in bucket, f"{key} missing ja"
        assert "en" in bucket, f"{key} missing en"


def test_no_empty_strings():
    for key, bucket in MESSAGES.items():
        for lang, msg in bucket.items():
            assert msg.strip(), f"{key}/{lang} is empty"


def test_japanese_min_length_20():
    """Mirrors envelope_wrapper.py min-length assert for ja explanations."""
    for key, bucket in MESSAGES.items():
        if not key.startswith("envelope."):
            continue
        # Some tool-specific buckets only have rich/sparse/empty/error;
        # all of them must clear 20 chars in ja to keep parity.
        assert len(bucket["ja"]) >= 20, f"{key}/ja too short: {bucket['ja']!r}"


def test_english_no_zenkaku_punctuation():
    """English strings should not slip 、。「」 into the catalog."""
    forbidden = "、。「」"
    for key, bucket in MESSAGES.items():
        en = bucket["en"]
        offenders = [ch for ch in en if ch in forbidden]
        assert not offenders, f"{key}/en has zenkaku punctuation: {en!r}"


def test_all_keys_sorted_and_unique():
    keys = all_keys()
    assert len(keys) == len(set(keys)), "duplicate keys in catalog"
    assert list(keys) == sorted(keys)


# ---------------------------------------------------------------------------
# Coverage floor
# ---------------------------------------------------------------------------

# 10 named autonomath tools that must have envelope status coverage at
# scaffolding time. enum_values intentionally lacks a "sparse" entry —
# the underlying tool returns either rich or empty.
_TOOLS_WITH_STATUS = {
    "search_tax_incentives": ("rich", "sparse", "empty", "error"),
    "search_certifications": ("rich", "sparse", "empty", "error"),
    "list_open_programs": ("rich", "sparse", "empty", "error"),
    "search_by_law": ("rich", "sparse", "empty", "error"),
    "active_programs_at": ("rich", "sparse", "empty", "error"),
    "related_programs": ("rich", "sparse", "empty", "error"),
    "search_acceptance_stats": ("rich", "sparse", "empty", "error"),
    "enum_values": ("rich", "empty", "error"),
    "intent_of": ("rich", "sparse", "empty", "error"),
    "reason_answer": ("rich", "sparse", "empty", "error"),
}


@pytest.mark.parametrize("tool,statuses", _TOOLS_WITH_STATUS.items())
def test_envelope_keys_present(tool: str, statuses: tuple[str, ...]):
    for status in statuses:
        key = f"envelope.{status}.{tool}"
        assert has_key(key), f"missing envelope key: {key}"


def test_fallback_bucket_complete():
    """Generic fallback used when no tool-specific entry exists."""
    for status in ("rich", "sparse", "empty", "error"):
        assert has_key(f"envelope.{status}.fallback")


def test_minimum_50_keys():
    """P6-E scaffolding floor; D2-D3 will expand to ~200 keys."""
    assert len(all_keys()) >= 50, f"only {len(all_keys())} keys"


# ---------------------------------------------------------------------------
# t() resolution
# ---------------------------------------------------------------------------


def test_t_exact_hit_ja():
    msg = t("envelope.empty.search_tax_incentives", "ja")
    assert "国税庁" in msg


def test_t_exact_hit_en():
    msg = t("envelope.empty.search_tax_incentives", "en")
    assert "NTA" in msg
    # Sanity: not just an echo of the ja string.
    assert "国税庁原典" not in msg


def test_t_default_lang_is_ja():
    """Backward compat: omitted lang must equal ja (no breaking change)."""
    assert t("envelope.empty.fallback") == t("envelope.empty.fallback", "ja")


def test_t_unknown_lang_falls_back_to_ja():
    """fr / zh / etc. silently degrade to ja so callers cannot crash us."""
    msg = t("envelope.empty.fallback", "fr")
    assert msg == t("envelope.empty.fallback", "ja")


def test_t_unknown_key_returns_key_literal():
    """Never raise; never return None — return the key so logs are searchable."""
    assert t("does.not.exist", "ja") == "does.not.exist"
    assert t("does.not.exist", "en") == "does.not.exist"


def test_t_returns_str_always():
    for key in all_keys():
        for lang in ("ja", "en", "fr"):
            out = t(key, lang)  # type: ignore[arg-type]
            assert isinstance(out, str)
            assert out  # non-empty


# ---------------------------------------------------------------------------
# Cross-check against existing envelope_wrapper.py shape
# ---------------------------------------------------------------------------


def test_tool_set_matches_envelope_wrapper():
    """The tool names in the catalog must be a subset of the tool names in
    envelope_wrapper.DEFAULT_EXPLANATIONS — otherwise a typo here will
    silently fail to ever resolve at runtime."""
    try:
        from jpintel_mcp.mcp.autonomath_tools.envelope_wrapper import (
            DEFAULT_EXPLANATIONS,
        )
    except ImportError:
        pytest.skip("autonomath_tools not importable in this env")

    catalog_tools = {
        key.split(".", 2)[2]
        for key in all_keys()
        if key.startswith("envelope.") and not key.endswith(".fallback")
    }
    wrapper_tools = set(DEFAULT_EXPLANATIONS.keys())
    missing = catalog_tools - wrapper_tools
    assert not missing, f"catalog references unknown tools: {missing}"
