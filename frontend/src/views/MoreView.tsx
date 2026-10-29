import { type ReactNode, useCallback, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiClient, newRequestId } from "../api/client";
import { useExamsRead, useHabitsRead, useMetricsRead, useReportCardRead, queryKeys } from "../api/queries";
import { useAdminCommandFlow } from "../api/mutations";
import { CommandStatus } from "../components/common/CommandStatus";
import { StatePanel, UnavailablePanel } from "../components/common/StatePanel";
import { MORE_GROUPS, MORE_SECTION_LABELS, moreGroupFor, moreTitle } from "../navigation";
import { ActivityPanel, ConnectionsPanel, HelpPanel, PrivacyPanel, SettingsPanel, UsagePanel } from "./DataPanels";
import { ExamsPanel, HabitsPanel, MetricsPanel, ReportCardPanel } from "./InsightPanels";

interface MoreViewProps { section: string; profile: "private" | "synthetic" | null; authenticated: boolean }

const OUTSIDE_DEMO = new Set(["chains", "radar", "library"]);

function Section({ id, children }: { id: string; children: ReactNode }) {
  const title = MORE_SECTION_LABELS[id] ?? id;
  return <div id={`more-${id}`} className="scroll-mt-24 space-y-3">
    <h2 id={`more-${id}-title`} tabIndex={-1} className="font-serif text-[22px] font-normal tracking-[-0.015em]">{title}</h2>
    {children}
  </div>;
}

export function MoreView({ section, profile, authenticated }: MoreViewProps) {
  const sectionId = section || undefined;
  const group = moreGroupFor(sectionId);
  const groupDef = group === null ? null : MORE_GROUPS.find((entry) => entry.id === group) ?? null;
  const evidenceActive = group === "evidence";
  const report = useReportCardRead("email_action", authenticated && evidenceActive);
  const metrics = useMetricsRead(authenticated && evidenceActive);
  const exams = useExamsRead(authenticated && evidenceActive);
  const habits = useHabitsRead(authenticated && evidenceActive);
  const [habitBusy, setHabitBusy] = useState<string | null>(null);
  const [habitError, setHabitError] = useState<string | null>(null);
  const commands = useAdminCommandFlow();
  const client = useQueryClient();

  useEffect(() => {
    if (sectionId === undefined) {
      document.getElementById("more-title")?.focus();
      return;
    }
    const target = document.getElementById(`more-${sectionId}`);
    if (target) {
      target.scrollIntoView({ block: "start" });
      target.querySelector<HTMLElement>("h2")?.focus();
    }
  }, [sectionId]);

  const denyHabit = async (habitId: string) => {
    setHabitBusy(habitId);
    setHabitError(null);
    try {
      await apiClient.denyHabit(habitId, newRequestId("deny-habit"));
      await client.invalidateQueries({ queryKey: queryKeys.habits });
    } catch {
      setHabitError("That could not be recorded. Nothing changed.");
    } finally {
      setHabitBusy(null);
    }
  };
  const onSettled = useCallback(() => { client.invalidateQueries({ queryKey: queryKeys.exams }); }, [client]);
  const runExam = (classKey: string, action: string) => void commands.submit("run-exam", `${classKey}|${action}`, () => apiClient.runExam(classKey, action));

  return <div className="space-y-6">
    <header>
      <h1 id="more-title" tabIndex={-1} className="page-title">{moreTitle(sectionId)}</h1>
      <p className="mt-2 text-sm text-ink-secondary">{groupDef?.description ?? "What it has learned, what it has earned, and what it spent."}</p>
    </header>
    <nav aria-label="More destinations" className="flex flex-wrap gap-x-5 gap-y-1 border-b border-line pb-1">
      {MORE_GROUPS.map((entry) => <a key={entry.id} href={`#/more/${entry.id}`} aria-current={group === entry.id ? "page" : undefined} className={`review-tab ${group === entry.id ? "text-ink border-ink" : "text-ink-secondary"}`}>{entry.label}</a>)}
    </nav>
    <CommandStatus commandIds={commands.submitted.map((entry) => entry.commandId)} onSettled={onSettled} />

    {groupDef === null && sectionId === undefined && <div className="grid gap-4 md:grid-cols-3">
      {MORE_GROUPS.map((entry) => <a key={entry.id} href={`#/more/${entry.id}`} className="group space-y-2 rounded-[10px] border border-line bg-surface p-5 transition-colors hover:bg-surfaceRaised">
        <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-tertiary">More</p>
        <h2 className="font-serif text-[24px] font-normal tracking-[-0.015em]">{entry.label}</h2>
        <p className="text-sm leading-6 text-ink-secondary">{entry.description}</p>
        <span className="inline-flex min-h-11 items-center text-sm underline underline-offset-4">Open</span>
      </a>)}
    </div>}

    {groupDef?.id === "evidence" && <div className="space-y-10">
      <Section id="insights">
        {report.data ? <ReportCardPanel reportCard={report.data} /> : report.isLoading ? <StatePanel state="loading" title="Loading performance" description="Reading recorded results." /> : report.error !== null ? <StatePanel state="error" title="Report card is unavailable" description={report.error instanceof Error ? report.error.message : "This information is unavailable right now."} onRetry={() => void report.refetch()} /> : null}
      </Section>
      <Section id="metrics">
        {metrics.data ? <MetricsPanel metrics={metrics.data} /> : metrics.isLoading ? <StatePanel state="loading" title="Loading counts" description="Reading recorded activity." /> : metrics.error !== null ? <StatePanel state="error" title="Counts are unavailable" description="Could not read recorded counts." onRetry={() => void metrics.refetch()} /> : null}
      </Section>
      <Section id="exams">
        {exams.data ? <ExamsPanel exams={exams.data.runs} busy={commands.busyKey !== null} error={commands.error} onRun={runExam} /> : exams.isLoading ? <StatePanel state="loading" title="Loading tests" description="Reading recorded tests." /> : exams.error !== null ? <StatePanel state="error" title="Tests are unavailable" description="Could not read recorded tests." onRetry={() => void exams.refetch()} /> : null}
      </Section>
      <Section id="habits">
        {habits.data ? <HabitsPanel habits={habits.data.habits} busyId={habitBusy} error={habitError} onDeny={(habitId) => void denyHabit(habitId)} /> : habits.isLoading ? <StatePanel state="loading" title="Loading what I have learned" description="Reading recorded patterns." /> : habits.error !== null ? <StatePanel state="error" title="What I have learned is unavailable" description="Could not read recorded patterns." onRetry={() => void habits.refetch()} /> : null}
      </Section>
    </div>}

    {groupDef?.id === "access" && <div className="space-y-10">
      <Section id="connections"><ConnectionsPanel profile={profile} /></Section>
      <Section id="privacy"><PrivacyPanel authenticated={authenticated} /></Section>
      <Section id="usage"><UsagePanel authenticated={authenticated} /></Section>
    </div>}

    {groupDef?.id === "record" && <div className="space-y-10">
      <Section id="activity"><ActivityPanel authenticated={authenticated} /></Section>
      <Section id="settings"><SettingsPanel authenticated={authenticated} /></Section>
      <Section id="help"><HelpPanel profile={profile} /></Section>
    </div>}

    {groupDef === null && sectionId !== undefined && OUTSIDE_DEMO.has(sectionId) && <UnavailablePanel title="Outside this email demo" reason="This workflow is not part of the focused email demonstration. Probation has no accepted end-to-end workflow to offer here." scope="Use Overview, Review, Activity and Permissions for this demonstration." />}
  </div>;
}
