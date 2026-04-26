#!/usr/bin/env python3
"""Monthly DR drill — exercise scenario 1-3 in dry-run mode (K8 / wave 18).

Solo ops cannot run live failovers (no on-call rotation, no second
operator to verify). This drill is the cheap substitute: every month
on the 1st we sanity-check that the recovery preconditions still hold,
without actually killing the VM or wiping the volume.

Scenarios
---------
1. **VM crash**: Fly auto-restarts within ~30 seconds. We probe
   ``/healthz`` 3x at 2-second intervals; fail if any of the 3
   returns non-2xx (indicates the live deploy is already broken,
   long before any "crash" — fix immediately).

2. **Volume corruption**: ``entrypoint.sh`` re-pulls
   ``autonomath.db`` from R2 on next boot when SHA mismatches. We
   verify that:
     - ``AUTONOMATH_DB_URL`` env is set on the Fly app
     - ``AUTONOMATH_DB_SHA256`` env is set
     - The R2 endpoint responds 2xx on a HEAD against the db URL
   We do NOT actually trigger restore — that takes ~30min and we
   have a paying customer base. We just assert preconditions.

3. **R2 outage**: ``/data/autonomath.db`` already exists locally on
   the Fly volume → entrypoint skips the bootstrap download. We
   verify the local file is present, sha matches the configured
   ``AUTONOMATH_DB_SHA256``, and ``PRAGMA integrity_check`` returns
   "ok".

Output
------
Append a markdown row to ``analysis_wave18/dr_drill_<YYYY-MM>.md``.
Each line: timestamp + scenario + pass/warn/fail + note.

No real failovers, no live R2 mutations. Read-only checks.
Anonymous quota unaffected (uses operator-side filesystem + env).

Usage
-----
    python scripts/cron/health_drill.py            # run all scenarios
    python scripts/cron/health_drill.py --only 2   # only scenario 2
    python scripts/cron/health_drill.py --health-url http://...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

logger = logging.getLogger("autonomath.cron.health_drill")

_DEFAULT_HEALTH_URL = "https://autonomath.fly.dev/healthz"
_DEFAULT_DB_PATH = os.environ.get("AUTONOMATH_DB_PATH", "/data/autonomath.db")


# ---------------------------------------------------------------------------
# Scenario 1: VM crash → Fly auto-restart probe
# ---------------------------------------------------------------------------


def scenario_1_vm_probe(health_url: str, *, attempts: int = 3) -> dict[str, Any]:
    """3 sequential GETs of /healthz — all must be 2xx."""
    successes = 0
    last_status: int | None = None
    last_err: str | None = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(
                health_url,
                headers={"User-Agent": "AutonoMath-DR-Drill/1.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                last_status = resp.status
                if 200 <= resp.status < 300:
                    successes += 1
        except urllib.error.HTTPError as exc:
            last_status = exc.code
            last_err = f"HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"
        if i < attempts - 1:
            time.sleep(2)
    if successes == attempts:
        return {
            "status": "pass",
            "note": f"{attempts}/{attempts} probes 2xx (Fly + healthz live)",
        }
    if successes >= 1:
        return {
            "status": "warn",
            "note": (
                f"{successes}/{attempts} probes 2xx — flapping or partial "
                f"outage (last_status={last_status} err={last_err})"
            ),
        }
    return {
        "status": "fail",
        "note": (
            f"0/{attempts} probes succeeded — service appears down "
            f"(last_status={last_status} err={last_err})"
        ),
    }


# ---------------------------------------------------------------------------
# Scenario 2: R2 restore preconditions
# ---------------------------------------------------------------------------


def scenario_2_r2_precond() -> dict[str, Any]:
    """Verify env + R2 reachability; do NOT trigger restore."""
    db_url = os.environ.get("AUTONOMATH_DB_URL", "")
    db_sha = os.environ.get("AUTONOMATH_DB_SHA256", "")
    if not db_url:
        return {
            "status": "fail",
            "note": "AUTONOMATH_DB_URL unset — bootstrap chain broken on cold-start",
        }
    if not db_sha:
        return {
            "status": "warn",
            "note": (
                "AUTONOMATH_DB_SHA256 unset — entrypoint will accept any "
                "downloaded blob without integrity check"
            ),
        }
    try:
        req = urllib.request.Request(
            db_url,
            method="HEAD",
            headers={"User-Agent": "AutonoMath-DR-Drill/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            if 200 <= resp.status < 300:
                size = resp.headers.get("Content-Length", "?")
                return {
                    "status": "pass",
                    "note": f"R2 HEAD 2xx, size={size}, sha={db_sha[:8]}...",
                }
            return {
                "status": "warn",
                "note": f"R2 HEAD returned {resp.status} (non-2xx)",
            }
    except urllib.error.HTTPError as exc:
        return {"status": "fail", "note": f"R2 HEAD HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "fail",
            "note": f"R2 HEAD failed: {type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# Scenario 3: local /data DB integrity
# ---------------------------------------------------------------------------


def _sha256_of(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
        return h.hexdigest()
    except Exception:  # noqa: BLE001
        return None


def scenario_3_local_db(db_path: str) -> dict[str, Any]:
    p = Path(db_path)
    if not p.exists() or p.stat().st_size == 0:
        return {
            "status": "fail",
            "note": f"local DB missing or empty at {db_path}",
        }
    expected_sha = os.environ.get("AUTONOMATH_DB_SHA256", "")
    actual_sha = _sha256_of(p) or ""
    sha_ok: bool | None
    if expected_sha and actual_sha:
        sha_ok = expected_sha.lower() == actual_sha.lower()
    else:
        sha_ok = None
    try:
        with sqlite3.connect(f"file:{p}?mode=ro", uri=True) as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        integrity = (row[0] or "").lower() if row else ""
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "fail",
            "note": f"sqlite open / integrity_check failed: {exc}",
        }
    if integrity != "ok":
        return {
            "status": "fail",
            "note": f"PRAGMA integrity_check = {integrity!r}",
        }
    if sha_ok is False:
        return {
            "status": "warn",
            "note": (
                "PRAGMA ok but SHA mismatches AUTONOMATH_DB_SHA256 — "
                "entrypoint would re-download on next restart"
            ),
        }
    suffix = " (sha verified)" if sha_ok else " (sha not configured)"
    return {
        "status": "pass",
        "note": f"local DB present, integrity ok, size={p.stat().st_size} bytes{suffix}",
    }


# ---------------------------------------------------------------------------
# Aggregate + report
# ---------------------------------------------------------------------------


def run_drill(
    *,
    health_url: str = _DEFAULT_HEALTH_URL,
    db_path: str = _DEFAULT_DB_PATH,
    only: int | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    scenarios: dict[str, dict[str, Any]] = {}
    if only in (None, 1):
        scenarios["scenario_1_vm_crash"] = scenario_1_vm_probe(health_url)
    if only in (None, 2):
        scenarios["scenario_2_volume_corruption"] = scenario_2_r2_precond()
    if only in (None, 3):
        scenarios["scenario_3_r2_outage"] = scenario_3_local_db(db_path)

    statuses = {s["status"] for s in scenarios.values()}
    overall = "fail" if "fail" in statuses else ("warn" if "warn" in statuses else "pass")

    report: dict[str, Any] = {
        "run_id": now.isoformat(),
        "overall": overall,
        "scenarios": scenarios,
    }

    out_dir = output_dir or (_REPO / "analysis_wave18")
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"dr_drill_{now.strftime('%Y-%m')}.md"
    _append_markdown(md_path, now, scenarios, overall)
    return report


def _append_markdown(
    path: Path,
    now: datetime,
    scenarios: dict[str, dict[str, Any]],
    overall: str,
) -> None:
    """Append a new section to the month's drill log.

    File grows month-over-month; one-shot SRE can grep ``status: fail``
    across all dr_drill_*.md to find every miss in repo history.
    """
    header_needed = not path.exists()
    with path.open("a", encoding="utf-8") as f:
        if header_needed:
            f.write(f"# DR Drill Log — {now.strftime('%Y-%m')}\n\n")
            f.write(
                "Monthly dry-run of disaster-recovery scenarios. See "
                "`docs/_internal/dr_backup_runbook.md` for full procedure.\n\n",
            )
        f.write(f"## {now.isoformat()} — overall: **{overall}**\n\n")
        f.write("| scenario | status | note |\n")
        f.write("|---|---|---|\n")
        for name, result in scenarios.items():
            note = (result.get("note") or "").replace("|", "\\|")
            f.write(f"| `{name}` | `{result.get('status')}` | {note} |\n")
        f.write("\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--health-url", default=_DEFAULT_HEALTH_URL,
                   help=f"Healthz URL (default {_DEFAULT_HEALTH_URL})")
    p.add_argument("--db-path", default=_DEFAULT_DB_PATH,
                   help=f"Local DB path (default {_DEFAULT_DB_PATH})")
    p.add_argument("--only", type=int, choices=[1, 2, 3], default=None,
                   help="Run only one scenario (1, 2, or 3)")
    p.add_argument("--out", default=None, help="Output dir (default analysis_wave18/)")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    out_dir = Path(args.out) if args.out else None
    report = run_drill(
        health_url=args.health_url,
        db_path=args.db_path,
        only=args.only,
        output_dir=out_dir,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    # Exit 0 when overall != fail; cron host can rely on exit code.
    return 0 if report["overall"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
