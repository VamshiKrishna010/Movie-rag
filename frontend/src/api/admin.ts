import { authFetch } from "../lib/auth";

export interface AdminStats {
  user_count: number;
  movie_count: number;
  chunk_count: number;
  genre_count: number;
}

export interface AdminUser {
  id: number;
  email: string;
  role: string;
  created_at: string;
}

export interface AdminMovie {
  id: number;
  title: string;
  release_year: number | null;
  overview: string | null;
  tagline: string | null;
  runtime: number | null;
  vote_average: number | null;
  poster_path: string | null;
  backdrop_path: string | null;
}

export interface PaginatedAdminMovies {
  movies: AdminMovie[];
  page: number;
  limit: number;
  total: number;
  total_pages: number;
}

export interface MovieFormData {
  id?: number;
  title: string;
  release_year: string;
  overview: string;
  tagline: string;
  runtime: string;
  vote_average: string;
  poster_path: string;
  backdrop_path: string;
}

export interface QueryResult {
  question: string;
  answer: string;
  retrieved: {
    movie_id: number;
    title: string;
    release_year: number | null;
    rrf_score: number;
    chunk_preview: string;
  }[];
}

async function parseError(res: Response, fallback: string): Promise<string> {
  const data = await res.json().catch(() => ({}));
  const detail = data.detail;
  if (typeof detail === "string") return detail;
  return fallback;
}

export async function fetchAdminStats(): Promise<AdminStats> {
  const res = await authFetch("/admin/stats");
  if (!res.ok) throw new Error(await parseError(res, "Failed to load stats"));
  return res.json();
}

export async function fetchAdminUsers(): Promise<AdminUser[]> {
  const res = await authFetch("/admin/users");
  if (!res.ok) throw new Error(await parseError(res, "Failed to load users"));
  return res.json();
}

export async function updateAdminUserRole(userId: number, role: string): Promise<AdminUser> {
  const res = await authFetch(`/admin/users/${userId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role }),
  });
  if (!res.ok) throw new Error(await parseError(res, "Failed to update role"));
  return res.json();
}

export async function fetchAdminMovies(
  page: number,
  q: string,
): Promise<PaginatedAdminMovies> {
  const params = new URLSearchParams({ page: String(page), limit: "20" });
  if (q.trim()) params.set("q", q.trim());
  const res = await authFetch(`/admin/movies?${params}`);
  if (!res.ok) throw new Error(await parseError(res, "Failed to load movies"));
  return res.json();
}

export async function fetchAdminMovie(id: number): Promise<AdminMovie> {
  const res = await authFetch(`/admin/movies/${id}`);
  if (!res.ok) throw new Error(await parseError(res, "Failed to load movie"));
  return res.json();
}

function toPayload(data: MovieFormData, includeId: boolean) {
  const payload: Record<string, unknown> = {
    title: data.title,
    release_year: data.release_year ? Number(data.release_year) : null,
    overview: data.overview || null,
    tagline: data.tagline || null,
    runtime: data.runtime ? Number(data.runtime) : null,
    vote_average: data.vote_average ? Number(data.vote_average) : null,
    poster_path: data.poster_path || null,
    backdrop_path: data.backdrop_path || null,
  };
  if (includeId && data.id != null) payload.id = data.id;
  return payload;
}

export async function createAdminMovie(data: MovieFormData): Promise<AdminMovie> {
  const res = await authFetch("/admin/movies", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(toPayload(data, true)),
  });
  if (!res.ok) throw new Error(await parseError(res, "Failed to create movie"));
  return res.json();
}

export async function updateAdminMovie(id: number, data: MovieFormData): Promise<AdminMovie> {
  const res = await authFetch(`/admin/movies/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(toPayload(data, false)),
  });
  if (!res.ok) throw new Error(await parseError(res, "Failed to update movie"));
  return res.json();
}

export async function submitQuery(question: string): Promise<QueryResult> {
  const res = await authFetch("/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, k: 5, include_chunks: false }),
  });
  if (!res.ok) throw new Error(await parseError(res, "Query failed"));
  return res.json();
}

export function movieToForm(movie: AdminMovie): MovieFormData {
  return {
    id: movie.id,
    title: movie.title,
    release_year: movie.release_year?.toString() ?? "",
    overview: movie.overview ?? "",
    tagline: movie.tagline ?? "",
    runtime: movie.runtime?.toString() ?? "",
    vote_average: movie.vote_average?.toString() ?? "",
    poster_path: movie.poster_path ?? "",
    backdrop_path: movie.backdrop_path ?? "",
  };
}

export const emptyMovieForm = (): MovieFormData => ({
  title: "",
  release_year: "",
  overview: "",
  tagline: "",
  runtime: "",
  vote_average: "",
  poster_path: "",
  backdrop_path: "",
});
