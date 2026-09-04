// src/lib/auth.ts
// Thin wrapper around localStorage for the JWT issued by POST /auth/login
// and /auth/signup. Kept separate from api.ts so any client component can
// read/clear the token without importing the whole API surface.

const TOKEN_KEY = "signal.auth.token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
}