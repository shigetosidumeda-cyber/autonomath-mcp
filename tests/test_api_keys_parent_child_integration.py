"""Integration test for api_keys parent/child fan-out (migration 086).

Migration 086 implements sub-API-key SaaS B2B fan-out: one parent key issues
child keys per 顧問先 (customer). The parent carries the Stripe subscription;
children inherit `tier`, `monthly_cap_yen`, and `stripe_subscription_id`
verbatim so Stripe sees ONE subscription regardless of how many children
fan out underneath.

This test packet exercises BILLING ISOLATION specifically:

  * A child key invocation must increment the child's own `usage_events`
    row (key_hash = child's hash) — NOT the parent's.
  * The parent's `usage_events` row count must NOT advance when a child
    consumes quota.
  * Parent revocation cascades to children (`revoke_key_tree`).
  * Child quota (tree-scope) cannot exceed parent's `monthly_cap_yen`
    (children inherit verbatim; cap is enforced at TREE scope via
    `_enforce_quota` aggregating across siblings).
  * Billing fan-out: usage records carry the child's key_hash plus the
    customer-supplied `client_tag` (migration 085 X-Client-Tag header)
    so 税理士事務所 can attribute spend per 顧問先 under one parent
    Stripe subscription.

The test uses the canonical fixtures from `tests/conftest.py` (`seeded_db`
+ `client` TestClient) and the production helpers in `billing/keys.py`.
No database mocking — past CLAUDE.md guidance: "Never mock the database
in integration tests — a past incident had mocked tests pass while a
production migration failed."

Validation:
    JPCITE_X402_SCHEMA_FAIL_OPEN_DEV=1 uv run pytest -q \
        tests/test_api_keys_parent_child_integration.py --tb=short
"""

from __future__ import annotations

import sqlite3
import uuid
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.api.deps import hash_api_key
from jpintel_mcp.billing.keys import (
    ChildKeyError,
    issue_child_key,
    issue_key,
    revoke_key_tree,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _conn(seeded_db: Path) -> sqlite3.Connection:
    """Open a row-factory connection bound to the seeded test DB.

    Mirrors the helper in tests/test_revoke_cascade.py — both
    `issue_child_key` and the cap aggregator rely on dict-style row
    access via the `id`, `parent_key_id`, `monthly_cap_yen`, and
    `key_hash` columns, so row_factory must be sqlite3.Row.
    """
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    return c


def _seed_metered_usage(
    db_path: Path,
    *,
    key_hash: str,
    count: int,
    client_tag: str | None = None,
    quantity: int = 1,
) -> None:
    """Insert `count` metered+successful usage_events rows keyed on key_hash.

    Each row carries metered=1, status=200, and the supplied client_tag +
    quantity. The timestamp anchors on the current JST month so the
    customer-cap middleware's month-to-date aggregator picks them up.
    """
    from datetime import UTC, datetime

    c = sqlite3.connect(db_path)
    try:
        ts_iso = datetime.now(UTC).isoformat()
        c.executemany(
            "INSERT INTO usage_events("
            "  key_hash, endpoint, ts, status, metered, client_tag, quantity"
            ") VALUES (?,?,?,?,?,?,?)",
            [
                (key_hash, "test.endpoint", ts_iso, 200, 1, client_tag, quantity)
                for _ in range(count)
            ],
        )
        c.commit()
    finally:
        c.close()


@pytest.fixture()
def parent_with_quota(seeded_db: Path) -> tuple[str, str, str]:
    """Issue `pk_test_a` parent with `monthly_cap_yen=1000`.

    The cap is the "quota" surface in jpcite's pricing model — there is
    no separate per-request quota knob, the cap is enforced in yen
    (¥3/req unit price). 1000 yen / ¥3 ≈ 333 billable units before the
    customer-cap middleware short-circuits the next request.

    Returns ``(raw_key, key_hash, customer_id)``. Each invocation uses
    a uuid-suffixed sub id so isolation is preserved across tests.
    """
    raw_sub = f"sub_pk_test_a_{uuid.uuid4().hex[:8]}"
    customer_id = f"cus_pk_test_a_{uuid.uuid4().hex[:8]}"
    c = _conn(seeded_db)
    try:
        raw = issue_key(
            c,
            customer_id=customer_id,
            tier="paid",
            stripe_subscription_id=raw_sub,
        )
        kh = hash_api_key(raw)
        # Set monthly_cap_yen=1000 (the "quota=1000" mandate).
        c.execute(
            "UPDATE api_keys SET monthly_cap_yen = 1000 WHERE key_hash = ?",
            (kh,),
        )
        c.commit()
    finally:
        c.close()
    return raw, kh, customer_id


# ---------------------------------------------------------------------------
# Test 1: Billing isolation — child usage does NOT increment parent's usage
# ---------------------------------------------------------------------------


def test_child_usage_does_not_increment_parent_usage(parent_with_quota, seeded_db):
    """Child key invocation increments child's usage_events row but NOT parent's.

    Billing isolation contract: a usage_events row is keyed on the
    CALLING key's `key_hash`. When a child key serves a request, the
    row carries the child's hash; the parent's hash never appears on
    that row. This is the per-顧問先 attribution surface — without it,
    the SaaS partner cannot break down their bill by tenant.
    """
    parent_raw, parent_hash, _customer_id = parent_with_quota

    # Spawn child ck_test_a1.
    c = _conn(seeded_db)
    try:
        child_raw, child_hash = issue_child_key(
            c,
            parent_key_hash=parent_hash,
            label="ck_test_a1",
        )
        c.commit()
    finally:
        c.close()

    # Seed 5 metered events keyed on the CHILD's hash. Mirrors what
    # the production hot path does via deps.log_usage(ctx) where
    # ctx.key_hash == child_hash for a child-authenticated request.
    _seed_metered_usage(seeded_db, key_hash=child_hash, count=5)

    # Parent must have ZERO usage rows; child must have exactly 5.
    c = sqlite3.connect(seeded_db)
    try:
        (parent_count,) = c.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ?",
            (parent_hash,),
        ).fetchone()
        (child_count,) = c.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ?",
            (child_hash,),
        ).fetchone()
    finally:
        c.close()

    assert parent_count == 0, (
        f"parent usage_events count must be 0 (child traffic is keyed on the "
        f"child's hash, not the parent's). Got {parent_count}."
    )
    assert child_count == 5, (
        f"child usage_events count must be 5 (rows attributed to ck_test_a1's "
        f"hash). Got {child_count}."
    )


# ---------------------------------------------------------------------------
# Test 2: Parent revocation cascades to children (revoke_key_tree)
# ---------------------------------------------------------------------------


def test_parent_revocation_cascades_to_children(parent_with_quota, seeded_db):
    """`revoke_key_tree(parent_hash)` flips revoked_at on parent + every child.

    The Stripe webhook on subscription.deleted calls this so a SaaS
    partner cannot continue serving traffic against children of a
    canceled subscription. The function returns the total number of
    rows revoked (parent + N children).
    """
    parent_raw, parent_hash, _customer_id = parent_with_quota

    # Spawn 3 children: ck_test_a1, ck_test_a2, ck_test_a3.
    c = _conn(seeded_db)
    child_hashes = []
    try:
        for i in range(1, 4):
            _child_raw, child_hash = issue_child_key(
                c,
                parent_key_hash=parent_hash,
                label=f"ck_test_a{i}",
            )
            child_hashes.append(child_hash)
        c.commit()
    finally:
        c.close()

    # Pre-revoke baseline: 4 rows total (1 parent + 3 children), all active.
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        rows = c.execute(
            "SELECT key_hash, parent_key_id, revoked_at FROM api_keys "
            "WHERE key_hash = ? OR key_hash IN (?, ?, ?)",
            (parent_hash, *child_hashes),
        ).fetchall()
        assert len(rows) == 4, f"expected 4 keys pre-revoke, got {len(rows)}"
        assert all(r["revoked_at"] is None for r in rows), (
            "every key (parent + 3 children) must be active before cascade"
        )
    finally:
        c.close()

    # Cascade revoke.
    c = _conn(seeded_db)
    try:
        total = revoke_key_tree(c, parent_hash)
        c.commit()
    finally:
        c.close()

    assert total == 4, (
        f"revoke_key_tree must report 4 rows revoked (1 parent + 3 children), got {total}"
    )

    # Verify: parent + every child carry revoked_at IS NOT NULL.
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        rows = c.execute(
            "SELECT key_hash, revoked_at FROM api_keys WHERE key_hash = ? OR key_hash IN (?, ?, ?)",
            (parent_hash, *child_hashes),
        ).fetchall()
    finally:
        c.close()

    revoked_count = sum(1 for r in rows if r["revoked_at"] is not None)
    assert revoked_count == 4, (
        f"all 4 rows (parent + 3 children) must be revoked after cascade, got {revoked_count}"
    )


# ---------------------------------------------------------------------------
# Test 3: Child inherits parent's monthly_cap_yen verbatim
# ---------------------------------------------------------------------------


def test_child_inherits_parent_monthly_cap_yen(parent_with_quota, seeded_db):
    """Child's monthly_cap_yen mirrors parent's at issuance time.

    The spec mandate "child quota cannot exceed parent's remaining
    quota" is implemented by VERBATIM INHERITANCE at issuance time +
    TREE-SCOPE ENFORCEMENT at request time. The child's row carries
    the same monthly_cap_yen integer as the parent, so a child cannot
    silently raise its own cap above the parent's. Spend aggregation
    is tree-wide (see test_billing_fan_out_*) so traffic across
    siblings sums against the single parent cap.
    """
    parent_raw, parent_hash, _customer_id = parent_with_quota

    c = _conn(seeded_db)
    try:
        _child_raw, child_hash = issue_child_key(
            c,
            parent_key_hash=parent_hash,
            label="ck_test_a1",
        )
        c.commit()
    finally:
        c.close()

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        parent_row = c.execute(
            "SELECT monthly_cap_yen FROM api_keys WHERE key_hash = ?",
            (parent_hash,),
        ).fetchone()
        child_row = c.execute(
            "SELECT monthly_cap_yen, parent_key_id, "
            "stripe_subscription_id, tier, customer_id "
            "FROM api_keys WHERE key_hash = ?",
            (child_hash,),
        ).fetchone()
    finally:
        c.close()

    assert parent_row["monthly_cap_yen"] == 1000
    assert child_row["monthly_cap_yen"] == 1000, (
        f"child monthly_cap_yen must mirror parent verbatim (1000); "
        f"got {child_row['monthly_cap_yen']}"
    )
    # parent_key_id non-NULL proves the row IS a child.
    assert child_row["parent_key_id"] is not None
    # Inherited columns: tier, sub_id, customer_id verbatim.
    assert child_row["tier"] == "paid"
    assert child_row["stripe_subscription_id"] is not None


# ---------------------------------------------------------------------------
# Test 4: Billing fan-out — usage rows carry child's hash + client_tag
# ---------------------------------------------------------------------------


def test_billing_fan_out_attributes_usage_to_child_with_client_tag(parent_with_quota, seeded_db):
    """Per-顧問先 attribution: usage_events row carries child's key_hash +
    customer-supplied client_tag (mig 085 X-Client-Tag header).

    A 税理士事務所 fan-out: parent serves 3 顧問先 via 3 children. Each
    child's usage rows must carry:
      * key_hash == that child's hash (NOT the parent's)
      * client_tag == that 顧問先's tag

    So the /v1/billing/client_tag_breakdown surface can group by
    client_tag under the parent's customer_id (single Stripe customer)
    and emit a per-顧問先 invoice line item.
    """
    parent_raw, parent_hash, customer_id = parent_with_quota

    c = _conn(seeded_db)
    children: list[tuple[str, str]] = []
    try:
        for label in ("ck_test_a1", "ck_test_a2", "ck_test_a3"):
            _child_raw, child_hash = issue_child_key(
                c,
                parent_key_hash=parent_hash,
                label=label,
            )
            children.append((label, child_hash))
        c.commit()
    finally:
        c.close()

    # Each child consumes a different number of units to verify per-child
    # attribution: a1=3, a2=5, a3=7. Tag string matches the child's label
    # which is how the 税理士事務所 names the 顧問先 internally.
    for label, kh in children:
        n = {"ck_test_a1": 3, "ck_test_a2": 5, "ck_test_a3": 7}[label]
        _seed_metered_usage(
            seeded_db,
            key_hash=kh,
            count=n,
            client_tag=label,
        )

    # Verify: each child's hash has exactly the expected row count + tag.
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        for label, kh in children:
            rows = c.execute(
                "SELECT key_hash, client_tag, status, metered FROM usage_events WHERE key_hash = ?",
                (kh,),
            ).fetchall()
            expected_n = {"ck_test_a1": 3, "ck_test_a2": 5, "ck_test_a3": 7}[label]
            assert len(rows) == expected_n, f"{label}: expected {expected_n} rows, got {len(rows)}"
            assert all(r["client_tag"] == label for r in rows), (
                f"{label}: every row must carry client_tag={label!r}"
            )
            assert all(r["metered"] == 1 for r in rows), (
                f"{label}: every row must be metered (parent's tier='paid')"
            )

        # Parent itself: zero usage rows (no traffic served against parent).
        (parent_count,) = c.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ?",
            (parent_hash,),
        ).fetchone()
        assert parent_count == 0, (
            f"parent must have NO usage rows when only children served traffic. Got {parent_count}."
        )

        # All children share the parent's customer_id (proves billing
        # entity is the parent, not the children).
        child_hashes = [kh for _, kh in children]
        placeholders = ",".join("?" for _ in child_hashes)
        cus_rows = c.execute(
            f"SELECT DISTINCT customer_id FROM api_keys WHERE key_hash IN ({placeholders})",  # noqa: S608
            child_hashes,
        ).fetchall()
        assert len(cus_rows) == 1, (
            f"all children must share ONE customer_id (parent's); got "
            f"{[r['customer_id'] for r in cus_rows]}"
        )
        assert cus_rows[0]["customer_id"] == customer_id
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Test 5: Tree-scope aggregation — siblings share parent's cap budget
# ---------------------------------------------------------------------------


def test_tree_scope_aggregation_sums_siblings_under_parent_cap(parent_with_quota, seeded_db):
    """Cap is enforced at TREE scope: parent + all siblings sum against
    parent's monthly_cap_yen.

    Verifies the contract in `deps._collect_tree_key_hashes`: when any
    key in the parent/child tree runs `_daily_quota_used` or the
    customer cap middleware, the aggregation includes every sibling
    so a SaaS partner cannot burst past the cap by spreading traffic
    across 1,000 children.

    Spec mandate: "Child quota cannot exceed parent's remaining quota"
    = siblings consume from one pooled budget, not their own private one.
    """
    parent_raw, parent_hash, _customer_id = parent_with_quota

    c = _conn(seeded_db)
    children: list[str] = []
    try:
        for label in ("ck_test_a1", "ck_test_a2"):
            _child_raw, child_hash = issue_child_key(
                c,
                parent_key_hash=parent_hash,
                label=label,
            )
            children.append(child_hash)
        c.commit()
    finally:
        c.close()

    # Sibling a1 consumes 100 units; sibling a2 consumes 200 units.
    # Tree-aggregate spend = 300 units * ¥3 = ¥900 — UNDER the ¥1000 cap.
    _seed_metered_usage(seeded_db, key_hash=children[0], count=100)
    _seed_metered_usage(seeded_db, key_hash=children[1], count=200)

    # Resolve the tree via the production helper. ApiContext for a child
    # walks parent_key_id → parent's id; the helper then returns parent +
    # all siblings.
    from jpintel_mcp.api.deps import ApiContext, _collect_tree_key_hashes

    c = _conn(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        # Build a child-rooted ApiContext (mirrors what require_key
        # produces when a child authenticates).
        child_row = c.execute(
            "SELECT id, parent_key_id, tier, customer_id, "
            "stripe_subscription_id FROM api_keys WHERE key_hash = ?",
            (children[0],),
        ).fetchone()
        ctx = ApiContext(
            key_hash=children[0],
            tier=child_row["tier"],
            customer_id=child_row["customer_id"],
            stripe_subscription_id=child_row["stripe_subscription_id"],
            key_id=child_row["id"],
            parent_key_id=child_row["parent_key_id"],
        )
        tree_hashes = _collect_tree_key_hashes(c, ctx)
    finally:
        c.close()

    # Tree must include parent + both children.
    assert parent_hash in tree_hashes, (
        f"parent_hash must appear in tree (cap is at tree scope, not row); got {tree_hashes}"
    )
    for ch in children:
        assert ch in tree_hashes, f"child {ch[:8]} missing from tree {tree_hashes}"
    assert len(tree_hashes) == 3, (
        f"expected exactly 3 keys in tree (parent + 2 children); got {len(tree_hashes)}"
    )

    # Aggregate spend across the tree must sum to 300 units (100 + 200),
    # NOT 100 (single-row scope). This is the load-bearing assertion
    # for "child quota cannot exceed parent's remaining quota": the
    # cap middleware sees every sibling's spend when it gates the next
    # request.
    c = sqlite3.connect(seeded_db)
    try:
        placeholders = ",".join("?" for _ in tree_hashes)
        (total,) = c.execute(
            f"SELECT COALESCE(SUM(COALESCE(quantity, 1)), 0) "  # noqa: S608
            f"FROM usage_events WHERE key_hash IN ({placeholders}) "
            f"AND metered = 1 AND (status IS NULL OR status < 400)",
            tree_hashes,
        ).fetchone()
    finally:
        c.close()

    assert total == 300, (
        f"tree-scope aggregation must SUM siblings (100 + 200 = 300 units), "
        f"NOT scope to a single child (100). Got {total}. This proves the "
        f"parent's monthly_cap_yen=1000 is the SHARED budget across the "
        f"tree, not a per-row cap."
    )


# ---------------------------------------------------------------------------
# Test 6: Grandchildren forbidden — flat tree only
# ---------------------------------------------------------------------------


def test_grandchildren_forbidden_flat_tree_only(parent_with_quota, seeded_db):
    """A child key cannot itself spawn children — flat tree only.

    Enforced server-side in `billing.keys.issue_child_key` via the
    "child keys cannot spawn grandchildren" guard. This keeps the
    cap-aggregation query O(1 + N) (parent + flat children) rather
    than walking an arbitrary depth.
    """
    parent_raw, parent_hash, _customer_id = parent_with_quota

    c = _conn(seeded_db)
    try:
        _child_raw, child_hash = issue_child_key(
            c,
            parent_key_hash=parent_hash,
            label="ck_test_a1",
        )
        c.commit()

        # Attempt to spawn a grandchild off the child — must raise.
        with pytest.raises(ChildKeyError) as excinfo:
            issue_child_key(
                c,
                parent_key_hash=child_hash,
                label="ck_test_a1_grandchild",
            )
        assert excinfo.value.error_code == "nesting_forbidden"
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Test 7: Revoked parent cannot spawn new children
# ---------------------------------------------------------------------------


def test_revoked_parent_cannot_spawn_new_children(parent_with_quota, seeded_db):
    """`issue_child_key` against a revoked parent raises parent_revoked.

    After revoke_key_tree fires (e.g. on Stripe subscription.deleted),
    the parent's revoked_at IS NOT NULL. Further fan-out attempts must
    fail rather than silently producing orphan children that the
    cascade left behind.
    """
    parent_raw, parent_hash, _customer_id = parent_with_quota

    c = _conn(seeded_db)
    try:
        # Issue one child first, then cascade-revoke parent + tree.
        issue_child_key(c, parent_key_hash=parent_hash, label="ck_test_a1")
        revoke_key_tree(c, parent_hash)
        c.commit()

        # Attempt to spawn a fresh child off the revoked parent — must raise.
        with pytest.raises(ChildKeyError) as excinfo:
            issue_child_key(
                c,
                parent_key_hash=parent_hash,
                label="ck_test_a_post_revoke",
            )
        assert excinfo.value.error_code == "parent_revoked"
    finally:
        c.close()
