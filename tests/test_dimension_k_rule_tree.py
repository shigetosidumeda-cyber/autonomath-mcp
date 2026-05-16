"""Tests for Dim K rule_tree_branching surface (Wave 46).

Closes the Wave 46 dim 19 / dim K (2.86/10) gap: server-side
multi-step rule tree evaluation (1 call replaces N rule_engine_check
round-trips). 3 case bundles: linear AND chain, branching AND/OR/XOR,
circular detection.

Hard constraints exercised:
  * No LLM SDK import
  * §52 / §47条の2 / §72 disclaimer parity envelope
  * Cycle detection raises HTTP 422 (ValueError → 422 map)
  * Depth cap enforced (>32 → 422)
  * LEAF predicate parsing surface (==, !=, >=, <=, >, <, in, exists)
  * Citation gap surfaces "conditional" result when LEAF source_doc_id is None
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_RULE_TREE = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "rule_tree_eval.py"


def _import_rule_tree_module():
    """Load the rule_tree_eval module by file path (avoids package init)."""
    spec = importlib.util.spec_from_file_location("_rule_tree_test_mod", SRC_RULE_TREE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_rule_tree_test_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Module-load tests
# ---------------------------------------------------------------------------


def test_rule_tree_file_exists() -> None:
    """Module file must exist on disk."""
    assert SRC_RULE_TREE.exists(), (
        "src/jpintel_mcp/api/rule_tree_eval.py is required to close "
        "dim 19 / dim K REST sub-criterion."
    )
    src = SRC_RULE_TREE.read_text(encoding="utf-8")
    assert 'router = APIRouter(prefix="/v1/rule_tree"' in src
    assert 'tags=["rule-tree-branching"]' in src


def test_rule_tree_no_llm_imports() -> None:
    """rule_tree_eval.py must NOT import any LLM SDK."""
    src = SRC_RULE_TREE.read_text(encoding="utf-8")
    banned = (
        "anthropic",
        "openai",
        "google.generativeai",
        "claude_agent_sdk",
    )
    for needle in banned:
        pattern = rf"^\s*(import|from)\s+{re.escape(needle)}\b"
        assert not re.search(pattern, src, re.MULTILINE), f"LLM SDK import detected: {needle}"


def test_rule_tree_disclaimer_present() -> None:
    """Surface must carry the §52 / §47条の2 / §72 / §1 disclaimer."""
    src = SRC_RULE_TREE.read_text(encoding="utf-8")
    assert "税理士法" in src and "52" in src
    assert "公認会計士法" in src and "47条の2" in src
    assert "弁護士法" in src and "72" in src
    assert "行政書士法" in src and "1" in src


# ---------------------------------------------------------------------------
# Case 1: Linear AND chain (3 nodes, all pass)
# ---------------------------------------------------------------------------


def test_case_linear_and_pass() -> None:
    """3-condition AND chain returns pass when all LEAFs evaluate true."""
    mod = _import_rule_tree_module()
    tree = {
        "node_id": "n_root",
        "operator": "AND",
        "source_doc_id": "law:smb_act:§2",
        "children": [
            {
                "node_id": "n_emp",
                "operator": "LEAF",
                "predicate": "employees <= 300",
                "source_doc_id": "law:smb_act:§2.1",
            },
            {
                "node_id": "n_cap",
                "operator": "LEAF",
                "predicate": "capital_yen <= 300000000",
                "source_doc_id": "law:smb_act:§2.2",
            },
            {
                "node_id": "n_industry",
                "operator": "LEAF",
                "predicate": 'industry_jsic in ("E", "F", "G")',
                "source_doc_id": "stat:jsic:2024",
            },
        ],
    }
    input_data = {
        "employees": 250,
        "capital_yen": 80_000_000,
        "industry_jsic": "E",
    }
    env = mod.evaluate_rule_tree(tree, input_data)
    assert env["result"] == "pass"
    # AND root + 3 LEAF nodes = 4 visited (root appended first).
    assert env["path"] == ["n_root", "n_emp", "n_cap", "n_industry"]
    # rationale order: LEAFs append on hit, root after children resolve.
    decisions = {r["node_id"]: r["decision"] for r in env["rationale"]}
    assert decisions["n_emp"] is True
    assert decisions["n_cap"] is True
    assert decisions["n_industry"] is True
    assert decisions["n_root"] is True
    assert env["citation_gap"] is False


def test_case_linear_and_fail_on_capital() -> None:
    """AND short-circuits to fail when one LEAF returns false."""
    mod = _import_rule_tree_module()
    tree = {
        "node_id": "n_root",
        "operator": "AND",
        "source_doc_id": "law:smb_act:§2",
        "children": [
            {
                "node_id": "n_emp",
                "operator": "LEAF",
                "predicate": "employees <= 300",
                "source_doc_id": "law:smb_act:§2.1",
            },
            {
                "node_id": "n_cap",
                "operator": "LEAF",
                "predicate": "capital_yen <= 300000000",
                "source_doc_id": "law:smb_act:§2.2",
            },
        ],
    }
    env = mod.evaluate_rule_tree(tree, {"employees": 250, "capital_yen": 800_000_000})
    assert env["result"] == "fail"
    decisions = {r["node_id"]: r["decision"] for r in env["rationale"]}
    assert decisions["n_cap"] is False
    assert decisions["n_root"] is False


# ---------------------------------------------------------------------------
# Case 2: Branching AND/OR/XOR
# ---------------------------------------------------------------------------


def test_case_branching_or_passes_on_either_arm() -> None:
    """OR returns pass when at least one branch evaluates true."""
    mod = _import_rule_tree_module()
    tree = {
        "node_id": "n_root",
        "operator": "OR",
        "source_doc_id": "law:subsidy:§5",
        "children": [
            {
                "node_id": "n_arm_a",
                "operator": "AND",
                "source_doc_id": "law:subsidy:§5.a",
                "children": [
                    {
                        "node_id": "n_a_emp",
                        "operator": "LEAF",
                        "predicate": "employees <= 100",
                        "source_doc_id": "law:subsidy:§5.a.1",
                    },
                    {
                        "node_id": "n_a_region",
                        "operator": "LEAF",
                        "predicate": 'region_code == "13101"',
                        "source_doc_id": "stat:jis_region",
                    },
                ],
            },
            {
                "node_id": "n_arm_b",
                "operator": "LEAF",
                "predicate": "annual_revenue_yen >= 500000000",
                "source_doc_id": "law:subsidy:§5.b",
            },
        ],
    }
    # Arm A fails (region mismatch); Arm B passes (revenue ≥ 500M).
    env = mod.evaluate_rule_tree(
        tree,
        {
            "employees": 80,
            "region_code": "27100",
            "annual_revenue_yen": 600_000_000,
        },
    )
    assert env["result"] == "pass"
    decisions = {r["node_id"]: r["decision"] for r in env["rationale"]}
    assert decisions["n_arm_a"] is False
    assert decisions["n_arm_b"] is True
    assert decisions["n_root"] is True


def test_case_branching_xor_exactly_one() -> None:
    """XOR returns pass when exactly one child evaluates true."""
    mod = _import_rule_tree_module()
    tree = {
        "node_id": "n_xor_root",
        "operator": "XOR",
        "source_doc_id": "law:exclusivity",
        "children": [
            {
                "node_id": "n_x1",
                "operator": "LEAF",
                "predicate": "claim_path_a exists",
                "source_doc_id": "law:exclusivity:§1",
            },
            {
                "node_id": "n_x2",
                "operator": "LEAF",
                "predicate": "claim_path_b exists",
                "source_doc_id": "law:exclusivity:§2",
            },
        ],
    }
    # Exactly one path present → pass.
    env_one = mod.evaluate_rule_tree(tree, {"claim_path_a": "yes"})
    assert env_one["result"] == "pass"
    # Both present → XOR fail.
    env_both = mod.evaluate_rule_tree(tree, {"claim_path_a": "yes", "claim_path_b": "yes"})
    assert env_both["result"] == "fail"
    # Neither present → XOR fail.
    env_neither = mod.evaluate_rule_tree(tree, {})
    assert env_neither["result"] == "fail"


def test_case_citation_gap_returns_conditional() -> None:
    """LEAF with no source_doc_id surfaces 'conditional' on pass."""
    mod = _import_rule_tree_module()
    tree = {
        "node_id": "n_root",
        "operator": "AND",
        "source_doc_id": "law:smb_act:§2",
        "children": [
            {
                "node_id": "n_cited",
                "operator": "LEAF",
                "predicate": "employees <= 300",
                "source_doc_id": "law:smb_act:§2.1",
            },
            {
                "node_id": "n_uncited",
                "operator": "LEAF",
                "predicate": "capital_yen <= 300000000",
                "source_doc_id": None,
            },
        ],
    }
    env = mod.evaluate_rule_tree(tree, {"employees": 100, "capital_yen": 100_000_000})
    # All LEAFs pass but one lacks citation → conditional, not pass.
    assert env["result"] == "conditional"
    assert env["citation_gap"] is True


# ---------------------------------------------------------------------------
# Case 3: Circular detection + structural rejection
# ---------------------------------------------------------------------------


def test_case_cycle_detection_rejected() -> None:
    """A tree whose child references its ancestor node_id raises ValueError."""
    mod = _import_rule_tree_module()
    # Construct a path-cycle: same node_id at root and as a grand-child.
    leaf = {
        "node_id": "n_root",  # collision with root → cycle
        "operator": "LEAF",
        "predicate": "employees <= 300",
        "source_doc_id": "x",
    }
    tree = {
        "node_id": "n_root",
        "operator": "AND",
        "source_doc_id": None,
        "children": [
            {
                "node_id": "n_mid",
                "operator": "AND",
                "source_doc_id": None,
                "children": [leaf],
            }
        ],
    }
    with pytest.raises(ValueError, match=r"cycle detected"):
        mod.evaluate_rule_tree(tree, {})


def test_case_depth_cap_rejected() -> None:
    """A tree deeper than _MAX_TREE_DEPTH raises ValueError."""
    mod = _import_rule_tree_module()
    # Build a chain of nested ANDs deeper than the cap.
    leaf = {
        "node_id": "leaf",
        "operator": "LEAF",
        "predicate": "x == 1",
        "source_doc_id": None,
    }
    node = leaf
    # 40 levels — well past the 32 cap.
    for i in range(40):
        node = {
            "node_id": f"n_{i}",
            "operator": "AND",
            "source_doc_id": None,
            "children": [node],
        }
    with pytest.raises(ValueError, match=r"(depth|node)"):
        mod.evaluate_rule_tree(node, {"x": 1})


def test_case_invalid_operator_rejected() -> None:
    """Unknown operator raises ValueError."""
    mod = _import_rule_tree_module()
    tree = {
        "node_id": "n_root",
        "operator": "NAND",  # not in valid set
        "source_doc_id": None,
        "children": [],
    }
    with pytest.raises(ValueError, match=r"invalid operator"):
        mod.evaluate_rule_tree(tree, {})


def test_case_invalid_predicate_rejected() -> None:
    """Malformed LEAF predicate raises ValueError at validate time."""
    mod = _import_rule_tree_module()
    tree = {
        "node_id": "n_root",
        "operator": "LEAF",
        "predicate": "nonsense ~~ something",  # ~~ is not a valid comparator
        "source_doc_id": None,
    }
    with pytest.raises(ValueError):
        mod.evaluate_rule_tree(tree, {})


# ---------------------------------------------------------------------------
# Wiring sanity: main.py imports the experimental router
# ---------------------------------------------------------------------------


def test_main_py_includes_rule_tree_eval() -> None:
    """``api/main.py`` must wire the experimental router."""
    main = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "main.py"
    src = main.read_text(encoding="utf-8")
    assert "jpintel_mcp.api.rule_tree_eval" in src, (
        "main.py must include rule_tree_eval via _include_experimental_router"
    )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
