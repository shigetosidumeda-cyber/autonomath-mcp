"""36協定 template renderer — deterministic, no LLM."""
from __future__ import annotations
from pathlib import Path
import re

TEMPLATE_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "autonomath_static" / "templates" / "36_kyotei_template.txt"

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "company_name": ("company_name", "会社名", "事業者名", "屋号", "法人名"),
    "address": ("address", "住所", "本店所在地", "事業所所在地"),
    "representative": ("representative", "代表者", "代表者氏名", "事業主"),
    "industry": ("industry", "業種", "事業の種類"),
    "employee_count": ("employee_count", "労働者数", "従業員数"),
    "agreement_period_start": ("agreement_period_start", "協定有効期間開始日", "起算日"),
    "agreement_period_end": ("agreement_period_end", "協定有効期間終了日", "満了日"),
    "max_overtime_hours_per_month": ("max_overtime_hours_per_month", "月間時間外労働時間"),
    "max_overtime_hours_per_year": ("max_overtime_hours_per_year", "年間時間外労働時間"),
    "holiday_work_days_per_month": ("holiday_work_days_per_month", "月間休日労働日数"),
}

REQUIRED_FIELDS = tuple(FIELD_ALIASES.keys())

class TemplateError(ValueError):
    pass

def render_36_kyotei(fields: dict[str, object]) -> str:
    """Return rendered 36協定 text. Raise TemplateError if any required field missing or any unknown field provided.
    Field names accept any alias from FIELD_ALIASES.
    """
    canonical: dict[str, str] = {}
    for key, value in fields.items():
        match = next((c for c, aliases in FIELD_ALIASES.items() if key in aliases), None)
        if not match:
            raise TemplateError(f"unknown field: {key}")
        canonical[match] = str(value)
    missing = [f for f in REQUIRED_FIELDS if f not in canonical]
    if missing:
        raise TemplateError(f"missing required fields: {missing}")
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    for key, value in canonical.items():
        text = text.replace("{" + key + "}", value)
    leftover = re.findall(r"\{[a-z_]+\}", text)
    if leftover:
        raise TemplateError(f"unsubstituted placeholders: {set(leftover)}")
    return text

def get_required_fields() -> dict[str, list[str]]:
    """Return {canonical_name: [aliases]} for client introspection."""
    return {k: list(v) for k, v in FIELD_ALIASES.items()}

def get_template_metadata() -> dict[str, object]:
    return {
        "template_id": "saburoku_kyotei",
        "obligation": "36協定 (時間外労働・休日労働協定届)",
        "authority": "厚生労働省",
        "license": "Public form — based on 厚労省 official 様式. Bookyou株式会社 reformulation, free to redistribute.",
        "quality_grade": "A",
        "method": "deterministic_template_substitution",
        "uses_llm": False,
        "required_fields": REQUIRED_FIELDS,
    }
