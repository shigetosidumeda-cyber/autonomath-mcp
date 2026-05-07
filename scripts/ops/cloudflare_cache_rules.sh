#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SECRETS_FILE="${JPCITE_SECRETS_FILE:-${HOME}/.jpcite_secrets.env}"
DRY_RUN=false

if [ -f "$SECRETS_FILE" ]; then
  # shellcheck disable=SC1090
  source "$SECRETS_FILE"
fi

for arg in "$@"; do
  case "$arg" in
    --dry-run)
      DRY_RUN=true
      ;;
    -h|--help)
      cat <<'USAGE'
Usage: bash scripts/ops/cloudflare_cache_rules.sh [--dry-run]

Applies the cache_rules block from cloudflare-rules.yaml to Cloudflare
Cache Rules (Rulesets API, http_request_cache_settings phase).

Required env for apply:
  CLOUDFLARE_API_TOKEN or CF_API_TOKEN
  CLOUDFLARE_ZONE_ID_JPCITE_COM or CF_ZONE_ID

--dry-run parses the YAML and prints rule names only; no token is required.
USAGE
      exit 0
      ;;
    *)
      printf '[cloudflare_cache_rules] unknown argument: %s\n' "$arg" >&2
      exit 2
      ;;
  esac
done

export JPCITE_ROOT="$ROOT"
export JPCITE_CF_DRY_RUN="$DRY_RUN"
export JPCITE_CF_TOKEN="${CLOUDFLARE_API_TOKEN:-${CF_API_TOKEN:-}}"
export JPCITE_CF_ZONE_ID_JPCITE_COM="${CLOUDFLARE_ZONE_ID_JPCITE_COM:-${CF_ZONE_ID:-}}"

python3 - <<'PY'
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required: python3 -m pip install pyyaml") from exc

ROOT = Path(os.environ["JPCITE_ROOT"])
DRY_RUN = os.environ["JPCITE_CF_DRY_RUN"] == "true"
TOKEN = os.environ.get("JPCITE_CF_TOKEN", "")
ZONE_IDS = {"jpcite.com": os.environ.get("JPCITE_CF_ZONE_ID_JPCITE_COM", "")}
PHASE = "http_request_cache_settings"
API_BASE = "https://api.cloudflare.com/client/v4"


def load_cache_rules() -> list[dict[str, Any]]:
    doc = yaml.safe_load((ROOT / "cloudflare-rules.yaml").read_text(encoding="utf-8"))
    rules = doc.get("cache_rules", [])
    if not isinstance(rules, list) or not rules:
        raise SystemExit("cloudflare-rules.yaml has no cache_rules block")
    return rules


def desired_rule(rule: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in ("name", "expression", "action", "action_parameters") if key not in rule]
    if missing:
        raise SystemExit(f"cache rule {rule.get('name', '<unnamed>')} missing: {', '.join(missing)}")
    return {
        "ref": rule.get("ref") or rule["name"],
        "description": rule.get("description", rule["name"]),
        "expression": rule["expression"],
        "action": rule["action"],
        "action_parameters": rule["action_parameters"],
        "enabled": bool(rule.get("enabled", True)),
    }


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
    return {key: value for key, value in rule.items() if key in allowed}


def cf_request(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any] | None:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {TOKEN}",
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
        raise SystemExit(f"Cloudflare API {method} {path} failed with HTTP {exc.code}: {payload}") from exc


def get_entrypoint(zone_id: str) -> dict[str, Any] | None:
    data = cf_request("GET", f"/zones/{zone_id}/rulesets/phases/{PHASE}/entrypoint")
    if not data or not data.get("success"):
        return None
    return data["result"]


def apply_zone(zone: str, rules: list[dict[str, Any]]) -> None:
    zone_id = ZONE_IDS.get(zone, "")
    if not zone_id:
        raise SystemExit(f"missing zone id env for {zone}")

    desired = [desired_rule(rule) for rule in rules]
    entrypoint = get_entrypoint(zone_id)
    desired_by_ref = {rule["ref"]: rule for rule in desired}

    if entrypoint is None:
        body = {
            "name": "Cache rules ruleset",
            "kind": "zone",
            "phase": PHASE,
            "rules": desired,
        }
        data = cf_request("POST", f"/zones/{zone_id}/rulesets", body)
        ruleset_id = data["result"]["id"] if data else "<unknown>"
        print(f"[OK] created zone={zone} ruleset={ruleset_id} managed_rules={len(desired)}")
        return

    merged: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    for existing in entrypoint.get("rules", []):
        ref = existing.get("ref")
        if ref in desired_by_ref:
            merged.append(desired_by_ref[ref])
            seen_refs.add(ref)
        else:
            merged.append(clean_existing_rule(existing))
    for rule in desired:
        if rule["ref"] not in seen_refs:
            merged.append(rule)

    body = {
        "name": entrypoint.get("name", "Cache rules ruleset"),
        "kind": "zone",
        "phase": PHASE,
        "rules": merged,
    }
    data = cf_request("PUT", f"/zones/{zone_id}/rulesets/{entrypoint['id']}", body)
    ruleset_id = data["result"]["id"] if data else entrypoint["id"]
    print(f"[OK] updated zone={zone} ruleset={ruleset_id} managed_rules={len(desired)}")


def main() -> int:
    rules = load_cache_rules()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for rule in rules:
        if rule.get("phase", PHASE) != PHASE:
            raise SystemExit(f"unsupported phase for {rule.get('name')}: {rule.get('phase')}")
        grouped.setdefault(rule["zone"], []).append(rule)

    if DRY_RUN:
        for zone, zone_rules in grouped.items():
            names = ", ".join(rule["name"] for rule in zone_rules)
            print(f"[dry-run] zone={zone} rules={len(zone_rules)} names={names}")
        return 0

    if not TOKEN:
        raise SystemExit("missing CLOUDFLARE_API_TOKEN or CF_API_TOKEN")

    for zone in sorted(grouped):
        apply_zone(zone, grouped[zone])
    return 0


if __name__ == "__main__":
    sys.exit(main())
PY
