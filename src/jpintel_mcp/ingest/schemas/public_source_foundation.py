from __future__ import annotations

from datetime import datetime
import re
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    artifact_outputs_enabled: list[str]
    sample_urls: list[str]
    sample_fields: list[str]
    known_gaps: list[str]
    checked_at: str = Field(min_length=1)

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
