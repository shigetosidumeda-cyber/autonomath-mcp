#!/usr/bin/env python3
"""Weekly SOC 2 audit evidence collector (Wave 18 E4).

Walks the implementation evidence paths declared in
``docs/compliance/soc2_control_map.md`` and dumps a single JSONL file
per ISO week to ``analytics/audit_evidence_{YYYY-Www}.jsonl``.

Each row captures:

    - control_id (e.g. CC6.1, A1.2, P5.1)
    - evidence_path (relative to repo root)
    - exists (bool) -- True if path resolves
    - is_dir (bool)
    - sha256 (str | null) -- hex digest for files, null for dirs
    - mtime_utc (str | null) -- ISO 8601 last-modified, null if missing
    - byte_size (int | null)
    - notes (str) -- anything the collector flagged

This is a static-only collector: no LLM, no Anthropic SDK, no operator
side-effect. Per ``feedback_no_operator_llm_api`` the script must run
entirely on local file metadata.

The accompanying audit log RSS (``site/audit-log.rss``) plus access log
retention (365 days, kept in Fly volume) are referenced but **not**
re-emitted here -- their freshness is verified by the existence /
mtime row alone, so a missing or stale feed shows up as exists=true
with mtime_utc older than 7 days.

Usage
-----
    python scripts/cron/audit_evidence_collector.py
    python scripts/cron/audit_evidence_collector.py --dry-run
    python scripts/cron/audit_evidence_collector.py --week 2026-W19

Exit codes
----------
0 success (writes file)
1 fatal (repo root not detected, write failure)
2 some evidence paths missing -- still writes output, but rc=2 for CI
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sys
from pathlib import Path

# Evidence map: (control_id, repo-relative path). Derived from
# docs/compliance/soc2_control_map.md. Keep alphabetical within each
# trust principle so future drift is easy to diff.
EVIDENCE: list[tuple[str, str]] = [
    # CC1 Control Environment
    ("CC1.1", "CODE_OF_CONDUCT.md"),
    ("CC1.2", "site/transparency.html"),
    ("CC1.3", "site/trust.html"),
    ("CC1.5", ".github/workflows/acceptance_criteria_ci.yml"),
    # CC2 Communication
    ("CC2.1", "site/audit-log.rss"),
    ("CC2.2", "docs/_internal"),
    ("CC2.3a", "site/legal"),
    ("CC2.3b", "site/security"),
    # CC3 Risk
    ("CC3.1a", "site/index.html"),
    ("CC3.1b", "docs/compliance/terms_of_service.md"),
    ("CC3.3", "scripts/ops/audit_runner_seo.py"),
    ("CC3.4a", "site/audit-log.rss"),
    ("CC3.4b", ".github/workflows/monthly-deep-audit.yml"),
    ("CC3.5", "docs/compliance/soc2_control_map.md"),
    # CC4 Monitoring
    ("CC4.1a", ".github/workflows/self-improve-weekly.yml"),
    ("CC4.1b", ".github/workflows/monthly-deep-audit.yml"),
    ("CC4.1c", ".github/workflows/audit-regression-gate.yml"),
    ("CC4.2", ".github/workflows/audit-regression-gate.yml"),
    # CC5 Control Activities
    ("CC5.1a", ".github/workflows"),
    ("CC5.1b", "src/jpintel_mcp/api"),
    ("CC5.2a", ".github/workflows/codeql.yml"),
    ("CC5.2b", ".github/workflows/sbom-publish-monthly.yml"),
    ("CC5.3", ".github/workflows/deploy.yml"),
    # CC6 Logical Access
    ("CC6.1a", "src/jpintel_mcp/api/me"),
    ("CC6.1b", "src/jpintel_mcp/api/auth_github.py"),
    ("CC6.1c", "src/jpintel_mcp/api/auth_google.py"),
    ("CC6.2a", "src/jpintel_mcp/api/me/login_request.py"),
    ("CC6.2b", "src/jpintel_mcp/api/me/login_verify.py"),
    ("CC6.3", "src/jpintel_mcp/api/me.py"),
    ("CC6.6", "fly.toml"),
    ("CC6.7a", "fly.toml"),
    ("CC6.7b", "cloudflare-rules.yaml"),
    ("CC6.8a", "Dockerfile"),
    ("CC6.8b", ".github/workflows/codeql.yml"),
    # CC7 System Operations
    ("CC7.1a", ".github/workflows/monthly-deep-audit.yml"),
    ("CC7.1b", "scripts/ops/audit_runner_seo.py"),
    ("CC7.2a", "scripts/cron/cf_ai_audit_dump.py"),
    ("CC7.2b", "scripts/ops/rum_aggregator.py"),
    ("CC7.3", "site/security/policy.md"),
    ("CC7.5a", "scripts/cron/backup_autonomath.py"),
    ("CC7.5b", "scripts/cron/backup_jpintel.py"),
    ("CC7.5c", "scripts/cron/restore_drill_monthly.py"),
    ("CC7.5d", ".github/workflows/restore-drill-monthly.yml"),
    # CC8 Change Management
    ("CC8.1a", ".github/workflows/acceptance_criteria_ci.yml"),
    ("CC8.1b", ".github/workflows/test.yml"),
    # CC9 Risk Mitigation
    ("CC9.1a", "scripts/cron/restore_drill_monthly.py"),
    ("CC9.1b", "scripts/cron/dispatch_webhooks.py"),
    ("CC9.2", "site/legal/subprocessors.md"),
    # Availability
    ("A1.1a", "fly.toml"),
    ("A1.1b", "src/jpintel_mcp/db/schema.sql"),
    ("A1.2a", ".github/workflows/nightly-backup.yml"),
    ("A1.2b", ".github/workflows/weekly-backup-autonomath.yml"),
    ("A1.2c", ".github/workflows/restore-drill-monthly.yml"),
    ("A1.3a", ".github/workflows/restore-drill-monthly.yml"),
    ("A1.3b", ".github/workflows/health-drill-monthly.yml"),
    ("A1.3c", "scripts/cron/health_drill.py"),
    # Processing Integrity
    ("PI1.1", "src/jpintel_mcp/api/_field_filter.py"),
    ("PI1.2a", "scripts/cron/cross_source_check.py"),
    ("PI1.2b", "scripts/cron/refresh_amendment_diff.py"),
    ("PI1.3a", "src/jpintel_mcp/api/_audit_seal.py"),
    ("PI1.3b", "scripts/cron/merkle_anchor_daily.py"),
    ("PI1.5a", ".github/workflows/production-gate-dashboard-daily.yml"),
    ("PI1.5b", "src/jpintel_mcp/db/schema.sql"),
    # Confidentiality
    ("C1.1a", "src/jpintel_mcp/api/_license_gate.py"),
    ("C1.1b", "src/jpintel_mcp/api/_audit_log.py"),
    ("C1.2a", "src/jpintel_mcp/api/me.py"),
    ("C1.2b", "docs/compliance/privacy_policy.md"),
    # Privacy
    ("P1.1a", "docs/compliance/privacy_policy.md"),
    ("P1.1b", "docs/compliance/tokushoho.md"),
    ("P1.1c", "docs/compliance/landing_disclaimer.md"),
    ("P3.2a", "docs/compliance/data_subject_rights.md"),
    ("P3.2b", "site/legal/dpa_template.pdf"),
    ("P3.2c", "functions/dpa_issue.ts"),
    ("P5.1", "src/jpintel_mcp/api/me.py"),
    ("P6.1a", "site/legal/subprocessors.md"),
    ("P6.1b", "site/audit-log.rss"),
    ("P8.1a", "scripts/cron/audit_evidence_collector.py"),
    ("P8.1b", "site/transparency.html"),
]


def _repo_root() -> Path:
    """Detect repo root by walking up until fly.toml + .github are found."""
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "fly.toml").exists() and (parent / ".github").is_dir():
            return parent
    raise SystemExit("fatal: could not locate repo root (looked for fly.toml + .github)")


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _collect_row(repo: Path, control_id: str, rel: str) -> dict:
    p = repo / rel
    exists = p.exists()
    is_dir = exists and p.is_dir()
    notes = []
    if not exists:
        notes.append("missing")
    sha = None if (is_dir or not exists) else _sha256(p)
    mtime_utc = None
    byte_size = None
    if exists:
        try:
            st = p.stat()
            mtime_utc = _dt.datetime.fromtimestamp(st.st_mtime, tz=_dt.timezone.utc).isoformat()
            byte_size = st.st_size if not is_dir else None
        except OSError:
            notes.append("stat-failed")
    # RSS / audit feed freshness check
    if rel.endswith(".rss") and mtime_utc:
        age = (_dt.datetime.now(tz=_dt.timezone.utc) - _dt.datetime.fromisoformat(mtime_utc)).days
        if age > 7:
            notes.append(f"stale-{age}d")
    return {
        "control_id": control_id,
        "evidence_path": rel,
        "exists": exists,
        "is_dir": is_dir,
        "sha256": sha,
        "mtime_utc": mtime_utc,
        "byte_size": byte_size,
        "notes": ",".join(notes) or "ok",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print rows to stdout, do not write file.")
    parser.add_argument("--week", default=None, help="ISO week (YYYY-Www). Default: current UTC week.")
    args = parser.parse_args(argv)

    repo = _repo_root()
    now = _dt.datetime.now(tz=_dt.timezone.utc)
    iso_y, iso_w, _ = now.isocalendar()
    week = args.week or f"{iso_y:04d}-W{iso_w:02d}"

    rows = [_collect_row(repo, cid, rel) for cid, rel in EVIDENCE]
    missing = [r for r in rows if not r["exists"]]

    if args.dry_run:
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))
        print(f"# week={week} total={len(rows)} missing={len(missing)}", file=sys.stderr)
        return 2 if missing else 0

    out_dir = repo / "analytics"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"audit_evidence_{week}.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False))
            fh.write("\n")
    print(f"wrote {out} ({len(rows)} rows, {len(missing)} missing)")
    return 2 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
