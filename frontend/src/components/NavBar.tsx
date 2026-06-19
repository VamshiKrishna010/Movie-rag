import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useGenre } from "../context/GenreContext";
import { useSearch } from "../context/SearchContext";
import { useTheme } from "../hooks/useTheme";
import { GenreMenuButton } from "./GenreMenuButton";
import { SearchBar } from "./SearchBar";
import { ThemeToggle } from "./ThemeToggle";

export function NavBar() {
  const { user, logout } = useAuth();
  const { isDark, toggle } = useTheme();
  const { setSidebarOpen } = useGenre();
  const { query, setQuery, submitSearch } = useSearch();
  const location = useLocation();
  const navigate = useNavigate();
  const isHome = location.pathname === "/";

  const handleBack = () => {
    if (location.key !== "default") {
      navigate(-1);
    } else {
      navigate("/");
    }
  };

  return (
    <header className="sticky top-0 z-30 px-4 pt-4">
      <nav className="nav-pill mx-auto flex w-full max-w-md flex-col gap-3 rounded-2xl border border-border bg-surface px-3 py-2.5 shadow-bar backdrop-blur-sm md:w-fit md:max-w-none md:flex-row md:items-center md:gap-3 md:rounded-full md:px-4 md:py-2">
        <div className="flex items-center justify-between gap-3 md:contents">
          <div className="flex min-w-0 items-center gap-2">
            {!isHome && (
              <button
                type="button"
                onClick={handleBack}
                className="shrink-0 text-xs text-muted transition-colors hover:text-text"
              >
                ← Back
              </button>
            )}
            <Link to="/" className="flex shrink-0 items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-bg text-xs font-bold text-text">
                M
              </span>
              <span className="hidden text-sm font-semibold text-text sm:inline">
                Movies
              </span>
            </Link>
          </div>

          {isHome && (
            <div className="hidden md:block">
              <SearchBar
                inline
                value={query}
                onChange={setQuery}
                onSubmit={submitSearch}
              />
            </div>
          )}

          <div className="flex items-center gap-1">
            {user ? (
              <div className="flex items-center gap-2">
                {user.role === "admin" && (
                  <Link
                    to="/admin"
                    className="rounded-lg px-2 py-1 text-xs text-muted transition-colors hover:text-text"
                  >
                    Admin
                  </Link>
                )}
                <span className="hidden max-w-[8rem] truncate text-xs text-muted sm:inline">
                  {user.email}
                </span>
                <button
                  type="button"
                  onClick={logout}
                  className="rounded-lg px-2 py-1 text-xs text-muted transition-colors hover:text-text"
                >
                  Log out
                </button>
              </div>
            ) : (
              <Link
                to="/auth"
                className="rounded-lg px-2 py-1 text-xs text-muted transition-colors hover:text-text"
              >
                Sign in
              </Link>
            )}
            <ThemeToggle isDark={isDark} onToggle={toggle} />
            {isHome && (
              <GenreMenuButton onClick={() => setSidebarOpen(true)} />
            )}
          </div>
        </div>

        {isHome && (
          <div className="md:hidden">
            <SearchBar
              inline
              value={query}
              onChange={setQuery}
              onSubmit={submitSearch}
            />
          </div>
        )}
      </nav>
    </header>
  );
}
