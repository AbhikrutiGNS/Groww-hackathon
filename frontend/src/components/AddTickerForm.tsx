"use client";

import { useState } from "react";

export function AddTickerForm({
  onAdd,
  adding,
  error,
}: {
  onAdd: (symbol: string) => void;
  adding: boolean;
  error: string | null;
}) {
  const [symbol, setSymbol] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = symbol.trim();
    if (!trimmed) return;
    onAdd(trimmed);
    setSymbol("");
  }

  return (
    <form onSubmit={handleSubmit} className="flex gap-2">
      <input
        value={symbol}
        onChange={(e) => setSymbol(e.target.value)}
        placeholder="Add a ticker — e.g. AAPL"
        className="flex-1 rounded-md border border-[var(--border)] bg-[var(--bg-raised)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none focus:border-[var(--signal)] font-mono-tabular"
      />
      <button
        type="submit"
        disabled={adding || !symbol.trim()}
        className="rounded-md px-4 py-2 text-sm font-medium disabled:opacity-50 transition-colors"
        style={{ background: "var(--signal)", color: "#1a1305" }}
      >
        {adding ? "Adding…" : "Add"}
      </button>
      {error && <p className="text-xs text-[var(--loss)] self-center ml-2">{error}</p>}
    </form>
  );
}
