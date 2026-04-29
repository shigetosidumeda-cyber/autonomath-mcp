#!/usr/bin/env bash
# =============================================================================
# AutonoMath MCP — atomic publish to all auto-approve registries
# =============================================================================
#
# Operator: Bookyou株式会社 (T8010001213708) / info@bookyou.net
# Product:  AutonoMath  (PyPI: autonomath-mcp / npm: @autonomath/sdk)
# Version:  0.3.1  (LOCKED — do not bump from this script)
# Audited:  2026-04-29
#
# This script executes the AUTO-APPROVE leg of registry publication.
# All MANUAL-APPROVE registries (web forms / GitHub PRs / email submissions)
# are listed in the table at the bottom of the file as a copy-paste runbook.
#
# >>> REVIEW-ONLY GATE <<<
# `set -x` echoes every command; `exit 0` immediately after the gate keeps
# this file safe to run blind. Comment out / delete the `exit 0` line below
# AFTER you have read the entire script, exported the required env vars,
# and decided to actually publish.
#
# Required env vars:
#   PYPI_TOKEN              -- pypi.org API token, scope=autonomath-mcp
#   NPM_TOKEN               -- npmjs.com automation token, scope=@autonomath/*
#   MCP_REGISTRY_TOKEN      -- (a.k.a. GH_TOKEN) GitHub PAT, repo:read on
#                              AutonoMath/autonomath-mcp; org publish rights
#                              required for io.github.AutonoMath/* namespace
#   GH_TOKEN                -- (alias for MCP_REGISTRY_TOKEN; both accepted)
#
# Run order (all auto-approve, parallel-safe except #1->#3 ordering):
#   1. PyPI                       (sdist + wheel via twine)
#   2. npm @autonomath/sdk        (typescript SDK; only if version aligned)
#   3. MCP Official Registry      (server.json publish; propagates to PulseMCP)
#   4. .mcpb DXT bundle copy      (verify Cloudflare Pages will serve it)
#   5. Build runbook regen        (write docs/_internal/mcp_registry_runbook.md)
#
# Manual-only (NOT executed by this script):
#   - Smithery (auto-indexed; verify via dashboard)
#   - Glama (auto-indexed; verify via daily crawl)
#   - Cursor / mcp.so / MCP Market / MCP Hunt / mcpservers.org / MCP Server
#     Finder / Cline / Awesome MCP / Anthropic External Plugins (form/PR/email)
#
# Exit codes:
#   0  every step ok (or --dry-run)
#   1  at least one step failed
#   2  pre-flight check failed (version drift, missing artifact, etc.)
# =============================================================================

set -euo pipefail
set -x

# >>> REVIEW-ONLY EARLY EXIT — delete this `exit 0` to actually publish <<<
echo "REVIEW-ONLY: read the script, export PYPI_TOKEN/NPM_TOKEN/MCP_REGISTRY_TOKEN, then delete the 'exit 0' below"
exit 0
# =============================================================================
# Everything below this line runs only when the gate is removed.
# =============================================================================

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${PY:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY="python3"

# -----------------------------------------------------------------------------
# Pre-flight: verify v0.3.1 alignment across all 5 manifests
# -----------------------------------------------------------------------------
"$PY" - <<'PYEOF'
import json, re, sys, tomllib

want = "0.3.1"
errors = []

# pyproject.toml
with open("pyproject.toml", "rb") as f:
    pv = tomllib.load(f)["project"]["version"]
if pv != want:
    errors.append(f"pyproject.toml version={pv} (want {want})")

# server.json
sv = json.load(open("server.json"))["version"]
if sv != want:
    errors.append(f"server.json version={sv} (want {want})")

# mcp-server.json
mv = json.load(open("mcp-server.json"))["version"]
if mv != want:
    errors.append(f"mcp-server.json version={mv} (want {want})")

# dxt/manifest.json
dv = json.load(open("dxt/manifest.json"))["version"]
if dv != want:
    errors.append(f"dxt/manifest.json version={dv} (want {want})")

# smithery.yaml (regex; avoid yaml dep)
yv = re.search(r'version:\s*"([^"]+)"', open("smithery.yaml").read()).group(1)
if yv != want:
    errors.append(f"smithery.yaml version={yv} (want {want})")

if errors:
    print("VERSION DRIFT:", *errors, sep="\n  ")
    sys.exit(2)
print(f"OK: all 5 manifests at v{want}")
PYEOF

# Verify dist artifacts exist for v0.3.1
test -f "dist/autonomath_mcp-0.3.1-py3-none-any.whl" || { echo "FAIL: missing 0.3.1 wheel"; exit 2; }
test -f "dist/autonomath_mcp-0.3.1.tar.gz"           || { echo "FAIL: missing 0.3.1 sdist"; exit 2; }
test -f "dist/autonomath-mcp-0.3.1.mcpb"             || { echo "FAIL: missing 0.3.1 .mcpb"; exit 2; }
test -f "site/downloads/autonomath-mcp.mcpb"         || { echo "FAIL: missing site .mcpb"; exit 2; }

# Verify required env vars
: "${PYPI_TOKEN:?PYPI_TOKEN not set; aborting publish}"
: "${MCP_REGISTRY_TOKEN:=${GH_TOKEN:?MCP_REGISTRY_TOKEN/GH_TOKEN not set}}"
# NPM_TOKEN is optional (skip npm if absent)
: "${NPM_TOKEN:=}"

# -----------------------------------------------------------------------------
# 1. PyPI
# -----------------------------------------------------------------------------
echo "=== [1/5] PyPI: autonomath-mcp 0.3.1 ==="
twine check dist/autonomath_mcp-0.3.1-py3-none-any.whl dist/autonomath_mcp-0.3.1.tar.gz
TWINE_USERNAME=__token__ TWINE_PASSWORD="$PYPI_TOKEN" \
    twine upload \
        dist/autonomath_mcp-0.3.1-py3-none-any.whl \
        dist/autonomath_mcp-0.3.1.tar.gz

# -----------------------------------------------------------------------------
# 2. npm  (gated; SDK package.json version=0.3.2 NOT aligned to MCP server 0.3.1)
# -----------------------------------------------------------------------------
echo "=== [2/5] npm: @autonomath/sdk ==="
if [ -z "$NPM_TOKEN" ]; then
    echo "skip: NPM_TOKEN not set"
elif ! grep -q '"version": "0.3.1"' sdk/typescript/package.json; then
    echo "skip: sdk/typescript/package.json version is independent of MCP server (currently 0.3.2)"
    echo "      run separately when SDK is ready: cd sdk/typescript && npm publish --access public"
else
    cd sdk/typescript
    npm pack --dry-run
    NPM_TOKEN="$NPM_TOKEN" npm publish --access public
    cd "$ROOT"
fi

# -----------------------------------------------------------------------------
# 3. MCP Official Registry
# -----------------------------------------------------------------------------
echo "=== [3/5] MCP Official Registry ==="
GH_TOKEN="$MCP_REGISTRY_TOKEN" "$PY" scripts/publish_to_mcp_registries.py --only mcp_registry

# -----------------------------------------------------------------------------
# 4. DXT bundle (Cloudflare Pages serves site/downloads/ on next deploy)
# -----------------------------------------------------------------------------
echo "=== [4/5] DXT .mcpb (verify only; Cloudflare Pages auto-deploys site/) ==="
ls -la site/downloads/autonomath-mcp.mcpb dist/autonomath-mcp-0.3.1.mcpb
unzip -l site/downloads/autonomath-mcp.mcpb | head

# -----------------------------------------------------------------------------
# 5. Regenerate the per-registry runbook (records every manual step left)
# -----------------------------------------------------------------------------
echo "=== [5/5] Regenerate registry runbook ==="
"$PY" scripts/publish_to_mcp_registries.py --dry-run --no-runbook=false || true

# -----------------------------------------------------------------------------
# DONE — manual-only registries below (run from a separate terminal).
# -----------------------------------------------------------------------------
cat <<'EOF'

== AUTO-APPROVE PUBLISH COMPLETE ==
Verify within 24-48h:
  - https://pypi.org/project/autonomath-mcp/0.3.1/
  - https://www.npmjs.com/package/@autonomath/sdk           (if NPM_TOKEN was set)
  - https://registry.modelcontextprotocol.io/servers/io.github.AutonoMath/autonomath-mcp
  - https://smithery.ai/server/io.github.AutonoMath/autonomath-mcp   (auto-indexed)
  - https://glama.ai/mcp/servers/AutonoMath/autonomath-mcp           (auto-indexed)

== MANUAL-APPROVE REMAINDER ==
6.  Cursor Marketplace          https://cursor.com/marketplace                (web form)
7.  PulseMCP                    https://www.pulsemcp.com/submit               (auto-ingest of #3, fallback form)
8.  Awesome MCP Servers (PR)    https://github.com/punkpeye/awesome-mcp-servers
9.  mcp.so                      https://mcp.so/submit                          (form/issue)
10. MCP Market                  https://mcpmarket.com/submit                   (web form)
11. MCP Hunt                    https://mcphunt.com                            (form + upvotes)
12. Cline MCP Marketplace       https://github.com/cline/mcp-marketplace      (PR)
13. MCP Server Finder           info@mcpserverfinder.com                      (email)
14. mcpservers.org              https://mcpservers.org/submit                 (form; auto-mirror of #8)
15. Anthropic External Plugins  https://clau.de/plugin-directory-submission   (form, 2-4 wk review)

Submission texts pre-staged in: scripts/mcp_registries_submission.json
Per-registry runbook (with rollback): docs/_internal/mcp_registry_runbook.md
EOF
