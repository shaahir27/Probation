import type { ReactNode } from "react";

interface LinkButtonProps {
  href: string;
  children: ReactNode;
  variant?: "primary" | "secondary";
  size?: "md" | "lg";
  className?: string;
}

/**
 * A real anchor that looks like the button system, so a destination stays a link
 * (browser history, middle click, keyboard focus) instead of a click handler.
 */
export function LinkButton({ href, children, variant = "secondary", size = "md", className = "" }: LinkButtonProps) {
  const base =
    "inline-flex items-center justify-center font-medium select-none focus:outline-none focus:ring-2 focus:ring-focus btn-tactile";
  const sizes = {
    md: "px-4 py-2 text-sm rounded-xl gap-2 min-h-[44px]",
    lg: "px-5 py-2.5 text-base rounded-xl gap-2.5 min-h-[48px]",
  };
  const variants = {
    primary: "bg-ink text-canvas hover:bg-white font-semibold",
    secondary: "bg-surface hover:bg-surfaceRaised border border-line text-ink",
  };
  return (
    <a href={href} className={`${base} ${sizes[size]} ${variants[variant]} ${className}`.trim()}>
      {children}
    </a>
  );
}
