"""Coverage-boost tests for 5 services modules (Stream AA, Wave 50 tick 9+).

This file adds targeted unit tests to lift coverage on the missing-line
ranges of five "no-LLM" services modules previously covered at
63%-97%. All tests are pure-Python — no DB, no HTTP, no LLM. The few
DB-touching tests build an in-memory ``sqlite3`` connection.

Targets and previous coverage at the start of this stream::

    citation_verifier.py        63%  (156 stmt, 58 miss)  — primary
    fact_conflicts.py           87%  (133 stmt, 17 miss)
    funding_stack_checker.py    92%  (247 stmt, 20 miss)
    known_gaps.py               90%  (126 stmt, 13 miss)
    token_compression.py        97%  ( 67 stmt,  2 miss)

The intent is **additive**: existing tests are untouched. Each test is a
focused poke at one missing branch / helper.

NO production code changes were made — every assertion is read-only.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from jpintel_mcp.services.citation_verifier import (
    MAX_EXCERPT_LEN,
    CitationVerifier,
    _coerce_int,
    _japanese_numeric_forms,
    _normalize_text,
    _strip_html,
)
from jpintel_mcp.services.fact_conflicts import (
    DEFAULT_SINGLETON_FIELD_ALLOWLIST,
    compute_entity_conflict_metadata,
)
from jpintel_mcp.services.known_gaps import (
    LOW_CONFIDENCE_THRESHOLD,
    STALE_THRESHOLD_DAYS,
    detect_gaps,
)
from jpintel_mcp.services.token_compression import (
    ESTIMATE_DISCLAIMER,
    ESTIMATE_METHOD,
    TokenCompressionEstimator,
)

# ---------------------------------------------------------------------------
# citation_verifier — pure helpers
# ---------------------------------------------------------------------------


class TestCitationVerifierHelpers:
    """Cover the pure helpers + verify() branches that ext tests missed."""

    def test_normalize_text_empty_input_returns_empty(self) -> None:
        assert _normalize_text("") == ""

    def test_normalize_text_collapses_full_width_space(self) -> None:
        # NFKC turns 全角空白 + 全角ASCII into half-width equivalents.
        # Then \s+ collapse runs.
        out = _normalize_text("５００万　円")
        assert out == "500万 円"

    def test_normalize_text_collapses_whitespace_runs(self) -> None:
        out = _normalize_text("foo \t\n  bar")
        assert out == "foo bar"

    def test_strip_html_empty_returns_empty(self) -> None:
        assert _strip_html("") == ""

    def test_strip_html_removes_script_and_style_blocks(self) -> None:
        html = (
            "<html><head><style>body{font:red}</style>"
            "<script>alert(1)</script></head>"
            "<body><p>本文</p></body></html>"
        )
        out = _strip_html(html)
        assert "alert" not in out
        assert "font:red" not in out
        assert "本文" in out

    def test_strip_html_handles_multiline_script(self) -> None:
        html = "<script>\n var x = 1;\n var y = 2;\n</script><p>txt</p>"
        out = _strip_html(html)
        assert "var x" not in out
        assert "txt" in out

    # _coerce_int branches
    def test_coerce_int_none(self) -> None:
        assert _coerce_int(None) is None

    def test_coerce_int_bool_rejected(self) -> None:
        # bool subclasses int but must be rejected; True must not coerce to 1.
        assert _coerce_int(True) is None
        assert _coerce_int(False) is None

    def test_coerce_int_positive_int(self) -> None:
        assert _coerce_int(5_000_000) == 5_000_000

    def test_coerce_int_zero_and_negative_int_rejected(self) -> None:
        assert _coerce_int(0) is None
        assert _coerce_int(-1) is None

    def test_coerce_int_integer_valued_float(self) -> None:
        assert _coerce_int(5_000_000.0) == 5_000_000

    def test_coerce_int_fractional_float_rejected(self) -> None:
        assert _coerce_int(1.5) is None

    def test_coerce_int_zero_or_negative_float_rejected(self) -> None:
        assert _coerce_int(-1.0) is None
        assert _coerce_int(0.0) is None

    def test_coerce_int_str_with_commas_and_spaces(self) -> None:
        assert _coerce_int("5, 000, 000") == 5_000_000

    def test_coerce_int_str_empty_or_whitespace_only(self) -> None:
        assert _coerce_int("") is None
        assert _coerce_int("   ") is None

    def test_coerce_int_str_invalid(self) -> None:
        assert _coerce_int("abc") is None
        assert _coerce_int("100xyz") is None

    def test_coerce_int_str_with_dot_integer(self) -> None:
        assert _coerce_int("5000000.0") == 5_000_000

    def test_coerce_int_str_with_dot_fractional_rejected(self) -> None:
        assert _coerce_int("5000000.5") is None

    def test_coerce_int_str_negative_rejected(self) -> None:
        assert _coerce_int("-100") is None

    def test_coerce_int_other_type_rejected(self) -> None:
        # tuple / list / dict all return None
        assert _coerce_int((1,)) is None
        assert _coerce_int([1]) is None
        assert _coerce_int({"a": 1}) is None

    # _japanese_numeric_forms branches
    def test_japanese_numeric_forms_zero(self) -> None:
        forms = _japanese_numeric_forms(0)
        assert forms == ["0"]

    def test_japanese_numeric_forms_negative_returns_bare(self) -> None:
        # Defensive: function returns [str(value)] for non-positive.
        forms = _japanese_numeric_forms(-5)
        assert forms == ["-5"]

    def test_japanese_numeric_forms_clean_oku(self) -> None:
        forms = _japanese_numeric_forms(200_000_000)
        # Both 億円 and 億 variants must appear.
        assert "2億円" in forms
        assert "2億" in forms

    def test_japanese_numeric_forms_dedup_preserves_order(self) -> None:
        # 5_000_000 yields multiple representations; check no dup.
        forms = _japanese_numeric_forms(5_000_000)
        assert len(forms) == len(set(forms))
        # And the comma-form appears before the bare integer form.
        idx_comma = forms.index("5,000,000")
        idx_bare = forms.index("5000000")
        assert idx_comma < idx_bare


class TestCitationVerifierVerify:
    """Branch coverage for CitationVerifier.verify()."""

    def test_verify_rejects_non_dict_citation(self) -> None:
        verifier = CitationVerifier()
        result = verifier.verify("not a dict", "source body")  # type: ignore[arg-type]
        assert result["verification_status"] == "unknown"
        assert result["error"] == "citation_must_be_dict"

    def test_verify_empty_claim_returns_unknown(self) -> None:
        verifier = CitationVerifier()
        result = verifier.verify({}, "source body")
        assert result["verification_status"] == "unknown"
        assert result["error"] == "no_claim_to_verify"

    def test_verify_excerpt_whitespace_only_treated_as_empty(self) -> None:
        verifier = CitationVerifier()
        result = verifier.verify({"excerpt": "   "}, "source")
        assert result["verification_status"] == "unknown"
        assert result["error"] == "no_claim_to_verify"

    def test_verify_excerpt_match_returns_verified(self) -> None:
        verifier = CitationVerifier()
        result = verifier.verify(
            {"excerpt": "補助上限額は1,000万円"},
            "<html><body>補助上限額は1,000万円までです。</body></html>",
        )
        assert result["verification_status"] == "verified"
        assert result["matched_form"] is not None

    def test_verify_excerpt_miss_returns_inferred_not_verified(self) -> None:
        # Even when field_value would match, excerpt miss downgrades to
        # ``inferred`` per §28.9 No-Go #1.
        verifier = CitationVerifier()
        result = verifier.verify(
            {"excerpt": "存在しない文字列", "field_value": 5_000_000},
            "本文には500万円と書かれている",
        )
        assert result["verification_status"] == "inferred"
        assert result["matched_form"] is None

    def test_verify_numeric_only_match_japanese_form(self) -> None:
        verifier = CitationVerifier()
        result = verifier.verify(
            {"field_value": 5_000_000},
            "本補助金の上限額は500万円です。",
        )
        assert result["verification_status"] == "verified"
        assert result["matched_form"] is not None

    def test_verify_numeric_only_no_match_returns_unknown(self) -> None:
        verifier = CitationVerifier()
        result = verifier.verify(
            {"field_value": 5_000_000},
            "全く別の本文です。",
        )
        assert result["verification_status"] == "unknown"
        assert result["error"] is None

    def test_verify_matched_form_capped_at_max_excerpt_len(self) -> None:
        long_excerpt = "あ" * (MAX_EXCERPT_LEN + 50)
        body = "前置き" + long_excerpt + "後置き"
        verifier = CitationVerifier()
        result = verifier.verify({"excerpt": long_excerpt}, body)
        assert result["verification_status"] == "verified"
        assert result["matched_form"] is not None
        assert len(result["matched_form"]) == MAX_EXCERPT_LEN

    def test_verify_idempotent_same_inputs(self) -> None:
        verifier = CitationVerifier()
        body = "本文中に500万円が含まれます"
        r1 = verifier.verify({"field_value": 5_000_000}, body)
        r2 = verifier.verify({"field_value": 5_000_000}, body)
        assert r1 == r2
        assert r1["source_checksum"] == r2["source_checksum"]


class TestCitationVerifierFetch:
    """Cover fetch_source branches without real network."""

    def test_fetch_source_rejects_non_str_url(self) -> None:
        verifier = CitationVerifier()
        assert verifier.fetch_source(123) is None  # type: ignore[arg-type]

    def test_fetch_source_rejects_empty_url(self) -> None:
        verifier = CitationVerifier()
        assert verifier.fetch_source("") is None

    def test_fetch_source_rejects_non_http_scheme(self) -> None:
        verifier = CitationVerifier()
        assert verifier.fetch_source("file:///etc/passwd") is None
        assert verifier.fetch_source("ftp://example.com/x") is None

    def test_fetch_source_cache_hit_returns_cached(self) -> None:
        verifier = CitationVerifier()
        url = "https://example.com/cached"
        # Pre-populate cache manually so we don't need a real fetch.
        import time

        verifier._cache[url] = ("CACHED BODY", time.time() + 1000)
        out = verifier.fetch_source(url)
        assert out == "CACHED BODY"

    def test_fetch_source_stale_cache_evicted(self) -> None:
        verifier = CitationVerifier()
        url = "https://example.com/stale"
        import time

        # Already expired
        verifier._cache[url] = ("OLD BODY", time.time() - 10)

        # Patch urlopen to fail; we just want to verify the stale entry
        # is dropped, then the fetch attempt fails and returns None.
        with patch(
            "jpintel_mcp.services.citation_verifier.urllib.request.urlopen",
            side_effect=OSError("net down"),
        ):
            out = verifier.fetch_source(url)
        assert out is None
        # Stale entry should have been popped before the failed fetch.
        assert url not in verifier._cache

    def test_fetch_source_4xx_returns_none(self) -> None:
        verifier = CitationVerifier()
        mock_resp = MagicMock()
        mock_resp.status = 404
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch(
            "jpintel_mcp.services.citation_verifier.urllib.request.urlopen",
            return_value=mock_resp,
        ):
            out = verifier.fetch_source("https://example.com/missing")
        assert out is None

    def test_fetch_source_5xx_returns_none(self) -> None:
        verifier = CitationVerifier()
        mock_resp = MagicMock()
        mock_resp.status = 503
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch(
            "jpintel_mcp.services.citation_verifier.urllib.request.urlopen",
            return_value=mock_resp,
        ):
            out = verifier.fetch_source("https://example.com/down")
        assert out is None

    def test_fetch_source_network_exception_returns_none(self) -> None:
        verifier = CitationVerifier()
        with patch(
            "jpintel_mcp.services.citation_verifier.urllib.request.urlopen",
            side_effect=TimeoutError("timeout"),
        ):
            out = verifier.fetch_source("https://example.com/slow")
        assert out is None

    def test_fetch_source_success_caches(self) -> None:
        verifier = CitationVerifier()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read = MagicMock(return_value=b"<p>body</p>")
        mock_headers = MagicMock()
        mock_headers.get_content_charset = MagicMock(return_value="utf-8")
        mock_resp.headers = mock_headers
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch(
            "jpintel_mcp.services.citation_verifier.urllib.request.urlopen",
            return_value=mock_resp,
        ):
            out = verifier.fetch_source("https://example.com/ok")
        assert out == "<p>body</p>"
        # Cache populated
        assert "https://example.com/ok" in verifier._cache

    def test_fetch_source_charset_lookup_error_falls_back_to_utf8(self) -> None:
        verifier = CitationVerifier()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read = MagicMock(return_value="本文".encode())
        mock_headers = MagicMock()
        # Return an invalid charset name to trigger LookupError on .decode().
        mock_headers.get_content_charset = MagicMock(return_value="not-a-real-charset")
        mock_resp.headers = mock_headers
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch(
            "jpintel_mcp.services.citation_verifier.urllib.request.urlopen",
            return_value=mock_resp,
        ):
            out = verifier.fetch_source("https://example.com/bad-charset")
        # Falls back to utf-8 decoding with replacement; content survives.
        assert out is not None
        assert "本文" in out

    def test_clear_cache_drops_everything(self) -> None:
        verifier = CitationVerifier()
        import time

        verifier._cache["https://example.com/a"] = ("X", time.time() + 100)
        verifier._cache["https://example.com/b"] = ("Y", time.time() + 100)
        verifier.clear_cache()
        assert verifier._cache == {}


# ---------------------------------------------------------------------------
# known_gaps — pure dict transform
# ---------------------------------------------------------------------------


class TestKnownGapsBranches:
    """Targeted branches missing from existing test_known_gaps.py."""

    def test_non_dict_packet_returns_empty(self) -> None:
        assert detect_gaps([]) == []  # type: ignore[arg-type]
        assert detect_gaps("not a packet") == []  # type: ignore[arg-type]
        assert detect_gaps(None) == []  # type: ignore[arg-type]

    def test_missing_records_treated_as_empty(self) -> None:
        # records key missing
        assert detect_gaps({}) == []
        # records not a list
        assert detect_gaps({"records": "oops"}) == []

    def test_non_dict_record_skipped(self) -> None:
        packet = {"records": [None, "string", 42, {"entity_id": "e1"}]}
        out = detect_gaps(packet)
        # source_url_quality fires on the one real dict (no source_url).
        kinds = {g["kind"] for g in out}
        assert "source_url_quality" in kinds

    def test_lookup_not_dict_skipped(self) -> None:
        # When lookup is present but not a dict, no lookup_* gap fires.
        packet = {
            "records": [
                {
                    "entity_id": "e1",
                    "lookup": "oops",
                    "source_url": "https://example.com",
                }
            ]
        }
        out = detect_gaps(packet)
        kinds = {g["kind"] for g in out}
        assert "lookup_status_unknown" not in kinds
        assert "not_found_in_local_mirror" not in kinds

    def test_lookup_status_not_found_emits_not_found_in_local_mirror(self) -> None:
        packet = {
            "records": [
                {
                    "entity_id": "e1",
                    "lookup": {"status": "not_found_in_local_mirror"},
                    "source_url": "https://example.com",
                }
            ]
        }
        out = detect_gaps(packet)
        kinds = {g["kind"] for g in out}
        assert "not_found_in_local_mirror" in kinds

    def test_houjin_bangou_verifying_record_does_not_flag(self) -> None:
        # invoice_registrant carries the bangou and IS a verifier; no flag.
        packet = {
            "records": [
                {
                    "entity_id": "e1",
                    "houjin_bangou": "1234567890123",
                    "record_kind": "invoice_registrant",
                    "source_url": "https://example.com",
                }
            ]
        }
        out = detect_gaps(packet)
        kinds = {g["kind"] for g in out}
        assert "houjin_bangou_unverified" not in kinds

    def test_source_url_http_not_https_flagged(self) -> None:
        packet = {
            "records": [
                {
                    "entity_id": "e1",
                    "source_url": "http://example.com/insecure",
                }
            ]
        }
        out = detect_gaps(packet)
        kinds = {g["kind"] for g in out}
        assert "source_url_quality" in kinds

    def test_source_url_non_http_flagged(self) -> None:
        packet = {
            "records": [
                {
                    "entity_id": "e1",
                    "source_url": "see brochure",
                }
            ]
        }
        out = detect_gaps(packet)
        kinds = {g["kind"] for g in out}
        assert "source_url_quality" in kinds

    def test_stale_record_flagged(self) -> None:
        old_ts = (datetime.now(UTC) - timedelta(days=STALE_THRESHOLD_DAYS + 5)).isoformat()
        packet = {
            "records": [
                {
                    "entity_id": "e1",
                    "source_url": "https://example.com",
                    "last_verified": old_ts,
                }
            ]
        }
        out = detect_gaps(packet)
        kinds = {g["kind"] for g in out}
        assert "source_stale" in kinds

    def test_fresh_record_not_flagged(self) -> None:
        fresh_ts = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        packet = {
            "records": [
                {
                    "entity_id": "e1",
                    "source_url": "https://example.com",
                    "last_verified": fresh_ts,
                }
            ]
        }
        out = detect_gaps(packet)
        kinds = {g["kind"] for g in out}
        assert "source_stale" not in kinds

    def test_date_shorthand_iso_accepted(self) -> None:
        # YYYY-MM-DD form must still parse.
        old_date = (datetime.now(UTC) - timedelta(days=200)).date().isoformat()
        packet = {
            "records": [
                {
                    "entity_id": "e1",
                    "source_url": "https://example.com",
                    "last_verified": old_date,
                }
            ]
        }
        out = detect_gaps(packet)
        kinds = {g["kind"] for g in out}
        assert "source_stale" in kinds

    def test_unparseable_timestamp_does_not_flag(self) -> None:
        packet = {
            "records": [
                {
                    "entity_id": "e1",
                    "source_url": "https://example.com",
                    "last_verified": "garbage-string",
                }
            ]
        }
        out = detect_gaps(packet)
        kinds = {g["kind"] for g in out}
        # Missing timestamp doesn't flag — see docstring rule.
        assert "source_stale" not in kinds

    def test_iso_with_trailing_z_accepted(self) -> None:
        old_z = (datetime.now(UTC) - timedelta(days=200)).isoformat().replace("+00:00", "Z")
        packet = {
            "records": [
                {
                    "entity_id": "e1",
                    "source_url": "https://example.com",
                    "last_verified": old_z,
                }
            ]
        }
        out = detect_gaps(packet)
        assert "source_stale" in {g["kind"] for g in out}

    def test_datetime_object_accepted(self) -> None:
        old_dt = datetime.now(UTC) - timedelta(days=200)
        packet = {
            "records": [
                {
                    "entity_id": "e1",
                    "source_url": "https://example.com",
                    "last_verified": old_dt,
                }
            ]
        }
        out = detect_gaps(packet)
        assert "source_stale" in {g["kind"] for g in out}

    def test_naive_datetime_object_treated_as_utc(self) -> None:
        # No tzinfo -> _parse_iso assigns UTC.
        old_dt = (datetime.now(UTC) - timedelta(days=200)).replace(tzinfo=None)
        packet = {
            "records": [
                {
                    "entity_id": "e1",
                    "source_url": "https://example.com",
                    "last_verified": old_dt,
                }
            ]
        }
        out = detect_gaps(packet)
        assert "source_stale" in {g["kind"] for g in out}

    def test_low_confidence_at_record_level(self) -> None:
        packet = {
            "records": [
                {
                    "entity_id": "e1",
                    "source_url": "https://example.com",
                    "confidence": 0.2,
                }
            ]
        }
        out = detect_gaps(packet)
        assert "low_confidence" in {g["kind"] for g in out}

    def test_low_confidence_at_fact_level(self) -> None:
        packet = {
            "records": [
                {
                    "entity_id": "e1",
                    "source_url": "https://example.com",
                    "facts": [{"name": "x", "confidence": 0.1}],
                }
            ]
        }
        out = detect_gaps(packet)
        assert "low_confidence" in {g["kind"] for g in out}

    def test_high_confidence_not_flagged(self) -> None:
        packet = {
            "records": [
                {
                    "entity_id": "e1",
                    "source_url": "https://example.com",
                    "confidence": 0.95,
                    "facts": [{"name": "x", "confidence": 0.9}],
                }
            ]
        }
        out = detect_gaps(packet)
        assert "low_confidence" not in {g["kind"] for g in out}

    def test_bool_confidence_rejected_as_signal(self) -> None:
        # bool is int subclass; _coerce_float rejects bool explicitly.
        packet = {
            "records": [
                {
                    "entity_id": "e1",
                    "source_url": "https://example.com",
                    "confidence": True,
                }
            ]
        }
        out = detect_gaps(packet)
        assert "low_confidence" not in {g["kind"] for g in out}

    def test_non_dict_fact_skipped(self) -> None:
        packet = {
            "records": [
                {
                    "entity_id": "e1",
                    "source_url": "https://example.com",
                    "facts": ["not a dict", None, {"confidence": 0.1}],
                }
            ]
        }
        out = detect_gaps(packet)
        assert "low_confidence" in {g["kind"] for g in out}

    def test_string_confidence_unparseable_rejected(self) -> None:
        packet = {
            "records": [
                {
                    "entity_id": "e1",
                    "source_url": "https://example.com",
                    "confidence": "low",  # cannot float()
                }
            ]
        }
        out = detect_gaps(packet)
        assert "low_confidence" not in {g["kind"] for g in out}

    def test_entity_id_dedup(self) -> None:
        # Two records carrying same entity_id and same gap should dedupe.
        packet = {
            "records": [
                {"entity_id": "e1", "source_url": ""},
                {"entity_id": "e1", "source_url": None},
            ]
        }
        out = detect_gaps(packet)
        # Only one source_url_quality entry, with affected_records=["e1"].
        gap = next(g for g in out if g["kind"] == "source_url_quality")
        assert gap["affected_records"] == ["e1"]

    def test_constants_exposed(self) -> None:
        assert STALE_THRESHOLD_DAYS == 90
        assert LOW_CONFIDENCE_THRESHOLD == 0.5


# ---------------------------------------------------------------------------
# fact_conflicts — am_entity_facts conflict detection
# ---------------------------------------------------------------------------


def _fact_conflicts_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_entity_facts (
            id INTEGER PRIMARY KEY,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            field_value_text TEXT,
            field_value_numeric REAL,
            field_value_json TEXT,
            source_id INTEGER,
            source_url TEXT
        );
        """
    )
    return conn


class TestFactConflictsBranches:
    def test_returns_none_when_table_missing(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        # No am_entity_facts table present.
        out = compute_entity_conflict_metadata(conn, "e1")
        assert out is None

    def test_returns_none_when_entity_has_no_facts(self) -> None:
        conn = _fact_conflicts_db()
        out = compute_entity_conflict_metadata(conn, "no-such-entity")
        assert out is None

    def test_returns_none_when_all_values_null(self) -> None:
        conn = _fact_conflicts_db()
        # field_value_text/numeric/json all NULL → _normalized_fact_value None.
        conn.execute(
            "INSERT INTO am_entity_facts(id, entity_id, field_name, field_value_text,"
            " field_value_numeric, field_value_json, source_id, source_url)"
            " VALUES (1, 'e1', 'pname', NULL, NULL, NULL, NULL, NULL)"
        )
        out = compute_entity_conflict_metadata(conn, "e1")
        assert out is None

    def test_returns_none_when_table_lacks_required_columns(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        # Table exists but is missing field_name → required columns absent.
        conn.execute("CREATE TABLE am_entity_facts (id INTEGER PRIMARY KEY, entity_id TEXT)")
        out = compute_entity_conflict_metadata(conn, "e1")
        assert out is None

    def test_invalid_numeric_falls_through_to_text(self) -> None:
        # A non-coercible numeric in a real-world DB normally cannot happen,
        # but _canonical_number returns None on InvalidOperation. We can
        # exercise the legacy-value path via the legacy 'value' column.
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE am_entity_facts (
                id INTEGER PRIMARY KEY,
                entity_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                field_value_text TEXT,
                field_value_numeric REAL,
                field_value_json TEXT,
                value TEXT,
                source_id INTEGER,
                source_url TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO am_entity_facts(id, entity_id, field_name, value) "
            "VALUES (1, 'e1', 'pname', 'legacy text')"
        )
        out = compute_entity_conflict_metadata(conn, "e1")
        assert out is not None
        names = {f["field_name"] for f in out["fields"]}
        assert "pname" in names

    def test_json_invalid_falls_back_to_text_key(self) -> None:
        conn = _fact_conflicts_db()
        conn.execute(
            "INSERT INTO am_entity_facts(id, entity_id, field_name, field_value_json,"
            " source_id) VALUES (1, 'e1', 'meta', '{not valid json', 1)"
        )
        out = compute_entity_conflict_metadata(conn, "e1")
        assert out is not None
        meta = next(f for f in out["fields"] if f["field_name"] == "meta")
        # Single value (json_text: prefix) -> consistent
        assert meta["status"] == "consistent"

    def test_singleton_field_with_two_values_is_conflict(self) -> None:
        conn = _fact_conflicts_db()
        conn.executemany(
            "INSERT INTO am_entity_facts(id, entity_id, field_name, field_value_text,"
            " source_id) VALUES (?, ?, ?, ?, ?)",
            [
                (1, "e1", "primary_name", "Alpha", 1),
                (2, "e1", "primary_name", "Beta", 2),
            ],
        )
        out = compute_entity_conflict_metadata(conn, "e1")
        assert out is not None
        f = next(x for x in out["fields"] if x["field_name"] == "primary_name")
        assert f["status"] == "conflict"
        assert out["summary"]["has_conflicts"] is True

    def test_non_singleton_field_multiple_values_status(self) -> None:
        conn = _fact_conflicts_db()
        # 'industry_jsic' is NOT in DEFAULT_SINGLETON_FIELD_ALLOWLIST.
        conn.executemany(
            "INSERT INTO am_entity_facts(id, entity_id, field_name, field_value_text,"
            " source_id) VALUES (?, ?, ?, ?, ?)",
            [
                (1, "e1", "industry_jsic", "A", 1),
                (2, "e1", "industry_jsic", "B", 2),
            ],
        )
        out = compute_entity_conflict_metadata(conn, "e1")
        assert out is not None
        f = next(x for x in out["fields"] if x["field_name"] == "industry_jsic")
        assert f["status"] == "multiple_values"
        assert out["summary"]["has_conflicts"] is False
        assert out["summary"]["multiple_values_count"] >= 1

    def test_custom_singleton_set_overrides_default(self) -> None:
        conn = _fact_conflicts_db()
        conn.executemany(
            "INSERT INTO am_entity_facts(id, entity_id, field_name, field_value_text,"
            " source_id) VALUES (?, ?, ?, ?, ?)",
            [
                (1, "e1", "custom_x", "v1", 1),
                (2, "e1", "custom_x", "v2", 2),
            ],
        )
        out = compute_entity_conflict_metadata(conn, "e1", singleton_fields={"custom_x"})
        assert out is not None
        f = next(x for x in out["fields"] if x["field_name"] == "custom_x")
        assert f["status"] == "conflict"

    def test_source_id_overrides_source_url_in_dedup(self) -> None:
        conn = _fact_conflicts_db()
        conn.executemany(
            "INSERT INTO am_entity_facts(id, entity_id, field_name, field_value_text,"
            " source_id, source_url) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (1, "e1", "primary_name", "Alpha", 1, "https://x.example/a"),
                (2, "e1", "primary_name", "Alpha", 1, "https://x.example/a"),
            ],
        )
        out = compute_entity_conflict_metadata(conn, "e1")
        assert out is not None
        f = next(x for x in out["fields"] if x["field_name"] == "primary_name")
        # Same value + same source_id collapses to 1 source.
        v = f["values"][0]
        assert v["source_count"] == 1

    def test_source_url_normalization_trailing_slash(self) -> None:
        conn = _fact_conflicts_db()
        conn.executemany(
            "INSERT INTO am_entity_facts(id, entity_id, field_name, field_value_text,"
            " source_id, source_url) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (1, "e1", "primary_name", "Alpha", None, "https://x.example/path/"),
                (2, "e1", "primary_name", "Alpha", None, "https://x.example/path"),
            ],
        )
        out = compute_entity_conflict_metadata(conn, "e1")
        assert out is not None
        v = out["fields"][0]["values"][0]
        # Both URLs normalize to the same form -> single source.
        assert v["source_count"] == 1

    def test_zero_numeric_canonicalized(self) -> None:
        conn = _fact_conflicts_db()
        conn.execute(
            "INSERT INTO am_entity_facts(id, entity_id, field_name, field_value_numeric,"
            " source_id) VALUES (1, 'e1', 'amount_min_yen', 0.0, 1)"
        )
        out = compute_entity_conflict_metadata(conn, "e1")
        assert out is not None
        f = out["fields"][0]
        assert f["values"][0]["display_value"] == 0

    def test_singleton_allowlist_constant(self) -> None:
        # Sanity check that the allowlist module-level constant is non-empty.
        assert len(DEFAULT_SINGLETON_FIELD_ALLOWLIST) > 5


# ---------------------------------------------------------------------------
# token_compression — minor branch fillers (97% already)
# ---------------------------------------------------------------------------


class TestTokenCompressionExtra:
    def test_estimate_packet_tokens_empty_packet(self) -> None:
        estimator = TokenCompressionEstimator()
        # Even an empty dict serializes to "{}" -> 2 chars -> ~0 tokens (rounded).
        tokens = estimator.estimate_packet_tokens({})
        assert tokens >= 0

    def test_estimate_from_text_empty_returns_zero(self) -> None:
        estimator = TokenCompressionEstimator()
        assert estimator._estimate_from_text("") == 0

    def test_estimate_source_tokens_unknown_basis_returns_none(self) -> None:
        estimator = TokenCompressionEstimator()
        # No text, no pdf_pages, basis="unknown" -> None
        assert estimator.estimate_source_tokens("https://example.com/") is None

    def test_estimate_source_tokens_pdf_pages_negative_returns_none(self) -> None:
        estimator = TokenCompressionEstimator()
        # pdf_pages must be > 0; -1 returns None.
        out = estimator.estimate_source_tokens("https://x", source_basis="pdf_pages", pdf_pages=-1)
        assert out is None

    def test_estimate_source_tokens_token_count_zero_returns_none(self) -> None:
        estimator = TokenCompressionEstimator()
        out = estimator.estimate_source_tokens(
            "https://x", source_basis="token_count", source_token_count=0
        )
        # 0 means "we measured it, source is empty" -> caller must still get
        # None per the > 0 guard, since the token_count path requires positive.
        assert out is None

    def test_estimate_source_tokens_token_count_negative_returns_none(self) -> None:
        estimator = TokenCompressionEstimator()
        out = estimator.estimate_source_tokens(
            "https://x", source_basis="token_count", source_token_count=-100
        )
        assert out is None

    def test_compute_savings_none_when_source_tokens_unknown(self) -> None:
        estimator = TokenCompressionEstimator()
        out = estimator.compute_savings(
            packet_tokens=100,
            source_tokens=None,
            jpcite_cost_jpy=3,
            input_price_jpy_per_1m=300.0,
        )
        assert out is None

    def test_compute_savings_none_when_price_nonpositive(self) -> None:
        estimator = TokenCompressionEstimator()
        out = estimator.compute_savings(
            packet_tokens=100,
            source_tokens=10_000,
            jpcite_cost_jpy=3,
            input_price_jpy_per_1m=0.0,
        )
        assert out is None
        out2 = estimator.compute_savings(
            packet_tokens=100,
            source_tokens=10_000,
            jpcite_cost_jpy=3,
            input_price_jpy_per_1m=-1.0,
        )
        assert out2 is None

    def test_compute_savings_full_block(self) -> None:
        estimator = TokenCompressionEstimator()
        out = estimator.compute_savings(
            packet_tokens=100,
            source_tokens=10_000,
            jpcite_cost_jpy=3,
            input_price_jpy_per_1m=300.0,
        )
        assert out is not None
        assert out["currency"] == "JPY"
        assert out["jpcite_billable_units"] == 1
        assert out["provider_billing_not_guaranteed"] is True
        assert "break_even_avoided_tokens" in out
        assert "break_even_source_tokens_estimate" in out

    def test_compose_minimum_inputs(self) -> None:
        estimator = TokenCompressionEstimator()
        block = estimator.compose({"foo": "bar"})
        # No source -> source_tokens None, compression_ratio None.
        assert block["source_tokens_estimate"] is None
        assert block["compression_ratio"] is None
        assert block["provider_billing_not_guaranteed"] is True
        assert block["estimate_method"] == ESTIMATE_METHOD
        assert block["estimate_disclaimer"] == ESTIMATE_DISCLAIMER

    def test_compose_with_source_text(self) -> None:
        estimator = TokenCompressionEstimator()
        block = estimator.compose(
            {"foo": "bar"},
            source_url="https://example.com/",
            source_text="本文" * 100,
            source_basis="html_chars",
        )
        assert block["source_tokens_estimate"] is not None
        assert block["compression_ratio"] is not None
        assert "cost_savings_estimate" not in block  # price not supplied

    def test_compose_with_pdf_pages_basis(self) -> None:
        estimator = TokenCompressionEstimator()
        block = estimator.compose(
            {"foo": "bar"},
            source_basis="pdf_pages",
            pdf_pages=10,
            input_price_jpy_per_1m=300.0,
        )
        assert block["source_pdf_pages"] == 10
        assert block["source_tokens_estimate"] is not None
        assert "cost_savings_estimate" in block

    def test_compose_with_token_count_basis(self) -> None:
        estimator = TokenCompressionEstimator()
        block = estimator.compose(
            {"foo": "bar"},
            source_basis="token_count",
            source_token_count=50_000,
        )
        assert block["source_token_count"] == 50_000
        assert block["source_tokens_estimate"] == 50_000


# ---------------------------------------------------------------------------
# funding_stack_checker — coverage fillers (already 92%)
# ---------------------------------------------------------------------------


def _build_minimal_jpintel(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE exclusion_rules (
            rule_id              TEXT PRIMARY KEY,
            kind                 TEXT NOT NULL,
            severity             TEXT,
            program_a            TEXT,
            program_b            TEXT,
            program_b_group_json TEXT,
            description          TEXT,
            source_notes         TEXT,
            source_urls_json     TEXT,
            extra_json           TEXT,
            source_excerpt       TEXT,
            condition            TEXT,
            program_a_uid        TEXT,
            program_b_uid        TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def _build_minimal_autonomath(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE am_compat_matrix (
            program_a_id    TEXT,
            program_b_id    TEXT,
            compat_status   TEXT,
            conditions_text TEXT,
            rationale_short TEXT,
            source_url      TEXT,
            confidence      REAL,
            inferred_only   INTEGER
        );
        """
    )
    conn.commit()
    conn.close()


class TestFundingStackCheckerFillers:
    def test_init_raises_on_missing_jpintel(self, tmp_path) -> None:
        from jpintel_mcp.services.funding_stack_checker import FundingStackChecker

        am = tmp_path / "am.db"
        _build_minimal_autonomath(str(am))
        # jpintel missing entirely.
        with pytest.raises(FileNotFoundError):
            FundingStackChecker(tmp_path / "nope.db", am)

    def test_init_raises_on_missing_autonomath(self, tmp_path) -> None:
        from jpintel_mcp.services.funding_stack_checker import FundingStackChecker

        jp = tmp_path / "jp.db"
        _build_minimal_jpintel(str(jp))
        with pytest.raises(FileNotFoundError):
            FundingStackChecker(jp, tmp_path / "nope.db")

    def test_load_compat_matrix_skips_empty_program_ids(self, tmp_path) -> None:
        from jpintel_mcp.services.funding_stack_checker import FundingStackChecker

        jp = tmp_path / "jp.db"
        am = tmp_path / "am.db"
        _build_minimal_jpintel(str(jp))
        _build_minimal_autonomath(str(am))

        conn = sqlite3.connect(str(am))
        conn.executemany(
            "INSERT INTO am_compat_matrix VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                # Both program IDs empty → must skip.
                ("", "", "compatible", None, None, None, 1.0, 0),
                # One empty → must skip.
                ("a", "", "compatible", None, None, None, 1.0, 0),
                # Valid pair.
                ("a", "b", "compatible", None, None, "https://x", 1.0, 0),
            ],
        )
        conn.commit()
        conn.close()

        checker = FundingStackChecker(jp, am)
        assert len(checker._compat_index) == 1

    def test_load_compat_authoritative_wins_over_heuristic(self, tmp_path) -> None:
        from jpintel_mcp.services.funding_stack_checker import FundingStackChecker

        jp = tmp_path / "jp.db"
        am = tmp_path / "am.db"
        _build_minimal_jpintel(str(jp))
        _build_minimal_autonomath(str(am))

        conn = sqlite3.connect(str(am))
        # Authoritative row first (inferred_only=0); then heuristic row should
        # be ignored on the same unordered pair.
        conn.executemany(
            "INSERT INTO am_compat_matrix VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("a", "b", "compatible", None, None, "https://x", 1.0, 0),
                ("b", "a", "incompatible", None, None, None, 0.8, 1),
            ],
        )
        conn.commit()
        conn.close()

        checker = FundingStackChecker(jp, am)
        # Authoritative entry preserved.
        keys = list(checker._compat_index.keys())
        assert len(keys) == 1
        row = checker._compat_index[keys[0]]
        assert row["inferred_only"] == 0
        assert row["compat_status"] == "compatible"

    def test_pair_key_is_order_independent(self, tmp_path) -> None:
        from jpintel_mcp.services.funding_stack_checker import FundingStackChecker

        jp = tmp_path / "jp.db"
        am = tmp_path / "am.db"
        _build_minimal_jpintel(str(jp))
        _build_minimal_autonomath(str(am))
        checker = FundingStackChecker(jp, am)
        # Method exists at class scope; both orderings produce the same key.
        k1 = checker._pair_key("alpha", "beta")
        k2 = checker._pair_key("beta", "alpha")
        assert k1 == k2

    def test_check_pair_self_pair_returns_incompatible(self, tmp_path) -> None:
        from jpintel_mcp.services.funding_stack_checker import FundingStackChecker

        jp = tmp_path / "jp.db"
        am = tmp_path / "am.db"
        _build_minimal_jpintel(str(jp))
        _build_minimal_autonomath(str(am))
        checker = FundingStackChecker(jp, am)
        out = checker.check_pair("p1", "p1")
        # Self-pair short-circuits to incompatible (cannot stack same program
        # with itself) — see funding_stack_checker.py:736.
        assert out.verdict == "incompatible"
        assert out.hard_blocker is True

    def test_check_stack_single_program_no_pairs(self, tmp_path) -> None:
        from jpintel_mcp.services.funding_stack_checker import FundingStackChecker

        jp = tmp_path / "jp.db"
        am = tmp_path / "am.db"
        _build_minimal_jpintel(str(jp))
        _build_minimal_autonomath(str(am))
        checker = FundingStackChecker(jp, am)
        # Single program -> no pairs to evaluate. Aggregate "unknown" is the
        # honest reading when there's nothing to compute against.
        out = checker.check_stack(["only-one"])
        assert out.pairs == []
        assert out.all_pairs_status in {"compatible", "unknown"}

    def test_check_stack_empty_program_list_returns_compat(self, tmp_path) -> None:
        from jpintel_mcp.services.funding_stack_checker import FundingStackChecker

        jp = tmp_path / "jp.db"
        am = tmp_path / "am.db"
        _build_minimal_jpintel(str(jp))
        _build_minimal_autonomath(str(am))
        checker = FundingStackChecker(jp, am)
        out = checker.check_stack([])
        assert out.pairs == []
        assert out.program_ids == []
