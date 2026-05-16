#!/usr/bin/env python3
"""Idempotent sync of release_capsule_manifest.json sha256 -> well-known.

Stream O (Wave 50, 2026-05-16).

Background
----------
The static P0 release capsule publishes its manifest sha256 in two places:

* The manifest file itself:
  ``site/releases/rc1-p0-bootstrap/release_capsule_manifest.json``
* The well-known release pointer:
  ``site/.well-known/jpcite-release.json`` field ``manifest_sha256``

The validator (``scripts/ops/validate_release_capsule.py`` lines 1519-1527)
fail-closes when these two values disagree. Stream M widened the manifest
to 21 ``generated_surfaces`` entries and Stream N regenerated
``accounting_csv_profiles.json`` -- any time those generators run the sha
drifts and a deploy can be blocked until the well-known is hand-patched.

This script removes the hand-patch step.

Behaviour
---------
* Default invocation (no args): recompute the manifest sha256, write it
  into the well-known JSON, leave every other field untouched. Already
  in-sync runs are a no-op and produce ``status=already_synced``.
* ``--dry-run``: print the current vs expected sha256 and the would-be
  diff, exit 0 with ``status=drift_detected`` when a write would happen,
  exit 0 with ``status=already_synced`` when no write is needed.
* ``--check`` (alias of dry-run that exits non-zero on drift): useful for
  CI gating. Exits 2 on drift, 0 when in sync.

Per the Stream O guard rails, only ``manifest_sha256`` is mutated. Path /
URL fields (``manifest_path``, ``active_capsule_manifest``,
``p0_facade_path``, ``runtime_pointer_path``, ``next_resume_doc``,
``schema_version``, ``active_capsule_id``) are preserved byte-for-byte.

The script is also surface-sha aware: if the manifest itself ever grows a
``surface_sha256`` map keyed by surface path (currently it does not), the
script will refresh each surface's hash before computing the top-level
sha. This keeps the script useful when the manifest schema evolves
without requiring a follow-up patch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    REPO_ROOT / "site" / "releases" / "rc1-p0-bootstrap" / "release_capsule_manifest.json"
)
WELL_KNOWN_PATH = REPO_ROOT / "site" / ".well-known" / "jpcite-release.json"
PUBLIC_PREFIX = "/releases/"
SITE_RELEASES_DIR = REPO_ROOT / "site"  # /releases/... resolves under site/


def _maybe_reexec_venv() -> None:
    """Re-execute under the repo virtualenv when run with bare system python."""

    venv_dir = REPO_ROOT / ".venv"
    venv_python = venv_dir / "bin" / "python"
    if (
        venv_python.exists()
        and Path(sys.prefix).resolve() != venv_dir.resolve()
        and os.environ.get("JPCITE_NO_VENV_REEXEC") != "1"
    ):
        os.environ["JPCITE_NO_VENV_REEXEC"] = "1"
        os.execv(str(venv_python), [str(venv_python), *sys.argv])


_maybe_reexec_venv()


def _sha256_file(path: Path) -> str:
    """Return the hex sha256 of *path* read in binary mode."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _refresh_surface_shas_if_present(manifest_text_path: Path) -> bool:
    """Recompute surface_sha256 entries in the manifest, if any exist.

    Returns ``True`` when the manifest file was modified, ``False`` when no
    ``surface_sha256`` mapping exists or no entry needed updating. The
    manifest is written back atomically (write-then-replace via Path).
    """

    raw_text = manifest_text_path.read_text(encoding="utf-8")
    manifest: dict[str, Any] = json.loads(raw_text)
    surface_map = manifest.get("surface_sha256")
    if not isinstance(surface_map, dict):
        return False
    changed = False
    for public_path, declared_sha in list(surface_map.items()):
        if not isinstance(public_path, str) or not public_path.startswith(PUBLIC_PREFIX):
            continue
        local_path = SITE_RELEASES_DIR / public_path.lstrip("/")
        if not local_path.exists():
            # honest absence: leave declared sha untouched, surface the gap
            continue
        actual = _sha256_file(local_path)
        if actual != declared_sha:
            surface_map[public_path] = actual
            changed = True
    if changed:
        manifest["surface_sha256"] = surface_map
        new_text = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        manifest_text_path.write_text(new_text, encoding="utf-8")
    return changed


def compute_sync_plan() -> dict[str, Any]:
    """Compute the sync plan without writing anything.

    Returns a dict with: ``manifest_path``, ``well_known_path``,
    ``current_sha`` (in well-known), ``expected_sha`` (real sha of
    manifest), ``in_sync`` (bool), ``surface_sha_refreshed`` (bool, always
    False at plan time -- only --apply touches surface map first).
    """

    expected_sha = _sha256_file(MANIFEST_PATH)
    well_known: dict[str, Any] = json.loads(WELL_KNOWN_PATH.read_text(encoding="utf-8"))
    current_sha = well_known.get("manifest_sha256")
    return {
        "manifest_path": str(MANIFEST_PATH.relative_to(REPO_ROOT)),
        "well_known_path": str(WELL_KNOWN_PATH.relative_to(REPO_ROOT)),
        "current_sha": current_sha,
        "expected_sha": expected_sha,
        "in_sync": current_sha == expected_sha,
        "surface_sha_refreshed": False,
    }


def apply_sync() -> dict[str, Any]:
    """Write the manifest sha256 into the well-known JSON if needed.

    Returns a dict with: ``manifest_path``, ``well_known_path``,
    ``previous_sha``, ``new_sha``, ``changed`` (bool),
    ``surface_sha_refreshed`` (bool), ``preserved_fields`` (list of keys
    left untouched).
    """

    surface_refreshed = _refresh_surface_shas_if_present(MANIFEST_PATH)
    expected_sha = _sha256_file(MANIFEST_PATH)

    well_known_text = WELL_KNOWN_PATH.read_text(encoding="utf-8")
    well_known: dict[str, Any] = json.loads(well_known_text)
    previous_sha = well_known.get("manifest_sha256")
    preserved_fields = [k for k in well_known if k != "manifest_sha256"]

    if previous_sha == expected_sha and not surface_refreshed:
        return {
            "manifest_path": str(MANIFEST_PATH.relative_to(REPO_ROOT)),
            "well_known_path": str(WELL_KNOWN_PATH.relative_to(REPO_ROOT)),
            "previous_sha": previous_sha,
            "new_sha": expected_sha,
            "changed": False,
            "surface_sha_refreshed": surface_refreshed,
            "preserved_fields": preserved_fields,
        }

    well_known["manifest_sha256"] = expected_sha
    new_text = json.dumps(well_known, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    WELL_KNOWN_PATH.write_text(new_text, encoding="utf-8")
    return {
        "manifest_path": str(MANIFEST_PATH.relative_to(REPO_ROOT)),
        "well_known_path": str(WELL_KNOWN_PATH.relative_to(REPO_ROOT)),
        "previous_sha": previous_sha,
        "new_sha": expected_sha,
        "changed": True,
        "surface_sha_refreshed": surface_refreshed,
        "preserved_fields": preserved_fields,
    }


def _print_plan(plan: dict[str, Any]) -> None:
    print(json.dumps(plan, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan, do not write. Exits 0 in either state.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Like --dry-run but exits 2 when drift is detected.",
    )
    args = parser.parse_args(argv)

    if not MANIFEST_PATH.exists():
        print(
            json.dumps(
                {"status": "error", "reason": "manifest_missing", "path": str(MANIFEST_PATH)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    if not WELL_KNOWN_PATH.exists():
        print(
            json.dumps(
                {"status": "error", "reason": "well_known_missing", "path": str(WELL_KNOWN_PATH)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    if args.dry_run or args.check:
        plan = compute_sync_plan()
        plan["status"] = "already_synced" if plan["in_sync"] else "drift_detected"
        _print_plan(plan)
        if args.check and not plan["in_sync"]:
            return 2
        return 0

    result = apply_sync()
    result["status"] = "synced" if result["changed"] else "already_synced"
    _print_plan(result)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
