#!/usr/bin/env python3
"""URL integrity scan for jpintel-mcp registry.

Read-only scan over `data/jpintel.db` (table ``programs``). Extracts every
URL-shaped value that we expose to paying customers — ``source_url``,
``official_url``, nested URLs inside ``enriched_json``, and URL-shaped values
inside ``source_mentions_json`` — and flags entries that point at synthetic,
placeholder, loopback, or obviously malformed origins.

Rationale (see ``research/data_quality_report.md``): even one fabricated URL
(e.g. ``https://www.example.com/...``) constitutes 不当表示 under 景品表示法
4/5 条 when shown to paying users. This check is a launch gate; it is expected
to exit 0 for a clean DB and 1 the moment any offending row creeps back in.

Outputs:
- Markdown report at ``research/url_integrity_scan_{YYYY-MM-DD}.md`` with a
  per-URL table and a per-reason rollup. When the violation count is large
  (> 100) the per-URL table is split by reason and capped per section; the
  full JSON side-car is written alongside for downstream tooling.
- Exit code 0 when no violations are found, 1 otherwise.

Usage::

    python scripts/url_integrity_scan.py [--db PATH] [--report PATH] [--json PATH]

The scan opens the DB in read-only mode (``mode=ro``) and performs no writes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(REPO_ROOT, "data", "jpintel.db")
DEFAULT_REPORT_DIR = os.path.join(REPO_ROOT, "research")

# ---------------------------------------------------------------------------
# Rule definitions
# ---------------------------------------------------------------------------

# Hostnames that cannot serve real content to customers.
SYNTHETIC_HOSTS: frozenset[str] = frozenset({
    "example.com",
    "example.jp",
    "example.org",
    "example.net",
    "localhost",
    "test.com",
    "test.jp",
})

# Explicit sentinel IPs (loopback / unspecified / link-local broadcast).
SENTINEL_IPS: frozenset[str] = frozenset({
    "127.0.0.1",
    "0.0.0.0",
    "::1",
})

# Tokens that scream "unfilled placeholder" regardless of surrounding text.
PLACEHOLDER_TOKENS: tuple[str, ...] = ("TODO", "FIXME", "XXXX", "...", "…")

# URL extractor: captures http(s) URLs from arbitrary string values. We stop
# at whitespace, quotes, and common JSON terminators so the match stays
# conservative — false negatives are acceptable for a gate, false positives
# are not.
URL_RE = re.compile(r"""https?://[^\s"'<>)\]}，、]+""", re.IGNORECASE)

# Columns scanned. Keep ordering deterministic for reproducible reports.
COLUMNS: tuple[str, ...] = (
    "source_url",
    "official_url",
    "enriched_json",
    "source_mentions_json",
)

# When the per-URL table exceeds this cap we switch to grouped output.
PAGINATE_THRESHOLD = 100
PER_REASON_CAP = 50


# ---------------------------------------------------------------------------
# URL classification
# ---------------------------------------------------------------------------


def _strip_trailing_junk(url: str) -> str:
    """Trim trailing punctuation that commonly sticks to URLs in free text."""
    return url.rstrip(".,;:!?)]}>\"'")


def _is_private_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_unspecified
        or ip.is_link_local
    )


def classify_url(url: str) -> list[str]:
    """Return a list of violation reasons for *url*; empty list means clean.

    The function is intentionally strict — any ambiguous case earns a reason.
    Downstream consumers can choose whether to treat an advisory reason as a
    hard failure, but the scan script fails on any non-empty reason list.
    """
    if not isinstance(url, str) or not url:
        return ["empty or non-string value"]

    reasons: list[str] = []

    # Placeholder tokens short-circuit further analysis — we never trust
    # a URL containing an obvious "fill me in" marker.
    for token in PLACEHOLDER_TOKENS:
        if token in url:
            reasons.append(f"placeholder token {token!r}")

    try:
        parsed = urlparse(url)
    except Exception as exc:  # extremely narrow, urlparse almost never raises
        reasons.append(f"unparseable URL: {exc}")
        return reasons

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        reasons.append(f"non-http scheme ({scheme or 'missing'})")
        return reasons

    # ``parsed.hostname`` does its own lowercasing / IDN-ish handling but
    # throws on malformed netlocs (fullwidth slash, etc.). Guard for that.
    try:
        host = (parsed.hostname or "").lower()
    except Exception as exc:
        reasons.append(f"malformed netloc: {exc}")
        return reasons

    if not host:
        reasons.append("missing host")
        return reasons

    if host in SYNTHETIC_HOSTS or any(
        host == base or host.endswith("." + base) for base in SYNTHETIC_HOSTS
    ):
        reasons.append(f"synthetic host ({host})")

    if host in SENTINEL_IPS:
        reasons.append(f"loopback/unspecified ip ({host})")
    elif _is_private_ip(host):
        reasons.append(f"private ip range ({host})")

    # "no TLD" catches single-label hosts like ``w`` (truncated) or ``test``.
    if "." not in host and host not in SENTINEL_IPS and not _is_private_ip(host):
        reasons.append(f"no TLD in host ({host})")

    # ``test.*`` subdomains, or ``*.test`` pseudo-TLD, or bare "test".
    if host.startswith("test.") or host.endswith(".test") or host == "test":
        reasons.append(f"test hostname ({host})")

    return reasons


# ---------------------------------------------------------------------------
# URL extraction from nested JSON blobs
# ---------------------------------------------------------------------------


def iter_urls_in_value(value: Any) -> Iterator[str]:
    """Yield every URL-shaped substring embedded in *value* (recursively)."""
    if isinstance(value, dict):
        for v in value.values():
            yield from iter_urls_in_value(v)
        return
    if isinstance(value, list):
        for v in value:
            yield from iter_urls_in_value(v)
        return
    if isinstance(value, str):
        for match in URL_RE.findall(value):
            yield _strip_trailing_junk(match)
        return
    # Non-string scalars (bool/int/None/float) carry no URLs.


def iter_urls_in_column(raw: str | None) -> Iterator[str]:
    """Yield URLs from a text column that may or may not contain JSON."""
    if not raw:
        return
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        for match in URL_RE.findall(raw):
            yield _strip_trailing_junk(match)
        return
    yield from iter_urls_in_value(payload)


# ---------------------------------------------------------------------------
# Scan driver
# ---------------------------------------------------------------------------


def scan(db_path: str) -> tuple[list[dict[str, str]], int]:
    """Scan *db_path* and return (flagged rows, total programs scanned)."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(
            f"Database not found at {db_path}. "
            "Hint: run scripts/bootstrap_db.sh or restore from backup."
        )

    uri = f"file:{db_path}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    try:
        total = con.execute("SELECT COUNT(*) FROM programs").fetchone()[0]
        cur = con.execute(
            "SELECT unified_id, source_url, official_url, enriched_json, "
            "source_mentions_json FROM programs"
        )
        flagged: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for row in cur:
            unified_id = row["unified_id"]
            for col in COLUMNS:
                value = row[col]
                if value is None:
                    continue
                if col in ("source_url", "official_url"):
                    # Empty strings are a separate "missing source_url"
                    # concern tracked by the data quality audit (WARN, not
                    # FAIL). This scan only cares about *present* URLs that
                    # happen to be fabricated.
                    value_str = value.strip() if isinstance(value, str) else ""
                    if not value_str:
                        continue
                    urls = [value_str]
                else:
                    urls = list(iter_urls_in_column(value))
                for url in urls:
                    reasons = classify_url(url)
                    if not reasons:
                        continue
                    key = (unified_id, col, url)
                    if key in seen:
                        continue
                    seen.add(key)
                    flagged.append({
                        "unified_id": unified_id,
                        "column": col,
                        "url": url,
                        "reason": "; ".join(reasons),
                    })
    finally:
        con.close()
    return flagged, total


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def _md_escape(cell: str) -> str:
    return cell.replace("|", "\\|").replace("\n", " ")


def _md_table(headers: list[str], rows: list[tuple[str, ...]]) -> str:
    if not rows:
        return "(none)"
    out = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for r in rows:
        out.append("| " + " | ".join(_md_escape(str(c)) for c in r) + " |")
    return "\n".join(out)


def _primary_reason(reason: str) -> str:
    """Extract the first reason token for grouping (strip parenthesised host)."""
    head = reason.split(";")[0].strip()
    # Collapse parameterised reasons (e.g. "synthetic host (foo)") so the
    # bucket key stays stable across hosts.
    return re.sub(r"\s*\(.*\)$", "", head)


def render_report(
    flagged: list[dict[str, str]],
    total_programs: int,
    db_path: str,
) -> str:
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    reason_counter: Counter[str] = Counter(
        _primary_reason(row["reason"]) for row in flagged
    )
    column_counter: Counter[str] = Counter(row["column"] for row in flagged)

    lines: list[str] = []
    lines.append("# URL integrity scan — jpintel-mcp registry")
    lines.append("")
    lines.append(f"生成日時: {now}")
    lines.append(f"DB: `{db_path}`")
    lines.append(f"プログラム総数: **{total_programs}**")
    lines.append(f"違反 URL 件数 (unified_id × column × url): **{len(flagged)}**")
    lines.append("")
    lines.append("## 判定 (Verdict)")
    lines.append("")
    if not flagged:
        lines.append(
            "**PASS** — No synthetic, placeholder, loopback, or malformed "
            "URLs were detected. 景品表示法 4/5 条 の URL 表示要件を満たす。"
        )
    else:
        lines.append(
            f"**FAIL** — {len(flagged)} URL(s) violate the integrity "
            "invariants (see `docs/data_integrity.md`). 本番公開前に修正必須。"
        )
    lines.append("")

    lines.append("## Reason rollup")
    lines.append("")
    if reason_counter:
        lines.append(_md_table(
            ["reason", "count"],
            sorted(reason_counter.items(), key=lambda kv: (-kv[1], kv[0])),
        ))
    else:
        lines.append("(none)")
    lines.append("")

    lines.append("## Column rollup")
    lines.append("")
    if column_counter:
        lines.append(_md_table(
            ["column", "count"],
            sorted(column_counter.items(), key=lambda kv: (-kv[1], kv[0])),
        ))
    else:
        lines.append("(none)")
    lines.append("")

    lines.append("## Violations")
    lines.append("")
    if not flagged:
        lines.append("(none)")
    elif len(flagged) <= PAGINATE_THRESHOLD:
        lines.append(_md_table(
            ["unified_id", "column", "url", "reason"],
            [(r["unified_id"], r["column"], r["url"], r["reason"])
             for r in flagged],
        ))
    else:
        lines.append(
            f"> Total {len(flagged)} violations exceed the "
            f"{PAGINATE_THRESHOLD}-row inline cap. Grouped by primary reason "
            f"below (up to {PER_REASON_CAP} rows per group); the full list "
            "is available in the JSON side-car written next to this report."
        )
        lines.append("")
        buckets: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in flagged:
            buckets[_primary_reason(row["reason"])].append(row)
        for reason, rows in sorted(
            buckets.items(), key=lambda kv: (-len(kv[1]), kv[0])
        ):
            lines.append(f"### {reason} — {len(rows)}")
            lines.append("")
            shown = rows[:PER_REASON_CAP]
            lines.append(_md_table(
                ["unified_id", "column", "url", "reason"],
                [(r["unified_id"], r["column"], r["url"], r["reason"])
                 for r in shown],
            ))
            if len(rows) > PER_REASON_CAP:
                lines.append("")
                lines.append(
                    f"…(+{len(rows) - PER_REASON_CAP} more in JSON side-car)"
                )
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "Scan is read-only (sqlite3 ``mode=ro``). No rows were modified. "
        "See `docs/data_integrity.md` for remediation playbook."
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _default_report_path() -> str:
    today = dt.date.today().isoformat()
    return os.path.join(DEFAULT_REPORT_DIR, f"url_integrity_scan_{today}.md")


def run(
    db_path: str,
    report_path: str | None,
    json_path: str | None,
) -> int:
    flagged, total = scan(db_path)
    report = render_report(flagged, total, db_path)

    if report_path:
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(report)

    # Always emit the JSON side-car when there are violations so paginated
    # reports do not lose fidelity; emit on clean runs too for traceability.
    if json_path is None and report_path:
        json_path = report_path.rsplit(".", 1)[0] + ".json"
    if json_path:
        os.makedirs(os.path.dirname(json_path), exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "generated_at": dt.datetime.now(
                        dt.UTC
                    ).isoformat(timespec="seconds"),
                    "db_path": db_path,
                    "total_programs": total,
                    "violation_count": len(flagged),
                    "violations": flagged,
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )

    # CLI summary — keep tight so CI logs stay readable.
    print(f"url_integrity_scan — scanned {total} programs")
    print(f"violations: {len(flagged)}")
    if flagged:
        by_reason: Counter[str] = Counter(
            _primary_reason(r["reason"]) for r in flagged
        )
        for reason, count in by_reason.most_common():
            print(f"  {count:>4}  {reason}")
    if report_path:
        print(f"report: {report_path}")
    if json_path:
        print(f"json:   {json_path}")

    return 1 if flagged else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--db",
        default=DEFAULT_DB,
        help=f"Path to sqlite DB (default: {DEFAULT_DB}).",
    )
    ap.add_argument(
        "--report",
        default=_default_report_path(),
        help=(
            "Path to write Markdown report (default: "
            "research/url_integrity_scan_YYYY-MM-DD.md). Pass '' to skip."
        ),
    )
    ap.add_argument(
        "--json",
        default=None,
        help=(
            "Path to write JSON side-car (default: derive from --report). "
            "Pass '' to skip."
        ),
    )
    args = ap.parse_args(argv)
    report = args.report if args.report else None
    json_out = None if args.json == "" else args.json
    return run(args.db, report, json_out)


if __name__ == "__main__":
    sys.exit(main())
