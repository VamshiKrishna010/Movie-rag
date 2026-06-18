import { useEffect } from "react";
import { useGenre } from "../context/GenreContext";

export function GenreSidebar() {
  const { genres, genreId, sidebarOpen, setSidebarOpen, selectGenre } = useGenre();

  useEffect(() => {
    if (!sidebarOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSidebarOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [sidebarOpen, setSidebarOpen]);

  return (
    <>
      <div
        role="presentation"
        onClick={() => setSidebarOpen(false)}
        className={`fixed inset-0 z-40 bg-black/40 transition-opacity duration-300 ${
          sidebarOpen ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      />

      <aside
        aria-label="Genre filter"
        className={`fixed right-0 top-0 z-50 flex h-full w-72 flex-col border-l border-border bg-surface shadow-xl transition-transform duration-300 ease-out ${
          sidebarOpen ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h2 className="text-sm font-semibold text-text">Genres</h2>
          <button
            type="button"
            onClick={() => setSidebarOpen(false)}
            aria-label="Close genre menu"
            className="flex h-8 w-8 items-center justify-center rounded-full text-muted transition-colors hover:bg-bg hover:text-text"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-5 w-5">
              <path fillRule="evenodd" d="M5.47 5.47a.75.75 0 011.06 0L12 10.94l5.47-5.47a.75.75 0 111.06 1.06L13.06 12l5.47 5.47a.75.75 0 11-1.06 1.06L12 13.06l-5.47 5.47a.75.75 0 01-1.06-1.06L10.94 12 5.47 6.53a.75.75 0 010-1.06z" clipRule="evenodd" />
            </svg>
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-3">
          <button
            type="button"
            onClick={() => selectGenre(null)}
            className={`mb-1 w-full rounded-xl px-4 py-2.5 text-left text-sm transition-colors ${
              genreId === null
                ? "bg-bg font-medium text-text"
                : "text-muted hover:bg-bg hover:text-text"
            }`}
          >
            All genres
          </button>
          {genres.map((g) => (
            <button
              key={g.id}
              type="button"
              onClick={() => selectGenre(g.id)}
              className={`mb-1 flex w-full items-center justify-between rounded-xl px-4 py-2.5 text-left text-sm transition-colors ${
                genreId === g.id
                  ? "bg-bg font-medium text-text"
                  : "text-muted hover:bg-bg hover:text-text"
              }`}
            >
              <span>{g.name}</span>
              <span className="text-xs text-muted">{g.movie_count}</span>
            </button>
          ))}
        </nav>
      </aside>
    </>
  );
}
