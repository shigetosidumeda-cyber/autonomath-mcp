#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""assemble_trust_matrix.py — read monitoring/* + analytics/* + practitioner-eval/_data/* -> matrix_latest.json.

NO LLM CALL. Pure file IO + counting. Memory: feedback_no_operator_llm_api.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "site/trust/_data/matrix_latest.json"

# Anchor files — see DC_02 spec §2.1 dl block for narrative.
ANCHORS = {
    "jcrb": ROOT / "analytics/jcrb_summary_latest.json",
    "practitioner": ROOT / "site/practitioner-eval/_data/results_latest.json",
    "composite": ROOT / "monitoring/composite_benchmark_latest.jsonl",
    "source_receipts": ROOT / "monitoring/source_receipts_coverage.jsonl",
    "known_gaps": ROOT / "monitoring/known_gaps_display.jsonl",
    "anchor_verify": ROOT / "monitoring/audit_seal_roundtrip.jsonl",
    "acceptance": ROOT / "monitoring/acceptance_contract_pass.jsonl",
}


def status_for_rate(rate: float, green_th: float, yellow_th: float) -> tuple[str, str]:
    if rate >= green_th:
        return "OK", "green"
    if rate >= yellow_th:
        return "WARN", "yellow"
    return "FAIL", "red"


def stat_jcrb(p: Path) -> dict:
    if not p.exists():
        return {
            "id": "jcrb",
            "label": "JCRB benchmark",
            "status": "NO DATA",
            "status_class": "yellow",
            "last_refreshed": "never",
            "verified_count_real": 0,
            "synth_count": 0,
            "anchor_file": str(p.relative_to(ROOT)),
            "detail": "4-arm A/B/C/D / 16 metrics — first run pending",
        }
    j = json.loads(p.read_text(encoding="utf-8"))
    real = j.get("real_calls_total", 0)
    synth = j.get("synthesized_count", 0)
    leaked_seed = False
    for m in j.get("metrics", []):
        if not isinstance(m, dict):
            continue
        for v in m.values():
            if isinstance(v, dict) and v.get("kind") == "seed":
                leaked_seed = True
                break
        if leaked_seed:
            break
    if leaked_seed:
        status, klass = "FAIL (seed leak)", "red"
    else:
        status, klass = "OK", "green"
    return {
        "id": "jcrb",
        "label": "JCRB benchmark",
        "detail": "4-arm A/B/C/D × 16 metrics",
        "status": status,
        "status_class": klass,
        "last_refreshed": j.get("as_of_date") or j.get("generated_at", "unknown"),
        "verified_count_real": real,
        "synth_count": synth,
        "anchor_file": str(p.relative_to(ROOT)),
    }


def stat_practitioner(p: Path) -> dict:
    if not p.exists():
        return {
            "id": "practitioner_eval",
            "label": "Practitioner eval (15 personas × 3 queries)",
            "status": "NO DATA",
            "status_class": "red",
            "last_refreshed": "never",
            "verified_count_real": 0,
            "synth_count": 0,
            "anchor_file": str(p.relative_to(ROOT)),
            "detail": "must_include / must_not_claim / boundary",
        }
    j = json.loads(p.read_text(encoding="utf-8"))
    rows = [q for pres in j.get("persona_results", []) for q in pres.get("queries", [])]
    passed = sum(1 for q in rows if q.get("row_pass"))
    rate = passed / len(rows) if rows else 0.0
    status, klass = status_for_rate(rate, 0.95, 0.80)
    return {
        "id": "practitioner_eval",
        "label": "Practitioner eval (15 personas × 3 queries)",
        "detail": f"pass {passed}/{len(rows)} ({rate * 100:.1f}%)",
        "status": f"{status} ({rate * 100:.1f}%)",
        "status_class": klass,
        "last_refreshed": j.get("generated_at", "unknown"),
        "verified_count_real": passed,
        "synth_count": max(0, len(rows) - passed),
        "anchor_file": str(p.relative_to(ROOT)),
    }


def stat_jsonl_rate(
    p: Path,
    label: str,
    detail: str,
    key_pass: str = "passed",
    green: float = 0.95,
    yellow: float = 0.85,
) -> dict:
    if not p.exists():
        return {
            "id": p.stem,
            "label": label,
            "status": "NO DATA",
            "status_class": "red",
            "last_refreshed": "never",
            "verified_count_real": 0,
            "synth_count": 0,
            "anchor_file": str(p.relative_to(ROOT)),
            "detail": detail,
        }
    rows: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not rows:
        return {
            "id": p.stem,
            "label": label,
            "status": "EMPTY",
            "status_class": "yellow",
            "last_refreshed": "unknown",
            "verified_count_real": 0,
            "synth_count": 0,
            "anchor_file": str(p.relative_to(ROOT)),
            "detail": detail,
        }
    last = rows[-1]
    real = last.get("real_calls_total", last.get("total", 0))
    synth = last.get("synthesized_count", 0)
    passed = last.get(key_pass, 0)
    rate = passed / real if real else 0.0
    status, klass = status_for_rate(rate, green, yellow)
    return {
        "id": p.stem,
        "label": label,
        "detail": f"{detail} — {passed}/{real} ({rate * 100:.1f}%)",
        "status": f"{status} ({rate * 100:.1f}%)",
        "status_class": klass,
        "last_refreshed": last.get("as_of") or last.get("generated_at", "unknown"),
        "verified_count_real": real,
        "synth_count": synth,
        "anchor_file": str(p.relative_to(ROOT)),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=OUT)
    args = p.parse_args(argv)

    rows = [
        stat_jcrb(ANCHORS["jcrb"]),
        stat_practitioner(ANCHORS["practitioner"]),
        stat_jsonl_rate(ANCHORS["composite"], "Composite benchmark", "real/synth split visible"),
        stat_jsonl_rate(
            ANCHORS["source_receipts"],
            "Source receipts coverage",
            "% of paid responses with non-empty _source_receipts",
            green=0.99,
            yellow=0.95,
        ),
        stat_jsonl_rate(
            ANCHORS["known_gaps"],
            "Known gaps display rate",
            "% of responses showing _known_gaps",
            green=0.95,
            yellow=0.85,
        ),
        stat_jsonl_rate(
            ANCHORS["anchor_verify"],
            "Anchor verify success rate",
            "audit seal verify roundtrip",
            green=0.99,
            yellow=0.95,
        ),
        stat_jsonl_rate(
            ANCHORS["acceptance"],
            "Acceptance contract pass rate",
            "paid artifact min contract",
            green=0.95,
            yellow=0.85,
        ),
    ]

    snapshot_id = "unknown"
    if ANCHORS["practitioner"].exists():
        with contextlib.suppress(json.JSONDecodeError):
            snapshot_id = json.loads(ANCHORS["practitioner"].read_text(encoding="utf-8")).get(
                "corpus_snapshot_id", "unknown"
            )

    payload = {
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "corpus_snapshot_id": snapshot_id,
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
