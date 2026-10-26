import { useExposureRead, useLedgerRead, useSettingsRead, useWebFactsRead } from "../api/queries";
import { ExternalLink } from "../components/common/ExternalLink";
import { Button } from "../components/common/Button";
import { StatePanel, UnavailablePanel } from "../components/common/StatePanel";
import { ApiError } from "../api/client";

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
      <p className="text-sm text-ink-secondary">
        Only requests Probation recorded are counted. An unrecorded cost is not a free one.
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
                {entry.endpoint} · {entry.created_at} · {entry.ok ? "returned" : "failed"}
              </p>
            </li>
          ))}
        </ul>
      )}
      {data.entities.map((entity) => (
        <div key={entity.domain} className="space-y-1 rounded-2xl border border-line bg-surface p-4 text-sm">
          <p className="break-words font-medium">{entity.domain}</p>
          <p className="text-xs text-ink-tertiary">Status: {entity.status} · checked {entity.fetched_at}</p>
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
    <div className="space-y-4 text-sm">
      <section className="space-y-2 rounded-2xl border border-line bg-surface p-4">
        <h2 className="text-base font-medium">
          {profile === "synthetic" ? "You are looking at synthetic data" : "You are looking at your own account"}
        </h2>
        <p className="text-ink-secondary">
          {profile === "synthetic"
            ? "Every email, name, address and result on this screen was generated for a demonstration. It is not a real person's mailbox, and nothing shown here was sent anywhere."
            : "Probation reads only the account you connected, through the owner key held in memory for this session."}
        </p>
      </section>
      <section className="space-y-2">
        <h2 className="text-base font-medium">Limits of this build</h2>
        <ul className="list-disc space-y-1 pl-5 text-ink-secondary">
          <li>Only email actions are wired end to end. Calendar, files, documents, notes and contacts are not.</li>
          <li>Radar and the Reading library are not accepted destinations; they show why instead of fake boards.</li>
          <li>Sending, archiving and trashing require your explicit decision every time.</li>
          <li>An action whose result could not be confirmed is shown as "Result not confirmed", never as done.</li>
          <li>Settings, caps and hands-off lists cannot be edited here.</li>
        </ul>
      </section>
      <section className="space-y-1 text-ink-secondary">
        <h2 className="text-base font-medium text-ink">Using your own data</h2>
        <p>
          Import happens outside the dashboard with the command line (<code className="font-mono text-xs">probation import …</code>).
          There is no upload button in this version.
        </p>
      </section>
    </div>
  );
}

export function ConnectionsPanel({ profile }: { profile: "private" | "synthetic" | null }) {
  if (profile === "synthetic") {
    return (
      <UnavailablePanel
        title="Connections"
        reason="This is the public synthetic replay. There is no real mailbox connected, so there is nothing to connect, backfill or revoke. The simulated account exists only inside this demonstration workspace."
        scope="The email screens show how a connected account would behave; they are labelled as synthetic data everywhere."
      />
    );
  }
  return (
    <div className="space-y-3 text-sm">
      <p className="text-ink-secondary">
        Your mailbox is connected by the local setup, not from this page. Probation never shows a token, cookie or key
        here, and connecting another source is not available in the dashboard yet.
      </p>
      <UnavailablePanel
        title="Adding a source"
        reason="Calendar, files, IMAP, iCal and MCP sources are not supported in this build."
        scope="Email is the only source with a reviewed read and action path."
      />
    </div>
  );
}
