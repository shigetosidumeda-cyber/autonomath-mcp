#!/usr/bin/env python3
"""Regenerate site/llms-full.txt with a compact program inventory appended.

Inputs:
  - data/jpintel.db  (programs table, source of truth for the FastAPI API)
  - site/llms-full.txt  (existing docs-heavy file; preserved verbatim above section)

Output (atomic write):
  - site/llms-full.txt  (preserved docs + ## All Programs (compact) section)

The compact section is a pipe-delimited inventory of every active program
(`excluded = 0` AND `tier IN ('S','A','B','C')`, matching the production search
filter; non-public rows stay excluded). It exists
so LLM crawlers (GPTBot, ClaudeBot, PerplexityBot, etc.) can ingest the full
program list without scraping 9,998 individual HTML pages.

Compact line format (UTF-8, LF):
  <unified_id> | <primary_name> | <program_kind> | <amount_max_man_yen> | <source_url> | <source_fetched_at>

Idempotent: re-running replaces the prior `## All Programs` block (and
everything below it) with a freshly queried block. Anything *above* the marker
stays intact, so docs edits in CI/manual concat are preserved.

CLI:
    uv run python scripts/regen_llms_full.py
    uv run python scripts/regen_llms_full.py --db data/jpintel.db --out site/llms-full.txt
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

try:
    from static_bad_urls import load_static_bad_urls  # type: ignore
except ImportError:  # pragma: no cover

    def load_static_bad_urls() -> set[str]:
        return set()


# Marker that delimits the auto-generated compact section. Anything from this
# line onward is regenerated each run; everything above is preserved.
SECTION_MARKER = "## All Programs"
_PUBLIC_ID_PREFIX_RE = re.compile(r"^(?:MUN-\d{2,6}-\d{3}|PREF-\d{2,6}-\d{3})[_\s]+")

# SQL filter: non-public rows and excluded=1 rows stay out of outputs.
# Both must stay out of any user-facing surface (CLAUDE.md non-negotiable).
_BANNED_SOURCE_HOSTS = frozenset(
    {
        "smart-hojokin.jp",
        "noukaweb.jp",
        "noukaweb.com",
        "hojyokin-portal.jp",
        "hojokin-portal.jp",
        "biz.stayway.jp",
        "biz-stayway.jp",
        "stayway.jp",
        "subsidymap.jp",
        "navit-j.com",
        "hojyokin.jp",
        "hojokin.jp",
        "creabiz.co.jp",
        "yorisoi.jp",
        "aichihojokin.com",
        "activation-service.jp",
        "jsearch.jp",
        "judgit.net",
        "news.mynavi.jp",
        "news.yahoo.co.jp",
        "shien-39.jp",
        "tamemap.net",
        "tokyo-np.co.jp",
        "yayoi-kk.co.jp",
        "jiji.com",
    }
)

PROGRAMS_SQL = """
SELECT
    unified_id,
    primary_name,
    COALESCE(program_kind, '') AS program_kind,
    COALESCE(amount_max_man_yen, 0) AS amount_max_man_yen,
    COALESCE(source_url, '') AS source_url,
    COALESCE(source_fetched_at, '') AS source_fetched_at
FROM programs
WHERE excluded = 0
  AND tier IN ('S', 'A', 'B', 'C')
  AND COALESCE(source_url_status, '') NOT IN ('broken', 'dead')
  AND COALESCE(source_last_check_status, 0) NOT IN (403, 404, 410)
ORDER BY tier, primary_name
LIMIT 20000
"""


def _source_host_allowed(source_url: str | None) -> bool:
    if not source_url:
        return True
    try:
        hostname = urlparse(str(source_url).strip()).hostname
    except ValueError:
        return True
    if not hostname:
        return True
    host = hostname.lower().rstrip(".")
    return not any(host == banned or host.endswith(f".{banned}") for banned in _BANNED_SOURCE_HOSTS)


def _sanitize(value: str) -> str:
    """Strip characters that would break the pipe-delimited line format.

    Removes embedded `|`, CR, LF and tabs; collapses inner whitespace runs.
    Returns an empty string for None.
    """
    if value is None:
        return ""
    s = str(value)
    for bad in ("\r\n", "\r", "\n", "\t", "|"):
        s = s.replace(bad, " ")
    # Collapse runs of whitespace that the substitutions may have introduced.
    return " ".join(s.split())


def _public_program_name(value: str | None) -> str:
    return _PUBLIC_ID_PREFIX_RE.sub("", _sanitize(value or ""))


def _format_amount(amount: float | int | None) -> str:
    """Format amount_max_man_yen as integer when whole, else as float."""
    if amount is None:
        return "0"
    try:
        f = float(amount)
    except (TypeError, ValueError):
        return "0"
    if f == int(f):
        return str(int(f))
    # Trim trailing zeros while keeping a single decimal place when meaningful.
    return f"{f:g}"


def fetch_programs(db_path: Path) -> list[sqlite3.Row]:
    if not db_path.exists():
        msg = f"db not found: {db_path}"
        raise FileNotFoundError(msg)
    # Read-only via URI to avoid accidental writes.
    uri = f"file:{db_path}?mode=ro"
    with sqlite3.connect(uri, uri=True) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(PROGRAMS_SQL).fetchall()
    denied = load_static_bad_urls()
    return [
        row
        for row in rows
        if _source_host_allowed(row["source_url"]) and row["source_url"] not in denied
    ]


def build_compact_section(rows: list[sqlite3.Row]) -> str:
    """Render the ## All Programs (compact) block as a single string."""
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    count = len(rows)

    lines: list[str] = []
    lines.append(f"{SECTION_MARKER} ({count:,} normalized LLM-index program rows, compact)")
    lines.append("")
    lines.append("Generated daily from the current public jpcite dataset.")
    lines.append(f"Generated at: {generated_at}.")
    lines.append(
        "Format: <unified_id> | <primary_name> | <program_kind> | "
        "<amount_max_man_yen> | <source_url> | <source_fetched_at>"
    )
    lines.append(
        "amount_max_man_yen is denominated in 万円 (10,000 JPY); 0 means unspecified or none."
    )
    lines.append("")

    for row in rows:
        line = " | ".join(
            [
                _sanitize(row["unified_id"]),
                _public_program_name(row["primary_name"]),
                _sanitize(row["program_kind"]),
                _format_amount(row["amount_max_man_yen"]),
                _sanitize(row["source_url"]),
                _sanitize(row["source_fetched_at"]),
            ]
        )
        lines.append(line)

    lines.append("")
    return "\n".join(lines)


def split_existing(text: str) -> str:
    """Return the prefix of `text` up to (but not including) the section marker.

    If the marker is not present, return the full text plus a trailing newline
    so the new section starts on its own block. Preserves any trailing
    whitespace normalization the source file had.
    """
    idx = text.find(f"\n{SECTION_MARKER}")
    if idx == -1:
        # First-run mode: append cleanly with one blank line between.
        if not text.endswith("\n"):
            text += "\n"
        if not text.endswith("\n\n"):
            text += "\n"
        return _sanitize_preserved_prefix(text)
    # Trim trailing whitespace from the kept prefix and re-add a single blank line.
    prefix = text[: idx + 1].rstrip() + "\n\n"
    return _sanitize_preserved_prefix(prefix)


def _sanitize_preserved_prefix(prefix: str) -> str:
    replacements = {
        "認証済み呼び出し (有効な API key 付き) はこの IP 制限を完全にバイパスし、metered 課金 (¥3/req 税別、上限なし) が適用される。": "認証済み呼び出し (有効な API key 付き) は匿名 IP 制限とは別に扱われます。従量課金は税別 ¥3/billable unit で、月次予算 cap、保護レート制限、異常バースト時の制御が適用される場合があります。",
        "| Paid (metered) | 上限なし | Stripe 従量、¥3/req 税別 (税込 ¥3.30) |": "| Paid (metered) | 利用量に応じて課金 | Stripe 従量、¥3/billable unit 税別 (税込 ¥3.30)。月次予算 cap と保護レート制限を設定可能 |",
        "Paid は cap なし (スパイクでも 429 は返らない)。": "認証済み利用でも、月次予算 cap、保護レート制限、異常バースト時の制御が適用される場合があります。",
        "- **bulk 再配布 (データセット販売等):** 元データ自体は一次資料のため出典明記で再配布可能。自社サービスに組み込む場合は Paid (¥3/req 税別・税込 ¥3.30) で叩けば制限なし。": "- **bulk 再配布 (データセット販売等):** 出典ごとにライセンス条件が異なります。API 利用可否と再配布許諾は別です。各 record の `source_url` / `license` / attribution 条件を確認してください。",
        "- **MCP ネイティブ対応** — Claude Desktop / Cursor / ChatGPT (Plus 以降) から直接ツール呼び出し": "- **MCP ネイティブ対応** — Claude Desktop / Cursor / Cline など、ローカル stdio MCP サーバーを起動できるクライアントで利用可能。ChatGPT Custom GPT は OpenAPI Actions を使います。",
        "jpcite は MCP (Model Context Protocol) サーバーとして 96 ツール を公開する。Claude Desktop / Cursor / ChatGPT (Plus 以降) / Gemini から直接呼び出せる。": "jpcite は MCP (Model Context Protocol) サーバーとして 96 ツールを公開します。Claude Desktop / Cursor / Cline などの stdio MCP クライアントで使えます。ChatGPT Custom GPT は OpenAPI Actions を使います。",
        "- **ChatGPT:** Plus 以降 (2025-10+) で MCP 対応": "- **ChatGPT:** Custom GPT は OpenAPI Actions (`/v1/openapi.agent.json`) 経由。ChatGPT Apps / Developer Mode の remote MCP は、この stdio MCP package とは別です。",
        '"args": ["<mcp-server-command>"]': '"args": ["autonomath-mcp"]',
        "curl https://api.jpcite.com/meta": "curl https://api.jpcite.com/v1/meta",
        "`GET /meta`": "`GET /v1/meta`",
        "GET /meta": "GET /v1/meta",
        "`/healthz`, `/meta`, `/v1` prefix を持たない utility 系": "`/healthz`, `/v1/meta`, `/v1` prefix を持たない utility 系",
        "- `/meta` は aggregate stats (total_programs, last_updated 等) を返すが、field 追加・削除・意味変更が発生しうる": "- `/v1/meta` は公開検索対象の aggregate stats (total_programs, last_ingested_at 等) を返します",
        '"total_programs": 13578': '"total_programs": 11684',
        "[pricing.md](./pricing.md) — tier 別制限": "[pricing.md](./pricing.md) — 料金・匿名枠・従量課金条件",
        '"tier=X の理由が見えづらい"': '"検索対象外判定の理由が見えづらい"',
        "`/meta`, `/v1/ping`, `/v1/programs/*`, `/v1/exclusions/*`, `/v1/feedback`": "`/v1/meta`, `/v1/ping`, `/v1/programs/*`, `/v1/exclusions/*`, `/v1/feedback`",
        "- `GET /healthz` / `GET /meta` はカウント対象外": "- `GET /healthz` はカウント対象外。`GET /v1/meta` は discoverability 枠に含まれます。",
        "- **Stripe 経由で自動 revoke:** サブスクリプション解約時、webhook (`customer.subscription.deleted`) で自動的に `revoked_at` セット。": "- **解約時の停止:** 解約時に API key は停止されます。漏えい時の緊急停止はサポートへ連絡してください。",
    }
    for old, new in replacements.items():
        prefix = prefix.replace(old, new)
    prefix = prefix.replace("¥3/request", "¥3/billable unit")
    prefix = prefix.replace("¥3/req", "¥3/billable unit")
    prefix = prefix.replace("¥3 / request", "¥3/billable unit")
    prefix = prefix.replace("¥3 / req", "¥3/billable unit")
    prefix = prefix.replace(
        '"tier_counts": {"S": 46, "A": 468, "B": 3174, "C": 6310, "X": 1213}',
        '"tier_counts": {"S": 114, "A": 1340, "B": 4186, "C": 6044}',
    )
    prefix = prefix.replace(
        "**¥3 / billable unit 税別 (税込 ¥3.30)**",
        "**¥3/billable unit 税別 (税込 ¥3.30)**",
    )
    prefix = prefix.replace(
        "`search_programs` — discover by keyword + region + amount across 11,684 制度 "
        "(tier S/A/B/C). 一次資料 URL 付き. **Use first** for any 制度 query.",
        "`search_programs` — discover by keyword + region + amount across 11,684 制度 "
        "(tier S/A/B/C). 一次資料 URL 付き. 広い回答生成では先に "
        "`/v1/intelligence/precomputed/query`、実在する `unified_id` が必要な時に使う。",
    )
    prefix = re.sub(
        r"The five highest-leverage endpoints for agent flows: `GET /v1/programs/search`.*?"
        r"For repeated stdio access,",
        "The five highest-leverage endpoints for agent flows are evidence-first: "
        "`POST /v1/evidence/packets/query`, `GET /v1/intelligence/precomputed/query`, "
        "`GET /v1/programs/search`, `GET /v1/programs/{unified_id}`, and "
        "`GET /v1/source_manifest/{program_id}`. Search responses share a "
        "`{total, limit, offset, results[]}` shape. Published rows generally expose "
        "`source_url` + `source_fetched_at` so agents can cite sources directly. "
        "For repeated stdio access,",
        prefix,
        flags=re.DOTALL,
    )
    # The preserved docs prefix may come from an older generated snapshot.
    # Keep LLM crawler input aligned with the public OpenAPI surface even when
    # the compact inventory is regenerated without rebuilding the docs prefix.
    prefix = prefix.replace(
        "| `include_excluded` | bool | no | `true` で tier=X も含める (default `false`) |\n",
        "",
    )
    prefix = prefix.replace(
        "| `include_excluded` | bool | false | `true` で tier=X も含める |\n",
        "",
    )
    prefix = re.sub(
        r"\n### `POST /v1/billing/webhook`\n.*?\n---\n\n",
        "\n",
        prefix,
        flags=re.DOTALL,
    )
    prefix = prefix.replace(
        "`/healthz`, `/v1/billing/webhook`, `/v1/subscribers/unsubscribe`, dashboard 系",
        "`/healthz`, `/v1/subscribers/unsubscribe`, dashboard 系",
    )
    # Standalone site/structured/*.jsonld shards are not shipped in the
    # Cloudflare Pages bundle because the bundle must stay under the 20k-file
    # deployment limit. Keep crawler-facing llms-full aligned with deployed URLs.
    prefix = re.sub(
        r"\n## Section: Structured data strategy\n.*?(?=\n## All Programs|\Z)",
        "\n",
        prefix,
        flags=re.DOTALL,
    )
    return prefix


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        os.replace(tmp_name, path)
    except Exception:
        # Best-effort cleanup of the temp file if rename failed.
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/jpintel.db"),
        help="Path to jpintel.db (default: data/jpintel.db relative to cwd).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("site/llms-full.txt"),
        help="Path to llms-full.txt (default: site/llms-full.txt).",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=5 * 1024 * 1024,
        help="Refuse to write if the result exceeds this size (default: 5 MiB).",
    )
    args = parser.parse_args(argv)

    db_path: Path = args.db.resolve()
    out_path: Path = args.out.resolve()

    if not out_path.exists():
        sys.stderr.write(f"warn: out file does not exist, creating fresh at {out_path}\n")
        existing = ""
    else:
        existing = out_path.read_text(encoding="utf-8")

    rows = fetch_programs(db_path)
    if not rows:
        sys.stderr.write("warn: programs query returned 0 rows; aborting\n")
        return 2

    section = build_compact_section(rows)
    prefix = split_existing(existing)
    new_content = prefix + section

    new_bytes = new_content.encode("utf-8")
    if len(new_bytes) > args.max_bytes:
        sys.stderr.write(
            f"error: rendered file is {len(new_bytes):,} bytes, "
            f"exceeds --max-bytes={args.max_bytes:,}\n"
        )
        return 3

    atomic_write(out_path, new_content)

    sys.stdout.write(
        f"wrote {out_path} | rows={len(rows):,} | "
        f"bytes={len(new_bytes):,} | lines={new_content.count(chr(10)) + 1:,}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
