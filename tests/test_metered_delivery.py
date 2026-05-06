import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import HTTPException


def test_metered_delivery_respects_monthly_cap(seeded_db: Path, paid_key: str, monkeypatch) -> None:
    from jpintel_mcp.api.deps import hash_api_key
    from jpintel_mcp.billing.delivery import record_metered_delivery

    key_hash = hash_api_key(paid_key)
    monkeypatch.setattr(
        "jpintel_mcp.billing.stripe_usage.report_usage_async",
        lambda *args, **kwargs: None,
    )

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            "UPDATE api_keys SET monthly_cap_yen = ? WHERE key_hash = ?",
            (3, key_hash),
        )
        conn.execute(
            "INSERT INTO usage_events(key_hash, endpoint, ts, status, metered, quantity) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                key_hash,
                "already.billed",
                datetime.now(UTC).isoformat(),
                200,
                1,
                1,
            ),
        )
        conn.commit()

        with pytest.raises(HTTPException) as exc_info:
            record_metered_delivery(
                conn,
                key_hash=key_hash,
                endpoint="cron.delivery",
            )
        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["code"] == "billing_cap_final_check_failed"
        (n,) = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE endpoint = 'cron.delivery'"
        ).fetchone()
        assert n == 0
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("status_code", "expected_strict"),
    [(200, True), (201, True), (204, True), (302, False), (500, False)],
)
def test_paid_2xx_metered_delivery_uses_strict_metering(
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    expected_strict: bool,
) -> None:
    from jpintel_mcp.api.deps import hash_api_key
    from jpintel_mcp.billing.delivery import record_metered_delivery

    calls: list[dict] = []

    def fake_log_usage(*args, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("jpintel_mcp.billing.delivery.log_usage", fake_log_usage)

    key_hash = hash_api_key(paid_key)
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        record_metered_delivery(
            conn,
            key_hash=key_hash,
            endpoint="cron.delivery",
            status_code=status_code,
        )
    finally:
        conn.close()

    assert len(calls) == 1
    assert calls[0]["strict_metering"] is expected_strict


def test_metered_delivery_skips_revoked_keys(seeded_db: Path, paid_key: str, monkeypatch) -> None:
    from jpintel_mcp.api.deps import hash_api_key
    from jpintel_mcp.billing.delivery import record_metered_delivery

    reported: list[tuple] = []
    monkeypatch.setattr(
        "jpintel_mcp.billing.stripe_usage.report_usage_async",
        lambda *args, **kwargs: reported.append((args, kwargs)),
    )

    key_hash = hash_api_key(paid_key)
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE key_hash = ?",
            (datetime.now(UTC).isoformat(), key_hash),
        )
        conn.commit()

        ok = record_metered_delivery(
            conn,
            key_hash=key_hash,
            endpoint="cron.revoked_delivery",
        )

        assert ok is False
        (n,) = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE endpoint = 'cron.revoked_delivery'"
        ).fetchone()
        assert n == 0
        assert reported == []
    finally:
        conn.close()
