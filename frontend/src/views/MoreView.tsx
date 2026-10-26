import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import {
  useChainsRead,
  useExamsRead,
  useHabitsRead,
  useMetricsRead,
  useReportCardRead,
  queryKeys,
} from "../api/queries";
import { useAdminCommandFlow } from "../api/mutations";
import { CommandStatus } from "../components/common/CommandStatus";
import { StatePanel, UnavailablePanel } from "../components/common/StatePanel";
import {
  ActivityPanel,
  ConnectionsPanel,
  HelpPanel,
  PrivacyPanel,
  SettingsPanel,
  UsagePanel,
} from "./DataPanels";
import { ChainsPanel, ExamsPanel, HabitsPanel, MetricsPanel, ReportCardPanel } from "./InsightPanels";
import { RadarView } from "./RadarView";

interface MoreViewProps {
  section: string;
  profile: "private" | "synthetic" | null;
  authenticated: boolean;
}

const REPORT_FAMILY = "email_action";

const SECTIONS: Array<{ id: string; label: string; hint: string }> = [
  { id: "insights", label: "Performance", hint: "Historical agreement, measured on recorded history." },
  { id: "metrics", label: "Counts and trends", hint: "What Probation recorded, week by week." },
  { id: "habits", label: "Learned about you", hint: "Patterns found in your own history." },
  { id: "chains", label: "Follow-on patterns", hint: "Sequences Probation noticed, one permission each." },
  { id: "exams", label: "Trick-question tests", hint: "Whether a decision holds when details change." },
  { id: "connections", label: "Connections", hint: "Which account Probation can read." },
  { id: "usage", label: "Cost and usage", hint: "Recorded model and search spend." },
  { id: "privacy", label: "Privacy and web", hint: "What left the machine and which searches were made." },
  { id: "activity", label: "Activity record", hint: "Tamper check on the saved record." },
  { id: "settings", label: "Settings in use", hint: "Effective policy values, read-only." },
  { id: "help", label: "Help and limits", hint: "What this build can and cannot do." },
  { id: "radar", label: "Radar", hint: "Opportunity board, when the pack is active." },
  { id: "library", label: "Reading library", hint: "Saved links, filed into collections." },
];

/**
 * Every secondary destination is discoverable here and renders its own content. A
 * screen that is not accepted for release says so plainly instead of showing a
 * working-looking control or seeded data.
 */
export function MoreView({ section, profile, authenticated }: MoreViewProps) {
  const active = SECTIONS.some((entry) => entry.id === section) ? section : "insights";
  const current = SECTIONS.find((entry) => entry.id === active) ?? SECTIONS[0];

  const report = useReportCardRead(REPORT_FAMILY, authenticated);
  const metrics = useMetricsRead(authenticated);
  const habits = useHabitsRead(authenticated);
  const chains = useChainsRead(authenticated);
  const exams = useExamsRead(authenticated);
  const commands = useAdminCommandFlow();

  const client = useQueryClient();
  const onSettled = useCallback(() => {
    client.invalidateQueries({ queryKey: queryKeys.habits });
    client.invalidateQueries({ queryKey: queryKeys.exams });
  }, [client]);

  const denyHabit = (habitId: string) =>
    void commands.submit("deny-habit", habitId, (requestId) => apiClient.denyHabit(habitId, requestId));
  const runExam = (classKey: string, action: string) =>
    void commands.submit("run-exam", `${classKey}|${action}`, () => apiClient.runExam(classKey, action));

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="font-serif text-2xl">More</h1>
        <p className="text-sm text-ink-secondary">{current.hint}</p>
      </header>

      <nav aria-label="More destinations" className="flex flex-wrap gap-2">
        {SECTIONS.map((entry) => (
          <a
            key={entry.id}
            href={`#/more/${entry.id}`}
            aria-current={entry.id === active ? "page" : undefined}
            className={`min-h-11 rounded-xl border px-3 py-2 text-sm ${
              entry.id === active ? "border-brand/40 bg-surfaceRaised text-ink" : "border-line bg-surface text-ink-secondary"
            }`}
          >
            {entry.label}
          </a>
        ))}
      </nav>

      <CommandStatus commandIds={commands.submitted.map((entry) => entry.commandId)} onSettled={onSettled} />

      {active === "insights" && <ReportCardPanel reportCard={report.data ?? null} />}
      {active === "metrics" && <MetricsPanel metrics={metrics.data ?? null} />}
      {active === "habits" && (
        <HabitsPanel
          habits={habits.data?.habits ?? []}
          busyId={commands.busyKey !== null && commands.busyKey.startsWith("deny-habit:") ? commands.busyKey.slice("deny-habit:".length) : null}
          error={commands.error}
          onDeny={denyHabit}
        />
      )}
      {active === "chains" && <ChainsPanel chains={chains.data?.chains ?? []} />}
      {active === "exams" && (
        <ExamsPanel exams={exams.data?.runs ?? []} busy={commands.busyKey !== null} error={commands.error} onRun={runExam} />
      )}
      {active === "connections" && <ConnectionsPanel profile={profile} />}
      {active === "usage" && <UsagePanel authenticated={authenticated} />}
      {active === "privacy" && <PrivacyPanel authenticated={authenticated} />}
      {active === "activity" && <ActivityPanel authenticated={authenticated} />}
      {active === "settings" && <SettingsPanel authenticated={authenticated} />}
      {active === "help" && <HelpPanel profile={profile} />}
      {active === "radar" && <RadarView authenticated={authenticated} />}
      {active === "library" && (
        <UnavailablePanel
          title="Reading library"
          reason="The Reading pack is not part of this release: there is no reviewed save, classify or archive path for saved links, so there is no library to show. Probation will not display seeded links as a finished feature."
          scope="Email review, the actions list and the activity record are the accepted destinations in this build."
        />
      )}

      {active === "insights" && report.error !== null && (
        <StatePanel
          state="error"
          title="Report card is unavailable"
          description={report.error instanceof Error ? report.error.message : "This information is unavailable right now."}
          onRetry={() => void report.refetch()}
        />
      )}
    </div>
  );
}
