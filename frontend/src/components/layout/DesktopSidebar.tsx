import {
  Home,
  Inbox,
  Zap,
  Shield,
  MoreHorizontal,
  Sparkles,
  Layers,
} from "lucide-react";

interface DesktopSidebarProps {
  currentTab: string;
  onTabChange: (tab: string) => void;
  queueCount: number;
  previewMode: boolean;
  onTogglePreview: () => void;
}

export function DesktopSidebar({
  currentTab,
  onTabChange,
  queueCount,
  previewMode,
  onTogglePreview,
}: DesktopSidebarProps) {
  const destinations = [
    { id: "home", label: "Home", icon: Home },
    { id: "queue", label: "Queue", icon: Inbox, badge: queueCount > 0 ? queueCount : undefined },
    { id: "actions", label: "Actions", icon: Zap },
    { id: "permissions", label: "Permissions", icon: Shield },
    { id: "more", label: "More", icon: MoreHorizontal },
  ];

  return (
    <aside className="w-[232px] h-screen sticky top-0 border-r border-line nav-glass flex flex-col justify-between p-4 z-40 select-none">
      <div>
        {/* Brand Header */}
        <div className="flex items-center gap-3 px-3 py-4 mb-3">
          <div className="w-8 h-8 rounded-lg bg-surfaceSubtle border border-line flex items-center justify-center text-brand">
            <Layers className="w-4 h-4 text-brand" />
          </div>
          <div>
            <span className="font-serif text-xl tracking-tight text-ink font-normal">
              Probation
            </span>
            <div className="text-[10px] text-ink-tertiary">Earned Autonomy</div>
          </div>
        </div>

        {/* Navigation Links */}
        <nav className="space-y-1.5">
          {destinations.map((dest) => {
            const Icon = dest.icon;
            const active = currentTab === dest.id;
            return (
              <button
                key={dest.id}
                onClick={() => onTabChange(dest.id)}
                className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm transition-all ${
                  active
                    ? "bg-surfaceRaised text-brand font-medium shadow-sm border border-line/80 brass-indicator"
                    : "text-ink-secondary hover:text-ink hover:bg-surfaceSubtle border border-transparent"
                }`}
              >
                <div className="flex items-center gap-3">
                  <Icon className={`w-4 h-4 ${active ? "text-brand" : "text-ink-tertiary"}`} />
                  <span className={active ? "text-brand" : "text-ink"}>{dest.label}</span>
                </div>
                {dest.badge !== undefined && (
                  <span className="px-1.5 py-0.5 rounded-full text-[11px] font-bold bg-brand text-brand-on">
                    {dest.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Explicit Preview Mode Switch (Persona: Meena) */}
      <div className="p-3 rounded-xl bg-surface border border-line">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <Sparkles className="w-3.5 h-3.5 text-brand" />
            <span className="text-xs font-medium text-ink">Preview Mode</span>
          </div>
          <button
            onClick={onTogglePreview}
            className={`w-9 h-5 rounded-full transition-colors relative p-0.5 ${
              previewMode ? "bg-brand" : "bg-surfaceSubtle border border-line"
            }`}
            aria-label="Toggle synthetic preview fixtures"
          >
            <div
              className={`w-4 h-4 rounded-full bg-white transition-transform ${
                previewMode ? "translate-x-4" : "translate-x-0"
              }`}
            />
          </button>
        </div>
        <div className="text-[10px] text-ink-tertiary mt-1">
          {previewMode ? "Showing Meena demo data" : "Showing real local API data"}
        </div>
      </div>
    </aside>
  );
}
