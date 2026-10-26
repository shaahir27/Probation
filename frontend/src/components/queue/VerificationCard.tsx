import { VerificationCard as VerificationCardType } from "../../api/types";
import { ExternalLink } from "../common/ExternalLink";
import { formatWhen } from "../../lib/emailText";
import {
  availabilityDetail,
  availabilityLabel,
  availabilityToneClass,
  citationCount,
  feeStatusCopy,
  feeStatusHeadline,
  verificationFieldLines,
} from "./verification_copy";

interface VerificationCardProps {
  card: VerificationCardType | null;
  /** The as-of stamp the server derived the card at, shown under Why. */
  asOf?: string | null;
}

/**
 * Verified facts for one email: availability in the four approved words, the fee
 * status (an unconfirmed cost is never shown as free), the cited fields and every
 * typed citation as a safe http(s) link.
 *
 * A missing card renders as an explicit unavailable panel. It never renders a
 * placeholder "checked" state and never substitutes another item's sources.
 */
export function VerificationCard({ card, asOf }: VerificationCardProps) {
  const citations = card?.citations ?? [];
  const fields = verificationFieldLines(card);
  const reasons = card?.reasons ?? [];

  return (
    <section aria-labelledby="verification-title" className="border-t border-line pt-5 space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="verification-title" className="text-base font-medium">
          Web check
        </h2>
        <p className={`text-sm font-medium ${availabilityToneClass(card)}`}>
          {availabilityLabel(card)}
        </p>
      </div>
      <p className="text-sm text-ink-secondary">{availabilityDetail(card)}</p>

      <p className="text-sm">
        <span className="font-medium text-ink">{feeStatusHeadline(card)}</span>
        <span aria-hidden="true">: </span>
        <span className="text-ink-secondary">{feeStatusCopy(card)}</span>
      </p>

      {card !== null && card.availability !== "unavailable" && (
        <>
          {fields.length > 0 ? (
            <dl className="grid gap-1 text-sm sm:grid-cols-[max-content_1fr] sm:gap-x-4">
              {fields.map((field) => (
                <div key={field.key} className="contents">
                  <dt className="text-ink-secondary capitalize">{field.key}</dt>
                  <dd className="text-ink break-words">{field.value}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="text-sm text-ink-secondary">No web-derived fields were recorded.</p>
          )}

          <div className="space-y-1">
            <h3 className="text-sm font-medium">
              Sources ({citationCount(card)})
            </h3>
            {citations.length > 0 ? (
              <ol className="list-decimal space-y-1 pl-5 text-sm">
                {citations.map((citation, index) => (
                  <li key={`${citation.url}-${index}`}>
                    <ExternalLink url={citation.url} title={citation.title} />
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-sm text-ink-secondary">
                No source page is cited for these facts. Probation shows nothing as verified without a citation.
              </p>
            )}
          </div>

          {reasons.length > 0 && (
            <details className="text-sm">
              <summary className="min-h-11 cursor-pointer py-2 text-ink underline underline-offset-4">Why</summary>
              <ul className="list-disc space-y-1 pl-5 text-ink-secondary">
                {reasons.map((reason, index) => (
                  <li key={`${reason}-${index}`}>{reason.replace(/_/g, " ")}</li>
                ))}
              </ul>
            </details>
          )}

          <p className="text-xs text-ink-tertiary">
            {card.fetched_at ? `Read on ${formatWhen(card.fetched_at)}. ` : "No read time recorded. "}
            {asOf ? `Judged as of ${formatWhen(asOf)}.` : "The check time could not be confirmed."}
          </p>
        </>
      )}
    </section>
  );
}
