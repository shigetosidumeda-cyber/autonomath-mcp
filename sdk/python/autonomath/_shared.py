"""Shared helpers for sync + async clients."""

from __future__ import annotations

from typing import Any

import httpx

from autonomath.exceptions import (
    AuthError,
    AutonoMathError,
    NotFoundError,
    RateLimitError,
    ServerError,
)

DEFAULT_BASE_URL = "https://api.autonomath.ai"
DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3


def build_headers(api_key: str | None, user_agent: str) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": user_agent,
    }
    if api_key:
        headers["X-API-Key"] = api_key
    return headers


def build_search_params(
    *,
    q: str | None,
    tier: list[str] | None,
    prefecture: str | None,
    authority_level: str | None,
    funding_purpose: list[str] | None,
    target_type: list[str] | None,
    amount_min: float | None,
    amount_max: float | None,
    include_excluded: bool,
    limit: int,
    offset: int,
) -> list[tuple[str, Any]]:
    # httpx happily serializes list-of-tuples as repeated query args
    params: list[tuple[str, Any]] = []
    if q is not None:
        params.append(("q", q))
    for t in tier or []:
        params.append(("tier", t))
    if prefecture is not None:
        params.append(("prefecture", prefecture))
    if authority_level is not None:
        params.append(("authority_level", authority_level))
    for fp in funding_purpose or []:
        params.append(("funding_purpose", fp))
    for tt in target_type or []:
        params.append(("target_type", tt))
    if amount_min is not None:
        params.append(("amount_min", amount_min))
    if amount_max is not None:
        params.append(("amount_max", amount_max))
    params.append(("include_excluded", "true" if include_excluded else "false"))
    params.append(("limit", limit))
    params.append(("offset", offset))
    return params


def raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return

    body_text: str | None
    try:
        body_text = response.text
    except Exception:
        body_text = None

    try:
        data = response.json()
        message = data.get("detail") or data.get("message") or body_text or "HTTP error"
    except ValueError:
        message = body_text or "HTTP error"

    status = response.status_code

    if status == 401 or status == 403:
        raise AuthError(str(message), status_code=status, body=body_text)
    if status == 404:
        raise NotFoundError(str(message), status_code=status, body=body_text)
    if status == 429:
        retry_after = _parse_retry_after(response.headers.get("Retry-After"))
        raise RateLimitError(
            str(message),
            retry_after=retry_after,
            status_code=status,
            body=body_text,
        )
    if 500 <= status < 600:
        raise ServerError(str(message), status_code=status, body=body_text)

    raise AutonoMathError(str(message), status_code=status, body=body_text)


def _parse_retry_after(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        # HTTP-date form is not supported; callers fall back to backoff
        return None


def backoff_seconds(attempt: int, base: float = 0.5, cap: float = 8.0) -> float:
    """Exponential backoff without jitter. Attempt is 0-indexed."""
    return min(cap, base * (2**attempt))


def should_retry(status_code: int) -> bool:
    return status_code == 429 or 500 <= status_code < 600
