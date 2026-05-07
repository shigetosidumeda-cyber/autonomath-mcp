"""Token-saving estimate helpers.

The estimate is intentionally tokenizer-free. It is a dashboard heuristic,
not a billing input.
"""

from __future__ import annotations

import json
from typing import Any


def estimate_tokens(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return int(len(text) / 2.5)


def estimate_tokens_saved(question_text: Any, response_body: Any) -> int:
    question_tokens = estimate_tokens(question_text)
    if question_tokens <= 0:
        return 0
    baseline_tokens = question_tokens * 5
    response_tokens = estimate_tokens(response_body)
    return max(0, baseline_tokens - response_tokens)
