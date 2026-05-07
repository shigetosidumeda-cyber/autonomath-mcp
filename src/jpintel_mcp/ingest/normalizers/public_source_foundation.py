from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

_OBSERVATION_KEYS = (
    "source_profile",
    "profile",
    "payload",
    "record",
    "row",
    "data",
    "observation",
)
_OBSERVATION_META_KEYS = (
    "fetched_at",
    "fetched_at_jst",
    "captured_at",
    "collected_at",
    "fetched",
    "as_of",
    "verified_at",
)

_ALIAS_GROUPS: dict[str, tuple[str, ...]] = {
    "checked_at": (
        "fetched_at",
        "fetched_at_jst",
        "captured_at",
        "collected_at",
        "fetched",
        "as_of",
        "verified_at",
        "verified",
        "verified_on",
        "checked",
    ),
    "source_url": (
        "source_url",
        "listing_url",
        "canonical_url",
        "canonical",
        "canonical_root",
        "root_url",
        "root",
        "url",
        "entry_url",
        "search_url",
        "enforcement_canonical_url",
        "subsidy_list",
        "sangyou_index",
        "sample_program_url",
        "gateway_url",
        "detail_url",
        "source_pdf",
        "pdf_url",
        "endpoint",
        "endpoints",
        "list_endpoint",
        "api_endpoint",
        "base_url",
        "web_url",
    ),
    "official_owner": (
        "official_owner",
        "owner",
        "operator",
        "agency",
        "authority",
        "authority_name",
        "entity",
        "org_name",
        "organization",
        "bureau",
        "ministry",
        "provider",
        "source_name",
        "name",
        "org_ja",
    ),
    "license_or_terms": (
        "license",
        "license_note",
        "license_doc",
        "license_doc_path",
        "terms",
        "terms_url",
        "reuse",
        "usage_terms",
        "tos",
        "terms_note",
    ),
    "robots_policy": ("robots_status", "robots", "robots_txt"),
    "source_type": ("source_type", "kind", "listing_type", "format"),
    "acquisition_method": (
        "acquisition_method",
        "collector_method",
        "fetch_method",
        "machine_retrieve",
        "method",
        "ingestion_strategy",
    ),
    "update_frequency": (
        "update_frequency",
        "update_cadence",
        "refresh_cadence",
        "koushi_freq",
        "update_freq",
    ),
    "data_objects": ("data_objects",),
    "target_tables": ("target_tables", "downstream_targets"),
}

_EMPTY_LIST_DEFAULTS = (
    "sample_urls",
    "sample_fields",
    "known_gaps",
    "join_keys",
    "artifact_outputs_enabled",
)

_SOURCE_ID_ALIASES = ("source", "source_id", "id", "slug", "aggregator")

_NOTE_KEY = "normalization_notes"

_PREF_NAMES = {
    "hokkaido": "北海道",
    "aomori": "青森県",
    "iwate": "岩手県",
    "miyagi": "宮城県",
    "akita": "秋田県",
    "yamagata": "山形県",
    "fukushima": "福島県",
    "ibaraki": "茨城県",
    "tochigi": "栃木県",
    "gunma": "群馬県",
    "saitama": "埼玉県",
    "chiba": "千葉県",
    "tokyo": "東京都",
    "kanagawa": "神奈川県",
    "niigata": "新潟県",
    "toyama": "富山県",
    "ishikawa": "石川県",
    "fukui": "福井県",
    "yamanashi": "山梨県",
    "nagano": "長野県",
    "gifu": "岐阜県",
    "shizuoka": "静岡県",
    "aichi": "愛知県",
    "mie": "三重県",
    "shiga": "滋賀県",
    "kyoto": "京都府",
    "osaka": "大阪府",
    "hyogo": "兵庫県",
    "nara": "奈良県",
    "wakayama": "和歌山県",
    "tottori": "鳥取県",
    "shimane": "島根県",
    "okayama": "岡山県",
    "hiroshima": "広島県",
    "yamaguchi": "山口県",
    "tokushima": "徳島県",
    "kagawa": "香川県",
    "ehime": "愛媛県",
    "kochi": "高知県",
    "fukuoka": "福岡県",
    "saga": "佐賀県",
    "nagasaki": "長崎県",
    "kumamoto": "熊本県",
    "oita": "大分県",
    "miyazaki": "宮崎県",
    "kagoshima": "鹿児島県",
    "okinawa": "沖縄県",
}


def normalize_source_profile_row(obj: Any) -> Any:
    """Normalize collector aliases before SourceProfileRow validation.

    This keeps high-signal source evidence strict: rows without a recoverable
    source_url, checked_at, license_or_terms, or robots_policy remain quarantine
    candidates. Lower-risk operational defaults are added with notes so they
    enter the review backlog rather than silently becoming ready sources.
    """
    if not isinstance(obj, Mapping):
        return obj

    row = _unwrap_observation(obj)
    notes = _normalization_notes(row)
    for target, aliases in _ALIAS_GROUPS.items():
        if _has_value(row.get(target)):
            continue
        value = _first_value(row, aliases)
        if value is None:
            continue
        if target == "checked_at":
            row[target] = _normalize_checked_at(value)
        elif target == "source_url":
            row[target] = _first_http_url(value) or value
        elif target == "robots_policy":
            row[target] = _normalize_robots_policy(value)
        elif target in {"license_or_terms", "acquisition_method", "update_frequency"}:
            row[target] = _stringify_if_structured(value)
        elif target in {"data_objects", "target_tables"}:
            row[target] = _listify(value)
        elif target == "source_type" and not isinstance(value, str):
            continue
        else:
            row[target] = value

    _derive_urls_and_samples(row)
    _derive_owner(row)
    _derive_license(row, notes)
    _derive_robots(row, notes)

    if not _has_value(row.get("source_id")):
        source_id = _derive_source_id(row)
        if source_id:
            row["source_id"] = source_id

    _apply_conservative_defaults(row, notes)

    for key in _EMPTY_LIST_DEFAULTS:
        if row.get(key) is None:
            row[key] = []

    if notes:
        row[_NOTE_KEY] = notes

    return row


def _unwrap_observation(obj: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(obj)
    for key in _OBSERVATION_KEYS:
        nested = row.get(key)
        if not isinstance(nested, Mapping):
            continue
        merged = {
            outer_key: outer_value
            for outer_key, outer_value in row.items()
            if outer_key not in _OBSERVATION_KEYS
        }
        merged.update(nested)
        for meta_key in _OBSERVATION_META_KEYS:
            if meta_key in row and meta_key not in merged:
                merged[meta_key] = row[meta_key]
        return merged
    return row


def _first_value(row: Mapping[str, Any], keys: tuple[str, ...]) -> Any | None:
    for key in keys:
        value = row.get(key)
        if _has_value(value):
            return value
    return None


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _normalization_notes(row: Mapping[str, Any]) -> list[str]:
    existing = row.get(_NOTE_KEY)
    if isinstance(existing, list):
        return [str(item) for item in existing if _has_value(item)]
    if _has_value(existing):
        return [str(existing)]
    return []


def _add_note(notes: list[str], note: str) -> None:
    if note not in notes:
        notes.append(note)


def _listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    return [value]


def _derive_urls_and_samples(row: dict[str, Any]) -> None:
    if not _has_value(row.get("source_url")) and _has_value(row.get("host")):
        row["source_url"] = _url_from_host(row["host"])

    sample_urls = _listify(row.get("sample_urls"))
    for key in (
        "sample_program_url",
        "subsidy_list",
        "listing_url",
        "enforcement_canonical_url",
        "detail_url",
        "source_pdf",
        "pdf_url",
        "endpoint",
        "endpoints",
        "list_endpoint",
        "api_endpoint",
    ):
        for value in _http_urls(row.get(key)):
            if value not in sample_urls:
                sample_urls.append(value)
    sample_program = row.get("sample_program")
    if isinstance(sample_program, Mapping):
        sp_value = sample_program.get("url")
        if _is_http_url(sp_value) and sp_value not in sample_urls:
            sample_urls.append(sp_value)
    if sample_urls:
        row["sample_urls"] = sample_urls

    sample_fields = _listify(row.get("sample_fields"))
    for key in (
        "schema_fields",
        "table_columns",
        "listing_fields",
        "sample_record_shape",
        "columns_a_to_k",
    ):
        sample_fields.extend(item for item in _listify(row.get(key)) if _has_value(item))
    if sample_fields:
        row["sample_fields"] = _dedupe_strings(sample_fields)


def _derive_owner(row: dict[str, Any]) -> None:
    if _has_value(row.get("official_owner")):
        return
    if _has_value(row.get("city")):
        row["official_owner"] = row["city"]
        return
    pref = row.get("pref")
    if isinstance(pref, str) and pref.strip():
        row["official_owner"] = _PREF_NAMES.get(pref.strip().lower(), pref.strip())


def _derive_license(row: dict[str, Any], notes: list[str]) -> None:
    if _has_value(row.get("license_or_terms")):
        return
    if _is_official_public_host(row):
        row["license_or_terms"] = (
            "unknown_review_required (official public site; terms not captured)"
        )
        _add_note(
            notes,
            "defaulted license_or_terms=unknown_review_required from official public host",
        )


def _derive_robots(row: dict[str, Any], notes: list[str]) -> None:
    if _has_value(row.get("robots_policy")):
        return
    if row.get("robots_blocked") is True:
        row["robots_policy"] = "robots disallow or blocked"
        return
    if row.get("robots_blocked") is False:
        row["robots_policy"] = "allowed"
        return
    if _has_value(row.get("source_url")) or _has_value(row.get("host")):
        row["robots_policy"] = "unknown_review_required"
        _add_note(notes, "defaulted robots_policy=unknown_review_required")


def _apply_conservative_defaults(row: dict[str, Any], notes: list[str]) -> None:
    if not _has_value(row.get("priority")):
        priority = _priority_from_recommendation(row.get("jpcite_recommended_priority"))
        row["priority"] = priority or "P3"
        _add_note(notes, f"defaulted priority={row['priority']}")
    elif isinstance(row.get("priority"), int):
        row["priority"] = _priority_from_recommendation(row["priority"]) or row["priority"]

    if not _has_value(row.get("source_type")):
        row["source_type"] = _infer_source_type(row)

    if not _has_value(row.get("data_objects")):
        row["data_objects"] = _infer_data_objects(row)
        _add_note(notes, f"defaulted data_objects={row['data_objects']}")
    else:
        row["data_objects"] = _listify(row["data_objects"])

    if not _has_value(row.get("acquisition_method")):
        row["acquisition_method"] = _infer_acquisition_method(row)
        _add_note(notes, f"defaulted acquisition_method={row['acquisition_method']}")

    if not _has_value(row.get("redistribution_risk")):
        row["redistribution_risk"] = _infer_redistribution_risk(row)
        _add_note(notes, f"defaulted redistribution_risk={row['redistribution_risk']}")

    if not _has_value(row.get("update_frequency")):
        row["update_frequency"] = "unknown_review_required"
        _add_note(notes, "defaulted update_frequency=unknown_review_required")

    if not _has_value(row.get("target_tables")):
        row["target_tables"] = _infer_target_tables(row)
        _add_note(notes, f"defaulted target_tables={row['target_tables']}")
    else:
        row["target_tables"] = _listify(row["target_tables"])


def _priority_from_recommendation(value: Any) -> str | None:
    if isinstance(value, str):
        value = value.strip().upper().removeprefix("P")
    if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
        number = int(value)
        if 0 <= number <= 3:
            return f"P{number}"
        if number == 4:
            return "P3"
    return None


def _infer_source_type(row: Mapping[str, Any]) -> str:
    text = _row_text(row)
    if "api" in text:
        return "api_or_html"
    if any(token in text for token in ("xlsx", "excel", "csv")):
        return "html_plus_file"
    if "pdf" in text:
        return "html_plus_pdf"
    if any(token in text for token in ("directory", "一覧", "list", "listing")):
        return "directory"
    return "html"


def _infer_data_objects(row: Mapping[str, Any]) -> list[str]:
    text = _row_text(row)
    if any(token in text for token in ("補助金", "subsidy", "grant", "program")):
        return ["program_listing"]
    if any(token in text for token in ("行政処分", "enforcement", "sanction")):
        return ["enforcement_listing"]
    if any(token in text for token in ("認定", "certification", "register")):
        return ["certification_listing"]
    if any(token in text for token in ("directory", "一覧", "listing")):
        return ["directory_listing"]
    return ["source_profile"]


def _infer_acquisition_method(row: Mapping[str, Any]) -> str:
    formats = " ".join(str(item) for item in _listify(row.get("formats") or row.get("format")))
    if any(token in formats.lower() for token in ("api", "csv", "xlsx", "excel", "pdf")):
        return "GET HTML plus linked files/API where allowed"
    if _has_value(row.get("host")) or _has_value(row.get("source_url")):
        return "GET HTML review_required"
    return "manual_review_required"


def _infer_redistribution_risk(row: Mapping[str, Any]) -> str:
    if row.get("redistributable") is True:
        return "low"
    text = _row_text(row)
    if any(
        token in text for token in ('name_redistribute": false', "転載不可", "再配布不可", "nda")
    ):
        return "high_review_required"
    if _is_official_public_host(row):
        return "medium_review_required"
    return "medium_review_required"


def _infer_target_tables(row: Mapping[str, Any]) -> list[str]:
    objects = _infer_data_objects(row)
    if "program_listing" in objects:
        return ["programs"]
    if "enforcement_listing" in objects:
        return ["am_enforcement_detail"]
    if "certification_listing" in objects:
        return ["am_entities"]
    return ["source_document"]


def _row_text(row: Mapping[str, Any]) -> str:
    return " ".join(str(value).lower() for value in row.values() if _has_value(value))


def _dedupe_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _is_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _url_from_host(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    host = value.strip().removeprefix("http://").removeprefix("https://").strip("/")
    if not host:
        return None
    return f"https://{host}/"


def _is_official_public_host(row: Mapping[str, Any]) -> bool:
    candidates = [
        row.get("host"),
        row.get("source_url"),
        row.get("root_url"),
        row.get("listing_url"),
    ]
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
        host = parsed.netloc.lower().removeprefix("www.")
        if host.endswith(".go.jp") or host.endswith(".lg.jp"):
            return True
        if host.startswith("city.") or host.startswith("pref."):
            return True
    return False


def _normalize_checked_at(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.isoformat() + "+09:00"
        return value.isoformat()
    if isinstance(value, date):
        return f"{value.isoformat()}T00:00:00+09:00"
    if not isinstance(value, str):
        return value

    stripped = value.strip()
    webfetch_match = re.search(r"WebFetch_(\d{4}-\d{2}-\d{2})", stripped)
    if webfetch_match:
        return f"{webfetch_match.group(1)}T00:00:00+09:00"
    jst_date_match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:\s+JST)?", stripped, re.IGNORECASE)
    if jst_date_match:
        return f"{jst_date_match.group(1)}T00:00:00+09:00"
    jst_datetime_match = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)\s+JST",
        stripped,
        re.IGNORECASE,
    )
    if jst_datetime_match:
        return f"{jst_datetime_match.group(1)}T{jst_datetime_match.group(2)}+09:00"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", stripped):
        return f"{stripped}T00:00:00+09:00"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?", stripped):
        return f"{stripped}+09:00"
    return stripped


def _derive_source_id(row: Mapping[str, Any]) -> str | None:
    candidates: list[Any] = []
    candidates.extend(row.get(key) for key in _SOURCE_ID_ALIASES)
    if _has_value(row.get("pref")) and _has_value(row.get("city")):
        candidates.append(f"{row['pref']}_{row['city']}")
    if _has_value(row.get("pref")):
        candidates.append(f"pref_{row['pref']}")
    candidates.append(row.get("host"))
    candidates.extend(
        row.get(key)
        for key in (
            "source_url",
            "root",
            "root_url",
            "listing_url",
            "canonical_url",
            "canonical_root",
            "domain",
        )
    )

    for candidate in candidates:
        source_id = _source_id_candidate(candidate)
        if source_id:
            return source_id
    return None


def _stringify_if_structured(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (Mapping, list, tuple, set)):
        return json_dumps_compact(value)
    return str(value)


def _normalize_robots_policy(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (Mapping, list, tuple, set)):
        return json_dumps_compact(value)
    return str(value)


def json_dumps_compact(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except TypeError:
        return str(value)


def _http_urls(value: Any) -> list[str]:
    if _is_http_url(value):
        return [str(value)]
    if isinstance(value, Mapping):
        urls: list[str] = []
        for item in value.values():
            urls.extend(_http_urls(item))
        return urls
    if isinstance(value, list | tuple | set):
        urls = []
        for item in value:
            urls.extend(_http_urls(item))
        return urls
    return []


def _first_http_url(value: Any) -> str | None:
    urls = _http_urls(value)
    return urls[0] if urls else None


def _source_id_candidate(value: Any) -> str | None:
    if not isinstance(value, str):
        value = str(value) if value is not None else ""
    stripped = value.strip()
    if not stripped:
        return None

    parsed = urlparse(stripped)
    if parsed.scheme and parsed.netloc:
        stripped = parsed.netloc

    source_id = stripped.lower()
    source_id = source_id.removeprefix("www.")
    source_id = re.sub(r"[^a-z0-9]+", "_", source_id).strip("_")
    source_id = re.sub(r"_+", "_", source_id)
    if len(source_id) > 80:
        source_id = source_id[:80].rstrip("_")
    if re.fullmatch(r"[a-z0-9][a-z0-9_]{2,80}", source_id):
        return source_id
    return None
