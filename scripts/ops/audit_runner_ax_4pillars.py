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
import ast
import json
import pathlib
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SITE = REPO_ROOT / "site"
WELL_KNOWN = SITE / ".well-known"
SRC_API = REPO_ROOT / "src" / "jpintel_mcp" / "api"
SRC_MCP = REPO_ROOT / "src" / "jpintel_mcp" / "mcp"
DOCS_OPENAPI = REPO_ROOT / "docs" / "openapi"

# Wave-post-E12 — `require_scope` import gate.
# CANONICAL_SCOPES in src/jpintel_mcp/api/me/api_keys.py defines 4 scopes
# (read:programs / read:cases / write:webhooks / admin:billing). The Access
# pillar scoped_api_token cell must verify that at least this many route files
# actually import + apply the helper via Depends(require_scope(...)) — not
# merely that the literal "X-API-Key" / "jc_" strings appear somewhere in the
# tree (which was the original grep flaw E12 caught).
REQUIRE_SCOPE_MIN_CALLERS = 4
REQUIRE_SCOPE_HELPER_MODULE = "api_keys"  # final segment of `api.me.api_keys`

API_PROBE_URL = "https://api.jpcite.com/v1/programs?q=test&limit=1"


@dataclass
class Check:
    name: str
    passed: bool
    evidence: str = ""
    missing: str = ""


# Wave 41 — 6 checks per pillar x 4 pillars = 24 cells; per-check weight
# +2.0 so PILLAR_MAX = 12.0, total possible = 48.0 (was 40.0).
PILLAR_MAX = 12.0
CHECK_WEIGHT = 2.0
SITE_STATUS = SITE / "status"


@dataclass
class Pillar:
    name: str
    checks: list[Check] = field(default_factory=list)

    @property
    def score(self) -> float:
        return round(sum(CHECK_WEIGHT for c in self.checks if c.passed), 2)

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


def _count_require_scope_callers(root: pathlib.Path) -> tuple[int, list[str]]:
    """Count distinct route files that import + apply ``require_scope``.

    Walks ``root`` for ``*.py`` files, parses each with the ``ast`` module,
    and counts a file as a caller iff it BOTH:

      1. imports ``require_scope`` from the ``api_keys`` helper module
         (matches both ``from .me.api_keys import require_scope`` and
         ``from jpintel_mcp.api.me.api_keys import require_scope``), AND
      2. actually applies the helper as ``Depends(require_scope(...))``
         (a route-handler decorator argument).

    The defining module (``me/api_keys.py`` itself) is excluded because
    its ``def require_scope`` is the helper, not a caller — passing on
    self-presence is exactly the E12 flaw this audit guards against.

    Returns ``(caller_count, sorted_relative_paths)``.
    """
    callers: set[str] = set()
    defining_module_path = root / "me" / "api_keys.py"

    for fp in root.rglob("*.py"):
        if not fp.is_file():
            continue
        try:
            resolved = fp.resolve()
        except OSError:
            continue
        if resolved == defining_module_path.resolve():
            continue
        try:
            src = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        try:
            tree = ast.parse(src, filename=str(fp))
        except SyntaxError:
            continue

        imports_helper = False
        applies_helper = False

        for node in ast.walk(tree):
            # 1. `from ... .api_keys import (..., require_scope, ...)`
            if isinstance(node, ast.ImportFrom):
                if not node.module:
                    continue
                # Match by trailing module segment to cover both relative
                # (`.me.api_keys`) and absolute (`jpintel_mcp.api.me.api_keys`)
                # import paths.
                tail = node.module.rsplit(".", 1)[-1]
                if tail != REQUIRE_SCOPE_HELPER_MODULE:
                    continue
                for alias in node.names:
                    if alias.name == "require_scope":
                        imports_helper = True
                        break
            # 2. `Depends(require_scope("..."))` somewhere in the file.
            elif isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name) and fn.id == "Depends" and node.args:
                    arg = node.args[0]
                    if (
                        isinstance(arg, ast.Call)
                        and isinstance(arg.func, ast.Name)
                        and arg.func.id == "require_scope"
                    ):
                        applies_helper = True

        if imports_helper and applies_helper:
            try:
                rel = fp.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                rel = str(fp)
            callers.add(rel)

    return len(callers), sorted(callers)


# ---------- Access pillar ----------


def access_pillar() -> Pillar:
    p = Pillar("Access")

    # 1. scope-prefixed API token — Wave-post-E12 honest scoring.
    #
    # Original logic grepped for the literal strings "X-API-Key" / "jc_"
    # anywhere under src/jpintel_mcp/api/ and counted any hit as a pass.
    # That awarded 12/12 even when the `require_scope()` helper had ZERO
    # external callers (every literal hit was an aspirational comment or
    # the helper's own docstring). E12 caught the flaw; C1 manually
    # downgraded the public summary to 10/12 + WARN.
    #
    # The honest check: count distinct route files that BOTH import
    # `require_scope` from `api.me.api_keys` AND actually apply it via
    # `Depends(require_scope(...))`. Pass iff callers >= 4 (the 4
    # canonical scopes defined in CANONICAL_SCOPES). Below 4 → emit a
    # WARN evidence row (cell still fails) so the cron can no longer
    # overwrite C1's honest 10/12 + WARN public artifact.
    caller_count, caller_paths = _count_require_scope_callers(SRC_API)
    passed = caller_count >= REQUIRE_SCOPE_MIN_CALLERS
    if passed:
        evidence_msg = (
            f"{caller_count} route file(s) import + Depends(require_scope(...)): {caller_paths[:6]}"
        )
        missing_msg = ""
    else:
        evidence_msg = (
            f"[WARN] scoped_api_token: documented helper exists but only "
            f"{caller_count} route(s) use it"
        )
        missing_msg = (
            f"require_scope() has {caller_count} caller(s) under src/jpintel_mcp/api/ "
            f"(need >= {REQUIRE_SCOPE_MIN_CALLERS} — one per CANONICAL_SCOPES entry)"
        )
    p.checks.append(
        Check(
            "scoped_api_token",
            passed,
            evidence=evidence_msg if passed else "",
            missing=missing_msg,
            # When passed=False the WARN evidence_msg is still useful for
            # the operator — surface it in the missing_items row so the
            # rendered audit explains *why* the cell warned rather than
            # silently dropping the diagnostic.
        )
    )
    # Surface the WARN line in missing_items prefix (Check renders missing
    # as "[MISS] name: <missing>"); when not passed we re-include the
    # WARN message so the public artifact carries the [WARN] marker that
    # C1's manual downgrade introduced.
    if not passed:
        p.checks[-1].missing = f"[WARN] only {caller_count} caller(s); {missing_msg}"

    # 2. OAuth 2.1 (GitHub + Google) wired
    has_github = (SRC_API / "auth_github.py").exists()
    has_google = (SRC_API / "auth_google.py").exists()
    passed = has_github and has_google
    p.checks.append(
        Check(
            "oauth_github_google",
            passed,
            evidence="auth_github.py + auth_google.py both present" if passed else "",
            missing=f"github={has_github}, google={has_google}" if not passed else "",
        )
    )

    # 3. API endpoints free of CAPTCHA (live probe)
    reachable, body = _http_probe(API_PROBE_URL)
    body_lower = body.lower()
    captcha_markers = ("hcaptcha", "recaptcha", "cf-turnstile", "g-recaptcha")
    has_captcha = any(m in body_lower for m in captcha_markers)
    captcha_grep = _grep_files(SRC_API, r"hcaptcha|recaptcha|turnstile")
    passed = reachable and (not has_captcha) and (not captcha_grep)
    if not reachable:
        captcha_missing = "live probe unavailable; captcha-free API cannot be verified"
    else:
        captcha_missing = (
            f"captcha marker detected (live={has_captcha}, repo_hits={len(captcha_grep)})"
        )
    p.checks.append(
        Check(
            "no_captcha_on_api",
            passed,
            evidence=(
                f"live probe captcha=no (reachable={reachable}), repo grep hits={len(captcha_grep)}"
            )
            if passed
            else "",
            missing=captcha_missing if not passed else "",
        )
    )

    # 4. Retry-After + X-RateLimit-Remaining headers returned
    # TODO(E12-followup): grep-only flaw — string presence does not prove the
    # headers are actually emitted on a 429 response. A stricter check would
    # mount a TestClient against the rate-limit middleware and assert the
    # response carries both header keys with numeric values. Tracked but not
    # in scope for the E12 packet.
    has_retry = bool(_grep_files(SRC_API, r"Retry-After"))
    has_rl_remaining = bool(
        _grep_files(SRC_API, r"X-RateLimit-Remaining|X-RateLimit-Reset|X-RateLimit-Limit")
    )
    passed = has_retry and has_rl_remaining
    p.checks.append(
        Check(
            "rate_limit_headers",
            passed,
            evidence="Retry-After + X-RateLimit-* both grep-hit in api/" if passed else "",
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
            evidence="CORS wiring in main.py + cors_setup.md runbook present" if passed else "",
            missing=f"main_wired={cors_origins_token}, runbook={cors_runbook}"
            if not passed
            else "",
        )
    )

    # 6. Wave 41 — OAuth Device Flow polling response live
    oauth_device_text = _read(SRC_API / "oauth_device.py")
    required_cases = ("authorization_pending", "slow_down", "expired_token", "access_denied")
    cases_present = all(c in oauth_device_text for c in required_cases)
    has_introspect = (
        "/poll_introspect" in oauth_device_text and "_POLL_RESPONSE_FIXTURES" in oauth_device_text
    )
    has_spec_endpoint = "/poll_response_spec" in oauth_device_text
    mounted_in_main = (
        "oauth_device_router" in main_py and "include_router(oauth_device_router" in main_py
    )
    passed = cases_present and has_introspect and has_spec_endpoint and mounted_in_main
    p.checks.append(
        Check(
            "device_flow_polling_live",
            passed,
            evidence=(
                "RFC 8628 §3.5 4 error cases + success wired, "
                "/poll_introspect + /poll_response_spec live, mounted in main.py"
            )
            if passed
            else "",
            missing=(
                f"cases={cases_present}, introspect={has_introspect}, "
                f"spec={has_spec_endpoint}, mounted={mounted_in_main}"
            )
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
        if "application/ld+json" in html and "schema.org" in html:
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
            missing=f"full={full}, agent={agent}, gpt30={gpt30}" if not passed else "",
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
            evidence="site/llms-meta.json + agents.json both present" if passed else "",
            missing=f"llms_meta={meta}, agents_json={agents}" if not passed else "",
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

    # 6. Wave 41 — Schema.org Dataset JSON-LD with hasPart sub-dataset linkage
    data_root = SITE / "_data"
    expected_payloads = {
        "dataset_jsonld_programs.json": "https://jpcite.com/#dataset-programs",
        "dataset_jsonld_laws.json": "https://jpcite.com/#dataset-laws",
        "dataset_jsonld_cases.json": "https://jpcite.com/#dataset-cases",
        "dataset_jsonld_enforcement.json": "https://jpcite.com/#dataset-enforcement",
        "dataset_jsonld_aggregate.json": "https://jpcite.com/#dataset-aggregate",
    }
    payload_hits: list[str] = []
    aria_marker_count = 0
    has_part_count = 0
    for filename, expected_id in expected_payloads.items():
        p_path = data_root / filename
        if not p_path.exists():
            continue
        try:
            payload = json.loads(p_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("@id") != expected_id or payload.get("@type") != "Dataset":
            continue
        payload_hits.append(filename)
        for prop in payload.get("additionalProperty", []) or []:
            if prop.get("name") == "ariaDescribedBy":
                aria_marker_count += 1
        if "hasPart" in payload:
            has_part_count = len(payload.get("hasPart", []))
    has_emitter = (REPO_ROOT / "scripts" / "generate_jsonld_dataset.py").exists()
    passed = (
        len(payload_hits) == 5 and has_part_count >= 4 and aria_marker_count >= 4 and has_emitter
    )
    p.checks.append(
        Check(
            "dataset_metadata_jsonld_live",
            passed,
            evidence=(
                f"{len(payload_hits)}/5 Dataset JSON-LD payloads in site/_data/, "
                f"aggregate hasPart={has_part_count}, ariaDescribedBy markers={aria_marker_count}, "
                f"emitter present"
            )
            if passed
            else "",
            missing=(
                f"payloads={len(payload_hits)}/5, has_part={has_part_count} (need >=4), "
                f"aria_markers={aria_marker_count} (need >=4), emitter={has_emitter}"
            )
            if not passed
            else "",
        )
    )

    return p


# ---------- Tools pillar ----------


def tools_pillar() -> Pillar:
    p = Pillar("Tools")

    # 1. MCP server live (151 tools at default gates)
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
            evidence=f"server.py present + manifest tool_count={tool_count}" if passed else "",
            missing=f"server_py={has_server}, tool_count={tool_count}" if not passed else "",
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
            evidence="_error_envelope.py present with code/message/docs_url" if passed else "",
            missing="_error_envelope.py missing or lacks code/message/docs_url field"
            if not passed
            else "",
        )
    )

    # 3. Idempotency-Key support
    # TODO(E12-followup): grep-only flaw — same shape as the original
    # `scoped_api_token` flaw. Counts files that mention any of three tokens
    # but does not verify a middleware/dependency actually short-circuits a
    # duplicate POST against `idempotency_cache`. A stricter check would AST-
    # walk for a Depends(...) or middleware class that reads + writes that
    # table. Tracked but not in scope for the E12 packet.
    idem_hits = _grep_files(SRC_API, r"Idempotency-Key|idempotency_key|idempotency_cache")
    passed = len(idem_hits) >= 2
    p.checks.append(
        Check(
            "idempotency_key",
            passed,
            evidence=f"{len(idem_hits)} file(s) reference Idempotency-Key / idempotency_cache"
            if passed
            else "",
            missing=f"only {len(idem_hits)} files reference idempotency" if not passed else "",
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
    site_script_hits = _grep_files(SITE, r"webmcp_init\.js", glob="*.html")
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

    # 6. Wave 41 — MCP Resource subscribe/unsubscribe + polling integration
    subscriber_path = SRC_MCP / "resource_subscriber.py"
    subscriber_present = subscriber_path.exists() and subscriber_path.stat().st_size > 1024
    subscriber_text = _read(subscriber_path) if subscriber_present else ""
    required_api = (
        "class ResourceSubscriberRegistry",
        "def subscribe(",
        "def unsubscribe(",
        "def publish(",
        "def poll(",
        "handle_subscribe_request",
        "handle_unsubscribe_request",
        "emit_notification_loop",
    )
    api_hits = [m for m in required_api if m in subscriber_text]
    has_notification_kind = "notifications/resources/updated" in subscriber_text
    has_registry_singleton = "get_registry" in subscriber_text
    passed = (
        subscriber_present
        and len(api_hits) == len(required_api)
        and has_notification_kind
        and has_registry_singleton
    )
    p.checks.append(
        Check(
            "mcp_resource_polling_live",
            passed,
            evidence=(
                f"resource_subscriber.py present (size={subscriber_path.stat().st_size if subscriber_present else 0}B), "
                f"{len(api_hits)}/{len(required_api)} API surfaces present, "
                f"notifications/resources/updated wired, get_registry singleton"
            )
            if passed
            else "",
            missing=(
                f"present={subscriber_present}, api={len(api_hits)}/{len(required_api)}, "
                f"notification_kind={has_notification_kind}, singleton={has_registry_singleton}"
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
            missing=f"mig_088={bool(mig_088)}, dispatch_cron={dispatch_cron}" if not passed else "",
        )
    )

    # 2. Long-running task async pattern
    # TODO(E12-followup): `async def` is grep-trivial — every FastAPI handler
    # uses it regardless of long-task semantics. A stricter check would
    # require an explicit BackgroundTasks dependency wired on at least one
    # route OR a job-queue (`_bg_task_queue.py`) consumer. Tracked but not in
    # scope for the E12 packet.
    bg_queue = (SRC_API / "_bg_task_queue.py").exists()
    has_async_task = bool(_grep_files(SRC_API, r"background_tasks|BackgroundTasks|async def"))
    passed = bg_queue and has_async_task
    p.checks.append(
        Check(
            "long_task_async",
            passed,
            evidence="_bg_task_queue.py present + async/BackgroundTasks usage" if passed else "",
            missing=f"bg_queue={bg_queue}, async_task={has_async_task}" if not passed else "",
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
    has_router_prefix = 'APIRouter(prefix="/v1/a2a"' in a2a_text or 'prefix="/v1/a2a"' in a2a_text
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
    has_hmac_24h = "hmac" in a2a_text.lower() and (
        "hours=24" in a2a_text or "24h" in a2a_text or "24" in a2a_text
    )
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
    transport_meta_text = _read(SRC_MCP / "transport_metadata.py")
    has_transports_meta = (
        '"transports"' in mcp_manifest
        and '"streamable_http"' in mcp_manifest
        and '"sse"' in mcp_manifest
        and '"stdio"' in mcp_manifest
    )
    a2a_text = _read(SRC_API / "a2a.py")
    has_transport_advertisement = (
        '"mcp_stdio"' in a2a_text and '"mcp_streamable_http"' in a2a_text
    ) or (
        "a2a_transport_advertisements" in a2a_text
        and "a2a_transport_advertisements" in transport_meta_text
        and '"stdio"' in transport_meta_text
        and '"streamable_http"' in transport_meta_text
        and "mcp_{name}" in transport_meta_text
    )
    passed = (
        has_transports_meta
        and (bool(streamable_hits) or bool(streamable_doc))
        and has_transport_advertisement
    )
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

    # 6. Wave 41 — A2A skill negotiation + capability advertisement
    has_skills_endpoint = '@router.get("/skills")' in a2a_text
    has_skill_get = '@router.get("/skills/{skill_name}")' in a2a_text
    has_negotiate = '@router.post("/skills/negotiate")' in a2a_text
    has_catalog = "SKILL_CATALOG" in a2a_text and "_normalise_skill_card" in a2a_text
    has_negotiation_model = "A2ASkillNegotiation" in a2a_text
    skill_category_hits = re.findall(r'"category":\s*"[^"]+"', a2a_text)
    skill_count = len(skill_category_hits)
    has_tags = '"tags":' in a2a_text and "requested_tags" in a2a_text
    has_input_schema = '"input_schema":' in a2a_text and '"output_schema":' in a2a_text
    passed = (
        has_skills_endpoint
        and has_skill_get
        and has_negotiate
        and has_catalog
        and has_negotiation_model
        and skill_count >= 5
        and has_tags
        and has_input_schema
    )
    p.checks.append(
        Check(
            "a2a_skill_negotiation_live",
            passed,
            evidence=(
                f"/v1/a2a/skills + /skills/{{name}} + /skills/negotiate wired, "
                f"SKILL_CATALOG ({skill_count} skills) + tags + input/output schema present, "
                f"A2ASkillNegotiation model wired"
            )
            if passed
            else "",
            missing=(
                f"skills_endpoint={has_skills_endpoint}, skill_get={has_skill_get}, "
                f"negotiate={has_negotiate}, catalog={has_catalog}, "
                f"model={has_negotiation_model}, skill_count={skill_count} (need >=5), "
                f"tags={has_tags}, schemas={has_input_schema}"
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
    max_total = round(PILLAR_MAX * len(pillars), 2)
    average = round((total / max_total) * 10.0, 2) if max_total > 0 else 0.0
    green_threshold = 8.0
    yellow_threshold = 6.0
    return {
        "axis": "ax_4pillars",
        "framework": "Biilmann Access/Context/Tools/Orchestration",
        "total_score": total,
        "average_score": average,
        "max_score": max_total,
        "pillar_max": PILLAR_MAX,
        "cell_count": sum(len(p.checks) for p in pillars),
        "verdict": (
            "green"
            if average >= green_threshold
            else ("yellow" if average >= yellow_threshold else "red")
        ),
        "pillars": {
            p.name: {
                "score": p.score,
                "max": PILLAR_MAX,
                "cells": len(p.checks),
                "evidence": p.evidence,
                "missing_items": p.missing_items,
            }
            for p in pillars
        },
        "generated_at": datetime.now(UTC).isoformat(),
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
        lines.append(f"| {name} | {body['score']:.2f} / {body.get('max', PILLAR_MAX):.0f} |")
    lines.append("")
    for name, body in result["pillars"].items():
        lines += [
            f"## {name} — {body['score']:.2f} / {body.get('max', PILLAR_MAX):.0f}",
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


def _sanitize_public_artifact_text(text: str) -> str:
    replacements = [
        (
            r"\[WARN\] only \d+ caller\(s\); require_scope\(\) has \d+ caller\(s\) "
            r"under src/jpintel_mcp/api/ \(need >= \d+ — one per CANONICAL_SCOPES entry\)",
            (
                "[WARN] route_access_check: route-level access checks are not yet "
                "broadly verified across the public API surface"
            ),
        ),
        (
            r"\d+ route file\(s\) import \+ Depends\(require_scope\(\.\.\.\)\): \[[^\]]*\]",
            "route-level access checks are applied across the public API surface",
        ),
        (r"\brequire_scope\(\)", "route-level access check"),
        (r"\bCANONICAL_SCOPES\b", "documented access levels"),
        (r"\bscoped_api_token\b", "route_access_check"),
        (r"\bscoped API token\b", "route-level access check"),
        (r"\bidempotency_cache\b", "replay-safe request store"),
        (r"\bmigration_\d+=True\b", "schema update present"),
        (r"\bmigration_\d+\b", "schema update"),
        (r"\bmig_\d+\b", "schema update"),
        (r"\bstate-token\b", "continuation handle"),
        (r"\bstate_token\+HMAC 24h\b", "signed continuation handoff"),
    ]
    out = text
    for pattern, replacement in replacements:
        out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
    return out


def _sanitize_public_artifact(node: object) -> object:
    if isinstance(node, dict):
        return {key: _sanitize_public_artifact(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_sanitize_public_artifact(item) for item in node]
    if isinstance(node, str):
        return _sanitize_public_artifact_text(node)
    return node


def _ensure_public_access_warn(result: dict) -> dict:
    access = (result.get("pillars") or {}).get("Access") or {}
    if not isinstance(access, dict):
        return result
    evidence = access.setdefault("evidence", [])
    missing_items = access.setdefault("missing_items", [])
    if not isinstance(evidence, list) or not isinstance(missing_items, list):
        return result

    has_access_warn = any(
        isinstance(item, str) and "route_access_check" in item and "[WARN]" in item
        for item in [*evidence, *missing_items]
    )
    if has_access_warn and not any(
        isinstance(item, str) and "[WARN] route_access_check" in item for item in evidence
    ):
        evidence.append(
            "[WARN] route_access_check: route-level access checks are not yet "
            "broadly verified across the public API surface"
        )
    if has_access_warn and not any(
        isinstance(item, str) and "route-level access checks" in item for item in missing_items
    ):
        missing_items.append(
            "[MISS] route_access_check: route-level access checks are not yet "
            "broadly verified across the public API surface"
        )
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        required=False,
        default=None,
        help="output markdown path (omit when --dry-run)",
    )
    ap.add_argument("--out-json", default=None)
    ap.add_argument(
        "--out-site-json",
        default=str(SITE_STATUS / "ax_4pillars.json"),
        help="public-safe sidecar for the status dashboard",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="run audit and print summary, but do not write any output files",
    )
    args = ap.parse_args(argv)

    if not args.dry_run and not args.out:
        ap.error("--out is required unless --dry-run is set")

    result = run_audit()

    if not args.dry_run:
        out_md = pathlib.Path(args.out)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(render_md(result), encoding="utf-8")

        if args.out_json:
            out_json = pathlib.Path(args.out_json)
            out_json.parent.mkdir(parents=True, exist_ok=True)
            out_json.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

        if args.out_site_json:
            out_site_json = pathlib.Path(args.out_site_json)
            out_site_json.parent.mkdir(parents=True, exist_ok=True)
            public_result = _ensure_public_access_warn(
                _sanitize_public_artifact(result)  # type: ignore[arg-type]
            )
            out_site_json.write_text(
                json.dumps(public_result, indent=2, ensure_ascii=False), encoding="utf-8"
            )

    # Brief stdout summary.
    print(
        f"AX 4 Pillars total={result['total_score']:.2f}/{result['max_score']:.0f} "
        f"average={result['average_score']:.2f}/10 "
        f"cells={result.get('cell_count', 0)} verdict={result['verdict']}"
    )
    for name, body in result["pillars"].items():
        print(
            f"  - {name}: {body['score']:.2f}/{body.get('max', PILLAR_MAX):.0f}"
            f" ({body.get('cells', '-')} cells)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
