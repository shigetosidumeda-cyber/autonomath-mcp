#!/usr/bin/env python3
"""Smoke-validate every distribution surface AutonoMath publishes to.

This script does **NOT** publish anything. It chains the dry-run / validate / pack
commands for each of the 12 registries listed in `docs/registries.md` and exits
non-zero if any check fails.

Operator launch-day runbook (2026-05-06) is in `scripts/mcp_registries.md`.
This file is the *pre-launch gate* — it must pass before the operator runs the
real publish commands. The 24 h post-launch grace period is handled manually
because each registry has different review latency and rollback semantics.

Usage:
    .venv/bin/python scripts/publish_to_registries.py
    .venv/bin/python scripts/publish_to_registries.py --skip npm,dxt
    .venv/bin/python scripts/publish_to_registries.py --json

Exit codes:
    0 — every check passed
    1 — at least one check failed
    2 — script-level error (missing dependency, bad CLI args)

The 12 surfaces (in priority order, matching docs/registries.md):
    1. PyPI                       twine check dist/*
    2. npm                        npm pack --dry-run
    3. MCP Official Registry      json.load + schema sanity on server.json
    4. DXT (Anthropic)            json.load on dxt/manifest.json + .mcpb existence
    5. Smithery                   yaml.safe_load on smithery.yaml
    6. Glama                      no-op (auto-indexed; verify README + LICENSE)
    7. Cline MCP Marketplace      no-op (GitHub PR; verify README badge text)
    8. PulseMCP                   no-op (auto-ingest from #3)
    9. mcp.so                     no-op (form/issue submission)
   10. Awesome MCP Servers        no-op (GitHub PR; verify README badge text)
   11. Cursor Marketplace         no-op (web form)
   12. mcpservers.org             no-op (auto-mirror from #10)
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Per-surface check primitives. Each returns (ok: bool, detail: str).
# ---------------------------------------------------------------------------


def _which_or_none(cmd: str) -> str | None:
    """Return absolute path of `cmd` if found on PATH, else None."""
    return shutil.which(cmd)


def check_pypi(repo: Path) -> tuple[bool, str]:
    """Smoke: ensure dist/ has both sdist + wheel and twine check passes."""
    dist = repo / "dist"
    if not dist.is_dir():
        return False, f"dist/ missing — run `python -m build` first ({dist})"
    artefacts = sorted(p.name for p in dist.iterdir() if p.is_file())
    if not any(a.endswith(".whl") for a in artefacts):
        return False, f"no wheel in dist/ ({artefacts})"
    if not any(a.endswith(".tar.gz") for a in artefacts):
        return False, f"no sdist in dist/ ({artefacts})"
    twine = _which_or_none("twine")
    if twine is None:
        return True, f"dist/ ok ({artefacts}); twine not on PATH — install before launch"
    proc = subprocess.run(
        [twine, "check"] + [str(dist / a) for a in artefacts if a.endswith((".whl", ".tar.gz"))],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return False, f"twine check failed: {proc.stdout.strip()} | {proc.stderr.strip()}"
    return True, f"twine check passed ({artefacts})"


def check_npm(repo: Path) -> tuple[bool, str]:
    """Smoke: npm pack --dry-run inside sdk/typescript/ if present."""
    pkg = repo / "sdk" / "typescript"
    if not (pkg / "package.json").exists():
        return True, f"skipped (no sdk/typescript/package.json — npm publish not yet wired)"
    npm = _which_or_none("npm")
    if npm is None:
        return False, "npm not on PATH; install Node.js + npm to validate"
    proc = subprocess.run(
        [npm, "pack", "--dry-run"],
        cwd=str(pkg),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return False, f"npm pack --dry-run failed: {proc.stderr.strip()}"
    return True, "npm pack --dry-run passed"


def check_mcp_registry(repo: Path) -> tuple[bool, str]:
    """Smoke: server.json parses and has the required top-level fields."""
    server_json = repo / "server.json"
    if not server_json.exists():
        return False, f"server.json missing at {server_json}"
    try:
        d = json.loads(server_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return False, f"server.json invalid JSON: {e}"
    required = ["$schema", "name", "version", "description", "packages"]
    missing = [k for k in required if k not in d]
    if missing:
        return False, f"server.json missing required fields: {missing}"
    pkgs = d.get("packages", [])
    if not isinstance(pkgs, list) or not pkgs:
        return False, "server.json packages[] must be a non-empty list"
    pkg0 = pkgs[0]
    for k in ("registryType", "identifier", "version", "transport"):
        if k not in pkg0:
            return False, f"server.json packages[0] missing {k}"
    return True, f"server.json ok (name={d['name']} version={d['version']} packages={len(pkgs)})"


def check_dxt(repo: Path) -> tuple[bool, str]:
    """Smoke: dxt/manifest.json parses; .mcpb present at site/downloads/."""
    manifest = repo / "dxt" / "manifest.json"
    if not manifest.exists():
        return False, f"dxt/manifest.json missing at {manifest}"
    try:
        json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return False, f"dxt/manifest.json invalid JSON: {e}"
    bundle = repo / "site" / "downloads" / "autonomath-mcp.mcpb"
    if not bundle.exists():
        return False, (
            f".mcpb bundle missing at {bundle} — run `bash scripts/build_mcpb.sh`"
        )
    return True, f"dxt manifest + bundle ok ({bundle.stat().st_size} bytes)"


def check_smithery(repo: Path) -> tuple[bool, str]:
    """Smoke: smithery.yaml parses as YAML and has top-level keys."""
    smithery = repo / "smithery.yaml"
    if not smithery.exists():
        return False, f"smithery.yaml missing at {smithery}"
    try:
        import yaml  # type: ignore
    except ImportError:
        return True, "skipped (PyYAML not installed; install with `pip install pyyaml`)"
    try:
        d = yaml.safe_load(smithery.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return False, f"smithery.yaml invalid YAML: {e}"
    if not isinstance(d, dict) or not d:
        return False, "smithery.yaml must be a non-empty mapping"
    return True, f"smithery.yaml ok (keys={sorted(d.keys())})"


def check_readme_present(repo: Path) -> tuple[bool, str]:
    """Smoke: README.md + LICENSE present (for Glama auto-index + Awesome MCP PR)."""
    readme = repo / "README.md"
    license_file = repo / "LICENSE"
    if not readme.exists():
        return False, f"README.md missing at {readme}"
    if not license_file.exists():
        return False, f"LICENSE missing at {license_file}"
    return True, f"README.md ({readme.stat().st_size}B) + LICENSE present"


# ---------------------------------------------------------------------------
# Surface registry — order matches docs/registries.md
# ---------------------------------------------------------------------------


@dataclass
class Surface:
    id: str
    title: str
    check: callable
    notes: str = ""
    is_no_op: bool = False


SURFACES: list[Surface] = [
    Surface("pypi", "1. PyPI", check_pypi),
    Surface("npm", "2. npm", check_npm),
    Surface("mcp_registry", "3. MCP Official Registry", check_mcp_registry),
    Surface("dxt", "4. DXT (Anthropic Claude Desktop)", check_dxt),
    Surface("smithery", "5. Smithery", check_smithery),
    Surface(
        "glama",
        "6. Glama",
        check_readme_present,
        notes="auto-indexed from public repo; check README + LICENSE",
    ),
    Surface(
        "cline",
        "7. Cline MCP Marketplace",
        check_readme_present,
        notes="GitHub PR submission; needs README + LICENSE",
        is_no_op=True,
    ),
    Surface(
        "pulsemcp",
        "8. PulseMCP",
        check_readme_present,
        notes="auto-ingest from MCP Registry (#3); manual form for corrections",
        is_no_op=True,
    ),
    Surface(
        "mcp_so",
        "9. mcp.so",
        check_readme_present,
        notes="form / GitHub-issue submission",
        is_no_op=True,
    ),
    Surface(
        "awesome_mcp",
        "10. Awesome MCP Servers (punkpeye)",
        check_readme_present,
        notes="GitHub PR submission; needs README + LICENSE",
        is_no_op=True,
    ),
    Surface(
        "cursor",
        "11. Cursor Marketplace",
        check_readme_present,
        notes="web form submission",
        is_no_op=True,
    ),
    Surface(
        "mcpservers_org",
        "12. mcpservers.org",
        check_readme_present,
        notes="auto-mirror from Awesome MCP (#10)",
        is_no_op=True,
    ),
]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip",
        default="",
        help="Comma-separated surface ids to skip (e.g. --skip npm,cursor)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON report on stdout instead of human text",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=REPO_ROOT,
        help=f"Repo root (default: {REPO_ROOT})",
    )
    args = parser.parse_args(argv)

    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    repo: Path = args.repo.resolve()

    results: list[dict[str, object]] = []
    overall_ok = True

    for s in SURFACES:
        if s.id in skip:
            results.append({"id": s.id, "title": s.title, "status": "skipped", "detail": "user-requested skip"})
            continue
        try:
            ok, detail = s.check(repo)
        except Exception as exc:  # pragma: no cover - defensive
            ok, detail = False, f"exception: {exc!r}"
        if not ok and not s.is_no_op:
            overall_ok = False
        results.append({
            "id": s.id,
            "title": s.title,
            "status": "ok" if ok else ("warn" if s.is_no_op else "fail"),
            "detail": detail,
            "notes": s.notes,
        })

    if args.json:
        print(json.dumps({"overall_ok": overall_ok, "results": results}, ensure_ascii=False, indent=2))
    else:
        print(f"AutonoMath registry smoke — repo={repo}")
        print("=" * 72)
        for r in results:
            marker = {"ok": "[ok]", "warn": "[warn]", "fail": "[FAIL]", "skipped": "[skip]"}[str(r["status"])]
            print(f"{marker:<7} {r['title']}")
            print(f"        {r['detail']}")
            if r["notes"]:
                print(f"        note: {r['notes']}")
        print("=" * 72)
        print(f"OVERALL: {'OK' if overall_ok else 'FAIL'}")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
