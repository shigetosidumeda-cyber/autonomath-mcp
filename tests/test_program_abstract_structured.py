"""Tests for program_abstract_structured — R7 multilingual abstract MCP tool.

3 mandatory cases per the design doc
(analysis_wave18/_r7_multilingual_abstracts_2026-04-25.md):

  1. foreign_employer audience + UNI-16b8d86302 → JSON shape with the
     full closed-enum surface populated.
  2. invalid audience enum → error envelope with code='invalid_enum'
     (the MCP-layer 422 equivalent — we return the canonical envelope
     rather than raising so the customer LLM can pattern-match).
  3. i18n_hints.official_name_must_keep_ja=true is present (and
     legal_id is verbatim Japanese / not translated).

Run::

    .venv/bin/python -m pytest tests/test_program_abstract_structured.py -x --tb=short

Uses the conftest-seeded tmp jpintel.db and inserts a single
``UNI-16b8d86302`` foreign_employer-audience row whose
``enriched_json`` mirrors the production sample (mhlw.go.jp 人材確保等
支援助成金 — 外国人労働者就労環境整備助成コース). This keeps the test
hermetic — no real DB dependency, no mocking (per CLAUDE.md "Never
mock the DB in integration tests").
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

# server must be imported first so `mcp` is bound before tool decoration.
from jpintel_mcp.mcp import server  # noqa: F401
from jpintel_mcp.mcp.autonomath_tools.multilingual_abstract_tool import (
    _AUDIENCE_VALUES,
    _program_abstract_structured_impl,
)

if TYPE_CHECKING:
    from pathlib import Path

_SAMPLE_PROGRAM_ID = "UNI-16b8d86302"
_SAMPLE_NAME = "人材確保等支援助成金（外国人労働者就労環境整備助成コース）"
_SAMPLE_LEGAL = "雇用保険法 (厚生労働省) - 雇用保険二事業 (事業主負担分)"
_SAMPLE_SOURCE_URL = (
    "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/gaikokujin.html"
)


def _build_enriched_json() -> str:
    """Mirror the production enriched_json shape for UNI-16b8d86302
    minimally — only the fields the tool reads (extraction.basic +
    classification + money + schedule_v3 + documents_v3 + contacts_v3 +
    obligations + ineligibility_v3 + _meta.source_urls)."""
    return json.dumps(
        {
            "_meta": {
                "program_id": _SAMPLE_PROGRAM_ID,
                "program_name": _SAMPLE_NAME,
                "source_urls": [_SAMPLE_SOURCE_URL],
            },
            "extraction": {
                "classification": {
                    "_source_ref": {
                        "url": _SAMPLE_SOURCE_URL,
                        "excerpt": (
                            "外国人労働者の職場定着を支援するため、"
                            "企業が実施する就労環境整備措置に対して助成"
                        ),
                    }
                },
                "basic": {
                    "正式名称": _SAMPLE_NAME,
                    "根拠法": _SAMPLE_LEGAL,
                },
                "money": {
                    "amount_max_man_yen": 80,
                    "amount_min_man_yen": 20,
                    "amount_detail": "1制度導入につき20万円、上限80万円",
                },
                "schedule_v3": {
                    "start_date": None,
                    "end_date": None,
                    "fiscal_year": 2025,
                    "cycle": "rolling",
                },
                "documents_v3": [
                    {
                        "name": "就労環境整備計画認定申請書",
                        "required": True,
                        "format": "docx",
                        "template_url": _SAMPLE_SOURCE_URL,
                    },
                    {
                        "name": "支給申請書",
                        "required": True,
                        "format": "docx",
                        "template_url": None,
                    },
                ],
                "contacts_v3": [
                    {
                        "office_name": "都道府県労働局 / ハローワーク",
                        "applicable_region": "全国",
                    }
                ],
                "obligations": [
                    {
                        "kind": "retention_target",
                        "label": ("計画期間終了後の外国人労働者離職率を15%以下に維持"),
                        "legal_basis": "雇用保険法施行規則",
                    }
                ],
                "ineligibility_v3": {
                    "applicant_types_excluded": [
                        {
                            "label": "corporation",
                            "label_raw": "外国人労働者を雇用していない事業主",
                            "reason": "雇用が必須",
                        }
                    ]
                },
                "application_plan": {
                    "eligibility_clauses": [
                        "外国人労働者を雇用している事業主",
                        "雇用保険二事業財源 (事業主負担)",
                    ]
                },
            },
        },
        ensure_ascii=False,
    )


@pytest.fixture(scope="module")
def seeded_foreign_employer_program(seeded_db: Path) -> Path:
    """Insert UNI-16b8d86302 (the design-doc anchor row) into the
    conftest-seeded tmp jpintel.db. Idempotent across the module."""
    conn = sqlite3.connect(seeded_db)
    try:
        already = conn.execute(
            "SELECT 1 FROM programs WHERE unified_id = ?",
            (_SAMPLE_PROGRAM_ID,),
        ).fetchone()
        if already:
            return seeded_db
        now = datetime.now(UTC).isoformat()
        conn.execute(
            """INSERT INTO programs(
                unified_id, primary_name, aliases_json,
                authority_level, authority_name, prefecture, municipality,
                program_kind, official_url,
                amount_max_man_yen, amount_min_man_yen, subsidy_rate,
                trust_level, tier, coverage_score, gap_to_tier_s_json,
                a_to_j_coverage_json,
                excluded, exclusion_reason,
                crop_categories_json, equipment_category,
                target_types_json, funding_purpose_json,
                amount_band, application_window_json,
                enriched_json, source_mentions_json, updated_at,
                source_url, source_fetched_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                _SAMPLE_PROGRAM_ID,
                _SAMPLE_NAME,
                None,
                "national",
                "厚生労働省",
                None,
                None,
                "助成金",
                _SAMPLE_SOURCE_URL,
                80.0,
                20.0,
                None,
                None,
                "A",
                None,
                None,
                None,
                0,
                None,
                None,
                None,
                json.dumps(["corporation"], ensure_ascii=False),
                json.dumps(["labor", "training"], ensure_ascii=False),
                "under_100",
                None,
                _build_enriched_json(),
                None,
                now,
                _SAMPLE_SOURCE_URL,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return seeded_db


# ---------------------------------------------------------------------------
# Case 1 — foreign_employer audience + UNI-16b8d86302 → JSON shape.
# ---------------------------------------------------------------------------


def test_foreign_employer_audience_returns_full_shape(
    seeded_foreign_employer_program: Path,
) -> None:
    """foreign_employer audience must return all top-level keys + a
    business_type_enum populated from target_types_json."""
    out = _program_abstract_structured_impl(
        program_id=_SAMPLE_PROGRAM_ID,
        audience="foreign_employer",
    )

    # Not an error envelope.
    assert "error" not in out, out

    # Top-level shape (matches design doc).
    expected_keys = {
        "program_id",
        "official_name_ja",
        "legal_id",
        "summary_ja",
        "audience",
        "eligibility",
        "amount",
        "deadline",
        "documents",
        "contact_route",
        "i18n_hints",
        "source_urls",
        "_disclaimer",
    }
    assert expected_keys.issubset(out.keys()), out.keys()

    # ID + audience echo.
    assert out["program_id"] == _SAMPLE_PROGRAM_ID
    assert out["audience"] == "foreign_employer"

    # Eligibility carries the foreign_employer-specific booleans.
    eligibility = out["eligibility"]
    assert eligibility["business_type_enum"] == ["corporation"]
    assert eligibility["must_employ_foreign_workers"] is True
    assert eligibility["must_join_employment_insurance"] is True

    # Amount in JPY 万円, currency closed-enum.
    assert out["amount"]["currency"] == "JPY"
    assert out["amount"]["max_man_yen"] == 80
    assert out["amount"]["min_man_yen"] == 20

    # Deadline cycle is closed-enum (rolling for this program).
    assert out["deadline"]["cycle"] == "rolling"
    assert out["deadline"]["fiscal_year"] == 2025

    # contact_route closed-enum, resolved from contacts_v3.
    assert out["contact_route"] == "prefectural_labor_bureau"

    # Documents flattened to ≤5 entries with closed shape.
    assert len(out["documents"]) >= 1
    for d in out["documents"]:
        assert set(d.keys()) == {"name_ja", "format", "template_url"}

    # source_urls are gov-issued primary references.
    assert any("mhlw.go.jp" in u for u in out["source_urls"])


# ---------------------------------------------------------------------------
# Case 2 — invalid audience enum → error envelope, no DB read needed.
# ---------------------------------------------------------------------------


def test_invalid_audience_returns_invalid_enum_error(
    seeded_foreign_employer_program: Path,
) -> None:
    """Audience outside the 5-value closed enum must return the canonical
    error envelope with code='invalid_enum' (MCP-layer 422 equivalent)."""
    out = _program_abstract_structured_impl(
        program_id=_SAMPLE_PROGRAM_ID,
        audience="not_a_real_audience",
    )

    assert "error" in out, out
    assert out["error"]["code"] == "invalid_enum"
    assert out["error"]["field"] == "audience"
    # Exhaustive allowed_values surface so customer LLM can self-correct.
    assert set(out["error"]["allowed_values"]) == set(_AUDIENCE_VALUES)
    assert out["error"]["severity"] == "hard"
    # Canonical envelope keys present even on error.
    assert out["total"] == 0
    assert out["results"] == []


# ---------------------------------------------------------------------------
# Case 3 — i18n_hints.official_name_must_keep_ja=true must be present;
# legal_id and official_name_ja must remain verbatim Japanese.
# ---------------------------------------------------------------------------


def test_i18n_hints_force_official_name_ja_verbatim(
    seeded_foreign_employer_program: Path,
) -> None:
    """The customer LLM must be told to NOT translate official_name_ja or
    legal_id. We assert the flag + the JP characters round-trip."""
    out = _program_abstract_structured_impl(
        program_id=_SAMPLE_PROGRAM_ID,
        audience="foreign_employer",
    )
    assert "error" not in out

    hints = out["i18n_hints"]
    # 音訳 mismatch 抑止 — translator MUST keep these verbatim.
    assert hints["official_name_must_keep_ja"] is True
    assert hints["legal_id_must_keep_ja"] is True
    assert hints["translate_summary"] is True
    # Render targets are the 6 launch languages.
    for lang in ("en", "vi", "id", "th", "zh-CN", "fil"):
        assert lang in hints["render_languages_supported"]

    # JP-character round-trip — proves the response carries the original
    # Japanese (not a romanized copy a translator could mistakenly produce).
    assert "人材確保" in out["official_name_ja"]
    assert "助成金" in out["official_name_ja"]
    assert out["legal_id"] is not None
    assert "雇用保険法" in out["legal_id"]
