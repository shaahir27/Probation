import { LicenceItem } from "../api/types";
import { StatePanel } from "../components/common/StatePanel";

interface PermissionsViewProps {
  licences: LicenceItem[];
  errorMessage?: string | null;
  onRetry?(): void;
}
const levelName = (level: number) => ["Watching", "Suggests", "Acts with undo", "Acts automatically"][level] ?? "Unavailable";

export function PermissionsView({ licences, errorMessage = null, onRetry }: PermissionsViewProps) {
  if (errorMessage !== null) {
    return (
      <StatePanel
        state="error"
        title="Permissions are unavailable"
        description={errorMessage}
        onRetry={onRetry}
        retryLabel="Try again"
      />
    );
  }
  if (!licences.length) return <StatePanel state="empty" title="No permissions yet" description="Permission appears only after Probation has enough evidence for a specific kind of task." />;
  return <section aria-labelledby="permissions-title" className="space-y-4">
    <header><h1 id="permissions-title" className="font-serif text-2xl">Permissions</h1><p className="mt-1 max-w-2xl text-sm text-ink-secondary">These are read-only. Probation earns permission from evidence and lowers it when it sees a risk.</p></header>
    <ul className="divide-y divide-line border-y border-line">{licences.map((entry) => {
      const lowerBound = Number.isFinite(entry.lower_bound) ? `${Math.floor(entry.lower_bound * 100)}%` : "Not available";
      return <li key={`${entry.class_key}-${entry.action}`} className="py-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium">{entry.title || "Email task"} · {entry.action_label || entry.action.replace(/_/g, " ").toLowerCase()}</h2>
          <span className="text-sm text-ink-secondary">{levelName(entry.level)}</span>
        </div>
        <details className="mt-2 text-sm text-ink-secondary">
          <summary className="min-h-11 cursor-pointer py-2 text-ink underline underline-offset-4">Why?</summary>
          <div className="space-y-2 pb-2">
            {entry.description && <p>{entry.description}</p>}
            {entry.reasons?.length ? <ul className="list-disc pl-5">{entry.reasons.map((reason, i) => <li key={i}>{reason.replace(/_/g, " ")}</li>)}</ul> : <p>No explanation is available.</p>}
            <p>Evidence: {entry.k_strong} matching choices out of {entry.n_strong}. Estimated agreement: {lowerBound}.</p>
            {entry.valid_until && <p>Checked through {entry.valid_until}.</p>}
          </div>
        </details>
      </li>;
    })}</ul>
  </section>;
}
