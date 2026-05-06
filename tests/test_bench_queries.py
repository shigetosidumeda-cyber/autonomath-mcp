from __future__ import annotations

import csv
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCH_QUERIES_CSV = REPO_ROOT / "tools" / "offline" / "bench_queries_2026_04_30.csv"


def _read_rows() -> list[dict[str, str]]:
    with BENCH_QUERIES_CSV.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_bench_queries_are_canonical_and_non_empty() -> None:
    rows = _read_rows()

    assert rows
    assert rows[0].keys() == {"query_id", "domain", "query_text", "notes"}
    assert len(rows) == 30
    assert [int(row["query_id"]) for row in rows] == list(range(1, 31))

    for row in rows:
        assert all(value.strip() for value in row.values()), row


def test_bench_queries_are_unique_and_diverse() -> None:
    rows = _read_rows()

    normalized_queries = [re.sub(r"\s+", " ", row["query_text"].strip()).casefold() for row in rows]
    assert len(set(normalized_queries)) == len(normalized_queries)

    domains = {row["domain"] for row in rows}
    assert domains == {"subsidy", "houjin", "law", "tax", "enforcement"}

    counts = dict.fromkeys(domains, 0)
    for row in rows:
        counts[row["domain"]] += 1
    assert counts["subsidy"] >= 8
    assert all(counts[domain] >= 4 for domain in domains - {"subsidy"})


def test_bench_queries_match_japanese_public_program_use_cases() -> None:
    rows = _read_rows()

    topic_terms = {
        "subsidy": ("補助金", "助成金"),
        "houjin": ("法人番号", "適格請求書発行事業者", "採択事例"),
        "law": ("法", "制度", "協定", "義務", "定義"),
        "tax": ("税", "控除", "課税", "仕入率"),
        "enforcement": ("処分", "停止", "取消", "命令"),
    }
    japanese_text = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")

    for row in rows:
        query = row["query_text"]
        assert japanese_text.search(query), row
        assert any(term in query for term in topic_terms[row["domain"]]), row
