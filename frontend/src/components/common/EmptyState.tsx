import React from "react";
import { Inbox } from "lucide-react";

interface EmptyStateProps {
  title: string;
  description: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
}

export function EmptyState({
  title,
  description,
  icon = <Inbox aria-hidden="true" className="w-6 h-6 text-ink-tertiary" />,
  action,
}: EmptyStateProps) {
  return (
    <div className="py-10 px-6 flex flex-col items-start justify-center rounded-xl bg-surface my-4">
      <div className="text-ink-tertiary mb-5">
        {icon}
      </div>
      <h3 className="text-base font-semibold text-ink">{title}</h3>
      <p className="text-sm text-ink-secondary mt-1 max-w-sm">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
