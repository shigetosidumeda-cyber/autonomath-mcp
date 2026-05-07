"""Token-saving estimator for JCRB-v1.

Customer-side helper that quantifies how many input/output tokens a
question consumes WITHOUT vs WITH jpcite context injection. The runner
calls this module to emit a CSV that joins the existing JCRB-v1 quality
scores with the implied token + USD cost delta.

NO LLM API calls happen here. Only tokenizer lookups (tiktoken /
character-based fallback for Anthropic + Gemini models, which do not
expose an offline tokenizer). The "estimate" half is a deterministic
length × reasoning-depth heuristic — see ``estimate_closed_book_tokens``
and ``estimate_with_jpcite_tokens`` for the exact arithmetic.

This file lives under ``benchmarks/`` (NOT under ``src/`` / ``scripts/``
/ ``tests/``), so the No-LLM CI guard does not scan it. Even so we
deliberately avoid any provider-SDK import — only ``tiktoken`` (which
is a tokenizer library, not a network client).

Pricing table is the public list price as of 2026-05-05. Update the
``MODEL_PRICING`` dict when providers re-price; the rest of the module
recomputes USD on every call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

try:
    import tiktoken  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - optional dependency
    tiktoken = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Pricing (USD per 1M tokens, public list 2026-05-05).
# ---------------------------------------------------------------------------

MODEL_PRICING: dict[str, dict[str, float]] = {
    # Anthropic
    "claude-opus-4-7": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    # OpenAI
    "gpt-5": {"input": 1.25, "output": 10.0},
    "gpt-4o": {"input": 2.50, "output": 10.0},
    # Google
    "gemini-2.5-pro": {"input": 1.25, "output": 10.0},
    "gemini": {"input": 1.25, "output": 10.0},
}


def _price_for(model: str) -> dict[str, float]:
    """Return per-1M-token pricing for ``model`` with sensible fallback."""
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    # Family fallback: pick the closest prefix match.
    for k, v in MODEL_PRICING.items():
        if model.startswith(k.split("-")[0]):
            return v
    # Default to Sonnet-tier so we never inflate cost for unknown model.
    return {"input": 3.0, "output": 15.0}


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------

# Anthropic / Gemini do NOT publish a free offline tokenizer. We
# approximate via a per-character ratio derived from public benchmarks:
#   * GPT-4o (cl100k_base) on Japanese ≈ 1 token per 1.4 chars
#   * Claude tokenizer on Japanese ≈ 1 token per 1.0 chars (tighter)
#   * Gemini tokenizer on Japanese ≈ 1 token per 1.5 chars (looser)
# These ratios are used as a fallback when tiktoken is unavailable for
# the model. They are intentionally conservative on the input side.
_CHAR_PER_TOKEN_FALLBACK: dict[str, float] = {
    "claude": 1.0,
    "gpt": 1.4,
    "gemini": 1.5,
}


def _fallback_ratio(model: str) -> float:
    head = model.split("-")[0].lower()
    return _CHAR_PER_TOKEN_FALLBACK.get(head, 1.3)


def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """Count tokens for ``text`` under ``model``'s tokenizer.

    Uses ``tiktoken`` when the model has a known tiktoken encoding
    (OpenAI family). For Anthropic + Gemini, falls back to a
    character-ratio estimate that overcounts slightly so we don't
    under-estimate jpcite savings.
    """
    if not text:
        return 0
    if tiktoken is not None and model.startswith(("gpt", "o1", "o3", "o4")):
        try:
            enc = tiktoken.encoding_for_model(model)
        except KeyError:
            enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    if tiktoken is not None and model.startswith("claude"):
        # Anthropic does not publish an offline tokenizer that exactly
        # matches the production one. cl100k_base is a defensible proxy
        # because Claude's tokenizer is BPE with similar code-point
        # coverage; absolute numbers will drift but ratios hold.
        try:
            enc = tiktoken.get_encoding("cl100k_base")
            # Claude tends to emit ~1.3× more tokens than cl100k_base on JP.
            return int(len(enc.encode(text)) * 1.3)
        except Exception:  # noqa: BLE001
            pass
    # Pure character-ratio fallback.
    ratio = _fallback_ratio(model)
    return max(1, int(len(text) / ratio))


# ---------------------------------------------------------------------------
# Reasoning-depth heuristic
# ---------------------------------------------------------------------------

# Closed-book: the model has to answer the question from parametric
# memory. For Japanese public-program questions this tends to mean a
# longer chain-of-thought + speculative URL guessing. Empirical floor
# from JCRB-v1 SEED runs: 250-450 output tokens for closed-book.
_CLOSED_BOOK_OUTPUT_BASE = 320  # tokens
_CLOSED_BOOK_OUTPUT_PER_QCHAR = 0.6

# With jpcite context: the model can quote the cited row. Output stays
# tight (one sentence + one URL). Empirical: 90-150 output tokens.
_WITH_JPCITE_OUTPUT_BASE = 110
_WITH_JPCITE_OUTPUT_PER_QCHAR = 0.2

# System prompt token cost (the JCRB-v1 SYSTEM_PROMPT in run.py).
SYSTEM_PROMPT_TOKENS_DEFAULT = 220

_URL_RE = re.compile(r"https?://[^\s)\"'<>]+")


@dataclass(frozen=True)
class TokenEstimate:
    """Per-(question, model, mode) token + cost rollup."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float

    def as_row(self) -> dict[str, float | int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }


def _cost(input_tokens: int, output_tokens: int, model: str) -> float:
    p = _price_for(model)
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000


def estimate_closed_book_tokens(
    question: str,
    model: str = "claude-opus-4-7",
    system_prompt_tokens: int = SYSTEM_PROMPT_TOKENS_DEFAULT,
) -> TokenEstimate:
    """Estimate input/output tokens for a closed-book LLM call.

    Input  = system prompt tokens + question tokens.
    Output = base reasoning-depth + linear factor on question length.

    The output side is INTENTIONALLY higher than the with-jpcite path
    because closed-book forces the model to (a) speculate, (b) hedge,
    (c) emit longer "I am not certain but ..." disclaimers, and
    (d) sometimes hallucinate URLs that take more tokens than a single
    cited row.
    """
    qchar = len(question)
    qtok = count_tokens(question, model)
    input_tokens = system_prompt_tokens + qtok
    output_tokens = int(_CLOSED_BOOK_OUTPUT_BASE + qchar * _CLOSED_BOOK_OUTPUT_PER_QCHAR)
    total = input_tokens + output_tokens
    return TokenEstimate(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total,
        cost_usd=_cost(input_tokens, output_tokens, model),
    )


def estimate_with_jpcite_tokens(
    question: str,
    jpcite_response: str,
    model: str = "claude-opus-4-7",
    system_prompt_tokens: int = SYSTEM_PROMPT_TOKENS_DEFAULT,
) -> TokenEstimate:
    """Estimate input/output tokens when jpcite response is injected as context.

    Input  = system prompt + jpcite context block + question.
    Output = compressed (model can quote — one sentence + one URL).
    """
    qchar = len(question)
    qtok = count_tokens(question, model)
    ctx_tok = count_tokens(jpcite_response, model)
    input_tokens = system_prompt_tokens + ctx_tok + qtok
    output_tokens = int(_WITH_JPCITE_OUTPUT_BASE + qchar * _WITH_JPCITE_OUTPUT_PER_QCHAR)
    total = input_tokens + output_tokens
    return TokenEstimate(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total,
        cost_usd=_cost(input_tokens, output_tokens, model),
    )


def jpcite_response_to_context_block(jpcite_response: dict | list | str) -> str:
    """Reduce a jpcite REST response to the context block we'd inject.

    Accepts:
      * raw response dict (``{"results": [...]}``)
      * already-formatted string (passes through)
      * list of result dicts
    """
    if isinstance(jpcite_response, str):
        return jpcite_response
    if isinstance(jpcite_response, dict):
        hits = jpcite_response.get("results", [])
    elif isinstance(jpcite_response, list):
        hits = jpcite_response
    else:
        return ""
    lines = ["[jpcite primary-source context]"]
    for i, h in enumerate(hits[:5], 1):
        if not isinstance(h, dict):
            continue
        name = (
            h.get("primary_name") or h.get("name") or h.get("title") or h.get("ruleset_name") or ""
        )
        url = h.get("source_url") or h.get("official_url") or h.get("url") or ""
        snippet = h.get("snippet") or h.get("summary") or ""
        if snippet:
            snippet = snippet[:200]
            lines.append(f"{i}. {name} — {url}\n   {snippet}")
        else:
            lines.append(f"{i}. {name} — {url}")
    return "\n".join(lines)


def savings(closed: TokenEstimate, with_jp: TokenEstimate) -> dict[str, float | int]:
    """Return the (closed - with_jpcite) delta + percent saved."""
    tok_saved = closed.total_tokens - with_jp.total_tokens
    usd_saved = closed.cost_usd - with_jp.cost_usd
    pct = (tok_saved / closed.total_tokens * 100.0) if closed.total_tokens else 0.0
    return {
        "tokens_saved": tok_saved,
        "usd_saved": round(usd_saved, 6),
        "pct_saved": round(pct, 2),
    }


__all__ = [
    "MODEL_PRICING",
    "TokenEstimate",
    "count_tokens",
    "estimate_closed_book_tokens",
    "estimate_with_jpcite_tokens",
    "jpcite_response_to_context_block",
    "savings",
]
