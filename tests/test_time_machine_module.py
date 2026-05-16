"""Unit tests for Wave 51 dim Q time-machine module.

Covers ``src/jpintel_mcp/time_machine/``:

  * :class:`Snapshot` validation (id regex / content_hash hex / payload)
  * :class:`SnapshotRegistry` put / get / list / atomic write
  * :func:`query_as_of` nearest-≤ semantics + out-of-range branches
  * :func:`counterfactual_diff` add / remove / change / unchanged
  * :meth:`SnapshotRegistry.prune_old_snapshots` 60-month retention +
    audit emit + audit JSONL append + retention floor guard

Naming
------
``test_time_machine_module.py`` (not ``test_time_machine.py``) because
the latter already covers the legacy DEEP-22 SQLite-backed time-machine
tools at ``mcp/autonomath_tools/time_machine_tools.py``. The two suites
exercise different subsystems and must not share a filename.

No mocks: the registry is filesystem-only, so every test uses
``tmp_path`` and writes real JSON files. The sample-snapshot generator
script is also exercised end-to-end via ``_load_sample_registry``.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from jpintel_mcp.time_machine import (
    RETENTION_MONTHS,
    DiffResult,
    PruneResult,
    Snapshot,
    SnapshotNotFoundError,
    SnapshotRegistry,
    SnapshotResult,
    counterfactual_diff,
    query_as_of,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_ROOT = REPO_ROOT / "data" / "snapshots" / "sample"


# ---------------------------------------------------------------------------
# Snapshot model — basic validation
# ---------------------------------------------------------------------------


def _hex64(token: str = "a") -> str:
    """Return a 64-char lowercase-hex placeholder for ``content_hash``."""
    return (token * 64)[:64]


def test_snapshot_round_trips_through_model_validate() -> None:
    """Snapshot.model_validate_json round-trips a put-shaped record."""
    payload = {"k": "v", "n": 7}
    digest = Snapshot.compute_content_hash(payload)
    snap = Snapshot(
        snapshot_id="programs@2024_03",
        as_of_date=date(2024, 3, 31),
        source_dataset_id="programs",
        content_hash=digest,
        payload=payload,
    )
    blob = snap.model_dump_json()
    restored = Snapshot.model_validate_json(blob)
    assert restored == snap


def test_snapshot_id_regex_rejects_bad_bucket() -> None:
    """snapshot_id must match '<dataset>@<yyyy_mm>'."""
    with pytest.raises(ValueError, match="snapshot_id"):
        Snapshot(
            snapshot_id="programs@2024-03",  # hyphen, not underscore
            as_of_date=date(2024, 3, 31),
            source_dataset_id="programs",
            content_hash=_hex64(),
        )


def test_snapshot_id_regex_rejects_month_zero() -> None:
    """yyyy_00 must be rejected — only 01..12 allowed."""
    with pytest.raises(ValueError, match="snapshot_id"):
        Snapshot(
            snapshot_id="programs@2024_00",
            as_of_date=date(2024, 1, 1),
            source_dataset_id="programs",
            content_hash=_hex64(),
        )


def test_snapshot_id_regex_rejects_uppercase_dataset() -> None:
    """source_dataset_id must be lowercase."""
    with pytest.raises(ValueError, match="snapshot_id"):
        Snapshot(
            snapshot_id="Programs@2024_03",
            as_of_date=date(2024, 3, 31),
            source_dataset_id="programs",
            content_hash=_hex64(),
        )


def test_snapshot_content_hash_rejects_uppercase() -> None:
    """content_hash must be 64-char lowercase hex."""
    with pytest.raises(ValueError, match="content_hash"):
        Snapshot(
            snapshot_id="programs@2024_03",
            as_of_date=date(2024, 3, 31),
            source_dataset_id="programs",
            content_hash="A" * 64,
        )


def test_snapshot_compute_content_hash_is_order_invariant() -> None:
    """Re-ordered keys produce the same digest (sorted-key canonicalisation)."""
    a = Snapshot.compute_content_hash({"x": 1, "y": 2})
    b = Snapshot.compute_content_hash({"y": 2, "x": 1})
    assert a == b


def test_snapshot_compute_content_hash_differs_on_value_change() -> None:
    """A single value flip changes the digest."""
    a = Snapshot.compute_content_hash({"x": 1})
    b = Snapshot.compute_content_hash({"x": 2})
    assert a != b


def test_snapshot_bucket_helper() -> None:
    """Snapshot.bucket() returns the yyyy_mm portion only."""
    snap = Snapshot(
        snapshot_id="programs@2024_03",
        as_of_date=date(2024, 3, 31),
        source_dataset_id="programs",
        content_hash=_hex64(),
    )
    assert snap.bucket() == "2024_03"


# ---------------------------------------------------------------------------
# SnapshotRegistry — put / get / list / atomic write
# ---------------------------------------------------------------------------


def _make_snapshot(
    dataset: str,
    bucket: str,
    as_of: date,
    payload: dict[str, object] | None = None,
) -> Snapshot:
    body: dict[str, object] = payload if payload is not None else {"v": 1}
    return Snapshot(
        snapshot_id=f"{dataset}@{bucket}",
        as_of_date=as_of,
        source_dataset_id=dataset,
        content_hash=Snapshot.compute_content_hash(body),
        payload=body,
    )


def test_registry_put_creates_bucket_dir(tmp_path: Path) -> None:
    """put() writes to <root>/<yyyy_mm>/<dataset>.json."""
    reg = SnapshotRegistry(tmp_path)
    snap = _make_snapshot("programs", "2024_03", date(2024, 3, 31))
    out = reg.put(snap)
    assert out == tmp_path / "2024_03" / "programs.json"
    assert out.exists()


def test_registry_put_is_idempotent(tmp_path: Path) -> None:
    """Re-putting the same snapshot overwrites with identical bytes."""
    reg = SnapshotRegistry(tmp_path)
    snap = _make_snapshot("programs", "2024_03", date(2024, 3, 31))
    p1 = reg.put(snap)
    bytes_1 = p1.read_bytes()
    p2 = reg.put(snap)
    bytes_2 = p2.read_bytes()
    assert p1 == p2
    assert bytes_1 == bytes_2


def test_registry_put_no_dot_tmp_left_over(tmp_path: Path) -> None:
    """The .json.tmp atomic-rename helper does not litter the bucket dir."""
    reg = SnapshotRegistry(tmp_path)
    snap = _make_snapshot("programs", "2024_03", date(2024, 3, 31))
    reg.put(snap)
    bucket = tmp_path / "2024_03"
    leftovers = [p.name for p in bucket.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_registry_get_returns_round_trip(tmp_path: Path) -> None:
    """get() deserialises the same Snapshot a put() wrote."""
    reg = SnapshotRegistry(tmp_path)
    snap = _make_snapshot("programs", "2024_03", date(2024, 3, 31))
    reg.put(snap)
    out = reg.get("programs@2024_03")
    assert out == snap


def test_registry_get_raises_on_missing(tmp_path: Path) -> None:
    """get() raises SnapshotNotFoundError when the file does not exist."""
    reg = SnapshotRegistry(tmp_path)
    with pytest.raises(SnapshotNotFoundError):
        reg.get("programs@2024_03")


def test_registry_list_for_dataset_sorted_by_as_of(tmp_path: Path) -> None:
    """list_for_dataset returns snapshots in as_of_date ascending order."""
    reg = SnapshotRegistry(tmp_path)
    reg.put(_make_snapshot("programs", "2024_06", date(2024, 6, 30)))
    reg.put(_make_snapshot("programs", "2024_03", date(2024, 3, 31)))
    reg.put(_make_snapshot("programs", "2024_09", date(2024, 9, 30)))
    out = reg.list_for_dataset("programs")
    assert [s.snapshot_id for s in out] == [
        "programs@2024_03",
        "programs@2024_06",
        "programs@2024_09",
    ]


def test_registry_list_for_dataset_empty_root_returns_empty(tmp_path: Path) -> None:
    """A registry rooted at a non-existent path returns []."""
    reg = SnapshotRegistry(tmp_path / "does_not_exist")
    assert reg.list_for_dataset("programs") == []


def test_registry_list_buckets_sorted(tmp_path: Path) -> None:
    """list_buckets returns yyyy_mm directories sorted asc."""
    reg = SnapshotRegistry(tmp_path)
    reg.put(_make_snapshot("programs", "2025_03", date(2025, 3, 31)))
    reg.put(_make_snapshot("programs", "2023_12", date(2023, 12, 31)))
    reg.put(_make_snapshot("programs", "2024_06", date(2024, 6, 30)))
    assert reg.list_buckets() == ["2023_12", "2024_06", "2025_03"]


# ---------------------------------------------------------------------------
# query_as_of — nearest ≤ semantics + out-of-range branches
# ---------------------------------------------------------------------------


def _seed_three_quarters(reg: SnapshotRegistry) -> None:
    """Seed Q1/Q2/Q3 2024 snapshots for the query suite."""
    reg.put(_make_snapshot("programs", "2024_03", date(2024, 3, 31)))
    reg.put(_make_snapshot("programs", "2024_06", date(2024, 6, 30)))
    reg.put(_make_snapshot("programs", "2024_09", date(2024, 9, 30)))


def test_query_as_of_exact_match(tmp_path: Path) -> None:
    """An exact as_of_date hit returns that snapshot."""
    reg = SnapshotRegistry(tmp_path)
    _seed_three_quarters(reg)
    out = query_as_of(reg, "programs", date(2024, 6, 30))
    assert isinstance(out, SnapshotResult)
    assert out.reason == "ok"
    assert out.nearest is not None
    assert out.nearest.snapshot_id == "programs@2024_06"


def test_query_as_of_between_snapshots_picks_floor(tmp_path: Path) -> None:
    """Dates between two snapshots return the latest one ≤ target."""
    reg = SnapshotRegistry(tmp_path)
    _seed_three_quarters(reg)
    out = query_as_of(reg, "programs", date(2024, 7, 15))
    assert out.reason == "ok"
    assert out.nearest is not None
    assert out.nearest.snapshot_id == "programs@2024_06"


def test_query_as_of_after_last_returns_last(tmp_path: Path) -> None:
    """A date after every snapshot returns the most recent one."""
    reg = SnapshotRegistry(tmp_path)
    _seed_three_quarters(reg)
    out = query_as_of(reg, "programs", date(2030, 1, 1))
    assert out.reason == "ok"
    assert out.nearest is not None
    assert out.nearest.snapshot_id == "programs@2024_09"


def test_query_as_of_before_first_returns_marker(tmp_path: Path) -> None:
    """A date before the first capture returns ``before_first_capture``."""
    reg = SnapshotRegistry(tmp_path)
    _seed_three_quarters(reg)
    out = query_as_of(reg, "programs", date(2020, 1, 1))
    assert out.reason == "before_first_capture"
    assert out.nearest is None


def test_query_as_of_no_snapshots_marker(tmp_path: Path) -> None:
    """A dataset with zero snapshots returns ``no_snapshots``."""
    reg = SnapshotRegistry(tmp_path)
    out = query_as_of(reg, "programs", date(2024, 6, 30))
    assert out.reason == "no_snapshots"
    assert out.nearest is None


# ---------------------------------------------------------------------------
# counterfactual_diff
# ---------------------------------------------------------------------------


def test_diff_identical_snapshots() -> None:
    """Identical payloads produce zero changed/added/removed + content_hash_changed=False."""
    payload = {"x": 1, "y": "a"}
    a = _make_snapshot("programs", "2024_03", date(2024, 3, 31), payload)
    b = _make_snapshot("programs", "2024_06", date(2024, 6, 30), payload)
    out = counterfactual_diff(a, b)
    assert isinstance(out, DiffResult)
    assert out.added == ()
    assert out.removed == ()
    assert out.changed == ()
    assert set(out.unchanged) == {"x", "y"}
    assert out.content_hash_changed is False
    assert out.is_identical() is True


def test_diff_added_key() -> None:
    """A key present only in B is reported as added."""
    a = _make_snapshot("programs", "2024_03", date(2024, 3, 31), {"x": 1})
    b = _make_snapshot("programs", "2024_06", date(2024, 6, 30), {"x": 1, "y": 2})
    out = counterfactual_diff(a, b)
    assert out.added == ("y",)
    assert out.removed == ()
    assert out.changed == ()
    assert out.unchanged == ("x",)
    assert out.content_hash_changed is True


def test_diff_removed_key() -> None:
    """A key present only in A is reported as removed."""
    a = _make_snapshot("programs", "2024_03", date(2024, 3, 31), {"x": 1, "y": 2})
    b = _make_snapshot("programs", "2024_06", date(2024, 6, 30), {"x": 1})
    out = counterfactual_diff(a, b)
    assert out.added == ()
    assert out.removed == ("y",)
    assert out.changed == ()
    assert out.unchanged == ("x",)


def test_diff_changed_value() -> None:
    """A key present in both with differing values is reported as changed."""
    a = _make_snapshot("programs", "2024_03", date(2024, 3, 31), {"x": 1})
    b = _make_snapshot("programs", "2024_06", date(2024, 6, 30), {"x": 2})
    out = counterfactual_diff(a, b)
    assert out.added == ()
    assert out.removed == ()
    assert out.changed == ("x",)
    assert out.unchanged == ()
    assert out.is_identical() is False


def test_diff_mixed_keys_are_sorted() -> None:
    """Every set field in DiffResult is sorted asc for stable audit logs."""
    a = _make_snapshot(
        "programs", "2024_03", date(2024, 3, 31),
        {"b": 1, "c": 2, "d": 3},
    )
    b = _make_snapshot(
        "programs", "2024_06", date(2024, 6, 30),
        {"a": 9, "c": 99, "d": 3, "e": 8},
    )
    out = counterfactual_diff(a, b)
    # 'a','e' added; 'b' removed; 'c' changed; 'd' unchanged.
    assert out.added == ("a", "e")
    assert out.removed == ("b",)
    assert out.changed == ("c",)
    assert out.unchanged == ("d",)
    # Tuples sorted ascending — verify lexicographic order.
    assert list(out.added) == sorted(out.added)


# ---------------------------------------------------------------------------
# prune_old_snapshots — 60-month retention + audit
# ---------------------------------------------------------------------------


def _seed_n_buckets(reg: SnapshotRegistry, n: int) -> list[str]:
    """Seed ``n`` synthetic monthly buckets starting at 2020-01."""
    ids: list[str] = []
    year, month = 2020, 1
    for i in range(n):
        bucket = f"{year:04d}_{month:02d}"
        as_of = date(year, month, 28)  # 28 = safe across feb
        snap = _make_snapshot("programs", bucket, as_of, {"i": i})
        reg.put(snap)
        ids.append(snap.snapshot_id)
        month += 1
        if month > 12:
            month = 1
            year += 1
    return ids


def test_prune_keeps_default_60_buckets(tmp_path: Path) -> None:
    """Default prune retains the newest RETENTION_MONTHS buckets."""
    reg = SnapshotRegistry(tmp_path)
    _seed_n_buckets(reg, 65)  # 5 over the 60-month cap
    result = reg.prune_old_snapshots()
    assert isinstance(result, PruneResult)
    assert len(result.pruned_ids) == 5
    assert result.retained_count == 60
    assert len(reg.list_buckets()) == 60


def test_prune_under_retention_is_noop(tmp_path: Path) -> None:
    """Prune with fewer buckets than retention is a no-op."""
    reg = SnapshotRegistry(tmp_path)
    _seed_n_buckets(reg, 12)
    result = reg.prune_old_snapshots()
    assert result.pruned_ids == ()
    assert result.retained_count == 12
    assert len(reg.list_buckets()) == 12


def test_prune_retention_floor_guard(tmp_path: Path) -> None:
    """retention_months < 1 raises ValueError."""
    reg = SnapshotRegistry(tmp_path)
    with pytest.raises(ValueError, match="retention_months"):
        reg.prune_old_snapshots(retention_months=0)


def test_prune_audit_emit_callback_fires(tmp_path: Path) -> None:
    """audit_emit fires once per pruned snapshot, ordered oldest first."""
    reg = SnapshotRegistry(tmp_path)
    _seed_n_buckets(reg, 8)
    events: list[dict[str, object]] = []
    result = reg.prune_old_snapshots(
        retention_months=5,
        audit_emit=events.append,
    )
    assert len(events) == 3
    assert [e["snapshot_id"] for e in events] == list(result.pruned_ids)
    # Events ordered oldest first (2020-01 / 02 / 03 buckets get pruned).
    assert events[0]["bucket"] == "2020_01"
    assert events[-1]["bucket"] == "2020_03"


def test_prune_audit_path_writes_jsonl(tmp_path: Path) -> None:
    """audit_path JSONL receives one row per deletion."""
    reg = SnapshotRegistry(tmp_path)
    _seed_n_buckets(reg, 8)
    audit_path = tmp_path / "audit" / "dim_q_prune.jsonl"
    result = reg.prune_old_snapshots(
        retention_months=5,
        audit_path=audit_path,
    )
    assert result.audit_path == audit_path
    assert audit_path.exists()
    rows = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 3
    assert {"snapshot_id", "source_dataset_id", "as_of_date", "bucket"} == set(
        rows[0].keys()
    )


def test_retention_months_constant_is_60() -> None:
    """RETENTION_MONTHS is the 5-year constant per dim Q spec."""
    assert RETENTION_MONTHS == 60


# ---------------------------------------------------------------------------
# Sample-snapshot generator end-to-end
# ---------------------------------------------------------------------------


def test_sample_snapshots_present_under_data_snapshots_sample() -> None:
    """The 12 quarterly sample snapshots are committed to the tree."""
    reg = SnapshotRegistry(SAMPLE_ROOT)
    snaps = reg.list_for_dataset("programs")
    assert len(snaps) == 12
    # First = Q2 2023; last = Q1 2026.
    assert snaps[0].as_of_date == date(2023, 6, 30)
    assert snaps[-1].as_of_date == date(2026, 3, 31)


def test_sample_snapshot_query_at_2024q3() -> None:
    """A query at 2024-08-15 returns the Q2 2024 snapshot (≤ rule)."""
    reg = SnapshotRegistry(SAMPLE_ROOT)
    out = query_as_of(reg, "programs", date(2024, 8, 15))
    assert out.reason == "ok"
    assert out.nearest is not None
    assert out.nearest.snapshot_id == "programs@2024_06"


def test_sample_snapshot_counterfactual_amount_changed() -> None:
    """Counterfactual between Q2 2023 and Q1 2026 surfaces ``program_001`` change."""
    reg = SnapshotRegistry(SAMPLE_ROOT)
    a = reg.get("programs@2023_06")
    b = reg.get("programs@2026_03")
    out = counterfactual_diff(a, b)
    assert "program_001" in out.changed
    assert out.content_hash_changed is True
