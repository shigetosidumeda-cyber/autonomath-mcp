#!/usr/bin/env python3
"""
DEEP-58 production gate status aggregator (session A draft, jpcite v0.3.4).

Daily cron entry point that:
  1. Invokes the DEEP-49..57 verify scripts via subprocess (graceful, never raises),
  2. Aggregates 4 blocker statuses + 8 ACK booleans + 33 spec implementation rows,
  3. Emits an `analytics/production_gate_<date>.json` snapshot,
  4. Upserts into the `production_gate_status` table (jpintel.db),
  5. Renders `analytics/production_gate.html` via the static jinja2 template.

Constraints (DEEP-58 spec, DEEP-26 axis B integration, jpcite CLAUDE.md):
  - LLM API import is FORBIDDEN. Only stdlib + jinja2 + sqlite3 are imported.
  - subprocess invocations time out and degrade to PARTIAL on non-zero exit.
  - Never propose a paid plan / sales surface; transparency = SEO uplift moat.
  - target_db is jpintel for `production_gate_status` upsert (not autonomath).

This file is a *draft* under the session A executable_artifacts lane.
Real `scripts/cron/aggregate_production_gate_status.py` is written by a
follow-up CL that copies this body verbatim with the path adjusted; nothing
under `src/`, `scripts/cron/`, or `scripts/etl/` is mutated by this draft.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# jinja2 is the ONLY non-stdlib dependency. It must be importable.
try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError as exc:  # pragma: no cover - hard fail signals dep gap
    print(
        "[FATAL] jinja2 is required (pip install jinja2). "
        "LLM API imports are forbidden in this script.",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc

LOG = logging.getLogger("deep58.aggregate")

# ---------------------------------------------------------------------------
# Constants: 4 blocker IDs, 8 ACK booleans, 33 spec rows.
# ---------------------------------------------------------------------------

BLOCKERS: list[dict[str, str]] = [
    {
        "id": "BLOCKER_DIRTY_TREE",
        "title": "dirty tree fingerprint",
        "deep": "DEEP-56",
        "verify_cmd": "scripts/compute_dirty_fingerprint.py",
    },
    {
        "id": "BLOCKER_WORKFLOW_TRACKING",
        "title": "workflow targets sync",
        "deep": "DEEP-49",
        "verify_cmd": "scripts/sync_workflow_targets.py --check",
    },
    {
        "id": "BLOCKER_OPERATOR_ACK",
        "title": "operator ACK signoff",
        "deep": "DEEP-51",
        "verify_cmd": "scripts/operator_ack_signoff.py --dry-run --json",
    },
    {
        "id": "BLOCKER_DELIVERY_STRICT",
        "title": "delivery strict (pre-deploy)",
        "deep": "DEEP-50",
        "verify_cmd": "scripts/pre_deploy_verify.py --json",
    },
]

# 8 ACK booleans (DEEP-51 operator_ack_signoff.py contract).
ACK_BOOLEANS: list[dict[str, str]] = [
    {"id": "ACK_MIGRATION_TARGETS", "title": "migration targets verified", "deep": "DEEP-52"},
    {"id": "ACK_FINGERPRINT_CLEAN", "title": "dirty tree fingerprint clean", "deep": "DEEP-56"},
    {"id": "ACK_WORKFLOWS_TRACKED", "title": "GHA workflows tracked", "deep": "DEEP-49"},
    {"id": "ACK_DELIVERY_STRICT", "title": "delivery strict tests green", "deep": "DEEP-50"},
    {"id": "ACK_SMOKE_RUNBOOK", "title": "smoke runbook executed", "deep": "DEEP-61"},
    {"id": "ACK_LANE_ENFORCED", "title": "dual-CLI lane enforcer green", "deep": "DEEP-60"},
    {"id": "ACK_RELEASE_READINESS", "title": "release readiness CI green", "deep": "DEEP-59"},
    {"id": "ACK_PROD_RUNBOOK", "title": "prod deploy runbook signed", "deep": "DEEP-57"},
]

# 33 spec implementation rows (DEEP-22..57). Each row gets last_check via
# the corresponding scripts/verify/deep_<id>_verify.sh convention if present;
# otherwise the row reports `pending` and a stable warning.
SPEC_IDS: list[str] = [f"DEEP-{n}" for n in range(22, 55)]
assert len(SPEC_IDS) == 33, "expected 33 spec rows DEEP-22..54 inclusive"

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class VerifyResult:
    """One subprocess invocation's normalized result."""

    cmd: str
    returncode: int
    stdout: str
    stderr: str
    sha256: str
    duration_ms: int
    timed_out: bool = False
    error: str | None = None

    @property
    def status(self) -> str:
        if self.timed_out or self.error is not None:
            return "PARTIAL"
        if self.returncode == 0:
            return "RESOLVED"
        return "BLOCKED"


@dataclass
class GateSnapshot:
    """Top-level snapshot serialized to JSON + rendered to HTML."""

    snapshot_date: str
    git_head_sha: str
    blockers: list[dict[str, Any]] = field(default_factory=list)
    acks: list[dict[str, Any]] = field(default_factory=list)
    specs: list[dict[str, Any]] = field(default_factory=list)
    last_update_utc: str = ""
    last_update_jst: str = ""
    schema_version: str = "deep58.v1"


# ---------------------------------------------------------------------------
# subprocess helpers (graceful degradation)
# ---------------------------------------------------------------------------


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def run_verify(cmd: str, *, repo_root: Path, timeout_sec: int = 120) -> VerifyResult:
    """Invoke a verify command relative to repo_root; never raise."""

    started = _dt.datetime.now(_dt.timezone.utc)
    parts = cmd.split()
    full = (
        [sys.executable, str(repo_root / parts[0]), *parts[1:]]
        if parts[0].endswith(".py")
        else parts
    )
    try:
        proc = subprocess.run(  # noqa: S603 - controlled command list
            full,
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        elapsed_ms = int((_dt.datetime.now(_dt.timezone.utc) - started).total_seconds() * 1000)
        return VerifyResult(
            cmd=cmd,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            sha256=_sha256_text(proc.stdout),
            duration_ms=elapsed_ms,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed_ms = int((_dt.datetime.now(_dt.timezone.utc) - started).total_seconds() * 1000)
        return VerifyResult(
            cmd=cmd,
            returncode=-1,
            stdout=exc.stdout or "",
            stderr=(exc.stderr or "") + f"\n[TIMEOUT after {timeout_sec}s]",
            sha256=_sha256_text(exc.stdout or ""),
            duration_ms=elapsed_ms,
            timed_out=True,
            error="timeout",
        )
    except (FileNotFoundError, PermissionError, OSError) as exc:
        elapsed_ms = int((_dt.datetime.now(_dt.timezone.utc) - started).total_seconds() * 1000)
        return VerifyResult(
            cmd=cmd,
            returncode=-2,
            stdout="",
            stderr=str(exc),
            sha256=_sha256_text(str(exc)),
            duration_ms=elapsed_ms,
            error=str(exc),
        )


def git_head_sha(repo_root: Path) -> str:
    """Best-effort git HEAD sha; returns 'unknown' offline."""

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
# Aggregation
# ---------------------------------------------------------------------------


def _spec_evidence_path(repo_root: Path, spec_id: str) -> Path:
    """Convention: scripts/verify/<lower-spec-id>_verify.sh"""

    return repo_root / "scripts" / "verify" / f"{spec_id.lower()}_verify.sh"


def collect_blockers(repo_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in BLOCKERS:
        result = run_verify(entry["verify_cmd"], repo_root=repo_root)
        rows.append(
            {
                "id": entry["id"],
                "title": entry["title"],
                "deep": entry["deep"],
                "status": result.status,
                "returncode": result.returncode,
                "duration_ms": result.duration_ms,
                "evidence_url": entry["verify_cmd"],
                "sha256": result.sha256,
                "stderr_tail": result.stderr[-400:] if result.stderr else "",
            }
        )
    return rows


def _ack_status_from_signoff(json_text: str) -> dict[str, str]:
    """Parse operator_ack_signoff.py --json stdout into {ACK_ID: status}."""

    try:
        payload = json.loads(json_text or "{}")
    except json.JSONDecodeError:
        return {}
    acks = payload.get("acks") or {}
    out: dict[str, str] = {}
    for ack_key, value in acks.items():
        if isinstance(value, bool):
            out[ack_key] = "RESOLVED" if value else "BLOCKED"
        elif isinstance(value, str):
            up = value.upper()
            out[ack_key] = up if up in {"RESOLVED", "BLOCKED", "PARTIAL"} else "PARTIAL"
        else:
            out[ack_key] = "PARTIAL"
    return out


def collect_acks(repo_root: Path, signoff_stdout: str) -> list[dict[str, Any]]:
    parsed = _ack_status_from_signoff(signoff_stdout)
    rows: list[dict[str, Any]] = []
    for entry in ACK_BOOLEANS:
        status = parsed.get(entry["id"], "PARTIAL")
        rows.append(
            {
                "id": entry["id"],
                "title": entry["title"],
                "deep": entry["deep"],
                "status": status,
                "evidence_url": "scripts/operator_ack_signoff.py",
            }
        )
    return rows


def collect_specs(repo_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec_id in SPEC_IDS:
        verify_sh = _spec_evidence_path(repo_root, spec_id)
        if verify_sh.is_file():
            result = run_verify(
                str(verify_sh.relative_to(repo_root)), repo_root=repo_root, timeout_sec=60
            )
            status = result.status
            evidence = str(verify_sh.relative_to(repo_root))
            sha256 = result.sha256
            last_check = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        else:
            status = "PARTIAL"
            evidence = f"docs/_internal/{spec_id}_*.md"
            sha256 = ""
            last_check = ""
        rows.append(
            {
                "id": spec_id,
                "title": f"{spec_id} implementation",
                "status": status,
                "last_check": last_check,
                "evidence_url": evidence,
                "sha256": sha256,
            }
        )
    return rows


def build_snapshot(repo_root: Path) -> GateSnapshot:
    now_utc = _dt.datetime.now(_dt.timezone.utc)
    jst = _dt.timezone(_dt.timedelta(hours=9))
    now_jst = now_utc.astimezone(jst)
    snap = GateSnapshot(
        snapshot_date=now_utc.date().isoformat(),
        git_head_sha=git_head_sha(repo_root),
        last_update_utc=now_utc.isoformat(timespec="seconds"),
        last_update_jst=now_jst.isoformat(timespec="seconds"),
    )
    snap.blockers = collect_blockers(repo_root)
    # Operator ACK invocation drives the 8-ACK pane.
    signoff_cmd = "scripts/operator_ack_signoff.py --dry-run --json"
    signoff_result = run_verify(signoff_cmd, repo_root=repo_root)
    snap.acks = collect_acks(repo_root, signoff_result.stdout)
    snap.specs = collect_specs(repo_root)
    return snap


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def write_json(snap: GateSnapshot, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(snap)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def upsert_db(snap: GateSnapshot, db_path: Path) -> int:
    """Upsert blocker rows into production_gate_status; returns row count."""

    if not db_path.parent.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS production_gate_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL,
                blocker_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('BLOCKED','PARTIAL','RESOLVED')),
                evidence_url TEXT,
                sha256 TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (snapshot_date, blocker_id)
            )
            """
        )
        rowcount = 0
        for row in snap.blockers + snap.acks:
            conn.execute(
                """
                INSERT INTO production_gate_status
                  (snapshot_date, blocker_id, status, evidence_url, sha256)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (snapshot_date, blocker_id) DO UPDATE SET
                  status=excluded.status,
                  evidence_url=excluded.evidence_url,
                  sha256=excluded.sha256
                """,
                (
                    snap.snapshot_date,
                    row["id"],
                    row["status"],
                    row.get("evidence_url"),
                    row.get("sha256", ""),
                ),
            )
            rowcount += 1
        conn.commit()
        return rowcount
    finally:
        conn.close()


def render_html(snap: GateSnapshot, template_dir: Path, out_path: Path) -> None:
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    tpl = env.get_template("production_gate.html.j2")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(tpl.render(snap=snap), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DEEP-58 production gate aggregator")
    parser.add_argument(
        "--repo-root", type=Path, default=Path.cwd(), help="repo root for subprocess cwd"
    )
    today = _dt.date.today().isoformat()
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(f"analytics/production_gate_{today}.json"),
        help="JSON snapshot path",
    )
    parser.add_argument(
        "--html-out",
        type=Path,
        default=Path("analytics/production_gate.html"),
        help="HTML output path",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path(os.environ.get("JPINTEL_DB_PATH", "data/jpintel.db")),
        help="jpintel.db path (target_db: jpintel)",
    )
    parser.add_argument(
        "--template-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="directory containing production_gate.html.j2",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="skip DB upsert (useful for offline draft runs)",
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
    LOG.info("aggregating DEEP-58 production gate snapshot @ %s", repo_root)
    snap = build_snapshot(repo_root)
    write_json(snap, args.out)
    LOG.info("wrote JSON snapshot: %s", args.out)
    try:
        render_html(snap, args.template_dir, args.html_out)
        LOG.info("rendered HTML dashboard: %s", args.html_out)
    except Exception as exc:  # pragma: no cover - render failure is graceful
        LOG.warning("HTML render skipped: %s", exc)
    if not args.no_db:
        try:
            n = upsert_db(snap, args.db_path)
            LOG.info("upserted %d rows into production_gate_status (%s)", n, args.db_path)
        except sqlite3.Error as exc:
            LOG.warning("DB upsert skipped: %s", exc)
    # Aggregator never raises non-zero on partial verify failures - dashboard
    # value is in continuous reporting, not failing the cron itself.
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
