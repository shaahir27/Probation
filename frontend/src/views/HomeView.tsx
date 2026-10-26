import { useState } from "react";
import { apiClient, newRequestId } from "../api/client";
import { ReplayStateResponse } from "../api/types";
import { LicenceItem, QueueItem } from "../api/types";
import { Button } from "../components/common/Button";
import { EmptyState } from "../components/common/EmptyState";
import { LinkButton } from "../components/common/LinkButton";
import { StatePanel } from "../components/common/StatePanel";

interface HomeViewProps {
  queueItems: QueueItem[];
  licences: LicenceItem[];
  profile: "private" | "synthetic";
  replay: ReplayStateResponse | null;
  replayError: string | null;
  onReplayRefresh(): void;
}

const levelName = (level: number) => ["Watching", "Suggests", "Acts with undo", "Acts automatically"][level] ?? "Unavailable";
const actionName = (action: string) =>
  ({ ARCHIVE: "Archive email", TRASH: "Move to trash", REPLY: "Send this reply", FORWARD: "Forward email", LEAVE: "Leave as is" }[action] ??
    action.replace(/_/g, " ").toLowerCase());

/** Replay controls submit an intent and never claim the replay moved. */
function ReplayControls({ pending, setPending }: { pending: boolean; setPending(value: boolean): void }) {
  const [speed, setSpeed] = useState<1 | 10 | 100>(10);
  const [message, setMessage] = useState<string | null>(null);
  const send = async (kind: "start" | "pause" | "speed") => {
    setPending(true);
    setMessage(null);
    try {
      const requestId = newRequestId(`replay-${kind}`);
      if (kind === "start") await apiClient.startReplay(requestId);
      else if (kind === "pause") await apiClient.pauseReplay(requestId);
      else await apiClient.setReplaySpeed(speed, requestId);
      setMessage("Request received. Probation is still processing it.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Probation could not record the replay request.");
    } finally {
      setPending(false);
    }
  };
  return (
    <section aria-labelledby="replay-title" className="space-y-2 border-t border-line pt-5">
      <h2 id="replay-title" className="text-base font-medium">
        Demo replay
      </h2>
      <p className="text-sm text-ink-secondary">
        Replay runs on the synthetic history only. Probation records the request; it does not claim the clock moved.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" size="md" disabled={pending} onClick={() => void send("start")}>
          Play replay
        </Button>
        <Button variant="secondary" size="md" disabled={pending} onClick={() => void send("pause")}>
          Pause replay
        </Button>
        <label htmlFor="replay-speed" className="text-sm text-ink-secondary">
          Speed
        </label>
        <select
          id="replay-speed"
          value={speed}
          onChange={(event) => setSpeed(Number(event.target.value) as 1 | 10 | 100)}
          className="min-h-11 rounded-md border border-line bg-surface px-2 text-sm"
        >
          <option value={1}>1x</option>
          <option value={10}>10x</option>
          <option value={100}>100x</option>
        </select>
        <Button variant="secondary" size="md" disabled={pending} onClick={() => void send("speed")}>
          Set speed
        </Button>
      </div>
      {message !== null && (
        <p role="status" aria-live="polite" className="text-sm text-ink-secondary">
          {message}
        </p>
      )}
    </section>
  );
}

export function HomeView({ queueItems, licences, profile, replay, replayError, onReplayRefresh }: HomeViewProps) {
  const [replayPending, setReplayPending] = useState(false);
  const needsDecision = queueItems.filter((item) => item.gate === "ASK").length;
  const suggested = queueItems.filter((item) => item.gate === "SUGGEST").length;
  const heading =
    queueItems.length === 0
      ? "Nothing needs your decision"
      : `${queueItems.length} ${queueItems.length === 1 ? "email needs" : "emails need"} your decision`;

  return (
    <div className="space-y-8">
      <section className="border-b border-line pb-6 flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl space-y-2">
          <p className="text-sm text-ink-secondary">
            {profile === "synthetic" ? "Public synthetic replay" : "Private test account"}
          </p>
          <h1 className="font-serif text-2xl sm:text-3xl font-normal">{heading}</h1>
          <p className="text-sm text-ink-secondary">
            Probation reads your own past decisions and asks before acting when it is unsure. It never acts on its own
            without a permission it earned from evidence.
          </p>
          {queueItems.length > 0 && (
            <p className="text-sm text-ink-secondary">
              Needs your decision: {needsDecision}. Suggested for you: {suggested}.
            </p>
          )}
        </div>
        {queueItems.length > 0 && (
          <LinkButton href="#/queue" variant="primary" size="lg">
            Review emails
          </LinkButton>
        )}
      </section>

      <section aria-labelledby="readiness-title" className="space-y-2">
        <h2 id="readiness-title" className="text-base font-medium">
          Current readiness
        </h2>
        {replay === null ? (
          replayError !== null ? (
            <StatePanel state="error" title="Clock state unavailable" description={replayError} onRetry={onReplayRefresh} />
          ) : (
            <p role="status" className="text-sm text-ink-secondary">
              Checking the clock state…
            </p>
          )
        ) : !replay.available ? (
          <p className="text-sm text-status-warning">Replay state is unavailable. Probation is not acting on replay time.</p>
        ) : (
          <p className="text-sm text-ink-secondary">
            {replay.mode === "replay" ? "Running a synthetic replay" : "Live mode"}
            {replay.simulated_date ? ` · Date shown: ${replay.simulated_date.split("T")[0]}` : ""}
            {replay.mode === "replay" ? ` · Speed ${replay.speed}x` : ""}
            {replay.running ? " · Replay is running" : " · Replay is paused"}
          </p>
        )}
        {profile === "synthetic" && <ReplayControls pending={replayPending} setPending={setReplayPending} />}
      </section>

      <section aria-labelledby="permissions-summary" className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 id="permissions-summary" className="text-base font-medium">
            What Probation may do
          </h2>
          <a className="min-h-11 text-sm text-ink-secondary underline underline-offset-4" href="#/permissions">
            See all permissions
          </a>
        </div>
        {licences.length === 0 ? (
          <EmptyState
            title="No permissions yet"
            description="Probation will show a task here after it has enough history to explain what it may do."
          />
        ) : (
          <ul className="divide-y border-y border-line">
            {licences.slice(0, 5).map((entry) => (
              <li key={`${entry.class_key}-${entry.action}`} className="py-3 flex flex-wrap justify-between gap-2 text-sm">
                <span className="text-ink">
                  {entry.title ? `${entry.title} · ${entry.action_label || actionName(entry.action)}` : actionName(entry.action)}
                </span>
                <span className="text-ink-secondary">{levelName(entry.level)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <nav aria-label="Other email views" className="flex flex-wrap gap-x-5 gap-y-2 text-sm">
        <a className="min-h-11 underline underline-offset-4" href="#/watching">
          See what Probation is watching
        </a>
        <a className="min-h-11 underline underline-offset-4" href="#/actions">
          See past actions
        </a>
        <a className="min-h-11 underline underline-offset-4" href="#/more/insights">
          See how Probation has done
        </a>
      </nav>
    </div>
  );
}
