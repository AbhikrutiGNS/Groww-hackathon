"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, AttentionFeedItem, WatchlistListItem } from "@/lib/api";
import { AttentionFeed } from "@/components/AttentionFeed";
import { WatchlistTable } from "@/components/WatchlistTable";
import { AddTickerForm } from "@/components/AddTickerForm";

const POLL_MS = 30_000;

export default function Home() {
  const [watchlist, setWatchlist] = useState<WatchlistListItem[]>([]);
  const [feed, setFeed] = useState<AttentionFeedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const [removingSymbol, setRemovingSymbol] = useState<string | null>(null);
  const [acknowledging, setAcknowledging] = useState(false);

  const refresh = useCallback(async () => {
    const [wl, af] = await Promise.all([api.listWatchlist(), api.getAttentionFeed()]);
    setWatchlist(wl);
    setFeed(af);
  }, []);

  useEffect(() => {
    refresh().finally(() => setLoading(false));
    const interval = setInterval(refresh, POLL_MS);
    return () => clearInterval(interval);
  }, [refresh]);

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

  return (
    <main className="flex-1 max-w-3xl w-full mx-auto px-6 py-12">
      <header className="mb-10">
        <h1 className="text-2xl font-semibold tracking-tight">Signal</h1>
        <p className="text-sm text-[var(--text-secondary)] mt-1">
          A watchlist that tells you what changed, not just what you own.
        </p>
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
