"""PII redaction primitives for dim N anonymized queries.

Wave 51 dim N reuses the proven 7-pattern Wave 49 ``api._pii_redact``
core (個人氏名 / 住所 / 電話 / マイナンバー / 銀行口座 / email / 法人番号)
for *text fields* and applies a **whitelist** strip to *structured
fields* (dict / dataclass / row mapping). The two paths are kept
distinct because:

    * Free-text fields can leak PII anywhere in the body and need
      regex pattern matching.
    * Structured fields have stable column names (``氏名`` /
      ``representative_name`` / ``houjin_bangou`` / ...) and are
      cheaper + safer to handle with a whitelist of cohort-defining
      keys than with a regex pass.

Both surfaces produce the **same** redact policy version string so the
audit log can replay the redact decision deterministically.

JP_PII_FIELDS — fields that MUST be stripped from any structured dict
that crosses an anonymized boundary. Sourced directly from the dim N
design memo ("法人番号 / 住所番地 / 担当者名 全削除").
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

# Bumped on every change to which fields are stripped vs surfaced. The
# REST router under ``api/anonymized_query.py`` historically used v1.0.0;
# this package starts at v1.1.0 because the *structured-field* strip is
# additive (the REST surface only redacted text).
REDACT_POLICY_VERSION: Final[str] = "dim-n-v1.1.0"

# --- Structured-field whitelist of forbidden keys ----------------------
#
# When the caller hands us a dict (e.g. one row of cohort sample data
# pulled from autonomath.db), these field names MUST be deleted before
# the dict leaves the anonymization boundary. We match case-insensitively
# AND treat the Japanese-original + romaji-canonical names equivalently
# because both flavors appear in our schema (法人マスタ vs gbiz mirror).
JP_PII_FIELDS: Final[frozenset[str]] = frozenset(
    {
        # 法人/個人 identifiers
        "houjin_bangou",
        "houjin_number",
        "corporate_number",
        "法人番号",
        "mynumber",
        "my_number",
        "個人番号",
        "マイナンバー",
        # 氏名
        "name",
        "full_name",
        "representative",
        "representative_name",
        "代表者名",
        "氏名",
        "姓名",
        "担当者名",
        "contact_name",
        # 住所
        "address",
        "street_address",
        "住所",
        "所在地",
        "番地",
        "building",
        "建物名",
        # 連絡先
        "phone",
        "telephone",
        "phone_number",
        "電話番号",
        "電話",
        "fax",
        "fax_number",
        "email",
        "email_address",
        "メールアドレス",
        # 口座
        "bank_account",
        "account_number",
        "口座番号",
        "支店名",
        # 個人プロフィール
        "date_of_birth",
        "dob",
        "生年月日",
        "passport_number",
        "パスポート番号",
    }
)

# --- Text-field regex patterns ----------------------------------------
#
# These mirror ``api._pii_redact`` but stay self-contained so this
# package has no runtime dependency on a FastAPI/pydantic stack — it
# must remain usable from cron / ETL / offline operator scripts.

_HOUJIN_RE: Final[re.Pattern[str]] = re.compile(r"T\d{13}")
_EMAIL_RE: Final[re.Pattern[str]] = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
)
# Strict phone — alphanumeric boundary lookbehind / lookahead so we
# don't eat canonical_id substrings or houjin-bangou digit runs.
_PHONE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:"
    r"\+?81[-\s]\d{1,4}[-\s.]\d{1,4}[-\s.]\d{3,4}"
    r"|0\d{1,4}[-\s.]\d{1,4}[-\s.]\d{3,4}"
    r"|0[789]0\d{8}"
    r")"
    r"(?![A-Za-z0-9])"
)
# マイナンバー = 12 digit personal number. Distinguish from 法人番号 (13)
# and canonical hash digests by alphanumeric boundary.
_MYNUMBER_RE: Final[re.Pattern[str]] = re.compile(r"(?<![A-Za-z0-9])\d{12}(?![A-Za-z0-9])")
# 個人氏名 — strict 漢字 4-glyph fallback (姓2+名2). Conservative; the
# structured-field strip handles the high-confidence path.
_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"[一-鿿]{2}\s?[一-鿿]{2}(?=さん|様|氏|殿|先生)"
)
# 住所 — requires 都道府県 + chōme/banchi marker. Tight to avoid eating
# region cohort labels.
_ADDRESS_RE: Final[re.Pattern[str]] = re.compile(
    r"[一-鿿]{1,4}[都道府県][一-鿿々]{1,8}"
    r"[市区町村][一-鿿぀-ゟ゠-ヿ0-9]{0,16}"
    r"\d+[-丁目番地]\d+"
)

PII_TEXT_PATTERNS: Final[tuple[tuple[str, re.Pattern[str], str], ...]] = (
    ("houjin", _HOUJIN_RE, "[REDACTED:HOUJIN]"),
    ("email", _EMAIL_RE, "[REDACTED:EMAIL]"),
    ("phone", _PHONE_RE, "[REDACTED:PHONE]"),
    ("mynumber", _MYNUMBER_RE, "[REDACTED:MYNUMBER]"),
    ("address", _ADDRESS_RE, "[REDACTED:ADDRESS]"),
    ("name", _NAME_RE, "[REDACTED:NAME]"),
)


def redact_text(s: str) -> tuple[str, list[str]]:
    """Redact PII patterns in a single string.

    Returns a tuple ``(clean, hits)`` where ``hits`` is the ordered list
    of pattern ids that fired. Pattern ordering rationale:

    1. ``houjin`` (T+13) — most specific literal prefix, runs first.
    2. ``email`` — runs before phone so local-part digits aren't eaten.
    3. ``phone`` — strict separators only.
    4. ``mynumber`` — 12 digit boundary-anchored.
    5. ``address`` — 都道府県 + 番地 anchor.
    6. ``name`` — 漢字 + honorific suffix anchor (conservative).
    """
    if not s:
        return s, []
    hits: list[str] = []
    out = s
    for pat_id, pat, repl in PII_TEXT_PATTERNS:
        new_out, n = pat.subn(repl, out)
        if n:
            hits.append(pat_id)
            out = new_out
    return out, hits


def redact_pii_fields(
    obj: Mapping[str, Any],
    *,
    extra_keys: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Return a shallow-copied dict with PII fields stripped.

    The input is not mutated — callers can safely pass the raw row from
    a DB query and reuse the original for audit hashing.

    Parameters
    ----------
    obj:
        Mapping representing one row / one structured response.
    extra_keys:
        Optional caller-supplied keys to strip in addition to
        :data:`JP_PII_FIELDS`. Useful for project-specific column names
        (e.g. ``"saved_search_seed_owner"``) without forcing a global
        whitelist edit.

    Returns
    -------
    dict
        New dict with PII keys removed and any **string** leaves passed
        through :func:`redact_text` so embedded PII in free-text values
        (e.g. a ``"notes": "問合せ先 田中様 03-1234-5678"`` field) is also
        scrubbed.
    """
    forbidden = JP_PII_FIELDS if extra_keys is None else JP_PII_FIELDS | extra_keys
    forbidden_lower = {k.lower() for k in forbidden}
    out: dict[str, Any] = {}
    for k, v in obj.items():
        if k in forbidden or k.lower() in forbidden_lower:
            continue
        if isinstance(v, str):
            cleaned, _ = redact_text(v)
            out[k] = cleaned
        else:
            # Non-string leaves (int / float / bool / None) cannot carry
            # textual PII; pass through as-is. Nested dict/list redaction
            # is intentionally NOT recursive — the dim N response shape
            # is flat (aggregate stats), and recursion would silently
            # accept structured PII payloads that should be redesigned.
            out[k] = v
    return out


__all__ = [
    "JP_PII_FIELDS",
    "PII_TEXT_PATTERNS",
    "REDACT_POLICY_VERSION",
    "redact_pii_fields",
    "redact_text",
]
