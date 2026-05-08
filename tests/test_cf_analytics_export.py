from __future__ import annotations

from scripts.cron import cf_analytics_export as cf


def test_classify_user_agent_separates_ai_crawlers_and_internal_traffic() -> None:
    assert cf.classify_user_agent("ChatGPT-User/1.0") == "bot:chatgpt-user"
    assert cf.classify_user_agent("OAI-SearchBot/1.0") == "bot:oai-searchbot"
    assert cf.classify_user_agent("Amazonbot/0.1") == "bot:amazonbot"
    assert cf.classify_user_agent("Codex read-only consistency review") == ("internal:codex-review")
    assert cf.classify_user_agent("TLM-Audit-Scanner/1.0") == "internal:tlm-audit-scanner"
    assert cf.classify_user_agent("nginx-ssl early hints") == "internal:early-hints"


def test_referer_host_normalizes_full_urls_and_host_only_values() -> None:
    assert cf._referer_host("https://www.google.com/search?q=jpcite") == "www.google.com"
    assert cf._referer_host("chatgpt.com/share/abc") == "chatgpt.com"
    assert cf._referer_host("HTTPS://EXAMPLE.COM/path") == "example.com"
    assert cf._referer_host("(direct)") == ""
    assert cf._referer_host("") == ""
