const TOKEN_KEY = "mr_token";
const REFRESH_KEY = "mr_refresh";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function setRefreshToken(token: string): void {
  localStorage.setItem(REFRESH_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

export function authHeaders(): HeadersInit {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

let refreshPromise: Promise<boolean> | null = null;

async function refreshAccessToken(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    return false;
  }

  const res = await fetch("/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });

  if (!res.ok) {
    return false;
  }

  const data = (await res.json()) as { access_token: string; refresh_token: string };
  setToken(data.access_token);
  setRefreshToken(data.refresh_token);
  return true;
}

async function tryRefreshAccessToken(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = refreshAccessToken().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

export async function authFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response = await fetch(input, { ...init, headers });

  if (response.status === 401 && getRefreshToken()) {
    const refreshed = await tryRefreshAccessToken();
    if (refreshed) {
      const retryHeaders = new Headers(init.headers);
      const newToken = getToken();
      if (newToken) {
        retryHeaders.set("Authorization", `Bearer ${newToken}`);
      }
      response = await fetch(input, { ...init, headers: retryHeaders });
    } else {
      clearToken();
      if (window.location.pathname !== "/auth") {
        window.location.href = "/auth";
      }
    }
  }

  return response;
}

export { refreshAccessToken };
