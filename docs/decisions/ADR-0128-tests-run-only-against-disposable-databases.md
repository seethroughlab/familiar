# ADR-0128: Tests Run Only Against Disposable Databases

Status: accepted

Date: 2026-09-17

Implementation:
- **Accepted 2026-09-17**, the day it was proposed, as written; built the same day.
- **Built 2026-09-17.** `backend/conftest.py` (rootdir, loaded before `tests/conftest.py` imports
  `app.config`) calls `tests/disposable_database.install`, which reads `TEST_DATABASE_URL` only,
  requires a database name ending in `_test`, and installs it as `DATABASE_URL` for the process
  — the application and alembic read that until ADR-0130's factory. A missing or wrongly named
  URL is a `pytest.UsageError` before collection, with the instructions. Four unit tests, no
  database. `scripts/ensure_test_database.py` creates the database from a maintenance
  connection if it is missing and runs `alembic upgrade head`; `make test` and
  `make test-contract` run it first, with `TEST_DATABASE_URL` defaulting to `familiar_test` on the
  compose stack's server. CI's three pytest jobs use a service database named `familiar_test`
  and pass `TEST_DATABASE_URL` to pytest (migrations and preflight still take `DATABASE_URL`,
  pointed at the same database); the E2E job runs the application, not the suite, and is
  unchanged. Point 7 (labelling pure tests) is not done: today every run needs the variable
  set, though pure tests do not connect and run fine against a name that does not exist.

## Context

The backend suite has two kinds of database user, and they currently share one configuration.
Application code and tests both read `settings.database_url`; its development default names the ordinary
`familiar` database (`app/config.py:26`). The `async_db` fixture (`tests/conftest.py:129`) then deletes
every row from the eighteen models in `_CLEANUP_TABLES` (`conftest.py:96`) — the library, analysis,
playlists, profiles, sessions and caches — before and after a test.

That cleanup is reasonable inside a disposable database. It is destructive when a developer runs the
documented `uv run pytest tests/ -x -q` command while their normal development database is configured.
Nothing in the fixture proves which case it is. The command looks read-only, the danger is not visible at
the call site, and a newcomer has no historical knowledge that would make them inspect `conftest.py`
before running it.

The session-scoped `TestClient` (`conftest.py:65`) carries the same risk through HTTP: tests that create,
edit or delete resources exercise the application against whatever database the imported app configured.
CI is safe because its environment happens to provide disposable services; that is a property of the CI
job, not an invariant enforced by the suite. CI's disposable database is itself named `familiar`
(`.github/workflows/ci.yml:335` and `:420`), indistinguishable by name from the one this record is
protecting.

## Decision

1. **Backend tests use `TEST_DATABASE_URL`, never `DATABASE_URL`.** There is no fallback from the test
   setting to the application setting. An absent test URL is an error with setup instructions, not a
   reason to try the development database.

2. **The suite proves the database is disposable before opening it.** The parsed database name must end
   in `_test`. There is no second marker and no command-line opt-out: CI renames its service database to
   `familiar_test`, and any other exceptional environment names its database honestly.

3. **The guard runs before application import and before cleanup.** A check after `app.main` is imported
   is too late: startup and session-scoped fixtures may already have connected. Test configuration is
   installed first, then the application is created. Until ADR-0130's `create_app(settings, …)` exists,
   `conftest.py` performs the check before its first `app` import; once it does, the suite constructs the
   application from test settings and the import-order dependency goes away.

4. **Local setup creates the test database mechanically.** One documented command provisions PostgreSQL
   and Redis, applies migrations to the test database and runs the suite. Re-running it is idempotent.
   Nobody is asked to edit a DSN by hand before every test run.

5. **Destructive fixtures remain destructive and become explicit.** They may truncate or delete for
   speed and isolation once points 1–3 prove the target. Hiding cleanup inside transactions is not a
   substitute for the guard because background jobs and additional connections do not share one test
   transaction.

6. **The safe path is the short path.** `make test` and the command in `CONTRIBUTING.md` use the isolated
   environment. Running raw `pytest` either uses that same configuration or stops before collection with
   the same useful message.

7. **Tests that do not need services are labelled and remain runnable without them.** Pure unit tests
   must not import the assembled application merely to reach a function. Contract and integration suites
   may require PostgreSQL and Redis, and their names and commands say so.

## Alternatives Considered

**Keep the shared URL and document the danger.** Rejected. The destructive action is automatic, so its
safety must be automatic too. A warning in a guide does not protect a developer who runs the conventional
test command.

**Accept any database when `CI=true`.** Rejected. It makes CI configuration a bypass rather than evidence.
A mistaken CI secret could then point at a persistent database and receive more trust, not less.

**Use SQLite for tests.** Rejected. Familiar depends on PostgreSQL behavior, pgvector, constraints and
query semantics. A safer test target should not become a less representative one.

**Wrap every test in one transaction and roll it back.** Useful for speed where possible, but rejected as
the safety boundary. The application, workers and tests use multiple connections and processes; rollback
cannot recover writes made outside the fixture's transaction.

## Consequences

- **Positive:** the ordinary test command cannot erase a developer's library.
- **Positive:** local, CI and future contributor environments exercise one named setup rather than three
  conventions.
- **Positive:** pure tests become easier to identify and faster to run.
- **Tradeoff:** local setup needs a second database and a small amount of orchestration.
- **Tradeoff:** importing the fully assembled app in unit tests becomes a visible smell and some tests may
  need narrower imports.
- **Follow-up:** backup/restore and migration tests need their own disposable-database rules because their
  intended behavior is broader than table cleanup.
- **Follow-up:** point 4's command and ADR-0127's `make doctor` / `make check` assume a `Makefile` that
  does not exist yet. Where the three targets live is one decision, taken once, not two records each
  assuming the other will create it.
