"""Load, verify and render the immutable prompt assets that back registered jobs.

Authority: docs/CONTRACT.md section 6, I-14, I-16; docs/PROMPTS.md section 2.6.
Assets are read through package resources, so an installed wheel behaves exactly like the
checkout and no caller can reach a file by path. A mismatch between an asset, its manifest
entry and the live output model fails before any HTTP request exists.

Format decision W3-D01: front matter is JSON inside the existing `---` delimiters and is
parsed with the standard library. No YAML dependency is introduced, and legacy assets that
predate this format are retained unchanged rather than rewritten.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from functools import cache, lru_cache
from importlib.resources import files
from typing import Any

from probation.core.hashing import canonical_json
from probation.llm.catalog import JobSpec
from probation.llm.results import FailureCode

FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
SECTION = re.compile(r"^## (?P<name>system|user|semantic)\s*$", re.MULTILINE)
PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
UNBOUND_BRACE = re.compile(r"\{[^{}]*\}")
MANIFEST_NAME = "catalog_manifest.json"
CONTEXT_VERSION = "wp3-v1"


class PromptAssetError(ValueError):
    """Raised when an asset, its manifest entry or its model schema cannot be reconciled."""

    def __init__(self, message: str, code: FailureCode = FailureCode.ASSET_MISMATCH) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PromptAsset:
    spec: JobSpec
    system: str
    user: str
    semantic: str
    template_hash: str
    schema_fingerprint: str

    def request_identity(self) -> dict[str, str]:
        return {
            "prompt_id": self.spec.prompt_id,
            "prompt_version": self.spec.prompt_version,
            "template_hash": self.template_hash,
            "schema_fingerprint": self.schema_fingerprint,
            "context_version": CONTEXT_VERSION,
        }


def _read_asset(name: str) -> str:
    try:
        path = files("probation.llm").joinpath("prompts", name)
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, OSError) as exc:
        raise PromptAssetError(
            f"prompt asset {name} is missing", FailureCode.ASSET_MISSING
        ) from exc


@lru_cache(maxsize=1)
def _manifest() -> dict[str, Any]:
    text = _read_asset(MANIFEST_NAME)
    try:
        loaded = json.loads(text)
    except ValueError as exc:
        raise PromptAssetError("prompt manifest is not valid JSON") from exc
    if not isinstance(loaded, dict) or not isinstance(loaded.get("assets"), dict):
        raise PromptAssetError("prompt manifest has no asset table")
    entries: dict[str, Any] = loaded["assets"]
    return entries


def schema_fingerprint(model: type[Any]) -> str:
    """Stable hash of the compiled JSON surface of a strict job model."""
    compiled = json.dumps(model.model_json_schema(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(compiled.encode("utf-8")).hexdigest()[:16]


def _front_matter(text: str, name: str) -> dict[str, Any]:
    match = FRONT_MATTER.match(text)
    if match is None:
        raise PromptAssetError(f"{name} has no front matter block")
    try:
        meta = json.loads(match.group(1))
    except ValueError as exc:
        raise PromptAssetError(f"{name} front matter is not valid JSON") from exc
    if not isinstance(meta, dict):
        raise PromptAssetError(f"{name} front matter is not an object")
    return meta


def _sections(text: str, name: str) -> dict[str, str]:
    body = FRONT_MATTER.sub("", text, count=1)
    marks = list(SECTION.finditer(body))
    if len(marks) != len({m.group("name") for m in marks}):
        raise PromptAssetError(f"{name} repeats a section")
    found: dict[str, str] = {}
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(body)
        found[mark.group("name")] = body[mark.end() : end].strip("\n")
    missing = {"system", "user"} - set(found)
    if missing:
        raise PromptAssetError(f"{name} is missing sections {sorted(missing)}")
    return found


@cache
def load_prompt(spec: JobSpec) -> PromptAsset:
    """Resolve a registered job to its verified asset, or fail typed and loudly.

    Assets are immutable and versioned, so a verified load is reused for the life of the
    process; a reload would only re-read the same bytes.
    """
    name = spec.asset
    text = _read_asset(name)
    meta = _front_matter(text, name)
    sections = _sections(text, name)
    if meta.get("id") != spec.prompt_id or meta.get("version") != spec.prompt_version:
        raise PromptAssetError(f"{name} declares {meta.get('id')}/{meta.get('version')}")
    if meta.get("model_role") != spec.model_role.value:
        raise PromptAssetError(f"{name} declares role {meta.get('model_role')}")
    declared = meta.get("declares")
    if not isinstance(declared, list) or sorted(str(d) for d in declared) != sorted(spec.declares):
        raise PromptAssetError(f"{name} placeholder declarations disagree with the registry")

    fingerprint = schema_fingerprint(spec.output_model())
    entries = _manifest()
    entry = entries.get(spec.qualified_id)
    if not isinstance(entry, dict):
        raise PromptAssetError(f"{name} is absent from the prompt manifest")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if entry.get("sha256") != digest:
        raise PromptAssetError(f"{name} bytes differ from the manifest hash")
    if entry.get("schema_fingerprint") != fingerprint:
        raise PromptAssetError(f"{name} schema fingerprint drifted from the manifest")

    return PromptAsset(
        spec=spec,
        system=sections["system"],
        user=sections["user"],
        semantic=sections.get("semantic", ""),
        template_hash=digest[:16],
        schema_fingerprint=fingerprint,
    )


def render(template: str, values: dict[str, str], *, limit: int, label: str) -> str:
    """Substitute only declared placeholders with already-bounded values.

    Untrusted text is inserted as data; a value that itself contains a placeholder-shaped
    token is left literal, because the model sees it inside the tagged region and the
    declared set is closed.
    """
    tokens = set(PLACEHOLDER.findall(template))
    if not tokens <= set(values):
        raise PromptAssetError(f"{label} needs values for {sorted(tokens - set(values))}")
    if UNBOUND_BRACE.findall(PLACEHOLDER.sub("", template)):
        raise PromptAssetError(f"{label} contains an undeclared brace expression")
    out = template
    for token in sorted(tokens, key=len, reverse=True):
        out = out.replace("{" + token + "}", values[token])
    if len(out) > limit:
        raise PromptAssetError(
            f"{label} exceeded its {limit} character bound", FailureCode.CONTEXT_TOO_LARGE
        )
    return out


def compile_request(
    asset: PromptAsset, values: dict[str, str], *, user_limit: int
) -> tuple[str, str]:
    """Render the exact (system, user) pair a job sends, with semantic definitions appended."""
    system = asset.system
    if asset.semantic:
        system = f"{system}\n\n{asset.semantic}"
    return system, render(asset.user, values, limit=user_limit, label=asset.spec.qualified_id)


def provider_schema(spec: JobSpec) -> dict[str, Any]:
    """Generate the wire schema from the same strict model that validates the answer."""
    schema = spec.output_model().model_json_schema()
    return {**schema, "additionalProperties": False}


def manifest_hash() -> str:
    """Hash of the manifest table, for run provenance."""
    return hashlib.sha256(_read_asset(MANIFEST_NAME).encode("utf-8")).hexdigest()[:16]


def as_json(spec: JobSpec) -> str:
    """Canonical registry entry, used by tests and provenance records."""
    return canonical_json(
        {
            "prompt_id": spec.prompt_id,
            "version": spec.prompt_version,
            "role": spec.model_role.value,
            "max_tokens": spec.max_tokens,
            "redaction_profile": spec.redaction_profile,
            "declares": list(spec.declares),
        }
    )


__all__ = [
    "CONTEXT_VERSION",
    "PromptAsset",
    "PromptAssetError",
    "as_json",
    "compile_request",
    "load_prompt",
    "manifest_hash",
    "provider_schema",
    "render",
    "schema_fingerprint",
]
