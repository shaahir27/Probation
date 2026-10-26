import { Home, Inbox, Zap, Shield, MoreHorizontal } from "lucide-react";

interface MobileNavProps {
  currentTab: string;
  queueCount: number;
}

export function MobileNav({ currentTab, queueCount }: MobileNavProps) {
  const destinations = [
    { id: "home", label: "Home", icon: Home },
    { id: "queue", label: "Review", icon: Inbox, badge: queueCount > 0 ? queueCount : undefined },
    { id: "actions", label: "Actions", icon: Zap },
    { id: "permissions", label: "Permissions", icon: Shield },
    { id: "more", label: "More", icon: MoreHorizontal },
  ];

  return (
    <nav aria-label="Main navigation" className="md:hidden fixed bottom-0 left-0 right-0 min-h-16 bg-canvas border-t border-line flex items-center justify-around px-1 z-50 pb-[env(safe-area-inset-bottom)]">
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
            className={`flex flex-col items-center justify-center flex-1 min-w-0 min-h-11 rounded-md transition-colors relative ${
              active ? "text-ink font-semibold" : "text-ink-secondary hover:text-ink"
            }`}
          >
            <div className="relative">
              <Icon aria-hidden="true" className="w-5 h-5" />
              {dest.badge !== undefined && (
                <span className="absolute -top-1 -right-2 px-1 py-0.2 rounded-full text-[9px] font-bold bg-brand text-brand-on">
                  {dest.badge}
                </span>
              )}
            </div>
            <span className="text-[10px] mt-0.5 truncate">{dest.label}</span>
          </a>
        );
      })}
    </nav>
  );
}
