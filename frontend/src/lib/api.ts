import { clearToken, getToken, setToken } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type TokenResponse = {
  access_token: string;
  token_type: string;
};

export type CurrentUser = {
  id: string;
  email: string;
};

export type WatchlistListItem = {
  symbol: string;
  notes: string | null;
  added_at: string;
  current_price: string | null;
  is_stale: boolean | null;
  day_high: string | null;
  day_low: string | null;
};

export type AttentionFeedItem = {
  symbol: string;
  current_price: string;
  baseline_price: string | null;
  percent_change: string | null;
  is_new_addition: boolean;
  is_stale: boolean;
  hit_52w_high: boolean;
  hit_52w_low: boolean;
};

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// Endpoints that must never redirect-on-401 themselves — a failed login or
// signup attempt is an expected, in-place error, not a session expiry.
const AUTH_ENDPOINTS = ["/auth/login", "/auth/signup"];

async function request<T>(path: string, init?: RequestInit, opts?: { skipAuth?: boolean }): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (token && !opts?.skipAuth) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* body wasn't JSON */
    }

    // Session expired / invalid token: clear it and send the user back to
    // the login page, unless the 401 came from login/signup itself (that's
    // just "wrong password", not "your session expired").
    if (res.status === 401 && !AUTH_ENDPOINTS.includes(path)) {
      clearToken();
      if (typeof window !== "undefined" && window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }

    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  signup: async (email: string, password: string) => {
    const tokens = await request<TokenResponse>(
      "/auth/signup",
      { method: "POST", body: JSON.stringify({ email, password }) },
      { skipAuth: true }
    );
    setToken(tokens.access_token);
    return tokens;
  },
  login: async (email: string, password: string) => {
    const tokens = await request<TokenResponse>(
      "/auth/login",
      { method: "POST", body: JSON.stringify({ email, password }) },
      { skipAuth: true }
    );
    setToken(tokens.access_token);
    return tokens;
  },
  me: () => request<CurrentUser>("/auth/me"),
  logout: () => clearToken(),

  listWatchlist: () => request<WatchlistListItem[]>("/watchlist"),
  addTicker: (symbol: string, notes?: string) =>
    request("/watchlist", {
      method: "POST",
      body: JSON.stringify({ symbol, notes: notes || null }),
    }),
  removeTicker: (symbol: string) =>
    request<void>(`/watchlist/${encodeURIComponent(symbol)}`, {
      method: "DELETE",
    }),
  getAttentionFeed: () => request<AttentionFeedItem[]>("/watchlist/attention-feed"),
  acknowledge: () => request<void>("/watchlist/acknowledge", { method: "POST" }),
};

export { ApiError };