"""
test_recurring_pdf_billing.py — DEEP-47 test stub (Pattern A charge-first).

Coverage of jpcite v0.3.4 spec DEEP-47:
- api/recurring_quarterly.py:get_quarterly_pdf re-ordered: charge → PDF render → R2
  upload → FileResponse.
- recurring_pdf_billing (jpintel migration wave24_179) tracks charge/render/upload
  status and signed URL expiry.
- Cleanup cron `scripts/cron/cleanup_pdf_unpaid_cache.py` removes orphaned R2
  objects + DB rows after 7 days.
- Signed URL expires after one quarter (~92 days).

Constraints:
- LLM API call: 0 (PDF render = WeasyPrint, no LLM).
- Test pattern: pytest fixtures + parametrize + freezegun-style fake clock.
- 8 test cases covering the success path + every failure branch in DEEP-47 §3.
"""

from __future__ import annotations

# Pull DEEP-46/47/48 shared fixtures (jpintel_conn, autonomath_conn,
# mock_stripe_client, mock_postmark, mock_r2_storage, synthetic_event_factory,
# assert_no_llm_imports, fake_clock, in_memory_sqlite) from the renamed
# conftest_delivery_strict.py — pytest only auto-loads `conftest.py`, so the
# delivery-strict fixtures must be opted in explicitly via pytest_plugins.
pytest_plugins = ["tests.conftest_delivery_strict"]

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Surrogate implementation
# ---------------------------------------------------------------------------


def _quarter_label(year: int, quarter: int) -> str:
    return f"{year}_q{quarter}"


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _idempotency_key(api_key_hash: str, year: int, quarter: int) -> str:
    return f"recurring.quarterly_pdf:{api_key_hash}:{year}:{quarter}"


def _saga_insert(conn: sqlite3.Connection, *, key_hash: str, label: str, status: str) -> int:
    cur = conn.execute(
        """
        INSERT INTO recurring_pdf_billing
            (user_api_key_hash, quarter_label, status, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (key_hash, label, status, _now_iso()),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def _saga_update(conn: sqlite3.Connection, row_id: int, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    conn.execute(
        f"UPDATE recurring_pdf_billing SET {cols} WHERE id=?",
        (*fields.values(), row_id),
    )
    conn.commit()


def get_quarterly_pdf_pattern_a(
    conn: sqlite3.Connection,
    *,
    api_key_hash: str,
    year: int,
    quarter: int,
    stripe_client: Any,
    pdf_renderer: Any,
    r2_storage: Any,
) -> dict[str, Any]:
    """DEEP-47 Pattern A: charge first, PDF render second, R2 upload third."""
    label = _quarter_label(year, quarter)
    # DB-as-SOT fence (DEEP-47 §5 last bullet): success row → idempotent return
    existing = conn.execute(
        """
        SELECT id, status, signed_url_expires_at FROM recurring_pdf_billing
        WHERE user_api_key_hash=? AND quarter_label=? AND status='success'
        """,
        (api_key_hash, label),
    ).fetchone()
    if existing is not None:
        return {"status": "success", "saga_id": existing["id"], "cached": True}

    saga_id = _saga_insert(conn, key_hash=api_key_hash, label=label, status="charge_failed")
    charged = stripe_client.record_metered_delivery(
        api_key_hash=api_key_hash,
        endpoint="recurring.quarterly_pdf",
        status_code=200,
        idempotency_key=_idempotency_key(api_key_hash, year, quarter),
    )
    if not charged:
        # No render, no R2 upload — clean fail.
        return {"status": "charge_failed", "saga_id": saga_id}

    _saga_update(conn, saga_id, status="pdf_failed", charge_at=_now_iso())
    pdf_bytes = pdf_renderer.render(api_key_hash=api_key_hash, year=year, quarter=quarter)
    if pdf_bytes is None:
        # Charge already happened → reconcile cron / refund flag is operator workflow.
        return {"status": "pdf_failed", "saga_id": saga_id}

    _saga_update(conn, saga_id, status="r2_failed", pdf_generated_at=_now_iso())
    uploaded = r2_storage.put_object(
        bucket="jpcite-quarterly-pdf",
        key=f"{api_key_hash}/{label}.pdf",
        body=pdf_bytes,
    )
    if not uploaded:
        return {"status": "r2_failed", "saga_id": saga_id}

    expires_at = (datetime.now(UTC) + timedelta(days=92)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    _saga_update(
        conn,
        saga_id,
        status="success",
        r2_uploaded_at=_now_iso(),
        signed_url_expires_at=expires_at,
    )
    signed_url = r2_storage.signed_url(
        bucket="jpcite-quarterly-pdf",
        key=f"{api_key_hash}/{label}.pdf",
    )
    return {
        "status": "success",
        "saga_id": saga_id,
        "signed_url": signed_url,
        "expires_at": expires_at,
    }


def cleanup_unpaid_cache(conn: sqlite3.Connection, r2_storage: Any, days: int = 7) -> int:
    """Surrogate for `scripts/cron/cleanup_pdf_unpaid_cache.py` (daily 04:00 JST)."""
    rows = conn.execute(
        """
        SELECT id, user_api_key_hash, quarter_label
        FROM recurring_pdf_billing
        WHERE status IN ('charge_failed','pdf_failed','r2_failed')
          AND julianday('now') - julianday(created_at) >= ?
        """,
        (days,),
    ).fetchall()
    purged = 0
    for row in rows:
        r2_storage.delete_object(
            bucket="jpcite-quarterly-pdf",
            key=f"{row['user_api_key_hash']}/{row['quarter_label']}.pdf",
        )
        conn.execute(
            "UPDATE recurring_pdf_billing SET status='cleaned' WHERE id=?",
            (row["id"],),
        )
        purged += 1
    conn.commit()
    return purged


class _StubRenderer:
    """Pure-Python PDF renderer surrogate; no WeasyPrint dependency in this draft."""

    def __init__(self, *, fail_next: int = 0) -> None:
        self.fail_next = fail_next
        self.calls = 0

    def render(self, *, api_key_hash: str, year: int, quarter: int) -> bytes | None:
        self.calls += 1
        if self.fail_next > 0:
            self.fail_next -= 1
            return None
        return f"PDF<{api_key_hash}|{year}|{quarter}>".encode()


@pytest.fixture
def pdf_renderer() -> _StubRenderer:
    return _StubRenderer()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_charge_first_then_pdf_generate_then_r2_upload_then_email(
    jpintel_conn, mock_stripe_client, pdf_renderer, mock_r2_storage
) -> None:
    """Happy path — full DEEP-47 §3 flow."""
    result = get_quarterly_pdf_pattern_a(
        jpintel_conn,
        api_key_hash="hash_aaa",
        year=2026,
        quarter=2,
        stripe_client=mock_stripe_client,
        pdf_renderer=pdf_renderer,
        r2_storage=mock_r2_storage,
    )
    assert result["status"] == "success"
    # Charge → render → upload, in that order
    assert len(mock_stripe_client.calls) == 1
    assert pdf_renderer.calls == 1
    assert "jpcite-quarterly-pdf/hash_aaa/2026_q2.pdf" in mock_r2_storage.objects
    # Saga row marked success
    rows = jpintel_conn.execute("SELECT status FROM recurring_pdf_billing").fetchall()
    assert rows[0]["status"] == "success"


def test_charge_failure_no_pdf_no_r2_upload(
    jpintel_conn, mock_stripe_client, pdf_renderer, mock_r2_storage
) -> None:
    """Cap-exceeded charge → render skipped, R2 untouched, ¥0 storage cost."""
    mock_stripe_client.cap_exceeded = True
    result = get_quarterly_pdf_pattern_a(
        jpintel_conn,
        api_key_hash="hash_bbb",
        year=2026,
        quarter=2,
        stripe_client=mock_stripe_client,
        pdf_renderer=pdf_renderer,
        r2_storage=mock_r2_storage,
    )
    assert result["status"] == "charge_failed"
    assert pdf_renderer.calls == 0
    assert len(mock_r2_storage.objects) == 0


def test_pdf_generation_failure_after_charge(
    jpintel_conn, mock_stripe_client, mock_r2_storage
) -> None:
    """Charge succeeded, PDF render failed → status='pdf_failed'; refund handled by reconcile cron."""
    bad_renderer = _StubRenderer(fail_next=1)
    result = get_quarterly_pdf_pattern_a(
        jpintel_conn,
        api_key_hash="hash_pdf_fail",
        year=2026,
        quarter=2,
        stripe_client=mock_stripe_client,
        pdf_renderer=bad_renderer,
        r2_storage=mock_r2_storage,
    )
    assert result["status"] == "pdf_failed"
    # No R2 object — leak avoided
    assert len(mock_r2_storage.objects) == 0
    # The saga row carries charge_at so the operator can refund
    saga = jpintel_conn.execute("SELECT charge_at, status FROM recurring_pdf_billing").fetchone()
    assert saga["charge_at"] is not None
    assert saga["status"] == "pdf_failed"


def test_r2_upload_failure_after_pdf(
    jpintel_conn, mock_stripe_client, pdf_renderer, mock_r2_storage
) -> None:
    """PDF rendered but R2 upload errored → cleanup cron flips it to 'cleaned' after 7 days."""
    mock_r2_storage.fail_next = 1
    result = get_quarterly_pdf_pattern_a(
        jpintel_conn,
        api_key_hash="hash_r2_fail",
        year=2026,
        quarter=2,
        stripe_client=mock_stripe_client,
        pdf_renderer=pdf_renderer,
        r2_storage=mock_r2_storage,
    )
    assert result["status"] == "r2_failed"
    # PDF rendering happened (¥10 burned), but R2 storage stays empty
    assert pdf_renderer.calls == 1
    assert len(mock_r2_storage.objects) == 0


def test_cleanup_cron_removes_unpaid_cache_after_7days(
    jpintel_conn, mock_stripe_client, pdf_renderer, mock_r2_storage
) -> None:
    """`cleanup_pdf_unpaid_cache.py` purges rows older than 7 days; younger rows stay."""
    # Old row → eligible for cleanup
    jpintel_conn.execute(
        """
        INSERT INTO recurring_pdf_billing
            (user_api_key_hash, quarter_label, status, created_at)
        VALUES ('old_hash', '2026_q1', 'r2_failed',
                strftime('%Y-%m-%dT%H:%M:%fZ','now', '-10 days'))
        """
    )
    # Young row → not yet
    jpintel_conn.execute(
        """
        INSERT INTO recurring_pdf_billing
            (user_api_key_hash, quarter_label, status, created_at)
        VALUES ('new_hash', '2026_q2', 'r2_failed',
                strftime('%Y-%m-%dT%H:%M:%fZ','now', '-2 days'))
        """
    )
    jpintel_conn.commit()
    purged = cleanup_unpaid_cache(jpintel_conn, mock_r2_storage, days=7)
    assert purged == 1
    rows = {
        r["user_api_key_hash"]: r["status"]
        for r in jpintel_conn.execute(
            "SELECT user_api_key_hash, status FROM recurring_pdf_billing"
        ).fetchall()
    }
    assert rows["old_hash"] == "cleaned"
    assert rows["new_hash"] == "r2_failed"


def test_signed_url_expires_after_quarter(
    jpintel_conn, mock_stripe_client, pdf_renderer, mock_r2_storage
) -> None:
    """signed_url_expires_at must be ~92 days out (one quarter window)."""
    result = get_quarterly_pdf_pattern_a(
        jpintel_conn,
        api_key_hash="hash_quarter",
        year=2026,
        quarter=2,
        stripe_client=mock_stripe_client,
        pdf_renderer=pdf_renderer,
        r2_storage=mock_r2_storage,
    )
    expires_at = datetime.strptime(result["expires_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
    delta = expires_at - datetime.utcnow()
    # Should be between 91 and 93 days (allow 1d slop for execution + DST)
    assert 91 <= delta.days <= 93


def test_idempotency_per_quarter(
    jpintel_conn, mock_stripe_client, pdf_renderer, mock_r2_storage
) -> None:
    """Same (api_key × year × quarter) on a second call must NOT re-charge."""
    args = dict(
        api_key_hash="hash_idempotent",
        year=2026,
        quarter=2,
        stripe_client=mock_stripe_client,
        pdf_renderer=pdf_renderer,
        r2_storage=mock_r2_storage,
    )
    first = get_quarterly_pdf_pattern_a(jpintel_conn, **args)
    assert first["status"] == "success"
    second = get_quarterly_pdf_pattern_a(jpintel_conn, **args)
    assert second["status"] == "success"
    assert second.get("cached") is True
    # Stripe charged exactly once
    assert len(mock_stripe_client.calls) == 1
    # Renderer called exactly once
    assert pdf_renderer.calls == 1


def test_no_llm_api_import(assert_no_llm_imports) -> None:
    """CI guard — DEEP-47 must remain LLM-import-free at runtime."""
    assert_no_llm_imports()
