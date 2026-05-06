#!/usr/bin/env python3
"""Acceptance gate for the jpcite user-value improvement loop.

This script is intentionally deterministic and dependency-free. It checks the
surfaces that should change when another CLI implements the 2026-05-03 user
value plan:

* public copy stays honest about token/cost claims;
* LLM/GEO/MCP discovery links are not broken;
* API response models expose machine-readable value signals;
* analytics and deploy-safety footguns are not left in place;
* production code still has no request-time LLM API imports.

It is not a replacement for the full test suite. Treat it as a fast
post-implementation acceptance screen before deeper pytest/smoke/deploy checks.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

PUBLIC_SURFACES = [
    "README.md",
    "site/index.html",
    "site/playground.html",
    "site/pricing.html",
    "site/llms.txt",
    "site/llms.en.txt",
    "site/en/llms.txt",
    "site/integrations/openai-custom-gpt.html",
    "docs/getting-started.md",
    "docs/api-reference.md",
    "docs/pricing.md",
    "docs/mcp-tools.md",
    "server.json",
    "mcp-server.json",
    "smithery.yaml",
    "dxt/manifest.json",
]

API_VALUE_SURFACES = [
    "src/jpintel_mcp/services/token_compression.py",
    "src/jpintel_mcp/services/evidence_packet.py",
    "src/jpintel_mcp/api/intelligence.py",
    "src/jpintel_mcp/api/_response_models.py",
    "docs/api-reference.md",
    "docs/openapi/v1.json",
    "tests/test_evidence_packet.py",
    "tests/test_intelligence_api.py",
]

FORBIDDEN_PUBLIC_PATTERNS = {
    "token_cost_shield": r"Token Cost Shield",
    "guaranteed_cost_reduction": (
        r"LLM\s*費用を削減保証|"
        r"費用削減を保証|"
        r"削減を保証|"
        r"削減保証します|"
        r"削減保証です|"
        r"必ず安くなる(?![」”』\s]*ではなく)"
    ),
    "primary_source_100": r"一次資料\s*100|一次資料100",
    "legacy_free_quota_50_month": r"50\s*req/月|50/月\s*free",
    "legacy_mcp_tool_count_89": r"89\s+MCP tools|89\s+tools|89-tool|MCP ツール一覧\s*\(89\)",
    "broken_dxt_link": r"jpcite-mcp\.dxt",
    "old_repo_slug_public": r"shigetosidumeda-cyber/jpintel-mcp",
}

REQUIRED_API_VALUE_TOKENS = [
    "input_context_reduction_rate",
    "provider_billing_not_guaranteed",
    "break_even_source_tokens_estimate",
    "evidence_value",
    "recommend_for_evidence",
    "evidence_decision",
    "value_reasons",
]

NEGATED_COST_CLAIM_TERMS = (
    "保証するものではありません",
    "保証するものではない",
    "保証しません",
    "保証しない",
    "保証なし",
    "避けて",
    "ではなく",
    "ではありません",
    "not guarantee",
    "not guaranteed",
    "not billing guarantees",
)

LLM_IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+"
    r"(?:anthropic|openai|google\.generativeai|claude_agent_sdk)\b",
    re.MULTILINE,
)


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str
    evidence: list[str]

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "evidence": self.evidence,
        }


def _read(path: str | Path) -> str:
    full = REPO_ROOT / path
    try:
        return full.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _exists(path: str | Path) -> bool:
    return (REPO_ROOT / path).exists()


def _line_hits(text: str, pattern: str) -> list[str]:
    rx = re.compile(pattern)
    hits: list[str] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        if rx.search(line):
            hits.append(f"L{idx}: {line.strip()[:180]}")
    return hits


def _public_texts():
    for rel in PUBLIC_SURFACES:
        text = _read(rel)
        if text:
            yield rel, text


def _pass(name: str, detail: str, evidence: list[str] | None = None) -> CheckResult:
    return CheckResult(name, "PASS", detail, evidence or [])


def _fail(name: str, detail: str, evidence: list[str] | None = None) -> CheckResult:
    return CheckResult(name, "FAIL", detail, evidence or [])


def _warn(name: str, detail: str, evidence: list[str] | None = None) -> CheckResult:
    return CheckResult(name, "WARN", detail, evidence or [])


def check_public_claims() -> CheckResult:
    evidence: list[str] = []
    for rel, text in _public_texts():
        for label, pattern in FORBIDDEN_PUBLIC_PATTERNS.items():
            rx = re.compile(pattern)
            for idx, line in enumerate(text.splitlines(), start=1):
                if not rx.search(line):
                    continue
                if label == "guaranteed_cost_reduction" and any(
                    term in line for term in NEGATED_COST_CLAIM_TERMS
                ):
                    continue
                evidence.append(f"{rel}:{label}:L{idx}: {line.strip()[:180]}")
    if evidence:
        return _fail(
            "public_claims_and_legacy_copy",
            "Public/distribution surfaces still contain forbidden or stale claims.",
            evidence,
        )
    return _pass(
        "public_claims_and_legacy_copy",
        "No forbidden token-cost, quota, tool-count, or old repo claims found.",
    )


def check_no_llm_imports() -> CheckResult:
    scan_roots = [
        REPO_ROOT / "src" / "jpintel_mcp",
        REPO_ROOT / "scripts" / "cron",
        REPO_ROOT / "scripts" / "etl",
        REPO_ROOT / "tests",
    ]
    evidence: list[str] = []
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            rel = path.relative_to(REPO_ROOT)
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in LLM_IMPORT_RE.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                evidence.append(f"{rel}:L{line_no}:{match.group(0).strip()}")
    if evidence:
        return _fail(
            "no_llm_api_imports",
            "Production/test Python surfaces import an LLM API package.",
            evidence,
        )
    return _pass("no_llm_api_imports", "No request-time LLM API imports found.")


def check_api_value_tokens() -> CheckResult:
    combined = "\n".join(_read(path) for path in API_VALUE_SURFACES)
    missing = [token for token in REQUIRED_API_VALUE_TOKENS if token not in combined]
    if missing:
        return _fail(
            "api_value_signals",
            "Expected machine-readable value tokens are missing.",
            missing,
        )
    return _pass(
        "api_value_signals",
        "Evidence/cost recommendation value fields are present in API/docs/tests.",
        REQUIRED_API_VALUE_TOKENS,
    )


def check_llms_first_call_block() -> CheckResult:
    text = _read("site/llms.txt")
    head = "\n".join(text.splitlines()[:80])
    required = ["Use when", "Do not use", "First call", "OpenAPI", "Pricing"]
    missing = [token for token in required if token not in head]
    bad_examples = []
    for pattern in [
        r'target_industry="construction"',
        r"jigyo-saikouchiku-r6",
        r"monodzukuri-r6",
    ]:
        bad_examples.extend(_line_hits(text, pattern))
    if missing or bad_examples:
        evidence = [f"missing_in_first_80:{token}" for token in missing]
        evidence.extend(f"unsafe_example:{hit}" for hit in bad_examples)
        return _fail(
            "llms_first_call_block",
            "llms.txt does not yet give agents a clean first-call recipe.",
            evidence,
        )
    return _pass(
        "llms_first_call_block",
        "llms.txt first 80 lines include use/do-not-use/first-call/install cues.",
    )


def _json_version(path: str) -> str | None:
    try:
        return json.loads(_read(path)).get("version")
    except json.JSONDecodeError:
        return None


def _pyproject_version() -> str | None:
    match = re.search(r'^version\s*=\s*"([^"]+)"', _read("pyproject.toml"), re.MULTILINE)
    return match.group(1) if match else None


def _smithery_version() -> str | None:
    match = re.search(r"^\s*version:\s*['\"]?([^'\"\n]+)", _read("smithery.yaml"), re.MULTILINE)
    return match.group(1).strip() if match else None


def check_mcp_distribution() -> CheckResult:
    evidence: list[str] = []
    mcpb = REPO_ROOT / "site" / "downloads" / "autonomath-mcp.mcpb"
    if not mcpb.exists():
        evidence.append("missing:site/downloads/autonomath-mcp.mcpb")
    else:
        try:
            with zipfile.ZipFile(mcpb) as archive:
                if "manifest.json" not in archive.namelist():
                    evidence.append("mcpb_missing_root_manifest_json")
        except zipfile.BadZipFile as exc:
            evidence.append(f"bad_mcpb_zip:{exc}")

    versions = {
        "pyproject.toml": _pyproject_version(),
        "server.json": _json_version("server.json"),
        "mcp-server.json": _json_version("mcp-server.json"),
        "dxt/manifest.json": _json_version("dxt/manifest.json"),
        "smithery.yaml": _smithery_version(),
    }
    unique_versions = {version for version in versions.values() if version}
    if len(unique_versions) != 1 or any(version is None for version in versions.values()):
        evidence.extend(f"{path}:{version}" for path, version in versions.items())

    if not (_exists("site/server.json") or _exists("site/mcp-server.json")):
        llms = _read("site/llms.txt")
        if "server.json" not in llms and "mcp-server.json" not in llms:
            evidence.append("no_public_manifest_link_or_site_copy")

    if evidence:
        return _fail(
            "mcp_distribution",
            "MCP bundle/version/manifest discovery gate failed.",
            evidence,
        )
    return _pass(
        "mcp_distribution",
        "MCP bundle is readable, manifest versions match, and manifest discovery exists.",
        [f"{path}:{version}" for path, version in versions.items()],
    )


def check_playground_funnel() -> CheckResult:
    text = _read("site/playground.html")
    evidence: list[str] = []
    for pattern in [
        r"NUDGE_THRESHOLD\s*=\s*10",
        r"10th success",
        r"残\s*N/50",
        r"50 req",
    ]:
        evidence.extend(_line_hits(text, pattern))
    if "evidence3" not in text:
        evidence.append("missing:evidence3 flow")
    if "source_tokens_basis" not in text or "source_pdf_pages" not in text:
        evidence.append("missing:compression baseline playground fields")
    if evidence:
        return _fail(
            "playground_three_try_funnel",
            "Playground does not yet align with anonymous 3-request evaluation.",
            evidence,
        )
    return _pass(
        "playground_three_try_funnel",
        "Playground appears aligned with evidence3 and compression-baseline trial.",
    )


def check_pricing_explains_break_even() -> CheckResult:
    text = _read("docs/pricing.md") + "\n" + _read("site/pricing.html")
    required = ["break_even_met", "入力文脈", "保証"]
    missing = [token for token in required if token not in text]
    if missing:
        return _fail(
            "pricing_break_even_copy",
            "Pricing surfaces do not explain conditional break-even semantics.",
            missing,
        )
    return _pass(
        "pricing_break_even_copy",
        "Pricing surfaces mention input-context break-even and no guarantee.",
    )


def check_analytics_measurement() -> CheckResult:
    evidence: list[str] = []
    workflow = _read(".github/workflows/analytics-cron.yml")
    cf_export = _read("scripts/cron/cf_analytics_export.py")
    if "zeimu-kaikei.ai" in workflow:
        evidence.append(".github/workflows/analytics-cron.yml still mentions zeimu-kaikei.ai")
    if "clientRequestPath: edgeResponseStatus" in cf_export:
        evidence.append("cf_analytics_export.py still aliases path to status")
    for token in ["top_paths", "status", "user_agent", "country"]:
        if token not in cf_export:
            evidence.append(f"cf_analytics_export.py missing expected collector token:{token}")
    if evidence:
        return _fail(
            "analytics_measurement",
            "Analytics export still cannot support a clean conversion/funnel view.",
            evidence,
        )
    return _pass(
        "analytics_measurement",
        "Cloudflare analytics export appears updated for jpcite and richer dimensions.",
    )


def check_deploy_safety() -> CheckResult:
    evidence: list[str] = []
    entrypoint = _read("entrypoint.sh")
    schema_guard = _read("scripts/schema_guard.py")
    smoke = _read("scripts/smoke_test.sh")
    deploy = _read(".github/workflows/deploy.yml")
    backup = _read(".github/workflows/nightly-backup.yml")

    for token in [".new", "quick_check", "COUNT(*) FROM programs"]:
        if token not in entrypoint:
            evidence.append(f"entrypoint.sh missing:{token}")
    for token in ["DEFAULT_PROD_PROGRAMS_FLOOR", "quick_check", "JPINTEL_ENV"]:
        if token not in schema_guard:
            evidence.append(f"schema_guard.py missing:{token}")
    if "programs total <=0" in smoke or "WARN programs total <=0" in smoke:
        evidence.append("scripts/smoke_test.sh still warns instead of failing on empty programs")
    if "scripts/smoke_test.sh" not in deploy and "./scripts/smoke_test.sh" not in deploy:
        evidence.append(".github/workflows/deploy.yml missing post-deploy smoke gate")
    if "R2 secrets not fully configured" not in backup or "exit 1" not in backup:
        evidence.append(".github/workflows/nightly-backup.yml missing explicit R2 fail-closed exit")
    if "::warning::R2" in backup or "silently lost off-site DR" not in backup:
        evidence.append(
            ".github/workflows/nightly-backup.yml may still carry old R2 warning semantics"
        )

    if evidence:
        return _fail(
            "deploy_and_billing_safety",
            "Deploy/seed/backup smoke gates are not fully fail-closed.",
            evidence,
        )
    return _pass(
        "deploy_and_billing_safety",
        "Seed/schema/smoke/backup safety checks appear fail-closed.",
    )


def check_worktree_context() -> CheckResult:
    try:
        proc = subprocess.run(
            ["git", "status", "--short", "--branch"],
            cwd=REPO_ROOT,
            text=True,
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        return _warn("worktree_context", f"Could not run git status: {exc}")
    lines = proc.stdout.strip().splitlines()
    dirty = [line for line in lines[1:] if line.strip()]
    if dirty:
        return _warn(
            "worktree_context",
            "Worktree has pending changes; review ownership before staging.",
            lines,
        )
    return _pass("worktree_context", "Worktree is clean.", lines)


def run_checks() -> list[CheckResult]:
    return [
        check_worktree_context(),
        check_public_claims(),
        check_no_llm_imports(),
        check_api_value_tokens(),
        check_llms_first_call_block(),
        check_mcp_distribution(),
        check_playground_funnel(),
        check_pricing_explains_break_even(),
        check_analytics_measurement(),
        check_deploy_safety(),
    ]


def _print_text(results: list[CheckResult]) -> None:
    for result in results:
        print(f"[{result.status}] {result.name}: {result.detail}")
        for item in result.evidence[:20]:
            print(f"  - {item}")
        if len(result.evidence) > 20:
            print(f"  - ... {len(result.evidence) - 20} more")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Always exit 0; useful while another CLI is still implementing.",
    )
    args = parser.parse_args(argv)

    results = run_checks()
    if args.json:
        print(json.dumps([result.as_dict() for result in results], ensure_ascii=False, indent=2))
    else:
        _print_text(results)

    has_fail = any(result.status == "FAIL" for result in results)
    return 0 if args.warn_only or not has_fail else 1


if __name__ == "__main__":
    sys.exit(main())
