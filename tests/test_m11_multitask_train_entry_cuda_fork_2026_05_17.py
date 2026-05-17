"""M11 multi-task train entrypoint CUDA/DataLoader guard tests."""

from __future__ import annotations

import ast
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ENTRYPOINT = REPO_ROOT / "scripts/aws_credit_ops/multitask_train_entry.py"


def _source_tree() -> ast.Module:
    return ast.parse(ENTRYPOINT.read_text(encoding="utf-8"))


def _collate_function(tree: ast.Module) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "collate":
            return node
    raise AssertionError("collate function not found")


def _calls_named(node: ast.AST, name: str) -> bool:
    return any(
        isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr == name
        for child in ast.walk(node)
    )


def test_dataloader_workers_stay_disabled_after_cuda_init() -> None:
    tree = _source_tree()
    assignments = {
        node.targets[0].id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"_DATALOADER_NUM_WORKERS", "_DATALOADER_PIN_MEMORY"}
        and isinstance(node.value, ast.Constant)
    }
    assert assignments == {
        "_DATALOADER_NUM_WORKERS": 0,
        "_DATALOADER_PIN_MEMORY": False,
    }
    dataloader_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "DataLoader"
    ]
    assert len(dataloader_calls) == 2
    for call in dataloader_calls:
        kwargs = {keyword.arg: keyword.value for keyword in call.keywords}
        assert isinstance(kwargs["num_workers"], ast.Name)
        assert kwargs["num_workers"].id == "_DATALOADER_NUM_WORKERS"
        assert isinstance(kwargs["pin_memory"], ast.Name)
        assert kwargs["pin_memory"].id == "_DATALOADER_PIN_MEMORY"


def test_collate_stays_cpu_only() -> None:
    collate = _collate_function(_source_tree())
    assert not _calls_named(collate, "to")
    assert not _calls_named(collate, "cuda")
