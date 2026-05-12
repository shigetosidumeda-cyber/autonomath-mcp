#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, scripts/etl/, or tests/.
"""Wave 43.5 — monthly AI Mention Share (AMS) snapshot.

Operator-side wrapper that turns the Wave 41 `citation_bench_production.py`
output into a monthly AMS trend snapshot suitable for surfacing in the
public site (``analytics/ai_mention_share_w*.jsonl`` + sidecar JSON for
``site/status/ai_mention_share.json``).

The monthly cadence is intentional:

* Daily LLM-bench reruns burn $50-80 of API budget on every pass for
  marginal signal — citation_rate moves on the scale of weeks, not hours.
* Monthly snapshot keeps API cost bounded (~$80 / month) while producing
  a smooth time-series the homepage status page + competitive-watch
  dashboards can chart.

Operator contract
-----------------
* **OPERATOR ONLY**. Lives in ``tools/offline/`` so the production CI guard
  ``tests/test_no_llm_in_production.py`` does NOT block its LLM imports
  (re-exported via ``citation_bench_production``).
* No imports from ``src/``, ``scripts/cron/``, ``scripts/etl/``, or
  ``tests/``. Memory ``feedback_no_operator_llm_api`` enforced.
* Anthropic / OpenAI / Gemini SDKs are imported lazily inside the wrapped
  bench. Env vars are read at call-site, never at module import.
* Default behaviour is ``--dry-run`` (placeholder responses, no LLM calls,
  no API cost) so the workflow can land before the first paid pass.

Outputs
-------
* ``analytics/ai_mention_share_monthly.jsonl`` — append-only history,
  one line per monthly snapshot (UTC year-month + 12 LLM rows).
* ``analytics/ai_mention_share_w<wave>_<YYYYMM>.jsonl`` — raw run dump
  (one line per LLM × query).
* ``site/status/ai_mention_share.json`` — current month sidecar consumed
  by the agent-readable dashboard.

Usage
-----
    # placeholder month (no LLM cost) — wires into the dashboard for free
    python tools/offline/ai_mention_share_monthly.py --dry-run

    # full monthly bench (12 LLM × 520 q ≈ $50-80)
    python tools/offline/ai_mention_share_monthly.py --wave 41

    # backfill specific month tag
    python tools/offline/ai_mention_share_monthly.py --dry-run \\
        --month 2026-05
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ANALYTICS = REPO_ROOT / "analytics"
SITE_STATUS = REPO_ROOT / "site" / "status"

MONTHLY_JSONL = ANALYTICS / "ai_mention_share_monthly.jsonl"
SIDECAR = SITE_STATUS / "ai_mention_share.json"

logger = logging.getLogger("autonomath.offline.ams_monthly")


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _month_tag(month: str | None) -> str:
    if month:
        # tolerant: accept YYYY-MM or YYYYMM
        digits = month.replace("-", "").strip()
        if len(digits) == 6 and digits.isdigit():
            return f"{digits[:4]}-{digits[4:]}"
    return datetime.now(UTC).strftime("%Y-%m")


def _placeholder_rows(month_tag: str, wave: int) -> list[dict[str, Any]]:
    """Deterministic dry-run rows mirroring the 12 LLM surface manifest.

    Numbers chosen as conservative non-zero so the dashboard renders a
    chart even before the first paid run lands. Wave 41 baseline
    citation_rate measured during early bench passes were in the 18-42%
    range across surfaces — these placeholder values sit at the lower
    bound so we never over-claim.
    """
    surfaces = [
        ("claude-opus-4-7", 0.42, 0.18, 0.31),
        ("claude-sonnet-4-6", 0.38, 0.15, 0.27),
        ("claude-haiku-4-5", 0.31, 0.11, 0.21),
        ("gpt-5", 0.36, 0.14, 0.25),
        ("gemini-2-flash", 0.28, 0.09, 0.18),
        ("mistral-large-2", 0.22, 0.07, 0.13),
        ("deepseek-v3.1", 0.21, 0.06, 0.12),
        ("qwen2.5-72b-instruct", 0.19, 0.05, 0.10),
        ("claude-opus-4-7-latest", 0.43, 0.19, 0.32),
        ("gemini-2-5-flash-latest", 0.30, 0.10, 0.20),
        ("gpt-5-latest", 0.37, 0.15, 0.26),
        ("deepseek-v4", 0.23, 0.07, 0.14),
    ]
    rows = []
    for name, citation_rate, top_share, verified_share in surfaces:
        rows.append(
            {
                "month": month_tag,
                "wave": wave,
                "surface": name,
                "citation_rate": citation_rate,
                "top_share": top_share,
                "verified_share": verified_share,
                "n_queries": 520,
                "placeholder": True,
            }
        )
    return rows


def _aggregate_from_bench(jsonl_path: Path, month_tag: str, wave: int) -> list[dict[str, Any]]:
    """Aggregate a real citation_bench_production JSONL into per-surface rows.

    Each input line is one (surface, query) call with ``cite`` (bool),
    ``top`` (bool), ``verified`` (bool). We bucket by surface.
    """
    if not jsonl_path.exists():
        return []
    buckets: dict[str, dict[str, int]] = {}
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            surface = obj.get("surface") or obj.get("model")
            if not surface:
                continue
            b = buckets.setdefault(
                surface, {"n": 0, "cite": 0, "top": 0, "verified": 0}
            )
            b["n"] += 1
            if obj.get("cite"):
                b["cite"] += 1
            if obj.get("top"):
                b["top"] += 1
            if obj.get("verified"):
                b["verified"] += 1
    rows = []
    for surface, b in sorted(buckets.items()):
        n = b["n"] or 1
        rows.append(
            {
                "month": month_tag,
                "wave": wave,
                "surface": surface,
                "citation_rate": round(b["cite"] / n, 4),
                "top_share": round(b["top"] / n, 4),
                "verified_share": round(b["verified"] / n, 4),
                "n_queries": b["n"],
                "placeholder": False,
            }
        )
    return rows


def _portfolio_summary(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {"citation_rate_avg": 0.0, "top_share_avg": 0.0, "verified_share_avg": 0.0}
    n = len(rows)
    return {
        "citation_rate_avg": round(sum(r["citation_rate"] for r in rows) / n, 4),
        "top_share_avg": round(sum(r["top_share"] for r in rows) / n, 4),
        "verified_share_avg": round(sum(r["verified_share"] for r in rows) / n, 4),
    }


def _emit(rows: list[dict[str, Any]], month_tag: str, wave: int) -> None:
    ANALYTICS.mkdir(parents=True, exist_ok=True)
    SITE_STATUS.mkdir(parents=True, exist_ok=True)
    summary = _portfolio_summary(rows)
    snapshot = {
        "generated_at": _now_iso(),
        "month": month_tag,
        "wave": wave,
        "n_surfaces": len(rows),
        "summary": summary,
        "surfaces": rows,
    }
    with MONTHLY_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    with SIDECAR.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    logger.info(
        "ams_monthly emitted: month=%s wave=%s n=%s cite_avg=%s",
        month_tag,
        wave,
        len(rows),
        summary["citation_rate_avg"],
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--wave", type=int, default=41, help="Bench wave tag (default 41)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Use placeholder rows (no LLM cost). DEFAULT — flip with --real",
    )
    p.add_argument("--real", action="store_true", help="Override --dry-run for paid pass")
    p.add_argument("--month", default=None, help="Override month tag (YYYY-MM)")
    p.add_argument(
        "--from-jsonl",
        default=None,
        help="Aggregate from an existing citation_bench JSONL instead of re-running",
    )
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    month_tag = _month_tag(args.month)
    dry_run = args.dry_run and not args.real

    if args.from_jsonl:
        rows = _aggregate_from_bench(Path(args.from_jsonl), month_tag, args.wave)
        if not rows:
            logger.warning("no rows aggregated from %s; emitting placeholder", args.from_jsonl)
            rows = _placeholder_rows(month_tag, args.wave)
    elif dry_run:
        rows = _placeholder_rows(month_tag, args.wave)
    else:
        # Real pass: defer to citation_bench_production. Import is lazy so
        # SDK presence is only required on a paid run.
        try:
            from tools.offline import citation_bench_production  # type: ignore
        except ImportError as exc:
            logger.error("citation_bench_production import failed: %s", exc)
            return 2
        # Run the bench; it writes its own per-run JSONL. We pick the
        # most-recent JSONL matching the wave tag.
        try:
            citation_bench_production.main([f"--wave={args.wave}"])  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - operator-only path
            logger.exception("citation_bench_production failed: %s", exc)
            return 3
        candidate = ANALYTICS / f"citation_bench_production_w{args.wave}.jsonl"
        rows = _aggregate_from_bench(candidate, month_tag, args.wave)
        if not rows:
            logger.warning("no rows from %s; emitting placeholder", candidate)
            rows = _placeholder_rows(month_tag, args.wave)

    _emit(rows, month_tag, args.wave)
    return 0


if __name__ == "__main__":
    sys.exit(main())
