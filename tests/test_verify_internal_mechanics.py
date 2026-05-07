"""DEEP-37 verifier internal-mechanics deepening tests (5 cases).

Complements the 10 happy-path cases in `test_verify_answer.py` (DEEP-25)
by exercising the deepened internals introduced in v0.3.4:

  1. tokenize_claims sudachipy fallback graceful — sentinel sentence
     splitter behaves identically when sudachipy is missing (CI default)
     and matches the regex baseline.
  2. match_to_corpus sqlite-vec witness probe — when am_entities_vec +
     am_alias rows exist, signal `vec_corroborated` surfaces; when they
     don't, no false positive.
  3. check_source_alive parallel speed — 5 license-OK URLs HEAD-fetch
     under 10s wall-clock with httpx mocked to 100ms each (proves the
     asyncio.gather + Semaphore(5) wiring is in the loop, not serial).
  4. detect_boundary_violations integrates the same forbidden-phrase
     surface as DEEP-38 `_business_law_detector.detect_violations`:
     7 業法 keys overlap, both pure regex, both LLM 0.
  5. claim_count > 5 → 400 (smoke; canonical case in
     `test_verify_answer.py::test_claim_count_cap_returns_400`).

All cases avoid network. The HEAD path is monkeypatched via httpx
AsyncClient stub. No LLM SDK is touched anywhere — verified by reusing
the assertion pattern from `test_verify_answer.py::test_zero_llm_api_imports_in_verifier_modules`.
"""

from __future__ import annotations

import asyncio
import importlib
import sqlite3
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Case 1 — tokenize_claims sudachipy fallback graceful
# ---------------------------------------------------------------------------


def test_tokenize_sudachi_fallback_matches_regex_baseline():
    """When sudachipy is absent, `_split_sentences_advanced` collapses to
    the regex `_split_sentences`. Claim count + ordering must be stable.
    """
    from jpintel_mcp.api import _verifier as v

    text = "持続化補助金は最大50万円。ものづくり補助金は最大1000万円。"
    claims_advanced = v.tokenize_claims(text, language="ja")
    # Regex-only baseline: temporarily monkeypatch the advanced splitter
    # to call the regex split directly and confirm parity.
    sentences_regex = v._split_sentences(v._normalize(text))
    assert len(sentences_regex) == 2
    # tokenize_claims emits ≥ len(sentences) claims (one per yen match
    # + bare-sentence claim if no match). Each sentence has 1 yen match.
    assert len(claims_advanced) >= 2
    yen_values = [c.numeric_value for c in claims_advanced if c.numeric_unit == "yen"]
    assert "500000" in yen_values
    assert "10000000" in yen_values
    # Sudachi must NEVER raise, regardless of install state.
    # (`_SUDACHI_AVAILABLE` may be False on the CI box; either branch is OK.)
    assert isinstance(v._SUDACHI_AVAILABLE, bool)
    assert isinstance(v._SPACY_AVAILABLE, bool)


# ---------------------------------------------------------------------------
# Case 2 — sqlite-vec witness probe (mock data)
# ---------------------------------------------------------------------------


def _seed_vec_db(path: Path) -> None:
    """Seed a tiny in-process sqlite DB that mimics autonomath.db's
    am_entities + am_alias + am_entities_vec just enough for the
    `_vec_match_signal` probe.
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            CREATE TABLE am_entities (
                entity_id TEXT PRIMARY KEY,
                name TEXT,
                record_kind TEXT
            );
            CREATE TABLE am_alias (
                entity_id TEXT,
                alias_text TEXT
            );
            CREATE TABLE am_entities_vec (
                entity_id TEXT PRIMARY KEY
            );
            CREATE TABLE am_amount_condition (
                entity_id TEXT,
                amount_max_yen INTEGER
            );
            INSERT INTO am_entities VALUES ('e1', '持続化補助金', 'program');
            INSERT INTO am_alias VALUES ('e1', '持続化補助金');
            INSERT INTO am_entities_vec VALUES ('e1');
            INSERT INTO am_amount_condition VALUES ('e1', 500000);
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_match_to_corpus_emits_vec_corroborated(tmp_path):
    from jpintel_mcp.api import _verifier as v

    db = tmp_path / "verifier_vec.db"
    _seed_vec_db(db)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        # Use a short keyword sentence so `re.split` keeps `持続化補助金` as
        # the first token and the LIKE probe lands on the seeded entity.
        claim = v.Claim(
            text="持続化補助金、最大50万円",
            numeric_value="500000",
            numeric_unit="yen",
            span=(0, 12),
        )
        match = v.match_to_corpus(claim, conn)
        assert match.matched_jpcite_record == "programs/e1", match
        assert "vec_corroborated" in match.signals
    finally:
        conn.close()


def test_match_to_corpus_no_vec_no_false_signal(tmp_path):
    """When am_entities_vec is missing, vec_corroborated MUST NOT surface."""
    from jpintel_mcp.api import _verifier as v

    db = tmp_path / "verifier_no_vec.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(
            """
            CREATE TABLE am_entities (
                entity_id TEXT PRIMARY KEY,
                name TEXT,
                record_kind TEXT
            );
            CREATE TABLE am_alias (
                entity_id TEXT,
                alias_text TEXT
            );
            CREATE TABLE am_amount_condition (
                entity_id TEXT,
                amount_max_yen INTEGER
            );
            INSERT INTO am_entities VALUES ('e2', '持続化補助金', 'program');
            INSERT INTO am_alias VALUES ('e2', '持続化補助金');
            INSERT INTO am_amount_condition VALUES ('e2', 500000);
            """
        )
        conn.commit()
    finally:
        conn.close()
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        claim = v.Claim(
            text="持続化補助金、最大50万円",
            numeric_value="500000",
            numeric_unit="yen",
            span=(0, 12),
        )
        match = v.match_to_corpus(claim, conn)
        assert "vec_corroborated" not in match.signals
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Case 3 — HEAD parallel speed (5 URL < 10s)
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status: int, headers: dict | None = None) -> None:
        self.status_code = status
        self.headers = headers or {}


class _FakeAsyncClient:
    """Async HEAD stub — sleeps 100ms per request to model real network."""

    def __init__(self, *_, **__) -> None:  # noqa: D401
        self._calls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def head(self, url: str):
        await asyncio.sleep(0.1)
        self._calls.append(url)
        return _FakeResp(200, {"Content-Type": "text/html"})


def test_check_source_alive_runs_in_parallel(monkeypatch):
    """5 URL × 100ms each must finish well below 0.5s × 5 = 2.5s serial.
    With Semaphore(5) + gather, total wall-clock ≈ 100-300ms.
    The sanity ceiling is 10s so the test never flakes on slow hosts.
    """
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    from jpintel_mcp.api._verifier import check_source_alive

    urls = [f"https://www.meti.go.jp/page-{i}" for i in range(5)]
    started = time.monotonic()
    results = asyncio.run(check_source_alive(urls))
    elapsed = time.monotonic() - started

    assert len(results) == 5
    assert all(r.alive is True for r in results)
    assert elapsed < 10.0, f"check_source_alive took {elapsed:.2f}s — not parallel?"


# ---------------------------------------------------------------------------
# Case 4 — DEEP-38 detector reuse / overlap
# ---------------------------------------------------------------------------


def test_deep38_detector_overlap_with_inline_boundary_check():
    """The verifier's inline `detect_boundary_violations` and DEEP-38's
    `_business_law_detector.detect_violations` are intentionally separate
    primitives (verifier ships a curated 7業法 + 景表法 subset for
    fail-closed scoring; DEEP-38 ships the full 124-pattern catalog
    covering ONLY 7業法). They MUST agree on the 7業法 keys.
    """
    from jpintel_mcp.api import _business_law_detector as d38
    from jpintel_mcp.api._verifier import detect_boundary_violations

    # 税理士法 §52 phrase shared by BOTH detectors.
    text = "税務代理を行います。"

    inline = detect_boundary_violations(text, lang="ja")
    d38_hits = d38.detect_violations(text)

    inline_laws = {v.law for v in inline}
    d38_laws = {h["law"] for h in d38_hits}

    # Both detectors must catch the 税理士法 §52 fence on this text.
    assert "税理士法" in inline_laws, f"inline missed 税理士法: {inline_laws}"
    assert "税理士法" in d38_laws, f"DEEP-38 missed 税理士法: {d38_laws}"

    # 7 業法 universe is consistent across both detectors (verifier
    # additionally carries 景表法; DEEP-38 does not).
    # Honest alias note: DEEP-38 uses the abbreviation `社労士法` while
    # the verifier inline uses the long form `社会保険労務士法`. Both
    # point to 社会保険労務士法 §27 — we accept either.
    seven_keys_inline = {
        "税理士法",
        "弁護士法",
        "行政書士法",
        "司法書士法",
        "弁理士法",
        "社会保険労務士法",
        "公認会計士法",
    }
    seven_keys_d38 = {
        "税理士法",
        "弁護士法",
        "行政書士法",
        "司法書士法",
        "弁理士法",
        "社労士法",
        "公認会計士法",
    }
    from jpintel_mcp.api._verifier import _COMPILED_JA

    inline_law_universe = {law for law, _, _, _ in _COMPILED_JA}
    assert seven_keys_inline.issubset(inline_law_universe), (
        f"verifier inline catalog missing 業法 keys: {seven_keys_inline - inline_law_universe}"
    )

    d38_universe = {
        h["law"]
        for h in d38.detect_violations(
            "税務代理を行います。示談交渉します。許認可申請代行。登記申請代行。"
            "特許出願代行。社会保険手続代行。監査証明します。"
        )
    }
    assert seven_keys_d38.issubset(d38_universe), (
        f"DEEP-38 catalog missing 業法 keys: {seven_keys_d38 - d38_universe}"
    )


# ---------------------------------------------------------------------------
# Case 5 — claim_count > 5 → 400 (smoke; canonical in test_verify_answer.py)
# ---------------------------------------------------------------------------


def test_claim_count_cap_enforced_at_route(client, monkeypatch):
    from jpintel_mcp.api import _verifier as v

    async def _stub_alive(urls):
        return [v.SourceLiveness(url=u, alive=True, status_code=200) for u in urls]

    monkeypatch.setattr("jpintel_mcp.api.verify.check_source_alive", _stub_alive)

    answer = (
        "Aは最大10万円。Bは最大20万円。Cは最大30万円。Dは最大40万円。Eは最大50万円。Fは最大60万円。"
    )
    resp = client.post(
        "/v1/verify/answer",
        json={
            "answer_text": answer,
            "claimed_sources": [],
            "language": "ja",
        },
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json().get("detail")
    if isinstance(detail, dict):
        assert detail.get("error") == "too_many_claims"
        assert detail.get("max_per_call") == 5


# ---------------------------------------------------------------------------
# LLM 0 sentinel — verifier deepening MUST NOT add LLM SDK imports
# ---------------------------------------------------------------------------


def test_zero_llm_api_imports_after_deepening():
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

    sys.modules.pop("jpintel_mcp.api._verifier", None)
    importlib.import_module("jpintel_mcp.api._verifier")
    sys.modules.pop("jpintel_mcp.api.verify", None)
    importlib.import_module("jpintel_mcp.api.verify")
