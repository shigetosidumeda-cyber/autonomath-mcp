#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== jpintel-mcp bootstrap ==="
python3 -m venv .venv 2>/dev/null || true
source .venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -e ".[dev]"

mkdir -p data

echo "=== init schema ==="
python3 -c "from jpintel_mcp.db.session import init_db; init_db()"

echo "=== ingest from Autonomath ==="
python3 -m jpintel_mcp.ingest.canonical

# autonomath.db (7.3 GB companion DB) — optional fetch from R2 or equivalent.
# Both env vars must be set to enable the fetch; if unset, this step is skipped
# and AUTONOMATH_ENABLED=false should be used until the DB is placed manually.
#
#   AUTONOMATH_DB_URL       pre-signed URL or public R2 endpoint for autonomath.db
#   AUTONOMATH_DB_SHA256    expected SHA-256 of the file (hex, lowercase)
#
# The fetch is idempotent: an existing file whose SHA-256 already matches is
# kept as-is. A mismatched file is re-downloaded rather than silently accepted.
if [[ -n "${AUTONOMATH_DB_URL:-}" && -n "${AUTONOMATH_DB_SHA256:-}" ]]; then
    echo "=== autonomath.db fetch ==="
    target="autonomath.db"
    expected="${AUTONOMATH_DB_SHA256}"

    verify_sha256() {
        if [[ ! -f "$1" ]]; then
            return 1
        fi
        if command -v sha256sum >/dev/null 2>&1; then
            actual=$(sha256sum "$1" | awk '{print $1}')
        else
            actual=$(shasum -a 256 "$1" | awk '{print $1}')
        fi
        [[ "$actual" == "$expected" ]]
    }

    if verify_sha256 "$target"; then
        echo "  autonomath.db already present + sha256 matches, skipping fetch"
    else
        if [[ -f "$target" ]]; then
            echo "  autonomath.db present but sha256 mismatch — redownloading"
            rm -f "$target"
        fi
        echo "  downloading from \$AUTONOMATH_DB_URL"
        if command -v curl >/dev/null 2>&1; then
            curl --fail --location --retry 3 --output "$target" "$AUTONOMATH_DB_URL"
        else
            wget --tries=3 --output-document="$target" "$AUTONOMATH_DB_URL"
        fi
        if ! verify_sha256 "$target"; then
            echo "  ERROR: sha256 mismatch after download (expected $expected)" >&2
            rm -f "$target"
            exit 1
        fi
        echo "  autonomath.db verified ($(ls -l "$target" | awk '{print $5}') bytes)"
    fi
else
    echo "=== autonomath.db fetch skipped (AUTONOMATH_DB_URL / AUTONOMATH_DB_SHA256 unset) ==="
fi

echo "=== done ==="
python3 -c "
import sqlite3
conn = sqlite3.connect('data/jpintel.db')
for tbl in ('programs','exclusion_rules'):
    (n,) = conn.execute(f'SELECT COUNT(*) FROM {tbl}').fetchone()
    print(f'  {tbl}: {n}')
"
