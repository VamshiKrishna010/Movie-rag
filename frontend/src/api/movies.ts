export interface Movie {
  id: number;
  title: string;
  release_year: number | null;
  overview: string | null;
  vote_average: number | null;
  poster_url: string | null;
}

export interface PaginatedMovies {
  movies: Movie[];
  page: number;
  limit: number;
  total: number;
  total_pages: number;
}

export interface SearchResponse extends PaginatedMovies {
  query: string;
  mode: "title" | "hybrid";
}

export interface Genre {
  id: number;
  name: string;
  movie_count: number;
}

export interface MovieDetail {
  id: number;
  title: string;
  release_year: number | null;
  overview: string | null;
  tagline: string | null;
  runtime: number | null;
  vote_average: number | null;
  poster_url: string | null;
  backdrop_url: string | null;
  genres: string[];
  directors: string[];
  writers: string[];
  cast: string[];
  keywords: string[];
}

const PAGE_SIZE = 16;

interface ListParams {
  page?: number;
  limit?: number;
  genreId?: number | null;
}

function buildParams({ page = 1, limit = PAGE_SIZE, genreId }: ListParams): URLSearchParams {
  const params = new URLSearchParams({
    page: String(page),
    limit: String(limit),
  });
  if (genreId != null) {
    params.set("genre_id", String(genreId));
  }
  return params;
}

export async function browseMovies(params: ListParams = {}): Promise<PaginatedMovies> {
  const qs = buildParams(params);
  const res = await fetch(`/movies/browse?${qs}`);
  if (!res.ok) throw new Error("Failed to load movies");
  return res.json();
}

export async function searchMovies(
  q: string,
  params: ListParams = {},
): Promise<SearchResponse> {
  const qs = buildParams(params);
  qs.set("q", q);
  const res = await fetch(`/movies/search?${qs}`);
  if (!res.ok) throw new Error("Search failed");
  return res.json();
}

export async function fetchGenres(): Promise<Genre[]> {
  const res = await fetch("/genres");
  if (!res.ok) throw new Error("Failed to load genres");
  const data = await res.json();
  return data.genres;
}

export async function fetchMovieDetail(id: number): Promise<MovieDetail> {
  const res = await fetch(`/movies/${id}`);
  if (!res.ok) throw new Error("Failed to load movie");
  return res.json();
}

export { PAGE_SIZE };
