"""§S1 audit_seal HMAC rotation regression tests (MASTER_PLAN_v1 章 2).

What we pin
-----------
1. A seal generated with secret_v1 (single-key path) continues to verify
   to True after the operator rotates the env var to a JSON array
   containing both v1 and v2. This is the core dual-key invariant: a
   customer presenting a "stale" seal is never told it is invalid just
   because we rotated the active key.

2. After rotation, fresh seals carry key_version = 2 (the new active
   key) and verify against the v2 secret only. This pins that we
   actually moved the active key, not just appended one.

Test isolation
--------------
We import ``_audit_seal`` directly and exercise the pure ``sign`` /
``verify`` API (plus the legacy ``verify_hmac`` 4-field path) so the
test does not depend on any FastAPI / SQLite fixture. The env var is
manipulated with ``monkeypatch`` so the change is scoped to the test.

Importantly, we DO want ``_load_keys()`` to re-read ``os.environ`` on
every call (the production code does — see ``_load_keys`` in
``_audit_seal.py``) so a single rotation is reflected immediately.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def fresh_audit_seal_module(monkeypatch):
    """Return ``_audit_seal`` with the env var cleared so the legacy
    single-secret path is the starting state.

    The rotation tests then ``monkeypatch.setenv`` to install a
    multi-key JSON array and re-call ``_load_keys`` indirectly through
    ``sign`` / ``verify``.
    """
    monkeypatch.delenv("JPINTEL_AUDIT_SEAL_KEYS", raising=False)
    monkeypatch.setenv("AUDIT_SEAL_SECRET", "secret_v1")
    # Force a fresh import so ``settings.audit_seal_secret`` picks up
    # the monkeypatched env var. ``conftest.py`` already pre-imports
    # jpintel_mcp; we override the relevant attribute below.
    from jpintel_mcp import config

    monkeypatch.setattr(config.settings, "audit_seal_secret", "secret_v1")
    from jpintel_mcp.api import _audit_seal as mod

    return mod


def test_old_seal_verifies_after_rotation(fresh_audit_seal_module, monkeypatch):
    """Core regression: a v1 seal still verifies after v2 is added."""
    mod = fresh_audit_seal_module

    # 1. Sign with secret_v1 (legacy single-key path).
    payload = b"the-canonical-payload-bytes"
    seal_v1 = mod.sign(payload)
    assert seal_v1["key_version"] == 1, seal_v1
    assert seal_v1["alg"] == "HMAC-SHA256"
    sig_v1 = seal_v1["sig"]
    assert isinstance(sig_v1, str) and len(sig_v1) == 64  # sha256 hex

    # 2. Operator rotates: JPINTEL_AUDIT_SEAL_KEYS now carries v1 + v2.
    new_keys = [
        {"v": 1, "s": "secret_v1", "retired_at": "2026-05-04T00:00:00+00:00"},
        {"v": 2, "s": "secret_v2_post_rotation", "retired_at": None},
    ]
    monkeypatch.setenv("JPINTEL_AUDIT_SEAL_KEYS", json.dumps(new_keys))

    # 3. The v1 seal MUST still verify — this is the customer guarantee.
    assert mod.verify(payload, seal_v1) is True

    # 4. New seals now use v2.
    seal_v2 = mod.sign(payload)
    assert seal_v2["key_version"] == 2, seal_v2
    assert seal_v2["sig"] != sig_v1  # different key → different signature

    # 5. The v2 seal also verifies.
    assert mod.verify(payload, seal_v2) is True

    # 6. A tampered seal (wrong sig) verifies to False on both keys.
    bad = dict(seal_v1)
    bad["sig"] = "0" * 64
    assert mod.verify(payload, bad) is False


def test_legacy_4field_verify_after_rotation(fresh_audit_seal_module, monkeypatch):
    """The legacy ``verify_hmac`` (4-field) API also walks all keys."""
    mod = fresh_audit_seal_module

    call_id = "01HW2J3000000000000000000A"
    ts = "2026-05-04T12:34:56+00:00"
    query_hash = "q" * 64
    response_hash = "r" * 64
    sig_v1 = mod.compute_hmac(call_id, ts, query_hash, response_hash)

    # Rotate.
    new_keys = [
        {"v": 1, "s": "secret_v1", "retired_at": "2026-05-04T00:00:00+00:00"},
        {"v": 2, "s": "secret_v2_post_rotation", "retired_at": None},
    ]
    monkeypatch.setenv("JPINTEL_AUDIT_SEAL_KEYS", json.dumps(new_keys))

    # Legacy verify (no key_version arg) must still succeed.
    assert mod.verify_hmac(call_id, ts, query_hash, response_hash, sig_v1) is True

    # Compute a v2 sig directly and verify it round-trips too.
    sig_v2 = mod.compute_hmac(call_id, ts, query_hash, response_hash, key_version=2)
    assert sig_v2 != sig_v1
    assert mod.verify_hmac(call_id, ts, query_hash, response_hash, sig_v2, key_version=2) is True


def test_malformed_env_falls_back_to_legacy(fresh_audit_seal_module, monkeypatch):
    """Unparseable JPINTEL_AUDIT_SEAL_KEYS must not break sign/verify."""
    mod = fresh_audit_seal_module
    monkeypatch.setenv("JPINTEL_AUDIT_SEAL_KEYS", "{not valid json")
    payload = b"abc"
    seal = mod.sign(payload)
    # Falls back to legacy single key v=1 keyed on settings.audit_seal_secret.
    assert seal["key_version"] == 1
    assert mod.verify(payload, seal) is True
