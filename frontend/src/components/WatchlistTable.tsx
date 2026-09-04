"use client";

import { WatchlistListItem } from "@/lib/api";
import { formatPrice, timeAgo } from "@/lib/format";

export function WatchlistTable({
  items,
  loading,
  onRemove,
  removingSymbol,
}: {
  items: WatchlistListItem[];
  loading: boolean;
  onRemove: (symbol: string) => void;
  removingSymbol: string | null;
}) {
  if (loading) {
    return <div className="text-sm text-[var(--text-tertiary)] py-6">Loading watchlist…</div>;
  }

  if (items.length === 0) {
    return (
      <div className="py-10 text-center border border-dashed border-[var(--border)] rounded-lg">
        <p className="text-sm text-[var(--text-secondary)]">Your watchlist is empty.</p>
        <p className="text-xs text-[var(--text-tertiary)] mt-1">Add a ticker above to start tracking it.</p>
      </div>
    );
  }

  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-[var(--text-tertiary)] border-b border-[var(--border)]">
          <th className="font-medium py-2 pr-2">Symbol</th>
          <th className="font-medium py-2 pr-2">Price</th>
          <th className="font-medium py-2 pr-2">Day range</th>
          <th className="font-medium py-2 pr-2">1W range</th>
          <th className="font-medium py-2 pr-2">Trend</th>
          <th className="font-medium py-2 pr-2">Added</th>
          <th className="font-medium py-2 pr-2 text-right"></th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr
            key={item.symbol}
            className="border-b border-[var(--border)] last:border-0 group hover:bg-[var(--bg-raised-hover)]"
          >
            <td className="py-2.5 pr-2 font-mono-tabular font-medium text-[var(--text-primary)]">
              {item.symbol}
              {item.notes && (
                <div className="text-xs font-sans font-normal text-[var(--text-tertiary)]">
                  {item.notes}
                </div>
              )}
            </td>
            <td className="py-2.5 pr-2 font-mono-tabular text-[var(--text-primary)]">
              {item.current_price ? `$${formatPrice(item.current_price)}` : (
                <span className="text-[var(--text-tertiary)]">pending…</span>
              )}
              {item.is_stale && (
                <span className="ml-2 text-xs" style={{ color: "var(--stale)" }} title="Last real quote failed; showing last known price">
                  stale
                </span>
              )}
            </td>
            <td className="py-2.5 pr-2 font-mono-tabular text-[var(--text-secondary)]">
              {item.day_low && item.day_high
                ? `${formatPrice(item.day_low)} – ${formatPrice(item.day_high)}`
                : "—"}
            </td>
            <td className="py-2.5 pr-2 font-mono-tabular text-[var(--text-secondary)]">
              {item.week_low && item.week_high
                ? `${formatPrice(item.week_low)} – ${formatPrice(item.week_high)}`
                : "—"}
            </td>
            <td className="py-2.5 pr-2 font-mono-tabular">
              {item.sma_20 && item.sma_50 ? (
                Number(item.sma_20) > Number(item.sma_50) ? (
                  <span style={{ color: "var(--gain)" }} title={`SMA20 ${formatPrice(item.sma_20)} > SMA50 ${formatPrice(item.sma_50)}`}>
                    ▲ up
                  </span>
                ) : (
                  <span style={{ color: "var(--loss)" }} title={`SMA20 ${formatPrice(item.sma_20)} < SMA50 ${formatPrice(item.sma_50)}`}>
                    ▼ down
                  </span>
                )
              ) : (
                <span className="text-[var(--text-tertiary)]" title="Needs 50 days of price history">
                  building…
                </span>
              )}
            </td>
            <td className="py-2.5 pr-2 text-[var(--text-tertiary)]">{timeAgo(item.added_at)}</td>
            <td className="py-2.5 pr-2 text-right">
              <button
                onClick={() => onRemove(item.symbol)}
                disabled={removingSymbol === item.symbol}
                className="opacity-0 group-hover:opacity-100 text-xs text-[var(--text-tertiary)] hover:text-[var(--loss)] transition-opacity disabled:opacity-50"
              >
                {removingSymbol === item.symbol ? "removing…" : "remove"}
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
