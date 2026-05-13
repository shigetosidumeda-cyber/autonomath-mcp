"""Static guard for public-vs-internal revenue/profit projection claims.

Wave 49 business analysis may live in internal/operator notes, but public
site/docs must not expose year-one profit/ARR/revenue projections or
bull/base ROI scenario claims.  This file intentionally keeps the guard
separate from the broader public sanitization tests so the business boundary is
easy to audit.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

PUBLIC_TEXT_SUFFIXES = {
    ".atom",
    ".html",
    ".js",
    ".json",
    ".md",
    ".rss",
    ".txt",
    ".xml",
}

PUBLIC_SITE_SKIP_DIRS = {
    "cases",
    "cities",
    "cross",
    "data",
    "enforcement",
    "industries",
    "laws",
    "programs",
}

PUBLIC_MANIFESTS = (
    "mcp-server.core.json",
    "mcp-server.composition.json",
    "mcp-server.full.json",
    "mcp-server.json",
    "server.json",
)

OPERATOR_ONLY_RE = re.compile(
    r"operator[- ]only|public docs excluded|公開(?:docs\s*)?除外|"
    r"公開 docs build から除外|internal[- ]only|非公開|外部公開しない",
    re.IGNORECASE,
)

SAFE_NEGATED_CLAIM_RE = re.compile(
    r"do\s+not\s+claim|must\s+not\s+claim|not\s+[^.。]{0,80}claim|"
    r"avoid\s+[^.。]{0,80}claim|internal[- ]only|operator[- ]only|"
    r"外部公開しない|公開しない|主張しない|表現しない|使わない|禁止|"
    r"含みません|含まない|含めない|除外",
    re.IGNORECASE,
)

CANDIDATE_CLAIM_RE = re.compile(
    r"\bY[13]\b|\byear\s*[13]\b|1\s*年目|3\s*年目|"
    r"\bARR\b|\bMRR\b|annual recurring revenue|profit|revenue|sales|"
    r"売上|収益|利益|\bROI\b|"
    r"\b(?:bull|base)\s+(?:case|scenario)\b|"
    r"\b(?:bull|base)[-_ ]ROI\b|\bROI[-_ ](?:bull|base)\b",
    re.IGNORECASE,
)

YEAR_MARKER = r"(?:\bY[13]\b|\byear\s*[13]\b|1\s*年目|3\s*年目)"
BUSINESS_METRIC = (
    r"(?:\bARR\b|\bMRR\b|annual recurring revenue|profit(?:s|ability)?|"
    r"revenue|sales|売上|収益|利益|営業利益|粗利|黒字|赤字)"
)
PROJECTION_MARKER = r"(?:projection|forecast|ceiling|試算|予測|上限)"
SCENARIO_MARKER = r"(?:bull|base)\s+(?:case|scenario)"
SCENARIO_METRIC = r"(?:\bROI\b|\bARR\b|profit|revenue|売上|収益|利益)"

FORBIDDEN_REVENUE_CLAIM_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "year_metric_projection": (
        re.compile(rf"{YEAR_MARKER}.{{0,180}}{BUSINESS_METRIC}", re.IGNORECASE | re.DOTALL),
        re.compile(rf"{BUSINESS_METRIC}.{{0,180}}{YEAR_MARKER}", re.IGNORECASE | re.DOTALL),
    ),
    "arr_profit_revenue_projection": (
        re.compile(
            rf"{BUSINESS_METRIC}.{{0,120}}{PROJECTION_MARKER}",
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            rf"{PROJECTION_MARKER}.{{0,120}}{BUSINESS_METRIC}",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    "bull_base_roi_or_arr_scenario": (
        re.compile(
            rf"\b{SCENARIO_MARKER}\b.{{0,160}}{SCENARIO_METRIC}",
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            rf"{SCENARIO_METRIC}.{{0,160}}\b{SCENARIO_MARKER}\b",
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(r"\b(?:bull|base)[-_ ]ROI\b|\bROI[-_ ](?:bull|base)\b", re.IGNORECASE),
    ),
}


def _mkdocs_exclude_patterns() -> tuple[list[str], list[str]]:
    text = (REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    excludes: list[str] = []
    includes: list[str] = []
    in_exclude_block = False
    for raw_line in text.splitlines():
        if raw_line.startswith("exclude_docs:"):
            in_exclude_block = True
            continue
        if in_exclude_block and raw_line and not raw_line.startswith("  "):
            break
        if not in_exclude_block:
            continue
        item = raw_line.strip()
        if not item or item.startswith("#"):
            continue
        target = includes if item.startswith("!") else excludes
        target.append(item[1:] if item.startswith("!") else item)
    return excludes, includes


def _matches_mkdocs_pattern(rel: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        return rel.startswith(pattern)
    return rel == pattern or Path(rel).match(pattern)


def _is_mkdocs_excluded(doc_path: Path) -> bool:
    rel = doc_path.relative_to(REPO_ROOT / "docs").as_posix()
    excludes, includes = _mkdocs_exclude_patterns()
    if any(_matches_mkdocs_pattern(rel, pattern) for pattern in includes):
        return False
    return any(_matches_mkdocs_pattern(rel, pattern) for pattern in excludes)


def _is_operator_only_doc(path: Path, text: str) -> bool:
    rel = path.relative_to(REPO_ROOT).as_posix()
    if rel.startswith("docs/_internal/"):
        return True
    return OPERATOR_ONLY_RE.search(text[:4096]) is not None


def _iter_public_doc_sources() -> list[Path]:
    paths = [REPO_ROOT / "README.md"]
    for path in (REPO_ROOT / "docs").rglob("*"):
        if path.suffix not in PUBLIC_TEXT_SUFFIXES or not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel.startswith("docs/_internal/"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if _is_operator_only_doc(path, text):
            continue
        if _is_mkdocs_excluded(path):
            continue
        paths.append(path)
    return sorted(set(paths))


def _iter_public_site_artifacts() -> list[Path]:
    paths: list[Path] = []
    site_root = REPO_ROOT / "site"
    for path in site_root.rglob("*"):
        if path.suffix not in PUBLIC_TEXT_SUFFIXES or not path.is_file():
            continue
        rel_parts = path.relative_to(site_root).parts
        if rel_parts and rel_parts[0] in PUBLIC_SITE_SKIP_DIRS:
            continue
        paths.append(path)
    for rel in PUBLIC_MANIFESTS:
        manifest = REPO_ROOT / rel
        if manifest.exists():
            paths.append(manifest)
    return sorted(set(paths))


def _find_projection_hits(paths: list[Path]) -> list[tuple[str, int, str, str]]:
    hits: list[tuple[str, int, str, str]] = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if CANDIDATE_CLAIM_RE.search(text) is None:
            continue
        if path.is_relative_to(REPO_ROOT / "docs") and _is_operator_only_doc(path, text):
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if CANDIDATE_CLAIM_RE.search(line) is None:
                continue
            context = " ".join(
                _bounded_line_for_scan(item)
                for item in lines[max(0, index - 2) : min(len(lines), index + 3)]
            )
            if SAFE_NEGATED_CLAIM_RE.search(context):
                continue
            for category, patterns in FORBIDDEN_REVENUE_CLAIM_PATTERNS.items():
                if any(pattern.search(context) for pattern in patterns):
                    hits.append((rel, index + 1, category, line.strip()[:220]))
                    break
    return hits


def _bounded_line_for_scan(line: str) -> str:
    if len(line) <= 1200:
        return line
    match = CANDIDATE_CLAIM_RE.search(line)
    if match is None:
        return line[:1200]
    start = max(0, match.start() - 400)
    end = min(len(line), match.end() + 800)
    return line[start:end]


def test_public_doc_sources_do_not_expose_revenue_profit_projection_claims() -> None:
    """Rendered docs and README must not leak internal business projections."""

    hits = _find_projection_hits(_iter_public_doc_sources())
    assert hits == [], (
        "Public docs expose revenue/profit projection or bull/base ROI claims. "
        "Move business analysis to docs/_internal or an explicitly private/operator doc. "
        f"Hits: {hits[:30]}"
    )


def test_public_static_site_artifacts_do_not_expose_revenue_profit_projection_claims() -> None:
    """Customer-facing static artifacts must keep Wave 49 projections internal."""

    hits = _find_projection_hits(_iter_public_site_artifacts())
    assert hits == [], (
        "Public site artifacts expose revenue/profit projection or bull/base ROI claims. "
        "Keep ARR/profit/ROI scenarios out of generated public surfaces. "
        f"Hits: {hits[:30]}"
    )
