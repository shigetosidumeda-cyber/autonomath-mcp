from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "public_copy_freshness.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("public_copy_freshness", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_public_copy_freshness_gate_passes() -> None:
    gate = _load_gate()
    findings = gate.scan()
    assert findings == []


def test_public_copy_freshness_rules_cover_recent_regressions() -> None:
    gate = _load_gate()
    rule_ids = {rule.rule_id for rule in gate.RULES}
    assert "old_rag_nav_label" in rule_ids
    assert "bpo_first_positioning" in rule_ids
    assert "all_response_claim" in rule_ids
    assert "old_company_folder_pack_unit" in rule_ids
    assert "audience_dark_inline_code_bg" in rule_ids
