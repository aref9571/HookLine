# 0002: Synchronous FastAPI routes and synchronous SQLAlchemy

Status: accepted

## Context

FastAPI supports both `async def` and plain `def` route functions, and SQLAlchemy 2 offers both a synchronous `Session` and an asyncio extension. Hookline needs a database layer for the API and for the worker, and the code must be easy to read, test and explain.

Most of the work in a Hookline request is a few short database queries. The part of the system where concurrency really matters is the worker, which claims deliveries from a PostgreSQL queue while other workers do the same.

## Decision

- Route functions are plain `def` functions. FastAPI runs them in a thread pool, so a slow query does not block other requests.
- The database layer uses synchronous SQLAlchemy 2 with the `psycopg` 3 driver and a `Session` per request, provided by the `get_session` dependency.
- Services are plain functions that take a `Session` and commit explicitly.
- The worker is a normal synchronous loop. Safe concurrent claiming comes from PostgreSQL itself, using `SELECT ... FOR UPDATE SKIP LOCKED`, not from asyncio.

## Consequences

- The code has no `async`/`await`, no event loop concerns and no mixing of sync and async database calls.
- Tests use the same synchronous code paths as production and run against a real PostgreSQL through Testcontainers.
- Throughput is limited by the thread pool and the connection pool size. That is enough for the scale of this project.
- Moving to async later would mean changing every service and route, so it should only happen if measurements show a need.
