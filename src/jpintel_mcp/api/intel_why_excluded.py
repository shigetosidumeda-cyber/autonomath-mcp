"""POST /v1/intel/why_excluded — eligibility-failure reasoning + remediation.

Why this exists
---------------
A customer LLM that asks ``intel/match`` or ``programs/{id}/eligibility_predicate``
gets a yes/no surface but no insight into *which* predicate axis failed,
*how blocking* the failure is, or *what to do about it*. The W26-6 predicate
cache (``am_program_eligibility_predicate_json``) carries enough structure
to answer all three in one POST — this endpoint does the cross-join +
diff + remediation generation server-side so the agent never has to fan
out four follow-up calls (predicate fetch / houjin fetch / programs read
/ alternative recommend).

Input axes (any subset; missing axis → "unknown" verdict, NOT a fail):
    * program_id: string (jpi_programs.unified_id)
    * houjin: dict — id (法人番号 with/without 'T' prefix) OR explicit
      attributes {capital, employees, industry, founded_year, prefecture,
      jsic, certifications[]}. When `id` is supplied we hydrate the rest
      from autonomath.db (am_entities corp.* + houjin_master); explicit
      values always win on collision.

Output (compact_envelope wrapped, billing_unit=1):
    * eligible: bool — True iff every blocking predicate passed
    * match_score: float (0..1) — passed_axes / evaluated_axes
    * predicate_evaluation:
        - passed: list of {predicate, expected, actual}
        - failed: list of {predicate, expected, actual, blocking, remediation}
    * remediation_steps: list of {step, est_difficulty, est_timeline_days, source_url}
    * alternative_programs: list of {program_id, name, match_score, relax_reason}
    * _disclaimer + corpus_snapshot_id + audit_seal (paid keys)

Hard constraints (CLAUDE.md / `feedback_no_operator_llm_api`)
-------------------------------------------------------------
NO LLM call inside this endpoint. Pure SQLite + Python diff + rules.
Remediation copy is rule-based per failed-axis kind (capital reduction,
industry pivot, prefecture relocation, etc.) — never generated text.

Sensitive surface (行政書士法 §1の2 fence) — final 受給可否判定 belongs to
qualified 行政書士 / 中小企業診断士. The disclaimer text mirrors the
`/v1/intel/probability_radar` fence verbatim so a customer LLM can drop
both into the same compliance template.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.intel_why_excluded")

router = APIRouter(prefix="/v1/intel", tags=["intel"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# JIS X 0401 prefecture name → 2-digit code (matches predicate.prefecture_jis).
PREFECTURE_JIS: dict[str, str] = {
    "北海道": "01",
    "青森県": "02",
    "岩手県": "03",
    "宮城県": "04",
    "秋田県": "05",
    "山形県": "06",
    "福島県": "07",
    "茨城県": "08",
    "栃木県": "09",
    "群馬県": "10",
    "埼玉県": "11",
    "千葉県": "12",
    "東京都": "13",
    "神奈川県": "14",
    "新潟県": "15",
    "富山県": "16",
    "石川県": "17",
    "福井県": "18",
    "山梨県": "19",
    "長野県": "20",
    "岐阜県": "21",
    "静岡県": "22",
    "愛知県": "23",
    "三重県": "24",
    "滋賀県": "25",
    "京都府": "26",
    "大阪府": "27",
    "兵庫県": "28",
    "奈良県": "29",
    "和歌山県": "30",
    "鳥取県": "31",
    "島根県": "32",
    "岡山県": "33",
    "広島県": "34",
    "山口県": "35",
    "徳島県": "36",
    "香川県": "37",
    "愛媛県": "38",
    "高知県": "39",
    "福岡県": "40",
    "佐賀県": "41",
    "長崎県": "42",
    "熊本県": "43",
    "大分県": "44",
    "宮崎県": "45",
    "鹿児島県": "46",
    "沖縄県": "47",
}

# Cap on alternative_programs[] returned. The MASTER_PLAN spec calls for 5;
# we bound at 5 to keep the envelope < 8 KB even when every alt carries
# its own relax_reason narrative.
_MAX_ALTERNATIVES = 5

# Cap on remediation_steps — typically 1 per failed predicate, plus a
# "verify primary source" steady-state step.
_MAX_REMEDIATION_STEPS = 12

# Soft-blocking axes — failures here are surfaced as `blocking=False`
# because the underlying constraint is heuristic / partially-extracted
# (regex residue) rather than authoritative. The customer LLM still
# learns about the gap but is told it MAY be a false positive.
_SOFT_AXES: frozenset[str] = frozenset({"funding_purposes", "raw_constraints"})


_DISCLAIMER = (
    "本 why_excluded reasoning は am_program_eligibility_predicate_json "
    "(jpi_programs corpus snapshot から rule-based 抽出) と houjin "
    "属性 (am_entities corporate_entity + houjin_master) の機械的 diff であり、"
    "「申請可否確定判断」「受給可否判定」 ではない。 missing axis は "
    "'unknown' (no constraint ではない)。 remediation_steps は規則ベースの"
    "指針であり個別申請助言ではありません。 申請可否判断 (行政書士法 §1の2) /"
    " 税務助言 (税理士法 §52) の代替ではなく、確定判断は資格を有する"
    "行政書士・税理士・中小企業診断士へ。"
)


# ---------------------------------------------------------------------------
# Pydantic body
# ---------------------------------------------------------------------------


class HoujinAttrs(BaseModel):
    """Attribute-level houjin descriptor.

    Every field is optional. When `id` is supplied we hydrate the rest
    from autonomath.db; an explicit value here always wins over a
    hydrated value.
    """

    id: str | None = Field(
        None,
        min_length=13,
        max_length=14,
        description="13-digit 法人番号 (with or without 'T' prefix). When supplied, missing attrs are hydrated from autonomath corp facts.",
    )
    capital: int | None = Field(None, ge=0, description="Paid-in capital in JPY.")
    employees: int | None = Field(
        None, ge=0, description="Headcount (常時雇用 or total — caller's call)."
    )
    industry: str | None = Field(
        None,
        max_length=200,
        description="Free-text industry label (e.g. '製造業') for human display.",
    )
    founded_year: int | None = Field(
        None, ge=1800, le=2100, description="Year the entity was founded."
    )
    prefecture: str | None = Field(
        None,
        max_length=20,
        description="Long-form prefecture name (e.g. '東京都'). JIS code derived server-side.",
    )
    jsic: str | None = Field(
        None,
        min_length=1,
        max_length=4,
        description="JSIC major letter (A–T) or major+medium code (e.g. 'D06').",
    )
    certifications: list[str] | None = Field(
        None,
        description="Self-declared certifications held (e.g. ['認定新規就農者']).",
    )


class WhyExcludedRequest(BaseModel):
    """POST body for /v1/intel/why_excluded."""

    program_id: str = Field(
        ...,
        min_length=4,
        max_length=64,
        description="jpi_programs.unified_id (e.g. 'UNI-75690a3d74'). Discover via /v1/programs/search.",
    )
    houjin: HoujinAttrs = Field(
        ...,
        description=(
            "Houjin descriptor. Either supply `id` (and we hydrate from "
            "corp facts) or explicit attributes (capital / employees / "
            "industry / founded_year / prefecture / jsic / certifications)."
        ),
    )


# ---------------------------------------------------------------------------
# Helpers (autonomath connection + houjin normalize)
# ---------------------------------------------------------------------------


def _autonomath_db_path() -> Path:
    """Resolve the autonomath.db path. Mirrors api/houjin.py."""
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[3] / "autonomath.db"


def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Open a read-only connection. Returns None when the file is missing."""
    p = _autonomath_db_path()
    if not p.exists():
        return None
    uri = f"file:{p}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute("PRAGMA query_only=1")
        return conn
    except sqlite3.OperationalError:
        return None


def _normalize_bangou(raw: str | None) -> str | None:
    """Strip 'T' prefix + non-digits. Return 13 digits or None."""
    if not raw:
        return None
    s = raw.strip().lstrip("Tt")
    s = re.sub(r"[\s\-,　]", "", s)
    if not s.isdigit() or len(s) != 13:
        return None
    return s


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
                (name,),
            ).fetchone()
            is not None
        )
    except sqlite3.Error:
        return False


def _safe_json_loads(blob: str | None) -> Any:
    if not blob:
        return None
    try:
        return json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return None


def _hydrate_houjin_from_corp_facts(am_conn: sqlite3.Connection, bangou: str) -> dict[str, Any]:
    """Pull capital/employees/jsic/prefecture/founded_year from
    am_entity_facts ``corp.*`` for the canonical_id ``houjin:<bangou>``.

    Returns a partial attribute dict. Missing columns/tables → empty dict.
    Caller layers explicit input over this.
    """
    out: dict[str, Any] = {}
    if not _table_exists(am_conn, "am_entity_facts"):
        return out
    canonical = f"houjin:{bangou}"
    try:
        rows = am_conn.execute(
            "SELECT field_name, field_value_text, field_value_numeric "
            "FROM am_entity_facts WHERE entity_id = ? LIMIT 100",
            (canonical,),
        ).fetchall()
    except sqlite3.Error:
        return out
    for r in rows:
        fname = r["field_name"]
        ntext = r["field_value_text"]
        num = r["field_value_numeric"]
        if fname == "corp.capital_amount" and num is not None:
            with contextlib.suppress(TypeError, ValueError):
                out["capital"] = int(num)
        elif fname == "corp.employee_count" and num is not None:
            with contextlib.suppress(TypeError, ValueError):
                out["employees"] = int(num)
        elif fname == "corp.jsic_major" and ntext:
            out["jsic"] = str(ntext).strip()
        elif fname == "corp.industry_raw" and ntext and "industry" not in out:
            out["industry"] = str(ntext).strip()
        elif fname == "corp.prefecture" and ntext:
            out["prefecture"] = str(ntext).strip()
        elif fname == "corp.date_of_establishment" and ntext:
            m = re.match(r"^(\d{4})", str(ntext))
            if m:
                with contextlib.suppress(ValueError):
                    out["founded_year"] = int(m.group(1))
    return out


def _resolve_houjin_attrs(
    am_conn: sqlite3.Connection | None,
    payload_houjin: HoujinAttrs,
) -> tuple[dict[str, Any], list[str]]:
    """Merge hydrated facts with explicit input. Returns (attrs, sources).

    `sources` records which axes came from explicit input vs corp.* facts
    so the output `houjin_resolved` envelope is honest about provenance.
    """
    sources: list[str] = []
    hydrated: dict[str, Any] = {}
    if payload_houjin.id and am_conn is not None:
        bangou = _normalize_bangou(payload_houjin.id)
        if bangou:
            hydrated = _hydrate_houjin_from_corp_facts(am_conn, bangou)
            if hydrated:
                sources.append("autonomath.am_entity_facts.corp.*")

    explicit = {
        k: v
        for k, v in {
            "capital": payload_houjin.capital,
            "employees": payload_houjin.employees,
            "industry": payload_houjin.industry,
            "founded_year": payload_houjin.founded_year,
            "prefecture": payload_houjin.prefecture,
            "jsic": payload_houjin.jsic,
            "certifications": payload_houjin.certifications,
        }.items()
        if v is not None
    }
    if explicit:
        sources.append("payload.houjin")

    merged = dict(hydrated)
    merged.update(explicit)
    if payload_houjin.id:
        merged["id"] = _normalize_bangou(payload_houjin.id) or payload_houjin.id
    return merged, sources


# ---------------------------------------------------------------------------
# Predicate fetch + program metadata
# ---------------------------------------------------------------------------


def _fetch_predicate_and_program(
    am_conn: sqlite3.Connection, program_id: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return (predicate_dict, program_meta_dict). Either may be None."""
    predicate: dict[str, Any] | None = None
    program_meta: dict[str, Any] | None = None

    if _table_exists(am_conn, "am_program_eligibility_predicate_json"):
        try:
            row = am_conn.execute(
                "SELECT predicate_json, extraction_method, confidence "
                "FROM am_program_eligibility_predicate_json "
                "WHERE program_id = ? LIMIT 1",
                (program_id,),
            ).fetchone()
            if row and row["predicate_json"]:
                parsed = _safe_json_loads(row["predicate_json"])
                if isinstance(parsed, dict):
                    predicate = parsed
                    predicate["_extraction_method"] = row["extraction_method"]
                    predicate["_confidence"] = row["confidence"]
        except sqlite3.Error as exc:
            logger.warning("predicate_json fetch failed: %s", exc)

    if _table_exists(am_conn, "jpi_programs"):
        try:
            row = am_conn.execute(
                "SELECT unified_id, primary_name, prefecture, program_kind, "
                "       authority_name, source_url "
                "FROM jpi_programs WHERE unified_id = ? LIMIT 1",
                (program_id,),
            ).fetchone()
            if row:
                program_meta = dict(row)
        except sqlite3.Error as exc:
            logger.warning("jpi_programs fetch failed: %s", exc)

    return predicate, program_meta


# ---------------------------------------------------------------------------
# Predicate evaluation (axis-level, not the SQL eligibility_predicate engine)
# ---------------------------------------------------------------------------


def _normalize_jsic(value: Any) -> str | None:
    """Accept 'D' / 'd' / 'D06' / 'D060' — return major letter only."""
    if not value:
        return None
    s = str(value).strip().upper()
    if not s or not s[0].isalpha():
        return None
    return s[0]


def _check_industry(expected: list[Any], actual: str | None) -> tuple[bool, str | None]:
    """Industry pass iff actual JSIC major is in expected. None actual → unknown."""
    expected_majors = sorted({str(x).strip().upper()[:1] for x in expected if x})
    actual_major = _normalize_jsic(actual)
    if actual_major is None:
        return False, "unknown"
    return actual_major in expected_majors, actual_major


def _check_prefecture(
    expected_names: list[Any],
    expected_codes: list[Any],
    actual_pref: str | None,
) -> tuple[bool, str | None]:
    """Prefecture pass iff actual ∈ expected_names OR actual JIS ∈ expected_codes."""
    if not actual_pref:
        return False, "unknown"
    actual_str = str(actual_pref).strip()
    actual_code = PREFECTURE_JIS.get(actual_str)
    expected_name_set = {str(x).strip() for x in expected_names if x}
    expected_code_set = {str(x).strip() for x in expected_codes if x}
    if actual_str in expected_name_set:
        return True, actual_str
    if actual_code and actual_code in expected_code_set:
        return True, actual_str
    return False, actual_str


def _check_max(field_name: str, cap: Any, actual: Any) -> tuple[bool, Any]:
    """``actual ≤ cap`` numeric guard. None actual → unknown (False, None)."""
    if actual is None:
        return False, None
    try:
        cap_n = float(cap)
        actual_n = float(actual)
    except (TypeError, ValueError):
        return False, actual
    return actual_n <= cap_n, actual_n


def _check_min_business_years(
    expected_years: int, founded_year: int | None
) -> tuple[bool, int | None]:
    """``current_year - founded_year ≥ expected_years``."""
    if founded_year is None:
        return False, None
    import datetime as _dt

    current_year = _dt.datetime.now().year
    actual_years = current_year - int(founded_year)
    try:
        return actual_years >= int(expected_years), actual_years
    except (TypeError, ValueError):
        return False, actual_years


def _check_age(age_axis: dict[str, Any], _actual: Any) -> tuple[bool, str]:
    """Age axis is applicant-personal — caller doesn't supply it via houjin
    (corporate). Return unknown so the LLM surfaces it as 'verify manually'.
    """
    return False, "applicant_personal_age_unknown"


def _check_certifications_any_of(
    expected: list[Any], actual: list[str] | None
) -> tuple[bool, list[str]]:
    """Pass iff at least one expected certification is in actual."""
    if not actual:
        return False, []
    expected_set = {str(x).strip() for x in expected if x}
    actual_set = {str(x).strip() for x in actual if x}
    held = sorted(expected_set & actual_set)
    return bool(held), held


def _check_target_entity_types(
    expected: list[Any], _actual: Any, payload: HoujinAttrs
) -> tuple[bool, str | None]:
    """Target-entity-types is corporate vs sole_proprietor. We always
    treat a houjin (法人番号 supplied) as 'corporation'."""
    expected_set = {str(x).strip().lower() for x in expected if x}
    if not expected_set:
        return True, None
    actual = "corporation" if payload.id else "unknown"
    return actual in expected_set, actual


# ---------------------------------------------------------------------------
# Remediation generator (rules-based, NEVER LLM)
# ---------------------------------------------------------------------------


_REMEDIATION_RULES: dict[str, dict[str, Any]] = {
    "industries_jsic": {
        "step": "JSIC 大分類 ({expected}) に該当する事業セグメントを新設または事業計画上で 主たる事業 に再分類する。 兼業 法人なら主たる売上比率の見直しで対応可能な場合あり。",
        "est_difficulty": "hard",
        "est_timeline_days": 180,
        "blocking": True,
    },
    "prefectures": {
        "step": "対象 prefecture ({expected}) に本社 または 主たる事業所を移転する。 移転に伴う登記費用 + 営業基盤再構築コストを試算してから判断。",
        "est_difficulty": "hard",
        "est_timeline_days": 365,
        "blocking": True,
    },
    "prefecture_jis": {
        "step": "対象 prefecture (JIS code {expected}) の事業所要件を満たすため拠点を増設または移転する。",
        "est_difficulty": "hard",
        "est_timeline_days": 365,
        "blocking": True,
    },
    "municipalities": {
        "step": "対象市区町村 ({expected}) に事業所を設置するか登記住所を移す。 同一都道府県内なら 90 日 程度。",
        "est_difficulty": "med",
        "est_timeline_days": 90,
        "blocking": True,
    },
    "capital_max_yen": {
        "step": "資本金を ¥{expected:,} 以下に減資する (会社法 §447 / §449 — 株主総会特別決議 + 債権者保護手続 1 ヶ月以上)。 中小企業 認定 ・ 適用税制 にも影響するため税理士確認必須。",
        "est_difficulty": "med",
        "est_timeline_days": 60,
        "blocking": True,
    },
    "employee_max": {
        "step": "従業員数を {expected} 人 以下に調整する。 短期では 退職勧奨 / 派遣切替 / 子会社分離 などの選択肢があるが 労務リスクが高いため社労士確認必須。",
        "est_difficulty": "hard",
        "est_timeline_days": 180,
        "blocking": True,
    },
    "min_business_years": {
        "step": "業歴 {expected} 年以上の要件を満たすまで時間を置く (現在 {actual} 年)。 設立日要件のため短縮不可 — 別制度を検討するのが現実的。",
        "est_difficulty": "hard",
        "est_timeline_days": 1095,  # ~3 years
        "blocking": True,
    },
    "age": {
        "step": "応募者個人の年齢要件 ({expected}) を確認。 申請者本人のプロフィールに依存するため 申請担当者 を切り替えることで満たせる場合あり。",
        "est_difficulty": "easy",
        "est_timeline_days": 7,
        "blocking": False,
    },
    "target_entity_types": {
        "step": "対象事業者類型 ({expected}) を満たす法人形態 (例: 法人化 / 個人事業主登録) を整える。 既に法人なら 認定 取得で対応可能な場合あり。",
        "est_difficulty": "med",
        "est_timeline_days": 60,
        "blocking": True,
    },
    "certifications_any_of": {
        "step": "対象認定 ({expected}) のいずれか 1 つを取得する。 認定機関 (経営革新等支援機関 / 都道府県農林事務所 等) に申請。 取得まで概ね 30-90 日。",
        "est_difficulty": "med",
        "est_timeline_days": 90,
        "blocking": True,
    },
    "crop_categories": {
        "step": "対象作物 ({expected}) を栽培品目に追加する。 栽培実績 1 期以上が要件となる場合多数。",
        "est_difficulty": "hard",
        "est_timeline_days": 365,
        "blocking": True,
    },
    "funding_purposes": {
        "step": "資金使途を {expected} に整合させた事業計画書を作成。 既存事業を再ラベリングできる場合は対応コスト低。",
        "est_difficulty": "easy",
        "est_timeline_days": 14,
        "blocking": False,  # narrative-level — usually a labeling fix
    },
}

_VERIFY_PRIMARY_SOURCE_STEP: dict[str, Any] = {
    "step": "公募要領 (source_url) を必ず一次資料で確認し、最新版の要件・募集枠・申請窓口を行政書士または認定経営革新等支援機関に確認する。",
    "est_difficulty": "easy",
    "est_timeline_days": 3,
    "blocking": False,
    "source_url": None,
}


def _format_expected(expected: Any) -> str:
    """Stringify an expected value for remediation copy."""
    if isinstance(expected, list):
        return " / ".join(str(x) for x in expected)
    if isinstance(expected, dict):
        return json.dumps(expected, ensure_ascii=False)
    return str(expected)


def _build_remediation(
    axis: str,
    expected: Any,
    actual: Any,
    source_url: str | None,
) -> dict[str, Any] | None:
    """Render a remediation step from `_REMEDIATION_RULES`. None when no rule."""
    rule = _REMEDIATION_RULES.get(axis)
    if rule is None:
        return None
    expected_s = _format_expected(expected)
    actual_s = _format_expected(actual) if actual is not None else "unknown"
    try:
        step_text = rule["step"].format(expected=expected_s, actual=actual_s)
    except (KeyError, IndexError, ValueError):
        step_text = rule["step"]
    return {
        "step": step_text,
        "est_difficulty": rule["est_difficulty"],
        "est_timeline_days": rule["est_timeline_days"],
        "source_url": source_url,
    }


# ---------------------------------------------------------------------------
# Predicate-level diff
# ---------------------------------------------------------------------------


def _evaluate_predicate(
    predicate: dict[str, Any],
    houjin_attrs: dict[str, Any],
    payload_houjin: HoujinAttrs,
    program_source_url: str | None,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    int,
    int,
]:
    """Run axis-level predicate diff. Returns (passed, failed, remediation,
    evaluated_axes, blocking_failures).
    """
    passed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    remediation: list[dict[str, Any]] = []
    blocking_failures = 0

    def _check(
        axis: str,
        expected: Any,
        outcome: tuple[bool, Any],
    ) -> None:
        nonlocal blocking_failures
        ok, actual = outcome
        if ok:
            passed.append({"predicate": axis, "expected": expected, "actual": actual})
            return
        is_blocking = axis not in _SOFT_AXES
        # An "unknown" actual (None) is always non-blocking — the customer
        # LLM should surface it as "verify manually" rather than treat as
        # a hard exclusion. The houjin attrs were partial.
        if actual is None or actual == "unknown" or actual == "applicant_personal_age_unknown":
            is_blocking = False
        if is_blocking:
            blocking_failures += 1
        rem = _build_remediation(axis, expected, actual, program_source_url)
        rem_text = rem["step"] if rem else None
        failed.append(
            {
                "predicate": axis,
                "expected": expected,
                "actual": actual,
                "blocking": is_blocking,
                "remediation": rem_text,
            }
        )
        if rem and len(remediation) < _MAX_REMEDIATION_STEPS:
            remediation.append(rem)

    evaluated = 0

    if "industries_jsic" in predicate:
        evaluated += 1
        _check(
            "industries_jsic",
            predicate["industries_jsic"],
            _check_industry(
                predicate["industries_jsic"],
                houjin_attrs.get("jsic"),
            ),
        )

    if "prefectures" in predicate or "prefecture_jis" in predicate:
        evaluated += 1
        _check(
            "prefectures" if "prefectures" in predicate else "prefecture_jis",
            predicate.get("prefectures") or predicate.get("prefecture_jis"),
            _check_prefecture(
                predicate.get("prefectures") or [],
                predicate.get("prefecture_jis") or [],
                houjin_attrs.get("prefecture"),
            ),
        )

    if "capital_max_yen" in predicate:
        evaluated += 1
        _check(
            "capital_max_yen",
            predicate["capital_max_yen"],
            _check_max(
                "capital",
                predicate["capital_max_yen"],
                houjin_attrs.get("capital"),
            ),
        )

    if "employee_max" in predicate:
        evaluated += 1
        _check(
            "employee_max",
            predicate["employee_max"],
            _check_max(
                "employees",
                predicate["employee_max"],
                houjin_attrs.get("employees"),
            ),
        )

    if "min_business_years" in predicate:
        evaluated += 1
        _check(
            "min_business_years",
            predicate["min_business_years"],
            _check_min_business_years(
                int(predicate["min_business_years"]),
                houjin_attrs.get("founded_year"),
            ),
        )

    if "age" in predicate:
        evaluated += 1
        _check(
            "age",
            predicate["age"],
            _check_age(predicate["age"], None),
        )

    if "target_entity_types" in predicate:
        evaluated += 1
        _check(
            "target_entity_types",
            predicate["target_entity_types"],
            _check_target_entity_types(
                predicate["target_entity_types"],
                None,
                payload_houjin,
            ),
        )

    if "certifications_any_of" in predicate:
        evaluated += 1
        _check(
            "certifications_any_of",
            predicate["certifications_any_of"],
            _check_certifications_any_of(
                predicate["certifications_any_of"],
                houjin_attrs.get("certifications") or [],
            ),
        )

    # Always append a "verify primary source" step so the LLM never
    # ships remediation without a 1-line fence.
    if remediation or failed:
        verify_step = dict(_VERIFY_PRIMARY_SOURCE_STEP)
        verify_step["source_url"] = program_source_url
        if len(remediation) < _MAX_REMEDIATION_STEPS:
            remediation.append(verify_step)

    return passed, failed, remediation, evaluated, blocking_failures


# ---------------------------------------------------------------------------
# Alternative program suggestion
# ---------------------------------------------------------------------------


def _alternative_programs_for_houjin(
    am_conn: sqlite3.Connection,
    *,
    bangou: str | None,
    failed_axes: list[str],
    excluded_program_id: str,
    limit: int = _MAX_ALTERNATIVES,
) -> list[dict[str, Any]]:
    """Top-N alternatives via am_recommended_programs (W29-8) — preferred —
    or a generic JSIC/prefecture fallback when the recommend table is empty.

    `failed_axes` becomes the per-row `relax_reason` so the LLM knows which
    constraint the alternative is *not* enforcing relative to the original.
    """
    if not bangou:
        return []
    if not _table_exists(am_conn, "am_recommended_programs"):
        return []
    try:
        rows = am_conn.execute(
            "SELECT program_unified_id AS program_id, score, rank "
            "FROM am_recommended_programs "
            "WHERE houjin_bangou = ? AND program_unified_id != ? "
            "ORDER BY rank ASC, score DESC LIMIT ?",
            (bangou, excluded_program_id, int(limit)),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_recommended_programs alt query failed: %s", exc)
        return []

    alternatives: list[dict[str, Any]] = []
    relax_reason = (
        f"既存マッチからの緩和: 失敗 axis = {','.join(failed_axes)} を緩めた候補"
        if failed_axes
        else "高ランクの代替候補"
    )
    program_ids = [r["program_id"] for r in rows if r["program_id"]]
    name_lookup: dict[str, str] = {}
    if program_ids and _table_exists(am_conn, "jpi_programs"):
        placeholders = ",".join("?" for _ in program_ids)
        try:
            for r in am_conn.execute(
                f"SELECT unified_id, primary_name FROM jpi_programs "
                f"WHERE unified_id IN ({placeholders})",
                program_ids,
            ).fetchall():
                name_lookup[r["unified_id"]] = r["primary_name"]
        except sqlite3.Error:
            pass

    for r in rows:
        pid = r["program_id"]
        if not pid:
            continue
        score = float(r["score"]) if r["score"] is not None else 0.0
        alternatives.append(
            {
                "program_id": pid,
                "name": name_lookup.get(pid),
                "match_score": round(min(1.0, max(0.0, score)), 4),
                "relax_reason": relax_reason,
            }
        )
    return alternatives


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/why_excluded",
    summary="Why a houjin failed eligibility — diff + remediation + alternatives in 1 call",
    description=(
        "Cross-joins ``am_program_eligibility_predicate_json`` (W26-6) "
        "with houjin attributes (am_entities corporate_entity + explicit "
        "input) and returns a per-axis pass/fail diff, rules-based "
        "remediation steps, and up to 5 alternative programs from "
        "``am_recommended_programs`` (W29-8). NO LLM call, pure SQLite + "
        "Python diff. Sensitive: 行政書士法 §1の2 / 税理士法 §52 fence.\n\n"
        "**Pricing:** ¥3 / call (`_billing_unit: 1`)."
    ),
    responses={
        200: {"description": "why_excluded envelope (compact-friendly)."},
        404: {"description": "Unknown program_id (no predicate cached)."},
    },
)
def post_why_excluded(
    payload: Annotated[WhyExcludedRequest, Body(...)],
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    _t0 = time.perf_counter()

    am_conn = _open_autonomath_ro()
    if am_conn is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "autonomath_db_unavailable",
                "message": "autonomath.db is not provisioned on this volume.",
            },
        )

    try:
        predicate, program_meta = _fetch_predicate_and_program(am_conn, payload.program_id)
        if predicate is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "predicate_not_found",
                    "message": (
                        f"no eligibility predicate cached for program_id="
                        f"{payload.program_id!r}; verify via /v1/programs/"
                        f"{payload.program_id}/eligibility_predicate or "
                        "wait for the next extract_eligibility_predicate "
                        "ETL run."
                    ),
                },
            )

        houjin_attrs, attr_sources = _resolve_houjin_attrs(am_conn, payload.houjin)

        program_source_url = (program_meta or {}).get("source_url")
        passed, failed, remediation, evaluated, blocking_failures = _evaluate_predicate(
            predicate,
            houjin_attrs,
            payload.houjin,
            program_source_url,
        )

        eligible = blocking_failures == 0 and any([passed, failed]) is True
        # When NO axes evaluated (caller supplied an empty houjin descriptor
        # AND the predicate has no axes) we surface eligible=False with
        # match_score=0 so the LLM knows nothing was actually checked.
        if not passed and not failed:
            eligible = False
        match_score = (
            round(len(passed) / max(1, len(passed) + len(failed)), 4) if (passed or failed) else 0.0
        )

        # Alternatives only when at least one blocking failure (otherwise
        # the customer would be steering away from a viable candidate).
        bangou = _normalize_bangou(payload.houjin.id) if payload.houjin.id else None
        failed_axes = [f["predicate"] for f in failed if f.get("blocking")]
        alternative_programs: list[dict[str, Any]] = []
        if blocking_failures > 0 and bangou:
            alternative_programs = _alternative_programs_for_houjin(
                am_conn,
                bangou=bangou,
                failed_axes=failed_axes,
                excluded_program_id=payload.program_id,
            )
    finally:
        with contextlib.suppress(sqlite3.Error):
            am_conn.close()

    body: dict[str, Any] = {
        "program_id": payload.program_id,
        "program_name": (program_meta or {}).get("primary_name"),
        "eligible": eligible,
        "match_score": match_score,
        "predicate_evaluation": {
            "passed": passed,
            "failed": failed,
            "evaluated_axes": evaluated,
            "blocking_failures": blocking_failures,
        },
        "remediation_steps": remediation,
        "alternative_programs": alternative_programs,
        "houjin_resolved": {
            "attrs": {k: v for k, v in houjin_attrs.items() if k != "id"},
            "id": houjin_attrs.get("id"),
            "sources": attr_sources,
        },
        "data_quality": {
            "predicate_extraction_method": predicate.get("_extraction_method"),
            "predicate_confidence": predicate.get("_confidence"),
            "predicate_axes_present": [
                k for k in predicate if not k.startswith("_") and k != "raw_constraints"
            ],
        },
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
    }
    body = attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "intel.why_excluded",
        latency_ms=latency_ms,
        result_count=evaluated,
        params={
            "program_id": payload.program_id,
            "houjin_has_id": bool(payload.houjin.id),
            "houjin_attr_count": sum(
                1
                for v in (
                    payload.houjin.capital,
                    payload.houjin.employees,
                    payload.houjin.industry,
                    payload.houjin.founded_year,
                    payload.houjin.prefecture,
                    payload.houjin.jsic,
                    payload.houjin.certifications,
                )
                if v is not None
            ),
        },
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="intel.why_excluded",
        request_params={
            "program_id": payload.program_id,
            "houjin_id": payload.houjin.id,
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return JSONResponse(content=body)


__all__ = ["router"]
