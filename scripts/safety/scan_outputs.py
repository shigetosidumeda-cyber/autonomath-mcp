#!/usr/bin/env python3
"""CLI runner for the JPCIR safety scanners.

Usage::

    python scripts/safety/scan_outputs.py <path>
    python scripts/safety/scan_outputs.py <s3_uri>
    python scripts/safety/scan_outputs.py path1 path2 path3

Accepts either a local file, a local directory (recursively walked for
``*.json`` files), or an S3 URI (``s3://bucket/key`` for a single object,
``s3://bucket/prefix/`` for a recursive prefix walk).

Exits ``0`` when zero violations were found, ``1`` when one or more
violations were found, ``2`` for argument / IO error.

The CLI invokes:

* :func:`jpintel_mcp.safety_scanners.scan_no_hit_regressions` on each file.
* :func:`jpintel_mcp.safety_scanners.scan_forbidden_claims` on each file.

Output is JSON-on-stdout::

    {
      "summary": {"files_scanned": 12, "violation_count": 0},
      "violations": []
    }

The MCP / FastAPI surface NEVER imports this script directly — it lives
under ``scripts/`` so the safety scanners can run in CI / cron / canary
without dragging the server boot path. The scanners themselves
(``src/jpintel_mcp/safety_scanners/``) are import-safe from any layer.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Make ``src/`` importable so the CLI works without `pip install -e .` in
# minimal CI runners.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.safety_scanners import (  # noqa: E402
    Violation,
    scan_forbidden_claims,
    scan_no_hit_regressions,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator


def _looks_like_s3(uri: str) -> bool:
    return uri.startswith("s3://")


def _split_s3_uri(uri: str) -> tuple[str, str]:
    body = uri[len("s3://") :]
    if "/" not in body:
        return body, ""
    bucket, _, key = body.partition("/")
    return bucket, key


def _iter_local_paths(root: Path) -> Iterator[Path]:
    if root.is_file():
        yield root
        return
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*.json")):
        if path.is_file():
            yield path


def _iter_s3_objects(uri: str) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ``(s3_uri, envelope_dict)`` for every object under the prefix.

    Imports ``boto3`` lazily so a developer can use the local-file scanner
    without installing AWS extras. PERF-35: prefers the shared client
    pool in :mod:`scripts.aws_credit_ops._aws` so the 200-500 ms boto3
    cold-start tax is paid once per ``(service, region)`` per process,
    and falls back to a direct ``boto3.client`` call when the pool
    module is unavailable (e.g. minimal CI runners).
    """
    bucket, key_or_prefix = _split_s3_uri(uri)
    try:
        from scripts.aws_credit_ops._aws import get_client
    except ImportError:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - only hit when AWS extra missing
            raise RuntimeError(
                "S3 scanning requires the `boto3` package. Install with: pip install boto3"
            ) from exc
        client = boto3.client("s3")
    else:
        client = get_client("s3")
    if key_or_prefix and not key_or_prefix.endswith("/"):
        # Single-object form.
        obj = client.get_object(Bucket=bucket, Key=key_or_prefix)
        body = obj["Body"].read()
        yield (uri, json.loads(body.decode("utf-8")))
        return
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=key_or_prefix):
        for item in page.get("Contents", []) or []:
            key = item["Key"]
            if not key.endswith(".json"):
                continue
            obj = client.get_object(Bucket=bucket, Key=key)
            body = obj["Body"].read()
            uri_for_item = f"s3://{bucket}/{key}"
            yield (uri_for_item, json.loads(body.decode("utf-8")))


def _scan_envelope(source: str, envelope: Any) -> list[Violation]:
    violations: list[Violation] = []
    violations.extend(scan_no_hit_regressions(envelope, source=source))
    violations.extend(scan_forbidden_claims(envelope, source=source))
    return violations


def _scan_one_local(path: Path) -> tuple[int, list[Violation]]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            envelope = json.load(fh)
    except json.JSONDecodeError as exc:
        return 1, [
            Violation(
                scanner="cli",
                packet_id="<unparseable>",
                path="$",
                code="unparseable_json",
                detail=f"JSONDecodeError: {exc}",
                source=str(path),
            )
        ]
    except OSError as exc:
        return 1, [
            Violation(
                scanner="cli",
                packet_id="<unreadable>",
                path="$",
                code="unreadable_file",
                detail=f"OSError: {exc}",
                source=str(path),
            )
        ]
    return 1, _scan_envelope(str(path), envelope)


def _scan_target(target: str) -> tuple[int, list[Violation]]:
    """Return ``(files_scanned, violations)`` for a single target string."""
    files = 0
    all_violations: list[Violation] = []

    if _looks_like_s3(target):
        for s3_uri, envelope in _iter_s3_objects(target):
            files += 1
            all_violations.extend(_scan_envelope(s3_uri, envelope))
        return files, all_violations

    path = Path(target)
    if not path.exists():
        return 0, [
            Violation(
                scanner="cli",
                packet_id="<missing>",
                path="$",
                code="missing_path",
                detail=f"path does not exist: {target}",
                source=target,
            )
        ]
    if path.is_file():
        return _scan_one_local(path)
    for entry in _iter_local_paths(path):
        scanned, file_violations = _scan_one_local(entry)
        files += scanned
        all_violations.extend(file_violations)
    return files, all_violations


def run(targets: Iterable[str], *, stream: Any = sys.stdout) -> int:
    """Run the scanner over each target and write a JSON report to ``stream``.

    Returns the process exit code: ``0`` clean, ``1`` violations, ``2`` arg error.
    """
    target_list = list(targets)
    if not target_list:
        print("error: no <path_or_s3_uri> argument provided", file=sys.stderr)
        return 2

    files_scanned = 0
    all_violations: list[Violation] = []
    for target in target_list:
        scanned, target_violations = _scan_target(target)
        files_scanned += scanned
        all_violations.extend(target_violations)

    report: dict[str, Any] = {
        "summary": {
            "files_scanned": files_scanned,
            "violation_count": len(all_violations),
            "targets": list(target_list),
        },
        "violations": [v.to_dict() for v in all_violations],
    }
    stream.write(json.dumps(report, ensure_ascii=False, indent=2))
    stream.write("\n")
    return 1 if all_violations else 0


def _parse_argv(argv: list[str] | None = None) -> list[str]:
    parser = argparse.ArgumentParser(
        prog="scan_outputs",
        description=(
            "Scan JPCIR envelope JSON files for no-hit regression + forbidden-claim violations."
        ),
    )
    parser.add_argument(
        "targets",
        nargs="+",
        metavar="<path_or_s3_uri>",
        help="local file/directory or s3://bucket/key[/prefix/]",
    )
    namespace = parser.parse_args(argv)
    return list(namespace.targets)


def main(argv: list[str] | None = None) -> int:
    targets = _parse_argv(argv)
    return run(targets)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
