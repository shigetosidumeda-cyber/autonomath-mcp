import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def test_metered_delivery_respects_monthly_cap(
    seeded_db: Path, paid_key: str, monkeypatch
) -> None:
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

        ok = record_metered_delivery(
            conn,
            key_hash=key_hash,
            endpoint="cron.delivery",
        )
        assert ok is False
        (n,) = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE endpoint = 'cron.delivery'"
        ).fetchone()
        assert n == 0
    finally:
        conn.close()


def test_metered_delivery_skips_revoked_keys(
    seeded_db: Path, paid_key: str, monkeypatch
) -> None:
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
