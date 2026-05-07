"""gBizINFO API rate limiter + 24h disk cache.

6 条件 enforcement substrate (per `docs/legal/gbizinfo_terms_compliance.md`):

- 条件 2 (1-token 原則): single ``GBIZINFO_API_TOKEN`` env var, single
  ``X-hojinInfo-api-token`` header, no other ingest path imports gBizINFO
  with a different token. ``RuntimeError`` raised at first call if the
  env var is missing — fail-fast for cron and for FastAPI startup so a
  silent no-op can never ship data without proper attribution.
- 条件 3a (1 rps 既定値): 利用制限 数値非開示 — defensive 1 req/sec floor
  via ``ratelimit`` decorator if available, fallback to ``time.sleep(1.0)``
  pre-call gating otherwise.
- 条件 3b (24h cache TTL): ``diskcache.Cache`` keyed on full URL + sorted
  query string. Fallback = simple JSON file cache under the same dir.
- 条件 3c (per-houjin debounce): cache key includes ``{houjin_bangou}``
  via the request path → repeated calls within the 24h window short-circuit.

Reference (verbatim ToS): tools/offline/_inbox/public_source_foundation/
gbizinfo_tos_verbatim_2026-05-06.md §レート制限 + §利用申請.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

_LOG = logging.getLogger("jpintel.ingest.gbiz")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GBIZ_API_BASE = "https://info.gbiz.go.jp/hojin"
GBIZ_RATE_LIMIT_RPS = 1
GBIZ_CACHE_TTL_SECONDS = 86400  # 24h hard floor — 条件 3b
GBIZ_USER_AGENT = "jpcite/0.3.4 (Bookyou株式会社, info@bookyou.net)"
_HOUR_SECONDS = 3600.0

# ---------------------------------------------------------------------------
# Optional deps — degrade gracefully so module import never crashes.
# pyproject.toml §2.2 should add ratelimit>=2.2.1 + diskcache>=5.6 to
# core deps. Until then, the fallbacks below give the same observable
# behaviour (1 rps + 24h cache) at slightly lower performance.
# ---------------------------------------------------------------------------
try:
    from ratelimit import limits, sleep_and_retry

    _HAS_RATELIMIT = True
except ImportError:  # pragma: no cover — deps not yet installed
    # TODO: add `ratelimit>=2.2.1,<3.0` to pyproject.toml core deps per
    # DEEP_01 §2.2. Until installed, we fall back to a manual time.sleep
    # gate which is observably equivalent for our 1 rps requirement.
    _HAS_RATELIMIT = False

try:
    from diskcache import Cache

    _HAS_DISKCACHE = True
except ImportError:  # pragma: no cover — deps not yet installed
    # TODO: add `diskcache>=5.6,<6.0` to pyproject.toml core deps per
    # DEEP_01 §2.2. Fallback = JSON-on-disk keyed by hashed cache key.
    _HAS_DISKCACHE = False


# ---------------------------------------------------------------------------
# Token + cache directory helpers
# ---------------------------------------------------------------------------
def _get_token() -> str:
    """Return the Bookyou名義 gBizINFO API token, or raise RuntimeError.

    The token is loaded from ``GBIZINFO_API_TOKEN``. Missing token is a
    fail-fast condition: cron exits non-zero, FastAPI startup raises.
    """
    token = os.environ.get("GBIZINFO_API_TOKEN")
    if not token:
        raise RuntimeError(
            "GBIZINFO_API_TOKEN missing — set in .env.local locally or via "
            "`fly secrets set GBIZINFO_API_TOKEN=...` for production. "
            "See docs/legal/gbizinfo_terms_compliance.md §条件1."
        )
    return token


def _get_cache_dir() -> Path:
    """Return the persistent cache directory (creating it if needed).

    On Fly.io the volume is mounted at ``/data`` and survives machine
    restarts — putting the cache there preserves the 24h TTL window
    across redeploys. Locally we fall back to ``~/.cache/jpintel/gbiz``.
    """
    if Path("/data").exists():
        cache_dir = Path("/data") / ".cache" / "jpintel" / "gbiz"
    else:
        cache_dir = Path.home() / ".cache" / "jpintel" / "gbiz"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


# ---------------------------------------------------------------------------
# Rate limit gating — decorator if available, manual sleep otherwise
# ---------------------------------------------------------------------------
if _HAS_RATELIMIT:

    @sleep_and_retry
    @limits(calls=GBIZ_RATE_LIMIT_RPS, period=1)
    def _rate_limit_gate() -> None:
        """1 rps token bucket — auto-sleeps on overflow."""
        return None

else:
    _last_call_ts: float = 0.0

    def _rate_limit_gate() -> None:
        """Manual 1 rps gate (fallback when ratelimit unavailable)."""
        global _last_call_ts
        now = time.monotonic()
        delta = now - _last_call_ts
        if delta < 1.0 / GBIZ_RATE_LIMIT_RPS:
            time.sleep((1.0 / GBIZ_RATE_LIMIT_RPS) - delta)
        _last_call_ts = time.monotonic()


# ---------------------------------------------------------------------------
# Cache abstraction — diskcache.Cache if available, JSON file fallback
# ---------------------------------------------------------------------------
class _JsonFileCache:
    """Minimal JSON-on-disk cache used when diskcache is not installed.

    Stores one file per cache key (hashed) under the cache dir, with a
    sidecar ``.expire`` file holding the absolute epoch timestamp at
    which the entry expires. Not as fast as diskcache but observably
    equivalent for the 1 rps + 24h TTL constraint.
    """

    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _hash(key: str) -> str:
        import hashlib

        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        item = self.get_with_age(key)
        return item[0] if item is not None else None

    def get_with_age(self, key: str) -> tuple[dict[str, Any], float | None] | None:
        h = self._hash(key)
        body_path = self._dir / f"{h}.json"
        expire_path = self._dir / f"{h}.expire"
        if not body_path.is_file() or not expire_path.is_file():
            return None
        try:
            expire_ts = float(expire_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None
        if expire_ts < time.time():
            return None
        try:
            body = json.loads(body_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        age_hours = max(0.0, (GBIZ_CACHE_TTL_SECONDS - (expire_ts - time.time())) / _HOUR_SECONDS)
        return (body, age_hours)

    def set(self, key: str, value: dict[str, Any], expire: int) -> None:
        h = self._hash(key)
        (self._dir / f"{h}.json").write_text(
            json.dumps(value, ensure_ascii=False), encoding="utf-8"
        )
        (self._dir / f"{h}.expire").write_text(str(time.time() + expire), encoding="utf-8")


def _make_cache(cache_dir: Path) -> Any:
    if _HAS_DISKCACHE:
        # 10 GB ceiling: ~5M corp profiles × ~2 KB/response worst-case.
        return Cache(str(cache_dir), size_limit=10 * 1024 * 1024 * 1024)
    return _JsonFileCache(cache_dir)


# ---------------------------------------------------------------------------
# Client class
# ---------------------------------------------------------------------------
class GbizRateLimitedClient:
    """1 rps + 24h cache gBizINFO REST API v2 client.

    Threadsafe-ish: the underlying ``ratelimit`` decorator and
    ``diskcache.Cache`` are both safe under threads; the manual
    fallback is process-local only. cron callers run single-threaded
    so this is acceptable.
    """

    def __init__(self, token: str | None = None) -> None:
        self._token = token or _get_token()
        self._cache_dir = _get_cache_dir()
        self._cache = _make_cache(self._cache_dir)
        self._headers = {
            "X-hojinInfo-api-token": self._token,
            "Accept": "application/json",
            "User-Agent": GBIZ_USER_AGENT,
        }

    @staticmethod
    def _build_cache_key(url: str, params: dict[str, Any] | None) -> str:
        if not params:
            return url
        qs = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        return f"{url}?{qs}"

    def _cache_get_with_age(self, key: str) -> tuple[dict[str, Any], float | None] | None:
        if hasattr(self._cache, "get_with_age"):
            item = self._cache.get_with_age(key)
            if item is not None:
                return item
        try:
            item = self._cache.get(key, expire_time=True)
        except TypeError:
            hit = self._cache.get(key)
            return (hit, None) if hit is not None else None
        if not item:
            return None
        try:
            body, expire_ts = item
        except (TypeError, ValueError):
            return None
        if body is None:
            return None
        age_hours = None
        if expire_ts:
            age_hours = max(
                0.0,
                (GBIZ_CACHE_TTL_SECONDS - (float(expire_ts) - time.time())) / _HOUR_SECONDS,
            )
        return (body, age_hours)

    @staticmethod
    def _with_cache_meta(
        body: dict[str, Any],
        *,
        cache_hit: bool,
        cache_age_hours: float | None,
    ) -> dict[str, Any]:
        out = dict(body)
        out["_cache_meta"] = {
            "cache_hit": cache_hit,
            "cache_age_hours": cache_age_hours,
        }
        return out

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Cached + rate-limited GET against gBizINFO REST v2.

        Args:
            path: relative path under ``/hojin`` (e.g.
                ``"v2/hojin/8010001213708"``) or full URL.
            params: querystring dict.
            force_refresh: bypass cache. Use sparingly — 24h TTL is the
                conservative interpretation of §2 利用制限 非開示.

        Returns:
            Parsed JSON dict. The upstream body is returned unchanged;
            the ``_attribution`` envelope is added by callers via
            ``_gbiz_attribution.inject_attribution_into_response``.
        """
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            url = f"{GBIZ_API_BASE.rstrip('/')}/{path.lstrip('/')}"
        cache_key = self._build_cache_key(url, params)

        if not force_refresh:
            hit = self._cache_get_with_age(cache_key)
            if hit is not None:
                body, age_hours = hit
                _LOG.debug("gbiz cache hit %s", cache_key)
                return self._with_cache_meta(
                    body,
                    cache_hit=True,
                    cache_age_hours=age_hours,
                )

        # 1 rps gate — blocks the calling thread when needed.
        _rate_limit_gate()

        # Retry transient transport errors, but never retry 429. The
        # operator contract treats upstream 429 as token-at-risk and requires
        # fail-fast manual review rather than automated re-calls.
        backoffs = [2.0, 4.0, 8.0]
        last_exc: Exception | None = None
        for attempt in range(len(backoffs) + 1):
            try:
                with httpx.Client(timeout=30.0) as client:
                    resp = client.get(url, params=params or {}, headers=self._headers)
            except httpx.HTTPError as exc:
                last_exc = exc
                _LOG.warning("gbiz http error attempt=%d %s", attempt, exc)
                if attempt < len(backoffs):
                    time.sleep(backoffs[attempt])
                    continue
                raise

            if resp.status_code in (401, 403):
                # Token rejected — fail loud, do not retry. 申請承認待ち
                # の可能性もあるが、いずれにしても運用者通知が必要。
                _LOG.error("gbiz auth failure status=%d url=%s", resp.status_code, url)
                raise RuntimeError(
                    "gbiz_token_invalid_or_revoked: "
                    "verify GBIZINFO_API_TOKEN and 申請承認状況 "
                    "(see docs/legal/gbizinfo_terms_compliance.md §条件1)"
                )
            if resp.status_code == 429:
                _LOG.error("gbiz 429 received — fail-fast token-at-risk url=%s", url)
                raise RuntimeError("gbiz_rate_limit_exceeded")

            resp.raise_for_status()
            body = resp.json()
            self._cache.set(cache_key, body, expire=GBIZ_CACHE_TTL_SECONDS)
            return self._with_cache_meta(
                body,
                cache_hit=False,
                cache_age_hours=0.0,
            )

        # Should never reach — loop body either returns or raises.
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("gbiz_unexpected_request_failure")


# ---------------------------------------------------------------------------
# Module-level singleton + convenience wrapper
# ---------------------------------------------------------------------------
_default_client: GbizRateLimitedClient | None = None


def get_client() -> GbizRateLimitedClient:
    """Return the process-wide default client, building it on first call."""
    global _default_client
    if _default_client is None:
        _default_client = GbizRateLimitedClient()
    return _default_client


def gbiz_get(
    path: str,
    params: dict[str, Any] | None = None,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Convenience wrapper: ``get_client().get(path, params)``."""
    return get_client().get(path, params=params, force_refresh=force_refresh)


def get(
    path: str,
    params: dict[str, Any] | None = None,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Backward-compatible module-level GET used by older cron drivers."""
    return gbiz_get(path, params=params, force_refresh=force_refresh)
