"""Wave 51 dim M — Multi-step rule tree (server-side branching eval).

This package is the **reusable, router-agnostic** core for the dim M
"branching condition chain in 1 call" layer described in
``feedback_rule_tree_branching``:

    * Japanese public-program eligibility is a chain of conditional
      branches (e.g. 中小企業 ∧ 業種ガイドライン適合 ∧ 過去 3 年未受給
      ∧ 設備投資 ¥XX 万以上).  Agents that resolve this with N atomic
      ``rule_engine_check`` calls pay ¥3 × N per evaluation.
    * One ``evaluate_tree`` call resolves the whole branch in a single
      round-trip and returns the chosen ``rationale_path`` so the agent
      can quote *why* each branch was taken (Dim O verification trail).
    * Trees are loaded from ``data/rule_trees/<id>.json`` so operators
      curate eligibility logic without code changes.

Relationship to ``api/rule_tree_eval.py``
-----------------------------------------
The existing :mod:`jpintel_mcp.api.rule_tree_eval` module ships the
*REST surface* (POST ``/v1/rule_tree/evaluate``) using an AND/OR/XOR
*operator-tree* shape.  This package ships the **branch-tree** kernel
where each interior node carries a single condition and chooses one of
two sub-trees — the canonical "decision tree" form taught in CS
textbooks.  Both forms are valid representations of dim M; the operator
picks whichever fits the policy document (NTA tax-rule branching forms
fit the decision-tree form; e-Gov 5-paragraph AND-chains fit the
operator-tree form).  The two shapes co-exist intentionally.

Public surface
--------------
    RuleNode               — Pydantic model for one node (recursive)
    RuleTree               — Pydantic model wrapping the root + metadata
    EvalResult             — Output: chosen action + ``rationale_path``
    evaluate_tree(...)     — Pure function: tree + context -> EvalResult
    load_rule_tree(...)    — Load a tree from ``data/rule_trees/<id>.json``
    list_rule_trees(...)   — List all tree IDs available on disk
    SafeExpressionError    — Raised by the predicate evaluator on bad input
    MaxRecursionError      — Raised when a tree exceeds depth 100

Hard constraints
----------------
* **No LLM API import.**  Rule eval is deterministic.
* **No ``eval()``.**  Predicate strings are tokenised and dispatched
  against a fixed whitelist of operators (``==``, ``!=``, ``>``, ``>=``,
  ``<``, ``<=``, ``in``, ``not in``, ``and``, ``or``, ``not``).  The
  whitelist is enforced at parse-time, not at eval-time.
* **Max recursion depth = 100.**  Guards against stack overflow on
  pathological or adversarial trees.
* **Frozen Pydantic models** + ``extra='forbid'`` so a typo in a tree
  JSON file fails loudly at load time rather than silently misrouting.
"""

from __future__ import annotations

from .evaluator import (
    MaxRecursionError,
    SafeExpressionError,
    evaluate_predicate,
    evaluate_tree,
)
from .loader import list_rule_trees, load_rule_tree
from .models import EvalResult, RuleNode, RuleTree

__all__ = [
    "EvalResult",
    "MaxRecursionError",
    "RuleNode",
    "RuleTree",
    "SafeExpressionError",
    "evaluate_predicate",
    "evaluate_tree",
    "list_rule_trees",
    "load_rule_tree",
]
