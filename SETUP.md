# Setup Guide

Instructions to run Smart Market Watchlist locally. For what the app does,
see [README.md](./README.md); for how it's built, see
[IMPLEMENTATION.md](./IMPLEMENTATION.md).

## Prerequisites

- **Python 3.12** (the pinned `requirements.txt` was built and verified
  against 3.12; 3.11+ should also work)
- **Node.js 20+** and npm (for the Next.js 16 / React 19 frontend)
- **A PostgreSQL database.** This was built and tested against
  [Supabase](https://supabase.com/) Postgres, but any Postgres 14+
  instance works — see the connection-string notes below if you're not
  using Supabase.

## 1. Clone and configure environment variables

```bash
git clone <this-repo-url>
cd Groww-hackathon
cp .env.example .env
```

Edit `.env`:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | App's runtime DB connection. Must use the `postgresql+asyncpg://` prefix — the app refuses to start otherwise. |
| `USE_PGBOUNCER` | Set `true` if `DATABASE_URL` points at a transaction-mode PgBouncer pooler (e.g. Supabase's port-6543 pooler). This disables asyncpg's prepared-statement cache, which otherwise breaks with intermittent "prepared statement does not exist" errors under a transaction-mode pooler. Set `false` for a direct connection. |
| `ALEMBIC_DATABASE_URL` | Connection Alembic uses to run migrations. **Must be a session-mode / direct connection, not a transaction-mode pooler** — transaction mode doesn't reliably support the DDL and advisory locks Alembic needs. Falls back to `DATABASE_URL` if unset. |
| `CORS_ALLOWED_ORIGINS` | Comma-separated list of allowed frontend origins. Defaults to `http://localhost:3000`. |
| `INGESTION_INTERVAL_SECONDS` | How often the price ingestion loop runs. Default `60`. |
| `FUNDAMENTALS_INTERVAL_SECONDS` | How often the fundamentals loop runs. Default `21600` (6h). Not in `.env.example` by default — add it if you want to override. |
| `JWT_SECRET_KEY` | **Set this to a real random secret.** The code falls back to an insecure hardcoded value if unset, which is fine for a quick local test but must never be used in anything reachable outside your machine. |
| `JWT_EXPIRE_MINUTES` | Token lifetime in minutes. Default `10080` (7 days) if unset. |
| `SQL_ECHO` | Set `true` to log all SQL statements — useful for debugging, noisy otherwise. |
| `DEMO_MODE` | Uncomment to enable the two `/watchlist/demo/*` endpoints for presenting without live market movement. If you enable it, also bump `INGESTION_INTERVAL_SECONDS` up (e.g. to `3600`) so the real ingestion loop isn't fighting your simulated prices — dotenv takes the *last* value it sees for a duplicate key in the same file, so leaving both set works, but it's clearer to comment one out. |
| `NEXT_PUBLIC_API_URL` | Frontend's base URL for the backend API. Default `http://localhost:8000`. |

### If you're not using Supabase
Just point `DATABASE_URL` and `ALEMBIC_DATABASE_URL` at the same regular
Postgres connection string (no pooler distinction needed) and set
`USE_PGBOUNCER=false`.

### If you are using Supabase
- `DATABASE_URL` → the **Transaction pooler** connection string (port
  `6543`), with `USE_PGBOUNCER=true`.
- `ALEMBIC_DATABASE_URL` → the **Session pooler** connection string (port
  `5432`), **not** the direct `db.<ref>.supabase.co` host — that host is
  IPv6-only in most regions and will fail to resolve
  (`getaddrinfo failed`) on an IPv4-only network. The session-mode pooler
  host resolves over IPv4 and supports the advisory lock Alembic needs.

## 2. Backend setup

From the repo root:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements-dev.txt   # runtime deps + pytest/ruff
# (use `pip install -r requirements.txt` instead if you don't need tests/linting)
```

Run database migrations:

```bash
alembic upgrade head
```

This creates `users`, `tickers`, `watchlist_items`, `stock_snapshots`,
`company_fundamentals`, `holding_transactions`, and `notification_history`.

Start the API:

```bash
uvicorn app.main:app --reload
```

The app starts on `http://localhost:8000` and immediately begins two
background loops: price ingestion (every `INGESTION_INTERVAL_SECONDS`)
and fundamentals ingestion (every `FUNDAMENTALS_INTERVAL_SECONDS`). Check
it's alive:

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

### Optional: backfill real historical prices

New tickers start with zero price history, so SMA(50)/EMA(50)/trend
signals need ~50 trading days of live ingestion (or ~70 calendar days) to
populate naturally. To get real numbers immediately instead of waiting:

```bash
python -m app.scripts.backfill_history AAPL MSFT TSLA   # specific symbols
python -m app.scripts.backfill_history                  # every symbol already in `tickers`
```

This pulls ~90 days of real daily OHLC from yfinance and works even
while markets are closed. Safe to re-run (it only ever adds rows).

## 3. Frontend setup

In a separate terminal, from the repo root:

```bash
cd frontend
npm install
npm run dev
```

The app runs on `http://localhost:3000` and expects the backend at
`NEXT_PUBLIC_API_URL` (default `http://localhost:8000`) — make sure that
matches wherever `uvicorn` is actually listening, and that the backend's
`CORS_ALLOWED_ORIGINS` includes `http://localhost:3000`.

## 4. Using the app

1. Open `http://localhost:3000`, sign up with an email + password
   (min 8 characters).
2. Add a ticker by symbol (e.g. `AAPL`, `MSFT`, `RELIANCE.NS`) — it's
   resolved against Yahoo Finance and added to your watchlist.
3. Fundamentals populate on-demand as soon as a ticker is added; price
   history populates on the next ingestion cycle (or immediately if you
   ran the backfill script above).
4. The Attention Feed only shows something once there's a real baseline
   to compare against — acknowledge it once to set your first baseline,
   then check back after a price move or the next day.

### Faster iteration in demo mode

If you don't want to wait on real market movement while presenting:

```bash
# in .env
DEMO_MODE=1
INGESTION_INTERVAL_SECONDS=3600
```

Restart the backend, then:

```bash
curl -X POST http://localhost:8000/watchlist/demo/simulate-move \
  -H "Authorization: Bearer <your JWT>" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "AAPL", "percent_change": 5.0}'
```

## 5. Running tests and linters

**Backend:**
```bash
pytest              # unit + integration tests, no live DB required
ruff check .        # unused imports / import order
```

**Frontend:**
```bash
cd frontend
npm test            # vitest
npm run lint        # eslint via next's flat config
```

See [TESTING_NOTES.md](./TESTING_NOTES.md) for what each test file covers
and the reasoning behind the linter scope.

## Troubleshooting

- **App refuses to start: `DATABASE_URL is not set`** — `.env` wasn't
  copied/filled in, or you're running from a directory where
  `python-dotenv` can't find it (it loads from the current working
  directory).
- **`DATABASE_URL must use the postgresql+asyncpg:// driver prefix`** —
  the URL is missing `+asyncpg` after `postgresql`. This isn't optional;
  the app uses the async SQLAlchemy engine throughout.
- **Intermittent "prepared statement does not exist" errors** — you're
  pointed at a transaction-mode pooler without `USE_PGBOUNCER=true`.
- **Alembic hangs or fails with a lock/DDL error** — you're pointed at a
  transaction-mode pooler for `ALEMBIC_DATABASE_URL` instead of a
  session-mode/direct connection.
- **New ticker won't add / "doesn't look like a valid ticker symbol"** —
  Yahoo Finance may not cover that symbol (common for thinly-traded
  NSE/BSE tickers), or you hit a transient Yahoo rate limit — the add
  endpoint already retries a few times, so try again after a few seconds
  before assuming the symbol is bad. `DEMO_MODE`'s `seed-fundamentals`
  endpoint can be used as a workaround for demoing fundamentals on a
  symbol Yahoo doesn't cover well, once it's on a watchlist.
- **Frontend gets CORS errors** — check that `CORS_ALLOWED_ORIGINS` in
  the backend `.env` includes the exact origin the frontend is served
  from (protocol + host + port).
