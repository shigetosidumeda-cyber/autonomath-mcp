"""Dim H — personalization MCP wrapper tests (Wave 46 dim 19 SFGH).

Covers ``src/jpintel_mcp/mcp/autonomath_tools/personalization_mcp.py``
which ships ``personalization_recommendations_am`` — the MCP wrapper
over ``api/personalization_v2.py`` (REST GET /v1/me/recommendations).

Posture
-------
* Pure unit test — no live MCP server, no live DB. We exercise the
  ``_personalization_recommendations_am_impl`` helper directly with
  monkeypatched DB openers so the test runs in-memory.
* No LLM SDK imports (verified by a banned-imports grep).
* No live autonomath.db / jpintel.db touch.

Cases
-----
1. anonymous session (api_key_hash=None) returns error envelope.
2. invalid limit returns error envelope.
3. unknown client_id returns 'not_found' error envelope.
4. happy-path: 200 with one scored program.
5. No LLM SDK imported by the module.
"""

from __future__ import annotations

import importlib
import sqlite3
from typing import Any

import pytest


@pytest.fixture()
def _seeded_dbs(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Seed tiny jpintel + autonomath sqlite fixtures and patch openers."""
    jp_path = tmp_path / "jpintel.db"
    am_path = tmp_path / "autonomath.db"

    jp = sqlite3.connect(str(jp_path))
    jp.row_factory = sqlite3.Row
    jp.executescript(
        """
        CREATE TABLE client_profiles (
          profile_id INTEGER PRIMARY KEY,
          api_key_hash TEXT NOT NULL,
          name_label TEXT
        );
        CREATE TABLE programs (
          unified_id TEXT PRIMARY KEY,
          primary_name TEXT NOT NULL,
          tier TEXT,
          prefecture TEXT,
          program_kind TEXT,
          source_url TEXT,
          official_url TEXT,
          excluded INTEGER DEFAULT 0
        );
        INSERT INTO client_profiles (profile_id, api_key_hash, name_label)
          VALUES (101, 'khash_xyz', '顧問先株式会社');
        INSERT INTO programs
          (unified_id, primary_name, tier, prefecture, program_kind, source_url, excluded)
          VALUES
          ('prog_A', '小規模事業者持続化補助金', 'A', '東京都', 'subsidy',
           'https://example.test/A', 0),
          ('prog_excl', 'excluded', 'A', '東京都', 'subsidy',
           'https://example.test/X', 1);
        """,
    )
    jp.commit()

    am = sqlite3.connect(str(am_path))
    am.row_factory = sqlite3.Row
    am.executescript(
        """
        CREATE TABLE am_personalization_score (
          api_key_hash TEXT NOT NULL,
          client_id    INTEGER NOT NULL,
          program_id   TEXT NOT NULL,
          score        INTEGER NOT NULL,
          score_breakdown_json TEXT,
          reasoning_json TEXT,
          refreshed_at TEXT,
          PRIMARY KEY (api_key_hash, client_id, program_id)
        );
        INSERT INTO am_personalization_score
          (api_key_hash, client_id, program_id, score, refreshed_at)
          VALUES ('khash_xyz', 101, 'prog_A', 72, '2026-05-12T03:00:00Z');
        """,
    )
    am.commit()

    # Patch the module's DB openers so we hit the tempdir fixtures.
    from jpintel_mcp.mcp.autonomath_tools import personalization_mcp as mod

    def _fake_jp() -> sqlite3.Connection:
        c = sqlite3.connect(str(jp_path))
        c.row_factory = sqlite3.Row
        return c

    def _fake_am() -> sqlite3.Connection:
        c = sqlite3.connect(f"file:{am_path}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(mod, "_open_jpintel_safe", _fake_jp)
    monkeypatch.setattr(mod, "_open_autonomath_ro_safe", _fake_am)
    return mod


def test_anonymous_session_returns_error(_seeded_dbs: Any) -> None:
    mod = _seeded_dbs
    out = mod._personalization_recommendations_am_impl(
        client_id=101, api_key_hash=None,
    )
    # error envelope shape from error_envelope.make_error
    assert "error" in out or "code" in out
    payload = out.get("error", out)
    # Coerced to missing_required_arg (closed enum); field signals which.
    assert payload.get("code") == "missing_required_arg"
    assert payload.get("field") == "api_key_hash"


def test_invalid_limit_returns_error(_seeded_dbs: Any) -> None:
    mod = _seeded_dbs
    out = mod._personalization_recommendations_am_impl(
        client_id=101, api_key_hash="khash_xyz", limit=0,
    )
    payload = out.get("error", out)
    assert payload.get("code") == "invalid_input"


def test_unknown_client_id_returns_not_found(_seeded_dbs: Any) -> None:
    mod = _seeded_dbs
    out = mod._personalization_recommendations_am_impl(
        client_id=999, api_key_hash="khash_xyz",
    )
    payload = out.get("error", out)
    assert payload.get("code") == "not_found"


def test_happy_path_returns_one_item(_seeded_dbs: Any) -> None:
    mod = _seeded_dbs
    out = mod._personalization_recommendations_am_impl(
        client_id=101, api_key_hash="khash_xyz", limit=5,
    )
    assert "error" not in out
    assert out["client_id"] == 101
    assert out["client_label"] == "顧問先株式会社"
    assert out["total"] == 1
    items = out["items"]
    assert len(items) == 1
    assert items[0]["program_id"] == "prog_A"
    assert items[0]["score"] == 72
    assert items[0]["tier"] == "A"
    assert out["_billing_unit"] == 1
    # Disclaimer text mentions the §52 / §72 / §1 / §47条の2 envelope
    assert "§52" in out["_disclaimer"]
    assert "§72" in out["_disclaimer"]


def test_no_llm_imports_in_personalization_mcp() -> None:
    """Hard guard: module must not import an LLM SDK."""
    mod = importlib.import_module(
        "jpintel_mcp.mcp.autonomath_tools.personalization_mcp"
    )
    src = mod.__file__
    assert src is not None
    with open(src, encoding="utf-8") as f:
        text = f.read()
    banned = [
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "import google.generativeai",
        "from google.generativeai",
        "import cohere",
        "from cohere",
    ]
    for ban in banned:
        assert ban not in text, (
            f"banned LLM import in personalization_mcp: {ban}"
        )
