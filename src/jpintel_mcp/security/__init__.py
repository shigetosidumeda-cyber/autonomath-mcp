"""Security primitives for AutonoMath.

Currently exports:
    pii_redact   — INV-21 PII redaction for query telemetry / query_log_v2.
"""

from jpintel_mcp.security.pii_redact import (
    PII_PATTERNS,
    redact_pii,
    redact_text,
)

__all__ = ["redact_pii", "redact_text", "PII_PATTERNS"]
