"""W3-12 UC7 — `get_program_narrative(reading_level=...)` rule-based 平易日本語.

Verifies the LINE 中小企業向け blocker fix: `_get_program_narrative_impl`
gained a `reading_level: Literal["standard","plain"]` argument that
post-processes `body_text` through `ingest.plain_japanese_dict` (NO LLM
call — pure str.replace per `feedback_no_operator_llm_api`).

Tests:
  1. Default (reading_level absent) returns the corpus body untouched
     and echoes `_reading_level: "standard"`.
  2. `reading_level="standard"` is identical to the default.
  3. `reading_level="plain"` substitutes 補助率 / 公募要領 / 経営強化税制
     / 採択 / 担保 etc. per the dict and echoes `_reading_level: "plain"`.
  4. Plain mode preserves non-jargon sentences verbatim.
  5. Section-specific lookup (section='overview') honours plain mode too.
  6. Invalid `reading_level` returns an `invalid_enum` error envelope.
  7. `reading_level='plain'` with `lang='en'` is rejected (en bodies are
     not in the dict's coverage).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from jpintel_mcp.ingest.plain_japanese_dict import (
    _PLAIN_REPLACEMENTS,
    replace_plain_japanese,
)
from jpintel_mcp.mcp.autonomath_tools import wave24_tools_first_half as w24a

# --------------------------------------------------------------------------- #
# In-memory autonomath.db fixture (just am_program_narrative).
# --------------------------------------------------------------------------- #

_PROGRAM_ID = "prog-uc7-001"

# Two ja sections + one en section. Body intentionally laden with jargon
# the dict knows about ('補助率', '公募要領', '経営強化税制', '採択',
# '担保', 'ものづくり補助金', '補助上限額') and one neutral sentence that
# must survive plain-mode untouched.
_BODY_OVERVIEW_JA = (
    "本制度はものづくり補助金の一種であり、"
    "補助率は通常二分の一、補助上限額は1,000万円です。"
    "公募要領を読んでから申込みしてください。"
)
_BODY_ELIGIBILITY_JA = (
    "経営強化税制の認定を受けた中小企業者が対象です。"
    "担保・保証人は不要ですが採択後は実績報告が必要です。"
    "詳細は別冊を参照してください。"
)
_BODY_OVERVIEW_EN = "This program supports SME capital investment."

_NEUTRAL_TAIL = "詳細は別冊を参照してください。"


@pytest.fixture()
def patched_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[sqlite3.Connection]:
    """Spin up an in-memory autonomath.db with am_program_narrative seeded."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE am_program_narrative (
          narrative_id INTEGER PRIMARY KEY AUTOINCREMENT,
          program_id TEXT NOT NULL,
          lang TEXT NOT NULL,
          section TEXT NOT NULL,
          body_text TEXT NOT NULL,
          source_url_json TEXT,
          model_id TEXT,
          generated_at TEXT,
          literal_quote_check_passed INTEGER,
          is_active INTEGER,
          content_hash TEXT
        )
        """
    )
    rows = [
        (
            _PROGRAM_ID,
            "ja",
            "overview",
            _BODY_OVERVIEW_JA,
            '["https://example.gov.jp/x"]',
            "claude-opus-4",
            "2026-05-04T00:00:00Z",
            1,
            1,
            "deadbeef",
        ),
        (
            _PROGRAM_ID,
            "ja",
            "eligibility",
            _BODY_ELIGIBILITY_JA,
            '["https://example.gov.jp/y"]',
            "claude-opus-4",
            "2026-05-04T00:00:00Z",
            1,
            1,
            "cafef00d",
        ),
        (
            _PROGRAM_ID,
            "en",
            "overview",
            _BODY_OVERVIEW_EN,
            '["https://example.gov.jp/x"]',
            "claude-opus-4",
            "2026-05-04T00:00:00Z",
            1,
            1,
            "feedface",
        ),
    ]
    conn.executemany(
        """
        INSERT INTO am_program_narrative
          (program_id, lang, section, body_text, source_url_json,
           model_id, generated_at, literal_quote_check_passed,
           is_active, content_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()

    monkeypatch.setattr(w24a, "connect_autonomath", lambda: conn)
    try:
        yield conn
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_default_reading_level_is_standard(patched_db: sqlite3.Connection) -> None:
    out = w24a._get_program_narrative_impl(
        program_id=_PROGRAM_ID,
        section="overview",
        lang="ja",
    )
    assert out["reading_level"] == "standard"
    assert out["_reading_level"] == "standard"
    assert out["total"] == 1
    body = out["results"][0]["body_text"]
    # Untouched corpus — jargon survives verbatim.
    assert body == _BODY_OVERVIEW_JA
    assert "補助率" in body
    assert "公募要領" in body


def test_explicit_standard_matches_default(patched_db: sqlite3.Connection) -> None:
    default_out = w24a._get_program_narrative_impl(
        program_id=_PROGRAM_ID,
        section="overview",
        lang="ja",
    )
    explicit_out = w24a._get_program_narrative_impl(
        program_id=_PROGRAM_ID,
        section="overview",
        lang="ja",
        reading_level="standard",
    )
    assert default_out["results"][0]["body_text"] == explicit_out["results"][0]["body_text"]
    assert explicit_out["_reading_level"] == "standard"


def test_plain_mode_substitutes_per_dict(patched_db: sqlite3.Connection) -> None:
    out = w24a._get_program_narrative_impl(
        program_id=_PROGRAM_ID,
        section="overview",
        lang="ja",
        reading_level="plain",
    )
    assert out["reading_level"] == "plain"
    assert out["_reading_level"] == "plain"
    body = out["results"][0]["body_text"]
    # Jargon must be gone.
    assert "補助率" not in body
    assert "公募要領" not in body
    assert "ものづくり補助金" not in body
    assert "補助上限額" not in body
    # Plain replacements must be present.
    assert "お金の半分くれます" in body
    assert "申込みの説明書" in body
    assert "新しい機械や設備を買うお金を助ける制度" in body
    assert "もらえるお金の最大の金額" in body


def test_plain_mode_preserves_non_jargon_sentence(
    patched_db: sqlite3.Connection,
) -> None:
    out = w24a._get_program_narrative_impl(
        program_id=_PROGRAM_ID,
        section="eligibility",
        lang="ja",
        reading_level="plain",
    )
    body = out["results"][0]["body_text"]
    # Neutral tail (no dict entry hits) is preserved verbatim.
    assert _NEUTRAL_TAIL in body
    # Eligibility-side jargon swapped per dict.
    assert "経営強化税制" not in body
    assert "会社を強くするための税金まけ制度" in body
    assert "担保" not in body
    assert "返せないときに代わりに渡す財産" in body
    assert "採択" not in body
    assert "申込みが選ばれる" in body


def test_section_all_plain_mode(patched_db: sqlite3.Connection) -> None:
    out = w24a._get_program_narrative_impl(
        program_id=_PROGRAM_ID,
        section="all",
        lang="ja",
        reading_level="plain",
    )
    assert out["reading_level"] == "plain"
    assert out["_reading_level"] == "plain"
    assert out["total"] == 2  # overview + eligibility (no application_flow / pitfalls)
    bodies_joined = "\n".join(r["body_text"] for r in out["results"])
    assert "補助率" not in bodies_joined
    assert "経営強化税制" not in bodies_joined
    assert "お金の半分くれます" in bodies_joined
    assert "会社を強くするための税金まけ制度" in bodies_joined


def test_invalid_reading_level_returns_error(patched_db: sqlite3.Connection) -> None:
    out = w24a._get_program_narrative_impl(
        program_id=_PROGRAM_ID,
        section="overview",
        lang="ja",
        reading_level="ultra-plain",  # type: ignore[arg-type]
    )
    assert out.get("error") is not None
    assert out["error"]["code"] == "invalid_enum"
    assert out["error"]["field"] == "reading_level"


def test_plain_mode_rejects_lang_en(patched_db: sqlite3.Connection) -> None:
    out = w24a._get_program_narrative_impl(
        program_id=_PROGRAM_ID,
        section="overview",
        lang="en",
        reading_level="plain",
    )
    assert out.get("error") is not None
    assert out["error"]["code"] == "invalid_enum"
    assert out["error"]["field"] == "reading_level"


def test_dict_helper_is_idempotent_on_plain_text() -> None:
    """`replace_plain_japanese` on already-plain text is a no-op."""
    plain = "今日はいい天気です。"
    assert replace_plain_japanese(plain) == plain
    assert replace_plain_japanese(None) == ""
    assert replace_plain_japanese("") == ""


def test_dict_has_required_uc7_entries() -> None:
    """W3-12 UC7 acceptance — these jargon→plain pairs must ship."""
    keys = {jargon for jargon, _plain in _PLAIN_REPLACEMENTS}
    for required in ("補助率", "公募要領", "経営強化税制"):
        assert required in keys, f"UC7 dict missing {required}"
    mapping = dict(_PLAIN_REPLACEMENTS)
    assert mapping["補助率"] == "お金の半分くれます"
    assert mapping["公募要領"] == "申込みの説明書"
