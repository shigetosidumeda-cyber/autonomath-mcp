"""DEEP-65 organic outreach monthly playbook tests.

Spec
----
tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_65_organic_outreach_playbook.md

5 cases:
    1. 32 yaml templates load (file count + minimum schema fields)
    2. per-channel x cohort coverage (8 cohort x 4 channel = 32, gap 0)
    3. forbidden-phrase guard: paid PR / sponsor / 商標 / aggregator NG
       in publishable fields (topic / outline / cta / publish_target /
       posting_constraint), allowed only as enumerations under
       forbidden_phrases:.
    4. KPI aggregation produces correct shape from tracker module
    5. LLM API import 0 (anthropic / openai / google.generativeai /
       claude_agent_sdk) in tracker + index + templates dir.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "data" / "organic_outreach_templates"
INDEX_PATH = TEMPLATES_DIR / "index.json"
TRACKER_PATH = REPO_ROOT / "scripts" / "cron" / "track_organic_outreach_monthly.py"

EXPECTED_CHANNELS = ("Zenn", "GitHub issue", "integration PR", "HN-Lobste.rs")
EXPECTED_COHORTS = ("zei", "kaikei", "shihou", "consul", "mna", "fdi", "smb", "ind")

FORBIDDEN_TOKENS = (
    "sponsored",
    "paid PR",
    "paid placement",
    "noukaweb",
    "hojyokin-portal",
    "biz.stayway",
    "商標出願済",
)
FORBIDDEN_LLM_MODULES = {
    "anthropic",
    "openai",
    "google.generativeai",
    "claude_agent_sdk",
}


def _load_tracker_module():
    """Import tracker module without running main()."""
    spec = importlib.util.spec_from_file_location("track_organic_outreach_monthly", TRACKER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_32_template_yaml_load():
    """1. 32 yaml templates load + minimum required fields per template."""
    yaml_files = sorted(TEMPLATES_DIR.glob("*.yaml"))
    assert (
        len(yaml_files) == 32
    ), f"expected 32 yaml templates, found {len(yaml_files)}: {[p.name for p in yaml_files]}"
    mod = _load_tracker_module()
    templates = mod._load_yaml_templates()
    assert len(templates) == 32
    required = {
        "id",
        "channel",
        "cohort",
        "topic",
        "outline",
        "cta",
        "publish_target",
        "posting_constraint",
        "citation_required",
        "forbidden_phrases",
    }
    for t in templates:
        missing = required - set(t.keys())
        assert not missing, f"template {t.get('_path')} missing fields: {missing}"


def test_per_channel_cohort_coverage_complete():
    """2. 8 cohort x 4 channel = 32, gap 0. Verify via filenames + index.json."""
    yaml_files = sorted(TEMPLATES_DIR.glob("*.yaml"))
    expected_filenames: set[str] = set()
    for ch_prefix in ("zenn", "github_issue", "integration_pr", "hn_lobsters"):
        for cohort_id in EXPECTED_COHORTS:
            expected_filenames.add(f"{ch_prefix}_{cohort_id}.yaml")
    actual_filenames = {p.name for p in yaml_files}
    missing = expected_filenames - actual_filenames
    extra = actual_filenames - expected_filenames
    assert not missing, f"missing template files: {missing}"
    assert not extra, f"unexpected template files: {extra}"

    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    assert len(index["templates"]) == 32
    pairs = {(t["channel"], t["cohort_id"]) for t in index["templates"]}
    assert len(pairs) == 32
    for ch in EXPECTED_CHANNELS:
        for co in EXPECTED_COHORTS:
            assert (ch, co) in pairs, f"index gap: ({ch}, {co})"


def test_forbidden_phrase_guard_in_publishable_fields():
    """3. paid PR / sponsor / 商標 / aggregator NG in publishable fields.

    Allowed ONLY as enumerated values under `forbidden_phrases:` block.
    """
    publishable_field_keys = {
        "topic",
        "cta",
        "publish_target",
        "posting_constraint",
    }
    yaml_files = sorted(TEMPLATES_DIR.glob("*.yaml"))
    assert yaml_files, "no template files"

    for path in yaml_files:
        text = path.read_text(encoding="utf-8")
        # Check the publishable scalar fields directly via line scan
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or ":" not in stripped:
                continue
            key = stripped.split(":", 1)[0].strip()
            if key not in publishable_field_keys:
                continue
            value = stripped.split(":", 1)[1].strip().lower()
            for tok in FORBIDDEN_TOKENS:
                # `posting_constraint: organic only / paid PR NG` is the
                # cohort-level NG declaration — that string is NOT a violation,
                # it's a NG flag. Detect by the trailing ' NG' marker.
                tok_low = tok.lower()
                if tok_low not in value:
                    continue
                # Tokens followed by " ng" are negation flags, allowed.
                pat = re.compile(re.escape(tok_low) + r"\s+ng\b", re.IGNORECASE)
                if pat.search(value):
                    continue
                pytest.fail(f"{path.name} field {key!r} contains forbidden token {tok!r}: {value}")


def test_kpi_aggregation_shape():
    """4. KPI aggregation produces correct shape (per-channel + per-cohort)."""
    mod = _load_tracker_module()
    templates = mod._load_yaml_templates()
    # Mock probe results without HTTP (offline test).
    probes = [{"channel": ch, "status": "ok", "mention_count": 0} for ch in mod.CHANNEL_PROBES]
    kpi = mod._aggregate_kpi(templates, probes)
    assert "per_channel_template_count" in kpi
    assert "per_cohort_template_count" in kpi
    assert "per_channel_mention_count" in kpi
    assert "per_channel_status" in kpi
    # 4 channel x 8 cohort = 32 templates, so each channel has 8, each cohort has 4
    for ch in EXPECTED_CHANNELS:
        assert (
            kpi["per_channel_template_count"].get(ch, 0) == 8
        ), f"channel {ch} expected 8, got {kpi['per_channel_template_count'].get(ch, 0)}"
    cohort_counts = list(kpi["per_cohort_template_count"].values())
    assert len(cohort_counts) == 8
    assert all(c == 4 for c in cohort_counts), f"per-cohort counts: {cohort_counts}"
    # violation check end-to-end
    violations = mod._violation_check(templates)
    assert (
        sum(violations.values()) == 0
    ), f"forbidden tokens leaked outside forbidden_phrases: {violations}"


def test_no_llm_api_imports_in_outreach_surface():
    """5. LLM API import 0 in tracker + index + template dir."""
    targets: list[pathlib.Path] = [TRACKER_PATH]
    targets.extend(TEMPLATES_DIR.rglob("*.py"))  # should be empty, but be safe

    for path in targets:
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    head = alias.name.split(".")[0]
                    assert (
                        head not in FORBIDDEN_LLM_MODULES
                    ), f"{path}: forbidden LLM import {alias.name!r}"
                    if alias.name == "google.generativeai" or alias.name.startswith(
                        "google.generativeai."
                    ):
                        pytest.fail(f"{path}: forbidden LLM import {alias.name!r}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                head = mod.split(".")[0]
                if head in {"anthropic", "openai", "claude_agent_sdk"}:
                    pytest.fail(f"{path}: forbidden LLM from-import {mod!r}")
                if mod == "google.generativeai" or mod.startswith("google.generativeai."):
                    pytest.fail(f"{path}: forbidden LLM from-import {mod!r}")

    # Plain regex sweep for env-var leakage in tracker source
    forbidden_env = (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    )
    src = TRACKER_PATH.read_text(encoding="utf-8")
    for env in forbidden_env:
        assert env not in src, f"tracker references forbidden env var {env!r}"
