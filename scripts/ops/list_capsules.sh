#!/usr/bin/env bash
# list_capsules.sh - Enumerate release capsules under site/releases/ and show
# the manifest summary for each. Read-only; safe to run any time.
#
# Usage:
#   scripts/ops/list_capsules.sh
#
# Output columns:
#   capsule_dir | manifest_present | release_capsule_id | capsule_state
#
# A 'current' directory is included as an active-pointer marker; its
# runtime_pointer.json is parsed for the live capsule id.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RELEASES_DIR="${REPO_ROOT}/site/releases"

if [[ ! -d "${RELEASES_DIR}" ]]; then
  echo "fatal: ${RELEASES_DIR} not found" >&2
  exit 1
fi

printf '%-44s %-9s %-44s %-10s\n' "capsule_dir" "manifest" "release_capsule_id" "state"
printf '%-44s %-9s %-44s %-10s\n' "----------------------------------------" "---------" "----------------------------------------" "----------"

for entry in "${RELEASES_DIR}"/*/; do
  dir_name="$(basename "${entry%/}")"
  manifest="${entry}release_capsule_manifest.json"
  pointer="${entry}runtime_pointer.json"

  if [[ "${dir_name}" == "current" && -f "${pointer}" ]]; then
    POINTER_PATH="${pointer}" python3 <<'PYEOF' || true
import json
import os
import sys

path = os.environ["POINTER_PATH"]
with open(path, "r", encoding="utf-8") as fh:
    p = json.load(fh)
cap_id = p.get("active_capsule_id", "(unknown)")
state = p.get("capsule_state", "(unknown)")
print(f"{'current':<44} {'pointer':<9} {cap_id:<44} {state:<10}")
PYEOF
    continue
  fi

  if [[ -f "${manifest}" ]]; then
    MANIFEST_PATH="${manifest}" DIR_NAME="${dir_name}" python3 <<'PYEOF' || true
import json
import os

path = os.environ["MANIFEST_PATH"]
dir_name = os.environ["DIR_NAME"]
try:
    with open(path, "r", encoding="utf-8") as fh:
        m = json.load(fh)
except Exception as exc:  # noqa: BLE001
    print(f"{dir_name:<44} {'YES':<9} {'(parse error: ' + str(exc)[:24] + ')':<44} {'(n/a)':<10}")
    raise SystemExit

cap_id = m.get("release_capsule_id") or m.get("capsule_id") or "(unknown)"
state = m.get("capsule_state") or m.get("state") or "(unknown)"
print(f"{dir_name:<44} {'YES':<9} {str(cap_id):<44} {str(state):<10}")
PYEOF
  else
    printf '%-44s %-9s %-44s %-10s\n' "${dir_name}" "NO" "(no manifest)" "(n/a)"
  fi
done
