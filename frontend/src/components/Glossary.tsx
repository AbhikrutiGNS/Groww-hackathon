"use client";

import type { ReactNode } from "react";

// Single source of truth for every fundamentals/technicals term surfaced in
// the expanded row — used both by the inline "?" tooltips and by the
// consolidated glossary box, so the two can never drift out of sync.
export const GLOSSARY: Record<string, string> = {
  "Market Cap": "Total value of all outstanding shares (price × shares outstanding). A quick read on company size.",
  "P/E Ratio": "Price-to-Earnings. Share price divided by earnings per share — how much you're paying for ₹1 of profit. Higher can mean pricier or higher growth expectations.",
  "P/B Ratio": "Price-to-Book. Share price divided by book value per share — compares market price to the company's accounting net worth.",
  "EPS": "Earnings Per Share. Net profit divided by number of shares — the company's bottom line, per share.",
  "ROE": "Return on Equity. Net profit as a % of shareholder equity — how efficiently the company turns shareholders' money into profit.",
  "ROCE": "Return on Capital Employed. Operating profit as a % of capital employed — profitability including debt, not just equity.",
  "Debt/Equity": "Total debt divided by shareholder equity. Higher means more of the company is financed by borrowing.",
  "Dividend Yield": "Annual dividend per share as a % of the current price — the cash-return rate if you hold the stock.",
  "52W High": "The highest price this stock has traded at over the last 52 weeks.",
  "52W Low": "The lowest price this stock has traded at over the last 52 weeks.",
  "1W Range": "The lowest–highest price this stock has traded at over the last 7 days.",
  "Day Range": "The lowest–highest price this stock has traded at so far today.",
  "SMA 20/50": "Simple Moving Average. The plain average closing price over the last 20 or 50 trading days — smooths out daily noise to show the underlying trend.",
  "EMA 20/50": "Exponential Moving Average. Like SMA, but weights recent days more heavily — reacts faster to new price moves.",
  "Golden Cross": "The 20-day average crossing above the 50-day average — often read as a bullish trend signal.",
  "Death Cross": "The 20-day average crossing below the 50-day average — often read as a bearish trend signal.",
};

// Small "?" badge that reveals a definition on hover/focus. Deliberately
// tiny and low-contrast until interacted with, so it doesn't compete with
// the actual numbers for attention.
export function Term({ label, term }: { label: ReactNode; term: keyof typeof GLOSSARY | string }) {
  const definition = GLOSSARY[term];
  return (
    <span className="inline-flex items-center gap-1">
      <span>{label}</span>
      {definition && (
        <span className="group/tip relative inline-flex">
          <button
            type="button"
            className="flex h-3.5 w-3.5 items-center justify-center rounded-full border border-violet-400/40 text-[9px] leading-none text-violet-300/80 transition-colors hover:border-fuchsia-400 hover:text-fuchsia-300 focus:border-fuchsia-400 focus:text-fuchsia-300 focus:outline-none"
            aria-label={`What is ${term}?`}
          >
            ?
          </button>
          <span
            role="tooltip"
            className="pointer-events-none absolute bottom-full left-1/2 z-30 mb-2 w-48 -translate-x-1/2 rounded-lg border border-violet-500/40 bg-[#181022] px-3 py-2 text-[11px] font-normal leading-snug text-[var(--text-secondary)] opacity-0 shadow-[0_0_24px_-6px_rgba(217,70,239,0.45)] transition-opacity duration-150 group-hover/tip:opacity-100 group-focus-within/tip:opacity-100"
          >
            {definition}
          </span>
        </span>
      )}
    </span>
  );
}

// Consolidated glossary box — one shared instance for the whole table,
// toggled by a "Glossary" button rather than repeated inside every
// expanded row (repeating it per-row was noisy and mostly redundant).
export function GlossaryBox({ terms }: { terms?: string[] }) {
  const entries = terms ?? Object.keys(GLOSSARY);
  return (
    <div className="rounded-lg border border-violet-500/30 bg-violet-950/20 p-4">
      <p className="mb-3 text-[11px] font-semibold uppercase tracking-wide text-fuchsia-300/80">
        Glossary
      </p>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-2.5 sm:grid-cols-2">
        {entries.map((term) => (
          <div key={term} className="text-[11px] leading-snug">
            <dt className="inline font-medium text-[var(--text-secondary)]">{term}: </dt>
            <dd className="inline text-[var(--text-tertiary)]">{GLOSSARY[term]}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}