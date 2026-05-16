"""CLI entry for the Wave 51 dim R federated-MCP recommendation module.

Usage
-----
    python -m jpintel_mcp.federated_mcp list
        Print the 6 curated partners as a JSON array.

    python -m jpintel_mcp.federated_mcp recommend "I need a freee invoice"
        Print up to 3 recommended partners as a JSON array.

    python -m jpintel_mcp.federated_mcp recommend "find a notion wiki page" --max 1
        Cap the recommendation count.

The CLI is for operator / agent ergonomics — no network call, no LLM
inference, no HTTP request. Pure-Python deterministic lookup against
the curated ``data/federated_partners.json`` shortlist.
"""

from __future__ import annotations

import argparse
import json
import sys

from jpintel_mcp.federated_mcp.recommend import recommend_handoff
from jpintel_mcp.federated_mcp.registry import load_default_registry


def _dump(partners: object) -> str:
    return json.dumps(partners, ensure_ascii=False, indent=2)


def _cmd_list(_args: argparse.Namespace) -> int:
    reg = load_default_registry()
    rows = [p.model_dump(mode="json") for p in reg.partners]
    print(_dump(rows))
    return 0


def _cmd_recommend(args: argparse.Namespace) -> int:
    if args.max < 1:
        print("--max must be >= 1", file=sys.stderr)
        return 2
    recs = recommend_handoff(args.query, max_results=args.max)
    rows = [p.model_dump(mode="json") for p in recs]
    print(_dump(rows))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m jpintel_mcp.federated_mcp",
        description=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="dump the 6 curated partners as JSON")

    rec = sub.add_parser(
        "recommend", help="recommend partners for a free-form query gap"
    )
    rec.add_argument(
        "query",
        help="free-form description of what jpcite cannot answer",
    )
    rec.add_argument(
        "--max",
        type=int,
        default=3,
        help="maximum recommendations to return (default: 3)",
    )

    args = parser.parse_args(argv)
    if args.cmd == "list":
        return _cmd_list(args)
    if args.cmd == "recommend":
        return _cmd_recommend(args)
    parser.error(f"unknown command: {args.cmd}")
    return 2  # pragma: no cover -- parser.error raises SystemExit


if __name__ == "__main__":
    sys.exit(main())
