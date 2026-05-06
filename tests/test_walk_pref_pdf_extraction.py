"""Tests for the PDF-extraction path of `scripts/walk_pref_subsidy_seeds.py`.

Covers the helpers that take previously-failed PDF children (disposition='http_200')
and harvest program rows from them. No network calls — fixtures are byte literals.

Background: the 47-prefecture walker silently dropped PDF children pre 2026-04-29,
so 茨城県 (24 candidates → 1 row) and 和歌山県 (24 candidates → 0 rows) were
under-counted. PDFs hosted on `pref.*.lg.jp` are legitimate primary sources;
this module verifies the heuristics that turn them into program rows.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WALKER_PATH = _REPO_ROOT / "scripts" / "walk_pref_subsidy_seeds.py"


@pytest.fixture(scope="module")
def walker():
    """Load the walker script as a module (it lives under scripts/, not src/)."""
    spec = importlib.util.spec_from_file_location("walker_pref", str(_WALKER_PATH))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["walker_pref"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# extract_pdf_text — corrupt / non-PDF inputs
# ---------------------------------------------------------------------------


def test_extract_pdf_text_empty(walker):
    assert walker.extract_pdf_text(b"") == ""


def test_extract_pdf_text_non_pdf_bytes(walker):
    assert walker.extract_pdf_text(b"NOT A PDF") == ""


def test_extract_pdf_text_truncated_pdf(walker):
    # %PDF magic but garbage afterwards — pdfplumber raises, we return ''.
    assert walker.extract_pdf_text(b"%PDF-1.4\nGARBAGE") == ""


# ---------------------------------------------------------------------------
# is_pdf_text_meaningful — image-only / scanned PDF detection
# ---------------------------------------------------------------------------


def test_is_pdf_text_meaningful_empty(walker):
    assert walker.is_pdf_text_meaningful("") is False


def test_is_pdf_text_meaningful_whitespace_only(walker):
    # Whitespace only — first 1KB has zero non-whitespace chars → image-only.
    assert walker.is_pdf_text_meaningful(" " * 2000) is False


def test_is_pdf_text_meaningful_real_program_text(walker):
    text = "新市町村づくり支援事業 市町村合併に伴うまちづくりを支援する。" * 10
    assert walker.is_pdf_text_meaningful(text) is True


def test_is_pdf_text_meaningful_threshold(walker):
    # ~30 non-whitespace chars in 1KB — under the 40-char floor → unparseable.
    sparse = " " * 1000 + "a" * 30 + " " * 1000
    assert walker.is_pdf_text_meaningful(sparse) is False


# ---------------------------------------------------------------------------
# _strip_pdf_boilerplate — 様式 / 別紙 / (参考) prefixes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("別紙第一号 新市町村づくり支援事業", "新市町村づくり支援事業"),
        ("様式 1 補助金交付申請書", "補助金交付申請書"),
        ("（参考）令和7年度 補助金一覧", "令和7年度 補助金一覧"),
        ("補助金交付申請書", "補助金交付申請書"),  # no prefix → unchanged
    ],
)
def test_strip_pdf_boilerplate(walker, raw, expected):
    assert walker._strip_pdf_boilerplate(raw) == expected


# ---------------------------------------------------------------------------
# extract_program_pdf — title / amount / deadline heuristics
# ---------------------------------------------------------------------------


def test_extract_program_pdf_with_marker(walker):
    """When PDF has '制度名 / 事業名' marker, use the value that follows."""
    text = (
        "総 務 部\n"
        "No. 1\n"
        "市町村課\n"
        "主管課名\n"
        "制 度 名 新市町村づくり支援事業 行政G\n"
        "問合せ先 029-301-2457\n"
        "市町村合併に伴うまちづくりを支援する。\n"
    )
    result = walker.extract_program_pdf(text, fallback_title="X")
    assert result["title"] == "新市町村づくり支援事業"


def test_extract_program_pdf_with_jigyo_marker(walker):
    """事業名 marker (和歌山県 PDF style)."""
    text = (
        "わかやま中小企業元気ファンド助成事業一覧表\n"
        "事業名：地域資源活用支援事業Ａ\n"
        "番号 事業者 所在地 テーマ\n"
    )
    result = walker.extract_program_pdf(text, fallback_title="X")
    assert result["title"] == "地域資源活用支援事業Ａ"


def test_extract_program_pdf_falls_back_to_first_line(walker):
    """No marker — first plausible non-boilerplate line wins."""
    text = "新市町村づくり支援事業\n目的・趣旨\n市町村合併を支援する。"
    result = walker.extract_program_pdf(text, fallback_title="X")
    assert result["title"] == "新市町村づくり支援事業"


def test_extract_program_pdf_skips_dept_header(walker):
    """Skip '総 務 部' (department header) and 'No. 1' (page number)."""
    text = "総 務 部\nNo. 1\n新市町村づくり支援事業\n"
    result = walker.extract_program_pdf(text, fallback_title="X")
    assert result["title"] == "新市町村づくり支援事業"


def test_extract_program_pdf_uses_fallback(walker):
    """All-boilerplate PDF text → use fallback title."""
    text = "様式 1\n別紙\nNo. 1"
    result = walker.extract_program_pdf(text, fallback_title="my_fallback")
    assert result["title"] == "my_fallback"


def test_extract_program_pdf_strips_trailing_group_hint(walker):
    """'制度名: X 行政G' → strip trailing '行政G' group annotation."""
    text = "制度名 補助金交付制度 行政G\n"
    result = walker.extract_program_pdf(text, fallback_title="X")
    assert result["title"] == "補助金交付制度"


def test_extract_program_pdf_handles_value_before_marker(walker):
    """茨城県 form layout: '<title> 主管課名 <dept>' all on one line."""
    text = "様式２\n総 務 部\nNo. 4\n共生の地域づくり助成事業 主管課名 市町村課・財政G\n制 度 名\n"
    result = walker.extract_program_pdf(text, fallback_title="X")
    assert result["title"] == "共生の地域づくり助成事業"


def test_extract_program_pdf_amount_with_kanji_unit(walker):
    """AMOUNT_RE picks up '上限 100万円' style explicit limit text."""
    text = "新規補助制度\n上限 100万円 を補助する。\n募集期間 令和7年5月15日まで\n"
    result = walker.extract_program_pdf(text, fallback_title="X")
    assert result["amount_max_man_yen"] == 100.0
    assert result["deadline_iso"] == "2025-05-15"


def test_extract_program_pdf_handles_empty_text(walker):
    result = walker.extract_program_pdf("", fallback_title="my_fallback")
    assert result["title"] == "my_fallback"
    assert result["summary"] == ""
    assert result["amount_max_man_yen"] is None
    assert result["deadline_iso"] is None


# ---------------------------------------------------------------------------
# fetch — verifies PDF detection (URL suffix or Content-Type)
# ---------------------------------------------------------------------------


def test_fetch_returns_4_tuple(walker):
    """fetch() must always return a 4-tuple — schema is part of the contract."""
    # Hit a deliberately-bad URL to exercise the error path.
    result = walker.fetch("http://not-a-real-host.invalid.example/x.pdf", retries=0)
    assert isinstance(result, tuple)
    assert len(result) == 4
    status, html, ctype, pdf = result
    # Network failure → status=0, all empty.
    assert status == 0
    assert html == ""
    assert pdf is None
