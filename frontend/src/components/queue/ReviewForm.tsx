import { useEffect, useMemo, useState } from "react";
import { registerSessionReset } from "../../auth/OwnerSession";
import { isValidEmailCandidate } from "../../lib/links";
import { Button } from "../common/Button";

/**
 * The owner's decision, expressed before it is bound to a reviewed payload.
 *
 * `reject` (Reject suggestion) and `leave` (Leave as is) are distinct decisions:
 * rejecting records that Probation was wrong, leaving records that the owner is
 * doing nothing. Forwarding always carries an explicit recipient, because the
 * server refuses a forward without one.
 */
export type ReviewDecision =
  | { kind: "accept" }
  | { kind: "reject" }
  | { kind: "leave" }
  | { kind: "edit"; editedAction: string; editedBody?: string }
  | { kind: "forward"; forwardRecipient: string; introduction?: string };

export const ACTION_LABELS: Record<string, string> = {
  ARCHIVE: "Archive email",
  TRASH: "Move to trash",
  REPLY: "Send this reply",
  FORWARD: "Forward email",
  LEAVE: "Leave as is",
  PREPARE_DECLINE_DRAFT: "Prepare a reply",
};

export function reviewActionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action.replace(/[_|]/g, " ").toLowerCase();
}

interface ReviewFormProps {
  /** Changes when a different email is opened, so drafts never leak across items. */
  formKey: string;
  proposedAction: string;
  supportedActions: string[];
  draftText: string | null;
  draftNeedsInput: boolean;
  readOnly?: boolean;
  /** Overrides the read-only sentence when the reason is not "only observing". */
  readOnlyNote?: string;
  busy?: boolean;
  /** A 409 from the server: the binding changed, so nothing may be resent silently. */
  conflict: string | null;
  onReview(decision: ReviewDecision): void;
  onFreshReview(): void;
}

export function ReviewForm({
  formKey,
  proposedAction,
  supportedActions,
  draftText,
  draftNeedsInput,
  readOnly = false,
  readOnlyNote,
  busy = false,
  conflict,
  onReview,
  onFreshReview,
}: ReviewFormProps) {
  const [selected, setSelected] = useState(proposedAction);
  const [body, setBody] = useState(draftText ?? "");
  const [forwardRecipient, setForwardRecipient] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);

  useEffect(() => {
    setSelected(proposedAction);
    setBody(draftText ?? "");
    setForwardRecipient("");
    setFieldError(null);
  }, [formKey, proposedAction, draftText]);

  // A logout clears every unsubmitted draft and selection with the session.
  useEffect(() => registerSessionReset(() => {
    setBody(draftText ?? "");
    setForwardRecipient("");
    setFieldError(null);
  }), [draftText]);

  const options = useMemo(
    () => (supportedActions.length > 0 ? supportedActions : [proposedAction]),
    [proposedAction, supportedActions],
  );
  const isSupported = options.includes(selected);
  const changedAction = isSupported && selected !== proposedAction;
  const forwardMode = selected === "FORWARD";
  const replyMode = selected === "REPLY";
  const hasDraft = Boolean(draftText);
  const edited = replyMode && hasDraft && body !== (draftText ?? "");

  const submit = (decision: ReviewDecision) => {
    if (decision.kind === "forward") {
      if (!isValidEmailCandidate(forwardRecipient)) {
        setFieldError("Enter the email address to forward to, such as name@example.com.");
        return;
      }
      setFieldError(null);
      onReview({ ...decision, forwardRecipient: forwardRecipient.trim(), introduction: body.trim() === "" ? undefined : body });
      return;
    }
    setFieldError(null);
    onReview(decision);
  };

  const primary = (): ReviewDecision => {
    if (forwardMode) return { kind: "forward", forwardRecipient };
    if (changedAction) return { kind: "edit", editedAction: selected };
    if (edited) return { kind: "edit", editedAction: selected, editedBody: body };
    return { kind: "accept" };
  };

  const primaryLabel = (): string => {
    if (forwardMode) return busy ? "Sending…" : "Forward email";
    if (changedAction) return busy ? "Sending…" : `Use: ${reviewActionLabel(selected)}`;
    if (edited) return busy ? "Sending…" : "Send edited reply";
    return busy ? "Sending…" : reviewActionLabel(selected);
  };

  if (readOnly) {
    return (
      <p className="border-t border-line pt-5 text-sm text-ink-secondary">
        {readOnlyNote ?? "Nothing here is waiting for your decision. Probation is only observing."}
      </p>
    );
  }

  return (
    <form
      className="space-y-4 border-t border-line pt-5"
      onSubmit={(event) => {
        event.preventDefault();
        submit(primary());
      }}
    >
      {conflict !== null && (
        <div role="alert" aria-live="assertive" className="space-y-2 rounded-xl border border-status-warning/30 bg-status-warning/10 p-4">
          <p className="text-sm font-medium text-ink">Nothing was sent.</p>
          <p className="text-sm text-ink-secondary">{conflict}</p>
          <Button type="button" variant="secondary" size="md" onClick={onFreshReview}>
            Review it again
          </Button>
        </div>
      )}

      {(replyMode || forwardMode) && (hasDraft || forwardMode) && (
        <div className="space-y-2">
          <label htmlFor="review-body" className="block text-sm text-ink-secondary">
            {forwardMode ? "Note to include at the top (optional)" : "Read or edit the reply before sending"}
          </label>
          <textarea
            id="review-body"
            value={body}
            onChange={(event) => setBody(event.target.value)}
            maxLength={1200}
            rows={8}
            className="w-full rounded-md border border-line bg-surface p-3 text-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
          />
          {draftNeedsInput && !edited && (
            <p className="text-sm text-status-warning">Probation needs a detail from you before this can be sent.</p>
          )}
        </div>
      )}

      {forwardMode && (
        <div className="space-y-1">
          <label htmlFor="forward-recipient" className="block text-sm text-ink-secondary">
            Forward to
          </label>
          <input
            id="forward-recipient"
            type="email"
            inputMode="email"
            autoComplete="off"
            value={forwardRecipient}
            aria-invalid={fieldError !== null}
            aria-describedby={fieldError !== null ? "forward-recipient-error" : "forward-recipient-help"}
            onChange={(event) => setForwardRecipient(event.target.value)}
            className="w-full min-h-11 rounded-md border border-line bg-surface px-3 text-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
          />
          {fieldError === null ? (
            <p id="forward-recipient-help" className="text-xs text-ink-tertiary">
              Only an address Probation is allowed to write to can be used. It is checked before sending.
            </p>
          ) : (
            <p id="forward-recipient-error" role="alert" className="text-sm text-status-danger">
              {fieldError}
            </p>
          )}
        </div>
      )}

      {options.length > 1 && (
        <div className="space-y-1">
          <label htmlFor="review-action" className="block text-sm text-ink-secondary">
            Action to take
          </label>
          <select
            id="review-action"
            value={isSupported ? selected : options[0]}
            onChange={(event) => setSelected(event.target.value)}
            className="w-full min-h-11 rounded-md border border-line bg-surface px-3 text-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
          >
            {options.map((option) => (
              <option key={option} value={option}>
                {reviewActionLabel(option)}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="submit"
          variant="primary"
          size="md"
          disabled={busy || !isSupported || selected === "LEAVE" || (replyMode && draftNeedsInput && !edited)}
        >
          {primaryLabel()}
        </Button>
        <Button type="button" variant="secondary" size="md" disabled={busy} onClick={() => submit({ kind: "reject" })}>
          Reject suggestion
        </Button>
        {selected !== "LEAVE" && (
          <Button type="button" variant="ghost" size="md" disabled={busy} onClick={() => submit({ kind: "leave" })}>
            Leave as is
          </Button>
        )}
      </div>
      {!isSupported && (
        <p className="text-sm text-ink-secondary">Probation cannot do this safely yet.</p>
      )}
      <p aria-live="polite" className="sr-only">
        {busy ? "Sending your decision to Probation." : ""}
      </p>
    </form>
  );
}
