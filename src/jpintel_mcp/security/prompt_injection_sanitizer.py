"""Prompt-injection defense for tool output.

Second line of defense alongside the 景表法 (INV-22) sanitizer in
``api/response_sanitizer.py``. An attacker can embed override directives
("ignore previous instructions", "you are now DAN", `<|im_start|>` tokens,
etc.) inside aggregator text or pass-through fields; without this layer
those phrases reach the customer's LLM verbatim and may flip its policy.

Origin: ``_archive/autonomath_tools_dead_2026-04-25/prompt_injection_sanitizer.py``
(Wave 17 baseline, 8-pattern subset). Re-wired 2026-04-25 with the
``sanitize_prompt_injection`` API that returns ``(clean, hit_ids)`` so it
composes with the existing 景表法 walker in ``api/response_sanitizer``.

Patterns target *override directives*, never legitimate vocabulary:
    - "ignore/disregard/forget {previous,all,the} instructions/prompts/rules"
    - "new instructions:" / "system prompt:"
    - "you are now {a foo} (gpt|claude|llm|model)"
    - ChatML control tokens: <|im_start|> / <|im_end|> / <|system|>
    - jailbreak markers: jailbreak / DAN mode / developer mode

Bare 「instructions」「rules」「system」 are NOT matched — the corpus
contains 「申請手続のinstructions」「new rules apply」 etc. Replacement
token is ``[sanitized]`` (chosen to align with the original Wave 17
contract; INV-22 walker uses 「対象となる場合があります」, kept distinct).

Public surface:
    sanitize_prompt_injection(s) -> (clean_text, hit_pattern_ids)

Toggle: ``AUTONOMATH_PROMPT_INJECTION_GUARD`` env (default "1"). When set
to "0" / "false" the function returns ``(text, [])`` unchanged so the
operator has a one-flag rollback path.
"""

from __future__ import annotations

import re

from jpintel_mcp.config import settings

# (pattern, hit_id) tuples. hit_id is short, snake_case, observable on the
# `_sanitize_hits` envelope key (MCP) / `x-content-sanitized` header path
# (REST) so dashboards can split injection-class vs INV-22 false positives.
_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)ignore (all |previous |the )?(instructions|prompts|rules)"),
        "pi-ignore",
    ),
    (
        re.compile(r"(?i)disregard (all |previous |the )?(instructions|prompts|rules)"),
        "pi-disregard",
    ),
    (
        re.compile(r"(?i)forget (all |previous |the )?(instructions|prompts|rules)"),
        "pi-forget",
    ),
    (
        re.compile(r"(?i)new (instructions|task|role|system)[:：]"),
        "pi-new-directive",
    ),
    (
        re.compile(r"(?i)system prompt[:：]"),
        "pi-system-prompt",
    ),
    (
        re.compile(r"(?i)you are (now |a )?[a-z][a-z ]+ (gpt|claude|llm|model)"),
        "pi-role-flip",
    ),
    (
        re.compile(r"<\|im_start\|>|<\|im_end\|>|<\|system\|>"),
        "pi-chatml-token",
    ),
    (
        re.compile(r"(?i)jailbreak|DAN mode|developer mode"),
        "pi-jailbreak",
    ),
)

_REPLACEMENT = "[sanitized]"


def sanitize_prompt_injection(text: str) -> tuple[str, list[str]]:
    """Strip prompt-injection markers from a single string.

    Returns ``(clean, hit_ids)``. ``hit_ids`` is empty when nothing matched
    or when the ``AUTONOMATH_PROMPT_INJECTION_GUARD`` flag is disabled.
    Non-string / empty inputs pass through unchanged.

    Never raises — this runs on the response hot path (every JSON leaf via
    ``api/response_sanitizer.sanitize_response_text``) so a regex bug must
    not 500 a healthy tool result.
    """
    if not text:
        return text, []
    if not getattr(settings, "prompt_injection_guard_enabled", True):
        return text, []
    hits: list[str] = []
    out = text
    for pat, hit_id in _RULES:
        new_out, n = pat.subn(_REPLACEMENT, out)
        if n:
            hits.append(hit_id)
            out = new_out
    return out, hits


__all__ = ["sanitize_prompt_injection"]
