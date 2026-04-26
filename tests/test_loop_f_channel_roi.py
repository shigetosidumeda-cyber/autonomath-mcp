"""Tests for loop_f_channel_roi.

Covers the launch-v1 happy path: synthesised subscribers + billing_events
feed the loop, which buckets by channel, computes paid_conversion + LTV,
and writes a JSON report. Asserts INV-21 (no PII in the report) and the
`feedback_organic_only_no_ads` invariant (no ad-spend recommendation).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from jpintel_mcp.self_improve import loop_f_channel_roi as loop_f

if TYPE_CHECKING:
    from pathlib import Path


def _fake_subscribers() -> list[dict[str, object]]:
    """Synthetic subscribers spread across multiple channels.

    Channel distribution:
        organic_search   -> 12 (high N) -- google referer
        github           -> 5  (low N)  -- explicit utm_source
        blog             -> 3  (low N)  -- zenn referer
        direct           -> 2  (low N)  -- no utm, no referer
    """
    rows: list[dict[str, object]] = []
    # organic_search via referer
    for i in range(12):
        rows.append(
            {
                "api_key_hash": f"ak_search_{i:02d}",
                "referer": "https://google.com/search?q=mcp+server",
                "email": "alice@example.co.jp",  # PII — must NEVER reach report
            }
        )
    # github via explicit utm_source
    for i in range(5):
        rows.append(
            {
                "api_key_hash": f"ak_gh_{i:02d}",
                "utm_source": "github",
                "email": "bob@example.com",
            }
        )
    # blog via zenn referer
    for i in range(3):
        rows.append(
            {
                "api_key_hash": f"ak_blog_{i:02d}",
                "referer": "https://zenn.dev/some-author/articles/foo",
            }
        )
    # direct (no signal)
    rows.append({"api_key_hash": "ak_direct_00"})
    rows.append({"api_key_hash": "ak_direct_01", "referer": "", "utm_source": ""})

    # Contamination: missing api_key_hash -> dropped (INV-21: cannot tie
    # revenue without the hash, and we will NOT join on email).
    rows.append({"email": "spam@example.com", "utm_source": "github"})
    rows.append({"api_key_hash": "", "utm_source": "github"})
    return rows


def _fake_billing_events() -> list[dict[str, object]]:
    """Revenue events. Six search customers paid ¥3000 each (1000 reqs ×
    ¥3); two github customers paid ¥600 each. Blog & direct didn't convert.
    """
    rows: list[dict[str, object]] = []
    for i in range(6):
        rows.append(
            {
                "api_key_hash": f"ak_search_{i:02d}",
                "amount_jpy": 3000,
                "occurred_at": "2026-04-20T10:00:00Z",
            }
        )
    for i in range(2):
        rows.append(
            {
                "api_key_hash": f"ak_gh_{i:02d}",
                "amount_jpy": 600,
                "occurred_at": "2026-04-21T10:00:00Z",
            }
        )
    # Refund / zero-amount row -> filtered out.
    rows.append({"api_key_hash": "ak_search_00", "amount_jpy": 0})
    # Unknown api_key_hash -> filtered (no subscriber to attribute to).
    rows.append({"api_key_hash": "ak_unknown_99", "amount_jpy": 9999})
    return rows


def test_loop_f_aggregates_channel_roi(tmp_path: Path):
    out_path = tmp_path / "channel_roi_report.json"
    subs = _fake_subscribers()
    events = _fake_billing_events()

    result = loop_f.run(
        dry_run=False,
        subscribers=subs,
        billing_events=events,
        out_path=out_path,
    )

    assert result["loop"] == "loop_f_channel_roi"
    assert result["scanned"] == len(subs)
    # actions_proposed counts channels with paid_28d > 0 AND confidence != 'low'.
    # Only organic_search (12 signups -> medium, 6 paid) qualifies. github has
    # 5 signups (low), blog has 3 (low), direct has 2 (low).
    assert result["actions_proposed"] == 1
    assert result["actions_executed"] == 1

    body = out_path.read_text(encoding="utf-8")
    report = json.loads(body)
    assert report["window_days"] == 28
    by_ch = {c["channel"]: c for c in report["channels"]}

    # The four channels we seeded all surface (low-confidence ones included).
    assert set(by_ch) == {"organic_search", "github", "blog", "direct"}

    search = by_ch["organic_search"]
    assert search["signups_28d"] == 12
    assert search["paid_28d"] == 6
    assert search["paid_conversion_rate"] == 0.5
    assert search["revenue_28d_jpy"] == 18000  # 6 * ¥3000
    assert search["ltv_jpy"] == 1500.0  # 18000 / 12
    assert search["confidence"] == "medium"  # 12 in 10..29

    gh = by_ch["github"]
    assert gh["signups_28d"] == 5
    assert gh["paid_28d"] == 2
    assert gh["revenue_28d_jpy"] == 1200  # 2 * ¥600
    assert gh["confidence"] == "low"  # 5 < N_MEDIUM

    blog = by_ch["blog"]
    assert blog["paid_28d"] == 0
    assert blog["paid_conversion_rate"] == 0.0
    assert blog["revenue_28d_jpy"] == 0

    direct = by_ch["direct"]
    assert direct["signups_28d"] == 2
    assert direct["paid_28d"] == 0

    # INV-21: PII (email) must NEVER reach the report.
    assert "alice@example.co.jp" not in body
    assert "bob@example.com" not in body
    assert "@" not in body  # no email-shaped strings anywhere

    # `feedback_organic_only_no_ads`: no ad-spend recommendation.
    assert "ad_spend" not in body
    assert "budget" not in body
    assert "cac" not in body.lower()  # we set cac=0 implicitly; no field surfaces it


def test_loop_f_no_subscribers_returns_zeroed_scaffold():
    """Pre-launch: orchestrator hasn't wired subscribers yet."""
    out = loop_f.run(dry_run=True)
    assert out == {
        "loop": "loop_f_channel_roi",
        "scanned": 0,
        "actions_proposed": 0,
        "actions_executed": 0,
    }


def test_loop_f_bucket_channel_pure_helper():
    """Sanity-check the channel router in isolation."""
    assert loop_f.bucket_channel(referer="https://google.com/search") == "organic_search"
    assert loop_f.bucket_channel(referer="https://github.com/foo") == "github"
    assert loop_f.bucket_channel(referer="https://zenn.dev/x/articles/y") == "blog"
    assert loop_f.bucket_channel(utm_source="github") == "github"
    assert loop_f.bucket_channel(utm_source="zenn") == "blog"
    assert loop_f.bucket_channel(utm_source="mcp.so") == "mcp_registry"
    assert loop_f.bucket_channel(utm_source="partnership") == "partnerships"
    assert loop_f.bucket_channel() == "direct"
    assert loop_f.bucket_channel(referer="", utm_source="") == "direct"
    # Unknown utm with unknown referer -> 'other' so label drift is visible.
    assert loop_f.bucket_channel(utm_source="weird-source") == "other"
