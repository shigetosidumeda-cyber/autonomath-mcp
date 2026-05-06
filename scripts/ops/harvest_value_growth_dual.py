#!/usr/bin/env python3
"""Summarize the dual-CLI value-growth research loop.

The two external CLI loops write under
tools/offline/_inbox/value_growth_dual/. This script is intentionally
read-only for source outputs and emits a compact markdown status report so the
main implementation loop can see which research artifacts are ready to use.
"""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = REPO_ROOT / "tools" / "offline" / "_inbox" / "value_growth_dual"
DEFAULT_OUT = DEFAULT_ROOT / "_integrated" / "MAIN_WORKSTREAM_STATUS.md"
JST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class InventoryItem:
    label: str
    path: Path
    exists: bool
    line_count: int
    item_count: int | None = None


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def _line_count(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    return len(_read_text(path).splitlines())


def _jsonl_count(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    return sum(1 for line in _read_text(path).splitlines() if line.strip())


def _pattern_count(path: Path, pattern: str) -> int:
    if not path.exists() or not path.is_file():
        return 0
    return len(re.findall(pattern, _read_text(path), flags=re.MULTILINE))


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _status(ok: bool) -> str:
    return "ready" if ok else "pending"


def _part_count(root: Path, slot_dir: str) -> int:
    parts = root / slot_dir / "parts"
    if not parts.exists():
        return 0
    return sum(1 for path in parts.glob("*.md") if path.is_file())


def load_agent_ledger(root: Path) -> tuple[int, int]:
    ledger = root / "_coordination" / "AGENT_LEDGER.csv"
    if not ledger.exists():
        return 0, 0

    rows = 0
    total_agents = 0
    with ledger.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows += 1
            try:
                total_agents += int(row.get("agent_count") or 0)
            except ValueError:
                continue
    return rows, total_agents


def build_inventory(root: Path) -> list[InventoryItem]:
    candidates: list[tuple[str, Path, str | None]] = [
        (
            "SLOT_A source profiles",
            root / "A_source_foundation" / "02_A_SOURCE_PROFILE.jsonl",
            "jsonl",
        ),
        ("SLOT_A schema backlog", root / "A_source_foundation" / "03_A_SCHEMA_BACKLOG.md", None),
        (
            "SLOT_A entity bridge",
            root / "A_source_foundation" / "04_A_ENTITY_BRIDGE_GRAPH.md",
            None,
        ),
        ("SLOT_A risk", root / "A_source_foundation" / "05_A_LICENSE_ROBOTS_RISK.md", None),
        ("SLOT_B persona map", root / "B_output_market" / "01_B_PERSONA_VALUE_MAP.md", None),
        (
            "SLOT_B artifact specs",
            root / "B_output_market" / "02_B_ARTIFACT_SPEC_CATALOG.md",
            "artifact",
        ),
        ("SLOT_B routing", root / "B_output_market" / "03_B_GEO_FIRST_HOP_ROUTING.md", None),
        ("SLOT_B eval queries", root / "B_output_market" / "04_B_EVAL_QUERIES.jsonl", "jsonl"),
        (
            "SLOT_B feature tickets",
            root / "B_output_market" / "06_B_FEATURE_TICKET_BACKLOG.md",
            "ticket",
        ),
        ("Integrated executive summary", root / "_integrated" / "00_EXECUTIVE_SUMMARY.md", None),
        (
            "Integrated top 30 tickets",
            root / "_integrated" / "01_TOP_30_IMPLEMENTATION_TICKETS.md",
            "ticket",
        ),
        (
            "Integrated source-artifact map",
            root / "_integrated" / "02_SOURCE_TO_ARTIFACT_MAP.md",
            None,
        ),
        ("Integrated next loop prompt", root / "_integrated" / "05_NEXT_LOOP_PROMPT.md", None),
    ]

    items: list[InventoryItem] = []
    for label, path, kind in candidates:
        item_count: int | None
        if kind == "jsonl":
            item_count = _jsonl_count(path)
        elif kind == "artifact":
            item_count = _pattern_count(path, r"^artifact_id\s*:")
        elif kind == "ticket":
            item_count = _pattern_count(path, r"^ticket_id\s*:")
        else:
            item_count = None
        items.append(
            InventoryItem(
                label=label,
                path=path,
                exists=path.exists(),
                line_count=_line_count(path),
                item_count=item_count,
            )
        )
    return items


def _claim_status(root: Path) -> list[tuple[str, str]]:
    coord = root / "_coordination"
    return [
        ("SLOT_A", _status((coord / "SLOT_A_CLAIM.md").exists())),
        ("SLOT_B", _status((coord / "SLOT_B_CLAIM.md").exists())),
        ("SLOT_A lock", _status((coord / "SLOT_A.lock").exists())),
        ("SLOT_B lock", _status((coord / "SLOT_B.lock").exists())),
    ]


def _gate_rows(items: list[InventoryItem]) -> list[tuple[str, str, str]]:
    by_label = {item.label: item for item in items}

    source_profiles = by_label["SLOT_A source profiles"].item_count or 0
    artifacts = by_label["SLOT_B artifact specs"].item_count or 0
    eval_queries = by_label["SLOT_B eval queries"].item_count or 0
    feature_tickets = by_label["SLOT_B feature tickets"].item_count or 0
    top_tickets = by_label["Integrated top 30 tickets"].item_count or 0

    return [
        ("SourceProfile >= 150", str(source_profiles), _status(source_profiles >= 150)),
        ("Artifact spec >= 30", str(artifacts), _status(artifacts >= 30)),
        ("Eval queries >= 150", str(eval_queries), _status(eval_queries >= 150)),
        ("Feature tickets >= 60", str(feature_tickets), _status(feature_tickets >= 60)),
        ("Integrated top tickets >= 30", str(top_tickets), _status(top_tickets >= 30)),
    ]


def render_markdown(root: Path) -> str:
    generated_at = datetime.now(UTC).astimezone(JST).isoformat(timespec="seconds")
    items = build_inventory(root)
    ledger_rows, total_agents = load_agent_ledger(root)

    lines: list[str] = [
        "# Value Growth Dual CLI Main Workstream Status",
        "",
        f"- generated_at: `{generated_at}`",
        f"- root: `{_relative(root)}`",
        f"- ledger_rows: `{ledger_rows}`",
        f"- total_agents_recorded: `{total_agents}`",
        f"- slot_a_part_files: `{_part_count(root, 'A_source_foundation')}`",
        f"- slot_b_part_files: `{_part_count(root, 'B_output_market')}`",
        "",
        "## Slot Claims",
        "",
        "| slot | status |",
        "|---|---|",
    ]
    for slot, status in _claim_status(root):
        lines.append(f"| {slot} | {status} |")

    lines.extend(
        [
            "",
            "## Output Inventory",
            "",
            "| output | status | lines | items | path |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for item in items:
        item_count = "" if item.item_count is None else str(item.item_count)
        lines.append(
            "| "
            f"{item.label} | {_status(item.exists)} | {item.line_count} | "
            f"{item_count} | `{_relative(item.path)}` |"
        )

    lines.extend(
        [
            "",
            "## Completion Gates",
            "",
            "| gate | observed | status |",
            "|---|---:|---|",
        ]
    )
    for gate, observed, status in _gate_rows(items):
        lines.append(f"| {gate} | {observed} | {status} |")

    lines.extend(
        [
            "",
            "## Main Workstream Next Actions",
            "",
            "1. If SLOT_A source profiles are ready, dry-run them through "
            "`scripts/cron/ingest_offline_inbox.py --tool public_source_foundation --dry-run` "
            "after copying or transforming them into the existing public_source_foundation inbox shape.",
            "2. If SLOT_B artifact specs are ready, map them to existing "
            "`src/jpintel_mcp/api/artifacts.py` builders before adding new endpoints.",
            "3. Keep OpenAPI/MCP/llms first-hop language aligned around "
            "`company_public_baseline`, `source_url`, `source_fetched_at`, "
            "`identity_confidence`, and `known_gaps`.",
            "4. Do not deploy from this report alone. Run targeted tests and the "
            "pre-deploy verification path after implementation changes.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print markdown to stdout instead of writing --out.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    text = render_markdown(args.root)
    if args.dry_run:
        print(text)
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + "\n", encoding="utf-8")
    print(_relative(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
