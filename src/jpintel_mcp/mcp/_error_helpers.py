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
    # Using logger.exception so the full traceback lands in the log.
    # The exception text ITSELF is only ever logged, never returned.
    log.exception(
        "%sinternal error %s: %s",
        prefix,
        incident_id,
        type(exc).__name__,
        extra=extra or {},
    )
    return (
        f"internal error (incident={incident_id})",
        incident_id,
    )
