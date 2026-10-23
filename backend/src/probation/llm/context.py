"""Bounded, redacted context for exactly one outbound LLM request.

Authority: docs/CONTRACT.md invariants I-14 and I-15; docs/PROMPTS.md sections 1, 5, 12;
docs/ENGINE_SPEC.md section 12.

A caller hands over typed scalar fields, never an address, a native resource credential, a raw
private URL or a whole history object. Each field is normalised, clipped to its own bound,
redacted through the request's shared token namespace, then placed in the template; the assembled
message is bound by the registry's per-job request limit. Two properties a caller must not be able
to defeat: text that arrives from the user can never open or close one of our tags or forge a
machine header in column zero, and every clip is reported, so provenance cannot describe a request
that quietly lost part of a field.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from probation.config import Settings, settings
from probation.core.identity import header_display_names
from probation.llm.catalog import JobSpec, ModelRole
from probation.llm.prompt_loader import (
    CONTEXT_VERSION,
    PromptAsset,
    PromptAssetError,
    compile_request,
)
from probation.llm.redact import (
    READER_MAX_INPUT_CHARS,
    RedactionLedger,
    RedactionResult,
    RequestRedaction,
    clip,
    redact,
)
from probation.llm.results import FailureCode

# docs/PROMPTS.md section 5: a file reader sees its name and at most this much text.
FILE_SNIPPET_MAX_CHARS = 600

# Per-field bounds, applied before the whole-request bound. ENGINE_SPEC.md section 12 fixes only
# the whole-request numbers (READER_MAX_INPUT_CHARS, QUARANTINE_MAX_INPUT_CHARS) and this 600
# character snippet; the intermediate shares below are this implementation's assumption, chosen so
# that one field can never fill a request by itself. They are listed for review in the WP3 handoff
# rather than presented as spec.
FIELD_LIMITS: dict[str, int] = {
    "subject": 200,
    "title": 200,
    "filename": 200,
    "sender_domain_class": 40,
    "organizer_domain_class": 40,
    "organiser_domain_class": 40,
    "duration_min": 16,
    "start_hour_bucket": 24,
    "snippet": FILE_SNIPPET_MAX_CHARS,
    "description": 600,
    "body": READER_MAX_INPUT_CHARS - 600,
    "incoming": 1800,
    "examples": 1800,
    "style_facts": 200,
    "text": 3000,
    "spec": 800,
    "template": 800,
    "entries": 3600,
}
DEFAULT_FIELD_LIMIT = 1200

# Fields that must occupy exactly one line, so a value cannot invent a following header.
SINGLE_LINE_FIELDS = frozenset(
    {
        "subject",
        "title",
        "filename",
        "sender_domain_class",
        "organizer_domain_class",
        "organiser_domain_class",
        "duration_min",
        "start_hour_bucket",
        "style_facts",
    }
)

# Free text that trails a machine header. Indenting every line keeps a value's own colon-shaped
# first characters out of column zero, where the header shape check would read them as ours.
INDENTED_FIELDS = frozenset(
    {"body", "snippet", "description", "incoming", "text", "spec", "template", "entries", "page"}
)

# Only mail-shaped documents lose quoted history and signatures. Exam and synthetic texts are
# built by code and must reach the model whole, or an invariance exam measures a different input.
MAIL_STRIP_FIELDS = frozenset({"body", "incoming"})

# A multipart job's restoration authority belongs to the item being answered, not to its examples.
CURRENT_FIELD_ORDER = ("body", "incoming", "text", "page", "snippet", "description", "entries")

HEADER = re.compile(r"^([A-Za-z][A-Za-z0-9 _/-]{0,31}):[ \t]", re.MULTILINE)
PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Angle brackets are markup in this system's prompts and data in none of them, so they are deleted
# rather than escaped. See `normalize`.
MARKUP_TABLE: Mapping[int, str | int | None] = {ord(char): None for char in "<>"}
INDENT = "  "

# docs/PROMPTS.md section 5: at most three owner replies accompany a request.
MAX_REPLY_EXAMPLES = 3


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Everything one request sends, plus the facts a later reader needs to distrust it."""

    spec: JobSpec
    values: Mapping[str, str] = field(compare=False)
    redaction: RequestRedaction = field(compare=False, repr=False)
    truncated: frozenset[str]
    request_limit: int
    context_version: str

    @property
    def counts(self) -> Mapping[str, int]:
        return self.redaction.counts

    @property
    def restore_authority(self) -> Mapping[str, str]:
        """The map a caller may put names back from: the current document's PERSON tokens only."""
        return self.redaction.authority()

    @property
    def projected_size(self) -> int:
        return sum(len(value) for value in self.values.values())

    def fits(self, template: str) -> bool:
        """Whether this context is expected to survive the request bound once rendered.

        A caller that can drop optional material, such as the writer shedding an example, uses this
        to degrade instead of failing. `compile_bounded_request` remains the hard bound.
        """
        overhead = len(PLACEHOLDER.sub("", template))
        return overhead + self.projected_size <= self.request_limit

    def redaction_counts(self) -> dict[str, int]:
        return dict(self.counts)


def quarantine_limit(cfg: Settings = settings) -> int:
    return int(cfg.quarantine_max_input_chars)


def request_limit_for(spec: JobSpec, cfg: Settings = settings) -> int:
    """The whole-request bound for a job: the two numbers the specs name, nothing else.

    docs/PROMPTS.md section 1 truncates reader input to `READER_MAX_INPUT_CHARS` and section 12
    gives the quarantined extractor `QUARANTINE_MAX_INPUT_CHARS`. No other request bound is
    defined, so every other role uses the reader's, which is the smaller and therefore the safe one.
    """
    if spec.model_role is ModelRole.QUARANTINE:
        return quarantine_limit(cfg)
    return READER_MAX_INPUT_CHARS


def owner_name_tokens(cfg: Settings = settings) -> tuple[str, ...]:
    """Configured names of the owner, redacted like any other display name.

    docs/PROMPTS.md section 1 counts the owner's own name among the PERSON tokens, so leaving it
    out of the redaction set would send the one identity the user most cares about in clear text.
    """
    raw = str(getattr(cfg, "user_name_tokens", "") or "")
    return tuple(p.strip() for p in re.split(r"[,;\n]+", raw) if len(p.strip()) >= 2)


def redaction_names(*values: object, cfg: Settings = settings) -> tuple[str, ...]:
    """The full PERSON token set for one item: header display names plus the owner's own names.

    A captured message knows its people by two things an egress copy must not carry: the display
    name in a header and the owner's configured name. Returning both from one call is what keeps a
    pack from redacting the address and leaking the person.
    """
    return header_display_names(*values) + owner_name_tokens(cfg)


def normalize(text: str) -> str:
    """Strip markup and control characters from untrusted text before it becomes prompt data.

    Deleting angle brackets here is what makes tag-forgery and placeholder-forgery impossible
    rather than merely unlikely: a sender who writes `</email>` or `<PERSON_9>` into a body has both
    characters gone before redaction assigns any token, so nothing they typed can close our region
    or be credited as one of our replacements.
    """
    if not isinstance(text, str):
        raise PromptAssetError(
            f"context value must be text, got {type(text).__name__}", FailureCode.CONTEXT_UNBOUND
        )
    flat = CONTROL_CHARS.sub(" ", text.replace("\r\n", "\n").replace("\r", "\n"))
    return flat.translate(MARKUP_TABLE)


def field_limit(label: str) -> int:
    return FIELD_LIMITS.get(label, DEFAULT_FIELD_LIMIT)


def _shape(label: str, value: str) -> str:
    if label in SINGLE_LINE_FIELDS:
        return " ".join(value.split())
    if label in INDENTED_FIELDS:
        return "\n".join(f"{INDENT}{line}" if line.strip() else "" for line in value.split("\n"))
    return value


def _bound_field(
    label: str, raw: str, *, names: tuple[str, ...], profile: str, scope: RedactionLedger
) -> tuple[RedactionResult, str, bool]:
    """Normalise, bound, redact and shape one untrusted document of this request.

    The field is clipped before redaction so a long value cannot crowd out a later placeholder.
    Indenting the lines a wrapper costs characters that this field's own bound has to pay for, so a
    value that overflows after shaping is redacted again at the smaller text bound. Re-redaction,
    rather than clipping the shaped text, is what keeps the counts, the restorable tokens and the
    truncation flag describing the bytes that actually leave instead of a text that was shortened
    again afterwards.
    """
    limit = field_limit(label)
    clean, pre_clipped = clip(normalize(raw), limit)
    result = redact(clean, display_names=names, profile=profile, ledger=scope, limit=limit)
    shaped = _shape(label, result.text)
    if len(shaped) > limit:
        overhead = len(shaped) - len(result.text)
        result = redact(
            clean,
            display_names=names,
            profile=profile,
            ledger=scope,
            limit=max(0, limit - overhead),
        )
        shaped = _shape(label, result.text)
    return result, shaped, pre_clipped or result.truncated


def build_request_context(
    spec: JobSpec,
    fields: Mapping[str, str],
    *,
    built: Mapping[str, str] | None = None,
    examples: Sequence[tuple[str, str]] = (),
    display_names: Iterable[str] = (),
    cfg: Settings = settings,
) -> RequestContext:
    """Sanitise, bound and redact one request's fields into values for its declared placeholders.

    `fields` carries untrusted text and is always redacted. `built` carries values this code
    assembled from typed facts and is bounded without rewriting, because a re-sanitised number or
    domain class is still only ever its own characters. Example pairs go through the same redaction
    as any other untrusted document and share the request's numbering namespace, so a name that
    appears in the incoming mail and in an example is one token rather than two identities.
    """
    if len(examples) > MAX_REPLY_EXAMPLES:
        raise PromptAssetError(
            f"{spec.qualified_id} supplied {len(examples)} examples, max {MAX_REPLY_EXAMPLES}",
            FailureCode.CONTEXT_TOO_LARGE,
        )

    scope = RedactionLedger()
    names = tuple(display_names) + owner_name_tokens(cfg)
    results: dict[str, RedactionResult] = {}
    values: dict[str, str] = {}
    truncated: set[str] = set()

    for label, raw in fields.items():
        profile = "mail" if label in MAIL_STRIP_FIELDS else spec.redaction_profile
        result, shaped, clipped = _bound_field(
            label, raw, names=names, profile=profile, scope=scope
        )
        results[label] = result
        values[label] = shaped
        if clipped:
            truncated.add(label)

    if examples:
        docs: dict[str, RedactionResult] = {}
        pairs: list[tuple[str, str]] = []
        clipped_docs: set[str] = set()
        for index, (in_text, out_text) in enumerate(examples, start=1):
            ends: list[str] = []
            for kind, raw in (("incoming", in_text), ("reply", out_text)):
                label = f"example_{index}_{kind}"
                result, shaped, clipped = _bound_field(
                    label, raw, names=names, profile="mail", scope=scope
                )
                docs[label] = result
                ends.append(shaped)
                if clipped:
                    clipped_docs.add(label)
            pairs.append((ends[0], ends[1]))

        # An example that does not fit is dropped whole. Clipping the assembled block instead would
        # leave a half-open `<example>` tag on the wire, and keeping a dropped document's count
        # would report an exposure that never happened.
        block, kept = _fit_examples(pairs, field_limit("examples"))
        for index in range(1, kept + 1):
            for kind in ("incoming", "reply"):
                label = f"example_{index}_{kind}"
                results[label] = docs[label]
                if label in clipped_docs:
                    truncated.add(label)
        values["examples"] = block
        if kept < len(pairs):
            truncated.add("examples")

    for label, raw in (built or {}).items():
        if label == "examples":
            raise PromptAssetError(
                f"{spec.qualified_id} builds its own examples block", FailureCode.CONTEXT_UNBOUND
            )
        text, clipped = clip(_shape(label, normalize(raw)), field_limit(label))
        values[label] = text
        if clipped:
            truncated.add(label)

    declared = set(spec.declares)
    missing = declared - set(values)
    extra = set(values) - declared
    if missing or extra:
        raise PromptAssetError(
            f"{spec.qualified_id} context does not match its declarations "
            f"(missing={sorted(missing)}, extra={sorted(extra)})",
            FailureCode.CONTEXT_UNBOUND,
        )

    current = next((label for label in CURRENT_FIELD_ORDER if label in values), spec.declares[0])
    return RequestContext(
        spec=spec,
        values=values,
        redaction=RequestRedaction(
            documents=results, ledger=scope, current=current, truncated=bool(truncated)
        ),
        truncated=frozenset(truncated),
        request_limit=request_limit_for(spec, cfg),
        context_version=CONTEXT_VERSION,
    )


def examples_block(pairs: Sequence[tuple[str, str]]) -> str:
    """Render owner reply pairs in the markup docs/PROMPTS.md section 5 documents."""
    if not pairs:
        return ""
    return "\n".join(
        f"{INDENT}<example><incoming>{incoming}</incoming><reply>{reply}</reply></example>"
        for incoming, reply in pairs
    )


def style_facts(pairs: Sequence[tuple[str, object]]) -> str:
    """Format owner style facts as the single-line `k=v; k=v` string section 5 shows."""
    return "; ".join(
        f"{key}={' '.join(str(value).split()).translate(MARKUP_TABLE)}" for key, value in pairs
    )


def _fit_examples(pairs: Sequence[tuple[str, str]], limit: int) -> tuple[str, int]:
    """Keep whole reply examples until the block reaches its bound, and report how many survived."""
    lines: list[str] = []
    total = 0
    for pair in pairs:
        line = examples_block([pair])
        extra = len(line) + (1 if lines else 0)
        if total + extra > limit:
            break
        lines.append(line)
        total += extra
    return "\n".join(lines), len(lines)


def header_names(text: str) -> list[str]:
    return [" ".join(m.group(1).split()).lower() for m in HEADER.finditer(text)]


def check_headers(spec: JobSpec, template: str, rendered: str) -> None:
    """Fail if the data a request carries invented a machine header the template never declared.

    The template's own header lines are the allowed set and the allowed count for each name, so a
    value whose first character reached column zero and reads `Subject: x` stops the request here
    instead of becoming a second header that a reader would trust over ours.
    """
    allowed = header_names(template)
    seen = header_names(rendered)
    for name in seen:
        if seen.count(name) > allowed.count(name):
            raise PromptAssetError(
                f"{spec.qualified_id} rendered context has an undeclared header '{name}'",
                FailureCode.HEADER_CONFLICT,
            )


def compile_bounded_request(asset: PromptAsset, ctx: RequestContext) -> tuple[str, str]:
    """Render the exact (system, user) pair a job sends, then re-check its header shape."""
    system, user = compile_request(asset, dict(ctx.values), user_limit=ctx.request_limit)
    check_headers(asset.spec, asset.user, user)
    return system, user


__all__ = [
    "CONTEXT_VERSION",
    "FILE_SNIPPET_MAX_CHARS",
    "MAX_REPLY_EXAMPLES",
    "RequestContext",
    "build_request_context",
    "check_headers",
    "compile_bounded_request",
    "examples_block",
    "field_limit",
    "header_names",
    "normalize",
    "owner_name_tokens",
    "quarantine_limit",
    "redaction_names",
    "request_limit_for",
    "style_facts",
]
