"""Wave 51 dim L — atomic test suite for ``jpintel_mcp.session_context``.

Covers:

    * SessionToken / SavedContext Pydantic validation (token format,
      created_at < expires_at, is_expired clock-skew handling).
    * SessionRegistry happy path: open → step (x N) → close.
    * 24h TTL enforcement: an expired token raises
      :class:`SessionExpiredError` and the on-disk row is deleted.
    * Close idempotency: second close on the same token raises
      :class:`SessionNotFoundError`.
    * Payload caps: oversize current_state / step payload / step
      count → :class:`SessionPayloadError`.
    * Module-level convenience wrappers route to a default registry.
    * Auxiliary surface: ``list_active_tokens`` / ``purge_expired``.

NO HTTP / NO FastAPI imports — the module is router-agnostic and
tests treat it as a pure library.
"""

from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from jpintel_mcp.session_context import (
    MAX_CONTEXT_BYTES,
    MAX_STEPS,
    SESSION_TTL_SEC,
    SavedContext,
    SessionExpiredError,
    SessionNotFoundError,
    SessionPayloadError,
    SessionRegistry,
    SessionToken,
    new_token_id,
)

_HEX32 = re.compile(r"^[0-9a-f]{32}$")


# ---------------------------------------------------------------------------
# Token / model shape
# ---------------------------------------------------------------------------


class TestNewTokenId:
    def test_new_token_id_returns_32_hex_chars(self) -> None:
        token = new_token_id()
        assert _HEX32.match(token), token

    def test_new_token_id_is_unique_per_call(self) -> None:
        # Two consecutive issues must never collide — secrets module
        # guarantees this but we still want a regression net.
        a = new_token_id()
        b = new_token_id()
        assert a != b


class TestSessionTokenModel:
    def test_valid_token_round_trips(self) -> None:
        now = time.time()
        tok = SessionToken(
            token_id="a" * 32,
            subject_id="agent-1",
            created_at=now,
            expires_at=now + SESSION_TTL_SEC,
        )
        # frozen=True — attribute access works, assignment does not.
        assert tok.token_id == "a" * 32
        with pytest.raises((TypeError, ValueError)):
            tok.token_id = "b" * 32  # type: ignore[misc]

    def test_invalid_token_format_rejected(self) -> None:
        now = time.time()
        with pytest.raises(ValueError):
            SessionToken(
                token_id="not-hex-32",
                subject_id="agent-1",
                created_at=now,
                expires_at=now + SESSION_TTL_SEC,
            )

    def test_token_is_expired_after_lapse(self) -> None:
        now = time.time()
        tok = SessionToken(
            token_id="0" * 32,
            subject_id="agent-1",
            created_at=now - SESSION_TTL_SEC - 10,
            expires_at=now - 1,
        )
        assert tok.is_expired() is True
        # Force-now lets tests be deterministic.
        assert tok.is_expired(now=now - 100) is False


class TestSavedContextModel:
    def test_valid_round_trip(self) -> None:
        now = time.time()
        ctx = SavedContext(
            token_id="b" * 32,
            subject_id="agent-1",
            created_at=now,
            expires_at=now + SESSION_TTL_SEC,
            current_state={"intent": "discover"},
            step_history=[],
        )
        assert ctx.steps_count() == 0
        assert ctx.current_state == {"intent": "discover"}

    def test_invalid_token_rejected(self) -> None:
        now = time.time()
        with pytest.raises(ValueError):
            SavedContext(
                token_id="not-hex",
                subject_id="agent-1",
                created_at=now,
                expires_at=now + SESSION_TTL_SEC,
            )


# ---------------------------------------------------------------------------
# SessionRegistry — happy path
# ---------------------------------------------------------------------------


@pytest.fixture
def registry(tmp_path: Path) -> SessionRegistry:
    return SessionRegistry(root=tmp_path / "sessions")


class TestOpenSession:
    def test_open_returns_valid_session_token(
        self, registry: SessionRegistry
    ) -> None:
        tok = registry.open_session(subject_id="agent-1")
        assert isinstance(tok, SessionToken)
        assert _HEX32.match(tok.token_id)
        assert tok.subject_id == "agent-1"
        # TTL must be exactly 24h.
        assert tok.expires_at - tok.created_at == pytest.approx(
            SESSION_TTL_SEC, abs=0.1
        )

    def test_open_persists_file(self, registry: SessionRegistry) -> None:
        tok = registry.open_session(
            subject_id="agent-1", current_state={"intent": "search"}
        )
        path = registry.root / f"{tok.token_id}.json"
        assert path.exists()
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["token_id"] == tok.token_id
        assert raw["current_state"] == {"intent": "search"}
        assert raw["step_history"] == []

    def test_open_rejects_empty_subject_id(
        self, registry: SessionRegistry
    ) -> None:
        with pytest.raises(SessionPayloadError) as excinfo:
            registry.open_session(subject_id="")
        assert excinfo.value.code == "invalid_subject_id"

    def test_open_rejects_oversize_current_state(
        self, registry: SessionRegistry
    ) -> None:
        big = {"x": "y" * (MAX_CONTEXT_BYTES + 100)}
        with pytest.raises(SessionPayloadError) as excinfo:
            registry.open_session(subject_id="agent-1", current_state=big)
        assert excinfo.value.code == "saved_context_too_large"


class TestStepSession:
    def test_single_step_appends_history(
        self, registry: SessionRegistry
    ) -> None:
        tok = registry.open_session(subject_id="agent-1")
        ctx = registry.step_session(
            tok.token_id, action="search", payload={"q": "hello"}
        )
        assert ctx.steps_count() == 1
        assert ctx.step_history[0]["action"] == "search"
        assert ctx.step_history[0]["data"] == {"q": "hello"}
        assert "at" in ctx.step_history[0]

    def test_multi_step_accumulates_in_order(
        self, registry: SessionRegistry
    ) -> None:
        tok = registry.open_session(subject_id="agent-1")
        for i in range(5):
            registry.step_session(
                tok.token_id, action=f"act-{i}", payload={"i": i}
            )
        ctx = registry.get_context(tok.token_id)
        assert ctx.steps_count() == 5
        actions = [e["action"] for e in ctx.step_history]
        assert actions == ["act-0", "act-1", "act-2", "act-3", "act-4"]

    def test_step_on_unknown_token_raises_not_found(
        self, registry: SessionRegistry
    ) -> None:
        with pytest.raises(SessionNotFoundError):
            registry.step_session("0" * 32, action="x", payload={})

    def test_step_rejects_empty_action(
        self, registry: SessionRegistry
    ) -> None:
        tok = registry.open_session(subject_id="agent-1")
        with pytest.raises(SessionPayloadError) as excinfo:
            registry.step_session(tok.token_id, action="", payload={})
        assert excinfo.value.code == "invalid_action"

    def test_step_rejects_oversize_payload(
        self, registry: SessionRegistry
    ) -> None:
        tok = registry.open_session(subject_id="agent-1")
        big = {"x": "y" * (MAX_CONTEXT_BYTES + 100)}
        with pytest.raises(SessionPayloadError) as excinfo:
            registry.step_session(tok.token_id, action="x", payload=big)
        assert excinfo.value.code == "step_payload_too_large"

    def test_step_cap_enforced(self, registry: SessionRegistry) -> None:
        tok = registry.open_session(subject_id="agent-1")
        for i in range(MAX_STEPS):
            registry.step_session(
                tok.token_id, action=f"act-{i}", payload={"i": i}
            )
        with pytest.raises(SessionPayloadError) as excinfo:
            registry.step_session(
                tok.token_id, action="overflow", payload={}
            )
        assert excinfo.value.code == "step_cap_exceeded"


class TestCloseSession:
    def test_close_returns_final_snapshot(
        self, registry: SessionRegistry
    ) -> None:
        tok = registry.open_session(
            subject_id="agent-1", current_state={"intent": "discover"}
        )
        registry.step_session(
            tok.token_id, action="search", payload={"q": "test"}
        )
        ctx = registry.close_session(tok.token_id)
        assert isinstance(ctx, SavedContext)
        assert ctx.steps_count() == 1
        assert ctx.current_state == {"intent": "discover"}

    def test_close_deletes_disk_file(
        self, registry: SessionRegistry
    ) -> None:
        tok = registry.open_session(subject_id="agent-1")
        path = registry.root / f"{tok.token_id}.json"
        assert path.exists()
        registry.close_session(tok.token_id)
        assert not path.exists()

    def test_close_idempotency_second_call_raises_not_found(
        self, registry: SessionRegistry
    ) -> None:
        # Second close must NOT silently succeed — the audit log needs
        # to distinguish "already closed" from "never opened".
        tok = registry.open_session(subject_id="agent-1")
        registry.close_session(tok.token_id)
        with pytest.raises(SessionNotFoundError):
            registry.close_session(tok.token_id)


# ---------------------------------------------------------------------------
# TTL expiry
# ---------------------------------------------------------------------------


class TestTTLExpiry:
    def _force_expire_on_disk(
        self, registry: SessionRegistry, token_id: str
    ) -> None:
        path = registry.root / f"{token_id}.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["expires_at"] = time.time() - 1
        path.write_text(
            json.dumps(raw, ensure_ascii=False), encoding="utf-8"
        )

    def test_expired_token_raises_expired_error(
        self, registry: SessionRegistry
    ) -> None:
        tok = registry.open_session(subject_id="agent-1")
        self._force_expire_on_disk(registry, tok.token_id)
        with pytest.raises(SessionExpiredError) as excinfo:
            registry.step_session(tok.token_id, action="x", payload={})
        assert excinfo.value.token_id == tok.token_id

    def test_expired_token_row_is_deleted(
        self, registry: SessionRegistry
    ) -> None:
        # After SessionExpiredError, the on-disk row must be gone so a
        # later subject re-using the same id never collides.
        tok = registry.open_session(subject_id="agent-1")
        path = registry.root / f"{tok.token_id}.json"
        self._force_expire_on_disk(registry, tok.token_id)
        with pytest.raises(SessionExpiredError):
            registry.step_session(tok.token_id, action="x", payload={})
        assert not path.exists()

    def test_get_context_on_expired_token_raises(
        self, registry: SessionRegistry
    ) -> None:
        tok = registry.open_session(subject_id="agent-1")
        self._force_expire_on_disk(registry, tok.token_id)
        with pytest.raises(SessionExpiredError):
            registry.get_context(tok.token_id)


# ---------------------------------------------------------------------------
# Auxiliary surface
# ---------------------------------------------------------------------------


class TestRegistryAuxiliary:
    def test_invalid_token_id_format_rejected(
        self, registry: SessionRegistry
    ) -> None:
        with pytest.raises(SessionPayloadError) as excinfo:
            registry.step_session(
                "../escape", action="x", payload={}
            )
        assert excinfo.value.code == "invalid_token_id"

    def test_list_active_tokens(
        self, registry: SessionRegistry
    ) -> None:
        t1 = registry.open_session(subject_id="agent-1")
        t2 = registry.open_session(subject_id="agent-2")
        active = registry.list_active_tokens()
        assert set(active) == {t1.token_id, t2.token_id}

    def test_list_active_tokens_excludes_expired(
        self, registry: SessionRegistry
    ) -> None:
        t1 = registry.open_session(subject_id="agent-1")
        t2 = registry.open_session(subject_id="agent-2")
        # Force t1 expired on disk.
        path = registry.root / f"{t1.token_id}.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["expires_at"] = time.time() - 1
        path.write_text(
            json.dumps(raw, ensure_ascii=False), encoding="utf-8"
        )
        active = registry.list_active_tokens()
        # t1 was purged as a side-effect of the failed load; only t2
        # survives.
        assert t2.token_id in active
        assert t1.token_id not in active

    def test_purge_expired_removes_lapsed_rows(
        self, registry: SessionRegistry
    ) -> None:
        t1 = registry.open_session(subject_id="agent-1")
        t2 = registry.open_session(subject_id="agent-2")
        # Force both expired.
        for token in (t1.token_id, t2.token_id):
            path = registry.root / f"{token}.json"
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["expires_at"] = time.time() - 1
            path.write_text(
                json.dumps(raw, ensure_ascii=False), encoding="utf-8"
            )
        purged = registry.purge_expired()
        assert purged == 2

    def test_purge_expired_keeps_live_rows(
        self, registry: SessionRegistry
    ) -> None:
        registry.open_session(subject_id="agent-1")
        purged = registry.purge_expired()
        assert purged == 0
        assert len(registry.list_active_tokens()) == 1

    def test_corrupt_row_treated_as_not_found(
        self, registry: SessionRegistry, tmp_path: Path
    ) -> None:
        # A row that fails JSON decode must NOT cascade into a 500 —
        # we surface SessionNotFoundError so the audit log can record
        # the corruption and the caller can open a fresh session.
        bogus = "f" * 32
        path = registry.root / f"{bogus}.json"
        path.write_text("not-json", encoding="utf-8")
        with pytest.raises(SessionNotFoundError):
            registry.get_context(bogus)


# ---------------------------------------------------------------------------
# Module-level convenience wrappers (default registry)
# ---------------------------------------------------------------------------


class TestModuleLevelWrappers:
    def test_open_step_close_via_module_functions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Re-point the default registry to a clean tmp_path so the
        # test doesn't pollute the repo-root state/ dir.
        from jpintel_mcp.session_context import registry as reg_mod

        monkeypatch.setattr(reg_mod, "_DEFAULT_REGISTRY", None)
        monkeypatch.setattr(
            reg_mod, "DEFAULT_REGISTRY_ROOT", tmp_path / "sessions"
        )
        from jpintel_mcp.session_context import (
            close_session,
            open_session,
            step_session,
        )

        tok = open_session(
            subject_id="agent-wrapper", current_state={"a": 1}
        )
        ctx = step_session(
            tok.token_id, action="ping", payload={"x": "y"}
        )
        assert ctx.steps_count() == 1
        terminal = close_session(tok.token_id)
        assert terminal.steps_count() == 1
        with pytest.raises(SessionNotFoundError):
            close_session(tok.token_id)
