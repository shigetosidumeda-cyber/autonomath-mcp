#!/usr/bin/env python3
"""Wave 17 AX — Agent Experience (AX) Journey 6-step audit runner.

Background
----------
ax_smart_guide.md §3.3 frames an agent's lifecycle on jpcite as six
journey steps: Discovery → Evaluation → Authentication → Execution →
Recovery → Completion. Each step has its own failure shape (a missing
discovery hint vs an unrecoverable Execution error are different bugs),
so the score is per-step, not a single number.

This runner is the AX counterpart to the SEO / GEO / AI-bot audits that
already live in `scripts/ops/`. Same NO-network + read-only contract:
the script walks repo artifacts (site/, src/, data/, docs/) and grep-
detects how much of each step is wired. Every score is 0-10 with one
small wrinkle: step 5 (Recovery) deducts 1 point per "agent-visible
failure pattern" detected, since a single un-canonical retryable error
can stall an autonomous loop indefinitely.

Pure stdlib. Read-only on repo. NO LLM call. Safe to run in CI / pre-
commit. Memory `feedback_no_operator_llm_api`: production-side audit
must be 0 LLM imports.

Output
------
`docs/audit/agent_journey_6step_audit_{date}.md` by default, structured
as 1 header + 6 step sections + 1 findings summary. JSON output via
`--out-json` if the operator wants to ingest into the regression gate.

Exit codes
----------
0 always (audit is observational; threshold gates live in
`audit-regression-gate.yml`). Failing scores surface in the markdown.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SITE = REPO_ROOT / "site"
SRC = REPO_ROOT / "src" / "jpintel_mcp"
DOCS = REPO_ROOT / "docs"
DATA = REPO_ROOT / "data"

# ---------------------------------------------------------------------------
# Step 1: Discovery — can an agent find jpcite at all?
# ---------------------------------------------------------------------------
DISCOVERY_REQUIRED = [
    SITE / "robots.txt",
    SITE / "sitemap.xml",
    SITE / "llms.txt",
    SITE / "llms-full.txt",
    SITE / ".well-known" / "mcp.json",
    SITE / ".well-known" / "agents.json",
    SITE / ".well-known" / "ai-plugin.json",
    REPO_ROOT / "README.md",
]
AI_BOT_WELCOME_UAS = [
    "GPTBot",
    "ChatGPT-User",
    "ClaudeBot",
    "Claude-User",
    "PerplexityBot",
    "Google-Extended",
]
MCP_REGISTRY_HINTS = ("mcp.so", "smithery.ai", "directory.llmstxt.org")


# ---------------------------------------------------------------------------
# Step 2: Evaluation — can the agent decide if jpcite fits its task?
# ---------------------------------------------------------------------------
EVALUATION_REQUIRED = [
    DOCS / "api-reference.md",
    DOCS / "examples.md",
    DOCS / "faq.md",
    DOCS / "getting-started.md",
    DOCS / "cookbook",
    DOCS / "recipes",
    DATA / "fence_registry.json",
]
EIGHT_BUSINESS_LAW_FENCES = (
    "税理士法",  # zeirishi
    "弁護士法",  # bengoshi
    "司法書士法",  # shihoushoshi
    "行政書士法",  # gyousei
    "社会保険労務士法",  # sharoushi
    "公認会計士法",  # kaikeishi
    "弁理士法",  # benrishi
    "労働基準法",  # 36協定 surface — labor standard act §36
)


# ---------------------------------------------------------------------------
# Step 3: Authentication — how smooth is jc_/OAuth/magic-link onboarding?
# ---------------------------------------------------------------------------
AUTH_SURFACES_REQUIRED = [
    SRC / "api" / "signup.py",
    SRC / "api" / "auth_google.py",
    SRC / "api" / "auth_github.py",
]
AUTH_DOCS_REQUIRED = [
    DOCS / "getting-started",
]


# ---------------------------------------------------------------------------
# Step 4: Execution — API completeness + typed error envelope
# ---------------------------------------------------------------------------
OPENAPI_PATHS_FLOOR = 180  # honest snapshot 2026-05-07; bump as surface grows
ERROR_ENVELOPE_REQUIRED = [
    SRC / "api" / "_error_envelope.py",
    SRC / "api" / "idempotency_context.py",
]


# ---------------------------------------------------------------------------
# Step 5: Recovery — agent self-correction
# ---------------------------------------------------------------------------
RECOVERY_REQUIRED_TOKENS = (
    "retry_after",
    "docs_url",
    "error_code",
)


# ---------------------------------------------------------------------------
# Step 6: Completion — success confirmation + idempotency
# ---------------------------------------------------------------------------
COMPLETION_REQUIRED_TOKENS = (
    "corpus_snapshot_id",
    "content_hash",
)


@dataclass
class StepScore:
    step: int
    name: str
    score: float
    findings: list[str] = field(default_factory=list)
    failure_patterns: list[str] = field(default_factory=list)


def _read(p: pathlib.Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    except IsADirectoryError:
        return ""


def _grep_repo(token: str, scopes: list[pathlib.Path]) -> int:
    """Recursive raw-text grep across given roots. Returns file-hit count."""
    hits = 0
    for root in scopes:
        if not root.exists():
            continue
        if root.is_file():
            if token in _read(root):
                hits += 1
            continue
        for p in root.rglob("*.py"):
            try:
                if token in p.read_text(encoding="utf-8", errors="replace"):
                    hits += 1
            except (OSError, UnicodeDecodeError):
                continue
        for p in root.rglob("*.json"):
            try:
                if token in p.read_text(encoding="utf-8", errors="replace"):
                    hits += 1
            except (OSError, UnicodeDecodeError):
                continue
        for p in root.rglob("*.md"):
            try:
                if token in p.read_text(encoding="utf-8", errors="replace"):
                    hits += 1
            except (OSError, UnicodeDecodeError):
                continue
    return hits


# ---------------------------------------------------------------------------
# Step scorers
# ---------------------------------------------------------------------------


def step1_discovery() -> StepScore:
    findings: list[str] = []
    failure: list[str] = []
    present = 0
    for p in DISCOVERY_REQUIRED:
        if p.exists() and p.stat().st_size > 0:
            present += 1
        else:
            failure.append(f"agent cannot locate jpcite via {p.relative_to(REPO_ROOT)}")
    presence_pts = (present / len(DISCOVERY_REQUIRED)) * 5.0
    findings.append(f"discovery surface presence: {present}/{len(DISCOVERY_REQUIRED)}")

    robots = _read(SITE / "robots.txt")
    welcomed = sum(1 for ua in AI_BOT_WELCOME_UAS if f"User-agent: {ua}" in robots)
    welcome_pts = (welcomed / len(AI_BOT_WELCOME_UAS)) * 2.5
    findings.append(f"AI bot welcome: {welcomed}/{len(AI_BOT_WELCOME_UAS)} UAs in robots.txt")
    if welcomed < len(AI_BOT_WELCOME_UAS):
        failure.append("robots.txt does not explicitly Allow all major AI crawlers")

    registry_hits = 0
    for hint in MCP_REGISTRY_HINTS:
        if _grep_repo(hint, [DOCS / "_internal", REPO_ROOT / "README.md"]):
            registry_hits += 1
    registry_pts = (registry_hits / len(MCP_REGISTRY_HINTS)) * 2.5
    findings.append(f"MCP registry visibility: {registry_hits}/{len(MCP_REGISTRY_HINTS)} hints")

    total = round(presence_pts + welcome_pts + registry_pts, 2)
    return StepScore(1, "discovery", min(10.0, total), findings, failure)


def step2_evaluation() -> StepScore:
    findings: list[str] = []
    failure: list[str] = []
    present = 0
    for p in EVALUATION_REQUIRED:
        # treat dir as present if any non-empty file lives inside
        if p.is_dir():
            files = [c for c in p.rglob("*.md") if c.is_file() and c.stat().st_size > 0]
            if files:
                present += 1
            else:
                failure.append(f"agent cannot evaluate fit: {p.relative_to(REPO_ROOT)} dir empty")
        elif p.exists() and p.stat().st_size > 0:
            present += 1
        else:
            failure.append(f"agent cannot evaluate fit: {p.relative_to(REPO_ROOT)} missing")
    presence_pts = (present / len(EVALUATION_REQUIRED)) * 5.0
    findings.append(f"evaluation docs presence: {present}/{len(EVALUATION_REQUIRED)}")

    fence_path = DATA / "fence_registry.json"
    fence_present = 0
    if fence_path.exists():
        try:
            fence_doc = json.loads(fence_path.read_text(encoding="utf-8"))
            fence_blob = json.dumps(fence_doc, ensure_ascii=False)
        except json.JSONDecodeError:
            fence_blob = ""
    else:
        fence_blob = ""
    for law in EIGHT_BUSINESS_LAW_FENCES:
        if law in fence_blob:
            fence_present += 1
        else:
            failure.append(f"fence_registry missing 8業法 entry: {law}")
    fence_pts = (fence_present / len(EIGHT_BUSINESS_LAW_FENCES)) * 3.0
    findings.append(f"8業法 fence coverage: {fence_present}/{len(EIGHT_BUSINESS_LAW_FENCES)}")

    recipe_dir = DOCS / "recipes"
    recipe_count = (
        sum(1 for p in recipe_dir.rglob("*.md") if p.stat().st_size > 0)
        if recipe_dir.exists()
        else 0
    )
    recipe_pts = min(2.0, recipe_count / 15.0)  # 30 recipes target → 2.0
    findings.append(f"recipes: {recipe_count} (target ≥ 30)")

    total = round(presence_pts + fence_pts + recipe_pts, 2)
    return StepScore(2, "evaluation", min(10.0, total), findings, failure)


def step3_authentication() -> StepScore:
    findings: list[str] = []
    failure: list[str] = []
    present = 0
    for p in AUTH_SURFACES_REQUIRED:
        if p.exists() and p.stat().st_size > 0:
            present += 1
        else:
            failure.append(f"missing auth surface: {p.relative_to(REPO_ROOT)}")
    surface_pts = (present / len(AUTH_SURFACES_REQUIRED)) * 4.0
    findings.append(f"auth surface files: {present}/{len(AUTH_SURFACES_REQUIRED)}")

    signup_src = _read(SRC / "api" / "signup.py")
    magic_link_seen = bool(re.search(r"magic[-_ ]?link", signup_src, re.IGNORECASE))
    jc_seen = "jc_" in signup_src or _grep_repo("jc_", [SRC / "api"]) > 0
    magic_pts = 2.0 if magic_link_seen else 0.0
    jc_pts = 2.0 if jc_seen else 0.0
    findings.append(f"magic-link flow detected: {magic_link_seen}")
    findings.append(f"jc_-prefixed token format detected: {jc_seen}")
    if not magic_link_seen:
        failure.append("agent cannot complete passwordless onboarding (no magic-link)")
    if not jc_seen:
        failure.append("agent token format unclear (no jc_ prefix in api/)")

    google_src = _read(SRC / "api" / "auth_google.py")
    github_src = _read(SRC / "api" / "auth_github.py")
    oauth_pts = 0.0
    if "redirect_uri" in google_src or "client_id" in google_src:
        oauth_pts += 1.0
    if "redirect_uri" in github_src or "client_id" in github_src:
        oauth_pts += 1.0
    findings.append(f"oauth surfaces wired (google + github): {oauth_pts}/2")

    total = round(surface_pts + magic_pts + jc_pts + oauth_pts, 2)
    return StepScore(3, "authentication", min(10.0, total), findings, failure)


def step4_execution() -> StepScore:
    findings: list[str] = []
    failure: list[str] = []
    # Canonical full spec; site/openapi.agent.json is the slim gpt30 profile.
    path_count = 0
    full_openapi = REPO_ROOT / "docs" / "openapi" / "v1.json"
    slim_openapi = SITE / "openapi.agent.json"
    slim_count = 0
    if full_openapi.exists():
        try:
            doc = json.loads(full_openapi.read_text(encoding="utf-8"))
            path_count = len(doc.get("paths") or {})
        except json.JSONDecodeError:
            failure.append("docs/openapi/v1.json failed to parse")
    else:
        failure.append("docs/openapi/v1.json missing")
    if slim_openapi.exists():
        try:
            slim_doc = json.loads(slim_openapi.read_text(encoding="utf-8"))
            slim_count = len(slim_doc.get("paths") or {})
        except json.JSONDecodeError:
            failure.append("site/openapi.agent.json failed to parse")
    else:
        failure.append("site/openapi.agent.json (slim gpt30 profile) missing")
    findings.append(
        f"openapi paths: full={path_count} slim_gpt30={slim_count} (floor {OPENAPI_PATHS_FLOOR})"
    )
    if path_count >= OPENAPI_PATHS_FLOOR:
        path_pts = 5.0
    else:
        path_pts = max(0.0, (path_count / OPENAPI_PATHS_FLOOR) * 5.0)
        failure.append(f"openapi path count below floor: {path_count} < {OPENAPI_PATHS_FLOOR}")

    envelope_present = 0
    for p in ERROR_ENVELOPE_REQUIRED:
        if p.exists() and p.stat().st_size > 0:
            envelope_present += 1
        else:
            failure.append(f"agent cannot execute reliably: {p.relative_to(REPO_ROOT)} missing")
    env_pts = (envelope_present / len(ERROR_ENVELOPE_REQUIRED)) * 3.0
    findings.append(
        f"error envelope + idempotency files: {envelope_present}/{len(ERROR_ENVELOPE_REQUIRED)}"
    )

    # Idempotency-Key header wired in middleware?
    idemp_hits = _grep_repo("Idempotency-Key", [SRC / "api"])
    idemp_pts = 2.0 if idemp_hits >= 1 else 0.0
    findings.append(f"Idempotency-Key references in api/: {idemp_hits}")
    if idemp_hits < 1:
        failure.append("Idempotency-Key header not honored in api/")

    total = round(path_pts + env_pts + idemp_pts, 2)
    return StepScore(4, "execution", min(10.0, total), findings, failure)


def step5_recovery() -> StepScore:
    findings: list[str] = []
    failure: list[str] = []
    # Each token weighted ~3.3 pts
    base_pts = 0.0
    for token in RECOVERY_REQUIRED_TOKENS:
        hits = _grep_repo(token, [SRC / "api", SRC / "mcp"])
        if hits >= 1:
            base_pts += 10.0 / len(RECOVERY_REQUIRED_TOKENS)
            findings.append(f"'{token}': {hits} file(s) in api/+mcp/")
        else:
            failure.append(f"agent cannot self-recover: '{token}' absent from api/+mcp/")
            findings.append(f"'{token}': 0 file(s) — recovery hint missing")

    # Step 5 rule from spec: each detected failure deducts 1 point.
    penalty = float(len(failure))
    score = max(0.0, base_pts - penalty)
    findings.append(f"failure-pattern penalty: -{penalty:.1f}")
    return StepScore(5, "recovery", round(score, 2), findings, failure)


def step6_completion() -> StepScore:
    findings: list[str] = []
    failure: list[str] = []
    base_pts = 0.0
    for token in COMPLETION_REQUIRED_TOKENS:
        hits = _grep_repo(token, [SRC / "api", SRC / "mcp", SRC / "models"])
        if hits >= 1:
            base_pts += 4.0
            findings.append(f"'{token}': {hits} file(s) in src/")
        else:
            failure.append(f"agent cannot verify completion: '{token}' absent from src/")
            findings.append(f"'{token}': 0 file(s) — completion proof missing")

    # idempotency_cache table is the durable proof. Bonus 2 pts if migration present.
    mig_hits = list((REPO_ROOT / "scripts" / "migrations").glob("*idempotency*.sql"))
    if mig_hits:
        base_pts += 2.0
        findings.append(f"idempotency_cache migration: {[p.name for p in mig_hits]}")
    else:
        failure.append("idempotency_cache migration not found in scripts/migrations/")

    # Step 5+ penalty rule applies to step 6 per task spec: -1 per failure.
    penalty = float(len(failure))
    score = max(0.0, base_pts - penalty)
    findings.append(f"failure-pattern penalty: -{penalty:.1f}")
    return StepScore(6, "completion", round(min(10.0, score), 2), findings, failure)


# ---------------------------------------------------------------------------
# Run + render
# ---------------------------------------------------------------------------


STEP_RUNNERS = (
    step1_discovery,
    step2_evaluation,
    step3_authentication,
    step4_execution,
    step5_recovery,
    step6_completion,
)


def run_audit() -> dict:
    scores = [fn() for fn in STEP_RUNNERS]
    avg = sum(s.score for s in scores) / len(scores)
    verdict = "green" if avg >= 8.5 else ("yellow" if avg >= 6.5 else "red")
    return {
        "audit": "agent_journey_6step",
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_score": round(avg, 2),
        "verdict": verdict,
        "steps": [
            {
                "step": s.step,
                "name": s.name,
                "score": s.score,
                "findings": s.findings,
                "failure_patterns": s.failure_patterns,
            }
            for s in scores
        ],
    }


def render_md(result: dict) -> str:
    lines = [
        f"# jpcite Agent Journey 6-Step Audit — {result['generated_at'][:10]}",
        "",
        "Wave 17 AX runner. ax_smart_guide §3.3 + §7. NO network, NO LLM call.",
        "",
        (f"**Overall**: {result['overall_score']:.2f} / 10 ({result['verdict'].upper()})"),
        "",
        "| step | name | score | failure patterns |",
        "| ---: | --- | ---: | ---: |",
    ]
    for s in result["steps"]:
        lines.append(
            f"| {s['step']} | {s['name']} | {s['score']:.2f} | {len(s['failure_patterns'])} |"
        )
    lines.append("")
    for s in result["steps"]:
        lines.extend(
            [
                f"## Step {s['step']}: {s['name']} — {s['score']:.2f} / 10",
                "",
                "### Findings",
                "",
            ]
        )
        if not s["findings"]:
            lines.append("- none")
        else:
            for f in s["findings"]:
                lines.append(f"- {f}")
        lines.extend(["", "### Failure patterns (agent-visible)", ""])
        if not s["failure_patterns"]:
            lines.append("- none")
        else:
            for fp in s["failure_patterns"]:
                lines.append(f"- {fp}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    today = datetime.now(UTC).strftime("%Y_%m_%d")
    default_md = REPO_ROOT / "docs" / "audit" / f"agent_journey_6step_audit_{today}.md"
    ap.add_argument(
        "--out",
        default=str(default_md),
        help="output markdown path",
    )
    ap.add_argument(
        "--out-json",
        default=None,
        help="optional json output path",
    )
    args = ap.parse_args(argv)

    result = run_audit()
    md = render_md(result)
    out_md = pathlib.Path(args.out)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md, encoding="utf-8")
    print(f"[agent_journey_audit] wrote {out_md}")
    if args.out_json:
        oj = pathlib.Path(args.out_json)
        oj.parent.mkdir(parents=True, exist_ok=True)
        oj.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[agent_journey_audit] wrote {oj}")
    print(f"[agent_journey_audit] overall = {result['overall_score']:.2f} ({result['verdict']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
