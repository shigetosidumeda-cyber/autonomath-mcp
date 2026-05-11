#!/usr/bin/env python3
"""
geo_weekly_bench_v3.py — jpcite GEO (Generative Engine Optimization) 週次 bench harness v3.

5 surface (ChatGPT / Claude / Cursor / Codex / Gemini) × 100 ja questions の
citation 計測を集計する。

## 計測方式

CSV import 一択 (Memory feedback_no_operator_llm_api + feedback_autonomath_no_api_use:
我々が LLM API を呼んだ瞬間に赤字構造。代替として user が各 surface の web UI で
質問を貼って回答をコピペし、CSV に保存する手動 workflow を採用).

WebFetch は採用しない。理由:

- ChatGPT / Claude / Gemini いずれも search-grounded chat の HTTP API は
  公開 endpoint がなく、ログイン session token を投げる必要がある (= 結局
  人手か bot 化)。
- "公開検索 UI 直叩き" は ToS 違反になりやすい (我々は memory
  feedback_data_collection_tos_ignore の対象 = 政府データ収集には適用するが、
  LLM SaaS の web UI には適用しない)。
- 100 問 × 5 surface × 週1 は手動でも 1-2 時間で終わるので、SaaS 側 ToS と
  赤字回避を優先。

将来 WebFetch を採用する場合は、Claude Code の WebFetch tool を operator が
別途 walk して response を CSV に流し込む形にする (= 本 script は CSV を
唯一の入力 contract にしておけば再利用できる)。

## 入出力

入力:
  - data/geo_questions.json (104 questions、B/S/D/R/C + 4 en overflow)
  - data/geo_responses/{surface}_{ISO_WEEK}.csv
      header: question_id,response_text,citation_url,citation_position
    - question_id: data/geo_questions.json の "id" と一致 (例 "B01")
    - response_text: surface の生回答テキスト (改行は \\n エスケープ or CSV quote)
    - citation_url: 任意。空欄なら response_text から自動検出
    - citation_position: 任意 (出典リスト中の順位、1-indexed)。空欄可

出力:
  - docs/bench/geo_week_{ISO_WEEK}.json
      surface 別 / category 別 citation rate + per-question 詳細 + 4 週 trend
  - docs/bench/geo_week_{ISO_WEEK}.md
      Markdown サマリー (前週 delta 表 + 4 週 trend ASCII chart)

## citation 判定ロジック

jpcite_cited = True iff いずれか満たす:
  1. response_text に "jpcite.com" / "jpcite" / "autonomath-mcp" / "zeimu-kaikei.ai" が
     case-insensitive で含まれる
  2. citation_url 列に上記 host を含む URL がある

citation_url が空欄かつ jpcite_cited=True の場合、response_text から regex で
最初に出現する jpcite host URL を抽出して埋める。

## CLI

  # 今週分を集計 (デフォルト = 現在の ISO week)
  python3 scripts/ops/geo_weekly_bench_v3.py

  # 特定週を指定
  python3 scripts/ops/geo_weekly_bench_v3.py --week 2026-W19

  # CSV template を吐く (空欄で 100 行)
  python3 scripts/ops/geo_weekly_bench_v3.py --emit-template chatgpt

  # 過去 4 週 trend のみ再計算 (CSV 再 read 必要)
  python3 scripts/ops/geo_weekly_bench_v3.py --week 2026-W19 --trend-only

## 依存

requests + urllib + csv + json + argparse + datetime + re + pathlib + sys
(他ライブラリ禁止。requests は本 script では未使用だが future-proof として
import 可能リストに残す)
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ----------------------------------------------------------------------
# constants
# ----------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS_PATH = ROOT / "data" / "geo_questions.json"
RESPONSES_DIR = ROOT / "data" / "geo_responses"
OUTPUT_DIR = ROOT / "docs" / "bench"

SURFACES = ["chatgpt", "claude", "cursor", "codex", "gemini"]

CATEGORIES = [
    "branded",
    "non-branded.business",
    "non-branded.data",
    "non-branded.subsidy",
    "competitor",
]

# CATEGORY -> prefix
CATEGORY_PREFIX = {
    "branded": "B",
    "non-branded.business": "S",
    "non-branded.data": "D",
    "non-branded.subsidy": "R",
    "competitor": "C",
}

# jpcite host markers (lower-case substrings to grep in response_text)
JPCITE_MARKERS = [
    "jpcite.com",
    "jpcite",
    "autonomath-mcp",
    "zeimu-kaikei.ai",
    "api.jpcite.com",
]

# URL extraction regex (HTTP/HTTPS only; stop at whitespace or close-paren)
URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+", re.IGNORECASE)

CSV_HEADER = ["question_id", "response_text", "citation_url", "citation_position"]


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def iso_week_of(d: date) -> str:
    """Return ISO 8601 week string like '2026-W19'."""
    iso_year, iso_week, _ = d.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"


def parse_iso_week(s: str) -> tuple[int, int]:
    """Parse '2026-W19' -> (2026, 19). Raises ValueError if malformed."""
    m = re.fullmatch(r"(\d{4})-W(\d{1,2})", s)
    if not m:
        raise ValueError(f"week must look like 'YYYY-Www', got {s!r}")
    return int(m.group(1)), int(m.group(2))


def prev_iso_week(week: str, steps: int = 1) -> str:
    """Step back N ISO weeks from `week`."""
    y, w = parse_iso_week(week)
    # Monday of given ISO week
    monday = date.fromisocalendar(y, w, 1)
    target = monday - timedelta(weeks=steps)
    return iso_week_of(target)


def load_questions() -> list[dict[str, Any]]:
    if not QUESTIONS_PATH.exists():
        raise FileNotFoundError(f"missing {QUESTIONS_PATH}")
    data = json.loads(QUESTIONS_PATH.read_text("utf-8"))
    qs = data.get("questions", [])
    if not qs:
        raise ValueError("geo_questions.json has empty 'questions' array")
    return qs


def detect_jpcite_citation(
    response_text: str, citation_url: str
) -> tuple[bool, str | None]:
    """
    Return (jpcite_cited, citation_url).

    Heuristic:
      1. If citation_url contains a jpcite marker -> True with the url.
      2. Else scan response_text for marker substrings (case-insensitive).
         If found AND a URL with marker host is in response_text, return that URL.
         If found but no URL, return True with None (text-only citation).
      3. Else False.
    """
    cit_lower = (citation_url or "").lower().strip()
    text_lower = (response_text or "").lower()

    # case 1: explicit citation_url
    if cit_lower and any(m in cit_lower for m in JPCITE_MARKERS):
        return True, citation_url.strip()

    # case 2: substring in body
    has_marker = any(m in text_lower for m in JPCITE_MARKERS)
    if not has_marker:
        return False, None

    # try to find a URL in response_text that points at jpcite
    for url in URL_RE.findall(response_text or ""):
        if any(m in url.lower() for m in JPCITE_MARKERS):
            return True, url
    # text-only mention (no clickable URL)
    return True, None


def emit_template(surface: str, week: str) -> Path:
    """Write a blank CSV scaffold for one surface × one week."""
    if surface not in SURFACES:
        raise ValueError(f"surface must be one of {SURFACES}, got {surface!r}")
    RESPONSES_DIR.mkdir(parents=True, exist_ok=True)
    path = RESPONSES_DIR / f"{surface}_{week}.csv"
    if path.exists():
        raise FileExistsError(
            f"refuse to overwrite existing {path} (delete first if intentional)"
        )
    qs = load_questions()
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(CSV_HEADER)
        for q in qs:
            writer.writerow([q["id"], "", "", ""])
    return path


def read_responses(surface: str, week: str) -> list[dict[str, str]]:
    """Read the CSV for one surface × one week. Returns [] if missing."""
    path = RESPONSES_DIR / f"{surface}_{week}.csv"
    if not path.exists():
        return []
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        # validate header
        missing = [h for h in CSV_HEADER if h not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(
                f"{path} header missing columns: {missing} "
                f"(got {reader.fieldnames})"
            )
        for r in reader:
            rows.append(
                {
                    "question_id": (r.get("question_id") or "").strip(),
                    "response_text": r.get("response_text") or "",
                    "citation_url": (r.get("citation_url") or "").strip(),
                    "citation_position": (r.get("citation_position") or "").strip(),
                }
            )
    return rows


def score_surface(
    surface: str, week: str, questions: list[dict[str, Any]]
) -> dict[str, Any]:
    """
    Aggregate citation rate for one surface × one week.

    Returns dict with:
      surface, week, csv_present, answered_count, total_questions,
      cited_count, citation_rate_pct, by_category{cat: {answered, cited, rate}},
      per_question[{question_id, category, jpcite_cited, citation_url, citation_position}]
    """
    rows = read_responses(surface, week)
    csv_present = bool(rows)

    by_qid = {r["question_id"]: r for r in rows}

    per_q: list[dict[str, Any]] = []
    by_cat: dict[str, dict[str, int]] = {c: {"answered": 0, "cited": 0} for c in CATEGORIES}

    answered = 0
    cited = 0
    for q in questions:
        qid = q["id"]
        cat = q["category"]
        row = by_qid.get(qid)
        response_text = (row or {}).get("response_text", "") or ""
        citation_url = (row or {}).get("citation_url", "") or ""
        citation_position = (row or {}).get("citation_position", "") or ""

        # "answered" = non-empty response_text
        has_answer = bool(response_text.strip())
        if has_answer:
            answered += 1
            if cat in by_cat:
                by_cat[cat]["answered"] += 1

        is_cited, resolved_url = (
            detect_jpcite_citation(response_text, citation_url) if has_answer else (False, None)
        )
        if is_cited:
            cited += 1
            if cat in by_cat:
                by_cat[cat]["cited"] += 1

        # citation_position -> int|None
        cp: int | None = None
        if citation_position:
            try:
                cp = int(citation_position)
            except ValueError:
                cp = None

        per_q.append(
            {
                "question_id": qid,
                "category": cat,
                "jpcite_cited": is_cited,
                "citation_url": resolved_url,
                "citation_position": cp,
            }
        )

    total = len(questions)
    rate = (cited / answered * 100.0) if answered else 0.0

    cat_summary: dict[str, dict[str, Any]] = {}
    for c in CATEGORIES:
        a = by_cat[c]["answered"]
        cc = by_cat[c]["cited"]
        cat_summary[c] = {
            "answered": a,
            "cited": cc,
            "citation_rate_pct": round((cc / a * 100.0) if a else 0.0, 2),
            "prefix": CATEGORY_PREFIX[c],
        }

    return {
        "surface": surface,
        "week": week,
        "csv_present": csv_present,
        "answered_count": answered,
        "total_questions": total,
        "cited_count": cited,
        "citation_rate_pct": round(rate, 2),
        "by_category": cat_summary,
        "per_question": per_q,
    }


def load_prev_week_rates(week: str, steps: int) -> dict[str, dict[str, Any] | None]:
    """
    Read previously-written JSON outputs for the prev N weeks.
    Returns { 'YYYY-Www': {surface: rate_pct, '__by_cat__': {surface: {cat: rate}}} | None }.
    """
    out: dict[str, dict[str, Any] | None] = {}
    for i in range(1, steps + 1):
        wk = prev_iso_week(week, i)
        path = OUTPUT_DIR / f"geo_week_{wk}.json"
        if not path.exists():
            out[wk] = None
            continue
        try:
            blob = json.loads(path.read_text("utf-8"))
        except Exception:
            out[wk] = None
            continue
        snapshot: dict[str, Any] = {}
        by_cat_snap: dict[str, dict[str, float]] = {}
        for sname, s in (blob.get("surfaces") or {}).items():
            snapshot[sname] = s.get("citation_rate_pct", 0.0)
            by_cat_snap[sname] = {
                c: (s.get("by_category", {}).get(c, {}) or {}).get("citation_rate_pct", 0.0)
                for c in CATEGORIES
            }
        snapshot["__by_cat__"] = by_cat_snap
        out[wk] = snapshot
    return out


# ----------------------------------------------------------------------
# rendering
# ----------------------------------------------------------------------


def render_markdown(report: dict[str, Any]) -> str:
    week = report["week"]
    generated = report["generated_at"]
    surfaces = report["surfaces"]
    trend = report["trend_4w"]
    prev_week = report["prev_week"]

    lines: list[str] = []
    lines.append(f"# GEO weekly bench — {week}")
    lines.append("")
    lines.append(f"- generated: `{generated}`")
    lines.append(f"- harness: `scripts/ops/geo_weekly_bench_v3.py`")
    lines.append(f"- method: CSV import (no LLM API call from harness)")
    lines.append(f"- inputs: `data/geo_responses/{{surface}}_{week}.csv`")
    lines.append("")

    lines.append("## 1. Surface 別 citation rate")
    lines.append("")
    lines.append("| surface | csv | answered | cited | rate | Δ vs 前週 |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for sname in SURFACES:
        s = surfaces[sname]
        prev = (prev_week or {}).get(sname)
        delta = ""
        if prev is not None:
            d = s["citation_rate_pct"] - float(prev)
            sign = "+" if d >= 0 else ""
            delta = f"{sign}{d:.2f} pt"
        csv_mark = "OK" if s["csv_present"] else "miss"
        lines.append(
            f"| {sname} | {csv_mark} | {s['answered_count']}/{s['total_questions']} "
            f"| {s['cited_count']} | {s['citation_rate_pct']:.2f}% | {delta} |"
        )
    lines.append("")

    lines.append("## 2. Category 別 citation rate (今週)")
    lines.append("")
    header = "| surface | " + " | ".join(
        f"{CATEGORY_PREFIX[c]} ({c.split('.')[-1]})" for c in CATEGORIES
    ) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (len(CATEGORIES) + 1))
    for sname in SURFACES:
        s = surfaces[sname]
        cells = [sname]
        for c in CATEGORIES:
            row = s["by_category"][c]
            cells.append(f"{row['cited']}/{row['answered']} ({row['citation_rate_pct']:.1f}%)")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("## 3. 4 週 trend (citation rate %)")
    lines.append("")
    # rows: surface; cols: 4 weeks oldest -> this week
    week_cols = [iso_week_of(date.fromisocalendar(*parse_iso_week(week), 1) - timedelta(weeks=i))
                 for i in range(3, -1, -1)]
    lines.append("| surface | " + " | ".join(week_cols) + " |")
    lines.append("|" + "---|" * (len(week_cols) + 1))
    for sname in SURFACES:
        cells = [sname]
        for wk in week_cols:
            v = trend.get(wk, {}).get(sname)
            cells.append(f"{v:.2f}%" if isinstance(v, (int, float)) else "—")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("`—` = その週の JSON が存在しない / surface 未集計。")
    lines.append("")

    lines.append("## 4. 計測方式と非自動化の理由")
    lines.append("")
    lines.append("- LLM API import 禁止 (memory: feedback_no_operator_llm_api / feedback_autonomath_no_api_use).")
    lines.append("- 我々が 5 surface の API を叩くと ¥3/req 構造で即赤字。")
    lines.append("- 各 surface の web UI に user が手動で 100 問を貼り、")
    lines.append("  回答を `data/geo_responses/{surface}_" + week + ".csv` にコピペするのが SOT。")
    lines.append("- 本 harness は CSV を読んで citation grep + 集計のみを行う。")
    lines.append("")

    lines.append("## 5. 運用 (今週の workflow)")
    lines.append("")
    lines.append("1. `python3 scripts/ops/geo_weekly_bench_v3.py --emit-template chatgpt --week " + week + "` で空 CSV を生成")
    lines.append("2. 同様に claude / cursor / codex / gemini 分を生成")
    lines.append("3. 各 surface の web UI で 100 問を順に問い、回答を `response_text` 列に貼る")
    lines.append("4. `python3 scripts/ops/geo_weekly_bench_v3.py --week " + week + "` で集計")
    lines.append("5. 本 md + JSON が `docs/bench/geo_week_" + week + ".{md,json}` に書き出される")
    lines.append("")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------


def run(week: str, *, trend_only: bool = False) -> tuple[Path, Path]:
    questions = load_questions()

    surfaces_out: dict[str, dict[str, Any]] = {}
    for sname in SURFACES:
        surfaces_out[sname] = score_surface(sname, week, questions)

    # prev week + 4-week trend
    prev_map = load_prev_week_rates(week, steps=1)
    prev_week_snapshot = next(iter(prev_map.values())) if prev_map else None

    trend_map = load_prev_week_rates(week, steps=3)
    trend: dict[str, dict[str, float]] = {}
    for wk, snap in trend_map.items():
        if snap is None:
            trend[wk] = {}
            continue
        trend[wk] = {s: snap[s] for s in SURFACES if s in snap and isinstance(snap[s], (int, float))}
    # add current week to trend bucket
    trend[week] = {s: surfaces_out[s]["citation_rate_pct"] for s in SURFACES}

    report = {
        "schema_version": "geo_weekly_v3",
        "week": week,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "csv_import",
        "harness": "scripts/ops/geo_weekly_bench_v3.py",
        "input_dir": str(RESPONSES_DIR.relative_to(ROOT)),
        "total_questions": len(questions),
        "surfaces": surfaces_out,
        "prev_week": (prev_week_snapshot or {}),
        "trend_4w": trend,
        "constraints": {
            "no_llm_api_import": True,
            "method": "user pastes surface responses into CSV; harness only greps for citation",
            "policy_refs": [
                "feedback_no_operator_llm_api",
                "feedback_autonomath_no_api_use",
                "feedback_destruction_free_organization (geo_eval.yml + tests/geo/bench_harness.py 残置)",
            ],
        },
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / f"geo_week_{week}.json"
    md_path = OUTPUT_DIR / f"geo_week_{week}.md"

    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    if not trend_only:
        md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="jpcite GEO weekly bench v3 (CSV import, no LLM API).",
    )
    parser.add_argument(
        "--week",
        default=iso_week_of(date.today()),
        help="ISO week like 2026-W19 (default: current week, JST-agnostic)",
    )
    parser.add_argument(
        "--emit-template",
        metavar="SURFACE",
        help="Write a blank CSV scaffold for SURFACE × --week and exit. "
        f"SURFACE in {SURFACES}.",
    )
    parser.add_argument(
        "--trend-only",
        action="store_true",
        help="Re-write JSON only (skip Markdown). Useful for re-aggregating after CSV edit.",
    )
    args = parser.parse_args(argv)

    try:
        parse_iso_week(args.week)
    except ValueError as e:
        print(f"[geo_weekly_bench_v3] {e}", file=sys.stderr)
        return 2

    if args.emit_template:
        try:
            path = emit_template(args.emit_template.lower(), args.week)
        except (ValueError, FileExistsError) as e:
            print(f"[geo_weekly_bench_v3] {e}", file=sys.stderr)
            return 2
        print(f"[geo_weekly_bench_v3] wrote template: {path}")
        return 0

    try:
        json_path, md_path = run(args.week, trend_only=args.trend_only)
    except FileNotFoundError as e:
        print(f"[geo_weekly_bench_v3] {e}", file=sys.stderr)
        return 1

    print(f"[geo_weekly_bench_v3] week={args.week}")
    print(f"  json -> {json_path}")
    if not args.trend_only:
        print(f"  md   -> {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
