"""Stripe webhook idempotency helper. LLM API 呼出ゼロ、pure SQLite.

Note: spec path was src/jpintel_mcp/api/billing/webhook_idempotency.py but
api/billing.py already exists as a 1820-line module imported by 30+ call
sites; creating a billing/ package would shadow it. Helper is placed here
as a sibling module to avoid breaking imports. See audit X1 M1.
"""
# ruff: noqa: SIM115,SIM117,BLE001,E501,F401,F841,PTH123,S301,S314,S603,UP017


from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3


def already_processed(conn: sqlite3.Connection, event_id: str) -> bool:
    row = conn.execute(
        "SELECT processing_outcome FROM stripe_event_idempotency WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    return row is not None and row[0] == "success"


def record_received(
    conn: sqlite3.Connection, event_id: str, event_type: str, customer_id: str | None = None
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO stripe_event_idempotency (event_id, event_type, stripe_customer_id, received_at) VALUES (?, ?, ?, ?)",
        (event_id, event_type, customer_id, datetime.now(UTC).isoformat()),
    )


def mark_success(
    conn: sqlite3.Connection,
    event_id: str,
    api_key_id: str | None = None,
    extra: dict | None = None,
) -> None:
    conn.execute(
        "UPDATE stripe_event_idempotency SET processing_outcome = 'success', processed_at = ?, api_key_id_minted = ?, metadata_json = ? WHERE event_id = ?",
        (
            datetime.now(UTC).isoformat(),
            api_key_id,
            json.dumps(extra or {}, ensure_ascii=False),
            event_id,
        ),
    )


def mark_failure(
    conn: sqlite3.Connection, event_id: str, error: str, permanent: bool = False
) -> None:
    outcome = "permanent_failure" if permanent else "retry"
    conn.execute(
        "UPDATE stripe_event_idempotency SET processing_outcome = ?, processed_at = ?, error_message = ? WHERE event_id = ?",
        (outcome, datetime.now(UTC).isoformat(), error[:1000], event_id),
    )
