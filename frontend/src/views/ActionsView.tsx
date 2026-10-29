import { useEffect, useState } from "react";
import { RESULT_NOT_CONFIRMED, actionStatusLabel, isSettledStatus, isUnconfirmedResult } from "../api/action_status";
import { ActionItem } from "../api/types";
import { useLedgerRead } from "../api/queries";
import { Button } from "../components/common/Button";
import { EmptyState } from "../components/common/EmptyState";
import { formatWhen, parseEmailText } from "../lib/emailText";

function RecordCheck() {
  const read = useLedgerRead(true);
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  useEffect(() => {
    if (read.data) setCheckedAt(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
  }, [read.data, read.dataUpdatedAt]);
  if (read.error !== null) {
    return <p role="alert" className="text-xs text-ink-tertiary">The record check is unavailable right now.</p>;
  }
  if (read.data === undefined) {
    return <p className="text-xs text-ink-tertiary">Checking the record…</p>;
  }
  return <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-y border-line py-2 text-xs text-ink-secondary" aria-live="polite">
    <span className={read.data.ok ? "font-semibold text-status-success" : "font-semibold text-status-danger"}>
      {read.data.ok ? "Record unchanged" : `Record check failed at event ${read.data.seq ?? "unknown"}`}
    </span>
    <span>{read.data.length} events</span>
    {checkedAt && <span>last checked {checkedAt}</span>}
    <button type="button" className="min-h-11 underline underline-offset-4" onClick={() => void read.refetch()}>Check again</button>
  </div>;
}

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
  const held = actions.filter((action) => action.status === "HELD").length;
  const undoable = actions.filter((action) => Boolean(action.undo_available)).length;
  const unconfirmed = actions.filter((action) => isUnconfirmedResult(action.status) || isUnconfirmedResult(action.execution_status)).length;
  return (
    <section aria-labelledby="actions-title" className="activity-page">
      <header className="activity-heading">
        <p className="dashboard-eyebrow">Your workspace</p>
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

      <RecordCheck />
      {actions.length > 0 && <p className="text-xs text-ink-secondary">{actions.length} recorded · {held} held · {undoable} can be cancelled · {unconfirmed} unconfirmed</p>}

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
        <div className="activity-table"><div className="activity-table-heading"><h2>Action history</h2><span>{actions.length} recorded</span></div><ul>
          {actions.map((action) => {
            const unconfirmed = isUnconfirmedResult(action.status) || isUnconfirmedResult(action.execution_status);
            const settled = isSettledStatus(action.status) && !unconfirmed;
            // An effect the server could not confirm never reads as completed: the frozen
            // copy for it is "Result not confirmed".
            const label = unconfirmed ? RESULT_NOT_CONFIRMED : actionStatusLabel(action.status);
            const canUndo = Boolean(action.undo_available);
            const text = parseEmailText(action.summary);
            return (
              <li key={action.id} className="activity-row">
                <div className="min-w-0 space-y-2">
                  <p className="font-serif text-[18px] font-normal leading-[1.35] tracking-[-0.01em] break-words">{action.summary ? text.subject : action.type.replace(/_/g, " ").toLowerCase()}</p>
                  {text.preview && <p className="line-clamp-2 text-sm leading-6 text-ink-secondary">{text.preview}</p>}
                  <p className="text-sm text-ink-secondary">
                    <span className="font-medium text-ink">{action.type.replace(/_/g, " ").toLowerCase()}</span> · {label}
                    {action.hold_until !== null ? ` · Held until ${formatWhen(action.hold_until)}` : ""}
                    {!settled && !unconfirmed ? " · Not completed yet" : ""}
                  </p>
                  {unconfirmed && (
                    <p className="text-sm text-status-warning">
                      Probation could not confirm whether this happened. Check the email before trying again.
                    </p>
                  )}
                  {action.status === "DONE" && action.undo_deadline !== null && action.undo_deadline !== undefined && (
                    <p className="text-xs text-ink-tertiary">Undo window until {formatWhen(action.undo_deadline)}.</p>
                  )}
                  <p className="text-xs text-ink-tertiary">
                    Recorded {formatWhen(action.created_at)}
                    {action.executed_at ? ` · Effect ${formatWhen(action.executed_at)}` : ""}
                    {action.updated_at !== action.created_at ? ` · Updated ${formatWhen(action.updated_at)}` : ""}
                  </p>
                </div>
                <div className="activity-row-control">
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
                    <p className="text-xs text-ink-tertiary">
                      {action.status === "UNDONE"
                        ? "This change was undone."
                        : action.status === "CANCELLED"
                          ? "This action was cancelled."
                          : action.status === "FAILED"
                            ? "No effect was applied."
                            : "Undo is not available for this action."}
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ul></div>
      )}
    </section>
  );
}
