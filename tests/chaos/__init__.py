"""Chaos engineering test suite (Wave 18 E3).

Toxiproxy-based fault-injection tests that validate the jpcite API's
resilience to upstream latency, connection resets, and bandwidth
constraints. Designed to be skipped cleanly in environments where
Toxiproxy is not running (every test in this package short-circuits on
the ``toxiproxy_client`` fixture so a Toxiproxy-less developer machine
sees a row of "skipped" markers instead of red errors).

Run locally with::

    docker run -d --name toxiproxy -p 8474:8474 -p 18001:18001 \\
        shopify/toxiproxy:latest
    pytest tests/chaos/ -v

Run in CI via ``.github/workflows/chaos-weekly.yml`` (土曜 04:00 UTC).
"""
