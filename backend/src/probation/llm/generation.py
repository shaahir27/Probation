"""Versioned bounded-form generation for the configured Nemotron Nano/Super roles."""

import hashlib
from typing import Any

from probation.config import settings
from probation.core.hashing import canonical_json


def generation_options(model: str) -> dict[str, Any]:
    configured = {
        settings.model_reader,
        settings.model_writer,
        settings.model_synth,
        settings.model_wording,
    }
    lower = model.casefold()
    if (
        not settings.llm_instruction_only
        or model not in configured
        or not any(name in lower for name in ("nemotron-3-nano", "nemotron-3-super"))
    ):
        return {}
    options = {"enable_thinking": False}
    if "nemotron-3-super" in lower:
        options["force_nonempty_content"] = True
    return {"chat_template_kwargs": options}


def profile_version(model: str) -> str:
    options = generation_options(model)
    return (
        "nemotron-instruction-v1:"
        + hashlib.sha256(canonical_json(options).encode()).hexdigest()[:12]
        if options
        else "provider-default-v1"
    )


def context_version(model: str, base: str) -> str:
    return base + ":" + profile_version(model) if generation_options(model) else base


def direct_content_hash(model: str, content_hash: str) -> str:
    if not generation_options(model):
        return content_hash
    return hashlib.sha256(
        canonical_json([content_hash, profile_version(model)]).encode()
    ).hexdigest()
