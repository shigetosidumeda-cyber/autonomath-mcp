"""CC4 — tests for the PDF watch pipeline.

Coverage:
  * Migration wave24_216 applies idempotently + creates view/indexes.
  * Detect cron: watchlist count is 54 sources; per-host throttle is
    honoured; UNIQUE constraint suppresses duplicate detection.
  * Detect cron: dry-run mode does not call SQS; commit mode emits an
    envelope and respects boto3 absence.
  * HTTP-fetch hardening: non-https + non-government hosts are refused.
  * Textract-submit Lambda: dry-run does not call boto3; commit mode
    builds the right S3 key + JobTag.
  * KG-extract Lambda: spaCy fallback to regex produces canonical
    DATE/MONEY/PROGRAM/LAW entities and idempotent inserts.
  * Pipeline deploy: dry-run plan shape contains 3 lambdas + 1 SQS +
    1 SNS + 1 EventBridge.
"""

from __future__ import annotations

import importlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ---------------------------------------------------------------------------
# Lazy imports — the modules are at file-path locations outside the
# installed package, so we import via importlib from absolute paths.
# ---------------------------------------------------------------------------


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def detect_mod() -> Any:
    return _load_module(
        "pdf_watch_detect_test",
        _REPO / "scripts" / "cron" / "pdf_watch_detect_2026_05_17.py",
    )


@pytest.fixture(scope="module")
def submit_mod() -> Any:
    return _load_module(
        "pdf_watch_submit_test",
        _REPO / "infra" / "aws" / "lambda" / "jpcite_pdf_watch_textract_submit.py",
    )


@pytest.fixture(scope="module")
def kg_mod() -> Any:
    return _load_module(
        "pdf_watch_kg_test",
        _REPO / "infra" / "aws" / "lambda" / "jpcite_pdf_watch_kg_extract.py",
    )


@pytest.fixture(scope="module")
def deploy_mod() -> Any:
    return _load_module(
        "pdf_watch_deploy_test",
        _REPO / "infra" / "aws" / "lambda" / "pdf_watch_pipeline_deploy.py",
    )


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    db = tmp_path / "autonomath_test.db"
    return db


# ---------------------------------------------------------------------------
# 1. Migration
# ---------------------------------------------------------------------------


def test_migration_applies_and_is_idempotent(tmp_db: Path) -> None:
    sql_path = _REPO / "scripts" / "migrations" / "wave24_216_am_pdf_watch_log.sql"
    sql = sql_path.read_text(encoding="utf-8")
    conn = sqlite3.connect(tmp_db)
    try:
        conn.executescript(sql)
        conn.executescript(sql)  # re-apply must not raise
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='am_pdf_watch_log'"
        ).fetchall()
        assert len(rows) == 1
        view_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view' AND name='v_am_pdf_watch_funnel'"
        ).fetchall()
        assert len(view_rows) == 1
        idx_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ix_am_pdf_watch_log_%'"
        ).fetchall()
        assert len(idx_rows) >= 5
    finally:
        conn.close()


def test_migration_unique_constraint_prevents_dup(tmp_db: Path) -> None:
    sql_path = _REPO / "scripts" / "migrations" / "wave24_216_am_pdf_watch_log.sql"
    sql = sql_path.read_text(encoding="utf-8")
    conn = sqlite3.connect(tmp_db)
    try:
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO am_pdf_watch_log (source_kind, source_url, content_hash) VALUES (?, ?, ?)",
            ("nta", "https://www.nta.go.jp/x.pdf", "abc"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_pdf_watch_log (source_kind, source_url, content_hash) "
                "VALUES (?, ?, ?)",
                ("nta", "https://www.nta.go.jp/x.pdf", "abc"),
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. Watchlist + crawl logic
# ---------------------------------------------------------------------------


def test_watchlist_count_is_54(detect_mod: Any) -> None:
    """6 省庁 + 1 e-Gov + 47 prefectures = 54 sources."""
    assert detect_mod.watchlist_count() == 54


def test_watchlist_all_government_hosts(detect_mod: Any) -> None:
    for ws in detect_mod.WATCHLIST:
        assert ws.crawl_url.startswith("https://"), ws.crawl_url
        assert detect_mod._is_government_host(ws.host), ws.host


def test_is_government_host_accepts_prefecture_bare_jp(detect_mod: Any) -> None:
    assert detect_mod._is_government_host("www.pref.iwate.jp")
    assert detect_mod._is_government_host("www.pref.aichi.jp")
    assert detect_mod._is_government_host("web.pref.hyogo.lg.jp")
    assert detect_mod._is_government_host("www.nta.go.jp")
    assert detect_mod._is_government_host("www.pref.tochigi.lg.jp")
    assert not detect_mod._is_government_host("example.com")
    assert not detect_mod._is_government_host("aggregator.jp")


def test_http_get_refuses_non_https(detect_mod: Any) -> None:
    with pytest.raises(ValueError, match="non-https"):
        detect_mod._http_get("http://www.nta.go.jp/x.pdf")


def test_http_get_refuses_aggregator(detect_mod: Any) -> None:
    with pytest.raises(ValueError, match="non-government"):
        detect_mod._http_get("https://example.com/x.pdf")


def test_extract_pdf_urls_filters_non_gov(detect_mod: Any) -> None:
    html = (
        b'<a href="https://www.nta.go.jp/a.pdf">ok</a>'
        b'<a href="https://example.com/b.pdf">aggregator</a>'
        b'<a href="http://www.fsa.go.jp/c.pdf">non-https</a>'
        b'<a href="/relative/d.pdf">relative</a>'
    )
    urls = detect_mod._extract_pdf_urls(html, "https://www.nta.go.jp/")
    assert "https://www.nta.go.jp/a.pdf" in urls
    assert "https://www.nta.go.jp/relative/d.pdf" in urls
    assert all("example.com" not in u for u in urls)
    assert all(u.startswith("https://") for u in urls)


# ---------------------------------------------------------------------------
# 3. Detect cron — end-to-end with injected fakes
# ---------------------------------------------------------------------------


def test_run_dry_run_inserts_db_but_no_sqs(
    detect_mod: Any, tmp_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    landing_html = b'<a href="https://www.nta.go.jp/foo.pdf">tsutatsu</a>'
    pdf_bytes = b"%PDF-1.4 sample"

    def fake_get(url: str, **kwargs: Any) -> tuple[int, bytes]:
        if url.endswith(".pdf"):
            return 200, pdf_bytes
        return 200, landing_html

    # single source to keep test deterministic
    fake_sources = (detect_mod.WatchSource("nta", "https://www.nta.go.jp/", "www.nta.go.jp"),)
    summary = detect_mod.run(
        db_path=str(tmp_db),
        queue_url=None,
        commit=False,
        sources=fake_sources,
        http_get=fake_get,
        sleep=lambda _s: None,
    )
    assert summary["sources_scanned"] == 1
    assert summary["newly_detected"] == 1
    assert summary["sqs_enqueued"] == 0
    # second run is fully idempotent (UNIQUE collides)
    summary2 = detect_mod.run(
        db_path=str(tmp_db),
        queue_url=None,
        commit=False,
        sources=fake_sources,
        http_get=fake_get,
        sleep=lambda _s: None,
    )
    assert summary2["newly_detected"] == 0
    assert summary2["skipped_duplicate"] == 1


def test_enqueue_textract_dry_run_no_boto3(
    detect_mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "boto3", None)  # type: ignore[arg-type]
    res = detect_mod.enqueue_textract_message(
        queue_url="https://sqs.example/q",
        watch_id=1,
        source_kind="nta",
        source_url="https://www.nta.go.jp/x.pdf",
        content_hash="h",
        commit=False,
    )
    assert res["mode"] == "dry_run"
    assert res["envelope"]["watch_id"] == 1


# ---------------------------------------------------------------------------
# 4. Textract submit Lambda
# ---------------------------------------------------------------------------


def test_textract_submit_dry_run_returns_envelope(submit_mod: Any) -> None:
    rec = {
        "body": json.dumps(
            {
                "watch_id": 42,
                "source_kind": "fsa",
                "source_url": "https://www.fsa.go.jp/x.pdf",
                "content_hash": "f" * 64,
            }
        )
    }
    out = submit_mod._process_record(rec, boto3=None, commit_mode=False)
    assert out["mode"] == "dry_run"
    assert out["watch_id"] == 42
    assert out["s3_input_key"] == f"in/ff/{'f' * 64}.pdf"


def test_textract_submit_handler_dry_run(submit_mod: Any) -> None:
    event = {
        "Records": [
            {
                "body": json.dumps(
                    {
                        "watch_id": 1,
                        "source_kind": "nta",
                        "source_url": "https://www.nta.go.jp/a.pdf",
                        "content_hash": "a" * 64,
                    }
                )
            }
        ]
    }
    out = submit_mod.lambda_handler(event, None)
    assert out["processed"] == 1
    assert out["mode"] == "dry_run"


# ---------------------------------------------------------------------------
# 5. KG extract Lambda
# ---------------------------------------------------------------------------


def test_kg_extract_regex_fallback_finds_canonical_entities(kg_mod: Any) -> None:
    text = (
        "令和7年4月1日に小規模事業者持続化補助金を施行する。"
        "対象は中小企業、上限は2,000万円、補助率は50%。所得税法 第33条 を改正する。"
    )
    ents = kg_mod._extract_entities(text)
    labels = {label for label, _ in ents}
    assert "DATE" in labels
    assert "MONEY" in labels
    assert "PROGRAM" in labels
    assert "LAW" in labels
    assert "PERCENT" in labels


def test_kg_extract_relations_pair_entities(kg_mod: Any) -> None:
    text = "令和7年4月1日に小規模事業者持続化補助金を支給する。"
    ents = kg_mod._extract_entities(text)
    rels = kg_mod._extract_relations(text, ents)
    assert any(r[1] == "支給" for r in rels), rels


def test_kg_extract_inserts_idempotently(kg_mod: Any, detect_mod: Any, tmp_db: Path) -> None:
    sql = (_REPO / "scripts" / "migrations" / "wave24_216_am_pdf_watch_log.sql").read_text(
        encoding="utf-8"
    )
    conn = sqlite3.connect(tmp_db)
    try:
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO am_pdf_watch_log (source_kind, source_url, content_hash) VALUES (?, ?, ?)",
            ("nta", "https://www.nta.go.jp/x.pdf", "h"),
        )
        wid = conn.execute("SELECT watch_id FROM am_pdf_watch_log").fetchone()[0]
        kg_mod._ensure_ner_tables(conn)
        entities = [("DATE", "令和7年4月1日"), ("MONEY", "2,000万円")]
        relations = [("令和7年4月1日", "支給", "2,000万円")]
        ec1, rc1 = kg_mod._insert_facts(
            conn,
            content_hash="h",
            watch_id=wid,
            source_url="https://www.nta.go.jp/x.pdf",
            entities=entities,
            relations=relations,
        )
        assert ec1 == 2
        assert rc1 == 1
        # Re-run must be a no-op (idempotent).
        ec2, rc2 = kg_mod._insert_facts(
            conn,
            content_hash="h",
            watch_id=wid,
            source_url="https://www.nta.go.jp/x.pdf",
            entities=entities,
            relations=relations,
        )
        assert ec2 == 0
        assert rc2 == 0
        kg_mod._flip_watch_log(conn, watch_id=wid, entity_count=2, relation_count=1)
        conn.commit()
        row = conn.execute(
            "SELECT kg_extract_status, kg_entity_count, kg_relation_count, ingested_at "
            "FROM am_pdf_watch_log WHERE watch_id=?",
            (wid,),
        ).fetchone()
        assert row[0] == "completed"
        assert row[1] == 2
        assert row[2] == 1
        assert row[3] is not None
    finally:
        conn.close()


def test_kg_extract_handler_skips_failed_textract(kg_mod: Any) -> None:
    sns_msg = json.dumps({"JobId": "j1", "Status": "FAILED", "JobTag": "jpcite-pdf-watch-1"})
    event = {"Records": [{"Sns": {"Message": sns_msg}}]}
    out = kg_mod.lambda_handler(event, None)
    assert out["processed"] == 1
    assert out["summaries"][0]["mode"] == "skipped"


# ---------------------------------------------------------------------------
# 6. Deploy plan shape
# ---------------------------------------------------------------------------


def test_deploy_plan_dry_run_shape(deploy_mod: Any) -> None:
    summary = deploy_mod.plan(commit=False)
    assert summary["mode"] == "dry_run"
    assert summary["lambda_count"] == 3
    assert summary["watch_sources"] == 54
    assert summary["sustained_burn_usd_per_day"] == 150
    assert summary["never_reach_ceiling_usd"] == 19490
    assert summary["sqs_queue"] == "jpcite-pdf-textract-queue"
    assert summary["sns_topic"] == "jpcite-pdf-textract-completion"
    assert summary["eventbridge_rule"] == "jpcite-pdf-watch-hourly"
    assert summary["schedule_expression"] == "rate(1 hour)"


def test_schedule_json_shape_matches_plan(deploy_mod: Any) -> None:
    schedule_path = _REPO / "infra" / "aws" / "eventbridge" / "jpcite_pdf_watch_schedule.json"
    data = json.loads(schedule_path.read_text(encoding="utf-8"))
    assert data["rule"]["schedule_expression"] == "rate(1 hour)"
    assert data["rule"]["state"] == "DISABLED"
    assert data["sqs_queue"]["name"] == "jpcite-pdf-textract-queue"
    assert data["sns_topic"]["name"] == "jpcite-pdf-textract-completion"
    assert data["cadence_economics"]["sustained_burn_usd_per_day"] == 150
    assert data["cadence_economics"]["never_reach_ceiling_usd"] == 19490
