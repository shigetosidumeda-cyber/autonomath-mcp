"""Wave 51 dim N — atomic test suite for ``jpintel_mcp.anonymized_query``.

Covers three primitives:

    * k-anonymity floor (``check_k_anonymity``) — including the
      compliance-floor lower-bound guard.
    * PII redact, both whitelist-strip (``redact_pii_fields``) and
      text-pattern (``redact_text``).
    * Append-only audit log (``write_audit_entry`` + ``read_audit_entries``).

Fixtures use realistic Japanese PII shapes (法人番号 / 個人氏名 /
都道府県+番地 + 個人/法人 number boundaries) so a regression that
silently breaks Japanese-specific patterns surfaces here.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from jpintel_mcp.anonymized_query import (
    JP_PII_FIELDS,
    K_ANONYMITY_MIN,
    REDACT_POLICY_VERSION,
    check_k_anonymity,
    redact_pii_fields,
    redact_text,
    write_audit_entry,
)
from jpintel_mcp.anonymized_query.audit_log import (
    cohort_hash,
    read_audit_entries,
)

# --- k-anonymity --------------------------------------------------------


class TestCheckKAnonymity:
    def test_floor_is_5_module_constant(self) -> None:
        # Per feedback_anonymized_query_pii_redact: "k=5 hard cap".
        assert K_ANONYMITY_MIN == 5

    def test_exactly_at_floor_passes(self) -> None:
        result = check_k_anonymity(5)
        assert result.ok is True
        assert result.reason == "ok"
        assert result.cohort_size == 5

    def test_one_below_floor_rejected(self) -> None:
        result = check_k_anonymity(4)
        assert result.ok is False
        assert result.reason == "cohort_too_small"
        assert result.cohort_size == 4

    def test_zero_cohort_rejected(self) -> None:
        result = check_k_anonymity(0)
        assert result.ok is False
        assert result.reason == "cohort_too_small"

    def test_negative_cohort_rejected_with_distinct_reason(self) -> None:
        # Distinct reason code lets the audit log surface "this would
        # have been a bug" vs "this was just a tiny cohort".
        result = check_k_anonymity(-3)
        assert result.ok is False
        assert result.reason == "negative_cohort"

    def test_floor_cannot_be_lowered_below_5(self) -> None:
        # Compliance floor guard — even an explicit override cannot
        # silently drop the bar.
        with pytest.raises(ValueError, match="k-anonymity floor cannot be lowered"):
            check_k_anonymity(10, floor=3)

    def test_floor_can_be_raised(self) -> None:
        # Raising to k=10 for a stricter cohort is allowed.
        result = check_k_anonymity(7, floor=10)
        assert result.ok is False
        assert result.reason == "cohort_too_small"
        result_ok = check_k_anonymity(15, floor=10)
        assert result_ok.ok is True

    def test_bool_is_not_an_int(self) -> None:
        # Python treats ``True`` as ``1`` — without an explicit guard
        # this would be a valid "1-entity cohort" sneaking past the gate.
        with pytest.raises(TypeError, match="cohort_size must be int"):
            check_k_anonymity(True)  # type: ignore[arg-type]

    def test_non_int_rejected(self) -> None:
        with pytest.raises(TypeError):
            check_k_anonymity("5")  # type: ignore[arg-type]


# --- PII redact: whitelist strip ----------------------------------------


class TestRedactPiiFields:
    def test_jp_pii_fields_covers_dim_n_design_intent(self) -> None:
        # Spot-check that the canonical PII fields from the dim N memo
        # are all in the strip set.
        for required in (
            "houjin_bangou",
            "法人番号",
            "代表者名",
            "住所",
            "番地",
            "電話番号",
            "email",
            "マイナンバー",
        ):
            assert required in JP_PII_FIELDS, f"{required} must be in JP_PII_FIELDS"

    def test_strips_japanese_corporate_fields(self) -> None:
        row = {
            "houjin_bangou": "T8010001213708",
            "法人番号": "T8010001213708",
            "industry_jsic_major": "D",
            "region_code": "13101",
            "size_bucket": "small",
            "amount_yen": 5_000_000,
        }
        clean = redact_pii_fields(row)
        assert "houjin_bangou" not in clean
        assert "法人番号" not in clean
        # cohort-defining fields MUST survive
        assert clean["industry_jsic_major"] == "D"
        assert clean["region_code"] == "13101"
        assert clean["size_bucket"] == "small"
        assert clean["amount_yen"] == 5_000_000

    def test_strips_personal_identifiers(self) -> None:
        row = {
            "氏名": "山田 太郎",
            "代表者名": "佐藤 花子",
            "マイナンバー": "123456789012",
            "phone_number": "03-1234-5678",
            "住所": "東京都千代田区霞が関1-2-3",
            "industry_jsic_major": "K",
        }
        clean = redact_pii_fields(row)
        for forbidden in ("氏名", "代表者名", "マイナンバー", "phone_number", "住所"):
            assert forbidden not in clean
        assert clean["industry_jsic_major"] == "K"

    def test_does_not_mutate_input(self) -> None:
        # Audit log writer needs the original row unchanged for hashing.
        row = {"houjin_bangou": "T8010001213708", "industry_jsic_major": "D"}
        before = dict(row)
        redact_pii_fields(row)
        assert row == before

    def test_extra_keys_are_stripped(self) -> None:
        row = {
            "industry_jsic_major": "D",
            "saved_search_seed_owner": "shigetomeda@example.co.jp",
        }
        clean = redact_pii_fields(row, extra_keys=frozenset({"saved_search_seed_owner"}))
        assert "saved_search_seed_owner" not in clean
        assert clean["industry_jsic_major"] == "D"

    def test_case_insensitive_strip(self) -> None:
        row = {"HOUJIN_BANGOU": "T8010001213708", "industry_jsic_major": "D"}
        clean = redact_pii_fields(row)
        assert "HOUJIN_BANGOU" not in clean

    def test_text_pii_in_kept_value_is_scrubbed(self) -> None:
        # If a free-text "notes" field survives, embedded PII inside it
        # must still be redacted via the text pattern path.
        row = {
            "industry_jsic_major": "D",
            "notes": "担当 田中様 までご連絡ください。電話 090-1234-5678 / メール tanaka@example.co.jp",
        }
        clean = redact_pii_fields(row)
        notes = clean["notes"]
        assert "090-1234-5678" not in notes
        assert "tanaka@example.co.jp" not in notes
        assert "[REDACTED:PHONE]" in notes
        assert "[REDACTED:EMAIL]" in notes


# --- PII redact: text patterns ------------------------------------------


class TestRedactText:
    def test_empty_string(self) -> None:
        clean, hits = redact_text("")
        assert clean == ""
        assert hits == []

    def test_houjin_bangou_redacted(self) -> None:
        clean, hits = redact_text("法人番号 T8010001213708 で照会")
        assert "T8010001213708" not in clean
        assert "houjin" in hits

    def test_japanese_phone_landline(self) -> None:
        clean, hits = redact_text("お問い合わせ: 03-1234-5678")
        assert "03-1234-5678" not in clean
        assert "phone" in hits

    def test_japanese_phone_mobile_no_separator(self) -> None:
        clean, hits = redact_text("携帯: 09012345678")
        assert "09012345678" not in clean
        assert "phone" in hits

    def test_email_redacted(self) -> None:
        clean, hits = redact_text("送信先 info@bookyou.net まで")
        assert "info@bookyou.net" not in clean
        assert "email" in hits

    def test_mynumber_redacted(self) -> None:
        # 個人番号 = 12 digits, distinct from 法人番号 (13).
        clean, hits = redact_text("マイナンバー 123456789012 を確認")
        assert "123456789012" not in clean
        assert "mynumber" in hits

    def test_houjin_bangou_is_not_eaten_by_phone(self) -> None:
        # Regression guard: 13桁 houjin must not match the phone pattern.
        # We expect "houjin" hit but NOT "phone".
        clean, hits = redact_text("T8010001213708")
        assert "T8010001213708" not in clean
        assert "houjin" in hits
        # Phone must NOT have eaten the bare digits.
        assert "phone" not in hits

    def test_address_with_chome_banchi(self) -> None:
        clean, hits = redact_text("所在地: 東京都文京区小日向2-22-1")
        assert "東京都文京区小日向2-22-1" not in clean
        assert "address" in hits

    def test_no_false_positive_on_canonical_id(self) -> None:
        # canonical_id strings like "program:04_program_documents:000000"
        # must NOT be redacted as PII (they are a structural key).
        canonical = "program:04_program_documents:000000"
        clean, hits = redact_text(canonical)
        assert clean == canonical
        assert hits == []

    def test_no_false_positive_on_sha256_digest(self) -> None:
        digest = "a" * 64  # 64-char hex pattern
        clean, hits = redact_text(digest)
        assert clean == digest
        assert hits == []

    def test_multiple_pii_in_one_string(self) -> None:
        s = "山田 太郎様 (T8010001213708) 03-1234-5678 yamada@example.co.jp"
        clean, hits = redact_text(s)
        assert "T8010001213708" not in clean
        assert "03-1234-5678" not in clean
        assert "yamada@example.co.jp" not in clean
        # All three patterns must have fired.
        assert "houjin" in hits
        assert "phone" in hits
        assert "email" in hits


# --- Audit log ----------------------------------------------------------


class TestAuditLog:
    def test_redact_policy_version_is_pinned(self) -> None:
        assert REDACT_POLICY_VERSION.startswith("dim-n-v")

    def test_cohort_hash_is_deterministic(self) -> None:
        h1 = cohort_hash("D", "13101", "small")
        h2 = cohort_hash("D", "13101", "small")
        assert h1 == h2
        # SHA-256 hex length
        assert len(h1) == 64
        # Domain separation: a different namespace must yield a
        # different hash for the same input.
        h_none = cohort_hash(None, None, None)
        assert h_none != h1

    def test_write_then_read_roundtrip(self, tmp_path: Path) -> None:
        log_path = tmp_path / "anonymized_query_audit.jsonl"
        entry = write_audit_entry(
            cohort_hash_hex=cohort_hash("D", "13101", "small"),
            redact_policy_version=REDACT_POLICY_VERSION,
            cohort_size=23,
            reason="ok",
            pii_hits=["houjin", "phone"],
            path=log_path,
        )
        assert entry.cohort_size == 23
        assert entry.reason == "ok"
        assert entry.pii_hits == ["houjin", "phone"]
        rows = read_audit_entries(log_path)
        assert len(rows) == 1
        assert rows[0]["cohort_size"] == 23
        assert rows[0]["reason"] == "ok"
        assert rows[0]["redact_policy_version"] == REDACT_POLICY_VERSION
        assert rows[0]["pii_hits"] == ["houjin", "phone"]

    def test_append_only_three_rows(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.jsonl"
        for size, reason in [(7, "ok"), (3, "cohort_too_small"), (12, "ok")]:
            write_audit_entry(
                cohort_hash_hex=cohort_hash("D", None, None),
                redact_policy_version=REDACT_POLICY_VERSION,
                cohort_size=size,
                reason=reason,
                path=log_path,
            )
        rows = read_audit_entries(log_path)
        assert [r["cohort_size"] for r in rows] == [7, 3, 12]
        assert [r["reason"] for r in rows] == ["ok", "cohort_too_small", "ok"]

    def test_pii_hits_deduplicated_and_sorted(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.jsonl"
        write_audit_entry(
            cohort_hash_hex=cohort_hash("D", None, None),
            redact_policy_version=REDACT_POLICY_VERSION,
            cohort_size=5,
            reason="ok",
            pii_hits=["phone", "email", "phone", "houjin"],
            path=log_path,
        )
        rows = read_audit_entries(log_path)
        # Sorted alphabetically + deduplicated.
        assert rows[0]["pii_hits"] == ["email", "houjin", "phone"]

    def test_raw_houjin_as_hash_is_rejected(self, tmp_path: Path) -> None:
        # Hard compliance guard: passing a 13桁 houjin where the hash is
        # expected must raise BEFORE the file is opened.
        log_path = tmp_path / "audit.jsonl"
        with pytest.raises(ValueError, match="64 lowercase hex"):
            write_audit_entry(
                cohort_hash_hex="T8010001213708",  # raw, not hashed
                redact_policy_version=REDACT_POLICY_VERSION,
                cohort_size=5,
                reason="ok",
                path=log_path,
            )
        assert not log_path.exists()

    def test_unknown_reason_rejected(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.jsonl"
        with pytest.raises(ValueError, match="not in"):
            write_audit_entry(
                cohort_hash_hex=cohort_hash("D", None, None),
                redact_policy_version=REDACT_POLICY_VERSION,
                cohort_size=5,
                reason="totally-made-up",  # not in _VALID_REASONS
                path=log_path,
            )

    def test_write_audit_entry_creates_parent_dir(self, tmp_path: Path) -> None:
        log_path = tmp_path / "nested" / "subdir" / "audit.jsonl"
        write_audit_entry(
            cohort_hash_hex=cohort_hash("D", None, None),
            redact_policy_version=REDACT_POLICY_VERSION,
            cohort_size=5,
            reason="ok",
            path=log_path,
        )
        assert log_path.exists()

    def test_each_row_is_valid_json(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.jsonl"
        write_audit_entry(
            cohort_hash_hex=cohort_hash("D", None, None),
            redact_policy_version=REDACT_POLICY_VERSION,
            cohort_size=5,
            reason="ok",
            pii_hits=["email"],
            path=log_path,
        )
        text = log_path.read_text(encoding="utf-8")
        # Every line parses as JSON and ends with a newline.
        for line in text.splitlines():
            payload = json.loads(line)
            assert set(payload).issuperset(
                {"ts", "cohort_hash", "redact_policy_version", "cohort_size", "reason", "pii_hits"}
            )
        assert text.endswith("\n")
