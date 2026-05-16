"""Dim T predictive watch large-scale seed (Wave 48 tick#3 / tick#6 100K-scale).

Seeds predictive watch subscriptions across 3 watch_type axes (houjin /
program / amendment) into ``am_predictive_watch_subscription``, plus one
deterministic alert row per watch into ``am_predictive_alert_log``.

Default distribution (tick#3, 1000 total, locked ratio 4:4:2):

  * houjin    -> 400 rows, watch_target = "houjin_NNNN" (zero-padded 4d)
  * program   -> 400 rows, watch_target = "program_NNNN"
  * amendment -> 200 rows, watch_target = "amendment_NNNN"

Tick#6 100K-scale incremental mode (``--apply --count N``):
The same locked 4:4:2 ratio is preserved for the new batch
(houjin 0.4N / program 0.4N / amendment 0.2N). New ``watch_target``
indices start at ``MAX(existing per-type index) + 1`` so the seed
batch is additive on top of any prior run without colliding on the
``(subscriber_token_hash, watch_type, watch_target)`` triple.

Each watch gets a deterministic subscriber_token_hash (sha256 of a
fixed seed string keyed by tick + watch_type + index) and a paired
alert with delivery_status='pending' and a structural JSON payload.

LLM-0 discipline (per ``feedback_no_operator_llm_api.md``): no
``anthropic`` / ``openai`` / ``google.generativeai`` SDK imports. This
script is pure sqlite3 + stdlib hashlib. The alert payload is
structural metadata only (watch_id, watch_type, watch_target,
fired_at) — NO natural-language summary text.

Usage
-----
    # legacy default (tick#3 1000-row distribution, locked)
    python seed_predictive_watch_log.py
    python seed_predictive_watch_log.py --db /path/to/autonomath.db

    # tick#6 100K-scale incremental (additive, ratio-preserving)
    python seed_predictive_watch_log.py --apply --count 5000

JSON output (final stdout line)::

    {
      "dim": "T",
      "wave": 48,
      "tick": 3,
      "seeded_watches": 1000,
      "seeded_alerts": 1000,
      "by_type": {"houjin": 400, "program": 400, "amendment": 200}
    }
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB_PATH = Path("/Users/shigetoumeda/jpcite/autonomath.db")
SEED_PREFIX = "wave48_dim_t_seed_"
DISTRIBUTION: tuple[tuple[str, int], ...] = (
    ("houjin", 400),
    ("program", 400),
    ("amendment", 200),
)
# Locked 4:4:2 ratio reused for --apply incremental batches (tick#6 100K-scale).
RATIO: tuple[tuple[str, int], ...] = (
    ("houjin", 4),
    ("program", 4),
    ("amendment", 2),
)


def _token_hash(watch_type: str, idx: int, tick: int = 3) -> str:
    """Deterministic sha256 hex (64 chars) for the seed subscriber.

    tick is included in the seed material so additive batches produce
    distinct subscriber hashes per (tick, watch_type, idx) triple.
    """
    if tick == 3:
        # Preserve legacy tick#3 hashes exactly (no tick suffix in seed).
        raw = f"{SEED_PREFIX}{watch_type}_{idx:04d}".encode()
    else:
        raw = f"{SEED_PREFIX}tick{tick}_{watch_type}_{idx:04d}".encode()
    return hashlib.sha256(raw).hexdigest()


def _payload_for(watch_type: str, idx: int, tick: int = 3) -> str:
    """Structural metadata payload — NO natural language."""
    return json.dumps(
        {
            "watch_type": watch_type,
            "watch_target": f"{watch_type}_{idx:04d}",
            "kind": "seed_alert",
            "wave": 48,
            "tick": tick,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _max_idx_per_type(conn: sqlite3.Connection) -> dict[str, int]:
    """Highest watch_target numeric suffix per watch_type (0 if none).

    Used by --apply to offset new indices so additive batches don't
    collide on (subscriber_token_hash, watch_type, watch_target).
    """
    out: dict[str, int] = {wt: 0 for wt, _ in RATIO}
    cur = conn.execute(
        """
        SELECT watch_type,
               COALESCE(MAX(CAST(SUBSTR(watch_target, INSTR(watch_target,'_')+1)
                                AS INTEGER)), 0) AS max_idx
          FROM am_predictive_watch_subscription
         GROUP BY watch_type
        """
    )
    for watch_type, max_idx in cur.fetchall():
        if watch_type in out:
            out[watch_type] = int(max_idx)
    return out


def _seed(conn: sqlite3.Connection) -> tuple[int, int, dict[str, int]]:
    by_type: dict[str, int] = {}
    total_watch = 0
    total_alert = 0
    for watch_type, count in DISTRIBUTION:
        for i in range(1, count + 1):
            sub_hash = _token_hash(watch_type, i)
            target = f"{watch_type}_{i:04d}"
            cur = conn.execute(
                """
                INSERT INTO am_predictive_watch_subscription
                    (subscriber_token_hash, watch_type, watch_target,
                     threshold, notify_window_hours, status)
                VALUES (?, ?, ?, 0.0, 24, 'active')
                """,
                (sub_hash, watch_type, target),
            )
            watch_id = cur.lastrowid
            conn.execute(
                """
                INSERT INTO am_predictive_alert_log
                    (watch_id, payload, delivery_status)
                VALUES (?, ?, 'pending')
                """,
                (watch_id, _payload_for(watch_type, i)),
            )
            total_watch += 1
            total_alert += 1
        by_type[watch_type] = count
    return total_watch, total_alert, by_type


def _split_by_ratio(count: int) -> dict[str, int]:
    """Split count across watch_type by locked 4:4:2 ratio.

    Rounding rule: floor each share, then assign the remainder to
    'houjin' so totals always equal ``count`` exactly.
    """
    weight_total = sum(w for _, w in RATIO)
    splits: dict[str, int] = {}
    assigned = 0
    for watch_type, weight in RATIO:
        share = (count * weight) // weight_total
        splits[watch_type] = share
        assigned += share
    splits["houjin"] += count - assigned
    return splits


def _seed_incremental(
    conn: sqlite3.Connection, count: int, tick: int
) -> tuple[int, int, dict[str, int]]:
    """Additive seed of `count` rows preserving the 4:4:2 ratio."""
    splits = _split_by_ratio(count)
    offsets = _max_idx_per_type(conn)
    by_type: dict[str, int] = {}
    total_watch = 0
    total_alert = 0
    for watch_type, n in splits.items():
        base = offsets[watch_type]
        for k in range(1, n + 1):
            idx = base + k
            sub_hash = _token_hash(watch_type, idx, tick=tick)
            target = f"{watch_type}_{idx:04d}"
            cur = conn.execute(
                """
                INSERT INTO am_predictive_watch_subscription
                    (subscriber_token_hash, watch_type, watch_target,
                     threshold, notify_window_hours, status)
                VALUES (?, ?, ?, 0.0, 24, 'active')
                """,
                (sub_hash, watch_type, target),
            )
            watch_id = cur.lastrowid
            conn.execute(
                """
                INSERT INTO am_predictive_alert_log
                    (watch_id, payload, delivery_status)
                VALUES (?, ?, 'pending')
                """,
                (watch_id, _payload_for(watch_type, idx, tick=tick)),
            )
            total_watch += 1
            total_alert += 1
        by_type[watch_type] = n
    return total_watch, total_alert, by_type


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Dim T predictive watch large-scale seed")
    p.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p.add_argument(
        "--apply",
        action="store_true",
        help="Incremental additive seed mode (vs. legacy fixed 1000 batch).",
    )
    p.add_argument(
        "--count",
        type=int,
        default=0,
        help="Number of rows to add in --apply mode (split 4:4:2 by watch_type).",
    )
    p.add_argument(
        "--tick",
        type=int,
        default=6,
        help="Tick stamp baked into payload + subscriber hash for additive mode.",
    )
    args = p.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: db not found at {db_path}", file=sys.stderr)
        return 2

    conn = _connect(db_path)
    try:
        with conn:
            if args.apply:
                if args.count <= 0:
                    print(
                        "ERROR: --apply requires --count N (N > 0)",
                        file=sys.stderr,
                    )
                    return 2
                watches, alerts, by_type = _seed_incremental(conn, args.count, args.tick)
                summary_tick = args.tick
            else:
                watches, alerts, by_type = _seed(conn)
                summary_tick = 3
    finally:
        conn.close()

    summary = {
        "dim": "T",
        "wave": 48,
        "tick": summary_tick,
        "seeded_watches": watches,
        "seeded_alerts": alerts,
        "by_type": by_type,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
