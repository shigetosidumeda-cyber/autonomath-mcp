"""Starlette / FastAPI middleware for the AutonoMath REST API.

Three middlewares live here:

* :class:`CustomerCapMiddleware` — per-key monthly spend cap (¥3/req metered,
  503 + ``cap_reached: true`` once month-to-date billable spend reaches the
  customer's ``monthly_cap_yen``). Imported via the legacy path
  ``from jpintel_mcp.api.middleware import CustomerCapMiddleware`` — the
  module was rehoused in this package on 2026-04-25 alongside ``rate_limit``
  but the import path is preserved here for back-compat.
* :class:`RateLimitMiddleware` — per-key / per-IP token-bucket throttle
  (10 req/sec for paid keys, 1 req/sec for anonymous IPs). Returns 429 +
  ``Retry-After`` header on bucket exhaustion. Process-local state, intended
  to absorb burst abuse before Cloudflare WAF rules kick in.
* :class:`StrictQueryMiddleware` — closed-set query-param gate. Rejects any
  request that carries a query key not declared on the matched route's
  ``dependant.query_params`` with HTTP 422 + the canonical
  ``unknown_query_parameter`` envelope. Closes K4/J10 silent-drop bug.
  Opt-out via ``JPINTEL_STRICT_QUERY_DISABLED=1``.

These are complementary:

* :class:`StrictQueryMiddleware` is a *correctness* gate (reject malformed
  requests early, before any DB read).
* :class:`RateLimitMiddleware` is a *short* (per-second) throttle aimed at
  abuse / DDoS / scraping defence.
* :class:`CustomerCapMiddleware` is a *long* (per-month) spend ceiling for
  paid customers who set a self-cap; it does not enforce abuse limits.
* Anonymous IPs additionally hit ``AnonIpLimitDep`` (3 req/日 quota) at the
  router-dep level — the per-second throttle here is the upstream gate.
"""

from __future__ import annotations

from jpintel_mcp.api.middleware.analytics_recorder import (
    AnalyticsRecorderMiddleware,
)
from jpintel_mcp.api.middleware.anon_quota_header import (
    AnonQuotaHeaderMiddleware,
)
from jpintel_mcp.api.middleware.client_tag import (
    ClientTagMiddleware,
    validate_client_tag,
)
from jpintel_mcp.api.middleware.cost_cap import (
    CostCapMiddleware,
    CostCapState,
)
from jpintel_mcp.api.middleware.customer_cap import (
    CustomerCapMiddleware,
    _reset_cap_cache_state,
    invalidate_cap_cache,
    invalidate_cap_cache_for_tree,
)
from jpintel_mcp.api.middleware.deprecation_warning import (
    DeprecationWarningMiddleware,
)
from jpintel_mcp.api.middleware.envelope_adapter import (
    EnvelopeAdapterMiddleware,
)
from jpintel_mcp.api.middleware.host_deprecation import (
    HostDeprecationMiddleware,
)
from jpintel_mcp.api.middleware.idempotency import IdempotencyMiddleware
from jpintel_mcp.api.middleware.kill_switch import (
    KillSwitchMiddleware,
    _reset_kill_switch_state,
)
from jpintel_mcp.api.middleware.origin_enforcement import (
    OriginEnforcementMiddleware,
)
from jpintel_mcp.api.middleware.per_ip_endpoint_limit import (
    PerIpEndpointLimitMiddleware,
    _reset_per_ip_endpoint_buckets,
)
from jpintel_mcp.api.middleware.rate_limit import (
    RateLimitMiddleware,
    _reset_rate_limit_buckets,
)
from jpintel_mcp.api.middleware.security_headers import (
    SecurityHeadersMiddleware,
)
from jpintel_mcp.api.middleware.static_cache_headers import (
    StaticManifestCacheMiddleware,
)
from jpintel_mcp.api.middleware.strict_query import StrictQueryMiddleware

__all__ = [
    "AnalyticsRecorderMiddleware",
    "AnonQuotaHeaderMiddleware",
    "ClientTagMiddleware",
    "CostCapMiddleware",
    "CostCapState",
    "CustomerCapMiddleware",
    "DeprecationWarningMiddleware",
    "EnvelopeAdapterMiddleware",
    "HostDeprecationMiddleware",
    "IdempotencyMiddleware",
    "KillSwitchMiddleware",
    "OriginEnforcementMiddleware",
    "PerIpEndpointLimitMiddleware",
    "RateLimitMiddleware",
    "SecurityHeadersMiddleware",
    "StaticManifestCacheMiddleware",
    "StrictQueryMiddleware",
    "_reset_cap_cache_state",
    "_reset_kill_switch_state",
    "_reset_per_ip_endpoint_buckets",
    "_reset_rate_limit_buckets",
    "invalidate_cap_cache",
    "invalidate_cap_cache_for_tree",
    "validate_client_tag",
]
