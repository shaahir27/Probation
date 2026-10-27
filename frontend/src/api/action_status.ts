/**
 * Plain-language action states. An unconfirmed result is never shown as done and
 * an unrecognised state is never silently relabelled as a failure or a success.
 */

export const RESULT_NOT_CONFIRMED = "Result not confirmed";

const COPY: Record<string, string> = {
  PENDING: "Waiting",
  HELD: "Waiting before action",
  DONE: "Completed",
  UNDONE: "Undone",
  CANCELLED: "Cancelled",
  FAILED: "Failed",
  // `unknown` is frozen by the D6 API contract for an effect the executor could
  // not confirm. Copy deck: needs_reconciliation -> "Result not confirmed".
  UNKNOWN: RESULT_NOT_CONFIRMED,
  "NEEDS-RECONCILIATION": RESULT_NOT_CONFIRMED,
  NEEDS_RECONCILIATION: RESULT_NOT_CONFIRMED,
};

export const STATUS_UNAVAILABLE = "Status unavailable";

/** Maps any server status token to approved wording; unknown tokens stay unavailable. */
export function actionStatusLabel(status: unknown): string {
  if (typeof status !== "string" || status.trim() === "") return STATUS_UNAVAILABLE;
  return COPY[status.trim().toUpperCase()] ?? STATUS_UNAVAILABLE;
}

/** True only when the server says the effect is confirmed to have happened. */
export function isConfirmedComplete(status: unknown): boolean {
  return typeof status === "string" && status.trim().toUpperCase() === "DONE";
}

const SETTLED = new Set(["DONE", "UNDONE", "CANCELLED", "FAILED"]);

/** A terminal state: nothing is still being waited on, including a completed undo. */
export function isSettledStatus(status: unknown): boolean {
  return typeof status === "string" && SETTLED.has(status.trim().toUpperCase());
}

/** A result the owner must go and check themselves before retrying. */
export function isUnconfirmedResult(status: unknown): boolean {
  if (typeof status !== "string") return false;
  const key = status.trim().toUpperCase();
  return key === "UNKNOWN" || key === "NEEDS-RECONCILIATION" || key === "NEEDS_RECONCILIATION";
}
