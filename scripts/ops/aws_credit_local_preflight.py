#!/usr/bin/env python3
"""Run the deterministic local AWS credit preflight simulation."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _maybe_reexec_venv() -> None:
    """Use the repo virtualenv when invoked by a bare system python.

    uv-managed venvs symlink to a shared interpreter, so ``Path.resolve()``
    collapses ``.venv/bin/python`` and the global ``python3.12`` to the same
    file. Detect "already in venv" via ``sys.prefix`` instead.
    """

    venv_dir = _REPO_ROOT / ".venv"
    venv_python = venv_dir / "bin" / "python"
    if (
        venv_python.exists()
        and Path(sys.prefix).resolve() != venv_dir.resolve()
        and os.environ.get("JPCITE_NO_VENV_REEXEC") != "1"
    ):
        os.environ["JPCITE_NO_VENV_REEXEC"] = "1"
        os.execv(str(venv_python), [str(venv_python), *sys.argv])


_maybe_reexec_venv()

for _path in (_REPO_ROOT, _REPO_ROOT / "src"):
    _path_text = str(_path)
    if _path_text not in sys.path:
        sys.path.insert(0, _path_text)

from jpintel_mcp.agent_runtime.aws_credit_simulation import (
    GATE_READY,
    build_preflight_simulation,
    exposure_inputs_from_mapping,
)


def _load_payload(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("preflight input must be a JSON object")
    return payload


def build_report(input_path: Path | None = None) -> dict[str, Any]:
    payload = _load_payload(input_path)
    canary_conditions = payload.get("canary_conditions")
    if not isinstance(canary_conditions, dict):
        canary_conditions = {}

    return build_preflight_simulation(
        canary_conditions=canary_conditions,
        exposure_inputs=exposure_inputs_from_mapping(payload),
        inspection_evidence=payload,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Simulate the AWS credit preflight gate locally.")
    parser.add_argument(
        "--input",
        type=Path,
        help="Optional JSON fixture with canary_conditions and exposure_inputs.",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Always exit 0 after printing the report.",
    )
    args = parser.parse_args(argv)

    report = build_report(args.input)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.warn_only:
        return 0
    return 0 if report["gate_state"] == GATE_READY else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
