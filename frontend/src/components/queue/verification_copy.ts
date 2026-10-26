/**
 * Verification-card wording, kept pure so it can be asserted without a browser.
 *
 * Truthfulness rules enforced here:
 *  - `unknown` fee status is never rendered as free; it is "Cost not confirmed".
 *  - Availability always resolves to one of the four approved labels. Anything
 *    unrecognised becomes "Unavailable", never "Checked".
 *  - A citation is shown only when it is a safe http(s) URL.
 */

import { VerificationCard } from "../../api/types";

export type AvailabilityTone = "checked" | "partial" | "not_checked" | "unavailable";

const AVAILABILITY_LABEL: Record<AvailabilityTone, string> = {
  checked: "Checked",
  partial: "Partial",
  not_checked: "Not checked",
  unavailable: "Unavailable",
};

const AVAILABILITY_DETAIL: Record<AvailabilityTone, string> = {
  checked: "Probation read a cited public page for this email.",
  partial: "Probation read some of what it expected. Details below are incomplete.",
  not_checked: "Probation did not check the web for this email.",
  unavailable: "This information is unavailable right now.",
};

const CARD_TO_TONE: Record<VerificationCard["availability"], AvailabilityTone> = {
  validated: "checked",
  partial: "partial",
  not_checked: "not_checked",
  unavailable: "unavailable",
};

export function availabilityTone(card: VerificationCard | null): AvailabilityTone {
  if (card === null) return "unavailable";
  return CARD_TO_TONE[card.availability] ?? "unavailable";
}

export function availabilityLabel(card: VerificationCard | null): string {
  return AVAILABILITY_LABEL[availabilityTone(card)];
}

export function availabilityDetail(card: VerificationCard | null): string {
  return AVAILABILITY_DETAIL[availabilityTone(card)];
}

/** Colour-safe tone text; the label is always written out, never colour alone. */
export function availabilityToneClass(card: VerificationCard | null): string {
  switch (availabilityTone(card)) {
    case "checked":
      return "text-status-success";
    case "partial":
      return "text-status-warning";
    case "not_checked":
      return "text-ink-secondary";
    case "unavailable":
      return "text-ink-tertiary";
  }
}

export const COST_NOT_CONFIRMED = "Cost not confirmed";

export function feeStatusCopy(card: VerificationCard | null): string {
  switch (card?.fee_status) {
    case "payment_mentioned":
      return "A payment is mentioned by the cited page. Check it before acting.";
    case "explicit_free":
      return "The cited page states this is free.";
    case "unknown":
    default:
      // An unconfirmed cost is never presented as free.
      return "Probation has not confirmed whether anything costs money.";
  }
}

export function feeStatusHeadline(card: VerificationCard | null): string {
  switch (card?.fee_status) {
    case "payment_mentioned":
      return "Payment mentioned";
    case "explicit_free":
      return "Cited as free";
    case "unknown":
    default:
      return COST_NOT_CONFIRMED;
  }
}

/** Field values are printed as bounded plain text lines, never as markup. */
export function verificationFieldLines(card: VerificationCard | null): Array<{ key: string; value: string }> {
  if (card === null) return [];
  return Object.entries(card.fields).flatMap(([key, value]) => {
    if (value === null || value === undefined) return [];
    const text = Array.isArray(value) ? value.join(", ") : typeof value === "boolean" ? (value ? "yes" : "no") : String(value);
    if (text.trim() === "") return [];
    return [{ key: key.replace(/_/g, " "), value: text }];
  });
}

export function citationCount(card: VerificationCard | null): number {
  return card?.citations.length ?? 0;
}
