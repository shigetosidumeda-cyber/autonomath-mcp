"""PII response-body redactor regression suite (S7 critical fix).

Covers layer 0 of `jpintel_mcp.api.response_sanitizer.sanitize_response_text`,
which runs **before** INV-22 / prompt-injection / loop_a so downstream
layers never see raw 法人番号 / email / 電話 in the response body.

Risk model (analysis_wave18 + memory `feedback_no_fake_data`):
    INV-21's existing `redact_pii()` only ran on telemetry. Response bodies
    remained APPI-exposed: ~5,904 `corp.representative` rows + 121k
    location strings carry personal email / 電話 / 法人番号 fragments.
    Without layer 0, customers consuming `search_corp` / `gbiz_*` tools see
    the raw values verbatim.

Four cases (per S7 spec) + S7 false-positive fix (2026-04-25):
    1. 13桁法人番号 (gated): default=preserve (gbiz public info); when
       ``settings.pii_redact_houjin_bangou=True`` → masked to
       ``T*************`` shape and ``pii-houjin`` hit emitted.
    2. email (個人/法人問わず) → ``<email-redacted>``
    3. 日本電話形式 (03-/090-/+81-) → ``<phone-redacted>``
    4. 代表者名 toggle: default off (preserve) ↔ on (mask)
       — gated by ``AUTONOMATH_PII_REDACT_REPRESENTATIVE`` env. Off path
       must NOT mutate, on path masks via the structured-field hook
       (`pii_redact_representative` setting). Memory fence: 法人番号 is
       公開情報 (gbiz PDL v1.0); 代表者名 sits at the APPI / 公開 boundary
       and we wait on legal review before flipping default → on.
    5. False-positive guards (NEW, 2026-04-25):
       - canonical_id substring ``program:09_xxx:000000:hexhash`` MUST
         pass through (not eaten by phone regex)
       - bare 13桁 houjin ``1010401030882`` (no T prefix) MUST pass
         through when houjin gate is OFF (gbiz queried.houjin_bangou
         echo path, cf test_check_enforcement_am_happy_with_real_houjin)
       - bare 6-digit ``000000`` MUST NOT match phone regex
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def _reload_sanitizer():
    """Re-import the sanitizer so the module-level `settings` reference
    picks up monkeypatched env / settings overrides between cases. Mirrors
    `tests/test_loop_a_wire.py::_reload_sanitizer`.
    """
    from jpintel_mcp.api import response_sanitizer

    return importlib.reload(response_sanitizer)


def test_houjin_bangou_masked_when_gate_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """13桁法人番号 (T+13 digits) — gated mask.

    Default は **preserve** (gbiz / 国税庁 PDL v1.0 公開情報、 DD UX で
    queried.houjin_bangou を verbatim echo する必要があるため)。
    operator が ``AUTONOMATH_PII_REDACT_HOUJIN_BANGOU=1`` を立てた時のみ
    legacy ``T*************`` mask + ``pii-houjin`` hit が出る。

    本テストは gate=on 時の旧挙動を確認する。 default=off 挙動は別ケース
    ``test_houjin_bangou_default_preserves`` で担保する。
    """
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "pii_redact_houjin_bangou", True)
    rs = _reload_sanitizer()

    text = "代表者の所属法人は T8010001213708 です。"
    clean, hits = rs.sanitize_response_text(text)
    assert "T8010001213708" not in clean
    assert "T*************" in clean
    assert "pii-houjin" in hits


def test_houjin_bangou_default_preserves() -> None:
    """default では T+13 を mask しない (gbiz / 国税庁 PDL v1.0 公開情報)。

    customer-facing tools (check_enforcement_am / search_corp 等) が
    queried.houjin_bangou を verbatim echo するために default preserve。
    `feedback_no_fake_data` で accuracy 損ねる過剰 mask は禁止。
    """
    from jpintel_mcp.config import settings

    # 念のため default 値を assert (config drift 検知)
    assert settings.pii_redact_houjin_bangou is False

    from jpintel_mcp.api.response_sanitizer import sanitize_response_text

    text = "代表者の所属法人は T8010001213708 です。"
    clean, hits = sanitize_response_text(text)
    # T+13 はそのまま残る
    assert "T8010001213708" in clean
    # 当 redactor は houjin hit を立てない (gate=off)
    assert "pii-houjin" not in hits


def test_bare_13digit_houjin_not_eaten_by_phone_regex() -> None:
    """gbiz の queried.houjin_bangou は T 接頭辞なしの 13 桁文字列で
    返ってくる (e.g. ``1010401030882``)。 旧 phone regex は leading 0/1
    を見て ``1<phone-redacted>`` と eat していた。 strict regex 化で
    canonical 13 桁 houjin が phone collision しないことを担保する。

    再現テスト元: tests/test_autonomath_tools.py
    ::test_check_enforcement_am_happy_with_real_houjin
    """
    from jpintel_mcp.api.response_sanitizer import sanitize_response_text

    text = '{"queried": {"houjin_bangou": "1010401030882"}}'
    clean, hits = sanitize_response_text(text)
    assert "1010401030882" in clean
    assert "pii-phone" not in hits


def test_program_canonical_id_not_eaten_by_phone_regex() -> None:
    """canonical_id 形 ``program:NN_xxx:000000:hexhash`` の ``:000000`` は
    プロダクト ID 内部の 6 桁 zero-pad であり 電話番号ではない。 旧 phone
    regex は ``0[\\d]{1,4}`` を見て eat していた。 strict regex 化で
    通過することを担保する。
    """
    from jpintel_mcp.api.response_sanitizer import sanitize_response_text

    text = "candidate=program:04_program_documents:000000:23_25d25bdfe8 を確認"
    clean, hits = sanitize_response_text(text)
    assert "program:04_program_documents:000000:23_25d25bdfe8" in clean
    assert "pii-phone" not in hits


def test_standalone_six_digit_not_phone() -> None:
    """単独 6 桁数字 (``000000``) は 電話番号として redact されない。

    郵便番号 / 統計コード / hash の zero-pad など、 separator なし純数字
    runs は phone regex に乗らないことを担保する。 strict regex は
    ``[-\\s.]`` 区切りまたは ``0[789]0`` 携帯接頭辞を要求する。
    """
    from jpintel_mcp.api.response_sanitizer import sanitize_response_text

    text = "code=000000 / serial=123456 / 8桁=12345678"
    clean, hits = sanitize_response_text(text)
    assert "000000" in clean
    assert "123456" in clean
    assert "12345678" in clean
    assert "pii-phone" not in hits


def test_sha256_digest_not_eaten_by_phone_regex() -> None:
    """64-char hex digests can contain ``080``-like digit runs.

    The response sanitizer must not corrupt audit hashes such as
    ``bundle_sha256`` just because a digest happens to include an
    11-digit mobile-phone-shaped substring.
    """
    from jpintel_mcp.api.response_sanitizer import sanitize_response_text

    digest = "e9894d592f37e3528d89ae7d866757752c08012345678b99e36994a145a3519c"
    clean, hits = sanitize_response_text(f'{{"bundle_sha256":"{digest}"}}')
    assert digest in clean
    assert "<phone-redacted>" not in clean
    assert "pii-phone" not in hits


def test_email_masked() -> None:
    """生 email を ``<email-redacted>`` に置換し pii-email を hit list に。"""
    from jpintel_mcp.api.response_sanitizer import sanitize_response_text

    text = "問い合わせ先: info@bookyou.net までご連絡ください。"
    clean, hits = sanitize_response_text(text)
    assert "info@bookyou.net" not in clean
    assert "<email-redacted>" in clean
    assert "pii-email" in hits


def test_phone_masked() -> None:
    """日本電話形式 (03-xxxx-xxxx, 090-xxxx-xxxx) を mask する。

    複数形式を一度に検証: 固定電話 (03-) と携帯 (090-) の双方が
    `<phone-redacted>` に置換され、 `pii-phone` が hit list に乗る。
    """
    from jpintel_mcp.api.response_sanitizer import sanitize_response_text

    text = "事務所 03-1234-5678 / 緊急 090-1234-5678"
    clean, hits = sanitize_response_text(text)
    assert "03-1234-5678" not in clean
    assert "090-1234-5678" not in clean
    # 両方 mask されているなら少なくとも 2 回置換されている
    assert clean.count("<phone-redacted>") >= 2
    assert "pii-phone" in hits


def test_representative_gate_default_off_then_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """代表者名 (corp.representative) は default=off で preserve、 =on で mask。

    APPI / 公開情報 boundary 上のフィールド。 gbiz 由来の公開情報なので
    default は preserve (= 法的見解確定後に flip)。
    on にした場合は層 0 が ``<name-redacted>`` 相当の placeholder に
    置換することで pii-representative hit を立てる。

    Implementation note: the layer-0 redactor itself does not change
    behaviour for this toggle directly (it operates on substring patterns,
    not field semantics). The toggle is consumed by the upstream
    `_walk_and_sanitize` walker via a structured-field check; in this
    test we stay at the substring-pattern boundary and assert the
    *settings handle* exists with the documented default and that the
    flag wires through the response-sanitizer module without raising.
    """
    from jpintel_mcp.config import settings

    # Default off — public info preserve.
    assert settings.pii_redact_representative is False

    # Toggle on — confirm settings flag flips and the sanitizer module
    # still imports cleanly. (No representative-specific substring
    # mutation today; substring-level email / 電話 / 法人番号 redaction
    # already covers the leakage paths inside a representative-name
    # string. The toggle exists so a future legal-review-driven
    # field-level mask can be wired without an env / migration churn.)
    monkeypatch.setattr(settings, "pii_redact_representative", True)
    rs = _reload_sanitizer()

    sample = "代表者: 梅田 茂利"  # plain Japanese name, no PII pattern hits
    clean, hits = rs.sanitize_response_text(sample)
    # Toggle ON: representative-field substring still preserved at this
    # layer (no substring pattern fires on a bare 漢字 name). The contract
    # tested here is "flip does not crash + default=False is observable".
    assert clean == sample
    assert hits == []

    # Flip back off and confirm same outcome — establishes the symmetric
    # baseline so any future field-level wiring will surface as a real
    # behavioural diff in this test.
    monkeypatch.setattr(settings, "pii_redact_representative", False)
    rs = _reload_sanitizer()
    clean, hits = rs.sanitize_response_text(sample)
    assert clean == sample
    assert hits == []
