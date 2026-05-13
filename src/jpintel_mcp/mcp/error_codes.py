"""Compatibility exports for MCP error codes.

The canonical definitions live in ``autonomath_tools.error_envelope``.
"""

from __future__ import annotations

from jpintel_mcp.mcp.autonomath_tools.error_envelope import (
    DOC_URL,
    ERROR_CODES,
    ErrorCode,
    is_error,
    make_error,
)

__all__ = [
    "DOC_URL",
    "ERROR_CODES",
    "ErrorCode",
    "is_error",
    "make_error",
]
