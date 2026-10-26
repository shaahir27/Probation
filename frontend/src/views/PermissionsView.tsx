import { Shield } from "lucide-react";
import { LicenceItem } from "../api/types";
import { StatePanel } from "../components/common/StatePanel";
import { formatWhen } from "../lib/emailText";

interface PermissionsViewProps { licences: LicenceItem[]; errorMessage?: string | null; onRetry?(): void }

const levelName = (level: number) => ["Watching", "Suggests", "Acts with undo", "Acts automatically"][level] ?? "Unavailable";

export function PermissionsView({ licences, errorMessage = null, onRetry }: PermissionsViewProps) {
  const earned = licences
    .filter((entry) => entry.level > 0)
    .filter((entry, index, all) =>
      all.findIndex(
        (other) =>
          other.class_key === entry.class_key &&
          other.action === entry.action &&
          other.level === entry.level,
      ) === index,
    );

  return <section aria-labelledby="permissions-title" className="space-y-6">
    <header className="max-w-2xl">
      <h1 id="permissions-title" className="page-title">Permissions</h1>
      <p className="mt-3 text-sm leading-6 text-ink-secondary">Every kind of email earns its own permission. Your approval of one action never unlocks the next.</p>
    </header>
    {errorMessage !== null ? (
      <StatePanel state="error" title="Permissions are unavailable" description={errorMessage} onRetry={onRetry} retryLabel="Try again" />
    ) : earned.length === 0 ? (
      <div className="flex items-start gap-4 border-t border-line pt-7">
        <Shield aria-hidden="true" size={23} className="mt-1 shrink-0 text-ink-tertiary" />
        <div className="space-y-3">
          <p className="section-heading">No permissions yet</p>
          <p className="section-caption max-w-lg">Permission appears only after Probation has enough evidence for a specific kind of task. Until then, it watches or asks for your decision.</p>
          <a href="#/queue" className="min-h-11 inline-flex items-center text-sm underline underline-offset-4">Go to Review</a>
        </div>
      </div>
    ) : (
      <div className="border-t border-line">
        <ul className="divide-y divide-line">
          {earned.map((entry) => {
            const lowerBound = Number.isFinite(entry.lower_bound) ? `${Math.floor(entry.lower_bound * 100)}%` : "Not available";
            const title = entry.title || entry.action_label || (entry.action === "ABSTAIN" ? "No recommendation yet" : "Email task");
            return <li key={`${entry.class_key}-${entry.action}`} className="py-6 first:pt-5 last:pb-0">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="space-y-1">
                  <h2 className="font-serif text-[20px] font-normal tracking-[-0.015em]">{title}</h2>
                  <p className="text-sm text-ink-secondary">{entry.action_label || entry.action.replace(/_/g, " ").toLowerCase()}</p>
                </div>
                <span className="rounded-full border border-line bg-surface px-3 py-1 text-xs font-semibold text-brand">{levelName(entry.level)}</span>
              </div>
              <details className="mt-2 text-sm">
                <summary className="min-h-11 cursor-pointer py-3 text-ink underline underline-offset-4">Why?</summary>
                <div className="max-w-3xl space-y-3 border-t border-line pt-4 leading-6 text-ink-secondary">
                  {entry.description && <p>{entry.description}</p>}
                  {entry.reasons?.length ? <ul className="list-disc pl-5">{entry.reasons.map((reason, index) => <li key={index}>{reason.replace(/_/g, " ")}</li>)}</ul> : <p>No explanation is available.</p>}
                  <p>Evidence: {entry.k_strong} matching choices out of {entry.n_strong}. Estimated agreement lower bound: {lowerBound}.</p>
                  {entry.valid_until && <p>Checked through {formatWhen(entry.valid_until)}.</p>}
                </div>
              </details>
            </li>;
          })}
        </ul>
      </div>
    )}
    <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-secondary">
      <a href="#/more/insights" className="min-h-11 inline-flex items-center underline underline-offset-4">Historical performance</a>
      <a href="#/more/activity" className="min-h-11 inline-flex items-center underline underline-offset-4">Integrity record</a>
    </div>
  </section>;
}
