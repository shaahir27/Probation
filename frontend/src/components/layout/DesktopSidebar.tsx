import {
  Home,
  Inbox,
  Zap,
  Shield,
  MoreHorizontal,
  Layers,
} from "lucide-react";

interface DesktopSidebarProps {
  currentTab: string;
  queueCount: number;
}

export function DesktopSidebar({ currentTab, queueCount }: DesktopSidebarProps) {
  const destinations = [
    { id: "home", label: "Home", icon: Home },
    { id: "queue", label: "Review", icon: Inbox, badge: queueCount > 0 ? queueCount : undefined },
    { id: "actions", label: "Actions", icon: Zap },
    { id: "permissions", label: "Permissions", icon: Shield },
    { id: "more", label: "More", icon: MoreHorizontal },
  ];

  return (
    <aside className="hidden md:flex w-[232px] h-screen sticky top-0 border-r border-line nav-glass flex-col justify-between p-4 z-40 select-none">
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
        <nav aria-label="Main navigation" className="space-y-1.5">
          {destinations.map((dest) => {
            const Icon = dest.icon;
            const active = currentTab === dest.id;
            return (
              <a
                key={dest.id}
                href={`#/${dest.id}`}
                aria-current={active ? "page" : undefined}
                aria-label={
                  dest.id === "queue"
                    ? queueCount > 0
                      ? `Review Queue, ${queueCount} waiting`
                      : "Review Queue"
                    : undefined
                }
                className={`w-full min-h-11 flex items-center justify-between px-3.5 py-2.5 rounded-md text-sm transition-colors ${
                  active
                    ? "text-ink font-medium"
                    : "text-ink-secondary hover:text-ink hover:bg-surfaceSubtle"
                }`}
              >
                <div className="flex items-center gap-3">
                  <Icon aria-hidden="true" className="w-4 h-4 text-ink-tertiary" />
                  <span>{dest.label}</span>
                </div>
                {dest.badge !== undefined && (
                  <span className="px-1.5 py-0.5 rounded-full text-[11px] font-bold bg-brand text-brand-on">
                    {dest.badge}
                  </span>
                )}
              </a>
            );
          })}
        </nav>
      </div>

      <div className="px-3 py-2 text-xs text-ink-tertiary">Your account</div>
    </aside>
  );
}
