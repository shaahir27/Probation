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
    "inline-flex items-center justify-center font-semibold transition-all select-none focus:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-canvas btn-tactile disabled:opacity-45 disabled:pointer-events-none active:translate-y-px";

  const sizes = {
    // `sm` is only for dense secondary affordances. Anything primary, and anything
    // that confirms an effect, is forced to at least 44px below.
    sm: "px-3 py-1.5 text-xs rounded-lg gap-1.5 min-h-[44px]",
    md: "px-4 py-2 text-sm rounded-xl gap-2 min-h-[44px]",
    lg: "px-5 py-2.5 text-base rounded-xl gap-2.5 min-h-[48px]",
  };

  const variants = {
    primary: "bg-ink text-canvas hover:bg-brand font-semibold",
    secondary: "bg-surface hover:bg-surfaceRaised border border-line text-ink",
    danger: "bg-status-danger/10 hover:bg-status-danger/20 border border-status-danger/30 text-status-danger",
    ghost: "bg-transparent hover:bg-surfaceSubtle text-ink-secondary hover:text-ink",
  };

  // Touch-target rule: a primary action is never smaller than 44px, whatever size
  // the caller asked for. Density may shrink secondary and ghost controls.
  const sizeClass = variant === "primary" ? `${sizes[size]} min-h-[44px]` : sizes[size];

  return (
    <button
      className={`${base} ${sizeClass} ${variants[variant]} ${className}`}
      disabled={disabled}
      {...props}
    >
      {children}
    </button>
  );
}
