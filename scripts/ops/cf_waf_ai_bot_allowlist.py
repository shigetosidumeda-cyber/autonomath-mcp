#!/usr/bin/env python3
"""Programmatically allowlist AI bot UAs in Cloudflare WAF (Wave 24).

This script creates (or updates) a Cloudflare Custom WAF Rule whose
expression matches any of the AI answer-engine crawler UAs that jpcite
explicitly welcomes. The action is ``skip`` which bypasses the WAF
managed rules and Bot Fight Mode category challenge for those UAs.

Why bypass Bot Fight Mode for AI crawlers
-----------------------------------------
Cloudflare's Bot Fight Mode catches headless-Chrome / Selenium / Puppeteer
by default and issues a JS-challenge. AI answer-engine crawlers (GPTBot /
ClaudeBot / PerplexityBot / Google-Extended) do not run JS, cannot solve
the challenge, and silently drop the page. The downstream effect is that
ChatGPT / Claude / Perplexity / Gemini fail to ingest jpcite content as a
citation source — destroying the AEO (answer-engine optimization) layer
that is the company's organic-acquisition substrate.

Allowlisting these UAs is therefore *required* for the LLM-citation
business model. We document the trust boundary by tagging the rule with
``ref=jpcite_ai_bot_allowlist`` so an operator can audit / rotate it.

Operational contract
--------------------
- Idempotent: re-running the script updates the existing rule by ``ref``
  rather than creating a duplicate.
- Dry-run by default: prints the rule body and exits 0 without calling
  the Cloudflare API. Pass ``--apply`` to actually write.
- Read-only credentials are not enough: the API token must have the
  ``Zone WAF: Edit`` permission for the jpcite.com zone.

Memory references
-----------------
- feedback_organic_only_no_ads: AI citation is the organic acquisition
  surface; blocking AI crawlers shuts off the funnel.
- feedback_zero_touch_solo: this allowlist is the only AI-bot intervention
  the operator needs. No per-bot deals, no rate cards.
- feedback_ax_4_pillars: AX Layer 1 (Access) requires that AI agents can
  reach the site without solving CAPTCHAs.

The bot UA list mirrors ``functions/aeo_redirect.ts`` AI_BOT_UA_SUBSTRINGS
- both files MUST stay in sync. If you add a UA here, also add it there
(and vice versa).

Usage::

    # Inspect what rule body would be written:
    python3 scripts/ops/cf_waf_ai_bot_allowlist.py

    # Write to Cloudflare (requires CLOUDFLARE_API_TOKEN +
    # CLOUDFLARE_ZONE_ID_JPCITE_COM):
    python3 scripts/ops/cf_waf_ai_bot_allowlist.py --apply
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

# UA substring list — keep in sync with functions/aeo_redirect.ts.
AI_BOT_UA_SUBSTRINGS: list[str] = [
    "gptbot",
    "chatgpt-user",
    "oai-searchbot",
    "claudebot",
    "claude-web",
    "anthropic-ai",
    "perplexitybot",
    "perplexity-user",
    "google-extended",
    "googleother",
    "bingbot-ai",
    "youbot",
    "amazonbot",
    "bytespider",
    "ccbot",
    "diffbot",
    "facebookbot",
    "applebot-extended",
    "cohere-ai",
    "mistral",
]

# Canonical rule identifiers — used for idempotent upsert.
RULE_REF = "jpcite_ai_bot_allowlist"
RULE_DESCRIPTION = (
    "AI answer-engine crawler allowlist (Wave 24). Bypass Bot Fight Mode "
    "and managed WAF challenges for GPTBot / ClaudeBot / PerplexityBot / "
    "Google-Extended / etc. so jpcite stays citable from LLM agents."
)
API_BASE = "https://api.cloudflare.com/client/v4"
PHASE = "http_request_firewall_custom"


def build_expression() -> str:
    """Build the Cloudflare expression matching any UA substring (lowercased)."""
    clauses = [f'lower(http.user_agent) contains "{ua}"' for ua in AI_BOT_UA_SUBSTRINGS]
    return " or ".join(clauses)


def desired_rule() -> dict[str, Any]:
    return {
        "ref": RULE_REF,
        "description": RULE_DESCRIPTION,
        "expression": build_expression(),
        "action": "skip",
        "enabled": True,
        "action_parameters": {
            # Bypass these protection products for AI bot UAs.
            "products": ["waf", "bic", "uaBlock", "zoneLockdown", "hot", "securityLevel"],
            "phases": ["http_ratelimit", "http_request_firewall_managed", "http_request_sbfm"],
            "ruleset": "current",
        },
    }


def cf_request(
    method: str, path: str, token: str, body: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        if method == "GET" and exc.code == 404:
            return None
        raise SystemExit(
            f"Cloudflare API {method} {path} failed with HTTP {exc.code}: {payload}"
        ) from exc


def get_entrypoint(zone_id: str, token: str) -> dict[str, Any] | None:
    data = cf_request("GET", f"/zones/{zone_id}/rulesets/phases/{PHASE}/entrypoint", token)
    if not data or not data.get("success"):
        return None
    return data["result"]


def clean_existing_rule(rule: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "ref",
        "description",
        "expression",
        "action",
        "action_parameters",
        "enabled",
        "logging",
    }
    return {k: v for k, v in rule.items() if k in allowed}


def apply(zone_id: str, token: str) -> None:
    want = desired_rule()
    entry = get_entrypoint(zone_id, token)
    if entry is None:
        # No firewall_custom ruleset yet — create the entrypoint with just us.
        body = {
            "name": "AI bot allowlist ruleset",
            "kind": "zone",
            "phase": PHASE,
            "rules": [want],
        }
        data = cf_request("POST", f"/zones/{zone_id}/rulesets", token, body)
        rid = data["result"]["id"] if data else "<unknown>"
        print(f"[OK] created firewall_custom ruleset id={rid} with {RULE_REF}")
        return

    merged: list[dict[str, Any]] = []
    seen = False
    for existing in entry.get("rules", []):
        if existing.get("ref") == RULE_REF:
            merged.append(want)
            seen = True
        else:
            merged.append(clean_existing_rule(existing))
    if not seen:
        merged.append(want)

    body = {
        "name": entry.get("name", "AI bot allowlist ruleset"),
        "kind": "zone",
        "phase": PHASE,
        "rules": merged,
    }
    data = cf_request("PUT", f"/zones/{zone_id}/rulesets/{entry['id']}", token, body)
    rid = data["result"]["id"] if data else entry["id"]
    print(
        f"[OK] updated firewall_custom ruleset id={rid} ({RULE_REF} present, rules={len(merged)})"
    )


def main(argv: list[str]) -> int:
    apply_mode = "--apply" in argv
    rule = desired_rule()
    print(f"# AI bot allowlist rule (ref={rule['ref']})")
    print(f"# Bots covered: {len(AI_BOT_UA_SUBSTRINGS)} UA substrings")
    print(f"# Action: skip ({', '.join(rule['action_parameters']['products'])})")
    print(f"# Expression length: {len(rule['expression'])} chars")
    print()
    print(json.dumps(rule, indent=2))
    print()

    if not apply_mode:
        print("[dry-run] pass --apply to write to Cloudflare API")
        return 0

    token = os.environ.get("CLOUDFLARE_API_TOKEN") or os.environ.get("CF_API_TOKEN")
    zone_id = os.environ.get("CLOUDFLARE_ZONE_ID_JPCITE_COM") or os.environ.get("CF_ZONE_ID")
    if not token:
        print("missing CLOUDFLARE_API_TOKEN / CF_API_TOKEN", file=sys.stderr)
        return 2
    if not zone_id:
        print("missing CLOUDFLARE_ZONE_ID_JPCITE_COM / CF_ZONE_ID", file=sys.stderr)
        return 2

    apply(zone_id, token)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
