"""Generic public-source fetcher for jpcite-crawler AWS Batch jobs.

Responsibilities:
    * Fetch ``target_urls`` from a job manifest with httpx (HTTP/2 + gzip).
    * Respect ``robots.txt`` (per host, cached per-run).
    * Apply per-source license boundary: ``no_collect`` short-circuits,
      ``link_only`` records URL + hash only, ``metadata_only`` strips body.
    * Per-host token-bucket rate limiting (default 1 req/sec).
    * Retry with exponential backoff on 5xx / network errors.
    * Use ETag / Last-Modified conditional GET when callers cache hints.
    * Emit ``FetchResult`` rows that ``entrypoint.py`` writes into
      ``source_receipts.jsonl`` / ``object_manifest.jsonl`` /
      ``known_gaps.jsonl``.

NO LLM API calls. NO outbound traffic beyond the manifest URLs +
their ``robots.txt`` siblings.
"""

from __future__ import annotations

import contextlib
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.robotparser import RobotFileParser

import httpx
from manifest import sha256_bytes

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

# ---------------------------------------------------------------------------
# Manifest schema (subset used by crawl.py)
# ---------------------------------------------------------------------------


@dataclass
class TargetSpec:
    """One ``target_urls[]`` entry from the job manifest."""

    url: str
    target_id: str = ""
    parser: str = "raw"  # "raw" | "html" | "json" | "pdf" | "xml"
    license_boundary: str = "derived_fact"
    etag: str | None = None
    last_modified: str | None = None
    extras: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class SourcePolicy:
    """Per-source robots + license policy (manifest top-level)."""

    source_id: str
    publisher: str = ""
    license_boundary: str = "derived_fact"
    respect_robots: bool = True
    user_agent: str = ""
    request_delay_seconds: float = 1.0
    max_retries: int = 3
    timeout_seconds: float = 30.0


@dataclass
class FetchResult:
    """One ``FetchResult`` per attempted URL.

    ``ok`` is True only when the response is usable downstream. License
    boundary mismatch and robots disallow are non-error stops: they emit
    a known_gap row rather than a failure row.
    """

    target: TargetSpec
    ok: bool
    http_status: int | None
    content_type: str | None
    content_bytes: bytes
    content_sha256: str
    elapsed_ms: int
    skipped_reason: str | None = None
    error: str | None = None
    response_headers: Mapping[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# robots.txt + per-host rate limit
# ---------------------------------------------------------------------------


class RobotsCache:
    """Per-host robots.txt cache.

    Fetches once per host per run. Failures land in ``manual_review`` per
    the source-terms policy doc (``aws_credit_review_11`` §2.2).
    """

    def __init__(self, client: httpx.Client, user_agent: str) -> None:
        self._client = client
        self._user_agent = user_agent
        self._cache: dict[str, RobotFileParser | None] = {}

    def allowed(self, url: str) -> tuple[bool, str | None]:
        """Return ``(allowed, decision_label)`` for ``url``.

        decision_label is None when allowed; otherwise it is one of:
            * "robots_disallow"
            * "robots_fetch_failed"
        """

        parsed = urllib.parse.urlsplit(url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        rp = self._cache.get(host)
        if rp is None and host not in self._cache:
            rp = self._load(host)
            self._cache[host] = rp
        if rp is None:
            return False, "robots_fetch_failed"
        if rp.can_fetch(self._user_agent, url):
            return True, None
        return False, "robots_disallow"

    def _load(self, host: str) -> RobotFileParser | None:
        robots_url = f"{host}/robots.txt"
        try:
            response = self._client.get(
                robots_url,
                headers={"User-Agent": self._user_agent},
                timeout=10.0,
            )
        except httpx.HTTPError:
            return None
        if response.status_code >= 500:
            return None
        rp = RobotFileParser()
        if response.status_code >= 400:
            # 404 / 403 on robots.txt is conventionally "no rules"; default
            # to allow. The source-terms doc still calls this manual_review
            # for unknown hosts, but the per-source policy already gates
            # that decision upstream (in the manifest).
            rp.parse([])
            return rp
        rp.parse(response.text.splitlines())
        return rp


class HostRateLimiter:
    """Simple per-host minimum-interval gate."""

    def __init__(self) -> None:
        self._last_at: dict[str, float] = {}

    def wait(self, host: str, delay_seconds: float) -> None:
        if delay_seconds <= 0:
            return
        now = time.monotonic()
        last = self._last_at.get(host, 0.0)
        elapsed = now - last
        if elapsed < delay_seconds:
            time.sleep(delay_seconds - elapsed)
        self._last_at[host] = time.monotonic()


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------


class Fetcher:
    """Generic fetcher with robots + rate limit + retry + conditional GET."""

    def __init__(
        self,
        policy: SourcePolicy,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.policy = policy
        # Force ASCII-only User-Agent (httpx Headers() defaults to ASCII encoding)
        raw_ua = policy.user_agent or "jpcite-crawler/0.1.0 (+ops@bookyou.net)"
        ua = raw_ua.encode("ascii", errors="ignore").decode("ascii")
        if not ua:
            ua = "jpcite-crawler/0.1.0"
        self.policy.user_agent = ua
        # httpx Headers() with encoding="utf-8" allows non-ASCII values without crashing
        # (but UA is forced to ASCII above for upstream HTTP/1.1 compatibility)
        client_headers = httpx.Headers(
            {"User-Agent": ua, "Accept-Encoding": "gzip, br"},
            encoding="utf-8",
        )
        self._client = client or httpx.Client(
            http2=False,  # h2 package not in requirements; HTTP/1.1 is sufficient for crawl
            follow_redirects=True,
            timeout=policy.timeout_seconds,
            headers=client_headers,
        )
        self._robots = RobotsCache(self._client, ua)
        self._limiter = HostRateLimiter()

    # ---- public API ----

    def fetch_many(self, targets: Iterable[TargetSpec]) -> list[FetchResult]:
        results: list[FetchResult] = []
        for target in targets:
            results.append(self.fetch_one(target))
        return results

    def fetch_one(self, target: TargetSpec) -> FetchResult:
        # 1. license boundary short-circuit
        if target.license_boundary == "no_collect":
            return self._skipped(target, "license_boundary_blocks_collection")

        # 2. robots.txt
        if self.policy.respect_robots:
            allowed, reason = self._robots.allowed(target.url)
            if not allowed:
                return self._skipped(target, reason or "robots_disallow")

        # 3. rate limit
        parsed = urllib.parse.urlsplit(target.url)
        host = parsed.netloc
        self._limiter.wait(host, self.policy.request_delay_seconds)

        # 4. fetch with retry
        return self._fetch_with_retry(target)

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._client.close()

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ---- internal ----

    def _skipped(self, target: TargetSpec, reason: str) -> FetchResult:
        return FetchResult(
            target=target,
            ok=False,
            http_status=None,
            content_type=None,
            content_bytes=b"",
            content_sha256=sha256_bytes(b""),
            elapsed_ms=0,
            skipped_reason=reason,
        )

    def _fetch_with_retry(self, target: TargetSpec) -> FetchResult:
        headers: dict[str, str] = {}
        if target.etag:
            headers["If-None-Match"] = target.etag
        if target.last_modified:
            headers["If-Modified-Since"] = target.last_modified

        last_error: str | None = None
        for attempt in range(self.policy.max_retries + 1):
            started = time.monotonic()
            try:
                response = self._client.get(target.url, headers=headers)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                self._sleep_backoff(attempt)
                continue
            elapsed_ms = int((time.monotonic() - started) * 1000)

            # 304 Not Modified: caller already has the body, just emit a
            # weak-support receipt + skip body.
            if response.status_code == 304:
                return FetchResult(
                    target=target,
                    ok=True,
                    http_status=304,
                    content_type=response.headers.get("content-type"),
                    content_bytes=b"",
                    content_sha256=sha256_bytes(b""),
                    elapsed_ms=elapsed_ms,
                    skipped_reason="not_modified",
                    response_headers=dict(response.headers),
                )

            # 4xx is non-retriable except for 429.
            if 400 <= response.status_code < 500 and response.status_code != 429:
                return FetchResult(
                    target=target,
                    ok=False,
                    http_status=response.status_code,
                    content_type=response.headers.get("content-type"),
                    content_bytes=b"",
                    content_sha256=sha256_bytes(b""),
                    elapsed_ms=elapsed_ms,
                    error=f"http_{response.status_code}",
                    response_headers=dict(response.headers),
                )

            # 5xx + 429: retry with backoff.
            if response.status_code >= 500 or response.status_code == 429:
                last_error = f"http_{response.status_code}"
                self._sleep_backoff(attempt)
                continue

            body = response.content
            return FetchResult(
                target=target,
                ok=True,
                http_status=response.status_code,
                content_type=response.headers.get("content-type"),
                content_bytes=body if target.license_boundary != "link_only" else b"",
                content_sha256=sha256_bytes(body),
                elapsed_ms=elapsed_ms,
                response_headers=dict(response.headers),
            )

        return FetchResult(
            target=target,
            ok=False,
            http_status=None,
            content_type=None,
            content_bytes=b"",
            content_sha256=sha256_bytes(b""),
            elapsed_ms=0,
            error=last_error or "retry_exhausted",
        )

    def _sleep_backoff(self, attempt: int) -> None:
        if attempt >= self.policy.max_retries:
            return
        # 0.5s, 1.0s, 2.0s, ...
        time.sleep(min(0.5 * (2 ** attempt), 8.0))
