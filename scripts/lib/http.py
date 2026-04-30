"""Shared HTTP utility for ingest / watch scripts.

Responsibilities:
  - robots.txt allow/deny per host (urllib.robotparser)
  - 1 req/sec/host pacing (per-host last-fetched clock)
  - fixed UA advertising contact
  - body size cap (default 2 MB, PDFs 10 MB)
  - 429/503 exponential backoff with small jitter

Design notes:
  - stdlib + httpx only. Do NOT pull in readability / feedparser here —
    callers handle content parsing.
  - Stateless across runs except the in-memory host clock (callers are
    short-lived CLI processes, so persistence is unnecessary).
  - This file is the canonical rate policy declared in
    docs/ingest_automation.md §5. scripts/competitive_watch.py currently
    has its own inlined copy; migration to this module is tracked as a
    follow-up (its behaviour is intentionally a superset — readability,
    feedparser — which belong in the caller not here).

Usage:
    from scripts.lib.http import HttpClient, FetchResult

    http = HttpClient()
    res = http.get("https://www.maff.go.jp/some/page")
    if res.ok:
        parse(res.body)
"""
from __future__ import annotations

import dataclasses
import logging
import random
import time
import urllib.parse
import urllib.robotparser

import httpx

_LOG = logging.getLogger("jpintel.scripts.http")

DEFAULT_USER_AGENT = (
    "jpintel-mcp-ingest/1.0 "
    "(+https://jpcite.com; contact=ops@jpcite.com)"
)
DEFAULT_PER_HOST_DELAY_SEC = 1.0  # 1 req/sec/host per §5
DEFAULT_TIMEOUT_SEC = 15.0
DEFAULT_MAX_BYTES = 2 * 1024 * 1024  # HTML cap
PDF_MAX_BYTES = 10 * 1024 * 1024  # PDF cap
DEFAULT_RETRIES = 2


@dataclasses.dataclass
class FetchResult:
    url: str
    status: int
    body: bytes
    headers: dict[str, str]
    ok: bool
    skip_reason: str | None = None  # "robots" | "oversize" | "rate-limit-exceeded"

    @property
    def text(self) -> str:
        # Trust server-declared encoding, fall back to utf-8 replace.
        ct = self.headers.get("content-type", "")
        for part in ct.split(";"):
            part = part.strip().lower()
            if part.startswith("charset="):
                try:
                    return self.body.decode(part[len("charset=") :], errors="replace")
                except LookupError:
                    break
        return self.body.decode("utf-8", errors="replace")


class HttpClient:
    """Shared rate-limited HTTP client for scripts.

    NOT thread-safe. Each CLI subcommand should own one instance.
    """

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        per_host_delay_sec: float = DEFAULT_PER_HOST_DELAY_SEC,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        max_bytes: int = DEFAULT_MAX_BYTES,
        retries: int = DEFAULT_RETRIES,
        respect_robots: bool = True,
    ) -> None:
        self._ua = user_agent
        self._per_host_delay = per_host_delay_sec
        self._timeout = timeout_sec
        self._max_bytes = max_bytes
        self._retries = retries
        self._respect_robots = respect_robots

        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Language": "ja,en;q=0.5"},
            timeout=timeout_sec,
            follow_redirects=True,
        )
        # host -> last-fetched monotonic timestamp
        self._host_clock: dict[str, float] = {}
        # host -> (RobotFileParser | None); None = fetch failed, treat as allow.
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    # -- Robots -----------------------------------------------------

    def _robots_for(self, host: str) -> urllib.robotparser.RobotFileParser | None:
        if host in self._robots_cache:
            return self._robots_cache[host]
        rp = urllib.robotparser.RobotFileParser()
        robots_url = f"https://{host}/robots.txt"
        try:
            r = self._client.get(robots_url, timeout=5.0)
            if r.status_code == 200:
                rp.parse(r.text.splitlines())
                self._robots_cache[host] = rp
                return rp
        except httpx.HTTPError as exc:
            _LOG.debug("robots fetch failed host=%s err=%s", host, exc)
        self._robots_cache[host] = None
        return None

    def _robots_allowed(self, url: str) -> bool:
        if not self._respect_robots:
            return True
        host = urllib.parse.urlparse(url).netloc
        rp = self._robots_for(host)
        if rp is None:
            # No robots.txt reachable → per §5, fall back to the same polite
            # rate (allowed, but pacing still applies).
            return True
        try:
            return rp.can_fetch(self._ua, url)
        except Exception:  # defensive; robotparser can be surprising
            return True

    # -- Pacing -----------------------------------------------------

    def _pace_host(self, host: str) -> None:
        now = time.monotonic()
        last = self._host_clock.get(host)
        if last is not None:
            wait = self._per_host_delay - (now - last)
            if wait > 0:
                time.sleep(wait)
        self._host_clock[host] = time.monotonic()

    # -- GET --------------------------------------------------------

    def get(self, url: str, *, max_bytes: int | None = None) -> FetchResult:
        """Rate-limited GET with robots + size cap.

        Returns a FetchResult. HTTP errors do NOT raise; they return
        ok=False so callers can fail a single authority without killing
        the whole run (see docs/ingest_automation.md §4).
        """
        cap = max_bytes if max_bytes is not None else self._max_bytes
        host = urllib.parse.urlparse(url).netloc

        if not self._robots_allowed(url):
            return FetchResult(
                url=url, status=0, body=b"", headers={}, ok=False,
                skip_reason="robots",
            )

        last_exc: Exception | None = None
        for attempt in range(self._retries + 1):
            self._pace_host(host)
            try:
                with self._client.stream("GET", url) as resp:
                    buf = bytearray()
                    for chunk in resp.iter_bytes():
                        buf.extend(chunk)
                        if len(buf) > cap:
                            resp.close()
                            return FetchResult(
                                url=url,
                                status=resp.status_code,
                                body=bytes(buf[:cap]),
                                headers=dict(resp.headers),
                                ok=False,
                                skip_reason="oversize",
                            )
                    ok = 200 <= resp.status_code < 300
                    if resp.status_code in (429, 503) and attempt < self._retries:
                        # respect Retry-After if present, else backoff
                        ra = resp.headers.get("retry-after")
                        try:
                            wait = float(ra) if ra else 2 ** attempt
                        except ValueError:
                            wait = 2 ** attempt
                        wait += random.uniform(0, 0.5)
                        _LOG.info(
                            "rate-limited host=%s status=%s backoff=%.1fs attempt=%d",
                            host, resp.status_code, wait, attempt,
                        )
                        time.sleep(wait)
                        continue
                    return FetchResult(
                        url=url,
                        status=resp.status_code,
                        body=bytes(buf),
                        headers=dict(resp.headers),
                        ok=ok,
                    )
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < self._retries:
                    wait = (2 ** attempt) + random.uniform(0, 0.5)
                    _LOG.info("fetch error host=%s err=%s backoff=%.1fs", host, exc, wait)
                    time.sleep(wait)
                    continue

        _LOG.warning("fetch failed url=%s err=%s", url, last_exc)
        return FetchResult(
            url=url, status=0, body=b"", headers={}, ok=False,
            skip_reason="rate-limit-exceeded" if last_exc is None else f"error:{last_exc}",
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
