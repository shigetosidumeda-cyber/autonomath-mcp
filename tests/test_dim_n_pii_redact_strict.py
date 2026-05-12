"""Wave 49 tick#7 Dim N Phase 1 — extended PII redact (7 patterns × 3 = 21 tests).

Tests the additive ``src.jpintel_mcp.api._pii_redact`` module. The legacy
3-pattern redactor (``src.jpintel_mcp.security.pii_redact``) is NOT
touched by this PR and is regression-covered by
``tests/test_pii_redactor_response.py``.

Per memory ``feedback_anonymized_query_pii_redact``:
  ZERO raw PII MUST leak via the Dim N strict surface. Each pattern
  here corresponds to a category called out in that memory and the
  Wave 47 migration 274 (anonymized query log) audit policy.

7 patterns × 3 cases = 21 tests, plus a small batch of negative
"should NOT eat this" tests guarding canonical-id substrings and 法人
suffix tokens that previously regressed in security/pii_redact (S7 fix,
2026-04-25).
"""

from __future__ import annotations

import pytest

from jpintel_mcp.api._pii_redact import (
    PATTERNS,
    redact_strict,
    redact_strict_with_hits,
    redact_with_audit,
)


# ---------------------------------------------------------------------------
# 1) NAME (kanji + katakana) — 3 cases
# ---------------------------------------------------------------------------


def test_name_kanji_simple_pair() -> None:
    text = "報告者は 山田 太郎 です。"
    clean, hits = redact_strict_with_hits(text)
    assert "山田" not in clean or "[REDACTED:NAME]" in clean
    assert any(h.startswith("pii-name") for h in hits)


def test_name_kanji_no_space() -> None:
    text = "（佐藤花子 は連絡先確認済み）"
    clean, hits = redact_strict_with_hits(text)
    assert "佐藤花子" not in clean
    assert any(h.startswith("pii-name") for h in hits)


def test_name_katakana_with_middot() -> None:
    text = "発表者: タナカ・ハナコ さん"
    clean, hits = redact_strict_with_hits(text)
    assert "タナカ・ハナコ" not in clean
    assert "[REDACTED:NAME]" in clean
    assert any(h.startswith("pii-name") for h in hits)


# ---------------------------------------------------------------------------
# 2) ADDRESS — 3 cases
# ---------------------------------------------------------------------------


def test_address_tokyo_chiyoda() -> None:
    text = "本社所在地: 東京都千代田区丸の内1丁目1番1号"
    clean, hits = redact_strict_with_hits(text)
    assert "千代田区丸の内" not in clean
    assert "[REDACTED:ADDRESS]" in clean
    assert "pii-address" in hits


def test_address_osaka_chuo() -> None:
    text = "拠点: 大阪府大阪市中央区本町2-3"
    clean, hits = redact_strict_with_hits(text)
    assert "[REDACTED:ADDRESS]" in clean
    assert "pii-address" in hits


def test_address_hokkaido_long() -> None:
    text = "営農場: 北海道札幌市北区北24条西10丁目"
    clean, hits = redact_strict_with_hits(text)
    assert "[REDACTED:ADDRESS]" in clean
    assert "pii-address" in hits


# ---------------------------------------------------------------------------
# 3) PHONE — 3 cases
# ---------------------------------------------------------------------------


def test_phone_landline_tokyo() -> None:
    text = "問合せ: 03-1234-5678"
    clean, hits = redact_strict_with_hits(text)
    assert "03-1234-5678" not in clean
    assert "[REDACTED:PHONE]" in clean
    assert "pii-phone" in hits


def test_phone_mobile_no_separator() -> None:
    text = "携帯 09012345678 まで"
    clean, hits = redact_strict_with_hits(text)
    assert "09012345678" not in clean
    assert "[REDACTED:PHONE]" in clean
    assert "pii-phone" in hits


def test_phone_intl_plus81() -> None:
    text = "Direct: +81-3-1234-5678 (JST)"
    clean, hits = redact_strict_with_hits(text)
    assert "+81-3-1234-5678" not in clean
    assert "[REDACTED:PHONE]" in clean
    assert "pii-phone" in hits


# ---------------------------------------------------------------------------
# 4) MYNUMBER (個人番号 12 桁) — 3 cases
# ---------------------------------------------------------------------------


def test_mynumber_simple() -> None:
    text = "本人確認資料の番号: 123456789012"
    clean, hits = redact_strict_with_hits(text)
    assert "123456789012" not in clean
    assert "[REDACTED:MYNUMBER]" in clean
    assert "pii-mynumber" in hits


def test_mynumber_in_sentence() -> None:
    text = "(マイナンバー)999988887777 を控えました。"
    clean, hits = redact_strict_with_hits(text)
    assert "999988887777" not in clean
    assert "pii-mynumber" in hits


def test_mynumber_does_not_eat_houjin_13() -> None:
    # 13桁 houjin (no T prefix) MUST NOT be matched as mynumber when
    # the houjin gate is OFF (default). The negative lookbehind/ahead
    # plus the strict 12-digit count guard this.
    text = "公開法人番号 1010401030882 は gbiz PDL 配下。"
    clean, hits = redact_strict_with_hits(text)
    assert "1010401030882" in clean
    assert "pii-mynumber" not in hits


# ---------------------------------------------------------------------------
# 5) ACCOUNT (銀行口座) — 3 cases
# ---------------------------------------------------------------------------


def test_account_futsuu() -> None:
    text = "振込先 普通 1234567"
    clean, hits = redact_strict_with_hits(text)
    assert "[REDACTED:ACCOUNT]" in clean
    assert "pii-account" in hits


def test_account_touza() -> None:
    text = "請求書: 当座 0000123"
    clean, hits = redact_strict_with_hits(text)
    assert "[REDACTED:ACCOUNT]" in clean
    assert "pii-account" in hits


def test_account_shiten_then_account() -> None:
    text = "本店支店 口座 9876543 を確認"
    clean, hits = redact_strict_with_hits(text)
    assert "[REDACTED:ACCOUNT]" in clean
    assert "pii-account" in hits


# ---------------------------------------------------------------------------
# 6) EMAIL — 3 cases
# ---------------------------------------------------------------------------


def test_email_simple() -> None:
    text = "連絡先: hanako@example.co.jp"
    clean, hits = redact_strict_with_hits(text)
    assert "hanako@example.co.jp" not in clean
    assert "[REDACTED:EMAIL]" in clean
    assert "pii-email" in hits


def test_email_with_subdomain() -> None:
    text = "担当 info+sales@team.dev.bookyou.net まで"
    clean, hits = redact_strict_with_hits(text)
    assert "@team.dev.bookyou.net" not in clean
    assert "pii-email" in hits


def test_email_multiple() -> None:
    text = "support@example.com / billing@example.com 両方記載"
    clean, hits = redact_strict_with_hits(text)
    assert "@example.com" not in clean
    assert "pii-email" in hits


# ---------------------------------------------------------------------------
# 7) HOUJIN (法人番号) — gated; 3 cases (ON / OFF / OFF preserves bare)
# ---------------------------------------------------------------------------


def test_houjin_default_preserves(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: T+13 公開情報 として preserve (gbiz / 国税庁 PDL v1.0)."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "pii_redact_houjin_bangou", False)
    text = "登録番号 T8010001213708 (Bookyou)"
    clean, hits = redact_strict_with_hits(text)
    assert "T8010001213708" in clean
    assert "pii-houjin" not in hits


def test_houjin_gated_on_redacts(monkeypatch: pytest.MonkeyPatch) -> None:
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "pii_redact_houjin_bangou", True)
    text = "登録番号 T8010001213708 (Bookyou)"
    clean, hits = redact_strict_with_hits(text)
    assert "T8010001213708" not in clean
    assert "[REDACTED:HOUJIN]" in clean
    assert "pii-houjin" in hits


def test_houjin_off_does_not_eat_bare13(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bare 13 桁 (no T prefix) must pass through even with gate OFF."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "pii_redact_houjin_bangou", False)
    text = "公開法人番号 1010401030882 (gbiz)"
    clean, hits = redact_strict_with_hits(text)
    assert "1010401030882" in clean
    assert "pii-houjin" not in hits


# ---------------------------------------------------------------------------
# Module-level surface tests (empty / table / audit hook)
# ---------------------------------------------------------------------------


def test_patterns_table_has_7_distinct_ids() -> None:
    """PATTERNS table exposes exactly 7 categories (kanji + katakana name
    share the same pii-name* prefix but use distinct ids for audit)."""
    ids = [pid for pid, _, _ in PATTERNS]
    assert len(ids) == len(set(ids))
    # 7 categories: houjin, email, phone, mynumber, account, address,
    # plus name (kanji + katakana share pii-name* prefix).
    name_ids = {pid for pid in ids if pid.startswith("pii-name")}
    assert len(name_ids) >= 1  # at least one name pattern
    non_name_ids = {pid for pid in ids if not pid.startswith("pii-name")}
    assert non_name_ids == {
        "pii-houjin",
        "pii-email",
        "pii-phone",
        "pii-mynumber",
        "pii-account",
        "pii-address",
    }


def test_empty_string_passthrough() -> None:
    clean, hits = redact_strict_with_hits("")
    assert clean == ""
    assert hits == []
    assert redact_strict("") == ""


def test_redact_with_audit_emits_no_raw(caplog: pytest.LogCaptureFixture) -> None:
    """Audit logger must NOT log the raw matched substring — only ids."""
    text = "連絡先: hanako@example.co.jp / 電話 09012345678"
    with caplog.at_level("INFO", logger="jpintel.api._pii_redact"):
        clean, hits = redact_with_audit(text)
    assert "hanako@example.co.jp" not in caplog.text
    assert "09012345678" not in caplog.text
    assert "pii-email" in hits
    assert "pii-phone" in hits
    # Cleaned output carries the redact tokens.
    assert "[REDACTED:EMAIL]" in clean
    assert "[REDACTED:PHONE]" in clean
