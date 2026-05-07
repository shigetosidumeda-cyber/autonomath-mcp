#!/usr/bin/env python3
"""
compute_dirty_fingerprint.py

DEEP-56 dirty tree fingerprint generator for jpcite v0.3.4 production deploy.

Generates the dirty tree fingerprint object that
``scripts/ops/production_deploy_go_gate.py`` consumes from the operator ACK
YAML when ``--allow-dirty`` is passed. The 7 fields the gate requires:

  1. current_head                      (str, sha1 git commit)
  2. dirty_entries                     (int)
  3. status_counts                     (dict[str,int])
  4. lane_counts                       (dict[str,int])
  5. path_sha256                       (str)
  6. content_sha256                    (str)
  7. content_hash_skipped_large_files  (list[str])

The actual algorithm lives in the canonical SOT helper
``scripts/ops/repo_dirty_lane_report.compute_canonical_dirty_fingerprint``.
This CLI is a thin shell so the operator-side fingerprint binds bit-for-bit
with the gate-side fingerprint. Drift between the two re-introduces the
4/5 PASS stall on ``operator_ack_signoff.py --all --commit``.

Constraints:
  - LLM API call count: 0 (no third-party AI SDK imports of any kind)
  - paid API call count: 0 (pure git + hashlib via the SOT helper)
  - net call count: 0 (only subprocess git)
  - stdlib + PyYAML only

Usage:
    python compute_dirty_fingerprint.py [--repo PATH] [--format json|yaml]
                                        [--out FILE]

Spec: tools/offline/_inbox/value_growth_dual/_deep_plan/
        DEEP_56_dirty_tree_fingerprint_generator.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# Locate the canonical SOT helper. The operator-review CLI lives under
# ``tools/offline/operator_review/`` so we walk up to the repo root and
# add ``scripts/ops/`` to ``sys.path``.
HERE = Path(__file__).resolve().parent
REPO_ROOT_DEFAULT = HERE.parents[2]
SOT_DIR = REPO_ROOT_DEFAULT / "scripts" / "ops"
if str(SOT_DIR) not in sys.path:
    sys.path.insert(0, str(SOT_DIR))

# noqa: E402 — the sys.path insert above is required for this import.
from repo_dirty_lane_report import (  # type: ignore  # noqa: E402
    classify_path,
    collect_status_lines,
    compute_canonical_dirty_fingerprint,
)

# ---------------------------------------------------------------------------
# Backwards-compatibility surface kept for older callers / tests
# ---------------------------------------------------------------------------


def classify_lane(path: str) -> str:
    """Compatibility shim — delegates to the canonical SOT classifier.

    Older tests import ``classify_lane`` directly. The canonical SOT lives in
    ``repo_dirty_lane_report.classify_path``; we forward there so both gate
    and CLI agree on the 16-lane taxonomy.
    """
    return classify_path(path)


def compute_fingerprint(
    repo: Path,
    skip_large: int | None = None,  # accepted for backwards compat; SOT uses 64 MiB
    workers: int | None = None,  # accepted for backwards compat; SOT is sequential
) -> dict:
    """Build the canonical fingerprint for ``repo``.

    ``skip_large`` and ``workers`` are accepted for backwards compatibility
    with older callers / tests but are ignored — the SOT helper picks the
    threshold from
    ``repo_dirty_lane_report.LARGE_FILE_CONTENT_HASH_THRESHOLD_BYTES`` and
    runs single-threaded (the gate-side reference implementation does too).
    """
    del skip_large, workers
    return compute_canonical_dirty_fingerprint(repo)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def dump_json(fp: dict) -> str:
    return json.dumps(fp, ensure_ascii=False, indent=2, sort_keys=False)


def dump_yaml(fp: dict) -> str:
    try:
        import yaml  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "PyYAML required for --format yaml; install with `pip install pyyaml`"
        ) from exc
    return yaml.safe_dump(fp, sort_keys=False, default_flow_style=False, allow_unicode=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="compute_dirty_fingerprint",
        description="DEEP-56 dirty tree fingerprint generator for jpcite",
    )
    p.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="Path to jpcite git repo (default: cwd)",
    )
    p.add_argument(
        "--format",
        choices=("json", "yaml"),
        default="json",
        help="Output format (default: json)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output file (default: stdout)",
    )
    # ``--skip-large`` and ``--workers`` are kept for argparse compatibility
    # with older invocations (`operator_ack_signoff.py` doesn't pass them
    # but external scripts might). They are no-ops under the SOT helper.
    p.add_argument(
        "--skip-large",
        type=int,
        default=None,
        help="DEPRECATED — SOT helper uses 64 MiB; flag retained for compatibility.",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        help="DEPRECATED — SOT helper runs sequentially; flag retained for compatibility.",
    )
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    repo = args.repo.resolve()
    if not (repo / ".git").exists():
        print(
            f"error: {repo} is not a git repository (no .git/ found)",
            file=sys.stderr,
        )
        return 2

    # Source raw porcelain lines via the SOT helper to guarantee both sides
    # of the deploy gate read identical input.
    lines = collect_status_lines(repo)
    fp = compute_canonical_dirty_fingerprint(repo, lines)

    out = dump_json(fp) if args.format == "json" else dump_yaml(fp)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(out, encoding="utf-8")
    else:
        sys.stdout.write(out)
        if not out.endswith("\n"):
            sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
