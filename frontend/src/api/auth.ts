import { authFetch, setToken } from "../lib/auth";

export interface User {
  id: number;
  email: string;
  role: string;
  scopes: string[];
}

export interface RoleScopes {
  roles: Record<string, string[]>;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export async function register(email: string, password: string): Promise<User> {
  const res = await fetch("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? "Registration failed");
  }
  return res.json();
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const body = new URLSearchParams({ username: email, password });
  const res = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    credentials: "include",
    body,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? "Login failed");
  }
  return res.json();
}

export async function logoutApi(): Promise<void> {
  await fetch("/auth/logout", {
    method: "POST",
    credentials: "include",
  }).catch(() => undefined);
}

export async function fetchMe(): Promise<User> {
  const res = await authFetch("/auth/me");
  if (!res.ok) throw new Error("Session expired");
  return res.json();
}

export async function fetchRoleScopes(): Promise<RoleScopes> {
  const res = await fetch("/auth/roles");
  if (!res.ok) throw new Error("Failed to load role scopes");
  return res.json();
}

export function storeAccessToken(tokens: TokenResponse): void {
  setToken(tokens.access_token);
}
