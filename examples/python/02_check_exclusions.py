"""
02_check_exclusions.py
----------------------
Given 4 program IDs, detect which pairs cannot be co-applied and why.
Hits a single /v1/exclusions/check endpoint; the server evaluates all 35
rules locally. This is the demo we show to AI agent builders — "if you let
the LLM pick programs, call this before the final answer."

env vars:
    JPINTEL_API_KEY   (optional)
    JPINTEL_API_BASE  (default: https://api.jpcite.com)

run:
    pip install -r ../requirements.txt
    python 02_check_exclusions.py

expected output:

    Checking 4 programs: keiei-kaishi-shikin, koyo-shuno-shikin, seinen-shuno-shikin, super-L-shikin

    [1] absolute  (critical)  rule=excl-keiei-kaishi-vs-koyo-shuno-absolute
        programs: keiei-kaishi-shikin + koyo-shuno-shikin
        reason:   経営開始資金は、雇用就農資金や他の雇用就農者を対象とした実践研修支援事業による助成...
    [2] prerequisite  (critical)  rule=excl-seinen-requires-cert-new-farmer
        programs: seinen-shuno-shikin
        reason:   青年等就農資金を借りるには、市町村から認定新規就農者の認定を受けていることが前提。認定前...
    [3] prerequisite  (critical)  rule=excl-super-L-requires-cert-farmer
        programs: super-L-shikin
        reason:   スーパーL資金を借りるには、市町村から認定農業者の認定を受けていることが前提。認定新規就...
    [4] entity_scope_restriction  (critical)  rule=excl-corp-established-vs-new-farmer-programs
        programs: keiei-kaishi-shikin + koyo-shuno-shikin + seinen-shuno-shikin
        reason:   経営開始から5年以上経過した100ha級の法人農家は、新規就農者向け制度 (経営開始資金・青年...

    total hits: 4 / rules_checked: 35
"""

from __future__ import annotations

import os
import sys

import httpx

API_BASE = os.environ.get("JPINTEL_API_BASE", "https://api.jpcite.com")
API_KEY = os.environ.get("JPINTEL_API_KEY")


def check_exclusions(program_ids: list[str]) -> dict:
    headers: dict[str, str] = {"Accept": "application/json", "Content-Type": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY

    try:
        resp = httpx.post(
            f"{API_BASE}/v1/exclusions/check",
            headers=headers,
            json={"program_ids": program_ids},
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        print(f"ERROR: transport failure: {exc}", file=sys.stderr)
        sys.exit(2)

    if resp.status_code == 401:
        print("ERROR: 401 — invalid key", file=sys.stderr)
        sys.exit(1)
    if resp.status_code == 429:
        print(
            f"ERROR: 429 rate limit, retry after {resp.headers.get('Retry-After', '?')}s",
            file=sys.stderr,
        )
        sys.exit(1)
    if resp.status_code >= 500:
        print(f"ERROR: server {resp.status_code}", file=sys.stderr)
        sys.exit(1)
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    # Realistic agri case: a new farmer eyeing all 4 major funding tracks at
    # once. Running this before applying prevents rejection for co-claiming.
    candidates = [
        "keiei-kaishi-shikin",  # 経営開始資金 (agency of new-farmer grant)
        "koyo-shuno-shikin",  # 雇用就農資金 (employed-new-farmer grant)
        "seinen-shuno-shikin",  # 青年等就農資金 (young-farmer loan, requires cert)
        "super-L-shikin",  # スーパーL資金 (large-scale loan, requires cert)
    ]

    print(f"Checking {len(candidates)} programs: {', '.join(candidates)}")
    print()

    data = check_exclusions(candidates)
    hits = data["hits"]
    for i, h in enumerate(hits, 1):
        progs = " + ".join(h["programs_involved"])
        reason = (h.get("description") or "")[:70].replace("\n", " ")
        print(f"[{i}] {h['kind']}  ({h.get('severity', '-') or '-'})  rule={h['rule_id']}")
        print(f"    programs: {progs}")
        print(f"    reason:   {reason}...")

    print()
    print(f"total hits: {len(hits)} / rules_checked: {data['checked_rules']}")


if __name__ == "__main__":
    main()
