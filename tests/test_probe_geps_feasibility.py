"""Fixture-driven tests for scripts/etl/probe_geps_feasibility.py.

The script's network probes are not exercised here — we test the pure
classifier + helpers (CSRF parsing, anti-bot detection, markdown rendering)
that decide the feasibility verdict. Network behaviour is captured through
hand-crafted ProbeResult fixtures that mirror real responses observed on
2026-04-30.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import probe_geps_feasibility as probe  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures: the four canonical world-states we care about.
# ---------------------------------------------------------------------------


def _legacy_redirect() -> probe.ProbeResult:
    return probe.ProbeResult(
        name="legacy_geps_root",
        url="https://www.geps.go.jp/",
        kind="html",
        status=200,
        final_url="https://www.geps.go.jp/",
        body_len=2567,
        body_excerpt=(
            "政府電子調達(GEPS)のポータルサイトは、調達ポータルに統合されました。"
        ),
    )


def _legacy_robots_404() -> probe.ProbeResult:
    return probe.ProbeResult(
        name="legacy_geps_robots",
        url="https://www.geps.go.jp/robots.txt",
        kind="robots",
        status=404,
    )


def _portal_robots_oidc() -> probe.ProbeResult:
    return probe.ProbeResult(
        name="p_portal_robots",
        url="https://www.p-portal.go.jp/robots.txt",
        kind="robots",
        status=302,
        redirected_to_oidc=True,
    )


def _portal_search_form_200() -> probe.ProbeResult:
    return probe.ProbeResult(
        name="p_portal_search_form",
        url="https://www.p-portal.go.jp/pps-web-biz/UAA01/OAA0100?OAA0115",
        kind="html",
        status=200,
        final_url="https://www.p-portal.go.jp/pps-web-biz/UAA01/OAA0101",
        body_len=175369,
        body_excerpt="調達情報の検索 form (CSRF-protected POST)",
    )


def _portal_rss_oidc() -> probe.ProbeResult:
    return probe.ProbeResult(
        name="p_portal_rss",
        url="https://www.p-portal.go.jp/pps-web-biz/rss",
        kind="feed",
        status=302,
        redirected_to_oidc=True,
    )


def _portal_rss_200() -> probe.ProbeResult:
    return probe.ProbeResult(
        name="p_portal_rss",
        url="https://www.p-portal.go.jp/pps-web-biz/rss",
        kind="feed",
        status=200,
        body_len=4096,
        body_excerpt="<rss version='2.0'><channel><item><title>...",
    )


def _portal_rss_login_html() -> probe.ProbeResult:
    """RSS endpoint that 302→login page (status=200 at end of chain, but body is the login form HTML, not a feed). Final URL = /pps-auth-biz/login-cert."""
    return probe.ProbeResult(
        name="p_portal_rss",
        url="https://www.p-portal.go.jp/pps-web-biz/rss",
        kind="feed",
        status=200,
        final_url="https://www.p-portal.go.jp/pps-auth-biz/login-cert",
        body_len=37398,
        redirected_to_oidc=True,
        body_excerpt="<html><title>ログイン</title>",
    )


# ---------------------------------------------------------------------------
# Classifier tests
# ---------------------------------------------------------------------------


class TestClassify:
    def test_real_world_2026_04_30_yields_search_public_with_anti_bot(self) -> None:
        """Reflects the actual probe state observed on 2026-04-30 — every
        feed/sitemap/opendata path 302-chains to /pps-auth-biz/login-cert
        (status=200 at the end but final_url is the login page).
        """
        probes = [
            _legacy_redirect(),
            _legacy_robots_404(),
            _portal_robots_oidc(),
            _portal_search_form_200(),
            _portal_rss_login_html(),
        ]
        rep = probe.classify(probes)
        assert rep.classification == "search_public_with_anti_bot"
        assert rep.public_search_form_ok is True
        assert rep.has_rss is False
        assert "anti-bot" in rep.summary or "CSRF" in rep.summary

    def test_rss_present_takes_precedence_over_search(self) -> None:
        """If a public RSS feed is ever exposed, we prefer it."""
        probes = [_portal_search_form_200(), _portal_rss_200()]
        rep = probe.classify(probes)
        assert rep.classification == "rss_public"
        assert rep.has_rss is True

    def test_only_oidc_redirects_classified_as_oidc_only(self) -> None:
        probes = [
            probe.ProbeResult(
                name="p_portal_search_form",
                url="x",
                kind="html",
                status=302,
                redirected_to_oidc=True,
            ),
            _portal_rss_oidc(),
        ]
        rep = probe.classify(probes)
        assert rep.classification == "oidc_only"
        assert rep.public_search_form_ok is False

    def test_login_cert_chain_treated_as_oidc(self) -> None:
        """If a probe 302-chains to /pps-auth-biz/login-cert, the final
        body is the login HTML — must NOT count as has_rss / has_sitemap.
        """
        probes = [_portal_rss_login_html(), _portal_search_form_200()]
        rep = probe.classify(probes)
        assert rep.has_rss is False  # login HTML must not be confused with a feed
        assert rep.classification == "search_public_with_anti_bot"

    def test_all_errors_yields_unreachable(self) -> None:
        probes = [
            probe.ProbeResult(
                name="p_portal_search_form",
                url="x",
                kind="html",
                status=None,
                error="timeout",
            ),
            probe.ProbeResult(
                name="p_portal_rss",
                url="y",
                kind="feed",
                status=503,
            ),
        ]
        rep = probe.classify(probes)
        assert rep.classification == "unreachable"


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_extract_csrf_from_real_html_snippet(self) -> None:
        html = (
            '<form><input type="hidden" name="_csrf" '
            'value="660a363b-6c84-450e-9db0-8b2881cbc297" /></form>'
        )
        assert probe._extract_csrf(html) == "660a363b-6c84-450e-9db0-8b2881cbc297"

    def test_extract_csrf_returns_none_when_absent(self) -> None:
        assert probe._extract_csrf("<html><body>no token</body></html>") is None

    def test_anti_bot_detection_matches_real_block_page(self) -> None:
        body = (
            '<article class="main-item"><div class="message-error">'
            "不正な操作が行われました。<br>"
            "トップページからアクセスし直してください。"
            "</div></article>"
        )
        assert probe.detect_submission_anti_bot(body) is True

    def test_anti_bot_detection_misses_normal_body(self) -> None:
        assert probe.detect_submission_anti_bot("<html>調達情報の検索</html>") is False

    def test_is_oidc_redirect_matches_cdcservlet(self) -> None:
        assert probe._is_oidc_redirect(
            "https://www.p-portal.go.jp/pps-auth-biz/CDCServlet?response_type=code"
        )

    def test_is_oidc_redirect_misses_normal_url(self) -> None:
        assert not probe._is_oidc_redirect(
            "https://www.p-portal.go.jp/pps-web-biz/UAA01/OAA0101"
        )


# ---------------------------------------------------------------------------
# Markdown + CSV writers
# ---------------------------------------------------------------------------


class TestRenderers:
    def test_render_markdown_includes_classification_and_probe_table(self) -> None:
        probes = [_legacy_redirect(), _portal_search_form_200(), _portal_rss_oidc()]
        rep = probe.classify(probes)
        rep.submission_blocked_by_anti_bot = True
        out = probe.render_markdown(rep)
        assert "GEPS" in out and "Feasibility" in out
        assert rep.classification in out
        assert "search_public_with_anti_bot" in out
        assert "Probe table" in out
        assert "legacy_geps_root" in out
        assert "p_portal_search_form" in out
        assert "anti_bot" in out.lower() or "anti-bot" in out.lower()
        # Constraint compliance section is mandatory
        assert "robots.txt" in out
        assert "OIDC bypass: not attempted" in out

    def test_write_smoke_csv_creates_file_with_header(self, tmp_path: Path) -> None:
        out = tmp_path / "smoke.csv"
        probe.write_smoke_csv(out, [])
        assert out.exists()
        with out.open(encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = list(reader)
        for col in probe.SMOKE_CSV_FIELDS:
            assert col in header
        assert rows == []  # no smoke rows under blocked classification

    def test_write_smoke_csv_round_trips_rows(self, tmp_path: Path) -> None:
        out = tmp_path / "smoke.csv"
        probe.write_smoke_csv(
            out,
            [
                {
                    "case_number": "2025-001",
                    "bid_title": "テスト調達案件",
                    "procuring_entity": "農林水産省",
                    "announcement_date": "2026-01-01",
                    "source_url": "https://www.p-portal.go.jp/pps-web-biz/UAA01/OAA0101?case_no=2025-001",
                    "fetched_at": "2026-04-30T00:00:00Z",
                    "note": "",
                }
            ],
        )
        with out.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["case_number"] == "2025-001"
        assert rows[0]["procuring_entity"] == "農林水産省"


# ---------------------------------------------------------------------------
# Integration: --no-network produces a valid report
# ---------------------------------------------------------------------------


class TestRowParser:
    """Verify the result-page row parser against fixture HTML."""

    _FIXTURE = (
        "<html><body>"
        "<table>"
        "<tr><td id=\"tri_WAA0101FM01/procurementResultListBean/articleNm\">"
        "テスト調達案件A</td>"
        "<td id=\"tri_WAA0101FM01/procurementResultListBean/procurementItemNo\">"
        "0000000000000456436</td>"
        "<td id=\"tri_WAA0101FM01/procurementResultListBean/procurementOrgan\">"
        "厚生労働省</td>"
        "<td id=\"tri_WAA0101FM01/procurementResultListBean/receiptAddress\">"
        "愛知県</td></tr>"
        "<tr><td id=\"tri_WAA0101FM01/procurementResultListBean/articleNm\">"
        "テスト調達案件B</td>"
        "<td id=\"tri_WAA0101FM01/procurementResultListBean/procurementItemNo\">"
        "0000000000000527319</td>"
        "<td id=\"tri_WAA0101FM01/procurementResultListBean/procurementOrgan\">"
        "財務省</td>"
        "<td id=\"tri_WAA0101FM01/procurementResultListBean/receiptAddress\">"
        "東京都</td></tr>"
        "</table></body></html>"
    )

    def test_parses_two_rows_in_order(self) -> None:
        rows = probe.parse_result_page_rows(
            html=self._FIXTURE,
            request_url="https://www.p-portal.go.jp/pps-web-biz/UAA01/OAA0106",
            fetched_at="2026-05-01T00:00:00Z",
            limit=30,
        )
        assert len(rows) == 2
        assert rows[0]["case_number"] == "0000000000000456436"
        assert rows[0]["bid_title"] == "テスト調達案件A"
        assert rows[0]["procuring_entity"] == "厚生労働省"
        assert rows[1]["procuring_entity"] == "財務省"
        # Source URL fragment must include case_no for traceability
        assert "#case_no=0000000000000456436" in rows[0]["source_url"]
        # receipt_address travels in note
        assert "愛知県" in rows[0]["note"]

    def test_limit_caps_row_count(self) -> None:
        rows = probe.parse_result_page_rows(
            html=self._FIXTURE,
            request_url="https://example.invalid/",
            fetched_at="x",
            limit=1,
        )
        assert len(rows) == 1

    def test_empty_html_yields_no_rows(self) -> None:
        rows = probe.parse_result_page_rows(
            html="<html></html>",
            request_url="x",
            fetched_at="x",
            limit=30,
        )
        assert rows == []


class TestNoNetworkRun:
    def test_no_network_writes_md_and_csv(self, tmp_path: Path) -> None:
        md = tmp_path / "report.md"
        csv_path = tmp_path / "smoke.csv"
        rc = probe.run(
            output_md=md,
            output_csv=csv_path,
            smoke_limit=30,
            no_network=True,
        )
        assert rc == 0
        assert md.exists() and csv_path.exists()
        body = md.read_text(encoding="utf-8")
        assert "search_public_with_anti_bot" in body
        assert "OIDC" in body or "oidc" in body
