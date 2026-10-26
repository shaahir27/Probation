export function ProbationMark({ className = "h-9 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 36" fill="none" aria-hidden="true" className={className}>
      <path d="M9 3h13l5 5v23l-4-2-4 2-4-2-4 2-4-2V7" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="m2 12 5 5 9-10M13 18h8M13 23h8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
