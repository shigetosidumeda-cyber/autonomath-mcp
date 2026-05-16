"""MCP Resource subscriber — Wave 41 AX Tools pillar +1 cell.

Polling-integration layer that lets MCP clients subscribe to changes on
specific Resource URIs (``jpcite://programs``, ``jpcite://laws``,
``jpcite://enforcement`` …) and receive change notifications when the
underlying corpus snapshot rotates.

Why this exists
---------------
The MCP **Resources** primitive (Wave 15 base) already lets a client
``list`` and ``read`` server-side resources. What it does NOT do by
default is tell the client *when* a resource has changed — that requires
the optional ``resources/subscribe`` capability + a server-sent
``notifications/resources/updated`` event. Wave 41 wires that path so
agents that hold a long-lived MCP session (Claude.ai project, Cursor
agent, smol-agents background worker) get a *push*-style change signal
rather than having to poll ``resources/read`` on a cadence.

NO LLM call. Pure protocol implementation per MCP spec 2025-06-18
``resources/subscribe`` + ``notifications/resources/updated``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("jpintel.mcp.resource_subscriber")


@dataclass
class Subscription:
    session_id: str
    uri: str
    subscribed_at: float
    last_notified_at: float = 0.0
    notify_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResourceUpdate:
    uri: str
    occurred_at: float
    snapshot_id: str | None = None
    change_kind: str = "content"
    detail: dict[str, Any] = field(default_factory=dict)


class ResourceSubscriberRegistry:
    """Process-local subscription + update registry."""

    def __init__(self, max_updates_per_uri: int = 1024) -> None:
        self._lock = threading.RLock()
        self._subscriptions: dict[tuple[str, str], Subscription] = {}
        self._updates: dict[str, list[ResourceUpdate]] = {}
        self._max_updates = max_updates_per_uri
        self._listeners: list[Callable[[ResourceUpdate], None]] = []

    def subscribe(
        self, session_id: str, uri: str, metadata: dict[str, Any] | None = None
    ) -> Subscription:
        key = (session_id, uri)
        with self._lock:
            existing = self._subscriptions.get(key)
            if existing is not None:
                if metadata:
                    existing.metadata.update(metadata)
                return existing
            sub = Subscription(
                session_id=session_id,
                uri=uri,
                subscribed_at=time.time(),
                metadata=metadata or {},
            )
            self._subscriptions[key] = sub
            logger.info("mcp_resource_subscribe", extra={"session_id": session_id, "uri": uri})
            return sub

    def unsubscribe(self, session_id: str, uri: str) -> bool:
        key = (session_id, uri)
        with self._lock:
            removed = self._subscriptions.pop(key, None)
            if removed is not None:
                logger.info(
                    "mcp_resource_unsubscribe", extra={"session_id": session_id, "uri": uri}
                )
            return removed is not None

    def list_subscriptions(self, session_id: str | None = None) -> list[Subscription]:
        with self._lock:
            if session_id is None:
                return list(self._subscriptions.values())
            return [s for (sid, _), s in self._subscriptions.items() if sid == session_id]

    def publish(self, update: ResourceUpdate) -> int:
        with self._lock:
            buf = self._updates.setdefault(update.uri, [])
            buf.append(update)
            if len(buf) > self._max_updates:
                del buf[: len(buf) - self._max_updates]
            recipients = [s for (_, uri), s in self._subscriptions.items() if uri == update.uri]
            for sub in recipients:
                sub.last_notified_at = update.occurred_at
                sub.notify_count += 1
            for listener in list(self._listeners):
                try:
                    listener(update)
                except Exception:  # noqa: BLE001
                    logger.exception("mcp_resource_update_listener_failed")
            return len(recipients)

    def register_listener(self, listener: Callable[[ResourceUpdate], None]) -> None:
        with self._lock:
            self._listeners.append(listener)

    def poll(self, uri: str, cursor: float | None = None) -> tuple[list[ResourceUpdate], float]:
        with self._lock:
            buf = list(self._updates.get(uri, []))
        if cursor is not None:
            buf = [u for u in buf if u.occurred_at > cursor]
        new_cursor = buf[-1].occurred_at if buf else time.time()
        return buf, new_cursor

    def stats(self) -> dict[str, Any]:
        with self._lock:
            by_uri: dict[str, int] = {}
            for (_, uri), _ in self._subscriptions.items():
                by_uri[uri] = by_uri.get(uri, 0) + 1
            total_updates = sum(len(v) for v in self._updates.values())
            return {
                "subscriptions": len(self._subscriptions),
                "subscriptions_by_uri": by_uri,
                "buffered_updates": total_updates,
                "updates_by_uri": {k: len(v) for k, v in self._updates.items()},
                "listener_count": len(self._listeners),
                "generated_at": datetime.now(UTC).isoformat(),
            }


_REGISTRY: ResourceSubscriberRegistry | None = None
_REGISTRY_LOCK = threading.Lock()


def get_registry() -> ResourceSubscriberRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        with _REGISTRY_LOCK:
            if _REGISTRY is None:
                _REGISTRY = ResourceSubscriberRegistry()
    return _REGISTRY


def handle_subscribe_request(session_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """MCP ``resources/subscribe`` request handler."""
    uri = params.get("uri")
    if not isinstance(uri, str) or not uri:
        return {
            "error": {
                "code": -32602,
                "message": "missing required field 'uri' in resources/subscribe params",
            }
        }
    sub = get_registry().subscribe(session_id, uri, metadata=params.get("metadata") or {})
    return {"result": {"uri": uri, "subscribed_at": sub.subscribed_at}}


def handle_unsubscribe_request(session_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """MCP ``resources/unsubscribe`` request handler."""
    uri = params.get("uri")
    if not isinstance(uri, str) or not uri:
        return {
            "error": {
                "code": -32602,
                "message": "missing required field 'uri' in resources/unsubscribe params",
            }
        }
    removed = get_registry().unsubscribe(session_id, uri)
    return {"result": {"uri": uri, "removed": removed}}


async def emit_notification_loop(
    notify_fn: Callable[[str, dict[str, Any]], Any], interval_seconds: float = 1.0
) -> None:
    """Background fanout loop translating publishes into
    ``notifications/resources/updated`` deliveries."""
    registry = get_registry()
    last_seen: dict[str, float] = {}
    while True:
        for uri in list(registry._updates.keys()):
            cursor = last_seen.get(uri)
            updates, new_cursor = registry.poll(uri, cursor=cursor)
            if updates:
                last_seen[uri] = new_cursor
                for u in updates:
                    try:
                        result = notify_fn(
                            "notifications/resources/updated",
                            {
                                "uri": u.uri,
                                "snapshot_id": u.snapshot_id,
                                "change_kind": u.change_kind,
                                "occurred_at": u.occurred_at,
                            },
                        )
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception:  # noqa: BLE001
                        logger.exception("notification_dispatch_failed")
        await asyncio.sleep(interval_seconds)


__all__ = [
    "ResourceSubscriberRegistry",
    "Subscription",
    "ResourceUpdate",
    "get_registry",
    "handle_subscribe_request",
    "handle_unsubscribe_request",
    "emit_notification_loop",
]
