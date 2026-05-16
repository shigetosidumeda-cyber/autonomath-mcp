"""Pydantic models for dim M rule trees (decision-tree shape).

A :class:`RuleNode` is one branch point in the decision tree.  It owns:

* ``node_id`` — short stable identifier surfaced in the rationale path.
* ``condition_expr`` — predicate string evaluated against the input
  context (``None`` when the node is a terminal action).
* ``true_branch`` / ``false_branch`` — child :class:`RuleNode` taken
  when the predicate evaluates True / False (``None`` when terminal).
* ``action`` — terminal label / dict returned in :attr:`EvalResult.action`
  when this node is reached.
* ``rationale`` — optional human-readable string included in the
  ``rationale_path`` so the consuming agent can quote *why* the branch
  was taken (Dim O verification trail).

A :class:`RuleTree` is the top-level container with a metadata header
(name + description + version + source_doc_id for Dim O integration)
plus the root :class:`RuleNode`.

All models are **frozen + extra='forbid'** so:

* Mutating a loaded tree mid-eval raises (catches accidental shared
  mutable state in concurrent evaluators).
* A typo in a tree JSON file (``"true_brach"``) fails at load time
  rather than silently routing every node into the false branch.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RuleNode(BaseModel):
    """One node in a rule decision tree.

    Two valid shapes:

    1. **Branch node** — ``condition_expr`` is set, both ``true_branch``
       and ``false_branch`` are set, ``action`` is ``None``.
    2. **Terminal node** — ``condition_expr`` is ``None``, both branches
       are ``None``, ``action`` is set.

    Mixed shapes (e.g. only ``true_branch`` set) raise at validation.
    The :meth:`is_terminal` helper lets the evaluator branch without
    re-deriving the shape.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str = Field(
        min_length=1,
        max_length=128,
        description=(
            "Short stable identifier surfaced in EvalResult.rationale_path. "
            "Convention: snake_case, no whitespace."
        ),
    )
    condition_expr: str | None = Field(
        default=None,
        description=(
            "Predicate string evaluated against the input context. "
            "Whitelist tokens only: comparisons (==/!=/>/>=/</<=), "
            "membership (in/not in), boolean (and/or/not), literals "
            "(numbers / quoted strings / true/false/null), parens. "
            "None for terminal nodes."
        ),
    )
    true_branch: RuleNode | None = Field(
        default=None,
        description="Child node taken when condition_expr evaluates True.",
    )
    false_branch: RuleNode | None = Field(
        default=None,
        description="Child node taken when condition_expr evaluates False.",
    )
    action: dict[str, Any] | str | None = Field(
        default=None,
        description=(
            "Terminal action label or structured action payload. Set only "
            "on terminal nodes. May be a free-form string or a small dict "
            "(e.g. {'verdict': 'eligible', 'next_step': 'apply'})."
        ),
    )
    rationale: str | None = Field(
        default=None,
        max_length=512,
        description=(
            "Optional human-readable explanation included in the "
            "rationale_path. Drop verbose legal-doc quotes here so the "
            "agent can render them downstream without re-fetching."
        ),
    )
    source_doc_id: str | None = Field(
        default=None,
        max_length=128,
        description=(
            "Optional Dim O citation identifier (法令番号 / first-party URL "
            "key). Surfaces in the rationale path for verification."
        ),
    )

    @model_validator(mode="after")
    def _validate_shape(self) -> RuleNode:
        """Reject mixed branch / terminal shapes.

        A node is *branch* iff ``condition_expr`` is set; in that case
        both children must be present.  A node is *terminal* iff
        ``action`` is set; in that case both children + condition must
        be absent.  Anything else is a malformed tree.
        """
        has_cond = self.condition_expr is not None
        has_true = self.true_branch is not None
        has_false = self.false_branch is not None
        has_action = self.action is not None

        if has_cond:
            if not (has_true and has_false):
                raise ValueError(
                    f"node {self.node_id!r}: branch node must set both "
                    "true_branch and false_branch"
                )
            if has_action:
                raise ValueError(
                    f"node {self.node_id!r}: branch node must not set 'action' "
                    "(reserve action for terminal nodes)"
                )
        else:
            if has_true or has_false:
                raise ValueError(
                    f"node {self.node_id!r}: terminal node must not set "
                    "true_branch / false_branch"
                )
            if not has_action:
                raise ValueError(
                    f"node {self.node_id!r}: terminal node must set 'action'"
                )
        return self

    def is_terminal(self) -> bool:
        """True iff this is a terminal action node (no condition / no children)."""
        return self.condition_expr is None


class RuleTree(BaseModel):
    """Top-level rule tree wrapper.

    Carries the root :class:`RuleNode` plus metadata used by the
    operator surface (tree listing endpoint) and the rationale path
    (so the agent can quote *which tree* produced the verdict).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tree_id: str = Field(
        min_length=1,
        max_length=128,
        description=(
            "Tree identifier — used as the file stem under "
            "data/rule_trees/<tree_id>.json."
        ),
    )
    name: str = Field(
        min_length=1,
        max_length=256,
        description="Human-readable tree name (e.g. '補助金適格性判定').",
    )
    description: str = Field(
        default="",
        max_length=2048,
        description="Short prose describing the policy this tree encodes.",
    )
    version: str = Field(
        default="1.0.0",
        max_length=32,
        description="Semantic version of the tree definition.",
    )
    source_doc_id: str | None = Field(
        default=None,
        max_length=128,
        description=(
            "Optional Dim O citation identifier for the originating policy "
            "document. Surfaces at the head of every rationale path."
        ),
    )
    root: RuleNode = Field(description="Root node of the decision tree.")


class EvalResult(BaseModel):
    """Output of :func:`evaluate_tree`.

    Carries the terminal action plus the full ``rationale_path``
    (ordered ``node_id`` list of every branch taken) so the consuming
    agent can render *why* each step was chosen without re-evaluating.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tree_id: str = Field(description="Tree ID that produced this result.")
    action: dict[str, Any] | str | None = Field(
        description=(
            "Terminal action label / payload reached by walking the tree. "
            "None only when the tree itself is a single-terminal stub."
        ),
    )
    rationale_path: list[str] = Field(
        description=(
            "Ordered list of node_ids visited from root to terminal. "
            "Length ≥ 1 — first entry is always the root node."
        ),
    )
    rationale_text: list[str] = Field(
        default_factory=list,
        description=(
            "Parallel list of per-node rationale strings (only the nodes "
            "that declared a 'rationale' field). Lengths need NOT match "
            "rationale_path."
        ),
    )
    source_doc_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Parallel list of Dim O source_doc_id values collected along "
            "the rationale path (only the nodes that declared one)."
        ),
    )
    branch_decisions: list[bool] = Field(
        default_factory=list,
        description=(
            "Parallel list of True/False decisions at each branch node "
            "along the path. Length = len(rationale_path) - 1 (terminal "
            "node has no decision)."
        ),
    )
