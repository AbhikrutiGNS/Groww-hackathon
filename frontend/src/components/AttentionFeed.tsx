"use client";

import { AttentionFeedItem } from "@/lib/api";
import { formatPrice, formatPercent } from "@/lib/format";

function ReasonBadge({ label, tone }: { label: string; tone: "signal" | "gain" | "loss" | "stale" }) {
  const toneMap = {
    signal: { bg: "var(--signal-dim)", fg: "var(--signal)" },
    gain: { bg: "var(--gain-dim)", fg: "var(--gain)" },
    loss: { bg: "var(--loss-dim)", fg: "var(--loss)" },
    stale: { bg: "#1c2229", fg: "var(--stale)" },
  }[tone];
  return (
    <span
      className="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium"
      style={{ background: toneMap.bg, color: toneMap.fg }}
    >
      {label}
    </span>
  );
}

export function AttentionFeed({
  items,
  loading,
  onAcknowledge,
  acknowledging,
}: {
  items: AttentionFeedItem[];
  loading: boolean;
  onAcknowledge: () => void;
  acknowledging: boolean;
}) {
  return (
    <section>
      <div className="flex items-baseline justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-[var(--text-primary)]">
            Needs your attention
          </h2>
          <p className="text-sm text-[var(--text-secondary)] mt-0.5">
            New additions, moves of 3% or more, and 52-week highs or lows since you last checked.
          </p>
        </div>
        {items.length > 0 && (
          <button
            onClick={onAcknowledge}
            disabled={acknowledging}
            className="shrink-0 rounded-md border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-hover)] transition-colors disabled:opacity-50"
          >
            {acknowledging ? "Marking reviewed…" : "Mark all reviewed"}
          </button>
        )}
      </div>

      {loading ? (
        <div className="text-sm text-[var(--text-tertiary)] py-8 text-center border border-dashed border-[var(--border)] rounded-lg">
          Loading…
        </div>
      ) : items.length === 0 ? (
        <div className="py-10 text-center border border-dashed border-[var(--border)] rounded-lg">
          <p className="text-sm text-[var(--text-secondary)]">You&apos;re caught up.</p>
          <p className="text-xs text-[var(--text-tertiary)] mt-1">
            Nothing has moved meaningfully since your last visit.
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => {
            const pct = item.percent_change ? Number(item.percent_change) : null;
            const isGain = pct !== null && pct > 0;
            return (
              <li
                key={item.symbol}
                className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--bg-raised)] px-4 py-3"
              >
                <div className="flex items-center gap-3">
                  <span className="font-mono-tabular text-sm font-semibold text-[var(--text-primary)] w-16">
                    {item.symbol}
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    {item.is_new_addition && <ReasonBadge label="new" tone="signal" />}
                    {item.hit_52w_high && <ReasonBadge label="52w high" tone="gain" />}
                    {item.hit_52w_low && <ReasonBadge label="52w low" tone="loss" />}
                    {item.is_stale && <ReasonBadge label="stale data" tone="stale" />}
                  </div>
                </div>
                <div className="text-right font-mono-tabular">
                  <div className="text-sm text-[var(--text-primary)]">
                    ${formatPrice(item.current_price)}
                  </div>
                  {pct !== null && (
                    <div
                      className="text-xs"
                      style={{ color: isGain ? "var(--gain)" : "var(--loss)" }}
                    >
                      {formatPercent(item.percent_change)}
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
