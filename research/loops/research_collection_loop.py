#!/usr/bin/env python3
"""Repeatable research loop for the OTHER CLI.

This file intentionally lives under research/loops so it stays out of the main
application, migrations, cron jobs, deployment files, and registry manifests.

It does not crawl the web or call LLM APIs. It creates max-agent work orders,
records the loop in RUN_LOG.md, and checks whether the expected deliverables
exist after agents finish.

Usage:

    ./.venv/bin/python research/loops/research_collection_loop.py plan --max-agents 32
    ./.venv/bin/python research/loops/research_collection_loop.py review --run-id 20260430
    ./.venv/bin/python research/loops/research_collection_loop.py next --previous-run 20260430 --max-agents 32
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

JST = timezone(timedelta(hours=9), name="JST")
REPO_ROOT = Path(__file__).resolve().parents[2]
LOOP_ROOT = Path("research/loops")
WORK_ROOT = LOOP_ROOT / "runs"
RUN_LOG = LOOP_ROOT / "RUN_LOG.md"

ALLOWED_OUTPUT_PREFIXES = (
    "analysis_wave18/",
    "data/snapshots/",
    "data/structured_facts/",
    "research/loops/",
)

HARD_CONSTRAINTS = (
    "Do not call any LLM API or hosted model API. Use regex, rules, difflib, sqlite, pdfplumber, csv/json tooling only.",
    "Do not use aggregator sites as evidence: noukaweb, hojyokin-portal, biz.stayway, or similar portals are discovery hints only.",
    "Respect robots.txt, crawl-delay, rate limits, and public-source terms.",
    "Do not propose tier SKUs, subscription tiers, or changes to the ¥3/request metered model.",
    "Do not write to src/, scripts/, .github/, docs/_internal/, fly.toml, server.json, smithery.yaml, or deployment files.",
    "Write job definitions and run logs only under research/loops/.",
    "Write research outputs only to analysis_wave18/, data/snapshots/, or data/structured_facts/.",
    "Do not estimate work-hours or calendar schedules. Return evidence and next concrete questions only.",
)


@dataclass(frozen=True)
class Lane:
    name: str
    title: str
    cap: int
    description: str
    shard_output_templates: tuple[str, ...]
    final_outputs: tuple[str, ...]
    evidence_rules: tuple[str, ...]
    # Per-shard scope hints — keeps 8 parallel agents from re-fetching the
    # same population. Indexed by 1-based shard number; lookup falls back to
    # `_default_partition_hint` when the shard exceeds the prepared list.
    shard_partitions: tuple[str, ...] = ()
    seed_inputs: tuple[str, ...] = ()
    _default_partition_hint: str = (
        "(no explicit shard partition — coordinate with peers via the run review file)"
    )

    def partition_for(self, shard: int) -> str:
        if 1 <= shard <= len(self.shard_partitions):
            return self.shard_partitions[shard - 1]
        return self._default_partition_hint


LANES: tuple[Lane, ...] = (
    Lane(
        name="url_liveness",
        title="Tier A and tier S official URL liveness",
        cap=12,
        description=(
            "Check official/source URLs for reachable status, redirect target, PDF/HTML type, "
            "staleness hints, and broken or placeholder origins. Target Tier A first; include "
            "tier S rescans if the shard has capacity."
        ),
        shard_output_templates=(
            "analysis_wave18/loops/{run_id}/url_liveness_shard{shard:02d}.json",
        ),
        final_outputs=(
            "analysis_wave18/url_liveness_{run_date}.json",
        ),
        evidence_rules=(
            "Record status_code, final_url, content_type, checked_at, tier, source_table/source_id if known.",
            "Classify each URL as ok, redirect, soft_404, hard_404, timeout, blocked, placeholder, or non_primary.",
            "Final file should target Tier A 1,340 rows when source selection is available.",
        ),
        seed_inputs=(
            "Source query: `SELECT unified_id, primary_name, source_url, prefecture, tier FROM programs WHERE tier='A' AND excluded=0` against data/jpintel.db (1,340 rows expected).",
            "Skip rows with NULL source_url or aggregator domains (noukaweb / hojyokin-portal / biz.stayway).",
            "Tier S rescan target: WHERE tier='S' AND source_url_status='broken' (after migration 118 lands; ~13 rows from the 2026-04-30 audit).",
        ),
        shard_partitions=(
            "Tier A, prefecture in (北海道, 青森県, 岩手県, 宮城県, 秋田県, 山形県, 福島県). Approx 168 rows.",
            "Tier A, prefecture in (茨城県, 栃木県, 群馬県, 埼玉県, 千葉県, 東京都). Approx 168 rows. Tokyo dense.",
            "Tier A, prefecture in (神奈川県, 新潟県, 富山県, 石川県, 福井県, 山梨県). Approx 168 rows.",
            "Tier A, prefecture in (長野県, 岐阜県, 静岡県, 愛知県, 三重県). Approx 168 rows. Aichi dense.",
            "Tier A, prefecture in (滋賀県, 京都府, 大阪府, 兵庫県, 奈良県, 和歌山県). Approx 168 rows. Osaka/Hyogo dense.",
            "Tier A, prefecture in (鳥取県, 島根県, 岡山県, 広島県, 山口県, 徳島県, 香川県, 愛媛県, 高知県). Approx 168 rows.",
            "Tier A, prefecture in (福岡県, 佐賀県, 長崎県, 熊本県, 大分県, 宮崎県, 鹿児島県, 沖縄県). Approx 168 rows.",
            "Tier A, prefecture IS NULL (national programs). Approx 168 rows. Plus tier S rescan if capacity.",
            "Tier A overflow / leftover prefectures + tier S broken-URL rescan.",
            "Tier A overflow + retry of any 5xx-classified rows from earlier shards in this run.",
            "Tier A overflow + verification spot-check of 30 random shard-01..08 outputs.",
            "Coordinator: dedupe + merge shards 01-11 into the final analysis_wave18/url_liveness_{run_date}.json.",
        ),
    ),
    Lane(
        name="consultant_firms",
        title="Consultant and firm list for direct outreach",
        cap=12,
        description=(
            "Build a primary-source list of likely customers or partners: certified tax accountants, "
            "administrative scriveners, SME consultants, subsidy consultants, and RAG/LLM "
            "implementation shops with Japan-facing evidence workflows."
        ),
        shard_output_templates=(
            "analysis_wave18/loops/{run_id}/consultant_firms_shard{shard:02d}.csv",
        ),
        final_outputs=(
            "analysis_wave18/consultant_firms_{run_date}.csv",
        ),
        evidence_rules=(
            "Final CSV should contain 100+ rows if enough primary-source candidates exist.",
            "CSV columns: name, category, region, public_url, contact_url, evidence_url, why_relevant, notes.",
            "Do not invent emails; leave contact_url blank if no public contact page is found.",
        ),
        seed_inputs=(
            "中小企業庁 認定支援機関 検索: https://ninteishien.force.com/NSK_NinteiKensaku",
            "日本行政書士会連合会: https://www.gyosei.or.jp/information/ (各都道府県会名簿経由)",
            "中小企業診断協会: https://www.j-smeca.jp/ (会員検索)",
            "全国社会保険労務士会連合会: https://www.shakaihokenroumushi.jp/ (会員名簿)",
            "日本税理士会連合会: https://www.nichizeiren.or.jp/taxaccount/find/",
        ),
        shard_partitions=(
            "category=補助金コンサル, region=東京/関東 (中小企業庁 認定支援機関 検索 by 関東ブロック).",
            "category=補助金コンサル, region=関西/中部 (大阪・愛知・京都・兵庫).",
            "category=補助金コンサル, region=その他全国 (北海道/東北/中国/四国/九州).",
            "category=行政書士, region=東京/関東 (公開実績ある事務所のみ — 補助金/許認可ブログ言及あり).",
            "category=行政書士, region=関西/中部.",
            "category=中小企業診断士, region=全国 (協会所属 + 補助金実績公開あり).",
            "category=社会保険労務士 (補助金/助成金で支援実績ある事務所のみ).",
            "category=税理士事務所 (補助金/M&A/事業承継 実績公開あり、4-15 名規模).",
            "category=RAG/LLM 導入支援 SaaS (Japan-facing, ja README).",
            "category=金融系 (地銀・信金 法人ソリューション部、商工会連合会).",
            "category=VC/PE 中堅 (Japan focus、SaaS / regtech).",
            "Coordinator: dedupe + merge shards 01-11 into final 100+ rows CSV.",
        ),
    ),
    Lane(
        name="pdf_structure",
        title="Government PDF extraction research",
        cap=8,
        description=(
            "Inspect public grant/program PDFs and map extractable fields by publisher/domain. "
            "This loop produces parser requirements, not production parser code."
        ),
        shard_output_templates=(
            "data/structured_facts/research_{run_id}/pdf_structure_shard{shard:02d}.json",
        ),
        final_outputs=(
            "analysis_wave18/pdf_extraction_research_{run_date}.md",
        ),
        evidence_rules=(
            "For each PDF, record source_url, publisher_domain, page_count, text_extractable, tables_detected, fields_found.",
            "Fields of interest: deadline, eligible_applicant, subsidy_rate, max_amount, required_docs, contact, update_date.",
            "Include parser_risk: low, medium, high, or blocked, with the reason.",
        ),
        seed_inputs=(
            "Source query: `SELECT source_url FROM programs WHERE tier IN ('S','A') AND source_url LIKE '%.pdf'` against data/jpintel.db.",
            "Tier S has 114 rows, Tier A has 1,340 rows; expect ~30% to be direct-PDF source_url. Targets: ~430 PDFs total.",
            "Use pdfplumber + regex; do NOT call any text extraction LLM.",
        ),
        shard_partitions=(
            "publisher_domain ⊆ {meti.go.jp, smrj.go.jp}. ものづくり / 中小企業庁 系 公募要領.",
            "publisher_domain ⊆ {maff.go.jp, env.go.jp}. 農林水産省 / 環境省 系 補助金 PDF.",
            "publisher_domain ⊆ {mlit.go.jp, mhlw.go.jp}. 国土交通省 / 厚労省 系.",
            "publisher_domain ⊆ {nedo.go.jp, jstage.jst.go.jp, jst.go.jp}. NEDO / JST 系 グリーン・研究助成.",
            "publisher_domain matches *.pref.*.jp + *.metro.tokyo.lg.jp. 都道府県補助金 PDF.",
            "publisher_domain matches *.city.*.jp + *.lg.jp (excluding pref/metro). 市町村補助金 PDF.",
            "publisher_domain ⊆ {jfc.go.jp}. 日本政策金融公庫 商品案内 PDF (融資 108 件 corpus).",
            "Coordinator: aggregate per-domain parser_risk + extraction-readiness summary into final analysis_wave18/pdf_extraction_research_{run_date}.md.",
        ),
    ),
    Lane(
        name="am_diff_design",
        title="Amendment diff design and false-positive research",
        cap=8,
        description=(
            "Collect read-only snapshots and design diff behavior for programs/laws likely to change. "
            "Do not write migrations, cron jobs, or production code from this loop."
        ),
        shard_output_templates=(
            "data/snapshots/am_diff_{run_id}_shard{shard:02d}.json",
            "analysis_wave18/loops/{run_id}/am_diff_design_shard{shard:02d}.md",
        ),
        final_outputs=(
            "analysis_wave18/am_diff_design_{run_date}.md",
        ),
        evidence_rules=(
            "Record snapshot cycle, diff algorithm candidates, false-positive patterns, and schema suggestions.",
            "Use difflib or structured field comparison only; no LLM extraction.",
            "If no previous snapshot exists, write baseline snapshot and mark diff_status=baseline_only.",
        ),
        seed_inputs=(
            "Snapshot scope: `SELECT unified_id, primary_name, source_url FROM programs WHERE tier='S' AND excluded=0 LIMIT 114` (tier S only first; expand to A in later loops).",
            "Per snapshot: fetch source_url, save raw HTML / PDF bytes + sha256 to data/snapshots/am_diff_{run_id}_shard{shard:02d}.json.",
            "Compare against any prior snapshot for the same source_url; emit diff candidates with field-level hints.",
        ),
        shard_partitions=(
            "Tier S programs 1-15 (alphabetical by primary_name). Snapshot + design notes.",
            "Tier S programs 16-30. False-positive: noise from boilerplate footers, contact section.",
            "Tier S programs 31-45. False-positive: visit counter, dynamic timestamp.",
            "Tier S programs 46-60. False-positive: reordered FAQ section without semantic change.",
            "Tier S programs 61-75. False-positive: PDF page-number pagination drift.",
            "Tier S programs 76-90. False-positive: minor wording shift (て・に・を) without amount/deadline change.",
            "Tier S programs 91-114 + retry of any earlier shard's failures.",
            "Coordinator: aggregate algorithm candidates + false-positive taxonomy into final analysis_wave18/am_diff_design_{run_date}.md.",
        ),
    ),
)


def today_run_id() -> str:
    return datetime.now(JST).strftime("%Y%m%d")


def run_date(run_id: str) -> str:
    if len(run_id) == 8 and run_id.isdigit():
        return f"{run_id[:4]}-{run_id[4:6]}-{run_id[6:]}"
    return datetime.now(JST).strftime("%Y-%m-%d")


def is_allowed(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in ALLOWED_OUTPUT_PREFIXES)


def lanes_by_name(names: list[str] | None) -> tuple[Lane, ...]:
    if not names:
        return LANES
    by_name = {lane.name: lane for lane in LANES}
    unknown = sorted(set(names) - set(by_name))
    if unknown:
        raise ValueError(f"unknown lane(s): {', '.join(unknown)}")
    return tuple(by_name[name] for name in names)


def allocate(max_agents: int, lanes: tuple[Lane, ...]) -> list[tuple[Lane, int]]:
    if max_agents < 1:
        raise ValueError("--max-agents must be >= 1")
    counts = {lane.name: 0 for lane in lanes}
    out: list[tuple[Lane, int]] = []
    while len(out) < max_agents:
        progressed = False
        for lane in lanes:
            if len(out) >= max_agents:
                break
            if counts[lane.name] >= lane.cap:
                continue
            counts[lane.name] += 1
            out.append((lane, counts[lane.name]))
            progressed = True
        if not progressed:
            break
    return out


def render_work_order(
    *,
    run_id: str,
    agent_index: int,
    agent_total: int,
    lane: Lane,
    shard: int,
    previous_review: str,
) -> tuple[str, list[str]]:
    date = run_date(run_id)
    shard_outputs = [
        template.format(run_id=run_id, run_date=date, shard=shard)
        for template in lane.shard_output_templates
    ]
    final_outputs = [
        template.format(run_id=run_id, run_date=date, shard=shard)
        for template in lane.final_outputs
    ]
    all_outputs = shard_outputs + final_outputs
    blocked = [path for path in all_outputs if not is_allowed(path)]
    if blocked:
        raise ValueError(f"disallowed output path(s): {blocked}")

    seed_block = (
        chr(10).join(f"- {item}" for item in lane.seed_inputs)
        if lane.seed_inputs
        else "- (no seed inputs declared for this lane — request from operator before scraping)"
    )
    body = f"""# OTHER CLI Research Work Order {agent_index:02d}/{agent_total:02d}

Run ID: `{run_id}`
Lane: `{lane.name}` - {lane.title}
Shard: `{shard:02d}`

## Mission

{lane.description}

## Shard Scope (yours and yours only — do NOT overlap with other shards)

{lane.partition_for(shard)}

## Seed Inputs

{seed_block}

## Hard Constraints

{chr(10).join(f"- {item}" for item in HARD_CONSTRAINTS)}

## Evidence Rules

{chr(10).join(f"- {item}" for item in lane.evidence_rules)}

## Shard Output

Write shard-level output here:

{chr(10).join(f"- `{path}`" for path in shard_outputs)}

## Final Deliverable For This Lane

If you are the last or coordinating agent for this lane, merge/dedupe shard outputs into:

{chr(10).join(f"- `{path}`" for path in final_outputs)}

## Previous Loop Review

{previous_review}

## Final Response Contract

List only:

- files_written
- rows_or_objects_written
- blockers
- suggested_next_queries
"""
    return body, all_outputs


def read_previous_review(repo: Path, previous_run: str | None) -> str:
    if not previous_run:
        return "No previous loop review."
    path = repo / WORK_ROOT / previous_run / "review.json"
    if not path.exists():
        return f"Previous run `{previous_run}` has no review.json yet."
    data = json.loads(path.read_text(encoding="utf-8"))
    compact = {
        "previous_run": previous_run,
        "expected": data.get("expected_outputs"),
        "present": data.get("present_outputs"),
        "missing": data.get("missing_outputs"),
        "empty": data.get("empty_outputs"),
        "next_action": data.get("next_action"),
    }
    return "```json\n" + json.dumps(compact, ensure_ascii=False, indent=2) + "\n```"


def append_run_log(repo: Path, line: str) -> None:
    path = repo / RUN_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("# Research Loop Run Log\n\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line.rstrip() + "\n")


def plan(
    *,
    repo: Path,
    max_agents: int,
    run_id: str | None,
    lane_names: list[str] | None,
    previous_run: str | None = None,
) -> dict[str, Any]:
    run_id = run_id or today_run_id()
    lanes = lanes_by_name(lane_names)
    allocations = allocate(max_agents, lanes)
    previous_review = read_previous_review(repo, previous_run)

    run_dir = repo / WORK_ROOT / run_id
    work_dir = run_dir / "work_orders"
    work_dir.mkdir(parents=True, exist_ok=True)
    (repo / "analysis_wave18/loops" / run_id).mkdir(parents=True, exist_ok=True)
    (repo / "data/snapshots").mkdir(parents=True, exist_ok=True)
    (repo / "data/structured_facts" / f"research_{run_id}").mkdir(parents=True, exist_ok=True)

    work_orders: list[dict[str, Any]] = []
    expected_outputs: list[str] = []
    for index, (lane, shard) in enumerate(allocations, start=1):
        body, outputs = render_work_order(
            run_id=run_id,
            agent_index=index,
            agent_total=len(allocations),
            lane=lane,
            shard=shard,
            previous_review=previous_review,
        )
        work_path = work_dir / f"{index:02d}_{lane.name}_shard{shard:02d}.md"
        work_path.write_text(body, encoding="utf-8")
        rel_work = work_path.relative_to(repo).as_posix()
        work_orders.append(
            {
                "agent_index": index,
                "lane": lane.name,
                "shard": shard,
                "work_order_path": rel_work,
                "expected_outputs": outputs,
            }
        )
        expected_outputs.extend(outputs)

    final_outputs = sorted(
        {
            template.format(run_id=run_id, run_date=run_date(run_id), shard=0)
            for lane in lanes
            for template in lane.final_outputs
        }
    )
    manifest = {
        "run_id": run_id,
        "created_at": datetime.now(JST).isoformat(timespec="seconds"),
        "max_agents_requested": max_agents,
        "agents_allocated": len(work_orders),
        "previous_run": previous_run,
        "hard_constraints": list(HARD_CONSTRAINTS),
        "work_orders": work_orders,
        "expected_outputs": expected_outputs,
        "final_outputs": final_outputs,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "PROMPT_FOR_MAX_AGENTS.md").write_text(
        render_master_prompt(run_id, manifest),
        encoding="utf-8",
    )
    append_run_log(
        repo,
        f"- {datetime.now(JST).isoformat(timespec='seconds')} plan run_id={run_id} agents={len(work_orders)} lanes={','.join(lane.name for lane in lanes)}",
    )
    return manifest


def render_master_prompt(run_id: str, manifest: dict[str, Any]) -> str:
    lines = [
        f"# OTHER CLI Max-Agent Research Loop {run_id}",
        "",
        "Use the maximum safe number of agents. Assign one work order per agent.",
        "This is research-only. Do not edit production code or deployment files.",
        "",
        "## Hard Constraints",
        "",
        *[f"- {item}" for item in HARD_CONSTRAINTS],
        "",
        "## Expected Final Deliverables",
        "",
        *[f"- `{path}`" for path in manifest["final_outputs"]],
        "",
        "## Work Orders",
        "",
    ]
    for item in manifest["work_orders"]:
        lines.append(
            f"- Agent {item['agent_index']:02d}: `{item['work_order_path']}` "
            f"-> {item['lane']} shard {item['shard']:02d}"
        )
    lines.extend(
        [
            "",
            "## Close The Loop",
            "",
            "After agents finish, run:",
            "",
            f"```bash\n./.venv/bin/python research/loops/research_collection_loop.py review --run-id {run_id}\n```",
        ]
    )
    return "\n".join(lines) + "\n"


def review(*, repo: Path, run_id: str) -> dict[str, Any]:
    run_dir = repo / WORK_ROOT / run_id
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    expected = list(dict.fromkeys(manifest.get("final_outputs", []) + manifest.get("expected_outputs", [])))
    present: list[dict[str, Any]] = []
    missing: list[str] = []
    empty: list[str] = []
    for rel in expected:
        path = repo / rel
        if not path.exists():
            missing.append(rel)
            continue
        size = path.stat().st_size
        present.append({"path": rel, "bytes": size})
        if size == 0:
            empty.append(rel)

    payload = {
        "run_id": run_id,
        "reviewed_at": datetime.now(JST).isoformat(timespec="seconds"),
        "expected_outputs": len(expected),
        "present_outputs": len(present),
        "missing_outputs": len(missing),
        "empty_outputs": len(empty),
        "present": present,
        "missing": missing,
        "empty": empty,
        "next_action": "retry_missing_or_empty" if missing or empty else "dedupe_and_deepen",
    }
    (run_dir / "review.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "NEXT_LOOP_PROMPT.md").write_text(
        render_next_prompt(run_id, payload),
        encoding="utf-8",
    )
    append_run_log(
        repo,
        f"- {datetime.now(JST).isoformat(timespec='seconds')} review run_id={run_id} present={len(present)} missing={len(missing)} empty={len(empty)}",
    )
    return payload


def render_next_prompt(run_id: str, payload: dict[str, Any]) -> str:
    lines = [
        f"# NEXT LOOP after {run_id}",
        "",
        "Use the same OTHER CLI constraints. Retry missing/empty outputs first, then deepen.",
        "",
        "## Review",
        "",
        f"- expected_outputs: {payload['expected_outputs']}",
        f"- present_outputs: {payload['present_outputs']}",
        f"- missing_outputs: {payload['missing_outputs']}",
        f"- empty_outputs: {payload['empty_outputs']}",
        f"- next_action: {payload['next_action']}",
        "",
    ]
    if payload["missing"] or payload["empty"]:
        lines.extend(["## Missing Or Empty", ""])
        lines.extend(f"- `{path}`" for path in payload["missing"])
        lines.extend(f"- `{path}` (empty)" for path in payload["empty"])
        lines.append("")
    lines.extend(
        [
            "## Next Command",
            "",
            f"```bash\n./.venv/bin/python research/loops/research_collection_loop.py next --previous-run {run_id} --max-agents 32\n```",
        ]
    )
    return "\n".join(lines) + "\n"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    lane_choices = [lane.name for lane in LANES]

    plan_cmd = sub.add_parser("plan")
    plan_cmd.add_argument("--max-agents", type=int, default=32)
    plan_cmd.add_argument("--run-id")
    plan_cmd.add_argument("--lane", action="append", choices=lane_choices)
    plan_cmd.add_argument("--previous-run")

    review_cmd = sub.add_parser("review")
    review_cmd.add_argument("--run-id", required=True)

    next_cmd = sub.add_parser("next")
    next_cmd.add_argument("--previous-run", required=True)
    next_cmd.add_argument("--max-agents", type=int, default=32)
    next_cmd.add_argument("--run-id")
    next_cmd.add_argument("--lane", action="append", choices=lane_choices)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    repo = REPO_ROOT
    if args.cmd == "plan":
        payload = plan(
            repo=repo,
            max_agents=args.max_agents,
            run_id=args.run_id,
            lane_names=args.lane,
            previous_run=args.previous_run,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "review":
        payload = review(repo=repo, run_id=args.run_id)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["missing_outputs"] == 0 and payload["empty_outputs"] == 0 else 1
    if args.cmd == "next":
        try:
            previous = review(repo=repo, run_id=args.previous_run)
        except FileNotFoundError:
            previous = None
        payload = plan(
            repo=repo,
            max_agents=args.max_agents,
            run_id=args.run_id,
            lane_names=args.lane,
            previous_run=args.previous_run,
        )
        print(json.dumps({"previous_review": previous, "next_manifest": payload}, ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
