import React from "react";

interface BadgeProps {
  children: React.ReactNode;
  variant?: "default" | "brand" | "success" | "warning" | "danger" | "subtle";
  className?: string;
}

export function Badge({ children, variant = "default", className = "" }: BadgeProps) {
  const base = "inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border";

  const variants = {
    default: "bg-surface text-ink border-line",
    brand: "bg-brand/10 text-brand border-brand/30",
    success: "bg-status-success/10 text-status-success border-status-success/30",
    warning: "bg-status-warning/10 text-status-warning border-status-warning/30",
    danger: "bg-status-danger/10 text-status-danger border-status-danger/30",
    subtle: "bg-surfaceSubtle text-ink-secondary border-line",
  };

  return <span className={`${base} ${variants[variant]} ${className}`}>{children}</span>;
}
