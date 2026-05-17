#!/usr/bin/env python3
"""MOAT P5 — Quality benchmark for the precomputed answer cache.

What it does
------------
Walks every row of ``am_actionable_answer_cache`` (target = 500 rows
produced by P3) and scores each envelope against an 8-axis **structural**
rubric. NO LLM calls anywhere — the rubric is purely deterministic so the
same input always produces the same score, which makes the benchmark
reproducible by external auditors.

8-axis rubric (1 point each, 0-8 total)
---------------------------------------
1. ``citation_density``  — at least 3 verbatim citation strings.
2. ``reasoning_depth``   — envelope walks at least 5 semantic sections.
3. ``freshness``         — ``corpus_snapshot_id`` or ``generated_at`` is
   within 30 days of today.
4. ``disclaimer_envelope`` — explicit §52 / §47条の2 / 行政書士法 / 司法書士
   / 社労士法 disclaimer marker present.
5. ``source_provenance`` — at least 3 unique HTTPS source URLs.
6. ``token_efficiency``  — payload size 800-2000 tokens.
7. ``cross_reference``   — at least 2 internal links to related answers.
8. ``edge_case_coverage`` — opposing view / 例外 / 不適格 marker present.

Outputs
-------
* JSON: ``data/quality_benchmark/precomputed_answers_2026_05_17.json``
* CSV : ``data/quality_benchmark/precomputed_answers_2026_05_17.csv``
* HTML: ``site/benchmark/jpcite_quality_score.html``

Constraints
-----------
* NO LLM API anywhere. Pure SQLite + stdlib + regex.
* mypy strict + ruff clean.
* Read-only on ``autonomath.db``.

Usage
-----
    .venv/bin/python scripts/quality/benchmark_precomputed_answers_2026_05_17.py
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as _dt
import html
import json
import logging
import os
import re
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

logger = logging.getLogger("autonomath.quality.benchmark_precomputed_answers")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "autonomath.db"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "quality_benchmark"
DEFAULT_OUT_HTML = REPO_ROOT / "site" / "benchmark" / "jpcite_quality_score.html"
DEFAULT_OUT_JSON_NAME = "precomputed_answers_2026_05_17.json"
DEFAULT_OUT_CSV_NAME = "precomputed_answers_2026_05_17.csv"

# Rubric thresholds (frozen for P5).
THRESHOLD_CITATION_COUNT = 3
THRESHOLD_REASONING_SECTIONS = 5
THRESHOLD_FRESHNESS_DAYS = 30
THRESHOLD_SOURCE_URL_UNIQUE = 3
THRESHOLD_TOKEN_LOW_BYTES = 3000
THRESHOLD_TOKEN_HIGH_BYTES = 8000
THRESHOLD_CROSS_REF_COUNT = 2

PRIORITY_HIGH_MIN_SCORE = 7
PRIORITY_LOW_MAX_SCORE = 4
WEAK_CELL_MAX_MEAN = 5.0
MAX_SCORE = 8

# Comparative analysis constants (P5 deliverable).
COST_OPUS_PER_TURN_JPY = 25.0
COST_JPCITE_PER_TURN_JPY = 3.0
OPUS_THEORETICAL_SCORE = 8.0

SHIGYO_COHORTS: tuple[str, ...] = (
    "税理士",
    "会計士",
    "行政書士",
    "司法書士",
    "社労士",
)

_RE_DISCLAIMER = re.compile(
    r"(税理士法\s*§?\s*52|公認会計士法\s*§?\s*47\s*条の?2|行政書士法\s*§?\s*1"
    r"|司法書士法\s*§?\s*3|社労士法\s*§?\s*27|景表法|消費者契約法)"
)

_SECTION_KEYS = (
    "basic",
    "amounts",
    "targeting",
    "rounds",
    "adoptions",
    "amendment_alerts",
    "amendment_diff",
    "compatibility",
    "exclusions",
    "case_studies",
    "enforcements",
    "corp_facts",
    "extraction",
    "top_matches",
    "reason_summary",
    "windows",
)
_SECTION_NARRATIVE_RE = re.compile(
    r"(結論|根拠|通達|判例|実務留意|関連書類|窓口|例外|不適格|リスク|脚注|出典)"
)

_CROSS_REF_KEYS = (
    "related_programs",
    "_next_calls",
    "next_calls",
    "cross_walk",
    "neighboring_programs",
    "similar_programs",
    "alternative_programs",
    "compat_matrix",
    "complementary",
)

_EDGE_KEYS = ("exclusions", "exclusion_rules", "warnings", "_warnings", "risk_flags")
_EDGE_NARRATIVE_RE = re.compile(r"(例外|不適格|対象外|リスク|警告|warning|exclude|exception)")

_RE_URL = re.compile(r"https?://[^\s\"'<>]+")

_RE_LEGAL_CITATION = re.compile(
    r"(法\s*§?\s*\d+(?:条の?\d+)?|法基通\s*\d+-\d+|消基通\s*\d+-\d+"
    r"|措置法\s*\d+|租特法\s*\d+|採択\s*第?\s*\d+回?|裁決\s*\d+)"
)


def _configure_logging(verbose: bool = False) -> None:
    root = logging.getLogger("autonomath.quality.benchmark_precomputed_answers")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


class AnswerScore(NamedTuple):
    subject_kind: str
    subject_id: str
    category: str
    byte_size: int
    citation_density: int
    reasoning_depth: int
    freshness: int
    disclaimer: int
    source_provenance: int
    token_efficiency: int
    cross_reference: int
    edge_case: int
    total: int

    @property
    def priority_bucket(self) -> str:
        if self.total >= PRIORITY_HIGH_MIN_SCORE:
            return "HIGH"
        if self.total <= PRIORITY_LOW_MAX_SCORE:
            return "LOW"
        return "MED"


def _flatten_strings(obj: Any) -> Iterator[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _flatten_strings(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _flatten_strings(item)


def _count_citations(payload: dict[str, Any]) -> int:
    leaves = list(_flatten_strings(payload))
    blob = "\n".join(leaves)
    url_hits = _RE_URL.findall(blob)
    legal_hits = _RE_LEGAL_CITATION.findall(blob)
    return len(url_hits) + len(legal_hits)


def _count_reasoning_sections(payload: dict[str, Any]) -> int:
    n = 0
    for key in _SECTION_KEYS:
        v = payload.get(key)
        if (
            (isinstance(v, dict) and v)
            or (isinstance(v, list) and v)
            or (isinstance(v, str) and v.strip())
        ):
            n += 1
    blob = "\n".join(_flatten_strings(payload))
    narrative_hits = len(set(_SECTION_NARRATIVE_RE.findall(blob)))
    return n + narrative_hits


def _is_fresh(payload: dict[str, Any], today: _dt.date) -> bool:
    candidates: list[str] = []
    for key in ("corpus_snapshot_id", "generated_at", "last_validated_at", "fetched_at"):
        v = payload.get(key)
        if isinstance(v, str):
            candidates.append(v)
    meta = payload.get("_cache_meta")
    if isinstance(meta, dict):
        v = meta.get("generated_at")
        if isinstance(v, str):
            candidates.append(v)
    enriched = payload.get("enriched")
    if isinstance(enriched, dict):
        meta2 = enriched.get("_meta")
        if isinstance(meta2, dict):
            for key in ("fetched_at", "snapshot_at"):
                v = meta2.get(key)
                if isinstance(v, str):
                    candidates.append(v)
    for s in candidates:
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                raw = s.replace("Z", "+00:00") if s.endswith("Z") else s
                if fmt == "%Y-%m-%dT%H:%M:%S%z":
                    ts = _dt.datetime.fromisoformat(raw)
                    parsed = ts.date()
                else:
                    parsed = _dt.datetime.strptime(s[: len(fmt)], fmt).date()
                age = (today - parsed).days
                if 0 <= age <= THRESHOLD_FRESHNESS_DAYS:
                    return True
                break
            except (ValueError, TypeError):
                continue
    return False


def _has_disclaimer(payload: dict[str, Any]) -> bool:
    blob = "\n".join(_flatten_strings(payload))
    return bool(_RE_DISCLAIMER.search(blob))


def _unique_source_urls(payload: dict[str, Any]) -> int:
    blob = "\n".join(_flatten_strings(payload))
    return len(set(_RE_URL.findall(blob)))


def _in_token_band(byte_size: int) -> bool:
    return THRESHOLD_TOKEN_LOW_BYTES <= byte_size <= THRESHOLD_TOKEN_HIGH_BYTES


def _count_cross_refs(payload: dict[str, Any]) -> int:
    n = 0
    for key in _CROSS_REF_KEYS:
        v = payload.get(key)
        if isinstance(v, list) or (isinstance(v, dict) and v):
            n += len(v)
        elif isinstance(v, str) and v.strip():
            n += 1
    return n


def _has_edge_case(payload: dict[str, Any]) -> bool:
    for key in _EDGE_KEYS:
        v = payload.get(key)
        if isinstance(v, dict) and v:
            return True
        if isinstance(v, list) and v:
            return True
        if isinstance(v, str) and v.strip():
            return True
    blob = "\n".join(_flatten_strings(payload))
    return bool(_EDGE_NARRATIVE_RE.search(blob))


def _extract_category(subject_kind: str, payload: dict[str, Any]) -> str:
    if subject_kind == "program":
        basic = payload.get("basic") or {}
        if isinstance(basic, dict):
            kind = basic.get("program_kind")
            if isinstance(kind, str) and kind:
                return kind
        return "unknown"
    if subject_kind == "houjin":
        basic = payload.get("basic") or {}
        if isinstance(basic, dict):
            ind = basic.get("industry_jsic_major")
            if isinstance(ind, str) and ind:
                return ind
        return "unknown"
    if subject_kind == "match":
        profile = payload.get("profile") or {}
        if isinstance(profile, dict):
            purpose = profile.get("purpose")
            if isinstance(purpose, str) and purpose:
                return purpose
        return "unknown"
    return "other"


def score_answer(
    subject_kind: str,
    subject_id: str,
    output_json: str,
    output_byte_size: int,
    today: _dt.date,
) -> AnswerScore:
    payload: dict[str, Any]
    try:
        payload = json.loads(output_json)
    except (TypeError, ValueError):
        payload = {}

    citations = _count_citations(payload)
    sections = _count_reasoning_sections(payload)
    fresh = 1 if _is_fresh(payload, today) else 0
    disclaimer = 1 if _has_disclaimer(payload) else 0
    unique_urls = _unique_source_urls(payload)
    in_band = 1 if _in_token_band(output_byte_size) else 0
    cross_refs = _count_cross_refs(payload)
    edge = 1 if _has_edge_case(payload) else 0

    citation_density = 1 if citations >= THRESHOLD_CITATION_COUNT else 0
    reasoning_depth = 1 if sections >= THRESHOLD_REASONING_SECTIONS else 0
    source_provenance = 1 if unique_urls >= THRESHOLD_SOURCE_URL_UNIQUE else 0
    cross_reference = 1 if cross_refs >= THRESHOLD_CROSS_REF_COUNT else 0

    total = (
        citation_density
        + reasoning_depth
        + fresh
        + disclaimer
        + source_provenance
        + in_band
        + cross_reference
        + edge
    )
    category = _extract_category(subject_kind, payload)
    return AnswerScore(
        subject_kind=subject_kind,
        subject_id=subject_id,
        category=category,
        byte_size=output_byte_size,
        citation_density=citation_density,
        reasoning_depth=reasoning_depth,
        freshness=fresh,
        disclaimer=disclaimer,
        source_provenance=source_provenance,
        token_efficiency=in_band,
        cross_reference=cross_reference,
        edge_case=edge,
        total=total,
    )


def _open_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=15.0)
    conn.row_factory = sqlite3.Row
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute("PRAGMA query_only = 1")
    return conn


def iter_cache_rows(conn: sqlite3.Connection) -> Iterator[tuple[str, str, str, int]]:
    cur = conn.execute(
        """SELECT subject_kind, subject_id, output_json,
                  COALESCE(output_byte_size, length(output_json)) AS byte_size
             FROM am_actionable_answer_cache
            ORDER BY subject_kind, subject_id"""
    )
    for row in cur:
        yield (
            str(row["subject_kind"]),
            str(row["subject_id"]),
            str(row["output_json"]),
            int(row["byte_size"] or 0),
        )


def _bucket_priority(s: AnswerScore) -> str:
    return s.priority_bucket


def aggregate(scores: list[AnswerScore]) -> dict[str, Any]:
    if not scores:
        return {
            "ok": False,
            "reason": "empty_cache",
            "total_answers": 0,
        }

    n = len(scores)
    total_scores = [s.total for s in scores]
    mean_total = statistics.fmean(total_scores)
    median_total = statistics.median(total_scores)
    score_histogram = Counter(total_scores)

    axes = (
        "citation_density",
        "reasoning_depth",
        "freshness",
        "disclaimer",
        "source_provenance",
        "token_efficiency",
        "cross_reference",
        "edge_case",
    )
    per_axis: dict[str, dict[str, float]] = {}
    for ax in axes:
        hits = sum(int(getattr(s, ax)) for s in scores)
        per_axis[ax] = {
            "pass": hits,
            "total": n,
            "pass_rate": round(hits / n, 4),
        }

    per_cohort: dict[str, dict[str, Any]] = {}
    by_cohort: dict[str, list[AnswerScore]] = defaultdict(list)
    for s in scores:
        by_cohort[s.subject_kind].append(s)
    for cohort, rows in by_cohort.items():
        sc = [r.total for r in rows]
        per_cohort[cohort] = {
            "n": len(rows),
            "mean_score": round(statistics.fmean(sc), 3),
            "median_score": round(statistics.median(sc), 3),
            "min_score": min(sc),
            "max_score": max(sc),
            "score_histogram": dict(Counter(sc)),
        }

    per_priority: dict[str, int] = Counter(_bucket_priority(s) for s in scores)

    per_category: dict[str, dict[str, dict[str, float | int]]] = {}
    for cohort, rows in by_cohort.items():
        by_cat: dict[str, list[AnswerScore]] = defaultdict(list)
        for r in rows:
            by_cat[r.category].append(r)
        per_category[cohort] = {}
        for cat, items in by_cat.items():
            sc2 = [it.total for it in items]
            per_category[cohort][cat] = {
                "n": len(items),
                "mean_score": round(statistics.fmean(sc2), 3),
                "median_score": round(statistics.median(sc2), 3),
                "min_score": min(sc2),
                "max_score": max(sc2),
            }

    weak_cells: list[dict[str, Any]] = []
    for cohort, cats in per_category.items():
        for cat, st in cats.items():
            mean = float(st["mean_score"])
            if mean < WEAK_CELL_MAX_MEAN:
                weak_cells.append(
                    {
                        "cohort": cohort,
                        "category": cat,
                        "n": int(st["n"]),
                        "mean_score": mean,
                    }
                )
    weak_cells.sort(key=lambda d: (d["mean_score"], -d["n"]))

    shigyo_heatmap: dict[str, dict[str, Any]] = {sh: {} for sh in SHIGYO_COHORTS}
    shigyo_filters: dict[str, list[tuple[str, str]]] = {
        "税理士": [("program", "incentive"), ("program", "tax_credit"), ("houjin", "*")],
        "会計士": [("houjin", "*"), ("program", "certification")],
        "行政書士": [("program", "incentive"), ("program", "permit"), ("match", "*")],
        "司法書士": [("houjin", "*"), ("program", "loan")],
        "社労士": [("program", "employment"), ("match", "small"), ("match", "*")],
    }
    for shigyo, filters in shigyo_filters.items():
        bucket: list[AnswerScore] = []
        for kind, cat_filter in filters:
            for s in scores:
                if s.subject_kind != kind:
                    continue
                if cat_filter == "*" or s.category == cat_filter:
                    bucket.append(s)
        if bucket:
            sc3 = [b.total for b in bucket]
            shigyo_heatmap[shigyo] = {
                "n": len(bucket),
                "mean_score": round(statistics.fmean(sc3), 3),
                "median_score": round(statistics.median(sc3), 3),
                "histogram": dict(Counter(sc3)),
            }
        else:
            shigyo_heatmap[shigyo] = {"n": 0, "mean_score": None, "median_score": None}

    quality_ratio = round(mean_total / OPUS_THEORETICAL_SCORE, 4)
    cost_ratio = round(COST_JPCITE_PER_TURN_JPY / COST_OPUS_PER_TURN_JPY, 4)
    value_cost_ratio = round(quality_ratio / cost_ratio, 3)
    saving_pct = round(1.0 - cost_ratio, 4)
    comparative = {
        "opus_baseline_score_theoretical": OPUS_THEORETICAL_SCORE,
        "jpcite_mean_score": round(mean_total, 3),
        "structural_quality_ratio": quality_ratio,
        "opus_cost_per_turn_jpy": COST_OPUS_PER_TURN_JPY,
        "jpcite_cost_per_turn_jpy": COST_JPCITE_PER_TURN_JPY,
        "cost_ratio_jpcite_over_opus": cost_ratio,
        "cost_saving_pct": saving_pct,
        "value_cost_ratio": value_cost_ratio,
        "interpretation": (
            f"jpcite delivers {quality_ratio:.1%} of theoretical Opus 4.7 "
            f"structural quality at {cost_ratio:.1%} of cost ({saving_pct:.1%} "
            f"saving) — {value_cost_ratio:.1f}x value/cost ratio."
        ),
    }

    return {
        "ok": True,
        "total_answers": n,
        "mean_score": round(mean_total, 3),
        "median_score": median_total,
        "max_score_possible": MAX_SCORE,
        "score_histogram": dict(score_histogram),
        "per_axis_pass_rate": per_axis,
        "per_cohort": per_cohort,
        "per_category": per_category,
        "per_priority_bucket": dict(per_priority),
        "shigyo_heatmap": shigyo_heatmap,
        "weak_cells": weak_cells,
        "comparative_analysis": comparative,
    }


def _write_json(path: Path, report: dict[str, Any]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    path.write_text(raw, encoding="utf-8")
    return len(raw.encode("utf-8"))


def _write_csv(path: Path, scores: Iterable[AnswerScore]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = (
        "subject_kind",
        "subject_id",
        "category",
        "byte_size",
        "citation_density",
        "reasoning_depth",
        "freshness",
        "disclaimer",
        "source_provenance",
        "token_efficiency",
        "cross_reference",
        "edge_case",
        "total",
        "priority_bucket",
    )
    written = 0
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(fields)
        for s in scores:
            writer.writerow(
                [
                    s.subject_kind,
                    s.subject_id,
                    s.category,
                    s.byte_size,
                    s.citation_density,
                    s.reasoning_depth,
                    s.freshness,
                    s.disclaimer,
                    s.source_provenance,
                    s.token_efficiency,
                    s.cross_reference,
                    s.edge_case,
                    s.total,
                    s.priority_bucket,
                ]
            )
            written += 1
    return written


def _render_html(report: dict[str, Any], today: _dt.date) -> str:
    n = int(report.get("total_answers", 0))
    mean = float(report.get("mean_score", 0.0))
    comparative = report.get("comparative_analysis", {})
    saving_pct = float(comparative.get("cost_saving_pct", 0.0))
    quality_ratio = float(comparative.get("structural_quality_ratio", 0.0))
    value_cost = float(comparative.get("value_cost_ratio", 0.0))

    per_axis = report.get("per_axis_pass_rate", {}) or {}
    axes_html_rows: list[str] = []
    for axis, st in per_axis.items():
        pass_rate = float(st.get("pass_rate", 0.0))
        bar_pct = round(pass_rate * 100, 1)
        axes_html_rows.append(
            f"<tr><td>{html.escape(axis)}</td>"
            f"<td class='num'>{int(st.get('pass', 0))}</td>"
            f"<td class='num'>{int(st.get('total', 0))}</td>"
            f"<td class='num'>{bar_pct:.1f}%</td>"
            f"<td><div class='bar' style='width:{bar_pct:.1f}%'></div></td>"
            f"</tr>"
        )

    cohort_rows: list[str] = []
    for cohort, st in (report.get("per_cohort", {}) or {}).items():
        cohort_rows.append(
            f"<tr><td>{html.escape(cohort)}</td>"
            f"<td class='num'>{int(st.get('n', 0))}</td>"
            f"<td class='num'>{float(st.get('mean_score', 0.0)):.2f}</td>"
            f"<td class='num'>{float(st.get('median_score', 0.0)):.2f}</td>"
            f"<td class='num'>{int(st.get('min_score', 0))}</td>"
            f"<td class='num'>{int(st.get('max_score', 0))}</td></tr>"
        )

    shigyo_rows: list[str] = []
    for shigyo, st in (report.get("shigyo_heatmap", {}) or {}).items():
        n_local = int(st.get("n", 0))
        if not n_local:
            shigyo_rows.append(
                f"<tr><td>{html.escape(shigyo)}</td><td class='num'>0</td>"
                "<td class='num'>n/a</td><td class='num'>n/a</td></tr>"
            )
            continue
        mean_local = float(st.get("mean_score", 0.0))
        median_local = float(st.get("median_score", 0.0))
        cls = (
            "high"
            if mean_local >= PRIORITY_HIGH_MIN_SCORE
            else ("low" if mean_local <= PRIORITY_LOW_MAX_SCORE else "mid")
        )
        shigyo_rows.append(
            f"<tr class='{cls}'><td>{html.escape(shigyo)}</td>"
            f"<td class='num'>{n_local}</td>"
            f"<td class='num'>{mean_local:.2f}</td>"
            f"<td class='num'>{median_local:.2f}</td></tr>"
        )

    weak_rows: list[str] = []
    weak_cells = report.get("weak_cells", []) or []
    for w in weak_cells[:30]:
        weak_rows.append(
            f"<tr><td>{html.escape(str(w['cohort']))}</td>"
            f"<td>{html.escape(str(w['category']))}</td>"
            f"<td class='num'>{int(w['n'])}</td>"
            f"<td class='num'>{float(w['mean_score']):.2f}</td></tr>"
        )

    priority = report.get("per_priority_bucket", {}) or {}
    high_n = int(priority.get("HIGH", 0))
    med_n = int(priority.get("MED", 0))
    low_n = int(priority.get("LOW", 0))

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>jpcite Quality Benchmark (P5) — {today.isoformat()}</title>
<meta name="description" content="jpcite precomputed answer cache の 8 軸構造的品質スコア — Opus 4.7 baseline との比較を含む透明性レポート">
<link rel="canonical" href="https://jpcite.com/benchmark/jpcite_quality_score.html">
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;
       margin:0;padding:32px 24px;color:#111;background:#fafafa;line-height:1.55;}}
  main{{max-width:980px;margin:0 auto;background:#fff;border:1px solid #e3e3e3;
        border-radius:8px;padding:32px;}}
  h1{{font-size:1.8rem;margin:0 0 8px;}}
  h2{{font-size:1.3rem;margin:32px 0 12px;border-bottom:1px solid #e3e3e3;padding-bottom:4px;}}
  table{{border-collapse:collapse;width:100%;margin:8px 0 24px;font-size:0.9rem;}}
  th,td{{border:1px solid #e3e3e3;padding:6px 10px;text-align:left;}}
  th{{background:#f2f2f2;}}
  td.num{{text-align:right;font-variant-numeric:tabular-nums;}}
  .bar{{height:10px;background:#5b8def;border-radius:2px;display:inline-block;}}
  tr.high{{background:#e6f6ea;}}
  tr.mid{{background:#fff7e0;}}
  tr.low{{background:#fde6e6;}}
  .kpi{{display:flex;gap:16px;flex-wrap:wrap;margin:16px 0 24px;}}
  .kpi .card{{flex:1 1 200px;background:#f5f8ff;border:1px solid #d6e0f5;
               padding:14px;border-radius:6px;}}
  .kpi .card .label{{font-size:0.75rem;color:#666;text-transform:uppercase;
                       letter-spacing:.05em;}}
  .kpi .card .value{{font-size:1.6rem;font-weight:600;color:#1f3a93;}}
  footer{{margin-top:48px;font-size:0.78rem;color:#777;}}
</style>
</head>
<body>
<main>
<h1>jpcite Quality Benchmark — P5 構造的スコア</h1>
<p>生成日 {today.isoformat()}。
500 件の precomputed answer envelope を 8 軸の構造的ルブリック (NO LLM) で評価した結果。
agent funnel の Justifiability stage における sales-grade 透明性レポート。</p>

<div class="kpi">
  <div class="card"><div class="label">Total answers</div><div class="value">{n}</div></div>
  <div class="card"><div class="label">Mean score (/ 8)</div><div class="value">{mean:.2f}</div></div>
  <div class="card"><div class="label">Quality vs Opus 4.7</div><div class="value">{quality_ratio:.1%}</div></div>
  <div class="card"><div class="label">Cost saving</div><div class="value">{saving_pct:.1%}</div></div>
  <div class="card"><div class="label">Value / cost ratio</div><div class="value">{value_cost:.1f}x</div></div>
</div>

<h2>8 軸別 pass rate</h2>
<table>
  <thead><tr><th>axis</th><th>pass</th><th>n</th><th>rate</th><th></th></tr></thead>
  <tbody>{"".join(axes_html_rows)}</tbody>
</table>

<h2>Priority bucket 分布</h2>
<p>HIGH (score &ge; {PRIORITY_HIGH_MIN_SCORE}): <b>{high_n}</b> /
 MED (5-6): <b>{med_n}</b> /
 LOW (&le; {PRIORITY_LOW_MAX_SCORE}): <b>{low_n}</b></p>

<h2>Cohort 別</h2>
<table>
  <thead><tr><th>cohort</th><th>n</th><th>mean</th><th>median</th><th>min</th><th>max</th></tr></thead>
  <tbody>{"".join(cohort_rows)}</tbody>
</table>

<h2>5 士業 heatmap</h2>
<table>
  <thead><tr><th>士業</th><th>n</th><th>mean</th><th>median</th></tr></thead>
  <tbody>{"".join(shigyo_rows)}</tbody>
</table>

<h2>Weak cells (mean &lt; {WEAK_CELL_MAX_MEAN:.0f})</h2>
<table>
  <thead><tr><th>cohort</th><th>category</th><th>n</th><th>mean</th></tr></thead>
  <tbody>{"".join(weak_rows) or "<tr><td colspan='4'>全 cell が閾値以上</td></tr>"}</tbody>
</table>

<h2>Comparative analysis vs Opus 4.7 baseline</h2>
<p>{html.escape(str(comparative.get("interpretation", "")))}</p>

<footer>
<p>Benchmark version: P5 (2026-05-17). NO LLM API。再現可能。</p>
<p>License: Bookyou株式会社 / jpcite. CC BY 4.0. Operator: info@bookyou.net.</p>
</footer>
</main>
</body>
</html>
"""


def _ensure_parents(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def run(
    db_path: Path,
    out_dir: Path,
    out_html: Path,
    today: _dt.date | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    _configure_logging(verbose)
    today = today or _dt.date.today()
    if not db_path.exists():
        return {"ok": False, "reason": "db_missing", "db_path": str(db_path)}

    conn = _open_db(db_path)
    try:
        scores: list[AnswerScore] = []
        for kind, sid, raw, byte_size in iter_cache_rows(conn):
            scores.append(score_answer(kind, sid, raw, byte_size, today))
        logger.info("scored %d cache rows", len(scores))
        report = aggregate(scores)
        report["benchmark_version"] = "P5"
        report["generated_at"] = today.isoformat()
        report["db_path"] = str(db_path)
        report["rubric_axes"] = [
            "citation_density",
            "reasoning_depth",
            "freshness",
            "disclaimer",
            "source_provenance",
            "token_efficiency",
            "cross_reference",
            "edge_case",
        ]

        json_path = out_dir / DEFAULT_OUT_JSON_NAME
        csv_path = out_dir / DEFAULT_OUT_CSV_NAME
        _ensure_parents(json_path)
        json_bytes = _write_json(json_path, report)
        rows_written = _write_csv(csv_path, scores)
        _ensure_parents(out_html)
        html_text = _render_html(report, today)
        out_html.write_text(html_text, encoding="utf-8")

        logger.info(
            "wrote json=%d bytes csv=%d rows html=%s",
            json_bytes,
            rows_written,
            out_html,
        )
        report["outputs"] = {
            "json": str(json_path),
            "csv": str(csv_path),
            "html": str(out_html),
            "json_bytes": json_bytes,
            "csv_rows": rows_written,
        }
        return report
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(_default_db_path()))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--out-html", default=str(DEFAULT_OUT_HTML))
    ap.add_argument("--today", default=None, help="YYYY-MM-DD (default: today)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    today_d: _dt.date | None = None
    if args.today:
        today_d = _dt.datetime.strptime(args.today, "%Y-%m-%d").date()

    report = run(
        db_path=Path(args.db),
        out_dir=Path(args.out_dir),
        out_html=Path(args.out_html),
        today=today_d,
        verbose=args.verbose,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 1


def _default_db_path() -> Path:
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return DEFAULT_DB


if __name__ == "__main__":
    sys.exit(main())
