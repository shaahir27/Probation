"""D5 data contracts. No web value carries probability or licence authority."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    title: str = Field(max_length=300)
    url: str = Field(max_length=2048)

    @field_validator("url")
    @classmethod
    def public_url(cls, value: str) -> str:
        from probation.links.sanitise import sanitise_url

        normalized, reason = sanitise_url(value)
        if reason is not None:
            raise ValueError("Unsafe citation URL")
        return normalized


class OfficialSearchReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    search_attempt_id: str
    entity_key: str
    url: str
    catalog_brand: str
    catalog_version: str
    catalog_source_url: str
    catalog_verified_at: str
    discovered_at: str


class VerificationCard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["d5.v1"] = "d5.v1"
    availability: Literal["validated", "partial", "not_checked", "unavailable"]
    fields: dict[str, str | bool | list[str] | None] = Field(default_factory=dict)
    fee_status: Literal["payment_mentioned", "explicit_free", "unknown"] = "unknown"
    citations: list[Citation] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    extraction_id: str | None = None
    fetched_at: str | None = None
    ttl_until: str | None = None
    provenance: dict[str, str | int | bool | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def cited_fields(self) -> "VerificationCard":
        supported = {
            "title",
            "organiser",
            "deadline_date",
            "start_date",
            "eligibility",
            "fee_mentioned",
            "mode",
            "apply_domain",
            "mail_deadline_date",
            "deadline_discrepancy",
            "link_mismatch",
        }
        if (self.fields or self.fee_status != "unknown") and not self.citations:
            raise ValueError("Web-derived fields require citations")
        if self.fields.keys() - supported:
            raise ValueError("Unsupported verification field")
        limits = {"title": 80, "organiser": 60, "apply_domain": 80}
        for key, value in self.fields.items():
            if value is None:
                continue
            if key in {"fee_mentioned", "deadline_discrepancy", "link_mismatch"}:
                if type(value) is not bool:
                    raise ValueError("Verification flags must be booleans")
            elif key == "eligibility":
                if (
                    not isinstance(value, list)
                    or len(value) > 3
                    or any(len(s) > 100 for s in value)
                ):
                    raise ValueError("Eligibility exceeds supported bounds")
            elif key in {"deadline_date", "start_date", "mail_deadline_date"}:
                from datetime import date

                if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                    raise ValueError("Unsupported calendar date")
            elif key == "mode":
                if not isinstance(value, str) or value not in {
                    "online",
                    "in_person",
                    "hybrid",
                    "unknown",
                }:
                    raise ValueError("Unsupported mode")
            elif not isinstance(value, str) or len(value) > limits[key]:
                raise ValueError("Verification text exceeds supported bounds")
        if self.fields:
            from probation.core.clock import parse_timestamp

            if not self.fetched_at or not self.ttl_until:
                raise ValueError("Claim timestamps required")
            if parse_timestamp(self.fetched_at) >= parse_timestamp(self.ttl_until):
                raise ValueError("Invalid claim lifetime")
        return self
