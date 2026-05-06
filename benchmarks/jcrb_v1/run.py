"""JCRB-v1 runner.

Customer-side CLI. Iterates ``questions.jsonl``, calls the chosen LLM
provider, writes a ``predictions.jsonl`` of ``{id, output}`` rows, then
optionally invokes ``scoring.py`` to compute per-domain accuracy.

This script is INTENDED to be run on customer hardware (or CI) — NOT on
the jpcite operator boxes. The operator never invokes an LLM provider
(see CLAUDE.md "What NOT to do"). The only operator-side script in this
benchmark is ``scripts/cron/jcrb_publish_results.py`` which receives
customer-posted result JSON and writes ``site/benchmark/results.json``
without making any LLM call.

Two execution modes:

* ``--mode without_jpcite``  (closed-book / vanilla provider call)
* ``--mode with_jpcite``     (provider call augmented by jpcite REST API
                              search context. Customer pays the jpcite
                              ¥3/req metering for each question.)

Provider plugins are HTTP-only. We intentionally do NOT import
``anthropic`` / ``openai`` / ``google.generativeai`` SDKs so the runner
stays installable with just ``httpx``. Submitters can swap their own
plugin via ``--provider-cmd "python my_runner.py"`` (the runner shells
out to that command, passing the question on stdin and reading output
from stdout).

Usage:

    python benchmarks/jcrb_v1/run.py \\
        --provider claude --model claude-opus-4-7 \\
        --mode without_jpcite \\
        --out predictions/claude_opus_47_without.jsonl

    python benchmarks/jcrb_v1/scoring.py \\
        --predictions predictions/claude_opus_47_without.jsonl \\
        --out reports/claude_opus_47_without

The runner DOES NOT score. Scoring is decoupled so anyone can re-grade
the same predictions.jsonl against an updated questions.jsonl without
re-paying for inference.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover - optional dependency
    httpx = None  # type: ignore[assignment]

DEFAULT_QUESTIONS = pathlib.Path(__file__).parent / "questions.jsonl"
SYSTEM_PROMPT = (
    "あなたは日本の公的制度 (補助金・税制・法令・行政処分) に詳しいアシスタントです。"
    "質問に対し、(1) 結論となる事実 (上限額・条文・日付など) を1文で答え、"
    "(2) 根拠となる一次資料 URL を必ず1つ以上引用してください。"
    "推測した URL ではなく、実在する政府サイト (go.jp / e-gov.go.jp など) の URL のみを引用してください。"
    "わからない場合は『情報なし』と答え、URL を捏造しないでください。"
)
JPCITE_API_BASE = os.environ.get("JPCITE_API_BASE", "https://api.jpcite.com")


# ---------------------------------------------------------------------------
# Provider HTTP plugins (no SDK imports — keeps runner dep-light)
# ---------------------------------------------------------------------------


def _require_httpx() -> None:
    if httpx is None:
        raise RuntimeError("httpx is required. pip install httpx")


def _call_anthropic(model: str, system: str, prompt: str) -> str:
    _require_httpx()
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    r = httpx.post(  # type: ignore[union-attr]
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60.0,
    )
    r.raise_for_status()
    blocks = r.json().get("content", [])
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def _call_openai(model: str, system: str, prompt: str) -> str:
    _require_httpx()
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set")
    r = httpx.post(  # type: ignore[union-attr]
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 1024,
        },
        timeout=60.0,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _call_gemini(model: str, system: str, prompt: str) -> str:
    _require_httpx()
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    r = httpx.post(  # type: ignore[union-attr]
        url,
        json={
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 1024},
        },
        timeout=60.0,
    )
    r.raise_for_status()
    cand = r.json().get("candidates", [{}])[0]
    parts = cand.get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts)


def _call_shell(cmd: str, system: str, prompt: str) -> str:
    """Generic stdin/stdout plugin: customer can wrap any model."""
    payload = json.dumps({"system": system, "prompt": prompt}, ensure_ascii=False)
    p = subprocess.run(
        cmd, shell=True, input=payload, capture_output=True, text=True, check=True, timeout=120,
    )
    return p.stdout


PROVIDERS = {
    "claude": _call_anthropic,
    "openai": _call_openai,
    "gemini": _call_gemini,
}


# ---------------------------------------------------------------------------
# jpcite augmentation
# ---------------------------------------------------------------------------


def _jpcite_context(question: str, api_key: str | None) -> str:
    """Hit jpcite REST search and return a compact context block.

    The customer pays ¥3/req per call. If ``--mode without_jpcite`` the
    runner skips this entirely (closed-book baseline).
    """
    _require_httpx()
    headers = {"accept": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    try:
        r = httpx.get(  # type: ignore[union-attr]
            f"{JPCITE_API_BASE}/v1/search",
            params={"q": question, "limit": 5},
            headers=headers,
            timeout=15.0,
        )
        r.raise_for_status()
        hits = r.json().get("results", [])[:5]
    except Exception as e:  # noqa: BLE001 — network failure is non-fatal
        return f"[jpcite context unavailable: {e}]"
    lines = ["[jpcite primary-source context]"]
    for i, h in enumerate(hits, 1):
        name = h.get("primary_name") or h.get("name") or h.get("title") or h.get("ruleset_name") or ""
        url = h.get("source_url") or h.get("official_url") or h.get("url") or ""
        lines.append(f"{i}. {name} — {url}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def _iter_questions(path: pathlib.Path):
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        yield json.loads(line)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run JCRB-v1 against an LLM provider.")
    p.add_argument("--questions", type=pathlib.Path, default=DEFAULT_QUESTIONS)
    p.add_argument("--provider", choices=list(PROVIDERS) + ["shell"], required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--mode", choices=["without_jpcite", "with_jpcite"], default="without_jpcite")
    p.add_argument("--out", type=pathlib.Path, required=True)
    p.add_argument("--jpcite-api-key", default=os.environ.get("JPCITE_API_KEY"))
    p.add_argument("--provider-cmd", default=None,
                   help="When --provider shell, the command to invoke (stdin=JSON, stdout=text)")
    p.add_argument("--limit", type=int, default=None, help="Run only first N questions (debug)")
    p.add_argument("--sleep-s", type=float, default=0.5, help="Delay between requests")
    args = p.parse_args(argv)

    args.out.parent.mkdir(parents=True, exist_ok=True)

    if args.provider == "shell":
        if not args.provider_cmd:
            p.error("--provider shell requires --provider-cmd")
        caller = lambda sysmsg, prm: _call_shell(args.provider_cmd, sysmsg, prm)  # noqa: E731
    else:
        fn = PROVIDERS[args.provider]
        caller = lambda sysmsg, prm: fn(args.model, sysmsg, prm)  # noqa: E731

    n = 0
    with args.out.open("w", encoding="utf-8") as fout:
        for q in _iter_questions(args.questions):
            if args.limit is not None and n >= args.limit:
                break
            qtext = q["question"]
            if args.mode == "with_jpcite":
                ctx = _jpcite_context(qtext, args.jpcite_api_key)
                prompt = f"{ctx}\n\n質問: {qtext}"
            else:
                prompt = qtext
            t0 = time.time()
            try:
                output = caller(SYSTEM_PROMPT, prompt)
                err = None
            except Exception as e:  # noqa: BLE001 — record errors, keep going
                output = ""
                err = str(e)
            elapsed = round(time.time() - t0, 3)
            row: dict[str, Any] = {
                "id": q["id"],
                "domain": q["domain"],
                "mode": args.mode,
                "provider": args.provider,
                "model": args.model,
                "output": output,
                "elapsed_s": elapsed,
            }
            if err:
                row["error"] = err
            fout.write(json.dumps(row, ensure_ascii=False) + "\n")
            fout.flush()
            n += 1
            print(f"[{n:3d}] {q['id']} {elapsed}s {'ERR' if err else 'ok'}", file=sys.stderr)
            if args.sleep_s:
                time.sleep(args.sleep_s)

    print(f"wrote {n} predictions to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
