import { Shield } from "lucide-react";
import { LicenceItem } from "../api/types";
import { StatePanel } from "../components/common/StatePanel";
import { formatWhen } from "../lib/emailText";

interface PermissionsViewProps { licences: LicenceItem[]; errorMessage?: string | null; onRetry?(): void }

const levelName = (level: number) => ["Watching", "Suggests", "Acts with undo", "Acts automatically"][level] ?? "Unavailable";

function PermissionRow({ entry }: { entry: LicenceItem }) {
  const checklist = entry.checklist;
  const watching = entry.level === 0;
  const lowerBound = Number.isFinite(entry.lower_bound) ? `${Math.floor(entry.lower_bound * 100)}%` : "Not available";
  const title = entry.title || entry.action_label || (entry.action === "ABSTAIN" ? "No recommendation yet" : "Email task");
  const next = checklist?.next;
  const basis = next?.basis === "all" ? "decisions" : "clean agreements";
  return <li className="py-6 first:pt-5 last:pb-0">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="space-y-1">
        <h2 className="font-serif text-[20px] font-normal tracking-[-0.015em]">{title}</h2>
        <p className="text-sm text-ink-secondary">{entry.action_label || entry.action.replace(/_/g, " ").toLowerCase()}</p>
      </div>
      <span className="rounded-full border border-line bg-surface px-3 py-1 text-xs font-semibold text-brand">{levelName(entry.level)}</span>
    </div>
    {checklist && <div className="mt-4 space-y-1 text-sm text-ink-secondary">
      <p>
        {watching
          ? (entry.n_all > 0 ? `${entry.k_all} of ${entry.n_all} decisions` : "No decisions yet")
          : (checklist.evidence.met
            ? `${checklist.evidence.have} clean agreements — the ${checklist.evidence.need} needed for this level`
            : `${checklist.evidence.have} of ${checklist.evidence.need} clean agreements`)}
        {" · "}
        {checklist.recent.met ? "recent volume met" : `${checklist.recent.have} of ${checklist.recent.need} recent`}
        {" · "}
        {checklist.exam.met ? "test passed" : "test not yet passed"}
        {" · "}
        {checklist.alarm.met ? "no alarm" : "alarm recorded"}
      </p>
      {next && <p>
        {next.remaining_clean > 0
          ? `${next.remaining_clean} more ${basis} for ${levelName(next.level)}` +
            (next.exam_required ? " and a passing test" : "") +
            (next.estimated_days > 0
              ? `, about ${next.estimated_days} days at the recent pace.`
              : ".")
          : `${levelName(next.level)} evidence is met` +
            (next.exam_required && !checklist.exam.met ? " — a passing test is still needed." : ".")}
      </p>}
      {!next && watching && <p>This action changes nothing, so Probation never earns permission for it.</p>}
    </div>}
    <details className="mt-2 text-sm">
      <summary className="min-h-11 cursor-pointer py-3 text-ink underline underline-offset-4">Why?</summary>
      <div className="max-w-3xl space-y-3 border-t border-line pt-4 leading-6 text-ink-secondary">
        {entry.description && <p>{entry.description}</p>}
        {entry.reasons?.length ? <ul className="list-disc pl-5">{entry.reasons.map((reason, index) => <li key={index}>{reason.replace(/_/g, " ")}</li>)}</ul> : <p>No explanation is available.</p>}
        <p>Evidence: {entry.k_strong} matching choices out of {entry.n_strong}. Estimated agreement lower bound: {lowerBound}.</p>
        {watching && <p>All decisions: {entry.k_all} matching out of {entry.n_all}.</p>}
        {entry.history?.length ? <div><p className="font-medium text-ink">Permission changes</p><ul className="list-disc pl-5">{entry.history.map((change) => <li key={`${change.seq}-${change.created_at}`}>{formatWhen(change.created_at)} · {change.old_level ?? "?"} → {change.new_level ?? "?"}{change.reason ? ` · ${change.reason.replace(/_/g, " ")}` : ""}</li>)}</ul></div> : <p>No permission changes recorded yet.</p>}
        <p>{entry.drift?.last_alarm_at ? `Last drift alarm ${formatWhen(entry.drift.last_alarm_at)}.` : "No drift alarm."}</p>
        <div className="flex flex-wrap gap-x-5 gap-y-1">
          <a href="#/more/exams" className="min-h-11 inline-flex items-center underline underline-offset-4">See the test</a>
          <a href="#/more/insights" className="min-h-11 inline-flex items-center underline underline-offset-4">See the backtest</a>
        </div>
        {entry.valid_until && <p>Checked through {formatWhen(entry.valid_until)}.</p>}
      </div>
    </details>
  </li>;
}

export function PermissionsView({ licences, errorMessage = null, onRetry }: PermissionsViewProps) {
  const rows = licences.filter((entry, index, all) =>
    all.findIndex((other) => other.class_key === entry.class_key && other.action === entry.action) === index,
  );
  const watching = rows.filter((entry) => entry.level === 0);
  const earned = rows.filter((entry) => entry.level > 0);
  const counts = [0, 1, 2, 3].map((level) => rows.filter((entry) => entry.level === level).length);

  return <section aria-labelledby="permissions-title" className="space-y-6">
    <header className="max-w-2xl">
      <h1 id="permissions-title" className="page-title">Permissions</h1>
      <p className="mt-3 text-sm leading-6 text-ink-secondary">Every kind of email earns its own permission. Your approval of one action never unlocks the next.</p>
    </header>
    {errorMessage !== null ? (
      <StatePanel state="error" title="Permissions are unavailable" description={errorMessage} onRetry={onRetry} retryLabel="Try again" />
    ) : rows.length === 0 ? (
      <div className="flex items-start gap-4 border-t border-line pt-7">
        <Shield aria-hidden="true" size={23} className="mt-1 shrink-0 text-ink-tertiary" />
        <div className="space-y-3">
          <p className="section-heading">No permissions yet</p>
          <p className="section-caption max-w-lg">Permission appears only after Probation has enough evidence for a specific kind of task. Until then, it watches or asks for your decision.</p>
          <a href="#/queue" className="min-h-11 inline-flex items-center text-sm underline underline-offset-4">Go to Review</a>
        </div>
      </div>
    ) : <>
      <p className="flex flex-wrap gap-x-5 gap-y-1 border-y border-line py-3 text-sm text-ink-secondary" aria-label="Permission ladder summary">
        <span><strong className="text-ink">{counts[0]}</strong> {levelName(0)}</span>
        <span><strong className="text-ink">{counts[1]}</strong> {levelName(1)}</span>
        <span><strong className="text-ink">{counts[2]}</strong> {levelName(2)}</span>
        <span><strong className="text-ink">{counts[3]}</strong> {levelName(3)}</span>
      </p>
      {earned.length > 0 && <div>
        <h2 className="section-heading mb-2">Earned</h2>
        <ul className="divide-y divide-line border-t border-line">
          {earned.map((entry) => <PermissionRow key={`${entry.class_key}-${entry.action}`} entry={entry} />)}
        </ul>
      </div>}
      {watching.length > 0 && <div>
        <h2 className="section-heading mb-2">Still watching</h2>
        <p className="mb-2 text-sm text-ink-secondary">These tasks are building evidence. They are not failures.</p>
        <ul className="divide-y divide-line border-t border-line">
          {watching.map((entry) => <PermissionRow key={`${entry.class_key}-${entry.action}`} entry={entry} />)}
        </ul>
      </div>}
    </>}
    <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-secondary">
      <a href="#/more/insights" className="min-h-11 inline-flex items-center underline underline-offset-4">Historical performance</a>
      <a href="#/more/activity" className="min-h-11 inline-flex items-center underline underline-offset-4">Integrity record</a>
    </div>
  </section>;
}
