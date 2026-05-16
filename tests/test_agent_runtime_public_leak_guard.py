from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

ROOT = Path(__file__).resolve().parents[1]

if TYPE_CHECKING:
    from collections.abc import Iterator

PUBLIC_P0_ROOTS = (
    ROOT / "site/releases/rc1-p0-bootstrap",
    ROOT / "site/.well-known/jpcite-release.json",
)
SCHEMA_ROOT = ROOT / "schemas/jpcir"
SCAN_ROOTS = (*PUBLIC_P0_ROOTS, SCHEMA_ROOT)


TEXT_SUFFIXES = {
    ".css",
    ".csv",
    ".html",
    ".js",
    ".json",
    ".jsonl",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
}

FALSE_ONLY_KEYS = {
    "aws_runtime_dependency_allowed",
    "live_allowed",
    "live_aws_commands_allowed",
    "no_hit_absence_claim_enabled",
    "public_claim_support",
    "public_surface_export_allowed",
    "csv_input_logged",
    "csv_input_retained",
    "csv_input_sent_to_aws",
    "raw_csv_logged",
    "raw_csv_retained",
    "raw_csv_sent_to_aws",
    "real_csv_runtime_enabled",
    "request_time_llm_fact_generation_enabled",
    "row_level_retention_enabled",
    "source_receipt_compatible",
}

RAW_PRIVATE_CSV_PATTERNS = {
    "private CSV header": re.compile(
        r"(?i)(?:^|[\"'`])(?:date|posted_at|取引日|日付|仕訳日|計上日)\s*,"
        r"\s*(?:description|memo|摘要|取引先|勘定科目|借方|貸方|金額)\s*,"
    ),
    "private CSV row": re.compile(
        r"(?:^|[\"'`])\d{4}[-/]\d{1,2}[-/]\d{1,2}\s*,\s*[^,\n]{2,}\s*,"
        r"\s*(?:[^,\n]{2,}\s*,\s*)?-?\d{3,}(?:\.\d{1,2})?(?:\s*(?:$|[\"'`]))"
    ),
    "raw provider export example": re.compile(
        r"(?i)(?:freee|money[\s_-]*forward|yayoi|弥生|tkc).{0,60}"
        r"(?:raw\s+csv|csv\s+row|export\s+row|仕訳|総勘定元帳)"
    ),
}

SECRET_PATTERNS = {
    "AWS access key id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "AWS secret access key assignment": re.compile(
        r"(?i)\baws_secret_access_key\b\s*[:=]\s*[\"'][^\"'<>{}\s]{20,}[\"']"
    ),
    "bearer token": re.compile(r"(?i)\bbearer\s+(?:eyJ|[a-z0-9_-]{24,}\.)"),
    "OpenAI secret key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "GitHub token": re.compile(r"\bgh[opsu]_[A-Za-z0-9_]{36,}\b"),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}

LIVE_AWS_ENABLEMENT_PATTERNS = {
    "live AWS enablement sentence": re.compile(
        r"(?i)\blive\s+aws\s+commands?\s+(?:are|is|now)\s+(?:allowed|enabled|ready)\b"
    ),
    "AWS command allowed true": re.compile(
        r'(?i)"(?:live_allowed|live_aws_commands_allowed|aws_runtime_dependency_allowed)"\s*:\s*true'
    ),
}

MISLEADING_NO_HIT_PATTERNS = {
    "no-hit means absence": re.compile(
        r"(?i)\bno[-\s]?hit(?:s)?\b.{0,80}\b(?:means|proves|confirms|guarantees)\b.{0,80}"
        r"\b(?:absence|none|no\s+(?:matching\s+)?(?:records?|programs?|evidence))\b"
    ),
    "no results means absence": re.compile(
        r"(?i)\bno\s+results?\b.{0,80}\b(?:means|proves|confirms|guarantees)\b.{0,80}"
        r"\b(?:absence|none|no\s+(?:matching\s+)?(?:records?|programs?|evidence))\b"
    ),
    "absence claim enabled": re.compile(r'(?i)"no_hit_absence_claim_enabled"\s*:\s*true'),
}


def _scan_files(roots: tuple[Path, ...] = SCAN_ROOTS) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        assert root.exists(), f"required P0 scan root is missing: {root.relative_to(ROOT)}"
        if root.is_file():
            files.append(root)
            continue
        files.extend(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES
        )
    return sorted(files)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _iter_json_values(value: Any, path: str = "$") -> Iterator[tuple[str, str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            yield child_path, key, child
            yield from _iter_json_values(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_json_values(child, f"{path}[{index}]")


def _pattern_hits(patterns: dict[str, re.Pattern[str]], files: list[Path]) -> list[str]:
    hits: list[str] = []
    for file_path in files:
        text = _read_text(file_path)
        rel_path = file_path.relative_to(ROOT)
        for line_no, line in enumerate(text.splitlines(), start=1):
            for label, pattern in patterns.items():
                if pattern.search(line):
                    hits.append(f"{rel_path}:{line_no}: {label}: {line.strip()}")
    return hits


def test_public_p0_artifact_set_is_scoped_to_generated_release_surfaces() -> None:
    scanned = [path.relative_to(ROOT).as_posix() for path in _scan_files()]

    assert "site/.well-known/jpcite-release.json" in scanned
    assert any(path.startswith("site/releases/rc1-p0-bootstrap/") for path in scanned)
    assert any(path.startswith("schemas/jpcir/") for path in scanned)
    assert all(
        path == "site/.well-known/jpcite-release.json"
        or path.startswith("site/releases/rc1-p0-bootstrap/")
        or path.startswith("schemas/jpcir/")
        for path in scanned
    )


def test_generated_p0_text_has_no_raw_private_csv_examples_or_secrets() -> None:
    files = _scan_files()
    hits = _pattern_hits(RAW_PRIVATE_CSV_PATTERNS | SECRET_PATTERNS, files)

    assert hits == []


def test_generated_p0_json_never_enables_private_or_live_runtime_flags() -> None:
    violations: list[str] = []

    for file_path in _scan_files():
        if file_path.suffix.lower() != ".json":
            continue

        data = json.loads(_read_text(file_path))
        rel_path = file_path.relative_to(ROOT)
        for json_path, key, value in _iter_json_values(data):
            if key in FALSE_ONLY_KEYS and value is True:
                violations.append(f"{rel_path}:{json_path} must not be true")

    assert violations == []


def test_generated_p0_text_has_no_live_aws_enablement_or_absence_claims() -> None:
    files = _scan_files()
    hits = _pattern_hits(LIVE_AWS_ENABLEMENT_PATTERNS | MISLEADING_NO_HIT_PATTERNS, files)

    assert hits == []


def test_private_fact_capsule_contract_names_stay_out_of_public_release_surfaces() -> None:
    public_files = _scan_files(PUBLIC_P0_ROOTS)
    public_hits = _pattern_hits(
        {
            "private fact capsule contract name": re.compile(
                r"\b(?:PrivateFactCapsule(?:Record)?|private_fact_capsule(?:\.schema\.json)?)\b"
            )
        },
        public_files,
    )

    schema_text = _read_text(SCHEMA_ROOT / "private_fact_capsule.schema.json")
    assert "PrivateFactCapsule" in schema_text
    assert public_hits == []
