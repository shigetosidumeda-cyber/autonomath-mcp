#!/usr/bin/env python3
"""C-side egov_law_articles iter runner — fetches 100 lawnums from queue tail.

Usage: .venv/bin/python tools/offline/iter_egov_c.py
Reads:  tools/offline/_inbox/egov_law_articles/_law_ids.json
        tools/offline/_inbox/_progress.json (A head, read-only)
        tools/offline/_inbox/_progress_c.json (or init)
Writes: tools/offline/_inbox/egov_law_articles/raw/{lawnum}.json
        tools/offline/_inbox/egov_law_articles/2026-05-05_iter{N}_agentC{X}.jsonl (×10)
        tools/offline/_inbox/_progress_c.json (atomic)
Stdout: [C-{iter}] egov_law_articles +N (back={n}/9484, tail_idx={t}) — {title} ({slug})
        or [DONE-C] converged at idx=t (A=h)
"""
import socket
import dns.resolver
import urllib.request
import urllib.error
import json
import hashlib
import time
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path("/Users/shigetoumeda/jpcite")
INBOX = ROOT / "tools/offline/_inbox/egov_law_articles"
RAW = INBOX / "raw"
QUEUE_F = INBOX / "_law_ids.json"
PROG_A = ROOT / "tools/offline/_inbox/_progress.json"
PROG_C = ROOT / "tools/offline/_inbox/_progress_c.json"

_r = dns.resolver.Resolver(configure=False)
_r.nameservers = ["8.8.8.8", "1.1.1.1"]
_cache: dict[str, str] = {}
_orig = socket.getaddrinfo


def _patched(host, port, *a, **kw):
    try:
        if host not in _cache:
            ans = _r.resolve(host, "A")
            _cache[host] = str(ans[0])
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_cache[host], port))]
    except Exception:
        return _orig(host, port, *a, **kw)


socket.getaddrinfo = _patched


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def atomic_write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_progress_a() -> int:
    j = json.loads(PROG_A.read_text(encoding="utf-8"))
    return int(j["sources"]["egov_law_articles"]["next_url_index"])


def load_or_init_progress_c(queue_total: int) -> dict:
    if PROG_C.exists():
        return json.loads(PROG_C.read_text(encoding="utf-8"))
    return {
        "started_at": now_utc(),
        "last_updated": now_utc(),
        "iterations": 0,
        "sources": {
            "egov_law_articles": {
                "status": "in_progress",
                "completed_urls_back": 0,
                "next_url_index_back": queue_total - 1,
                "last_fetched_url": None,
                "quarantine": False,
            }
        },
        "errors": [],
    }


def recount_tail(queue: list[str]) -> int:
    """Walk from tail, count consecutive existing raw files."""
    cnt = 0
    for i in range(len(queue) - 1, -1, -1):
        p = RAW / f"{queue[i]}.json"
        if p.exists() and p.stat().st_size > 0:
            cnt += 1
        else:
            break
    return cnt


def fetch_one(lawnum: str) -> dict:
    """Fetch one lawnum. Returns row dict or {'skipped':True} or {'error':..}."""
    bp = RAW / f"{lawnum}.json"
    if bp.exists() and bp.stat().st_size > 0:
        return {"skipped": True, "lawnum": lawnum}
    url = f"https://laws.e-gov.go.jp/api/2/law_data/{lawnum}?law_full_text_format=json"
    try:
        time.sleep(3)
        req = urllib.request.Request(url, headers={"User-Agent": "jpcite-collector-c/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
            status = r.status
        bp.write_bytes(body)
        d = json.loads(body)
        title = (
            (d.get("law_full_text") or {}).get("law_title")
            or (d.get("law_info") or {}).get("law_title")
            or ""
        )
        return {
            "fetched_at": now_utc(),
            "source_id": "egov_law_articles",
            "url": url,
            "http_status": status,
            "content_hash": "sha256:" + hashlib.sha256(body).hexdigest(),
            "mime": "application/json",
            "license": "cc_by_4.0",
            "body_path": f"tools/offline/_inbox/egov_law_articles/raw/{lawnum}.json",
            "title": title,
            "extracted_text": body[:500].decode("utf-8", "replace"),
            "screenshot_path": None,
            "fetch_method": "agent_pool_dns_c",
            "notes": "",
            "lawnum": lawnum,
        }
    except urllib.error.HTTPError as e:
        return {"error": f"http_{e.code}", "lawnum": lawnum, "url": url}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e!r}"[:200], "lawnum": lawnum, "url": url}


def main() -> int:
    queue: list[str] = json.loads(QUEUE_F.read_text(encoding="utf-8"))
    total = len(queue)
    head_a = load_progress_a()
    prog_c = load_or_init_progress_c(total)
    src_c = prog_c["sources"]["egov_law_articles"]
    tail_idx = int(src_c["next_url_index_back"])

    # Convergence
    if tail_idx < head_a:
        print(f"[DONE-C] converged at idx={tail_idx} (A head={head_a})")
        src_c["status"] = "done_converged"
        prog_c["last_updated"] = now_utc()
        atomic_write_json(PROG_C, prog_c)
        return 2  # exit 2 = done

    # Slice 100 from tail (or down to head_a if fewer)
    lo = max(tail_idx - 100, head_a - 1)
    indices = list(range(tail_idx, lo, -1))
    if not indices:
        print(f"[DONE-C] no work: tail={tail_idx}, head_a={head_a}")
        src_c["status"] = "done_converged"
        prog_c["last_updated"] = now_utc()
        atomic_write_json(PROG_C, prog_c)
        return 2

    iter_n = int(prog_c.get("iterations", 0)) + 1
    # Distribute across 10 "agents" (logical pools), 10 each (or fewer)
    agents: list[list[str]] = [[] for _ in range(10)]
    for k, idx in enumerate(indices):
        agents[k // 10 if k < 100 else 9].append(queue[idx])

    # Open jsonl files per agent
    jsonl_files = {}
    today = "2026-05-05"
    for ai, lawnums in enumerate(agents, start=1):
        if not lawnums:
            continue
        f = INBOX / f"{today}_iter{iter_n}_agentC{ai}.jsonl"
        jsonl_files[ai] = f.open("a", encoding="utf-8")

    ok = err = skip = 0
    last_title = ""
    last_lawnum = ""
    errors_collected: list[dict] = []

    # Submit all 100 jobs across a 10-thread pool. Each thread sleeps 3s
    # internally before each request, so effective rate per thread is < 1 req/3s.
    # Map lawnum → agent index for jsonl routing
    lawnum_to_agent: dict[str, int] = {}
    for ai, lawnums in enumerate(agents, start=1):
        for ln in lawnums:
            lawnum_to_agent[ln] = ai

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = []
        for ai, lawnums in enumerate(agents, start=1):
            for ln in lawnums:
                futures.append(ex.submit(fetch_one, ln))
        for fut in as_completed(futures):
            res = fut.result()
            ln = res.get("lawnum", "")
            if "skipped" in res:
                skip += 1
            elif "error" in res:
                err += 1
                errors_collected.append({
                    "ts": now_utc(),
                    "source_id": "egov_law_articles",
                    "url": res.get("url", ""),
                    "kind": "fetch_error_c",
                    "msg": res["error"],
                })
            else:
                ai = lawnum_to_agent.get(ln, 1)
                f = jsonl_files.get(ai)
                if f is not None:
                    row = {k: v for k, v in res.items() if k != "lawnum"}
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                ok += 1
                last_title = res.get("title", "") or last_title
                last_lawnum = ln

    for f in jsonl_files.values():
        f.close()

    # Recount tail
    completed_back = recount_tail(queue)
    new_tail_idx = total - 1 - completed_back

    src_c["completed_urls_back"] = completed_back
    src_c["next_url_index_back"] = new_tail_idx
    if last_lawnum:
        src_c["last_fetched_url"] = (
            f"https://laws.e-gov.go.jp/api/2/law_data/{last_lawnum}?law_full_text_format=json"
        )
    prog_c["iterations"] = iter_n
    prog_c["last_updated"] = now_utc()
    if errors_collected:
        prog_c["errors"].extend(errors_collected[:10])  # cap
    atomic_write_json(PROG_C, prog_c)

    title_short = last_title[:40] if last_title else ""
    print(
        f"[C-{iter_n}] egov_law_articles +{ok} (skip={skip} err={err}) "
        f"back={completed_back}/{total} tail_idx={new_tail_idx} — {title_short} ({last_lawnum})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
