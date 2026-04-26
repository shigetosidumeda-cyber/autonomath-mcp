#!/usr/bin/env bash
# Rewrite [PACKAGE_NAME] / [DOMAIN] / [GH_ORG] / [GH_REPO] / [AUTHOR] placeholders
# across MCP-registry submission artifacts once the rebrand is finalized.
#
# Rebrand is pending per user memory: project_jpintel_trademark_intel_risk
# (jpintel / Intel collision risk; candidates: jpi-data, jpinst, JGI).
#
# Usage:
#   scripts/rebrand_mcp_entries.sh                      # dry-run (default)
#   scripts/rebrand_mcp_entries.sh --apply              # actually write files
#   scripts/rebrand_mcp_entries.sh --apply --vars=./scripts/rebrand_vars.env
#
# A vars file (`scripts/rebrand_vars.env`) looks like:
#   PACKAGE_NAME=jpi-data
#   DOMAIN=jpidata.jp
#   GH_ORG=shigetoumeda
#   GH_REPO=jpi-data-mcp
#   AUTHOR="Shigetoumeda Umeda"
#
# Safety:
#   - Default is dry-run: prints planned substitutions, no file writes.
#   - --apply requires all 5 vars to be non-empty.
#   - Refuses to run if git working tree has unstaged changes to any target file
#     (protects review-in-progress).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APPLY=0
VARS_FILE=""

for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --vars=*) VARS_FILE="${arg#--vars=}" ;;
    --help|-h)
      sed -n '1,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

# Load vars
if [[ -n "$VARS_FILE" ]]; then
  [[ -f "$VARS_FILE" ]] || { echo "vars file not found: $VARS_FILE" >&2; exit 2; }
  # shellcheck disable=SC1090
  set -a; source "$VARS_FILE"; set +a
fi

: "${PACKAGE_NAME:=}"
: "${DOMAIN:=}"
: "${GH_ORG:=}"
: "${GH_REPO:=}"
: "${AUTHOR:=}"

if [[ "$APPLY" -eq 1 ]]; then
  missing=()
  for v in PACKAGE_NAME DOMAIN GH_ORG GH_REPO AUTHOR; do
    if [[ -z "${!v}" ]]; then missing+=("$v"); fi
  done
  if (( ${#missing[@]} > 0 )); then
    echo "ERROR: missing required vars for --apply: ${missing[*]}" >&2
    echo "Supply them via env or --vars=FILE" >&2
    exit 2
  fi
fi

# Files we rewrite. Keep this list explicit — never use `git grep -l` style
# auto-discovery, which could hit generated or bundled third-party content.
#
# Submission drafts live under docs/_internal/ (operational-only, not surfaced
# in the rendered docs site per README convention).
TARGETS=(
  "mcp-server.json"
  "smithery.yaml"
  "README.md"
  "docs/_internal/mcp_registry_submissions/README.md"
  "docs/_internal/mcp_registry_submissions/official_registry_submission.md"
  "docs/_internal/mcp_registry_submissions/glama_submission.md"
  "docs/_internal/mcp_registry_submissions/mcphub_tools_submission.md"
  "docs/_internal/mcp_registry_submissions/smithery_submission.md"
  "docs/_internal/mcp_registry_submissions/modelcontextprotocol_pr.md"
)

# Abort if any target has unstaged changes (protects review diff).
if [[ "$APPLY" -eq 1 ]] && command -v git >/dev/null 2>&1 && [[ -d .git ]]; then
  dirty=$(git status --porcelain "${TARGETS[@]}" 2>/dev/null || true)
  if [[ -n "$dirty" ]]; then
    echo "ERROR: target files have unstaged changes. Commit or stash first." >&2
    echo "$dirty" >&2
    exit 3
  fi
fi

# Sub set. Order matters if any placeholder is a substring of another
# (currently none, but future-proof: longest first).
declare -a KEYS=("PACKAGE_NAME" "DOMAIN" "GH_ORG" "GH_REPO" "AUTHOR")

rewrite_file() {
  local f="$1"
  [[ -f "$f" ]] || { echo "  skip (not found): $f" >&2; return 0; }

  # Count placeholders before. Matches both [DOMAIN] (our convention) and
  # {{DOMAIN}} (MkDocs/linter-added convention for the rendered-docs block
  # introduced post-initial-draft). Both get the same substitution.
  local before
  # `|| true` so pipefail doesn't kill us when grep finds zero matches
  before=$({ grep -Eo '(\[|\{\{)(PACKAGE_NAME|DOMAIN|GH_ORG|GH_REPO|AUTHOR)(\]|\}\})' "$f" || true; } | wc -l | tr -d ' ')

  if [[ "$before" == "0" ]]; then
    echo "  no placeholders: $f"
    return 0
  fi

  if [[ "$APPLY" -eq 0 ]]; then
    echo "  would rewrite $before placeholders in: $f"
    return 0
  fi

  # Stream via perl so we can do literal substring replacement safely (sed's
  # `[...]` is a bracket class; escaping is fiddly). Perl with `quotemeta`
  # quotes the LHS literally.
  local tmp
  tmp=$(mktemp)
  # shellcheck disable=SC2016
  perl -pe '
    BEGIN {
      %m = (
        "[PACKAGE_NAME]" => $ENV{"PACKAGE_NAME"},
        "[DOMAIN]"       => $ENV{"DOMAIN"},
        "[GH_ORG]"       => $ENV{"GH_ORG"},
        "[GH_REPO]"      => $ENV{"GH_REPO"},
        "[AUTHOR]"       => $ENV{"AUTHOR"},
        "{{PACKAGE_NAME}}" => $ENV{"PACKAGE_NAME"},
        "{{DOMAIN}}"       => $ENV{"DOMAIN"},
        "{{GH_ORG}}"       => $ENV{"GH_ORG"},
        "{{GH_REPO}}"      => $ENV{"GH_REPO"},
        "{{AUTHOR}}"       => $ENV{"AUTHOR"},
      );
    }
    for my $k (keys %m) {
      my $qk = quotemeta($k);
      s/$qk/$m{$k}/g;
    }
  ' "$f" > "$tmp"

  local after
  after=$({ grep -Eo '(\[|\{\{)(PACKAGE_NAME|DOMAIN|GH_ORG|GH_REPO|AUTHOR)(\]|\}\})' "$tmp" || true; } | wc -l | tr -d ' ')

  mv "$tmp" "$f"
  echo "  rewrote $before → $after remaining in: $f"
}

echo "== MCP registry rebrand rewrite =="
if [[ "$APPLY" -eq 0 ]]; then
  echo "   (dry run — pass --apply to write)"
else
  printf "   applying: PACKAGE_NAME=%s DOMAIN=%s GH_ORG=%s GH_REPO=%s AUTHOR=%s\n" \
    "$PACKAGE_NAME" "$DOMAIN" "$GH_ORG" "$GH_REPO" "$AUTHOR"
fi
echo

export PACKAGE_NAME DOMAIN GH_ORG GH_REPO AUTHOR
for t in "${TARGETS[@]}"; do
  rewrite_file "$t"
done

echo
echo "done."
if [[ "$APPLY" -eq 0 ]]; then
  echo "re-run with --apply to write changes."
fi
