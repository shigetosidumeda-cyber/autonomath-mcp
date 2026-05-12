"""POST /v1/rule_tree/evaluate — Wave 46 Dim K rule-tree branching surface.

Implements feedback_rule_tree_branching: server-side evaluation of a
JSON-defined decision tree for Japanese public-program eligibility
chains. Where the existing ``api/rule_engine_check`` surface answers
"does this entity pass a single rule?", this surface answers "given a
multi-level AND/OR/XOR tree of N conditions, what is the pass/fail path
+ rationale + source citations in 1 call?".

Hard constraints (Wave 43 / Wave 46 dim K + feedback_rule_tree_branching)
-----------------------------------------------------------------------
* **NO LLM call.** Rule eval is deterministic Python / SQL — predicate
  evaluation is pure logic, not inference.
* **Single-DB.** Touches autonomath.db only (am_rule_trees /
  am_rule_nodes via experimental schema probe).
* **§52 / §47条の2 / §72 / §1 disclaimer parity** — the evaluation is
  an eligibility *primitive*, not a 税理士/会計士/弁護士/行政書士 opinion.
* **Circular detection.** Tree definition is a DAG (parent → children)
  and an in-eval cycle guard rejects ill-formed trees (HTTP 422).
* **Depth cap.** Tree depth is bounded at 32 to prevent server-side
  exhaustion via adversarial input. Wider trees can chain via separate
  evaluate calls — the per-call cost stays flat regardless of width.

Endpoints
---------
    POST /v1/rule_tree/evaluate
        body: {tree: {<JSON tree def>}, input: {<entity field map>}}
        200 -> {result: "pass"|"fail"|"conditional",
                 path: [...node_id...],
                 rationale: [{node_id, operator, decision, source_doc_id}...],
                 _billing_unit: 1, _disclaimer: "..."}
        422 -> malformed tree / cycle detected / depth exceeded

Tree node schema
----------------
    {
        "node_id": "n_root",            # required, str ≤128
        "operator": "AND" | "OR" | "XOR" | "LEAF",
        "predicate": "<field> <op> <value>",  # only for LEAF
        "source_doc_id": "<id>" | null,        # citation, Dim O integration
        "children": [<node>, ...]              # only for AND/OR/XOR
    }

Predicate forms (LEAF only)
---------------------------
    "<field> == <value>"      # equality (str / int / float / bool)
    "<field> != <value>"      # inequality
    "<field> >= <value>"      # numeric (int / float only)
    "<field> <= <value>"      # numeric
    "<field> > <value>"       # numeric
    "<field> < <value>"       # numeric
    "<field> in (<v1>, <v2>)" # set membership (str / int)
    "<field> exists"           # null check
    "<field> not_exists"       # null check

Why this lives in the API tier (not MCP server)
------------------------------------------------
Per feedback_rule_tree_branching: the MCP wrapper is the customer-facing
tool that composes this REST surface with the entity-resolution path.
This module is the **deterministic eval kernel** so the MCP tool stays
thin + the same kernel can be reused by the audit-workpaper composer +
the eligibility-chain MCP wrapper.
"""

from __future__ import annotations

import logging
import re
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger("jpintel.api.rule_tree_eval")

router = APIRouter(prefix="/v1/rule_tree", tags=["rule-tree-branching"])

_NODE_ID_RE = re.compile(r"^[A-Za-z0-9_\-:.]{1,128}$")
_FIELD_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

_MAX_TREE_DEPTH = 32
_MAX_TREE_NODES = 512
_VALID_OPERATORS = frozenset({"AND", "OR", "XOR", "LEAF"})
_VALID_COMPARATORS = (">=", "<=", "==", "!=", ">", "<")

# Mirrors api/fact_signature_v2._DISCOVERY_DISCLAIMER for envelope parity.
_RULE_TREE_DISCLAIMER = (
    "本エンドポイントは autonomath am_rule_trees / am_rule_nodes "
    "(feedback_rule_tree_branching, Wave 46) の決定論的 eligibility "
    "tree evaluation surface で、AND/OR/XOR 連鎖を 1 call で評価し "
    "rationale path を返却します。本サーフェスは税理士法 52 / 公認会計士法 "
    "47条の2 / 弁護士法 72 / 行政書士法 1 に基づく税務判断・監査意見・"
    "法律解釈・申請書面作成の代替ではありません。"
)


# ---------------------------------------------------------------------------
# Predicate parsing + evaluation
# ---------------------------------------------------------------------------


def _coerce_value(token: str) -> Any:
    """Parse a predicate-RHS literal into a typed Python value.

    Tokens are: ``true`` / ``false`` / quoted string / int / float.
    Unquoted bare words fall back to ``str``.
    """
    token = token.strip()
    if not token:
        return ""
    lowered = token.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null" or lowered == "none":
        return None
    if (token.startswith('"') and token.endswith('"')) or (
        token.startswith("'") and token.endswith("'")
    ):
        return token[1:-1]
    try:
        if "." in token:
            return float(token)
        return int(token)
    except ValueError:
        return token


def _parse_predicate(predicate: str) -> tuple[str, str, Any]:
    """Split a LEAF predicate string into (field, op, value).

    Raises ``ValueError`` on malformed input.
    """
    if not predicate or not isinstance(predicate, str):
        raise ValueError("predicate must be a non-empty string")
    stripped = predicate.strip()
    # exists / not_exists null checks come first (1-arg form).
    if stripped.endswith(" exists"):
        field = stripped[: -len(" exists")].strip()
        if not _FIELD_NAME_RE.match(field):
            raise ValueError(f"invalid field name: {field}")
        return (field, "exists", None)
    if stripped.endswith(" not_exists"):
        field = stripped[: -len(" not_exists")].strip()
        if not _FIELD_NAME_RE.match(field):
            raise ValueError(f"invalid field name: {field}")
        return (field, "not_exists", None)
    # in (...) set membership.
    in_match = re.match(r"^(\w+)\s+in\s+\((.+)\)$", stripped)
    if in_match:
        field, raw_set = in_match.group(1), in_match.group(2)
        if not _FIELD_NAME_RE.match(field):
            raise ValueError(f"invalid field name: {field}")
        members = [_coerce_value(t) for t in raw_set.split(",")]
        return (field, "in", tuple(members))
    # Binary comparators, longest-first to avoid '>' eating '>='.
    for op in _VALID_COMPARATORS:
        idx = stripped.find(f" {op} ")
        if idx > 0:
            field = stripped[:idx].strip()
            rhs = stripped[idx + len(f" {op} ") :].strip()
            if not _FIELD_NAME_RE.match(field):
                raise ValueError(f"invalid field name: {field}")
            return (field, op, _coerce_value(rhs))
    raise ValueError(f"unparseable predicate: {predicate}")


def _evaluate_leaf(
    predicate: str, input_data: dict[str, Any]
) -> bool:
    """Evaluate a single LEAF predicate against the input dict.

    Numeric comparators only succeed when both sides are numeric (int /
    float). String comparators succeed on equality / inequality only.
    """
    field, op, value = _parse_predicate(predicate)
    if op == "exists":
        return field in input_data and input_data[field] is not None
    if op == "not_exists":
        return field not in input_data or input_data[field] is None
    actual = input_data.get(field)
    if op == "==":
        return actual == value
    if op == "!=":
        return actual != value
    if op == "in":
        return actual in value
    # Numeric comparators (>=, <=, >, <)
    if actual is None:
        return False
    if not isinstance(actual, (int, float)) or isinstance(actual, bool):
        return False
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    if op == ">=":
        return actual >= value
    if op == "<=":
        return actual <= value
    if op == ">":
        return actual > value
    if op == "<":
        return actual < value
    return False  # pragma: no cover (unreachable; comparator already validated)


# ---------------------------------------------------------------------------
# Tree validation + cycle detection
# ---------------------------------------------------------------------------


def _validate_tree_node(
    node: Any,
    seen_ids: set[str],
    depth: int,
    node_count: list[int],
) -> None:
    """Recursive structural validation + cycle detection.

    ``seen_ids`` is path-local (passed down then removed on unwind) so
    sibling subtrees may share node_ids, but a cycle in a single path
    raises ``ValueError``.
    """
    if depth > _MAX_TREE_DEPTH:
        raise ValueError(f"tree depth exceeds {_MAX_TREE_DEPTH}")
    node_count[0] += 1
    if node_count[0] > _MAX_TREE_NODES:
        raise ValueError(f"tree exceeds {_MAX_TREE_NODES} nodes")
    if not isinstance(node, dict):
        raise ValueError(f"node must be a dict, got {type(node).__name__}")
    nid = node.get("node_id")
    if not isinstance(nid, str) or not _NODE_ID_RE.match(nid):
        raise ValueError(f"invalid node_id: {nid!r}")
    if nid in seen_ids:
        raise ValueError(f"cycle detected at node_id={nid}")
    operator = node.get("operator")
    if operator not in _VALID_OPERATORS:
        raise ValueError(f"invalid operator at {nid}: {operator!r}")
    if operator == "LEAF":
        if not isinstance(node.get("predicate"), str):
            raise ValueError(f"LEAF at {nid} requires predicate (str)")
        # Eager parse so malformed predicates surface at validate-time.
        _parse_predicate(node["predicate"])
        return
    children = node.get("children")
    if not isinstance(children, list) or len(children) == 0:
        raise ValueError(
            f"{operator} at {nid} requires non-empty children list"
        )
    seen_ids.add(nid)
    try:
        for child in children:
            _validate_tree_node(child, seen_ids, depth + 1, node_count)
    finally:
        seen_ids.discard(nid)


# ---------------------------------------------------------------------------
# Tree evaluation
# ---------------------------------------------------------------------------


def _evaluate_tree_node(
    node: dict[str, Any],
    input_data: dict[str, Any],
    path: list[str],
    rationale: list[dict[str, Any]],
) -> bool:
    """Recursive evaluation. Appends to ``path`` + ``rationale`` in-place."""
    nid = node["node_id"]
    operator = node["operator"]
    path.append(nid)
    src_doc = node.get("source_doc_id")
    if operator == "LEAF":
        decision = _evaluate_leaf(node["predicate"], input_data)
        rationale.append(
            {
                "node_id": nid,
                "operator": "LEAF",
                "predicate": node["predicate"],
                "decision": bool(decision),
                "source_doc_id": src_doc,
            }
        )
        return decision
    child_results = [
        _evaluate_tree_node(c, input_data, path, rationale)
        for c in node["children"]
    ]
    if operator == "AND":
        decision = all(child_results)
    elif operator == "OR":
        decision = any(child_results)
    elif operator == "XOR":
        decision = sum(1 for r in child_results if r) == 1
    else:  # pragma: no cover (validated upstream)
        decision = False
    rationale.append(
        {
            "node_id": nid,
            "operator": operator,
            "decision": bool(decision),
            "source_doc_id": src_doc,
        }
    )
    return decision


def evaluate_rule_tree(
    tree: dict[str, Any], input_data: dict[str, Any]
) -> dict[str, Any]:
    """Public eval entry. Returns the wire-shape envelope (without billing).

    Raises ``ValueError`` on malformed tree (caller maps to HTTP 422).
    """
    # Structural validation first (cycles, depth, predicate parsing).
    _validate_tree_node(tree, set(), 0, [0])
    path: list[str] = []
    rationale: list[dict[str, Any]] = []
    final = _evaluate_tree_node(tree, input_data, path, rationale)
    # "conditional" reserved for trees where any LEAF lacked a source_doc_id
    # — exposes the citation gap to the caller without failing the eval.
    has_citation_gap = any(
        r["operator"] == "LEAF" and r["source_doc_id"] is None
        for r in rationale
    )
    if final and has_citation_gap:
        # All LEAFs evaluated true but at least one lacks a citation —
        # surface as 'conditional' so the caller knows the eval is
        # provisional pending Dim O verification trail backfill.
        result = "conditional"
    elif final:
        result = "pass"
    else:
        result = "fail"
    return {
        "result": result,
        "path": path,
        "rationale": rationale,
        "citation_gap": has_citation_gap,
    }


# ---------------------------------------------------------------------------
# REST surface
# ---------------------------------------------------------------------------


@router.post("/evaluate")
async def evaluate_rule_tree_endpoint(
    body: Annotated[
        dict[str, Any],
        Body(
            ...,
            description=(
                "{tree: <JSON tree def>, input: <entity field map>}"
            ),
        ),
    ],
) -> JSONResponse:
    """Evaluate a rule tree in 1 call.

    Replaces ``n`` round-trips of ``rule_engine_check`` with a single
    deterministic eval. Pass/fail decision + path + rationale (with
    per-node ``source_doc_id`` for Dim O verification trail) returned
    in the response.

    Cost: 1 metered unit (¥3 / 税込 ¥3.30) regardless of tree depth.
    """
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_body", "message": "body must be a dict"},
        )
    tree = body.get("tree")
    input_data = body.get("input")
    if not isinstance(tree, dict):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "missing_tree",
                "message": "request body must include 'tree' (dict)",
                "field": "tree",
            },
        )
    if not isinstance(input_data, dict):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "missing_input",
                "message": "request body must include 'input' (dict)",
                "field": "input",
            },
        )

    try:
        envelope = evaluate_rule_tree(tree, input_data)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "tree_validation_failed",
                "message": str(exc),
            },
        ) from exc

    envelope["_billing_unit"] = 1
    envelope["_disclaimer"] = _RULE_TREE_DISCLAIMER
    return JSONResponse(content=envelope)


__all__ = ["router", "evaluate_rule_tree"]
