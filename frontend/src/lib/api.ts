const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* body wasn't JSON */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
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
