import type { ReactNode } from "react";

interface ContentShellProps {
  children: ReactNode;
  embedded?: boolean;
}

export function ContentShell({ children, embedded = false }: ContentShellProps) {
  const panel = (
    <div className="rounded-3xl border border-border bg-surface p-5 shadow-sm sm:p-6">
      {children}
    </div>
  );

  if (embedded) return panel;

  return (
    <div className="mx-auto max-w-5xl px-4 pb-8 pt-4">
      {panel}
    </div>
  );
}
