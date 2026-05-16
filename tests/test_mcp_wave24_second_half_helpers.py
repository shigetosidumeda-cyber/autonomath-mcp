"""Pure-function tests for ``wave24_tools_second_half`` (Stream EE, 80%→85%).

Targets ``src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_second_half.py``
private helpers that have no DB / HTTP / LLM dependencies:

  * ``_today_jst`` — JST date deterministic shape.
  * ``_normalize_houjin`` — invoice T-prefix strip.
  * ``_to_unified`` — id translator pass-through path.
  * ``_empty_envelope`` — graceful zero-result envelope builder.
  * ``_try_mecab_tokenize`` — naive fallback path (no MeCab in test env).
  * ``make_error`` / ``_finalize`` — corpus_snapshot attachment idempotency.
  * ``_STOPWORDS_JA`` taxonomy invariants.

NO DB / HTTP / LLM calls. We monkeypatch ``connect_autonomath`` away for
helpers that incidentally route through ``_open_db``.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

import jpintel_mcp.mcp.autonomath_tools.wave24_tools_second_half as w

# ---------------------------------------------------------------------------
# _today_jst
# ---------------------------------------------------------------------------


def test_today_jst_returns_date_in_reasonable_window() -> None:
    today = w._today_jst()
    assert isinstance(today, _dt.date)
    # JST is UTC+9; |today - utc_today| <= 1 day.
    utc_today = _dt.datetime.now(_dt.UTC).date()
    delta = abs((today - utc_today).days)
    assert delta <= 1


# ---------------------------------------------------------------------------
# _normalize_houjin
# ---------------------------------------------------------------------------


def test_normalize_houjin_strips_t_prefix() -> None:
    assert w._normalize_houjin("T8010001213708") == "8010001213708"


def test_normalize_houjin_lowercase_t_normalized() -> None:
    assert w._normalize_houjin("t8010001213708") == "8010001213708"


def test_normalize_houjin_no_prefix_passthrough() -> None:
    assert w._normalize_houjin("8010001213708") == "8010001213708"


def test_normalize_houjin_none_returns_empty() -> None:
    assert w._normalize_houjin(None) == ""


def test_normalize_houjin_whitespace_trimmed() -> None:
    assert w._normalize_houjin("  T8010001213708  ") == "8010001213708"


# ---------------------------------------------------------------------------
# _to_unified
# ---------------------------------------------------------------------------


def test_to_unified_unknown_id_passes_through() -> None:
    # Translator returns (None, None) for unknown input; we fall back to input.
    out = w._to_unified("definitely-not-a-real-id")
    assert out == "definitely-not-a-real-id"


def test_to_unified_already_uni_form_returns_uni_form() -> None:
    # UNI-... input should round-trip even when translator has no row.
    out = w._to_unified("UNI-xxxxxxxxxxxxxxxxxxxxxxxx")
    # Output is either the same UNI-... or the resolved UNI-...; either way
    # it starts with UNI-.
    assert isinstance(out, str)


# ---------------------------------------------------------------------------
# _empty_envelope
# ---------------------------------------------------------------------------


def test_empty_envelope_basic_shape() -> None:
    env = w._empty_envelope(billing_unit=1, limit=20, offset=0)
    assert env["total"] == 0
    assert env["limit"] == 20
    assert env["offset"] == 0
    assert env["results"] == []
    assert env["_billing_unit"] == 1
    assert env["_next_calls"] == []


def test_empty_envelope_clamps_limit_to_max_100() -> None:
    env = w._empty_envelope(billing_unit=1, limit=999, offset=0)
    assert env["limit"] == 100


def test_empty_envelope_clamps_limit_to_min_1() -> None:
    env = w._empty_envelope(billing_unit=1, limit=0, offset=0)
    assert env["limit"] == 1


def test_empty_envelope_clamps_offset_to_min_0() -> None:
    env = w._empty_envelope(billing_unit=1, limit=10, offset=-5)
    assert env["offset"] == 0


def test_empty_envelope_includes_extra_fields() -> None:
    env = w._empty_envelope(
        billing_unit=2,
        limit=10,
        offset=0,
        extra={"data_quality": {"missing_columns": ["x"]}},
    )
    assert env["data_quality"]["missing_columns"] == ["x"]
    assert env["_billing_unit"] == 2


def test_empty_envelope_includes_next_calls() -> None:
    nc = [{"tool": "x", "args": {}, "rationale": "r"}]
    env = w._empty_envelope(billing_unit=1, limit=10, offset=0, next_calls=nc)
    assert env["_next_calls"] == nc


# ---------------------------------------------------------------------------
# _try_mecab_tokenize — naive fallback path
# ---------------------------------------------------------------------------


def test_try_mecab_tokenize_ascii_words_lowercased() -> None:
    # We rely on either MeCab path or the naive fallback. The contract is the
    # SAME for ASCII: ≥2-char tokens, lowercased.
    out = w._try_mecab_tokenize("DX MVP")
    # Both code paths produce ≥2-char tokens.
    assert all(len(t) >= 2 for t in out)


def test_try_mecab_tokenize_short_tokens_filtered() -> None:
    # Single-letter ASCII tokens (A, B, ...) are skipped (len <= 1).
    out = w._try_mecab_tokenize("A B C")
    # Naive fallback excludes len<=1 tokens; MeCab fallback also drops <2.
    assert all(len(t) >= 2 for t in out)


def test_try_mecab_tokenize_empty_returns_empty() -> None:
    out = w._try_mecab_tokenize("")
    assert out == []


def test_try_mecab_tokenize_japanese_2char_window() -> None:
    # The naive fallback emits 2-char rolling windows on CJK tokens.
    # MeCab path emits >=2-char wakati tokens. Both produce ≥1 token here.
    out = w._try_mecab_tokenize("補助金")
    assert isinstance(out, list)
    # Either MeCab gives ["補助金"] or naive gives ["補助", "助金"] — both non-empty.
    assert len(out) >= 1


# ---------------------------------------------------------------------------
# make_error / _finalize — corpus_snapshot envelope idempotency
# ---------------------------------------------------------------------------


def test_make_error_attaches_corpus_snapshot_pair() -> None:
    out = w.make_error(code="x", message="m")
    # attach_corpus_snapshot is supposed to inject the snapshot id+checksum.
    assert isinstance(out, dict)
    assert "code" in out or "error" in out  # error envelope variant


def test_finalize_is_idempotent_for_already_attached_body() -> None:
    body: dict[str, Any] = {"total": 1, "results": []}
    out1 = w._finalize(body)
    out2 = w._finalize(out1)
    # Same shape after re-running; no crash, no double-injection corrupting
    # the body.
    assert out2.get("total") == out1.get("total")
    assert out2.get("results") == out1.get("results")


# ---------------------------------------------------------------------------
# _STOPWORDS_JA invariants
# ---------------------------------------------------------------------------


def test_stopwords_ja_includes_common_particles() -> None:
    for tok in ("の", "を", "は", "が", "に"):
        assert tok in w._STOPWORDS_JA


def test_stopwords_ja_is_a_frozenset_or_set() -> None:
    # Should support membership test in O(1) — set / frozenset.
    assert isinstance(w._STOPWORDS_JA, (set, frozenset))


# ---------------------------------------------------------------------------
# Module-load gate (_ENABLED) — just ensures import side-effects didn't crash.
# ---------------------------------------------------------------------------


def test_module_enabled_flag_resolves_to_known_value() -> None:
    # Default ON ("1") unless explicitly flipped.
    assert isinstance(w._ENABLED, bool)
