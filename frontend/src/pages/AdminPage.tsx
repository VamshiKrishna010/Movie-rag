import { useEffect, useState } from "react";
import {
  createAdminMovie,
  emptyMovieForm,
  fetchAdminMovie,
  fetchAdminMovies,
  fetchAdminStats,
  fetchAdminUsers,
  movieToForm,
  submitQuery,
  updateAdminMovie,
  updateAdminUserRole,
  type AdminMovie,
  type AdminStats,
  type AdminUser,
  type MovieFormData,
  type QueryResult,
} from "../api/admin";
import { ContentShell } from "../components/ContentShell";
import { Pagination } from "../components/Pagination";

type Tab = "overview" | "users" | "movies" | "rag";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "users", label: "Users" },
  { id: "movies", label: "Movies" },
  { id: "rag", label: "RAG Test" },
];

const inputClass =
  "mt-1 w-full rounded-xl border border-border bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent";

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl border border-border bg-bg p-4">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-text">{value.toLocaleString()}</p>
    </div>
  );
}

function OverviewTab() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAdminStats()
      .then(setStats)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load stats"));
  }, []);

  if (error) return <p className="text-sm text-red-500">{error}</p>;
  if (!stats) return <p className="text-sm text-muted">Loading stats…</p>;

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <StatCard label="Users" value={stats.user_count} />
      <StatCard label="Movies" value={stats.movie_count} />
      <StatCard label="Chunks" value={stats.chunk_count} />
      <StatCard label="Genres" value={stats.genre_count} />
    </div>
  );
}

function UsersTab() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [roleError, setRoleError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchAdminUsers()
      .then((data) => {
        if (!cancelled) setUsers(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load users");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleRoleChange = async (user: AdminUser, role: string) => {
    setRoleError(null);
    try {
      const updated = await updateAdminUserRole(user.id, role);
      setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)));
    } catch (err) {
      setRoleError(err instanceof Error ? err.message : "Failed to update role");
    }
  };

  if (error) return <p className="text-sm text-red-500">{error}</p>;

  return (
    <div>
      {roleError && (
        <p className="mb-4 text-sm text-red-500" role="alert">
          {roleError}
        </p>
      )}
      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full min-w-[32rem] text-left text-sm">
          <thead className="border-b border-border bg-bg text-muted">
            <tr>
              <th className="px-4 py-3 font-medium">Email</th>
              <th className="px-4 py-3 font-medium">Role</th>
              <th className="px-4 py-3 font-medium">Joined</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.id} className="border-b border-border last:border-0">
                <td className="px-4 py-3 text-text">{user.email}</td>
                <td className="px-4 py-3">
                  <select
                    value={user.role}
                    onChange={(e) => void handleRoleChange(user, e.target.value)}
                    className="rounded-lg border border-border bg-bg px-2 py-1 text-sm text-text"
                  >
                    <option value="user">user</option>
                    <option value="admin">admin</option>
                  </select>
                </td>
                <td className="px-4 py-3 text-muted">
                  {new Date(user.created_at).toLocaleDateString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MovieForm({
  form,
  setForm,
  onSubmit,
  onCancel,
  submitLabel,
  showId,
}: {
  form: MovieFormData;
  setForm: (form: MovieFormData) => void;
  onSubmit: () => void;
  onCancel: () => void;
  submitLabel: string;
  showId: boolean;
}) {
  const set = (key: keyof MovieFormData, value: string) =>
    setForm({ ...form, [key]: value });

  return (
    <form
      className="space-y-4 rounded-2xl border border-border bg-bg p-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      {showId && (
        <label className="block">
          <span className="text-sm text-muted">Movie ID</span>
          <input
            type="number"
            required
            min={1}
            value={form.id ?? ""}
            onChange={(e) => setForm({ ...form, id: Number(e.target.value) })}
            className={inputClass}
          />
        </label>
      )}
      <label className="block">
        <span className="text-sm text-muted">Title</span>
        <input
          type="text"
          required
          value={form.title}
          onChange={(e) => set("title", e.target.value)}
          className={inputClass}
        />
      </label>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="text-sm text-muted">Release year</span>
          <input
            type="number"
            value={form.release_year}
            onChange={(e) => set("release_year", e.target.value)}
            className={inputClass}
          />
        </label>
        <label className="block">
          <span className="text-sm text-muted">Runtime (min)</span>
          <input
            type="number"
            value={form.runtime}
            onChange={(e) => set("runtime", e.target.value)}
            className={inputClass}
          />
        </label>
      </div>
      <label className="block">
        <span className="text-sm text-muted">Vote average</span>
        <input
          type="number"
          step="0.1"
          min={0}
          max={10}
          value={form.vote_average}
          onChange={(e) => set("vote_average", e.target.value)}
          className={inputClass}
        />
      </label>
      <label className="block">
        <span className="text-sm text-muted">Tagline</span>
        <input
          type="text"
          value={form.tagline}
          onChange={(e) => set("tagline", e.target.value)}
          className={inputClass}
        />
      </label>
      <label className="block">
        <span className="text-sm text-muted">Overview</span>
        <textarea
          rows={4}
          value={form.overview}
          onChange={(e) => set("overview", e.target.value)}
          className={inputClass}
        />
      </label>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="text-sm text-muted">Poster path</span>
          <input
            type="text"
            placeholder="/abc123.jpg"
            value={form.poster_path}
            onChange={(e) => set("poster_path", e.target.value)}
            className={inputClass}
          />
        </label>
        <label className="block">
          <span className="text-sm text-muted">Backdrop path</span>
          <input
            type="text"
            placeholder="/xyz789.jpg"
            value={form.backdrop_path}
            onChange={(e) => set("backdrop_path", e.target.value)}
            className={inputClass}
          />
        </label>
      </div>
      <p className="text-xs text-muted">
        Editing overview does not auto re-embed. Run{" "}
        <code className="rounded bg-surface px-1">python scripts/run_embed.py</code> after bulk
        changes.
      </p>
      <div className="flex gap-2">
        <button
          type="submit"
          className="rounded-xl bg-text px-4 py-2 text-sm font-medium text-bg hover:opacity-90"
        >
          {submitLabel}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-xl border border-border px-4 py-2 text-sm text-muted hover:text-text"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

function MoviesTab() {
  const [movies, setMovies] = useState<AdminMovie[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [formMode, setFormMode] = useState<"none" | "add" | "edit">("none");
  const [form, setForm] = useState<MovieFormData>(emptyMovieForm());
  const [editId, setEditId] = useState<number | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchAdminMovies(page, query)
      .then((data) => {
        if (cancelled) return;
        setError(null);
        setMovies(data.movies);
        setTotalPages(data.total_pages);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load movies");
      });
    return () => {
      cancelled = true;
    };
  }, [page, query, reloadToken]);

  const startAdd = () => {
    setForm(emptyMovieForm());
    setEditId(null);
    setFormError(null);
    setFormMode("add");
  };

  const startEdit = async (id: number) => {
    setFormError(null);
    try {
      const movie = await fetchAdminMovie(id);
      setForm(movieToForm(movie));
      setEditId(id);
      setFormMode("edit");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load movie");
    }
  };

  const handleSubmit = async () => {
    setFormError(null);
    try {
      if (formMode === "add") {
        if (!form.id) {
          setFormError("Movie ID is required");
          return;
        }
        await createAdminMovie(form);
      } else if (formMode === "edit" && editId != null) {
        await updateAdminMovie(editId, form);
      }
      setFormMode("none");
      setReloadToken((n) => n + 1);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Save failed");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <form
          className="flex flex-1 gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setPage(1);
            setQuery(search);
          }}
        >
          <input
            type="search"
            placeholder="Search by title…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 rounded-xl border border-border bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent"
          />
          <button
            type="submit"
            className="rounded-xl border border-border px-4 py-2 text-sm text-text hover:bg-bg"
          >
            Search
          </button>
        </form>
        <button
          type="button"
          onClick={startAdd}
          className="rounded-xl bg-text px-4 py-2 text-sm font-medium text-bg hover:opacity-90"
        >
          Add movie
        </button>
      </div>

      {error && <p className="text-sm text-red-500">{error}</p>}

      {formMode !== "none" && (
        <MovieForm
          form={form}
          setForm={setForm}
          onSubmit={() => void handleSubmit()}
          onCancel={() => setFormMode("none")}
          submitLabel={formMode === "add" ? "Create movie" : "Save changes"}
          showId={formMode === "add"}
        />
      )}

      {formError && (
        <p className="text-sm text-red-500" role="alert">
          {formError}
        </p>
      )}

      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full min-w-[40rem] text-left text-sm">
          <thead className="border-b border-border bg-bg text-muted">
            <tr>
              <th className="px-4 py-3 font-medium">ID</th>
              <th className="px-4 py-3 font-medium">Title</th>
              <th className="px-4 py-3 font-medium">Year</th>
              <th className="px-4 py-3 font-medium">Rating</th>
              <th className="px-4 py-3 font-medium" />
            </tr>
          </thead>
          <tbody>
            {movies.map((movie) => (
              <tr key={movie.id} className="border-b border-border last:border-0">
                <td className="px-4 py-3 text-muted">{movie.id}</td>
                <td className="px-4 py-3 text-text">{movie.title}</td>
                <td className="px-4 py-3 text-muted">{movie.release_year ?? "—"}</td>
                <td className="px-4 py-3 text-muted">
                  {movie.vote_average?.toFixed(1) ?? "—"}
                </td>
                <td className="px-4 py-3 text-right">
                  <button
                    type="button"
                    onClick={() => void startEdit(movie.id)}
                    className="text-xs text-muted hover:text-text"
                  >
                    Edit
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Pagination page={page} totalPages={totalPages} onChange={setPage} />
    </div>
  );
}

function RagTab() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<QueryResult | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const data = await submitQuery(question.trim());
      setResult(data);
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : "Query failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <form onSubmit={(e) => void handleSubmit(e)} className="flex flex-col gap-3 sm:flex-row">
        <input
          type="text"
          required
          placeholder="Ask about movies…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          className="flex-1 rounded-xl border border-border bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent"
        />
        <button
          type="submit"
          disabled={loading}
          className="rounded-xl bg-text px-4 py-2 text-sm font-medium text-bg hover:opacity-90 disabled:opacity-50"
        >
          {loading ? "Running…" : "Ask"}
        </button>
      </form>

      {error && (
        <p className="text-sm text-red-500" role="alert">
          {error}
        </p>
      )}

      {result && (
        <div className="space-y-4">
          <div className="rounded-2xl border border-border bg-bg p-4">
            <p className="text-xs text-muted">Answer</p>
            <p className="mt-2 text-sm text-text">{result.answer}</p>
          </div>
          <div>
            <p className="mb-2 text-xs text-muted">Retrieved chunks</p>
            <ul className="space-y-2">
              {result.retrieved.map((chunk) => (
                <li
                  key={`${chunk.movie_id}-${chunk.rrf_score}`}
                  className="rounded-xl border border-border bg-bg p-3 text-sm"
                >
                  <p className="font-medium text-text">
                    {chunk.title}
                    {chunk.release_year ? ` (${chunk.release_year})` : ""}
                    <span className="ml-2 text-xs font-normal text-muted">
                      score {chunk.rrf_score.toFixed(3)}
                    </span>
                  </p>
                  <p className="mt-1 text-muted">{chunk.chunk_preview}</p>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>("overview");

  return (
    <ContentShell>
      <h1 className="text-xl font-semibold text-text">Admin</h1>
      <p className="mt-1 text-sm text-muted">Manage users, movies, and test RAG queries.</p>

      <div className="mt-6 flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`rounded-full border px-4 py-1.5 text-sm transition-colors ${
              tab === t.id
                ? "border-accent/40 bg-bg text-text"
                : "border-border text-muted hover:text-text"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="mt-6">
        {tab === "overview" && <OverviewTab />}
        {tab === "users" && <UsersTab />}
        {tab === "movies" && <MoviesTab />}
        {tab === "rag" && <RagTab />}
      </div>
    </ContentShell>
  );
}
