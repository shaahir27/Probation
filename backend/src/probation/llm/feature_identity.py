"""Feature identity without pack/connector imports or model inference."""

import hashlib

from probation.core.hashing import canonical_json

FEATURIZER_VERSION = "wp3-reader-v1"


def semantic_feature_version(*, stub: bool = False) -> str:
    """Shared extraction/training identity, excluding operational transport facts."""
    from probation.config import settings
    from probation.llm.catalog import JobNotRegistered, ModelRole, model_for_job, registered_jobs
    from probation.llm.gateway import ENCODER_VERSION
    from probation.llm.generation import profile_version
    from probation.llm.prompt_loader import CONTEXT_VERSION, PromptAssetError, load_prompt

    jobs = []
    for spec in registered_jobs().values():
        if spec.model_role is ModelRole.READER:
            try:
                asset = load_prompt(spec)
                model = "offline-stub" if stub else model_for_job(spec)
            except (PromptAssetError, JobNotRegistered):
                return FEATURIZER_VERSION + ":unavailable"
            jobs.append(
                [
                    spec.qualified_id,
                    model,
                    asset.template_hash,
                    asset.schema_fingerprint,
                    profile_version(model),
                ]
            )
    encoded = canonical_json(
        {
            "encoder": FEATURIZER_VERSION,
            "context": CONTEXT_VERSION,
            "redaction": ENCODER_VERSION,
            "history": "wp4-history-v2",
            "novelty_context": "wp4-redacted-v1",
            "endpoint": settings.llm_base_url,
            "jobs": jobs,
        }
    )
    return FEATURIZER_VERSION + ":" + hashlib.sha256(encoded.encode()).hexdigest()[:16]
