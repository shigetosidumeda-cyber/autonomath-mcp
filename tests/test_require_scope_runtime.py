from __future__ import annotations

import json
import sqlite3

import pytest

from jpintel_mcp.api.deps import ApiContext
from jpintel_mcp.api.me.api_keys import require_scope


def _conn(scope_json: str | None) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE api_keys(key_hash TEXT PRIMARY KEY, scope_json TEXT)")
    conn.execute(
        "INSERT INTO api_keys(key_hash, scope_json) VALUES (?, ?)",
        ("kh_test", scope_json),
    )
    return conn


def test_require_scope_defers_anonymous_to_route_auth_gate() -> None:
    check = require_scope("read:programs")
    ctx = ApiContext(key_hash=None, tier="free", customer_id=None)

    assert check(ctx, _conn(None)) is None


def test_require_scope_allows_legacy_null_scope_key() -> None:
    check = require_scope("write:webhooks")
    ctx = ApiContext(key_hash="kh_test", tier="paid", customer_id="cus_test")

    assert check(ctx, _conn(None)) is None


def test_require_scope_allows_matching_scope() -> None:
    check = require_scope("read:cases")
    ctx = ApiContext(key_hash="kh_test", tier="paid", customer_id="cus_test")

    assert check(ctx, _conn(json.dumps(["read:cases"]))) is None


def test_require_scope_rejects_authenticated_key_missing_scope() -> None:
    check = require_scope("admin:billing")
    ctx = ApiContext(key_hash="kh_test", tier="paid", customer_id="cus_test")

    with pytest.raises(Exception) as exc_info:
        check(ctx, _conn(json.dumps(["read:programs"])))

    exc = exc_info.value
    assert getattr(exc, "status_code", None) == 403
    assert exc.detail["error"]["required_scope"] == "admin:billing"
