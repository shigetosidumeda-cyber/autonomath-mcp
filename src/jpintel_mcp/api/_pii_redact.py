"""Wave 49 tick#7 Dim N Phase 1 — extended PII redact middleware (7 patterns).

Extends the Wave 43+ ``jpintel_mcp.security.pii_redact`` core (3 patterns:
houjin / email / phone) with 4 additional patterns required by the Dim N
strict surface (Wave 49 Phase 1 k=10 view + strict cohort responses):

    1. **name**       — JP 個人氏名 (姓+名 漢字 / カナ) and rōmaji fallback.
                       Strict pattern only — won't eat 法人 / 団体 names
                       that include common 法人 suffix tokens.
    2. **address**    — JP 住所 (都道府県 + 市区町村 prefix tokens).
                       Conservative: requires 都道府県 token + 1-2 digit
                       building / chōme separator to avoid eating generic
                       industry / region names.
    3. **phone**      — landline / mobile / +81 international with strict
                       boundary lookahead (mirrors security/pii_redact._PHONE_RE
                       so behavior is consistent on the existing surface).
    4. **mynumber**   — 個人番号 (12 桁 連続) with separator-aware
                       boundary so it does NOT eat 法人番号 (13 桁) or
                       canonical-id substrings.
    5. **account**    — 銀行口座 4-7 桁 numeric strings prefixed by
                       支店/口座 token (普通/当座). Conservative — bare
                       digit runs are not matched.
    6. **email**      — RFC 5322-lite (mirrors security/pii_redact._EMAIL_RE).
    7. **houjin**     — 法人番号 (T+13 digits). **Gated** (default
                       PRESERVE) per memory `feedback_no_fake_data` and
                       the Wave 43 S7 fix (gbiz / 国税庁 PDL v1.0 公開
                       情報). Operators flip
                       ``AUTONOMATH_PII_REDACT_HOUJIN_BANGOU=1`` to mask.

Non-goals (anti-creep)
----------------------
* Does NOT replace ``jpintel_mcp.security.pii_redact`` — the 3-pattern
  module continues to serve the response_sanitizer cascade layer 0 and
  the telemetry redact path. This module is **additive**: callers that
  want the broader Dim N strict policy import this module explicitly.
* Does NOT add new env knobs. Houjin gate honors the existing
  ``settings.pii_redact_houjin_bangou`` toggle so operator surface
  remains identical.
* Does NOT log raw values. The ``redact_with_audit`` hook emits ONLY
  pattern ids + hit counts to the standard ``jpintel.api._pii_redact``
  logger — never the matched substring.

Public surface
--------------
    PATTERNS                       — tuple of (id, compiled regex, replacement)
    redact_strict(text)            -> str
    redact_strict_with_hits(text)  -> tuple[str, list[str]]
    redact_with_audit(text)        -> tuple[str, list[str]]
                                       (logs hits to audit logger; safe noop on empty)
"""

from __future__ import annotations

import logging
import re
from typing import Final

logger = logging.getLogger("jpintel.api._pii_redact")

# 1) JP 個人氏名 — strict.
#    Two paths:
#      a) 漢字 surname (2-4 chars) + 漢字 given (1-4 chars) bounded by
#         non-CJK char on either side. Avoids gobbling sentence-level
#         CJK runs by requiring a 1-char ASCII space / punctuation
#         lookaround.
#      b) Katakana 姓 + 名 separated by "・" or " " (full/half width).
#    法人 / 団体 names are not matched because they almost always carry
#    a corporate-suffix token (株式会社/有限会社/合同会社/etc.) which is
#    blocked by an explicit negative lookahead.
_NAME_KANJI_RE = re.compile(
    r"(?<![一-鿿゠-ヿ])"
    r"(?![株有合社財団]式?会社|株式会社|有限会社|合同会社|合名会社|合資会社|"
    r"財団法人|社団法人|学校法人|医療法人|宗教法人|特定非営利活動法人|協同組合)"
    r"[一-鿿]{2,4}"
    r"(?:\s|　)?"
    r"[一-鿿]{1,4}"
    r"(?![一-鿿])"
)
_NAME_KATAKANA_RE = re.compile(
    r"(?<![゠-ヿ])"
    r"[ァ-ヺー]{2,8}"
    r"[\s　・]"
    r"[ァ-ヺー]{2,8}"
    r"(?![゠-ヿ])"
)

# 2) JP 住所 — 都道府県 prefix + 市区町村 + 数字 chōme/building.
#    Conservative to avoid eating generic industry / region labels.
_PREFECTURE_TOKEN = (
    r"(?:北海道|青森県|岩手県|宮城県|秋田県|山形県|福島県|"
    r"茨城県|栃木県|群馬県|埼玉県|千葉県|東京都|神奈川県|"
    r"新潟県|富山県|石川県|福井県|山梨県|長野県|"
    r"岐阜県|静岡県|愛知県|三重県|"
    r"滋賀県|京都府|大阪府|兵庫県|奈良県|和歌山県|"
    r"鳥取県|島根県|岡山県|広島県|山口県|"
    r"徳島県|香川県|愛媛県|高知県|"
    r"福岡県|佐賀県|長崎県|熊本県|大分県|宮崎県|鹿児島県|沖縄県)"
)
_ADDRESS_RE = re.compile(
    _PREFECTURE_TOKEN
    + r"[一-鿿゠-ヿ\w]{1,30}"
    + r"(?:[0-9０-９]{1,4}[-丁目]?){1,4}"
)

# 3) JP phone — mirrors security/pii_redact._PHONE_RE for behavior parity.
_PHONE_RE = re.compile(
    r"(?<!\d)"
    r"(?:"
    r"\+?81[-\s]\d{1,4}[-\s.]\d{1,4}[-\s.]\d{3,4}"
    r"|0\d{1,4}[-\s.]\d{1,4}[-\s.]\d{3,4}"
    r"|0[789]0\d{8}"
    r")"
    r"(?!\d)"
)

# 4) 個人番号 (My Number) — 12 桁 連続. Strict boundary so 13桁 houjin
#    (e.g. ``T8010001213708`` or bare ``1010401030882``) does NOT match.
_MYNUMBER_RE = re.compile(r"(?<!\d)(?<!T)\d{12}(?!\d)")

# 5) 銀行口座 — requires 普通/当座/口座/支店 token within 16 chars before
#    a 4-7 digit run. Bare digit runs are deliberately NOT matched.
_ACCOUNT_RE = re.compile(
    r"(?:普通|当座|口座|支店)[^\d]{0,16}"
    r"(?<!\d)\d{4,7}(?!\d)"
)

# 6) Email — mirrors security/pii_redact._EMAIL_RE.
_EMAIL_RE = re.compile(r"[\w.-]+@[\w.-]+\.[a-zA-Z]{2,}")

# 7) 法人番号 — gated. The regex itself is identical to
#    security/pii_redact._HOUJIN_RE; the gate is honored at runtime in
#    ``redact_strict_with_hits``.
_HOUJIN_RE = re.compile(r"T\d{13}")


# Public pattern table. Order matters: more-specific patterns first so
# the broader ones (name / address) don't gobble already-redacted
# placeholders. Each tuple is (id, compiled_regex, replacement_token).
PATTERNS: Final[tuple[tuple[str, re.Pattern[str], str], ...]] = (
    ("pii-houjin", _HOUJIN_RE, "[REDACTED:HOUJIN]"),     # gated
    ("pii-email", _EMAIL_RE, "[REDACTED:EMAIL]"),
    ("pii-phone", _PHONE_RE, "[REDACTED:PHONE]"),
    ("pii-mynumber", _MYNUMBER_RE, "[REDACTED:MYNUMBER]"),
    ("pii-account", _ACCOUNT_RE, "[REDACTED:ACCOUNT]"),
    ("pii-address", _ADDRESS_RE, "[REDACTED:ADDRESS]"),
    ("pii-name", _NAME_KATAKANA_RE, "[REDACTED:NAME]"),
    # Kanji name applied last because it is the broadest pattern and
    # could eat substrings of 法人 / 住所 if applied earlier.
    ("pii-name-kanji", _NAME_KANJI_RE, "[REDACTED:NAME]"),
)


def _houjin_gate_enabled() -> bool:
    """Read the houjin gate from runtime settings, default False.

    Lazy import keeps this module importable in pure-regex unit tests
    that never load the FastAPI / pydantic-settings stack — same posture
    as ``security/pii_redact.redact_response_text``.
    """
    try:
        from jpintel_mcp.config import settings as _settings

        return bool(getattr(_settings, "pii_redact_houjin_bangou", False))
    except Exception:
        return False


def redact_strict(text: str) -> str:
    """Apply the 7-pattern Dim N strict redact, return cleaned string only.

    Empty / None inputs pass through. Houjin pattern is gated.
    """
    if not text:
        return text
    out = text
    gate = _houjin_gate_enabled()
    for pid, pat, repl in PATTERNS:
        if pid == "pii-houjin" and not gate:
            continue
        out = pat.sub(repl, out)
    return out


def redact_strict_with_hits(text: str) -> tuple[str, list[str]]:
    """Apply 7-pattern redact and return (clean, hit_ids).

    ``hit_ids`` lists each pattern id that fired (deduplicated). Houjin
    pattern is gated; when off, it never fires and never appears.
    """
    if not text:
        return text, []
    out = text
    hits: list[str] = []
    seen: set[str] = set()
    gate = _houjin_gate_enabled()
    for pid, pat, repl in PATTERNS:
        if pid == "pii-houjin" and not gate:
            continue
        new_out, n = pat.subn(repl, out)
        if n and pid not in seen:
            hits.append(pid)
            seen.add(pid)
        out = new_out
    return out, hits


def redact_with_audit(text: str) -> tuple[str, list[str]]:
    """``redact_strict_with_hits`` + audit-log emit (id + count only).

    Logs ONE info record per call summarizing the pattern ids that
    fired plus a per-pattern hit count. NEVER logs the raw / cleaned
    text — only metadata, mirroring the migration 274
    ``am_anonymized_query_log.pii_stripped`` discipline.
    """
    clean, hits = redact_strict_with_hits(text)
    if hits:
        # Per-pattern counts via cheap re-count on the original; the
        # value is small and bounded by 7 regex passes on text that
        # is already PII-sized (typically < 4 KB). Houjin gate honored.
        gate = _houjin_gate_enabled()
        counts: dict[str, int] = {}
        for pid, pat, _repl in PATTERNS:
            if pid == "pii-houjin" and not gate:
                continue
            if pid in hits:
                counts[pid] = len(pat.findall(text))
        logger.info(
            "pii_redact_hits", extra={"hits": hits, "counts": counts}
        )
    return clean, hits


__all__ = [
    "PATTERNS",
    "redact_strict",
    "redact_strict_with_hits",
    "redact_with_audit",
]
