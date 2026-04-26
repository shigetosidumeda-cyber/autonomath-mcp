"""Asynchronous Client for the AutonoMath REST API."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from autonomath._shared import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT,
    MAX_RETRIES,
    backoff_seconds,
    build_headers,
    build_search_params,
    raise_for_status,
    should_retry,
)
from autonomath.exceptions import AutonoMathError
from autonomath.types import (
    ExclusionCheckResponse,
    ExclusionRule,
    Meta,
    ProgramDetail,
    SearchResponse,
    Tier,
)


class AsyncClient:
    """Async variant of `Client`, backed by `httpx.AsyncClient`.

    Example:
        >>> async with AsyncClient(api_key="am_...") as c:
        ...     meta = await c.meta()
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        from autonomath import __version__

        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self._user_agent = f"autonomath-python/{__version__}"
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers=build_headers(api_key, self._user_agent),
            timeout=timeout,
            transport=transport,
        )

    async def __aenter__(self) -> AsyncClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # -------- public endpoints --------

    async def healthz(self) -> dict[str, str]:
        data = await self._request("GET", "/healthz")
        return dict(data)

    async def meta(self) -> Meta:
        data = await self._request("GET", "/meta")
        return Meta.model_validate(data)

    async def search_programs(
        self,
        *,
        q: str | None = None,
        tier: list[Tier] | None = None,
        prefecture: str | None = None,
        authority_level: str | None = None,
        funding_purpose: list[str] | None = None,
        target_type: list[str] | None = None,
        amount_min: float | None = None,
        amount_max: float | None = None,
        include_excluded: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResponse:
        params = build_search_params(
            q=q,
            tier=tier,
            prefecture=prefecture,
            authority_level=authority_level,
            funding_purpose=funding_purpose,
            target_type=target_type,
            amount_min=amount_min,
            amount_max=amount_max,
            include_excluded=include_excluded,
            limit=limit,
            offset=offset,
        )
        data = await self._request("GET", "/v1/programs/search", params=params)
        return SearchResponse.model_validate(data)

    async def get_program(self, unified_id: str) -> ProgramDetail:
        data = await self._request("GET", f"/v1/programs/{unified_id}")
        return ProgramDetail.model_validate(data)

    async def list_exclusion_rules(self) -> list[ExclusionRule]:
        data = await self._request("GET", "/v1/exclusions/rules")
        return [ExclusionRule.model_validate(x) for x in data]

    async def check_exclusions(self, program_ids: list[str]) -> ExclusionCheckResponse:
        if not program_ids:
            raise ValueError("program_ids must be non-empty")
        data = await self._request(
            "POST",
            "/v1/exclusions/check",
            json={"program_ids": list(program_ids)},
        )
        return ExclusionCheckResponse.model_validate(data)

    # -------- internals --------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: list[tuple[str, Any]] | None = None,
        json: Any = None,
    ) -> Any:
        last_exc: AutonoMathError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._http.request(
                    method,
                    path,
                    params=params,
                    json=json,
                )
            except httpx.HTTPError as exc:
                last_exc = AutonoMathError(f"transport error: {exc}")
                if attempt >= self.max_retries:
                    raise last_exc from exc
                await asyncio.sleep(backoff_seconds(attempt))
                continue

            if should_retry(response.status_code) and attempt < self.max_retries:
                delay = _retry_delay(response, attempt)
                await asyncio.sleep(delay)
                continue

            raise_for_status(response)
            if not response.content:
                return None
            return response.json()

        assert last_exc is not None
        raise last_exc


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    if response.status_code == 429:
        raw = response.headers.get("Retry-After")
        if raw is not None:
            try:
                return max(0.0, float(raw))
            except (TypeError, ValueError):
                pass
    return backoff_seconds(attempt)


__all__ = ["AsyncClient"]
