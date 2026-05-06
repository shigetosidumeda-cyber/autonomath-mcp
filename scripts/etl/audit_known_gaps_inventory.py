"""A8 audit: validate ``services.known_gaps.detect_gaps`` against live packets.

Runs ``EvidencePacketComposer.compose_for_query`` over a built-in panel of
30 sample queries (mix of program-search, free-text, houjin / invoice /
enforcement intents) and reports:

  * gap kind histogram across all packets
  * per-packet gap count
  * fraction of packets carrying ≥1 gap (target: ≥ 50%)

Read-only against the production sqlite mirrors. No network. No LLM.

Usage (from repo root)::

    .venv/bin/python scripts/etl/audit_known_gaps_inventory.py
    .venv/bin/python scripts/etl/audit_known_gaps_inventory.py --json

The default output is a markdown-friendly text block. ``--json`` emits a
single JSON document for downstream consumption.

When the live ``autonomath.db`` is unavailable (e.g. a fresh checkout)
the script gracefully reports the partial run and exits 0 — the gap
inventory contract is exercised regardless because each empty packet
still has its envelope-shape inspected.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Make the package importable when run directly from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from jpintel_mcp.services.evidence_packet import EvidencePacketComposer  # noqa: E402
from jpintel_mcp.services.known_gaps import detect_gaps  # noqa: E402

SAMPLE_QUERIES: tuple[tuple[str, dict[str, Any]], ...] = (
    # Program-search intents — broad surface across cohorts.
    ("IT導入補助金", {}),
    ("ものづくり補助金", {}),
    ("事業再構築補助金", {}),
    ("省力化投資補助金", {}),
    ("省エネ補助金", {}),
    ("GX 脱炭素 設備投資", {}),
    ("DX 中小企業 補助金", {}),
    ("研究開発税制", {}),
    ("インボイス 経過措置", {}),
    ("電子帳簿保存法 対応 補助金", {}),
    # Prefecture-flavored queries.
    ("東京都 設備投資 補助金", {"prefecture": "東京都"}),
    ("大阪府 創業 補助金", {"prefecture": "大阪府"}),
    ("北海道 農業 補助金", {"prefecture": "北海道"}),
    ("沖縄県 観光 補助金", {"prefecture": "沖縄県"}),
    # Generic/long-tail.
    ("認定新規就農者 給付金", {}),
    ("中小企業 賃上げ 補助", {}),
    ("人材確保 助成金", {}),
    ("事業承継 税制", {}),
    ("スタートアップ 創業 認定", {}),
    ("小規模事業者 持続化", {}),
    # Loan / 融資 axis.
    ("日本政策金融公庫 創業融資", {}),
    ("商工中金 融資", {}),
    ("セーフティネット 保証", {}),
    # Tax / 税制 axis.
    ("特別償却 税額控除", {}),
    ("固定資産税 軽減", {}),
    # Enforcement / regulatory axis.
    ("行政処分 法人番号 8010001213708", {}),
    ("業務停止命令", {}),
    # Invoice / 法人番号 specific.
    ("適格請求書 T8010001213708 登録日", {}),
    ("法人番号 1234567890123 採択", {}),
    # Free-text & messy.
    ("中小企業 が 使える 補助金 を 教えてください", {}),
)


def _resolve_db_paths() -> tuple[Path, Path]:
    """Resolve jpintel.db / autonomath.db with sensible fallbacks."""
    candidates_jp = [
        _REPO_ROOT / "data" / "jpintel.db",
        _REPO_ROOT / "jpintel.db",
    ]
    candidates_am = [
        _REPO_ROOT / "autonomath.db",
        _REPO_ROOT / "data" / "autonomath.db",
    ]
    jp = next((p for p in candidates_jp if p.exists() and p.stat().st_size > 0), candidates_jp[0])
    am = next((p for p in candidates_am if p.exists() and p.stat().st_size > 0), candidates_am[0])
    return jp, am


def _run_one(
    composer: EvidencePacketComposer,
    query_text: str,
    filters: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        packet = composer.compose_for_query(
            query_text,
            filters=filters,
            limit=10,
            include_facts=True,
            include_rules=False,
            include_compression=False,
        )
    except Exception as exc:  # pragma: no cover - audit script defensive surface
        return ({"error": str(exc), "query": query_text}, [])
    inventory = detect_gaps(packet)
    return (packet, inventory)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    p.add_argument(
        "--target-ratio",
        type=float,
        default=0.5,
        help="Required fraction of packets reporting ≥1 gap (default 0.5).",
    )
    args = p.parse_args(argv)

    jp_db, am_db = _resolve_db_paths()
    composer = EvidencePacketComposer(jpintel_db=jp_db, autonomath_db=am_db)

    histogram: Counter[str] = Counter()
    packets_with_gaps = 0
    packets_total = len(SAMPLE_QUERIES)
    packet_records: list[dict[str, Any]] = []

    for q, filters in SAMPLE_QUERIES:
        packet, inventory = _run_one(composer, q, filters)
        kinds = sorted({entry["kind"] for entry in inventory})
        if kinds:
            packets_with_gaps += 1
        for k in kinds:
            histogram[k] += 1
        record_count = len(packet.get("records", []) or [])
        packet_records.append(
            {
                "query": q,
                "filters": filters,
                "record_count": record_count,
                "gap_kinds": kinds,
                "gap_total": len(inventory),
            }
        )

    ratio = packets_with_gaps / packets_total if packets_total else 0.0
    summary = {
        "packets_total": packets_total,
        "packets_with_gaps": packets_with_gaps,
        "packets_with_gaps_ratio": round(ratio, 4),
        "target_ratio": args.target_ratio,
        "target_met": ratio >= args.target_ratio,
        "kind_histogram": dict(sorted(histogram.items(), key=lambda kv: -kv[1])),
        "jpintel_db": str(jp_db),
        "autonomath_db": str(am_db),
        "per_packet": packet_records,
    }

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["target_met"] else 1

    print(f"# A8 known_gaps audit ({packets_total} sample queries)")
    print()
    print(f"- packets total          : {packets_total}")
    print(f"- packets with ≥1 gap    : {packets_with_gaps}")
    print(f"- ratio with ≥1 gap      : {ratio:.2%}")
    print(f"- target ratio           : {args.target_ratio:.0%}")
    print(f"- target met             : {summary['target_met']}")
    print(f"- jpintel.db             : {jp_db}")
    print(f"- autonomath.db          : {am_db}")
    print()
    print("## kind histogram")
    print()
    if not histogram:
        print("(no gaps detected — corpus may be empty or fully clean)")
    else:
        for kind, count in summary["kind_histogram"].items():
            print(f"- {kind}: {count}")
    print()
    print("## per-packet")
    print()
    for rec in packet_records:
        kinds_str = ", ".join(rec["gap_kinds"]) if rec["gap_kinds"] else "(none)"
        print(
            f"- `{rec['query']}` filters={rec['filters']} "
            f"records={rec['record_count']} gaps={rec['gap_total']} "
            f"[{kinds_str}]"
        )
    return 0 if summary["target_met"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
