"""Tests for ``jpintel_mcp.aws_credit_ops.textract_client``.

The tests mock boto3 entirely — no live AWS calls. They cover:

* Pydantic request/response model validation (extra=forbid, bucket /
  key sanity checks, feature-type defaults).
* The synchronous ``AnalyzeDocument`` path (≤ 5 pages).
* The asynchronous ``StartDocumentAnalysis`` + poll loop, including
  ``IN_PROGRESS`` → ``SUCCEEDED`` transitions, ``NextToken`` pagination,
  ``FAILED`` status, and timeout.
* Block projection helpers (``LINE`` → text, ``TABLE`` / ``CELL`` →
  rows, ``KEY_VALUE_SET`` → form fields, page-count rollup, confidence
  rollup).
* JPCIR ``request_time_llm_call_performed=false`` is always emitted —
  this is the canonical marker that distinguishes OCR from LLM.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from jpintel_mcp.aws_credit_ops import (
    DEFAULT_REGION,
    SYNC_PAGE_LIMIT,
    AnalyzeFeatureType,
    TextractClientError,
    TextractRequest,
    TextractResult,
    analyze_document,
)

# ---------------------------------------------------------------------------
# Fake boto3 client
# ---------------------------------------------------------------------------


class _FakeTextractClient:
    """Hand-rolled fake Textract client.

    We deliberately do not use ``unittest.mock.MagicMock`` because the
    real Textract API surface is small and the tests are clearer when
    each fake method is named and asserted explicitly.
    """

    _SENTINEL: dict[str, Any] = {}

    def __init__(
        self,
        analyze_response: dict[str, Any] | None = None,
        start_response: dict[str, Any] | None = _SENTINEL,
        get_pages: list[dict[str, Any]] | None = None,
        get_default: dict[str, Any] | None = None,
    ) -> None:
        self._analyze_response = analyze_response if analyze_response is not None else {"Blocks": []}
        # Use a sentinel so callers can pass an *empty* {} on purpose
        # (to exercise the "no JobId" error path) without it being
        # silently swapped for the happy-path default.
        if start_response is _FakeTextractClient._SENTINEL:
            self._start_response: dict[str, Any] = {"JobId": "job-abc"}
        else:
            self._start_response = start_response if start_response is not None else {}
        self._get_pages = list(get_pages or [])
        # Default page returned once _get_pages is exhausted. Tests that
        # exercise the timeout path pass {"JobStatus": "IN_PROGRESS"}
        # here so polling never accidentally falls into a SUCCEEDED
        # sentinel after the prepared pages drain.
        self._get_default = get_default if get_default is not None else {"JobStatus": "SUCCEEDED", "Blocks": []}
        self.analyze_calls: list[dict[str, Any]] = []
        self.start_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []

    def analyze_document(self, **kwargs: Any) -> dict[str, Any]:
        self.analyze_calls.append(kwargs)
        return self._analyze_response

    def start_document_analysis(self, **kwargs: Any) -> dict[str, Any]:
        self.start_calls.append(kwargs)
        return self._start_response

    def get_document_analysis(self, **kwargs: Any) -> dict[str, Any]:
        self.get_calls.append(kwargs)
        if not self._get_pages:
            return self._get_default
        return self._get_pages.pop(0)


def _line_block(text: str, page: int = 1) -> dict[str, Any]:
    return {"BlockType": "LINE", "Text": text, "Page": page}


def _word_block(block_id: str, text: str, confidence: float = 99.0) -> dict[str, Any]:
    return {"BlockType": "WORD", "Id": block_id, "Text": text, "Confidence": confidence}


# ---------------------------------------------------------------------------
# Pydantic model tests
# ---------------------------------------------------------------------------


def test_textract_request_defaults() -> None:
    req = TextractRequest(s3_bucket="jpcite-credit-993693061769-202605-raw", s3_key="J06_ministry_pdf/sample.pdf")
    assert req.region == DEFAULT_REGION
    assert req.feature_types == (AnalyzeFeatureType.TABLES, AnalyzeFeatureType.FORMS)
    assert req.poll_interval_seconds > 0
    assert req.poll_timeout_seconds > 0
    assert req.estimated_page_count is None


def test_textract_request_rejects_uppercase_bucket() -> None:
    with pytest.raises(ValidationError):
        TextractRequest(s3_bucket="JPCITE-CREDIT", s3_key="a.pdf")


def test_textract_request_rejects_leading_slash_key() -> None:
    with pytest.raises(ValidationError):
        TextractRequest(s3_bucket="jpcite-credit", s3_key="/a.pdf")


def test_textract_request_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        TextractRequest(  # type: ignore[call-arg]
            s3_bucket="jpcite-credit",
            s3_key="a.pdf",
            unexpected="boom",
        )


def test_textract_result_always_marks_llm_false() -> None:
    result = TextractResult(s3_bucket="b", s3_key="k", page_count=0)
    assert result.request_time_llm_call_performed is False


def test_textract_result_frozen_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        TextractResult(  # type: ignore[call-arg]
            s3_bucket="b",
            s3_key="k",
            page_count=0,
            request_time_llm_call_performed=True,  # Literal[False] — must reject
        )


# ---------------------------------------------------------------------------
# Synchronous path
# ---------------------------------------------------------------------------


def test_analyze_document_sync_routes_under_page_limit() -> None:
    fake = _FakeTextractClient(
        analyze_response={
            "Blocks": [
                _line_block("締切: 2026年6月30日", page=1),
                _line_block("対象者: 中小企業者", page=1),
            ]
        }
    )
    req = TextractRequest(
        s3_bucket="jpcite-credit",
        s3_key="J06_ministry_pdf/short.pdf",
        estimated_page_count=2,
    )
    result = analyze_document(req, client=fake)

    assert fake.analyze_calls and not fake.start_calls and not fake.get_calls
    call = fake.analyze_calls[0]
    assert call["Document"]["S3Object"]["Bucket"] == "jpcite-credit"
    assert call["Document"]["S3Object"]["Name"] == "J06_ministry_pdf/short.pdf"
    assert sorted(call["FeatureTypes"]) == ["FORMS", "TABLES"]
    assert "締切: 2026年6月30日" in result.extracted_text
    assert "対象者: 中小企業者" in result.extracted_text
    assert result.page_count == 1
    assert result.request_time_llm_call_performed is False


def test_analyze_document_sync_at_boundary_uses_sync_path() -> None:
    fake = _FakeTextractClient()
    req = TextractRequest(
        s3_bucket="jpcite-credit",
        s3_key="boundary.pdf",
        estimated_page_count=SYNC_PAGE_LIMIT,
    )
    analyze_document(req, client=fake)
    assert fake.analyze_calls and not fake.start_calls


# ---------------------------------------------------------------------------
# Asynchronous path
# ---------------------------------------------------------------------------


def test_analyze_document_async_routes_over_page_limit() -> None:
    fake = _FakeTextractClient(
        start_response={"JobId": "job-1"},
        get_pages=[
            {
                "JobStatus": "SUCCEEDED",
                "Blocks": [_line_block("HELLO", page=1)],
            }
        ],
    )
    req = TextractRequest(
        s3_bucket="jpcite-credit",
        s3_key="big.pdf",
        estimated_page_count=50,
    )
    result = analyze_document(req, client=fake)
    assert fake.start_calls and fake.get_calls
    assert not fake.analyze_calls
    assert result.extracted_text == "HELLO"
    assert result.page_count == 1


def test_analyze_document_async_with_unknown_pages_routes_async() -> None:
    fake = _FakeTextractClient(
        start_response={"JobId": "job-x"},
        get_pages=[{"JobStatus": "SUCCEEDED", "Blocks": []}],
    )
    req = TextractRequest(s3_bucket="jpcite-credit", s3_key="unknown.pdf")
    analyze_document(req, client=fake)
    assert fake.start_calls and not fake.analyze_calls


def test_analyze_document_async_polls_through_in_progress() -> None:
    fake = _FakeTextractClient(
        start_response={"JobId": "job-p"},
        get_pages=[
            {"JobStatus": "IN_PROGRESS"},
            {"JobStatus": "IN_PROGRESS"},
            {"JobStatus": "SUCCEEDED", "Blocks": [_line_block("DONE")]},
        ],
    )
    sleeps: list[float] = []
    req = TextractRequest(
        s3_bucket="jpcite-credit",
        s3_key="slow.pdf",
        estimated_page_count=10,
        poll_interval_seconds=0.01,
    )
    result = analyze_document(req, client=fake, sleep=sleeps.append)
    assert len(fake.get_calls) == 3
    assert len(sleeps) == 2  # one sleep per IN_PROGRESS poll
    assert result.extracted_text == "DONE"


def test_analyze_document_async_paginates_next_token() -> None:
    fake = _FakeTextractClient(
        start_response={"JobId": "job-pg"},
        get_pages=[
            {
                "JobStatus": "SUCCEEDED",
                "Blocks": [_line_block("page1", page=1)],
                "NextToken": "tok-1",
            },
            {
                "JobStatus": "SUCCEEDED",
                "Blocks": [_line_block("page2", page=2)],
            },
        ],
    )
    req = TextractRequest(s3_bucket="jpcite-credit", s3_key="pgs.pdf", estimated_page_count=20)
    result = analyze_document(req, client=fake)
    assert len(fake.get_calls) == 2
    assert fake.get_calls[1].get("NextToken") == "tok-1"
    assert "page1" in result.extracted_text and "page2" in result.extracted_text
    assert result.page_count == 2


def test_analyze_document_async_raises_on_failed_status() -> None:
    fake = _FakeTextractClient(
        start_response={"JobId": "job-f"},
        get_pages=[{"JobStatus": "FAILED", "StatusMessage": "boom"}],
    )
    req = TextractRequest(s3_bucket="jpcite-credit", s3_key="fail.pdf", estimated_page_count=10)
    with pytest.raises(TextractClientError, match="FAILED"):
        analyze_document(req, client=fake)


def test_analyze_document_async_raises_without_job_id() -> None:
    fake = _FakeTextractClient(start_response={})
    req = TextractRequest(s3_bucket="jpcite-credit", s3_key="nojob.pdf", estimated_page_count=10)
    with pytest.raises(TextractClientError, match="JobId"):
        analyze_document(req, client=fake)


def test_analyze_document_async_times_out() -> None:
    # Always IN_PROGRESS — set get_default so the poll loop never falls
    # through to a SUCCEEDED sentinel after the prepared pages drain.
    fake = _FakeTextractClient(
        start_response={"JobId": "job-t"},
        get_pages=[],
        get_default={"JobStatus": "IN_PROGRESS"},
    )
    req = TextractRequest(
        s3_bucket="jpcite-credit",
        s3_key="hang.pdf",
        estimated_page_count=10,
        poll_interval_seconds=0.0001,
        poll_timeout_seconds=0.0005,
    )
    with pytest.raises(TextractClientError, match="did not finish"):
        analyze_document(req, client=fake, sleep=lambda _x: None)


# ---------------------------------------------------------------------------
# Block projection
# ---------------------------------------------------------------------------


def test_table_projection_walks_cell_words() -> None:
    blocks = [
        {
            "BlockType": "TABLE",
            "Id": "t1",
            "Page": 1,
            "Relationships": [{"Type": "CHILD", "Ids": ["c1", "c2"]}],
        },
        {
            "BlockType": "CELL",
            "Id": "c1",
            "RowIndex": 1,
            "ColumnIndex": 1,
            "Confidence": 95.0,
            "Relationships": [{"Type": "CHILD", "Ids": ["w1"]}],
        },
        {
            "BlockType": "CELL",
            "Id": "c2",
            "RowIndex": 1,
            "ColumnIndex": 2,
            "Confidence": 90.0,
            "Relationships": [{"Type": "CHILD", "Ids": ["w2", "w3"]}],
        },
        _word_block("w1", "締切"),
        _word_block("w2", "2026年"),
        _word_block("w3", "6月30日"),
    ]
    fake = _FakeTextractClient(analyze_response={"Blocks": blocks})
    req = TextractRequest(s3_bucket="jpcite-credit", s3_key="t.pdf", estimated_page_count=1)
    result = analyze_document(req, client=fake)
    assert len(result.tables) == 1
    cells = result.tables[0].cells
    assert {c.text for c in cells} == {"締切", "2026年 6月30日"}
    assert result.confidence_per_field["tables_avg"] > 0


def test_form_projection_resolves_key_and_value() -> None:
    blocks = [
        {
            "BlockType": "KEY_VALUE_SET",
            "Id": "k1",
            "EntityTypes": ["KEY"],
            "Page": 1,
            "Relationships": [
                {"Type": "CHILD", "Ids": ["wk1"]},
                {"Type": "VALUE", "Ids": ["v1"]},
            ],
        },
        {
            "BlockType": "KEY_VALUE_SET",
            "Id": "v1",
            "EntityTypes": ["VALUE"],
            "Page": 1,
            "Relationships": [{"Type": "CHILD", "Ids": ["wv1"]}],
        },
        _word_block("wk1", "対象者", confidence=98.0),
        _word_block("wv1", "中小企業者", confidence=88.0),
    ]
    fake = _FakeTextractClient(analyze_response={"Blocks": blocks})
    req = TextractRequest(s3_bucket="jpcite-credit", s3_key="f.pdf", estimated_page_count=1)
    result = analyze_document(req, client=fake)
    assert len(result.forms) == 1
    f = result.forms[0]
    assert f.key == "対象者"
    assert f.value == "中小企業者"
    assert f.key_confidence == pytest.approx(98.0)
    assert f.value_confidence == pytest.approx(88.0)
    assert result.confidence_per_field["forms_avg"] == pytest.approx(93.0)


def test_page_count_rolls_up_unique_pages() -> None:
    fake = _FakeTextractClient(
        analyze_response={
            "Blocks": [
                _line_block("a", page=1),
                _line_block("b", page=2),
                _line_block("c", page=2),
                _line_block("d", page=3),
            ]
        }
    )
    req = TextractRequest(s3_bucket="jpcite-credit", s3_key="p.pdf", estimated_page_count=1)
    result = analyze_document(req, client=fake)
    assert result.page_count == 3


# ---------------------------------------------------------------------------
# Client construction seam
# ---------------------------------------------------------------------------


def test_client_factory_is_called_when_no_client_passed() -> None:
    calls: list[str] = []

    def factory(region: str) -> _FakeTextractClient:
        calls.append(region)
        return _FakeTextractClient(analyze_response={"Blocks": []})

    req = TextractRequest(
        s3_bucket="jpcite-credit",
        s3_key="f.pdf",
        region="ap-northeast-1",
        estimated_page_count=1,
    )
    result = analyze_document(req, client_factory=factory)
    assert calls == ["ap-northeast-1"]
    assert result.request_time_llm_call_performed is False
