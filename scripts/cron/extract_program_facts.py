#!/usr/bin/env python3
"""Deterministic dry-run fact extractor for program PDF text.

B6 intentionally does not fetch network resources, call LLM APIs, or write to
the database.  It accepts already-extracted text for the first PDF profile
(``grant_env_content``) and emits JSON facts suitable for review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

PROFILE_GRANT_ENV_CONTENT = "grant_env_content"

_ERA_START_YEARS = {
    "令和": 2018,
    "平成": 1988,
    "昭和": 1925,
}
_KANJI_DIGITS = {
    "〇": 0,
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_SECTION_HEADERS = (
    "提出書類",
    "必要書類",
    "添付書類",
    "申請書類",
    "問い合わせ",
    "問合せ",
    "お問い合わせ",
    "担当",
    "補助率",
    "補助額",
    "補助上限",
    "上限額",
    "募集期間",
    "申請期限",
    "提出期限",
)


@dataclass(frozen=True)
class ExtractedFacts:
    profile: str
    source_url: str
    source_domain: str
    deadline: dict[str, object] | None
    subsidy_rate: dict[str, object] | None
    required_docs: list[str]
    contact: dict[str, object] | None
    max_amount: dict[str, object] | None
    content_hash: str
    text_hash: str
    confidence: float


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _kanji_number_to_int(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    if value in {"元", "元年"}:
        return 1
    if value.isdecimal():
        return int(value)
    total = 0
    current = 0
    units = {"十": 10, "百": 100}
    for char in value:
        if char in _KANJI_DIGITS:
            current = _KANJI_DIGITS[char]
            continue
        if char in units:
            total += (current or 1) * units[char]
            current = 0
            continue
        return None
    return total + current


def _parse_int(value: str) -> int | None:
    value = unicodedata.normalize("NFKC", value).replace(",", "").strip()
    if value in {"元", "元年"}:
        return 1
    if value.isdecimal():
        return int(value)
    return _kanji_number_to_int(value)


def normalize_japanese_date(raw: str) -> str | None:
    text = unicodedata.normalize("NFKC", raw)
    era_match = re.search(
        r"(令和|平成|昭和)\s*([元\d〇零一二三四五六七八九十百]+)\s*年\s*"
        r"(\d{1,2}|[〇零一二三四五六七八九十]+)\s*月\s*"
        r"(\d{1,2}|[〇零一二三四五六七八九十]+)\s*日",
        text,
    )
    if era_match:
        era, era_year_raw, month_raw, day_raw = era_match.groups()
        era_year = _parse_int(era_year_raw)
        month = _parse_int(month_raw)
        day = _parse_int(day_raw)
        if era_year is None or month is None or day is None:
            return None
        return _date_or_none(_ERA_START_YEARS[era] + era_year, month, day)

    western_match = re.search(
        r"(\d{4})\s*[年/-]\s*(\d{1,2})\s*[月/-]\s*(\d{1,2})\s*日?",
        text,
    )
    if western_match:
        year, month, day = (int(part) for part in western_match.groups())
        return _date_or_none(year, month, day)
    return None


def _date_or_none(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _date_candidates(text: str) -> list[tuple[str, str]]:
    patterns = (
        r"(?:令和|平成|昭和)\s*[元\d〇零一二三四五六七八九十百]+\s*年\s*"
        r"(?:\d{1,2}|[〇零一二三四五六七八九十]+)\s*月\s*"
        r"(?:\d{1,2}|[〇零一二三四五六七八九十]+)\s*日",
        r"\d{4}\s*[年/-]\s*\d{1,2}\s*[月/-]\s*\d{1,2}\s*日?",
    )
    out: list[tuple[str, str]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            normalized = normalize_japanese_date(match.group(0))
            if normalized:
                out.append((normalized, match.group(0).strip()))
    return out


def extract_deadline(text: str) -> dict[str, object] | None:
    lines = text.splitlines()
    keyword_lines = [
        line.strip()
        for line in lines
        if re.search(r"(申請期限|提出期限|募集期間|受付期間|公募期間|締切|締め切り)", line)
    ]
    for line in keyword_lines:
        if re.search(r"(随時|予算.*達し次第|なくなり次第)", line):
            return {"value": None, "raw": line, "status": "rolling_or_budget_limited"}
        candidates = _date_candidates(line)
        if candidates:
            value, raw_date = candidates[-1]
            return {"value": value, "raw": line, "raw_date": raw_date}

    candidates = _date_candidates(text)
    if candidates:
        value, raw_date = candidates[-1]
        return {"value": value, "raw": raw_date, "raw_date": raw_date}
    return None


def normalize_subsidy_rate(raw: str) -> dict[str, object] | None:
    text = unicodedata.normalize("NFKC", raw)
    percent_match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if percent_match:
        percent = float(percent_match.group(1))
        return {"raw": raw.strip(), "normalized": f"{percent:g}%", "percent": percent}

    fraction_match = re.search(r"(\d+)\s*/\s*(\d+)", text)
    if fraction_match:
        numerator, denominator = (int(value) for value in fraction_match.groups())
        if denominator:
            return {
                "raw": raw.strip(),
                "normalized": f"{numerator}/{denominator}",
                "percent": round(numerator / denominator * 100, 4),
            }

    japanese_fraction = re.search(
        r"([一二三四五六七八九十\d]+)\s*分の\s*([一二三四五六七八九十\d]+)", text
    )
    if japanese_fraction:
        denominator = _parse_int(japanese_fraction.group(1))
        numerator = _parse_int(japanese_fraction.group(2))
        if numerator is not None and denominator:
            return {
                "raw": raw.strip(),
                "normalized": f"{numerator}/{denominator}",
                "percent": round(numerator / denominator * 100, 4),
            }
    return None


def extract_subsidy_rate(text: str) -> dict[str, object] | None:
    for line in text.splitlines():
        if "補助率" not in line and "助成率" not in line:
            continue
        normalized = normalize_subsidy_rate(line)
        if normalized:
            return normalized
    return normalize_subsidy_rate(text)


def normalize_yen_amount(raw: str) -> dict[str, object] | None:
    text = unicodedata.normalize("NFKC", raw)
    match = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(億|千万|百万|万円|千円|円)", text)
    if not match:
        return None
    amount = float(match.group(1).replace(",", ""))
    unit = match.group(2)
    multiplier = {
        "億": 100_000_000,
        "千万": 10_000_000,
        "百万": 1_000_000,
        "万円": 10_000,
        "千円": 1_000,
        "円": 1,
    }[unit]
    yen = int(amount * multiplier)
    return {"raw": raw.strip(), "yen": yen, "display": f"{yen:,}円"}


def extract_max_amount(text: str) -> dict[str, object] | None:
    amount_lines = [
        line.strip()
        for line in text.splitlines()
        if re.search(r"(上限|限度額|最大|補助額)", line)
        and re.search(r"[0-9０-９].*(円|万円|千円|億)", line)
    ]
    candidates = [
        normalized
        for line in amount_lines
        if (normalized := normalize_yen_amount(line)) is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: int(item["yen"]))


def extract_required_docs(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    docs: list[str] = []
    collecting = False
    for line in lines:
        if not line:
            if collecting and docs:
                break
            continue
        if re.search(r"(提出書類|必要書類|添付書類|申請書類)", line):
            collecting = True
            remainder = re.sub(
                r"^.*?(提出書類|必要書類|添付書類|申請書類)\s*[:：]?", "", line
            ).strip()
            if remainder:
                docs.extend(_split_doc_items(remainder))
            continue
        if not collecting:
            continue
        if any(line.startswith(header) for header in _SECTION_HEADERS):
            break
        docs.extend(_split_doc_items(line))
    return _dedupe_keep_order(docs)


def _split_doc_items(line: str) -> list[str]:
    cleaned = re.sub(r"^[・\-\*●○◆◇□■\d]+[.)、\s]*", "", line).strip()
    if not cleaned:
        return []
    parts = [
        part.strip(" ・、,") for part in re.split(r"[、,]\s*", cleaned) if part.strip(" ・、,")
    ]
    return parts


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def extract_contact(text: str) -> dict[str, object] | None:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not re.search(r"(問い合わせ|問合せ|お問い合わせ|担当課|担当部署|連絡先)", line):
            continue
        block = " ".join(part.strip() for part in lines[index : index + 3] if part.strip())
        phone = re.search(r"0\d{1,4}-\d{1,4}-\d{3,4}", block)
        email = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", block)
        return {
            "raw": block,
            "phone": phone.group(0) if phone else None,
            "email": email.group(0) if email else None,
        }
    return None


def confidence_for(facts: ExtractedFacts) -> float:
    score = 0.2
    if facts.deadline:
        score += 0.2
    if facts.subsidy_rate:
        score += 0.18
    if facts.max_amount:
        score += 0.18
    if facts.required_docs:
        score += 0.12
    if facts.contact:
        score += 0.12
    return round(min(score, 1.0), 2)


def parse_program_facts(
    text: str,
    *,
    source_url: str,
    source_domain: str,
    profile: str = PROFILE_GRANT_ENV_CONTENT,
) -> ExtractedFacts:
    if profile != PROFILE_GRANT_ENV_CONTENT:
        raise ValueError(f"unsupported profile: {profile}")
    normalized_text = normalize_text(text)
    facts = ExtractedFacts(
        profile=profile,
        source_url=source_url,
        source_domain=source_domain,
        deadline=extract_deadline(normalized_text),
        subsidy_rate=extract_subsidy_rate(normalized_text),
        required_docs=extract_required_docs(normalized_text),
        contact=extract_contact(normalized_text),
        max_amount=extract_max_amount(normalized_text),
        content_hash=_sha256(f"{source_url}\n{normalized_text}"),
        text_hash=_sha256(normalized_text),
        confidence=0.0,
    )
    return ExtractedFacts(**{**asdict(facts), "confidence": confidence_for(facts)})


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text-file", type=Path, help="Path to already-extracted PDF text")
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--source-domain", required=True)
    parser.add_argument("--profile", default=PROFILE_GRANT_ENV_CONTENT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    text = args.text_file.read_text(encoding="utf-8") if args.text_file else sys.stdin.read()
    facts = parse_program_facts(
        text,
        source_url=args.source_url,
        source_domain=args.source_domain,
        profile=args.profile,
    )
    print(json.dumps(asdict(facts), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
