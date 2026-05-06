#!/usr/bin/env python3
"""DEEP-42 12 axis evolution dashboard aggregator (jpcite v0.3.4).

Weekly cron entry point that:
  1. Pulls 12 axis sources (DEEP-36 ODE / DEEP-39 国会会議録 / DEEP-40 業界誌 /
     DEEP-41 brand mention / regulatory_signal / industry_journal_mention /
     analytics manual sample json / etc.) read-only.
  2. Normalizes each signal to scalar / json + axis-specific status
     ('healthy' / 'degraded' / 'broken') using thresholds from
     data/evolution_thresholds.yml (operator-curated, quarterly review).
  3. Bulk INSERT OR REPLACE into evolution_dashboard_snapshot
     (target_db: jpintel, migration wave24_188).
  4. Emits analytics/evolution_dashboard_<YYYY-WW>.json.
  5. Renders site/transparency/evolution.html via jinja2 template.
  6. Records 5 KPI plot data points (read-only; svg generation is shipped as
     pre-rendered placeholders in the template, regenerated weekly).

Constraints (DEEP-42 spec, DEEP-26 axis B integration, jpcite CLAUDE.md):
  - LLM API import is FORBIDDEN. Only stdlib + jinja2 + sqlite3 are imported.
  - paid analytics 0 (no Stripe / GSC / Cloudflare API live calls in this
    script — those land their own json under analytics/ via dedicated cron
    and we read those json snapshots).
  - target_db is jpintel for evolution_dashboard_snapshot upsert.
  - Aggregator never raises non-zero on partial source failures — graceful
    degradation per DEEP-42 §9 risk table.

Usage:
  python scripts/cron/aggregate_evolution_dashboard.py --week current
  python scripts/cron/aggregate_evolution_dashboard.py --week 2026-W19 --no-db

Sister: scripts/cron/aggregate_production_gate_status.py (DEEP-58).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError as exc:  # pragma: no cover - hard fail signals dep gap
    print(
        "[FATAL] jinja2 is required (pip install jinja2). "
        "LLM API imports are forbidden in this script.",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc

LOG = logging.getLogger("deep42.aggregate")

# ---------------------------------------------------------------------------
# Constants: 12 axis × signal definitions (IA-01..12).
# Each entry maps axis_id -> list of (signal_id, source_kind, source_ref).
# source_kind:
#   'sqlite_count'      -> SELECT COUNT(*) FROM <table>
#   'sqlite_query'      -> custom SELECT <expr> FROM <table> ...
#   'analytics_json'    -> read analytics/<filename> -> jsonpath
#   'manual_sample'     -> analytics/manual_sample/<latest>.json (operator)
#   'placeholder'       -> emit None + 'degraded' if absent (graceful)
# Thresholds default-encoded here; can be overridden by data/evolution_thresholds.yml.
# ---------------------------------------------------------------------------

AXES: list[dict[str, Any]] = [
    {
        "id": "IA-01",
        "title": "新 1 次資料 (primary corpus growth)",
        "signals": [
            {"id": "am_law_article_count",   "kind": "sqlite_count",  "table": "am_law_article", "db": "autonomath"},
            {"id": "programs_count",         "kind": "sqlite_count",  "table": "programs",       "db": "jpintel"},
            {"id": "kokkai_utterance_count", "kind": "placeholder",   "ref": "kokkai_utterances",  "db": "autonomath"},
        ],
    },
    {
        "id": "IA-02",
        "title": "customer feedback (usage envelope)",
        "signals": [
            {"id": "tool_call_density",   "kind": "placeholder", "ref": "usage_events.density"},
            {"id": "zero_result_rate",    "kind": "placeholder", "ref": "usage_events.zero_result"},
            {"id": "disclaimer_envelope", "kind": "placeholder", "ref": "usage_events.disclaimer"},
        ],
    },
    {
        "id": "IA-03",
        "title": "competitor intel (claude.ai / Perplexity sample)",
        "signals": [
            {"id": "citation_rate", "kind": "manual_sample", "ref": "competitor"},
        ],
    },
    {
        "id": "IA-04",
        "title": "regulatory early detect",
        "signals": [
            {"id": "regulatory_signal_count", "kind": "placeholder", "ref": "regulatory_signal", "db": "jpintel"},
            {"id": "egov_pubcomment_count",   "kind": "placeholder", "ref": "egov_pubcomment"},
        ],
    },
    {
        "id": "IA-05",
        "title": "academic citation (CiNii / Scholar manual sample)",
        "signals": [
            {"id": "citation_count", "kind": "manual_sample", "ref": "academic"},
        ],
    },
    {
        "id": "IA-06",
        "title": "tech perf (p95 / cold-start / cron success)",
        "signals": [
            {"id": "api_p95_ms",         "kind": "analytics_json", "file": "tech_perf.json", "path": "p95_ms"},
            {"id": "cold_start_rto_s",   "kind": "analytics_json", "file": "tech_perf.json", "path": "cold_start_s"},
            {"id": "cron_success_rate",  "kind": "analytics_json", "file": "tech_perf.json", "path": "cron_success_rate"},
        ],
    },
    {
        "id": "IA-07",
        "title": "OSS ecosystem (PyPI / npm / MCP registry)",
        "signals": [
            {"id": "pypi_downloads_weekly", "kind": "analytics_json", "file": "npm_daily.jsonl", "path": "pypi_weekly"},
            {"id": "npm_downloads_weekly",  "kind": "analytics_json", "file": "npm_daily.jsonl", "path": "npm_weekly"},
            {"id": "mcp_registry_rank",     "kind": "manual_sample",   "ref": "mcp_registry"},
        ],
    },
    {
        "id": "IA-08",
        "title": "cohort behavior (industry journal mention)",
        "signals": [
            {"id": "industry_journal_mention_count", "kind": "placeholder", "ref": "industry_journal_mention", "db": "jpintel"},
        ],
    },
    {
        "id": "IA-09",
        "title": "SEO (GSC + AI crawler UA)",
        "signals": [
            {"id": "gsc_impression",      "kind": "analytics_json", "file": "seo.json", "path": "impression"},
            {"id": "gsc_avg_position",    "kind": "analytics_json", "file": "seo.json", "path": "avg_position"},
            {"id": "ai_crawler_ua_rate",  "kind": "analytics_json", "file": "seo.json", "path": "ai_crawler_rate"},
        ],
    },
    {
        "id": "IA-10",
        "title": "moat verify (V_cobb_douglas / λ_max / cascade_q)",
        "signals": [
            {"id": "v_cobb_douglas",  "kind": "analytics_json", "file": "moat_verify.json", "path": "v_cobb_douglas"},
            {"id": "lambda_max",      "kind": "analytics_json", "file": "moat_verify.json", "path": "lambda_max"},
            {"id": "cascade_q",       "kind": "analytics_json", "file": "moat_verify.json", "path": "cascade_q"},
            {"id": "bayesian_post",   "kind": "analytics_json", "file": "moat_verify.json", "path": "bayesian_posterior"},
        ],
    },
    {
        "id": "IA-11",
        "title": "financial (MAPC / ARPU / net margin)",
        "signals": [
            {"id": "mapc",       "kind": "analytics_json", "file": "financial.json", "path": "mapc"},
            {"id": "arpu",       "kind": "analytics_json", "file": "financial.json", "path": "arpu"},
            {"id": "net_margin", "kind": "analytics_json", "file": "financial.json", "path": "net_margin"},
        ],
    },
    {
        "id": "IA-12",
        "title": "brand (自発 vs 他発 mention ratio)",
        "signals": [
            {"id": "self_vs_other_ratio", "kind": "analytics_json", "file": "brand_mention.json", "path": "self_vs_other_ratio"},
            {"id": "brand_reach_total",   "kind": "analytics_json", "file": "brand_mention.json", "path": "brand_reach_total"},
        ],
    },
]
assert len(AXES) == 12, "expected exactly 12 axes IA-01..IA-12"

# axis-default thresholds: scalar bounds for healthy/degraded/broken bands.
# Override via data/evolution_thresholds.yml `axis_thresholds:<IA-NN>:<signal_id>`.
DEFAULT_THRESHOLDS: dict[str, dict[str, dict[str, float]]] = {
    "IA-01": {
        "am_law_article_count": {"healthy": 10000, "degraded": 1000},
        "programs_count":       {"healthy": 8000,  "degraded": 1000},
    },
    "IA-06": {
        "api_p95_ms":        {"healthy_le": 800,   "degraded_le": 2000},
        "cold_start_rto_s":  {"healthy_le": 5,     "degraded_le": 30},
        "cron_success_rate": {"healthy": 0.95,     "degraded": 0.80},
    },
    "IA-09": {
        "gsc_impression":   {"healthy": 1000, "degraded": 100},
        "gsc_avg_position": {"healthy_le": 20, "degraded_le": 50},
    },
    "IA-10": {
        "v_cobb_douglas": {"healthy": 1.0, "degraded": 0.5},
        "lambda_max":     {"healthy": 0.0, "degraded": -0.05},
        "cascade_q":      {"healthy": 0.05, "degraded": 0.01},
    },
    "IA-12": {
        "self_vs_other_ratio": {"healthy_le": 0.7, "degraded_le": 0.9},
    },
}

# 5 KPI plot keys (DEEP-42 §5 公開 transparency page):
#   1. self_vs_other_ratio (IA-12)
#   2. v_cobb_douglas (IA-10)
#   3. lambda_max (IA-10)
#   4. cascade_q (IA-10)
#   5. pypi_downloads_weekly (IA-07)
KPI_PLOT_KEYS: list[tuple[str, str]] = [
    ("IA-12", "self_vs_other_ratio"),
    ("IA-10", "v_cobb_douglas"),
    ("IA-10", "lambda_max"),
    ("IA-10", "cascade_q"),
    ("IA-07", "pypi_downloads_weekly"),
]
assert len(KPI_PLOT_KEYS) == 5

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SignalRow:
    axis_id: str
    signal_id: str
    signal_value: float | None = None
    signal_value_json: str | None = None
    status: str = "degraded"
    note: str = ""


@dataclass
class EvolutionSnapshot:
    snapshot_date: str           # ISO week e.g. '2026-W19'
    snapshot_iso_date: str       # ISO date of Tuesday of that week (run day)
    git_head_sha: str = "unknown"
    axes: list[dict[str, Any]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    kpi_plots: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    last_update_utc: str = ""
    last_update_jst: str = ""
    schema_version: str = "deep42.v1"


# ---------------------------------------------------------------------------
# ISO-week + git helpers
# ---------------------------------------------------------------------------


def iso_week_label(date: _dt.date) -> str:
    """Return ISO YYYY-Www label (e.g. '2026-W19')."""
    iso = date.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def parse_week_arg(arg: str, today: _dt.date | None = None) -> tuple[str, _dt.date]:
    """Parse --week argument: 'current' -> today's ISO week; 'YYYY-Www'."""
    today = today or _dt.date.today()
    if arg in ("current", "now"):
        return iso_week_label(today), today
    # accept '2026-W19' or '2026W19'
    s = arg.replace("W", "-W").replace("--W", "-W")
    if "-W" not in s:
        raise ValueError(f"invalid --week: {arg!r}")
    year_str, week_str = s.split("-W", 1)
    year = int(year_str)
    week = int(week_str)
    monday = _dt.date.fromisocalendar(year, week, 1)
    tuesday = monday + _dt.timedelta(days=1)
    return iso_week_label(tuesday), tuesday


def git_head_sha(repo_root: Path) -> str:
    """Best-effort git HEAD sha; returns 'unknown' offline."""
    import shutil
    import subprocess
    if shutil.which("git") is None:
        return "unknown"
    try:
        proc = subprocess.run(  # noqa: S603 - controlled command
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return "unknown"
    if proc.returncode == 0:
        return proc.stdout.strip() or "unknown"
    return "unknown"


# ---------------------------------------------------------------------------
# Source pull helpers (graceful: every fetch returns (value, note) and never raises)
# ---------------------------------------------------------------------------


def _resolve_db_path(db_kind: str, jpintel_path: Path, autonomath_path: Path) -> Path:
    if db_kind == "jpintel":
        return jpintel_path
    return autonomath_path


def fetch_sqlite_count(table: str, db_path: Path) -> tuple[float | None, str]:
    if not db_path.exists():
        return None, f"db missing: {db_path}"
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            cur = conn.execute(f'SELECT COUNT(*) FROM "{table}"')  # noqa: S608 - whitelist literal
            row = cur.fetchone()
            return float(row[0] if row else 0), ""
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return None, f"sqlite_error: {exc}"


def fetch_analytics_json(
    file_name: str, json_path: str, analytics_dir: Path
) -> tuple[float | None, str | None, str]:
    """Read analytics/<file>, return (scalar, json_blob, note).

    json_path is a dotted path like 'pypi_weekly' or 'p95_ms'.
    Files ending in .jsonl are treated as line-delimited; we read the LAST line.
    """
    fp = analytics_dir / file_name
    if not fp.exists():
        return None, None, f"missing: {fp.name}"
    try:
        text = fp.read_text(encoding="utf-8")
    except OSError as exc:
        return None, None, f"read_error: {exc}"
    payload: Any
    try:
        if file_name.endswith(".jsonl"):
            lines = [ln for ln in text.splitlines() if ln.strip()]
            if not lines:
                return None, None, "empty jsonl"
            payload = json.loads(lines[-1])
        else:
            payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, None, f"json_error: {exc}"
    cur: Any = payload
    for part in json_path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None, None, f"path_missing: {json_path}"
    if isinstance(cur, (int, float)):
        return float(cur), None, ""
    if isinstance(cur, (list, dict)):
        return None, json.dumps(cur, ensure_ascii=False), ""
    if isinstance(cur, str):
        try:
            return float(cur), None, ""
        except ValueError:
            return None, cur, ""
    return None, None, "unsupported_type"


def fetch_manual_sample(ref: str, analytics_dir: Path) -> tuple[float | None, str | None, str]:
    """Read latest analytics/manual_sample/<YYYY-WW>.json containing ref key."""
    sub = analytics_dir / "manual_sample"
    if not sub.is_dir():
        return None, None, "manual_sample dir missing"
    candidates = sorted(sub.glob("*.json"))
    if not candidates:
        return None, None, "manual_sample empty"
    latest = candidates[-1]
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, None, f"manual_sample read_error: {exc}"
    if not isinstance(payload, dict) or ref not in payload:
        return None, None, f"manual_sample missing key: {ref}"
    val = payload[ref]
    if isinstance(val, (int, float)):
        return float(val), None, f"src={latest.name}"
    if isinstance(val, (dict, list)):
        return None, json.dumps(val, ensure_ascii=False), f"src={latest.name}"
    return None, str(val), f"src={latest.name}"


# ---------------------------------------------------------------------------
# Status classification
# ---------------------------------------------------------------------------


def classify_status(
    axis_id: str,
    signal_id: str,
    value: float | None,
    json_blob: str | None,
    thresholds: dict[str, dict[str, dict[str, float]]],
) -> str:
    """Return 'healthy' / 'degraded' / 'broken' for a numeric signal.

    Conventions:
      - missing scalar AND missing json -> 'broken'
      - thresholds entry with 'healthy' / 'degraded' (higher = better) OR
        'healthy_le' / 'degraded_le' (lower = better).
      - no threshold defined: scalar present -> 'healthy', else 'degraded'.
    """
    if value is None and json_blob is None:
        return "broken"
    if value is None:
        # We have structured data but no scalar. Conservative: degraded.
        return "degraded"
    rule = thresholds.get(axis_id, {}).get(signal_id, {})
    if not rule:
        return "healthy"
    if "healthy_le" in rule and "degraded_le" in rule:
        if value <= rule["healthy_le"]:
            return "healthy"
        if value <= rule["degraded_le"]:
            return "degraded"
        return "broken"
    if "healthy" in rule and "degraded" in rule:
        if value >= rule["healthy"]:
            return "healthy"
        if value >= rule["degraded"]:
            return "degraded"
        return "broken"
    return "healthy"


# ---------------------------------------------------------------------------
# Threshold loader (yml optional; graceful degradation if missing/parse-fail)
# ---------------------------------------------------------------------------


def load_thresholds(path: Path | None) -> dict[str, dict[str, dict[str, float]]]:
    if path is None or not path.exists():
        return DEFAULT_THRESHOLDS
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        LOG.info("PyYAML not installed; using defaults")
        return DEFAULT_THRESHOLDS
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        LOG.warning("threshold yml unreadable (%s); using defaults", exc)
        return DEFAULT_THRESHOLDS
    section = doc.get("axis_thresholds") if isinstance(doc, dict) else None
    if not isinstance(section, dict):
        return DEFAULT_THRESHOLDS
    out: dict[str, dict[str, dict[str, float]]] = {}
    for axis_id, axis_rules in section.items():
        if not isinstance(axis_rules, dict):
            continue
        out[axis_id] = {}
        for signal_id, rule in axis_rules.items():
            if isinstance(rule, dict):
                out[axis_id][signal_id] = {
                    k: float(v) for k, v in rule.items() if isinstance(v, (int, float))
                }
    # merge defaults for axes not overridden
    merged = dict(DEFAULT_THRESHOLDS)
    merged.update(out)
    return merged


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def collect_signal(
    axis_id: str,
    signal: dict[str, Any],
    *,
    jpintel_path: Path,
    autonomath_path: Path,
    analytics_dir: Path,
    thresholds: dict[str, dict[str, dict[str, float]]],
) -> SignalRow:
    sid = signal["id"]
    kind = signal["kind"]
    value: float | None = None
    json_blob: str | None = None
    note = ""
    if kind == "sqlite_count":
        db_path = _resolve_db_path(signal.get("db", "jpintel"), jpintel_path, autonomath_path)
        value, note = fetch_sqlite_count(signal["table"], db_path)
    elif kind == "analytics_json":
        value, json_blob, note = fetch_analytics_json(signal["file"], signal["path"], analytics_dir)
    elif kind == "manual_sample":
        value, json_blob, note = fetch_manual_sample(signal["ref"], analytics_dir)
    elif kind == "placeholder":
        # Source not yet wired; emit degraded with note for transparency.
        note = f"placeholder ref={signal.get('ref','?')}"
    else:
        note = f"unknown kind={kind}"
    status = classify_status(axis_id, sid, value, json_blob, thresholds)
    return SignalRow(
        axis_id=axis_id,
        signal_id=sid,
        signal_value=value,
        signal_value_json=json_blob,
        status=status,
        note=note,
    )


def build_snapshot(
    *,
    week_label: str,
    iso_date: _dt.date,
    repo_root: Path,
    jpintel_path: Path,
    autonomath_path: Path,
    analytics_dir: Path,
    threshold_yml: Path | None,
) -> EvolutionSnapshot:
    now_utc = _dt.datetime.now(_dt.timezone.utc)
    jst = _dt.timezone(_dt.timedelta(hours=9))
    now_jst = now_utc.astimezone(jst)
    snap = EvolutionSnapshot(
        snapshot_date=week_label,
        snapshot_iso_date=iso_date.isoformat(),
        git_head_sha=git_head_sha(repo_root),
        last_update_utc=now_utc.isoformat(timespec="seconds"),
        last_update_jst=now_jst.isoformat(timespec="seconds"),
    )
    thresholds = load_thresholds(threshold_yml)
    rows: list[SignalRow] = []
    for axis in AXES:
        axis_rows: list[SignalRow] = []
        for signal in axis["signals"]:
            row = collect_signal(
                axis["id"],
                signal,
                jpintel_path=jpintel_path,
                autonomath_path=autonomath_path,
                analytics_dir=analytics_dir,
                thresholds=thresholds,
            )
            axis_rows.append(row)
        rows.extend(axis_rows)
        # axis-level worst status
        statuses = [r.status for r in axis_rows]
        if "broken" in statuses:
            axis_status = "broken"
        elif "degraded" in statuses:
            axis_status = "degraded"
        else:
            axis_status = "healthy"
        snap.axes.append(
            {
                "id": axis["id"],
                "title": axis["title"],
                "status": axis_status,
                "signal_count": len(axis_rows),
                "signals": [asdict(r) for r in axis_rows],
            }
        )
    snap.rows = [asdict(r) for r in rows]
    snap.kpi_plots = collect_kpi_plots(rows, snap.snapshot_date)
    return snap


def collect_kpi_plots(
    rows: list[SignalRow], current_week: str
) -> dict[str, list[dict[str, Any]]]:
    """Materialize 5 KPI series. Current week only — historical points get
    appended by future cron runs reading the snapshot table.

    Each entry: {"axis_id":..., "signal_id":..., "snapshot_date":..., "value":...}
    """
    out: dict[str, list[dict[str, Any]]] = {}
    for axis_id, signal_id in KPI_PLOT_KEYS:
        for r in rows:
            if r.axis_id == axis_id and r.signal_id == signal_id:
                key = f"{axis_id}/{signal_id}"
                out.setdefault(key, []).append(
                    {
                        "axis_id": axis_id,
                        "signal_id": signal_id,
                        "snapshot_date": current_week,
                        "value": r.signal_value,
                        "status": r.status,
                    }
                )
                break
        else:
            key = f"{axis_id}/{signal_id}"
            out.setdefault(key, []).append(
                {
                    "axis_id": axis_id,
                    "signal_id": signal_id,
                    "snapshot_date": current_week,
                    "value": None,
                    "status": "broken",
                }
            )
    assert len(out) == 5, "expected 5 KPI plot series"
    return out


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def write_json(snap: EvolutionSnapshot, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(snap)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def upsert_db(snap: EvolutionSnapshot, db_path: Path) -> int:
    """Upsert all signal rows into evolution_dashboard_snapshot (target_db: jpintel)."""
    if not db_path.parent.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        # Ensure table exists even if migration loop has not run yet.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS evolution_dashboard_snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL,
                axis_id TEXT NOT NULL,
                signal_id TEXT NOT NULL,
                signal_value REAL,
                signal_value_json TEXT,
                status TEXT NOT NULL CHECK (status IN ('healthy','degraded','broken')),
                computed_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE (snapshot_date, axis_id, signal_id)
            )
            """
        )
        rowcount = 0
        for row in snap.rows:
            conn.execute(
                """
                INSERT INTO evolution_dashboard_snapshot
                  (snapshot_date, axis_id, signal_id, signal_value, signal_value_json, status)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (snapshot_date, axis_id, signal_id) DO UPDATE SET
                  signal_value=excluded.signal_value,
                  signal_value_json=excluded.signal_value_json,
                  status=excluded.status,
                  computed_at=datetime('now')
                """,
                (
                    snap.snapshot_date,
                    row["axis_id"],
                    row["signal_id"],
                    row["signal_value"],
                    row["signal_value_json"],
                    row["status"],
                ),
            )
            rowcount += 1
        conn.commit()
        return rowcount
    finally:
        conn.close()


def render_html(snap: EvolutionSnapshot, template_dir: Path, out_path: Path) -> None:
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    tpl = env.get_template("evolution.html.j2")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(tpl.render(snap=snap), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DEEP-42 evolution dashboard aggregator")
    parser.add_argument(
        "--repo-root", type=Path, default=Path.cwd(), help="repo root path"
    )
    parser.add_argument(
        "--week", default="current", help="ISO week 'YYYY-Www' or 'current'"
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="JSON snapshot path (default: analytics/evolution_dashboard_<YYYY-WW>.json)"
    )
    parser.add_argument(
        "--html-out",
        type=Path,
        default=Path("site/transparency/evolution.html"),
        help="HTML output path",
    )
    parser.add_argument(
        "--jpintel-db",
        type=Path,
        default=Path(os.environ.get("JPINTEL_DB_PATH", "data/jpintel.db")),
    )
    parser.add_argument(
        "--autonomath-db",
        type=Path,
        default=Path(os.environ.get("AUTONOMATH_DB_PATH", "autonomath.db")),
    )
    parser.add_argument(
        "--analytics-dir", type=Path, default=Path("analytics")
    )
    parser.add_argument(
        "--threshold-yml",
        type=Path,
        default=Path("data/evolution_thresholds.yml"),
    )
    parser.add_argument(
        "--template-dir",
        type=Path,
        default=Path("scripts/templates"),
    )
    parser.add_argument(
        "--no-db", action="store_true", help="skip DB upsert (offline / dry-run)"
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    repo_root = args.repo_root.resolve()
    week_label, iso_date = parse_week_arg(args.week)
    LOG.info("DEEP-42 evolution snapshot week=%s @ %s", week_label, repo_root)
    snap = build_snapshot(
        week_label=week_label,
        iso_date=iso_date,
        repo_root=repo_root,
        jpintel_path=args.jpintel_db,
        autonomath_path=args.autonomath_db,
        analytics_dir=args.analytics_dir,
        threshold_yml=args.threshold_yml,
    )
    out_path = args.out or Path(f"analytics/evolution_dashboard_{week_label}.json")
    write_json(snap, out_path)
    LOG.info("wrote JSON snapshot: %s (%d signals)", out_path, len(snap.rows))
    try:
        render_html(snap, args.template_dir, args.html_out)
        LOG.info("rendered HTML dashboard: %s", args.html_out)
    except Exception as exc:  # pragma: no cover - graceful render failure
        LOG.warning("HTML render skipped: %s", exc)
    if not args.no_db:
        try:
            n = upsert_db(snap, args.jpintel_db)
            LOG.info("upserted %d rows into evolution_dashboard_snapshot (%s)", n, args.jpintel_db)
        except sqlite3.Error as exc:
            LOG.warning("DB upsert skipped: %s", exc)
    # Aggregator never raises non-zero on partial source failures - dashboard
    # value is in continuous reporting, not failing the cron itself.
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
