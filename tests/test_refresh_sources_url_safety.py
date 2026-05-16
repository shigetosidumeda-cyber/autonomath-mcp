"""URL safety guard for scripts/refresh_sources.py (R2 P2, 2026-05-13).

Covers two failure modes that a bad ``programs.source_url`` row used to
trigger silently:

  * ``file:///etc/passwd`` — the script would call ``httpx.head`` on a
    ``file://`` URL and httpx would happily read the local file.
  * ``http://169.254.169.254/latest/`` — the AWS instance-metadata service
    (IMDS). A non-AWS environment ignores it; an AWS environment leaks
    credentials.

The guard is two-stage: scheme must be ``https``, and the host must
resolve to a publicly routable address (no RFC 1918 / loopback / link-local
/ multicast / reserved / IMDS). Refused URLs are not probed, but they still
advance the source-failure streak and quarantine on the third strike.
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path
from unittest import mock

import pytest

# refresh_sources.py is a script, not a module under src/. Add it to sys.path
# directly so we can import its helpers verbatim.
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import refresh_sources  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_dns_cache() -> None:
    refresh_sources._DNS_RESOLVE_CACHE.clear()
    yield
    refresh_sources._DNS_RESOLVE_CACHE.clear()


# ---------------------------------------------------------------------------
# Scheme guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "https://api.example.jp/abc?x=1",
        "https://sub.domain.gov.jp/page",
    ],
)
def test_url_scheme_is_safe_accepts_https(url: str) -> None:
    assert refresh_sources._url_scheme_is_safe(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/",  # plain http
        "file:///etc/passwd",
        "ftp://example.com/x",
        "javascript:alert(1)",
        "data:text/plain;base64,YWJj",
        "//example.com/no-scheme",
        "",
        "not a url",
        "https://",  # no host
    ],
)
def test_url_scheme_is_safe_rejects_everything_else(url: str) -> None:
    assert not refresh_sources._url_scheme_is_safe(url)


# ---------------------------------------------------------------------------
# Private-IP gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "addr",
    [
        "127.0.0.1",  # loopback
        "10.0.0.1",  # RFC1918
        "172.16.0.1",  # RFC1918
        "192.168.1.1",  # RFC1918
        "169.254.169.254",  # AWS IMDS / link-local
        "169.254.1.1",  # link-local
        "224.0.0.1",  # multicast
        "0.0.0.0",  # unspecified
        "::1",  # IPv6 loopback
        "fe80::1",  # IPv6 link-local
        "fc00::1",  # IPv6 unique-local
        "fd00::1",  # IPv6 unique-local
        "ff02::1",  # IPv6 multicast
        "garbage",  # unparseable falls into the safe branch (refused)
    ],
)
def test_is_private_or_reserved_ip_rejects(addr: str) -> None:
    assert refresh_sources._is_private_or_reserved_ip(addr)


@pytest.mark.parametrize(
    "addr",
    [
        "8.8.8.8",
        "1.1.1.1",
        "203.0.113.5",  # documentation range is technically reserved...
    ],
)
def test_is_private_or_reserved_ip_decision_for_public(addr: str) -> None:
    # 203.0.113.0/24 is TEST-NET-3 (reserved) but ipaddress flags it as
    # reserved. Public-routable for our purposes are 8.8.8.8 and 1.1.1.1.
    if addr in ("8.8.8.8", "1.1.1.1"):
        assert not refresh_sources._is_private_or_reserved_ip(addr)
    else:
        # documentation-range — Python flags it reserved. We accept the
        # stricter verdict because no real production source_url ever
        # legitimately points at TEST-NET.
        assert refresh_sources._is_private_or_reserved_ip(addr)


# ---------------------------------------------------------------------------
# is_url_safe — end-to-end
# ---------------------------------------------------------------------------


def _patch_getaddrinfo(mapping: dict[str, list[str]]) -> mock._patch:
    """Patch socket.getaddrinfo so each host returns the IPs in `mapping`."""

    def fake(host, port, *args, **kwargs):  # noqa: ANN001
        if host in mapping:
            return [(0, 0, 0, "", (addr, 0)) for addr in mapping[host]]
        raise OSError(f"unmocked host: {host}")

    return mock.patch("refresh_sources.socket.getaddrinfo", side_effect=fake)


def test_is_url_safe_accepts_public_https_url() -> None:
    with _patch_getaddrinfo({"example.com": ["93.184.216.34"]}):
        safe, reason = refresh_sources.is_url_safe("https://example.com/p")
    assert safe is True
    assert reason is None


def test_is_url_safe_rejects_http() -> None:
    safe, reason = refresh_sources.is_url_safe("http://example.com/")
    assert safe is False
    assert reason == "scheme_not_https"


def test_is_url_safe_rejects_file_scheme() -> None:
    safe, reason = refresh_sources.is_url_safe("file:///etc/passwd")
    assert safe is False
    assert reason == "scheme_not_https"


def test_is_url_safe_rejects_aws_imds_resolving_host() -> None:
    """A hostname that resolves to the AWS IMDS address must be refused."""
    with _patch_getaddrinfo({"metadata.internal.example.com": ["169.254.169.254"]}):
        safe, reason = refresh_sources.is_url_safe(
            "https://metadata.internal.example.com/latest/meta-data/"
        )
    assert safe is False
    assert reason is not None
    assert "private" in reason and "169.254.169.254" in reason


def test_is_url_safe_rejects_rfc1918_resolving_host() -> None:
    with _patch_getaddrinfo({"internal.example": ["10.0.0.5"]}):
        safe, reason = refresh_sources.is_url_safe("https://internal.example/x")
    assert safe is False
    assert reason is not None and "10.0.0.5" in reason


def test_is_url_safe_rejects_loopback_resolving_host() -> None:
    with _patch_getaddrinfo({"localhost.alias": ["127.0.0.1"]}):
        safe, reason = refresh_sources.is_url_safe("https://localhost.alias/")
    assert safe is False


def test_is_url_safe_rejects_when_any_answer_is_private() -> None:
    """If a host returns BOTH a public and a private IP, refuse (dns rebind)."""
    with _patch_getaddrinfo({"split.example": ["8.8.8.8", "192.168.1.1"]}):
        safe, reason = refresh_sources.is_url_safe("https://split.example/")
    assert safe is False
    assert reason is not None and "192.168.1.1" in reason


def test_is_url_safe_rejects_nxdomain() -> None:
    """DNS failures fail closed."""
    with mock.patch(
        "refresh_sources.socket.getaddrinfo",
        side_effect=OSError("nxdomain"),
    ):
        safe, reason = refresh_sources.is_url_safe("https://nx.invalid.example/")
    assert safe is False
    assert reason is not None and reason.startswith("dns:")


def test_is_url_safe_caches_resolution() -> None:
    """A host is resolved exactly once per process — repeat lookups hit the cache."""
    calls = 0

    def fake(host, port, *args, **kwargs):  # noqa: ANN001
        nonlocal calls
        calls += 1
        return [(0, 0, 0, "", ("8.8.8.8", 0))]

    with mock.patch("refresh_sources.socket.getaddrinfo", side_effect=fake):
        assert refresh_sources.is_url_safe("https://cached.example/a") == (
            True,
            None,
        )
        assert refresh_sources.is_url_safe("https://cached.example/b") == (
            True,
            None,
        )
    assert calls == 1


# ---------------------------------------------------------------------------
# TTL + LRU bound on _DNS_RESOLVE_CACHE
# ---------------------------------------------------------------------------


def test_dns_cache_ttl_re_resolves_after_expiry() -> None:
    """A stale entry past TTL (300s) is re-resolved on next access.

    Simulates DNS rebind: first call returns a public IP (cached as safe),
    the entry ages past TTL, then the host drift-rebinds to RFC1918 — the
    cache MUST re-resolve and flip the verdict to unsafe rather than
    handing out the stale "safe" answer.
    """
    answers = [["8.8.8.8"], ["10.0.0.5"]]
    call_idx = [0]

    def fake(host, port, *args, **kwargs):  # noqa: ANN001
        i = min(call_idx[0], len(answers) - 1)
        call_idx[0] += 1
        return [(0, 0, 0, "", (addr, 0)) for addr in answers[i]]

    with mock.patch("refresh_sources.socket.getaddrinfo", side_effect=fake):
        # First call: public IP -> safe, cached.
        safe1, reason1 = refresh_sources.is_url_safe("https://rebind.example/a")
        assert safe1 is True and reason1 is None
        assert call_idx[0] == 1

        # Repeat call within TTL: cache hit, no new resolution.
        safe2, _ = refresh_sources.is_url_safe("https://rebind.example/b")
        assert safe2 is True
        assert call_idx[0] == 1

        # Age the cached entry past TTL by rewriting its cached_at.
        is_safe, reason, _ = refresh_sources._DNS_RESOLVE_CACHE["rebind.example"]
        stale_at = __import__("time").time() - refresh_sources._DNS_RESOLVE_TTL_SEC - 1.0
        refresh_sources._DNS_RESOLVE_CACHE["rebind.example"] = (
            is_safe,
            reason,
            stale_at,
        )

        # Next call must re-resolve and flip to unsafe (RFC1918 answer).
        safe3, reason3 = refresh_sources.is_url_safe("https://rebind.example/c")
    assert call_idx[0] == 2
    assert safe3 is False
    assert reason3 is not None and "10.0.0.5" in reason3


def test_dns_cache_lru_evicts_oldest_at_capacity() -> None:
    """When the cache exceeds _DNS_RESOLVE_CACHE_MAX entries, the oldest is dropped."""
    # Shrink the bound to keep the test fast — restore afterwards.
    original_max = refresh_sources._DNS_RESOLVE_CACHE_MAX
    refresh_sources._DNS_RESOLVE_CACHE_MAX = 10
    try:

        def fake(host, port, *args, **kwargs):  # noqa: ANN001
            # Every host resolves to a public IP so verdict is always safe;
            # we only care about cache-size behaviour here.
            return [(0, 0, 0, "", ("8.8.8.8", 0))]

        with mock.patch("refresh_sources.socket.getaddrinfo", side_effect=fake):
            # Insert MAX + 5 distinct hosts.
            for i in range(refresh_sources._DNS_RESOLVE_CACHE_MAX + 5):
                refresh_sources.is_url_safe(f"https://host-{i:04d}.example/")

        # Cache must be bounded — never exceeds MAX.
        assert len(refresh_sources._DNS_RESOLVE_CACHE) == refresh_sources._DNS_RESOLVE_CACHE_MAX
        # The 5 oldest entries (host-0000..host-0004) were evicted; the
        # newest 10 (host-0005..host-0014) remain.
        for i in range(5):
            assert f"host-{i:04d}.example" not in refresh_sources._DNS_RESOLVE_CACHE
        for i in range(5, 15):
            assert f"host-{i:04d}.example" in refresh_sources._DNS_RESOLVE_CACHE
    finally:
        refresh_sources._DNS_RESOLVE_CACHE_MAX = original_max


def test_dns_cache_lru_bound_at_10000_default() -> None:
    """The shipped default LRU bound is 10,000 entries."""
    assert refresh_sources._DNS_RESOLVE_CACHE_MAX == 10_000


def test_dns_cache_ttl_default_is_300_seconds() -> None:
    """The shipped default TTL is 5 minutes (300 s)."""
    assert refresh_sources._DNS_RESOLVE_TTL_SEC == 300.0


# ---------------------------------------------------------------------------
# handle_row — the live path
# ---------------------------------------------------------------------------


def _row(unified_id: str, source_url: str, fail_count: int = 0) -> sqlite3.Row:
    """Build a sqlite3.Row-like object via a real in-memory connection."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(
        "CREATE TABLE r (unified_id TEXT, source_url TEXT, tier TEXT, source_fail_count INTEGER)"
    )
    con.execute(
        "INSERT INTO r VALUES (?, ?, 'A', ?)",
        (unified_id, source_url, fail_count),
    )
    return con.execute("SELECT * FROM r").fetchone()


def test_handle_row_refuses_file_scheme_without_probing_but_counts_failure() -> None:
    from collections import Counter

    client_probes: list[str] = []

    class _Client:
        async def head(self, url, **kwargs):  # noqa: ANN001
            client_probes.append(url)
            raise AssertionError("probe must not run for file:// scheme")

        async def get(self, url, **kwargs):  # noqa: ANN001
            client_probes.append(url)
            raise AssertionError("probe must not run for file:// scheme")

    class _Robots:
        async def can_fetch(self, url):  # noqa: ANN001
            raise AssertionError("robots must not be consulted for unsafe url")

    class _Limiter:
        async def acquire(self, host):  # noqa: ANN001
            raise AssertionError("limiter must not be acquired for unsafe url")

    stats: Counter[str] = Counter()
    per_host: Counter[str] = Counter()
    changes: list[dict] = []

    asyncio.run(
        refresh_sources.handle_row(
            _row("UID-1", "file:///etc/passwd"),
            _Client(),
            _Limiter(),
            _Robots(),
            asyncio.Semaphore(1),
            stats,
            per_host,
            changes,
        )
    )

    assert client_probes == []
    assert stats["unsafe_url"] == 1
    assert len(changes) == 1
    assert changes[0]["outcome"] == "unsafe_url"
    assert changes[0]["error"] == "scheme_not_https"
    assert changes[0]["fail_count_after"] == 1
    assert changes[0]["quarantined"] is False


def test_handle_row_refuses_imds_without_probing_but_counts_failure() -> None:
    from collections import Counter

    class _Client:
        async def head(self, url, **kwargs):  # noqa: ANN001
            raise AssertionError("probe must not run for IMDS host")

        async def get(self, url, **kwargs):  # noqa: ANN001
            raise AssertionError("probe must not run for IMDS host")

    class _Robots:
        async def can_fetch(self, url):  # noqa: ANN001
            raise AssertionError("robots must not be consulted for IMDS")

    class _Limiter:
        async def acquire(self, host):  # noqa: ANN001
            raise AssertionError("limiter must not run for IMDS")

    stats: Counter[str] = Counter()
    per_host: Counter[str] = Counter()
    changes: list[dict] = []

    with _patch_getaddrinfo({"metadata.example.invalid": ["169.254.169.254"]}):
        asyncio.run(
            refresh_sources.handle_row(
                _row("UID-2", "https://metadata.example.invalid/latest/"),
                _Client(),
                _Limiter(),
                _Robots(),
                asyncio.Semaphore(1),
                stats,
                per_host,
                changes,
            )
        )

    assert stats["unsafe_url"] == 1
    assert changes[0]["outcome"] == "unsafe_url"
    assert changes[0]["error"] is not None
    assert "169.254.169.254" in changes[0]["error"]
    assert changes[0]["fail_count_after"] == 1
    assert changes[0]["quarantined"] is False


def test_handle_row_quarantines_unsafe_url_on_third_strike() -> None:
    from collections import Counter

    class _Client:
        async def head(self, url, **kwargs):  # noqa: ANN001
            raise AssertionError("probe must not run for unsafe url")

        async def get(self, url, **kwargs):  # noqa: ANN001
            raise AssertionError("probe must not run for unsafe url")

    class _Robots:
        async def can_fetch(self, url):  # noqa: ANN001
            raise AssertionError("robots must not be consulted for unsafe url")

    class _Limiter:
        async def acquire(self, host):  # noqa: ANN001
            raise AssertionError("limiter must not be acquired for unsafe url")

    stats: Counter[str] = Counter()
    per_host: Counter[str] = Counter()
    changes: list[dict] = []

    asyncio.run(
        refresh_sources.handle_row(
            _row("UID-3", "file:///etc/passwd", fail_count=2),
            _Client(),
            _Limiter(),
            _Robots(),
            asyncio.Semaphore(1),
            stats,
            per_host,
            changes,
        )
    )

    assert stats["unsafe_url"] == 1
    assert stats["quarantined"] == 1
    assert changes[0]["outcome"] == "unsafe_url"
    assert changes[0]["fail_count_after"] == refresh_sources.QUARANTINE_THRESHOLD
    assert changes[0]["quarantined"] is True


def test_handle_row_lets_public_https_through_to_probe() -> None:
    """Sanity: a public URL still reaches the probe path."""
    from collections import Counter

    probed: list[str] = []

    class _Client:
        async def head(self, url, **kwargs):  # noqa: ANN001
            probed.append(url)

            class _Resp:
                status_code = 200
                url = "https://example.com/p"

            return _Resp()

        async def get(self, url, **kwargs):  # noqa: ANN001
            return await self.head(url, **kwargs)

    class _Robots:
        async def can_fetch(self, url):  # noqa: ANN001
            return True

    class _Limiter:
        async def acquire(self, host):  # noqa: ANN001
            return None

    stats: Counter[str] = Counter()
    per_host: Counter[str] = Counter()
    changes: list[dict] = []

    with _patch_getaddrinfo({"example.com": ["93.184.216.34"]}):
        asyncio.run(
            refresh_sources.handle_row(
                _row("UID-3", "https://example.com/p"),
                _Client(),
                _Limiter(),
                _Robots(),
                asyncio.Semaphore(1),
                stats,
                per_host,
                changes,
            )
        )

    assert probed == ["https://example.com/p"]
    assert stats["ok"] == 1
    assert changes[0]["outcome"] == "ok"


# ---------------------------------------------------------------------------
# commit_changes — 3-strike quarantine semantics
# ---------------------------------------------------------------------------


def _open_commit_db(tmp_path: Path, fail_count: int = 2) -> sqlite3.Connection:
    db_path = tmp_path / "refresh_sources_commit.db"
    con = sqlite3.connect(str(db_path))
    con.execute(
        """
        CREATE TABLE programs (
          unified_id TEXT PRIMARY KEY,
          source_url TEXT,
          tier TEXT,
          excluded INTEGER DEFAULT 0,
          source_fetched_at TEXT,
          source_url_corrected_at TEXT,
          source_last_check_status INTEGER,
          source_fail_count INTEGER DEFAULT 0
        )
        """
    )
    refresh_sources.apply_migrations(con)
    con.execute(
        "INSERT INTO programs (unified_id, source_url, tier, excluded, "
        "source_fetched_at, source_fail_count) VALUES (?, ?, ?, ?, ?, ?)",
        ("UID-Q", "https://example.gov.jp/p", "A", 0, "2026-01-01", fail_count),
    )
    con.commit()
    return con


@pytest.mark.parametrize(
    ("outcome", "error", "status"),
    [
        ("unsafe_url", "scheme_not_https", None),
        ("error", "head:ConnectError", None),
        ("fail", None, 500),
    ],
)
def test_commit_changes_quarantines_failure_outcomes_on_third_strike(
    tmp_path: Path,
    outcome: str,
    error: str | None,
    status: int | None,
) -> None:
    con = _open_commit_db(tmp_path, fail_count=2)
    changes = [
        {
            "unified_id": "UID-Q",
            "url": "https://example.gov.jp/p",
            "host": "example.gov.jp",
            "outcome": outcome,
            "status": status,
            "final_url": None,
            "error": error,
            "fail_count_after": 3,
            "quarantined": True,
        }
    ]

    written = refresh_sources.commit_changes(con, changes, dry_run=False)
    row = con.execute(
        "SELECT excluded, tier, source_fail_count, source_fetched_at "
        "FROM programs WHERE unified_id='UID-Q'"
    ).fetchone()
    failure = con.execute("SELECT action FROM source_failures WHERE unified_id='UID-Q'").fetchone()

    assert written["quarantine"] == 1
    assert row == (1, "X", 3, "2026-01-01")
    assert failure is not None
    assert failure[0].startswith(f"quarantined_after_3:{outcome}:")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_rejects_unknown_args() -> None:
    with pytest.raises(SystemExit) as excinfo:
        refresh_sources.main(["--definitely-not-supported"])
    assert excinfo.value.code == 2


def test_cli_rejects_unsupported_enrich_arg() -> None:
    with pytest.raises(SystemExit) as excinfo:
        refresh_sources.main(["--enrich"])
    assert excinfo.value.code == 2
