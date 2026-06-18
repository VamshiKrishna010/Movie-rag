const MAX_AGE_DAYS = 365;

export function getCookie(name: string): string | null {
  const match = document.cookie.match(
    new RegExp(`(?:^|; )${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}=([^;]*)`),
  );
  return match ? decodeURIComponent(match[1]) : null;
}

export function setCookie(name: string, value: string, days = MAX_AGE_DAYS): void {
  const expires = new Date(Date.now() + days * 864e5).toUTCString();
  document.cookie = `${name}=${encodeURIComponent(value)}; expires=${expires}; path=/; SameSite=Lax`;
}

export function deleteCookie(name: string): void {
  document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
}

export const GENRE_COOKIE = "mr_genre";

export function getStoredGenreId(): number | null {
  const raw = getCookie(GENRE_COOKIE);
  if (!raw || raw === "all") return null;
  const id = parseInt(raw, 10);
  return Number.isNaN(id) ? null : id;
}

export function setStoredGenreId(genreId: number | null): void {
  if (genreId === null) {
    deleteCookie(GENRE_COOKIE);
  } else {
    setCookie(GENRE_COOKIE, String(genreId));
  }
}
