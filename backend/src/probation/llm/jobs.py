"""Closed, strict output models for every job specified in PROMPTS.md.

Prompt wording/context validators remain the caller's responsibility. A valid form
is data, never permission, source support or proof that a draft may be sent.
"""

from datetime import date
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class JobOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, allow_inf_nan=False)


class MailReader(JobOutput):
    intent: Literal[
        "request",
        "question",
        "fyi",
        "newsletter",
        "receipt",
        "invite_mention",
        "social",
        "sales",
        "opportunity",
        "other",
    ]
    asks_me_to_do_something: bool
    has_deadline: bool
    deadline_text: Annotated[str | None, Field(max_length=40)]
    money_involved: bool
    urgency: Annotated[int, Field(ge=0, le=3)]
    formality: Literal["casual", "neutral", "formal"]
    asks_for_personal_info: bool
    looks_automated: bool

    @model_validator(mode="after")
    def deadline_consistency(self) -> Self:
        if not self.has_deadline and self.deadline_text is not None:
            raise ValueError("deadline_text must be null without a deadline")
        return self


class InviteReader(JobOutput):
    purpose: Literal["class", "club", "interview", "social", "work", "sales", "other"]
    looks_mandatory: bool
    money_involved: bool


class FileReader(JobOutput):
    doc_type: Literal[
        "lecture_notes",
        "assignment",
        "manual",
        "receipt_invoice",
        "ticket",
        "image_photo",
        "paper",
        "form",
        "other",
    ]
    course_hint: Annotated[str | None, Field(max_length=20, pattern=r"^[A-Za-z0-9 \-]*$")]


class ReplyWriter(JobOutput):
    body: Annotated[str, Field(min_length=5, max_length=1200)]
    needs_user_input: bool


class Wording(JobOutput):
    sentence: Annotated[str, Field(min_length=20, max_length=160)]


class ExamEdit(JobOutput):
    edited_text: Annotated[str, Field(min_length=1, max_length=12000)]


class SyntheticMail(JobOutput):
    subject: Annotated[str, Field(min_length=1, max_length=200)]
    body: Annotated[str, Field(min_length=1, max_length=6000)]


class SyntheticInvite(JobOutput):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str, Field(max_length=6000)]


class OpportunityReader(JobOutput):
    opp_type: Literal[
        "hackathon",
        "internship",
        "job",
        "scholarship",
        "competition",
        "conference",
        "workshop",
        "other",
    ]
    topic: Literal[
        "ai_ml",
        "web_dev",
        "data",
        "cybersecurity",
        "design",
        "finance",
        "core_eng",
        "research",
        "general",
    ]
    organiser_name: Annotated[str | None, Field(max_length=40)]
    opportunity_name: Annotated[str | None, Field(max_length=60)]
    deadline_text: Annotated[str | None, Field(max_length=40)]
    fee_mentioned: bool
    requires_personal_docs: bool


class OpportunityExtraction(JobOutput):
    title: Annotated[str | None, Field(max_length=80)]
    organiser: Annotated[str | None, Field(max_length=60)]
    deadline_date: Annotated[str | None, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    start_date: Annotated[str | None, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    eligibility: Annotated[list[Annotated[str, Field(max_length=100)]], Field(max_length=3)]
    fee_mentioned: bool
    mode: Literal["online", "in_person", "hybrid", "unknown"]
    apply_domain: Annotated[str | None, Field(max_length=80)]

    @field_validator("deadline_date", "start_date")
    @classmethod
    def real_calendar_date(cls, value: str | None) -> str | None:
        if value is not None:
            date.fromisoformat(value)
        return value


class LinkExtraction(JobOutput):
    title: Annotated[str | None, Field(max_length=100)]
    topic: Literal[
        "programming",
        "ai_ml",
        "web_dev",
        "data",
        "security",
        "career",
        "college",
        "finance",
        "health",
        "design",
        "science",
        "news",
        "other",
    ]
    content_type: Literal[
        "article",
        "paper",
        "video",
        "docs",
        "tutorial",
        "repo",
        "product",
        "forum",
        "social",
        "other",
    ]
    actionable: bool


class RadarDigest(JobOutput):
    digest: Annotated[str, Field(max_length=700)]


JOB_MODELS: dict[tuple[str, str], type[JobOutput]] = {
    ("reader.mail", "v2"): MailReader,
    ("reader.invite", "v1"): InviteReader,
    ("reader.file", "v1"): FileReader,
    ("writer.reply", "v1"): ReplyWriter,
    ("wording", "v1"): Wording,
    ("exam.paraphrase", "v1"): ExamEdit,
    ("exam.add_money_request", "v1"): ExamEdit,
    ("exam.add_personal_info_request", "v1"): ExamEdit,
    ("synth.mail_body", "v1"): SyntheticMail,
    ("synth.invite", "v1"): SyntheticInvite,
    ("reader.opportunity", "v1"): OpportunityReader,
    ("extract.opportunity", "v1"): OpportunityExtraction,
    ("extract.link", "v1"): LinkExtraction,
    ("radar.digest", "v1"): RadarDigest,
}


def job_model(prompt_id: str, prompt_version: str) -> type[JobOutput] | None:
    suffix = f".{prompt_version}"
    name = prompt_id.removesuffix(suffix)
    return JOB_MODELS.get((name, prompt_version))


def validate_job_output(data: dict[str, Any], prompt_id: str, prompt_version: str) -> bool:
    model = job_model(prompt_id, prompt_version)
    if model is None:
        return True  # Generic callers are still checked against their compiled schema.
    try:
        model.model_validate(data, strict=True)
        return True
    except ValidationError:
        return False
