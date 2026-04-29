#!/usr/bin/env bash
# Build the Claude Desktop Extension bundle (autonomath-mcp.mcpb).
#
# Source: dxt/manifest.json
# Output: site/downloads/autonomath-mcp.mcpb
#
# The .mcpb format is a flat zip containing manifest.json at the root.
# Install path for end users: Claude Desktop Settings → Extensions →
# Install from file. Runtime: uvx autonomath-mcp (resolved from PyPI at
# install time — keeps the bundle tiny, picks up every PyPI release).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$ROOT/dxt"
OUT_DIR="$ROOT/site/downloads"
OUT_FILE="$OUT_DIR/autonomath-mcp.mcpb"
DIST_DIR="$ROOT/dist"

mkdir -p "$OUT_DIR"
mkdir -p "$DIST_DIR"

# Pick a Python with tomllib (3.11+). Prefer .venv, fall back to system.
PY_BIN="python3"
if [ -x "$ROOT/.venv/bin/python" ]; then
    PY_BIN="$ROOT/.venv/bin/python"
fi

# Validate manifest.json is valid JSON before bundling.
"$PY_BIN" -m json.tool "$SRC_DIR/manifest.json" > /dev/null

# Assert version alignment with pyproject.toml + server.json.
MF_VER="$("$PY_BIN" -c 'import json; print(json.load(open("'"$SRC_DIR"'/manifest.json"))["version"])')"
PY_VER="$("$PY_BIN" -c 'import tomllib; print(tomllib.load(open("'"$ROOT"'/pyproject.toml","rb"))["project"]["version"])')"
SRV_VER="$("$PY_BIN" -c 'import json; print(json.load(open("'"$ROOT"'/server.json"))["version"])')"
if [ "$MF_VER" != "$PY_VER" ] || [ "$MF_VER" != "$SRV_VER" ]; then
    echo "ERROR: version mismatch (manifest=$MF_VER pyproject=$PY_VER server.json=$SRV_VER)" >&2
    exit 1
fi

rm -f "$OUT_FILE"
# Bundle every file in dxt/ (manifest.json + icon.png + README.md if present)
# into the .mcpb. Matches v0.3.0 bundle composition.
( cd "$SRC_DIR" && zip -q -X "$OUT_FILE" manifest.json $( [ -f icon.png ] && echo icon.png ) $( [ -f README.md ] && echo README.md ) )

# Mirror the bundle into dist/ with the version-stamped name so downstream
# publish scripts can verify the version-pinned artifact.
DIST_FILE="$DIST_DIR/autonomath-mcp-$MF_VER.mcpb"
cp -f "$OUT_FILE" "$DIST_FILE"

echo "built: $OUT_FILE"
echo "mirrored: $DIST_FILE"
unzip -l "$OUT_FILE"
