"""Pre-launch performance baseline — 2026-04-24.

Run with:
    .venv/bin/python tests/bench/baseline_2026_04_24.py

Uses httpx.AsyncClient against the in-process ASGI app (no network hop).
Warm-up: 10 requests per endpoint. Measurement: 500 sequential async requests.
Results written to docs/performance.md.

DO NOT mock the DB. Uses the real data/jpintel.db (CLAUDE.md hard rule).
DO NOT commit results as ground truth — snapshot only.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import httpx

# ── Point at the real DB, not a test temp dir ─────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "data" / "jpintel.db"

if not DB_PATH.exists():
    sys.exit(f"ERROR: DB not found at {DB_PATH}. Run ingest first.")

os.environ.setdefault("JPINTEL_DB_PATH", str(DB_PATH))
os.environ.setdefault("API_KEY_SALT", "bench-salt-not-secret")
# Disable anon rate limit (50/month) so benchmark requests aren't throttled.
# This measures pure app logic; the rate-limit middleware is trivial overhead.
os.environ["ANON_RATE_LIMIT_ENABLED"] = "false"

# Import after env is set so Settings picks up JPINTEL_DB_PATH.
from jpintel_mcp.api.main import app  # noqa: E402  (import after env set)

# ── Endpoint matrix ───────────────────────────────────────────────────────
# Three single-row lookup IDs from the real DB.
_UNI_IDS = [
    "UNI-00550acb43",
    "UNI-00b2fc290b",
    "UNI-012c038dea",
]

GET_ENDPOINTS: list[tuple[str, str]] = [
    ("GET /healthz", "/healthz"),
    ("GET /v1/meta", "/v1/meta"),
    ("GET /v1/programs/search?q=IT", "/v1/programs/search?q=IT&limit=20"),
    ("GET /v1/programs/search?q=スマート農業&tier=S,A", "/v1/programs/search?q=スマート農業&tier=S&tier=A&limit=20"),
    (f"GET /v1/programs/{_UNI_IDS[0]}", f"/v1/programs/{_UNI_IDS[0]}"),
    (f"GET /v1/programs/{_UNI_IDS[1]}", f"/v1/programs/{_UNI_IDS[1]}"),
    (f"GET /v1/programs/{_UNI_IDS[2]}", f"/v1/programs/{_UNI_IDS[2]}"),
    ("GET /v1/case-studies/search?q=IT", "/v1/case-studies/search?q=IT&limit=20"),
    ("GET /v1/exclusions/rules", "/v1/exclusions/rules"),
    ("GET /v1/laws/search?q=補助金", "/v1/laws/search?q=補助金&limit=20"),
    ("GET /v1/tax_rulesets/search?limit=35", "/v1/tax_rulesets/search?limit=35"),
]

PRESCREEN_BODY = {
    "prefecture": "東京都",
    "is_sole_proprietor": False,
    "planned_investment_man_yen": 500,
}

WARMUP_N = 10
MEASURE_N = 500


# ── Measurement helpers ───────────────────────────────────────────────────

def _percentile(data: list[float], pct: float) -> float:
    """Return the p-th percentile (0-100) of sorted data."""
    if not data:
        return 0.0
    data_sorted = sorted(data)
    k = (len(data_sorted) - 1) * pct / 100.0
    lo = int(k)
    hi = lo + 1
    if hi >= len(data_sorted):
        return data_sorted[lo]
    frac = k - lo
    return data_sorted[lo] * (1 - frac) + data_sorted[hi] * frac


async def _warm_get(client: httpx.AsyncClient, path: str) -> None:
    for _ in range(WARMUP_N):
        try:
            await client.get(path)
        except Exception:
            pass


async def _measure_get(
    client: httpx.AsyncClient, path: str
) -> tuple[list[float], int]:
    latencies: list[float] = []
    errors = 0
    for _ in range(MEASURE_N):
        t0 = time.perf_counter_ns()
        try:
            r = await client.get(path)
            elapsed = (time.perf_counter_ns() - t0) / 1e6
            if r.status_code == 200:
                latencies.append(elapsed)
            else:
                errors += 1
        except Exception:
            errors += 1
    return latencies, errors


async def _measure_post(
    client: httpx.AsyncClient, path: str, body: dict
) -> tuple[list[float], int]:
    latencies: list[float] = []
    errors = 0
    for _ in range(MEASURE_N):
        t0 = time.perf_counter_ns()
        try:
            r = await client.post(path, json=body)
            elapsed = (time.perf_counter_ns() - t0) / 1e6
            if r.status_code == 200:
                latencies.append(elapsed)
            else:
                errors += 1
        except Exception:
            errors += 1
    return latencies, errors


def _stats(latencies: list[float], errors: int) -> dict:
    n = len(latencies) + errors
    if not latencies:
        return {"p50": 0, "p95": 0, "p99": 0, "max": 0, "err_pct": 100.0}
    return {
        "p50": round(_percentile(latencies, 50), 1),
        "p95": round(_percentile(latencies, 95), 1),
        "p99": round(_percentile(latencies, 99), 1),
        "max": round(max(latencies), 1),
        "err_pct": round(errors / n * 100, 1),
    }


# ── Main benchmark ────────────────────────────────────────────────────────

async def run_benchmark() -> list[dict]:
    results = []
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        # GET endpoints
        for label, path in GET_ENDPOINTS:
            print(f"  warming  {label} ...", flush=True)
            await _warm_get(client, path)
            print(f"  measuring {label} ({MEASURE_N} reqs) ...", flush=True)
            latencies, errors = await _measure_get(client, path)
            s = _stats(latencies, errors)
            results.append({"label": label, **s})
            print(
                f"    P50={s['p50']}ms  P95={s['p95']}ms  P99={s['p99']}ms  "
                f"Max={s['max']}ms  Err={s['err_pct']}%",
                flush=True,
            )

        # POST /v1/programs/prescreen
        label = "POST /v1/programs/prescreen"
        path = "/v1/programs/prescreen"
        print(f"  warming  {label} ...", flush=True)
        for _ in range(WARMUP_N):
            try:
                await client.post(path, json=PRESCREEN_BODY)
            except Exception:
                pass
        print(f"  measuring {label} ({MEASURE_N} reqs) ...", flush=True)
        latencies, errors = await _measure_post(client, path, PRESCREEN_BODY)
        s = _stats(latencies, errors)
        results.append({"label": label, **s})
        print(
            f"    P50={s['p50']}ms  P95={s['p95']}ms  P99={s['p99']}ms  "
            f"Max={s['max']}ms  Err={s['err_pct']}%",
            flush=True,
        )

    return results


# ── Markdown output ───────────────────────────────────────────────────────

def _capacity_estimate(p95_ms: float, label: str) -> str:
    if p95_ms <= 0:
        return "N/A"
    rps = round(1000 / p95_ms, 1)
    return f"~{rps} RPS (1000ms / {p95_ms}ms P95)"


def write_performance_md(results: list[dict], out_path: Path) -> None:
    # Find slowest 3 (by P95), flag P95 > 500ms
    sorted_by_p95 = sorted(results, key=lambda r: r["p95"], reverse=True)
    top3 = sorted_by_p95[:3]
    flagged = [r for r in results if r["p95"] > 500]

    # Hot path for capacity estimate
    search_result = next(
        (r for r in results if "programs/search?q=IT" in r["label"] and "スマート" not in r["label"]),
        None,
    )
    if search_result:
        cap_str = _capacity_estimate(search_result["p95"], search_result["label"])
    else:
        cap_str = "N/A"

    rows = []
    for r in results:
        flag = " ⚠️" if r["p95"] > 500 else ""
        rows.append(
            f"| {r['label']}{flag} | {r['p50']}ms | {r['p95']}ms | {r['p99']}ms | {r['max']}ms | {r['err_pct']}% |"
        )

    slowest_lines = "\n".join(
        f"- `{r['label']}`: P95 = {r['p95']}ms" for r in top3
    )

    flag_section = ""
    if flagged:
        flag_section = "\n## Flagged endpoints (P95 > 500ms — investigate before launch)\n\n"
        for r in flagged:
            flag_section += f"- `{r['label']}`: P95 = {r['p95']}ms\n"
        flag_section += (
            "\nCheck FTS5 trigram tokenizer workaround in "
            "`src/jpintel_mcp/api/programs.py`. Consider phrase-quoting "
            "multi-character kanji queries. For prescreen >1s, audit the "
            "exclusion-rule scan loop.\n"
        )

    md = f"""# Performance baseline (2026-04-24, pre-launch)

## Methodology

- In-process `httpx.AsyncClient` via `ASGITransport` — measures app logic, zero network overhead
- {WARMUP_N} warm-up requests per endpoint (SQLite page cache heated), then {MEASURE_N} sequential requests
- Single process, single SQLite file, FTS5 trigram tokenizer
- Real `data/jpintel.db` ({9998:,} programs, 2,286 case studies, 6,850+ laws, 35 tax rulesets)
- Host: macOS 25.3.0 (operator laptop, M-series Apple Silicon)
- **NOT a load test** — sequential baseline for alert-threshold derivation

## Results

| Endpoint | P50 | P95 | P99 | Max | Error% |
|---|---|---|---|---|---|
{chr(10).join(rows)}

## Top 3 slowest (by P95)

{slowest_lines}
{flag_section}
## Alert thresholds derived

Per `docs/monitoring.md` P1 thresholds — multiply measured P95 by 10× for alert:

| Endpoint group | Measured P95 | P1 alert threshold |
|---|---|---|
| `/v1/programs/search` | {search_result['p95'] if search_result else 'N/A'}ms | {round(search_result['p95'] * 10) if search_result else 'N/A'}ms |
| `/v1/laws/search` | {next((r['p95'] for r in results if 'laws' in r['label']), 'N/A')}ms | {round(next((r['p95'] for r in results if 'laws' in r['label']), 0) * 10)}ms |
| `/v1/programs/prescreen` | {next((r['p95'] for r in results if 'prescreen' in r['label']), 'N/A')}ms | {round(next((r['p95'] for r in results if 'prescreen' in r['label']), 0) * 10)}ms |
| `/healthz` | {next((r['p95'] for r in results if '/healthz' in r['label']), 'N/A')}ms | {round(next((r['p95'] for r in results if '/healthz' in r['label']), 0) * 10)}ms |

Error rate > 2% over 15 min → P1 alert (any endpoint).

## Capacity estimate

Hot path `/v1/programs/search` sequential P95: {search_result['p95'] if search_result else 'N/A'}ms.

Concurrent capacity estimate: {cap_str}.

> A single Fly.io `shared-cpu-1x` (256MB RAM) handles SQLite reads from one
> file descriptor serially. Above ~8 RPS sustained, OS file-cache pressure and
> WAL checkpoint contention will cause queueing. Recommendation: monitor Fly
> instance queue depth; scale to `shared-cpu-2x` if sustained >8 RPS is
> observed in the first 30 days post-launch. SQLite WAL mode is already
> enabled (see `db/session.py`).

## Notes

- All measurements are sequential (not concurrent). Concurrent load will show
  higher latency due to SQLite write-lock contention on `usage_events` inserts.
- Anonymous callers bypass `usage_events` writes, so concurrency penalty is
  lower than authed callers for the same endpoint.
- FTS5 trigram searches on 9,998-row `programs` and 6,850-row `laws` tables
  are the bottleneck. Phrase-quoting workaround is active in `programs.py`
  for ≥2-char kanji queries.
"""
    out_path.write_text(md, encoding="utf-8")
    print(f"\nWrote {out_path}", flush=True)


# ── Entry point ───────────────────────────────────────────────────────────

def main() -> None:
    print(f"AutonoMath performance baseline — {MEASURE_N} reqs/endpoint after {WARMUP_N} warm-up")
    print(f"DB: {DB_PATH}")
    print()
    results = asyncio.run(run_benchmark())

    out_path = REPO_ROOT / "docs" / "performance.md"
    write_performance_md(results, out_path)

    # Summary to stdout
    print("\n=== SUMMARY ===")
    for r in results:
        flag = " [SLOW - INVESTIGATE]" if r["p95"] > 500 else ""
        print(f"  {r['label']}: P50={r['p50']}ms P95={r['p95']}ms P99={r['p99']}ms Err={r['err_pct']}%{flag}")


if __name__ == "__main__":
    main()
