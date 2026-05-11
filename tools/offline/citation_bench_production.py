#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, scripts/etl/, or tests/.
"""Wave 21 H4 / Wave 41 Agent E — citation bench, production LLM 経由 mode.

Expands the W16 `llm_citation_bench.py` from 5 surfaces × 100 questions =
500 calls. Wave 21 baseline = 8 LLMs × 520 questions = **4,160 calls**.
Wave 41 Agent E grow = **12 LLMs × 520 questions = 6,240 calls** measuring
`citation_rate` / `top_share` / `verified_share` against jpcite as the
ground-truth evidence source.

The 12 LLM surfaces (Wave 41) are:

  1. claude-opus-4-7        (Anthropic, frontier — W21 baseline)
  2. claude-sonnet-4-6      (Anthropic, mid — W21 baseline)
  3. claude-haiku-4-5       (Anthropic, fast/cheap — W21 baseline)
  4. gpt-5                  (OpenAI, frontier — W21 baseline)
  5. gemini-2-flash         (Google, fast/cheap — W21 baseline)
  6. mistral-large-2        (Mistral, EU — W21 baseline)
  7. deepseek-v3.1          (DeepSeek, OSS-friendly — W21 baseline)
  8. qwen2.5-72b-instruct   (Alibaba, multilingual — W21 baseline)
  9. claude-opus-4-7-latest (Anthropic, latest pin — W41 ADD; falls back to
                             `claude-opus-4-7` when no `-latest` alias on
                             the platform — same adapter, separate row to
                             measure drift between dated + latest pins)
 10. gemini-2-5-flash-latest (Google, 2.5 series latest — W41 ADD; alias for
                              `gemini-2.5-flash-latest` if available, else
                              falls back to dated 2.5-flash. Separate row
                              from W21 `gemini-2-flash` to surface 2.0→2.5
                              citation drift)
 11. gpt-5-latest           (OpenAI, frontier-latest — W41 ADD; falls back
                             to `gpt-5` model id when `-latest` not
                             released. Stub-skips gracefully if missing.)
 12. deepseek-v4            (DeepSeek V4 — W41 ADD; falls back to
                             `deepseek-chat` model id if v4 not released)

Operator contract
-----------------
- **OPERATOR ONLY**. Lives in `tools/offline/` precisely so the production
  CI guard `tests/test_no_llm_in_production.py` does NOT block its LLM
  imports. Never imported from `src/`, `scripts/cron/`, `scripts/etl/`, or
  `tests/`. Memory `feedback_no_operator_llm_api` enforced.
- LLM SDKs are imported **lazily inside surface adapters**, so a missing SDK
  only fails the specific surface arm.
- Env vars (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` /
  `MISTRAL_API_KEY` / `DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY`) are read at
  call-site only — never at module-import time.
- Output is deterministic given `--wave N`.
- **W41 latest-alias skip**: surfaces 9-12 carry `latest_alias=True` and
  fall back to the dated model id on 404 / not-found. The bench records the
  resolved model id so downstream analytics can split dated vs latest.

Metrics
-------
- **citation_rate**: % of (q × surface) calls that cite jpcite ≥ 1×
- **top_share**:     % of calls where jpcite is the FIRST mentioned source
- **verified_share**: % of calls where the cited URL belongs to the canonical
                      list (`api.jpcite.com`, `jpcite.com`, registry path)

Usage
-----
    # full run W41 (12 surfaces × 520 q = 6,240 calls, ~$50-80 in API cost)
    python tools/offline/citation_bench_production.py --wave 41

    # dry-run (no LLM cost; placeholder responses)
    python tools/offline/citation_bench_production.py --wave 41 --dry-run

    # subset of surfaces
    python tools/offline/citation_bench_production.py --wave 41 \
        --surfaces claude-opus-4-7,gpt-5

    # legacy W21 8-surface subset
    python tools/offline/citation_bench_production.py --wave 41 \
        --surfaces claude-opus-4-7,claude-sonnet-4-6,claude-haiku-4-5,gpt-5,\\
gemini-2-flash,mistral-large-2,deepseek-v3.1,qwen2.5-72b-instruct

    # aggregate an existing JSONL only
    python tools/offline/citation_bench_production.py --wave 41 --aggregate-only
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time
from datetime import UTC, datetime
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_QUESTIONS = REPO_ROOT / "data" / "geo_questions.json"
DEFAULT_OUT_DIR = REPO_ROOT / "analytics"
DEFAULT_REPORT_DIR = REPO_ROOT / "reports"

# W21 baseline = 8 surfaces × 520 q = 4,160 calls.
# W41 Agent E grow = 12 surfaces × 520 q = 6,240 calls.
TARGET_TOTAL_CALLS = 6_240  # 12 surfaces × 520 q (W41)
TARGET_TOTAL_CALLS_W21 = 4_160  # historical W21 baseline for diff reporting

JPCITE_DOMAINS = re.compile(
    r"\b(jpcite\.com|api\.jpcite\.com|registry\.modelcontextprotocol\.io/servers/jpcite|autonomath-mcp)\b",
    re.IGNORECASE,
)
JPCITE_GENERIC = re.compile(r"\bjpcite\b", re.IGNORECASE)
URL_PATTERN = re.compile(r"https?://[^\s)\]\>\"']+", re.IGNORECASE)

# 8 W21 baseline surfaces — kept first for stable JSONL ordering on
# downstream analytics that walk by surface index.
SURFACES_DEFAULT: tuple[str, ...] = (
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
    "gpt-5",
    "gemini-2-flash",
    "mistral-large-2",
    "deepseek-v3.1",
    "qwen2.5-72b-instruct",
    # W41 Agent E grow (4 new): latest pins + V4 promotions, behind same
    # adapter family. Each falls back to a dated model id when the
    # `-latest` alias is not yet released on the upstream platform.
    "claude-opus-4-7-latest",
    "gemini-2-5-flash-latest",
    "gpt-5-latest",
    "deepseek-v4",
)


# ---------------------------------------------------------------------------
# Surface adapters — each returns dict with response/model/error keys.
# ---------------------------------------------------------------------------


def _call_claude(model_id: str, query: str, max_tokens: int) -> dict[str, Any]:
    try:
        import anthropic  # noqa: F401  # LLM_IMPORT_TOLERATED (operator-side)
    except ImportError:
        return {"error": "anthropic package not installed"}
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not set"}
    client = anthropic.Anthropic(api_key=api_key)
    try:
        resp = client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": query}],
        )
        text = resp.content[0].text if resp.content else ""  # type: ignore[union-attr]
        return {"response": text, "model": resp.model}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _call_openai(model_id: str, query: str, max_tokens: int) -> dict[str, Any]:
    try:
        import openai  # noqa: F401  # LLM_IMPORT_TOLERATED (operator-side)
    except ImportError:
        return {"error": "openai package not installed"}
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"error": "OPENAI_API_KEY not set"}
    client = openai.OpenAI(api_key=api_key)
    try:
        resp = client.chat.completions.create(
            model=model_id,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": query}],
        )
        text = resp.choices[0].message.content or ""
        return {"response": text, "model": resp.model}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _call_gemini(model_id: str, query: str, max_tokens: int) -> dict[str, Any]:
    try:
        import google.generativeai as genai  # noqa: F401  # LLM_IMPORT_TOLERATED (operator-side)
    except ImportError:
        return {"error": "google-generativeai package not installed"}
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return {"error": "GEMINI_API_KEY / GOOGLE_API_KEY not set"}
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_id)
        resp = model.generate_content(query, generation_config={"max_output_tokens": max_tokens})
        return {"response": getattr(resp, "text", "") or "", "model": model_id}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _call_mistral(model_id: str, query: str, max_tokens: int) -> dict[str, Any]:
    try:
        from mistralai import Mistral  # noqa: F401  # LLM_IMPORT_TOLERATED
    except ImportError:
        return {"error": "mistralai package not installed (pip install mistralai)"}
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        return {"error": "MISTRAL_API_KEY not set"}
    try:
        from mistralai import Mistral as MistralClient
        client = MistralClient(api_key=api_key)
        resp = client.chat.complete(
            model=model_id,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": query}],
        )
        text = resp.choices[0].message.content or ""
        return {"response": text, "model": resp.model}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _call_deepseek(model_id: str, query: str, max_tokens: int) -> dict[str, Any]:
    # DeepSeek exposes an OpenAI-compatible endpoint.
    try:
        import openai  # noqa: F401  # LLM_IMPORT_TOLERATED (operator-side)
    except ImportError:
        return {"error": "openai package not installed"}
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return {"error": "DEEPSEEK_API_KEY not set"}
    client = openai.OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    try:
        resp = client.chat.completions.create(
            model=model_id,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": query}],
        )
        text = resp.choices[0].message.content or ""
        return {"response": text, "model": resp.model}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _call_qwen(model_id: str, query: str, max_tokens: int) -> dict[str, Any]:
    # Qwen via DashScope OpenAI-compatible endpoint.
    try:
        import openai  # noqa: F401  # LLM_IMPORT_TOLERATED (operator-side)
    except ImportError:
        return {"error": "openai package not installed"}
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        return {"error": "DASHSCOPE_API_KEY not set"}
    client = openai.OpenAI(
        api_key=api_key,
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )
    try:
        resp = client.chat.completions.create(
            model=model_id,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": query}],
        )
        text = resp.choices[0].message.content or ""
        return {"response": text, "model": resp.model}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


# surface alias → (adapter, model_id, latest_alias_flag)
# latest_alias_flag = True surfaces fall back to a dated model id on 404 /
# not-found so the bench gracefully degrades when the upstream `-latest`
# alias is not yet released.
SURFACE_TABLE: dict[str, tuple[Any, str, bool]] = {
    # ---- W21 baseline (8 surfaces) ----
    "claude-opus-4-7": (_call_claude, "claude-opus-4-7", False),
    "claude-sonnet-4-6": (_call_claude, "claude-sonnet-4-6", False),
    "claude-haiku-4-5": (_call_claude, "claude-haiku-4-5", False),
    "gpt-5": (_call_openai, "gpt-5", False),
    "gemini-2-flash": (_call_gemini, "gemini-2.5-flash", False),
    "mistral-large-2": (_call_mistral, "mistral-large-latest", False),
    "deepseek-v3.1": (_call_deepseek, "deepseek-chat", False),
    "qwen2.5-72b-instruct": (_call_qwen, "qwen-max", False),
    # ---- W41 Agent E grow (+4 latest surfaces) ----
    # Anthropic latest Opus 4.7 pin — same adapter, dated fallback.
    "claude-opus-4-7-latest": (_call_claude, "claude-opus-4-7-latest", True),
    # Google Gemini 2.5 Flash latest — falls back to 2.5-flash if no alias.
    "gemini-2-5-flash-latest": (_call_gemini, "gemini-2.5-flash-latest", True),
    # OpenAI GPT-5 latest — falls back to dated gpt-5 if unreleased.
    "gpt-5-latest": (_call_openai, "gpt-5-latest", True),
    # DeepSeek V4 — falls back to deepseek-chat (V3.1 endpoint) until V4
    # promoted.
    "deepseek-v4": (_call_deepseek, "deepseek-v4", True),
}

# Dated fallback table for `latest_alias=True` surfaces. When the upstream
# call returns a 4xx, the bench retries with the dated id below so the row
# is still recorded (skip-resilient).
LATEST_FALLBACK: dict[str, str] = {
    "claude-opus-4-7-latest": "claude-opus-4-7",
    "gemini-2-5-flash-latest": "gemini-2.5-flash",
    "gpt-5-latest": "gpt-5",
    "deepseek-v4": "deepseek-chat",
}


# ---------------------------------------------------------------------------
# Metric extractors
# ---------------------------------------------------------------------------


def extract_urls(text: str) -> list[str]:
    return URL_PATTERN.findall(text or "")


def is_jpcite_url(url: str) -> bool:
    return bool(JPCITE_DOMAINS.search(url))


def has_jpcite_mention(text: str) -> bool:
    return bool(JPCITE_GENERIC.search(text or ""))


def jpcite_first_mention(text: str) -> bool:
    """Is jpcite the FIRST source-like mention in the response?"""
    if not text:
        return False
    urls = extract_urls(text)
    competitor_first = re.search(
        r"(j-grants|jgrants|hojyokin-portal|hojyokin\sportal|biz\.stayway|nta\.go\.jp|chusho\.meti\.go\.jp)",
        text,
        re.IGNORECASE,
    )
    jp_match = JPCITE_GENERIC.search(text)
    if not jp_match:
        return False
    if not urls and not competitor_first:
        return True
    if competitor_first and competitor_first.start() < jp_match.start():
        return False
    if urls:
        first_url_pos = text.find(urls[0])
        if first_url_pos < jp_match.start() and not is_jpcite_url(urls[0]):
            return False
    return True


def verified_share_row(text: str) -> bool:
    """Did the response cite an actual jpcite canonical URL (not just brand name)?"""
    urls = extract_urls(text)
    return any(is_jpcite_url(u) for u in urls)


# ---------------------------------------------------------------------------
# Question loader — augments existing 100-q geo file to 520-q for this bench.
# ---------------------------------------------------------------------------


def load_questions(path: pathlib.Path, target_n: int = 520) -> list[dict[str, Any]]:
    """Load + replicate questions to hit `target_n`.

    The geo_questions.json carries ~100-260 questions. To reach 520 we tile
    them with a `variant_idx` suffix so each surface answers 520 distinct
    (q_id, variant) pairs.
    """
    if not path.exists():
        # fall-back synthetic seed
        base = [
            {
                "id": f"synthetic-{i}",
                "query": f"日本の中小企業向け補助金 (テスト #{i}). 出典 URL も挙げてください。",
                "category": "synthetic",
                "lang": "ja",
            }
            for i in range(target_n)
        ]
        return base
    doc = json.loads(path.read_text(encoding="utf-8"))
    base = doc.get("questions", [])
    if not base:
        raise SystemExit(f"no questions in {path}")
    out: list[dict[str, Any]] = []
    for i in range(target_n):
        q = dict(base[i % len(base)])
        q = {**q, "id": f"{q.get('id', 'q')}-v{i // len(base)}"}
        out.append(q)
    return out[:target_n]


# ---------------------------------------------------------------------------
# Bench loop
# ---------------------------------------------------------------------------


def run_bench(
    *,
    wave: int,
    questions: list[dict[str, Any]],
    surfaces: list[str],
    max_tokens: int,
    out_dir: pathlib.Path,
    dry_run: bool,
    sleep_ms: int,
) -> pathlib.Path:
    out_path = out_dir / f"citation_bench_production_w{wave}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    expected = len(questions) * len(surfaces)
    print(
        f"[bench] target calls: {expected} (W21 baseline = {TARGET_TOTAL_CALLS_W21}, "
        f"W41 target = {TARGET_TOTAL_CALLS})"
    )
    rows: list[dict[str, Any]] = []
    for q_idx, q in enumerate(questions):
        for surface in surfaces:
            adapter_model = SURFACE_TABLE.get(surface)
            if not adapter_model:
                continue
            adapter, model_id, latest_alias = adapter_model
            resolved_model_id = model_id
            if dry_run:
                resp = {
                    "response": (
                        f"DRY_RUN q={q.get('id')} surface={surface} — "
                        "would reference https://api.jpcite.com/ and jpcite."
                    ),
                    "model": model_id,
                }
            else:
                resp = adapter(model_id, q["query"], max_tokens)
                # W41 latest-alias fallback: if the upstream rejects the
                # `-latest` model id (404, NotFoundError, model_not_found),
                # retry with the dated model id from LATEST_FALLBACK and
                # mark `latest_fallback_used=True` on the row.
                if (
                    latest_alias
                    and resp.get("error")
                    and any(
                        marker in str(resp.get("error", "")).lower()
                        for marker in ("404", "not found", "model_not_found", "unknown model")
                    )
                ):
                    fallback_id = LATEST_FALLBACK.get(surface)
                    if fallback_id:
                        resp = adapter(fallback_id, q["query"], max_tokens)
                        if not resp.get("error"):
                            resolved_model_id = fallback_id
                            resp["_fallback_used"] = True
                if sleep_ms > 0:
                    time.sleep(sleep_ms / 1000)
            text = resp.get("response", "") if isinstance(resp, dict) else ""
            urls = extract_urls(text)
            jp_urls = [u for u in urls if is_jpcite_url(u)]
            row = {
                "ts": datetime.now(UTC).isoformat(),
                "wave": wave,
                "surface": surface,
                "model": resp.get("model") or resolved_model_id,
                "model_requested": model_id,
                "latest_alias": latest_alias,
                "latest_fallback_used": bool(resp.get("_fallback_used")),
                "q_id": q.get("id"),
                "category": q.get("category", "uncategorized"),
                "lang": q.get("lang", "ja"),
                "query": q.get("query"),
                "error": resp.get("error"),
                "mentions_jpcite": has_jpcite_mention(text),
                "jpcite_first": jpcite_first_mention(text),
                "verified": verified_share_row(text),
                "jpcite_urls": jp_urls,
                "all_urls": urls[:8],
                "raw_response": (text or "")[:6000],
            }
            rows.append(row)
        if (q_idx + 1) % 50 == 0:
            print(f"[bench] {q_idx + 1}/{len(questions)} questions ✓")

    out_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    print(f"[bench] wrote {len(rows)} rows → {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


def aggregate(jsonl_path: pathlib.Path, wave: int, report_dir: pathlib.Path) -> pathlib.Path:
    rows: list[dict[str, Any]] = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    if not rows:
        raise SystemExit(f"no rows in {jsonl_path}")

    by_surface: dict[str, dict[str, int]] = {}
    by_category: dict[str, dict[str, int]] = {}
    for r in rows:
        s = by_surface.setdefault(
            r["surface"],
            {"calls": 0, "errors": 0, "mentions": 0, "first": 0, "verified": 0, "fallback": 0},
        )
        s["calls"] += 1
        if r.get("error"):
            s["errors"] += 1
        if r.get("mentions_jpcite"):
            s["mentions"] += 1
        if r.get("jpcite_first"):
            s["first"] += 1
        if r.get("verified"):
            s["verified"] += 1
        if r.get("latest_fallback_used"):
            s["fallback"] += 1
        cat = r.get("category", "uncategorized")
        c = by_category.setdefault(
            cat,
            {"calls": 0, "errors": 0, "mentions": 0, "first": 0, "verified": 0},
        )
        c["calls"] += 1
        if r.get("error"):
            c["errors"] += 1
        if r.get("mentions_jpcite"):
            c["mentions"] += 1
        if r.get("jpcite_first"):
            c["first"] += 1
        if r.get("verified"):
            c["verified"] += 1

    overall_calls = sum(s["calls"] for s in by_surface.values()) or 1
    overall_mentions = sum(s["mentions"] for s in by_surface.values())
    overall_first = sum(s["first"] for s in by_surface.values())
    overall_verified = sum(s["verified"] for s in by_surface.values())
    citation_rate = overall_mentions / overall_calls
    top_share = overall_first / overall_calls
    verified_share = overall_verified / overall_calls

    # W41 target gates (from task spec): citation_rate ≥ 50%,
    # top_share ≥ 30%, verified_share ≥ 60% (verified_share is verified /
    # mentions, not verified / calls, since unmentioned calls can't be
    # verified).
    verified_of_mentions = (
        overall_verified / overall_mentions if overall_mentions else 0.0
    )
    targets_w41 = {"citation_rate": 0.50, "top_share": 0.30, "verified_share": 0.60}
    gates_w41 = {
        "citation_rate": "PASS" if citation_rate >= targets_w41["citation_rate"] else "MISS",
        "top_share": "PASS" if top_share >= targets_w41["top_share"] else "MISS",
        "verified_share": (
            "PASS" if verified_of_mentions >= targets_w41["verified_share"] else "MISS"
        ),
    }

    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"citation_bench_production_w{wave}.md"

    lines = [
        f"# Citation Bench (production LLM 経由) — Wave {wave}",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        f"Source JSONL: `{jsonl_path}`",
        f"Total calls: {overall_calls} "
        f"(W21 target ≥ {TARGET_TOTAL_CALLS_W21}; W41 target ≥ {TARGET_TOTAL_CALLS})",
        "",
        "## Headline metrics (W41 gates)",
        "",
        f"- **citation_rate**:  {citation_rate * 100:.2f}% "
        f"(target ≥ {targets_w41['citation_rate'] * 100:.0f}% — {gates_w41['citation_rate']})",
        f"- **top_share**:      {top_share * 100:.2f}% "
        f"(target ≥ {targets_w41['top_share'] * 100:.0f}% — {gates_w41['top_share']})",
        f"- **verified_share** (verified / mentions): {verified_of_mentions * 100:.2f}% "
        f"(target ≥ {targets_w41['verified_share'] * 100:.0f}% — {gates_w41['verified_share']})",
        f"- **verified / calls**: {verified_share * 100:.2f}% (raw — for trend comparison)",
        "",
        "## By surface",
        "",
        "| surface | calls | errors | fallback | citation_rate | top_share | verified_share |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    # Surface ordering: keep W21 baseline first (in SURFACES_DEFAULT order),
    # then the W41 grow surfaces, then any unknown surfaces alphabetical.
    ordered_surfaces: list[str] = []
    for s in SURFACES_DEFAULT:
        if s in by_surface:
            ordered_surfaces.append(s)
    for s in sorted(by_surface.keys()):
        if s not in ordered_surfaces:
            ordered_surfaces.append(s)
    for surface in ordered_surfaces:
        s = by_surface[surface]
        calls = s["calls"] or 1
        lines.append(
            f"| {surface} | {s['calls']} | {s['errors']} | {s['fallback']} | "
            f"{s['mentions']/calls*100:.1f}% | {s['first']/calls*100:.1f}% | "
            f"{s['verified']/calls*100:.1f}% |"
        )
    lines += [
        "",
        "## By category",
        "",
        "| category | calls | citation_rate | top_share | verified_share |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for cat, c in sorted(by_category.items()):
        calls = c["calls"] or 1
        lines.append(
            f"| {cat} | {c['calls']} | "
            f"{c['mentions']/calls*100:.1f}% | {c['first']/calls*100:.1f}% | "
            f"{c['verified']/calls*100:.1f}% |"
        )
    lines.append("")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # --- W41 dashboard JSON snapshot ---
    # Emit a structured JSON next to the report so the AEO dashboard (and
    # any agent-readable consumer) can render the 12-LLM × 4-metric heatmap
    # without re-walking the JSONL.
    dashboard_json = report_dir / f"citation_bench_production_w{wave}.json"
    snapshot = {
        "wave": wave,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_jsonl": str(jsonl_path),
        "total_calls": overall_calls,
        "target_total_calls_w21": TARGET_TOTAL_CALLS_W21,
        "target_total_calls_w41": TARGET_TOTAL_CALLS,
        "targets_w41": targets_w41,
        "gates_w41": gates_w41,
        "headline": {
            "citation_rate": citation_rate,
            "top_share": top_share,
            "verified_share": verified_of_mentions,
            "verified_per_call": verified_share,
        },
        "by_surface": {
            surface: {
                "calls": s["calls"],
                "errors": s["errors"],
                "fallback": s.get("fallback", 0),
                "citation_rate": s["mentions"] / (s["calls"] or 1),
                "top_share": s["first"] / (s["calls"] or 1),
                "verified_share": s["verified"] / (s["calls"] or 1),
            }
            for surface, s in by_surface.items()
        },
        "by_category": {
            cat: {
                "calls": c["calls"],
                "citation_rate": c["mentions"] / (c["calls"] or 1),
                "top_share": c["first"] / (c["calls"] or 1),
                "verified_share": c["verified"] / (c["calls"] or 1),
            }
            for cat, c in by_category.items()
        },
    }
    dashboard_json.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"[bench] aggregate → {report_path}")
    print(f"[bench] dashboard snapshot → {dashboard_json}")
    return report_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--wave", type=int, required=True)
    parser.add_argument("--questions", type=pathlib.Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--surfaces", default=",".join(SURFACES_DEFAULT))
    parser.add_argument("--target-questions", type=int, default=520)
    parser.add_argument("--max-tokens", type=int, default=800)
    parser.add_argument("--out-dir", type=pathlib.Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-dir", type=pathlib.Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--aggregate-only", action="store_true")
    parser.add_argument("--jsonl", type=pathlib.Path, default=None)
    parser.add_argument(
        "--sleep-ms",
        type=int,
        default=200,
        help="Sleep between LLM calls to avoid rate-limit clutter.",
    )
    args = parser.parse_args(argv)

    surfaces = [s.strip() for s in args.surfaces.split(",") if s.strip()]
    unknown = [s for s in surfaces if s not in SURFACE_TABLE]
    if unknown:
        print(f"[bench] unknown surfaces: {unknown}", file=sys.stderr)
        return 2

    if args.aggregate_only:
        jsonl = args.jsonl or (args.out_dir / f"citation_bench_production_w{args.wave}.jsonl")
        if not jsonl.exists():
            print(f"[bench] jsonl not found: {jsonl}", file=sys.stderr)
            return 2
        aggregate(jsonl, args.wave, args.report_dir)
        return 0

    questions = load_questions(args.questions, args.target_questions)
    jsonl_path = run_bench(
        wave=args.wave,
        questions=questions,
        surfaces=surfaces,
        max_tokens=args.max_tokens,
        out_dir=args.out_dir,
        dry_run=args.dry_run,
        sleep_ms=args.sleep_ms,
    )
    aggregate(jsonl_path, args.wave, args.report_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
