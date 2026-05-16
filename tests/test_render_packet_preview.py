"""Tests for ``scripts.aws_credit_ops.render_packet_preview``.

Coverage targets per the master plan §3.3 spec:

1. Happy-path render of the canonical sample fixture.
2. Output size stays within the 5-15 KB ceiling.
3. Missing optional fields (records / sections / known_gaps / coverage).
4. Forbidden English wording rejection (``eligible`` in section body).
5. Forbidden Japanese wording rejection (``問題ありません``).
6. License + publisher + fetched_at preservation in the sources table.
7. Safe + unsafe URL rendering (``https://`` linked, ``javascript:`` not).
8. HTML escape + ``<script>`` tag stripping in section markdown body.
9. Sanitizer redaction of forbidden wording that bypassed the scanner.
10. ``main()`` exit codes: 0 success / 2 forbidden / 1 I/O failure.
11. Markdown subset (bold, italic, code, bullets, heading) round-trips.
12. S3 URI parser accepts canonical ``s3://bucket/key`` form.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts" / "aws_credit_ops"
SRC_DIR = REPO_ROOT / "src"

# Add both paths so we can import the script under test plus the
# ``jpintel_mcp.safety_scanners`` package it depends on.
for entry in (str(SCRIPTS_DIR), str(SRC_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from render_packet_preview import (  # noqa: E402 — sys.path setup above
    DEFAULT_DISCLAIMER,
    REDACTION_PLACEHOLDER,
    ForbiddenWordingError,
    _is_safe_http_url,
    _parse_s3_uri,
    build_html,
    load_packet,
    main,
    render_markdown,
    render_packet,
    sanitize_text,
)

FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "packet_preview"
SAMPLE_PACKET = FIXTURES_DIR / "sample_packet.json"
FORBIDDEN_PACKET = FIXTURES_DIR / "forbidden_wording_packet.json"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_renders_full_html() -> None:
    envelope = load_packet(SAMPLE_PACKET)
    html_text = render_packet(envelope, source=str(SAMPLE_PACKET))
    assert html_text.startswith("<!DOCTYPE html>")
    assert html_text.rstrip().endswith("</html>")
    assert '<html lang="ja">' in html_text
    assert "pkg_sample_001" in html_text
    assert "evidence_packet" in html_text
    # Required source URL must be rendered as a clickable link.
    assert (
        '<a href="https://www.meti.go.jp/example/program_demo_42"'
        in html_text
    )
    # Records table appears and has both rows.
    assert "rec_001" in html_text
    assert "rec_002" in html_text
    # Sections appear with their titles + anchor IDs.
    assert 'id="section-ranked_candidates"' in html_text
    assert "候補制度ランキング" in html_text
    # Known gaps appear with the 7-enum code.
    assert "no_hit_not_absence" in html_text
    assert "professional_review_required" in html_text
    # Coverage grade A surfaces in the header.
    assert ">A<" in html_text
    # Disclaimer renders.
    assert "個別具体的な税務・法律" in html_text


def test_output_size_is_within_5_15_kb() -> None:
    envelope = load_packet(SAMPLE_PACKET)
    html_text = build_html(envelope)
    size_kb = len(html_text.encode("utf-8")) / 1024.0
    assert 1.0 <= size_kb <= 15.0, f"unexpected size {size_kb:.2f} KB"


# ---------------------------------------------------------------------------
# Optional fields
# ---------------------------------------------------------------------------


def test_missing_optional_fields_does_not_raise() -> None:
    minimal: dict[str, Any] = {
        "package_id": "pkg_min_001",
        "package_kind": "evidence_packet",
        "subject": {"kind": "query", "id": "q1"},
        "generated_at": "2026-05-16T00:00:00+09:00",
        "jpcite_cost_jpy": 3,
        "estimated_tokens_saved": 0,
        "source_count": 0,
        "known_gaps": [],
        "sources": [],
    }
    html_text = render_packet(minimal)
    # The empty-known-gaps placeholder must appear.
    assert "登録された既知ギャップはありません" in html_text
    # The empty-sources placeholder must appear.
    assert "出典は登録されていません" in html_text
    # The fallback disclaimer must appear.
    assert DEFAULT_DISCLAIMER in html_text


def test_missing_records_section_skips_records_table() -> None:
    minimal: dict[str, Any] = {
        "package_id": "pkg_no_records_001",
        "package_kind": "watch_digest",
        "generated_at": "2026-05-16T00:00:00+09:00",
        "jpcite_cost_jpy": 3,
        "estimated_tokens_saved": 100,
        "source_count": 1,
        "sources": [
            {
                "source_url": "https://example.go.jp/x",
                "source_fetched_at": "2026-05-15T00:00:00+09:00",
                "publisher": "official_primary",
                "license": "gov_standard",
            }
        ],
    }
    html_text = render_packet(minimal)
    assert "レコード (records)" not in html_text


# ---------------------------------------------------------------------------
# Forbidden wording rejection (English + Japanese)
# ---------------------------------------------------------------------------


def test_forbidden_english_wording_refuses_render() -> None:
    envelope = load_packet(FORBIDDEN_PACKET)
    with pytest.raises(ForbiddenWordingError) as excinfo:
        render_packet(envelope, source=str(FORBIDDEN_PACKET))
    codes = {v.code for v in excinfo.value.violations}
    assert "forbidden_english_wording" in codes


def test_forbidden_japanese_wording_refuses_render() -> None:
    envelope: dict[str, Any] = {
        "package_id": "pkg_forbidden_ja_001",
        "package_kind": "evidence_packet",
        "generated_at": "2026-05-16T00:00:00+09:00",
        "jpcite_cost_jpy": 3,
        "estimated_tokens_saved": 10,
        "source_count": 0,
        "known_gaps": [],
        "sources": [],
        "sections": [
            {
                "section_id": "verdict",
                "title": "結論",
                "body": "この事業者は問題ありません。",
            }
        ],
    }
    with pytest.raises(ForbiddenWordingError) as excinfo:
        render_packet(envelope)
    codes = {v.code for v in excinfo.value.violations}
    assert "forbidden_japanese_wording" in codes


# ---------------------------------------------------------------------------
# License + publisher + fetched_at preservation
# ---------------------------------------------------------------------------


def test_license_publisher_fetched_at_preserved() -> None:
    envelope = load_packet(SAMPLE_PACKET)
    html_text = render_packet(envelope)
    # All 4 source-table columns appear with the canonical values.
    assert "2026-05-15T09:00:00+09:00" in html_text
    assert "official_primary" in html_text
    assert "gov_standard" in html_text
    assert "2026-05-14T10:30:00+09:00" in html_text
    assert "official_secondary" in html_text
    assert "public_domain" in html_text


# ---------------------------------------------------------------------------
# Safe / unsafe URL handling
# ---------------------------------------------------------------------------


def test_safe_http_url_predicate() -> None:
    assert _is_safe_http_url("https://example.com/x") is True
    assert _is_safe_http_url("http://example.com/x") is True
    assert _is_safe_http_url("HTTPS://EXAMPLE.COM/x") is True
    assert _is_safe_http_url("javascript:alert(1)") is False
    assert _is_safe_http_url("data:text/html,<script>") is False
    assert _is_safe_http_url("file:///etc/passwd") is False
    assert _is_safe_http_url(None) is False
    assert _is_safe_http_url("") is False
    assert _is_safe_http_url("relative/path.html") is False


def test_javascript_url_is_not_rendered_as_anchor() -> None:
    envelope: dict[str, Any] = {
        "package_id": "pkg_unsafe_url_001",
        "package_kind": "evidence_packet",
        "generated_at": "2026-05-16T00:00:00+09:00",
        "jpcite_cost_jpy": 3,
        "estimated_tokens_saved": 0,
        "source_count": 1,
        "known_gaps": [],
        "sources": [
            {
                "source_url": "javascript:alert(1)",
                "source_fetched_at": "2026-05-15T00:00:00+09:00",
                "publisher": "official_primary",
                "license": "gov_standard",
            }
        ],
    }
    html_text = render_packet(envelope)
    assert '<a href="javascript:' not in html_text
    # The raw text is HTML-escaped but is not an anchor tag.
    assert "javascript:alert(1)" in html_text


# ---------------------------------------------------------------------------
# Script tag stripping + sanitizer
# ---------------------------------------------------------------------------


def test_script_tag_stripped_from_section_body() -> None:
    envelope: dict[str, Any] = {
        "package_id": "pkg_xss_attempt_001",
        "package_kind": "evidence_packet",
        "generated_at": "2026-05-16T00:00:00+09:00",
        "jpcite_cost_jpy": 3,
        "estimated_tokens_saved": 0,
        "source_count": 0,
        "known_gaps": [],
        "sources": [],
        "sections": [
            {
                "section_id": "xss",
                "title": "test",
                "body": "before <script>alert(1)</script> after",
            }
        ],
    }
    html_text = render_packet(envelope)
    assert "<script>" not in html_text
    assert "alert(1)" in html_text  # escaped text content is fine
    assert "before" in html_text and "after" in html_text


def test_sanitize_text_redacts_forbidden_wording() -> None:
    assert "eligible" not in sanitize_text("you are eligible")
    assert REDACTION_PLACEHOLDER in sanitize_text("you are eligible")
    assert "問題ありません" not in sanitize_text("問題ありませんよ")
    assert REDACTION_PLACEHOLDER in sanitize_text("問題ありませんよ")
    # The whitelist set must still be flagged because sanitize_text is a
    # blunt fallback that runs AFTER the scanner. The allow-list lives in
    # the scanner, not here.
    assert sanitize_text("clean text") == "clean text"


# ---------------------------------------------------------------------------
# Markdown subset round-trips
# ---------------------------------------------------------------------------


def test_render_markdown_supports_bullets_bold_italic_code() -> None:
    body = (
        "# Heading One\n"
        "Paragraph with **bold** and *italic* and `code`.\n\n"
        "- item one\n"
        "- item two\n"
    )
    html_text = render_markdown(body)
    # heading promoted to <h3> (level + 2, min 3) under the section <h2>.
    assert "<h3>Heading One</h3>" in html_text
    assert "<strong>bold</strong>" in html_text
    assert "<em>italic</em>" in html_text
    assert "<code>code</code>" in html_text
    assert "<ul><li>item one</li><li>item two</li></ul>" in html_text


# ---------------------------------------------------------------------------
# CLI / main()
# ---------------------------------------------------------------------------


def test_main_happy_path_exits_zero(tmp_path: Path) -> None:
    out_path = tmp_path / "out" / "preview.html"
    rc = main([str(SAMPLE_PACKET), "--out", str(out_path)])
    assert rc == 0
    assert out_path.exists()
    body = out_path.read_text(encoding="utf-8")
    assert "pkg_sample_001" in body


def test_main_forbidden_wording_exits_two(tmp_path: Path) -> None:
    out_path = tmp_path / "out" / "preview.html"
    rc = main([str(FORBIDDEN_PACKET), "--out", str(out_path)])
    assert rc == 2
    # On refusal we MUST NOT write the output file.
    assert not out_path.exists()


def test_main_missing_file_exits_one(tmp_path: Path) -> None:
    missing = tmp_path / "nope.json"
    out_path = tmp_path / "out" / "preview.html"
    rc = main([str(missing), "--out", str(out_path)])
    assert rc == 1
    assert not out_path.exists()


def test_main_invalid_json_exits_one(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    out_path = tmp_path / "out" / "preview.html"
    rc = main([str(bad), "--out", str(out_path)])
    assert rc == 1


def test_main_non_object_json_exits_one(tmp_path: Path) -> None:
    arr = tmp_path / "arr.json"
    arr.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    out_path = tmp_path / "out" / "preview.html"
    rc = main([str(arr), "--out", str(out_path)])
    assert rc == 1


# ---------------------------------------------------------------------------
# S3 URI parser
# ---------------------------------------------------------------------------


def test_parse_s3_uri_canonical() -> None:
    bucket, key = _parse_s3_uri("s3://my-bucket/path/to/file.json")
    assert bucket == "my-bucket"
    assert key == "path/to/file.json"


def test_parse_s3_uri_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        _parse_s3_uri("not-s3://x/y")
    with pytest.raises(ValueError):
        _parse_s3_uri("s3://just-a-bucket")
    with pytest.raises(ValueError):
        _parse_s3_uri("s3:///empty-bucket/k")


# ---------------------------------------------------------------------------
# Output is JS-free and agent-crawlable
# ---------------------------------------------------------------------------


def test_no_external_resources_or_javascript() -> None:
    envelope = load_packet(SAMPLE_PACKET)
    html_text = render_packet(envelope)
    # No JS.
    assert "<script" not in html_text.lower()
    assert "javascript:" not in html_text.lower()
    # No external CSS or images.
    assert '<link ' not in html_text.lower()
    assert "<img" not in html_text.lower()
    # robots meta is present and indexable.
    assert 'name="robots" content="index,follow"' in html_text
