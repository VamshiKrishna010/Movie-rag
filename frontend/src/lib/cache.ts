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
