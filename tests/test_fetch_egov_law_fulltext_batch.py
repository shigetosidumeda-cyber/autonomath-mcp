"""Tests for scripts/etl/fetch_egov_law_fulltext_batch.py.

Mocks httpx with a MockTransport so no real network call is made.
Exercises:
  1. ``parse_egov_xml`` extracts body_text + promulgation_date + amendment_summary
     from a representative e-Gov v2 XML payload.
  2. ``select_candidates`` reads laws from a temp SQLite (read-only mode)
     and pulls e-Gov law_id out of full_text_url.
  3. ``fetch_batch`` (async) returns one ok row when httpx returns the
     mocked XML response.
  4. ``HostGate`` enforces per-domain Crawl-Delay across two consecutive
     calls — second acquire waits ≥ delay seconds.
  5. ``disallows_api_path`` correctly flags blocking robots.txt rules.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sqlite3
import time
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "etl" / "fetch_egov_law_fulltext_batch.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "fetch_egov_law_fulltext_batch", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_SAMPLE_XML_TEXT = """<?xml version="1.0" encoding="UTF-8"?>
<law_data_response>
  <law_info>
    <law_type>Act</law_type>
    <law_id>340AC0000000034</law_id>
    <law_num>昭和四十年法律第三十四号</law_num>
    <promulgation_date>1965-03-31</promulgation_date>
  </law_info>
  <revision_info>
    <law_revision_id>340AC0000000034_20260401_508AC0000000012</law_revision_id>
    <law_title>法人税法</law_title>
  </revision_info>
  <law_full_text>
    <Law>
      <LawBody>
        <MainProvision>
          <Article Num="1">
            <ArticleTitle>第一条</ArticleTitle>
            <Paragraph><ParagraphSentence><Sentence>この法律は、法人税について定める。</Sentence></ParagraphSentence></Paragraph>
          </Article>
          <Article Num="2">
            <ArticleTitle>第二条</ArticleTitle>
            <Paragraph><ParagraphSentence><Sentence>内国法人とは、国内に本店を有する法人をいう。</Sentence></ParagraphSentence></Paragraph>
          </Article>
        </MainProvision>
      </LawBody>
    </Law>
  </law_full_text>
</law_data_response>
"""
_SAMPLE_XML = _SAMPLE_XML_TEXT.encode("utf-8")


# --------------------------------------------------------------------------- #
# parse_egov_xml
# --------------------------------------------------------------------------- #


def test_parse_egov_xml_extracts_body_and_metadata() -> None:
    mod = _load_module()
    parsed = mod.parse_egov_xml(_SAMPLE_XML)
    assert parsed["article_count"] == 2
    assert "法人税" in parsed["body_text"] or "内国法人" in parsed["body_text"]
    assert parsed["promulgation_date"] == "1965-03-31"
    assert "340AC0000000034_20260401_508AC0000000012" in parsed["amendment_summary"]
    assert "法人税法" in parsed["amendment_summary"]


def test_parse_egov_xml_collapses_whitespace() -> None:
    mod = _load_module()
    parsed = mod.parse_egov_xml(_SAMPLE_XML)
    body = parsed["body_text"]
    # No newlines + no double spaces.
    assert "\n" not in body
    assert "  " not in body


# --------------------------------------------------------------------------- #
# select_candidates (read-only DB)
# --------------------------------------------------------------------------- #


def test_select_candidates_reads_law_id_from_url(tmp_path: Path) -> None:
    mod = _load_module()
    db_path = tmp_path / "mini_jpintel.db"
    con = sqlite3.connect(db_path)
    con.execute(
        """
        CREATE TABLE laws (
            unified_id TEXT PRIMARY KEY,
            full_text_url TEXT,
            law_title TEXT
        )
        """
    )
    con.executemany(
        "INSERT INTO laws (unified_id, full_text_url, law_title) VALUES (?, ?, ?)",
        [
            ("LAW-aaaaaaaaaa", "https://laws.e-gov.go.jp/law/340AC0000000034", "法人税法"),
            ("LAW-bbbbbbbbbb", "https://laws.e-gov.go.jp/law/340AC0000000033", "所得税法"),
            ("LAW-cccccccccc", None, "URL欠損"),  # should be skipped
        ],
    )
    con.commit()
    con.close()

    con_ro = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con_ro.row_factory = sqlite3.Row
    try:
        cands = mod.select_candidates(con_ro, limit=None)
    finally:
        con_ro.close()
    ids = sorted(c["law_id"] for c in cands)
    assert ids == ["340AC0000000033", "340AC0000000034"]


# --------------------------------------------------------------------------- #
# disallows_api_path
# --------------------------------------------------------------------------- #


def test_disallows_api_path_detects_blocking_rules() -> None:
    mod = _load_module()
    assert mod.disallows_api_path(["/"]) is True
    assert mod.disallows_api_path(["/api"]) is True
    assert mod.disallows_api_path(["/some/lawdata"]) is True
    assert mod.disallows_api_path(["/admin"]) is False
    assert mod.disallows_api_path([]) is False


# --------------------------------------------------------------------------- #
# fetch_batch (async, mocked httpx)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_fetch_batch_one_law_ok(monkeypatch) -> None:
    mod = _load_module()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_SAMPLE_XML, headers={"content-type": "text/xml"})

    transport = httpx.MockTransport(handler)

    # Patch the module's httpx.AsyncClient so it routes through the mock.
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(mod.httpx, "AsyncClient", patched_async_client)

    candidates = [
        {
            "unified_id": "LAW-aaaaaaaaaa",
            "law_id": "340AC0000000034",
            "law_title": "法人税法",
            "full_text_url": "https://laws.e-gov.go.jp/law/340AC0000000034",
        }
    ]
    rows = await mod.fetch_batch(candidates, parallel=2, crawl_delay_sec=0.0, timeout_sec=5.0)
    assert len(rows) == 1
    r = rows[0]
    assert r["status"] == "ok", f"expected ok, got status={r['status']} err={r['error']}"
    assert r["law_id"] == "340AC0000000034"
    assert r["body_text"]
    assert len(r["content_hash"]) == 64  # sha256 hex
    assert r["article_count"] == 2


# --------------------------------------------------------------------------- #
# HostGate Crawl-Delay
# --------------------------------------------------------------------------- #


def test_hostgate_enforces_delay() -> None:
    mod = _load_module()
    gate = mod.HostGate(delay_sec=0.2)

    async def run() -> float:
        t0 = time.monotonic()
        await gate.acquire("laws.e-gov.go.jp")
        await gate.acquire("laws.e-gov.go.jp")
        return time.monotonic() - t0

    elapsed = asyncio.run(run())
    # Two sequential acquires on the same host must take ≥ delay.
    # Allow some tolerance for scheduling.
    assert elapsed >= 0.18, f"elapsed={elapsed} (expected ≥ 0.18s)"


def test_hostgate_does_not_delay_distinct_hosts() -> None:
    mod = _load_module()
    gate = mod.HostGate(delay_sec=0.5)

    async def run() -> float:
        t0 = time.monotonic()
        await gate.acquire("laws.e-gov.go.jp")
        await gate.acquire("other.example.com")
        return time.monotonic() - t0

    elapsed = asyncio.run(run())
    # Distinct hosts → no inter-host wait.
    assert elapsed < 0.2, f"elapsed={elapsed} (expected <0.2s)"
