"""Shared webhook URL safety helper.

Used by:
  * ``src/jpintel_mcp/api/customer_webhooks.py`` (POST /v1/me/webhooks/{id}/test)
  * ``scripts/cron/dispatch_webhooks.py`` (per-attempt re-check at fire time)

Purpose: reject URLs that resolve (via DNS) to RFC1918 / loopback /
link-local / multicast / reserved / unspecified addresses. This is the
DNS-rebind defence. A customer can register ``https://internal.example.com``
which today resolves to a public IP and tomorrow resolves to ``10.0.0.5``;
the validate-at-register call (``api/customer_webhooks._validate_webhook_url``)
will not catch that drift. Every actual POST surface must re-validate.

Single source of truth — do not duplicate this logic into more callers
without converging on this module.
"""

from __future__ import annotations

import ipaddress
import socket
import threading
from typing import Any
from urllib.parse import urlparse

import httpx

_CONNECT_LOCK = threading.Lock()


class UnsafeWebhookTargetError(OSError):
    """Raised when the final outbound connect target is not public-safe."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"unsafe webhook target: {reason}")


def _is_unsafe_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve_safe_connect_infos(host: str, port: int) -> list[Any]:
    """Resolve a connect target and fail closed if any answer is unsafe."""
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        if _is_unsafe_ip(ip):
            raise UnsafeWebhookTargetError("internal_ip_literal")

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeWebhookTargetError("dns_failed") from exc

    safe_infos: list[Any] = []
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError as exc:
            raise UnsafeWebhookTargetError("dns_unparseable") from exc
        if _is_unsafe_ip(ip):
            raise UnsafeWebhookTargetError("internal_ip_resolved")
        safe_infos.append(info)
    if not safe_infos:
        raise UnsafeWebhookTargetError("dns_failed")
    return safe_infos


def _safe_create_connection(
    address: tuple[str, int],
    timeout: float | None = None,
    source_address: tuple[str, int] | None = None,
) -> socket.socket:
    """socket.create_connection replacement that pins to safe DNS answers."""
    host, port = address
    last_error: OSError | None = None
    for family, socktype, proto, _canonname, sockaddr in _resolve_safe_connect_infos(host, port):
        sock = socket.socket(family, socktype, proto)
        try:
            if timeout is not None:
                sock.settimeout(timeout)
            if source_address is not None:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last_error = exc
            sock.close()
    if last_error is not None:
        raise last_error
    raise UnsafeWebhookTargetError("dns_failed")


class SafeWebhookTransport(httpx.BaseTransport):
    """httpx transport that validates the final TCP connect address.

    ``is_safe_webhook`` is still used before storing and before delivery, but
    this transport closes the DNS TOCTOU gap where ``httpx`` would otherwise
    perform a second, independent DNS lookup during connect.
    """

    def __init__(self) -> None:
        self._transport = httpx.HTTPTransport(trust_env=False, retries=0)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        with _CONNECT_LOCK:
            original = socket.create_connection
            socket.create_connection = _safe_create_connection
            try:
                return self._transport.handle_request(request)
            finally:
                socket.create_connection = original

    def close(self) -> None:
        self._transport.close()


def is_safe_webhook(url: str) -> tuple[bool, str | None]:
    """Re-validate the URL at fire time. Returns ``(ok, reason_if_unsafe)``.

    Performs:
      1. Parse + scheme check (https only).
      2. Reject empty host / ``localhost``.
      3. If host is an IP literal: reject loopback / private / link-local
         / multicast / reserved / unspecified.
      4. Otherwise DNS-resolve via ``socket.getaddrinfo`` and reject if ANY
         resolved address falls in the same private/reserved set
         (DNS-rebind defence).

    Reason strings (stable, used by retry-policy fast-path in dispatcher):
      * ``url_unparseable``
      * ``scheme_not_https``
      * ``no_host``
      * ``internal_ip_literal``
      * ``dns_failed``
      * ``internal_ip_resolved``
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "url_unparseable"
    if parsed.scheme.lower() != "https":
        return False, "scheme_not_https"
    host = (parsed.hostname or "").strip("[]").lower()
    if not host or host == "localhost":
        return False, "no_host"
    try:
        ip = ipaddress.ip_address(host)
        if _is_unsafe_ip(ip):
            return False, "internal_ip_literal"
        return True, None
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False, "dns_failed"
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _is_unsafe_ip(ip):
            return False, "internal_ip_resolved"
    return True, None


__all__ = ["SafeWebhookTransport", "UnsafeWebhookTargetError", "is_safe_webhook"]
