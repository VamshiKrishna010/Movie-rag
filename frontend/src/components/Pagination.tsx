interface PaginationProps {
  page: number;
  totalPages: number;
  onChange: (page: number) => void;
}

function pageNumbers(current: number, total: number): (number | "...")[] {
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }
  const pages: (number | "...")[] = [1];
  if (current > 3) pages.push("...");
  for (let p = Math.max(2, current - 1); p <= Math.min(total - 1, current + 1); p++) {
    pages.push(p);
  }
  if (current < total - 2) pages.push("...");
  if (total > 1) pages.push(total);
  return pages;
}

export function Pagination({ page, totalPages, onChange }: PaginationProps) {
  if (totalPages <= 1) return null;

  const pages = pageNumbers(page, totalPages);

  return (
    <nav
      aria-label="Pagination"
      className="mt-8 flex items-center justify-center gap-1"
    >
      <button
        type="button"
        disabled={page <= 1}
        onClick={() => onChange(page - 1)}
        className="rounded-full border border-border px-3 py-1.5 text-sm text-muted transition-colors hover:text-text disabled:cursor-not-allowed disabled:opacity-40"
      >
        Prev
      </button>

      {pages.map((p, i) =>
        p === "..." ? (
          <span key={`ellipsis-${i}`} className="px-2 text-muted">
            …
          </span>
        ) : (
          <button
            key={p}
            type="button"
            onClick={() => onChange(p)}
            className={`min-w-9 rounded-full border px-3 py-1.5 text-sm transition-colors ${
              p === page
                ? "border-accent/40 bg-surface text-text"
                : "border-border text-muted hover:text-text"
            }`}
          >
            {p}
          </button>
        ),
      )}

      <button
        type="button"
        disabled={page >= totalPages}
        onClick={() => onChange(page + 1)}
        className="rounded-full border border-border px-3 py-1.5 text-sm text-muted transition-colors hover:text-text disabled:cursor-not-allowed disabled:opacity-40"
      >
        Next
      </button>
    </nav>
  );
}
