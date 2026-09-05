# Smart Market Watchlist

A full-stack stock watchlist app: track any real ticker (via Yahoo Finance),
get an "Attention Feed" that surfaces only what actually changed since you
last checked, and see fundamentals + technicals (SMA/EMA, golden/death
cross, 52-week and 1-week range) alongside live price.

FastAPI + PostgreSQL backend, Next.js + React frontend.

For a deep dive into how each piece is built, see **[IMPLEMENTATION.md](./IMPLEMENTATION.md)**.
To get it running locally, see **[SETUP.md](./SETUP.md)**.
Notes on the test suite and linters added on top of the app live in
**[TESTING_NOTES.md](./TESTING_NOTES.md)**.

---

## Features

### Authentication
- Email/password signup and login.
- Passwords hashed with bcrypt; sessions are stateless JWTs (Bearer tokens).
- `/auth/me` for resolving the current user; a 401 on any protected route
  clears the token and bounces the frontend to `/login`.

### Watchlist
- Add any real ticker by symbol — it's resolved against Yahoo Finance on
  first sight and its master record (`tickers`) is created automatically,
  so the app isn't limited to a hand-seeded list.
- Remove a ticker (soft delete) and re-add it later without hitting a
  uniqueness conflict — add/re-add is a single atomic upsert.
- Per-user notes on each tracked ticker.
- Full list view shows live price, day range, 52-week range, and
  fundamentals/technicals for every tracked symbol at once.

### Attention Feed
- A separate view that only shows tickers with something *meaningful* to
  report: a ≥3% move since you last checked, a new 52-week or 1-week
  high/low, a golden/death cross, or a ticker that's brand new to your
  watchlist.
- "Since you last checked" is measured against an explicit baseline
  (`last_viewed_at`), advanced only when you explicitly acknowledge the
  feed — never silently on page load.
- No baseline yet (first-time user, or a ticker with no price history)
  is treated as an honest "just added — building history" state rather
  than a fabricated comparison.
- Last 5 acknowledged notifications remain viewable afterward, so the
  feed going quiet doesn't erase what you just reviewed.

### Fundamentals
Market cap, P/E, P/B, EPS, ROE, ROCE, debt/equity, dividend yield —
refreshed periodically in the background (default every 6 hours) plus a
best-effort on-demand fetch the moment a ticker is added.

### Technicals
Computed on read from stored price history, not stored themselves:
- 1-week and 52-week high/low
- SMA(20) / SMA(50)
- EMA(20) / EMA(50)
- Golden cross / death cross detection (an actual crossover event, not
  just "20 > 50 today")
- Trading-day history counter, so the UI can show real progress (e.g.
  "23/50 days") instead of a static "still building" message

### Frontend UX details
- In-app glossary with hover/focus tooltips on every fundamentals/technicals
  term (Market Cap, P/E, ROE, SMA, EMA, etc.), backed by a single shared
  glossary object so tooltips and the glossary panel can't drift out of sync.
- Background polling (every 30s) keeps price/feed data fresh without a
  full page reload, with a non-intrusive "still trying to reconnect"
  indicator if the backend is briefly unreachable — last-known-good data
  stays on screen the whole time.
- Demo mode: two gated endpoints (`/watchlist/demo/simulate-move` and
  `/watchlist/demo/seed-fundamentals`) let you simulate a price move or
  seed fundamentals for a symbol, for presenting the Attention Feed and
  dashboard without waiting on a real market move or a Yahoo-covered
  ticker. Both 404 unless `DEMO_MODE=1` is set.

---

## Tech Stack

**Backend**
- [FastAPI](https://fastapi.tiangolo.com/) (Python, async)
- [SQLAlchemy 2.0](https://www.sqlalchemy.org/) (async ORM) + [asyncpg](https://github.com/MagicStack/asyncpg)
- [PostgreSQL](https://www.postgresql.org/) (tested against Supabase Postgres)
- [Alembic](https://alembic.sqlalchemy.org/) for schema migrations
- [yfinance](https://github.com/ranaroussi/yfinance) for live price and fundamentals data
- [python-jose](https://python-jose.readthedocs.io/) for JWTs, [bcrypt](https://pypi.org/project/bcrypt/) for password hashing
- [Pydantic v2](https://docs.pydantic.dev/) for request/response validation
- [pytest](https://docs.pytest.org/) + [pytest-asyncio](https://pytest-asyncio.readthedocs.io/) + [httpx](https://www.python-httpx.org/) for testing, [ruff](https://docs.astral.sh/ruff/) for linting

**Frontend**
- [Next.js 16](https://nextjs.org/) (App Router) + [React 19](https://react.dev/)
- [TypeScript](https://www.typescriptlang.org/)
- [Tailwind CSS 4](https://tailwindcss.com/)
- [Vitest](https://vitest.dev/) + jsdom for testing
- [ESLint](https://eslint.org/) (`eslint-config-next`) for linting

**Infra / other**
- Background ingestion loops (price every 60s by default, fundamentals every
  6h by default) run inside the FastAPI process lifespan — no separate
  worker/queue needed at this scale.
- CORS is configured via an env var allow-list.

---

## Project Structure

```
app/
  main.py                    # FastAPI app, CORS, background ingestion loops
  auth.py                    # bcrypt hashing + JWT issuance/verification
  models.py                  # SQLAlchemy ORM models
  db.py                      # engine/session setup
  routers/
    auth.py                  # /auth/signup, /auth/login, /auth/me
    watchlist.py             # /watchlist/* — add, list, remove, attention-feed, acknowledge, demo routes
  services/
    market_data.py           # price ingestion from yfinance
    fundamentals.py          # fundamentals ingestion from yfinance
    ticker_registry.py       # resolves + lazily registers new tickers
    technicals.py            # SMA/EMA/crossover/range computed on read
  scripts/
    backfill_history.py      # one-off backfill utility

alembic/versions/            # schema migrations (initial, holdings, notifications)
tests/                       # pytest unit + integration tests

frontend/
  src/app/                   # Next.js pages (/, /login, /signup)
  src/components/            # WatchlistTable, AttentionFeed, AddTickerForm, Authform, Glossary
  src/lib/                   # api client, auth token storage, formatting helpers
  src/lib/__tests__/         # vitest unit/integration tests
```

---

## Quick Start

See **[SETUP.md](./SETUP.md)** for full instructions. In short:

```bash
# Backend
pip install -r requirements-dev.txt
cp .env.example .env   # fill in your DB + JWT secret
alembic upgrade head
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```
