"""DEEP-46 policy_upstream test suite — 6 cases.

Coverage map:

  1. test_watch_envelope_contract            — policy_upstream_watch happy path
  2. test_watch_input_validation             — keyword empty / invalid bounds
  3. test_timeline_envelope_contract         — policy_upstream_timeline happy path
  4. test_timeline_input_validation          — topic empty / out-of-range limit
  5. test_no_llm_imports_in_deep46_files     — LLM 0 guard
  6. test_router_mounted_in_main             — REST router wired in api.main
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_KOKKAI_MIGRATION = _REPO_ROOT / "scripts" / "migrations" / "wave24_185_kokkai_utterance.sql"
_PUBCOMMENT_MIGRATION = (
    _REPO_ROOT / "scripts" / "migrations" / "wave24_192_pubcomment_announcement.sql"
)
_TOOL_MODULE = (
    _REPO_ROOT / "src" / "jpintel_mcp" / "mcp" / "autonomath_tools" / "policy_upstream_tools.py"
)
_REST_MODULE = _REPO_ROOT / "src" / "jpintel_mcp" / "api" / "policy_upstream.py"
_MAIN_MODULE = _REPO_ROOT / "src" / "jpintel_mcp" / "api" / "main.py"


def _seed_db(db_path: Path) -> None:
    """Apply DEEP-39 + DEEP-45 migrations + insert one row each axis.

    The fixture writes one matching kokkai utterance, one shingikai
    minute, and one ongoing pubcomment announcement so both impls
    have non-empty data to roll up.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_KOKKAI_MIGRATION.read_text(encoding="utf-8"))
        conn.executescript(_PUBCOMMENT_MIGRATION.read_text(encoding="utf-8"))
        conn.execute(
            """
            INSERT INTO kokkai_utterance
                (id, session_no, house, committee, date, speaker,
                 speaker_role, body, source_url, retrieved_at, sha256)
            VALUES ('s1', 215, '衆議院', '財務金融', '2026-04-15', '山田',
                    '委員', '事業承継 制度の改正案について議論',
                    'https://kokkai.ndl.go.jp/s1',
                    '2026-04-16T00:00:00Z',
                    'aa' || hex(randomblob(31)))
            """
        )
        conn.execute(
            """
            INSERT INTO shingikai_minutes
                (id, ministry, council, date, agenda, body_text,
                 pdf_url, retrieved_at, sha256)
            VALUES ('m1', '財務省', '税制調査会', '2026-04-20',
                    '事業承継税制 見直し',
                    '事業承継 における税制特例の対象範囲を議論。',
                    'https://example.go.jp/m1.pdf',
                    '2026-04-21T00:00:00Z',
                    'bb' || hex(randomblob(31)))
            """
        )
        conn.execute(
            """
            INSERT INTO pubcomment_announcement
                (id, ministry, target_law, announcement_date,
                 comment_deadline, summary_text, full_text_url,
                 retrieved_at, sha256, jpcite_relevant)
            VALUES ('p1', '中小企業庁', '事業承継・引継ぎ補助金 取扱要領',
                    '2026-04-25', '2099-12-31',
                    '事業承継 関連の取扱要領 改正案。', 'https://example.go.jp/p1',
                    '2026-04-26T00:00:00Z',
                    'cc' || hex(randomblob(31)), 1)
            """
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1. policy_upstream_watch — envelope contract.
# ---------------------------------------------------------------------------


def test_watch_envelope_contract(tmp_path, monkeypatch) -> None:
    """Happy path: returns canonical envelope with all 5 axes per keyword."""
    db_path = tmp_path / "test_autonomath.db"
    _seed_db(db_path)

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("AUTONOMATH_POLICY_UPSTREAM_ENABLED", "1")
    from jpintel_mcp.mcp.autonomath_tools import db as _db_mod

    _db_mod.close_all()
    _db_mod.AUTONOMATH_DB_PATH = db_path  # type: ignore[assignment]

    from jpintel_mcp.mcp.autonomath_tools.policy_upstream_tools import (
        _policy_upstream_watch_impl,
    )

    res = _policy_upstream_watch_impl(
        keywords=["事業承継", "存在しない_keyword_xyz"],
        watch_period_days=180,
    )
    assert "results" in res
    assert "_disclaimer" in res
    assert "_next_calls" in res
    assert "corpus_snapshot_id" in res
    assert "corpus_checksum" in res
    assert res["_billing_unit"] == 1
    assert res["watch_period_days"] == 180
    assert res["total"] == 2
    # Sort: 事業承継 (3 hits) > 存在しない_xyz (0 hits)
    assert res["results"][0]["keyword"] == "事業承継"
    first = res["results"][0]
    assert first["kokkai"]["count"] >= 1
    assert first["shingikai"]["count"] >= 1
    assert first["pubcomment"]["recent_total"] >= 1
    assert first["pubcomment"]["ongoing"] >= 1
    assert first["signal_strength"] >= 3
    # Empty axis still returns a structured rollup, not None.
    second = res["results"][1]
    assert second["signal_strength"] == 0
    assert second["kokkai"]["count"] == 0
    assert "lead_time_horizon_months" not in second  # keyword-level, not event-level


# ---------------------------------------------------------------------------
# 2. policy_upstream_watch — input validation.
# ---------------------------------------------------------------------------


def test_watch_input_validation(tmp_path, monkeypatch) -> None:
    """Rejects empty list / non-string entries / clamps watch_period_days."""
    db_path = tmp_path / "test_autonomath.db"
    _seed_db(db_path)
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.mcp.autonomath_tools import db as _db_mod

    _db_mod.close_all()
    _db_mod.AUTONOMATH_DB_PATH = db_path  # type: ignore[assignment]
    from jpintel_mcp.mcp.autonomath_tools.policy_upstream_tools import (
        _policy_upstream_watch_impl,
    )

    # Empty list -> error envelope.
    err = _policy_upstream_watch_impl(keywords=[])
    assert err.get("error", {}).get("code") == "missing_required_arg"

    # Non-list -> error envelope.
    err2 = _policy_upstream_watch_impl(keywords="事業承継")  # type: ignore[arg-type]
    assert err2.get("error", {}).get("code") == "missing_required_arg"

    # All-blank list -> error envelope.
    err3 = _policy_upstream_watch_impl(keywords=["", "  ", None])  # type: ignore[list-item]
    assert err3.get("error", {}).get("code") == "missing_required_arg"

    # Clamp at upper bound (365).
    res = _policy_upstream_watch_impl(keywords=["事業承継"], watch_period_days=99999)
    assert res["watch_period_days"] == 365
    # Clamp at lower bound (1).
    res2 = _policy_upstream_watch_impl(keywords=["事業承継"], watch_period_days=0)
    assert res2["watch_period_days"] == 1
    # Dedup + cap at 20 entries.
    many = ["kw"] * 30
    res3 = _policy_upstream_watch_impl(keywords=many)
    assert res3["total"] == 1


# ---------------------------------------------------------------------------
# 3. policy_upstream_timeline — envelope contract.
# ---------------------------------------------------------------------------


def test_timeline_envelope_contract(tmp_path, monkeypatch) -> None:
    """Happy path: chronological merge across all 5 stages, ASC by date."""
    db_path = tmp_path / "test_autonomath.db"
    _seed_db(db_path)
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.mcp.autonomath_tools import db as _db_mod

    _db_mod.close_all()
    _db_mod.AUTONOMATH_DB_PATH = db_path  # type: ignore[assignment]
    from jpintel_mcp.mcp.autonomath_tools.policy_upstream_tools import (
        _policy_upstream_timeline_impl,
    )

    res = _policy_upstream_timeline_impl(topic="事業承継", limit=50)
    assert "results" in res
    assert "_disclaimer" in res
    assert "_next_calls" in res
    assert "stage_counts" in res
    assert res["_billing_unit"] == 1
    assert res["limit"] == 50
    # All 3 seeded stages present.
    sc = res["stage_counts"]
    assert sc["kokkai"] >= 1
    assert sc["shingikai"] >= 1
    assert sc["pubcomment"] >= 1
    # ASC order by date.
    dates = [ev.get("date") for ev in res["results"] if ev.get("date")]
    assert dates == sorted(dates), f"events not in ASC order: {dates}"
    # Each event has a `stage` literal among the 5 known.
    allowed_stages = {
        "kokkai",
        "shingikai",
        "pubcomment",
        "law_amendment",
        "program_launch",
    }
    for ev in res["results"]:
        assert ev["stage"] in allowed_stages
    # Pubcomment row carries comment_deadline + is_ongoing.
    pc_events = [ev for ev in res["results"] if ev["stage"] == "pubcomment"]
    assert pc_events
    assert pc_events[0]["is_ongoing"] is True
    assert pc_events[0]["comment_deadline"] == "2099-12-31"


# ---------------------------------------------------------------------------
# 4. policy_upstream_timeline — input validation.
# ---------------------------------------------------------------------------


def test_timeline_input_validation(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "test_autonomath.db"
    _seed_db(db_path)
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.mcp.autonomath_tools import db as _db_mod

    _db_mod.close_all()
    _db_mod.AUTONOMATH_DB_PATH = db_path  # type: ignore[assignment]
    from jpintel_mcp.mcp.autonomath_tools.policy_upstream_tools import (
        _policy_upstream_timeline_impl,
    )

    err = _policy_upstream_timeline_impl(topic="")
    assert err.get("error", {}).get("code") == "missing_required_arg"
    err2 = _policy_upstream_timeline_impl(topic="   ")
    assert err2.get("error", {}).get("code") == "missing_required_arg"
    # Clamp upper.
    res = _policy_upstream_timeline_impl(topic="事業承継", limit=9999)
    assert res["limit"] == 200
    # Clamp lower.
    res2 = _policy_upstream_timeline_impl(topic="事業承継", limit=0)
    assert res2["limit"] == 1


# ---------------------------------------------------------------------------
# 5. LLM-0 guard.
# ---------------------------------------------------------------------------


_FORBIDDEN_LLM_HEADS = {"anthropic", "openai", "claude_agent_sdk"}


def _has_forbidden_imports(py_path: Path) -> list[str]:
    src = py_path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                head = alias.name.split(".")[0]
                if head in _FORBIDDEN_LLM_HEADS:
                    hits.append(alias.name)
                if alias.name.startswith("google.generativeai"):
                    hits.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            head = node.module.split(".")[0]
            if head in _FORBIDDEN_LLM_HEADS:
                hits.append(node.module)
            if node.module.startswith("google.generativeai"):
                hits.append(node.module)
    return hits


def test_no_llm_imports_in_deep46_files() -> None:
    """DEEP-46 files must not import LLM SDKs."""
    for t in (_TOOL_MODULE, _REST_MODULE):
        hits = _has_forbidden_imports(t)
        assert not hits, f"{t.name}: forbidden LLM imports {hits}"


# ---------------------------------------------------------------------------
# 6. REST router wired in main.py — string scan (no app boot).
# ---------------------------------------------------------------------------


def test_router_mounted_in_main() -> None:
    """policy_upstream_router must be imported and included in api.main."""
    src = _MAIN_MODULE.read_text(encoding="utf-8")
    assert "policy_upstream_router" in src, (
        "policy_upstream_router import or include missing from api/main.py"
    )
    # Verify both the import line and the include call are present.
    assert "from jpintel_mcp.api.policy_upstream import" in src
    assert "app.include_router(policy_upstream_router" in src


# ---------------------------------------------------------------------------
# 7. Sanity check that the REST module can be imported without DB present.
# ---------------------------------------------------------------------------


def test_rest_module_imports_clean(tmp_path, monkeypatch) -> None:
    """Importing api.policy_upstream alone must not require a live DB."""
    # Point AUTONOMATH_DB_PATH at a non-existent file; import must still succeed,
    # only first call to the impl would surface a db_unavailable envelope.
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(tmp_path / "missing.db"))
    import importlib

    import jpintel_mcp.api.policy_upstream as mod

    importlib.reload(mod)
    assert hasattr(mod, "router")
    assert mod.router.prefix == "/v1/policy_upstream"


# ---------------------------------------------------------------------------
# 8. db_unavailable envelope when autonomath.db missing.
# ---------------------------------------------------------------------------


def test_db_unavailable_envelope(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(tmp_path / "no_such.db"))
    from jpintel_mcp.mcp.autonomath_tools import db as _db_mod

    _db_mod.close_all()
    _db_mod.AUTONOMATH_DB_PATH = tmp_path / "no_such.db"  # type: ignore[assignment]
    from jpintel_mcp.mcp.autonomath_tools.policy_upstream_tools import (
        _policy_upstream_timeline_impl,
        _policy_upstream_watch_impl,
    )

    res1 = _policy_upstream_watch_impl(keywords=["事業承継"])
    assert res1.get("error", {}).get("code") == "db_unavailable"
    res2 = _policy_upstream_timeline_impl(topic="事業承継")
    assert res2.get("error", {}).get("code") == "db_unavailable"


# Re-set the cached module path so the rest of the test session sees the
# default DB resolution after the missing-file probe.
@pytest.fixture(autouse=True)
def _reset_db_module_after_each():
    yield
    from jpintel_mcp.mcp.autonomath_tools import db as _db_mod

    _db_mod.close_all()
