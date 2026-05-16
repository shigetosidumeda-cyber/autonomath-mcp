"""Toxiproxy fixtures for the chaos engineering test suite (Wave 18 E3).

These tests inject network faults (latency, bandwidth caps, TCP resets,
timeouts) onto a Toxiproxy listener that sits in front of the local API.
Toxiproxy is a TCP proxy used to test resilience — see
https://github.com/Shopify/toxiproxy.

Skip semantics
--------------
Every fixture in this file is wrapped to *skip* the test cleanly when
Toxiproxy is not available (control plane on 127.0.0.1:8474 by default).
A developer running ``pytest`` on a vanilla machine sees a row of
"skipped" markers, not red errors. The chaos-weekly.yml workflow boots a
Toxiproxy sidecar via the GitHub Actions service container, so CI
exercises the real path.

Resilience score
----------------
The chaos suite reports a 0-5 score (one point per passing scenario)
via the pytest summary. Production gate target: ≥ 4.5 / 5 weekly.

Env vars
--------
``TOXIPROXY_HOST``  default ``127.0.0.1``
``TOXIPROXY_PORT``  default ``8474`` (control plane)
``TOXIPROXY_API_LISTEN_PORT`` default ``18001`` (downstream toxic listener)
"""

from __future__ import annotations

import os
import socket
from collections.abc import Iterator
from contextlib import closing
from typing import Any

import pytest


def _toxiproxy_available(host: str, port: int) -> bool:
    """Return True iff the Toxiproxy control plane accepts TCP on host:port.

    Uses a 0.5s connect timeout so tests degrade quickly when Toxiproxy
    is not running — the chaos suite is opt-in via the workflow, not a
    gating dependency of the regular pytest run.
    """
    try:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.settimeout(0.5)
            s.connect((host, port))
            return True
    except (OSError, TimeoutError):
        return False


@pytest.fixture(scope="session")
def toxiproxy_host() -> str:
    return os.getenv("TOXIPROXY_HOST", "127.0.0.1")


@pytest.fixture(scope="session")
def toxiproxy_port() -> int:
    return int(os.getenv("TOXIPROXY_PORT", "8474"))


@pytest.fixture(scope="session")
def toxiproxy_listen_port() -> int:
    return int(os.getenv("TOXIPROXY_API_LISTEN_PORT", "18001"))


@pytest.fixture(scope="session")
def toxiproxy_client(toxiproxy_host: str, toxiproxy_port: int) -> Iterator[Any]:
    """Return a connected ``toxiproxy.Toxiproxy`` client, or skip.

    Skips the test cleanly when (a) the ``toxiproxy-python`` package is
    not installed, or (b) the Toxiproxy control plane is not reachable
    on ``TOXIPROXY_HOST:TOXIPROXY_PORT``. Both states are normal on a
    developer laptop without the sidecar — the chaos suite is meant to
    run in CI weekly and on demand, not on every local pytest call.
    """
    if not _toxiproxy_available(toxiproxy_host, toxiproxy_port):
        pytest.skip(
            f"Toxiproxy not reachable on {toxiproxy_host}:{toxiproxy_port}; "
            "run `docker run -p 8474:8474 -p 18001:18001 shopify/toxiproxy` "
            "to enable."
        )
    try:
        from toxiproxy import Toxiproxy
    except ImportError:
        pytest.skip("toxiproxy-python not installed; run `pip install toxiproxy-python`.")
    client = Toxiproxy(host=toxiproxy_host, port=toxiproxy_port)
    # Reset any leftover state from a previous run so each session
    # starts from a known-clean control plane.
    try:
        client.reset()
    except Exception:  # noqa: BLE001 — control-plane wipes are best-effort
        pass
    yield client
    try:
        client.reset()
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture
def api_proxy(
    toxiproxy_client: Any,
    toxiproxy_host: str,
    toxiproxy_listen_port: int,
) -> Iterator[Any]:
    """Create + tear down a `jpcite_api` proxy fronting localhost:8080.

    Each test gets a fresh proxy so toxic state never leaks between
    scenarios. The proxy listens on ``TOXIPROXY_API_LISTEN_PORT`` and
    forwards to ``127.0.0.1:8080`` (the assumed local API). Tests
    issue HTTP requests to ``http://<toxiproxy_host>:<listen_port>/...``
    and observe the injected fault.
    """
    name = "jpcite_api"
    listen = f"0.0.0.0:{toxiproxy_listen_port}"
    upstream = os.getenv("CHAOS_UPSTREAM", "127.0.0.1:8080")
    # Tear down any leftover proxy with the same name from a crashed run.
    try:
        existing = toxiproxy_client.get_proxy(name)
        existing.destroy()
    except Exception:  # noqa: BLE001 — proxy may not exist yet
        pass
    proxy = toxiproxy_client.create(name=name, listen=listen, upstream=upstream)
    yield proxy
    try:
        proxy.destroy()
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture
def proxy_base_url(api_proxy: Any, toxiproxy_host: str, toxiproxy_listen_port: int) -> str:
    """Base URL clients hit instead of the direct API to see toxic faults."""
    _ = api_proxy  # ensure fixture ordering — proxy must exist first
    return f"http://{toxiproxy_host}:{toxiproxy_listen_port}"
