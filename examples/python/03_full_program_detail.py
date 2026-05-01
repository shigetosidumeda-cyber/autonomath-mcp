"""
03_full_program_detail.py
-------------------------
Fetch one program + its enriched A-J dimensions and source_mentions. This is
the "what does a tier-S record actually contain?" demo — the thing investors
and buyers ask you to prove before they sign.

A-J dimensions (Autonomath canonical schema):
    A_basic              — name, authority, legal basis
    B_money              — amount_max/min, rate
    C_schedule           — application window
    D_documents          — required forms
    E_application_plan   — eligibility clauses / critical rules
    F_exclusions         — co-application forbidden list
    G_dealbreakers       — hard no-go conditions
    H_obligations        — post-award reporting
    I_contacts           — office addr / phone
    J_statistics         — acceptance rate / annual count (often null, tier S/A only)

env vars:
    JPINTEL_API_KEY   (optional)
    JPINTEL_API_BASE  (default: https://api.jpcite.com)

run:
    pip install -r ../requirements.txt
    python 03_full_program_detail.py UNI-0e2daaa865

expected output (real, unified_id=UNI-0e2daaa865):

    === 経営発展支援事業 ===
    tier: S   coverage_score: 9.0
    authority: 青森県つがる市 (municipality)
    url:       https://www.city.tsugaru.aomori.jp/soshiki/keizai/nourin/nogyo/7299.html
    amount:    up to 1000.0 万円 @ rate=0.25

    A_basic                OK   root keys: ['正式名称', '根拠法', '募集年度', '_source_ref']
    B_money                OK   amount_max=1000 amount_min=None rate=None
    C_schedule             OK   window=2024-11-22 → None (cycle=None)
    D_documents            OK   items=10
    E_application_plan     OK   root keys: ['eligibility_clauses', 'critical_rules', 'internal_checklist', 'past_acceptance_summaries', 'accounting_treatment']
    F_exclusions           OK   items=11
    G_dealbreakers         NULL
    H_obligations          OK   items=5
    I_contacts             OK   offices=2
    J_statistics           NULL (公式ページに採択率・件数の記載なし。予算範囲内審査制で、申請件数・採択件数は非公表。)

    source_mentions: 1 entry, master_kb=MUN-NW01457-1457
"""
from __future__ import annotations

import os
import sys

import httpx

API_BASE = os.environ.get("JPINTEL_API_BASE", "https://api.jpcite.com")
API_KEY = os.environ.get("JPINTEL_API_KEY")


def get_program(unified_id: str) -> dict:
    headers: dict[str, str] = {"Accept": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    try:
        resp = httpx.get(f"{API_BASE}/v1/programs/{unified_id}", headers=headers, timeout=15.0)
    except httpx.HTTPError as exc:
        print(f"ERROR: transport failure: {exc}", file=sys.stderr)
        sys.exit(2)

    if resp.status_code == 404:
        print(f"ERROR: program not found: {unified_id}", file=sys.stderr)
        sys.exit(1)
    if resp.status_code == 401:
        print("ERROR: 401 — invalid key", file=sys.stderr)
        sys.exit(1)
    if resp.status_code == 429:
        print(f"ERROR: 429 rate limit, retry after {resp.headers.get('Retry-After', '?')}s", file=sys.stderr)
        sys.exit(1)
    if resp.status_code >= 500:
        print(f"ERROR: server {resp.status_code}", file=sys.stderr)
        sys.exit(1)
    resp.raise_for_status()
    return resp.json()


def pretty_print(d: dict) -> None:
    print(f"=== {d['primary_name']} ===")
    print(f"tier: {d.get('tier')}   coverage_score: {d.get('coverage_score')}")
    print(f"authority: {d.get('authority_name')} ({d.get('authority_level')})")
    print(f"url:       {d.get('official_url')}")
    amt = d.get("amount_max_man_yen")
    rate = d.get("subsidy_rate")
    print(f"amount:    up to {amt} 万円 @ rate={rate}")
    print()

    enriched = d.get("enriched") or {}
    extraction = enriched.get("extraction") or {}

    def row(label: str, payload) -> None:
        if payload is None:
            print(f"{label:22s} NULL")
        elif isinstance(payload, dict):
            keys = list(payload.keys())[:6]
            print(f"{label:22s} OK   root keys: {keys}")
        elif isinstance(payload, list):
            print(f"{label:22s} OK   items={len(payload)}")
        else:
            print(f"{label:22s} OK   value={payload!r:.80s}")

    row("A_basic", extraction.get("basic"))
    money = extraction.get("money") or {}
    if money:
        print(
            f"{'B_money':22s} OK   amount_max={money.get('amount_max_man_yen')} "
            f"amount_min={money.get('amount_min_man_yen')} rate={money.get('subsidy_rate')}"
        )
    else:
        row("B_money", None)

    sch = extraction.get("schedule") or {}
    if sch:
        print(
            f"{'C_schedule':22s} OK   window={sch.get('start_date')} → "
            f"{sch.get('end_date')} (cycle={sch.get('cycle')})"
        )
    else:
        row("C_schedule", None)

    docs = extraction.get("documents") or {}
    if isinstance(docs, dict):
        n = len(docs.get("__legacy__") or [])
    else:
        n = len(docs) if docs else 0
    print(f"{'D_documents':22s} {'OK' if n else 'NULL'}   items={n}")

    row("E_application_plan", extraction.get("application_plan"))
    row("F_exclusions", extraction.get("exclusions"))
    row("G_dealbreakers", extraction.get("dealbreakers"))
    row("H_obligations", extraction.get("obligations"))

    contacts = extraction.get("contacts") or []
    n = len(contacts) if isinstance(contacts, list) else 1 if contacts else 0
    print(f"{'I_contacts':22s} {'OK' if n else 'NULL'}   offices={n}")

    stats = extraction.get("statistics") or {}
    has_stats = bool(stats and (stats.get("acceptance_rate") or stats.get("annual_accepted_count")))
    if has_stats:
        print(f"{'J_statistics':22s} OK   accept_rate={stats.get('acceptance_rate')}")
    else:
        note = (stats.get("note") or "")[:70]
        print(f"{'J_statistics':22s} NULL ({note})")

    print()
    sm = d.get("source_mentions")
    if isinstance(sm, dict):
        pairs = ", ".join(f"{k}={v}" for k, v in sm.items())
        print(f"source_mentions: {len(sm)} entry, {pairs}")
    elif isinstance(sm, list):
        print(f"source_mentions: {len(sm)} entries")


def main() -> None:
    unified_id = sys.argv[1] if len(sys.argv) > 1 else "UNI-0e2daaa865"
    data = get_program(unified_id)
    pretty_print(data)


if __name__ == "__main__":
    main()
