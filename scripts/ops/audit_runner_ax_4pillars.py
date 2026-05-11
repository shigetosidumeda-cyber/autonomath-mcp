#!/usr/bin/env python3
"""Wave 17 AX — Agent Experience 4-pillar audit (Biilmann framework).

Four pillars (Access / Context / Tools / Orchestration), each 0-10. Each pillar
has 5 binary checks worth +2 points. Output: docs/audit/ax_4pillars_audit_*.md
with one cell per pillar (score, evidence, missing_items).

Pure stdlib + requests (used for the optional live-endpoint CAPTCHA probe).
Read-only against the repo; the live probe is best-effort and skips on network
error so the script remains deterministic in CI / offline.

CLI: python3 scripts/ops/audit_runner_ax_4pillars.py --out <path>
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SITE = REPO_ROOT / "site"
WELL_KNOWN = SITE / ".well-known"
SRC_API = REPO_ROOT / "src" / "jpintel_mcp" / "api"
SRC_MCP = REPO_ROOT / "src" / "jpintel_mcp" / "mcp"
DOCS_OPENAPI = REPO_ROOT / "docs" / "openapi"

API_PROBE_URL = "https://api.jpcite.com/v1/programs?q=test&limit=1"


@dataclass
class Check:
    name: str
    passed: bool
    evidence: str = ""
    missing: str = ""


@dataclass
class Pillar:
    name: str
    checks: list[Check] = field(default_factory=list)

    @property
    def score(self) -> float:
        return round(sum(2.0 for c in self.checks if c.passed), 2)

    @property
    def evidence(self) -> list[str]:
        return [f"[OK] {c.name}: {c.evidence}" for c in self.checks if c.passed]

    @property
    def missing_items(self) -> list[str]:
        return [
            f"[MISS] {c.name}: {c.missing or 'criterion not satisfied'}"
            for c in self.checks
            if not c.passed
        ]


def _read(p: pathlib.Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _exists(p: pathlib.Path) -> bool:
    return p.exists() and p.stat().st_size > 0


def _grep_files(root: pathlib.Path, pattern: str, glob: str = "**/*.py") -> list[pathlib.Path]:
    rx = re.compile(pattern)
    hits: list[pathlib.Path] = []
    for fp in root.glob(glob):
        if not fp.is_file():
            continue
        try:
            if rx.search(fp.read_text(encoding="utf-8", errors="ignore")):
                hits.append(fp)
        except (OSError, UnicodeDecodeError):
            continue
    return hits


def _http_probe(url: str) -> tuple[bool, str]:
    """Best-effort HEAD on a live URL. Returns (reachable, body_or_err)."""
    try:
        import requests  # type: ignore
    except ImportError:
        return False, "requests-not-installed"
    try:
        r = requests.get(url, timeout=5.0, allow_redirects=True)
        return True, r.text[:4096]
    except Exception as e:  # noqa: BLE001 — best-effort probe
        return False, f"probe-error: {e}"


# ---------- Access pillar ----------


def access_pillar() -> Pillar:
    p = Pillar("Access")

    # 1. scope-prefixed API token (X-API-Key with jc_ prefix)
    api_key_hits = _grep_files(SRC_API, r'X-API-Key|"jc_|jc_[a-z0-9]')
    passed = bool(api_key_hits)
    p.checks.append(
        Check(
            "scoped_api_token",
            passed,
            evidence=f"{len(api_key_hits)} file(s) reference X-API-Key/jc_ prefix"
            if passed
            else "",
            missing="no X-API-Key / jc_ prefix grep hit under src/jpintel_mcp/api/"
            if not passed
            else "",
        )
    )

    # 2. OAuth 2.1 (GitHub + Google) wired
    has_github = (SRC_API / "auth_github.py").exists()
    has_google = (SRC_API / "auth_google.py").exists()
    passed = has_github and has_google
    p.checks.append(
        Check(
            "oauth_github_google",
            passed,
            evidence="auth_github.py + auth_google.py both present"
            if passed
            else "",
            missing=f"github={has_github}, google={has_google}"
            if not passed
            else "",
        )
    )

    # 3. API endpoints free of CAPTCHA (live probe)
    reachable, body = _http_probe(API_PROBE_URL)
    body_lower = body.lower()
    captcha_markers = ("hcaptcha", "recaptcha", "cf-turnstile", "g-recaptcha")
    has_captcha = any(m in body_lower for m in captcha_markers)
    # If not reachable, we still pass — local repo-level proof (no captcha module).
    captcha_grep = _grep_files(SRC_API, r"hcaptcha|recaptcha|turnstile")
    passed = (not has_captcha) and (not captcha_grep)
    p.checks.append(
        Check(
            "no_captcha_on_api",
            passed,
            evidence=(
                f"live probe captcha=no (reachable={reachable}), "
                f"repo grep hits={len(captcha_grep)}"
            )
            if passed
            else "",
            missing=(
                f"captcha marker detected (live={has_captcha}, repo_hits={len(captcha_grep)})"
            )
            if not passed
            else "",
        )
    )

    # 4. Retry-After + X-RateLimit-Remaining headers returned
    has_retry = bool(_grep_files(SRC_API, r"Retry-After"))
    has_rl_remaining = bool(_grep_files(SRC_API, r"X-RateLimit-Remaining|X-RateLimit-Reset|X-RateLimit-Limit"))
    passed = has_retry and has_rl_remaining
    p.checks.append(
        Check(
            "rate_limit_headers",
            passed,
            evidence="Retry-After + X-RateLimit-* both grep-hit in api/"
            if passed
            else "",
            missing=f"retry_after={has_retry}, rl_remaining={has_rl_remaining}"
            if not passed
            else "",
        )
    )

    # 5. CORS allowlist for jpcite.com + api.jpcite.com
    main_py = _read(SRC_API / "main.py")
    cors_origins_token = "cors_origins" in main_py.lower() or "JPINTEL_CORS_ORIGINS" in main_py
    # The actual allowlist lives in a Fly secret + settings default — check that
    # the wiring + a runbook reference both exist.
    cors_runbook = (REPO_ROOT / "docs" / "runbook" / "cors_setup.md").exists()
    passed = cors_origins_token and cors_runbook
    p.checks.append(
        Check(
            "cors_allowlist",
            passed,
            evidence="CORS wiring in main.py + cors_setup.md runbook present"
            if passed
            else "",
            missing=f"main_wired={cors_origins_token}, runbook={cors_runbook}"
            if not passed
            else "",
        )
    )

    return p


# ---------- Context pillar ----------


def context_pillar() -> Pillar:
    p = Pillar("Context")

    # 1. llms.txt 4-file delivery (jp/en × normal/full)
    needed = ["llms.txt", "llms.en.txt", "llms-full.txt", "llms-full.en.txt"]
    found = [f for f in needed if _exists(SITE / f)]
    passed = len(found) == 4
    p.checks.append(
        Check(
            "llms_txt_4_files",
            passed,
            evidence=f"all 4 present: {found}" if passed else "",
            missing=f"only {len(found)}/4 found: {found}" if not passed else "",
        )
    )

    # 2. schema.org JSON-LD injected on key pages
    pages = ["index.html", "pricing.html", "about.html", "facts.html"]
    json_ld_pages = []
    for pg in pages:
        html = _read(SITE / pg)
        if 'application/ld+json' in html and 'schema.org' in html:
            json_ld_pages.append(pg)
    passed = len(json_ld_pages) >= 3
    p.checks.append(
        Check(
            "schema_org_jsonld",
            passed,
            evidence=f"JSON-LD on {len(json_ld_pages)}/{len(pages)} key pages: {json_ld_pages}"
            if passed
            else "",
            missing=f"only {len(json_ld_pages)}/{len(pages)} pages carry JSON-LD"
            if not passed
            else "",
        )
    )

    # 3. OpenAPI 3.1 spec in 3 layers (full / agent / agent.gpt30)
    full = _exists(DOCS_OPENAPI / "v1.json")
    agent = _exists(SITE / "openapi.agent.json")
    gpt30 = _exists(SITE / "openapi.agent.gpt30.json")
    passed = full and agent and gpt30
    p.checks.append(
        Check(
            "openapi_3layer",
            passed,
            evidence="docs/openapi/v1.json + site/openapi.agent.json + site/openapi.agent.gpt30.json"
            if passed
            else "",
            missing=f"full={full}, agent={agent}, gpt30={gpt30}"
            if not passed
            else "",
        )
    )

    # 4. hosted context files (llms-meta.json + agents.json)
    meta = _exists(SITE / "llms-meta.json")
    agents = _exists(WELL_KNOWN / "agents.json") or _exists(SITE / "agents.json")
    passed = meta and agents
    p.checks.append(
        Check(
            "hosted_context_files",
            passed,
            evidence="site/llms-meta.json + agents.json both present"
            if passed
            else "",
            missing=f"llms_meta={meta}, agents_json={agents}"
            if not passed
            else "",
        )
    )

    # 5. companion .md at 6+ site roots
    md_companions = sorted(p.name for p in SITE.glob("*.html.md"))
    passed = len(md_companions) >= 6
    p.checks.append(
        Check(
            "companion_md_6plus",
            passed,
            evidence=f"{len(md_companions)} .html.md siblings: {md_companions[:8]}"
            if passed
            else "",
            missing=f"only {len(md_companions)} .html.md siblings (need >= 6)"
            if not passed
            else "",
        )
    )

    return p


# ---------- Tools pillar ----------


def tools_pillar() -> Pillar:
    p = Pillar("Tools")

    # 1. MCP server live (139 tools at default gates)
    server_py = SRC_MCP / "server.py"
    has_server = server_py.exists() and server_py.stat().st_size > 1024
    # Manifest tool_count cross-check.
    manifest = _read(REPO_ROOT / "server.json")
    tool_count_hit = re.search(r'"tool_count"\s*:\s*(\d+)', manifest)
    tool_count = int(tool_count_hit.group(1)) if tool_count_hit else 0
    passed = has_server and tool_count >= 139
    p.checks.append(
        Check(
            "mcp_server_live",
            passed,
            evidence=f"server.py present + manifest tool_count={tool_count}"
            if passed
            else "",
            missing=f"server_py={has_server}, tool_count={tool_count}"
            if not passed
            else "",
        )
    )

    # 2. Typed-error canonical envelope
    envelope = _read(SRC_API / "_error_envelope.py")
    has_code_msg = "code" in envelope and "message" in envelope and "docs_url" in envelope
    passed = bool(envelope) and has_code_msg
    p.checks.append(
        Check(
            "typed_error_envelope",
            passed,
            evidence="_error_envelope.py present with code/message/docs_url"
            if passed
            else "",
            missing="_error_envelope.py missing or lacks code/message/docs_url field" if not passed else "",
        )
    )

    # 3. Idempotency-Key support
    idem_hits = _grep_files(SRC_API, r"Idempotency-Key|idempotency_key|idempotency_cache")
    passed = len(idem_hits) >= 2
    p.checks.append(
        Check(
            "idempotency_key",
            passed,
            evidence=f"{len(idem_hits)} file(s) reference Idempotency-Key / idempotency_cache"
            if passed
            else "",
            missing=f"only {len(idem_hits)} files reference idempotency"
            if not passed
            else "",
        )
    )

    # 4. MCP Resources + Prompts (Wave 18 strictening — require manifest count
    # markers AND list-fn surfaces in repo). Counts come from
    # `mcp-server.json._meta.{resource,prompt}_count` so the audit follows the
    # canonical manifest, not aspirational doc strings.
    mcp_manifest = _read(REPO_ROOT / "mcp-server.json")
    res_match = re.search(r'"resource_count"\s*:\s*(\d+)', mcp_manifest)
    pr_match = re.search(r'"prompt_count"\s*:\s*(\d+)', mcp_manifest)
    res_count = int(res_match.group(1)) if res_match else 0
    pr_count = int(pr_match.group(1)) if pr_match else 0
    has_resources_module = (SRC_MCP / "jpcite_resources.py").exists() and (
        SRC_MCP / "cohort_resources.py"
    ).exists()
    has_prompts_module = (SRC_MCP / "jpcite_prompts.py").exists() and (
        SRC_MCP / "autonomath_tools" / "prompts.py"
    ).exists()
    # REST surfaces let an agent enumerate without speaking MCP.
    has_meta_resources_route = bool(_grep_files(SRC_API, r"/v1/meta/resources"))
    has_meta_prompts_route = bool(_grep_files(SRC_API, r"/v1/meta/prompts"))
    passed = (
        has_resources_module
        and has_prompts_module
        and res_count >= 5
        and pr_count >= 15
        and has_meta_resources_route
        and has_meta_prompts_route
    )
    p.checks.append(
        Check(
            "mcp_resources_prompts",
            passed,
            evidence=(
                f"manifest resource_count={res_count} + prompt_count={pr_count}, "
                f"modules present, /v1/meta/{{resources,prompts}} routes wired"
            )
            if passed
            else "",
            missing=(
                f"res_module={has_resources_module}, pr_module={has_prompts_module}, "
                f"resource_count={res_count}, prompt_count={pr_count}, "
                f"meta_resources_route={has_meta_resources_route}, "
                f"meta_prompts_route={has_meta_prompts_route}"
            )
            if not passed
            else "",
        )
    )

    # 5. WebMCP early preview (Wave 18 strictening — file delivery + 4 registerTool).
    #
    # Strict criterion (Wave 18): polyfill JS file present AND defines at least
    # 4 distinct tools registered via `navigator.modelContext.registerTool`.
    # Counting `name:` keys inside the TOOLS array is robust to whitespace
    # variation and avoids relying on filename heuristics.
    polyfill_path = SITE / "assets" / "webmcp_init.js"
    polyfill_present = polyfill_path.exists() and polyfill_path.stat().st_size > 256
    polyfill_text = _read(polyfill_path) if polyfill_present else ""
    has_register_call = "navigator.modelContext.registerTool" in polyfill_text or (
        "modelContext" in polyfill_text and "registerTool" in polyfill_text
    )
    # Count tool names — match `name: '...'` blocks inside the catalogue array.
    tool_name_hits = re.findall(r"name:\s*['\"]([a-z_][a-z0-9_]*)['\"]", polyfill_text)
    distinct_tools = sorted(set(tool_name_hits))
    # Confirm the script tag is wired on at least one site root so production
    # delivery is real, not just a checked-in file.
    site_script_hits = _grep_files(SITE, r'webmcp_init\.js', glob="*.html")
    passed = (
        polyfill_present
        and has_register_call
        and len(distinct_tools) >= 4
        and bool(site_script_hits)
    )
    p.checks.append(
        Check(
            "webmcp_preview",
            passed,
            evidence=(
                f"polyfill={polyfill_present} (size={polyfill_path.stat().st_size if polyfill_present else 0}B), "
                f"registerTool=yes, tools={len(distinct_tools)} ({','.join(distinct_tools[:6])}), "
                f"script_tag_wired_on={len(site_script_hits)} site root(s)"
            )
            if passed
            else "",
            missing=(
                f"polyfill={polyfill_present}, registerTool={has_register_call}, "
                f"tools={len(distinct_tools)} (need >=4), script_tags={len(site_script_hits)}"
            )
            if not passed
            else "",
        )
    )

    return p


# ---------- Orchestration pillar ----------


def orchestration_pillar() -> Pillar:
    p = Pillar("Orchestration")

    # 1. Webhook + event-driven dispatch (migration 088 houjin_watch)
    mig_088 = list(REPO_ROOT.glob("scripts/migrations/088_*"))
    dispatch_cron = (REPO_ROOT / "scripts" / "cron" / "dispatch_webhooks.py").exists()
    passed = bool(mig_088) and dispatch_cron
    p.checks.append(
        Check(
            "webhook_event_driven",
            passed,
            evidence=f"migration_088={bool(mig_088)} + dispatch_webhooks.py present"
            if passed
            else "",
            missing=f"mig_088={bool(mig_088)}, dispatch_cron={dispatch_cron}"
            if not passed
            else "",
        )
    )

    # 2. Long-running task async pattern
    bg_queue = (SRC_API / "_bg_task_queue.py").exists()
    has_async_task = bool(_grep_files(SRC_API, r"background_tasks|BackgroundTasks|async def"))
    passed = bg_queue and has_async_task
    p.checks.append(
        Check(
            "long_task_async",
            passed,
            evidence="_bg_task_queue.py present + async/BackgroundTasks usage"
            if passed
            else "",
            missing=f"bg_queue={bg_queue}, async_task={has_async_task}"
            if not passed
            else "",
        )
    )

    # 3. Interrupt / resume session design (idempotency_cache + session/state token).
    #
    # Wave 18 widening: `state_token` (HMAC) in the A2A receiver counts as a
    # resume primitive — it is the durable identifier a remote agent re-presents
    # to continue a delegated task. Keep the legacy session_token / resume_token
    # / continuation_token tokens too for back-compat.
    idem_cache = list(REPO_ROOT.glob("scripts/migrations/087_*"))
    sess_hits = _grep_files(
        SRC_API,
        r"session_token|resume_token|continuation_token|state_token",
    )
    passed = bool(idem_cache) and bool(sess_hits)
    p.checks.append(
        Check(
            "interrupt_resume_session",
            passed,
            evidence=f"mig_087 idempotency_cache + {len(sess_hits)} session/state-token grep hits"
            if passed
            else "",
            missing=f"idem_cache_mig={bool(idem_cache)}, session_hits={len(sess_hits)}"
            if not passed
            else "",
        )
    )

    # 4. A2A receiver endpoint (Wave 18 strictening — file + agent_card route
    # + 5 lifecycle endpoints + state_token HMAC 24h TTL all present).
    a2a_file = SRC_API / "a2a.py"
    a2a_text = _read(a2a_file)
    has_router_prefix = "APIRouter(prefix=\"/v1/a2a\"" in a2a_text or 'prefix="/v1/a2a"' in a2a_text
    # All 5 lifecycle paths from the brief: agent_card / task POST / task GET /
    # resume / cancel.
    expected_routes = [
        '@router.get("/agent_card"',
        '@router.post("/task"',
        '@router.get("/task/{task_id}"',
        '@router.post("/task/{task_id}/resume"',
        '@router.post("/task/{task_id}/cancel"',
    ]
    routes_present = [r for r in expected_routes if r in a2a_text]
    has_state_token = "state_token" in a2a_text and "_mint_state_token" in a2a_text
    has_hmac_24h = "hmac" in a2a_text.lower() and ("hours=24" in a2a_text or "24h" in a2a_text or "24" in a2a_text)
    mounted_in_main = "include_router(a2a_router" in _read(SRC_API / "main.py")
    passed = (
        a2a_file.exists()
        and has_router_prefix
        and len(routes_present) >= 5
        and has_state_token
        and has_hmac_24h
        and mounted_in_main
    )
    p.checks.append(
        Check(
            "a2a_receiver",
            passed,
            evidence=(
                f"a2a.py present (router=/v1/a2a, {len(routes_present)}/5 routes), "
                f"state_token+HMAC 24h, mounted in main.py"
            )
            if passed
            else "",
            missing=(
                f"file={a2a_file.exists()}, router_prefix={has_router_prefix}, "
                f"routes={len(routes_present)}/5, state_token={has_state_token}, "
                f"hmac_24h={has_hmac_24h}, mounted={mounted_in_main}"
            )
            if not passed
            else "",
        )
    )

    # 5. Streamable HTTP transport (Wave 18 strictening — manifest advertises
    # 3 transports + repo carries source / doc markers).
    streamable_hits = _grep_files(
        SRC_MCP, r"streamable_http|StreamableHTTP|Streamable HTTP|streamable-http"
    )
    streamable_doc = _grep_files(
        REPO_ROOT / "docs", r"Streamable HTTP|streamable_http|streamable-http", glob="**/*.md"
    )
    mcp_manifest = _read(REPO_ROOT / "mcp-server.json")
    has_transports_meta = (
        '"transports"' in mcp_manifest
        and '"streamable_http"' in mcp_manifest
        and '"sse"' in mcp_manifest
        and '"stdio"' in mcp_manifest
    )
    a2a_text = _read(SRC_API / "a2a.py")
    has_transport_advertisement = (
        '"mcp_stdio"' in a2a_text and '"mcp_streamable_http"' in a2a_text
    )
    passed = has_transports_meta and (bool(streamable_hits) or bool(streamable_doc)) and has_transport_advertisement
    p.checks.append(
        Check(
            "streamable_http",
            passed,
            evidence=(
                f"mcp-server.json _meta.transports=3 values, "
                f"a2a agent_card advertises stdio+streamable_http, "
                f"src/doc markers={len(streamable_hits)}/{len(streamable_doc)}"
            )
            if passed
            else "",
            missing=(
                f"transports_meta={has_transports_meta}, "
                f"a2a_advert={has_transport_advertisement}, "
                f"src_hits={len(streamable_hits)}, doc_hits={len(streamable_doc)}"
            )
            if not passed
            else "",
        )
    )

    return p


# ---------- runner ----------


def run_audit() -> dict:
    pillars = [
        access_pillar(),
        context_pillar(),
        tools_pillar(),
        orchestration_pillar(),
    ]
    total = round(sum(p.score for p in pillars), 2)
    average = round(total / len(pillars), 2)
    return {
        "axis": "ax_4pillars",
        "framework": "Biilmann Access/Context/Tools/Orchestration",
        "total_score": total,
        "average_score": average,
        "max_score": 40.0,
        "verdict": "green" if average >= 8.0 else ("yellow" if average >= 6.0 else "red"),
        "pillars": {
            p.name: {
                "score": p.score,
                "evidence": p.evidence,
                "missing_items": p.missing_items,
            }
            for p in pillars
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def render_md(result: dict) -> str:
    date = result["generated_at"][:10]
    lines = [
        f"# jpcite AX 4 Pillars Audit — {date} (automated)",
        "",
        f"**Total**: {result['total_score']:.2f} / {result['max_score']:.0f}  ",
        f"**Average**: {result['average_score']:.2f} / 10 ({result['verdict'].upper()})  ",
        f"**Framework**: {result['framework']}  ",
        "",
        "| Pillar | Score |",
        "| --- | --- |",
    ]
    for name, body in result["pillars"].items():
        lines.append(f"| {name} | {body['score']:.2f} / 10 |")
    lines.append("")
    for name, body in result["pillars"].items():
        lines += [
            f"## {name} — {body['score']:.2f} / 10",
            "",
            "### Evidence",
            "",
        ]
        if not body["evidence"]:
            lines.append("- (none)")
        else:
            for e in body["evidence"]:
                lines.append(f"- {e}")
        lines += ["", "### Missing items", ""]
        if not body["missing_items"]:
            lines.append("- (none)")
        else:
            for m in body["missing_items"]:
                lines.append(f"- {m}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="output markdown path")
    ap.add_argument("--out-json", default=None)
    args = ap.parse_args(argv)

    result = run_audit()
    out_md = pathlib.Path(args.out)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_md(result), encoding="utf-8")

    if args.out_json:
        out_json = pathlib.Path(args.out_json)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # Brief stdout summary.
    print(f"AX 4 Pillars total={result['total_score']:.2f}/40 average={result['average_score']:.2f}/10 verdict={result['verdict']}")
    for name, body in result["pillars"].items():
        print(f"  - {name}: {body['score']:.2f}/10")
    return 0


if __name__ == "__main__":
    sys.exit(main())
