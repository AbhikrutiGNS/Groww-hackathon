"use client";

import { Fragment, useState } from "react";
import { WatchlistListItem } from "@/lib/api";
import {
  formatPrice,
  formatMarketCap,
  formatRatio,
  formatPlainPercent,
  timeAgo,
} from "@/lib/format";
import { GlossaryBox, Term } from "@/components/Glossary";

function isRecentlyAdded(iso: string): boolean {
  const then = new Date(iso).getTime();
  return Date.now() - then < 60 * 60 * 1000; // < 1h
}

// Free/delayed market data APIs (yfinance included) don't guarantee
// real-time freshness — 15 minutes is the standard "delayed quote"
// threshold most retail platforms use, so past that we say so instead of
// quietly presenting a number that might be stale.
const STALE_THRESHOLD_MS = 15 * 60 * 1000;

function isDataStale(iso: string): boolean {
  return Date.now() - new Date(iso).getTime() > STALE_THRESHOLD_MS;
}

function Stat({ label, term, value }: { label: string; term: string; value: string }) {
  return (
    <div className="rounded-md border border-violet-500/20 bg-[var(--bg)]/40 px-2.5 py-2">
      <div className="text-[10px] font-medium uppercase tracking-wide text-[var(--text-tertiary)]">
        <Term label={label} term={term} />
      </div>
      <div className="mt-0.5 font-mono-tabular text-xs text-[var(--text-primary)]">{value}</div>
    </div>
  );
}

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
  const [expanded, setExpanded] = useState<string | null>(null);
  const [showGlossary, setShowGlossary] = useState(false);

  if (loading) {
    return <div className="text-sm text-[var(--text-tertiary)] py-6">Loading watchlist…</div>;
  }

  if (items.length === 0) {
    return (
      <div className="py-14 text-center border border-dashed border-violet-500/40 rounded-xl shadow-[0_0_40px_-14px_rgba(168,85,247,0.5)]">
        <p className="text-sm font-medium text-transparent bg-clip-text bg-gradient-to-r from-fuchsia-400 to-violet-400">
          Your watchlist is empty.
        </p>
        <p className="text-xs text-[var(--text-tertiary)] mt-2 max-w-xs mx-auto">
          Add a ticker above to start tracking meaningful market changes.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-violet-500/40 bg-[var(--bg-raised)]/40 shadow-[0_0_30px_-12px_rgba(168,85,247,0.35)]">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-[var(--text-tertiary)] border-b border-violet-500/30">
            <th className="font-medium py-2 pl-4 pr-2"></th>
            <th className="font-medium py-2 pr-2">Symbol</th>
            <th className="font-medium py-2 pr-2">Price</th>
            <th className="font-medium py-2 pr-2">Day range</th>
            <th className="font-medium py-2 pr-2">1W range</th>
            <th className="font-medium py-2 pr-2">Trend</th>
            <th className="font-medium py-2 pr-2">Added</th>
            <th className="font-medium py-2 pr-4 text-right"></th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const isExpanded = expanded === item.symbol;
            const recentlyAdded = isRecentlyAdded(item.added_at);
            return (
              <Fragment key={item.symbol}>
                <tr
                  onClick={() => setExpanded(isExpanded ? null : item.symbol)}
                  className={`cursor-pointer border-b border-violet-500/15 last:border-0 group transition-colors ${
                    isExpanded ? "bg-violet-900/30" : "hover:bg-violet-900/20"
                  }`}
                >
                  <td className="py-2.5 pl-4 pr-2 text-violet-300/70">
                    <span
                      className={`inline-block transition-transform duration-150 ${isExpanded ? "rotate-90" : ""}`}
                    >
                      ›
                    </span>
                  </td>
                  <td className="py-2.5 pr-2 font-mono-tabular font-medium text-[var(--text-primary)]">
                    <span className="inline-flex items-center gap-1.5">
                      {item.symbol}
                      {recentlyAdded && (
                        <span className="rounded px-1.5 py-0.5 text-[10px] font-semibold bg-fuchsia-500/10 text-fuchsia-400 border border-fuchsia-400/30">
                          new
                        </span>
                      )}
                    </span>
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
                      <span
                        className="inline-flex items-center gap-1.5 text-[var(--text-tertiary)]"
                        title={`Needs 50 trading days of price history — ${item.history_days}/50 so far`}
                      >
                        <span className="h-1 w-8 rounded-full bg-violet-500/15 overflow-hidden">
                          <span
                            className="block h-full bg-gradient-to-r from-fuchsia-400 to-violet-400"
                            style={{ width: `${Math.min(100, (item.history_days / 50) * 100)}%` }}
                          />
                        </span>
                        {item.history_days}/50d
                      </span>
                    )}
                  </td>
                  <td className="py-2.5 pr-2 text-[var(--text-tertiary)]">{timeAgo(item.added_at)}</td>
                  <td className="py-2.5 pr-4 text-right">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onRemove(item.symbol);
                      }}
                      disabled={removingSymbol === item.symbol}
                      className="opacity-0 group-hover:opacity-100 text-xs text-[var(--text-tertiary)] hover:text-[var(--loss)] transition-opacity disabled:opacity-50"
                    >
                      {removingSymbol === item.symbol ? "removing…" : "remove"}
                    </button>
                  </td>
                </tr>
                {isExpanded && (
                  <tr className="bg-violet-950/20 border-b border-violet-500/15">
                    <td colSpan={8} className="px-4 py-4">
                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-8 gap-y-4">
                        <div>
                          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-fuchsia-300/80">
                            Fundamentals
                          </p>
                          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                            <Stat label="Market Cap" term="Market Cap" value={formatMarketCap(item.market_cap)} />
                            <Stat label="P/E" term="P/E Ratio" value={formatRatio(item.pe_ratio)} />
                            <Stat label="P/B" term="P/B Ratio" value={formatRatio(item.pb_ratio)} />
                            <Stat label="EPS" term="EPS" value={item.eps ? `$${formatPrice(item.eps)}` : "—"} />
                            <Stat label="ROE" term="ROE" value={formatPlainPercent(item.roe)} />
                            <Stat label="ROCE" term="ROCE" value={formatPlainPercent(item.roce)} />
                            <Stat label="Debt/Equity" term="Debt/Equity" value={formatRatio(item.debt_to_equity, "")} />
                            <Stat label="Div Yield" term="Dividend Yield" value={formatPlainPercent(item.dividend_yield)} />
                          </div>
                          {item.fundamentals_updated_at && (
                            <p
                              className={`mt-1.5 text-[10px] ${
                                isDataStale(item.fundamentals_updated_at)
                                  ? "text-yellow-500"
                                  : "text-[var(--text-tertiary)]"
                              }`}
                            >
                              {isDataStale(item.fundamentals_updated_at) && "⚠️ Delayed — "}
                              Fundamentals as of {timeAgo(item.fundamentals_updated_at)}
                            </p>
                          )}
                        </div>

                        <div>
                          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-fuchsia-300/80">
                            Technicals
                          </p>
                          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                            <Stat label="52W High" term="52W High" value={item.week_52_high ? `$${formatPrice(item.week_52_high)}` : "—"} />
                            <Stat label="52W Low" term="52W Low" value={item.week_52_low ? `$${formatPrice(item.week_52_low)}` : "—"} />
                            <Stat
                              label="SMA 20/50"
                              term="SMA 20/50"
                              value={item.sma_20 && item.sma_50 ? `${formatPrice(item.sma_20)} / ${formatPrice(item.sma_50)}` : "—"}
                            />
                            <Stat
                              label="EMA 20/50"
                              term="EMA 20/50"
                              value={item.ema_20 && item.ema_50 ? `${formatPrice(item.ema_20)} / ${formatPrice(item.ema_50)}` : "—"}
                            />
                          </div>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>

      <div className="border-t border-violet-500/20 px-4 py-2.5">
        <button
          type="button"
          onClick={() => setShowGlossary((v) => !v)}
          className="inline-flex items-center gap-1.5 text-xs font-medium text-violet-300/80 hover:text-fuchsia-300 transition-colors"
        >
          <span className={`inline-block transition-transform duration-150 ${showGlossary ? "rotate-90" : ""}`}>
            ›
          </span>
          Glossary
        </button>
        {showGlossary && (
          <div className="mt-3">
            <GlossaryBox />
          </div>
        )}
      </div>
    </div>
  );
}