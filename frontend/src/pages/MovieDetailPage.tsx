import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { fetchMovieDetail, type MovieDetail } from "../api/movies";
import { ContentShell } from "../components/ContentShell";
import { detailCacheKey, getCache, setCache } from "../lib/cache";

function PosterColumn({ movie }: { movie: MovieDetail }) {
  const rating = movie.vote_average?.toFixed(1);
  const runtime = movie.runtime ? `${movie.runtime} min` : null;
  const meta = [movie.release_year, rating && `★ ${rating}`, runtime]
    .filter(Boolean)
    .join(" · ");

  return (
    <aside className="mx-auto shrink-0 md:mx-0">
      <div className="aspect-[2/3] w-[12.125rem] overflow-hidden rounded-xl bg-skeleton sm:w-[13.2rem] md:w-[14.3rem]">
        {movie.poster_url ? (
          <img
            src={movie.poster_url}
            alt={movie.title}
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-muted">
            No poster
          </div>
        )}
      </div>
      {meta && (
        <p className="mt-3 text-center text-sm text-muted md:text-left">{meta}</p>
      )}
    </aside>
  );
}

function DetailSkeleton() {
  return (
    <div className="mx-auto max-w-5xl px-4 pb-8 pt-4">
      <div className="flex flex-col gap-6 md:flex-row md:items-start">
        <div className="mx-auto shrink-0 animate-pulse md:mx-0">
          <div className="aspect-[2/3] w-[12.125rem] rounded-xl bg-skeleton sm:w-[13.2rem] md:w-[14.3rem]" />
          <div className="mx-auto mt-3 h-4 w-32 rounded bg-skeleton md:mx-0" />
        </div>
        <div className="min-w-0 flex-1 md:max-w-[608px]">
          <ContentShell embedded>
            <div className="animate-pulse space-y-4">
              <div className="h-8 w-3/4 rounded bg-skeleton" />
              <div className="flex gap-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="h-6 w-16 rounded-full bg-skeleton" />
                ))}
              </div>
              <div className="space-y-2">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="h-3 rounded bg-skeleton" />
                ))}
              </div>
            </div>
          </ContentShell>
        </div>
      </div>
    </div>
  );
}

function DetailInfo({ movie }: { movie: MovieDetail }) {
  return (
    <article className="detail-card-enter">
      <h1 className="text-2xl font-semibold text-text">{movie.title}</h1>

      {movie.tagline && (
        <p className="mt-3 text-sm italic text-muted">{movie.tagline}</p>
      )}

      {movie.genres.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {movie.genres.map((g) => (
            <span
              key={g}
              className="rounded-full border border-border px-3 py-0.5 text-xs text-muted"
            >
              {g}
            </span>
          ))}
        </div>
      )}

      {movie.overview && (
        <p className="mt-6 text-sm leading-relaxed text-text">{movie.overview}</p>
      )}

      {movie.directors.length > 0 && (
        <div className="mt-6">
          <h2 className="text-xs font-medium uppercase tracking-wide text-muted">
            Directors
          </h2>
          <p className="mt-1 text-sm text-text">{movie.directors.join(", ")}</p>
        </div>
      )}

      {movie.writers.length > 0 && (
        <div className="mt-4">
          <h2 className="text-xs font-medium uppercase tracking-wide text-muted">
            Writers
          </h2>
          <p className="mt-1 text-sm text-text">{movie.writers.join(", ")}</p>
        </div>
      )}

      {movie.cast.length > 0 && (
        <div className="mt-4">
          <h2 className="text-xs font-medium uppercase tracking-wide text-muted">
            Cast
          </h2>
          <p className="mt-1 text-sm text-text">{movie.cast.join(", ")}</p>
        </div>
      )}
    </article>
  );
}

export default function MovieDetailPage() {
  const { id } = useParams<{ id: string }>();
  const movieId = Number(id);
  const isInvalidId = !id || Number.isNaN(movieId);
  const [movie, setMovie] = useState<MovieDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isInvalidId) return;

    let cancelled = false;

    async function loadMovie() {
      await Promise.resolve();
      if (cancelled) return;

      const cacheKey = detailCacheKey(movieId);
      const cached = getCache<MovieDetail>(cacheKey);
      if (cached) {
        setMovie(cached);
        setError(null);
        setLoading(false);
        return;
      }

      setMovie(null);
      setLoading(true);
      setError(null);

      try {
        const data = await fetchMovieDetail(movieId);
        if (cancelled) return;
        setCache(cacheKey, data);
        setMovie(data);
      } catch {
        if (!cancelled) setError("Could not load movie details.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadMovie();
    return () => {
      cancelled = true;
    };
  }, [movieId, isInvalidId]);

  if (isInvalidId) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-16 text-center text-muted">
        Invalid movie ID
      </div>
    );
  }

  if (loading) return <DetailSkeleton />;

  if (error || !movie) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-16 text-center text-muted">
        {error ?? "Movie not found"}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-4 pb-8 pt-4">
      <div className="flex flex-col gap-6 md:flex-row md:items-start">
        <PosterColumn movie={movie} />
        <div className="min-w-0 flex-1 md:max-w-[608px]">
          <ContentShell embedded>
            <DetailInfo movie={movie} />
          </ContentShell>
        </div>
      </div>
    </div>
  );
}
