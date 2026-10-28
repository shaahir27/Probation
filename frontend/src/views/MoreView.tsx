import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import { useExamsRead, useMetricsRead, useReportCardRead, queryKeys } from "../api/queries";
import { useAdminCommandFlow } from "../api/mutations";
import { CommandStatus } from "../components/common/CommandStatus";
import { StatePanel, UnavailablePanel } from "../components/common/StatePanel";
import { ActivityPanel, ConnectionsPanel, HelpPanel, PrivacyPanel, SettingsPanel, UsagePanel } from "./DataPanels";
import { ExamsPanel, MetricsPanel, ReportCardPanel } from "./InsightPanels";
interface MoreViewProps { section: string; profile: "private" | "synthetic" | null; authenticated: boolean }
const SECTIONS = [
  { id: "connections", label: "Connect apps" }, { id: "insights", label: "Performance" },
  { id: "metrics", label: "Counts & trends" }, { id: "exams", label: "Trick tests" },
  { id: "privacy", label: "Privacy & web" }, { id: "usage", label: "Cost & usage" },
  { id: "activity", label: "Integrity record" }, { id: "settings", label: "Settings in use" },
  { id: "help", label: "Help & limits" },
];
const OUTSIDE_DEMO = new Set(["habits", "chains", "radar", "library"]);
export function MoreView({ section, profile, authenticated }: MoreViewProps) {
  const active = section || "connections";
  const report = useReportCardRead("email_action", authenticated && active === "insights");
  const metrics = useMetricsRead(authenticated && active === "metrics");
  const exams = useExamsRead(authenticated && active === "exams");
  const commands = useAdminCommandFlow();
  const client = useQueryClient();
  const onSettled = useCallback(() => { client.invalidateQueries({ queryKey: queryKeys.exams }); }, [client]);
  const runExam = (classKey: string, action: string) => void commands.submit("run-exam", `${classKey}|${action}`, () => apiClient.runExam(classKey, action));
  return <div className="space-y-6">
    <header><h1 className="page-title">More</h1><p className="mt-2 text-sm text-ink-secondary">Connections, earned performance, exposure and recorded usage.</p></header>
    <nav aria-label="More destinations" className="flex flex-wrap gap-x-5 gap-y-1 border-b border-line pb-1">{SECTIONS.map((entry) => <a key={entry.id} href={`#/more/${entry.id}`} aria-current={active === entry.id ? "page" : undefined} className={`review-tab ${active === entry.id ? "text-ink border-ink" : "text-ink-secondary"}`}>{entry.label}</a>)}</nav>
    <CommandStatus commandIds={commands.submitted.map((entry) => entry.commandId)} onSettled={onSettled} />
    <div className="space-y-6">
      {active === "connections" && <ConnectionsPanel profile={profile} />}
      {active === "privacy" && <PrivacyPanel authenticated={authenticated} />}
      {active === "usage" && <UsagePanel authenticated={authenticated} />}
      {active === "activity" && <ActivityPanel authenticated={authenticated} />}
      {active === "settings" && <SettingsPanel authenticated={authenticated} />}
      {active === "help" && <HelpPanel profile={profile} />}
      {active === "insights" && report.data && <ReportCardPanel reportCard={report.data} />}
      {active === "metrics" && metrics.data && <MetricsPanel metrics={metrics.data} />}
      {active === "exams" && exams.data && <ExamsPanel exams={exams.data.runs} busy={commands.busyKey !== null} error={commands.error} onRun={runExam} />}
      {OUTSIDE_DEMO.has(active) && <UnavailablePanel title="Outside this email demo" reason="This workflow is not part of the focused email demonstration. Probation has no accepted end-to-end workflow to offer here." scope="Use Overview, Review, Activity and Permissions for this demonstration." />}
    </div>
    {active === "insights" && report.isLoading && <StatePanel state="loading" title="Loading performance" description="Reading recorded results." />}
    {active === "metrics" && metrics.isLoading && <StatePanel state="loading" title="Loading counts" description="Reading recorded activity." />}
    {active === "exams" && exams.isLoading && <StatePanel state="loading" title="Loading tests" description="Reading recorded tests." />}
    {active === "metrics" && metrics.error !== null && <StatePanel state="error" title="Counts are unavailable" description="Could not read recorded counts." onRetry={() => void metrics.refetch()} />}
    {active === "exams" && exams.error !== null && <StatePanel state="error" title="Tests are unavailable" description="Could not read recorded tests." onRetry={() => void exams.refetch()} />}
    {active === "insights" && report.error !== null && <StatePanel state="error" title="Report card is unavailable" description={report.error instanceof Error ? report.error.message : "This information is unavailable right now."} onRetry={() => void report.refetch()} />}
  </div>;
}
