from __future__ import annotations

import ast
from pathlib import Path

PACKET_MODULES = (
    Path("src/jpintel_mcp/services/packets/agent_routing_decision.py"),
    Path("src/jpintel_mcp/services/packets/source_receipt_ledger.py"),
    Path("src/jpintel_mcp/services/packets/evidence_answer.py"),
    Path("src/jpintel_mcp/services/packets/outcome_catalog_summary.py"),
    Path("src/jpintel_mcp/services/packets/inline_registry.py"),
)
FORBIDDEN_IMPORTS = {
    "boto3",
    "botocore",
    "openai",
    "requests",
    "subprocess",
    "urllib.request",
}


def test_p0_packet_composers_have_no_live_runtime_dependencies() -> None:
    for path in PACKET_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )

        assert not (imports & FORBIDDEN_IMPORTS), path
        assert "datetime" not in imports
        assert "random" not in imports


def test_p0_packet_composer_source_has_no_live_execution_terms() -> None:
    for path in PACKET_MODULES:
        text = path.read_text(encoding="utf-8")
        assert "settle_artifact_charge" not in text
        assert "authorize_execute" not in text
        assert "client(" not in text
        assert ".execute(" not in text
