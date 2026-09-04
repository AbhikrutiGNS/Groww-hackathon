"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, AttentionFeedItem, CurrentUser, WatchlistListItem } from "@/lib/api";
import { AttentionFeed } from "@/components/AttentionFeed";
import { WatchlistTable } from "@/components/WatchlistTable";
import { AddTickerForm } from "@/components/AddTickerForm";

const POLL_MS = 30_000;

export default function Home() {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [checkingAuth, setCheckingAuth] = useState(true);

  const [watchlist, setWatchlist] = useState<WatchlistListItem[]>([]);
  const [feed, setFeed] = useState<AttentionFeedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const [removingSymbol, setRemovingSymbol] = useState<string | null>(null);
  const [acknowledging, setAcknowledging] = useState(false);
  // Set only while a background poll is failing (backend unreachable,
  // brief network blip, dev server mid-restart, etc.) — never thrown, so
  // it can't crash the UI. Last-known-good watchlist/feed data stays on
  // screen the whole time; this is just an honest "still trying" signal.
  const [connectionIssue, setConnectionIssue] = useState(false);

  // Resolve who's logged in before loading any watchlist data. api.me()
  // hits GET /auth/me; on a 401 (no/expired/invalid token) the shared
  // request() helper in lib/api.ts already clears the token and redirects
  // to /login, so a thrown ApiError here just means "redirect is in
  // flight" — nothing else to do.
  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => {
        /* redirect handled by lib/api.ts's 401 handler */
      })
      .finally(() => setCheckingAuth(false));
  }, []);

  const refresh = useCallback(async () => {
    // Deliberately swallowed here, not thrown — a background poll failing
    // (backend down for a moment, network blip, dev server reloading) must
    // never surface as an unhandled rejection / crash overlay. The last
    // successfully fetched watchlist/feed stay on screen; we just flag
    // that we're having trouble and let the next poll retry.
    try {
      const [wl, af] = await Promise.all([api.listWatchlist(), api.getAttentionFeed()]);
      setWatchlist(wl);
      setFeed(af);
      setConnectionIssue(false);
    } catch (err) {
      // A 401 mid-poll is handled by lib/api.ts itself (clears token,
      // redirects to /login) — nothing more to do here. Anything else is
      // a transient connectivity problem, not a real error state.
      if (!(err instanceof ApiError && err.status === 401)) {
        setConnectionIssue(true);
      }
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    refresh().finally(() => setLoading(false));
    const interval = setInterval(refresh, POLL_MS);
    return () => clearInterval(interval);
  }, [user, refresh]);

  function handleLogout() {
    api.logout();
    router.push("/login");
  }

  async function handleAdd(symbol: string) {
    setAdding(true);
    setAddError(null);
    try {
      await api.addTicker(symbol);
      await refresh();
    } catch (err) {
      setAddError(err instanceof ApiError ? err.message : "Couldn't add that ticker.");
    } finally {
      setAdding(false);
    }
  }

  async function handleRemove(symbol: string) {
    setRemovingSymbol(symbol);
    try {
      await api.removeTicker(symbol);
      await refresh();
    } finally {
      setRemovingSymbol(null);
    }
  }

  async function handleAcknowledge() {
    setAcknowledging(true);
    try {
      await api.acknowledge();
      await refresh();
    } finally {
      setAcknowledging(false);
    }
  }

  if (checkingAuth) {
    return (
      <main className="flex-1 flex items-center justify-center px-6 py-12">
        <p className="text-sm text-[var(--text-tertiary)]">Loading…</p>
      </main>
    );
  }

  if (!user) {
    // Redirect to /login is already underway (triggered by the 401
    // handler in lib/api.ts); render nothing in the meantime.
    return null;
  }

  return (
    <main className="flex-1 max-w-3xl w-full mx-auto px-6 py-12">
      <header className="mb-10 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight bg-gradient-to-r from-fuchsia-400 to-violet-400 bg-clip-text text-transparent">
            Signal
          </h1>
          <p className="text-sm text-[var(--text-secondary)] mt-1">
            A watchlist that tells you what changed, not just what you own.
          </p>
          {connectionIssue && (
            <p className="text-xs text-yellow-500 mt-1.5">
              ⚠️ Having trouble reaching the server — showing last known data, retrying…
            </p>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0 pt-1">
          <span className="text-xs text-[var(--text-tertiary)] font-mono-tabular">{user.email}</span>
          <button
            onClick={handleLogout}
            className="rounded-md border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-hover)] transition-colors"
          >
            Log out
          </button>
        </div>
      </header>

      <div className="mb-12">
        <AttentionFeed
          items={feed}
          loading={loading}
          onAcknowledge={handleAcknowledge}
          acknowledging={acknowledging}
        />
      </div>

      <section>
        <h2 className="text-lg font-semibold mb-4">Your watchlist</h2>
        <div className="mb-4">
          <AddTickerForm onAdd={handleAdd} adding={adding} error={addError} />
        </div>
        <WatchlistTable
          items={watchlist}
          loading={loading}
          onRemove={handleRemove}
          removingSymbol={removingSymbol}
        />
      </section>
    </main>
  );
}