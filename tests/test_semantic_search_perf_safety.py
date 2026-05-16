"""Focused performance-safety checks for semantic search endpoints."""

from __future__ import annotations

import json
import pathlib
import sqlite3
import sys
import time
import types

import pytest

_REPO_SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
if str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))


def _paid_cap_conn(*, key_hash: str, cap_yen: int) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE api_keys ("
        "key_hash TEXT PRIMARY KEY, tier TEXT, monthly_cap_yen INTEGER, "
        "id INTEGER, parent_key_id INTEGER, revoked_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE usage_events ("
        "key_hash TEXT, ts TEXT, metered INTEGER, status INTEGER, quantity INTEGER)"
    )
    conn.execute(
        "INSERT INTO api_keys "
        "(key_hash, tier, monthly_cap_yen, id, parent_key_id, revoked_at) "
        "VALUES (?, 'paid', ?, 1, NULL, NULL)",
        (key_hash, cap_yen),
    )
    return conn


@pytest.fixture(autouse=True)
def _clear_semantic_search_v2_model_state():
    def clear() -> None:
        mod = sys.modules.get("jpintel_mcp.api.semantic_search_v2")
        if mod is not None:
            mod._E5_MODEL_CACHE.clear()
            mod._RERANKER_MODEL_CACHE.clear()
            mod._MODEL_CIRCUIT_OPEN_UNTIL.clear()

    clear()
    yield
    clear()


def test_legacy_vec_table_probe_uses_limit_not_count() -> None:
    from jpintel_mcp.api.semantic_search import _vec_table_has_rows

    class FakeConn:
        def __init__(self) -> None:
            self.sql: list[str] = []

        def execute(self, sql: str, params: tuple[str, ...] = ()):
            self.sql.append(sql)
            return self

        def fetchone(self):
            return ("ok",)

    conn = FakeConn()
    assert _vec_table_has_rows(conn, "am_canonical_vec_program") is True  # type: ignore[arg-type]
    joined = "\n".join(conn.sql).upper()
    assert "COUNT(*)" not in joined
    assert "LIMIT 1" in joined


def test_semantic_search_v2_caches_local_models(monkeypatch) -> None:
    import jpintel_mcp.api.semantic_search_v2 as mod

    calls = {"st": 0, "ce": 0}

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, **kwargs: object) -> None:
            calls["st"] += 1
            self.model_name = model_name

        def encode(self, text: str, normalize_embeddings: bool = False):
            return [0.0] * mod.EXPECTED_EMBEDDING_DIM

    class FakeCrossEncoder:
        def __init__(self, model_name: str, **kwargs: object) -> None:
            calls["ce"] += 1
            self.model_name = model_name

        def predict(self, pairs):
            return [0.5] * len(pairs)

    fake_module = types.SimpleNamespace(
        SentenceTransformer=FakeSentenceTransformer,
        CrossEncoder=FakeCrossEncoder,
    )
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("SENTENCE_TRANSFORMERS_HOME", raising=False)

    mod._E5_MODEL_CACHE.clear()
    mod._RERANKER_MODEL_CACHE.clear()
    mod._MODEL_CIRCUIT_OPEN_UNTIL.clear()

    assert mod._encode_query_e5("補助金") == [0.0] * mod.EXPECTED_EMBEDDING_DIM
    assert mod._encode_query_e5("税制") == [0.0] * mod.EXPECTED_EMBEDDING_DIM
    assert calls["st"] == 1

    candidates = [{"primary_name": "A"}, {"primary_name": "B"}]
    assert mod._rerank_pairs("query", candidates) == [0.5, 0.5]
    assert mod._rerank_pairs("query", candidates) == [0.5, 0.5]
    assert calls["ce"] == 1


def test_semantic_search_v2_projected_cap_rejects_before_db_or_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jpintel_mcp.api.semantic_search_v2 as mod
    from jpintel_mcp.api.deps import ApiContext

    calls = {"open": 0, "fts": 0, "encode": 0, "rerank": 0}

    def forbidden_open():
        calls["open"] += 1
        raise AssertionError("autonomath DB must not open near cap")

    def forbidden_fts(*_args: object, **_kwargs: object):
        calls["fts"] += 1
        raise AssertionError("FTS work must not start near cap")

    def forbidden_encode(*_args: object, **_kwargs: object):
        calls["encode"] += 1
        raise AssertionError("embedding model must not start near cap")

    def forbidden_rerank(*_args: object, **_kwargs: object):
        calls["rerank"] += 1
        raise AssertionError("reranker model must not start near cap")

    monkeypatch.setattr(mod, "_open_autonomath_ro", forbidden_open)
    monkeypatch.setattr(mod, "_fts5_search", forbidden_fts)
    monkeypatch.setattr(mod, "_encode_query_e5", forbidden_encode)
    monkeypatch.setattr(mod, "_rerank_pairs", forbidden_rerank)

    key_hash = "kh-semantic-cap"
    conn = _paid_cap_conn(key_hash=key_hash, cap_yen=3)
    ctx = ApiContext(
        key_hash=key_hash,
        tier="paid",
        customer_id="cus_test",
        stripe_subscription_id="sub_test",
    )

    response = mod.search_semantic(
        conn,
        ctx,
        mod.SemanticSearchV2Body(query="補助金", rerank=True),
    )

    assert response.status_code == 503
    err = json.loads(response.body)["error"]
    assert err["projected_units"] == 2
    assert err["projected_yen"] == 6
    assert calls == {"open": 0, "fts": 0, "encode": 0, "rerank": 0}


def test_semantic_search_v2_record_kind_filter_is_bounded() -> None:
    from jpintel_mcp.api.semantic_search_v2 import (
        MAX_RECORD_KIND_FILTERS,
        SemanticSearchV2Body,
    )

    with pytest.raises(ValueError):
        SemanticSearchV2Body(
            query="補助金",
            record_kinds=[f"kind{i}" for i in range(MAX_RECORD_KIND_FILTERS + 1)],
        )


def test_semantic_search_v2_sqlite_interrupt_raises_timeout() -> None:
    from jpintel_mcp.api.semantic_search_v2 import (
        SemanticSearchTimeoutError,
        _fts5_search,
        _vec_search,
    )

    class InterruptedConn:
        def execute(self, *args: object, **kwargs: object):
            raise sqlite3.OperationalError("interrupted")

    conn = InterruptedConn()
    with pytest.raises(SemanticSearchTimeoutError):
        _fts5_search(conn, "補助金", limit=10, kinds=None)  # type: ignore[arg-type]
    with pytest.raises(SemanticSearchTimeoutError):
        _vec_search(conn, [0.0] * 384, limit=10, kinds=None)  # type: ignore[arg-type]


def test_semantic_search_v2_non_timeout_operational_error_degrades() -> None:
    from jpintel_mcp.api.semantic_search_v2 import _fts5_search

    class MissingTableConn:
        def execute(self, *args: object, **kwargs: object):
            raise sqlite3.OperationalError("no such table: am_entities_fts")

    assert _fts5_search(MissingTableConn(), "補助金", limit=10, kinds=None) == []  # type: ignore[arg-type]


def test_semantic_search_v2_slow_encode_opens_circuit(monkeypatch) -> None:
    import jpintel_mcp.api.semantic_search_v2 as mod

    calls = {"encode": 0}

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, **kwargs: object) -> None:
            self.model_name = model_name

        def encode(self, text: str, normalize_embeddings: bool = False):
            calls["encode"] += 1
            time.sleep(0.02)
            return [0.0] * mod.EXPECTED_EMBEDDING_DIM

    fake_module = types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    deadline = time.perf_counter() + 0.005
    assert mod._encode_query_e5("補助金", deadline=deadline, min_remaining_ms=0) is None
    assert calls["encode"] == 1
    assert mod._model_circuit_open(mod.E5_MODEL) is True

    later_deadline = time.perf_counter() + 60.0
    assert mod._encode_query_e5("税制", deadline=later_deadline, min_remaining_ms=0) is None
    assert calls["encode"] == 1


def test_semantic_search_v2_rerank_low_budget_skips_model(monkeypatch) -> None:
    import jpintel_mcp.api.semantic_search_v2 as mod

    calls = {"ce": 0}

    class FakeCrossEncoder:
        def __init__(self, model_name: str, **kwargs: object) -> None:
            calls["ce"] += 1

        def predict(self, pairs):
            return [0.5] * len(pairs)

    fake_module = types.SimpleNamespace(CrossEncoder=FakeCrossEncoder)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    low_budget_deadline = time.perf_counter() + 0.05
    candidates = [{"primary_name": "A"}]
    assert mod._should_skip_rerank(low_budget_deadline) is True
    assert (
        mod._rerank_pairs(
            "query",
            candidates,
            deadline=low_budget_deadline,
            min_remaining_ms=1_000,
        )
        is None
    )
    assert calls["ce"] == 0


def test_semantic_search_v2_slow_rerank_opens_circuit(monkeypatch) -> None:
    import jpintel_mcp.api.semantic_search_v2 as mod

    calls = {"predict": 0}

    class FakeCrossEncoder:
        def __init__(self, model_name: str, **kwargs: object) -> None:
            self.model_name = model_name

        def predict(self, pairs):
            calls["predict"] += 1
            time.sleep(0.02)
            return [0.5] * len(pairs)

    fake_module = types.SimpleNamespace(CrossEncoder=FakeCrossEncoder)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    deadline = time.perf_counter() + 0.005
    candidates = [{"primary_name": "A"}]
    assert mod._rerank_pairs("query", candidates, deadline=deadline, min_remaining_ms=0) is None
    assert calls["predict"] == 1
    assert mod._model_circuit_open(mod.RERANKER_MODEL) is True

    later_deadline = time.perf_counter() + 60.0
    assert (
        mod._rerank_pairs(
            "query",
            candidates,
            deadline=later_deadline,
            min_remaining_ms=0,
        )
        is None
    )
    assert calls["predict"] == 1


def test_semantic_search_v2_vec_overfetches_restrictive_kinds_and_trims() -> None:
    from jpintel_mcp.api.semantic_search_v2 import EXPECTED_EMBEDDING_DIM, _vec_search

    class FakeConn:
        def __init__(self) -> None:
            self.params: tuple[object, ...] | None = None

        def execute(self, sql: str, params: tuple[object, ...]):
            self.params = params
            return self

        def fetchall(self):
            rows = []
            kinds = ["law", "law", "case_study", "program", "program", "program"]
            for idx, kind in enumerate(kinds, start=1):
                rows.append(
                    {
                        "rid": idx,
                        "l2": 0.01 * idx,
                        "cid": f"cid-{idx}",
                        "pn": f"name-{idx}",
                        "rk": kind,
                        "surl": f"https://example.test/{idx}",
                    }
                )
            return rows

    conn = FakeConn()
    results = _vec_search(conn, [0.0] * EXPECTED_EMBEDDING_DIM, limit=2, kinds=["program"])  # type: ignore[arg-type]

    assert conn.params is not None
    assert conn.params[1] > 2
    assert [r["record_kind"] for r in results] == ["program", "program"]
    assert len(results) == 2


def test_semantic_search_v2_vec_fetch_limit_capped_at_max_window() -> None:
    """Overfetch is capped at MAX_VECTOR_FETCH_WINDOW even for huge
    base limits + restrictive kinds. Guards against unbounded vec scan.
    """
    from jpintel_mcp.api.semantic_search_v2 import (
        MAX_VECTOR_FETCH_WINDOW,
        VECTOR_KIND_OVERFETCH_MULTIPLIER,
        _vec_fetch_limit,
    )

    # No kinds filter → pass-through (no overfetch).
    assert _vec_fetch_limit(10, None) == 10

    # With kinds filter → overfetch up to multiplier, capped at window.
    small = _vec_fetch_limit(5, ["program"])
    assert small == 5 * VECTOR_KIND_OVERFETCH_MULTIPLIER
    assert small <= MAX_VECTOR_FETCH_WINDOW

    # Huge base × multiplier must not exceed cap when cap is binding.
    huge = _vec_fetch_limit(1000, ["program"])
    assert huge <= max(1000, MAX_VECTOR_FETCH_WINDOW)


def test_semantic_search_v2_encode_unknown_exception_opens_circuit(monkeypatch) -> None:
    """Defensive catch-all: any unexpected model exception must open
    the circuit, not crash the request.
    """
    import jpintel_mcp.api.semantic_search_v2 as mod

    class _BoomError(Exception):
        """Brand-new exception not in the known (ImportError/OSError/
        RuntimeError/ValueError) tuple."""

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, **kwargs: object) -> None:
            self.model_name = model_name

        def encode(self, text: str, normalize_embeddings: bool = False):
            raise _BoomError("unexpected torch fault")

    fake_module = types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    assert mod._encode_query_e5("補助金") is None
    assert mod._model_circuit_open(mod.E5_MODEL) is True


def test_semantic_search_v2_rerank_unknown_exception_opens_circuit(monkeypatch) -> None:
    """Defensive catch-all: cross-encoder unexpected fault must open
    the circuit and keep the RRF order.
    """
    import jpintel_mcp.api.semantic_search_v2 as mod

    class _BoomError(Exception):
        """Brand-new exception not in the known tuple."""

    class FakeCrossEncoder:
        def __init__(self, model_name: str, **kwargs: object) -> None:
            self.model_name = model_name

        def predict(self, pairs):
            raise _BoomError("unexpected reranker fault")

    fake_module = types.SimpleNamespace(CrossEncoder=FakeCrossEncoder)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    candidates = [{"primary_name": "A"}]
    assert mod._rerank_pairs("query", candidates) is None
    assert mod._model_circuit_open(mod.RERANKER_MODEL) is True


def test_semantic_search_v2_residual_p1_documented_in_source() -> None:
    """Packet A9 residual P1: local model inference cannot be hard-
    aborted after it starts. Must be documented in code comments so
    future readers know not to claim a true cancellation guarantee.
    """
    import jpintel_mcp.api.semantic_search_v2 as mod

    src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
    # Module docstring must call out the residual P1.
    assert "Residual P1" in src
    assert "cannot be hard-aborted" in src
    # Each model-call helper must inline-comment the caveat so an
    # in-place reader of `_encode_query_e5` or `_rerank_pairs` sees it
    # without scrolling to the module docstring.
    encode_idx = src.index("def _encode_query_e5")
    encode_block = src[encode_idx : encode_idx + 2000]
    assert "Residual P1" in encode_block
    rerank_idx = src.index("def _rerank_pairs")
    rerank_block = src[rerank_idx : rerank_idx + 2000]
    assert "Residual P1" in rerank_block


def test_semantic_search_v2_sqlite_deadline_helper_installs_progress_handler() -> None:
    """Bounded query time guard: `_set_sqlite_deadline` installs a
    progress handler that interrupts after the timeout fires. We
    verify the handler returns non-zero past the deadline (the
    sqlite3 driver translates non-zero into an `interrupted` raise).
    """
    import jpintel_mcp.api.semantic_search_v2 as mod

    handlers: list[object] = []

    class FakeConn:
        def set_progress_handler(self, fn, n_ops):
            handlers.append((fn, n_ops))

    conn = FakeConn()
    mod._set_sqlite_deadline(conn, timeout_ms=1)  # type: ignore[arg-type]
    assert handlers, "progress handler must be installed"
    fn, n_ops = handlers[-1]  # type: ignore[misc]
    assert n_ops == mod.SQLITE_PROGRESS_OPS
    # Past the deadline (1ms timeout + a small sleep) the progress
    # callback must return non-zero so SQLite raises `interrupted`.
    time.sleep(0.005)
    assert fn() == 1  # type: ignore[operator]


def test_semantic_search_v2_circuit_open_blocks_subsequent_encode(monkeypatch) -> None:
    """Stale model circuit: once the circuit opens, subsequent
    `_encode_query_e5` calls must short-circuit without re-invoking
    the loader, until the cooldown elapses.
    """
    import jpintel_mcp.api.semantic_search_v2 as mod

    calls = {"init": 0, "encode": 0}

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, **kwargs: object) -> None:
            calls["init"] += 1

        def encode(self, text: str, normalize_embeddings: bool = False):
            calls["encode"] += 1
            return [0.0] * mod.EXPECTED_EMBEDDING_DIM

    fake_module = types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    # Open the circuit manually.
    mod._open_model_circuit(mod.E5_MODEL)
    assert mod._model_circuit_open(mod.E5_MODEL) is True

    # All calls while circuit is open return None without loading the
    # model.
    assert mod._encode_query_e5("a") is None
    assert mod._encode_query_e5("b") is None
    assert calls["init"] == 0
    assert calls["encode"] == 0


# ----------------------------------------------------------------------
# R3 P1-5: cross-encoder cold-load timeout + warmup helper.
# ----------------------------------------------------------------------


def test_reranker_cold_load_timeout_constant_default() -> None:
    """R3 P1-5: the cold-load timeout constant must be present and
    default to 2000 ms so a slow cross-encoder load cannot hold the
    request thread indefinitely.
    """
    import jpintel_mcp.api.semantic_search_v2 as mod

    assert hasattr(mod, "RERANKER_COLD_LOAD_TIMEOUT_MS")
    assert mod.RERANKER_COLD_LOAD_TIMEOUT_MS == 2000


def test_reranker_cold_load_timeout_opens_circuit(monkeypatch) -> None:
    """R3 P1-5: when `_get_reranker_model` cold-loads slower than
    RERANKER_COLD_LOAD_TIMEOUT_MS, the function must (a) return None,
    (b) open the reranker circuit, and (c) NOT cache the slow model so
    a future cooldown-reset call can retry.
    """
    import jpintel_mcp.api.semantic_search_v2 as mod

    # Shrink the budget so we don't actually sleep 2.5s in the test.
    monkeypatch.setattr(mod, "RERANKER_COLD_LOAD_TIMEOUT_MS", 5, raising=True)

    calls = {"init": 0}

    class SlowCrossEncoder:
        def __init__(self, model_name: str, **kwargs: object) -> None:
            calls["init"] += 1
            # Simulate the 2500 ms cold-load described in R3 P1-5 by
            # sleeping longer than the (shrunk) budget.
            time.sleep(0.05)

        def predict(self, pairs):
            return [0.5] * len(pairs)

    fake_module = types.SimpleNamespace(CrossEncoder=SlowCrossEncoder)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("SENTENCE_TRANSFORMERS_HOME", raising=False)

    mod._RERANKER_MODEL_CACHE.clear()
    mod._MODEL_CIRCUIT_OPEN_UNTIL.clear()

    result = mod._get_reranker_model()
    assert result is None
    assert calls["init"] == 1
    assert mod._model_circuit_open(mod.RERANKER_MODEL) is True
    # Slow model must NOT be cached — we want the cooldown to gate
    # retries via the circuit, not a permanent cache poison.
    assert (mod.RERANKER_MODEL, None) not in mod._RERANKER_MODEL_CACHE


def test_reranker_cold_load_fast_path_caches(monkeypatch) -> None:
    """R3 P1-5: warm / fast cold-load must still cache the model. We
    only refuse to cache when the load exceeded the budget.
    """
    import jpintel_mcp.api.semantic_search_v2 as mod

    monkeypatch.setattr(mod, "RERANKER_COLD_LOAD_TIMEOUT_MS", 5_000, raising=True)

    calls = {"init": 0}

    class FastCrossEncoder:
        def __init__(self, model_name: str, **kwargs: object) -> None:
            calls["init"] += 1

        def predict(self, pairs):
            return [0.5] * len(pairs)

    fake_module = types.SimpleNamespace(CrossEncoder=FastCrossEncoder)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("SENTENCE_TRANSFORMERS_HOME", raising=False)

    mod._RERANKER_MODEL_CACHE.clear()
    mod._MODEL_CIRCUIT_OPEN_UNTIL.clear()

    first = mod._get_reranker_model()
    second = mod._get_reranker_model()
    assert first is not None
    assert first is second
    assert calls["init"] == 1
    assert mod._model_circuit_open(mod.RERANKER_MODEL) is False


def test_reranker_cold_load_timeout_falls_back_to_vector_only(monkeypatch) -> None:
    """R3 P1-5: with the cold-load timeout tripped, `_rerank_pairs`
    must return None so the caller keeps the RRF (vector + FTS5) order.
    This is the user-facing fallback: response stays valid, reranker
    is skipped silently.
    """
    import jpintel_mcp.api.semantic_search_v2 as mod

    monkeypatch.setattr(mod, "RERANKER_COLD_LOAD_TIMEOUT_MS", 5, raising=True)

    class SlowCrossEncoder:
        def __init__(self, model_name: str, **kwargs: object) -> None:
            time.sleep(0.05)

        def predict(self, pairs):  # pragma: no cover - never reached
            return [0.9] * len(pairs)

    fake_module = types.SimpleNamespace(CrossEncoder=SlowCrossEncoder)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("SENTENCE_TRANSFORMERS_HOME", raising=False)

    mod._RERANKER_MODEL_CACHE.clear()
    mod._MODEL_CIRCUIT_OPEN_UNTIL.clear()

    candidates = [
        {"primary_name": "中小企業補助金", "rid": 1, "rrf_score": 0.9},
        {"primary_name": "ものづくり補助金", "rid": 2, "rrf_score": 0.8},
    ]
    # First call cold-loads → exceeds budget → circuit opens → returns None.
    assert mod._rerank_pairs("補助金", candidates) is None
    assert mod._model_circuit_open(mod.RERANKER_MODEL) is True

    # Second call short-circuits via the open circuit; still None, no
    # loader re-entry. This is the production fallback path: the
    # endpoint will see `reranker_state` flip to "unavailable" /
    # "timeout_skipped" and serve RRF-only results.
    assert mod._rerank_pairs("税制", candidates) is None


def test_warmup_semantic_reranker_smoke(monkeypatch, tmp_path) -> None:
    """R3 P1-5: the warmup script must be importable + runnable. We
    monkeypatch sentence_transformers to a tiny fake so the test does
    not require the real ~80 MB model to be on disk. The script must
    exit 0 (best-effort warmup).
    """
    import importlib.util

    script_path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "scripts"
        / "ops"
        / "warmup_semantic_reranker.py"
    )
    assert script_path.exists(), (
        "warmup script must exist at scripts/ops/warmup_semantic_reranker.py"
    )

    predict_calls: list[object] = []

    class FakeCrossEncoder:
        def __init__(self, model_name: str, **kwargs: object) -> None:
            self.model_name = model_name

        def predict(self, pairs):
            predict_calls.append(pairs)
            return [0.5] * len(pairs)

    fake_module = types.SimpleNamespace(CrossEncoder=FakeCrossEncoder)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("SENTENCE_TRANSFORMERS_HOME", raising=False)

    spec = importlib.util.spec_from_file_location(
        "warmup_semantic_reranker_under_test", script_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert hasattr(module, "warmup")
    assert hasattr(module, "main")

    # Run the warmup; must succeed and call .predict at least once with
    # the documented dummy ("warmup", "warmup") pair.
    from jpintel_mcp.api import semantic_search_v2 as ssv2

    ssv2._RERANKER_MODEL_CACHE.clear()
    ssv2._MODEL_CIRCUIT_OPEN_UNTIL[ssv2.RERANKER_MODEL] = 999999999.0
    rc = module.warmup()
    assert rc == 0
    assert predict_calls, "warmup must run at least one dummy .predict()"
    first_pair = predict_calls[0]
    assert list(first_pair) == [("warmup", "warmup")]
    cached = ssv2._RERANKER_MODEL_CACHE[(ssv2.RERANKER_MODEL, None)]
    assert isinstance(cached, FakeCrossEncoder)
    assert not ssv2._model_circuit_open(ssv2.RERANKER_MODEL)


def test_warmup_semantic_reranker_tolerates_missing_dep(monkeypatch) -> None:
    """R3 P1-5: warmup must NOT fail boot when sentence_transformers is
    unavailable — it logs and exits 0 so entrypoint.sh stays clean.
    """
    import importlib.util

    script_path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "scripts"
        / "ops"
        / "warmup_semantic_reranker.py"
    )

    # Force ImportError on `from sentence_transformers import CrossEncoder`.
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    spec = importlib.util.spec_from_file_location(
        "warmup_semantic_reranker_under_test_missing", script_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.warmup() == 0
