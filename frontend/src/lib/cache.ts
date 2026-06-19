const TTL_MS = 5 * 60 * 1000;

interface CacheEntry<T> {
  data: T;
  expiresAt: number;
}

export function getCache<T>(key: string): T | null {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const entry: CacheEntry<T> = JSON.parse(raw);
    if (Date.now() > entry.expiresAt) {
      sessionStorage.removeItem(key);
      return null;
    }
    return entry.data;
  } catch {
    return null;
  }
}

export function setCache<T>(key: string, data: T): void {
  try {
    const entry: CacheEntry<T> = { data, expiresAt: Date.now() + TTL_MS };
    sessionStorage.setItem(key, JSON.stringify(entry));
  } catch {
    // sessionStorage full or unavailable
  }
}

export function browseCacheKey(genreId: number | null, page: number): string {
  return `mr:browse:${genreId ?? "all"}:${page}`;
}

export function searchCacheKey(
  q: string,
  genreId: number | null,
  page: number,
): string {
  return `mr:search:${q}:${genreId ?? "all"}:${page}`;
}

export function detailCacheKey(id: number): string {
  return `mr:detail:${id}`;
}

export function adminStatsKey(): string {
  return "mr:admin:stats";
}

export function adminUsersKey(): string {
  return "mr:admin:users";
}

export function adminMoviesKey(page: number, q: string): string {
  return `mr:admin:movies:${page}:${q.trim() || ""}`;
}

export function adminMovieKey(id: number): string {
  return `mr:admin:movie:${id}`;
}

export function invalidateAdminStats(): void {
  try {
    sessionStorage.removeItem(adminStatsKey());
  } catch {
    // ignore
  }
}

export function invalidateAdminUsers(): void {
  try {
    sessionStorage.removeItem(adminUsersKey());
  } catch {
    // ignore
  }
}

export function invalidateAdminMovies(): void {
  try {
    for (let i = sessionStorage.length - 1; i >= 0; i--) {
      const key = sessionStorage.key(i);
      if (key?.startsWith("mr:admin:movies:") || key?.startsWith("mr:admin:movie:")) {
        sessionStorage.removeItem(key);
      }
    }
  } catch {
    // ignore
  }
}
