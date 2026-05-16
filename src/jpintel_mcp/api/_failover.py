"""Active/passive Fly region failover marker (Wave 43.3.8 — AX Resilience cell 8).

jpcite production runs on Fly.io with ``primary_region = "nrt"`` (Tokyo) in
``fly.toml``. The intended DR posture is *active/passive*: NRT serves all
traffic; ``sin`` (Singapore) is a standby that can be brought online via
``flyctl scale count N --region sin`` when NRT is impaired.

This module gives every routed response a deterministic, machine-readable
hint about WHICH region answered and WHETHER it is the declared primary,
plus a single-source health probe that other modules (cron alerts, deep
health, status page) can call to ask "is the primary up?".

Why: the existing ``/healthz`` + ``/v1/am/health/deep`` answer for the
*current* process, but they cannot answer "should this process even be
serving?". That decision belongs to a small, dependency-free helper that
reads ``FLY_REGION`` / ``$PRIMARY_REGION`` / ``$STANDBY_REGION`` and
returns one of {primary, standby, unknown}. The marker is stamped onto
the deep-health envelope so the operator dashboard can colour the
region badge without re-implementing the rule.

NO LLM call, NO networked dep — only ``socket.gethostname`` (used to
break the tie when ``FLY_REGION`` is unset on a dev laptop). Importable
from MCP tools, cron, status page generator alike.
"""

from __future__ import annotations

import logging
import os
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

# Declared topology — overridable via env so DR drills can swap roles
# without a code change.  Tokyo primary / Singapore standby is the
# default per fly.toml `primary_region = "nrt"`.
DEFAULT_PRIMARY_REGION: str = "nrt"
DEFAULT_STANDBY_REGION: str = "sin"

RoleType = Literal["primary", "standby", "unknown"]


@dataclass(frozen=True)
class RegionMarker:
    """Snapshot of the region resolution at one point in time."""

    region: str
    primary: str
    standby: str
    role: RoleType
    is_primary: bool
    is_standby: bool
    host: str
    probed_at: float

    def to_dict(self) -> dict[str, object]:
        return {
            "region": self.region,
            "primary": self.primary,
            "standby": self.standby,
            "role": self.role,
            "is_primary": self.is_primary,
            "is_standby": self.is_standby,
            "host": self.host,
            "probed_at": self.probed_at,
        }


def _resolve_region() -> str:
    """Read region from Fly env, fall back to hostname heuristic.

    Fly sets ``FLY_REGION`` on every machine.  In dev we sometimes set
    ``PRIMARY_REGION_OVERRIDE`` so tests can pretend to be primary or
    standby without booting Fly.
    """
    for key in ("FLY_REGION", "PRIMARY_REGION_OVERRIDE", "REGION"):
        v = os.getenv(key, "").strip().lower()
        if v:
            return v
    # Last-resort: parse hostname for a region-shaped suffix (Fly assigns
    # hostnames like ``jpcite-api-abc123.internal``; this branch is mainly
    # a safety net for dev laptops where ``FLY_REGION`` is empty).
    try:
        host = socket.gethostname().lower()
    except Exception:  # noqa: BLE001
        host = ""
    for candidate in ("nrt", "sin", "hkg", "iad", "lhr", "fra", "syd"):
        if candidate in host:
            return candidate
    return ""


def get_region_marker() -> RegionMarker:
    """Return the current region marker. Idempotent + cheap (<1 µs)."""
    primary = os.getenv("PRIMARY_REGION", DEFAULT_PRIMARY_REGION).strip().lower()
    standby = os.getenv("STANDBY_REGION", DEFAULT_STANDBY_REGION).strip().lower()
    region = _resolve_region()
    if region == primary:
        role: RoleType = "primary"
    elif region == standby:
        role = "standby"
    else:
        role = "unknown"
    try:
        host = socket.gethostname()
    except Exception:  # noqa: BLE001
        host = ""
    return RegionMarker(
        region=region or "unknown",
        primary=primary,
        standby=standby,
        role=role,
        is_primary=role == "primary",
        is_standby=role == "standby",
        host=host,
        probed_at=time.time(),
    )


# ---------------------------------------------------------------------------
# Health-check-based switch
# ---------------------------------------------------------------------------

#: Module-level cache so a single deep-health request does not re-call
#: ``primary_healthy()`` for every sub-check.  TTL is short on purpose so
#: a flapping primary surfaces quickly to the dashboard.
_PRIMARY_HEALTH_CACHE: dict[str, float | bool] = {
    "value": False,
    "expires_at": 0.0,
}
_PRIMARY_HEALTH_TTL_S: float = 5.0


def primary_healthy(
    probe: Callable[[], bool] | None = None,
    ttl_s: float = _PRIMARY_HEALTH_TTL_S,
) -> bool:
    """Return whether the primary region is currently healthy.

    ``probe`` is an injectable callable so tests + deep-health can pass
    their own check (HTTP, DB ping, etc.).  Defaults to a "we ARE the
    primary, so we're healthy if we got this far" self-affirmation,
    which is what the standby would also use (it just returns False
    because it is NOT primary).
    """
    now = time.time()
    expires_at = float(_PRIMARY_HEALTH_CACHE.get("expires_at", 0.0))
    if now < expires_at:
        return bool(_PRIMARY_HEALTH_CACHE["value"])

    marker = get_region_marker()
    if probe is None:
        # No external probe: a process can speak only to its own role.
        healthy = marker.is_primary
    else:
        try:
            healthy = bool(probe())
        except Exception as exc:  # noqa: BLE001
            logger.warning("primary_healthy.probe_error err=%s", exc)
            healthy = False

    _PRIMARY_HEALTH_CACHE["value"] = healthy
    _PRIMARY_HEALTH_CACHE["expires_at"] = now + ttl_s
    return healthy


def should_serve(probe: Callable[[], bool] | None = None) -> bool:
    """Active/passive admission gate.

    Returns True if this process should be answering traffic right now.
    * primary  → always True (it IS the primary).
    * standby  → True only if primary is *un*healthy.
    * unknown  → True (fail-open: dev laptops, single-region setups).
    """
    marker = get_region_marker()
    if marker.is_primary:
        return True
    if marker.is_standby:
        return not primary_healthy(probe)
    return True


def stamp_region_meta(payload: dict[str, object]) -> dict[str, object]:
    """Attach the region marker to a response ``_meta`` block in-place-safe.

    Convenience for routes / deep-health to surface region role without
    each caller re-implementing the merge.
    """
    if not isinstance(payload, dict):
        return payload
    marker = get_region_marker()
    meta_raw = payload.get("_meta") or payload.get("meta") or {}
    meta = dict(meta_raw) if isinstance(meta_raw, dict) else {}
    meta["region"] = marker.to_dict()
    out = dict(payload)
    out["_meta"] = meta
    if "meta" in payload:
        out["meta"] = meta
    return out


__all__ = [
    "DEFAULT_PRIMARY_REGION",
    "DEFAULT_STANDBY_REGION",
    "RegionMarker",
    "get_region_marker",
    "primary_healthy",
    "should_serve",
    "stamp_region_meta",
]
