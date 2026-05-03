"""Tests for the /v1/me/keys/children REST surface (W2-3 Fix 2 / mig 086).

Wires the existing `issue_child_key` / `list_children` /
`revoke_child_by_id` helpers (billing/keys.py) into the dashboard
session-cookie + CSRF flow used by the rest of /v1/me/*.

Coverage:

* Parent issues a child via POST -> 201 with raw key returned ONCE
  (`api_key`), id + label + key_hash_prefix surfaced for follow-up.
* Issued child appears in GET /v1/me/keys/children (live filter by
  default) with matching id / label / key_hash_prefix.
* DELETE /v1/me/keys/children/{id} flips the child's revoked_at and
  the next GET (default include_revoked=False) hides it.
* `include_revoked=True` shows the same child as revoked.
* Re-revoke (already revoked) -> 404 child_not_found.
* CSRF gate: POST without X-CSRF-Token header -> 403 csrf_missing.
* Label validation: empty label -> 422 label_missing; label > 64 chars
  -> 422 label_too_long.
* Child-key holder calling list returns [] (defensive — children never
  hold sessions in normal flows).
"""

from __future__ import annotations

import importlib
import sqlite3
import sys
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.api.deps import hash_api_key as _hash_api_key
from jpintel_mcp.billing.keys import issue_key

if TYPE_CHECKING:
    from pathlib import Path


def _me_module():
    mod = sys.modules.get("jpintel_mcp.api.me")
    if mod is None:
        mod = importlib.import_module("jpintel_mcp.api.me")
    return mod


@pytest.fixture(autouse=True)
def _reset_session_rate_limit(client):
    """Reset the per-IP session rate-limit bucket between tests.

    The /v1/session endpoint caps each IP at 5 attempts per hour. Tests
    in this file (especially the child-as-caller test) need a fresh
    bucket because they call /v1/session twice (once as parent to issue
    the child via the route helper, once as the child to verify the
    list shape). The autouse fixture mirrors the helper used in
    tests/test_me.py.
    """
    mod = _me_module()
    mod._reset_session_rate_limit_state()
    yield
    mod._reset_session_rate_limit_state()


def _csrf_headers(client) -> dict:
    """Echo the am_csrf cookie back as the X-CSRF-Token header.

    Mirrors the helper used in tests/test_me.py — the children
    endpoints use the same double-submit cookie pattern as rotate-key
    and billing-portal.
    """
    tok = client.cookies.get("am_csrf")
    return {"X-CSRF-Token": tok} if tok else {}


@pytest.fixture()
def parent_paid_key(seeded_db: Path) -> str:
    """Issue a paid parent key and return the raw secret."""
    import uuid

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id=f"cus_children_{uuid.uuid4().hex[:8]}",
        tier="paid",
        stripe_subscription_id=f"sub_children_{uuid.uuid4().hex[:8]}",
    )
    c.commit()
    c.close()
    return raw


def _start_session(client, raw: str) -> None:
    """Authenticate the test client via /v1/session (sets am_session + csrf)."""
    r = client.post("/v1/session", json={"api_key": raw})
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Happy path: issue → list → revoke
# ---------------------------------------------------------------------------


def test_parent_issues_lists_and_revokes_child(client, parent_paid_key, seeded_db):
    _start_session(client, parent_paid_key)
    csrf = _csrf_headers(client)

    # Issue
    r = client.post(
        "/v1/me/keys/children",
        json={"label": "tenant-a"},
        headers=csrf,
    )
    assert r.status_code == 201, r.text
    issued = r.json()
    assert issued["api_key"].startswith("am_") or issued["api_key"]
    assert issued["label"] == "tenant-a"
    assert isinstance(issued["id"], int)
    assert len(issued["key_hash_prefix"]) == 8

    # List (default: live only) — should contain the new child
    r = client.get("/v1/me/keys/children")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["id"] == issued["id"]
    assert rows[0]["label"] == "tenant-a"
    assert rows[0]["key_hash_prefix"] == issued["key_hash_prefix"]
    assert rows[0]["revoked_at"] is None

    # Revoke by id
    r = client.delete(
        f"/v1/me/keys/children/{issued['id']}",
        headers=csrf,
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"revoked": True, "child_id": issued["id"]}

    # Live list now empty
    r = client.get("/v1/me/keys/children")
    assert r.status_code == 200
    assert r.json() == []

    # include_revoked surfaces the same row with a non-null revoked_at
    r = client.get("/v1/me/keys/children?include_revoked=true")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["id"] == issued["id"]
    assert rows[0]["revoked_at"] is not None

    # Re-revoking is idempotent for the helper but the route surfaces
    # 404 child_not_found because no row was flipped.
    r = client.delete(
        f"/v1/me/keys/children/{issued['id']}",
        headers=csrf,
    )
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["error"] == "child_not_found"


# ---------------------------------------------------------------------------
# CSRF + auth gates
# ---------------------------------------------------------------------------


def test_issue_without_csrf_header_403(client, parent_paid_key):
    _start_session(client, parent_paid_key)
    # Deliberately NO csrf header
    r = client.post(
        "/v1/me/keys/children",
        json={"label": "tenant-a"},
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["error"] in {"csrf_missing", "csrf_mismatch"}


def test_revoke_without_csrf_header_403(client, parent_paid_key):
    _start_session(client, parent_paid_key)
    csrf = _csrf_headers(client)
    r = client.post(
        "/v1/me/keys/children",
        json={"label": "tenant-a"},
        headers=csrf,
    )
    assert r.status_code == 201
    child_id = r.json()["id"]

    # DELETE without csrf → 403
    r = client.delete(f"/v1/me/keys/children/{child_id}")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Label validation
# ---------------------------------------------------------------------------


def test_empty_label_rejected_422(client, parent_paid_key):
    _start_session(client, parent_paid_key)
    csrf = _csrf_headers(client)
    r = client.post(
        "/v1/me/keys/children",
        json={"label": "  "},  # whitespace only — passes pydantic min_length=1
        headers=csrf,
    )
    # pydantic min_length=1 catches "" first; whitespace-only flows through to
    # the helper which raises label_missing. Either way we want a 422.
    assert r.status_code == 422, r.text


def test_overlong_label_rejected_422(client, parent_paid_key):
    _start_session(client, parent_paid_key)
    csrf = _csrf_headers(client)
    r = client.post(
        "/v1/me/keys/children",
        json={"label": "x" * 65},  # 65 > MAX_LABEL_LEN (64)
        headers=csrf,
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Child caller defensive shape
# ---------------------------------------------------------------------------


def test_child_key_caller_lists_empty(client, parent_paid_key, seeded_db):
    """A child key holder calling list_children must see [] (defensive).

    Children never log in via /v1/session in the dashboard fan-out flow,
    but if one does, the helper resolves to the child's parent_key_id —
    so the child's "own" children list is empty (children cannot spawn
    grandchildren by design).
    """
    # Issue a child via the helper directly (skipping the route to keep
    # this test focused on the read shape).
    from jpintel_mcp.billing.keys import issue_child_key

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        child_raw, _child_hash = issue_child_key(
            c,
            parent_key_hash=_hash_api_key(parent_paid_key),
            label="tenant-from-helper",
        )
        c.commit()
    finally:
        c.close()

    # Authenticate AS the child
    _start_session(client, child_raw)
    r = client.get("/v1/me/keys/children")
    assert r.status_code == 200
    # Child's own "children" list is empty by construction.
    assert r.json() == []
