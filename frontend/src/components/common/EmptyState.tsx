import React from "react";
import { CheckCircle2 } from "lucide-react";

interface EmptyStateProps {
  title: string;
  description: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
}

export function EmptyState({
  title,
  description,
  icon = <CheckCircle2 className="w-8 h-8 text-status-success" />,
  action,
}: EmptyStateProps) {
  return (
    <div className="py-16 px-6 text-center flex flex-col items-center justify-center rounded-2xl bg-surface border border-line my-6">
      <div className="w-12 h-12 rounded-2xl bg-surfaceSubtle flex items-center justify-center mb-4">
        {icon}
      </div>
      <h3 className="text-base font-semibold text-ink">{title}</h3>
      <p className="text-sm text-ink-secondary mt-1 max-w-sm">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
