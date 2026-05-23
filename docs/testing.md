# Testing Strategy

## Testing Approach

Agent GTD uses a layered testing approach:

1. **Backend unit tests** — pytest with in-memory SQLite. Tests cover HTTP endpoints (via
   `httpx.AsyncClient` + `ASGITransport`), service layer functions (direct calls, no HTTP), and
   pure utility functions. Property-based tests use `hypothesis` for inputs with mathematical
   invariants.

2. **Frontend unit tests** — vitest with `happy-dom`. Tests cover pure utility functions
   (`utils.ts`), custom hooks, and React components with mocked API calls.

3. **Pre-push hook enforcement** — the test suite (with coverage) must pass before any push.
   A failing push is a signal to investigate, not to bypass.

The guiding rule: **tests are written alongside the code they cover**, not added afterward.
New features require tests before merging. Bug fixes require a regression test that would have
caught the original bug.

## Test Environments

**Development (local):** Tests run against an in-memory SQLite database. No PostgreSQL
required. Run `uv run pytest` from the repo root.

**CI:** Tests run in the same in-memory SQLite environment. There is no separate staging
database for tests.

**Production:** Tests do not run against the production database. The production PostgreSQL
instance and the test SQLite instance are entirely separate.

## Test Data

The `conftest.py` fixtures provide the foundational test data for every test:

- **`_setup_db`** (autouse): Creates a fresh in-memory SQLite database for each test. Uses
  `SqlitePool` with `aiosqlite` and runs the full `init_db()` schema creation. Cleaned up
  (pool closed) after the test. This means every test starts with a clean slate.

- **`_clear_agent_name_env`** (autouse): Unsets `AGENT_GTD_AGENT_NAME` before each test so
  attribution tests start from a known state. Tests that need specific attribution call
  `monkeypatch.setenv("AGENT_GTD_AGENT_NAME", "claude-build-abc12345")`.

- **`client`**: An `httpx.AsyncClient` wired to the FastAPI app via `ASGITransport`. Makes
  in-process HTTP requests without a real network connection.

- **`auth_headers`**: Registers a test user, creates a JWT, and returns
  `{"Authorization": "Bearer <token>"}` for use in request headers.

- **`project_id`**: Creates a test project and returns its ID.

- **`user_id`**: Returns the test user's ID (from `GET /api/auth/me`).

Tests that need additional setup (e.g., a second user, a shared project) create those
resources inline using the `client` and `auth_headers` fixtures.

## Unit Tests

### Backend: HTTP endpoint tests

Most tests exercise the REST API through the `client` fixture. This approach tests the full
request-response cycle including auth, request parsing, service calls, and response
serialization — without the overhead of a real HTTP server.

```bash
# Run all backend tests
uv run pytest

# Run a specific test file
uv run pytest tests/test_items.py

# Run a specific test
uv run pytest tests/test_items.py::test_create_item

# Run with verbose output
uv run pytest -v
```

**Test file layout:** One file per resource or concern.

| File | What it covers |
|---|---|
| `test_auth.py` | Register, login, API keys, password change; hypothesis tests for password hashing and token roundtrip |
| `test_items.py` | Items CRUD, status filters, version locking |
| `test_projects.py` | Projects CRUD, status/area filters |
| `test_notes.py` | Notes CRUD, project scoping |
| `test_comments.py` | Comments on items and projects, attribution |
| `test_blockers.py` | Blocker relationships, cycle detection, same-project constraint |
| `test_services.py` | Direct service function calls (no HTTP) |
| `test_dispatch.py` | Run creation, dispatch settings |
| `test_rollout_service.py` | Rollout planning, legality contract, advance, complete-item |
| `test_mcp_tools.py` | MCP tool calls via the MCP backend |
| `test_sharing.py` | Project member add/remove, shared project access |
| `test_identity.py` | Attribution string computation |
| `test_events.py` | Event bus publish/subscribe, SSE replay |
| `test_smoke.py` | Health check, app startup |

### Backend: Service layer unit tests

`test_services.py` tests service functions directly (bypassing HTTP) for fast, focused
coverage of business logic. Import the service module, set up data via other service calls,
and assert the output:

```python
async def test_version_conflict(user_id, project_id):
    db = await get_db()
    item = await item_service.create_item(db, user_id, project_id=project_id, title="Test")
    # version=1 is current; pass version=0 to force a conflict
    with pytest.raises(VersionConflictError):
        await item_service.update_item(db, user_id, item["id"], version=0, title="Updated")
```

### Backend: Hypothesis property-based tests

`hypothesis` is used for inputs with mathematical invariants — values where correctness must
hold for any valid input, not just the few examples a developer thinks of.

Currently in `test_auth.py`:

```python
from hypothesis import given, settings
from hypothesis import strategies as st

@given(
    password=st.text(min_size=1, max_size=72).filter(lambda s: len(s.encode()) <= 72)
)
@settings(max_examples=10, deadline=None)
def test_hash_verify_any_password(password):
    """bcrypt hash/verify must round-trip for any valid password."""
    h = hash_password(password)
    assert verify_password(password, h)

@given(user_id=st.text(min_size=1, max_size=100))
@settings(max_examples=10)
def test_token_roundtrip_any_user_id(user_id):
    """JWT create/decode must round-trip for any user_id string."""
    token = create_token(user_id)
    assert decode_token(token) == user_id
```

**When to add hypothesis tests:**
- Encoding/decoding functions that must round-trip (password hash, JWT, JSON list encoding)
- Distance or ordering functions with mathematical properties
- Input validation that should hold for all values in a range
- Any pure function where "it works for these 3 examples" is insufficient confidence

Use `@settings(max_examples=10, deadline=None)` for slow operations (like bcrypt). Use the
default `max_examples=100` for fast pure functions.

### Frontend: vitest tests

Frontend tests use [vitest](https://vitest.dev/) with `happy-dom` as the DOM environment.
Tests live in `frontend/src/__tests__/`.

```bash
# Run frontend tests
npm --prefix frontend run test

# Run in watch mode (for development)
npm --prefix frontend run test -- --watch
```

**Test file layout:**

| File | What it covers |
|---|---|
| `utils.test.ts` | Pure utility functions (`utils.ts`) — key conversion, formatting |
| `blockers.test.ts` | Blocker utility functions |
| `statusChip.test.ts` | Status chip label/color mapping |
| `rolloutEventFeed.test.ts` | Rollout event feed utilities |
| `useDraftState.test.ts` | `useDraftState` custom hook |
| `settings.test.tsx` | Settings page component |
| `RolloutBanner.test.tsx` | Rollout banner component |
| `Runs.test.tsx` | Runs component |

**Convention:** Every exported function in `utils.ts` must have a corresponding test. Every
new pure utility function added to any `utils.ts` file must be tested before merging.

```typescript
// Example: utils.test.ts
import { describe, it, expect } from 'vitest';
import { toSnakeCase, toCamelCase } from '../utils';

describe('toSnakeCase', () => {
    it('converts camelCase keys to snake_case', () => {
        expect(toSnakeCase({ firstName: 'Alice' })).toEqual({ first_name: 'Alice' });
    });
});
```

**vitest setup file:** `frontend/src/test-setup.ts` runs before all tests. Add global mocks
(e.g., `localStorage`, browser APIs) there.

## Test Automation

**Pre-commit hooks** run on every `git commit`:
- Ruff lint and format check (Python)
- mypy type check (Python)
- ESLint (TypeScript/React)
- tsc type check (TypeScript)
- Trailing whitespace removal
- gitleaks secrets scan

**Pre-push hook** runs on every `git push`:
- `uv run pytest --cov=agent_gtd` with coverage enforcement
- The push is blocked if coverage falls below `fail_under` in `pyproject.toml`

The pre-push hook uses `uv run --frozen` to prevent uv from rebuilding the package mid-hook,
which would cause a spurious "files were modified by a hook" failure.

## Coverage Ratchet

The coverage threshold is enforced via `[tool.coverage.report] fail_under` in `pyproject.toml`.
The current threshold is **96.6%**.

**Ratcheting up:** After adding tests that increase coverage, update `fail_under` to the new
floor so future regressions are caught:

1. Run `uv run pytest --cov=agent_gtd` and note the reported coverage percentage.
2. Edit `pyproject.toml`: increase `fail_under` to the new percentage (rounded down to one
   decimal place, e.g., 96.8%).
3. Commit both the tests and the updated threshold together.

Never leave `fail_under` below the current coverage — silently regressing coverage defeats
the purpose of the enforcement.

**Coverage omissions** (files excluded from coverage measurement):

```toml
[tool.coverage.run]
omit = [
    "src/agent_gtd/dispatch_worker.py",  # tested via integration; hard to unit-test polling loops
    "src/agent_gtd/mcp_server.py",       # tested via mcp_backend; FastMCP internals omitted
    "src/agent_gtd/mcp_backend.py",      # HTTP transport wrapper; omitted
]
```

These files are covered by `test_dispatch_worker.py` and `test_mcp_tools.py` but are excluded
from the threshold calculation because they contain long-running background loops and
framework wrappers that are difficult to reach with unit tests.

## Manual Testing Procedures

After a feature is implemented and tests pass, verify it manually before merging:

1. **Start the dev servers:** `./start.sh`
2. **Open the web UI:** `http://localhost:5173`
3. **Exercise the feature in the UI** — create, edit, delete items; verify real-time SSE updates
   appear without page reload.
4. **Verify SSE:** Keep the browser tab open in the background for 2–3 minutes; it should not
   reload (no HMR WebSocket reconnect reloads in dev mode).
5. **Test MCP tools** (if applicable): Use the `agent-gtd-mcp` CLI or a connected Claude Code
   session to call the relevant MCP tools and verify results match the REST API.
6. **Check the health endpoint:** `curl http://localhost:8000/api/health` → `{"status": "ok"}`

## Validation Criteria

A feature is ready to merge when:
- All backend tests pass: `uv run pytest`
- All frontend tests pass: `npm --prefix frontend run test`
- mypy reports no errors: `uv run mypy src/`
- ruff reports no errors: `uv run ruff check .`
- Coverage has not dropped below `fail_under` (pre-push hook enforces this)
- If coverage increased, `fail_under` in `pyproject.toml` has been ratcheted up

## Bug Reporting

When a bug is found:
1. Create a GTD item in the relevant project with `priority=high` and `status=next_action`.
2. Include in the description: steps to reproduce, expected behaviour, actual behaviour,
   and any relevant log output.
3. Write a failing test that reproduces the bug before fixing it. The test should be the
   first commit on the fix branch.

## Regression Testing

Every bug fix must include a regression test. The test should fail on the unfixed code and
pass after the fix. This is enforced by convention, not tooling.

For hypothesis tests: when a property violation is discovered, add the failing example as a
`@example` decorator so it is always tested, even if hypothesis does not rediscover it in
future runs.

## Pointers

> `docs/setup.md` — how to install dependencies and get the test environment running.
> `docs/codebase.md` — testing patterns and where tests live in the project structure.
> `docs/architecture.md` — how the in-memory SQLite pool (`SqlitePool`) replaces asyncpg in tests.
