#!/usr/bin/env bash
# rollback_capsule.sh - Atomic rollback of Cloudflare Pages release capsule pointer.
#
# Usage:
#   scripts/ops/rollback_capsule.sh <previous_capsule_id>
#
# Behaviour:
#   - Reads site/releases/current/runtime_pointer.json
#   - Rewrites .active_capsule_id and .active_capsule_manifest using a Python
#     json round-trip (NOT sed) so that the JSON structure stays canonical.
#   - Writes to a temp file first, then mv-renames into place for atomicity
#     so a Cloudflare Pages build cannot read a half-written pointer file.
#   - Leaves a sibling .bak file with the original pointer (one slot only,
#     overwritten on each invocation) for one-step recovery.
#
# Notes:
#   - Does NOT validate that the target capsule directory exists on disk.
#     The companion list_capsules.sh script is the human-eyes pre-check.
#   - Does NOT touch the production functions/release/[[path]].ts handler.
#     The handler reads runtime_pointer.json at edge request time and will
#     pick up the new pointer on the next request once Cloudflare Pages
#     redeploys the static asset (handled by pages-rollback.yml workflow).

set -euo pipefail

if [[ "${1:-}" == "" ]]; then
  echo "usage: $0 <previous_capsule_id>" >&2
  exit 2
fi

PREV_CAPSULE_ID="$1"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
POINTER_PATH="${REPO_ROOT}/site/releases/current/runtime_pointer.json"

if [[ ! -f "${POINTER_PATH}" ]]; then
  echo "fatal: runtime_pointer.json not found at ${POINTER_PATH}" >&2
  exit 1
fi

TMP_PATH="${POINTER_PATH}.tmp.$$"
BAK_PATH="${POINTER_PATH}.bak"

cp -p "${POINTER_PATH}" "${BAK_PATH}"

PREV_CAPSULE_ID="${PREV_CAPSULE_ID}" POINTER_PATH="${POINTER_PATH}" TMP_PATH="${TMP_PATH}" python3 <<'PYEOF'
import json
import os
import sys

pointer_path = os.environ["POINTER_PATH"]
tmp_path = os.environ["TMP_PATH"]
prev = os.environ["PREV_CAPSULE_ID"]

with open(pointer_path, "r", encoding="utf-8") as fh:
    pointer = json.load(fh)

if not isinstance(pointer, dict):
    print("fatal: runtime_pointer.json root is not an object", file=sys.stderr)
    sys.exit(3)

# Derive the capsule directory slug from the capsule id.
# Convention: capsule_id = <slug>-YYYY-MM-DD (slug may itself contain hyphens).
# active_capsule_manifest = /releases/<slug>/release_capsule_manifest.json
# The runtime handler in functions/release/[[path]].ts validates the path
# against an allow-list, so we mirror its format exactly.
parts = prev.rsplit("-", 3)
if len(parts) >= 4 and all(p.isdigit() for p in parts[-3:]):
    slug = parts[0]
else:
    slug = prev

pointer["active_capsule_id"] = prev
pointer["active_capsule_manifest"] = f"/releases/{slug}/release_capsule_manifest.json"

# Re-affirm safety flags so a rollback does not silently flip the
# AWS-runtime gate open (the edge handler treats either flag != false
# as a refuse-to-serve signal).
pointer["aws_runtime_dependency_allowed"] = False
pointer["live_aws_commands_allowed"] = False

with open(tmp_path, "w", encoding="utf-8") as fh:
    json.dump(pointer, fh, indent=2, ensure_ascii=False, sort_keys=True)
    fh.write("\n")
PYEOF

mv -f "${TMP_PATH}" "${POINTER_PATH}"

echo "rollback_capsule: active_capsule_id -> ${PREV_CAPSULE_ID}"
echo "rollback_capsule: pointer written ${POINTER_PATH}"
echo "rollback_capsule: previous pointer backed up ${BAK_PATH}"
