import { useEffect } from "react";
import { useItemRead } from "../api/queries";
import { QueueItem } from "../api/types";
import { reviewActionLabel, ReviewDecision, ReviewForm } from "../components/queue/ReviewForm";
import { VerificationCard } from "../components/queue/VerificationCard";
import { Button } from "../components/common/Button";
import { StatePanel } from "../components/common/StatePanel";

interface ItemDetailViewProps {
  id: string;
  item?: QueueItem;
  authenticated: boolean;
  readOnly?: boolean;
  review: {
    busy: boolean;
    conflict: string | null;
    error: string | null;
    submit(proposalId: string, decision: ReviewDecision): Promise<string | null>;
    refresh(): void;
  };
  onBack(): void;
}

/**
 * One email: what Probation found, what it wants to do, the verified facts with their
 * citations, and only the decisions this item actually supports.
 */
export function ItemDetailView({ id, item, authenticated, readOnly = false, review, onBack }: ItemDetailViewProps) {
  const read = useItemRead(id, authenticated);
  const detail = read.data ?? null;
  const readError = read.error instanceof Error ? read.error.message : null;
  const readStatus = (read.error as { status?: number } | null)?.status;

  // A fresh review is required after a conflict, so the binding is dropped and the
  // detail re-read before the owner can confirm again.
  useEffect(() => {
    if (review.conflict !== null) void read.refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [review.conflict]);

  const title = item?.summary || detail?.summary || "Email details";
  const action = detail?.action || item?.action || "";
  const supported = detail?.supported_actions ?? [];
  const draftText = detail?.draft?.body_text ?? item?.draft?.body_text ?? null;
  const needsInput = detail?.draft?.needs_user_input ?? item?.draft?.needs_user_input ?? false;
  const answered = detail?.user_response ?? null;
  const expiry = detail?.proposed_at ?? item?.proposed_at ?? null;
  const gateLabel = (item?.gate ?? detail?.gate) === "SUGGEST" ? "Suggested for you" : "Needs your decision";

  const submit = (decision: ReviewDecision) => {
    void review.submit(id, decision);
  };

  return (
    <article className="max-w-3xl space-y-6">
      <a href={readOnly ? "#/watching" : "#/queue"} onClick={(event) => { event.preventDefault(); onBack(); }} className="min-h-11 text-sm text-ink-secondary underline underline-offset-4">
        ← Back to review
      </a>
      <header className="space-y-2">
        <p className="text-sm text-ink-secondary">Email · {gateLabel}</p>
        <h1 className="font-serif text-2xl font-normal break-words">{title}</h1>
        <p className="text-sm text-ink-secondary">
          Requested action: <span className="text-ink">{reviewActionLabel(action)}</span>
          {expiry !== null ? ` · Proposed ${expiry}` : ""}
        </p>
      </header>

      {readError !== null && (
        <StatePanel
          state={readStatus === 401 || readStatus === 403 ? "locked" : "error"}
          title="Email details are unavailable"
          description={readError}
          onRetry={() => void read.refetch()}
          retryLabel="Try again"
        />
      )}
      {read.isFetching && detail === null && readError === null && (
        <p role="status" className="text-sm text-ink-secondary">Loading email details…</p>
      )}
      {detail !== null && read.isStale && (
        <p role="status" className="text-sm text-status-warning">
          This detail is out of date. A newer version may exist.
        </p>
      )}

      {answered !== null && (
        <p role="status" className="rounded-xl border border-line bg-surface p-4 text-sm">
          You already answered this: {answered.response}. Nothing will be sent again.
        </p>
      )}

      {detail !== null && (
        <>
          <section aria-labelledby="why-title" className="border-t border-line pt-5 space-y-3">
            <h2 id="why-title" className="text-base font-medium">
              Why Probation suggested this
            </h2>
            {detail.explanation.summary_reason && <p className="text-sm text-ink-secondary">{detail.explanation.summary_reason}</p>}
            {detail.explanation.top_clues.length > 0 ? (
              <ul className="list-disc space-y-1 pl-5 text-sm text-ink-secondary">
                {detail.explanation.top_clues.map((clue, index) => (
                  <li key={`${clue}-${index}`}>{clue}</li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-ink-secondary">No explanation is available for this suggestion.</p>
            )}
            <details className="text-sm">
              <summary className="min-h-11 cursor-pointer py-2 text-ink underline underline-offset-4">Details</summary>
              <div className="space-y-1 text-ink-secondary">
                <p>Task: {detail.class_key || "unavailable"}</p>
                <p>Evidence cutoff: {detail.verification_as_of ?? detail.proposed_at}</p>
                <p>
                  Evidence line: {String(detail.evidence.k_strong ?? 0)} matching choices out of{" "}
                  {String(detail.evidence.n_strong ?? 0)}.
                </p>
                <p>Current permission: level {String(detail.licence.level ?? 0)}.</p>
                <p>Web effect on this decision: web facts can only restrict, never widen, what Probation may do.</p>
              </div>
            </details>
          </section>

          <VerificationCard card={detail.verification_card} asOf={detail.verification_as_of} />

          {review.conflict !== null && (
            <div role="alert" aria-live="assertive" className="space-y-2 rounded-xl border border-status-warning/30 bg-status-warning/10 p-4">
              <p className="text-sm font-medium text-ink">Nothing was sent.</p>
              <p className="text-sm text-ink-secondary">{review.conflict}</p>
              <Button type="button" variant="secondary" size="md" onClick={review.refresh}>
                Review it again
              </Button>
            </div>
          )}

          <ReviewForm
            formKey={id}
            proposedAction={action}
            supportedActions={supported}
            draftText={draftText}
            draftNeedsInput={needsInput}
            readOnly={readOnly || answered !== null}
            readOnlyNote={
              answered === null
                ? undefined
                : "Your decision is already recorded, so there is nothing left to confirm for this email."
            }
            busy={review.busy}
            // Owned by this view instead: the conflict must not disappear when the item turns
            // read-only because another tab answered it. See the notice above the form.
            conflict={null}
            onReview={submit}
            onFreshReview={review.refresh}
          />
        </>
      )}

      {detail === null && readError === null && !read.isLoading && (
        <StatePanel
          state="empty"
          title="No detail for this email"
          description="Probation has no recorded detail for this item, so there is nothing to review."
        />
      )}
    </article>
  );
}
