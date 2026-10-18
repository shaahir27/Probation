import { useEffect, useState, useCallback } from "react";
import { Sparkles } from "lucide-react";
import { apiClient } from "./api/client";
import {
  ActionItem,
  ChainItem,
  ExamRunItem,
  HabitItem,
  LicenceItem,
  MetricsSummaryResponse,
  QueueItem,
  ReportCardResponse,
} from "./api/types";
import { DesktopSidebar } from "./components/layout/DesktopSidebar";
import { MobileNav } from "./components/layout/MobileNav";
import { Header } from "./components/layout/Header";
import { ErrorBanner } from "./components/common/ErrorBanner";
import { HomeView } from "./views/HomeView";
import { QueueView } from "./views/QueueView";
import { ActionsView } from "./views/ActionsView";
import { PermissionsView } from "./views/PermissionsView";
import { MoreView } from "./views/MoreView";

export default function App() {
  const [currentTab, setCurrentTab] = useState<string>("home");
  const [previewMode, setPreviewMode] = useState<boolean>(false);
  const [radarActive, setRadarActive] = useState<boolean>(false);
  const [clockMode, setClockMode] = useState<string>("live");
  const [simulatedDate, setSimulatedDate] = useState<string | undefined>(undefined);

  // Core Data
  const [queueItems, setQueueItems] = useState<QueueItem[]>([]);
  const [actions, setActions] = useState<ActionItem[]>([]);
  const [licences, setLicences] = useState<LicenceItem[]>([]);
  const [reportCard, setReportCard] = useState<ReportCardResponse | null>(null);
  const [metrics, setMetrics] = useState<MetricsSummaryResponse | null>(null);
  const [habits, setHabits] = useState<HabitItem[]>([]);
  const [chains, setChains] = useState<ChainItem[]>([]);
  const [exams, setExams] = useState<ExamRunItem[]>([]);

  // Loading & Error States
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // 1. Fetch replay / health state
      try {
        const replay = await apiClient.getReplayState();
        setClockMode(replay.mode || "live");
        setSimulatedDate(replay.simulated_date);
      } catch {
        // Fallback to live health check if replay endpoint fails
        try {
          const health = await apiClient.getHealth();
          setClockMode(health.mode || "live");
        } catch {
          // If backend is entirely down and not in preview mode, let error bubble
          if (!previewMode) {
            throw new Error(
              "Unable to connect to Probation backend at http://localhost:8000. Start backend with `make serve` or enable Preview Mode."
            );
          }
        }
      }

      // 2. Fetch Board Radar state (fail-closed check for conditional visibility)
      try {
        const radarRes = await apiClient.getBoard("radar");
        setRadarActive(Boolean(radarRes?.active));
      } catch {
        setRadarActive(false);
      }

      // 3. Fetch Core Data concurrently
      const [
        queueRes,
        actionsRes,
        licencesRes,
        reportRes,
        metricsRes,
        habitsRes,
        chainsRes,
        examsRes,
      ] = await Promise.all([
        apiClient.getQueue(),
        apiClient.getActions(),
        apiClient.getLicences(),
        apiClient.getReportCard("email_action").catch(() => null),
        apiClient.getMetricsSummary().catch(() => null),
        apiClient.getHabits().catch(() => ({ habits: [] })),
        apiClient.getChains().catch(() => ({ chains: [] })),
        apiClient.getExams().catch(() => ({ runs: [] })),
      ]);

      setQueueItems(queueRes.items || []);
      setActions(actionsRes.actions || []);
      setLicences(licencesRes.licences || []);
      setReportCard(reportRes);
      setMetrics(metricsRes);
      setHabits(habitsRes.habits || []);
      setChains(chainsRes.chains || []);
      setExams(examsRes.runs || []);
    } catch (err: unknown) {
      setError(
        err instanceof Error
          ? err.message
          : "An unexpected error occurred while communicating with the API."
      );
    } finally {
      setLoading(false);
    }
  }, [previewMode]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleTogglePreview = () => {
    const next = !previewMode;
    setPreviewMode(next);
    apiClient.setPreviewMode(next);
  };

  const handleRespond = async (
    id: string,
    response: "accept" | "reject" | "edit",
    editedAction?: string
  ) => {
    await apiClient.respondQueue(id, response, editedAction);
    // Optimistically update queue view
    setQueueItems((prev) => prev.filter((item) => item.id !== id));
  };

  const handleUndo = async (actionId: string) => {
    await apiClient.undoAction(actionId);
    // Refresh actions to show updated status
    const updated = await apiClient.getActions();
    setActions(updated.actions || []);
  };

  const handleDenyHabit = async (habitId: string) => {
    await apiClient.denyHabit(habitId);
    setHabits((prev) =>
      prev.map((h) => (h.id === habitId ? { ...h, status: "denied", denied: true } : h))
    );
  };

  const handleRunExam = async (classKey: string, action: string) => {
    await apiClient.runExam(classKey, action);
    const updated = await apiClient.getExams();
    setExams(updated.runs || []);
  };

  const getPageTitle = (tab: string) => {
    switch (tab) {
      case "home":
        return "Home";
      case "queue":
        return "Queue";
      case "actions":
        return "Actions";
      case "permissions":
        return "Permissions";
      case "more":
        return "More";
      default:
        return "Probation";
    }
  };

  return (
    <div className="min-h-screen bg-canvas text-ink flex flex-col md:flex-row font-sans selection:bg-brand selection:text-brand-on">
      {/* Desktop Sidebar (Persistent 5 Destinations) */}
      <div className="hidden md:block">
        <DesktopSidebar
          currentTab={currentTab}
          onTabChange={setCurrentTab}
          queueCount={queueItems.length}
          previewMode={previewMode}
          onTogglePreview={handleTogglePreview}
        />
      </div>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-h-screen pb-20 md:pb-6">
        <Header
          title={getPageTitle(currentTab)}
          mode={clockMode}
          simulatedDate={simulatedDate}
        />

        {/* Visible Preview Banner (Strictly labeled when enabled) */}
        {previewMode && (
          <div className="bg-brand/10 border-b border-brand/30 px-6 py-2.5 flex items-center justify-between text-xs text-brand">
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 flex-shrink-0" />
              <span>
                <strong>Preview Mode Active:</strong> Displaying synthetic demonstration fixtures
                (Persona: Meena). Real actions will not be performed.
              </span>
            </div>
            <button
              onClick={handleTogglePreview}
              className="text-xs font-semibold underline hover:text-ink ml-4"
            >
              Exit Preview
            </button>
          </div>
        )}

        {/* Core View Container */}
        <main className="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
          {error && (
            <div className="mb-6">
              <ErrorBanner message={error} onRetry={loadData} />
            </div>
          )}

          {loading ? (
            <div className="space-y-4 animate-pulse">
              <div className="h-28 bg-surface rounded-2xl border border-line" />
              <div className="h-64 bg-surface rounded-2xl border border-line" />
            </div>
          ) : (
            <>
              {currentTab === "home" && (
                <HomeView
                  queueItems={queueItems}
                  licences={licences}
                  onNavigate={setCurrentTab}
                />
              )}

              {currentTab === "queue" && (
                <QueueView items={queueItems} onRespond={handleRespond} />
              )}

              {currentTab === "actions" && (
                <ActionsView actions={actions} onUndo={handleUndo} />
              )}

              {currentTab === "permissions" && (
                <PermissionsView licences={licences} />
              )}

              {currentTab === "more" && (
                <MoreView
                  reportCard={reportCard}
                  metrics={metrics}
                  habits={habits}
                  chains={chains}
                  exams={exams}
                  onDenyHabit={handleDenyHabit}
                  onRunExam={handleRunExam}
                  radarActive={radarActive}
                />
              )}
            </>
          )}
        </main>
      </div>

      {/* Mobile Bottom Navigation (Persistent 5 Destinations) */}
      <MobileNav
        currentTab={currentTab}
        onTabChange={setCurrentTab}
        queueCount={queueItems.length}
      />
    </div>
  );
}
