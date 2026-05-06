"""DEEP-28 + DEEP-31 contribution endpoint — unit + behavioural tests.

Spec: tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_28_customer_contribution.md
Spec: tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_31_contribution_form_static.md
Module under test: src/jpintel_mcp/api/contribute.py
Migration: scripts/migrations/wave24_184_contribution_queue.sql

8 cases:
    1. test_submit_ok                     — happy path, row written 'pending'
    2. test_aggregator_url_reject         — INV-04 banlist 400
    3. test_pii_email_reject              — server PII gate 400
    4. test_program_id_mismatch_reject    — FK probe 400
    5. test_houjin_hash_one_way           — server NEVER computes hash
    6. test_rate_limit_5_per_24h          — in-process IP cap 429
    7. test_no_llm_call_negative          — static grep guard
    8. test_anonymous_mode_no_api_key     — no X-API-Key required
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jpintel_mcp.api import contribute
from jpintel_mcp.api.contribute import router as contribute_router


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def autonomath_db(tmp_path: pathlib.Path, monkeypatch) -> pathlib.Path:
    """Build a minimal autonomath.db with `programs` mirror + apply migration 184."""
    db = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL
        );
        INSERT INTO programs (unified_id, primary_name)
            VALUES ('UNI-test-s-1', 'テスト S-tier 補助金');
        INSERT INTO programs (unified_id, primary_name)
            VALUES ('UNI-test-a-1', '青森 認定新規就農者 支援事業');
        """
    )
    conn.commit()
    conn.close()

    # Point settings at the temp DB.
    from jpintel_mcp.config import settings as _settings

    monkeypatch.setattr(_settings, "autonomath_db_path", db)
    return db


@pytest.fixture()
def app(autonomath_db) -> FastAPI:
    """Mount only the contribute router so tests stay fast and don't depend
    on the full create_app() boot sequence."""
    a = FastAPI()
    a.include_router(contribute_router)
    return a


@pytest.fixture()
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_rate_limit() -> None:
    """Each test starts with an empty rate-limit bucket."""
    contribute._reset_rate_limit_store()


def _hash13(houjin: str = "1010401030882") -> str:
    return hashlib.sha256(houjin.encode("utf-8")).hexdigest()


def _valid_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "program_id": "UNI-test-s-1",
        "observed_year": 2025,
        "observed_eligibility_text": (
            "観察された minimum 売上要件 = 3000万円 / FY2024。"
            "業種 JSIC E、 製造業 設備投資 補助金 採択 ケース。"
            "公募要領 §3 に対応、必要書類は事業計画書・決算書 直近 2 期。"
        ),
        "observed_amount_yen": 5000000,
        "observed_outcome": "採択",
        "source_urls": ["https://www.maff.go.jp/j/kanbo/saisei/dummy_program.html"],
        "houjin_bangou_hash": _hash13(),
        "tax_pro_credit_name": None,
        "public_credit_consent": False,
        "consent_acknowledged": True,
        "cohort": "税理士",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. happy path
# ---------------------------------------------------------------------------
def test_submit_ok(client, autonomath_db) -> None:
    r = client.post(
        "/v1/contribute/eligibility_observation",
        json=_valid_payload(),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["review_eta_days"] == 7
    assert body["next_steps_url"].endswith("/contributors/queue-status")
    assert isinstance(body["contribution_id"], int)
    assert body["contribution_id"] > 0

    conn = sqlite3.connect(autonomath_db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT program_id, status, observed_outcome, source_urls, "
            "       houjin_bangou_hash, contributor_api_key_id "
            "FROM contribution_queue WHERE id = ?",
            (body["contribution_id"],),
        ).fetchone()
        assert row is not None
        assert row["status"] == "pending"
        assert row["program_id"] == "UNI-test-s-1"
        assert row["observed_outcome"] == "採択"
        assert row["contributor_api_key_id"] is None  # anonymous
        urls = json.loads(row["source_urls"])
        assert urls and urls[0].startswith("https://www.maff.go.jp/")
        assert re.fullmatch(r"[a-f0-9]{64}", row["houjin_bangou_hash"]) is not None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. aggregator URL reject (INV-04 banlist)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad_url",
    [
        "https://noukaweb.example.com/list",
        "https://hojyokin-portal.jp/article/12345",
        "https://biz.stayway.jp/article/foo",
        "https://stayway.jp/foo",
        "https://subsidies-japan.com/foo",
        "https://en.wikipedia.org/wiki/Subsidy",
    ],
)
def test_aggregator_url_reject(client, bad_url) -> None:
    r = client.post(
        "/v1/contribute/eligibility_observation",
        json=_valid_payload(source_urls=[bad_url]),
    )
    assert r.status_code == 400, r.text
    body = r.json()
    detail = body.get("detail", "")
    assert "aggregator_url_banned" in detail or "banned" in detail.lower(), detail


# ---------------------------------------------------------------------------
# 3. PII reject — server-side scrubber
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "leaked_text,expected_token",
    [
        # email leak
        (
            "観察された 売上要件 等 詳細は contact@example.co.jp に問い合わせ — "
            "業種 JSIC E、 製造業 設備投資 補助金 採択 ケース、 必要書類は事業計画書。",
            "email",
        ),
        # phone leak
        (
            "観察 minimum 売上要件 = 3000万円 / FY2024、 担当 03-1234-5678 まで。"
            "業種 JSIC E、 製造業 設備投資 補助金 採択 ケース、 必要書類は事業計画書。",
            "phone",
        ),
        # マイナンバー (12 桁) leak
        (
            "観察された minimum 売上要件 = 3000万円 FY2024、 個人番号は 123456789012 が含まれる。"
            "業種 JSIC E、 製造業 設備投資 補助金 採択 ケース、 必要書類は事業計画書。",
            "individual_id",
        ),
    ],
)
def test_pii_reject(client, leaked_text, expected_token) -> None:
    r = client.post(
        "/v1/contribute/eligibility_observation",
        json=_valid_payload(observed_eligibility_text=leaked_text),
    )
    assert r.status_code == 400, r.text
    detail = r.json().get("detail", "")
    assert expected_token in detail, f"expected '{expected_token}' in {detail!r}"


# ---------------------------------------------------------------------------
# 4. program_id mismatch — FK probe rejects unknown unified_id
# ---------------------------------------------------------------------------
def test_program_id_mismatch_reject(client) -> None:
    r = client.post(
        "/v1/contribute/eligibility_observation",
        json=_valid_payload(program_id="UNI-does-not-exist"),
    )
    assert r.status_code == 400, r.text
    detail = r.json().get("detail", "")
    assert "program_id" in detail and "not found" in detail.lower(), detail


# ---------------------------------------------------------------------------
# 5. houjin hash is one-way — server REJECTS non-hex / wrong length
# ---------------------------------------------------------------------------
def test_houjin_hash_one_way(client) -> None:
    """Server NEVER computes the SHA-256; it only validates the shape.

    Sending a raw 13-digit 法人番号 (instead of the hex hash) MUST 400 —
    if the server silently re-hashed it, this test would pass with 201
    and the APPI fence would be broken.
    """
    # Raw 13 digits is not 64-char hex — must reject.
    r = client.post(
        "/v1/contribute/eligibility_observation",
        json=_valid_payload(houjin_bangou_hash="1010401030882"),
    )
    assert r.status_code == 422 or r.status_code == 400, r.text

    # Non-hex 64-char string also rejected.
    r2 = client.post(
        "/v1/contribute/eligibility_observation",
        json=_valid_payload(houjin_bangou_hash="z" * 64),
    )
    assert r2.status_code == 400, r2.text
    assert "houjin_bangou_hash" in r2.json().get("detail", "")

    # Static grep — server module must NOT call hashlib.sha256 anywhere
    # near the 法人番号 path. It only validates the shape.
    src = (
        pathlib.Path(__file__).resolve().parents[1]
        / "src"
        / "jpintel_mcp"
        / "api"
        / "contribute.py"
    ).read_text(encoding="utf-8")
    assert "hashlib.sha256(houjin" not in src, "server must not hash 法人番号"
    assert "sha256(houjin" not in src, "server must not hash 法人番号"


# ---------------------------------------------------------------------------
# 6. rate limit — 5 per 24h per IP (in-process bucket)
# ---------------------------------------------------------------------------
def test_rate_limit_5_per_24h(client, autonomath_db) -> None:
    """The 6th submission within the window 429s.

    Note: the rate-limit bucket is keyed on the constant 'anon' inside
    the handler (no Request introspection). 5 successful POSTs fill the
    bucket; the 6th must 429.
    """
    contribute._reset_rate_limit_store()
    for i in range(5):
        r = client.post(
            "/v1/contribute/eligibility_observation",
            json=_valid_payload(observed_amount_yen=10000 + i),
        )
        assert r.status_code == 201, f"#{i + 1}: {r.text}"

    # 6th call should bounce.
    r = client.post(
        "/v1/contribute/eligibility_observation",
        json=_valid_payload(observed_amount_yen=99999),
    )
    assert r.status_code == 429, r.text
    assert "rate limit" in r.json().get("detail", "").lower()


# ---------------------------------------------------------------------------
# 7. LLM 0 — static grep guard
# ---------------------------------------------------------------------------
_FORBIDDEN_IMPORTS = (
    "anthropic",
    "openai",
    "claude_agent_sdk",
    "google.generativeai",
)


def test_no_llm_call_negative() -> None:
    """Static grep: contribute.py + scrubber.js + migration must not
    import any LLM SDK or hard-code an LLM API key env var."""
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    files = [
        repo_root / "src" / "jpintel_mcp" / "api" / "contribute.py",
        repo_root / "site" / "contribute" / "scrubber.js",
        repo_root / "site" / "contribute" / "index.html",
        repo_root / "scripts" / "migrations" / "wave24_184_contribution_queue.sql",
    ]
    for path in files:
        assert path.exists(), f"missing: {path}"
        text = path.read_text(encoding="utf-8")
        for mod in _FORBIDDEN_IMPORTS:
            pat = re.compile(
                rf"^\s*(?:from|import)\s+{re.escape(mod)}\b",
                re.MULTILINE,
            )
            assert not pat.findall(text), f"{path} imports forbidden LLM module {mod!r}"
        for env_key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
            assert env_key not in text, f"{path} references LLM env var {env_key!r}"


# ---------------------------------------------------------------------------
# 8. anonymous mode — no X-API-Key required
# ---------------------------------------------------------------------------
def test_anonymous_mode_no_api_key(client, autonomath_db) -> None:
    """Submitting WITHOUT X-API-Key must succeed; contributor_api_key_id is NULL.

    Per DEEP-31 §7 anonymous mode (rate-limited to 5/24h IP-side), the
    endpoint must not require auth headers.
    """
    r = client.post(
        "/v1/contribute/eligibility_observation",
        json=_valid_payload(),
        # no X-API-Key on purpose
    )
    assert r.status_code == 201, r.text

    # confirm row carries NULL contributor_api_key_id
    conn = sqlite3.connect(autonomath_db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT contributor_api_key_id FROM contribution_queue WHERE id = ?",
            (r.json()["contribution_id"],),
        ).fetchone()
        assert row is not None
        assert row["contributor_api_key_id"] is None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Bonus: consent_acknowledged gate
# ---------------------------------------------------------------------------
def test_consent_unchecked_rejects(client) -> None:
    r = client.post(
        "/v1/contribute/eligibility_observation",
        json=_valid_payload(consent_acknowledged=False),
    )
    assert r.status_code == 400, r.text
    assert "consent" in r.json().get("detail", "").lower()


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
