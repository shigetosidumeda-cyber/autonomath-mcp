#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""run_practitioner_eval.py — substring/regex eval over live jpcite REST.

NO LLM CALL. Memory: feedback_no_operator_llm_api.

Inputs:
  - eval JSONL corpus (default: tests/eval/practitioner_output_acceptance_queries_2026-05-06.jsonl)
  - JPCITE_API_KEY env var (X-Api-Key for paid quota)
  - JPCITE_API_BASE env var (default https://api.jpcite.com)

Output:
  - site/practitioner-eval/_data/results_latest.json
  - site/practitioner-eval/_data/results_<run_id>.json (archive)

Each row triggers 1-2 jpcite REST calls = 3-6 yen on the operator's metered
quota. 150 rows x ~3 calls x ¥3 ~= ¥1,350/run; weekly ~= ¥5,400/month. Fits
within zero-touch solo ops budget.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = ROOT / "tests/eval/practitioner_output_acceptance_queries_2026-05-06.jsonl"
DATA_DIR = ROOT / "site/practitioner-eval/_data"

DEFAULT_API_BASE = os.environ.get("JPCITE_API_BASE", "https://api.jpcite.com")

# Persona slug map — see _persona_index.py for the canonical list.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _persona_index import (  # noqa: E402
    BOUNDARY_PHRASES_BY_PERSONA,
    PERSONA_COHORT,
    PERSONA_INDEX,
)

USER_AGENT = "jpcite-practitioner-eval/1.0 (+https://jpcite.com/practitioner-eval/)"

# Maps expected_artifact -> (HTTP method, REST path template). When a row's
# artifact is not in the table, the runner falls back to a generic dispatch
# surface (POST /v1/artifacts/dispatch) that M00-A is expected to mount.
ROUTE_HINT_PER_ARTIFACT: dict[str, tuple[str, str]] = {
    "houjin_baseline_pack": ("POST", "/v1/artifacts/houjin_baseline_pack"),
    "dd_question_pack": ("POST", "/v1/artifacts/dd_question_pack"),
    "houjin_watch_provisioning_receipt": ("POST", "/v1/me/houjin_watch/provision"),
    "adoption_dependency_risk_pack": ("POST", "/v1/artifacts/adoption_dependency_risk_pack"),
    "kanyosaki_monthly_briefing_provisioning": ("POST", "/v1/me/saved_searches/provision"),
    "pre_kessan_impact_pack": ("POST", "/v1/artifacts/pre_kessan_impact_pack"),
    "invoice_compliance_pack": ("POST", "/v1/artifacts/invoice_compliance_pack"),
    "amendment_sunset_calendar": ("POST", "/v1/artifacts/amendment_sunset_calendar"),
    "audit_pack": ("POST", "/v1/artifacts/audit_pack"),
    "audit_risk_signals_pack": ("POST", "/v1/artifacts/audit_risk_signals_pack"),
    "post_balance_amendment_pack": ("POST", "/v1/artifacts/post_balance_amendment_pack"),
    "foreign_fdi_program_pack": ("POST", "/v1/artifacts/foreign_fdi_program_pack"),
    "tax_treaty_baseline_pack": ("POST", "/v1/artifacts/tax_treaty_baseline_pack"),
    "foreign_fdi_eligibility_filtered_list": (
        "POST",
        "/v1/artifacts/foreign_fdi_eligibility_filtered_list",
    ),
    "jurisdiction_consistency_report": ("POST", "/v1/artifacts/jurisdiction_consistency_report"),
    "tax_client_premeeting_memo": ("POST", "/v1/artifacts/tax_client_premeeting_memo"),
    "client_invoice_and_program_note": ("POST", "/v1/artifacts/client_invoice_and_program_note"),
    "batch_company_folder_brief": ("POST", "/v1/artifacts/batch_company_folder_brief"),
    "identity_resolution_gap_memo": ("POST", "/v1/artifacts/identity_resolution_gap_memo"),
    "bpo_program_intake_batch": ("POST", "/v1/artifacts/bpo_program_intake_batch"),
}


@dataclass
class QueryResult:
    query_id: str
    persona_slug: str
    persona_label: str
    expected_artifact: str
    query: str
    artifact_output_full: str
    artifact_output_truncated: str
    must_include_total: int
    must_include_hits: list[dict]
    must_include_match: bool
    must_not_claim_findings: list[dict]
    must_not_claim_violations: int
    boundary_kept: bool
    boundary_text: str
    row_pass: bool
    duration_ms: int
    http_status: int
    error: str | None = None


@dataclass
class PersonaResult:
    persona_slug: str
    persona_label: str
    cohort: str
    queries: list[QueryResult]


@dataclass
class RunResult:
    run_id: str
    generated_at: str
    corpus_snapshot_id: str
    api_base: str
    persona_results: list[PersonaResult] = field(default_factory=list)


def load_corpus(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("//"):
                rows.append(json.loads(line))
    return rows


def select_three_per_persona(rows: list[dict]) -> dict[str, list[dict]]:
    """Pick the 3 highest-severity queries per persona slug.

    Severity = len(must_include) + 2*len(must_not_claim).
    Personas not present in PERSONA_INDEX are skipped silently.
    """
    by_slug: dict[str, list[tuple[int, dict]]] = {}
    label_to_slug = {label: slug for slug, label in PERSONA_INDEX.items()}
    for row in rows:
        persona_label = (row.get("persona") or "").strip()
        slug = label_to_slug.get(persona_label)
        if slug is None:
            continue
        sev = len(row.get("must_include", [])) + 2 * len(row.get("must_not_claim", []))
        by_slug.setdefault(slug, []).append((sev, row))
    out: dict[str, list[dict]] = {}
    for slug, entries in by_slug.items():
        entries.sort(key=lambda t: -t[0])
        out[slug] = [r for _, r in entries[:3]]
    return out


def call_jpcite(
    method: str, path: str, query_text: str, api_base: str, api_key: str, timeout: float = 30.0
) -> tuple[int, str]:
    body = json.dumps(
        {
            "query": query_text,
            "as_of_date": dt.date.today().isoformat(),
        }
    ).encode("utf-8")
    req = urlrequest.Request(f"{api_base}{path}", method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Api-Key", api_key)
    req.add_header("User-Agent", USER_AGENT)
    try:
        with urlrequest.urlopen(req, body, timeout=timeout) as resp:
            return resp.getcode(), resp.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except URLError as e:
        return 0, json.dumps({"error": str(e.reason)})


def judge_must_include(out: str, needles: list[str]) -> tuple[bool, list[dict]]:
    """Each needle: substring (default) OR regex if it starts with 're:'."""
    findings: list[dict] = []
    all_match = True
    for needle in needles:
        matched = _match_needle(out, needle)
        findings.append({"needle": needle, "matched": matched})
        if not matched:
            all_match = False
    return all_match, findings


def judge_must_not_claim(out: str, needles: list[str]) -> tuple[int, list[dict]]:
    findings: list[dict] = []
    violations = 0
    for needle in needles:
        matched = _match_needle(out, needle)
        findings.append({"needle": needle, "matched": matched})
        if matched:
            violations += 1
    return violations, findings


def judge_boundary(out: str, persona_slug: str) -> tuple[bool, str]:
    phrases = BOUNDARY_PHRASES_BY_PERSONA.get(persona_slug, [])
    if not phrases:
        return True, "境界該当なし persona — N/A"
    for p in phrases:
        if p in out:
            return True, p
    return False, " / ".join(phrases)


def _match_needle(out: str, needle: str) -> bool:
    if needle.startswith("re:"):
        try:
            return bool(re.search(needle[3:], out))
        except re.error:
            return False
    return needle in out


def fetch_corpus_snapshot_id(api_base: str, api_key: str) -> str:
    """Fetch /v1/health to read the current corpus_snapshot_id."""
    req = urlrequest.Request(f"{api_base}/v1/health")
    req.add_header("X-Api-Key", api_key)
    req.add_header("User-Agent", USER_AGENT)
    try:
        with urlrequest.urlopen(req, timeout=10.0) as resp:
            j = json.loads(resp.read().decode("utf-8"))
            return j.get("corpus_snapshot_id", "unknown")
    except (HTTPError, URLError, json.JSONDecodeError):
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    p.add_argument("--api-base", default=DEFAULT_API_BASE)
    p.add_argument("--out-dir", type=Path, default=DATA_DIR)
    p.add_argument("--max-per-persona", type=int, default=3)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip live REST calls; emit empty artifact output. CI smoke-only.",
    )
    args = p.parse_args(argv)

    api_key = os.environ.get("JPCITE_API_KEY", "")
    if not api_key and not args.dry_run:
        print("ERROR: JPCITE_API_KEY missing", file=sys.stderr)
        return 2

    rows = load_corpus(args.corpus)
    selected = select_three_per_persona(rows)

    snapshot_id = "dryrun" if args.dry_run else fetch_corpus_snapshot_id(args.api_base, api_key)
    run_id = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    run = RunResult(
        run_id=run_id,
        generated_at=dt.datetime.utcnow().isoformat() + "Z",
        corpus_snapshot_id=snapshot_id,
        api_base=args.api_base,
    )

    for slug, persona_label in PERSONA_INDEX.items():
        rows_for_p = selected.get(slug, [])[: args.max_per_persona]
        # Pad to 3 with stub rows so the page always shows 3 cells.
        while len(rows_for_p) < 3:
            rows_for_p.append(
                {
                    "_stub": True,
                    "persona": persona_label,
                    "query": "(no eval row defined for this persona slot)",
                    "expected_artifact": "n/a",
                    "must_include": [],
                    "must_not_claim": [],
                }
            )
        cohort = PERSONA_COHORT.get(slug, "unknown")
        pres = PersonaResult(
            persona_slug=slug, persona_label=persona_label, cohort=cohort, queries=[]
        )
        for row in rows_for_p:
            qid = (
                row.get("query_id")
                or row.get("id")
                or hashlib.sha1(row["query"].encode("utf-8")).hexdigest()[:10]
            )
            artifact = row.get("expected_artifact", "n/a")
            method, path = ROUTE_HINT_PER_ARTIFACT.get(artifact, ("POST", "/v1/artifacts/dispatch"))
            t0 = time.perf_counter()
            if args.dry_run or row.get("_stub"):
                status, out = 0, ""
            else:
                status, out = call_jpcite(method, path, row["query"], args.api_base, api_key)
            dur = int((time.perf_counter() - t0) * 1000)
            inc_match, inc_hits = judge_must_include(out, row.get("must_include", []))
            ng_count, ng_findings = judge_must_not_claim(out, row.get("must_not_claim", []))
            bnd_kept, bnd_text = judge_boundary(out, slug)
            row_pass = inc_match and ng_count == 0 and bnd_kept
            qr = QueryResult(
                query_id=qid,
                persona_slug=slug,
                persona_label=persona_label,
                expected_artifact=artifact,
                query=row["query"],
                artifact_output_full=out,
                artifact_output_truncated=out[:4096],
                must_include_total=len(row.get("must_include", [])),
                must_include_hits=inc_hits,
                must_include_match=inc_match,
                must_not_claim_findings=ng_findings,
                must_not_claim_violations=ng_count,
                boundary_kept=bnd_kept,
                boundary_text=bnd_text,
                row_pass=row_pass,
                duration_ms=dur,
                http_status=status,
            )
            pres.queries.append(qr)
        run.persona_results.append(pres)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    archive = args.out_dir / f"results_{run_id}.json"
    latest = args.out_dir / "results_latest.json"
    payload = {
        "run_id": run.run_id,
        "generated_at": run.generated_at,
        "corpus_snapshot_id": run.corpus_snapshot_id,
        "api_base": run.api_base,
        "persona_results": [
            {
                **{k: v for k, v in asdict(pr).items() if k != "queries"},
                "queries": [
                    # Drop full artifact output from public JSON; only truncated 4 kB ships.
                    {k: v for k, v in asdict(q).items() if k != "artifact_output_full"}
                    for q in pr.queries
                ],
            }
            for pr in run.persona_results
        ],
    }
    with archive.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    with latest.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"wrote {archive} and {latest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
