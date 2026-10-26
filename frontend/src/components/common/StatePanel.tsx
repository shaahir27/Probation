import { ReactNode } from "react";
import { Button } from "./Button";

export type PanelState = "loading" | "empty" | "error" | "stale" | "locked" | "unsupported";

interface StatePanelProps {
  state: PanelState;
  title: string;
  description: string;
  /** Only for error/stale: retrying must be a real re-read, never a fake success. */
  onRetry?: () => void;
  retryLabel?: string;
  retrying?: boolean;
  action?: ReactNode;
  className?: string;
}

const ROLE: Record<PanelState, "status" | "alert"> = {
  loading: "status",
  empty: "status",
  error: "alert",
  stale: "status",
  locked: "alert",
  unsupported: "status",
};

const HEADING: Record<PanelState, string> = {
  loading: "Loading",
  empty: "Nothing here",
  error: "Not available",
  stale: "Out of date",
  locked: "Locked",
  unsupported: "Not supported yet",
};

/**
 * The shared state panel. Every asynchronous panel uses one of these six states so
 * an unavailable screen is always labelled, never a decorative empty grid.
 */
export function StatePanel({
  state,
  title,
  description,
  onRetry,
  retryLabel = "Try again",
  retrying = false,
  action,
  className = "",
}: StatePanelProps) {
  return (
    <div
      role={ROLE[state]}
      aria-live={state === "error" || state === "locked" ? "assertive" : "polite"}
      className={`rounded-xl border border-line bg-surface p-5 space-y-3 ${className}`.trim()}
    >
      <p className="text-xs font-semibold uppercase tracking-wider text-ink-tertiary">{HEADING[state]}</p>
      <h2 className="text-base font-medium text-ink">{title}</h2>
      <p className="max-w-prose text-sm text-ink-secondary">{description}</p>
      {onRetry && (
        <Button variant="secondary" size="md" onClick={onRetry} disabled={retrying}>
          {retrying ? "Refreshing…" : retryLabel}
        </Button>
      )}
      {action}
    </div>
  );
}

/** An honest explanation for a destination that is not implemented or not accepted. */
export function UnavailablePanel({
  title,
  reason,
  scope,
}: {
  title: string;
  reason: string;
  scope?: string;
}) {
  return (
    <StatePanel
      state="unsupported"
      title={`${title} is unavailable`}
      description={reason}
      action={
        scope ? (
          <p className="max-w-prose text-xs text-ink-tertiary">
            What Probation can do instead: {scope}
          </p>
        ) : undefined
      }
    />
  );
}
