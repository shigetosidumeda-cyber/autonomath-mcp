#!/usr/bin/env python3
"""check_openapi_drift: assert published OpenAPI specs are current.

LLM 呼出ゼロ。Targets:
- site/openapi.agent.json -> openapi_paths_agent range
- site/openapi.agent.gpt30.json -> openapi_paths_agent range
- docs/openapi/v1.json -> openapi_paths_public range

The numeric ranges catch implausible schema changes. The regen comparisons
catch stale-but-valid JSON that would otherwise pass syntax checks and publish
to Pages. The leak-pattern scan (A3 extension) catches internal table names
and runbook references that survived the export-time sanitizer.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "data" / "facts_registry.json"
OPENAPI_DISCOVERY = ROOT / "site" / ".well-known" / "openapi-discovery.json"

# Banned leak patterns — keep aligned with
# `scripts/export_openapi.BANNED_OPENAPI_LEAK_PATTERNS` and
# `scripts/sync_mcp_public_manifests.BANNED_PUBLIC_LEAK_PATTERNS`.
LEAK_SCAN_TARGETS = (
    "docs/openapi/v1.json",
    "docs/openapi/agent.json",
    "site/openapi.agent.json",
    "site/openapi/agent.json",
    "site/openapi.agent.gpt30.json",
    "site/docs/openapi/v1.json",
    "site/docs/openapi/agent.json",
)

BANNED_LEAK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bam_compat_matrix\b"),
    re.compile(r"\bam_entity_facts\b"),
    re.compile(r"\bam_entities\b"),
    re.compile(r"\bam_relation\b"),
    re.compile(r"\bam_loan_product\b"),
    re.compile(r"\bam_law_article\b"),
    re.compile(r"\bam_enforcement_detail\b"),
    re.compile(r"\bam_amount_condition\b"),
    re.compile(r"\bam_tax_treaty\b"),
    re.compile(r"\bam_industry_jsic\b"),
    re.compile(r"\bam_application_round\b"),
    re.compile(r"\bam_amendment_snapshot\b"),
    re.compile(r"\bam_amendment_diff\b"),
    re.compile(r"\bhoujin_watch\b"),
    re.compile(r"\busage_events\b"),
    re.compile(r"\bcost_ledger\b"),
    re.compile(r"\bidempotency_cache\b"),
    re.compile(r"\bjpintel\.db\b", re.IGNORECASE),
    re.compile(r"\bautonomath\.db\b", re.IGNORECASE),
    re.compile(r"CLAUDE\.md"),
    re.compile(r"\bWave\s+\d", re.IGNORECASE),
    re.compile(r"\bmigration\s+\d", re.IGNORECASE),
    re.compile(r"\bscripts/cron/"),
    re.compile(r"\bscripts/etl/"),
)


def _maybe_reexec_venv() -> None:
    """Use the repo virtualenv when invoked by a bare system python."""

    venv_python = ROOT / ".venv" / "bin" / "python"
    if (
        venv_python.exists()
        and pathlib.Path(sys.executable).resolve() != venv_python.resolve()
        and os.environ.get("JPCITE_NO_VENV_REEXEC") != "1"
    ):
        os.environ["JPCITE_NO_VENV_REEXEC"] = "1"
        os.execv(str(venv_python), [str(venv_python), *sys.argv])


_maybe_reexec_venv()

CHECKS = [
    ("site/openapi.agent.json", "openapi_paths_agent"),
    ("site/openapi.agent.gpt30.json", "openapi_paths_agent"),
    ("docs/openapi/v1.json", "openapi_paths_public"),
]

DISCOVERY_TIERS = {
    "full": "site/docs/openapi/v1.json",
    "agent": "site/openapi.agent.json",
    "gpt30": "site/openapi.agent.gpt30.json",
}


def _stable_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["AUTONOMATH_EXPERIMENTAL_API_ENABLED"] = "0"
    src = str(ROOT / "src")
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def _run(cmd: list[str]) -> None:
    subprocess.run(
        cmd,
        cwd=ROOT,
        env=_stable_env(),
        check=True,
        text=True,
        stdout=sys.stdout,
        stderr=subprocess.STDOUT,
    )


def _diff_summary(expected: pathlib.Path, actual: pathlib.Path, label: str) -> str:
    expected_lines = expected.read_text(encoding="utf-8").splitlines()
    actual_lines = actual.read_text(encoding="utf-8").splitlines()
    diff = list(
        difflib.unified_diff(
            actual_lines,
            expected_lines,
            fromfile=f"committed/{label}",
            tofile=f"regenerated/{label}",
            lineterm="",
            n=3,
        )
    )
    if not diff:
        return f"{label}: bytes differ but text diff is empty"
    shown = "\n".join(diff[:80])
    suffix = "\n... diff truncated ..." if len(diff) > 80 else ""
    return f"{label} is stale; run the exporter and commit the result:\n{shown}{suffix}"


def _compare_file(committed_rel: str, generated: pathlib.Path, fails: list[str]) -> None:
    committed = ROOT / committed_rel
    if not committed.exists():
        fails.append(f"{committed_rel}: missing committed publish surface")
        return
    if committed.read_bytes() != generated.read_bytes():
        fails.append(_diff_summary(generated, committed, committed_rel))
    else:
        print(f"OK {committed_rel}: matches regenerated export")


def _check_regenerated_exports(fails: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="jpcite-openapi-drift-") as tmp:
        tmpdir = pathlib.Path(tmp)

        full_docs = tmpdir / "docs-openapi-v1.json"
        full_site = tmpdir / "site-docs-openapi-v1.json"
        _run(
            [
                sys.executable,
                "scripts/export_openapi.py",
                "--out",
                str(full_docs),
                "--site-out",
                str(full_site),
            ],
        )
        _compare_file("docs/openapi/v1.json", full_docs, fails)
        _compare_file("site/docs/openapi/v1.json", full_site, fails)

        agent_docs = tmpdir / "docs-openapi-agent.json"
        agent_root = tmpdir / "site-openapi-agent.json"
        agent_directory = tmpdir / "site-openapi-agent-directory.json"
        agent_site = tmpdir / "site-docs-openapi-agent.json"
        _run(
            [
                sys.executable,
                "scripts/export_agent_openapi.py",
                "--out",
                str(agent_docs),
                "--site-root-out",
                str(agent_root),
                "--site-directory-out",
                str(agent_directory),
                "--site-out",
                str(agent_site),
            ],
        )
        _compare_file("docs/openapi/agent.json", agent_docs, fails)
        _compare_file("site/openapi.agent.json", agent_root, fails)
        _compare_file("site/openapi/agent.json", agent_directory, fails)
        _compare_file("site/docs/openapi/agent.json", agent_site, fails)

        gpt30_committed = ROOT / "site/openapi.agent.gpt30.json"
        if gpt30_committed.exists():
            gpt30_tmp = tmpdir / "site-openapi-agent-gpt30.json"
            # The exporter preserves hand-curated policy blocks from the target
            # file. Seed the temp target so this check validates route/schema
            # freshness without stripping those curated blocks.
            shutil.copyfile(gpt30_committed, gpt30_tmp)
            _run(
                [
                    sys.executable,
                    "scripts/export_openapi.py",
                    "--profile",
                    "gpt30",
                    "--out",
                    str(gpt30_tmp),
                ],
            )
            _compare_file("site/openapi.agent.gpt30.json", gpt30_tmp, fails)
        else:
            print("SKIP site/openapi.agent.gpt30.json (not present)")


def _check_leak_patterns(fails: list[str]) -> None:
    """Hard gate: refuse to publish if a banned leak pattern survived.

    Per E11 audit the leak scan exempts JSON-pointer subtrees that the runtime
    echoes back verbatim (`default` / `example` / `examples` / `operationId`).
    We delegate to `export_openapi.assert_no_openapi_leaks`, which applies the
    same exemption — description / summary leaks still trip but runtime-echoed
    literals in exempt slots are accepted.
    """
    # Lazy-import so this module remains useful standalone (without the venv
    # holding `export_openapi` on sys.path it falls back to the local scan).
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from export_openapi import (  # type: ignore[import-not-found]
            assert_no_openapi_leaks as _assert_no_openapi_leaks,
        )
    except Exception:  # noqa: BLE001 -- best-effort import
        _assert_no_openapi_leaks = None  # type: ignore[assignment]

    for rel in LEAK_SCAN_TARGETS:
        path = ROOT / rel
        if not path.exists():
            print(f"SKIP {rel} (not present, leak scan)")
            continue
        try:
            payload = path.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 -- best-effort read
            fails.append(f"{rel}: read error during leak scan: {exc}")
            continue
        if _assert_no_openapi_leaks is not None:
            try:
                _assert_no_openapi_leaks(payload, label=rel)
            except SystemExit as exc:
                message = str(exc)
                fails.append(
                    f"{rel}: leak patterns survived sanitizer — re-run "
                    f"scripts/export_openapi.py and scripts/export_agent_openapi.py; "
                    f"{message}"
                )
            else:
                print(f"OK {rel}: no banned leak patterns")
            continue
        # Fallback: in-line scan over the raw text (no exemption awareness).
        hits: list[str] = []
        for pattern in BANNED_LEAK_PATTERNS:
            match = pattern.search(payload)
            if match:
                idx = match.start()
                window = payload[max(0, idx - 60) : idx + 80].replace("\n", " ")
                hits.append(f"{pattern.pattern!r} near …{window}…")
        if hits:
            joined = "; ".join(hits[:6])
            suffix = f" (+{len(hits) - 6} more)" if len(hits) > 6 else ""
            fails.append(
                f"{rel}: leak patterns survived sanitizer — re-run "
                f"scripts/export_openapi.py and scripts/export_agent_openapi.py; "
                f"leaks: {joined}{suffix}"
            )
        else:
            print(f"OK {rel}: no banned leak patterns")


def _check_openapi_discovery(fails: list[str]) -> None:
    if not OPENAPI_DISCOVERY.exists():
        print("SKIP site/.well-known/openapi-discovery.json (not present)")
        return
    try:
        discovery = json.loads(OPENAPI_DISCOVERY.read_text("utf-8"))
    except Exception as e:
        fails.append(f"site/.well-known/openapi-discovery.json: parse error {e}")
        return
    tiers = {
        tier.get("tier"): tier
        for tier in discovery.get("tiers", [])
        if isinstance(tier, dict)
    }
    for tier_name, rel in DISCOVERY_TIERS.items():
        path = ROOT / rel
        if not path.exists():
            fails.append(f"{rel}: missing spec referenced by openapi-discovery tier {tier_name}")
            continue
        tier = tiers.get(tier_name)
        if not isinstance(tier, dict):
            fails.append(f"site/.well-known/openapi-discovery.json: missing tier {tier_name}")
            continue
        spec_text = path.read_text("utf-8")
        try:
            path_count = len(json.loads(spec_text).get("paths") or {})
        except Exception as e:
            fails.append(f"{rel}: parse error while checking discovery metadata {e}")
            continue
        expected = {
            "path_count": path_count,
            "size_bytes": path.stat().st_size,
            "sha256_prefix": hashlib.sha256(spec_text.encode("utf-8")).hexdigest()[:16],
        }
        for key, value in expected.items():
            if tier.get(key) != value:
                fails.append(
                    "site/.well-known/openapi-discovery.json: "
                    f"tier {tier_name} {key}={tier.get(key)!r} "
                    f"does not match {rel} ({value!r})"
                )
        print(f"OK site/.well-known/openapi-discovery.json: tier {tier_name} metadata current")


def main() -> int:
    reg = json.loads(REGISTRY.read_text("utf-8"))
    ranges = reg["guards"]["numeric_ranges"]
    fails: list[str] = []

    for rel, key in CHECKS:
        p = ROOT / rel
        if not p.exists():
            print(f"SKIP {rel} (not present)")
            continue
        try:
            spec = json.loads(p.read_text("utf-8"))
        except Exception as e:
            fails.append(f"{rel}: parse error {e}")
            continue
        n = len(spec.get("paths") or {})
        lo, hi = ranges[key]
        if not lo <= n <= hi:
            fails.append(f"{rel}: paths={n} not in [{lo},{hi}] ({key})")
        else:
            print(f"OK {rel}: paths={n} in [{lo},{hi}] ({key})")

    _check_regenerated_exports(fails)
    _check_openapi_discovery(fails)
    _check_leak_patterns(fails)

    if fails:
        for f in fails:
            print("FAIL", f)
        return 1
    print("OK: openapi drift gates passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
