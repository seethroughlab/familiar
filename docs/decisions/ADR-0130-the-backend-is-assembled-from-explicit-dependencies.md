# ADR-0130: The Backend Is Assembled from Explicit Dependencies

Status: accepted

Date: 2026-09-17

## Context

Familiar's route/service split is real, but construction is mostly implicit. Services for outputs,
metadata, video, maps, artwork, metrics, Redis, background work, community cache, S3, lyrics and settings
are held in module-global singletons and reached through ten `get_*_service()` functions. Configuration
is also split: most values belong to `Settings`, while `MUSIC_LIBRARY_PATH` reads `os.environ` at import
(`app/config.py:7`).

`app.main` performs process-wide work while it is imported: it configures multiprocessing (line 15),
constructs the FastAPI app (line 458) and MCP application (lines 471–475), registers middleware, and
imports the complete route surface. A test that
wants one route or pure helper can therefore acquire global resources and production configuration before
it has installed test dependencies.

The problem is not that every class lacks an interface. Most internal services have one implementation and
benefit from direct code. The problem is that boundaries with expensive resources, external systems or
mutable lifecycle are hidden, which makes replacement and isolation depend on monkeypatching module state.

## Decision

1. **The application has a factory.** `create_app(settings, services)` constructs FastAPI, MCP, middleware
   and routes. Importing a domain module does not assemble the running server.

2. **One typed application container owns long-lived resources.** Database engines, Redis, executors,
   HTTP clients, metrics and external-provider adapters are created during lifespan, exposed through
   dependencies and closed during lifespan shutdown.

3. **Routes receive application operations through FastAPI dependencies.** A route authenticates,
   validates, invokes one operation and serializes its declared result. It does not locate global services
   or construct infrastructure itself.

4. **Application operations coordinate a use case.** Examples are `StartLibrarySync`,
   `PreviewDuplicateTracks`, `RestoreBackup` and `RotateServerToken`. They define transaction and job
   boundaries and call domain services; they contain no HTTP response logic.

5. **Interfaces exist at volatile boundaries, not around every function.** Protocols are appropriate for
   object storage, job queues, settings persistence, metadata/discovery providers, community cache and
   other network services. SQLAlchemy queries that have no alternate implementation stay direct or in
   domain-specific query modules; there is no generic repository layer.

6. **All environment configuration enters through one immutable settings object.** Library paths, URLs,
   flags and resource limits are parsed and validated together. Modules do not read environment variables
   at import time.

7. **Background work receives a serializable command and resolves dependencies in the worker context.**
   It does not capture request sessions or process-local singleton state.

8. **Migration follows touched domains.** Existing singleton getters remain until a domain is moved, but
   new services do not add another module-global instance. A migration removes the old getter and its test
   reset hooks together.

9. **The route, operation and adapter boundaries are checked structurally.** Dependency rules prevent
   infrastructure adapters from importing routes and prevent domain/application modules from importing
   FastAPI response types.

## Alternatives Considered

**Keep globals and improve reset fixtures.** Rejected as the target. Resetting every singleton treats the
test symptom while keeping resource ownership implicit in production.

**Adopt a third-party dependency-injection framework.** Rejected initially. FastAPI dependencies plus a
typed container are sufficient; a second container would add concepts before it removed any.

**Create repositories for every model.** Rejected. Generic CRUD abstraction obscures SQLAlchemy without
creating a useful substitution boundary. Query modules and purpose-specific protocols are enough.

**Rewrite the backend into clean-architecture layers at once.** Rejected. Large moves would erase useful
history and create risk without changing behavior. This record defines the destination and a rule for new
work, not a flag-day project.

## Consequences

- **Positive:** tests can assemble the application with disposable dependencies and no module-state reset.
- **Positive:** resource startup, shutdown and ownership become visible in one place.
- **Positive:** external integrations can be exercised with small fakes rather than HTTP monkeypatches.
- **Tradeoff:** constructors and dependency functions become more explicit and sometimes longer.
- **Tradeoff:** two construction styles coexist during migration.
- **Tradeoff:** choosing operation boundaries requires judgement; mechanically adding one class per route
  would only rename the current structure.
- **Follow-up:** the first migration is Soulseek — `services/soulseek.py`, `services/background/soulseek.py`
  and `api/routes/soulseek.py` (ADR-0116/0117). It is bounded, it is the newest code with the fewest
  callers, and it exercises every boundary this record names at once: an HTTP client to slskd behind a
  protocol, a settings-gated presence, a background poller that must resolve its dependencies in the worker
  context, and a route surface that is withheld rather than failing when unconfigured. Library sync and
  analysis come last, so the pattern is proved before it reaches the largest services.
