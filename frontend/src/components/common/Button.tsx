import React from "react";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md" | "lg";
}

export function Button({
  children,
  variant = "secondary",
  size = "md",
  className = "",
  disabled,
  ...props
}: ButtonProps) {
  const base =
    "inline-flex items-center justify-center font-medium transition-all select-none focus:outline-none focus:ring-2 focus:ring-focus btn-tactile disabled:opacity-50 disabled:pointer-events-none";

  const sizes = {
    sm: "px-3 py-1.5 text-xs rounded-lg gap-1.5 min-h-[36px]",
    md: "px-4 py-2 text-sm rounded-xl gap-2 min-h-[44px]",
    lg: "px-5 py-2.5 text-base rounded-xl gap-2.5 min-h-[48px]",
  };

  const variants = {
    primary: "bg-brand text-brand-on hover:bg-brand-hover shadow-sm font-semibold",
    secondary: "bg-surface hover:bg-surfaceRaised border border-line text-ink hover:border-brand/40",
    danger: "bg-status-danger/10 hover:bg-status-danger/20 border border-status-danger/30 text-status-danger",
    ghost: "bg-transparent hover:bg-surfaceSubtle text-ink-secondary hover:text-ink",
  };

  return (
    <button
      className={`${base} ${sizes[size]} ${variants[variant]} ${className}`}
      disabled={disabled}
      {...props}
    >
      {children}
    </button>
  );
}
