#!/usr/bin/env python3
"""Read-only production deploy GO/NO-GO gate.

This script is intentionally stricter than ``pre_deploy_verify.py``. The
pre-deploy verifier answers "are local checks green?"; this gate answers
"is it acceptable to mutate production now?". It performs no network calls,
does not read secret values, and never applies migrations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_FLY_APP = "autonomath-api"
LEGACY_FLY_APP_ALIASES = (
    "jpcite-api",
    "autonomath-api-tokyo",
    "AutonoMath",
    "jpintel-mcp",
)
REQUIRED_PRODUCTION_SECRETS = (
    "ADMIN_API_KEY",
    "API_KEY_SALT",
    "AUDIT_SEAL_SECRET",
    "AUTONOMATH_API_HASH_PEPPER",
    "AUTONOMATH_DB_SHA256",
    "AUTONOMATH_DB_URL",
    "INVOICE_FOOTER_JA",
    "INVOICE_REGISTRATION_NUMBER",
    "JPINTEL_CORS_ORIGINS",
    "JPINTEL_ENV",
    "RATE_LIMIT_FREE_PER_DAY",
    "R2_ACCESS_KEY_ID",
    "R2_BUCKET",
    "R2_ENDPOINT",
    "R2_SECRET_ACCESS_KEY",
    "STRIPE_BILLING_PORTAL_CONFIG_ID",
    "STRIPE_PRICE_PER_REQUEST",
    "STRIPE_SECRET_KEY",
    "STRIPE_TAX_ENABLED",
    "STRIPE_WEBHOOK_SECRET",
)
CONDITIONAL_PRODUCTION_SECRETS = {
    "CLOUDFLARE_TURNSTILE_SECRET": (
        "required when production APPI intake/deletion is enabled "
        "(AUTONOMATH_APPI_ENABLED is not 0/false)"
    ),
    "GBIZINFO_API_TOKEN": "required on the Fly machine only when live gBiz ingest is enabled",
}
OPTIONAL_PRODUCTION_SECRETS = {
    "JPINTEL_AUDIT_SEAL_KEYS": "optional rotation set; alternative to AUDIT_SEAL_SECRET",
    "TG_BOT_TOKEN": "optional GitHub/Fly notification secret; canonical Telegram token name",
    "TG_CHAT_ID": "optional GitHub/Fly notification target",
}
CRITICAL_DIRTY_LANES = (
    "runtime_code",
    "billing_auth_security",
    "migrations",
    "cron_etl_ops",
    "workflows",
    "root_release_files",
)
REQUIRED_OPERATOR_ACK_FIELDS = (
    "fly_app_confirmed",
    "fly_secrets_names_confirmed",
    "appi_disabled_or_turnstile_secret_confirmed",
    "target_db_packet_reviewed",
    "rollback_reconciliation_packet_ready",
    "live_gbiz_ingest_disabled_or_approved",
    "dirty_lanes_reviewed",
    "pre_deploy_verify_clean",
)
REQUIRED_DIRTY_TREE_FINGERPRINT_FIELDS = (
    "current_head",
    "dirty_entries",
    "status_counts",
    "lane_counts",
    "path_sha256",
    "content_sha256",
    "content_hash_skipped_large_files",
)


@dataclass(frozen=True)
class GateCheck:
    name: str
    ok: bool
    severity: str
    issues: list[str]
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "severity": self.severity,
            "issues": self.issues,
            "evidence": self.evidence,
        }


class GitStatusUnavailableError(RuntimeError):
    """Raised when git status cannot be read for a fail-closed gate."""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _iter_scan_files(repo_root: Path) -> list[Path]:
    roots = [
        repo_root / ".env.example",
        repo_root / "fly.toml",
        repo_root / ".github" / "workflows",
        repo_root / "docs" / "_internal",
        repo_root / "docs" / "runbook",
        repo_root / "docs" / "legal",
    ]
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(
                path
                for path in root.rglob("*")
                if path.is_file()
                and path.suffix.lower() in {".md", ".txt", ".toml", ".yml", ".yaml"}
            )
    return sorted(files)


def _fly_toml_app(repo_root: Path) -> str | None:
    text = _read_text(repo_root / "fly.toml")
    for line in text.splitlines():
        match = re.match(r"\s*app\s*=\s*[\"']([^\"']+)[\"']", line)
        if match:
            return match.group(1)
    return None


def check_fly_app_command_contexts(repo_root: Path) -> GateCheck:
    legacy = "|".join(re.escape(alias) for alias in LEGACY_FLY_APP_ALIASES)
    patterns = (
        re.compile(rf"\b(?:fly|flyctl)\b[^\n]*(?:-a|--app)(?:\s*=\s*|\s+)[\"']?(?:{legacy})[\"']?"),
        re.compile(rf"\bFLY_APP\s*[:=]\s*[\"']?(?:{legacy})[\"']?"),
        re.compile(rf"https://fly\.io/apps/(?:{legacy})(?:/|\b)"),
    )
    hits: list[str] = []
    fly_toml_app = _fly_toml_app(repo_root)
    issues: list[str] = []
    if fly_toml_app is None:
        issues.append("fly_toml_app_missing")
    elif fly_toml_app != CANONICAL_FLY_APP:
        issues.append(f"fly_toml_app_mismatch:expected={CANONICAL_FLY_APP}:actual={fly_toml_app}")
    for path in _iter_scan_files(repo_root):
        text = _read_text(path)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if any(pattern.search(line) for pattern in patterns):
                hits.append(f"{path.relative_to(repo_root)}:{lineno}:{line.strip()[:180]}")
    issues.extend(f"legacy_fly_app_context:{hit}" for hit in hits)
    return GateCheck(
        name="fly_app_command_contexts",
        ok=not issues,
        severity="blocker",
        issues=issues,
        evidence={
            "canonical_fly_app": CANONICAL_FLY_APP,
            "fly_toml_app": fly_toml_app,
            "legacy_aliases": list(LEGACY_FLY_APP_ALIASES),
            "scanned_files": len(_iter_scan_files(repo_root)),
        },
    )


def check_secret_registry(repo_root: Path) -> GateCheck:
    registry = repo_root / "docs" / "_internal" / "SECRETS_REGISTRY.md"
    text = _read_text(registry)
    missing = [name for name in REQUIRED_PRODUCTION_SECRETS if name not in text]
    issues = [f"secret_name_missing_from_registry:{name}" for name in missing]
    missing_conditional = [name for name in CONDITIONAL_PRODUCTION_SECRETS if name not in text]
    issues.extend(
        f"conditional_secret_name_missing_from_registry:{name}" for name in missing_conditional
    )
    if CANONICAL_FLY_APP not in text:
        issues.append(f"canonical_fly_app_missing_from_registry:{CANONICAL_FLY_APP}")
    return GateCheck(
        name="secret_registry_names",
        ok=not issues,
        severity="blocker",
        issues=issues,
        evidence={
            "registry": str(registry.relative_to(repo_root)),
            "required_secret_names": list(REQUIRED_PRODUCTION_SECRETS),
            "conditional_secret_names": CONDITIONAL_PRODUCTION_SECRETS,
            "optional_secret_names": OPTIONAL_PRODUCTION_SECRETS,
            "secret_values_read": False,
        },
    )


def _migration_target(path: Path) -> str | None:
    for line in _read_text(path).splitlines()[:5]:
        match = re.match(r"\s*--\s*target_db:\s*(\S+)", line, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _normalise_target_db(value: str | None) -> str | None:
    if value is None:
        return None
    target = value.strip().lower()
    if target.endswith(".db"):
        target = target[:-3]
    return target or None


def _migration_is_manual(path: Path) -> bool:
    for line in _read_text(path).splitlines()[:20]:
        if re.match(r"\s*--\s*boot_time:\s*manual\b", line, flags=re.IGNORECASE):
            return True
    return False


def _sql_without_line_comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))


def _drop_view_issues(sql: str, path_text: str) -> list[str]:
    issues: list[str] = []
    for match in re.finditer(
        r"\bDROP\s+VIEW(?:\s+IF\s+EXISTS)?\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        sql,
        flags=re.IGNORECASE,
    ):
        view_name = match.group(1)
        create_after = re.search(
            rf"\bCREATE\s+VIEW(?:\s+IF\s+NOT\s+EXISTS)?\s+{re.escape(view_name)}\b",
            sql[match.end() :],
            flags=re.IGNORECASE,
        )
        if create_after is None:
            issues.append(
                f"dirty_forward_migration_drop_view_without_recreate:{path_text}:{view_name}"
            )
    return issues


def _delete_from_allowed(sql: str, start: int) -> bool:
    end = sql.find(";", start)
    statement = sql[start:] if end < 0 else sql[start : end + 1]
    trigger_prefix = sql[max(0, start - 1200) : start]
    return bool(
        re.search(r"\bAFTER\s+DELETE\b", trigger_prefix, flags=re.IGNORECASE)
        and re.search(
            r"\bDELETE\s+FROM\s+[A-Za-z_][A-Za-z0-9_]*_fts\s+WHERE\s+rowid\s*=\s*OLD\.",
            statement,
            flags=re.IGNORECASE,
        )
    )


def _dangerous_forward_sql_issues(path: Path, path_text: str) -> list[str]:
    sql = _sql_without_line_comments(_read_text(path))
    issues: list[str] = []
    for label, pattern in (
        ("drop_table", r"\bDROP\s+TABLE\b"),
        ("drop_column", r"\bDROP\s+COLUMN\b"),
        ("truncate", r"\bTRUNCATE\b"),
    ):
        if re.search(pattern, sql, flags=re.IGNORECASE):
            issues.append(f"dirty_forward_migration_dangerous_sql:{path_text}:{label}")
    issues.extend(_drop_view_issues(sql, path_text))
    for match in re.finditer(r"\bDELETE\s+FROM\b", sql, flags=re.IGNORECASE):
        if not _delete_from_allowed(sql, match.start()):
            issues.append(f"dirty_forward_migration_dangerous_sql:{path_text}:delete_from")
    return issues


def check_migration_target_boundaries(repo_root: Path) -> GateCheck:
    migrations = repo_root / "scripts" / "migrations"
    expected = {
        "wave24_164_gbiz_v2_mirror_tables.sql": "autonomath",
        "wave24_166_credit_pack_reservation.sql": "jpintel",
    }
    issues: list[str] = []
    actual: dict[str, str | None] = {}
    for name, target in expected.items():
        path = migrations / name
        value = _migration_target(path)
        actual[name] = value
        if _normalise_target_db(value) != target:
            issues.append(f"migration_target_mismatch:{name}:expected={target}:actual={value}")
    dirty_migration_targets: dict[str, str | None] = {}
    try:
        dirty_lines = _git_status(repo_root)
    except GitStatusUnavailableError:
        dirty_lines = []
    for raw in dirty_lines:
        status = raw[:2]
        path_text = raw[3:].strip()
        if " -> " in path_text:
            path_text = path_text.split(" -> ", 1)[1]
        if not path_text.startswith("scripts/migrations/") or not path_text.endswith(".sql"):
            continue
        if "D" in status:
            continue
        path = repo_root / path_text
        if path.name.endswith("_rollback.sql"):
            continue
        target_raw = _migration_target(path)
        target = _normalise_target_db(target_raw)
        dirty_migration_targets[path_text] = target_raw
        if target is None:
            issues.append(f"dirty_forward_migration_missing_target_db:{path_text}")
        elif target not in {"autonomath", "jpintel"}:
            issues.append(f"dirty_forward_migration_unknown_target_db:{path_text}:{target_raw}")
        if not _migration_is_manual(path):
            issues.extend(_dangerous_forward_sql_issues(path, path_text))
    rollback_target_marked = [
        path.name
        for path in migrations.glob("*_rollback.sql")
        if _migration_target(path) in {"autonomath", "jpintel"}
    ]
    return GateCheck(
        name="migration_target_boundaries",
        ok=not issues,
        severity="blocker",
        issues=issues,
        evidence={
            "expected_targets": expected,
            "actual_targets": actual,
            "dirty_forward_migration_targets": dirty_migration_targets,
            "rollback_files_are_runner_excluded": True,
            "rollback_target_marked_count": len(rollback_target_marked),
        },
    )


def _git_status(repo_root: Path) -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=repo_root,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as err:
        raise GitStatusUnavailableError("git_status_unavailable") from err
    return [line for line in out.splitlines() if line.strip()]


def _git_head(repo_root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def _lane_for_path(path: str) -> str:
    try:
        from repo_dirty_lane_report import classify_path
    except Exception:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from repo_dirty_lane_report import classify_path

    return classify_path(path)


def _dirty_tree_fingerprint(repo_root: Path, lines: list[str]) -> dict[str, Any]:
    lane_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    content_hash = hashlib.sha256()
    content_hash_skipped_large_files: list[str] = []
    parsed_entries: list[tuple[str, str, str | None, str]] = []
    for raw in sorted(lines):
        status = raw[:2].strip() or raw[:2]
        path = raw[3:].strip()
        old_path = None
        if " -> " in path:
            old_path, path = path.split(" -> ", 1)
            old_lane = _lane_for_path(old_path)
            lane_counts[old_lane] = lane_counts.get(old_lane, 0) + 1
        lane = _lane_for_path(path)
        lane_counts[lane] = lane_counts.get(lane, 0) + 1
        status_counts[status] = status_counts.get(status, 0) + 1
        parsed_entries.append((status, path, old_path, raw))

    for status, path, _old_path, raw in parsed_entries:
        content_hash.update(f"{status}\t{path}\n".encode("utf-8", errors="replace"))
        disk_path = repo_root / path
        if "D" in raw[:2] or not disk_path.is_file():
            content_hash.update(b"<deleted-or-not-file>\n")
            continue
        try:
            size = disk_path.stat().st_size
        except OSError:
            content_hash.update(b"<stat-unavailable>\n")
            continue
        content_hash.update(f"size={size}\n".encode("ascii"))
        if size > 64 * 1024 * 1024:
            content_hash_skipped_large_files.append(path)
            content_hash.update(b"<content-skipped-large-file>\n")
            continue
        file_hash = hashlib.sha256()
        try:
            with disk_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    file_hash.update(chunk)
        except OSError:
            content_hash.update(b"<read-unavailable>\n")
            continue
        content_hash.update(file_hash.hexdigest().encode("ascii"))
        content_hash.update(b"\n")
    critical_lanes_present = sorted(
        lane for lane in CRITICAL_DIRTY_LANES if lane_counts.get(lane, 0) > 0
    )
    return {
        "current_head": _git_head(repo_root),
        "dirty_entries": len(lines),
        "status_counts": dict(sorted(status_counts.items())),
        "lane_counts": dict(sorted(lane_counts.items())),
        "critical_lanes_present": critical_lanes_present,
        "path_sha256": hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest(),
        "content_sha256": content_hash.hexdigest(),
        "content_hash_skipped_large_files": content_hash_skipped_large_files,
    }


def _dirty_fingerprint_matches(
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> list[str]:
    issues: list[str] = []
    for key in REQUIRED_DIRTY_TREE_FINGERPRINT_FIELDS:
        if key not in expected:
            issues.append(f"dirty_fingerprint_missing:{key}")
        elif expected.get(key) != actual.get(key):
            issues.append(f"dirty_fingerprint_mismatch:{key}")
    reviewed = set(expected.get("critical_dirty_lanes_reviewed") or [])
    missing_critical = [
        lane for lane in actual.get("critical_lanes_present", []) if lane not in reviewed
    ]
    if missing_critical:
        issues.append("dirty_critical_lanes_not_reviewed:" + ",".join(missing_critical))
    return issues


def check_dirty_tree(
    repo_root: Path,
    *,
    allow_dirty: bool,
    ack_data: dict[str, Any] | None = None,
) -> GateCheck:
    try:
        lines = _git_status(repo_root)
    except GitStatusUnavailableError:
        return GateCheck(
            name="dirty_tree",
            ok=False,
            severity="blocker",
            issues=["git_status_unavailable"],
            evidence={"allow_dirty": allow_dirty},
        )
    fingerprint = _dirty_tree_fingerprint(repo_root, lines)
    issues: list[str] = []
    if fingerprint.get("content_hash_skipped_large_files"):
        issues.append(
            "dirty_large_file_content_hash_skipped:"
            + ",".join(fingerprint["content_hash_skipped_large_files"])
        )
    if lines and not allow_dirty:
        issues.append(f"dirty_tree_present:{len(lines)}")
    if lines and allow_dirty:
        ack_fingerprint = {}
        if isinstance(ack_data, dict):
            raw_fingerprint = ack_data.get("dirty_tree_fingerprint")
            if isinstance(raw_fingerprint, dict):
                ack_fingerprint = raw_fingerprint
        if not ack_fingerprint:
            issues.append("dirty_tree_fingerprint:not_provided")
        else:
            issues.extend(_dirty_fingerprint_matches(ack_fingerprint, fingerprint))
    return GateCheck(
        name="dirty_tree",
        ok=not issues,
        severity="operator_required",
        issues=issues,
        evidence={
            "allow_dirty": allow_dirty,
            "required_fingerprint_fields_when_allow_dirty": list(
                REQUIRED_DIRTY_TREE_FINGERPRINT_FIELDS
            ),
            **fingerprint,
        },
    )


def _load_operator_ack(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    text = _read_text(path)
    if not text.strip():
        return None
    try:
        import yaml

        loaded = yaml.safe_load(text)
    except Exception:
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            return None
    return loaded if isinstance(loaded, dict) else None


def check_operator_ack(path: Path | None) -> GateCheck:
    ack = _load_operator_ack(path)
    issues: list[str] = []
    if ack is None:
        issues.append("operator_ack:not_provided_or_unreadable")
        present: dict[str, Any] = {}
    else:
        present = {field: ack.get(field) for field in REQUIRED_OPERATOR_ACK_FIELDS}
        for field in REQUIRED_OPERATOR_ACK_FIELDS:
            if ack.get(field) is not True:
                issues.append(f"operator_ack:false_or_missing:{field}")
    return GateCheck(
        name="operator_ack",
        ok=not issues,
        severity="operator_required",
        issues=issues,
        evidence={
            "ack_path": str(path) if path else None,
            "required_fields": list(REQUIRED_OPERATOR_ACK_FIELDS),
            "present_fields": present,
        },
    )


def build_report(
    repo_root: Path = REPO_ROOT,
    *,
    allow_dirty: bool = False,
    operator_ack: Path | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    ack_data = _load_operator_ack(operator_ack)
    checks = [
        check_fly_app_command_contexts(root),
        check_secret_registry(root),
        check_migration_target_boundaries(root),
        check_dirty_tree(root, allow_dirty=allow_dirty, ack_data=ack_data),
        check_operator_ack(operator_ack),
    ]
    failing = [check for check in checks if not check.ok]
    return {
        "scope": "production deploy GO gate; read-only; no network; no secret values",
        "generated_at": _utc_now(),
        "repo_root": str(root),
        "ok": not failing,
        "summary": {
            "pass": sum(1 for check in checks if check.ok),
            "fail": len(failing),
            "total": len(checks),
        },
        "checks": [check.to_dict() for check in checks],
        "issues": [
            {"name": check.name, "severity": check.severity, "issues": check.issues}
            for check in failing
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run read-only production deploy GO gate.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Do not fail solely because the worktree is dirty. Use only with a reviewed dirty-lane packet.",
    )
    parser.add_argument(
        "--operator-ack",
        type=Path,
        help="YAML/JSON file with required operator confirmations.",
    )
    parser.add_argument("--warn-only", action="store_true", help="Always exit 0 after JSON output.")
    args = parser.parse_args(argv)

    report = build_report(
        args.repo_root,
        allow_dirty=args.allow_dirty,
        operator_ack=args.operator_ack,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.warn_only:
        return 0
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
