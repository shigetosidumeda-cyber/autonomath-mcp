"""Safe predicate evaluator + recursive tree walker for dim M.

Two layers:

1. :func:`evaluate_predicate` — Parses one ``condition_expr`` string
   against the input ``context`` dict.  No ``eval()`` — the string is
   tokenised, every token is matched against a fixed whitelist, and a
   small recursive-descent parser produces a boolean.
2. :func:`evaluate_tree` — Recursively walks a :class:`RuleTree`,
   delegating each condition to :func:`evaluate_predicate` and choosing
   ``true_branch`` / ``false_branch`` accordingly.  Returns an
   :class:`EvalResult` with the full ``rationale_path``.

The predicate grammar is deliberately small (BNF-ish)::

    expr      := or_expr
    or_expr   := and_expr ( "or" and_expr )*
    and_expr  := not_expr ( "and" not_expr )*
    not_expr  := "not" not_expr | comp
    comp      := operand ( COMP_OP operand )?
               | operand "in" list_literal
               | operand "not" "in" list_literal
    operand   := IDENT | NUMBER | STRING | "true" | "false" | "null"
               | "(" expr ")"
    COMP_OP   := "==" | "!=" | ">=" | "<=" | ">" | "<"
    list_literal := "(" operand ( "," operand )* ")"
                  | "[" operand ( "," operand )* "]"

Identifiers resolve against the input ``context`` dict (dotted paths
*not* supported — flatten before calling).  A missing identifier raises
:class:`SafeExpressionError` so the evaluator surfaces the bug instead
of silently treating it as ``None``.
"""

from __future__ import annotations

import re
from typing import Any

from .models import EvalResult, RuleNode, RuleTree

#: Hard guard against pathological / adversarial trees.  Per memory
#: ``feedback_rule_tree_branching`` Wave 46 ships the operator-tree
#: kernel with depth cap 32; dim M's branch-tree kernel allows 100 to
#: accommodate deep linear chains (e.g. 10-condition AND chain encoded
#: as 10 nested branch nodes) while still rejecting cycles + runaway
#: recursion well before Python's default 1000-frame stack limit.
MAX_RECURSION_DEPTH = 100


class SafeExpressionError(ValueError):
    """Raised when a ``condition_expr`` cannot be safely evaluated.

    Possible causes:
        * Disallowed token (e.g. an attribute access ``a.b``)
        * Unknown identifier in the input context
        * Type mismatch (e.g. ``str > int``)
        * Malformed expression (unbalanced parens, dangling ``and``)
    """


class MaxRecursionError(RuntimeError):
    """Raised when a tree walk exceeds :data:`MAX_RECURSION_DEPTH`."""


# ---------------------------------------------------------------------------
# Tokeniser
# ---------------------------------------------------------------------------

# Order matters — longer operators must match before shorter prefixes.
_TOKEN_PATTERNS: list[tuple[str, str]] = [
    ("SKIP", r"\s+"),
    ("STRING", r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\""),
    ("NUMBER", r"-?\d+(?:\.\d+)?"),
    ("OP", r"==|!=|>=|<=|>|<|,"),
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
    ("LBRACK", r"\["),
    ("RBRACK", r"\]"),
    ("IDENT", r"[A-Za-z_][A-Za-z0-9_]*"),
]
_TOKEN_RE = re.compile("|".join(f"(?P<{n}>{p})" for n, p in _TOKEN_PATTERNS))

_KEYWORDS = frozenset({"and", "or", "not", "in", "true", "false", "null"})
_COMP_OPS = frozenset({"==", "!=", ">=", "<=", ">", "<"})


def _tokenize(expr: str) -> list[tuple[str, str]]:
    """Tokenise ``expr`` into (kind, value) pairs.

    Raises :class:`SafeExpressionError` on any unrecognised character.
    """
    tokens: list[tuple[str, str]] = []
    pos = 0
    for m in _TOKEN_RE.finditer(expr):
        if m.start() != pos:
            bad = expr[pos : m.start()]
            raise SafeExpressionError(
                f"unrecognised characters in predicate: {bad!r}"
            )
        kind = m.lastgroup or ""
        value = m.group()
        pos = m.end()
        if kind == "SKIP":
            continue
        if kind == "IDENT" and value in _KEYWORDS:
            kind = "KEYWORD"
        tokens.append((kind, value))
    if pos != len(expr):
        bad = expr[pos:]
        raise SafeExpressionError(f"unrecognised tail in predicate: {bad!r}")
    return tokens


# ---------------------------------------------------------------------------
# Parser + evaluator (recursive descent, single pass)
# ---------------------------------------------------------------------------


class _Parser:
    """Recursive-descent parser that evaluates as it parses.

    Parser state is a token cursor; values are computed inline so the
    AST never materialises.  This keeps the evaluator dependency-free
    and avoids leaking parser internals through the public surface.
    """

    def __init__(self, tokens: list[tuple[str, str]], context: dict[str, Any]):
        self._tokens = tokens
        self._pos = 0
        self._context = context

    def _peek(self) -> tuple[str, str] | None:
        if self._pos >= len(self._tokens):
            return None
        return self._tokens[self._pos]

    def _consume(self) -> tuple[str, str]:
        tok = self._peek()
        if tok is None:
            raise SafeExpressionError("unexpected end of predicate")
        self._pos += 1
        return tok

    def _eat(self, kind: str, value: str | None = None) -> tuple[str, str]:
        tok = self._consume()
        if tok[0] != kind or (value is not None and tok[1] != value):
            want = f"{kind}={value!r}" if value else kind
            raise SafeExpressionError(
                f"expected {want}, got {tok[0]}={tok[1]!r}"
            )
        return tok

    def parse(self) -> bool:
        result = self._or()
        if self._pos != len(self._tokens):
            extra = self._tokens[self._pos]
            raise SafeExpressionError(
                f"trailing tokens after predicate: {extra!r}"
            )
        if not isinstance(result, bool):
            raise SafeExpressionError(
                f"predicate must evaluate to bool, got {type(result).__name__}"
            )
        return result

    # or_expr := and_expr ( "or" and_expr )*
    def _or(self) -> Any:
        left = self._and()
        while True:
            tok = self._peek()
            if tok is None or tok != ("KEYWORD", "or"):
                break
            self._consume()
            right = self._and()
            if not isinstance(left, bool) or not isinstance(right, bool):
                raise SafeExpressionError("'or' requires bool operands")
            left = left or right
        return left

    # and_expr := not_expr ( "and" not_expr )*
    def _and(self) -> Any:
        left = self._not()
        while True:
            tok = self._peek()
            if tok is None or tok != ("KEYWORD", "and"):
                break
            self._consume()
            right = self._not()
            if not isinstance(left, bool) or not isinstance(right, bool):
                raise SafeExpressionError("'and' requires bool operands")
            left = left and right
        return left

    # not_expr := "not" not_expr | comp
    def _not(self) -> Any:
        tok = self._peek()
        if tok == ("KEYWORD", "not"):
            self._consume()
            # Disambiguate 'not in' — handled inside _comp via lookahead.
            inner = self._not()
            if not isinstance(inner, bool):
                raise SafeExpressionError("'not' requires a bool operand")
            return not inner
        return self._comp()

    # comp := operand ( COMP_OP operand | "in" list | "not" "in" list )?
    def _comp(self) -> Any:
        left = self._operand()
        tok = self._peek()
        if tok is None:
            return left
        # Comparison operator
        if tok[0] == "OP" and tok[1] in _COMP_OPS:
            op = self._consume()[1]
            right = self._operand()
            return _apply_comparison(left, op, right)
        # 'in' membership
        if tok == ("KEYWORD", "in"):
            self._consume()
            members = self._list_literal()
            return left in members
        # 'not in' membership (the leading 'not' was consumed by _not when
        # used after a comp; this branch covers `foo not in (...)` literal).
        if tok == ("KEYWORD", "not"):
            # Save position so we can backtrack if the next token isn't 'in'.
            save_pos = self._pos
            self._consume()
            nxt = self._peek()
            if nxt == ("KEYWORD", "in"):
                self._consume()
                members = self._list_literal()
                return left not in members
            # Not a 'not in' — restore.
            self._pos = save_pos
        return left

    def _list_literal(self) -> list[Any]:
        tok = self._consume()
        if tok[0] == "LPAREN":
            close = "RPAREN"
        elif tok[0] == "LBRACK":
            close = "RBRACK"
        else:
            raise SafeExpressionError(
                f"expected '(' or '[' for list literal, got {tok!r}"
            )
        items: list[Any] = []
        # Empty list allowed
        if (peek := self._peek()) is not None and peek[0] == close:
            self._consume()
            return items
        items.append(self._operand())
        while True:
            tok2 = self._peek()
            if tok2 is None:
                raise SafeExpressionError("unterminated list literal")
            if tok2[0] == close:
                self._consume()
                return items
            if tok2 == ("OP", ","):
                self._consume()
                items.append(self._operand())
                continue
            raise SafeExpressionError(
                f"expected ',' or '{close}' in list literal, got {tok2!r}"
            )

    def _operand(self) -> Any:
        tok = self._consume()
        kind, value = tok
        if kind == "LPAREN":
            inner = self._or()
            self._eat("RPAREN")
            return inner
        if kind == "NUMBER":
            return float(value) if "." in value else int(value)
        if kind == "STRING":
            # Strip surrounding quote + decode escapes.
            quote = value[0]
            body = value[1:-1]
            return body.replace(f"\\{quote}", quote).replace("\\\\", "\\")
        if kind == "KEYWORD":
            if value == "true":
                return True
            if value == "false":
                return False
            if value == "null":
                return None
            raise SafeExpressionError(
                f"keyword {value!r} not valid here"
            )
        if kind == "IDENT":
            if value not in self._context:
                raise SafeExpressionError(
                    f"unknown identifier {value!r} in context "
                    f"(available: {sorted(self._context.keys())!r})"
                )
            return self._context[value]
        raise SafeExpressionError(f"unexpected token {tok!r} in operand")


def _apply_comparison(left: Any, op: str, right: Any) -> bool:
    """Apply a whitelisted comparison.

    Type-strict — comparing ``str`` to ``int`` raises rather than
    coercing.  Equality (``==``/``!=``) is the one exception that
    tolerates cross-type comparison (False on type mismatch, matching
    Python's native ``==`` semantics for mixed-type bool/str/int).
    """
    if op == "==":
        return bool(left == right)
    if op == "!=":
        return bool(left != right)
    # Ordering comparisons require comparable numeric / str types.
    if isinstance(left, bool) or isinstance(right, bool):
        raise SafeExpressionError(
            f"ordering comparison {op!r} not allowed on bool operands"
        )
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return _ord(left, op, right)
    if isinstance(left, str) and isinstance(right, str):
        return _ord(left, op, right)
    raise SafeExpressionError(
        f"cannot compare {type(left).__name__} {op} {type(right).__name__}"
    )


def _ord(left: Any, op: str, right: Any) -> bool:
    if op == ">":
        return bool(left > right)
    if op == ">=":
        return bool(left >= right)
    if op == "<":
        return bool(left < right)
    if op == "<=":
        return bool(left <= right)
    raise SafeExpressionError(f"unknown ordering op {op!r}")  # pragma: no cover


def evaluate_predicate(expr: str, context: dict[str, Any]) -> bool:
    """Evaluate one predicate string against ``context``.

    Public surface — exported from the package for callers (tests,
    MCP wrapper) that need to validate a predicate in isolation
    without constructing a full tree.

    Raises
    ------
    SafeExpressionError
        On any unrecognised token, malformed grammar, type mismatch,
        or missing identifier.
    """
    tokens = _tokenize(expr)
    if not tokens:
        raise SafeExpressionError("empty predicate")
    return _Parser(tokens, context).parse()


# ---------------------------------------------------------------------------
# Tree walker
# ---------------------------------------------------------------------------


def evaluate_tree(
    tree: RuleTree,
    context: dict[str, Any],
    *,
    max_depth: int = MAX_RECURSION_DEPTH,
) -> EvalResult:
    """Walk ``tree`` against ``context`` and return the chosen path.

    Parameters
    ----------
    tree:
        :class:`RuleTree` previously loaded via :func:`load_rule_tree`
        or constructed directly.
    context:
        Flat mapping of identifier → value.  Identifiers referenced by
        any ``condition_expr`` must exist as keys (missing keys raise
        :class:`SafeExpressionError`).
    max_depth:
        Stack-depth budget.  Defaults to :data:`MAX_RECURSION_DEPTH`
        (100).  Exposed as a kwarg so test cases can shrink the budget
        to exercise the guard.

    Raises
    ------
    SafeExpressionError
        Surfaced from :func:`evaluate_predicate` when a node's
        ``condition_expr`` is malformed or references a missing key.
    MaxRecursionError
        When the walk would exceed ``max_depth``.
    """
    path: list[str] = []
    rationale_text: list[str] = []
    source_doc_ids: list[str] = []
    branch_decisions: list[bool] = []

    # Seed source_doc_ids with the tree-level citation if present so
    # downstream callers have a single "tree provenance" marker even
    # when no individual node carries one.
    if tree.source_doc_id is not None:
        source_doc_ids.append(tree.source_doc_id)

    final = _walk(
        tree.root,
        context,
        depth=0,
        max_depth=max_depth,
        path=path,
        rationale_text=rationale_text,
        source_doc_ids=source_doc_ids,
        branch_decisions=branch_decisions,
    )
    return EvalResult(
        tree_id=tree.tree_id,
        action=final.action,
        rationale_path=path,
        rationale_text=rationale_text,
        source_doc_ids=source_doc_ids,
        branch_decisions=branch_decisions,
    )


def _walk(
    node: RuleNode,
    context: dict[str, Any],
    *,
    depth: int,
    max_depth: int,
    path: list[str],
    rationale_text: list[str],
    source_doc_ids: list[str],
    branch_decisions: list[bool],
) -> RuleNode:
    """Recursive walker. Returns the terminal node reached."""
    if depth > max_depth:
        raise MaxRecursionError(
            f"rule tree exceeded max recursion depth {max_depth} at node "
            f"{node.node_id!r} — likely malformed / cyclic input"
        )
    path.append(node.node_id)
    if node.rationale is not None:
        rationale_text.append(node.rationale)
    if node.source_doc_id is not None:
        source_doc_ids.append(node.source_doc_id)

    if node.is_terminal():
        return node

    # Branch — condition_expr guaranteed non-None by RuleNode validator.
    assert node.condition_expr is not None
    decision = evaluate_predicate(node.condition_expr, context)
    branch_decisions.append(decision)
    next_node = node.true_branch if decision else node.false_branch
    # Both branches guaranteed non-None on branch nodes by RuleNode validator.
    assert next_node is not None
    return _walk(
        next_node,
        context,
        depth=depth + 1,
        max_depth=max_depth,
        path=path,
        rationale_text=rationale_text,
        source_doc_ids=source_doc_ids,
        branch_decisions=branch_decisions,
    )


__all__ = [
    "MAX_RECURSION_DEPTH",
    "MaxRecursionError",
    "SafeExpressionError",
    "evaluate_predicate",
    "evaluate_tree",
]
