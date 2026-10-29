import { Shield } from "lucide-react";
import { LicenceItem } from "../api/types";
import { StatePanel } from "../components/common/StatePanel";
import { reviewActionLabel } from "../components/queue/ReviewForm";
import { formatWhen } from "../lib/emailText";

interface PermissionsViewProps { licences: LicenceItem[]; errorMessage?: string | null; onRetry?(): void }

const LEVELS = ["Watching", "Suggests", "Acts with undo", "Acts automatically"] as const;
const LEVEL_COPY = [
  "You decide. It does not act on its own.",
  "It recommends an action; you approve it.",
  "It acts in this task, with undo available.",
  "It acts without asking, within its caps.",
];
const NOOP = new Set(["LEAVE", "ABSTAIN", "NO_RESPONSE", "NONE", "REJECT"]);
const levelName = (level: number) => LEVELS[level] ?? "Unavailable";
const lowerBound = (entry: LicenceItem) => {
  const value = entry.level === 0 ? entry.lb_all ?? entry.lower_bound : entry.lb_strong ?? entry.lower_bound;
  return Number.isFinite(value) ? `${Math.floor(value * 100)}%` : "Not available";
};

function PermissionCard({ entry, watching }: { entry: LicenceItem; watching: boolean }) {
  const checklist = entry.checklist;
  const next = checklist?.next ?? null;
  const current = next?.basis === "all" ? entry.n_all : entry.n_strong;
  const target = next?.clean_agreements_needed ?? 0;
  const percent = target > 0 ? Math.min(100, Math.round((current / target) * 100)) : 0;
  const basis = next?.basis === "all" ? "decisions" : "clean agreements";
  const title = entry.title || entry.action_label || "Email task";
  const action = reviewActionLabel(entry.action);
  const testLabel = entry.level === 0 ? "Not required yet" : checklist?.exam.met ? "Passed" : "Not yet";

  const nextCopy = next === null ? "No next level is available for this action." : next.remaining_clean > 0
    ? `${next.remaining_clean} more ${basis} for ${levelName(next.level)}` +
      (next.exam_required ? " and a passing test" : "") +
      (next.estimated_days > 0 ? ` — about ${next.estimated_days} days at the recent pace.` : ".")
    : `${levelName(next.level)} evidence is met` +
      (next.exam_required && !checklist?.exam.met ? "; a passing test is still needed." : ".");

  return <article className="permission-card">
    <header className="permission-card-head">
      <div><h3>{title}</h3><p>{action} · {levelName(entry.level)}</p></div>
      <span className="permission-level">{levelName(entry.level)}</span>
    </header>
    {next !== null && <div className="permission-progress">
      <div className="permission-progress-head"><span>{next.basis === "all" ? "All decisions" : "Clean agreements"}</span><span>{current} of {target}</span></div>
      <div className="permission-progress-track" role="progressbar" aria-valuemin={0} aria-valuemax={target} aria-valuenow={current} aria-label={`${title}: ${current} of ${target}`}>
        <span style={{ width: `${percent}%` }} />
      </div>
      <p className="permission-progress-copy">{nextCopy}</p>
    </div>}
    <dl className="permission-facts">
      <div><dt>{watching ? "Matching decisions" : "Matching choices"}</dt><dd>{watching ? `${entry.k_all} of ${entry.n_all}` : `${entry.k_strong} of ${entry.n_strong}`}</dd></div>
      <div><dt>{watching ? "All-decision estimate" : "Clean-agreement estimate"}</dt><dd>{lowerBound(entry)}</dd></div>
      <div><dt>Recent decisions</dt><dd>{entry.n_recent}</dd></div>
      <div><dt>Test</dt><dd>{testLabel}</dd></div>
      <div><dt>Drift</dt><dd>{entry.drift?.last_alarm_at ? formatWhen(entry.drift.last_alarm_at) : "No alarm"}</dd></div>
    </dl>
    <details className="permission-why">
      <summary>Why?</summary>
      <div>
        {entry.description && <p>{entry.description}</p>}
        {entry.reasons?.length ? <ul className="list-disc pl-5">{entry.reasons.map((reason, index) => <li key={index}>{reason.replace(/_/g, " ")}</li>)}</ul> : <p>No explanation is available.</p>}
        <p>Evidence: {entry.k_strong} matching choices out of {entry.n_strong}. Clean-agreement lower bound: {Math.floor((entry.lb_strong ?? entry.lower_bound) * 100)}%; all-decision lower bound: {Math.floor((entry.lb_all ?? entry.lower_bound) * 100)}%.</p>
        {watching && <p>All decisions: {entry.k_all} matching out of {entry.n_all}.</p>}
        {entry.history?.length ? <div><p className="font-medium text-ink">Permission changes</p><ul className="list-disc pl-5">{entry.history.map((change) => <li key={`${change.seq}-${change.created_at}`}>{formatWhen(change.created_at)} · {levelName(change.old_level ?? 0)} to {levelName(change.new_level ?? entry.level)}{change.reason ? ` · ${change.reason.replace(/_/g, " ")}` : ""}</li>)}</ul></div> : <p>No permission changes recorded yet.</p>}
        <p>{entry.drift?.last_alarm_at ? `Last drift alarm ${formatWhen(entry.drift.last_alarm_at)}.` : "No drift alarm."}</p>
        {entry.valid_until && <p>Checked through {formatWhen(entry.valid_until)}.</p>}
        <div className="flex flex-wrap gap-x-5 gap-y-1"><a href="#/more/evidence">See the test</a><a href="#/more/evidence">See the backtest</a></div>
      </div>
    </details>
  </article>;
}

export function PermissionsView({ licences, errorMessage = null, onRetry }: PermissionsViewProps) {
  const rows = licences.filter((entry, index, all) =>
    all.findIndex((other) => other.class_key === entry.class_key && other.action === entry.action) === index,
  );
  const applicable = rows.filter((entry) => !NOOP.has(entry.action));
  const noop = rows.filter((entry) => NOOP.has(entry.action));
  const watching = applicable.filter((entry) => entry.level === 0).sort((a, b) => (a.checklist?.next?.remaining_clean ?? 999) - (b.checklist?.next?.remaining_clean ?? 999));
  const earned = applicable.filter((entry) => entry.level > 0).sort((a, b) => b.level - a.level || a.class_key.localeCompare(b.class_key));
  const counts = LEVELS.map((_, level) => applicable.filter((entry) => entry.level === level).length);

  return <section aria-labelledby="permissions-title" className="space-y-6">
    <header className="max-w-2xl">
      <h1 id="permissions-title" className="page-title">Permissions</h1>
      <p className="mt-3 text-sm leading-6 text-ink-secondary">Every kind of email earns its own permission. Your approval of one action never unlocks the next.</p>
    </header>
    {errorMessage !== null ? (
      <StatePanel state="error" title="Permissions are unavailable" description={errorMessage} onRetry={onRetry} retryLabel="Try again" />
    ) : applicable.length === 0 ? (
      <div className="flex items-start gap-4 border-t border-line pt-7">
        <Shield aria-hidden="true" size={23} className="mt-1 shrink-0 text-ink-tertiary" />
        <div className="space-y-3">
          <p className="section-heading">No permissions yet</p>
          <p className="section-caption max-w-lg">Permission appears only after Probation has enough evidence for a specific kind of task. Until then, it watches or asks for your decision.</p>
          <a href="#/queue" className="min-h-11 inline-flex items-center text-sm underline underline-offset-4">Go to Review</a>
        </div>
      </div>
    ) : <>
      <section className="permission-explainer" aria-labelledby="permission-explainer-title">
        <h2 id="permission-explainer-title">How a permission is earned</h2>
        <ol className="permission-steps">
          {LEVELS.map((label, level) => <li key={label}><span className="permission-step-dot" aria-hidden="true" /><strong>{label}</strong><p>{LEVEL_COPY[level]}</p><span className="permission-step-count">{counts[level]} {counts[level] === 1 ? "task" : "tasks"}</span></li>)}
        </ol>
      </section>
      {earned.length > 0 && <div>
        <h2 className="section-heading mb-2">Earned</h2>
        <div className="space-y-3">{earned.map((entry) => <PermissionCard key={`${entry.class_key}-${entry.action}`} entry={entry} watching={false} />)}</div>
      </div>}
      {watching.length > 0 && <div>
        <h2 className="section-heading mb-2">Still watching</h2>
        <p className="mb-3 text-sm text-ink-secondary">These tasks are building evidence. They are not failures.</p>
        <div className="space-y-3">{watching.map((entry) => <PermissionCard key={`${entry.class_key}-${entry.action}`} entry={entry} watching />)}</div>
      </div>}
      {noop.length > 0 && <p className="permission-noop">Some actions change nothing (for example, Leave as is). They cannot earn a permission, so they are not counted in the ladder.</p>}
    </>}
    <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-secondary">
      <a href="#/more/evidence" className="min-h-11 inline-flex items-center underline underline-offset-4">Historical performance</a>
      <a href="#/more/record" className="min-h-11 inline-flex items-center underline underline-offset-4">Integrity record</a>
    </div>
  </section>;
}
