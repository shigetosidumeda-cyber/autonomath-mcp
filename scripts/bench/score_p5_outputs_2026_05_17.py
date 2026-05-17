#!/usr/bin/env python3
"""scripts/bench/score_p5_outputs_2026_05_17.py — FF3 P5 LIVE rubric scorer.

Compares jpcite envelopes (`data/p5_benchmark/jpcite_outputs/*.json`)
against Opus 4.7 7-turn ground-truth envelopes
(`data/p5_benchmark/opus_4_7_outputs/*.json`) on a deterministic
**1-8 rubric** (each axis ∈ [0, 10] → total ∈ [0, 80]).

CRITICAL: **NO LLM-AS-JUDGE.** The eight axes are evaluated by
text-similarity / citation-overlap / structural-feature comparison,
all implementable with the stdlib. CLAUDE.md §3 forbids LLM imports
under `scripts/` so this file uses **stdlib + difflib only**.

Rubric (each 0..10):

  1. Correctness   — token-set Jaccard between jpcite ``output_text`` and
                     the Opus ``output_text``. (0..10 by 0.1 step.)
  2. Completeness  — fraction of Opus ``checklist_must_have`` tokens that
                     appear in the jpcite ``output_text``.
  3. Citation      — overlap of citation hostnames (intersection /
                     min(len(opus.citations), 1)).
  4. Currency      — credit for ``source_fetched_at`` ≥ 2026-01-01 on
                     every jpcite citation.
  5. Depth         — bonus for ≥ 4 tool-call steps in jpcite vs Opus
                     7-turn baseline.
  6. Concision     — penalty if jpcite ``output_text`` is > 4× longer
                     than Opus ``output_text``.
  7. Actionability — bonus if jpcite output references the V3 endpoint
                     surface that the Opus answer also references.
  8. Cohort-fit    — same cohort string + tier alignment with the
                     Opus fixture.

Inputs:
    data/p5_benchmark/queries_2026_05_17.yaml
    data/p5_benchmark/jpcite_outputs/*.json
    data/p5_benchmark/opus_4_7_outputs/*.json     (operator-generated; may be empty)

Outputs:
    data/p5_benchmark/scores/<query_id>.json     (per-query 8-axis breakdown)
    data/p5_benchmark/scores/_summary.json        (per-cohort aggregates +
                                                   target gates)

If an Opus fixture is missing for a given query, the scorer emits a
``score: null`` per-query envelope and a ``missing_opus_count`` counter
in the summary — never blocks the pipeline.

NO LLM IMPORTS.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
QUERY_PATH = REPO_ROOT / "data" / "p5_benchmark" / "queries_2026_05_17.yaml"
JPCITE_DIR = REPO_ROOT / "data" / "p5_benchmark" / "jpcite_outputs"
OPUS_DIR = REPO_ROOT / "data" / "p5_benchmark" / "opus_4_7_outputs"
SCORES_DIR = REPO_ROOT / "data" / "p5_benchmark" / "scores"
SUMMARY_PATH = SCORES_DIR / "_summary.json"

JAPANESE_TOKEN_RE = re.compile(r"[一-龯々ァ-ヴーぁ-ん0-9A-Za-z]+")
CURRENCY_CUTOFF = "2026-01-01"

# Score gates (from the dispatch).
GATE_AVG_RATIO = 0.70  # jpcite avg score ≥ Opus 70%.
GATE_COST_RATIO = 1.0 / 17.0  # jpcite cost ≤ Opus 1/17.


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "PyYAML missing. Install via `pip install pyyaml` (NOT an LLM SDK)."
        ) from exc
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise SystemExit(f"Expected mapping at top of {path}, got {type(loaded)!r}")
    return loaded


def _tokenize(text: str) -> set[str]:
    return set(JAPANESE_TOKEN_RE.findall(text or ""))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _hostnames(citations: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for cit in citations or []:
        url = cit.get("source_url", "")
        host = urlparse(url).hostname or ""
        if host:
            out.add(host.lower())
    return out


def _score_axes(jpcite_env: dict[str, Any], opus_env: dict[str, Any] | None) -> dict[str, float]:
    """Compute the 8-axis vector (each ∈ [0, 10]).

    If ``opus_env`` is None (operator has not yet generated the fixture
    for this query), every axis returns ``0.0`` and the per-query
    envelope is flagged ``missing_opus: true`` upstream.
    """
    if opus_env is None:
        return {
            "correctness": 0.0,
            "completeness": 0.0,
            "citation": 0.0,
            "currency": 0.0,
            "depth": 0.0,
            "concision": 0.0,
            "actionability": 0.0,
            "cohort_fit": 0.0,
        }

    jp_text: str = jpcite_env.get("output_text", "")
    op_text: str = opus_env.get("output_text", "")

    # 1. Correctness — Jaccard token overlap.
    correctness = round(_jaccard(_tokenize(jp_text), _tokenize(op_text)) * 10.0, 2)

    # 2. Completeness — fraction of must-have tokens present.
    must_have: list[str] = list(opus_env.get("checklist_must_have") or [])
    if must_have:
        hits = sum(1 for tok in must_have if tok in jp_text)
        completeness = round((hits / len(must_have)) * 10.0, 2)
    else:
        completeness = correctness  # fallback: token-overlap proxy.

    # 3. Citation — hostname intersection.
    jp_hosts = _hostnames(jpcite_env.get("citations", []))
    op_hosts = _hostnames(opus_env.get("citations", []))
    if op_hosts:
        cit_overlap = len(jp_hosts & op_hosts) / max(1, len(op_hosts))
        citation = round(min(1.0, cit_overlap) * 10.0, 2)
    else:
        citation = 10.0 if jp_hosts else 0.0

    # 4. Currency — every jpcite citation must be on/after CURRENCY_CUTOFF.
    cits = jpcite_env.get("citations", [])
    if cits:
        ok = sum(1 for c in cits if (c.get("source_fetched_at") or "") >= CURRENCY_CUTOFF)
        currency = round((ok / len(cits)) * 10.0, 2)
    else:
        currency = 0.0

    # 5. Depth — ≥ 4 tool steps → full credit.
    n_steps = len(jpcite_env.get("tool_calls") or [])
    depth = min(10.0, round(n_steps * 2.5, 2))

    # 6. Concision — penalty if jpcite text > 4× opus.
    if op_text:
        ratio = len(jp_text) / max(1, len(op_text))
        if ratio <= 4.0:
            concision = 10.0
        elif ratio <= 8.0:
            concision = 5.0
        else:
            concision = 0.0
    else:
        concision = 10.0 if jp_text else 0.0

    # 7. Actionability — overlap of endpoint names between jpcite tool_calls
    # and Opus tool_calls / referenced_endpoints.
    jp_endpoints = {str(c.get("endpoint", "")) for c in (jpcite_env.get("tool_calls") or [])}
    op_endpoints = set(opus_env.get("referenced_endpoints") or [])
    if not op_endpoints:
        op_endpoints = {str(c.get("endpoint", "")) for c in (opus_env.get("tool_calls") or [])}
    if op_endpoints:
        ovl = len(jp_endpoints & op_endpoints) / len(op_endpoints)
        actionability = round(min(1.0, ovl) * 10.0, 2)
    else:
        actionability = 5.0

    # 8. Cohort-fit — cohort string match + tier letter alignment.
    same_cohort = jpcite_env.get("cohort") == opus_env.get("cohort")
    same_tier = jpcite_env.get("tier") == opus_env.get("tier")
    cohort_fit = (5.0 if same_cohort else 0.0) + (5.0 if same_tier else 0.0)

    return {
        "correctness": correctness,
        "completeness": completeness,
        "citation": citation,
        "currency": currency,
        "depth": depth,
        "concision": concision,
        "actionability": actionability,
        "cohort_fit": cohort_fit,
    }


def _load_env(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return None
    return loaded


def run() -> dict[str, Any]:
    """Score every query in the YAML and return the aggregate summary."""
    data = _load_yaml(QUERY_PATH)
    queries = data.get("queries", [])
    SCORES_DIR.mkdir(parents=True, exist_ok=True)

    per_cohort_jpcite_total: dict[str, float] = {}
    per_cohort_opus_total: dict[str, float] = {}
    per_cohort_count: dict[str, int] = {}
    per_cohort_jpcite_cost: dict[str, int] = {}
    per_cohort_opus_cost: dict[str, int] = {}
    missing_opus = 0

    for q in queries:
        qid = str(q["id"])
        cohort = str(q["cohort"])
        jp_env = _load_env(JPCITE_DIR / f"{qid}.json")
        op_env = _load_env(OPUS_DIR / f"{qid}.json")
        if jp_env is None:
            # jpcite missing → counts as 0 score, still emit envelope.
            jp_env = {
                "query_id": qid,
                "cohort": cohort,
                "output_text": "",
                "citations": [],
                "tool_calls": [],
                "tier": q.get("expected_tier", "C"),
                "cost_jpy": 0,
            }
        axes = _score_axes(jp_env, op_env)
        total = round(sum(axes.values()), 2)
        opus_total = float(op_env.get("self_reported_score", 80.0)) if op_env else 0.0

        per_cohort_jpcite_total[cohort] = per_cohort_jpcite_total.get(cohort, 0.0) + total
        per_cohort_opus_total[cohort] = per_cohort_opus_total.get(cohort, 0.0) + opus_total
        per_cohort_count[cohort] = per_cohort_count.get(cohort, 0) + 1
        per_cohort_jpcite_cost[cohort] = per_cohort_jpcite_cost.get(cohort, 0) + int(
            jp_env.get("cost_jpy", 0)
        )
        if op_env:
            per_cohort_opus_cost[cohort] = per_cohort_opus_cost.get(cohort, 0) + int(
                op_env.get("cost_jpy_estimate", 0)
            )
        else:
            missing_opus += 1
            per_cohort_opus_cost.setdefault(cohort, 0)

        out = {
            "query_id": qid,
            "cohort": cohort,
            "axes": axes,
            "total": total,
            "opus_total": opus_total,
            "missing_opus": op_env is None,
            "jpcite_cost_jpy": int(jp_env.get("cost_jpy", 0)),
            "opus_cost_jpy_estimate": int(op_env.get("cost_jpy_estimate", 0)) if op_env else None,
        }
        (SCORES_DIR / f"{qid}.json").write_text(
            json.dumps(out, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    summary_rows: dict[str, dict[str, Any]] = {}
    for cohort, n in per_cohort_count.items():
        jp_avg = per_cohort_jpcite_total[cohort] / n if n else 0.0
        op_avg = per_cohort_opus_total[cohort] / n if n else 0.0
        jp_cost = per_cohort_jpcite_cost[cohort]
        op_cost = per_cohort_opus_cost.get(cohort, 0)
        avg_ratio = (jp_avg / op_avg) if op_avg else 0.0
        cost_ratio = (jp_cost / op_cost) if op_cost else 0.0
        summary_rows[cohort] = {
            "count": n,
            "jpcite_avg_score": round(jp_avg, 2),
            "opus_avg_score": round(op_avg, 2),
            "score_ratio": round(avg_ratio, 4),
            "score_gate_pass": avg_ratio >= GATE_AVG_RATIO,
            "jpcite_total_cost_jpy": jp_cost,
            "opus_total_cost_jpy_estimate": op_cost,
            "cost_ratio": round(cost_ratio, 4),
            "cost_gate_pass": (cost_ratio <= GATE_COST_RATIO) if op_cost else None,
        }

    summary = {
        "generated_at": "2026-05-17T00:00:00+09:00",
        "rubric_axes": [
            "correctness",
            "completeness",
            "citation",
            "currency",
            "depth",
            "concision",
            "actionability",
            "cohort_fit",
        ],
        "rubric_max_total": 80,
        "score_gate_avg_ratio": GATE_AVG_RATIO,
        "cost_gate_ratio": GATE_COST_RATIO,
        "missing_opus_count": missing_opus,
        "cohorts": summary_rows,
    }
    SUMMARY_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="FF3 P5 LIVE — deterministic rubric scorer (NO LLM)."
    )
    parser.parse_args(argv)
    summary = run()
    json.dump(summary, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
