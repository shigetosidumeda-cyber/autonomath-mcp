"""Tests for ``scripts.aws_credit_ops.textract_batch``.

All boto3 + Textract calls are mocked. No live AWS, no real S3 access.
The tests cover:

* S3 URI parsing (bucket / prefix / joining).
* PDF listing with content-type + suffix filters and pagination.
* The budget gate (warn at 80 %, stop at 100 %, projected spend rollup).
* DRY_RUN path (no Textract call, synthetic page count).
* Real-path Textract drive (mocked analyze_fn) + per-page JSONL projection.
* Run manifest + summary writes (mocked S3 PUT).
* CLI argument parsing + main() return codes.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from jpintel_mcp.aws_credit_ops import (
    AnalyzeFeatureType,
    TextractClientError,
    TextractRequest,
    TextractResult,
)
from scripts.aws_credit_ops.textract_batch import (
    DEFAULT_BUDGET_USD,
    DEFAULT_PER_PAGE_USD,
    DEFAULT_WARN_THRESHOLD,
    DRY_RUN_SIMULATED_PAGE_COUNT,
    MAGIC_BYTES_SCAN_LEN,
    PdfListEntry,
    RunReport,
    S3Uri,
    _parse_args,
    audit_magic_bytes,
    build_per_page_jsonl,
    classify_magic_bytes,
    list_pdfs,
    main,
    projected_spend_after,
    run_batch,
    should_stop,
    should_warn,
    write_jsonl,
    write_run_manifest,
)

# ---------------------------------------------------------------------------
# Fake clients
# ---------------------------------------------------------------------------


class _FakeS3:
    def __init__(
        self,
        pages: list[dict[str, Any]] | None = None,
        *,
        prefix_bytes: dict[str, bytes] | None = None,
    ) -> None:
        self._pages = list(pages or [])
        self._prefix_bytes = dict(prefix_bytes or {})
        self.put_calls: list[dict[str, Any]] = []
        self.list_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        self.list_calls.append(kwargs)
        if not self._pages:
            return {"Contents": []}
        return self._pages.pop(0)

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.put_calls.append(kwargs)
        return {"ETag": "abc"}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.get_calls.append(kwargs)
        key = kwargs.get("Key")
        data = self._prefix_bytes.get(str(key), b"")

        class _Body:
            def __init__(self, payload: bytes) -> None:
                self._payload = payload

            def read(self, n: int = -1) -> bytes:
                if n < 0:
                    return self._payload
                return self._payload[:n]

        return {"Body": _Body(data)}


# ---------------------------------------------------------------------------
# S3Uri
# ---------------------------------------------------------------------------


def test_s3uri_parse_with_prefix() -> None:
    u = S3Uri.parse("s3://my-bucket/some/prefix/")
    assert u.bucket == "my-bucket"
    assert u.key_prefix == "some/prefix/"


def test_s3uri_parse_bucket_only() -> None:
    u = S3Uri.parse("s3://my-bucket")
    assert u.bucket == "my-bucket"
    assert u.key_prefix == ""


def test_s3uri_parse_rejects_non_s3_scheme() -> None:
    with pytest.raises(ValueError, match="s3://"):
        S3Uri.parse("https://example.com/x")


def test_s3uri_join_adds_separator() -> None:
    u = S3Uri.parse("s3://b/p")
    assert u.join("x.json") == "s3://b/p/x.json"
    u2 = S3Uri.parse("s3://b/p/")
    assert u2.join("x.json") == "s3://b/p/x.json"


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def test_list_pdfs_filters_by_suffix() -> None:
    fake = _FakeS3(
        pages=[
            {
                "Contents": [
                    {"Key": "a/b.pdf", "Size": 100},
                    {"Key": "a/c.txt", "Size": 50},
                    {"Key": "a/d.PDF", "Size": 200},
                ]
            }
        ]
    )
    entries = list_pdfs(S3Uri.parse("s3://bkt/a/"), s3_client=fake)
    keys = [e.key for e in entries]
    assert keys == ["a/b.pdf", "a/d.PDF"]


def test_list_pdfs_rejects_wrong_content_type() -> None:
    fake = _FakeS3(
        pages=[
            {
                "Contents": [
                    {"Key": "x.pdf", "Size": 100, "ContentType": "application/pdf"},
                    {"Key": "y.pdf", "Size": 200, "ContentType": "text/html"},
                ]
            }
        ]
    )
    entries = list_pdfs(S3Uri.parse("s3://bkt/"), s3_client=fake)
    keys = [e.key for e in entries]
    assert keys == ["x.pdf"]


def test_list_pdfs_paginates() -> None:
    fake = _FakeS3(
        pages=[
            {
                "Contents": [{"Key": "p1.pdf", "Size": 1}],
                "IsTruncated": True,
                "NextContinuationToken": "tok-1",
            },
            {"Contents": [{"Key": "p2.pdf", "Size": 2}]},
        ]
    )
    entries = list_pdfs(S3Uri.parse("s3://bkt/"), s3_client=fake)
    assert [e.key for e in entries] == ["p1.pdf", "p2.pdf"]
    # Second list call must include the continuation token.
    assert fake.list_calls[1].get("ContinuationToken") == "tok-1"


def test_list_pdfs_honors_max_cap() -> None:
    fake = _FakeS3(
        pages=[
            {
                "Contents": [
                    {"Key": f"x{i}.pdf", "Size": 1} for i in range(50)
                ]
            }
        ]
    )
    entries = list_pdfs(S3Uri.parse("s3://bkt/"), s3_client=fake, max_pdfs=10)
    assert len(entries) == 10


# ---------------------------------------------------------------------------
# Budget gate
# ---------------------------------------------------------------------------


def test_projected_spend_after_zero_pages() -> None:
    assert projected_spend_after(0, 0.05, 0) == pytest.approx(0.0)


def test_projected_spend_after_sums_pages() -> None:
    # 100 + 10 = 110 pages * 0.05 = 5.5
    assert projected_spend_after(100, 0.05, 10) == pytest.approx(5.5)


def test_should_stop_when_at_or_above_budget() -> None:
    assert should_stop(100.0, 100.0)
    assert should_stop(150.0, 100.0)
    assert not should_stop(99.99, 100.0)


def test_should_warn_at_threshold() -> None:
    assert should_warn(80.0, 100.0, 0.8)
    assert not should_warn(79.99, 100.0, 0.8)


# ---------------------------------------------------------------------------
# DRY_RUN drive
# ---------------------------------------------------------------------------


def test_run_batch_dry_run_emits_no_s3_writes() -> None:
    fake_s3 = _FakeS3(
        pages=[
            {
                "Contents": [
                    {"Key": "a.pdf", "Size": 100},
                    {"Key": "b.pdf", "Size": 200},
                ]
            }
        ]
    )
    report = run_batch(
        input_prefix="s3://in-bucket/J06/raw/",
        output_prefix="s3://out-bucket/J06_textract/",
        dry_run=True,
        s3_client=fake_s3,
    )
    assert report.dry_run is True
    assert report.pdf_count_listed == 2
    assert report.pdf_count_analyzed == 2
    assert report.page_count_total == 2 * DRY_RUN_SIMULATED_PAGE_COUNT
    # Dry run must NOT issue any PUTs.
    assert fake_s3.put_calls == []


def test_run_batch_dry_run_stops_at_budget() -> None:
    # 100 PDFs * 10 pages * 0.05 = USD 50. Set budget to USD 5 so we
    # stop very early.
    fake_s3 = _FakeS3(
        pages=[
            {
                "Contents": [
                    {"Key": f"p{i}.pdf", "Size": 1} for i in range(100)
                ]
            }
        ]
    )
    report = run_batch(
        input_prefix="s3://in-bucket/J06/",
        output_prefix="s3://out-bucket/J06_textract/",
        budget_usd=5.0,
        dry_run=True,
        s3_client=fake_s3,
    )
    assert report.stopped_at_pdf is not None
    assert "budget" in (report.stop_reason or "")
    # Some PDFs are skipped due to the stop; analyzed count is bounded.
    assert report.pdf_count_analyzed < 100


def test_run_batch_dry_run_emits_warn_below_stop() -> None:
    # 100 pages cost USD 5. Budget USD 6 hits the 80% warn line at USD 4.8.
    fake_s3 = _FakeS3(
        pages=[
            {
                "Contents": [
                    {"Key": f"p{i}.pdf", "Size": 1} for i in range(10)
                ]
            }
        ]
    )
    report = run_batch(
        input_prefix="s3://in-bucket/J06/",
        output_prefix="s3://out-bucket/J06_textract/",
        budget_usd=6.0,
        dry_run=True,
        s3_client=fake_s3,
    )
    assert report.warn_emitted_at_pdf is not None


# ---------------------------------------------------------------------------
# Real-path Textract drive (mocked)
# ---------------------------------------------------------------------------


def test_run_batch_commit_writes_jsonl_and_summary() -> None:
    fake_s3 = _FakeS3(
        pages=[
            {
                "Contents": [
                    {"Key": "a.pdf", "Size": 100},
                ]
            }
        ]
    )

    captured: list[TextractRequest] = []

    def fake_analyze(req: TextractRequest, **kwargs: Any) -> TextractResult:
        captured.append(req)
        return TextractResult(
            s3_bucket=req.s3_bucket,
            s3_key=req.s3_key,
            page_count=3,
            raw_blocks=(
                {"BlockType": "LINE", "Text": "page1", "Page": 1},
                {"BlockType": "LINE", "Text": "page2", "Page": 2},
                {"BlockType": "LINE", "Text": "page3", "Page": 3},
            ),
        )

    report = run_batch(
        input_prefix="s3://in-bucket/J06/",
        output_prefix="s3://out-bucket/J06_textract/",
        dry_run=False,
        s3_client=fake_s3,
        analyze_fn=fake_analyze,
    )
    assert len(captured) == 1
    req = captured[0]
    assert req.feature_types == (AnalyzeFeatureType.TABLES, AnalyzeFeatureType.FORMS)
    assert report.page_count_total == 3
    # Expect at least: 1 jsonl + 1 summary + 1 run manifest.
    assert len(fake_s3.put_calls) >= 3
    put_keys = [c["Key"] for c in fake_s3.put_calls]
    assert any("jsonl" in k for k in put_keys)
    assert any("summary" in k for k in put_keys)
    assert any("run_manifest.json" in k for k in put_keys)


def test_run_batch_handles_textract_error_as_skip() -> None:
    fake_s3 = _FakeS3(
        pages=[
            {"Contents": [{"Key": "a.pdf", "Size": 100}]},
        ]
    )

    def fake_analyze(req: TextractRequest, **kwargs: Any) -> TextractResult:
        raise TextractClientError("simulated FAILED")

    report = run_batch(
        input_prefix="s3://in-bucket/J06/",
        output_prefix="s3://out-bucket/J06_textract/",
        dry_run=False,
        s3_client=fake_s3,
        analyze_fn=fake_analyze,
    )
    assert report.pdf_count_analyzed == 0
    assert report.pdf_count_skipped == 1
    assert "simulated FAILED" in report.skipped_entries[0]["reason"]


# ---------------------------------------------------------------------------
# Projections + writes
# ---------------------------------------------------------------------------


def test_build_per_page_jsonl_one_row_per_page() -> None:
    result = TextractResult(
        s3_bucket="b",
        s3_key="k.pdf",
        page_count=2,
        raw_blocks=(
            {"BlockType": "LINE", "Text": "line1", "Page": 1},
            {"BlockType": "LINE", "Text": "line2", "Page": 2},
        ),
    )
    rows = build_per_page_jsonl(result)
    assert len(rows) == 2
    assert rows[0]["page_index"] == 1
    assert rows[0]["extracted_text"] == "line1"
    assert rows[1]["page_index"] == 2
    assert rows[1]["request_time_llm_call_performed"] is False


def test_build_per_page_jsonl_zero_pages_returns_empty() -> None:
    result = TextractResult(s3_bucket="b", s3_key="k.pdf", page_count=0)
    assert build_per_page_jsonl(result) == []


def test_write_jsonl_emits_one_line_per_row() -> None:
    fake_s3 = _FakeS3()
    uri = write_jsonl(
        [{"a": 1}, {"a": 2}],
        output_uri=S3Uri.parse("s3://out/p/"),
        key_suffix="x.jsonl",
        s3_client=fake_s3,
    )
    assert uri == "s3://out/p/x.jsonl"
    body = fake_s3.put_calls[0]["Body"].decode("utf-8")
    # Two rows -> two newline-terminated lines.
    assert body.count("\n") == 2


def test_write_run_manifest_round_trip() -> None:
    fake_s3 = _FakeS3()
    report = RunReport(
        job_run_id="run-1",
        input_prefix="s3://in/",
        output_prefix="s3://out/",
        budget_usd=DEFAULT_BUDGET_USD,
        per_page_usd=DEFAULT_PER_PAGE_USD,
        warn_threshold=DEFAULT_WARN_THRESHOLD,
        dry_run=True,
    )
    write_run_manifest(report, output_uri=S3Uri.parse("s3://out/"), s3_client=fake_s3)
    body = fake_s3.put_calls[0]["Body"].decode("utf-8")
    loaded = json.loads(body)
    assert loaded["job_run_id"] == "run-1"
    assert loaded["dry_run"] is True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_parse_args_minimum() -> None:
    args = _parse_args(
        [
            "--input-prefix",
            "s3://in/",
            "--output-prefix",
            "s3://out/",
        ]
    )
    assert args.input_prefix == "s3://in/"
    assert args.budget_usd == DEFAULT_BUDGET_USD
    assert args.commit is False


def test_main_dry_run_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_s3 = _FakeS3(pages=[{"Contents": []}])

    def fake_run_batch(**kwargs: Any) -> RunReport:
        return RunReport(
            job_run_id="r",
            input_prefix=kwargs["input_prefix"],
            output_prefix=kwargs["output_prefix"],
            budget_usd=DEFAULT_BUDGET_USD,
            per_page_usd=DEFAULT_PER_PAGE_USD,
            warn_threshold=DEFAULT_WARN_THRESHOLD,
            dry_run=True,
        )

    monkeypatch.setattr("scripts.aws_credit_ops.textract_batch.run_batch", fake_run_batch)
    rc = main(["--input-prefix", "s3://in/", "--output-prefix", "s3://out/"])
    assert rc == 0
    # Avoid unused-var warning for fake_s3.
    assert fake_s3.put_calls == []


def test_main_stop_returns_two(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_batch(**kwargs: Any) -> RunReport:
        rep = RunReport(
            job_run_id="r",
            input_prefix=kwargs["input_prefix"],
            output_prefix=kwargs["output_prefix"],
            budget_usd=DEFAULT_BUDGET_USD,
            per_page_usd=DEFAULT_PER_PAGE_USD,
            warn_threshold=DEFAULT_WARN_THRESHOLD,
            dry_run=True,
        )
        rep.stopped_at_pdf = 1
        rep.stop_reason = "budget"
        return rep

    monkeypatch.setattr("scripts.aws_credit_ops.textract_batch.run_batch", fake_run_batch)
    rc = main(["--input-prefix", "s3://in/", "--output-prefix", "s3://out/"])
    assert rc == 2


# ---------------------------------------------------------------------------
# Misc smoke
# ---------------------------------------------------------------------------


def test_pdf_list_entry_defaults() -> None:
    entry = PdfListEntry(bucket="b", key="k.pdf", size_bytes=10)
    assert entry.estimated_page_count is None
    assert entry.skip_reason is None


# ---------------------------------------------------------------------------
# Magic-byte audit
# ---------------------------------------------------------------------------


def test_classify_magic_bytes_pdf() -> None:
    assert classify_magic_bytes(b"%PDF-1.4") == "application/pdf"


def test_classify_magic_bytes_html_doctype() -> None:
    assert classify_magic_bytes(b"<!DOCTYPE html>") == "text/html"


def test_classify_magic_bytes_html_lowercase_doctype() -> None:
    assert classify_magic_bytes(b"<!doctype html>") == "text/html"


def test_classify_magic_bytes_html_tag() -> None:
    assert classify_magic_bytes(b"<html><head>") == "text/html"


def test_classify_magic_bytes_xml() -> None:
    assert classify_magic_bytes(b"<?xml ver") == "application/xml"


def test_classify_magic_bytes_utf8_bom_html() -> None:
    assert classify_magic_bytes(b"\xef\xbb\xbf<htm") == "text/html"


def test_classify_magic_bytes_zip() -> None:
    assert classify_magic_bytes(b"PK\x03\x04...") == "application/zip"


def test_classify_magic_bytes_empty() -> None:
    assert classify_magic_bytes(b"") == "empty"


def test_classify_magic_bytes_unknown() -> None:
    assert classify_magic_bytes(b"\x00\x01\x02\x03") == "unknown"


def test_magic_bytes_scan_len_is_eight() -> None:
    # Encodes the design contract: 8 bytes is enough to discriminate
    # every prefix in the table without paying for kilobyte reads.
    assert MAGIC_BYTES_SCAN_LEN == 8


def test_audit_magic_bytes_j06_pattern() -> None:
    """Reproduce the 2026-05-16 J06 finding: .bin files = HTML payload."""

    fake = _FakeS3(
        pages=[
            {
                "Contents": [
                    {"Key": "J06/raw/aaa.bin", "Size": 6795},
                    {"Key": "J06/raw/bbb.bin", "Size": 20795},
                    {"Key": "J06/raw/ccc.bin", "Size": 42174},
                ]
            }
        ],
        prefix_bytes={
            "J06/raw/aaa.bin": b"<!DOCTYPE",
            "J06/raw/bbb.bin": b"<html><h",
            "J06/raw/ccc.bin": b"<?xml ve",
        },
    )
    rows = audit_magic_bytes(S3Uri.parse("s3://bkt/J06/raw/"), s3_client=fake)
    types = sorted(r["inferred_content_type"] for r in rows)
    assert types == ["application/xml", "text/html", "text/html"]
    # Every object should have been ranged-GET-fetched once.
    assert len(fake.get_calls) == 3
    for call in fake.get_calls:
        assert call.get("Range") == "bytes=0-7"


def test_audit_magic_bytes_detects_real_pdf() -> None:
    fake = _FakeS3(
        pages=[
            {
                "Contents": [
                    {"Key": "real.pdf", "Size": 100},
                    {"Key": "fake.bin", "Size": 200},
                ]
            }
        ],
        prefix_bytes={
            "real.pdf": b"%PDF-1.5",
            "fake.bin": b"<!DOCTYP",
        },
    )
    rows = audit_magic_bytes(S3Uri.parse("s3://bkt/"), s3_client=fake)
    by_key = {r["key"]: r["inferred_content_type"] for r in rows}
    assert by_key == {
        "real.pdf": "application/pdf",
        "fake.bin": "text/html",
    }


def test_audit_magic_bytes_paginates() -> None:
    fake = _FakeS3(
        pages=[
            {
                "Contents": [{"Key": "p1.bin", "Size": 1}],
                "IsTruncated": True,
                "NextContinuationToken": "tok-a",
            },
            {"Contents": [{"Key": "p2.bin", "Size": 2}]},
        ],
        prefix_bytes={"p1.bin": b"<html><b", "p2.bin": b"<?xml ve"},
    )
    rows = audit_magic_bytes(S3Uri.parse("s3://bkt/"), s3_client=fake)
    assert [r["key"] for r in rows] == ["p1.bin", "p2.bin"]
    assert fake.list_calls[1].get("ContinuationToken") == "tok-a"


def test_audit_magic_bytes_honors_max_objects() -> None:
    fake = _FakeS3(
        pages=[
            {
                "Contents": [
                    {"Key": f"x{i}.bin", "Size": 1} for i in range(50)
                ]
            }
        ],
        prefix_bytes={f"x{i}.bin": b"<!DOCTYP" for i in range(50)},
    )
    rows = audit_magic_bytes(
        S3Uri.parse("s3://bkt/"), s3_client=fake, max_objects=7
    )
    assert len(rows) == 7


def test_main_audit_magic_bytes_branch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: dict[str, Any] = {}

    def fake_audit(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        captured["called"] = True
        return [
            {
                "key": "J06/raw/a.bin",
                "size_bytes": 100,
                "magic_prefix_hex": "3c21444f43545950",
                "inferred_content_type": "text/html",
            },
            {
                "key": "J06/raw/b.bin",
                "size_bytes": 200,
                "magic_prefix_hex": "3c3f786d6c2076",
                "inferred_content_type": "application/xml",
            },
        ]

    def fake_write_jsonl(*args: Any, **kwargs: Any) -> str:
        captured["jsonl_called"] = True
        return "s3://out/audit/foo/magic_bytes.jsonl"

    monkeypatch.setattr(
        "scripts.aws_credit_ops.textract_batch.audit_magic_bytes", fake_audit
    )
    monkeypatch.setattr(
        "scripts.aws_credit_ops.textract_batch.write_jsonl", fake_write_jsonl
    )
    rc = main(
        [
            "--input-prefix",
            "s3://in/J06/raw/",
            "--output-prefix",
            "s3://out/",
            "--audit-magic-bytes",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert captured.get("called") is True
    assert captured.get("jsonl_called") is True
    assert "audit: objects=2" in out
    assert "real_pdfs=0" in out
    assert "AUDIT WARN" in out
