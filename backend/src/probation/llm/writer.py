"""P08 reply generation, independent of preview/prediction and target-app I/O."""

from collections.abc import Sequence
from email.utils import parseaddr
from statistics import median

from pydantic import ValidationError

from probation.llm.consumers import RegisteredConsumer
from probation.llm.context import redaction_names
from probation.llm.draft_validation import DraftInvalid, body_hash, validate_draft
from probation.llm.gateway import JobFailure
from probation.llm.jobs import ReplyWriter
from probation.llm.prompt_loader import PromptAssetError
from probation.llm.redact import restore_person
from probation.llm.results import FailureCode, Provenance, WriterOutcome, WriterStatus


def unavailable_provenance() -> Provenance:
    return Provenance("writer.reply", "v2", None, None, None, "none", "none", "writer")


def generate_reply(
    consumer: RegisteredConsumer | None,
    *,
    incoming: str,
    original_sender: str,
    situation_id: str,
    preview_warrants_reply: bool,
    examples: Sequence[tuple[str, str]] = (),
    display_names: Sequence[str] = (),
) -> WriterOutcome:
    """Call only after preview; caller supplies bounded eligible examples from HistoryView.

    At most two logical generations; gateway transport repair/retries remain separately
    budgeted. Retrying the same redacted question reuses the validated cached response.
    A deterministic validation failure is not a licence to bypass cache identity.
    """
    provenance = unavailable_provenance()
    recipient = parseaddr(original_sender)[1]
    if "@" not in recipient or any(c in original_sender for c in "\r\n"):
        recipient = ""
    if not preview_warrants_reply or consumer is None or not recipient:
        return WriterOutcome(
            WriterStatus.UNAVAILABLE,
            None,
            False,
            None,
            provenance,
            failure=FailureCode.DRAFT_UNAVAILABLE,
        )
    pairs = tuple(examples[:3])
    words = int(median([len(reply.split()) for _, reply in pairs])) if pairs else 0
    greetings = [reply.split()[0].strip(",!") for _, reply in pairs if reply.split()]
    greeting = next((x for x in greetings if x in {"Hi", "Hello", "Dear"}), "unknown")
    signoff = next(
        (x for x in ("Regards", "Thanks", "Sincerely") if any(x in r for _, r in pairs)), "unknown"
    )
    facts = f"greeting={greeting}; signoff={signoff}; median_words={words}; formality=unknown; examples={len(pairs)}; style_support={'available' if pairs else 'unavailable'}"
    for attempt in range(1, 3):
        try:
            context = consumer.context(
                "writer.reply",
                {"incoming": incoming, "examples": "", "style_facts": facts},
                examples=pairs,
                display_names=(*redaction_names(original_sender), *display_names),
                prompt_version="v2",
            )
            result = consumer.run(context, purpose="reply_draft", situation_id=situation_id)
            provenance = result.provenance
            output = ReplyWriter.model_validate(dict(result.data), strict=True)
            # Validate redacted output first against the actual redacted source context.
            notes = validate_draft(
                output.body,
                context.values["incoming"],
                allow_person_tokens=True,
                needs_user_input=output.needs_user_input,
            )
            restored, unresolved = restore_person(output.body, context.restore_authority)
            if unresolved:
                raise DraftInvalid("foreign_person_placeholder")
            validate_draft(restored, incoming, needs_user_input=output.needs_user_input)
            return WriterOutcome(
                WriterStatus.NEEDS_USER_INPUT if output.needs_user_input else WriterStatus.DRAFTED,
                restored,
                output.needs_user_input,
                recipient,
                provenance,
                (*notes, f"body_sha256:{body_hash(restored)}"),
                attempt,
            )
        except (DraftInvalid, ValidationError):
            if attempt == 2:
                return WriterOutcome(
                    WriterStatus.INVALID,
                    None,
                    False,
                    recipient,
                    provenance,
                    ("draft_invalid",),
                    attempt,
                    FailureCode.DRAFT_INVALID,
                )
            facts += "; previous_draft=rejected_by_local_validator"
        except (JobFailure, PromptAssetError) as exc:
            return WriterOutcome(
                WriterStatus.FAILED,
                None,
                False,
                recipient,
                provenance,
                attempts=attempt,
                failure=exc.code,
            )
    raise AssertionError("bounded writer exhausted without outcome")
