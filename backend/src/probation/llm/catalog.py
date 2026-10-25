"""Closed registry of production LLM jobs: what may run, on which role, at what cost.

Authority: docs/CONTRACT.md section 6, docs/PROMPTS.md sections 2-14.
A job that is not registered here cannot reach the network. Presence of an API key is
never authorization; the transport context decides that separately.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from probation.config import Settings, settings
from probation.llm.jobs import JobOutput, job_model


class ModelRole(StrEnum):
    """The model tiers named in docs/PROMPTS.md section 2."""

    READER = "reader"
    WRITER = "writer"
    WORDING = "wording"
    EXAM_EDIT = "exam_edit"
    SYNTH = "synth"
    QUARANTINE = "quarantine"
    BASELINE = "baseline"


class JobNotRegistered(ValueError):
    """Raised when a caller asks for a production job this registry does not declare."""


_MODEL_SETTING: dict[ModelRole, str] = {
    ModelRole.READER: "model_reader",
    ModelRole.WRITER: "model_writer",
    ModelRole.WORDING: "model_wording",
    ModelRole.EXAM_EDIT: "model_exam_edits",
    ModelRole.SYNTH: "model_synth",
    ModelRole.QUARANTINE: "model_reader",
    ModelRole.BASELINE: "model_writer",
}

# docs/PROMPTS.md section 2.4 budgets the four roles it names: reader 200, writer 400, wording
# 120, exam edit 500. A job never overrides a number that section states. SYNTH, QUARANTINE and
# BASELINE are not covered by section 2.4, so their values here are this implementation's
# assumption, recorded for sign-off in the WP3 handoff rather than presented as spec.
_ROLE_MAX_TOKENS: dict[ModelRole, int] = {
    ModelRole.READER: 200,
    ModelRole.WRITER: 400,
    ModelRole.WORDING: 120,
    ModelRole.EXAM_EDIT: 500,
    ModelRole.SYNTH: 800,
    ModelRole.QUARANTINE: 500,
    ModelRole.BASELINE: 200,
}


@dataclass(frozen=True, slots=True)
class JobSpec:
    """One registered production job, addressed by its immutable (id, version) pair."""

    prompt_id: str
    prompt_version: str
    model_role: ModelRole
    redaction_profile: str
    max_tokens: int
    asset: str
    declares: tuple[str, ...]

    @property
    def key(self) -> tuple[str, str]:
        return (self.prompt_id, self.prompt_version)

    @property
    def qualified_id(self) -> str:
        return f"{self.prompt_id}.{self.prompt_version}"

    def output_model(self) -> type[JobOutput]:
        model = job_model(self.prompt_id, self.prompt_version)
        if model is None:
            raise JobNotRegistered(f"{self.qualified_id} has no registered output model")
        return model


def _job(
    qualified: str,
    role: ModelRole,
    profile: str,
    declares: tuple[str, ...],
    *,
    max_tokens: int | None = None,
) -> JobSpec:
    prompt_id, _, version = qualified.rpartition(".")
    return JobSpec(
        prompt_id=prompt_id,
        prompt_version=version,
        model_role=role,
        redaction_profile=profile,
        max_tokens=max_tokens if max_tokens is not None else _ROLE_MAX_TOKENS[role],
        asset=f"{prompt_id}.{version}.md",
        declares=declares,
    )


# The fourteen canonical jobs of docs/PROMPTS.md plus the registered B3 transport contract.
# `reader.mail.v3` and `reader.invite.v2` are the same output models as their predecessors,
# re-declared because the request text changes; the older assets stay on disk as historical
# bytes and are deliberately *not* jobs, so an unmigrated caller fails closed here rather
# than silently borrowing a different prompt.
JOBS: dict[tuple[str, str], JobSpec] = {
    spec.key: spec
    for spec in (
        _job(
            "reader.mail.v3", ModelRole.READER, "mail", ("subject", "sender_domain_class", "body")
        ),
        _job(
            "reader.invite.v2",
            ModelRole.READER,
            "invite",
            ("title", "description", "organizer_domain_class", "duration_min", "start_hour_bucket"),
        ),
        _job("reader.file.v1", ModelRole.READER, "file", ("filename", "snippet")),
        _job(
            "writer.reply.v1", ModelRole.WRITER, "writer", ("style_facts", "examples", "incoming")
        ),
        _job("wording.v1", ModelRole.WORDING, "template", ("template",)),
        _job("exam.paraphrase.v1", ModelRole.EXAM_EDIT, "exam", ("text",)),
        _job("exam.add_money_request.v1", ModelRole.EXAM_EDIT, "exam", ("text",)),
        _job("exam.add_personal_info_request.v1", ModelRole.EXAM_EDIT, "exam", ("text",)),
        _job("synth.mail_body.v1", ModelRole.SYNTH, "synth", ("spec",)),
        _job("synth.invite.v1", ModelRole.SYNTH, "synth", ("spec",)),
        _job("reader.opportunity.v1", ModelRole.READER, "mail", ("subject", "body")),
        _job("reader.opportunity.v2", ModelRole.READER, "mail", ("subject", "body")),
        _job(
            "writer.reply.v2", ModelRole.WRITER, "writer", ("style_facts", "examples", "incoming")
        ),
        _job("extract.opportunity.v1", ModelRole.QUARANTINE, "page", ("page",)),
        _job("extract.link.v1", ModelRole.QUARANTINE, "page", ("page",)),
        _job("radar.digest.v1", ModelRole.WRITER, "digest", ("entries",)),
        _job("b3.baseline.v1", ModelRole.BASELINE, "mail", ("subject", "body")),
    )
}

_ASSET_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}\.md$")


def resolve_job(prompt_id: str, prompt_version: str) -> JobSpec:
    """Return the registered spec, or fail before any transport work is attempted."""
    spec = JOBS.get((prompt_id, prompt_version))
    if spec is None:
        raise JobNotRegistered(f"job {prompt_id}.{prompt_version} is not registered")
    if not _ASSET_NAME.match(spec.asset):
        raise JobNotRegistered(f"job {spec.qualified_id} declares an unsafe asset name")
    return spec


def model_for_job(spec: JobSpec, cfg: Settings = settings) -> str:
    """Resolve the model id from settings only; code never carries a model literal."""
    attr = _MODEL_SETTING[spec.model_role]
    value = getattr(cfg, attr, None)
    if not isinstance(value, str) or not value.strip():
        raise JobNotRegistered(f"model role {spec.model_role.value} has no configured model id")
    return value


def registered_jobs() -> Mapping[tuple[str, str], JobSpec]:
    return JOBS
