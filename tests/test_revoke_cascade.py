"""Tests for MASTER_PLAN v2.1 §A3 + §M3 — revoke cascade + Stripe proration notify.

§A3 — `revoke_subscription` must walk every parent (parent_key_id IS NULL)
bound to the Stripe subscription and tear down each parent's tree via the
existing `revoke_key_tree` helper. A flat UPDATE WHERE stripe_subscription_id=?
silently misses orphaned children and any future child whose parent already
had its tree pruned but kept the same subscription anchor.

§M3 — when a single child key is revoked through `revoke_child_by_id` we
must notify Stripe by issuing `SubscriptionItem.modify(proration_behavior=
"create_prorations")` against the parent's metered subscription item. This
gives operators an audit signal that the underlying tenant fan-out shrank
even though the metered price itself carries no quantity field.

Both behaviors must continue to work end-to-end without an Anthropic /
OpenAI / Gemini API call (memory: feedback_no_operator_llm_api). All
Stripe interaction is monkeypatched.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from jpintel_mcp.api.deps import hash_api_key
from jpintel_mcp.billing.keys import (
    issue_child_key,
    issue_key,
    revoke_child_by_id,
    revoke_subscription,
)


@pytest.fixture()
def conn(seeded_db: Path):
    """Row-factory connection bound to the shared seeded test DB.

    Mirrors the helper in `tests/test_billing.py` — `revoke_subscription`
    + `issue_child_key` both rely on dict-style row access via key_hash /
    parent_key_id / id, so the row factory must be `sqlite3.Row`.
    """
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def _all_rows(conn: sqlite3.Connection, sub_id: str) -> list[sqlite3.Row]:
    """All api_keys rows (parent + children) for a Stripe subscription.

    Children inherit `stripe_subscription_id` from the parent at issuance
    so a single SELECT on the column returns the entire fan-out tree.
    Ordered by id ASC so the parent (lowest rowid) sorts first.
    """
    return conn.execute(
        "SELECT id, key_hash, parent_key_id, revoked_at "
        "FROM api_keys "
        "WHERE stripe_subscription_id = ? "
        "ORDER BY id ASC",
        (sub_id,),
    ).fetchall()


# ---------------------------------------------------------------------------
# §A3 — cascade revoke
# ---------------------------------------------------------------------------


def test_revoke_subscription_cascades_to_children(conn):
    """parent + 3 children → 4 revoked_at IS NOT NULL after revoke_subscription.

    Reproduces the failure mode that motivated A3: pre-fix the flat UPDATE
    revoked only the rows whose `stripe_subscription_id` matched verbatim
    AND were not yet revoked. That accidentally included children (because
    they inherit the parent's sub id) BUT the subtle bug was that a stale
    child whose parent_key_id pointed at a row that had ALSO been revoked
    via a different path (rotation, manual admin revoke) could end up
    orphaned with the sub id still set — those rows survived. Walking
    parents + cascading via revoke_key_tree is idempotent and complete.
    """
    sub_id = "sub_a3_cascade"
    parent_raw = issue_key(
        conn,
        customer_id="cus_a3",
        tier="paid",
        stripe_subscription_id=sub_id,
    )
    parent_hash = hash_api_key(parent_raw)
    conn.commit()

    # Spawn 3 children. issue_child_key backfills the parent's `id` column
    # via UPDATE id=rowid on the first call so the FK resolves.
    for label in ("tenant-a", "tenant-b", "tenant-c"):
        issue_child_key(conn, parent_key_hash=parent_hash, label=label)
    conn.commit()

    # Pre-revoke baseline: 4 rows total, all active (revoked_at IS NULL).
    pre = _all_rows(conn, sub_id)
    assert len(pre) == 4, f"expected 1 parent + 3 children, got {len(pre)}"
    assert all(row["revoked_at"] is None for row in pre)

    revoked = revoke_subscription(conn, sub_id)
    conn.commit()

    # Cascade revoke must flip all 4. revoke_key_tree returns:
    #   children-revoked-count + 1 (for the parent itself) per parent walked.
    # With 1 parent + 3 children that's 3 + 1 = 4.
    assert revoked == 4, f"expected 4 revoked rows, got {revoked}"

    post = _all_rows(conn, sub_id)
    assert len(post) == 4
    assert all(row["revoked_at"] is not None for row in post), (
        "every parent + child row must carry revoked_at after cascade"
    )


def test_revoke_subscription_unknown_sub_returns_zero(conn):
    """Unknown stripe_subscription_id is a benign no-op (returns 0)."""
    n = revoke_subscription(conn, "sub_does_not_exist_12345")
    assert n == 0


def test_revoke_subscription_idempotent_on_replay(conn):
    """Calling revoke_subscription twice on the same sub returns 0 the second time.

    revoke_key_tree skips rows where revoked_at IS NOT NULL, so a replay
    must not double-flip or count already-dead rows.
    """
    sub_id = "sub_a3_replay"
    parent_raw = issue_key(
        conn,
        customer_id="cus_a3_r",
        tier="paid",
        stripe_subscription_id=sub_id,
    )
    parent_hash = hash_api_key(parent_raw)
    issue_child_key(conn, parent_key_hash=parent_hash, label="t1")
    issue_child_key(conn, parent_key_hash=parent_hash, label="t2")
    conn.commit()

    first = revoke_subscription(conn, sub_id)
    conn.commit()
    second = revoke_subscription(conn, sub_id)
    conn.commit()

    assert first == 3, f"first revoke must flip 3 rows, got {first}"
    assert second == 0, f"replay must be a no-op, got {second}"


def test_revoke_subscription_handles_legacy_flat_keys(conn):
    """Two parent rows sharing one sub id (legacy non-fan-out shape) → both revoked.

    Pre-mig-086 deployments could have multiple parent api_keys rows for
    the same Stripe subscription (rotation history, double-issue races).
    The cascade must walk both because each is its own parent_key_id IS NULL
    row. The original test_revoke_subscription_cascades in test_billing.py
    asserts this at n==2; we re-assert here for completeness.
    """
    sub_id = "sub_a3_flat"
    issue_key(
        conn,
        customer_id="cus_a3_flat",
        tier="paid",
        stripe_subscription_id=sub_id,
    )
    issue_key(
        conn,
        customer_id="cus_a3_flat",
        tier="paid",
        stripe_subscription_id=sub_id,
    )
    conn.commit()

    n = revoke_subscription(conn, sub_id)
    assert n == 2, f"expected 2 flat-key revokes, got {n}"


# ---------------------------------------------------------------------------
# §M3 — Stripe proration notify on individual child revoke
# ---------------------------------------------------------------------------


def test_revoke_child_notifies_stripe_proration(conn, monkeypatch):
    """revoke_child_by_id → SubscriptionItem.modify called with create_prorations.

    The notify is fire-and-forget on a daemon thread, so the test:
      1. Patches the in-process resolver _get_subscription_item_id to
         return a deterministic SI id (no Stripe Subscription.retrieve
         round trip needed).
      2. Patches stripe.SubscriptionItem.modify to capture (si_id, kwargs).
      3. Hydrates settings.stripe_secret_key so the early `if not
         stripe_secret_key: return False` short-circuit doesn't fire.
      4. Joins the daemon thread by polling the captured-calls list with
         a deadline (250ms is generous — modify is a no-op stub here).
    """
    from jpintel_mcp.billing import stripe_usage
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_m3_dummy", raising=False)
    monkeypatch.setattr(
        settings,
        "stripe_api_version",
        "2024-11-20.acacia",
        raising=False,
    )

    # Deterministic SI id — bypass the live Subscription.retrieve path.
    monkeypatch.setattr(
        stripe_usage,
        "_get_subscription_item_id",
        lambda _sub_id: "si_m3_metered_test",
    )

    captured: list[dict] = []

    def _modify(si_id, **kwargs):
        captured.append({"si_id": si_id, "kwargs": kwargs})
        # Mirror Stripe SDK shape minimally — modify returns the modified
        # item; we don't assert on the return so an empty dict is fine.
        return {"id": si_id, "object": "subscription_item"}

    monkeypatch.setattr(stripe_usage.stripe.SubscriptionItem, "modify", _modify)

    # Spin up parent + child.
    sub_id = "sub_m3_notify"
    parent_raw = issue_key(
        conn,
        customer_id="cus_m3",
        tier="paid",
        stripe_subscription_id=sub_id,
    )
    parent_hash = hash_api_key(parent_raw)
    _child_raw, _child_hash = issue_child_key(
        conn, parent_key_hash=parent_hash, label="tenant-revoke"
    )
    conn.commit()

    # Resolve the child's id so we can target the revoke precisely.
    child_row = conn.execute(
        "SELECT id FROM api_keys WHERE parent_key_id IS NOT NULL "
        "AND stripe_subscription_id = ? AND revoked_at IS NULL",
        (sub_id,),
    ).fetchone()
    assert child_row is not None
    child_id = int(child_row["id"])

    ok = revoke_child_by_id(conn, parent_key_hash=parent_hash, child_id=child_id)
    conn.commit()
    assert ok is True, "revoke_child_by_id must report success"

    # Wait up to 1s for the daemon thread to deliver the modify call. The
    # stubbed _modify is purely in-process so latency is microseconds, but
    # the join slack absorbs CI scheduler jitter.
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not captured:
        time.sleep(0.01)

    assert len(captured) == 1, (
        f"expected 1 SubscriptionItem.modify call within 1s, got {len(captured)}"
    )
    call = captured[0]
    assert call["si_id"] == "si_m3_metered_test"
    assert call["kwargs"].get("proration_behavior") == "create_prorations", (
        "M3 contract: create_prorations must be passed verbatim so Stripe "
        "attaches a proration line to the next invoice cycle"
    )

    # Local revoke must have committed regardless of the async notify.
    final = conn.execute(
        "SELECT revoked_at FROM api_keys WHERE id = ?",
        (child_id,),
    ).fetchone()
    assert final["revoked_at"] is not None


def test_revoke_child_swallows_stripe_modify_failure(conn, monkeypatch):
    """A Stripe outage during M3 notify must NOT mask the local revoke.

    The notify thread is daemon + best-effort. If stripe.SubscriptionItem.
    modify raises, we log a warning but the SQLite row is already flipped
    to revoked_at=now. revoke_child_by_id still returns True.
    """
    from jpintel_mcp.billing import stripe_usage
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_m3_fail", raising=False)
    monkeypatch.setattr(
        stripe_usage,
        "_get_subscription_item_id",
        lambda _sub_id: "si_m3_fail",
    )

    def _explode(si_id, **kwargs):
        raise RuntimeError("stripe outage simulated")

    monkeypatch.setattr(stripe_usage.stripe.SubscriptionItem, "modify", _explode)

    sub_id = "sub_m3_fail"
    parent_raw = issue_key(
        conn,
        customer_id="cus_m3_fail",
        tier="paid",
        stripe_subscription_id=sub_id,
    )
    parent_hash = hash_api_key(parent_raw)
    issue_child_key(conn, parent_key_hash=parent_hash, label="t-fail")
    conn.commit()

    child_row = conn.execute(
        "SELECT id FROM api_keys WHERE parent_key_id IS NOT NULL "
        "AND stripe_subscription_id = ? AND revoked_at IS NULL",
        (sub_id,),
    ).fetchone()
    child_id = int(child_row["id"])

    ok = revoke_child_by_id(conn, parent_key_hash=parent_hash, child_id=child_id)
    conn.commit()
    assert ok is True, "Stripe modify exception must not unwind the local SQLite revoke"

    final = conn.execute(
        "SELECT revoked_at FROM api_keys WHERE id = ?",
        (child_id,),
    ).fetchone()
    assert final["revoked_at"] is not None


def test_revoke_child_skips_stripe_when_parent_has_no_subscription(conn, monkeypatch):
    """A parent without a Stripe subscription_id must NOT trigger any Stripe call.

    Defensive: legacy or admin-issued parent rows can carry NULL
    stripe_subscription_id; we still want the local revoke to work but
    no SubscriptionItem.modify should fire.
    """
    from jpintel_mcp.billing import stripe_usage
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_m3_nosub", raising=False)

    called: list[tuple] = []

    def _resolver(_sub_id):
        called.append(("resolve", _sub_id))
        return "si_should_not_be_used"

    def _modify(si_id, **kwargs):  # pragma: no cover — regression guard
        called.append(("modify", si_id, kwargs))
        raise AssertionError("SubscriptionItem.modify must not be called when parent has no sub")

    monkeypatch.setattr(stripe_usage, "_get_subscription_item_id", _resolver)
    monkeypatch.setattr(stripe_usage.stripe.SubscriptionItem, "modify", _modify)

    # Parent with NULL stripe_subscription_id.
    parent_raw = issue_key(
        conn,
        customer_id="cus_m3_nosub",
        tier="paid",
        stripe_subscription_id=None,
    )
    parent_hash = hash_api_key(parent_raw)
    issue_child_key(conn, parent_key_hash=parent_hash, label="t-nosub")
    conn.commit()

    child_row = conn.execute(
        "SELECT id FROM api_keys WHERE parent_key_id IS NOT NULL "
        "AND key_hash != ? AND customer_id = ? AND revoked_at IS NULL",
        (parent_hash, "cus_m3_nosub"),
    ).fetchone()
    child_id = int(child_row["id"])

    ok = revoke_child_by_id(conn, parent_key_hash=parent_hash, child_id=child_id)
    conn.commit()
    assert ok is True

    # Give any (would-be) daemon thread a chance to misbehave; it should
    # not have been spawned at all because parent_sub_id was NULL.
    time.sleep(0.1)
    assert called == [], f"no Stripe call expected when parent has NULL sub id, got {called}"
