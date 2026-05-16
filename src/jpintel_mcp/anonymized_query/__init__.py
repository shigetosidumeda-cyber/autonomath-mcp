"""Wave 51 dim N — Anonymized query primitives (k-anonymity + PII redact + audit).

This package is the **reusable, router-agnostic** core for the dim N
"network-effect query" layer described in
``feedback_anonymized_query_pii_redact``:

    * Agents need "how did similar entities fare?" lookups
      (業種コード XX × 規模 YY × 地域 ZZ で n=23 件採択、平均 ¥XX 万).
    * Sharing the underlying 法人番号 / 氏名 / 住所 is an APPI violation.
    * Statistical aggregates with k-anonymity ≥ 5 + PII redact are the
      jpcite unbeatable moat (1M entity statistical layer is unbuyable
      by competitors).

The existing REST surface (``src/jpintel_mcp/api/anonymized_query.py``)
already implements the *endpoint* and ad-hoc audit ring buffer. This
package provides the **atomic primitives** so the same enforcement runs
across REST, MCP tools, ETL composition, and offline operator scripts
without each call site re-implementing k-anonymity / PII redact / audit
write logic. Use these primitives from any new dim N consumer instead of
copying the REST router internals.

Public surface
--------------
    K_ANONYMITY_MIN         — module constant (5). NEVER override at runtime.
    REDACT_POLICY_VERSION   — current redact rule version string.
    check_k_anonymity(n)    -> tuple[bool, str | None]
    redact_pii_fields(d)    -> dict
    redact_text(s)          -> tuple[str, list[str]]
    write_audit_entry(...)  -> None  (append-only JSONL)
    AuditEntry              — dataclass returned by audit helpers.

Non-goals
---------
* Does NOT call any LLM API or external HTTP endpoint.
* Does NOT replace ``security.pii_redact`` (telemetry layer 0) or
  ``api._pii_redact`` (extended 7-pattern Dim N strict). This package
  composes those redactors behind a single ergonomic entry point for the
  *response-shaping* path and persists an audit row to JSONL.
"""

from __future__ import annotations

from .audit_log import AuditEntry, write_audit_entry
from .k_anonymity import K_ANONYMITY_MIN, KAnonymityResult, check_k_anonymity
from .pii_redact import (
    JP_PII_FIELDS,
    REDACT_POLICY_VERSION,
    redact_pii_fields,
    redact_text,
)

__all__ = [
    "AuditEntry",
    "JP_PII_FIELDS",
    "KAnonymityResult",
    "K_ANONYMITY_MIN",
    "REDACT_POLICY_VERSION",
    "check_k_anonymity",
    "redact_pii_fields",
    "redact_text",
    "write_audit_entry",
]
