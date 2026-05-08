from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_LICENSE_BOUNDARIES = {
    "full_fact",
    "derived_fact",
    "metadata_only",
    "link_only",
    "no_collect",
}


class SourceProfileRow(BaseModel):
    """Source research profile produced by external collection CLIs."""

    model_config = ConfigDict(extra="allow")

    source_id: str = Field(min_length=1)
    priority: str = Field(min_length=2)
    official_owner: str = Field(min_length=1)
    source_url: str = Field(min_length=4)
    source_type: str = Field(min_length=1)
    data_objects: list[str] = Field(min_length=1)
    acquisition_method: str = Field(min_length=1)
    robots_policy: str = Field(min_length=1)
    license_or_terms: str = Field(min_length=1)
    redistribution_risk: str | dict[str, object]
    update_frequency: str = Field(min_length=1)
    join_keys: list[str]
    target_tables: list[str]
    new_tables_needed: list[str] | None = None
    artifact_outputs_enabled: list[str] = Field(default_factory=list)
    target_artifacts: list[str] = Field(default_factory=list)
    artifact_sections_filled: list[str] = Field(default_factory=list)
    known_gaps_reduced: list[str] = Field(default_factory=list)
    new_known_gaps_created: list[str] = Field(default_factory=list)
    license_boundary: str = Field(default="metadata_only", min_length=1)
    refresh_frequency: str = Field(default="unknown_review_required", min_length=1)
    sample_urls: list[str]
    sample_fields: list[str]
    known_gaps: list[str]
    checked_at: str = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _backfill_contract_aliases(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        row = dict(data)
        if not row.get("target_artifacts") and row.get("artifact_outputs_enabled"):
            row["target_artifacts"] = row["artifact_outputs_enabled"]
        if not row.get("artifact_outputs_enabled") and row.get("target_artifacts"):
            row["artifact_outputs_enabled"] = row["target_artifacts"]
        if not row.get("refresh_frequency") and row.get("update_frequency"):
            row["refresh_frequency"] = row["update_frequency"]
        if not row.get("update_frequency") and row.get("refresh_frequency"):
            row["update_frequency"] = row["refresh_frequency"]
        return row

    @field_validator("source_id")
    @classmethod
    def _source_id_shape(cls, value: str) -> str:
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_]{2,80}", normalized):
            raise ValueError("source_id must normalize to ^[a-z0-9][a-z0-9_]{2,80}$")
        return normalized

    @field_validator("priority")
    @classmethod
    def _priority_shape(cls, value: str) -> str:
        if value not in {"P0", "P1", "P2", "P3"}:
            raise ValueError("priority must be one of P0, P1, P2, P3")
        return value

    @field_validator(
        "join_keys",
        "target_tables",
        "artifact_outputs_enabled",
        "target_artifacts",
        "artifact_sections_filled",
        "known_gaps_reduced",
        "new_known_gaps_created",
        "sample_urls",
        "sample_fields",
        "known_gaps",
        mode="before",
    )
    @classmethod
    def _list_shape(cls, value: object) -> list[object]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple | set):
            return list(value)
        return [value]

    @field_validator("license_boundary")
    @classmethod
    def _license_boundary_shape(cls, value: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
        normalized = {
            "full": "full_fact",
            "raw": "full_fact",
            "raw_fact": "full_fact",
            "derived": "derived_fact",
            "derived_only": "derived_fact",
            "metadata": "metadata_only",
            "link": "link_only",
            "deep_link": "link_only",
            "none": "no_collect",
            "no": "no_collect",
            "do_not_collect": "no_collect",
        }.get(normalized, normalized)
        if normalized not in _LICENSE_BOUNDARIES:
            raise ValueError(
                "license_boundary must be one of "
                "full_fact, derived_fact, metadata_only, link_only, no_collect"
            )
        return normalized

    @field_validator("source_url")
    @classmethod
    def _absolute_http_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source_url must be an absolute http(s) URL")
        return value

    @field_validator("sample_urls")
    @classmethod
    def _sample_urls_are_http(cls, values: list[str]) -> list[str]:
        for value in values:
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("sample_urls must contain absolute http(s) URLs")
        return values

    @field_validator("checked_at")
    @classmethod
    def _checked_at_has_timezone(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("checked_at must include timezone")
        return value
