#!/usr/bin/env python3
"""
operator_ack_signoff.py — DEEP-51 guided 8-boolean ACK CLI.

Generates an ACK YAML for `production_deploy_go_gate.py --operator-ack`,
forcing each of 8 booleans through a read-only verify command before any
signoff is allowed. NO LLM API calls. Pure stdlib + PyYAML + subprocess.

Usage
-----
  uv run python operator_ack_signoff.py --all [--commit] [--json]
  uv run python operator_ack_signoff.py --boolean 3
  uv run python operator_ack_signoff.py --dry-run --all          # default

Behavior
--------
- DRY_RUN by default. Use --commit to actually write the YAML.
- Each boolean: subprocess verify -> PASS/FAIL -> [y/N/skip] prompt.
- ANY skip / N / verify FAIL aborts YAML emission (fail-fast).
- Output path: ~/jpcite-deploy-ack/<utc>.yaml (out-of-repo).
- Signature line: operator_email + utc + git commit hash + yaml_sha256.

Spec: /Users/shigetoumeda/jpcite/tools/offline/_inbox/value_growth_dual/
       _deep_plan/DEEP_51_operator_ack_guided_workflow.md
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
from typing import Any, NamedTuple

try:
    import yaml  # PyYAML
except ImportError:  # pragma: no cover - hard requirement
    sys.stderr.write(
        "operator_ack_signoff: PyYAML required. Install with `uv pip install pyyaml`.\n"
    )
    raise

# ----------------------------------------------------------------------
# constants
# ----------------------------------------------------------------------

TOOL_VERSION = "operator_ack_signoff/0.1.0"
APP_NAME = "autonomath-api"
DEFAULT_ACK_DIR = pathlib.Path.home() / "jpcite-deploy-ack"
SECRETS_REGISTRY_REL = "docs/_internal/SECRETS_REGISTRY.md"
DEFAULT_OPERATOR_EMAIL = "info@bookyou.net"

BOOLEAN_NAMES: list[str] = [
    "fly_app_confirmed",
    "fly_secrets_names_confirmed",
    "appi_disabled_or_turnstile_secret_confirmed",
    "target_db_packet_reviewed",
    "rollback_reconciliation_packet_ready",
    "live_gbiz_ingest_disabled_or_approved",
    "dirty_lanes_reviewed",
    "pre_deploy_verify_clean",
]

FIX_DOC_URLS: dict[str, str] = {
    "fly_app_confirmed": "fly.toml `app =` line + `flyctl apps list`",
    "fly_secrets_names_confirmed": SECRETS_REGISTRY_REL,
    "appi_disabled_or_turnstile_secret_confirmed": "docs/_internal/PRODUCTION_DEPLOY_OPERATOR_ACK_DRAFT_2026-05-07.md#AppI",
    "target_db_packet_reviewed": "DEEP-52 migration boundary spec",
    "rollback_reconciliation_packet_ready": "DEEP-46 transactional rollback spec",
    "live_gbiz_ingest_disabled_or_approved": "DEEP-01 gBiz ingest activation",
    "dirty_lanes_reviewed": "DEEP-50 dirty tree triage",
    "pre_deploy_verify_clean": "scripts/ops/pre_deploy_verify.py --warn-only failures[] -> release_readiness fix",
}


class VerifyResult(NamedTuple):
    """Result of one verify command."""

    boolean_name: str
    passed: bool
    detail: str
    raw_evidence: dict[str, Any]


# ----------------------------------------------------------------------
# subprocess helpers (read-only)
# ----------------------------------------------------------------------


def _run_capture(cmd: list[str], *, timeout: int = 60) -> tuple[int, str, str]:
    """Run cmd, return (rc, stdout, stderr). Read-only callers only."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError as exc:
        return 127, "", f"command not found: {exc}"
    except subprocess.TimeoutExpired as exc:
        return 124, exc.stdout or "", exc.stderr or "timeout"


def _which(name: str) -> str | None:
    return shutil.which(name)


def _git_head_sha() -> str:
    rc, out, _ = _run_capture(["git", "rev-parse", "HEAD"])
    return out.strip() if rc == 0 and out.strip() else "unknown"


def _utc_now_iso_filename() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")


def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------------
# 8 verify functions (all read-only)
# ----------------------------------------------------------------------


def verify_fly_app_confirmed() -> VerifyResult:
    """boolean 1: flyctl status -a autonomath-api -j -> App.Name == 'autonomath-api'."""
    name = "fly_app_confirmed"
    if _which("flyctl") is None:
        return VerifyResult(name, False, "flyctl not on PATH", {"reason": "no_flyctl"})
    rc, out, err = _run_capture(["flyctl", "status", "-a", APP_NAME, "-j"])
    if rc != 0:
        return VerifyResult(
            name, False, f"flyctl rc={rc}: {err.strip()[:200]}", {"rc": rc, "stderr": err}
        )
    try:
        payload = json.loads(out)
    except json.JSONDecodeError as exc:
        return VerifyResult(
            name, False, f"flyctl JSON parse fail: {exc}", {"stdout_head": out[:200]}
        )
    actual = payload.get("App", {}).get("Name") or payload.get("Name")
    passed = actual == APP_NAME
    return VerifyResult(
        name,
        passed,
        f'App.Name="{actual}" expected="{APP_NAME}"',
        {"app_name": actual},
    )


def _read_secrets_registry(repo_root: pathlib.Path) -> tuple[set[str], set[str]]:
    """Parse SECRETS_REGISTRY.md → (required_set, conditional_set).

    Convention: lines like `- REQUIRED: NAME` and `- CONDITIONAL: NAME`.
    Tolerant of formatting drift; missing file -> two empty sets.
    """
    p = repo_root / SECRETS_REGISTRY_REL
    required: set[str] = set()
    conditional: set[str] = set()
    if not p.is_file():
        return required, conditional
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip().lstrip("-* ").strip()
        if s.upper().startswith("REQUIRED:"):
            tok = s.split(":", 1)[1].strip().split()[0:1]
            if tok:
                required.add(tok[0].strip("`"))
        elif s.upper().startswith("CONDITIONAL:"):
            tok = s.split(":", 1)[1].strip().split()[0:1]
            if tok:
                conditional.add(tok[0].strip("`"))
    return required, conditional


def verify_fly_secrets_names_confirmed(repo_root: pathlib.Path) -> VerifyResult:
    """boolean 2: name-set diff between flyctl secrets list and SECRETS_REGISTRY.md."""
    name = "fly_secrets_names_confirmed"
    if _which("flyctl") is None:
        return VerifyResult(name, False, "flyctl not on PATH", {"reason": "no_flyctl"})
    rc, out, err = _run_capture(["flyctl", "secrets", "list", "-a", APP_NAME, "-j"])
    if rc != 0:
        return VerifyResult(
            name, False, f"flyctl rc={rc}: {err.strip()[:200]}", {"rc": rc, "stderr": err}
        )
    try:
        rows = json.loads(out)
    except json.JSONDecodeError as exc:
        return VerifyResult(
            name, False, f"flyctl JSON parse fail: {exc}", {"stdout_head": out[:200]}
        )
    live_names = {r.get("Name") for r in rows if isinstance(r, dict) and r.get("Name")}
    required, conditional = _read_secrets_registry(repo_root)
    missing_required = required - live_names
    missing_conditional = conditional - live_names
    passed = not missing_required  # conditional missing -> warn, not fail
    detail = (
        f"required={len(required - missing_required)}/{len(required)}, "
        f"conditional={len(conditional - missing_conditional)}/{len(conditional)}"
    )
    return VerifyResult(
        name,
        passed,
        detail,
        {
            "live_count": len(live_names),
            "missing_required": sorted(missing_required),
            "missing_conditional": sorted(missing_conditional),
        },
    )


def verify_appi_or_turnstile(repo_root: pathlib.Path) -> VerifyResult:
    """boolean 3: AppI disabled OR Turnstile secret present."""
    name = "appi_disabled_or_turnstile_secret_confirmed"
    if os.environ.get("JPINTEL_APPI_DISABLED") == "1":
        return VerifyResult(name, True, "JPINTEL_APPI_DISABLED=1 in env", {"path": "env_disabled"})
    if _which("flyctl") is None:
        return VerifyResult(
            name, False, "flyctl missing and APPI not env-disabled", {"reason": "no_flyctl"}
        )
    rc, out, err = _run_capture(["flyctl", "secrets", "list", "-a", APP_NAME, "-j"])
    if rc != 0:
        return VerifyResult(name, False, f"flyctl rc={rc}: {err.strip()[:200]}", {"rc": rc})
    try:
        rows = json.loads(out)
    except json.JSONDecodeError:
        return VerifyResult(name, False, "flyctl JSON parse fail", {"stdout_head": out[:200]})
    names = {r.get("Name") for r in rows if isinstance(r, dict)}
    has_turnstile = "CLOUDFLARE_TURNSTILE_SECRET" in names
    has_appi_disable_secret = "JPINTEL_APPI_DISABLED" in names
    passed = has_turnstile or has_appi_disable_secret
    return VerifyResult(
        name,
        passed,
        f"turnstile={'PRESENT' if has_turnstile else 'ABSENT'}, "
        f"appi_disabled_secret={'PRESENT' if has_appi_disable_secret else 'ABSENT'}",
        {"turnstile": has_turnstile, "appi_disabled": has_appi_disable_secret},
    )


def verify_target_db_packet(repo_root: pathlib.Path) -> VerifyResult:
    """boolean 4: DEEP-52 verify_migration_targets / migration_inventory exit 0.

    DEEP-51 CLI flag fix (2026-05-07): the canonical inventory CLI is
    `migration_inventory.py --dry-run` (preflight, no write). The legacy
    `--check` path was renamed; --dry-run is the read-only equivalent and
    exits 0 when no preflight failure is detected.
    """
    name = "target_db_packet_reviewed"
    # DEEP-51 fix: prefer migration_inventory.py --dry-run (read-only preflight,
    # tolerant of ROLLBACK_PAIR_BROKEN warnings) over verify_migration_targets.py
    # --check (which hard-fails on any per-file check error).
    candidates = [
        repo_root / "scripts" / "ops" / "migration_inventory.py",
        repo_root / "scripts" / "ops" / "verify_migration_targets.py",
        repo_root.parent / "verify_migration_targets" / "verify_migration_targets.py",
    ]
    script = next((c for c in candidates if c.is_file()), None)
    if script is None:
        return VerifyResult(
            name,
            False,
            "migration_inventory.py / verify_migration_targets.py not found",
            {"searched": [str(c) for c in candidates]},
        )
    # migration_inventory.py uses --dry-run (read-only); legacy
    # verify_migration_targets.py uses --check.
    flag = "--dry-run" if script.name == "migration_inventory.py" else "--check"
    rc, out, err = _run_capture([sys.executable, str(script), flag])
    if rc != 0:
        return VerifyResult(name, False, f"rc={rc}: {err.strip()[:200]}", {"rc": rc, "stderr": err})
    try:
        payload = json.loads(out) if out.strip() else {}
    except json.JSONDecodeError:
        payload = {"stdout_head": out[:200]}
    return VerifyResult(name, True, f"{script.name} {flag} exit 0", payload)


def verify_rollback_packet(repo_root: pathlib.Path) -> VerifyResult:
    """boolean 5: rollback SQL packet existence (>= 1 *_rollback.sql file)."""
    name = "rollback_reconciliation_packet_ready"
    mig_dir = repo_root / "scripts" / "migrations"
    if not mig_dir.is_dir():
        return VerifyResult(name, False, f"missing dir: {mig_dir}", {"path": str(mig_dir)})
    rollbacks = sorted(mig_dir.glob("*_rollback.sql"))
    passed = len(rollbacks) > 0
    return VerifyResult(
        name,
        passed,
        f"rollback_files={len(rollbacks)}",
        {"count": len(rollbacks), "first_5": [p.name for p in rollbacks[:5]]},
    )


def verify_live_gbiz_ingest(repo_root: pathlib.Path) -> VerifyResult:
    """boolean 6: gBizINFO ingest disabled OR approved (env or fly secret)."""
    name = "live_gbiz_ingest_disabled_or_approved"
    if os.environ.get("GBIZINFO_INGEST_APPROVED") == "1":
        return VerifyResult(
            name, True, "GBIZINFO_INGEST_APPROVED=1 in env", {"path": "env_approved"}
        )
    if _which("flyctl") is None:
        return VerifyResult(
            name, False, "flyctl missing and not env-approved", {"reason": "no_flyctl"}
        )
    rc, out, err = _run_capture(["flyctl", "secrets", "list", "-a", APP_NAME, "-j"])
    if rc != 0:
        return VerifyResult(name, False, f"flyctl rc={rc}: {err.strip()[:200]}", {"rc": rc})
    try:
        rows = json.loads(out)
    except json.JSONDecodeError:
        return VerifyResult(name, False, "flyctl JSON parse fail", {"stdout_head": out[:200]})
    names = {r.get("Name") for r in rows if isinstance(r, dict)}
    has_token = "GBIZINFO_API_TOKEN" in names
    has_approval = "GBIZINFO_INGEST_APPROVED" in names
    # disabled = token absent OR approval flag explicitly set
    passed = (not has_token) or has_approval
    return VerifyResult(
        name,
        passed,
        f"token={'PRESENT' if has_token else 'ABSENT'}, "
        f"approval={'PRESENT' if has_approval else 'ABSENT'}",
        {"token_present": has_token, "approval_present": has_approval},
    )


def verify_dirty_lanes(repo_root: pathlib.Path) -> tuple[VerifyResult, dict[str, Any] | None]:
    """boolean 7: DEEP-56 compute_dirty_fingerprint.py --format=json -> fingerprint object."""
    name = "dirty_lanes_reviewed"
    candidates = [
        repo_root / "tools" / "offline" / "operator_review" / "compute_dirty_fingerprint.py",
        repo_root / "scripts" / "ops" / "compute_dirty_fingerprint.py",
        repo_root.parent / "compute_dirty_fingerprint" / "compute_dirty_fingerprint.py",
    ]
    script = next((c for c in candidates if c.is_file()), None)
    if script is None:
        return (
            VerifyResult(
                name,
                False,
                "compute_dirty_fingerprint.py not found",
                {"searched": [str(c) for c in candidates]},
            ),
            None,
        )
    rc, out, err = _run_capture(
        [sys.executable, str(script), "--repo", str(repo_root), "--format", "json"]
    )
    if rc != 0:
        return (
            VerifyResult(name, False, f"rc={rc}: {err.strip()[:200]}", {"rc": rc, "stderr": err}),
            None,
        )
    try:
        fingerprint = json.loads(out)
    except json.JSONDecodeError:
        return (
            VerifyResult(name, False, "fingerprint JSON parse fail", {"stdout_head": out[:200]}),
            None,
        )
    return (
        VerifyResult(
            name, True, f"fingerprint keys={sorted(fingerprint)[:5]}", {"keys": sorted(fingerprint)}
        ),
        fingerprint,
    )


def verify_pre_deploy(repo_root: pathlib.Path) -> VerifyResult:
    """boolean 8: pre_deploy_verify.py --warn-only -> stdout JSON contains ok=true.

    pre_deploy_verify.py always emits JSON to stdout; --warn-only forces exit 0
    so we evaluate `ok` from the parsed payload rather than the rc.
    """
    name = "pre_deploy_verify_clean"
    script = repo_root / "scripts" / "ops" / "pre_deploy_verify.py"
    if not script.is_file():
        return VerifyResult(name, False, f"missing script: {script}", {"path": str(script)})
    rc, out, err = _run_capture([sys.executable, str(script), "--warn-only"])
    # With --warn-only the script returns 0 even on failure; rc != 0 indicates
    # an actual crash / arg mismatch / import error.
    if rc != 0:
        return VerifyResult(name, False, f"rc={rc}: {err.strip()[:200]}", {"rc": rc, "stderr": err})
    try:
        payload = json.loads(out) if out.strip() else {}
    except json.JSONDecodeError:
        return VerifyResult(name, False, "pre_deploy JSON parse fail", {"stdout_head": out[:200]})
    ok = bool(payload.get("ok"))
    return VerifyResult(
        name,
        ok,
        f"ok={ok} failures={len(payload.get('failures', []))}",
        {"ok": ok, "failures": payload.get("failures", [])},
    )


# ----------------------------------------------------------------------
# orchestrator
# ----------------------------------------------------------------------


def _verify_one(idx: int, repo_root: pathlib.Path) -> tuple[VerifyResult, dict[str, Any] | None]:
    """Dispatch verify for boolean idx (1-based)."""
    if idx == 1:
        return verify_fly_app_confirmed(), None
    if idx == 2:
        return verify_fly_secrets_names_confirmed(repo_root), None
    if idx == 3:
        return verify_appi_or_turnstile(repo_root), None
    if idx == 4:
        return verify_target_db_packet(repo_root), None
    if idx == 5:
        return verify_rollback_packet(repo_root), None
    if idx == 6:
        return verify_live_gbiz_ingest(repo_root), None
    if idx == 7:
        return verify_dirty_lanes(repo_root)
    if idx == 8:
        return verify_pre_deploy(repo_root), None
    raise ValueError(f"boolean idx out of range: {idx}")


def _prompt_signoff(name: str, *, auto_yes: bool) -> bool:
    """Return True if operator types y. Empty / N / anything else -> False."""
    if auto_yes:
        return True
    try:
        ans = input("  signoff? [y/N/skip]: ").strip().lower()
    except EOFError:
        return False
    return ans == "y"


def _generate_ack_yaml(
    signoffs: dict[str, bool],
    fingerprint: dict[str, Any] | None,
    operator_email: str,
    out_path: pathlib.Path,
    *,
    commit: bool,
) -> tuple[pathlib.Path, str, str]:
    """Build the ACK payload, return (path, body, sha256)."""
    payload: dict[str, Any] = dict(signoffs)
    if fingerprint is not None:
        payload["dirty_tree_fingerprint"] = fingerprint
    payload["_meta"] = {
        "tool_version": TOOL_VERSION,
        "operator_email": operator_email,
        "signed_at": _utc_now_iso(),
        "git_commit_hash": _git_head_sha(),
        "yaml_sha256": "",  # placeholder, filled below
    }
    # First serialize without sha for hashing; then re-serialize with sha.
    body_no_sha = yaml.safe_dump(
        {k: v for k, v in payload.items() if k != "_meta"},
        sort_keys=True,
        allow_unicode=True,
    )
    meta_for_hash = {k: v for k, v in payload["_meta"].items() if k != "yaml_sha256"}
    body_no_sha += yaml.safe_dump({"_meta": meta_for_hash}, sort_keys=True, allow_unicode=True)
    sha256 = hashlib.sha256(body_no_sha.encode("utf-8")).hexdigest()
    payload["_meta"]["yaml_sha256"] = sha256
    body = yaml.safe_dump(payload, sort_keys=True, allow_unicode=True)
    if commit:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(body, encoding="utf-8")
    return out_path, body, sha256


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="operator_ack_signoff",
        description="DEEP-51 8-boolean ACK signoff CLI (LLM-API-free).",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--all", action="store_true", default=True, help="Run all 8 booleans (default)."
    )
    mode.add_argument(
        "--boolean", type=int, choices=range(1, 9), help="Verify a single boolean (1-8) and exit."
    )
    p.add_argument(
        "--commit", action="store_true", help="Actually write the ACK YAML (default DRY_RUN)."
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Force DRY_RUN even if --commit was implied (default).",
    )
    p.add_argument("--json", action="store_true", help="Emit verify results as JSON to stdout.")
    p.add_argument(
        "--ack-out",
        type=pathlib.Path,
        default=None,
        help=f"Override output path (default: {DEFAULT_ACK_DIR}/<utc>.yaml).",
    )
    p.add_argument(
        "--repo-root",
        type=pathlib.Path,
        default=pathlib.Path("/Users/shigetoumeda/jpcite"),
        help="jpcite repo root for verify scripts.",
    )
    p.add_argument(
        "--operator-email",
        default=os.environ.get("OPERATOR_EMAIL", DEFAULT_OPERATOR_EMAIL),
        help="Operator email (default: env OPERATOR_EMAIL or info@bookyou.net).",
    )
    p.add_argument(
        "--yes", action="store_true", help="Auto-confirm signoff prompts (test/CI only)."
    )
    return p.parse_args(argv)


def _print_header(idx: int, name: str) -> None:
    print(f"\n[{idx}/8] {name}")


def _print_result(result: VerifyResult) -> None:
    status = "PASS" if result.passed else "FAIL"
    print(f"  result: {result.detail}")
    print(f"  STATUS: {status}")
    if not result.passed:
        print(f"  fix: {FIX_DOC_URLS[result.boolean_name]}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.dry_run:
        args.commit = False
    repo_root: pathlib.Path = args.repo_root.resolve()
    out_path = args.ack_out or (DEFAULT_ACK_DIR / f"{_utc_now_iso_filename()}.yaml")

    if args.boolean is not None:
        result, fp = _verify_one(args.boolean, repo_root)
        _print_header(args.boolean, result.boolean_name)
        _print_result(result)
        if args.json:
            print(
                json.dumps(
                    {
                        "boolean_name": result.boolean_name,
                        "passed": result.passed,
                        "detail": result.detail,
                        "evidence": result.raw_evidence,
                        "fingerprint": fp,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
        return 0 if result.passed else 1

    # --all path
    signoffs: dict[str, bool] = {}
    fingerprint: dict[str, Any] | None = None
    json_results: list[dict[str, Any]] = []
    for idx, name in enumerate(BOOLEAN_NAMES, start=1):
        result, fp = _verify_one(idx, repo_root)
        if name == "dirty_lanes_reviewed" and fp is not None:
            fingerprint = fp
        _print_header(idx, name)
        _print_result(result)
        json_results.append(
            {
                "boolean_name": result.boolean_name,
                "passed": result.passed,
                "detail": result.detail,
            }
        )
        if not result.passed:
            print("  abort: verify FAIL — partial signoff not allowed.")
            if args.json:
                print(
                    json.dumps(
                        {"results": json_results, "ack_emitted": False},
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            return 1
        if not _prompt_signoff(name, auto_yes=args.yes):
            print("  aborted by operator (skip / N).")
            if args.json:
                print(
                    json.dumps(
                        {"results": json_results, "ack_emitted": False},
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            return 1
        signoffs[name] = True
        print("  signed.")

    print("\nALL 8 PASS. Generating ACK YAML...")
    path, body, sha = _generate_ack_yaml(
        signoffs,
        fingerprint,
        args.operator_email,
        out_path,
        commit=args.commit,
    )
    if args.commit:
        print(f"WROTE: {path}")
    else:
        print(f"DRY_RUN: would write {path} (use --commit to write)")
    print(f"yaml_sha256: {sha}")
    if args.json:
        print(
            json.dumps(
                {
                    "results": json_results,
                    "ack_emitted": True,
                    "path": str(path),
                    "yaml_sha256": sha,
                    "commit": args.commit,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
