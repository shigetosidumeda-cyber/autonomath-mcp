#!/usr/bin/env python3
"""H5 companion: aggregate the A/B test conversion warehouse and emit
a two-proportion z-test (95% confidence) per active test.

Pairs with `functions/ab_assign.ts`. The CF Pages Function persists
each conversion to the upstream API (`POST /v1/ab/conversion`) which
in turn writes JSONL to `analytics/ab_conversions/*.jsonl`. This
script consumes that warehouse and writes:

    site/status/ab_test_results.json    (LLM/agent + dashboard read)

It does NOT call the LLM API. Pure stdlib + math.

JSONL schema (per event)
------------------------
    {
      "test_id":        "landing_copy_v1",
      "event":          "conversion" | "checkout_start" | ...,
      "value":          float | null,
      "bucket":         "a" | "b",
      "external_ref":   str | null,
      "occurred_at":    ISO-8601 timestamp,
      "user_agent":     str | null
    }

Aggregation
-----------
For each (test_id, event) tuple we accumulate:

    n_a, n_b                 = visitor count by bucket (deduped on external_ref)
    conv_a, conv_b           = conversion count by bucket
    rate_a, rate_b           = conv / n
    value_sum_a, value_sum_b = sum of `value`
    arpu_a, arpu_b           = value_sum / n

Two-proportion z-test
---------------------
    p_pool = (conv_a + conv_b) / (n_a + n_b)
    se     = sqrt(p_pool * (1 - p_pool) * (1/n_a + 1/n_b))
    z      = (rate_b - rate_a) / se
    p      = 2 * (1 - Phi(|z|))            # two-sided
    sig    = "yes" if p < 0.05 else "no"

When n_a or n_b is < 30 the test is reported as "underpowered" rather
than significant.

Visitor count
-------------
We derive `n_a` / `n_b` from the COUNT of unique external_ref values
(the Stripe customer / session id). If external_ref is missing we fall
back to UA-bucketed approximate counts — flagged as `approximate=True`
in the output.

CLI
---
    python3 scripts/ops/ab_test_results.py
    python3 scripts/ops/ab_test_results.py --warehouse path/to/conversions.jsonl
    python3 scripts/ops/ab_test_results.py --dry-run

Output schema
-------------
{
  "schema": "jpcite/ab_test_results/v1",
  "generated_at": "...",
  "tests": {
    "landing_copy_v1": {
      "events": {
        "conversion": {
          "n_a": ..., "n_b": ...,
          "conv_a": ..., "conv_b": ...,
          "rate_a": ..., "rate_b": ...,
          "p_value": ..., "z": ...,
          "significant_95pct": true|false|"underpowered",
          "winner": "a"|"b"|"none"
        }
      }
    }
  }
}
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WAREHOUSE_DIR = REPO_ROOT / "analytics" / "ab_conversions"
OUT_PATH = REPO_ROOT / "site" / "status" / "ab_test_results.json"

POWER_FLOOR = 30  # min sample per arm before we trust significance
ALPHA = 0.05  # 95% confidence


def _norm_cdf(x: float) -> float:
    """Abramowitz & Stegun 26.2.17 — accurate to 7.5e-8.
    No scipy dep, keeps the production posture pure-stdlib.
    """
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def two_proportion_z(conv_a: int, n_a: int, conv_b: int, n_b: int) -> tuple[float, float]:
    if n_a == 0 or n_b == 0:
        return (float("nan"), float("nan"))
    p_pool = (conv_a + conv_b) / (n_a + n_b)
    se = math.sqrt(max(0.0, p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b)))
    if se == 0:
        return (float("nan"), float("nan"))
    rate_a = conv_a / n_a
    rate_b = conv_b / n_b
    z = (rate_b - rate_a) / se
    p = 2 * (1 - _norm_cdf(abs(z)))
    return (z, p)


def iter_warehouse_rows(paths: list[Path]):
    for p in paths:
        if not p.exists():
            continue
        try:
            with p.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue


def discover_warehouse(arg: str | None) -> list[Path]:
    if arg:
        p = Path(arg)
        if p.is_file():
            return [p]
        if p.is_dir():
            return sorted(p.glob("*.jsonl"))
        return []
    if not DEFAULT_WAREHOUSE_DIR.exists():
        return []
    return sorted(DEFAULT_WAREHOUSE_DIR.glob("*.jsonl"))


def aggregate(rows) -> dict:
    # (test_id, event) -> bucket -> set(external_ref), conv_count, value_sum
    visitors: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(lambda: {"a": set(), "b": set()})
    conv: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"a": 0, "b": 0})
    val: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: {"a": 0.0, "b": 0.0})
    approximate: dict[tuple[str, str], bool] = defaultdict(bool)

    for r in rows:
        t = r.get("test_id")
        b = r.get("bucket")
        e = r.get("event", "conversion")
        if not t or b not in ("a", "b"):
            continue
        key = (t, e)
        ref = r.get("external_ref") or r.get("user_agent") or ""
        if not r.get("external_ref"):
            approximate[key] = True
        visitors[key][b].add(ref or f"_anon_{r.get('occurred_at')}")
        conv[key][b] += 1
        v = r.get("value")
        if isinstance(v, (int, float)):
            val[key][b] += float(v)

    out: dict[str, dict] = {}
    for (t, e), bv in visitors.items():
        n_a = len(bv["a"])
        n_b = len(bv["b"])
        c_a = conv[(t, e)]["a"]
        c_b = conv[(t, e)]["b"]
        s_a = val[(t, e)]["a"]
        s_b = val[(t, e)]["b"]
        rate_a = c_a / n_a if n_a else 0.0
        rate_b = c_b / n_b if n_b else 0.0
        z, p_value = two_proportion_z(c_a, n_a, c_b, n_b)
        if n_a < POWER_FLOOR or n_b < POWER_FLOOR:
            sig_flag: bool | str = "underpowered"
            winner = "none"
        else:
            sig_flag = bool(not math.isnan(p_value) and p_value < ALPHA)
            if sig_flag:
                winner = "b" if rate_b > rate_a else "a"
            else:
                winner = "none"

        out.setdefault(t, {"events": {}})["events"][e] = {
            "n_a": n_a,
            "n_b": n_b,
            "conv_a": c_a,
            "conv_b": c_b,
            "rate_a": round(rate_a, 6),
            "rate_b": round(rate_b, 6),
            "rate_lift_pct": round((rate_b - rate_a) * 100, 4),
            "value_sum_a": round(s_a, 2),
            "value_sum_b": round(s_b, 2),
            "arpu_a": round(s_a / n_a, 4) if n_a else 0.0,
            "arpu_b": round(s_b / n_b, 4) if n_b else 0.0,
            "z": None if math.isnan(z) else round(z, 4),
            "p_value": None if math.isnan(p_value) else round(p_value, 6),
            "significant_95pct": sig_flag,
            "winner": winner,
            "approximate": approximate[(t, e)],
        }
    return out


def atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".ab_results.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warehouse", default=None, help="path to single .jsonl or dir")
    parser.add_argument("--out", default=str(OUT_PATH))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    paths = discover_warehouse(args.warehouse)
    if not paths:
        print("warehouse: no input files found (this is OK on first run)", file=sys.stderr)
    rows = list(iter_warehouse_rows(paths))
    tests = aggregate(rows)

    doc = {
        "schema": "jpcite/ab_test_results/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "warehouse_files": [str(p) for p in paths],
        "row_count": len(rows),
        "tests": tests,
        "alpha": ALPHA,
        "power_floor": POWER_FLOOR,
    }

    if args.dry_run:
        json.dump(doc, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    atomic_write(Path(args.out), doc)
    print(f"wrote {args.out}")
    print(f"tests aggregated: {len(tests)}")
    sig_count = sum(
        1 for t in tests.values() for e in t["events"].values()
        if e["significant_95pct"] is True
    )
    print(f"significant @95%: {sig_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
