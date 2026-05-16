"""Tests for the Wave 51 dim M ``jpintel_mcp.rule_tree`` package.

Coverage targets:
    * terminal-only tree returns its action without branching
    * single-branch tree picks true / false correctly
    * multi-level chain produces a correct rationale path
    * max-depth guard rejects pathologically deep trees
    * predicate evaluator rejects disallowed tokens (eval-injection guard)
    * predicate evaluator rejects unknown identifiers
    * load_rule_tree finds the example file shipped with the repo
    * loader rejects path traversal in tree_id
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

if TYPE_CHECKING:
    from pathlib import Path

from jpintel_mcp.rule_tree import (
    EvalResult,
    MaxRecursionError,
    RuleNode,
    RuleTree,
    SafeExpressionError,
    evaluate_predicate,
    evaluate_tree,
    list_rule_trees,
    load_rule_tree,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _terminal(node_id: str, action: Any, **extra: Any) -> RuleNode:
    return RuleNode(node_id=node_id, action=action, **extra)


def _branch(
    node_id: str,
    condition_expr: str,
    true_branch: RuleNode,
    false_branch: RuleNode,
    **extra: Any,
) -> RuleNode:
    return RuleNode(
        node_id=node_id,
        condition_expr=condition_expr,
        true_branch=true_branch,
        false_branch=false_branch,
        **extra,
    )


def _wrap(root: RuleNode, *, tree_id: str = "t_test") -> RuleTree:
    return RuleTree(tree_id=tree_id, name="test tree", root=root)


# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------


def test_terminal_node_requires_action() -> None:
    with pytest.raises(ValidationError):
        RuleNode(node_id="t1")  # no action, no condition


def test_terminal_node_must_not_have_branches() -> None:
    with pytest.raises(ValidationError):
        RuleNode(
            node_id="t1",
            action="x",
            true_branch=_terminal("t2", "y"),
        )


def test_branch_node_requires_both_children() -> None:
    with pytest.raises(ValidationError):
        RuleNode(
            node_id="b1",
            condition_expr="a == 1",
            true_branch=_terminal("t1", "y"),
        )


def test_branch_node_must_not_have_action() -> None:
    with pytest.raises(ValidationError):
        RuleNode(
            node_id="b1",
            condition_expr="a == 1",
            true_branch=_terminal("t1", "y"),
            false_branch=_terminal("t2", "n"),
            action="conflict",
        )


def test_node_id_required_non_empty() -> None:
    with pytest.raises(ValidationError):
        RuleNode(node_id="", action="x")


def test_extra_field_rejected_at_load() -> None:
    with pytest.raises(ValidationError):
        RuleNode(node_id="t1", action="x", typo_field="oops")  # type: ignore[call-arg]


def test_is_terminal_helper() -> None:
    leaf = _terminal("t1", "x")
    branch = _branch("b1", "a == 1", _terminal("t1", "y"), _terminal("t2", "n"))
    assert leaf.is_terminal() is True
    assert branch.is_terminal() is False


# ---------------------------------------------------------------------------
# Predicate evaluator — happy paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expr", "ctx", "expected"),
    [
        ("flag == true", {"flag": True}, True),
        ("flag == false", {"flag": True}, False),
        ("n >= 10", {"n": 10}, True),
        ("n > 10", {"n": 10}, False),
        ("n <= 5", {"n": 4}, True),
        ("n < 5", {"n": 5}, False),
        ("name == 'foo'", {"name": "foo"}, True),
        ("name != 'bar'", {"name": "foo"}, True),
        ("x in (1, 2, 3)", {"x": 2}, True),
        ("x in [1, 2, 3]", {"x": 4}, False),
        ("x not in (1, 2)", {"x": 3}, True),
        ("a == 1 and b == 2", {"a": 1, "b": 2}, True),
        ("a == 1 or b == 2", {"a": 0, "b": 2}, True),
        ("not (a == 1)", {"a": 0}, True),
        ("(a == 1 or a == 2) and b > 0", {"a": 2, "b": 5}, True),
        ("flag == null", {"flag": None}, True),
    ],
)
def test_evaluate_predicate_happy(expr: str, ctx: dict[str, Any], expected: bool) -> None:
    assert evaluate_predicate(expr, ctx) is expected


# ---------------------------------------------------------------------------
# Predicate evaluator — error paths
# ---------------------------------------------------------------------------


def test_predicate_rejects_eval_injection() -> None:
    """Eval-injection guard: arbitrary Python is not allowed."""
    with pytest.raises(SafeExpressionError):
        evaluate_predicate("__import__('os').system('echo pwned')", {})


def test_predicate_rejects_attribute_access() -> None:
    with pytest.raises(SafeExpressionError):
        evaluate_predicate("a.b == 1", {"a": 1})


def test_predicate_rejects_unknown_identifier() -> None:
    with pytest.raises(SafeExpressionError):
        evaluate_predicate("missing == 1", {"present": 1})


def test_predicate_rejects_empty() -> None:
    with pytest.raises(SafeExpressionError):
        evaluate_predicate("", {})


def test_predicate_rejects_dangling_and() -> None:
    with pytest.raises(SafeExpressionError):
        evaluate_predicate("a == 1 and", {"a": 1})


def test_predicate_rejects_unbalanced_parens() -> None:
    with pytest.raises(SafeExpressionError):
        evaluate_predicate("(a == 1", {"a": 1})


def test_predicate_rejects_non_bool_result() -> None:
    with pytest.raises(SafeExpressionError):
        evaluate_predicate("a", {"a": 5})


def test_predicate_rejects_string_vs_int_ordering() -> None:
    with pytest.raises(SafeExpressionError):
        evaluate_predicate("a > 1", {"a": "foo"})


def test_predicate_rejects_bool_ordering() -> None:
    with pytest.raises(SafeExpressionError):
        evaluate_predicate("a > false", {"a": True})


# ---------------------------------------------------------------------------
# Tree walker
# ---------------------------------------------------------------------------


def test_terminal_only_tree() -> None:
    tree = _wrap(_terminal("only", {"verdict": "ok"}))
    result = evaluate_tree(tree, {})
    assert isinstance(result, EvalResult)
    assert result.action == {"verdict": "ok"}
    assert result.rationale_path == ["only"]
    assert result.branch_decisions == []


def test_single_branch_picks_true() -> None:
    tree = _wrap(
        _branch(
            "root",
            "x == 1",
            _terminal("t_yes", "yes"),
            _terminal("t_no", "no"),
        )
    )
    result = evaluate_tree(tree, {"x": 1})
    assert result.action == "yes"
    assert result.rationale_path == ["root", "t_yes"]
    assert result.branch_decisions == [True]


def test_single_branch_picks_false() -> None:
    tree = _wrap(
        _branch(
            "root",
            "x == 1",
            _terminal("t_yes", "yes"),
            _terminal("t_no", "no"),
        )
    )
    result = evaluate_tree(tree, {"x": 0})
    assert result.action == "no"
    assert result.rationale_path == ["root", "t_no"]
    assert result.branch_decisions == [False]


def test_multi_level_chain_rationale_path() -> None:
    tree = _wrap(
        _branch(
            "b1",
            "is_smb == true",
            _branch(
                "b2",
                "capex >= 100",
                _terminal("ok", {"verdict": "eligible"}),
                _terminal("low", {"verdict": "too_small"}),
            ),
            _terminal("nope", {"verdict": "not_smb"}),
        )
    )
    result = evaluate_tree(tree, {"is_smb": True, "capex": 200})
    assert result.action == {"verdict": "eligible"}
    assert result.rationale_path == ["b1", "b2", "ok"]
    assert result.branch_decisions == [True, True]


def test_rationale_text_and_source_doc_ids_collected() -> None:
    tree = _wrap(
        _branch(
            "b1",
            "x == 1",
            _terminal("t1", "ok", rationale="terminal rationale", source_doc_id="doc:t1"),
            _terminal("t2", "no"),
            rationale="branch rationale",
            source_doc_id="doc:b1",
        )
    )
    result = evaluate_tree(tree, {"x": 1})
    assert result.rationale_text == ["branch rationale", "terminal rationale"]
    assert result.source_doc_ids == ["doc:b1", "doc:t1"]


def test_tree_level_source_doc_id_seeds_path() -> None:
    tree = RuleTree(
        tree_id="t_seed",
        name="seeded",
        source_doc_id="tree:root_citation",
        root=_terminal("only", "ok"),
    )
    result = evaluate_tree(tree, {})
    assert result.source_doc_ids[0] == "tree:root_citation"


def test_unknown_condition_surface_raises() -> None:
    tree = _wrap(
        _branch(
            "root",
            "missing == 1",
            _terminal("y", "y"),
            _terminal("n", "n"),
        )
    )
    with pytest.raises(SafeExpressionError):
        evaluate_tree(tree, {"present": 1})


# ---------------------------------------------------------------------------
# Max recursion guard
# ---------------------------------------------------------------------------


def _build_linear_chain(length: int) -> RuleNode:
    """Build a tree of ``length`` chained always-true branches."""
    node: RuleNode = _terminal("leaf", "done")
    for i in range(length, 0, -1):
        node = _branch(
            f"n{i}",
            "go == true",
            node,
            _terminal(f"bypass_{i}", "bypass"),
        )
    return node


def test_max_depth_guard_rejects_deep_tree() -> None:
    tree = _wrap(_build_linear_chain(150))
    with pytest.raises(MaxRecursionError):
        evaluate_tree(tree, {"go": True})


def test_max_depth_guard_allows_within_budget() -> None:
    tree = _wrap(_build_linear_chain(50))
    result = evaluate_tree(tree, {"go": True})
    assert result.action == "done"
    assert len(result.rationale_path) == 51  # 50 branches + 1 leaf


def test_max_depth_override_via_kwarg() -> None:
    tree = _wrap(_build_linear_chain(20))
    with pytest.raises(MaxRecursionError):
        evaluate_tree(tree, {"go": True}, max_depth=5)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def test_load_example_tree_from_disk() -> None:
    """The canonical example tree shipped with the repo loads cleanly."""
    tree = load_rule_tree("subsidy_eligibility_smb_capex")
    assert isinstance(tree, RuleTree)
    assert tree.tree_id == "subsidy_eligibility_smb_capex"
    assert tree.root.node_id == "n_is_smb"


def test_example_tree_eligible_path() -> None:
    tree = load_rule_tree("subsidy_eligibility_smb_capex")
    result = evaluate_tree(
        tree,
        {
            "is_smb": True,
            "industry_code": "manufacturing",
            "years_since_last_award": 5,
            "capex_jpy_man": 250,
        },
    )
    assert isinstance(result.action, dict)
    assert result.action["verdict"] == "eligible"
    assert result.rationale_path[0] == "n_is_smb"
    assert result.rationale_path[-1] == "n_eligible"
    assert result.branch_decisions == [True, True, True, True]


def test_example_tree_not_smb_short_circuits() -> None:
    tree = load_rule_tree("subsidy_eligibility_smb_capex")
    result = evaluate_tree(
        tree,
        {
            "is_smb": False,
            "industry_code": "manufacturing",
            "years_since_last_award": 5,
            "capex_jpy_man": 250,
        },
    )
    assert isinstance(result.action, dict)
    assert result.action["reason"] == "not_smb"
    # Path is root + terminal only (short-circuit on the very first node).
    assert result.rationale_path == ["n_is_smb", "n_not_smb"]


def test_example_tree_capex_below_threshold() -> None:
    tree = load_rule_tree("subsidy_eligibility_smb_capex")
    result = evaluate_tree(
        tree,
        {
            "is_smb": True,
            "industry_code": "retail",
            "years_since_last_award": 10,
            "capex_jpy_man": 50,
        },
    )
    assert isinstance(result.action, dict)
    assert result.action["reason"] == "capex_below_threshold"


def test_list_rule_trees_includes_example(tmp_path: Path) -> None:
    """Default lookup picks up the shipped tree(s)."""
    trees = list_rule_trees()
    assert "subsidy_eligibility_smb_capex" in trees


def test_loader_rejects_path_traversal() -> None:
    with pytest.raises(ValueError):
        load_rule_tree("../etc/passwd")


def test_loader_rejects_empty_tree_id() -> None:
    with pytest.raises(ValueError):
        load_rule_tree("")


def test_loader_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_rule_tree("does_not_exist", root_dir=tmp_path)


def test_loader_uses_filename_as_default_tree_id(tmp_path: Path) -> None:
    """A JSON without explicit tree_id picks up the filename stem."""
    payload = {
        "name": "default-id test",
        "root": {"node_id": "only", "action": "ok"},
    }
    (tmp_path / "auto_id.json").write_text(json.dumps(payload), encoding="utf-8")
    tree = load_rule_tree("auto_id", root_dir=tmp_path)
    assert tree.tree_id == "auto_id"


def test_loader_validates_malformed_payload(tmp_path: Path) -> None:
    """A malformed payload fails at load time, not at eval time."""
    payload: dict[str, Any] = {
        "tree_id": "bad",
        "name": "bad",
        "root": {
            "node_id": "b1",
            "condition_expr": "x == 1",
            "true_branch": {"node_id": "t1", "action": "y"},
            # missing false_branch -> shape validation error
        },
    }
    (tmp_path / "bad.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_rule_tree("bad", root_dir=tmp_path)


def test_list_rule_trees_empty_when_dir_missing(tmp_path: Path) -> None:
    missing = tmp_path / "absent"
    assert list_rule_trees(root_dir=missing) == []


def test_env_var_override_resolves_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "tree_id": "via_env",
        "name": "via_env",
        "root": {"node_id": "only", "action": "ok"},
    }
    (tmp_path / "via_env.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("JPCITE_RULE_TREES_DIR", str(tmp_path))
    tree = load_rule_tree("via_env")
    assert tree.tree_id == "via_env"


# ---------------------------------------------------------------------------
# Sanity — no LLM imports at module load
# ---------------------------------------------------------------------------


def test_module_does_not_import_llm_apis() -> None:
    """The dim M kernel must remain LLM-free per CLAUDE.md contract."""
    import sys

    banned = {"anthropic", "openai", "google.generativeai", "claude_agent_sdk"}
    # Each forbidden SDK should NOT have been imported as a side effect of
    # loading the rule_tree package.
    for name in banned:
        assert name not in sys.modules, f"{name} leaked into rule_tree imports"
