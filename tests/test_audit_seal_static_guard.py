from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_DIR = REPO_ROOT / "src" / "jpintel_mcp" / "api"
BILLING_LOG_USAGE_PATHS = (REPO_ROOT / "src" / "jpintel_mcp" / "billing" / "delivery.py",)

_REVIEWED_DIRECT_ATTACH_SEAL_CALL_MAX_COUNTS = {
    "src/jpintel_mcp/api/audit.py": 4,
    "src/jpintel_mcp/api/discover.py": 1,
    "src/jpintel_mcp/api/eligibility_predicate.py": 1,
    "src/jpintel_mcp/api/funding_stack.py": 1,
    "src/jpintel_mcp/api/houjin.py": 1,
    "src/jpintel_mcp/api/intel.py": 3,
    "src/jpintel_mcp/api/intel_actionable.py": 4,
    "src/jpintel_mcp/api/intel_bundle_optimal.py": 1,
    "src/jpintel_mcp/api/intel_citation_pack.py": 1,
    "src/jpintel_mcp/api/intel_competitor_landscape.py": 1,
    "src/jpintel_mcp/api/intel_conflict.py": 1,
    "src/jpintel_mcp/api/intel_diff.py": 1,
    "src/jpintel_mcp/api/intel_houjin_full.py": 1,
    "src/jpintel_mcp/api/intel_path.py": 1,
    "src/jpintel_mcp/api/intel_peer_group.py": 1,
    "src/jpintel_mcp/api/intel_portfolio_heatmap.py": 1,
    "src/jpintel_mcp/api/intel_program_full.py": 1,
    "src/jpintel_mcp/api/intel_regulatory_context.py": 1,
    "src/jpintel_mcp/api/intel_risk_score.py": 1,
    "src/jpintel_mcp/api/intel_timeline.py": 1,
    "src/jpintel_mcp/api/intel_why_excluded.py": 1,
    "src/jpintel_mcp/api/intelligence.py": 1,
    "src/jpintel_mcp/api/ma_dd.py": 2,
    "src/jpintel_mcp/api/narrative.py": 1,
    "src/jpintel_mcp/api/time_machine.py": 2,
}


_HTTP_STATUS_ATTRS = {
    "HTTP_400_BAD_REQUEST": 400,
    "HTTP_401_UNAUTHORIZED": 401,
    "HTTP_403_FORBIDDEN": 403,
    "HTTP_404_NOT_FOUND": 404,
    "HTTP_409_CONFLICT": 409,
    "HTTP_422_UNPROCESSABLE_ENTITY": 422,
    "HTTP_429_TOO_MANY_REQUESTS": 429,
    "HTTP_500_INTERNAL_SERVER_ERROR": 500,
    "HTTP_503_SERVICE_UNAVAILABLE": 503,
}


def _is_attach_seal_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "attach_seal_to_body"
    return isinstance(func, ast.Attribute) and func.attr == "attach_seal_to_body"


def _direct_attach_seal_call_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in API_DIR.glob("*.py"):
        if path.name == "_audit_seal.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        count = sum(1 for node in ast.walk(tree) if _is_attach_seal_call(node))
        if count:
            counts[path.relative_to(REPO_ROOT).as_posix()] = count
    return counts


def test_direct_attach_seal_calls_do_not_expand_without_review() -> None:
    """New paid JSON surfaces should issue seals through strict log_usage."""
    counts = _direct_attach_seal_call_counts()
    unexpected_files = sorted(set(counts) - set(_REVIEWED_DIRECT_ATTACH_SEAL_CALL_MAX_COUNTS))
    increased_counts = {
        path: (count, _REVIEWED_DIRECT_ATTACH_SEAL_CALL_MAX_COUNTS[path])
        for path, count in counts.items()
        if path in _REVIEWED_DIRECT_ATTACH_SEAL_CALL_MAX_COUNTS
        and count > _REVIEWED_DIRECT_ATTACH_SEAL_CALL_MAX_COUNTS[path]
    }

    assert unexpected_files == []
    assert increased_counts == {}


def _is_log_usage_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "log_usage"
    return isinstance(func, ast.Attribute) and func.attr == "log_usage"


def _has_strict_metering_enabled(call: ast.Call) -> bool:
    for keyword in call.keywords:
        if keyword.arg == "strict_metering":
            return not (isinstance(keyword.value, ast.Constant) and keyword.value.value is False)
    return False


def _status_code_value(node: ast.AST) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "status"
    ):
        return _HTTP_STATUS_ATTRS.get(node.attr)
    return None


def _keyword_status_code(call: ast.Call) -> int | None:
    for keyword in call.keywords:
        if keyword.arg == "status_code":
            return _status_code_value(keyword.value)
    return None


def _has_error_status_code(call: ast.Call) -> bool:
    status_code = _keyword_status_code(call)
    return status_code is not None and status_code >= 400


def _is_json_response_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "JSONResponse"
    return isinstance(func, ast.Attribute) and func.attr == "JSONResponse"


def _iter_shallow_log_usage_calls(stmt: ast.stmt) -> list[ast.Call]:
    calls: list[ast.Call] = []
    skipped_block_fields = {"body", "orelse", "finalbody", "handlers", "cases"}
    for field, value in ast.iter_fields(stmt):
        if field in skipped_block_fields:
            continue
        nodes = value if isinstance(value, list) else [value]
        for node in nodes:
            if isinstance(node, ast.AST):
                calls.extend(child for child in ast.walk(node) if _is_log_usage_call(child))
    return calls


def _iter_body_log_usage_calls(
    body: list[ast.stmt],
) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for stmt in body:
        calls.extend(node for node in _iter_shallow_log_usage_calls(stmt))

        child_bodies: list[list[ast.stmt]] = []
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            child_bodies.append(stmt.body)
        elif isinstance(stmt, (ast.If, ast.For, ast.AsyncFor, ast.While)):
            child_bodies.extend([stmt.body, stmt.orelse])
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            child_bodies.append(stmt.body)
        elif isinstance(stmt, ast.Try):
            child_bodies.extend([stmt.body, stmt.orelse, stmt.finalbody])
            child_bodies.extend(handler.body for handler in stmt.handlers)
        elif isinstance(stmt, ast.Match):
            child_bodies.extend(case.body for case in stmt.cases)

        for child_body in child_bodies:
            calls.extend(_iter_body_log_usage_calls(child_body))
    return calls


def _unstrict_log_usage_violations() -> list[str]:
    violations: list[str] = []
    paths = list(API_DIR.glob("*.py")) + list(BILLING_LOG_USAGE_PATHS)
    for path in paths:
        if path.name == "deps.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative_path = path.relative_to(REPO_ROOT).as_posix()
        for call in _iter_body_log_usage_calls(tree.body):
            if _has_strict_metering_enabled(call) or _has_error_status_code(call):
                continue
            violations.append(f"{relative_path}:{call.lineno}")
    return sorted(violations)


def test_api_log_usage_paid_success_paths_require_strict_metering() -> None:
    """Paid 2xx log_usage calls must opt in to strict metering."""
    assert _unstrict_log_usage_violations() == []
