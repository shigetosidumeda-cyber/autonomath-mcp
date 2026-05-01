#!/usr/bin/env python3
"""Propose and optionally probe slash-flipped replacements for hard-404 URLs.

D7 is intentionally read-only: it can read liveness JSON/CSV or DB rows, then
materialize candidate ``old_url -> new_url`` rows for manual review.  It never
updates SQLite.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import time
import urllib.parse
import urllib.robotparser
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from collections.abc import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_OUTPUT = (
    REPO_ROOT / "analysis_wave18" / "url_slash_flip_recovery_2026-05-01.csv"
)
USER_AGENT = "AutonoMath-SlashFlipProbe/0.1 (+https://jpcite.com/bot)"
TIMEOUT_SEC = 15.0
PER_HOST_DELAY_SEC = 1.0

HARD_404_STATUSES = {"hard_404"}


@dataclass(frozen=True)
class LivenessRow:
    source_id: str
    old_url: str
    classification: str
    status_code: int | None = None
    primary_name: str = ""
    tier: str = ""
    source_table: str = ""
    source_field: str = ""


@dataclass(frozen=True)
class SlashFlipProposal:
    source_id: str
    primary_name: str
    tier: str
    source_table: str
    source_field: str
    old_url: str
    new_url: str
    transform: str
    reason: str = "slash_flip_candidate"


@dataclass(frozen=True)
class ProbeResult:
    source_id: str
    old_url: str
    new_url: str
    transform: str
    status_code: int | None
    final_url: str
    outcome: str
    method: str | None
    error: str = ""


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _source_id(row: dict[str, Any]) -> str:
    for key in ("source_id", "program_id", "unified_id", "id"):
        value = _text(row.get(key))
        if value:
            return value
    return ""


def _source_url(row: dict[str, Any]) -> str:
    for key in ("url", "source_url", "old_url"):
        value = _text(row.get(key))
        if value:
            return value
    return ""


def _classification(row: dict[str, Any]) -> str:
    for key in ("latest_classification", "classification", "outcome"):
        value = _text(row.get(key))
        if value:
            return value
    status_code = _int_or_none(row.get("status_code") or row.get("http_status"))
    return "hard_404" if status_code == 404 else ""


def _row_from_mapping(row: dict[str, Any]) -> LivenessRow | None:
    old_url = _source_url(row)
    if not old_url:
        return None
    return LivenessRow(
        source_id=_source_id(row),
        old_url=old_url,
        classification=_classification(row),
        status_code=_int_or_none(row.get("status_code") or row.get("http_status")),
        primary_name=_text(row.get("primary_name") or row.get("name")),
        tier=_text(row.get("tier")),
        source_table=_text(row.get("source_table")),
        source_field=_text(row.get("source_field") or "source_url"),
    )


def load_liveness_json(path: Path) -> list[LivenessRow]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        raw_rows = data.get("results", [])
    elif isinstance(data, list):
        raw_rows = data
    else:
        raise ValueError(f"unsupported JSON root in {path}")
    rows: list[LivenessRow] = []
    for raw in raw_rows:
        if isinstance(raw, dict):
            row = _row_from_mapping(raw)
            if row is not None:
                rows.append(row)
    return rows


def load_liveness_csv(path: Path) -> list[LivenessRow]:
    with path.open(encoding="utf-8", newline="") as f:
        return [
            row
            for raw in csv.DictReader(f)
            if (row := _row_from_mapping(dict(raw))) is not None
        ]


def load_db_rows(conn: sqlite3.Connection, *, limit: int | None = None) -> list[LivenessRow]:
    sql = (
        "SELECT unified_id AS source_id, primary_name, tier, source_url AS url, "
        "source_last_check_status AS status_code "
        "FROM programs "
        "WHERE source_url IS NOT NULL "
        "AND TRIM(source_url) != '' "
        "AND source_last_check_status = 404 "
        "ORDER BY unified_id"
    )
    if limit is not None and limit > 0:
        sql += f" LIMIT {int(limit)}"
    return [
        LivenessRow(
            source_id=_text(row["source_id"]),
            old_url=_text(row["url"]),
            classification="hard_404",
            status_code=_int_or_none(row["status_code"]),
            primary_name=_text(row["primary_name"]),
            tier=_text(row["tier"]),
            source_table="programs",
            source_field="source_url",
        )
        for row in conn.execute(sql).fetchall()
    ]


def slash_flip_url(url: str) -> tuple[str | None, str | None]:
    stripped = url.strip()
    if not stripped:
        return None, None
    try:
        parsed = urllib.parse.urlsplit(stripped)
    except ValueError:
        return None, None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None, None

    if parsed.path.endswith("/") and parsed.path != "/":
        new_path = parsed.path.rstrip("/")
        transform = "remove_trailing_slash"
    elif not parsed.path.endswith("/"):
        new_path = f"{parsed.path}/" if parsed.path else "/"
        transform = "add_trailing_slash"
    else:
        return None, None

    flipped = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, new_path, parsed.query, parsed.fragment)
    )
    if flipped == stripped:
        return None, None
    return flipped, transform


def collect_slash_flip_proposals(rows: Iterable[LivenessRow]) -> list[SlashFlipProposal]:
    materialized = list(rows)
    known_urls = {row.old_url.strip() for row in materialized if row.old_url.strip()}
    candidate_counts: Counter[str] = Counter()
    provisional: list[tuple[LivenessRow, str, str]] = []

    for row in materialized:
        if row.classification not in HARD_404_STATUSES:
            continue
        new_url, transform = slash_flip_url(row.old_url)
        if new_url is None or transform is None:
            continue
        if new_url in known_urls:
            continue
        candidate_counts[new_url] += 1
        provisional.append((row, new_url, transform))

    proposals: list[SlashFlipProposal] = []
    for row, new_url, transform in provisional:
        if candidate_counts[new_url] > 1:
            continue
        proposals.append(
            SlashFlipProposal(
                source_id=row.source_id,
                primary_name=row.primary_name,
                tier=row.tier,
                source_table=row.source_table,
                source_field=row.source_field,
                old_url=row.old_url,
                new_url=new_url,
                transform=transform,
            )
        )
    return proposals


class PoliteProber:
    def __init__(
        self,
        *,
        user_agent: str = USER_AGENT,
        per_host_delay_sec: float = PER_HOST_DELAY_SEC,
        timeout_sec: float = TIMEOUT_SEC,
        respect_robots: bool = True,
    ) -> None:
        self._ua = user_agent
        self._per_host_delay = per_host_delay_sec
        self._respect_robots = respect_robots
        self._host_clock: dict[str, float] = {}
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Language": "ja,en;q=0.5"},
            follow_redirects=True,
            timeout=timeout_sec,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PoliteProber:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _host_key(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        return f"{parsed.scheme or 'https'}://{host}"

    def _pace(self, url: str) -> None:
        key = self._host_key(url)
        now = time.monotonic()
        last = self._host_clock.get(key)
        if last is not None:
            wait = self._per_host_delay - (now - last)
            if wait > 0:
                time.sleep(wait)
        self._host_clock[key] = time.monotonic()

    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        key = self._host_key(url)
        if key in self._robots_cache:
            return self._robots_cache[key]
        robots_url = f"{key}/robots.txt"
        self._pace(robots_url)
        try:
            resp = self._client.get(robots_url, timeout=5.0)
            if resp.status_code == 200:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(resp.text.splitlines())
                self._robots_cache[key] = parser
                return parser
        except httpx.HTTPError:
            pass
        self._robots_cache[key] = None
        return None

    def _robots_allowed(self, url: str) -> bool:
        if not self._respect_robots:
            return True
        parser = self._robots_for(url)
        if parser is None:
            return True
        try:
            return parser.can_fetch(self._ua, url)
        except Exception:
            return True

    def _request(self, method: str, url: str) -> httpx.Response:
        self._pace(url)
        if method == "GET":
            return self._client.get(url, headers={"Range": "bytes=0-0"})
        return self._client.head(url)

    def probe(self, proposal: SlashFlipProposal) -> ProbeResult:
        if not self._robots_allowed(proposal.new_url):
            return ProbeResult(
                source_id=proposal.source_id,
                old_url=proposal.old_url,
                new_url=proposal.new_url,
                transform=proposal.transform,
                status_code=None,
                final_url=proposal.new_url,
                outcome="robots_disallow",
                method=None,
            )
        try:
            resp = self._request("HEAD", proposal.new_url)
            method = "HEAD"
            if resp.status_code in {405, 501}:
                resp = self._request("GET", proposal.new_url)
                method = "GET"
            return ProbeResult(
                source_id=proposal.source_id,
                old_url=proposal.old_url,
                new_url=proposal.new_url,
                transform=proposal.transform,
                status_code=resp.status_code,
                final_url=str(resp.url),
                outcome=classify_probe_status(resp.status_code),
                method=method,
            )
        except httpx.HTTPError as exc:
            return ProbeResult(
                source_id=proposal.source_id,
                old_url=proposal.old_url,
                new_url=proposal.new_url,
                transform=proposal.transform,
                status_code=None,
                final_url=proposal.new_url,
                outcome="transport_error",
                method="HEAD",
                error=f"{type(exc).__name__}: {exc}",
            )


def classify_probe_status(status_code: int) -> str:
    if 200 <= status_code < 300:
        return "ok"
    if 300 <= status_code < 400:
        return "redirect"
    if status_code == 404:
        return "hard_404"
    if 400 <= status_code < 500:
        return "client_error"
    if status_code >= 500:
        return "server_error"
    return "unknown"


def probe_proposals(
    proposals: Iterable[SlashFlipProposal],
    *,
    limit: int,
    prober: PoliteProber | None = None,
) -> list[ProbeResult]:
    bounded = list(proposals)[: max(0, limit)]
    if prober is not None:
        return [prober.probe(proposal) for proposal in bounded]
    with PoliteProber() as live_prober:
        return [live_prober.probe(proposal) for proposal in bounded]


def write_csv(
    path: Path,
    proposals: list[SlashFlipProposal],
    probe_results: list[ProbeResult] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    probe_by_key = {
        (result.source_id, result.old_url, result.new_url): result
        for result in probe_results or []
    }
    fieldnames = [
        "source_id",
        "primary_name",
        "tier",
        "source_table",
        "source_field",
        "old_url",
        "new_url",
        "transform",
        "reason",
        "probe_status_code",
        "probe_final_url",
        "probe_outcome",
        "probe_method",
        "probe_error",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for proposal in proposals:
            row = asdict(proposal)
            result = probe_by_key.get(
                (proposal.source_id, proposal.old_url, proposal.new_url)
            )
            row.update(
                {
                    "probe_status_code": result.status_code if result else "",
                    "probe_final_url": result.final_url if result else "",
                    "probe_outcome": result.outcome if result else "",
                    "probe_method": result.method if result else "",
                    "probe_error": result.error if result else "",
                }
            )
            writer.writerow(row)


def _connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def _load_inputs(args: argparse.Namespace) -> list[LivenessRow]:
    if args.json_input:
        return load_liveness_json(args.json_input)
    if args.csv_input:
        return load_liveness_csv(args.csv_input)
    with _connect(args.db) as conn:
        return load_db_rows(conn, limit=args.db_limit)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--json-input", type=Path)
    source.add_argument("--csv-input", type=Path)
    source.add_argument("--db", type=Path, default=None)
    parser.add_argument("--db-limit", type=int, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--write-csv", action="store_true")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--probe-limit", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.db is None:
        args.db = JPINTEL_DB

    rows = _load_inputs(args)
    proposals = collect_slash_flip_proposals(rows)
    probe_results = (
        probe_proposals(proposals, limit=args.probe_limit) if args.probe else []
    )
    if args.write_csv:
        write_csv(args.output, proposals, probe_results)

    result = {
        "input_rows": len(rows),
        "hard_404_rows": sum(row.classification in HARD_404_STATUSES for row in rows),
        "proposal_count": len(proposals),
        "probe_count": len(probe_results),
        "probe_outcomes": dict(sorted(Counter(r.outcome for r in probe_results).items())),
        "output": str(args.output) if args.write_csv else "",
        "sample_proposals": [asdict(proposal) for proposal in proposals[:10]],
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"input_rows={result['input_rows']}")
        print(f"hard_404_rows={result['hard_404_rows']}")
        print(f"proposal_count={result['proposal_count']}")
        print(f"probe_count={result['probe_count']}")
        if args.write_csv:
            print(f"output={result['output']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
