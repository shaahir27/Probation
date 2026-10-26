import { useEffect, useState } from "react";
import { isSettledStatus, useResponseStatusRead } from "../api/queries";
import { Button } from "../components/common/Button";
import { LinkButton } from "../components/common/LinkButton";
import { StatePanel } from "../components/common/StatePanel";

/**
 * The durable record of one owner request. Decision recording and execution are two
 * separate results; a queued request is never described as complete.
 */
export function RequestStatusView({ id, authenticated }: { id: string; authenticated: boolean }) {
  const [poll, setPoll] = useState(true);
  const read = useResponseStatusRead(id, authenticated && poll);
  const status = read.data ?? null;
  const execution = status?.execution_status ?? null;
  const decision = status?.decision_status ?? null;
  const errorMessage = read.error instanceof Error ? read.error.message : null;

  useEffect(() => {
    if (isSettledStatus(execution)) setPoll(false);
  }, [execution]);

  const decisionCopy =
    decision === "succeeded"
      ? "Your decision was recorded."
      : decision === "failed"
        ? "Your decision could not be recorded."
        : decision === "not_required"
          ? "No decision record is needed for this request."
          : "Probation is still recording your decision.";

  const executionCopy =
    execution === "succeeded"
      ? "Probation confirmed this action."
      : execution === "failed"
        ? "Probation could not complete this action."
        : execution === "cancelled"
          ? "The action was cancelled."
          : execution === "undone"
            ? "The action was undone."
            : execution === "needs-reconciliation"
              ? "Probation could not confirm whether this happened. Check the email before trying again."
              : execution === "not_required"
                ? "No action was needed for this decision."
                : "Probation has not reported an effect for this request yet.";

  // The durable record is only finished when both halves have settled. A queued request
  // is never described as complete, whatever the individual parts say.
  const queued = !(isSettledStatus(execution) && isSettledStatus(decision));

  return (
    <section className="max-w-xl space-y-4" aria-labelledby="request-title">
      <h1 id="request-title" className="page-title">
        Request status
      </h1>

      {errorMessage !== null && (
        <StatePanel
          state="error"
          title="Status unavailable"
          description={errorMessage}
          onRetry={() => {
            setPoll(true);
            void read.refetch();
          }}
          retryLabel="Check status"
        />
      )}

      {status === null && errorMessage === null && (
        <p role="status" aria-live="polite" className="text-sm text-ink">
          Your request was received. Probation is still processing it.
        </p>
      )}

      {status !== null && (
        <div className="space-y-3 border-t border-line pt-4" role="status" aria-live="polite">
          {queued && <p className="text-sm text-ink">Your request was received. Probation is still processing it.</p>}
          <p className="text-sm text-ink">{executionCopy}</p>
          <p className="text-sm text-ink-secondary">{decisionCopy}</p>
          <p className="text-xs text-ink-tertiary">
            Request {status.request_id} · decision: {decision ?? "unavailable"} · execution: {execution ?? "unavailable"}
          </p>
          {!isSettledStatus(execution) && (
            <p className="text-xs text-ink-tertiary">
              This page refreshes the status on its own. A queued request is never shown as complete.
            </p>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="secondary"
          size="md"
          disabled={read.isFetching}
          onClick={() => {
            setPoll(true);
            void read.refetch();
          }}
        >
          Check status
        </Button>
        <LinkButton href="#/actions" variant="secondary">
          See actions
        </LinkButton>
        <LinkButton href="#/queue" variant="secondary">
          Back to review
        </LinkButton>
      </div>
    </section>
  );
}
