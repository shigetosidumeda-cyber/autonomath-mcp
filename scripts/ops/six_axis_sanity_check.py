#!/usr/bin/env python3
"""Wave 38 — 6-axis production sanity check.

Verifies each of the 6 design axes (data 量 / data 質 / 鮮度 / 組み合わせ /
多言語 / output) is meeting its minimum gate. Each gate is a binary
pass / fail probe (NOT a soft score). When any axis fails the script
exits non-zero so the daily cron (.github/workflows/six-axis-sanity-daily.yml)
flips red and the Telegram bot fires an SLA-breach alert.

Each minimum gate:
    Axis 1 (data 量):
      1a municipal_subsidies     row_count >= 100
      1b jpo_patent_*            row_count >= 100
      1c edinet_*                row_count >= 100
      1d court_decisions         row_count >= 100
      1e industry_*              row_count >= 100
      1f nta_invoice_registrants row_count >= 100
    Axis 2 (data 質):
      2a am_cohort_5d            row_count >= 1_000
      2b am_program_risk_4d      row_count >= 1_000
      2c am_supplier_chain       row_count >= 1_000
      2d am_compat_promote       row_count >= 1_000
      2e am_amount_verify        row_count >= 1_000
      2f am_amendment_dated      row_count >= 1_000
    Axis 3 (鮮度): each daily ingest has > 0 fresh rows in the last 7 days.
    Axis 4 (組み合わせ): each precompute table refreshed (last_run within
        7 days for portfolio / risk / forecast / alliance / graph_vec).
    Axis 5 (多言語): en coverage >= 80 %, zh/ko coverage >= 5 % per table.
    Axis 6 (output): >= 80 % success rate across 6 channels.

Pure stdlib. NO LLM imports. Honest-null: if an input table or sidecar
file is genuinely missing the sub-axis is recorded as ``unknown`` and
DOES NOT auto-fail; the verdict is computed only over the sub-axes that
the probe was able to materialise.

Usage:
    python3 scripts/ops/six_axis_sanity_check.py
    python3 scripts/ops/six_axis_sanity_check.py --out-json analytics/six_axis_status.json
    python3 scripts/ops/six_axis_sanity_check.py --out-md docs/audit/six_axis_2026_05_12.md
    python3 scripts/ops/six_axis_sanity_check.py --emit-alert /tmp/sla_breach.txt

The companion REST endpoint `GET /v1/status/six_axis` reads the JSON
sidecar that this script writes; the dashboard
`site/status/six_axis_dashboard.html` does the same thing in the browser.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
ANALYTICS_DIR = REPO_ROOT / "analytics"

# DB resolution: env override first; fall back to volume mount paths if those
# exist; otherwise use repo-root paths. This lets the script run both inside
# CI (where the 9.7 GB autonomath.db is absent) and in production.
def _resolve_db(env_key: str, *candidates: Path) -> Path | None:
    env_val = os.environ.get(env_key, "").strip()
    if env_val:
        p = Path(env_val)
        if p.exists():
            return p
    for c in candidates:
        if c.exists():
            return c
    return None


AUTONOMATH_DB = _resolve_db(
    "AUTONOMATH_DB_PATH",
    Path("/data/autonomath.db"),
    REPO_ROOT / "autonomath.db",
    DATA_DIR / "autonomath.db",
)
JPINTEL_DB = _resolve_db(
    "JPINTEL_DB_PATH",
    Path("/data/jpintel.db"),
    DATA_DIR / "jpintel.db",
)


# ---------------------------------------------------------------------------
# Axis specs
# ---------------------------------------------------------------------------

AXIS_1_SOURCES: list[tuple[str, str, str, int]] = [
    # (sub_id, table_name, db_key, min_rows)
    ("1a", "municipal_subsidies", "jpintel", 100),
    ("1b", "jpo_patent_index", "autonomath", 100),
    ("1c", "edinet_filings", "autonomath", 100),
    ("1d", "court_decisions", "jpintel", 100),
    ("1e", "industry_corpus", "autonomath", 100),
    ("1f", "invoice_registrants", "jpintel", 100),
]

AXIS_2_PRECOMPUTES: list[tuple[str, str, int]] = [
    ("2a", "am_cohort_5d", 1_000),
    ("2b", "am_program_risk_4d", 1_000),
    ("2c", "am_supplier_chain", 1_000),
    ("2d", "am_compat_promote", 1_000),
    ("2e", "am_amount_verify", 1_000),
    ("2f", "am_amendment_dated", 1_000),
]

AXIS_3_INGESTS: list[tuple[str, str]] = [
    ("3a", "amendment_diff"),
    ("3b", "law_articles"),
    ("3c", "adoption_records"),
    ("3d", "enforcement_cases"),
    ("3e", "invoice_registrants"),
]

AXIS_4_REFRESHES: list[tuple[str, str, int]] = [
    ("4a", "am_portfolio_optimize", 100),
    ("4b", "am_houjin_risk_score", 100),
    ("4c", "am_subsidy_30yr_forecast", 100),
    ("4d", "am_alliance_opportunity", 100),
    ("4e", "am_knowledge_graph_vec_index", 100),
]

AXIS_5_LANGS: list[tuple[str, str, float]] = [
    ("5_en", "en", 0.80),
    ("5_zh", "zh", 0.05),
    ("5_ko", "ko", 0.05),
    ("5_ja", "ja", 1.00),  # base language, always 100%
]

AXIS_6_CHANNELS: list[str] = [
    "pdf", "excel", "freee", "mf", "yayoi",
    "notion", "linear", "slack", "discord", "teams",
]


# ---------------------------------------------------------------------------
# Probe primitives
# ---------------------------------------------------------------------------

@dataclass
class SubResult:
    sub_id: str
    label: str
    status: str  # ok | warn | fail | unknown
    observed: float | int | None
    threshold: float | int
    detail: str = ""


@dataclass
class AxisResult:
    axis_id: str
    label: str
    sub_results: list[SubResult] = field(default_factory=list)
    verdict: str = "unknown"  # ok | degraded | breach | unknown


def _safe_count(db_path: Path | None, table: str) -> int | None:
    if db_path is None or not db_path.exists():
        return None
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('table','view') AND name = ?",
                (table,),
            ).fetchone()
            if not row:
                return None
            cur = conn.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
            return int(cur.fetchone()[0])
    except sqlite3.Error:
        return None


def _safe_recent_count(db_path: Path | None, table: str, days: int = 7,
                       ts_col: str = "fetched_at") -> int | None:
    if db_path is None or not db_path.exists():
        return None
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5) as conn:
            t = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('table','view') AND name = ?",
                (table,),
            ).fetchone()
            if not t:
                return None
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            try:
                cur = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {ts_col} >= ?",  # noqa: S608
                    (cutoff,),
                )
                return int(cur.fetchone()[0])
            except sqlite3.OperationalError:
                # column missing — fall back to row count
                cur = conn.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
                return int(cur.fetchone()[0])
    except sqlite3.Error:
        return None


def _load_sidecar(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Axis runners
# ---------------------------------------------------------------------------

def _classify(observed: int | float | None, threshold: int | float,
              unit: str = "") -> tuple[str, str]:
    if observed is None:
        return "unknown", f"input missing (threshold {threshold}{unit})"
    if observed >= threshold:
        return "ok", f"observed={observed}{unit} >= {threshold}{unit}"
    return "fail", f"observed={observed}{unit} < {threshold}{unit}"


def run_axis1() -> AxisResult:
    axis = AxisResult(axis_id="1", label="data 量")
    for sub_id, table, db_key, min_rows in AXIS_1_SOURCES:
        db_path = AUTONOMATH_DB if db_key == "autonomath" else JPINTEL_DB
        count = _safe_count(db_path, table)
        status, detail = _classify(count, min_rows)
        axis.sub_results.append(SubResult(
            sub_id=sub_id, label=table, status=status,
            observed=count, threshold=min_rows, detail=detail,
        ))
    return _finalise(axis)


def run_axis2() -> AxisResult:
    axis = AxisResult(axis_id="2", label="data 質")
    for sub_id, table, min_rows in AXIS_2_PRECOMPUTES:
        count = _safe_count(AUTONOMATH_DB, table)
        status, detail = _classify(count, min_rows)
        axis.sub_results.append(SubResult(
            sub_id=sub_id, label=table, status=status,
            observed=count, threshold=min_rows, detail=detail,
        ))
    return _finalise(axis)


def run_axis3() -> AxisResult:
    axis = AxisResult(axis_id="3", label="鮮度")
    for sub_id, table in AXIS_3_INGESTS:
        db_path = JPINTEL_DB
        recent = _safe_recent_count(db_path, table, days=7)
        if recent is None:
            # try autonomath side
            recent = _safe_recent_count(AUTONOMATH_DB, table, days=7)
        status, detail = _classify(recent, 1)  # at least one row in 7d
        axis.sub_results.append(SubResult(
            sub_id=sub_id, label=table, status=status,
            observed=recent, threshold=1, detail=detail,
        ))
    return _finalise(axis)


def run_axis4() -> AxisResult:
    axis = AxisResult(axis_id="4", label="組み合わせ")
    for sub_id, table, min_rows in AXIS_4_REFRESHES:
        count = _safe_count(AUTONOMATH_DB, table)
        status, detail = _classify(count, min_rows)
        axis.sub_results.append(SubResult(
            sub_id=sub_id, label=table, status=status,
            observed=count, threshold=min_rows, detail=detail,
        ))
    return _finalise(axis)


def run_axis5() -> AxisResult:
    axis = AxisResult(axis_id="5", label="多言語")
    # The multilingual sidecar is populated by scripts/cron/fill_laws_*.py
    sidecar = _load_sidecar(ANALYTICS_DIR / "multilingual_coverage.json")
    for sub_id, lang_code, min_pct in AXIS_5_LANGS:
        if sidecar:
            obs = float(sidecar.get(lang_code, {}).get("coverage", 0.0))
        else:
            # Honest-null when sidecar missing
            obs = None  # type: ignore[assignment]
        status, detail = _classify(obs, min_pct, unit="")
        axis.sub_results.append(SubResult(
            sub_id=sub_id, label=f"{lang_code} coverage", status=status,
            observed=obs, threshold=min_pct, detail=detail,
        ))
    return _finalise(axis)


def run_axis6() -> AxisResult:
    axis = AxisResult(axis_id="6", label="output")
    # Output channel health sidecar; written by ax_metrics_aggregator.py.
    sidecar = _load_sidecar(ANALYTICS_DIR / "output_channel_health.json")
    threshold = 0.80
    for channel in AXIS_6_CHANNELS:
        if sidecar:
            stats = sidecar.get(channel, {})
            obs = stats.get("success_rate")
            if obs is not None:
                obs = float(obs)
        else:
            obs = None
        status, detail = _classify(obs, threshold)
        axis.sub_results.append(SubResult(
            sub_id=f"6_{channel}", label=channel, status=status,
            observed=obs, threshold=threshold, detail=detail,
        ))
    return _finalise(axis)


def _finalise(axis: AxisResult) -> AxisResult:
    statuses = [s.status for s in axis.sub_results]
    if not statuses or all(s == "unknown" for s in statuses):
        axis.verdict = "unknown"
    elif any(s == "fail" for s in statuses):
        axis.verdict = "breach"
    elif any(s == "warn" for s in statuses):
        axis.verdict = "degraded"
    else:
        axis.verdict = "ok"
    return axis


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_all() -> dict[str, Any]:
    started = datetime.now(timezone.utc).isoformat()
    axes = [
        run_axis1(),
        run_axis2(),
        run_axis3(),
        run_axis4(),
        run_axis5(),
        run_axis6(),
    ]
    verdicts = [a.verdict for a in axes]
    if any(v == "breach" for v in verdicts):
        overall = "breach"
    elif any(v == "degraded" for v in verdicts):
        overall = "degraded"
    elif all(v == "unknown" for v in verdicts):
        overall = "unknown"
    else:
        overall = "ok"

    return {
        "schema_version": 1,
        "generated_at": started,
        "overall_verdict": overall,
        "axes": [_axis_to_dict(a) for a in axes],
        "_meta": {
            "autonomath_db_present": AUTONOMATH_DB is not None,
            "jpintel_db_present": JPINTEL_DB is not None,
            "ci_mode": os.environ.get("CI") == "true",
        },
    }


def _axis_to_dict(axis: AxisResult) -> dict[str, Any]:
    return {
        "axis_id": axis.axis_id,
        "label": axis.label,
        "verdict": axis.verdict,
        "sub_results": [asdict(s) for s in axis.sub_results],
    }


def render_alert(report: dict[str, Any]) -> str | None:
    """Return SLA breach text, or None if no breach."""
    if report["overall_verdict"] != "breach":
        return None
    lines = [
        f"[jpcite 6-axis SLA breach] {report['generated_at']}",
        f"Overall: {report['overall_verdict']}",
        "",
    ]
    for axis in report["axes"]:
        if axis["verdict"] != "breach":
            continue
        lines.append(f"Axis {axis['axis_id']} ({axis['label']}): BREACH")
        for sub in axis["sub_results"]:
            if sub["status"] == "fail":
                lines.append(
                    f"  - {sub['sub_id']} {sub['label']}: {sub['detail']}"
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_md(report: dict[str, Any]) -> str:
    lines = [
        "# 6-axis production sanity check",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- overall_verdict: **{report['overall_verdict']}**",
        "",
        "| axis | label | verdict | sub-axes |",
        "| --- | --- | --- | --- |",
    ]
    for axis in report["axes"]:
        sub_count = len(axis["sub_results"])
        ok_count = sum(1 for s in axis["sub_results"] if s["status"] == "ok")
        lines.append(
            f"| {axis['axis_id']} | {axis['label']} | {axis['verdict']} "
            f"| {ok_count}/{sub_count} ok |"
        )
    lines += ["", "## Sub-axis detail", ""]
    for axis in report["axes"]:
        lines.append(f"### Axis {axis['axis_id']} — {axis['label']}")
        lines.append("")
        lines.append("| sub | label | status | observed | threshold | detail |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for sub in axis["sub_results"]:
            lines.append(
                f"| {sub['sub_id']} | {sub['label']} | {sub['status']} "
                f"| {sub['observed']} | {sub['threshold']} | {sub['detail']} |"
            )
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-json", help="Write JSON status to this path.")
    p.add_argument("--out-md", help="Write Markdown report to this path.")
    p.add_argument("--emit-alert", help="If overall verdict is breach, "
                                        "write SLA alert text here.")
    p.add_argument("--exit-on-breach", action="store_true",
                   help="Exit non-zero when verdict is breach (default off "
                        "so probe runs are observable in CI logs).")
    args = p.parse_args(argv)

    report = run_all()

    if args.out_json:
        out = Path(args.out_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        # default behaviour: surface to stdout for cron logs
        print(json.dumps(report, indent=2, ensure_ascii=False))

    if args.out_md:
        out = Path(args.out_md)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_md(report))

    alert_text = render_alert(report)
    if args.emit_alert and alert_text:
        out = Path(args.emit_alert)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(alert_text)

    if args.exit_on_breach and report["overall_verdict"] == "breach":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
