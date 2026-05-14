"""Focused tests for public program links emitted by cron scripts."""

from __future__ import annotations

from scripts import compliance_cron
from scripts.cron import run_saved_searches, sunset_alerts


def test_run_saved_searches_prefers_static_program_url_when_name_available() -> None:
    url = run_saved_searches._public_url("東京都 テスト補助金", "UNI-test-static-1")

    assert url.startswith("https://jpcite.com/programs/")
    assert url.endswith(".html")
    assert "/programs/UNI-test-static-1" not in url
    assert "/programs/?id=" not in url


def test_run_saved_searches_falls_back_to_share_url_when_only_id_available() -> None:
    url = run_saved_searches._public_url(None, "UNI test/static")

    assert url == "https://jpcite.com/programs/share.html?ids=UNI%20test%2Fstatic"


def test_sunset_alerts_uses_safe_program_links() -> None:
    static_url = sunset_alerts._program_public_url("大阪府 テスト補助金", "UNI-test-static-2")
    fallback_url = sunset_alerts._program_public_url(None, "UNI test/static")

    assert static_url.startswith("https://jpcite.com/programs/")
    assert static_url.endswith(".html")
    assert "/programs/UNI-test-static-2" not in static_url
    assert fallback_url == "https://jpcite.com/programs/share.html?ids=UNI%20test%2Fstatic"


def test_compliance_cron_program_detail_url_is_static_or_share_fallback() -> None:
    static_url = compliance_cron._detail_url(
        "programs",
        "UNI-test-static-3",
        "北海道 テスト補助金",
    )
    fallback_url = compliance_cron._detail_url("programs", "UNI test/static")

    assert static_url.startswith("https://jpcite.com/programs/")
    assert static_url.endswith(".html")
    assert "/programs/UNI-test-static-3" not in static_url
    assert fallback_url == "https://jpcite.com/programs/share.html?ids=UNI%20test%2Fstatic"
