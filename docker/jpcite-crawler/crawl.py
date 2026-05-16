"""Generic public-source fetcher for jpcite-crawler AWS Batch jobs.

Responsibilities:
    * Fetch ``target_urls`` from a job manifest with httpx (HTTP/2 + gzip).
    * Respect ``robots.txt`` (per host, cached per-run).
    * Apply per-source license boundary: ``no_collect`` short-circuits,
      ``link_only`` records URL + hash only, ``metadata_only`` strips body.
    * Per-host token-bucket rate limiting (default 1 req/sec).
    * Retry with exponential backoff on 5xx / network errors.
    * Use ETag / Last-Modified conditional GET when callers cache hints.
    * Optionally follow ``<a href>`` from HTML responses according to
      :class:`FollowMode` so HTML index pages can be expanded into actual
      PDF / sibling-page artifacts (needed for J06 ministry PDF index sweep
      where the manifest carries 100+ HTML index URLs but Textract needs
      the linked ``*.pdf`` siblings).
    * Emit ``FetchResult`` rows that ``entrypoint.py`` writes into
      ``source_receipts.jsonl`` / ``object_manifest.jsonl`` /
      ``known_gaps.jsonl``.

NO LLM API calls. NO outbound traffic beyond the manifest URLs +
their ``robots.txt`` siblings + (when ``follow_mode`` is enabled) the
``<a href>`` URLs extracted from already-fetched HTML bodies.
"""

from __future__ import annotations

import contextlib
import enum
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


class FollowMode(str, enum.Enum):  # noqa: UP042 — container is 3.12 but local devbox often 3.9
    """Link-following policy applied after fetching an HTML body.

    Values match the manifest string surface so a JSON entry like
    ``"follow_mode": "pdf_only"`` deserializes directly.

    * ``none`` — never follow ``<a href>``. Legacy behaviour for J01..J05/J07.
    * ``pdf_only`` — follow only links whose URL path ends in ``.pdf``
      (case-insensitive). J06 ministry PDF index sweep is the canonical
      consumer: the manifest lists HTML index pages, each linking to many
      ``*.pdf`` siblings that Textract then OCRs.
    * ``same_domain`` — follow any ``<a href>`` whose netloc matches the
      parent page's netloc. Useful for self-hosted hubs.
    * ``all_anchors`` — follow every absolute ``<a href>`` regardless of
      domain. Use sparingly — combined with naive seed lists this can
      explode into an open-internet crawl.
    """

    NONE = "none"
    PDF_ONLY = "pdf_only"
    SAME_DOMAIN = "same_domain"
    ALL_ANCHORS = "all_anchors"


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
    # Provenance for follow-mode emitted targets so downstream auditors
    # can trace a PDF back to the HTML index that linked it.
    follow_parent_url: str | None = None
    follow_depth: int = 0


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

    # ---- follow-mode policy ----
    # Default = legacy behaviour (no following). Manifest authors must
    # opt in explicitly so existing J01..J07 SUCCEEDED runs reproduce
    # byte-for-byte.
    follow_mode: FollowMode = FollowMode.NONE
    follow_max_per_page: int = 50
    follow_max_total: int = 5000
    follow_max_depth: int = 1


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
# HTML link extractor (follow-mode helper)
# ---------------------------------------------------------------------------


def _looks_like_html(content_type: str | None) -> bool:
    """True iff ``content_type`` smells like an HTML body.

    Empty / None content-types fall through to a permissive True so a
    misconfigured upstream still gets its links walked. The lxml parser
    itself filters non-HTML safely (returns 0 anchors).
    """

    if not content_type:
        return True
    ct = content_type.split(";", 1)[0].strip().lower()
    return ct in {"text/html", "application/xhtml+xml", ""} or ct.startswith("text/html")


def extract_followable_links(
    *,
    body: bytes,
    base_url: str,
    follow_mode: FollowMode,
    max_links: int,
    content_type: str | None = None,
) -> list[str]:
    """Parse ``body`` and return follow-eligible absolute URLs.

    Returns up to ``max_links`` unique absolute URLs. Filtering rules
    follow :class:`FollowMode`. Non-HTML bodies return ``[]``.

    The parser uses ``lxml.html`` (fast, lenient) because the J06 corpus
    is ministry/municipality HTML that is occasionally malformed (legacy
    Shift_JIS pages declared as UTF-8, unclosed ``<a>`` tags, etc.). lxml
    tolerates this; html.parser would raise.
    """

    if follow_mode is FollowMode.NONE:
        return []
    if not body:
        return []
    if not _looks_like_html(content_type):
        return []

    try:
        # local import keeps module-load fast in tests; lxml ships
        # without type stubs (lxml-stubs is third-party) so we silence the
        # missing-stub error with type: ignore — the parser API surface
        # we touch (fromstring + iterlinks) is stable and well-known.
        import lxml.html  # type: ignore[import-untyped]
    except Exception:
        return []

    try:
        # lxml.html.fromstring is forgiving about declared encodings; the
        # bytes path lets it sniff a meta tag / BOM when present.
        doc = lxml.html.fromstring(body)
    except Exception:
        return []

    base_parsed = urllib.parse.urlsplit(base_url)
    base_host = base_parsed.netloc.lower()

    seen: set[str] = set()
    out: list[str] = []
    # `make_links_absolute` is more robust than iterating manually because
    # it honors a `<base href>` element when one is present. Even with
    # resolve_base_href off we still get usable anchors back from
    # .iterlinks() so any failure here is non-fatal.
    with contextlib.suppress(Exception):
        doc.make_links_absolute(base_url, resolve_base_href=True)

    for element, attribute, link, _pos in doc.iterlinks():
        if attribute != "href":
            continue
        if element.tag != "a":
            continue
        if not link:
            continue
        absolute = link.strip()
        # Drop fragments + javascript: / mailto: / tel: / data: schemes.
        parsed = urllib.parse.urlsplit(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        # Strip trailing fragment so two #anchor variants of the same URL
        # don't bloat the follow queue.
        absolute = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")
        )
        if not absolute or absolute in seen:
            continue

        path_lower = parsed.path.lower()
        if follow_mode is FollowMode.PDF_ONLY:
            if not path_lower.endswith(".pdf"):
                continue
        elif follow_mode is FollowMode.SAME_DOMAIN:
            if parsed.netloc.lower() != base_host:
                continue
        elif follow_mode is FollowMode.ALL_ANCHORS:
            # No filter beyond scheme.
            pass

        seen.add(absolute)
        out.append(absolute)
        if len(out) >= max_links:
            break

    return out


def _coerce_follow_mode(value: Any) -> FollowMode:
    """Map manifest input (string / FollowMode / None) onto FollowMode.

    Unknown strings fall back to :data:`FollowMode.NONE` rather than
    raising — manifest typos must not crash a live Batch job. The
    entrypoint will log the coerced value for auditability.
    """

    if value is None or value == "":
        return FollowMode.NONE
    if isinstance(value, FollowMode):
        return value
    if isinstance(value, str):
        try:
            return FollowMode(value.strip().lower())
        except ValueError:
            return FollowMode.NONE
    return FollowMode.NONE


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
        # Track follow-mode bookkeeping so we honor follow_max_total + dedupe.
        self._follow_seen: set[str] = set()
        self._follow_emitted_total: int = 0

    # ---- public API ----

    def fetch_many(self, targets: Iterable[TargetSpec]) -> list[FetchResult]:
        """Fetch ``targets`` plus any follow-queue extensions.

        Follow extensions (when ``follow_mode != NONE``) inherit the
        parent target's ``license_boundary`` so a metadata-only manifest
        doesn't accidentally upgrade itself to derived_fact via a
        followed PDF. ``follow_parent_url`` + ``follow_depth`` are
        stamped onto the child :class:`TargetSpec` for provenance.
        """

        results: list[FetchResult] = []
        # Seed the queue with originals; mark them as already seen so a
        # self-link from the page doesn't loop.
        queue: list[TargetSpec] = []
        for target in targets:
            if target.url not in self._follow_seen:
                self._follow_seen.add(target.url)
                queue.append(target)

        while queue:
            target = queue.pop(0)
            result = self.fetch_one(target)
            results.append(result)

            # Only follow successful HTML bodies and only when the policy
            # asks us to. Children must respect follow_max_depth so a
            # ministry index that links to another index doesn't recurse
            # forever.
            if (
                self.policy.follow_mode is not FollowMode.NONE
                and result.ok
                and result.content_bytes
                and target.follow_depth < self.policy.follow_max_depth
                and self._follow_emitted_total < self.policy.follow_max_total
            ):
                child_urls = extract_followable_links(
                    body=result.content_bytes,
                    base_url=target.url,
                    follow_mode=self.policy.follow_mode,
                    max_links=self.policy.follow_max_per_page,
                    content_type=result.content_type,
                )
                added = 0
                for child_url in child_urls:
                    if child_url in self._follow_seen:
                        continue
                    if self._follow_emitted_total >= self.policy.follow_max_total:
                        break
                    self._follow_seen.add(child_url)
                    self._follow_emitted_total += 1
                    added += 1
                    queue.append(
                        TargetSpec(
                            url=child_url,
                            target_id=f"follow_{target.target_id or 'root'}_{added:04d}",
                            parser=(
                                "pdf"
                                if child_url.lower().endswith(".pdf")
                                else target.parser
                            ),
                            license_boundary=target.license_boundary,
                            follow_parent_url=target.url,
                            follow_depth=target.follow_depth + 1,
                        )
                    )

        return results

    def fetch_one(self, target: TargetSpec) -> FetchResult:
        # 1. license boundary short-circuit
        if target.license_boundary == "no_collect":
            return self._skipped(target, "license_boundary_blocks_collection")

        # 2. robots.txt — applied to followed URLs too. The policy bit
        # is shared so a manifest that opts into respect_robots gets
        # follow-queue protection automatically.
        if self.policy.respect_robots:
            allowed, reason = self._robots.allowed(target.url)
            if not allowed:
                return self._skipped(target, reason or "robots_disallow")

        # 3. rate limit (per-host; same gate for parents + children).
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

    # ---- diagnostics ----

    @property
    def follow_emitted_total(self) -> int:
        """How many child URLs were appended to the follow queue."""

        return self._follow_emitted_total

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
