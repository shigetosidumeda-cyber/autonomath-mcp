#!/usr/bin/env python3
"""Generate 12 sample dim Q snapshots — 1 per quarter for last 3 years.

Writes deterministic synthetic snapshots under
``data/snapshots/sample/<yyyy_mm>/`` for testing the time-machine
primitives end-to-end without touching the production
``data/snapshots/`` tree (which the dim Q monthly batch owns).

Why ``data/snapshots/sample/`` and not the root
``data/snapshots/``?
    The root path is owned by the production monthly snapshot batch
    (``scripts/cron/snapshot_monthly_state.py``). Co-locating sample
    data in the same root would let a test query accidentally walk
    production buckets and vice versa. The ``sample/`` subdirectory
    isolates the fixture corpus.

Determinism
    The snapshot payload uses a tiny synthetic ``program_001`` row whose
    ``amount_max_yen`` walks from ¥10M (Q2 2023) to ¥21M (Q1 2026) in
    +¥1M increments and ``rate_max`` walks from 0.50 to 0.61 in +0.01
    increments. The ``content_hash`` is recomputed via
    :meth:`Snapshot.compute_content_hash` so re-running this script
    produces byte-identical files.

Usage
    .venv/bin/python scripts/etl/generate_dim_q_sample_snapshots.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

# Make ``src/`` importable when invoked directly via the venv.
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from jpintel_mcp.time_machine import Snapshot, SnapshotRegistry  # noqa: E402

#: Quarter buckets covering the last 3 years (12 snapshots).
#: Buckets pick the **last month of each quarter** so the
#: ``as_of_date`` is the end-of-quarter date a 税理士 audit would query.
_QUARTERS: list[tuple[str, date]] = [
    ("2023_06", date(2023, 6, 30)),
    ("2023_09", date(2023, 9, 30)),
    ("2023_12", date(2023, 12, 31)),
    ("2024_03", date(2024, 3, 31)),
    ("2024_06", date(2024, 6, 30)),
    ("2024_09", date(2024, 9, 30)),
    ("2024_12", date(2024, 12, 31)),
    ("2025_03", date(2025, 3, 31)),
    ("2025_06", date(2025, 6, 30)),
    ("2025_09", date(2025, 9, 30)),
    ("2025_12", date(2025, 12, 31)),
    ("2026_03", date(2026, 3, 31)),
]


def _build_snapshot(bucket: str, as_of: date, index: int) -> Snapshot:
    """Build one synthetic ``programs`` snapshot for ``bucket``.

    ``index`` is the 0-based quarter index used to derive the
    deterministic walk on ``amount_max_yen`` / ``rate_max``.
    """
    payload: dict[str, object] = {
        "program_001": {
            "name": "ものづくり補助金",
            "amount_max_yen": 10_000_000 + index * 1_000_000,
            "rate_max": round(0.50 + index * 0.01, 2),
            "eligibility": {
                "min_employees": 1,
                "max_employees": 300 if index < 8 else 500,
            },
        },
        "program_count": 1,
        "captured_dataset_id": "programs_sample",
    }
    content_hash = Snapshot.compute_content_hash(payload)
    return Snapshot(
        snapshot_id=f"programs@{bucket}",
        as_of_date=as_of,
        source_dataset_id="programs",
        content_hash=content_hash,
        payload=payload,
    )


def main() -> int:
    """Generate 12 sample snapshots; return shell exit code."""
    sample_root = REPO_ROOT / "data" / "snapshots" / "sample"
    registry = SnapshotRegistry(sample_root)
    written: list[str] = []
    for idx, (bucket, as_of) in enumerate(_QUARTERS):
        snap = _build_snapshot(bucket, as_of, idx)
        path = registry.put(snap)
        written.append(str(path.relative_to(REPO_ROOT)))
    print(f"wrote {len(written)} sample snapshots under {sample_root.relative_to(REPO_ROOT)}/")
    for rel in written:
        print(f"  {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
