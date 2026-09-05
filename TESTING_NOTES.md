# Testing, Linting & Deploy-Readiness Notes

This covers what was added on top of the existing app: unit/integration
tests, linters for both the backend and frontend, a pinned `requirements.txt`
for the backend, and a bug fix in `frontend/src/app/page.tsx` that the new
linter caught.

For what the app does and how it's built, see [README.md](./README.md)
and [IMPLEMENTATION.md](./IMPLEMENTATION.md). For local setup, see
[SETUP.md](./SETUP.md).

All file paths below are relative to the repo root.

## What's new

```
requirements.txt              # pinned backend runtime deps (didn't exist before)
requirements-dev.txt          # + pytest, pytest-asyncio, httpx, ruff
pyproject.toml                # pytest + ruff config
tests/
  conftest.py
  test_technicals.py          # unit: SMA/EMA/golden-death-cross math
  test_auth.py                # unit: bcrypt hashing + JWT issuance/validation
  test_app_integration.py     # integration: real FastAPI app via TestClient
  test_auth_router.py         # integration: /auth/signup, /auth/login over HTTP

frontend/
  package.json                # + vitest, jsdom, eslint, eslint-config-next; test/lint scripts
  package-lock.json
  vitest.config.ts
  eslint.config.mjs
  src/lib/__tests__/
    format.test.ts            # unit: price/percent/market-cap/ratio formatting, timeAgo
    auth.test.ts               # unit: localStorage token wrapper
    api.test.ts                # integration: request layer, auth headers, 401 flow
  src/app/page.tsx             # FIXED — see below
```

## Running everything

**Backend** (from repo root):
```bash
pip install -r requirements-dev.txt
pytest          # 35 tests
ruff check .    # unused imports / import order only — see note below
```

No live Postgres is required for any of this — see "No real Postgres in
these tests" below for how that's achieved.

**Frontend** (from `frontend/`):
```bash
npm install
npm test        # 34 tests (vitest)
npm run lint    # eslint via next's flat config
```

### Running a subset

```bash
# Backend — one file, one class, or one test by name
pytest tests/test_technicals.py
pytest tests/test_auth.py::TestPasswordHashing
pytest tests/test_auth_router.py::TestLogin::test_login_rejects_wrong_password
pytest -k "cross"          # any test with "cross" in its name, across files
pytest -v                  # verbose, one line per test

# Frontend — same idea via vitest
npm test -- format.test.ts
npm test -- -t "formats trillions"
npm test -- --watch        # re-run on file change
```

## Test breakdown

35 backend tests across 4 files, split into pure unit tests (no DB, no
HTTP, no event loop dependencies beyond `pytest-asyncio`) and integration
tests (real FastAPI app driven over HTTP via `TestClient`). Frontend
mirrors the same split: pure unit tests for formatting/storage helpers,
plus one integration-style suite for the API request layer.

### Backend unit tests

**`tests/test_technicals.py`** (11 tests) — pure math, no DB or event
loop: feeds plain lists of `Decimal` closes straight into
`_sma`/`_ema`/`_detect_cross` and checks the numbers.
- `TestSma` (4): not-enough-data → `None`, empty list → `None`, only the
  last N values are averaged (not the whole list), exact-length window.
- `TestEma` (3): not-enough-data → `None`, EMA equals SMA when the input
  is exactly one window long (no smoothing yet to apply), and a concrete
  worked example for the smoothing formula past the seed window.
- `TestDetectCross` (4): fewer than 51 points → `None`; a monotonically
  rising series never triggers a cross (SMA20 stays above SMA50 the
  whole time — ordering never *flips*, so no event fires even though
  SMA20 > SMA50 is true throughout); a golden cross engineered to flip
  exactly on the latest point; the same for a death cross.

**`tests/test_auth.py`** (12 tests) — pure crypto/token logic, no DB or
HTTP: calls `hash_password`/`verify_password`/`create_access_token`/
`get_current_user_id` directly with hand-built inputs.
- `TestPasswordHashing` (6): hash→verify round-trips; wrong password is
  rejected; passwords over bcrypt's 72-byte limit raise `ValueError`
  instead of silently truncating; exactly 72 bytes is accepted; verifying
  an overlong password returns `False` rather than raising; two hashes
  of the same password differ (confirms bcrypt is salting per-call).
- `TestAccessTokens` (6): a token's `sub` claim matches the user id it
  was issued for; a valid token resolves to the right user id; missing
  credentials, a garbage/unparseable token, an expired token, and a
  well-formed token with no `sub` claim all raise `401` — not a 500 or
  an unhandled exception.

### Backend integration tests

**`tests/test_app_integration.py`** (5 tests) — the real `app.main.app`
object driven through `TestClient`, with the two background ingestion
coroutines monkey-patched to no-ops before the lifespan starts (see
"No real Postgres" below).
- `/health` returns `200 {"status": "ok"}`.
- CORS: a request from the configured frontend origin
  (`http://localhost:3000`) gets the matching
  `access-control-allow-origin` header back.
- A protected route (`GET /watchlist`) with no `Authorization` header
  returns `401` before any DB access is attempted.
- The same route with a well-formed-but-garbage bearer token also
  returns `401`.
- With `DEMO_MODE` unset, `/watchlist/demo/simulate-move` returns `404`
  even with a *valid* auth token — proving the route is gated by the
  feature flag, not by auth (auth passes; the feature flag hides the
  route from the schema and 404s the handler).

**`tests/test_auth_router.py`** (7 tests) — the real `/auth` router over
real HTTP, with `get_db` swapped via FastAPI's `dependency_overrides` for
an in-memory `FakeSession` (see below) instead of a real database.
- `TestSignup` (4): a successful signup returns `201`, a `bearer` token,
  and never echoes the password back in the response body; signing up
  with an email that's already taken returns `409`; a password under the
  8-character minimum is rejected by Pydantic validation with `422`;
  email is normalized to lowercase and trimmed before being stored
  (`"  Mixed.Case@Example.com  "` → `"mixed.case@example.com"`).
- `TestLogin` (3): correct credentials return `200` with an access
  token; a wrong password returns `401`; a login attempt for an email
  that was never registered returns the exact same `401` and message as
  a wrong password, so the endpoint can't be used to enumerate which
  emails are registered.

### Frontend unit tests

**`src/lib/__tests__/format.test.ts`** (23 tests) — pure functions, no
DOM interaction beyond what `Date`/`Intl` need.
- `formatPrice` (4): null/non-numeric → em dash; two-decimal formatting
  with thousands separators; whole numbers get `.00`.
- `formatPercent` (4): null → em dash; positive values get an explicit
  `+` prefix; negative values keep their own `-`; exactly zero gets no
  sign.
- `formatPlainPercent` (2): same rounding as `formatPercent` but never
  adds a `+` sign, even for positive values.
- `formatMarketCap` (6): null → em dash, and correct suffix/scaling at
  each magnitude — trillions, billions, millions, thousands, and plain
  dollars below a thousand.
- `formatRatio` (3): null → em dash; default `×` suffix; custom suffix
  override.
- `timeAgo` (4): "just now" under a minute; minutes under an hour; hours
  under a day; days at a day or more.

**`src/lib/__tests__/auth.test.ts`** (4 tests) — the `localStorage`
token wrapper (`getToken`/`setToken`/`clearToken`), with `localStorage`
cleared before each test: no token stored returns `null`; a stored token
round-trips; setting a second token overwrites the first; clearing
removes it.

### Frontend integration-style tests

**`src/lib/__tests__/api.test.ts`** (7 tests) — the shared `request()`
layer in `src/lib/api.ts`, with `fetch` mocked via `vi.fn()` and the
module re-imported fresh per test (`vi.resetModules()`) since it reads
`NEXT_PUBLIC_API_URL` at import time.
- An authenticated call (`api.listWatchlist()`) attaches
  `Authorization: Bearer <token>`.
- `api.login(...)` does **not** attach a stale bearer token to its own
  request.
- A successful login stores the token it receives back for later calls.
- A failed request surfaces the server's `detail` message as a typed
  `ApiError` (checked both for message content and `instanceof`).
- A `401` from a non-auth endpoint clears the stored token and redirects
  to `/login`.
- A `401` from the login endpoint itself does **not** clear an existing
  (unrelated) token — a failed *login attempt* isn't the same as an
  *existing session* expiring.
- A `204 No Content` response resolves to `undefined` without ever
  calling `.json()` on an empty body (which would throw).

## The bug fix in `page.tsx`

The new ESLint rule `react-hooks/set-state-in-effect` flagged this pattern:

```ts
useEffect(() => {
  if (!user) return;
  refresh().finally(() => setLoading(false));
  const interval = setInterval(refresh, POLL_MS);
  return () => clearInterval(interval);
}, [user, refresh]);
```

`setLoading(false)` was chained directly off a promise created in the effect
body, which is the exact pattern this rule targets (it can cause cascading
renders and is a known footgun in data-fetching effects). The fix:

1. `refresh` now takes an `isInitialLoad` flag and owns its own
   `setLoading(false)` call internally, so the state update lives inside a
   stable `useCallback` rather than a one-off `.finally()` chained in the
   effect. Poll ticks pass `isInitialLoad = false` and never touch `loading`
   again after the first successful/failed fetch — so polling can no longer
   flash the UI back to a loading skeleton.
2. The effect still calls `refresh(true)` directly (this is the standard
   "fetch on mount" pattern) — that residual call is still statically
   flagged because the linter can't distinguish an async, interval-driven
   update from a synchronous render-loop `setState`. That single line has a
   scoped `eslint-disable-next-line` with a comment explaining why, rather
   than restructuring a well-understood polling effect into something more
   convoluted just to satisfy the rule.

Verified: `npm run lint` now reports 0 errors in `page.tsx` (one pre-existing,
unrelated warning remains in `lib/api.ts` about `window.location.href` — not
touched, out of scope for this pass).

## `requirements.txt`

The repo had **no `requirements.txt` at all**. The pinned file was built by
installing exactly what `app/**/*.py` imports (fastapi, sqlalchemy\[asyncio],
asyncpg, python-dotenv, bcrypt, python-jose\[cryptography], pydantic\[email],
yfinance, alembic) into a clean Python 3.12 virtualenv, freezing the
resulting versions, and confirming `import app.main` succeeds against them.
A few security/behavior-relevant transitive packages (starlette,
pydantic-core, email-validator, cryptography, greenlet, Mako) are pinned
explicitly too, so a fresh install can't silently drift to an incompatible
major version.

`requirements-dev.txt` just layers `-r requirements.txt` plus
`pytest`/`pytest-asyncio`/`httpx`/`ruff`.

## Design notes / things worth knowing

- **No real Postgres in these tests.** `test_app_integration.py` patches out
  the background ingestion loops (which need a live DB) before the app's
  lifespan starts, then drives the real app object through `TestClient` —
  covering CORS, routing, and auth short-circuiting for real.
  `test_auth_router.py` swaps `get_db` for `FakeSession`, a small
  dataclass-based in-memory stand-in that implements just enough of the
  real `AsyncSession` interface (`execute`/`add`/`commit`/`rollback`/
  `refresh`) to exercise the actual signup/login HTTP contract
  end-to-end, including the duplicate-email and wrong-password paths —
  `execute()` inspects the compiled statement's bound parameter to find
  the email being looked up, and `commit()` enforces the same
  unique-email constraint Postgres would. `conftest.py` also sets
  `DATABASE_URL`/`JWT_SECRET_KEY`/`CORS_ALLOWED_ORIGINS` as environment
  defaults *before* any test module imports `app.*` — both `app/db.py`
  and `app/auth.py` read their config at import time, so this has to
  land ahead of collection, not inside a fixture.
- **Ruff is scoped narrowly on purpose** — `E`, `F`, `I` (real errors, unused
  imports/vars, import order), not `UP`/`B`/`SIM` pyupgrade-style rules. The
  broader rule set flagged 127 issues across the existing codebase (mostly
  `Optional[X]` vs `X | None` style preferences) that would mean rewriting
  files this task wasn't meant to touch. The narrow set currently reports 4
  minor, genuine findings (an unsorted import block, one unused import) —
  left as-is since fixing them means editing files outside this task's scope,
  but they're quick to `ruff check --fix` if you want them cleaned up.
- **ESLint caught one more thing already reported**: `lib/api.ts` uses
  `window.location.href` for the 401-redirect-to-login flow, which
  `@next/next/no-location-assign-relative-destination` flags as a warning
  (prefers `useRouter().push()`/`redirect()`). Left untouched since it's a
  warning, not an error, and outside this pass's fix.
