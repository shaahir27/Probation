import { useExposureRead, useLedgerRead, useSettingsRead, useWebFactsRead } from "../api/queries";
import { ExternalLink } from "../components/common/ExternalLink";
import { Button } from "../components/common/Button";
import { StatePanel } from "../components/common/StatePanel";
import { ApiError } from "../api/client";
import { ConnectAppsPanel } from "./ConnectAppsPanel";
import { formatWhen } from "../lib/emailText";

function money(value: number): string {
  return `$${value.toFixed(4)}`;
}

/** A failed read is shown as an error or a locked panel, never as empty data. */
function errorState(error: unknown): { message: string; locked: boolean } | null {
  if (!(error instanceof Error)) return null;
  const status = error instanceof ApiError ? error.status : undefined;
  return { message: error.message, locked: status === 401 || status === 403 };
}

/** Recorded model and search spend, with the caveat that nothing recorded is nothing spent. */
export function UsagePanel({ authenticated }: { authenticated: boolean }) {
  const read = useExposureRead(authenticated);
  const failure = errorState(read.error);
  if (failure !== null) {
    return (
      <StatePanel
        state={failure.locked ? "locked" : "error"}
        title={failure.locked ? "Locked" : "Usage is unavailable"}
        description={failure.message}
        onRetry={failure.locked ? undefined : () => void read.refetch()}
      />
    );
  }
  const usage = read.data;
  if (usage === undefined) return <StatePanel state="loading" title="Reading usage" description="Loading what Probation recorded." />;

  return (
    <div className="space-y-4">
      <dl className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-2xl border border-line bg-surface p-4">
          <dt className="text-xs text-ink-tertiary">Recorded cost</dt>
          <dd className="mt-1 text-2xl">{money(usage.total_cost_usd)}</dd>
        </div>
        <div className="rounded-2xl border border-line bg-surface p-4">
          <dt className="text-xs text-ink-tertiary">Recorded requests</dt>
          <dd className="mt-1 text-2xl">{usage.calls}</dd>
        </div>
      </dl>
      <section
        className="space-y-3 rounded-2xl border border-line bg-surface p-4"
        aria-labelledby="budget-authority-title"
      >
        <h2 id="budget-authority-title" className="text-base font-medium">
          Spend authority
        </h2>
        {usage.budget.available ? (
          <>
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-xs text-ink-tertiary">Confirmed charged</dt>
                <dd className="mt-1 text-xl tabular-nums">{money(usage.budget.confirmed_usd)}</dd>
              </div>
              <div>
                <dt className="text-xs text-ink-tertiary">Estimated / reserved</dt>
                <dd className="mt-1 text-xl tabular-nums">{money(usage.budget.estimated_usd)}</dd>
              </div>
              <div>
                <dt className="text-xs text-ink-tertiary">Unresolved holds</dt>
                <dd className="mt-1 text-xl tabular-nums">{usage.budget.unresolved_holds}</dd>
              </div>
              <div>
                <dt className="text-xs text-ink-tertiary">Priced but never dispatched</dt>
                <dd className="mt-1 text-xl tabular-nums">{usage.budget.never_dispatched}</dd>
              </div>
            </dl>
            {Object.keys(usage.budget.holds_by_state).length > 0 && (
              <ul className="divide-y divide-line text-sm">
                {Object.entries(usage.budget.holds_by_state).map(([state, entry]) => (
                  <li key={state} className="flex flex-wrap items-center justify-between gap-2 py-2">
                    <span>{state.replace(/_/g, " ")}</span>
                    <span className="text-ink-secondary">
                      {entry.attempts} attempts · {money(entry.usd_estimate)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <p className="text-xs leading-5 text-ink-secondary">
              An unresolved hold may already be a charge. It stays counted and is never retried
              automatically.
            </p>
          </>
        ) : (
          <p className="text-sm text-ink-secondary">
            Spend authority is unavailable: {usage.budget.reason}.
          </p>
        )}
      </section>
      <p className="text-sm text-ink-secondary">
        The app's recorded cost and the provider's spend authority are separate records. Only
        requests Probation recorded are counted; an unrecorded cost is not a free one.
      </p>
      {usage.breakdown.length === 0 ? (
        <p className="rounded-xl border border-line bg-surface p-4 text-sm text-ink-secondary">No per-task breakdown is available.</p>
      ) : (
        <ul className="divide-y rounded-2xl border border-line bg-surface text-sm">
          {usage.breakdown.map((row) => (
            <li key={`${row.call_kind}-${row.model_id}`} className="flex flex-wrap items-center justify-between gap-2 p-3">
              <span className="break-words">{row.call_kind.replace(/_/g, " ")}</span>
              <span className="text-ink-secondary">
                {row.calls} calls · {row.tokens_in + row.tokens_out} tokens · {money(row.cost_usd)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** What left the machine, and the exact public queries sent to the web service. */
export function PrivacyPanel({ authenticated }: { authenticated: boolean }) {
  const read = useWebFactsRead(authenticated);
  const failure = errorState(read.error);
  if (failure !== null) {
    return (
      <StatePanel
        state={failure.locked ? "locked" : "error"}
        title={failure.locked ? "Locked" : "Web record is unavailable"}
        description={failure.message}
        onRetry={failure.locked ? undefined : () => void read.refetch()}
      />
    );
  }
  const data = read.data;
  if (data === undefined) return <StatePanel state="loading" title="Reading the web record" description="Loading the recorded searches." />;

  return (
    <div className="space-y-4">
      <p className="text-sm text-ink-secondary">
        Message bodies never go to the web service. Only public entity names and domains are searched, and a search
        result can only restrict or inform a decision — never widen what Probation may do.
      </p>
      <p className="text-sm">
        Searches recorded: <strong>{data.total_calls}</strong> · credits used: <strong>{data.total_credits}</strong>
      </p>
      {data.queries.length === 0 ? (
        <StatePanel state="empty" title="No web searches recorded" description="Probation has not searched the web for this account." />
      ) : (
        <ul className="divide-y rounded-2xl border border-line bg-surface text-sm">
          {data.queries.map((entry) => (
            <li key={entry.id} className="space-y-1 p-3">
              <p className="break-words">{entry.query}</p>
              <p className="text-xs text-ink-tertiary">
                {entry.endpoint} · {formatWhen(entry.created_at)} · {entry.ok ? "returned" : "failed"}
              </p>
            </li>
          ))}
        </ul>
      )}
      {data.entities.map((entity) => (
        <div key={entity.domain} className="space-y-1 rounded-2xl border border-line bg-surface p-4 text-sm">
          <p className="break-words font-medium">{entity.domain}</p>
          <p className="text-xs text-ink-tertiary">Status: {entity.status} · checked {formatWhen(entity.fetched_at)}</p>
          <ul className="flex flex-wrap gap-2 text-xs">
            {entity.sources.map((source, index) => (
              <li key={`${source.url}-${index}`}>
                <ExternalLink url={source.url} title={source.title} />
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

/** Integrity of the activity record on demand — never correctness, never permission. */
export function ActivityPanel({ authenticated }: { authenticated: boolean }) {
  const read = useLedgerRead(false);
  const failure = errorState(read.error);
  const result = read.data ?? null;

  return (
    <div className="space-y-4">
      <p className="text-sm text-ink-secondary">
        This checks that the saved activity record has not been altered. An intact record is not proof that a decision
        was correct, and it does not grant permission.
      </p>
      <Button variant="secondary" size="md" disabled={!authenticated || read.isFetching} onClick={() => void read.refetch()}>
        {read.isFetching ? "Checking…" : "Check the record now"}
      </Button>
      {failure !== null && (
        <StatePanel
          state={failure.locked ? "locked" : "error"}
          title={failure.locked ? "Locked" : "The record check is unavailable"}
          description={failure.message}
        />
      )}
      {result === null && failure === null && (
        <StatePanel
          state="empty"
          title="No check recorded yet"
          description="Probation has not verified the activity record in this session."
        />
      )}
      {result !== null && (
        <div className="space-y-1 rounded-2xl border border-line bg-surface p-4 text-sm" role="status" aria-live="polite">
          <p className={result.ok ? "text-status-success" : "text-status-danger"}>
            {result.ok ? "Activity record verified" : "Activity record check failed"}
          </p>
          <p className="text-xs text-ink-tertiary">
            {result.length} events checked{result.seq !== null ? ` · position ${result.seq}` : ""}
          </p>
          <p className="break-words font-mono text-xs text-ink-secondary">Head: {result.head_hash}</p>
        </div>
      )}
    </div>
  );
}

export function SettingsPanel({ authenticated }: { authenticated: boolean }) {
  const read = useSettingsRead(authenticated);
  const failure = errorState(read.error);
  if (failure !== null) {
    return (
      <StatePanel
        state={failure.locked ? "locked" : "error"}
        title={failure.locked ? "Locked" : "Settings are unavailable"}
        description={failure.message}
        onRetry={failure.locked ? undefined : () => void read.refetch()}
      />
    );
  }
  const settings = read.data;
  if (settings === undefined) return <StatePanel state="loading" title="Reading settings" description="Loading the values in use." />;

  const rows: Array<[string, string]> = [
    ["Clock mode", settings.clock_mode],
    ["Time zone", settings.user_tz],
    ["Spending limit", `$${settings.budget_hard_limit_usd.toFixed(2)}`],
    ["Spot-check rate", `${Math.floor(settings.audit_fraction * 100)}%`],
    ["Suggestions need", `${settings.l1_min_n} examples and a ${Math.floor(settings.l1_min_lb * 100)}% estimate`],
    ["Acts with undo needs", `${settings.l2_min_n} examples and a ${Math.floor(settings.l2_min_lb * 100)}% estimate`],
    ["Acts quietly needs", `${settings.l3_min_n} examples and a ${Math.floor(settings.l3_min_lb * 100)}% estimate`],
    ["Tests valid for", `${settings.exam_valid_days} days`],
    ["Tests per day", `${settings.exam_max_per_day}`],
  ];

  return (
    <div className="space-y-3">
      <p className="text-sm text-ink-secondary">
        These values are fixed by Probation's policy. Nothing here is editable from the dashboard: permission comes from
        evidence, and caps are not stored as user settings.
      </p>
      <dl className="divide-y rounded-2xl border border-line bg-surface text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="flex flex-wrap items-baseline justify-between gap-2 p-3">
            <dt className="text-ink-secondary">{label}</dt>
            <dd className="break-words font-mono text-xs">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function HelpPanel({ profile }: { profile: "private" | "synthetic" | null }) {
  return (
    <div className="space-y-5 text-sm">
      <section className="space-y-2 rounded-2xl border border-line bg-surface p-4">
        <h2 className="text-base font-medium">
          {profile === "synthetic" ? "You are looking at synthetic data" : "You are looking at the private test account"}
        </h2>
        <p className="text-ink-secondary">
          {profile === "synthetic"
            ? "Every email, name, address and result on this screen was generated for a demonstration. It is not a real person's mailbox, and nothing shown here was sent anywhere."
            : "Probation reads only the account you connected, through your local owner session. Gmail read access and action access require separate consent."}
        </p>
      </section>
      <section className="space-y-2">
        <h2 className="text-base font-medium">What this build demonstrates</h2>
        <ul className="list-disc space-y-1 pl-5 text-ink-secondary">
          <li>Gmail observation, an explained suggestion and an owner decision in this browser.</li>
          <li>Google Calendar and Google Drive are planned in Connect apps; they are not connected in this build.</li>
          <li>{profile === "synthetic" ? "Synthetic demo actions do not change Gmail." : "Separately granted action access allows approved Gmail operations; a reply needs a validated draft."}</li>
          <li>Permission is derived from evidence, never granted by a click. A new account starts by watching and asking.</li>
          <li>An unconfirmed result is shown as "Result not confirmed" and is never retried automatically.</li>
          <li>Settings, caps and hands-off lists cannot be edited here.</li>
        </ul>
      </section>
      {profile !== "synthetic" && (
        <section className="space-y-2 rounded-2xl border border-line bg-surface p-4">
          <h2 className="text-base font-medium">Connecting Gmail</h2>
          <p className="text-ink-secondary">
            Open <a href="#/more/connections" className="text-ink underline underline-offset-4">Connect apps</a> and
            choose Connect Gmail. Sign in with a local account or owner key; Google read consent is a separate step. Action access requires another consent.
          </p>
          <p className="text-ink-secondary">
            If the connection does not complete, run the local preflight in the project terminal:
          </p>
          <code className="block rounded-lg bg-surface-recessed p-3 font-mono text-xs text-ink-secondary">
            python -B scripts/d6_gmail_setup.py --check
          </code>
          <p className="text-xs leading-5 text-ink-secondary">
            It prints configuration booleans and the exact loopback redirect URI. It never prints a
            token or secret. For a Web OAuth client, register
            <span className="font-mono"> http://127.0.0.1:8765/ </span> as an authorized redirect URI.
          </p>
        </section>
      )}
      <section className="space-y-1 text-ink-secondary">
        <h2 className="text-base font-medium text-ink">Using your own data</h2>
        <p>
          The command-line import remains for other approved local data (<code className="font-mono text-xs">probation import …</code>).
          There is no browser upload button in this version.
        </p>
      </section>
    </div>
  );
}

export function ConnectionsPanel({ profile }: { profile: "private" | "synthetic" | null }) {
  return <ConnectAppsPanel profile={profile} />;
}
