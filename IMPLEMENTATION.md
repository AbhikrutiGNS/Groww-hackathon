# Implementation Notes

This document explains *how* the app is built and *why* it's built that
way — the design decisions behind the data model, ingestion, technicals,
and the Attention Feed. See [README.md](./README.md) for a feature-level
overview and [SETUP.md](./SETUP.md) to run it.

## Architecture at a glance

```
┌─────────────┐        HTTP/JSON (Bearer JWT)        ┌──────────────────┐
│  Next.js UI │ ───────────────────────────────────► │   FastAPI app    │
│  (frontend) │ ◄─────────────────────────────────── │   (app/main.py)  │
└─────────────┘                                      └────────┬─────────┘
                                                              │
                                       ┌──────────────────────┼───────────────────────────────┐
                                       │                      │                               │
                              background ingestion       routers (auth, watchlist)    services layer
                              loops (asyncio tasks,           │                      (technicals, market_data,
                              started in lifespan)            │                       fundamentals, ticker_registry)
                                       │                      │                              │
                                       └──────────────┬───────┴──────────────────────────────┘
                                                      ▼
                                            PostgreSQL (async, SQLAlchemy 2.0)
                                                       ▲
                                                       │
                                              Alembic migrations (source of truth for schema)
                                                       │
                                              yfinance (external market data)
```

The backend is a single FastAPI process. There's no separate worker/queue:
two `asyncio` background tasks (price ingestion, fundamentals ingestion)
are started in the app's `lifespan` context manager and run for the life
of the process, each on its own interval.

## Data model

Defined in `app/models.py`, versioned by Alembic in `alembic/versions/`.
The ORM models are documented as **not** the source of truth for schema —
migrations are — so the two must be kept in lockstep by hand.

| Table | Shape | Purpose |
|---|---|---|
| `users` | one row per account | email, bcrypt hash, `last_viewed_at` baseline for the Attention Feed |
| `tickers` | one row per instrument, shared across users | master data, lazily created on first `add` |
| `watchlist_items` | one row per (user, symbol) | soft-deletable (`is_active`/`removed_at`) so re-adding never conflicts with the unique constraint |
| `stock_snapshots` | append-only, high frequency | price/volume/day-range/52w-range time series, shared across all users tracking a symbol |
| `company_fundamentals` | one row per symbol, upserted | market cap, PE, PB, EPS, ROE, ROCE, D/E, dividend yield — overwritten each refresh, not append-only |
| `holding_transactions` | append-only ledger | BUY/SELL fills; a position is *derived* by replaying rows, never stored as a mutable running balance (moving-average cost basis, not FIFO/LIFO tax lots) |
| `notification_history` | append-only log | snapshot of what was "meaningful" each time the user acknowledged the Attention Feed; no FK on `symbol` so it survives the watchlist item (or even the ticker) it was about |

Key design choices:
- **Snapshots and fundamentals are shared per-symbol, never duplicated
  per-user.** Ten users tracking `AAPL` read the same rows.
- **Everything time-based is append-only** (`stock_snapshots`,
  `holding_transactions`, `notification_history`) rather than
  mutated-in-place, so history is always reconstructable.

## Authentication (`app/auth.py`, `app/routers/auth.py`)

- Signup/login issue a stateless JWT (`HS256`, `sub` = user id, default
  7-day expiry) signed with `JWT_SECRET_KEY`.
- Passwords are hashed with bcrypt. bcrypt silently truncates input at 72
  bytes, which can degrade to comparing only a password's prefix — this
  is guarded against explicitly by rejecting overlong passwords in
  `hash_password`/`verify_password` themselves (not just relying on the
  request schema's max length).
- Login returns an identical error for "no such user" and "wrong
  password" so the response can't be used to enumerate registered emails.
- `get_current_user_id` is a FastAPI dependency used on every protected
  route; on missing/invalid/expired token it raises 401. This replaced an
  earlier mock-auth stub that returned one hardcoded user id for every
  request with no verification at all.

## Ticker resolution (`app/services/ticker_registry.py`)

Adding a ticker isn't a plain `INSERT`. `ensure_ticker_exists()`:
1. Resolves the symbol against yfinance (with up to 3 retries — a
   never-before-fetched symbol fails transiently far more often than a
   warm one, and a couple of retries absorbs that without masking a
   genuinely invalid symbol).
2. Lazily creates the `tickers` master row on first sight via
   `ON CONFLICT DO NOTHING` (not check-then-insert, which races under
   concurrent requests).
3. Never commits itself — the caller (`POST /watchlist`) commits once,
   after its own dependent watchlist-item insert, in the same
   transaction. Either both rows land or neither does.

## Market data ingestion (`app/services/market_data.py`)

Two rules are load-bearing, not stylistic:

1. **Bounded concurrency on the network fetch.** Yahoo rate-limits/blocks
   cloud IPs under burst load, so an unbounded `asyncio.gather` across
   every tracked ticker is the fastest way to get the outbound IP banned.
   A semaphore caps concurrent `yfinance` calls (5 for price, 3 for the
   heavier fundamentals call), each run via `asyncio.to_thread` since
   `yfinance` is synchronous.
2. **`AsyncSession` is never touched concurrently.** All DB reads/writes
   happen sequentially, strictly *after* the concurrent network-fetch
   phase completes. The gathered coroutines only touch the network.

Fetching a quote also validates the payload, not just the call: `yfinance`
frequently returns successfully (no exception) for a halted, delisted, or
momentarily-unavailable ticker, but with `price` as `None` or `NaN`.
`_is_valid_price()` checks for both. There's also a `fast_info` →
`.history()` fallback, since `fast_info` is a lazy proxy that can itself
raise for reasons unrelated to connectivity (e.g. a known upstream
`yfinance` issue with missing chart metadata on some tickers).

Each ingestion cycle is wrapped in its own `try/except` so one bad cycle
(a Yahoo outage, a single bad ticker) can't silently kill all future
ingestion — it logs and retries on the next interval.

## Fundamentals ingestion (`app/services/fundamentals.py`)

Deliberately a separate loop and separate table from price:
fundamentals change quarterly-ish, not every 60 seconds, so polling them
at price cadence would be wasted `yfinance` load. `company_fundamentals`
is upserted (one row per symbol, overwritten each refresh) rather than
appended like `stock_snapshots`. Values are converted from `yfinance`'s
plain floats to the DB's fixed-precision `Numeric` columns defensively:
anything that can't be represented (including `NaN`) is dropped to `NULL`
rather than failing the whole upsert — a missing metric is a normal,
expected state here, a crash on insert is not.

## Technicals — computed on read (`app/services/technicals.py`)

Nothing here is a new data source or a new migration; it's all derived
from `stock_snapshots` that ingestion already writes. Two choices worth
calling out:

1. **SMA/EMA use one price per calendar day, not raw snapshot rows.**
   Snapshots land every `INGESTION_INTERVAL_SECONDS` (default 60s), so
   averaging raw rows over a date range would overweight days with more
   market-open minutes or more successful fetches. Instead, the last
   snapshot of each day is taken as a "close" proxy
   (`DISTINCT ON (captured_at::date) ... ORDER BY captured_at DESC`), and
   SMA/EMA are computed across those daily closes.
2. **A 120-day lookback window**, not 60. Trading days are ~5/7 of
   calendar days before holidays are even counted, and SMA-50 needs 50
   trading days (51 for crossover detection) — 60 calendar days only
   ever yields ~43 trading days, which made `sma_50` (and therefore any
   trend signal, which needs both `sma_20` and `sma_50`) permanently
   null regardless of how much real history existed.

**Golden/death cross detection** is a *change* in ordering, not a static
"20-day average is above the 50-day average today" (which is true on
most days and isn't news). `_detect_cross()` compares today's
SMA20-vs-SMA50 relationship against the same comparison with the most
recent close dropped — only the day the ordering actually flips counts.

`get_technicals()` also returns `history_days` (how many daily closes are
available) so the frontend can show real progress toward the 50-day
requirement (e.g. "23/50 days") instead of a static "still building..."
message that looks identical on day 1 and day 49.

## The Attention Feed (`app/routers/watchlist.py`)

This is the most deliberately-designed part of the backend. The goal:
show a user what changed *since they last looked*, without ever
fabricating a comparison point.

- `users.last_viewed_at` is the baseline. It's `NULL` until the user
  explicitly acknowledges the feed at least once.
- The feed query uses two `LEFT JOIN LATERAL`s per watchlist item in a
  single SQL statement (no N+1): one for the latest snapshot, one for a
  real snapshot at-or-before `last_viewed_at`, if one exists.
- **What this deliberately does *not* do:**
  ```sql
  COALESCE(last_viewed_at, added_at - interval '24 hours')
  ```
  A fabricated fallback like this can point at a timestamp with no real
  market data behind it (a weekend, a holiday, or a ticker nobody on the
  platform has ever tracked before). Showing "+3.2% since you last
  checked" against a comparison point that never happened is treated as
  a worse failure than plainly saying "just added — building history."
  If there's no real baseline, the API returns `is_new_addition=true`
  with `percent_change=null` — an honest state, not a guessed one.
- **A brand-new ticker's degenerate range is filtered out.** With only
  one snapshot ever, `week_high == week_low == that one price`, which
  trivially satisfies *both* "hit the week high" and "hit the week low"
  at once. `hit_week_high`/`hit_week_low` require a genuinely
  non-degenerate range before either flag can fire.
- **"Meaningful"** (the bar for appearing in the feed) is: new addition,
  OR `|percent_change| >= 3`, OR a genuine 52-week/1-week high or low,
  OR a golden/death cross.
- `POST /watchlist/acknowledge` is a distinct, explicit action — never
  called on every `GET` of the feed. It snapshots whatever's currently
  meaningful into `notification_history` (against the *old* baseline,
  before it moves — otherwise everything would already read as "no
  change" against itself), then advances `last_viewed_at`. The frontend
  calls this on an explicit "mark as reviewed" action, not on page load.
- `_compute_attention_feed()` is shared by the `GET` endpoint and the
  `acknowledge` endpoint specifically so the two can never drift apart on
  what counts as "meaningful."

## Add-or-reactivate as an atomic upsert

`POST /watchlist` is never a plain `INSERT`. The unique constraint on
`(user_id, symbol)` would reject re-adding a soft-deleted ticker, and a
check-then-insert pattern is a race condition under concurrent requests.
Instead it's a single `INSERT ... ON CONFLICT DO UPDATE` that flips
`is_active` back on, clears `removed_at`, and refreshes `notes` — so
add and reactivate are the same code path.

## Demo mode

`DEMO_MODE=1` unlocks two endpoints, both 404 otherwise:
- `POST /watchlist/demo/simulate-move` — inserts a synthetic snapshot at
  a chosen percent change off the latest real price, so the Attention
  Feed has something to show without waiting on real market movement.
- `POST /watchlist/demo/seed-fundamentals` — manually sets fundamentals
  for a symbol, useful for thinly-traded NSE/BSE tickers Yahoo doesn't
  cover well, or when running without network access to Yahoo at all.

Both are gated with `include_in_schema=os.getenv("DEMO_MODE") == "1"`
*and* a runtime check inside the handler, so they can't be hit even if
someone discovers the path by guessing while `DEMO_MODE` is unset.

## Frontend

- **`src/lib/api.ts`** — a thin fetch wrapper that attaches the JWT
  Bearer header, and centralizes 401 handling: on any 401 it clears the
  stored token and redirects to `/login`, so no individual page has to
  handle that case itself.
- **`src/lib/auth.ts`** — token storage.
- **`src/lib/format.ts`** — shared formatting for price, percent,
  market cap, ratios, and relative time ("time ago").
- **`src/app/page.tsx`** — the main dashboard: resolves the current user
  first (`GET /auth/me`), then loads watchlist + attention feed, and
  polls both every 30 seconds. A failed background poll sets a
  non-fatal `connectionIssue` flag rather than throwing — the
  last-known-good data stays on screen instead of the UI crashing or
  flashing back to a loading state.
- **`src/components/Glossary.tsx`** — a single `GLOSSARY` record is the
  source of truth for every fundamentals/technicals term, consumed both
  by inline "?" tooltips and the consolidated glossary panel, so the two
  can't drift out of sync.
- **`src/components/AttentionFeed.tsx` / `WatchlistTable.tsx` /
  `AddTickerForm.tsx` / `Authform.tsx`** — presentational components
  consuming the typed API client.

## Testing

- **Backend** (`tests/`, pytest + pytest-asyncio + httpx): unit tests for
  SMA/EMA/crossover math and bcrypt/JWT auth, plus integration tests that
  drive the real FastAPI app through `TestClient` — with background
  ingestion loops patched out (they need a live DB) before the app's
  lifespan starts — and a signup/login integration test against a small
  in-memory fake `AsyncSession` that implements just enough of the real
  interface (`execute`/`add`/`commit`/`rollback`/`refresh`) to exercise
  the actual HTTP contract end-to-end, including duplicate-email and
  wrong-password paths.
- **Frontend** (`frontend/src/lib/__tests__/`, Vitest + jsdom): unit
  tests for formatting helpers and the token storage wrapper, plus an
  integration test for the request layer (auth headers, 401 redirect
  flow).
- See [TESTING_NOTES.md](./TESTING_NOTES.md) for exact commands and
  scope notes on the linters (`ruff`, ESLint).
