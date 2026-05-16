from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER = REPO_ROOT / "workers" / "www-redirect.js"


def test_www_redirect_worker_is_apex_301_only() -> None:
    text = WORKER.read_text(encoding="utf-8")

    assert '"www.jpcite.com"' in text
    assert '"zeimu-kaikei.ai"' in text
    assert '"www.zeimu-kaikei.ai"' in text
    assert "!redirectHosts.has(url.hostname)" in text
    assert 'url.hostname = "jpcite.com"' in text
    assert "Response.redirect(url.toString(), 301)" in text


def test_www_redirect_worker_does_not_drop_path_or_query() -> None:
    text = WORKER.read_text(encoding="utf-8")

    assert "new URL(request.url)" in text
    assert "url.pathname" not in text
    assert "url.search" not in text
