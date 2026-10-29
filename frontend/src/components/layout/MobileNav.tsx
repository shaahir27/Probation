import { Home, Inbox, ArrowUpRight, Shield, MoreHorizontal } from "lucide-react";
export function MobileNav({ currentTab, queueCount }: { currentTab: string; queueCount: number }) {
  const destinations = [
    { id: "home", label: "Overview", icon: Home }, { id: "queue", label: "Review", icon: Inbox },
    { id: "actions", label: "Activity", icon: ArrowUpRight }, { id: "permissions", label: "Permissions", icon: Shield },
    { id: "more", label: "More", icon: MoreHorizontal },
  ];
  return <nav aria-label="Main navigation" className="mobile-workspace-nav md:hidden">
    {destinations.map(({ id, label, icon: Icon }) => <a key={id} href={`#/${id}`} aria-current={currentTab === id ? "page" : undefined}
      aria-label={id === "queue" ? `Review emails${queueCount > 0 ? `, ${queueCount} waiting` : ""}` : undefined}
      className={currentTab === id ? "is-current" : ""}>
      <Icon aria-hidden="true" size={18} strokeWidth={1.6} /><span>{label}</span>
    </a>)}
  </nav>;
}
