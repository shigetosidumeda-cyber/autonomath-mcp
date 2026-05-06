"""Shared denylist for generated public static source URLs.

The production DB carries the canonical liveness columns, but historical
research loops also produce confirmed dead/blocked URL reports before those
fields are promoted into `programs`. Static generation should not promote
those URLs while the DB repair loop catches up.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

_DEFAULT_JSON_REPORTS = (REPO_ROOT / "analysis_wave18" / "url_liveness_2026-04-30.json",)
_DEFAULT_JSONL_REPORTS = (REPO_ROOT / "data" / "autonomath" / "dead_pref_urls.jsonl",)
_BAD_CLASSIFICATIONS = {"hard_404", "soft_404"}
_BAD_STATUS_CODES = {403, 404, 410}
_BAD_DISPOSITIONS = {"dead_url", "confirmed_dead", "broken", "hard_404", "soft_404"}


def _norm_url(value: object) -> str:
    return str(value or "").strip()


def _status_code(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _is_bad_liveness_row(row: dict[str, Any]) -> bool:
    classification = (
        str(row.get("latest_classification") or row.get("classification") or "").strip().lower()
    )
    disposition = str(row.get("disposition") or "").strip().lower()
    status_code = _status_code(row.get("status_code") or row.get("http_status"))

    if classification in _BAD_CLASSIFICATIONS:
        return True
    if disposition in _BAD_DISPOSITIONS:
        return True
    return status_code in _BAD_STATUS_CODES


def load_static_bad_urls(
    *,
    json_reports: tuple[Path, ...] = _DEFAULT_JSON_REPORTS,
    jsonl_reports: tuple[Path, ...] = _DEFAULT_JSONL_REPORTS,
) -> set[str]:
    """Return URL strings that static outputs must not promote."""
    bad: set[str] = set()

    for path in json_reports:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows: object = data.get("results") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or not _is_bad_liveness_row(row):
                continue
            url = _norm_url(row.get("url") or row.get("source_url"))
            if url:
                bad.add(url)

    for path in jsonl_reports:
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict) or not _is_bad_liveness_row(row):
                continue
            url = _norm_url(row.get("url") or row.get("source_url"))
            if url:
                bad.add(url)

    return bad


__all__ = ["load_static_bad_urls"]
