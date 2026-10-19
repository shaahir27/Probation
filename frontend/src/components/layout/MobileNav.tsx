import { Home, Inbox, Zap, Shield, MoreHorizontal } from "lucide-react";

interface MobileNavProps {
  currentTab: string;
  onTabChange: (tab: string) => void;
  queueCount: number;
}

export function MobileNav({ currentTab, onTabChange, queueCount }: MobileNavProps) {
  const destinations = [
    { id: "home", label: "Home", icon: Home },
    { id: "queue", label: "Queue", icon: Inbox, badge: queueCount > 0 ? queueCount : undefined },
    { id: "actions", label: "Actions", icon: Zap },
    { id: "permissions", label: "Perms", icon: Shield },
    { id: "more", label: "More", icon: MoreHorizontal },
  ];

  return (
    <nav className="md:hidden fixed bottom-0 left-0 right-0 h-16 nav-glass border-t border-line flex items-center justify-around px-2 z-50 pb-[env(safe-area-inset-bottom)]">
      {destinations.map((dest) => {
        const Icon = dest.icon;
        const active = currentTab === dest.id;
        return (
          <button
            key={dest.id}
            onClick={() => onTabChange(dest.id)}
            className={`flex flex-col items-center justify-center w-14 h-12 rounded-xl transition-all relative ${
              active ? "text-brand font-semibold" : "text-ink-secondary hover:text-ink"
            }`}
          >
            <div className="relative">
              <Icon className="w-5 h-5" />
              {dest.badge !== undefined && (
                <span className="absolute -top-1 -right-2 px-1 py-0.2 rounded-full text-[9px] font-bold bg-brand text-brand-on">
                  {dest.badge}
                </span>
              )}
            </div>
            <span className="text-[10px] mt-0.5">{dest.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
