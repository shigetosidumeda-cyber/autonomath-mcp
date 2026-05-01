"""Internal error sanitization for MCP tool responses.

Why this exists
---------------
Wrapping a raw ``str(exc)`` inside an MCP error envelope leaks internal
detail to the client LLM (and onward to the end user): SQL fragments,
column names, file paths, table names, sometimes Python tracebacks.
That's three separate problems:

  1. **Trust.** Customers see raw exception text and conclude AutonoMath
     is unstable. Even when the system recovers cleanly, the leaked
     traceback poisons brand perception.
  2. **Security.** Internal SQL ('SELECT … FROM jpi_pc_program_health
     WHERE …') tells an attacker our schema. File paths
     ('/Users/.../autonomath.db') tell them our deployment.
  3. **Compliance.** APPI / 個人情報保護法: even error text can be
     'personal data' under JP law if it carries identifying tuples.

The fix is simple: when we hit ``except Exception`` in a tool, log the
full exception server-side with a short incident id, and return only the
incident id to the client. Operations can grep logs for the id when a
customer reports a failure.

Usage
-----
::

    from jpintel_mcp.mcp._error_helpers import safe_internal_message

    try:
        ...
    except Exception as exc:
        msg, incident_id = safe_internal_message(exc, logger=logger,
                                                 tool_name="render_36_kyotei_am")
        return make_error("internal", msg)
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

__all__ = [
    "safe_internal_error_payload",
    "safe_internal_message",
]


_DEFAULT_LOGGER = logging.getLogger("jpintel.mcp.errors")


def safe_internal_message(
    exc: BaseException,
    *,
    logger: logging.Logger | None = None,
    tool_name: str | None = None,
    extra: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Return a sanitized error message + a server-side incident id.

    The returned message contains only the incident id — no exception
    text, no SQL, no file paths. The full exception (including traceback)
    is logged via ``logger.exception`` under the incident id so ops can
    correlate a customer report with the raw failure.

    Parameters
    ----------
    exc : BaseException
        The exception caught in the tool body.
    logger : logging.Logger, optional
        Logger to record the full exception against. Defaults to
        ``jpintel.mcp.errors``.
    tool_name : str, optional
        Tool name to prefix the log line with — makes grepping logs by
        tool trivial.
    extra : dict, optional
        Additional structured fields to log alongside the exception
        (e.g. arg snapshot). Logged via ``extra=`` so structured-log
        consumers (Datadog / Loki) can index them.

    Returns
    -------
    (sanitized_message, incident_id)
        ``sanitized_message`` is safe to put in the response envelope.
        ``incident_id`` is a 12-char hex string that uniquely tags the
        log line for this failure.
    """
    incident_id = uuid.uuid4().hex[:12]
    log = logger or _DEFAULT_LOGGER
    prefix = f"[{tool_name}] " if tool_name else ""
    log_extra = dict(extra or {})
    correlation_id = _find_correlation_id(log_extra)
    log_extra["incident_id"] = incident_id
    if tool_name:
        log_extra["tool_name"] = tool_name
    if correlation_id:
        log_extra["correlation_id"] = correlation_id
    # Using logger.exception so the full traceback lands in the log.
    # The exception text ITSELF is only ever logged, never returned.
    log.exception(
        "%sinternal error %s%s: %s",
        prefix,
        incident_id,
        f" correlation={correlation_id}" if correlation_id else "",
        type(exc).__name__,
        extra=log_extra,
    )
    return (
        f"internal error (incident={incident_id})",
        incident_id,
    )


def safe_internal_error_payload(
    exc: BaseException,
    *,
    logger: logging.Logger | None = None,
    tool_name: str | None = None,
    extra: dict[str, Any] | None = None,
    code: str = "internal",
    severity: str = "hard",
) -> dict[str, Any]:
    """Return a sanitized MCP error object for an unexpected exception.

    The payload is safe to embed under ``{"error": ...}``: it contains no
    exception class, exception message, SQL, file path, migration name, or
    traceback. The raw exception is still logged by ``safe_internal_message``.
    """
    message, incident_id = safe_internal_message(
        exc,
        logger=logger,
        tool_name=tool_name,
        extra=extra,
    )
    return {
        "code": code,
        "message": message,
        "hint": "Unhandled tool error. Retry with backoff; report the incident id if it persists.",
        "severity": severity,
        "documentation": f"https://jpcite.com/docs/error_handling#{code}",
        "incident_id": incident_id,
    }


def _find_correlation_id(extra: dict[str, Any]) -> str | None:
    for key in ("correlation_id", "request_id", "trace_id", "incident_id"):
        value = extra.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
