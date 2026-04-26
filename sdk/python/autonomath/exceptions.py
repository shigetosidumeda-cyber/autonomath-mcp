"""Exception hierarchy for the autonomath SDK."""

from __future__ import annotations


class AutonoMathError(Exception):
    """Base class for all autonomath SDK errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body

    def __repr__(self) -> str:
        return f"{type(self).__name__}(status_code={self.status_code!r}, message={self.args[0]!r})"


class AuthError(AutonoMathError):
    """401 - invalid or revoked API key."""


class NotFoundError(AutonoMathError):
    """404 - resource not found."""


class RateLimitError(AutonoMathError):
    """429 - quota or rate limit exceeded."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        status_code: int | None = 429,
        body: str | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, body=body)
        self.retry_after = retry_after


class ServerError(AutonoMathError):
    """5xx - server-side failure."""


# deprecated alias, retained for backwards compatibility
JpintelError = AutonoMathError
