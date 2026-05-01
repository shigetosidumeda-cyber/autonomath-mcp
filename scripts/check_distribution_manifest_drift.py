#!/usr/bin/env python3
"""Distribution manifest drift checker.

Source of truth: ``scripts/distribution_manifest.yml`` (hand-edited).

For each manifest field, this script scans a hard-coded list of distribution
surfaces (``server.json``, ``mcp-server.json``, ``dxt/manifest.json``,
``smithery.yaml``, ``scripts/mcp_registries_submission.json``,
``pyproject.toml``, ``README.md``, ``site/llms.txt``, ``CLAUDE.md``,
``sdk/python/autonomath/_shared.py``) and:

  * for ``canonical_*`` and version fields: verifies the canonical value
    appears (best-effort substring match);
  * for ``forbidden_tokens``: verifies the legacy strings are absent from
    surfaces not listed in ``forbidden_token_exclude_paths``;
  * for ``tool_count_default_gates``: verifies a numeric mention matches the
    canonical count using the same patterns as
    ``check_tool_count_consistency.py``.

Output: a pretty table of (field, expected, file, observed, status) rows.
Exits 1 on any drift; 0 if clean. ``--fix`` prints suggested edits but does
NOT auto-apply (manual review required per §28.9).

Constraints:
  * No LLM imports.
  * Runs in <5s locally (no DB, no runtime server boot — runtime probe lives
    in ``probe_runtime_distribution.py``).
  * PyYAML is loaded if available; falls back to a small flat parser otherwise.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = Path(__file__).resolve().parent / "distribution_manifest.yml"

# Hard-coded list of distribution surfaces to scan.
# These are the files customers / AI crawlers / MCP registries fetch.
SURFACES: list[Path] = [
    REPO_ROOT / "server.json",
    REPO_ROOT / "mcp-server.json",
    REPO_ROOT / "dxt" / "manifest.json",
    REPO_ROOT / "smithery.yaml",
    REPO_ROOT / "scripts" / "mcp_registries_submission.json",
    REPO_ROOT / "pyproject.toml",
    REPO_ROOT / "README.md",
    REPO_ROOT / "site" / "llms.txt",
    REPO_ROOT / "CLAUDE.md",
    REPO_ROOT / "sdk" / "python" / "autonomath" / "_shared.py",
]

# Pattern shape for tool-count surface mentions (matches
# check_tool_count_consistency.py so the two checkers agree on language).
TOOL_COUNT_PATTERNS = [
    re.compile(r"\b(\d{2,3}) MCP tools\b"),
    re.compile(r"\b(\d{2,3}) tools at default gates\b"),
    re.compile(r"\b(\d{2,3}) tools \(protocol "),
    re.compile(r"\b(\d{2,3}) tools, protocol "),
    re.compile(r"\b(\d{2,3})-tool MCP\b"),
    re.compile(r"\b(\d{2,3})-tool surface\b"),
    re.compile(r'"tool_count":\s*(\d{2,3})'),
]

# Patterns for route count.
ROUTE_COUNT_PATTERNS = [
    re.compile(r"\b(\d{2,3}) routes\b"),
    re.compile(r'"route_count":\s*(\d{2,3})'),
]


def _load_manifest_from(path: Path) -> dict[str, Any]:
    """Return the parsed manifest. Uses PyYAML if installed, else flat parser."""
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]

        return yaml.safe_load(text)
    except ImportError:
        return _flat_yaml_parse(text)


def _load_manifest() -> dict[str, Any]:
    """Default-path convenience wrapper used by tests + interactive runs."""
    return _load_manifest_from(MANIFEST_PATH)


def _flat_yaml_parse(text: str) -> dict[str, Any]:
    """Tiny YAML subset parser for the simple schema used by distribution_manifest.yml.

    Supports:
      * top-level scalar keys (``key: value``)
      * one-level nested mapping (``parent:`` then indented ``key: value`` lines)
      * top-level list of scalars (``key:`` followed by ``  - item`` lines)
    """
    data: dict[str, Any] = {}
    current_parent: str | None = None
    current_list_key: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        if indent == 0:
            current_parent = None
            current_list_key = None
            if ":" not in stripped:
                continue
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            if value == "":
                # parent of a sub-map or list
                data[key] = None
                current_parent = key
                current_list_key = key
            else:
                data[key] = _strip_quotes(value)
        else:
            # nested
            if stripped.startswith("- "):
                # list item under current_list_key
                if current_list_key is None:
                    continue
                if not isinstance(data.get(current_list_key), list):
                    data[current_list_key] = []
                data[current_list_key].append(_strip_quotes(stripped[2:].strip()))
            elif ":" in stripped:
                key, _, value = stripped.partition(":")
                if current_parent is None:
                    continue
                if not isinstance(data.get(current_parent), dict):
                    data[current_parent] = {}
                data[current_parent][key.strip()] = _strip_quotes(value.strip())
    return data


def _strip_quotes(value: str) -> Any:
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    if value.isdigit():
        return int(value)
    return value


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


# A drift row.
class DriftRow:
    __slots__ = ("field", "expected", "file", "observed", "status", "line_no", "hint")

    def __init__(
        self,
        field: str,
        expected: Any,
        file: str,
        observed: str,
        status: str,
        line_no: int = 0,
        hint: str = "",
    ) -> None:
        self.field = field
        self.expected = expected
        self.file = file
        self.observed = observed
        self.status = status
        self.line_no = line_no
        self.hint = hint


def _scan_forbidden_tokens(
    manifest: dict[str, Any],
) -> list[DriftRow]:
    rows: list[DriftRow] = []
    forbidden = manifest.get("forbidden_tokens") or []
    excludes = manifest.get("forbidden_token_exclude_paths") or []

    if not isinstance(forbidden, list) or not isinstance(excludes, list):
        return rows

    for surface in SURFACES:
        rel = str(surface.relative_to(REPO_ROOT))
        if any(frag in rel for frag in excludes):
            continue
        if not surface.exists():
            continue
        text = _read(surface)
        for line_no, line in enumerate(text.splitlines(), 1):
            for token in forbidden:
                if token and token in line:
                    rows.append(
                        DriftRow(
                            field=f"forbidden:{token}",
                            expected="(absent)",
                            file=rel,
                            observed=line.strip()[:100],
                            status="DRIFT",
                            line_no=line_no,
                            hint=f"Replace '{token}' with the canonical equivalent or move text into an excluded path.",
                        )
                    )
    return rows


def _scan_canonical_values(
    manifest: dict[str, Any],
) -> list[DriftRow]:
    """Verify canonical_* values appear at least once in each relevant surface."""
    rows: list[DriftRow] = []
    site = (manifest.get("canonical_domains") or {}).get("site", "")
    pkg = manifest.get("canonical_mcp_package", "")
    repo = manifest.get("canonical_repo", "")
    env_key = (manifest.get("canonical_api_env") or {}).get("api_key", "")
    env_base = (manifest.get("canonical_api_env") or {}).get("api_base", "")
    version = str(manifest.get("pyproject_version", ""))

    # Per-file expectation: each surface should at minimum reference the
    # canonical site domain (this is the strongest "is this still ours?" probe).
    # Stricter checks below for files where a specific value is load-bearing.
    for surface in SURFACES:
        rel = str(surface.relative_to(REPO_ROOT))
        if not surface.exists():
            rows.append(
                DriftRow(
                    field="surface",
                    expected="(file present)",
                    file=rel,
                    observed="(missing)",
                    status="MISSING",
                    hint="File listed in SURFACES does not exist.",
                )
            )
            continue
        text = _read(surface)

        # Site domain — every distribution surface should mention it.
        if site and site not in text and "jpcite.com" not in text:
            rows.append(
                DriftRow(
                    field="canonical_domains.site",
                    expected=site,
                    file=rel,
                    observed="(not found)",
                    status="DRIFT",
                    hint=f"Add a reference to {site}.",
                )
            )

        # canonical_mcp_package — every surface that names a package should
        # use the canonical name. The drift surfaces here for the surfaces
        # that do mention a package at all.
        names_a_package = any(
            kw in text for kw in ("autonomath-mcp", "jpintel-mcp", "package", "pypi")
        )
        if pkg and names_a_package and pkg not in text:
            rows.append(
                DriftRow(
                    field="canonical_mcp_package",
                    expected=pkg,
                    file=rel,
                    observed="(canonical not found despite package mentions)",
                    status="DRIFT",
                    hint=f"Use {pkg} as the package name.",
                )
            )

    # Version: pyproject + manifest JSONs must match the manifest version.
    version_strict_files = [
        REPO_ROOT / "server.json",
        REPO_ROOT / "mcp-server.json",
        REPO_ROOT / "dxt" / "manifest.json",
        REPO_ROOT / "smithery.yaml",
        REPO_ROOT / "scripts" / "mcp_registries_submission.json",
        REPO_ROOT / "pyproject.toml",
    ]
    for surface in version_strict_files:
        if not surface.exists():
            continue
        rel = str(surface.relative_to(REPO_ROOT))
        text = _read(surface)
        # Look for any "version": "X" or version: X declaration.
        found_versions: set[str] = set()
        for m in re.finditer(
            r'(?:^|[^a-zA-Z0-9_])version["\']?\s*[:=]\s*["\']?(\d+\.\d+\.\d+)', text
        ):
            found_versions.add(m.group(1))
        if not found_versions:
            continue
        if version not in found_versions:
            rows.append(
                DriftRow(
                    field="pyproject_version",
                    expected=version,
                    file=rel,
                    observed=", ".join(sorted(found_versions)),
                    status="DRIFT",
                    hint=f"Bump version declarations to {version}.",
                )
            )

    # Repo: pyproject + smithery + server.json + dxt + mcp-server should reference
    # the canonical repo path.
    repo_strict_files = [
        REPO_ROOT / "server.json",
        REPO_ROOT / "mcp-server.json",
        REPO_ROOT / "dxt" / "manifest.json",
        REPO_ROOT / "smithery.yaml",
        REPO_ROOT / "scripts" / "mcp_registries_submission.json",
        REPO_ROOT / "pyproject.toml",
        REPO_ROOT / "README.md",
    ]
    for surface in repo_strict_files:
        if not surface.exists():
            continue
        rel = str(surface.relative_to(REPO_ROOT))
        text = _read(surface)
        if "github.com/shigetosidumeda-cyber" not in text and "github.com/AutonoMath" not in text:
            continue  # surface does not reference a repo at all
        if repo and repo not in text:
            rows.append(
                DriftRow(
                    field="canonical_repo",
                    expected=repo,
                    file=rel,
                    observed="(canonical repo path absent despite github.com/ mentions)",
                    status="DRIFT",
                    hint=f"Use github.com/{repo} as the repo URL.",
                )
            )

    # Env names: README + smithery + dxt + sdk shared must use JPCITE_* as the
    # canonical names. AUTONOMATH_* may remain only as an explicit legacy alias;
    # JPINTEL_* is an older internal name and should not appear.
    env_strict_files = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "smithery.yaml",
        REPO_ROOT / "dxt" / "manifest.json",
        REPO_ROOT / "sdk" / "python" / "autonomath" / "_shared.py",
    ]
    for surface in env_strict_files:
        if not surface.exists():
            continue
        rel = str(surface.relative_to(REPO_ROOT))
        text = _read(surface)
        if "JPINTEL_API_KEY" in text:
            rows.append(
                DriftRow(
                    field="canonical_api_env.api_key",
                    expected=env_key,
                    file=rel,
                    observed="JPINTEL_API_KEY",
                    status="DRIFT",
                    hint=f"Rename JPINTEL_API_KEY to {env_key}.",
                )
            )
        if "JPINTEL_API_BASE" in text:
            rows.append(
                DriftRow(
                    field="canonical_api_env.api_base",
                    expected=env_base,
                    file=rel,
                    observed="JPINTEL_API_BASE",
                    status="DRIFT",
                    hint=f"Rename JPINTEL_API_BASE to {env_base}.",
                )
            )
        if "AUTONOMATH_API_KEY" in text and env_key not in text:
            rows.append(
                DriftRow(
                    field="canonical_api_env.api_key",
                    expected=env_key,
                    file=rel,
                    observed="AUTONOMATH_API_KEY without canonical JPCITE alias",
                    status="DRIFT",
                    hint=(
                        f"Prefer {env_key}; keep AUTONOMATH_API_KEY only as "
                        "an explicitly documented legacy alias."
                    ),
                )
            )
        if "AUTONOMATH_API_BASE" in text and env_base not in text:
            rows.append(
                DriftRow(
                    field="canonical_api_env.api_base",
                    expected=env_base,
                    file=rel,
                    observed="AUTONOMATH_API_BASE without canonical JPCITE alias",
                    status="DRIFT",
                    hint=(
                        f"Prefer {env_base}; keep AUTONOMATH_API_BASE only as "
                        "an explicitly documented legacy alias."
                    ),
                )
            )

    return rows


def _scan_tool_count(manifest: dict[str, Any]) -> list[DriftRow]:
    rows: list[DriftRow] = []
    expected = manifest.get("tool_count_default_gates")
    if expected is None:
        return rows
    expected_int = int(expected)
    for surface in SURFACES:
        if not surface.exists():
            continue
        rel = str(surface.relative_to(REPO_ROOT))
        text = _read(surface)
        for line_no, line in enumerate(text.splitlines(), 1):
            for pat in TOOL_COUNT_PATTERNS:
                for m in pat.finditer(line):
                    found = int(m.group(1))
                    if found != expected_int and 50 <= found <= 100:
                        rows.append(
                            DriftRow(
                                field="tool_count_default_gates",
                                expected=expected_int,
                                file=rel,
                                observed=f"{found} (line: {line.strip()[:80]})",
                                status="DRIFT",
                                line_no=line_no,
                                hint=f"Update to {expected_int}.",
                            )
                        )
    return rows


def _scan_route_count(manifest: dict[str, Any]) -> list[DriftRow]:
    rows: list[DriftRow] = []
    expected = manifest.get("route_count")
    if expected is None:
        return rows
    expected_int = int(expected)
    for surface in SURFACES:
        if not surface.exists():
            continue
        rel = str(surface.relative_to(REPO_ROOT))
        text = _read(surface)
        for line_no, line in enumerate(text.splitlines(), 1):
            for pat in ROUTE_COUNT_PATTERNS:
                for m in pat.finditer(line):
                    found = int(m.group(1))
                    if found != expected_int and 50 <= found <= 500:
                        rows.append(
                            DriftRow(
                                field="route_count",
                                expected=expected_int,
                                file=rel,
                                observed=f"{found} (line: {line.strip()[:80]})",
                                status="DRIFT",
                                line_no=line_no,
                                hint=f"Update to {expected_int}.",
                            )
                        )
    return rows


def _format_table(rows: list[DriftRow]) -> str:
    if not rows:
        return "(no drift)"
    headers = ["field", "expected", "file", "observed", "status"]
    cols = [
        [r.field for r in rows],
        [str(r.expected)[:48] for r in rows],
        [r.file + (f":{r.line_no}" if r.line_no else "") for r in rows],
        [r.observed[:80] for r in rows],
        [r.status for r in rows],
    ]
    widths = [max(len(headers[i]), max((len(c) for c in cols[i]), default=0)) for i in range(5)]
    out_lines = []
    sep = "  "
    out_lines.append(sep.join(headers[i].ljust(widths[i]) for i in range(5)))
    out_lines.append(sep.join("-" * widths[i] for i in range(5)))
    for i in range(len(rows)):
        out_lines.append(sep.join(cols[c][i].ljust(widths[c]) for c in range(5)))
    return "\n".join(out_lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Print suggested edits (does NOT auto-apply; manual review required).",
    )
    parser.add_argument(
        "--manifest",
        default=str(MANIFEST_PATH),
        help="Path to distribution_manifest.yml (default: scripts/distribution_manifest.yml).",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        sys.stderr.write(f"manifest not found: {manifest_path}\n")
        return 2

    manifest = _load_manifest_from(manifest_path)

    rows: list[DriftRow] = []
    rows.extend(_scan_canonical_values(manifest))
    rows.extend(_scan_forbidden_tokens(manifest))
    rows.extend(_scan_tool_count(manifest))
    rows.extend(_scan_route_count(manifest))

    if not rows:
        print(
            "[check_distribution_manifest_drift] OK — manifest is consistent across all surfaces."
        )
        return 0

    print(
        f"[check_distribution_manifest_drift] DRIFT — {len(rows)} issue(s) "
        f"across {len({r.file for r in rows})} surface(s):\n"
    )
    print(_format_table(rows))

    if args.fix:
        print("\nSuggested edits (manual review required):\n")
        for r in rows:
            location = r.file + (f":{r.line_no}" if r.line_no else "")
            print(f"  - {location}  [{r.field}]\n      {r.hint}")
    else:
        print("\nRun with --fix to print suggested edits. Manual review required (no auto-apply).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
