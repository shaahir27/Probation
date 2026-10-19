import { useState } from "react";
import {
  Mail,
  Calendar,
  FileText,
  Check,
  X,
  Eye,
  Info,
  ShieldCheck,
  ExternalLink,
  Edit3,
  Clock,
} from "lucide-react";
import { QueueItem } from "../api/types";
import { Button } from "../components/common/Button";
import { EmptyState } from "../components/common/EmptyState";

interface QueueViewProps {
  items: QueueItem[];
  onRespond: (id: string, response: "accept" | "reject" | "edit", editedAction?: string) => Promise<void>;
}

export function QueueView({ items, onRespond }: QueueViewProps) {
  const [inspectingItem, setInspectingItem] = useState<QueueItem | null>(null);
  const [isResponding, setIsResponding] = useState(false);
  const [editingDraft, setEditingDraft] = useState<string>("");
  const [customAction, setCustomAction] = useState<string>("");
  const [isEditingAction, setIsEditingAction] = useState(false);

  // Compute metric counts
  const totalCount = items.length;
  const lowRiskCount = items.filter(
    (i) => i.risk_level === "low" || i.gate === "SUGGEST" || (i.p_max >= 0.85 && i.novelty <= 0.05)
  ).length;
  const needsAttentionCount = items.filter(
    (i) =>
      i.risk_level === "medium" ||
      (i.gate === "ASK" && !i.audit_holdout && (i.risk_level !== "high"))
  ).length;
  const highRiskCount = items.filter(
    (i) => i.risk_level === "high" || i.audit_holdout || i.cap <= 1
  ).length;

  const handleAction = async (
    id: string,
    response: "accept" | "reject" | "edit",
    actionName?: string
  ) => {
    setIsResponding(true);
    try {
      await onRespond(id, response, actionName);
      if (inspectingItem?.id === id) {
        setInspectingItem(null);
      }
      setIsEditingAction(false);
      setCustomAction("");
    } finally {
      setIsResponding(false);
    }
  };

  const getPackIcon = (item: QueueItem) => {
    const pack = item.pack_type || (item.family.includes("calendar") ? "calendar" : item.family.includes("file") ? "file" : "mail");
    switch (pack) {
      case "calendar":
        return <Calendar className="w-5 h-5 text-ink-secondary" />;
      case "file":
      case "doc":
        return <FileText className="w-5 h-5 text-ink-secondary" />;
      case "mail":
      default:
        return <Mail className="w-5 h-5 text-ink-secondary" />;
    }
  };

  const getRiskInfo = (item: QueueItem) => {
    if (item.risk_level === "high" || item.audit_holdout || item.cap <= 1) {
      return {
        label: "High risk",
        dotColor: "bg-[#E28F88]",
        textColor: "text-[#E28F88]",
        subtext: item.family.includes("file") ? "Internal file" : "Security critical",
      };
    }
    if (item.risk_level === "medium" || item.gate === "ASK") {
      return {
        label: "Needs attention",
        dotColor: "bg-[#E0B663]",
        textColor: "text-[#E0B663]",
        subtext: item.family.includes("calendar") ? "Calendar update" : "Review needed",
      };
    }
    return {
      label: "Low risk",
      dotColor: "bg-[#85B99A]",
      textColor: "text-[#85B99A]",
      subtext: item.family.includes("email") ? "Email draft" : "Routine action",
    };
  };

  if (items.length === 0) {
    return (
      <EmptyState
        title="Queue is empty"
        description="All pending items have been reviewed or resolved. Nothing needs your decision right now."
      />
    );
  }

  return (
    <div className="space-y-6">
      {/* Editorial Header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 pb-2">
        <div>
          <h1 className="font-serif text-3xl sm:text-4xl font-normal text-ink tracking-tight">
            Queue
          </h1>
          <p className="text-sm text-ink-secondary mt-1">
            Review and approve AI actions before they’re taken.
          </p>
        </div>

        <div className="flex items-center gap-3 text-xs">
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-surfaceSubtle border border-line text-ink-secondary">
            <span className="w-2 h-2 rounded-full bg-[#85B99A] animate-pulse" />
            <span className="font-medium text-ink">AI systems online</span>
          </div>
          <div className="hidden sm:flex items-center gap-1.5 text-ink-tertiary">
            <Clock className="w-3.5 h-3.5" />
            <span>Replay up to date</span>
          </div>
        </div>
      </div>

      {/* Top 4-Column KPI Metrics Bar */}
      <div className="p-4 sm:p-5 rounded-2xl bg-surface border border-line grid grid-cols-2 sm:grid-cols-4 gap-4 divide-y sm:divide-y-0 sm:divide-x divide-line shadow-sm">
        <div className="pt-2 sm:pt-0">
          <div className="text-2xl sm:text-3xl font-bold text-ink">{totalCount}</div>
          <div className="text-xs text-ink-secondary font-medium mt-0.5">Pending review</div>
        </div>

        <div className="pt-2 sm:pt-0 sm:pl-4">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#85B99A]" />
            <span className="text-2xl sm:text-3xl font-bold text-ink">{lowRiskCount}</span>
          </div>
          <div className="text-xs text-[#85B99A] font-medium mt-0.5">● Low risk</div>
        </div>

        <div className="pt-2 sm:pt-0 sm:pl-4">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#E0B663]" />
            <span className="text-2xl sm:text-3xl font-bold text-ink">{needsAttentionCount}</span>
          </div>
          <div className="text-xs text-[#E0B663] font-medium mt-0.5">● Needs attention</div>
        </div>

        <div className="pt-2 sm:pt-0 sm:pl-4">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#E28F88]" />
            <span className="text-2xl sm:text-3xl font-bold text-ink">{highRiskCount}</span>
          </div>
          <div className="text-xs text-[#E28F88] font-medium mt-0.5">● High risk</div>
        </div>
      </div>

      {/* Queue Items List */}
      <div className="space-y-4">
        {items.map((item) => {
          const risk = getRiskInfo(item);
          const headline = item.action_headline || item.summary;
          const timeAgo = item.requested_time_ago || "Requested recently";

          // Build metadata entries from metadata_table or fallback to params
          const metadataEntries: Array<[string, string]> = item.metadata_table
            ? Object.entries(item.metadata_table)
            : Object.entries(item.params)
                .slice(0, 3)
                .map(([k, v]) => [k.charAt(0).toUpperCase() + k.slice(1), String(v)]);

          return (
            <div
              key={item.id}
              className="p-5 sm:p-6 rounded-2xl bg-surface border border-line space-y-4 hover:border-brand/30 transition-all shadow-sm"
            >
              {/* Header row: Icon + Risk Pill + Time */}
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-4">
                  {/* Dedicated 48x48 Pack Icon Container */}
                  <div className="w-12 h-12 rounded-xl bg-surfaceSubtle border border-line flex items-center justify-center shrink-0">
                    {getPackIcon(item)}
                  </div>

                  <div>
                    {/* Risk indicator pill */}
                    <div className="flex items-center gap-2 text-xs">
                      <span className={`flex items-center gap-1 font-semibold ${risk.textColor}`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${risk.dotColor}`} />
                        {risk.label}
                      </span>
                      <span className="text-ink-tertiary">·</span>
                      <span className="text-ink-secondary">{risk.subtext}</span>
                      {item.audit_holdout && (
                        <>
                          <span className="text-ink-tertiary">·</span>
                          <span className="text-[#E0B663] font-semibold text-[11px]">Audit Holdout</span>
                        </>
                      )}
                    </div>

                    {/* Headline */}
                    <h3 className="text-base sm:text-lg font-bold text-ink mt-1">
                      {headline}
                    </h3>

                    {/* Description */}
                    <p className="text-xs sm:text-sm text-ink-secondary mt-0.5">
                      {item.summary}
                    </p>
                  </div>
                </div>

                {/* Requested timestamp */}
                <div className="text-xs text-ink-tertiary whitespace-nowrap shrink-0">
                  {timeAgo}
                </div>
              </div>

              {/* Recessed Context Box (Exact Spruce & Brass styling) */}
              {metadataEntries.length > 0 && (
                <div className="bg-[#131F1C] border border-[#344840]/60 rounded-xl p-3.5 sm:p-4 text-xs font-mono space-y-2">
                  {metadataEntries.map(([key, val]) => (
                    <div key={key} className="grid grid-cols-12 gap-2">
                      <div className="col-span-3 sm:col-span-2 text-ink-tertiary font-medium">
                        {key}:
                      </div>
                      <div className="col-span-9 sm:col-span-10 text-ink truncate font-mono">
                        {val}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Bottom Action Row */}
              <div className="pt-2 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="text-xs text-ink-tertiary flex items-center gap-2">
                  <span>Confidence: <strong>{Math.round(item.p_max * 100)}%</strong></span>
                  <span>·</span>
                  <span>Autonomy: <strong>L{item.licence_level}</strong></span>
                </div>

                <div className="flex items-center justify-end gap-2.5">
                  {/* Inspect Button */}
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => {
                      setInspectingItem(item);
                      setEditingDraft(item.draft?.body_text || "");
                      setIsEditingAction(false);
                      setCustomAction("");
                    }}
                    className="border-line hover:border-brand/40 text-xs px-3.5 py-2 font-medium"
                  >
                    <Eye className="w-3.5 h-3.5 text-ink-secondary" />
                    <span>Inspect</span>
                  </Button>

                  {/* Decline Button */}
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={isResponding}
                    onClick={() => handleAction(item.id, "reject")}
                    className="border-line hover:border-status-danger/40 text-xs px-3.5 py-2 font-medium hover:text-status-danger"
                  >
                    <X className="w-3.5 h-3.5" />
                    <span>Decline</span>
                  </Button>

                  {/* Approve Button (Solid Brushed Brass #C8B27D) */}
                  <button
                    disabled={isResponding}
                    onClick={() => handleAction(item.id, "accept")}
                    className="bg-[#C8B27D] hover:bg-[#D4C08D] text-[#111B18] font-semibold px-4 py-2 rounded-xl text-xs transition-colors flex items-center gap-1.5 shadow-sm active:scale-95 disabled:opacity-50"
                  >
                    <Check className="w-3.5 h-3.5 stroke-[2.5]" />
                    <span>Approve</span>
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Inspection Slide-Over Drawer Modal */}
      {inspectingItem && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/60 backdrop-blur-xs transition-opacity animate-in fade-in duration-200">
          <div className="w-full max-w-xl bg-surface border-l border-line h-full flex flex-col shadow-2xl overflow-hidden animate-in slide-in-from-right duration-300">
            {/* Drawer Header */}
            <div className="p-5 border-b border-line flex items-center justify-between bg-surfaceRaised">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-surfaceSubtle border border-line flex items-center justify-center shrink-0">
                  {getPackIcon(inspectingItem)}
                </div>
                <div>
                  <h3 className="font-serif text-lg font-bold text-ink">
                    {inspectingItem.action_headline || inspectingItem.action}
                  </h3>
                  <div className="flex items-center gap-2 text-xs text-ink-secondary">
                    <span>{inspectingItem.class_key}</span>
                    <span>·</span>
                    <span>Gate: {inspectingItem.gate}</span>
                  </div>
                </div>
              </div>

              <button
                onClick={() => setInspectingItem(null)}
                className="p-2 rounded-lg text-ink-tertiary hover:text-ink hover:bg-surfaceSubtle transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Drawer Scrollable Content */}
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              {/* Summary & Reasons */}
              <div className="p-4 rounded-xl bg-surfaceSubtle border border-line space-y-2.5">
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-brand">
                  <Info className="w-4 h-4" />
                  <span>Why Probation Recommended This</span>
                </div>
                <p className="text-sm text-ink-secondary leading-relaxed">
                  {inspectingItem.explanation.summary_reason ||
                    "Derived from consistent historical actions on similar inbound patterns."}
                </p>

                {inspectingItem.explanation.top_clues && (
                  <div className="pt-2 border-t border-line/60">
                    <span className="text-xs font-semibold text-ink">Top Observed Clues:</span>
                    <ul className="text-xs text-ink-secondary list-disc pl-4 mt-1.5 space-y-1">
                      {inspectingItem.explanation.top_clues.map((c, i) => (
                        <li key={i}>{c}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              {/* Similar Past Cases */}
              {inspectingItem.explanation.similar_cases && inspectingItem.explanation.similar_cases.length > 0 && (
                <div className="space-y-2.5">
                  <span className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
                    Past Similar Decisions
                  </span>
                  <div className="space-y-2">
                    {inspectingItem.explanation.similar_cases.map((c, i) => (
                      <div
                        key={i}
                        className="p-3 rounded-xl bg-surfaceRaised border border-line text-xs space-y-1"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-ink">{c.summary}</span>
                          <span className="font-mono text-[11px] text-[#85B99A]">
                            {Math.round(c.similarity * 100)}% match
                          </span>
                        </div>
                        <div className="text-ink-tertiary">
                          Action taken: <strong className="text-ink">{c.action_taken}</strong> (ID: {c.situation_id})
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Web Verification (Tavily/Pack grounding) */}
              {inspectingItem.web && inspectingItem.web.status && inspectingItem.web.status !== "not_checked" && (
                <div className="p-4 rounded-xl bg-surfaceRaised border border-line space-y-2">
                  <div className="flex items-center gap-2 text-xs font-semibold text-brand uppercase">
                    <ShieldCheck className="w-4 h-4 text-[#85B99A]" />
                    <span>External Grounding Verification</span>
                  </div>
                  <div className="text-xs text-ink-secondary">
                    Verification status: <strong className="text-ink">{inspectingItem.web.status}</strong>
                  </div>
                  {inspectingItem.web.source_ids && (
                    <div className="flex flex-wrap gap-2 pt-1">
                      {inspectingItem.web.source_ids.map((src, idx) => (
                        <a
                          key={idx}
                          href={src}
                          target="_blank"
                          rel="noreferrer"
                          className="text-[11px] text-brand hover:underline flex items-center gap-1 bg-surfaceSubtle px-2 py-1 rounded"
                        >
                          <span>{src}</span>
                          <ExternalLink className="w-3 h-3" />
                        </a>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Draft Preview or Action Payload */}
              {inspectingItem.draft ? (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
                      Draft Message
                    </span>
                    <span className="text-[11px] text-ink-tertiary">Will save to Drafts upon approval</span>
                  </div>
                  <textarea
                    rows={5}
                    value={editingDraft}
                    onChange={(e) => setEditingDraft(e.target.value)}
                    className="w-full p-3.5 rounded-xl bg-[#131F1C] border border-[#344840]/60 text-xs text-ink font-mono focus:outline-none focus:ring-1 focus:ring-brand leading-relaxed resize-y"
                  />
                </div>
              ) : (
                <div className="space-y-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
                    Target Parameters
                  </span>
                  <pre className="p-3.5 rounded-xl bg-[#131F1C] border border-[#344840]/60 text-xs text-ink font-mono overflow-x-auto">
                    {JSON.stringify(inspectingItem.params, null, 2)}
                  </pre>
                </div>
              )}

              {/* Change Proposed Action */}
              {isEditingAction ? (
                <div className="p-4 rounded-xl bg-surfaceRaised border border-brand/40 space-y-3">
                  <span className="text-xs font-semibold text-brand uppercase">Override Proposed Action</span>
                  <input
                    type="text"
                    placeholder="e.g. ARCHIVE, SNOOZE, STAR"
                    value={customAction}
                    onChange={(e) => setCustomAction(e.target.value.toUpperCase())}
                    className="w-full px-3 py-2 text-xs rounded-lg bg-surface border border-line text-ink focus:outline-none focus:ring-1 focus:ring-brand font-mono"
                  />
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="primary"
                      disabled={!customAction || isResponding}
                      onClick={() => handleAction(inspectingItem.id, "edit", customAction)}
                    >
                      Confirm override
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setIsEditingAction(false)}>
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                <button
                  onClick={() => setIsEditingAction(true)}
                  className="text-xs text-ink-secondary hover:text-brand flex items-center gap-1.5 transition-colors"
                >
                  <Edit3 className="w-3.5 h-3.5" />
                  <span>Choose different action</span>
                </button>
              )}
            </div>

            {/* Drawer Footer Actions */}
            <div className="p-5 border-t border-line bg-surfaceRaised flex items-center justify-between gap-3">
              <Button
                variant="ghost"
                onClick={() => setInspectingItem(null)}
                className="text-xs text-ink-secondary"
              >
                Cancel
              </Button>

              <div className="flex items-center gap-2.5">
                <Button
                  variant="secondary"
                  disabled={isResponding}
                  onClick={() => handleAction(inspectingItem.id, "reject")}
                  className="border-line text-xs font-medium hover:text-status-danger"
                >
                  <X className="w-3.5 h-3.5" />
                  <span>Decline</span>
                </Button>

                <button
                  disabled={isResponding}
                  onClick={() => handleAction(inspectingItem.id, "accept")}
                  className="bg-[#C8B27D] hover:bg-[#D4C08D] text-[#111B18] font-semibold px-4 py-2 rounded-xl text-xs transition-colors flex items-center gap-1.5 shadow-sm active:scale-95 disabled:opacity-50"
                >
                  <Check className="w-3.5 h-3.5 stroke-[2.5]" />
                  <span>Approve & Continue</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
