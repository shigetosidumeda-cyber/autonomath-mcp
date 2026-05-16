"""Unit tests for the acceptance probability cohort packet generator.

We test the pure-Python pieces (Wilson CI, scale_band, packet renderer,
known_gap selection, adjacency attach) directly. The DB aggregation is
covered by the integration smoke run at the script level.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "aws_credit_ops"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generate_acceptance_probability_packets as gen  # noqa: E402


def _cohort(
    *,
    n_sample: int,
    n_eligible_programs: int,
    freshest_announced_at: str | None = "2026-04-01",
    prefecture: str = "TOKYO",
    jsic_major: str = "E",
    scale_band: str = "mid",
    program_kind: str = "subsidy",
    fiscal_year: str = "2026",
) -> gen.CohortRow:
    return gen.CohortRow(
        prefecture=prefecture,
        jsic_major=jsic_major,
        scale_band=scale_band,
        program_kind=program_kind,
        fiscal_year=fiscal_year,
        n_sample=n_sample,
        n_eligible_programs=n_eligible_programs,
        freshest_announced_at=freshest_announced_at,
    )


def test_scale_band_buckets() -> None:
    assert gen.scale_band(None) == "unknown"
    assert gen.scale_band(500_000) == "micro"
    assert gen.scale_band(5_000_000) == "small"
    assert gen.scale_band(50_000_000) == "mid"
    assert gen.scale_band(500_000_000) == "large"


def test_wilson_zero_sample_returns_full_interval() -> None:
    interval = gen.wilson_95_ci(0, 0)
    assert interval.point == 0.0
    assert interval.low == 0.0
    assert interval.high == 1.0


def test_wilson_centred() -> None:
    interval = gen.wilson_95_ci(50, 100)
    assert 0.39 < interval.low < 0.41
    assert 0.59 < interval.high < 0.61
    assert interval.low < interval.point < interval.high


def test_wilson_high_proportion() -> None:
    interval = gen.wilson_95_ci(95, 100)
    assert interval.point == 0.95
    assert interval.low > 0.88
    assert interval.high < 1.0001


def test_render_packet_shape() -> None:
    cohort = _cohort(n_sample=12, n_eligible_programs=40)
    packet = gen.render_packet(
        cohort,
        generated_at=dt.datetime(2026, 5, 16, 9, 0, tzinfo=dt.UTC),
    )
    assert packet["package_kind"] == gen.PACKAGE_KIND
    header = packet["header"]
    assert isinstance(header, dict)
    assert header["object_type"] == gen.PACKAGE_KIND
    assert header["request_time_llm_call_performed"] is False
    defn = packet["cohort_definition"]
    assert isinstance(defn, dict)
    assert defn["cohort_id"] == "TOKYO.E.mid.subsidy.2026"
    ci = packet["confidence_interval"]
    assert isinstance(ci, dict)
    assert ci["method"] == "wilson_score"
    assert ci["level"] == 0.95
    assert 0.0 <= ci["low"] <= ci["high"] <= 1.0
    gaps = packet["known_gaps"]
    assert isinstance(gaps, list)
    assert any(g["gap_type"] == "professional_review_required" for g in gaps)


def test_render_packet_emits_no_hit_when_zero_sample() -> None:
    cohort = _cohort(n_sample=0, n_eligible_programs=10)
    packet = gen.render_packet(
        cohort,
        generated_at=dt.datetime(2026, 5, 16, tzinfo=dt.UTC),
    )
    gaps = packet["known_gaps"]
    assert isinstance(gaps, list)
    types = [g["gap_type"] for g in gaps]
    assert "no_hit_not_absence" in types
    assert "professional_review_required" in types


def test_render_packet_emits_stale_when_old() -> None:
    cohort = _cohort(
        n_sample=3,
        n_eligible_programs=5,
        freshest_announced_at="2023-01-01",
    )
    packet = gen.render_packet(
        cohort,
        generated_at=dt.datetime(2026, 5, 16, tzinfo=dt.UTC),
    )
    gaps = packet["known_gaps"]
    assert isinstance(gaps, list)
    types = [g["gap_type"] for g in gaps]
    assert "freshness_stale_or_unknown" in types


def test_render_packet_emits_stale_when_missing() -> None:
    cohort = _cohort(
        n_sample=1,
        n_eligible_programs=2,
        freshest_announced_at=None,
    )
    packet = gen.render_packet(
        cohort,
        generated_at=dt.datetime(2026, 5, 16, tzinfo=dt.UTC),
    )
    gaps = packet["known_gaps"]
    assert isinstance(gaps, list)
    types = [g["gap_type"] for g in gaps]
    assert "freshness_stale_or_unknown" in types


def test_packet_size_under_10kb() -> None:
    cohort = _cohort(n_sample=12, n_eligible_programs=40)
    packet = gen.render_packet(
        cohort,
        generated_at=dt.datetime(2026, 5, 16, tzinfo=dt.UTC),
    )
    body = json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2)
    assert len(body.encode("utf-8")) < gen.PACKET_MAX_BYTES


def test_attach_adjacency_surfaces_higher_probability_peers() -> None:
    packets: list[dict[str, object]] = [
        gen.render_packet(
            _cohort(
                n_sample=5,
                n_eligible_programs=100,
                program_kind="subsidy",
                fiscal_year="2026",
            ),
            generated_at=dt.datetime(2026, 5, 16, tzinfo=dt.UTC),
        ),
        gen.render_packet(
            _cohort(
                n_sample=40,
                n_eligible_programs=100,
                program_kind="loan",
                fiscal_year="2026",
            ),
            generated_at=dt.datetime(2026, 5, 16, tzinfo=dt.UTC),
        ),
        gen.render_packet(
            _cohort(
                n_sample=60,
                n_eligible_programs=100,
                program_kind="grant",
                fiscal_year="2026",
            ),
            generated_at=dt.datetime(2026, 5, 16, tzinfo=dt.UTC),
        ),
    ]
    gen.attach_adjacency(packets, max_suggestions=5)
    first = packets[0]
    suggestions = first["adjacency_suggestions"]
    assert isinstance(suggestions, list)
    assert len(suggestions) >= 1
    deltas = [s["delta"] for s in suggestions]
    for delta in deltas:
        assert isinstance(delta, float)
        assert delta > 0.0


def test_write_packet_path_uses_stable_digest(tmp_path: Path) -> None:
    cohort = _cohort(n_sample=1, n_eligible_programs=2)
    packet = gen.render_packet(
        cohort,
        generated_at=dt.datetime(2026, 5, 16, tzinfo=dt.UTC),
    )
    path = gen.write_packet(tmp_path, packet)
    assert path.exists()
    assert path.name.startswith("TOKYO.E.mid.subsidy.2026.")
    assert path.name.endswith(".json")
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["package_kind"] == gen.PACKAGE_KIND


def test_write_packet_rejects_oversize(tmp_path: Path) -> None:
    cohort = _cohort(n_sample=12, n_eligible_programs=40)
    packet = gen.render_packet(
        cohort,
        generated_at=dt.datetime(2026, 5, 16, tzinfo=dt.UTC),
    )
    packet["disclaimer"] = "X" * 12_000  # blow past the 10 KB ceiling
    with pytest.raises(ValueError, match="byte ceiling"):
        gen.write_packet(tmp_path, packet)
