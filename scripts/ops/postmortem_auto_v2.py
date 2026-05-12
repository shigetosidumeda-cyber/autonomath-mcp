#!/usr/bin/env python3
"""Wave 43.3.10 cell 11 — Auto postmortem draft generator (v2).

Detects incidents (healthz 5xx > 5min OR cron fail > 24h), then renders a
rule-based markdown draft at ``docs/postmortem/{date}_auto_{kind}.md`` and
opens a draft PR with the ``gh`` CLI. NO LLM call — pure template fill from
``site/status/status.json`` + ``analytics/cron_health_24h.json`` +
``site/status/sla_breach_w43_3_10.json`` (cell 10 output) so the script
remains deterministic in CI / offline.

Wave 25 base (manual postmortem under ``docs/postmortem/``) is extended
with:
  * incident detection (3 axes: healthz / cron / sla)
  * deterministic template fill (timeline / impact / mitigation /
    follow-ups), no LLM
  * draft PR open (``gh pr create --draft``) — best-effort, skipped when
    ``gh`` is absent

Usage:
    python3 scripts/ops/postmortem_auto_v2.py --kind auto
    python3 scripts/ops/postmortem_auto_v2.py --kind healthz5xx --force
    python3 scripts/ops/postmortem_auto_v2.py --kind cronfail --dry-run

Output exit codes: 0 ok / 1 misuse / 2 detection-failed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ANALYTICS = REPO_ROOT / "analytics"
SITE_STATUS = REPO_ROOT / "site" / "status"
POSTMORTEM_DIR = REPO_ROOT / "docs" / "postmortem"

# Detection thresholds.
HEALTHZ_5XX_WINDOW_MIN = 5
HEALTHZ_5XX_RATE_MAX = 0.01  # >1% 5xx in window triggers incident
CRON_FAIL_WINDOW_HOURS = 24
CRON_FAIL_THRESHOLD = 0.80  # success rate <0.80 in 24h triggers incident
SLA_BREACH_CRITICAL_COUNT = 3  # 3+ concurrent SLA breaches triggers incident


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_jst_date() -> str:
    # JST date label for postmortem filename.
    from datetime import timedelta
    return (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")


def _load(rel: str) -> dict[str, Any] | None:
    p = REPO_ROOT / rel
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def detect_incidents() -> list[dict[str, Any]]:
    """Return a list of incident records (one per breaching axis). Empty
    list means no incident to draft.
    """
    incidents: list[dict[str, Any]] = []

    # Axis 1: healthz 5xx rate above threshold.
    status = _load("site/status/status.json") or {}
    h5xx_rate = status.get("healthz_5xx_rate_5m")
    if isinstance(h5xx_rate, (int, float)) and h5xx_rate > HEALTHZ_5XX_RATE_MAX:
        incidents.append({
            "kind": "healthz5xx",
            "severity": "P1" if h5xx_rate < 0.05 else "P0",
            "detected_at": _now_iso(),
            "signal": f"healthz 5xx rate {h5xx_rate:.3%} > {HEALTHZ_5XX_RATE_MAX:.2%} (5min window)",
            "evidence": {"healthz_5xx_rate_5m": h5xx_rate,
                         "uptime_24h_pct": status.get("uptime_24h_pct")},
        })

    # Axis 2: cron 24h success rate below threshold.
    cron = _load("analytics/cron_health_24h.json") or {}
    cron_rate = cron.get("success_rate_24h")
    if isinstance(cron_rate, (int, float)) and cron_rate < CRON_FAIL_THRESHOLD:
        incidents.append({
            "kind": "cronfail",
            "severity": "P1" if cron_rate >= 0.50 else "P0",
            "detected_at": _now_iso(),
            "signal": f"cron success_rate_24h={cron_rate:.2%} < {CRON_FAIL_THRESHOLD:.0%}",
            "evidence": {"success_rate_24h": cron_rate,
                         "failed_jobs": cron.get("failed_jobs", [])[:10]},
        })

    # Axis 3: SLA breach count (uses cell 10 sidecar).
    sla = _load("site/status/sla_breach_w43_3_10.json") or {}
    breach_count = sla.get("breach_count", 0)
    if isinstance(breach_count, int) and breach_count >= SLA_BREACH_CRITICAL_COUNT:
        breaches = [m["id"] for m in (sla.get("metrics") or []) if m.get("breach")]
        incidents.append({
            "kind": "slacluster",
            "severity": "P1" if breach_count < 6 else "P0",
            "detected_at": _now_iso(),
            "signal": f"{breach_count} concurrent SLA breaches ≥ {SLA_BREACH_CRITICAL_COUNT}",
            "evidence": {"breach_count": breach_count, "breach_ids": breaches[:12]},
        })

    return incidents


def render_md(incident: dict[str, Any], date_label: str) -> str:
    kind = incident["kind"]
    severity = incident["severity"]
    detected_at = incident["detected_at"]
    signal = incident["signal"]
    evidence = incident.get("evidence", {})

    # Rule-based template — no LLM. Wave 41 J postmortem v2 lineage.
    lines = [
        f"# Postmortem — {date_label} ({kind}) [AUTO-DRAFT]",
        "",
        f"**Severity**: {severity}  ",
        f"**Detected at**: {detected_at}  ",
        f"**Trigger**: {signal}  ",
        "**Status**: AUTO-DRAFT — operator must verify timeline + complete mitigation before merging.",
        "",
        "## Summary",
        "",
        f"自動検出された incident ({kind}). 以下の signal が threshold を超過したため、",
        "Wave 43.3.10 cell 11 (postmortem_auto_v2.py) が rule-based template から起案。",
        "",
        "## Impact",
        "",
        f"- Detected signal: `{signal}`",
        "- Customer-facing impact: 要 operator 補完 (RUM / endpoint surface / billing flow)",
        "- Data integrity impact: 要 verify (backup verify cell 12 sidecar 参照)",
        "",
        "## Timeline (UTC)",
        "",
        f"| Time | Event |",
        f"| --- | --- |",
        f"| {detected_at} | Auto-detector tripped: {signal} |",
        f"| TBD | Operator acknowledged |",
        f"| TBD | Mitigation applied |",
        f"| TBD | Incident closed |",
        "",
        "## Evidence",
        "",
        "```json",
        json.dumps(evidence, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Root cause (operator to fill)",
        "",
        "TBD — operator は以下の checklist を埋めること:",
        "",
        "- [ ] proximate cause (immediate trigger)",
        "- [ ] contributing factors (config / cron drift / dependency outage)",
        "- [ ] detection gap (なぜ自動検出に hit したのか / もっと早く検出できたか)",
        "",
        "## Mitigation (operator to fill)",
        "",
        "- [ ] short-term fix (rollback / restart / config tweak)",
        "- [ ] verification (cell 10 sidecar / status_probe / RUM)",
        "",
        "## Follow-up actions",
        "",
        "- [ ] CI guard / regression test",
        "- [ ] runbook update (`docs/runbook/`)",
        "- [ ] SLA metric threshold review (`scripts/cron/sla_breach_alert.py` METRICS)",
        "- [ ] memory note (`feedback_*.md` if recurring pattern)",
        "",
        "## References",
        "",
        "- SLA snapshot: `site/status/sla_breach_w43_3_10.json` (cell 10)",
        "- Status dashboard: `site/status/monitoring.html`",
        "- AX 5pillars audit: `site/status/ax_5pillars_dashboard.html`",
        "- Wave 41 J postmortem v2 SOP: `docs/_internal/postmortem_v2_sop.md`",
        "",
        "---",
        "",
        f"_Auto-generated by `scripts/ops/postmortem_auto_v2.py` at {detected_at}._",
        "",
    ]
    return "\n".join(lines)


def write_draft(incident: dict[str, Any], date_label: str, *, force: bool) -> Path:
    kind = incident["kind"]
    path = POSTMORTEM_DIR / f"{date_label}_auto_{kind}.md"
    POSTMORTEM_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        # Append a numeric suffix to avoid clobbering.
        n = 2
        while True:
            cand = POSTMORTEM_DIR / f"{date_label}_auto_{kind}_{n}.md"
            if not cand.exists():
                path = cand
                break
            n += 1
    path.write_text(render_md(incident, date_label), encoding="utf-8")
    return path


def open_draft_pr(path: Path, incident: dict[str, Any], *, dry_run: bool) -> str:
    """Open a draft PR via gh CLI. Best-effort — skipped when gh missing or
    branch un-pushed.
    """
    if dry_run:
        return "skip:dry_run"
    try:
        subprocess.run(["gh", "--version"], check=True, capture_output=True, timeout=10)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "skip:gh_missing"
    title = f"postmortem(auto): {incident['kind']} {incident['severity']} {path.name}"
    body = (
        f"AUTO-DRAFT postmortem generated by Wave 43.3.10 cell 11.\n\n"
        f"- File: `{path.relative_to(REPO_ROOT)}`\n"
        f"- Severity: {incident['severity']}\n"
        f"- Signal: {incident['signal']}\n\n"
        "Operator must verify timeline + complete mitigation sections before flipping draft→ready.\n"
    )
    try:
        result = subprocess.run(
            ["gh", "pr", "create", "--draft", "--title", title, "--body", body],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return f"ok:{result.stdout.strip()[:200]}"
        return f"error:rc={result.returncode}:{result.stderr.strip()[:160]}"
    except subprocess.TimeoutExpired:
        return "error:timeout"


def _parse(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Wave 43.3.10 cell 11 auto postmortem v2")
    ap.add_argument("--kind", default="auto",
                    help="detection kind: auto|healthz5xx|cronfail|slacluster (auto = run all detectors)")
    ap.add_argument("--force", action="store_true", help="overwrite existing draft")
    ap.add_argument("--dry-run", action="store_true", help="render but skip PR open")
    ap.add_argument("--no-pr", action="store_true", help="skip PR open even when not dry-run")
    return ap.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    if args.kind not in ("auto", "healthz5xx", "cronfail", "slacluster"):
        print(f"ERR unknown kind={args.kind}", file=sys.stderr)
        return 1
    try:
        all_incidents = detect_incidents()
    except Exception as exc:
        print(f"ERR detection_failed err={exc}", file=sys.stderr)
        return 2
    if args.kind != "auto":
        incidents = [i for i in all_incidents if i["kind"] == args.kind]
    else:
        incidents = all_incidents
    if not incidents:
        print(json.dumps({"detected": 0, "drafted": 0, "kind": args.kind}, ensure_ascii=False))
        return 0
    date_label = _today_jst_date()
    drafted_paths: list[str] = []
    pr_results: list[str] = []
    for inc in incidents:
        path = write_draft(inc, date_label, force=args.force)
        drafted_paths.append(str(path.relative_to(REPO_ROOT)))
        if not args.no_pr:
            pr_results.append(open_draft_pr(path, inc, dry_run=args.dry_run))
    print(json.dumps({"detected": len(all_incidents), "drafted": len(drafted_paths),
                      "files": drafted_paths, "pr_results": pr_results,
                      "kind": args.kind, "dry_run": args.dry_run},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(run())
