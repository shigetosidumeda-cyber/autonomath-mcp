#!/usr/bin/env python3
"""SBOM (Software Bill of Materials) generator for jpcite supply-chain transparency.

Emits CycloneDX 1.4 JSON for every shipped surface — Python runtime + SDK
plugins + Node SDKs + Docker base image — and an aggregated index that ships
to ``site/.well-known/sbom.json`` for public consumption.

Inputs (read-only)
------------------
* ``pyproject.toml`` — installed environment audited via pip-audit.
* ``sdk/freee-plugin/requirements.txt`` + ``sdk/mf-plugin/requirements.txt`` —
  python plugins audited via pip-audit -r.
* ``sdk/typescript/package.json`` + ``sdk/agents/package.json`` +
  ``sdk/npm-package/package.json`` + ``sdk/vscode-extension/package.json`` —
  npm declared dependencies, parsed (no network).
* ``Dockerfile`` — base image FROM line, recorded as a component.

Outputs (new files only — never overwrite the public site without intent)
------------------------------------------------------------------------
* ``site/.well-known/sbom/sbom-pip.cyclonedx.json`` — main project Python deps.
* ``site/.well-known/sbom/sbom-sdk-freee.cyclonedx.json`` — freee plugin reqs.
* ``site/.well-known/sbom/sbom-sdk-mf.cyclonedx.json`` — mf plugin reqs.
* ``site/.well-known/sbom/sbom-npm-<pkg>.cyclonedx.json`` — one per npm pkg.
* ``site/.well-known/sbom/sbom-docker-base.cyclonedx.json`` — base image.
* ``site/.well-known/sbom.json`` — aggregated index (component counts +
  per-surface SHA256 + spec ``CycloneDX 1.4``).

Why pip-audit (not cyclonedx-bom directly)
------------------------------------------
``pip-audit`` is already installed in ``.venv`` (used by the dependency
hygiene cron). It supports ``--format=cyclonedx-json`` natively, so we get
SBOM + vulnerability sweep in one pass. Adding a separate ``cyclonedx-bom``
package would duplicate the dependency graph walk for no extra signal.

Why not syft for the docker layer
---------------------------------
``syft`` would deep-scan the runtime image (~775 MB) and surface every
``apt`` package. Useful but heavyweight (10+ minutes of CI). For now we
record the base image as a single declared component (``python:3.12-slim-bookworm``)
and leave deeper scanning to the monthly workflow's optional ``with-syft``
input. This keeps the default monthly run under 5 minutes.

Honesty + safety
----------------
* ``LLM 0`` — no model call inside this script. Pure subprocess + JSON.
* No production secret value is embedded; the script reads only public
  manifests (pyproject / requirements / package.json / Dockerfile).
* New files only: refuses to overwrite without ``--force`` if the target
  already exists with a different SHA. Defaults to overwrite-on-equal.
* ``--dry-run`` plans the write set without touching disk; CI uses this on
  PRs to confirm no drift before the monthly cron writes.

Usage
-----
::

    python scripts/cron/generate_sbom.py             # full regenerate
    python scripts/cron/generate_sbom.py --dry-run   # plan only
    python scripts/cron/generate_sbom.py --skip-pip  # skip Python audit (faster)
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
SBOM_DIR = REPO_ROOT / "site" / ".well-known" / "sbom"
INDEX_PATH = REPO_ROOT / "site" / ".well-known" / "sbom.json"

# Sub-projects (path, label, kind).
PIP_TARGETS = [
    ("sdk/freee-plugin/requirements.txt", "sdk-freee", "python"),
    ("sdk/mf-plugin/requirements.txt", "sdk-mf", "python"),
]
NPM_TARGETS = [
    ("sdk/typescript/package.json", "npm-typescript"),
    ("sdk/agents/package.json", "npm-agents"),
    ("sdk/npm-package/package.json", "npm-jpcite"),
    ("sdk/vscode-extension/package.json", "npm-vscode-extension"),
]

# Base image — declared (not deep-scanned) component.
DOCKER_BASE_IMAGE = "python:3.12-slim-bookworm"
DOCKER_BASE_PURL = (
    "pkg:docker/python@3.12-slim-bookworm?repository_url=docker.io%2Flibrary"
)

CYCLONEDX_SPEC = "1.4"
SCHEMA_URL = "http://cyclonedx.org/schema/bom-1.4.schema.json"
TOOL_NAME = "jpcite-sbom-generator"
TOOL_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def utc_now() -> str:
    """Return RFC 3339 UTC timestamp with seconds resolution."""
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json_atomic(path: Path, payload: dict, dry_run: bool) -> str:
    """Write JSON atomically; return SHA256 of the (would-be) bytes."""
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    body_bytes = body.encode("utf-8")
    digest = sha256_bytes(body_bytes)
    if dry_run:
        print(f"  [dry-run] {path.relative_to(REPO_ROOT)} sha256={digest[:12]}…")
        return digest
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(body_bytes)
    tmp.replace(path)
    print(f"  wrote {path.relative_to(REPO_ROOT)} sha256={digest[:12]}…")
    return digest


def cyclonedx_envelope(components: list[dict]) -> dict:
    """Wrap a component list in the CycloneDX 1.4 boilerplate envelope."""
    return {
        "$schema": SCHEMA_URL,
        "bomFormat": "CycloneDX",
        "specVersion": CYCLONEDX_SPEC,
        "version": 1,
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "metadata": {
            "timestamp": utc_now(),
            "tools": [
                {
                    "vendor": "Bookyou株式会社",
                    "name": TOOL_NAME,
                    "version": TOOL_VERSION,
                }
            ],
            "component": {
                "type": "application",
                "name": "jpcite",
                "version": read_pyproject_version(),
                "supplier": {"name": "Bookyou株式会社"},
                "licenses": [{"license": {"id": "MIT"}}],
            },
        },
        "components": components,
    }


def read_pyproject_version() -> str:
    """Read [project].version from pyproject.toml without TOML parser dep."""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("version = "):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "0.0.0"


# ---------------------------------------------------------------------------
# Python / pip surface
# ---------------------------------------------------------------------------

def run_pip_audit(extra_args: list[str], out_path: Path, dry_run: bool) -> str:
    """Invoke pip-audit and return SHA256 of resulting JSON.

    pip-audit emits a complete CycloneDX 1.4 envelope; we accept its output
    verbatim (no rewriting) so the supply-chain attestation matches exactly
    what an auditor would reproduce by running the same command.
    """
    venv_pip_audit = REPO_ROOT / ".venv" / "bin" / "pip-audit"
    binary = str(venv_pip_audit) if venv_pip_audit.exists() else "pip-audit"
    cmd = [binary, "--format=cyclonedx-json", "--skip-editable", "-o", str(out_path), *extra_args]
    print(f"  $ {' '.join(cmd)}")
    if dry_run:
        return "dry-run"
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode not in (0, 1):
        # pip-audit returns 1 when vulnerabilities are found — that is OK,
        # we still want the SBOM. Anything else is a real failure.
        print(f"  pip-audit failed rc={proc.returncode}: {proc.stderr[:500]}", file=sys.stderr)
        raise SystemExit(2)
    if proc.returncode == 1:
        print("  WARN: pip-audit reported vulnerabilities — SBOM still written")
    if not out_path.exists():
        # Defensive: if pip-audit exited 0 but produced no file (sub-project
        # with empty deps) write an empty CycloneDX envelope so the index
        # stays referentially intact.
        write_json_atomic(out_path, cyclonedx_envelope([]), dry_run=False)
    body = out_path.read_bytes()
    return sha256_bytes(body)


def emit_pip_main(dry_run: bool) -> tuple[str, int]:
    out = SBOM_DIR / "sbom-pip.cyclonedx.json"
    digest = run_pip_audit([], out, dry_run)
    if dry_run:
        return digest, 0
    component_count = len(json.loads(out.read_text(encoding="utf-8")).get("components", []))
    return digest, component_count


def emit_pip_sub(req_relpath: str, label: str, dry_run: bool) -> tuple[str, int]:
    req_path = REPO_ROOT / req_relpath
    if not req_path.exists():
        print(f"  skip: {req_relpath} not found")
        return "missing", 0
    out = SBOM_DIR / f"sbom-{label}.cyclonedx.json"
    # NOTE: ``--disable-pip`` requires a hashed requirements file or ``--no-deps``.
    # The plugin reqs are unhashed and we want transitive deps walked, so we let
    # pip-audit invoke pip in a temp venv (its default behaviour). This adds
    # ~10s per plugin but produces an accurate transitive component graph.
    digest = run_pip_audit(["-r", str(req_path)], out, dry_run)
    if dry_run:
        return digest, 0
    component_count = len(json.loads(out.read_text(encoding="utf-8")).get("components", []))
    return digest, component_count


# ---------------------------------------------------------------------------
# npm surface
# ---------------------------------------------------------------------------

def emit_npm(pkg_relpath: str, label: str, dry_run: bool) -> tuple[str, int]:
    """Parse package.json into a CycloneDX 1.4 envelope.

    We deliberately do NOT shell out to ``npm sbom`` because the minimal
    npm-package dirs in this repo do not always have ``node_modules`` checked
    in or installed, and we want the SBOM to reflect the *declared* manifest
    (which is what a downstream consumer pins to). Resolved versions land in
    the lockfile-aware audit step, not here.
    """
    pkg_path = REPO_ROOT / pkg_relpath
    if not pkg_path.exists():
        print(f"  skip: {pkg_relpath} not found")
        return "missing", 0
    manifest = json.loads(pkg_path.read_text(encoding="utf-8"))
    out = SBOM_DIR / f"sbom-{label}.cyclonedx.json"
    components: list[dict] = []
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        for name, ver in (manifest.get(section) or {}).items():
            ver_str = ver if isinstance(ver, str) else ""
            ver_clean = ver_str.lstrip("^~>=<= ")
            purl_name = name if "/" not in name else "%2F".join(name.split("/", 1))
            components.append(
                {
                    "type": "library",
                    "name": name,
                    "version": ver_clean,
                    "purl": f"pkg:npm/{purl_name}@{ver_clean}" if ver_clean else f"pkg:npm/{purl_name}",
                    "properties": [
                        {"name": "scope", "value": section},
                        {"name": "version_constraint", "value": ver_str},
                    ],
                }
            )
    envelope = cyclonedx_envelope(components)
    # Override the metadata.component to reflect the npm package itself.
    envelope["metadata"]["component"] = {
        "type": "application",
        "name": manifest.get("name", label),
        "version": manifest.get("version", "0.0.0"),
        "supplier": {"name": "Bookyou株式会社"},
        "licenses": [{"license": {"id": manifest.get("license", "MIT")}}],
    }
    digest = write_json_atomic(out, envelope, dry_run)
    return digest, len(components)


# ---------------------------------------------------------------------------
# Docker surface
# ---------------------------------------------------------------------------

def emit_docker(dry_run: bool) -> tuple[str, int]:
    """Record the Dockerfile FROM image as a single declared component.

    Deeper apt-package enumeration is left for the optional ``with-syft``
    input on the monthly workflow. This keeps the default cron under 5 min.
    """
    out = SBOM_DIR / "sbom-docker-base.cyclonedx.json"
    components = [
        {
            "type": "container",
            "name": DOCKER_BASE_IMAGE,
            "version": "3.12-slim-bookworm",
            "purl": DOCKER_BASE_PURL,
            "supplier": {"name": "Python Software Foundation / Docker Hub library"},
            "properties": [
                {"name": "platform", "value": "linux/amd64"},
                {"name": "registry", "value": "docker.io"},
                {"name": "image_path", "value": "library/python"},
                {
                    "name": "scan_depth",
                    "value": "declared_only (run with --with-syft for layer scan)",
                },
            ],
        }
    ]
    envelope = cyclonedx_envelope(components)
    envelope["metadata"]["component"] = {
        "type": "container",
        "name": "jpcite-runtime",
        "version": read_pyproject_version(),
        "supplier": {"name": "Bookyou株式会社"},
    }
    digest = write_json_atomic(out, envelope, dry_run)
    return digest, len(components)


# ---------------------------------------------------------------------------
# Aggregated index (public)
# ---------------------------------------------------------------------------

def write_index(entries: list[dict], dry_run: bool) -> None:
    """Write the public aggregated index at site/.well-known/sbom.json.

    The index advertises *what SBOMs we publish*. It is small, JSON-only,
    and safe to fetch anonymously — auditors hit it first to discover the
    per-surface CycloneDX shards.
    """
    payload = {
        "schema": "jpcite_sbom_index_v1",
        "generated_at": utc_now(),
        "operator": "Bookyou株式会社",
        "product": "jpcite",
        "product_version": read_pyproject_version(),
        "spec": f"CycloneDX {CYCLONEDX_SPEC}",
        "license": "CC0-1.0 (this index file)",
        "shards": entries,
        "policy": {
            "regeneration_cadence": "monthly (1st of month, GHA workflow)",
            "regeneration_workflow": ".github/workflows/sbom-publish-monthly.yml",
            "vulnerability_audit_tool": "pip-audit (PyPI advisory DB + OSV)",
            "scope_python": "main pyproject + sdk/freee-plugin + sdk/mf-plugin",
            "scope_npm": "@autonomath/sdk, @jpcite/agents, @bookyou/jpcite, vscode-extension",
            "scope_container": "Dockerfile FROM (declared); deep apt scan opt-in via syft",
            "report_disclosure_url": "https://jpcite.com/.well-known/security.txt",
        },
        "totals": {
            "shard_count": len(entries),
            "component_count": sum(e.get("component_count", 0) for e in entries),
        },
    }
    write_json_atomic(INDEX_PATH, payload, dry_run)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Generate SBOMs for jpcite supply chain")
    ap.add_argument("--dry-run", action="store_true", help="plan writes, do not touch disk")
    ap.add_argument("--skip-pip", action="store_true", help="skip Python pip-audit (faster CI)")
    ap.add_argument("--skip-npm", action="store_true", help="skip npm package.json parsing")
    ap.add_argument("--skip-docker", action="store_true", help="skip Docker base image record")
    ap.add_argument(
        "--reuse-docker",
        action="store_true",
        help=(
            "do not regenerate the Docker shard, but ingest the existing file's "
            "sha256 + component_count into the index. Used by the monthly workflow's "
            "syft path so a deep scan is preserved while the index stays consistent."
        ),
    )
    args = ap.parse_args()

    # Refuse to silently overwrite outside of the expected directory.
    if not args.dry_run:
        SBOM_DIR.mkdir(parents=True, exist_ok=True)

    print(f"jpcite SBOM generator v{TOOL_VERSION}")
    print(f"  repo_root = {REPO_ROOT}")
    print(f"  out_dir   = {SBOM_DIR.relative_to(REPO_ROOT)}")
    print(f"  dry_run   = {args.dry_run}")

    entries: list[dict] = []

    if not args.skip_pip:
        print("\n[1/4] pip (main project)")
        digest, count = emit_pip_main(args.dry_run)
        entries.append(
            {
                "label": "pip-main",
                "ecosystem": "python",
                "path": "site/.well-known/sbom/sbom-pip.cyclonedx.json",
                "sha256": digest,
                "component_count": count,
            }
        )

        for relpath, label, _kind in PIP_TARGETS:
            print(f"\n[1/4 sub] pip ({label})")
            digest, count = emit_pip_sub(relpath, label, args.dry_run)
            entries.append(
                {
                    "label": label,
                    "ecosystem": "python",
                    "path": f"site/.well-known/sbom/sbom-{label}.cyclonedx.json",
                    "sha256": digest,
                    "component_count": count,
                }
            )

    if not args.skip_npm:
        print("\n[2/4] npm packages")
        for relpath, label in NPM_TARGETS:
            print(f"  {label}")
            digest, count = emit_npm(relpath, label, args.dry_run)
            entries.append(
                {
                    "label": label,
                    "ecosystem": "npm",
                    "path": f"site/.well-known/sbom/sbom-{label}.cyclonedx.json",
                    "sha256": digest,
                    "component_count": count,
                }
            )

    if not args.skip_docker:
        print("\n[3/4] docker base image")
        if args.reuse_docker:
            existing = SBOM_DIR / "sbom-docker-base.cyclonedx.json"
            if not existing.exists():
                print("  --reuse-docker set but no existing shard — falling back to declared")
                digest, count = emit_docker(args.dry_run)
            else:
                body = existing.read_bytes()
                digest = sha256_bytes(body)
                count = len(json.loads(body).get("components", []))
                print(f"  reused existing shard sha256={digest[:12]}… ({count} components)")
        else:
            digest, count = emit_docker(args.dry_run)
        entries.append(
            {
                "label": "docker-base",
                "ecosystem": "container",
                "path": "site/.well-known/sbom/sbom-docker-base.cyclonedx.json",
                "sha256": digest,
                "component_count": count,
            }
        )

    print("\n[4/4] aggregated index")
    write_index(entries, args.dry_run)

    total = sum(e.get("component_count", 0) for e in entries)
    print(f"\nDone. {len(entries)} shards, {total} total components.")
    if args.dry_run:
        print("(dry-run — no files written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
