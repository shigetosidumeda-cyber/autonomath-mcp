#!/usr/bin/env python3
"""Read-only distribution manifest drift checker.

Source of truth: ``scripts/distribution_manifest.yml``.

The checker performs static-file validation only. It does not boot the API, it
does not contact the network, and it never writes fixes. Runtime route/tool
verification remains in ``scripts/probe_runtime_distribution.py``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = Path(__file__).resolve().parent / "distribution_manifest.yml"

DEFAULT_DISTRIBUTION_SURFACES = [
    "README.md",
    "pyproject.toml",
    "mcp-server.json",
    "dxt/manifest.json",
    "docs/openapi/v1.json",
    "site/llms.txt",
]

AGENT_OPENAPI_PACKAGE_SCAN_EXCLUDES = {
    "docs/openapi/agent.json",
    "site/openapi.agent.json",
}

TOOL_COUNT_PATTERNS = [
    re.compile(r"\b(\d{2,3})\s+MCP tools\b", re.IGNORECASE),
    re.compile(r"\bMCP tools\s*\((\d{2,3})\)", re.IGNORECASE),
    re.compile(r"\bMCP\s+\*\*(\d{2,3})\s+tools\*\*", re.IGNORECASE),
    re.compile(r"\bMCP exposes\s+(\d{2,3})\s+tools\b", re.IGNORECASE),
    re.compile(r"\b(\d{2,3})\s+tools at default gates\b", re.IGNORECASE),
    re.compile(r"\b(\d{2,3})\s+tools in the standard public configuration\b", re.IGNORECASE),
    re.compile(r"\b(\d{2,3})\s+tools in the standard configuration\b", re.IGNORECASE),
    re.compile(r"\b(\d{2,3})\s+tools \(protocol\b", re.IGNORECASE),
    re.compile(r"\b(\d{2,3})\s+tools, protocol\b", re.IGNORECASE),
    re.compile(r"\b(\d{2,3})\s+tools live\b", re.IGNORECASE),
    re.compile(r"\b(\d{2,3})\s+tools\b", re.IGNORECASE),
    re.compile(r"\b(\d{2,3})-tool MCP\b", re.IGNORECASE),
    re.compile(r"\b(\d{2,3})-tool surface\b", re.IGNORECASE),
    re.compile(r'"tool_count"\s*:\s*(\d{2,3})', re.IGNORECASE),
]

OPENAPI_PATH_COUNT_PATTERNS = [
    re.compile(r"\b(\d{2,3})\s+public paths\b", re.IGNORECASE),
    re.compile(r"\b(\d{2,3})\s+paths\b", re.IGNORECASE),
]

PRICE_PATTERNS = [
    re.compile(r"¥\s*3(?:\.00)?(?:\b|/|円|リクエスト|request)", re.IGNORECASE),
    re.compile(r"\bJPY\s*3\b", re.IGNORECASE),
    re.compile(r"\b3\s*yen/req\b", re.IGNORECASE),
    re.compile(r"\b3\s*yen\b", re.IGNORECASE),
    re.compile(r"税別\s*3円", re.IGNORECASE),
    re.compile(r"1リクエスト税別3円", re.IGNORECASE),
]

TAX_INCLUDED_PATTERNS = [
    re.compile(r"¥\s*3\.30", re.IGNORECASE),
    re.compile(r"\b3\.30\s+tax-incl\b", re.IGNORECASE),
    re.compile(r"税込\s*¥?\s*3\.30", re.IGNORECASE),
    re.compile(r"税込3\.30円", re.IGNORECASE),
]

FREE_TIER_PATTERNS = [
    re.compile(r"\b3\s*free/day\b", re.IGNORECASE),
    re.compile(r"\b3/day\b", re.IGNORECASE),
    re.compile(r"\b3\s*(?:req|requests)\s*/\s*(?:日|day)\b", re.IGNORECASE),
    re.compile(r"\b3\s*(?:req|requests)\s+per\s+(?:IP\s+)?day\b", re.IGNORECASE),
    re.compile(r"\bFirst\s+3\s+requests/day\s+free\b", re.IGNORECASE),
    re.compile(r"匿名\s*3\s*req/日", re.IGNORECASE),
    re.compile(r"1\s*IP\s*あたり\s*1\s*日\s*3\s*(?:回|リクエスト)", re.IGNORECASE),
]

SUSPECT_TOOL_COUNT_RANGE = range(50, 301)


def _load_manifest_from(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]

        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except ImportError:
        return _flat_yaml_parse(text)


def _load_manifest() -> dict[str, Any]:
    return _load_manifest_from(MANIFEST_PATH)


def _flat_yaml_parse(text: str) -> dict[str, Any]:
    """Parse the small YAML subset used by distribution_manifest.yml.

    Supports top-level scalars, one-level nested mappings, and top-level lists
    of scalar values. This keeps the checker usable without PyYAML.
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
            if value:
                data[key] = _strip_quotes(value)
            else:
                data[key] = None
                current_parent = key
                current_list_key = key
            continue

        if stripped.startswith("- "):
            if current_list_key is None:
                continue
            if not isinstance(data.get(current_list_key), list):
                data[current_list_key] = []
            data[current_list_key].append(_strip_quotes(stripped[2:].strip()))
            continue

        if ":" in stripped and current_parent is not None:
            key, _, value = stripped.partition(":")
            if not isinstance(data.get(current_parent), dict):
                data[current_parent] = {}
            data[current_parent][key.strip()] = _strip_quotes(value.strip())

    return data


def _strip_quotes(value: str) -> Any:
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if re.fullmatch(r"\d+", value):
        return int(value)
    return value


def _manifest_paths(manifest: dict[str, Any], key: str, default: list[str]) -> list[Path]:
    values = manifest.get(key, default)
    if values is None:
        values = default
    if not isinstance(values, list):
        values = default
    return [REPO_ROOT / str(value) for value in values]


def _manifest_glob_paths(manifest: dict[str, Any], key: str) -> list[Path]:
    values = manifest.get(key, [])
    if not isinstance(values, list):
        return []

    paths: list[Path] = []
    for value in values:
        pattern = str(value)
        if not pattern:
            continue
        paths.extend(path for path in REPO_ROOT.glob(pattern) if path.is_file())
    return paths


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


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


def _json_load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _semantic_text(path: Path) -> str:
    """Return text for substring checks, decoding JSON escapes when possible."""
    if path.suffix == ".json":
        data = _json_load(path)
        if data is not None:
            return json.dumps(data, ensure_ascii=False)
    return _read(path)


def _version_values(path: Path) -> set[str]:
    if path.suffix == ".json":
        data = _json_load(path)
        if isinstance(data, dict) and data.get("openapi"):
            info = data.get("info")
            value = info.get("version") if isinstance(info, dict) else None
            return {str(value)} if value else set()
        values: set[str] = set()
        if isinstance(data, dict):
            if data.get("version"):
                values.add(str(data["version"]))
            for package in data.get("packages") or []:
                if isinstance(package, dict) and package.get("version"):
                    values.add(str(package["version"]))
        return values

    text = _read(path)
    values = set()
    for match in re.finditer(r'(?m)^\s*version\s*=\s*["\']?(\d+\.\d+\.\d+)', text):
        values.add(match.group(1))
    return values


def _canonical_mcp_package_paths(manifest: dict[str, Any]) -> list[Path]:
    default_values = manifest.get("distribution_surface_paths", DEFAULT_DISTRIBUTION_SURFACES)
    if not isinstance(default_values, list):
        default_values = DEFAULT_DISTRIBUTION_SURFACES
    default = [
        str(value)
        for value in default_values
        if str(value) not in AGENT_OPENAPI_PACKAGE_SCAN_EXCLUDES
    ]
    return _manifest_paths(manifest, "canonical_mcp_package_surface_paths", default)


def _line_matches(text: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _scan_required_paths(manifest: dict[str, Any]) -> list[DriftRow]:
    rows: list[DriftRow] = []
    paths = _manifest_paths(manifest, "distribution_surface_paths", DEFAULT_DISTRIBUTION_SURFACES)
    paths.extend(_manifest_paths(manifest, "docs_paths", []))

    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        if not path.exists():
            rows.append(
                DriftRow(
                    field="path.exists",
                    expected="present",
                    file=_rel(path),
                    observed="missing",
                    status="MISSING",
                    hint="Create the file or remove it from distribution_manifest.yml.",
                )
            )
    return rows


def _scan_versions(manifest: dict[str, Any]) -> list[DriftRow]:
    rows: list[DriftRow] = []
    expected = str(manifest.get("pyproject_version", "")).strip()
    if not expected:
        return rows

    paths = _manifest_paths(
        manifest,
        "version_surface_paths",
        ["pyproject.toml", "mcp-server.json", "dxt/manifest.json", "docs/openapi/v1.json"],
    )
    for path in paths:
        if not path.exists():
            continue
        values = _version_values(path)
        if not values:
            rows.append(
                DriftRow(
                    field="pyproject_version",
                    expected=expected,
                    file=_rel(path),
                    observed="not found",
                    status="MISSING",
                    hint=f"Add a version declaration matching {expected}.",
                )
            )
            continue
        if values != {expected}:
            rows.append(
                DriftRow(
                    field="pyproject_version",
                    expected=expected,
                    file=_rel(path),
                    observed=", ".join(sorted(values)),
                    status="DRIFT",
                    hint=f"Update version declaration(s) to {expected}.",
                )
            )
    return rows


def _scan_json_tool_arrays(manifest: dict[str, Any]) -> list[DriftRow]:
    rows: list[DriftRow] = []
    expected = manifest.get("tool_count_default_gates")
    if expected is None:
        return rows
    expected_int = int(expected)

    for path in _manifest_paths(
        manifest, "tool_count_surface_paths", DEFAULT_DISTRIBUTION_SURFACES
    ):
        if path.suffix != ".json" or not path.exists():
            continue
        data = _json_load(path)
        if not isinstance(data, dict) or not isinstance(data.get("tools"), list):
            continue
        found = len(data["tools"])
        if found != expected_int:
            rows.append(
                DriftRow(
                    field="tool_count_default_gates",
                    expected=expected_int,
                    file=_rel(path),
                    observed=f"{found} JSON tools[] entries",
                    status="DRIFT",
                    hint=f"Regenerate the manifest with {expected_int} tools or update the canonical count.",
                )
            )
    return rows


def _scan_tool_count(manifest: dict[str, Any]) -> list[DriftRow]:
    rows: list[DriftRow] = []
    expected = manifest.get("tool_count_default_gates")
    if expected is None:
        return rows
    expected_int = int(expected)

    paths = _manifest_paths(manifest, "tool_count_surface_paths", DEFAULT_DISTRIBUTION_SURFACES)
    for path in paths:
        if not path.exists():
            continue
        text = _read(path)
        seen_mentions: set[tuple[int, int]] = set()
        for line_no, line in enumerate(text.splitlines(), 1):
            for pattern in TOOL_COUNT_PATTERNS:
                for match in pattern.finditer(line):
                    found = int(match.group(1))
                    marker = (line_no, found)
                    if marker in seen_mentions:
                        continue
                    seen_mentions.add(marker)
                    if found in SUSPECT_TOOL_COUNT_RANGE and found != expected_int:
                        rows.append(
                            DriftRow(
                                field="tool_count_default_gates",
                                expected=expected_int,
                                file=_rel(path),
                                observed=f"{found} (line: {line.strip()[:100]})",
                                status="DRIFT",
                                line_no=line_no,
                                hint=f"Update the tool-count wording to {expected_int}.",
                            )
                        )
    rows.extend(_scan_json_tool_arrays(manifest))
    return rows


def _scan_pricing(manifest: dict[str, Any]) -> list[DriftRow]:
    rows: list[DriftRow] = []
    expected_price = manifest.get("pricing_unit_jpy_ex_tax")
    expected_free = manifest.get("free_tier_requests_per_day")
    paths = _manifest_paths(manifest, "pricing_surface_paths", DEFAULT_DISTRIBUTION_SURFACES)

    for path in paths:
        if not path.exists():
            continue
        text = _semantic_text(path)
        if expected_price is not None and not _line_matches(text, PRICE_PATTERNS):
            rows.append(
                DriftRow(
                    field="pricing_unit_jpy_ex_tax",
                    expected=f"JPY {expected_price}",
                    file=_rel(path),
                    observed="price marker not found",
                    status="DRIFT",
                    hint="Add or update the JPY 3 per billable unit/request wording.",
                )
            )
        if expected_free is not None and not _line_matches(text, FREE_TIER_PATTERNS):
            rows.append(
                DriftRow(
                    field="free_tier_requests_per_day",
                    expected=f"{expected_free}/day",
                    file=_rel(path),
                    observed="free-tier marker not found",
                    status="DRIFT",
                    hint="Add or update the anonymous 3/day free-tier wording.",
                )
            )
        if (
            manifest.get("pricing_unit_jpy_tax_included") is not None
            and "3.30" in text
            and not _line_matches(text, TAX_INCLUDED_PATTERNS)
        ):
            rows.append(
                DriftRow(
                    field="pricing_unit_jpy_tax_included",
                    expected=f"JPY {manifest['pricing_unit_jpy_tax_included']}",
                    file=_rel(path),
                    observed="3.30 appears without a recognized tax-included marker",
                    status="DRIFT",
                    hint="Use the canonical tax-included wording, e.g. 税込 JPY 3.30.",
                )
            )
    return rows


def _scan_openapi_path_count(manifest: dict[str, Any]) -> list[DriftRow]:
    rows: list[DriftRow] = []
    expected = manifest.get("openapi_path_count")
    if expected is None:
        return rows
    expected_int = int(expected)

    openapi_paths = [REPO_ROOT / "docs" / "openapi" / "v1.json"]
    for path in _manifest_paths(
        manifest, "distribution_surface_paths", DEFAULT_DISTRIBUTION_SURFACES
    ):
        if path.name == "v1.json" and path.parent.name == "openapi" and path not in openapi_paths:
            openapi_paths.append(path)

    for openapi_path in openapi_paths:
        data = _json_load(openapi_path)
        if isinstance(data, dict) and isinstance(data.get("paths"), dict):
            found = len(data["paths"])
            if found != expected_int:
                rows.append(
                    DriftRow(
                        field="openapi_path_count",
                        expected=expected_int,
                        file=_rel(openapi_path),
                        observed=str(found),
                        status="DRIFT",
                        hint=f"Update openapi_path_count to {found} or regenerate the OpenAPI file.",
                    )
                )

    for path in _manifest_paths(
        manifest, "distribution_surface_paths", DEFAULT_DISTRIBUTION_SURFACES
    ):
        if not path.exists():
            continue
        for line_no, line in enumerate(_read(path).splitlines(), 1):
            for pattern in OPENAPI_PATH_COUNT_PATTERNS:
                for match in pattern.finditer(line):
                    found = int(match.group(1))
                    if found != expected_int:
                        rows.append(
                            DriftRow(
                                field="openapi_path_count",
                                expected=expected_int,
                                file=_rel(path),
                                observed=f"{found} (line: {line.strip()[:100]})",
                                status="DRIFT",
                                line_no=line_no,
                                hint=f"Update the OpenAPI public-path count to {expected_int}.",
                            )
                        )
    return rows


def _scan_canonical_values(manifest: dict[str, Any]) -> list[DriftRow]:
    """Verify stable package/domain/env markers in surfaces where they matter."""
    rows: list[DriftRow] = []
    domains = manifest.get("canonical_domains") or {}
    site = domains.get("site", "") if isinstance(domains, dict) else ""
    pkg = str(manifest.get("canonical_mcp_package", "")).strip()
    api_env = manifest.get("canonical_api_env") or {}
    env_key = api_env.get("api_key", "") if isinstance(api_env, dict) else ""
    env_base = api_env.get("api_base", "") if isinstance(api_env, dict) else ""

    for path in _manifest_paths(
        manifest, "distribution_surface_paths", DEFAULT_DISTRIBUTION_SURFACES
    ):
        if not path.exists():
            continue
        text = _read(path)
        rel = _rel(path)
        if site and site not in text and "jpcite.com" not in text:
            rows.append(
                DriftRow(
                    field="canonical_domains.site",
                    expected=site,
                    file=rel,
                    observed="not found",
                    status="DRIFT",
                    hint=f"Add a reference to {site}.",
                )
            )
        if "JPINTEL_API_KEY" in text:
            rows.append(
                DriftRow(
                    field="canonical_api_env.api_key",
                    expected=env_key,
                    file=rel,
                    observed="JPINTEL_API_KEY",
                    status="DRIFT",
                    hint=f"Use {env_key}.",
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
                    hint=f"Use {env_base}.",
                )
            )

    # Agent-safe OpenAPI files are OpenAI Actions schemas, not MCP install
    # manifests; they may mention MCP conceptually without carrying the package
    # identifier.
    for path in _canonical_mcp_package_paths(manifest):
        if not path.exists():
            continue
        text = _read(path)
        rel = _rel(path)
        if pkg and ("mcp" in text.lower() or "package" in text.lower()) and pkg not in text:
            rows.append(
                DriftRow(
                    field="canonical_mcp_package",
                    expected=pkg,
                    file=rel,
                    observed="canonical package not found",
                    status="DRIFT",
                    hint=f"Use {pkg} as the MCP package name.",
                )
            )
    return rows


def _scan_forbidden_tokens(manifest: dict[str, Any]) -> list[DriftRow]:
    rows: list[DriftRow] = []
    forbidden = manifest.get("forbidden_tokens") or []
    excludes = manifest.get("forbidden_token_exclude_paths") or []
    if not isinstance(forbidden, list) or not isinstance(excludes, list):
        return rows

    paths = []
    paths.extend(
        _manifest_paths(manifest, "distribution_surface_paths", DEFAULT_DISTRIBUTION_SURFACES)
    )
    paths.extend(_manifest_paths(manifest, "public_count_guard_paths", []))
    paths.extend(_manifest_glob_paths(manifest, "public_count_guard_globs"))

    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        rel = _rel(path)
        if any(str(fragment) in rel for fragment in excludes):
            continue
        if not path.exists():
            continue
        for line_no, line in enumerate(_read(path).splitlines(), 1):
            for token in forbidden:
                if token and str(token) in line:
                    rows.append(
                        DriftRow(
                            field=f"forbidden:{token}",
                            expected="absent",
                            file=rel,
                            observed=line.strip()[:100],
                            status="DRIFT",
                            line_no=line_no,
                            hint=f"Remove legacy token {token} from this distribution surface.",
                        )
                    )
    return rows


def _format_table(rows: list[DriftRow]) -> str:
    if not rows:
        return "(no drift)"
    headers = ["field", "expected", "file", "observed", "status"]
    cols = [
        [row.field for row in rows],
        [str(row.expected)[:48] for row in rows],
        [row.file + (f":{row.line_no}" if row.line_no else "") for row in rows],
        [row.observed[:100] for row in rows],
        [row.status for row in rows],
    ]
    widths = [
        max(len(headers[i]), max((len(value) for value in cols[i]), default=0)) for i in range(5)
    ]
    sep = "  "
    lines = [sep.join(headers[i].ljust(widths[i]) for i in range(5))]
    lines.append(sep.join("-" * widths[i] for i in range(5)))
    for idx in range(len(rows)):
        lines.append(sep.join(cols[col][idx].ljust(widths[col]) for col in range(5)))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Print suggested edits only. No files are modified.",
    )
    parser.add_argument(
        "--manifest",
        default=str(MANIFEST_PATH),
        help="Path to distribution_manifest.yml.",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        sys.stderr.write(f"manifest not found: {manifest_path}\n")
        return 2

    manifest = _load_manifest_from(manifest_path)

    rows: list[DriftRow] = []
    rows.extend(_scan_required_paths(manifest))
    rows.extend(_scan_versions(manifest))
    rows.extend(_scan_canonical_values(manifest))
    rows.extend(_scan_forbidden_tokens(manifest))
    rows.extend(_scan_tool_count(manifest))
    rows.extend(_scan_pricing(manifest))
    rows.extend(_scan_openapi_path_count(manifest))

    if not rows:
        print(
            "[check_distribution_manifest_drift] OK - distribution manifest matches static surfaces."
        )
        return 0

    print(
        f"[check_distribution_manifest_drift] DRIFT - {len(rows)} issue(s) "
        f"across {len({row.file for row in rows})} surface(s):\n"
    )
    print(_format_table(rows))

    if args.fix:
        print("\nSuggested edits (manual review required; no files modified):\n")
        for row in rows:
            location = row.file + (f":{row.line_no}" if row.line_no else "")
            print(f"  - {location} [{row.field}]\n      {row.hint}")
    else:
        print(
            "\nRun with --fix to print suggested edits. Manual review required; no files are modified."
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
