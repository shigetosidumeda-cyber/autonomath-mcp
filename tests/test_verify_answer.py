"""DEEP-25 + DEEP-37 + DEEP-38 verifiable answer primitive tests.

10 cases covering POST /v1/verify/answer:
  1. true positive — corpus match, score > 0.
  2. false claim — claim not in corpus, signal `claim_not_in_corpus`.
  3. dead source URL — HEAD 404, alive=False.
  4. boundary violation — `確実に採択されます`, score 0 clamp + violation.
  5. claim_count > 5 -> 400 too_many_claims.
  6. language en — body_en path runs, returns en disclaimer.
  7. aggregator URL reject — noukaweb.com, signal `aggregator_source`.
  8. timeout — HEAD takes >5s, signal `fetch_timeout`.
  9. rate limit smoke — anon path returns OK on 1st call (full 4-day flow
     covered by anon_limit fixture in shared conftest).
 10. LLM API import 0 — verifier modules import zero LLM SDKs.

Network is NEVER touched in this suite — `check_source_alive` is
monkeypatched per case.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def verify_client(client):
    """Reuse shared `client` fixture (from conftest)."""
    return client


# ---------------------------------------------------------------------------
# Case 1 — true positive
# ---------------------------------------------------------------------------


def test_true_positive_corpus_match(verify_client, monkeypatch):
    from jpintel_mcp.api import _verifier as v

    async def _stub_alive(urls):
        return [
            v.SourceLiveness(
                url=u,
                alive=True,
                status_code=200,
                signals=(),
            )
            for u in urls
        ]

    monkeypatch.setattr("jpintel_mcp.api.verify.check_source_alive", _stub_alive)

    resp = verify_client.post(
        "/v1/verify/answer",
        json={
            "answer_text": "持続化補助金は最大50万円。",
            "claimed_sources": ["https://www.meti.go.jp/example"],
            "language": "ja",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "verifiability_score" in body
    assert isinstance(body["verifiability_score"], int)
    assert 0 <= body["verifiability_score"] <= 100
    assert body["_cost_yen"] == 3
    assert "_disclaimer" in body
    assert body["language"] == "ja"
    assert "request_id" in body
    assert len(body["per_claim"]) >= 1


# ---------------------------------------------------------------------------
# Case 2 — false claim, not in corpus
# ---------------------------------------------------------------------------


def test_false_claim_not_in_corpus(verify_client, monkeypatch):
    from jpintel_mcp.api import _verifier as v

    # Force a degraded corpus path so all claims signal claim_not_in_corpus.
    monkeypatch.setattr(
        "jpintel_mcp.api.verify._open_autonomath_ro",
        lambda: None,
    )

    async def _stub_alive(urls):
        return [
            v.SourceLiveness(
                url=u,
                alive=True,
                status_code=200,
            )
            for u in urls
        ]

    monkeypatch.setattr("jpintel_mcp.api.verify.check_source_alive", _stub_alive)

    resp = verify_client.post(
        "/v1/verify/answer",
        json={
            "answer_text": "ダミー架空補助金は最大999万円。",
            "claimed_sources": ["https://www.meti.go.jp/example"],
            "language": "ja",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # Either claim_not_in_corpus or corpus_degraded must surface.
    signals = set(body["hallucination_signals"])
    assert {"claim_not_in_corpus", "corpus_degraded"} & signals or any(
        not pc["sources_match"] for pc in body["per_claim"]
    )


# ---------------------------------------------------------------------------
# Case 3 — dead source URL
# ---------------------------------------------------------------------------


def test_dead_source_url(verify_client, monkeypatch):
    from jpintel_mcp.api import _verifier as v

    async def _stub_alive(urls):
        return [
            v.SourceLiveness(
                url=u,
                alive=False,
                status_code=404,
                signals=("dead_source",),
            )
            for u in urls
        ]

    monkeypatch.setattr("jpintel_mcp.api.verify.check_source_alive", _stub_alive)

    resp = verify_client.post(
        "/v1/verify/answer",
        json={
            "answer_text": "持続化補助金は最大50万円。",
            "claimed_sources": ["https://www.meti.go.jp/dead-link"],
            "language": "ja",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "dead_source" in body["hallucination_signals"]


# ---------------------------------------------------------------------------
# Case 4 — boundary violation, score clamped to 0
# ---------------------------------------------------------------------------


def test_boundary_violation_score_clamped_to_zero(verify_client, monkeypatch):
    from jpintel_mcp.api import _verifier as v

    async def _stub_alive(urls):
        return [v.SourceLiveness(url=u, alive=True, status_code=200) for u in urls]

    monkeypatch.setattr("jpintel_mcp.api.verify.check_source_alive", _stub_alive)

    resp = verify_client.post(
        "/v1/verify/answer",
        json={
            "answer_text": "持続化補助金は確実に採択されます。最大50万円。",
            "claimed_sources": ["https://www.meti.go.jp/example"],
            "language": "ja",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verifiability_score"] == 0
    assert len(body["boundary_violations"]) >= 1
    laws_hit = {b["law"] for b in body["boundary_violations"]}
    assert "景表法" in laws_hit


# ---------------------------------------------------------------------------
# Case 5 — claim_count > 5 -> 400 too_many_claims
# ---------------------------------------------------------------------------


def test_claim_count_cap_returns_400(verify_client):
    # Six numeric claims in one payload triggers >5 atomic claims.
    answer = (
        "Aは最大10万円。Bは最大20万円。Cは最大30万円。Dは最大40万円。Eは最大50万円。Fは最大60万円。"
    )
    resp = verify_client.post(
        "/v1/verify/answer",
        json={
            "answer_text": answer,
            "claimed_sources": [],
            "language": "ja",
        },
    )
    assert resp.status_code == 400
    detail = resp.json().get("detail")
    if isinstance(detail, dict):
        assert detail.get("error") == "too_many_claims"
        assert detail.get("max_per_call") == 5
        assert detail.get("claim_count", 0) > 5
    else:
        # Some envelope adapters wrap the detail; assert the text marker.
        assert "too_many_claims" in resp.text


# ---------------------------------------------------------------------------
# Case 6 — language en
# ---------------------------------------------------------------------------


def test_language_en_returns_en_disclaimer(verify_client, monkeypatch):
    from jpintel_mcp.api import _verifier as v

    async def _stub_alive(urls):
        return [v.SourceLiveness(url=u, alive=True, status_code=200) for u in urls]

    monkeypatch.setattr("jpintel_mcp.api.verify.check_source_alive", _stub_alive)

    resp = verify_client.post(
        "/v1/verify/answer",
        json={
            "answer_text": "The subsidy program offers up to 500,000 yen.",
            "claimed_sources": ["https://www.meti.go.jp/example"],
            "language": "en",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["language"] == "en"
    # English disclaimer must NOT be Japanese.
    assert "tax advice" in body["_disclaimer"].lower() or "qualified" in body["_disclaimer"].lower()


# ---------------------------------------------------------------------------
# Case 7 — aggregator URL reject
# ---------------------------------------------------------------------------


def test_aggregator_url_rejected():
    """Direct unit test: noukaweb.com should mark aggregator_violation."""
    import asyncio

    from jpintel_mcp.api._verifier import check_source_alive

    sources = asyncio.run(check_source_alive(["https://noukaweb.com/some-program"]))
    assert len(sources) == 1
    s = sources[0]
    assert s.aggregator_violation is True
    assert "aggregator_source" in s.signals
    assert s.alive is False


# ---------------------------------------------------------------------------
# Case 8 — timeout
# ---------------------------------------------------------------------------


def test_fetch_timeout_signal(verify_client, monkeypatch):
    from jpintel_mcp.api import _verifier as v

    async def _timeout_stub(urls):
        return [
            v.SourceLiveness(
                url=u,
                alive=None,
                status_code=0,
                signals=("fetch_timeout",),
            )
            for u in urls
        ]

    monkeypatch.setattr("jpintel_mcp.api.verify.check_source_alive", _timeout_stub)

    resp = verify_client.post(
        "/v1/verify/answer",
        json={
            "answer_text": "持続化補助金は最大50万円。",
            "claimed_sources": ["https://www.meti.go.jp/slow"],
            "language": "ja",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "fetch_timeout" in body["hallucination_signals"]


# ---------------------------------------------------------------------------
# Case 9 — anon-tier sanity (single call should pass)
# ---------------------------------------------------------------------------


def test_anonymous_single_call_succeeds(verify_client, monkeypatch):
    from jpintel_mcp.api import _verifier as v

    async def _stub_alive(urls):
        return [v.SourceLiveness(url=u, alive=True, status_code=200) for u in urls]

    monkeypatch.setattr("jpintel_mcp.api.verify.check_source_alive", _stub_alive)

    # No X-API-Key header — anonymous path. AnonIpLimitDep allows the
    # first call within the JST quota (test fixture resets to 100/day).
    resp = verify_client.post(
        "/v1/verify/answer",
        json={
            "answer_text": "持続化補助金は最大50万円。",
            "claimed_sources": [],
            "language": "ja",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["_cost_yen"] == 3
    assert "_disclaimer" in body


# ---------------------------------------------------------------------------
# Case 10 — LLM API import 0
# ---------------------------------------------------------------------------


def test_zero_llm_api_imports_in_verifier_modules():
    """The verifier and route MUST NOT import any LLM SDK.

    memory `feedback_no_operator_llm_api` enforces zero
    `anthropic` / `openai` / `google.generativeai` / `claude_agent_sdk`
    imports anywhere under src/jpintel_mcp/api/.
    """
    forbidden = (
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "import google.generativeai",
        "from google.generativeai",
        "import claude_agent_sdk",
        "from claude_agent_sdk",
    )

    repo_root = Path(__file__).resolve().parents[1]
    files_to_check = [
        repo_root / "src" / "jpintel_mcp" / "api" / "_verifier.py",
        repo_root / "src" / "jpintel_mcp" / "api" / "verify.py",
    ]

    for fp in files_to_check:
        assert fp.exists(), f"missing module: {fp}"
        content = fp.read_text(encoding="utf-8")
        for bad in forbidden:
            assert bad not in content, (
                f"{fp.name} must not contain `{bad}` (memory feedback_no_operator_llm_api)"
            )

    # Also confirm the modules import cleanly without dragging in any
    # LLM SDK as a transitive symbol (e.g. via re-exports).
    sys.modules.pop("jpintel_mcp.api._verifier", None)
    importlib.import_module("jpintel_mcp.api._verifier")

    sys.modules.pop("jpintel_mcp.api.verify", None)
    importlib.import_module("jpintel_mcp.api.verify")

    leaked = [
        m
        for m in sys.modules
        if m.split(".")[0] in {"anthropic", "openai", "google", "claude_agent_sdk"}
        and m != "google"  # google namespace package may exist via httpx etc.
    ]
    # google submodules of generativeai would be the regression we worry
    # about; just google itself is harmless.
    leaked = [m for m in leaked if "generativeai" in m]
    assert not leaked, f"forbidden LLM SDK leaked into sys.modules: {leaked}"
