from __future__ import annotations

import socket

import httpx
import pytest

from jpintel_mcp.utils.webhook_safety import SafeWebhookTransport, is_safe_webhook


def test_safe_webhook_transport_blocks_connect_time_dns_rebind(monkeypatch):
    """Preflight-safe DNS followed by private connect DNS must fail closed."""

    answers = [
        [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
        [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    ]

    def fake_getaddrinfo(host, port, *args, **kwargs):
        return answers.pop(0)

    socket_calls: list[tuple] = []

    def fail_if_socket_opened(*args, **kwargs):
        socket_calls.append((args, kwargs))
        raise AssertionError("unsafe connect target should be rejected before socket open")

    monkeypatch.setattr(
        "jpintel_mcp.utils.webhook_safety.socket.getaddrinfo",
        fake_getaddrinfo,
    )
    monkeypatch.setattr(
        "jpintel_mcp.utils.webhook_safety.socket.socket",
        fail_if_socket_opened,
    )

    assert is_safe_webhook("https://race.example.test/hook") == (True, None)

    with (
        httpx.Client(timeout=0.1, transport=SafeWebhookTransport()) as client,
        pytest.raises(httpx.ConnectError),
    ):
        client.post("https://race.example.test/hook", content=b"{}")

    assert socket_calls == []
