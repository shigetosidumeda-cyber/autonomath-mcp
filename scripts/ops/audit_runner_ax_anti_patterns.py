#!/usr/bin/env python3
"""Wave 17 AX — Anti-pattern audit (9 anti-patterns from ax_smart_guide §4).

Each check enumerates violations across site/, src/, and docs/. Target = 0
violations across all 9 axes.

1. Separate "agent-version" site path
2. ARIA over-use (role="button" alongside existing <button>)
3. JSON-LD vs HTML body divergence (Schema.org price vs rendered price)
4. CAPTCHA on API endpoints (curl-probe + repo grep)
5. Vague MCP tool descriptions (< 50 chars, or "データ取得" / "処理する" etc.)
6. Browser-only OAuth (no API token alternative)
7. Server-side session state (Session cookie dependency)
8. JS-required content (no main content in initial HTML)
9. Partially humanized AI (chat persona / mascot / first-person voice)

Output: docs/audit/ax_anti_patterns_audit_*.md with per-axis violation list.

Pure stdlib + optional requests for the live CAPTCHA probe. Read-only.
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
SRC_API = REPO_ROOT / "src" / "jpintel_mcp" / "api"
SRC_MCP = REPO_ROOT / "src" / "jpintel_mcp" / "mcp"

API_PROBE_URL = "https://api.jpcite.com/v1/programs?q=test&limit=1"

VAGUE_DESC_PHRASES = (
    "データを取得",
    "データ取得",
    "処理する",
    "実行する",
    "取得する",
    "Gets data",
    "fetches data",
    "returns data",
    "process the",
)

HUMANIZED_MARKERS = (
    "私はAI",
    "私はあなたの",
    "私の名前は",
    "こんにちは!",
    "I'm your AI assistant",
    "Hi, I'm",
    "mascot",
    "chat-persona",
    "ai-assistant-name",
)


@dataclass
class AntiPatternResult:
    name: str
    description: str
    violations: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.violations)

    @property
    def passed(self) -> bool:
        return self.count == 0


def _read(p: pathlib.Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _http_probe(url: str) -> tuple[bool, str]:
    try:
        import requests  # type: ignore
    except ImportError:
        return False, "requests-not-installed"
    try:
        r = requests.get(url, timeout=5.0, allow_redirects=True)
        return True, r.text[:8192]
    except Exception as e:  # noqa: BLE001
        return False, f"probe-error: {e}"


# ---------- 1. separate agent-version site ----------


def check_separate_agent_site() -> AntiPatternResult:
    r = AntiPatternResult(
        "separate_agent_site_path",
        "Avoid maintaining a parallel agent-only site (site/agent/, site/ai/ etc.). One canonical site benefits both humans and agents.",
    )
    for forbidden in ("agent", "ai", "agents", "bot", "for-agents", "for-ai", "for-bots"):
        sub = SITE / forbidden
        if sub.is_dir():
            # Acceptable carve-outs: site/audiences/ai_engineer.html is a single
            # landing page, not a separate site. Only flag if it has > 3 HTML files
            # AND has its own index.
            html_files = list(sub.glob("**/*.html"))
            if len(html_files) >= 3 and (sub / "index.html").exists():
                r.violations.append(
                    f"site/{forbidden}/ looks like a parallel agent-only site "
                    f"({len(html_files)} HTML files + own index.html)"
                )
    return r


# ---------- 2. ARIA over-use ----------


def check_aria_overuse() -> AntiPatternResult:
    r = AntiPatternResult(
        "aria_overuse",
        "role='button' on a non-<button> element when a native <button> would suffice (WebAIM: ARIA-heavy sites score worse on a11y).",
    )
    pattern_role = re.compile(r'role\s*=\s*["\'](button|link|nav|main|article|heading)["\']')
    sampled = sorted(SITE.glob("*.html"))[:25]
    for fp in sampled:
        html = _read(fp)
        for m in pattern_role.finditer(html):
            role = m.group(1)
            # Look at the 60-char window around the match to see if the host
            # element is already a native equivalent (then it's redundant).
            start = max(0, m.start() - 200)
            window = html[start : m.start()]
            # Find the last opening tag in the window.
            tag_match = re.search(r"<([a-zA-Z][a-zA-Z0-9]*)[^>]*$", window)
            host_tag = tag_match.group(1).lower() if tag_match else "?"
            redundant_pairs = {
                "button": "button",
                "link": "a",
                "nav": "nav",
                "main": "main",
                "article": "article",
                "heading": "h1",
            }
            if host_tag == redundant_pairs.get(role):
                r.violations.append(
                    f"{fp.name}: <{host_tag} role='{role}'> — redundant ARIA on native equivalent"
                )
    return r


# ---------- 3. JSON-LD vs HTML body divergence ----------


def check_jsonld_html_divergence() -> AntiPatternResult:
    r = AntiPatternResult(
        "jsonld_html_divergence",
        "Schema.org JSON-LD price/availability must match visible HTML body (search-engine penalty + agent-trust loss).",
    )
    sample_pages = ["pricing.html", "index.html", "about.html", "facts.html", "compare.html"]
    price_rx = re.compile(r'"price"\s*:\s*"?(\d[\d,]*)"?')
    body_price_rx = re.compile(r"¥\s*(\d[\d,]*)|JPY\s*(\d[\d,]*)|(\d[\d,]+)\s*円")
    for name in sample_pages:
        html = _read(SITE / name)
        if not html or "application/ld+json" not in html:
            continue
        # Extract JSON-LD blocks.
        for m in re.finditer(
            r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>',
            html,
            flags=re.DOTALL,
        ):
            block = m.group(1)
            jsonld_prices = {pm.group(1).replace(",", "") for pm in price_rx.finditer(block)}
            if not jsonld_prices:
                continue
            # Extract body prices outside <script> tags.
            body = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
            body_prices = set()
            for bm in body_price_rx.finditer(body):
                v = bm.group(1) or bm.group(2) or bm.group(3) or ""
                if v:
                    body_prices.add(v.replace(",", ""))
            # If JSON-LD has prices and body has prices, but NO overlap,
            # that's a divergence violation.
            if body_prices and not (jsonld_prices & body_prices):
                r.violations.append(
                    f"{name}: JSON-LD prices {sorted(jsonld_prices)} vs body prices "
                    f"{sorted(body_prices)} — no overlap"
                )
    return r


# ---------- 4. CAPTCHA on API endpoints ----------


def check_captcha_on_api() -> AntiPatternResult:
    r = AntiPatternResult(
        "captcha_on_api",
        "API endpoints must not require CAPTCHA. Use scoped tokens + rate limits instead.",
    )
    captcha_markers = ("hcaptcha", "recaptcha", "g-recaptcha", "cf-turnstile", "captcha-token")
    reachable, body = _http_probe(API_PROBE_URL)
    body_lower = body.lower()
    if reachable:
        for marker in captcha_markers:
            if marker in body_lower:
                r.violations.append(
                    f"live probe of {API_PROBE_URL}: response contains marker '{marker}'"
                )
    rx = re.compile("|".join(captcha_markers), re.IGNORECASE)
    for fp in SRC_API.glob("**/*.py"):
        text = _read(fp)
        if rx.search(text):
            r.violations.append(f"{fp.relative_to(REPO_ROOT)}: CAPTCHA marker found in API source")
    return r


# ---------- 5. Vague MCP tool descriptions ----------


def check_vague_mcp_descriptions() -> AntiPatternResult:
    r = AntiPatternResult(
        "vague_mcp_descriptions",
        "MCP tool `description` must be specific and >= 50 chars. Vague placeholders like 'データを取得' are AX-hostile.",
    )
    desc_rx = re.compile(
        r'description\s*=\s*(?:"|\')([^"\']{1,400})(?:"|\')'
    )
    for fp in SRC_MCP.glob("**/*.py"):
        text = _read(fp)
        for m in desc_rx.finditer(text):
            desc = m.group(1).strip()
            # Skip non-MCP-tool descriptions (e.g. Pydantic field descriptions
            # tend to be short by nature). Heuristic: descriptions inside an
            # @mcp.tool / FastMCP context are bigger blocks. We restrict by
            # context: only files under src/jpintel_mcp/mcp/ that mention @mcp.
            if "@mcp" not in text:
                continue
            line_no = text[: m.start()].count("\n") + 1
            if len(desc) < 50:
                r.violations.append(
                    f"{fp.relative_to(REPO_ROOT)}:{line_no}: short description "
                    f"({len(desc)} chars): {desc[:80]!r}"
                )
                continue
            for phrase in VAGUE_DESC_PHRASES:
                if phrase in desc and len(desc) < 120:
                    r.violations.append(
                        f"{fp.relative_to(REPO_ROOT)}:{line_no}: vague phrase '{phrase}' "
                        f"in short description: {desc[:80]!r}"
                    )
                    break
    return r


# ---------- 6. Browser-only OAuth ----------


def check_browser_only_oauth() -> AntiPatternResult:
    r = AntiPatternResult(
        "browser_only_oauth",
        "Must offer at least one non-browser auth path (API token / device-code / client-credentials).",
    )
    has_github = (SRC_API / "auth_github.py").exists()
    has_google = (SRC_API / "auth_google.py").exists()
    # API-key issuance route present somewhere.
    api_key_routes = []
    for fp in SRC_API.glob("**/*.py"):
        text = _read(fp)
        if re.search(r'/api[_-]?keys?\b|issue_api_key|create_api_key', text):
            api_key_routes.append(fp.relative_to(REPO_ROOT))
    if (has_github or has_google) and not api_key_routes:
        r.violations.append(
            "OAuth wired but no API-key issuance route found — agents would be forced "
            "through a browser popup with no token-only alternative"
        )
    return r


# ---------- 7. Server-side session state ----------


def check_server_side_session() -> AntiPatternResult:
    r = AntiPatternResult(
        "server_side_session_state",
        "Server-side session-ID cookie state is hard for agent HTTP clients. Prefer stateless token auth.",
    )
    sess_rx = re.compile(
        r'SessionMiddleware|request\.session\[|fastapi\.middleware\.sessions'
    )
    for fp in SRC_API.glob("**/*.py"):
        text = _read(fp)
        for m in sess_rx.finditer(text):
            line_no = text[: m.start()].count("\n") + 1
            # Exempt OAuth callback paths — short-lived session for the callback
            # exchange is the de-facto pattern.
            ctx_start = max(0, m.start() - 200)
            ctx = text[ctx_start : m.end() + 200]
            if "oauth" in ctx.lower() or "csrf" in ctx.lower() or "callback" in ctx.lower():
                continue
            r.violations.append(
                f"{fp.relative_to(REPO_ROOT)}:{line_no}: server-side session usage outside OAuth callback"
            )
    return r


# ---------- 8. JS-required content ----------


def check_js_required_content() -> AntiPatternResult:
    r = AntiPatternResult(
        "js_required_content",
        "Initial HTML must carry main content; retrieval crawlers do not execute JS. Hydrate, do not bootstrap.",
    )
    sample_pages = ["index.html", "pricing.html", "about.html", "facts.html", "compare.html"]
    for name in sample_pages:
        html = _read(SITE / name)
        if not html:
            continue
        # Strip <script> + <style> + <noscript>.
        stripped = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        stripped = re.sub(r"<style[^>]*>.*?</style>", "", stripped, flags=re.DOTALL)
        # Extract <main> ... </main> or <body> ... </body> visible text length.
        main_match = re.search(r"<main[^>]*>(.*?)</main>", stripped, flags=re.DOTALL)
        body_text = main_match.group(1) if main_match else stripped
        visible = re.sub(r"<[^>]+>", " ", body_text)
        visible = re.sub(r"\s+", " ", visible).strip()
        if len(visible) < 200:
            r.violations.append(
                f"{name}: initial HTML main/body has only {len(visible)} chars of "
                f"non-script text — likely JS-required"
            )
    return r


# ---------- 9. Partially humanized AI ----------


def check_humanized_ai() -> AntiPatternResult:
    r = AntiPatternResult(
        "partially_humanized_ai",
        "TOAST research: partially-humanized AI is least trusted. Be clearly AI, no mascot / persona / first-person voice.",
    )
    rx = re.compile("|".join(re.escape(m) for m in HUMANIZED_MARKERS), re.IGNORECASE)
    sampled = list(SITE.glob("*.html"))[:40]
    for fp in sampled:
        html = _read(fp)
        for m in rx.finditer(html):
            line_no = html[: m.start()].count("\n") + 1
            r.violations.append(
                f"{fp.name}:{line_no}: humanized marker '{m.group(0)}'"
            )
    return r


# ---------- runner ----------


def run_audit() -> dict:
    checks = [
        check_separate_agent_site(),
        check_aria_overuse(),
        check_jsonld_html_divergence(),
        check_captcha_on_api(),
        check_vague_mcp_descriptions(),
        check_browser_only_oauth(),
        check_server_side_session(),
        check_js_required_content(),
        check_humanized_ai(),
    ]
    total_violations = sum(c.count for c in checks)
    return {
        "axis": "ax_anti_patterns",
        "anti_pattern_count_target": 0,
        "total_violations": total_violations,
        "verdict": (
            "green" if total_violations == 0
            else ("yellow" if total_violations <= 10 else "red")
        ),
        "anti_patterns": [
            {
                "name": c.name,
                "description": c.description,
                "violation_count": c.count,
                "passed": c.passed,
                "violations": c.violations,
            }
            for c in checks
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def render_md(result: dict) -> str:
    date = result["generated_at"][:10]
    lines = [
        f"# jpcite AX Anti-Patterns Audit — {date} (automated)",
        "",
        f"**Total violations**: {result['total_violations']} (target: 0)  ",
        f"**Verdict**: {result['verdict'].upper()}  ",
        "",
        "| # | Anti-pattern | Violations | Status |",
        "| --- | --- | --- | --- |",
    ]
    for i, ap in enumerate(result["anti_patterns"], 1):
        status = "PASS" if ap["passed"] else "FAIL"
        lines.append(f"| {i} | {ap['name']} | {ap['violation_count']} | {status} |")
    lines.append("")
    for i, ap in enumerate(result["anti_patterns"], 1):
        lines += [
            f"## {i}. {ap['name']} — {'PASS' if ap['passed'] else f'FAIL ({ap[\"violation_count\"]} violations)'}",
            "",
            f"_{ap['description']}_",
            "",
        ]
        if ap["passed"]:
            lines.append("- (none)")
        else:
            for v in ap["violations"][:30]:
                lines.append(f"- {v}")
            if len(ap["violations"]) > 30:
                lines.append(f"- ... and {len(ap['violations']) - 30} more")
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

    print(
        f"AX Anti-Patterns total_violations={result['total_violations']} "
        f"verdict={result['verdict']}"
    )
    for ap_item in result["anti_patterns"]:
        print(f"  - {ap_item['name']}: {ap_item['violation_count']} violations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
