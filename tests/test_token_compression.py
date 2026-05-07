"""Tests for ``TokenCompressionEstimator`` (plan §9.1 token cost shield).

Verifies:
  * Char-weighted estimate of pure-Japanese text matches expectation (±10%).
  * Char-weighted estimate of pure-English text matches expectation (±10%).
  * Mixed JP/EN text falls between the two pure-language values.
  * ``source_basis="unknown"`` returns ``None`` (NOT ``0`` — the plan demands
    honest absence rather than a fake measurement).
  * ``compose`` with full inputs produces the full block including
    ``cost_savings_estimate``.
  * ``compose`` with ``input_price_jpy_per_1m=None`` omits
    ``cost_savings_estimate`` entirely.
  * Source file has zero LLM imports.
"""

from __future__ import annotations

import ast
import pathlib

from jpintel_mcp.services.token_compression import (
    ESTIMATE_DISCLAIMER,
    ESTIMATE_METHOD,
    TokenCompressionEstimator,
)

# 5KB-class sample of Japanese government doc text. This is a plausible
# excerpt structure (公募要領 outline) — kanji/hiragana/katakana mixed,
# numerals + line breaks, a couple of ASCII URLs. ~700 chars = ~280 tokens
# under the v1 heuristic.
SAMPLE_JP_GOV_TEXT = (
    "中小企業庁 ものづくり・商業・サービス生産性向上促進補助金 公募要領 第18次。"
    "本補助金は、革新的なサービス開発・試作品開発・生産プロセスの改善を行う中小企業・"
    "小規模事業者等が行う設備投資等を支援するものです。補助対象者は、日本国内に本社及び"
    "補助事業の実施場所を有する中小企業者等であって、認定経営革新等支援機関の全面バックアップ"
    "を受けて経営革新計画を策定し、当該計画に基づいて補助事業を実施する事業者とします。"
    "補助上限額は通常枠で1,000万円から1,250万円、補助率は1/2(小規模事業者等は2/3)です。"
    "申請受付期間は令和8年5月1日から令和8年7月31日までとし、電子申請システム"
    "(jGrants)を利用して申請を行うものとします。詳細は中小企業庁ウェブサイト "
    "https://www.chusho.meti.go.jp/keiei/sapoin/ を参照のこと。"
)

# Pure-English baseline.
SAMPLE_EN_TEXT = (
    "The Ministry of Economy, Trade and Industry administers the Monodzukuri "
    "Subsidy program to support productivity-enhancing capital investment by "
    "small and medium-sized enterprises in Japan. Eligible recipients must "
    "operate in Japan and partner with a certified management innovation "
    "support organization. The standard cap is between ten and twelve and a "
    "half million yen, with a subsidy rate of one half (or two thirds for "
    "small businesses). Applications are accepted via the jGrants electronic "
    "application system between May and July of the fiscal year."
)


def test_pure_japanese_chars_per_token_within_10_percent() -> None:
    """At ~2.5 chars/token, ~700 JP chars should land near 280 tokens (±10%)."""
    estimator = TokenCompressionEstimator()
    text = SAMPLE_JP_GOV_TEXT
    tokens = estimator._estimate_from_text(text)

    # Expected from heuristic: cjk_count / 2.5 + ascii_count / 4.0.
    # Sanity: the result should imply ~2.5–3.5 chars per token overall
    # (mixed because URLs add some ASCII).
    chars = len(text)
    chars_per_token = chars / tokens
    assert (
        2.3 <= chars_per_token <= 3.8
    ), f"Pure-JP text should land near 2.5-3.0 chars/token, got {chars_per_token:.2f}"

    # Tight upper-bound sanity: must be within 10% of the closed-form
    # heuristic prediction.
    import re

    cjk_re = re.compile(r"[぀-ゟ゠-ヿ一-鿿]")
    cjk_chars = len(cjk_re.findall(text))
    other_chars = chars - cjk_chars
    expected = int(round(cjk_chars / 2.5 + other_chars / 4.0))
    assert abs(tokens - expected) / max(expected, 1) <= 0.10


def test_pure_english_chars_per_token_within_10_percent() -> None:
    """At ~4.0 chars/token, English text should hit 4.0 chars/token closely."""
    estimator = TokenCompressionEstimator()
    text = SAMPLE_EN_TEXT
    tokens = estimator._estimate_from_text(text)

    chars_per_token = len(text) / tokens
    # English is ~4.0 chars/token by definition of our weight; allow ±10%.
    assert (
        3.6 <= chars_per_token <= 4.4
    ), f"Pure-EN text should land near 4.0 chars/token, got {chars_per_token:.2f}"


def test_mixed_jp_en_falls_between() -> None:
    """Mixed text density (chars/token) lies strictly between pure-JP and pure-EN."""
    estimator = TokenCompressionEstimator()
    jp_density = len(SAMPLE_JP_GOV_TEXT) / estimator._estimate_from_text(SAMPLE_JP_GOV_TEXT)
    en_density = len(SAMPLE_EN_TEXT) / estimator._estimate_from_text(SAMPLE_EN_TEXT)

    # Construct an explicit ~50/50 mix.
    mixed = "本補助金は中小企業庁が運営する。" + " The subsidy is administered by METI." * 3
    mixed_density = len(mixed) / estimator._estimate_from_text(mixed)

    # Mixed density must lie between the two pure-language densities.
    low = min(jp_density, en_density)
    high = max(jp_density, en_density)
    assert (
        low <= mixed_density <= high
    ), f"Mixed density {mixed_density:.2f} should lie in [{low:.2f}, {high:.2f}]"


def test_source_basis_unknown_returns_none() -> None:
    """``source_basis='unknown'`` with no text must return None (not 0)."""
    estimator = TokenCompressionEstimator()
    result = estimator.estimate_source_tokens(
        "https://example.gov.jp/notice.pdf",
        source_basis="unknown",
    )
    assert result is None, "Unknown source must return None, not 0 — honesty rule."


def test_source_basis_pdf_pages_uses_700_per_page() -> None:
    """Per-page heuristic kicks in when basis=pdf_pages and pdf_pages provided."""
    estimator = TokenCompressionEstimator()
    result = estimator.estimate_source_tokens(
        "https://example.gov.jp/notice.pdf",
        source_basis="pdf_pages",
        pdf_pages=10,
    )
    assert result == 7000


def test_source_basis_token_count_uses_caller_measurement() -> None:
    """Caller-measured token counts pass through unchanged."""
    estimator = TokenCompressionEstimator()
    result = estimator.estimate_source_tokens(
        "https://example.gov.jp/notice.pdf",
        source_basis="token_count",
        source_token_count=18_500,
    )
    assert result == 18_500


def test_source_text_overrides_basis() -> None:
    """When source_text is provided, char-weighted estimate is used regardless of basis."""
    estimator = TokenCompressionEstimator()
    text_only = estimator.estimate_source_tokens(
        "https://example.gov.jp/notice.pdf",
        source_text=SAMPLE_JP_GOV_TEXT,
        source_basis="unknown",
    )
    expected = estimator._estimate_from_text(SAMPLE_JP_GOV_TEXT)
    assert text_only == expected
    assert text_only is not None and text_only > 0


def test_compose_full_inputs_produces_full_block() -> None:
    """compose with everything produces full schema block including cost_savings_estimate."""
    estimator = TokenCompressionEstimator()
    packet = {
        "subject": "monodzukuri_18",
        "facts": [{"k": "deadline", "v": "2026-07-31"}],
        "citations": [{"url": "https://example.gov.jp/notice.pdf"}],
    }
    result = estimator.compose(
        packet,
        source_url="https://example.gov.jp/notice.pdf",
        source_basis="pdf_pages",
        pdf_pages=30,
        jpcite_cost_jpy=3,
        input_price_jpy_per_1m=300.0,
    )

    assert result["estimate_method"] == ESTIMATE_METHOD
    assert result["estimate_disclaimer"] == ESTIMATE_DISCLAIMER
    assert result["source_tokens_basis"] == "pdf_pages"
    assert isinstance(result["packet_tokens_estimate"], int)
    assert isinstance(result["source_tokens_estimate"], int)
    assert result["source_tokens_estimate"] == 30 * 700
    assert isinstance(result["avoided_tokens_estimate"], int)
    assert result["avoided_tokens_estimate"] >= 0
    assert isinstance(result["compression_ratio"], float)
    assert 0 < result["compression_ratio"] <= 1
    assert result["input_context_reduction_rate"] == round(
        result["avoided_tokens_estimate"] / result["source_tokens_estimate"], 4
    )
    assert result["provider_billing_not_guaranteed"] is True

    savings = result["cost_savings_estimate"]
    assert savings["currency"] == "JPY"
    assert savings["input_token_price_jpy_per_1m"] == 300.0
    assert savings["jpcite_billable_units"] == 1
    assert savings["jpcite_cost_jpy_ex_tax"] == 3
    assert savings["break_even_avoided_tokens"] == 10000
    assert savings["break_even_source_tokens_estimate"] == (
        result["packet_tokens_estimate"] + savings["break_even_avoided_tokens"]
    )
    assert savings["break_even_met"] is True
    assert savings["input_context_only"] is True
    assert savings["provider_billing_not_guaranteed"] is True
    assert savings["price_input_source"] == "caller_supplied"
    assert savings["billing_savings_claim"] == "estimate_not_guarantee"
    assert isinstance(savings["gross_input_savings_jpy"], float)
    assert isinstance(savings["net_savings_jpy_ex_tax"], float)


def test_compose_no_price_omits_cost_savings() -> None:
    """When input_price_jpy_per_1m is None, cost_savings_estimate is OMITTED."""
    estimator = TokenCompressionEstimator()
    packet = {"subject": "test", "facts": []}
    result = estimator.compose(
        packet,
        source_url="https://example.gov.jp/notice.pdf",
        source_basis="pdf_pages",
        pdf_pages=10,
        input_price_jpy_per_1m=None,
    )
    assert (
        "cost_savings_estimate" not in result
    ), "Plan §9.1 demands omission when price unknown — never fabricate a price."
    # Other fields still present.
    assert result["estimate_method"] == ESTIMATE_METHOD
    assert result["source_tokens_estimate"] == 7000
    assert result["input_context_reduction_rate"] is not None
    assert result["provider_billing_not_guaranteed"] is True


def test_compose_token_count_baseline_returns_exact_context_estimate() -> None:
    """token_count lets callers compare against their own LLM/tokenizer baseline."""
    estimator = TokenCompressionEstimator()
    packet = {
        "subject": "monodzukuri_18",
        "facts": [{"k": "deadline", "v": "2026-07-31"}],
        "citations": [{"url": "https://example.gov.jp/notice.pdf"}],
    }
    result = estimator.compose(
        packet,
        source_url="https://example.gov.jp/notice.pdf",
        source_basis="token_count",
        source_token_count=18_500,
        input_price_jpy_per_1m=300.0,
    )

    assert result["source_tokens_basis"] == "token_count"
    assert result["source_token_count"] == 18_500
    assert result["source_tokens_estimate"] == 18_500
    assert result["source_tokens_input_source"] == "caller_supplied"
    assert result["avoided_tokens_estimate"] == max(0, 18_500 - result["packet_tokens_estimate"])
    assert result["estimate_scope"] == "input_context_only"
    assert result["savings_claim"] == "estimate_not_guarantee"
    assert result["input_context_reduction_rate"] == round(
        result["avoided_tokens_estimate"] / result["source_tokens_estimate"], 4
    )
    assert result["provider_billing_not_guaranteed"] is True
    savings = result["cost_savings_estimate"]
    assert savings["break_even_source_tokens_estimate"] == (
        result["packet_tokens_estimate"] + savings["break_even_avoided_tokens"]
    )
    assert savings["input_context_only"] is True
    assert savings["provider_billing_not_guaranteed"] is True


def test_compose_unknown_source_emits_null_ratio() -> None:
    """When source tokens unknown, ratio is None (not 0, not a guess)."""
    estimator = TokenCompressionEstimator()
    packet = {"subject": "test", "facts": []}
    result = estimator.compose(
        packet,
        source_url="https://example.gov.jp/notice.pdf",
        source_basis="unknown",
    )
    assert result["source_tokens_estimate"] is None
    assert result["compression_ratio"] is None
    assert result["avoided_tokens_estimate"] is None
    assert result["input_context_reduction_rate"] is None
    assert result["provider_billing_not_guaranteed"] is True
    assert "cost_savings_estimate" not in result


def test_module_has_zero_llm_imports() -> None:
    """Source file imports nothing from anthropic/openai/google.generativeai/claude_agent_sdk."""
    src_path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "src"
        / "jpintel_mcp"
        / "services"
        / "token_compression.py"
    )
    tree = ast.parse(src_path.read_text(encoding="utf-8"))

    forbidden = {
        "anthropic",
        "openai",
        "google.generativeai",
        "claude_agent_sdk",
        "tiktoken",
        "sentencepiece",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                head = alias.name.split(".")[0]
                assert head not in {
                    "anthropic",
                    "openai",
                    "claude_agent_sdk",
                    "tiktoken",
                    "sentencepiece",
                }, f"Forbidden import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            head = mod.split(".")[0]
            assert mod not in forbidden and head not in {
                "anthropic",
                "openai",
                "claude_agent_sdk",
                "tiktoken",
                "sentencepiece",
            }, f"Forbidden from-import: {mod}"


def test_compression_ratio_matches_plan_example_shape() -> None:
    """Plan §9.1 example: packet=820 / source=18500 → ratio 0.044. We match the shape."""
    estimator = TokenCompressionEstimator()
    # Synthesize source text big enough that source >> packet.
    source_text = SAMPLE_JP_GOV_TEXT * 60  # ~42K chars
    packet = {
        "subject": "test",
        "facts": [{"k": "deadline", "v": "2026-07-31"}],
        "citations": [{"url": "https://example.gov.jp/notice.pdf"}],
    }
    result = estimator.compose(
        packet,
        source_url="https://example.gov.jp/notice.pdf",
        source_text=source_text,
        source_basis="html_chars",
        input_price_jpy_per_1m=300.0,
    )

    assert result["packet_tokens_estimate"] < result["source_tokens_estimate"]
    assert 0 < result["compression_ratio"] < 0.5
    assert result["cost_savings_estimate"]["gross_input_savings_jpy"] > 0


def test_savings_math_matches_plan_formula() -> None:
    """net = gross - jpcite_cost; gross = (source - packet) * (price / 1M)."""
    estimator = TokenCompressionEstimator()
    savings = estimator.compute_savings(
        packet_tokens=820,
        source_tokens=18500,
        jpcite_cost_jpy=3,
        input_price_jpy_per_1m=300.0,
    )
    assert savings is not None
    # gross = (18500 - 820) * 300 / 1_000_000 = 17680 * 0.0003 = 5.304
    assert savings["gross_input_savings_jpy"] == 5.3
    # net = 5.304 - 3 = 2.304
    assert savings["net_savings_jpy_ex_tax"] == 2.3
    assert savings["jpcite_cost_jpy_ex_tax"] == 3
    assert savings["jpcite_billable_units"] == 1
    assert savings["break_even_avoided_tokens"] == 10000
    assert savings["break_even_source_tokens_estimate"] == 10820
    assert savings["break_even_met"] is True
    assert savings["input_context_only"] is True
    assert savings["provider_billing_not_guaranteed"] is True


def test_savings_break_even_false_when_context_too_small() -> None:
    """A small source can reduce tokens but still not clear the ¥3 break-even."""
    estimator = TokenCompressionEstimator()
    savings = estimator.compute_savings(
        packet_tokens=900,
        source_tokens=5_000,
        jpcite_cost_jpy=3,
        input_price_jpy_per_1m=300.0,
    )
    assert savings is not None
    assert savings["break_even_avoided_tokens"] == 10000
    assert savings["break_even_met"] is False
    assert savings["net_savings_jpy_ex_tax"] < 0


def test_compute_savings_returns_none_when_price_missing() -> None:
    """No price → no savings dict."""
    estimator = TokenCompressionEstimator()
    assert (
        estimator.compute_savings(
            packet_tokens=100, source_tokens=1000, jpcite_cost_jpy=3, input_price_jpy_per_1m=None
        )
        is None
    )


def test_compute_savings_returns_none_when_source_unknown() -> None:
    """No source tokens → no savings dict (would be a fabricated number otherwise)."""
    estimator = TokenCompressionEstimator()
    assert (
        estimator.compute_savings(
            packet_tokens=100, source_tokens=None, jpcite_cost_jpy=3, input_price_jpy_per_1m=300.0
        )
        is None
    )


def test_packet_estimate_uses_compact_json() -> None:
    """Packet token estimate must reflect the compact JSON serialisation, not pretty-printed."""
    estimator = TokenCompressionEstimator()
    packet = {"a": "中小企業庁", "b": [1, 2, 3], "c": {"nested": "値"}}
    tokens = estimator.estimate_packet_tokens(packet)
    # Sanity: should be small — under 50 tokens for this 4-field object.
    assert 0 < tokens < 50
