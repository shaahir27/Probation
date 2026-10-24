"""Versioned immutable owner request wire models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal["v2"]
    response: Literal["accept", "reject", "edit", "leave"]
    edited_action: str | None = None
    edited_body: str | None = Field(default=None, max_length=1200)
    forward_recipient: str | None = Field(default=None, max_length=320)


class RespondBody(ReviewBody):
    request_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    reviewed_payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class UndoBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal["v2"]
    request_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
