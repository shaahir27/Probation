import { RESULT_NOT_CONFIRMED, actionStatusLabel, isConfirmedComplete, isUnconfirmedResult } from "../api/action_status";
import { ActionItem } from "../api/types";
import { Button } from "../components/common/Button";
import { EmptyState } from "../components/common/EmptyState";
import { formatWhen, parseEmailText } from "../lib/emailText";

interface ActionsViewProps {
  actions: ActionItem[];
  busyId: string | null;
  conflict: string | null;
  error: string | null;
  onUndo(actionId: string): void;
}

/**
 * What Probation actually did. A held or unconfirmed operation is never described as
 * completed; `unknown` and `needs-reconciliation` both read "Result not confirmed".
 */
export function ActionsView({ actions, busyId, conflict, error, onUndo }: ActionsViewProps) {
  return (
    <section aria-labelledby="actions-title" className="space-y-6">
      <header>
        <h1 id="actions-title" className="page-title">
          Activity
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-secondary">
          What Probation has done, what is still waiting, and what can be undone or cancelled now.
        </p>
        <p className="mt-2 max-w-2xl text-xs leading-5 text-ink-tertiary">
          Undo is re-checked against the mailbox when you ask. If Probation cannot prove the original state, it refuses the undo and changes nothing.
        </p>
      </header>

      {conflict !== null && (
        <p role="alert" className="rounded-xl border border-status-warning/30 bg-status-warning/10 p-4 text-sm">
          Nothing was sent. {conflict}
        </p>
      )}
      {error !== null && <p role="alert" className="text-sm text-status-danger">{error}</p>}

      {actions.length === 0 ? (
        <EmptyState
          title="No actions yet"
          description="Actions Probation takes will appear here with their current status."
        />
      ) : (
        <ul className="border-t border-line divide-y divide-line">
          {actions.map((action) => {
            const unconfirmed = isUnconfirmedResult(action.status) || isUnconfirmedResult(action.execution_status);
            const confirmed = isConfirmedComplete(action.status) && !unconfirmed;
            // An effect the server could not confirm never reads as completed: the frozen
            // copy for it is "Result not confirmed".
            const label = unconfirmed ? RESULT_NOT_CONFIRMED : actionStatusLabel(action.status);
            const canUndo = Boolean(action.undo_available);
            const text = parseEmailText(action.summary);
            return (
              <li key={action.id} className="flex flex-wrap items-start justify-between gap-4 py-5 first:pt-0 last:pb-0">
                <div className="min-w-0 max-w-3xl space-y-1">
                  <p className="font-serif text-[18px] font-normal leading-[1.35] tracking-[-0.01em] break-words">{action.summary ? text.subject : action.type.replace(/_/g, " ").toLowerCase()}</p>
                  {text.preview && <p className="line-clamp-2 text-sm leading-6 text-ink-secondary">{text.preview}</p>}
                  <p className="text-sm text-ink-secondary">
                    {label}
                    {action.hold_until !== null ? ` · Held until ${formatWhen(action.hold_until)}` : ""}
                    {!confirmed && !unconfirmed ? " · Not completed yet" : ""}
                  </p>
                  {unconfirmed && (
                    <p className="text-sm text-status-warning">
                      Probation could not confirm whether this happened. Check the email before trying again.
                    </p>
                  )}
                  {action.undo_deadline !== null && action.undo_deadline !== undefined && (
                    <p className="text-xs text-ink-tertiary">Undo window until {formatWhen(action.undo_deadline)}.</p>
                  )}
                </div>
                <div className="shrink-0">
                  {canUndo ? (
                    <Button
                      size="md"
                      variant="secondary"
                      disabled={busyId !== null}
                      onClick={() => onUndo(action.id)}
                    >
                      {busyId === action.id ? "Sending…" : action.status === "HELD" ? "Cancel action" : "Undo action"}
                    </Button>
                  ) : (
                    <p className="text-xs text-ink-tertiary">Undo is not available for this action.</p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
