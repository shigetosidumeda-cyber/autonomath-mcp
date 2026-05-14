#!/usr/bin/env python3
"""One-command local gate for frontend copy/static releases.

Default mode is read-only and fast enough to run before every public-site
commit. Use `--refresh-static` when generated docs/assets should be rebuilt
locally before the checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable


def run(cmd: list[str], *, required: bool = True, env: dict[str, str] | None = None) -> int:
    print("+ " + " ".join(cmd), flush=True)
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    result = subprocess.run(cmd, cwd=REPO_ROOT, env=run_env)
    if required and result.returncode:
        raise SystemExit(result.returncode)
    return result.returncode


def strip_trailing_whitespace(root: Path) -> None:
    suffixes = {".html", ".md", ".txt", ".json", ".xml"}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        original = path.read_text(encoding="utf-8", errors="replace")
        stripped = "\n".join(line.rstrip() for line in original.splitlines())
        if original.endswith("\n"):
            stripped += "\n"
        if stripped != original:
            path.write_text(stripped, encoding="utf-8")


def sync_openapi_discovery_metadata() -> None:
    discovery_path = REPO_ROOT / "site" / ".well-known" / "openapi-discovery.json"
    if not discovery_path.exists():
        return
    discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
    tier_paths = {
        "full": REPO_ROOT / "site" / "docs" / "openapi" / "v1.json",
        "agent": REPO_ROOT / "site" / "openapi.agent.json",
        "gpt30": REPO_ROOT / "site" / "openapi.agent.gpt30.json",
    }
    for tier in discovery.get("tiers", []):
        path = tier_paths.get(str(tier.get("tier")))
        if not path or not path.exists():
            continue
        spec_text = path.read_text(encoding="utf-8")
        spec = json.loads(spec_text)
        tier["path_count"] = len(spec.get("paths") or {})
        tier["size_bytes"] = path.stat().st_size
        tier["sha256_prefix"] = hashlib.sha256(spec_text.encode("utf-8")).hexdigest()[:16]
    discovery_path.write_text(
        json.dumps(discovery, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def resolve_executable(name: str) -> str:
    on_path = shutil.which(name)
    if on_path:
        return on_path
    local = REPO_ROOT / ".venv" / "bin" / name
    if local.exists():
        return str(local)
    raise SystemExit(f"{name} is not on PATH or in .venv/bin; cannot refresh generated docs")


def maybe_refresh_static() -> None:
    run(
        [
            PY,
            "scripts/export_openapi.py",
            "--out",
            "docs/openapi/v1.json",
            "--site-out",
            "site/openapi/v1.json",
        ]
    )
    shutil.copyfile(
        REPO_ROOT / "site" / "openapi" / "v1.json",
        REPO_ROOT / "site" / "docs" / "openapi" / "v1.json",
    )
    run([PY, "scripts/export_agent_openapi.py"])
    run(
        [
            PY,
            "scripts/export_openapi.py",
            "--profile",
            "gpt30",
            "--out",
            "site/openapi.agent.gpt30.json",
        ]
    )
    run([PY, "scripts/sync_mcp_public_manifests.py"])
    sync_openapi_discovery_metadata()
    run(
        [resolve_executable("mkdocs"), "build", "--strict"],
        env={"MKDOCS_SOCIAL_ENABLED": os.environ.get("MKDOCS_SOCIAL_ENABLED", "false")},
    )
    strip_trailing_whitespace(REPO_ROOT / "site" / "docs")
    run([PY, "scripts/build_minify.py", "--no-fonts", "--no-webp"])
    run([PY, "scripts/sitemap_gen.py", "--site-dir", "site", "--domain", "jpcite.com"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh-static",
        action="store_true",
        help="rebuild mkdocs, minified assets, and sitemap before checks",
    )
    parser.add_argument(
        "--with-pre-deploy",
        action="store_true",
        help="also run scripts/ops/pre_deploy_verify.py",
    )
    args = parser.parse_args()

    if args.refresh_static:
        maybe_refresh_static()

    run([PY, "scripts/ops/public_copy_freshness.py"])
    run(["node", "--check", "site/assets/playground.bundle.js"])
    run(["git", "diff", "--check"])
    run(
        [
            PY,
            "-m",
            "pytest",
            "-q",
            "tests/test_public_copy_freshness.py",
            "tests/test_public_site_integrity.py",
            "tests/test_static_public_reachability.py",
            "tests/test_audiences_cost_saving.py",
            "tests/test_audiences_rest_cost_saving.py",
            "tests/test_cron_program_static_links.py",
        ]
    )
    if args.with_pre_deploy:
        run([PY, "scripts/ops/pre_deploy_verify.py"])
    print("frontend release check: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
