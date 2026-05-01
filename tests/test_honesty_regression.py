"""Regression tests preventing fraud-adjacent inflated claims from re-entering the codebase.

Background: Z3 audit (2026-04-26) found compat_matrix moat / amendment time-series claims were inflated.
We cleaned up landing/docs/docstrings on 2026-04-26. These tests ensure they stay clean.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Phrases that imply unreproducible / unique / decisive moat — fraud-adjacent if not backed
INFLATED_PHRASES = [
    r"dependency baseline",
    r"baseline layer",
    r"AI agent が呼ぶ前に呼ぶ",
    r"48,815 行 moat",
    r"compat_matrix moat",
    r"dark inventory",
    r"改正時系列追跡",
    r"amendment time[- ]series tracking",
    r"決定的優位",
    r"唯一の moat",
    r"永続 moat",
    r"decisive moat",
    r"irreplaceable",
]

# Files that are user-facing (publicly served or shipped to PyPI / MCP registry)
USER_FACING_GLOBS = [
    "site/index.ja.html",
    "site/index.en.html",
    "docs/**/*.md",
    "README.md",
    "src/jpintel_mcp/mcp/autonomath_tools/*.py",
    "src/jpintel_mcp/api/main.py",
]

# Internal docs we expect inflated language in (historical / planning) — exclude
EXCLUDED_PATTERNS = [
    "docs/_internal/",
    "analysis_wave18/",
    "analysis_wave*/",
    "docs/canonical/",  # may have legacy / archived content
]


def _gather_user_facing_files():
    files = []
    for pattern in USER_FACING_GLOBS:
        files.extend(REPO.glob(pattern))
    # Filter out excluded
    out = []
    for f in files:
        rel = str(f.relative_to(REPO))
        if any(rel.startswith(ex.rstrip("*")) for ex in EXCLUDED_PATTERNS):
            continue
        out.append(f)
    return out


def test_no_inflated_phrases_in_user_facing():
    """User-facing files (site/, docs/, README, MCP tools) must not contain fraud-adjacent claims."""
    violations = []
    for f in _gather_user_facing_files():
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for phrase in INFLATED_PHRASES:
            if re.search(phrase, text, flags=re.IGNORECASE):
                violations.append(f"{f.relative_to(REPO)}: {phrase}")
    assert not violations, "\n".join(violations)


def test_disclaimer_mentions_law():
    """Sensitive tool disclaimers must mention at least one of: 弁護士法 / 税理士法 / 行政書士法 / 社労士法."""
    from jpintel_mcp.mcp.autonomath_tools.envelope_wrapper import (
        SENSITIVE_TOOLS,
        disclaimer_for,
    )
    laws = ("弁護士法", "税理士法", "行政書士法", "社労士法")
    for tool in SENSITIVE_TOOLS:
        d = disclaimer_for(tool, "standard")
        assert d, f"{tool}: missing disclaimer"
        assert any(law in d for law in laws), (
            f"{tool}: disclaimer doesn't reference any covered law: {d!r}"
        )


def test_disclaimer_no_advice_promise():
    """Disclaimers must not promise advice / decisive verification."""
    from jpintel_mcp.mcp.autonomath_tools.envelope_wrapper import (
        SENSITIVE_TOOLS,
        disclaimer_for,
    )
    forbidden = ["精度の高い", "確実な判定", "decisive", "guaranteed", "保証"]
    for tool in SENSITIVE_TOOLS:
        for level in ("minimal", "standard", "strict"):
            d = disclaimer_for(tool, level)
            assert d, f"{tool}/{level}: missing disclaimer"
            for word in forbidden:
                assert word not in d, f"{tool}/{level}: forbidden word {word!r} in disclaimer"


def test_pricing_no_tier_mention():
    """No tier / starter / pro / enterprise plans should be mentioned."""
    forbidden_tiers = [
        r"\bstarter plan\b",
        r"\bpro plan\b",
        r"\benterprise plan\b",
        r"スタータープラン",
        r"プロプラン",
        r"エンタープライズプラン",
        r"tier-badge",
    ]
    violations = []
    for f in _gather_user_facing_files():
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for phrase in forbidden_tiers:
            if re.search(phrase, text, flags=re.IGNORECASE):
                violations.append(f"{f.relative_to(REPO)}: {phrase}")
    assert not violations, "\n".join(violations)
