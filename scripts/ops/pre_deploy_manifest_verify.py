#!/usr/bin/env python3
"""Wave 41 — pre-deploy boot-manifest superset gate.

Background
----------
Wave 22 baked-seed deploys produce a Docker image with ``jpintel.db``
embedded but ``autonomath.db`` on the Fly volume. On a FRESH volume
(Wave 36-40 redeploys after machine destroy), the bootstrapped
``autonomath.db`` has none of the legacy migrations recorded in
``schema_migrations``. ``entrypoint.sh`` defaults to
``AUTONOMATH_BOOT_MIGRATION_MODE=manifest`` — it only re-applies
migrations whose filenames are listed in
``scripts/migrations/autonomath_boot_manifest.txt``. If the manifest is
missing any migration that ``scripts/schema_guard.py`` declares as
required (``AM_REQUIRED_MIGRATIONS``), the entrypoint can never bring a
fresh volume up to the required state, ``schema_guard`` raises
``required migrations missing from schema_migrations``, the entrypoint
exits non-zero, and Fly restart-loops the machine.

That exact shape produced the 2026-05-12 RC4 outage (post-mortem v2
``docs/postmortem/2026-05-11_14h_outage_v2.md``). PR #75 lifted the
manifest to include the 5 required migrations; this script is the gate
that prevents the manifest from drifting back out of sync.

What it does
------------
Walks ``scripts/schema_guard.py`` for ``AM_REQUIRED_MIGRATIONS`` and
``JPINTEL_REQUIRED_MIGRATIONS``, then diffs the autonomath subset
against the contents of ``scripts/migrations/autonomath_boot_manifest.txt``.
Exits non-zero if the manifest is missing any required autonomath
migration. ``JPINTEL_REQUIRED_MIGRATIONS`` is verified for on-disk
presence only (jpintel migrations are applied by ``migrate.py``, not
manifest-gated).

This is a pre-deploy gate. The intended call sites:

- ``.github/workflows/deploy.yml`` — first step, before build / push.
- ``scripts/ops/pre_deploy_verify.py`` — local wrapper (read-only).
- Operator laptop before ``gh workflow run deploy.yml --ref main``.

Constraints
-----------
- LLM API import budget = 0 (stdlib only).
- No mutation; this script is read-only.
- Exit 0 = manifest is a superset of required autonomath migrations.
- Exit 1 = manifest is missing one or more required autonomath migrations.
- Exit 2 = could not parse schema_guard or manifest (treat as block).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_GUARD = REPO_ROOT / "scripts" / "schema_guard.py"
MANIFEST = REPO_ROOT / "scripts" / "migrations" / "autonomath_boot_manifest.txt"
MIGRATIONS_DIR = REPO_ROOT / "scripts" / "migrations"

# Match either set literal inside an assignment like
#   AM_REQUIRED_MIGRATIONS = {
#       "049_provenance_strengthen.sql",
#       ...
#   }
_REQ_RE = re.compile(
    r"^(?P<name>AM_REQUIRED_MIGRATIONS|JPINTEL_REQUIRED_MIGRATIONS)\s*=\s*\{(?P<body>[^}]+)\}",
    re.MULTILINE | re.DOTALL,
)
_FILENAME_RE = re.compile(r'"([A-Za-z0-9_./-]+\.sql)"')


def parse_schema_guard_requirements(path: Path = SCHEMA_GUARD) -> dict[str, set[str]]:
    """Extract ``{constant_name: {migration_filename, ...}}`` from schema_guard.py.

    We parse with a regex instead of importing schema_guard so this script
    works in any Python interpreter without the project's full dependency
    tree (depot builder, slim CI matrix, etc.).
    """
    text = path.read_text(encoding="utf-8")
    out: dict[str, set[str]] = {}
    for match in _REQ_RE.finditer(text):
        name = match.group("name")
        body = match.group("body")
        filenames = set(_FILENAME_RE.findall(body))
        out[name] = filenames
    return out


def parse_manifest(path: Path = MANIFEST) -> set[str]:
    """Return the set of migration filenames declared in the boot manifest.

    Comments (``#``) and blank lines are skipped. Anything else is treated
    as one migration filename per line (the entrypoint reads it the same
    way).
    """
    out: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.add(line)
    return out


def existing_migrations(path: Path = MIGRATIONS_DIR) -> set[str]:
    """Return the set of migration filenames physically present on disk."""
    if not path.is_dir():
        return set()
    return {p.name for p in path.iterdir() if p.is_file() and p.suffix == ".sql"}


def parse_migration_target_db(path: Path) -> str | None:
    """Extract the ``target_db`` marker from the first 30 lines of a migration.

    Migration files convention: the second comment line declares
    ``-- target_db: autonomath`` or ``-- target_db: jpintel``. Returns
    ``None`` if the marker is absent (in which case ``entrypoint.sh``
    skips it for the autonomath boot path; jpintel-default migrations
    are handled by ``migrate.py``).
    """
    try:
        with path.open("r", encoding="utf-8") as fp:
            for _ in range(30):
                line = fp.readline()
                if not line:
                    return None
                m = re.match(r"^\s*--\s*target_db:\s*(\w+)\s*$", line)
                if m:
                    return m.group(1).lower()
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return None
    return None


def verify(
    schema_guard: Path = SCHEMA_GUARD,
    manifest: Path = MANIFEST,
    migrations_dir: Path = MIGRATIONS_DIR,
) -> dict[str, object]:
    """Run the verification and return a structured report.

    The autonomath boot manifest only gates autonomath-target migrations
    (entrypoint.sh §autonomath_migrations). jpintel-target migrations
    are applied by ``migrate.py`` without a manifest gate, so we scope
    the manifest superset check to ``AM_REQUIRED_MIGRATIONS`` only.
    """
    try:
        requirements = parse_schema_guard_requirements(schema_guard)
    except (FileNotFoundError, OSError) as exc:
        return {
            "ok": False,
            "fatal": True,
            "reason": f"could not read schema_guard: {exc}",
            "schema_guard_path": str(schema_guard),
        }

    if "AM_REQUIRED_MIGRATIONS" not in requirements:
        return {
            "ok": False,
            "fatal": True,
            "reason": "schema_guard.py missing AM_REQUIRED_MIGRATIONS definition",
            "found_keys": sorted(requirements.keys()),
        }

    try:
        manifest_entries = parse_manifest(manifest)
    except (FileNotFoundError, OSError) as exc:
        return {
            "ok": False,
            "fatal": True,
            "reason": f"could not read manifest: {exc}",
            "manifest_path": str(manifest),
        }

    on_disk = existing_migrations(migrations_dir)

    am_required = requirements.get("AM_REQUIRED_MIGRATIONS", set())
    jpintel_required = requirements.get("JPINTEL_REQUIRED_MIGRATIONS", set())

    # Manifest invariant — the autonomath boot manifest must list every
    # AM_REQUIRED migration. jpintel migrations are NOT manifest-gated;
    # they ride migrate.py.
    missing_from_manifest = sorted(am_required - manifest_entries)
    missing_from_disk_am = sorted(am_required - on_disk)
    missing_from_disk_jpintel = sorted(jpintel_required - on_disk)

    # Extra defensive check: every entry the manifest declares must
    # (a) exist on disk and (b) be tagged ``target_db: autonomath``.
    # If a jpintel-target migration slipped in, entrypoint.sh silently
    # skips it (per the "Not an autonomath-target migration" branch),
    # so it would be a no-op — but the manifest should not lie.
    manifest_wrong_target: list[str] = []
    manifest_missing_on_disk: list[str] = []
    for name in sorted(manifest_entries):
        path = migrations_dir / name
        if not path.is_file():
            manifest_missing_on_disk.append(name)
            continue
        target = parse_migration_target_db(path)
        if target is not None and target != "autonomath":
            manifest_wrong_target.append(f"{name} (target_db={target})")

    ok = (
        not missing_from_manifest
        and not missing_from_disk_am
        and not manifest_wrong_target
        and not manifest_missing_on_disk
    )

    return {
        "ok": ok,
        "fatal": False,
        "scope": "AM_REQUIRED_MIGRATIONS ⊆ autonomath_boot_manifest.txt",
        "am_required_count": len(am_required),
        "jpintel_required_count": len(jpintel_required),
        "manifest_count": len(manifest_entries),
        "on_disk_count": len(on_disk),
        "am_required_migrations": sorted(am_required),
        "jpintel_required_migrations": sorted(jpintel_required),
        "manifest_migrations": sorted(manifest_entries),
        "missing_from_manifest": missing_from_manifest,
        "missing_from_disk_am": missing_from_disk_am,
        "missing_from_disk_jpintel": missing_from_disk_jpintel,
        "manifest_wrong_target": manifest_wrong_target,
        "manifest_missing_on_disk": manifest_missing_on_disk,
        "schema_guard_path": str(schema_guard),
        "manifest_path": str(manifest),
        "migrations_dir": str(migrations_dir),
        "requirements_by_profile": {k: sorted(v) for k, v in requirements.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that scripts/migrations/autonomath_boot_manifest.txt is a "
            "superset of scripts/schema_guard.py AM_REQUIRED_MIGRATIONS. Wave 40 "
            "fix for the 2026-05-12 14h outage RC4."
        )
    )
    parser.add_argument(
        "--schema-guard",
        type=Path,
        default=SCHEMA_GUARD,
        help=f"Path to schema_guard.py (default: {SCHEMA_GUARD})",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=MANIFEST,
        help=f"Path to boot manifest (default: {MANIFEST})",
    )
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=MIGRATIONS_DIR,
        help=f"Migrations directory (default: {MIGRATIONS_DIR})",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Always exit 0 after printing JSON (do not block deploy).",
    )
    args = parser.parse_args(argv)

    report = verify(
        schema_guard=args.schema_guard,
        manifest=args.manifest,
        migrations_dir=args.migrations_dir,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))

    if args.warn_only:
        return 0
    if report.get("fatal"):
        return 2
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
