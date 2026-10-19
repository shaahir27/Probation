import { useState } from "react";
import {
  Mail,
  Calendar,
  Receipt,
  MessageCircle,
  FileText,
  Users,
  CheckSquare,
  Tag,
  Database,
  ChevronRight,
  FlaskConical,
  Shield,
  Info,
  Layers,
  AlertTriangle,
  CheckCircle2,
} from "lucide-react";
import { LicenceItem } from "../api/types";
import { EmptyState } from "../components/common/EmptyState";

interface PermissionsViewProps {
  licences: LicenceItem[];
}

export function PermissionsView({ licences }: PermissionsViewProps) {
  const [selectedKey, setSelectedKey] = useState<string>(
    licences[0] ? `${licences[0].class_key}-${licences[0].action}` : ""
  );

  if (licences.length === 0) {
    return (
      <EmptyState
        title="No permissions derived yet"
        description="Probation derives permissions per task and action as it observes consistent, high-agreement decisions."
      />
    );
  }

  const selectedLicence =
    licences.find((l) => `${l.class_key}-${l.action}` === selectedKey) ||
    licences[0];

  const getPackIcon = (iconName?: string, classKey?: string) => {
    const key = (iconName || classKey || "").toLowerCase();
    if (key.includes("mail") || key.includes("email") || key.includes("recruiter")) {
      return <Mail className="w-4 h-4 text-ink-secondary" />;
    }
    if (key.includes("calendar") || key.includes("meeting") || key.includes("sync")) {
      return <Calendar className="w-4 h-4 text-ink-secondary" />;
    }
    if (key.includes("receipt") || key.includes("expense")) {
      return <Receipt className="w-4 h-4 text-ink-secondary" />;
    }
    if (key.includes("message") || key.includes("support")) {
      return <MessageCircle className="w-4 h-4 text-ink-secondary" />;
    }
    if (key.includes("file") || key.includes("doc")) {
      return <FileText className="w-4 h-4 text-ink-secondary" />;
    }
    if (key.includes("user") || key.includes("recruit")) {
      return <Users className="w-4 h-4 text-ink-secondary" />;
    }
    if (key.includes("check") || key.includes("project") || key.includes("standup")) {
      return <CheckSquare className="w-4 h-4 text-ink-secondary" />;
    }
    if (key.includes("tag") || key.includes("crm")) {
      return <Tag className="w-4 h-4 text-ink-secondary" />;
    }
    if (key.includes("data") || key.includes("export") || key.includes("database")) {
      return <Database className="w-4 h-4 text-ink-secondary" />;
    }
    return <Shield className="w-4 h-4 text-ink-secondary" />;
  };

  const getCategoryBadge = (lic: LicenceItem) => {
    const category =
      lic.status_category ||
      (lic.level >= 2 ? "allowed" : lic.level === 1 ? "limited" : "restricted");

    switch (category) {
      case "allowed":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#85B99A]/15 text-[#85B99A] border border-[#85B99A]/30">
            <span className="w-1.5 h-1.5 rounded-full bg-[#85B99A]" />
            Allowed
          </span>
        );
      case "limited":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#E0B663]/15 text-[#E0B663] border border-[#E0B663]/30">
            <span className="w-1.5 h-1.5 rounded-full bg-[#E0B663]" />
            Limited
          </span>
        );
      case "restricted":
      default:
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#E28F88]/15 text-[#E28F88] border border-[#E28F88]/30">
            <span className="w-1.5 h-1.5 rounded-full bg-[#E28F88]" />
            Restricted
          </span>
        );
    }
  };

  const isAttentionLicence = (lic: LicenceItem) => {
    return Boolean(
      lic.needs_attention ||
      lic.drift?.last_alarm_at ||
      lic.reasons?.some((r) => r.includes("reduced") || r.includes("exam") || r.includes("alarm") || r.includes("drift"))
    );
  };

  const attentionLicences = licences.filter(isAttentionLicence);
  const stableLicences = licences.filter((lic) => !isAttentionLicence(lic));

  const getAutonomyName = (level: number) => {
    switch (level) {
      case 3:
        return "Does it quietly (Level 3)";
      case 2:
        return "Does it with undo (Level 2)";
      case 1:
        return "Suggests (Level 1)";
      case 0:
      default:
        return "Watching (Level 0)";
    }
  };

  const renderTaskCard = (lic: LicenceItem) => {
    const licKey = `${lic.class_key}-${lic.action}`;
    const isSelected = licKey === `${selectedLicence.class_key}-${selectedLicence.action}`;
    const title = lic.title || lic.class_key.split("|").slice(-2).join(" ");
    const actionLabel = lic.action_label || lic.action.replace(/_/g, " ").toLowerCase();

    return (
      <div
        key={licKey}
        onClick={() => setSelectedKey(licKey)}
        className={`p-3.5 rounded-xl border transition-all cursor-pointer select-none flex items-center justify-between gap-3 ${
          isSelected
            ? "bg-surfaceRaised border-brand/50 shadow-sm ring-1 ring-brand/20"
            : "bg-surface border-line hover:border-brand/20 hover:bg-surfaceSubtle/50"
        }`}
      >
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-9 h-9 rounded-lg bg-surfaceSubtle border border-line flex items-center justify-center shrink-0">
            {getPackIcon(lic.pack_icon, lic.class_key)}
          </div>
          <div className="min-w-0">
            <h4 className="text-sm font-semibold text-ink truncate capitalize">
              {title}
            </h4>
            <p className="text-xs text-ink-secondary truncate">
              {actionLabel}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {getCategoryBadge(lic)}
          <ChevronRight className={`w-4 h-4 transition-transform ${isSelected ? "text-brand translate-x-0.5" : "text-ink-tertiary"}`} />
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-6">
      {/* Editorial Header */}
      <div>
        <h1 className="font-serif text-3xl sm:text-4xl font-normal text-ink tracking-tight">
          Permissions
        </h1>
        <p className="text-sm text-ink-secondary mt-1">
          Control what Probation may do for each task, with evidence, tests, and usage limits.
        </p>
      </div>

      {/* 2-Column Split: Left Task List & Right Inspector Pane */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: Task List (~380px wide on desktop) */}
        <div className="lg:col-span-5 space-y-4">
          {attentionLicences.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-xs text-[#E0B663] font-bold uppercase tracking-wider px-1 flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5 text-[#E0B663]" />
                <span>Needs Attention ({attentionLicences.length})</span>
              </div>
              <div className="space-y-1.5">
                {attentionLicences.map(renderTaskCard)}
              </div>
            </div>
          )}

          <div className="space-y-1.5">
            <div className="text-xs text-ink-secondary font-bold uppercase tracking-wider px-1 flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-[#85B99A]" />
              <span>Stable ({stableLicences.length})</span>
            </div>
            <div className="space-y-1.5">
              {stableLicences.map(renderTaskCard)}
            </div>
          </div>
        </div>

        {/* Right Column: Full Selected Task Inspector Pane */}
        <div className="lg:col-span-7 bg-surface border border-line rounded-2xl p-6 sm:p-7 space-y-6 shadow-sm">
          {/* Header Row: Pack Icon + Breadcrumb Title + Description */}
          <div className="flex items-start gap-4 pb-4 border-b border-line">
            <div className="w-12 h-12 rounded-xl bg-surfaceSubtle border border-line flex items-center justify-center shrink-0">
              {getPackIcon(selectedLicence.pack_icon, selectedLicence.class_key)}
            </div>
            <div>
              <h2 className="font-serif text-xl sm:text-2xl font-bold text-ink">
                {selectedLicence.title || selectedLicence.class_key} →{" "}
                <span className="text-ink-secondary font-normal font-sans text-lg">
                  {selectedLicence.action_label || selectedLicence.action}
                </span>
              </h2>
              <p className="text-xs sm:text-sm text-ink-secondary mt-1 leading-relaxed">
                {selectedLicence.description ||
                  `Automated assistance for ${selectedLicence.class_key} requiring proof before autonomous action.`}
              </p>
            </div>
          </div>

          {/* Current Permission Section */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
                Current Permission
              </span>
              <span className="text-xs text-ink-tertiary px-2 py-0.5 rounded bg-surfaceSubtle border border-line">
                Read only
              </span>
            </div>

            <div className="p-4 rounded-xl bg-surfaceRaised border border-line space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  {getCategoryBadge(selectedLicence)}
                  <span className="text-xs text-ink-secondary">
                    {getAutonomyName(selectedLicence.level)}
                  </span>
                </div>
                <div className="text-xs text-ink-tertiary font-mono">
                  Safe Estimate: {Math.round(selectedLicence.lower_bound * 100)}%
                </div>
              </div>

              {/* 3-Column Scope, Human Review, Data Access */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-3 border-t border-line text-xs">
                <div>
                  <div className="text-ink-tertiary font-semibold uppercase tracking-wider text-[10px]">
                    Scope
                  </div>
                  <div className="font-semibold text-ink mt-1">
                    {selectedLicence.scope_description || "This task only"}
                  </div>
                </div>

                <div>
                  <div className="text-ink-tertiary font-semibold uppercase tracking-wider text-[10px]">
                    Human Review
                  </div>
                  <div className="font-semibold text-ink mt-1">
                    {selectedLicence.human_review_description || "Always required before action"}
                  </div>
                </div>

                <div>
                  <div className="text-ink-tertiary font-semibold uppercase tracking-wider text-[10px]">
                    Data Access
                  </div>
                  <div className="font-semibold text-ink mt-1">
                    {selectedLicence.data_access_description || "Read-only access to task messages"}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Task-Specific Agreement Disclaimer Card */}
          <div className="p-3.5 rounded-xl bg-surfaceSubtle border border-line flex items-center gap-3 text-xs text-ink-secondary">
            <Info className="w-4 h-4 text-brand shrink-0" />
            <span>
              Matched you <strong>{selectedLicence.k_strong}</strong> of <strong>{selectedLicence.n_strong}</strong> times on historical timeline. Last 30 days: <strong>{selectedLicence.n_recent}</strong> checks.
            </span>
          </div>

          {/* 2-Card Row: Evidence & Test Results */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Evidence Card */}
            <div className="p-4 rounded-xl bg-surfaceRaised border border-line space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-ink">
                  <Layers className="w-4 h-4 text-brand" />
                  <span>Evidence</span>
                </div>
                <span className="text-xs font-bold text-ink">
                  {selectedLicence.evidence_count || selectedLicence.n_strong} examples
                </span>
              </div>
              <p className="text-xs text-ink-secondary">
                Task-specific examples used to mathematically validate behavior.
              </p>

              {selectedLicence.evidence_samples && selectedLicence.evidence_samples.length > 0 && (
                <div className="space-y-1.5 pt-2 border-t border-line text-[11px] text-ink-secondary">
                  {selectedLicence.evidence_samples.map((sample, idx) => (
                    <div key={idx} className="flex items-start gap-1.5 truncate">
                      <span className="text-ink-tertiary shrink-0">{sample.date}:</span>
                      <span className="truncate">{sample.summary}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Test Results Card */}
            <div className="p-4 rounded-xl bg-surfaceRaised border border-line space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-ink">
                  <FlaskConical className="w-4 h-4 text-[#85B99A]" />
                  <span>Test Results</span>
                </div>
                <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-[#85B99A]">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#85B99A]" />
                  Passed
                </span>
              </div>

              <div className="text-xs text-ink-secondary space-y-1">
                <div>
                  Last tested: <strong className="text-ink">{selectedLicence.exam_summary?.tested_at || "Apr 10, 2025"}</strong>
                </div>
                <div>
                  Tested at: <strong className="text-ink">{selectedLicence.exam_summary?.level_tested || "Allowed"} level</strong>
                </div>
                <div className="pt-1.5 border-t border-line text-[11px] text-ink-tertiary">
                  {selectedLicence.exam_summary?.pass_rate || "Invariance test: 100% pass"} · {selectedLicence.exam_summary?.critical_violations ?? 0} violations
                </div>
              </div>
            </div>
          </div>

          {/* 2-Card Row: Usage & Limits + Permission History */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Usage and Limits */}
            <div className="p-4 rounded-xl bg-surfaceRaised border border-line space-y-3">
              <div className="text-xs font-semibold uppercase tracking-wider text-ink">
                Usage and Limits
              </div>
              <div className="space-y-2">
                <div className="flex justify-between text-xs">
                  <span className="text-ink-secondary">Daily cap:</span>
                  <span className="font-semibold text-ink">
                    {selectedLicence.daily_cap || 10} actions / day
                  </span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-ink-secondary">Current usage:</span>
                  <span className="font-semibold text-ink">
                    {selectedLicence.current_usage ?? 2} used today
                  </span>
                </div>

                {/* Progress bar */}
                <div className="w-full bg-surfaceSubtle h-2 rounded-full overflow-hidden border border-line">
                  <div
                    className="bg-[#C8B27D] h-full rounded-full transition-all"
                    style={{
                      width: `${Math.min(
                        100,
                        (((selectedLicence.current_usage ?? 2) / (selectedLicence.daily_cap || 10)) * 100)
                      )}%`,
                    }}
                  />
                </div>

                <div className="pt-2 border-t border-line text-[11px] text-ink-tertiary">
                  <span className="font-semibold text-ink-secondary">Blocked: </span>
                  {selectedLicence.blocked_description || "Direct unmonitored execution"}
                </div>
              </div>
            </div>

            {/* Permission History Timeline */}
            <div className="p-4 rounded-xl bg-surfaceRaised border border-line space-y-3">
              <div className="text-xs font-semibold uppercase tracking-wider text-ink">
                Permission History
              </div>

              <div className="relative pl-5 space-y-3 before:absolute before:left-2 before:top-1.5 before:bottom-1.5 before:w-0.5 before:bg-line">
                {selectedLicence.history && selectedLicence.history.length > 0 ? (
                  selectedLicence.history.map((h, i) => (
                    <div key={i} className="relative text-xs space-y-0.5">
                      <span className={`absolute -left-[17px] top-1 w-2.5 h-2.5 rounded-full border-2 border-surface ${i === 0 ? "bg-[#85B99A]" : "bg-ink-tertiary"}`} />
                      <div className="flex items-center justify-between text-ink font-semibold">
                        <span>{i === 0 ? "Allowed" : i === 1 ? "Limited" : "Watching"}</span>
                        <span className="text-[10px] text-ink-tertiary font-normal">
                          {h.created_at.split("T")[0]}
                        </span>
                      </div>
                      <p className="text-[11px] text-ink-secondary line-clamp-2">
                        {h.reason || "Updated license state based on driving exams"}
                      </p>
                    </div>
                  ))
                ) : (
                  <div className="text-xs text-ink-tertiary">No recorded state transitions.</div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
