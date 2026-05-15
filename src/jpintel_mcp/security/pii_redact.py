"""PII redaction for query telemetry / query_log_v2 (INV-21) AND response body (S7).

Risk model (from analysis_wave18 deep_dive_v8/05_property_invariants.md):
    Free-text query parameters (`q=...`) and similar text fields can leak
    法人番号 (T+13 digits) / email / phone numbers into logs. Storing those
    raw in `query_log_v2.query_normalized` violates 個人情報保護法 (APPI).

S7 extension (2026-04-25):
    INV-21's `redact_pii()` only ran on telemetry. The same APPI risk
    applies to the **response body** — gbiz facts surface 13桁法人番号 in
    rich text, ~5,904 corp.representative (代表者名) rows, and 121k
    location strings can all carry email / 電話 / 法人番号 fragments. A
    new public surface `redact_response_text` runs as **layer 0** of the
    `api.response_sanitizer.sanitize_response_text` cascade so the
    downstream INV-22 + prompt-injection + loop_a layers never see raw
    PII.

S7 false-positive fix (2026-04-25):
    1. 法人番号 is **公開情報** (国税庁 法人番号公表サイト PDL v1.0 + gbiz
       PDL v1.0). Tools like ``check_enforcement_am`` / ``search_corp``
       MUST echo the queried 13桁 verbatim for accuracy — masking it
       breaks DD UX and confuses the LLM (cf memory `feedback_no_fake_data`
       which warns against accuracy loss). Default behaviour is therefore
       **preserve** (do not redact). Operators flip
       ``AUTONOMATH_PII_REDACT_HOUJIN_BANGOU=1`` once legal opinion
       changes; the redactor still emits ``pii-houjin`` audit hits when
       on, mirroring the pattern used by ``pii_redact_representative`` /
       ``pii_redact_postal_code``.
    2. The phone regex previously matched any leading-``0`` digit run,
       collapsing canonical IDs like ``program:04_program_documents:000000``
       (gbiz / am_entities canonical_id shape) and the bare 13桁 houjin
       (``1010401030882``) into ``<phone-redacted>``. The new regex
       insists on either an explicit Japanese telephone separator
       structure (``\\d{2,4}-\\d{2,4}-\\d{4}`` with hyphens / spaces) or a
       ``0[789]0`` mobile prefix followed by exactly 8 digits, and uses
       alphanumeric boundaries so 64-char hex digests are not corrupted.
       Bare 6+ digit substrings without separators are no longer matched.

Patterns (must stay synchronized with tests/test_invariants_critical.py):
    - 法人番号:  T\\d{13}              -> [REDACTED:HOUJIN]
    - email:    user@host.tld         -> [REDACTED:EMAIL]
    - 電話:     +81/0 prefixed phones -> [REDACTED:PHONE]

Response-body extras (gated):
    - 法人番号 (T+13 / response body): default off; flip
      AUTONOMATH_PII_REDACT_HOUJIN_BANGOU=1 to mask to ``T*************``.
    - 代表者名 (corp.representative): default off; flip
      AUTONOMATH_PII_REDACT_REPRESENTATIVE=1 once legal review confirms.
    - 郵便番号 (corp.postal_code): default off; gbiz public info — flip
      AUTONOMATH_PII_REDACT_POSTAL_CODE=1 to redact pending review.

Public surface:
    redact_text(s)             -> str  (telemetry path; idempotent)
    redact_pii(obj)            -> recursive walk, str leaves redacted
    redact_response_text(s)    -> (clean, hits)  (response sanitizer path)
"""

from __future__ import annotations

import re
from typing import Any

# Patterns mirror tests/test_invariants_critical.py::PII_PATTERNS so a hit
# there also hits here (and a redacted log row passes the test).
_HOUJIN_RE = re.compile(r"T\d{13}")
_EMAIL_RE = re.compile(r"[\w.-]+@[\w.-]+\.[a-zA-Z]{2,}")
# 日本電話形式 — strict (S7 false-positive fix, 2026-04-25). We accept ONLY:
#   1. landline / 03-/06- 等: \d{2,4}[-\s.]\d{2,4}[-\s.]\d{3,4} starting with 0
#   2. +81 国際表記:           +81[-\s]\d{1,4}[-\s.]\d{1,4}[-\s.]\d{3,4}
#   3. 携帯 (no separators):   0[789]0\d{8} (e.g. 09012345678)
# A ``(?<![A-Za-z0-9])`` lookbehind + ``(?![A-Za-z0-9])`` lookahead anchors to
# alphanumeric boundaries so canonical_id substrings like
# ``...:000000:23_xxx`` (program ID hash), bare 13桁 houjin
# ``1010401030882``, and 64-char SHA-256 digests cannot be eaten as a phone.
# This replaces the old loose pattern that allowed bare ``0\d{1,4}`` without
# any separator and produced ``1<phone-redacted>`` collapses on real houjin
# inputs (cf test_check_enforcement_am_happy_with_real_houjin failure).
_PHONE_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:"
    r"\+?81[-\s]\d{1,4}[-\s.]\d{1,4}[-\s.]\d{3,4}"
    r"|0\d{1,4}[-\s.]\d{1,4}[-\s.]\d{3,4}"
    r"|0[789]0\d{8}"
    r")"
    r"(?![A-Za-z0-9])"
)

PII_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("HOUJIN", _HOUJIN_RE, "[REDACTED:HOUJIN]"),
    ("EMAIL", _EMAIL_RE, "[REDACTED:EMAIL]"),
    ("PHONE", _PHONE_RE, "[REDACTED:PHONE]"),
)

# --- Response-body (S7) layer 0 ----------------------------------------
# Distinct from PII_PATTERNS above so the response cascade can:
#   1. emit per-pattern `pii-*` hit ids onto `_sanitize_hits`, and
#   2. mask the 法人番号 in a recoverable shape (`T*************`) that
#      preserves the prefix character so downstream UI / LLM still see
#      "this is a 法人番号 placeholder", not the opaque [REDACTED:*] form
#      that telemetry uses.
_HOUJIN_RESP_RE = re.compile(r"T(\d{13})")
_EMAIL_RESP_RE = _EMAIL_RE
_PHONE_RESP_RE = _PHONE_RE


def _mask_houjin_resp(m: re.Match[str]) -> str:
    """T+13 digits -> T+13 asterisks. Preserves prefix shape for the LLM."""
    return "T" + "*" * 13


def redact_text(s: str) -> str:
    """Redact 法人番号 / email / 電話 occurrences in a single string.

    Order matters: email is matched before phone because an email's local
    part can contain digit runs that the phone regex would otherwise eat.
    法人番号 (T+13) goes first because it is the most specific.
    """
    if not s:
        return s
    out = s
    for _label, pat, repl in PII_PATTERNS:
        out = pat.sub(repl, out)
    return out


def redact_response_text(s: str) -> tuple[str, list[str]]:
    """Layer 0 PII redactor for the response sanitizer cascade.

    Returns ``(clean, hit_ids)`` where ``hit_ids`` is the set of pattern
    ids triggered (subset of {pii-houjin, pii-email, pii-phone}). 法人番号
    is masked to ``T*************`` so the placeholder shape stays
    parseable; email -> ``<email-redacted>``; 電話 -> ``<phone-redacted>``.

    Non-string / empty inputs pass through unchanged. The function never
    raises — it lives on the response hot path and a regex bug must not
    500 a healthy tool result.

    Pattern ordering rationale: 法人番号 is the most specific (literal T
    prefix + fixed digit count) so it goes first; email second so its
    local-part digits cannot be eaten by the phone regex; 電話 last.

    Houjin-bangou gating (S7 false-positive fix, 2026-04-25):
        Default behaviour is **preserve** the T+13 literal because it is
        gbiz / 国税庁 PDL v1.0 公開情報 and customer-facing tools need to
        echo the queried 13桁 verbatim for DD accuracy. Operators flip
        ``settings.pii_redact_houjin_bangou=True`` (env
        ``AUTONOMATH_PII_REDACT_HOUJIN_BANGOU=1``) to restore the legacy
        ``T*************`` mask. The settings import happens lazily inside
        the function so test monkeypatches and module reloads in
        ``tests/test_pii_redactor_response.py`` pick up the latest value.
    """
    if not s:
        return s, []
    # Lazy import — keeps the module importable in pure-pattern unit tests
    # that never need the FastAPI / pydantic-settings stack and lets test
    # cases that monkeypatch ``settings.pii_redact_houjin_bangou`` see the
    # latest value without forcing a redact_response_text reload.
    try:
        from jpintel_mcp.config import settings as _settings

        _redact_houjin = bool(getattr(_settings, "pii_redact_houjin_bangou", False))
    except Exception:
        _redact_houjin = False
    hits: list[str] = []
    out = s
    if _redact_houjin:
        new_out, n = _HOUJIN_RESP_RE.subn(_mask_houjin_resp, out)
        if n:
            hits.append("pii-houjin")
            out = new_out
    new_out, n = _EMAIL_RESP_RE.subn("<email-redacted>", out)
    if n:
        hits.append("pii-email")
        out = new_out
    new_out, n = _PHONE_RESP_RE.subn("<phone-redacted>", out)
    if n:
        hits.append("pii-phone")
        out = new_out
    return out, hits


def redact_pii(obj: Any) -> Any:
    """Recursively walk obj, returning a new structure with str leaves redacted.

    Dict keys are NOT redacted (param-shape only logs keys, not values).
    Tuples become tuples; lists become lists; everything else returns as-is.
    """
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        return {k: redact_pii(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_pii(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(redact_pii(v) for v in obj)
    return obj


__all__ = ["redact_pii", "redact_text", "redact_response_text", "PII_PATTERNS"]
