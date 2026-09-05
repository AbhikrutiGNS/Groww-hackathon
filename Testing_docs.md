# Testing, Linting & Deploy-Readiness Notes

This covers what was added on top of the existing app: unit/integration
tests, linters for both the backend and frontend, a pinned `requirements.txt`
for the backend, and a bug fix in `frontend/src/app/page.tsx` that the new
linter caught.

All file paths below are relative to the repo root
(`Groww-hackathon_v7_ui_done_needs_testing/`).

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

## Running everything

**Backend** (from repo root):
```bash
pip install -r requirements-dev.txt
pytest          # 35 tests
ruff check .    # unused imports / import order only — see note below
```

**Frontend** (from `frontend/`):
```bash
npm install
npm test        # 34 tests (vitest)
npm run lint    # eslint via next's flat config
```

## Design notes / things worth knowing

- **No real Postgres in these tests.** `test_app_integration.py` patches out
  the background ingestion loops (which need a live DB) before the app's
  lifespan starts, then drives the real app object through `TestClient` —
  covering CORS, routing, and auth short-circuiting for real.
  `test_auth_router.py` swaps `get_db` for a small in-memory fake session
  that implements just enough of `AsyncSession` (`execute`/`add`/`commit`/
  `rollback`/`refresh`) to exercise the actual signup/login HTTP contract
  end-to-end, including the duplicate-email and wrong-password paths.
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
