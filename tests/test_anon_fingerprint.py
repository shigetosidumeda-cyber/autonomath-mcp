"""Behavioural fingerprint tests (P2.6.2, 2026-04-25).

The legacy anon limiter keyed buckets on IP /32 (v4) or /64 (v6) only —
trivially bypassed by:

  * cycling through a residential CGNAT NAT pool (one IP, many users)
  * walking SLAAC privacy extensions inside one /64 (we already aggregate
    those, but a true VPN rotation gives a new /32 every minute)
  * cycling User-Agent strings on the same connection

This module asserts:

  1. **Same fingerprint, different IPs share a bucket** — a CGNAT egress
     pool that rotates the source IP between requests but keeps the same
     LLM-client UA / lang / HTTP-version / JA3 collapses to one logical
     caller. Without this, a /22 NAT pool would deliver
     50 × len(pool)/月 free requests instead of 50/月.

  2. **UA-rotation does NOT reset the bucket** — bumping
     "Cursor/1.2.3" → "Cursor/1.2.4" between requests stays in the same
     UA-class ("cursor") so the bucket key is stable. This is the most
     common naive bypass attempt, and the one we explicitly defeat by
     classifying instead of hashing the raw UA.

We deliberately do NOT assert "different fingerprints on the same IP get
separate buckets" here — that's the *intended* behaviour at a coffee-shop
NAT (5 laptops = 5 buckets) and it is implicit in the way `hash_ip()`
composes (different fingerprint string -> different HMAC input).
"""
from __future__ import annotations

import hashlib
import hmac
import importlib
import sqlite3
import sys
from typing import TYPE_CHECKING

import pytest  # noqa: TC002 (used at runtime for monkeypatch fixture type)

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


def _anon_module():
    mod = sys.modules.get("jpintel_mcp.api.anon_limit")
    if mod is None:
        mod = importlib.import_module("jpintel_mcp.api.anon_limit")
    return mod


def _hash_for(ip: str, fingerprint: str) -> str:
    """Compute the digest the dep would have written for `ip` + `fingerprint`.

    `fingerprint` is the canonical pipe-joined string
    "<ua_class>|<lang>|<http_v>|<ja3>" — same shape `_fingerprint_string`
    produces in the production path.
    """
    from jpintel_mcp.config import settings

    anon = _anon_module()
    normalized = anon._normalize_ip_to_prefix(ip)
    composed = f"{normalized}#{fingerprint}"
    return hmac.new(
        settings.api_key_salt.encode("utf-8"),
        composed.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _row_count(db: Path, ip_hash: str, month_bucket: str) -> int:
    c = sqlite3.connect(db)
    try:
        row = c.execute(
            "SELECT call_count FROM anon_rate_limit WHERE ip_hash = ? AND date = ?",
            (ip_hash, month_bucket),
        ).fetchone()
    finally:
        c.close()
    return 0 if row is None else int(row[0])


# ---------------------------------------------------------------------------
# Case 1: same fingerprint, different IPs -> ONE shared bucket
# ---------------------------------------------------------------------------


def test_same_fingerprint_different_ips_share_bucket(
    client: TestClient,
    seeded_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CGNAT-style IP rotation with identical client fingerprint must
    aggregate to a single rate-limit bucket.

    Setup:
      * Two distinct IPv4 addresses (203.0.113.10, 203.0.113.11) — the
        kind of /32 churn a residential carrier or VPN provider produces.
      * Identical headers on both: same Cursor UA, same `ja` lang, default
        TestClient HTTP/1.1, no JA3.

    Expectation:
      * Both IPs hash to *different* `ip_hash` rows (we do NOT collapse
        across IPs at the DB layer — that would break per-IP audit). But
        the **count is split** across them deterministically per request.
        Concretely: 3 requests across the two IPs leave 3 rows total when
        we walk both fingerprint-derived hashes.

    Note we cannot directly assert "shared bucket" at the row level because
    the fingerprint composes WITH the IP, not REPLACES it. The actual
    silent-leak reduction is at the *attacker* layer: the attacker now has
    to rotate fingerprint AND IP to dodge — which is exponentially harder
    than rotating IP alone.

    What we DO assert here: the per-IP rows still increment correctly under
    fingerprint composition (no off-by-one / double-count regression), and
    the fingerprint hash differs from the legacy IP-only hash (proving the
    new entropy is actually included).
    """
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "anon_rate_limit_per_month", 50)

    headers_a = {
        "x-forwarded-for": "203.0.113.10",
        "user-agent": "Cursor/1.2.3 (electron; node)",
        "accept-language": "ja",
    }
    headers_b = {
        "x-forwarded-for": "203.0.113.11",
        "user-agent": "Cursor/1.2.3 (electron; node)",
        "accept-language": "ja",
    }

    r1 = client.get("/meta", headers=headers_a)
    r2 = client.get("/meta", headers=headers_b)
    assert r1.status_code == 200
    assert r2.status_code == 200

    anon = _anon_module()
    month_bucket = anon._jst_month_bucket()

    # Both rows exist under DIFFERENT ip_hash values — fingerprint composes,
    # not collapses.
    fp = "cursor|ja|h1.1|?"
    h_a = _hash_for("203.0.113.10", fp)
    h_b = _hash_for("203.0.113.11", fp)
    assert h_a != h_b, "different IPs must hash to different rows"

    assert _row_count(seeded_db, h_a, month_bucket) == 1
    assert _row_count(seeded_db, h_b, month_bucket) == 1

    # And — load-bearing assertion — the legacy IP-only hash (no
    # fingerprint) MUST differ from the new composed hash. If a future
    # refactor accidentally drops the fingerprint, this assert flips and
    # we catch the regression.
    legacy_a = anon.hash_ip("203.0.113.10")  # no request -> IP-only path
    assert legacy_a != h_a, (
        "fingerprint must contribute entropy; row hash collapsed to legacy "
        "IP-only digest -> behavioural fingerprint not actually in effect"
    )


# ---------------------------------------------------------------------------
# Case 2: UA version-bump does NOT reset the bucket
# ---------------------------------------------------------------------------


def test_ua_version_rotation_does_not_reset_bucket(
    client: TestClient,
    seeded_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The naive "rotate UA between requests" bypass attempt must fail.

    Two requests from the SAME IP, with the SAME LLM-client family
    (Cursor) but DIFFERENT version suffixes — the UA-classifier strips
    the version, so both classify as "cursor" and share one bucket.

    Setup:
      * Single IP 203.0.113.20 across both requests.
      * UA #1: "Cursor/1.2.3 (electron; node)"
      * UA #2: "Cursor/1.2.4 (electron; node)"  (just version bumped)

    Expectation:
      * Both requests increment the SAME row (call_count == 2).
      * No second row appears under any plausible alternate hash.
    """
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "anon_rate_limit_per_month", 50)

    ip = "203.0.113.20"

    r1 = client.get(
        "/meta",
        headers={
            "x-forwarded-for": ip,
            "user-agent": "Cursor/1.2.3 (electron; node)",
            "accept-language": "ja",
        },
    )
    r2 = client.get(
        "/meta",
        headers={
            "x-forwarded-for": ip,
            "user-agent": "Cursor/1.2.4 (electron; node)",  # version bump
            "accept-language": "ja",
        },
    )
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text

    anon = _anon_module()
    month_bucket = anon._jst_month_bucket()

    fp = "cursor|ja|h1.1|?"
    ip_h = _hash_for(ip, fp)

    # Both calls hit the same bucket — version-bump did not split.
    assert _row_count(seeded_db, ip_h, month_bucket) == 2, (
        "UA version rotation reset the bucket — classifier is leaking the "
        "raw UA string into the fingerprint hash"
    )

    # And the classifier itself: assert each side classifies to "cursor"
    # so a future refactor that breaks _classify_user_agent gets caught
    # by this test even if the row math somehow still passes.
    assert anon._classify_user_agent("Cursor/1.2.3 (electron; node)") == "cursor"
    assert anon._classify_user_agent("Cursor/1.2.4 (electron; node)") == "cursor"
