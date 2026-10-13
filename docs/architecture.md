# Architecture

## Purpose

Hookline receives events from producer applications over a REST API and delivers each event to every subscriber endpoint that has asked for that event type. Deliveries are signed, retried with backoff when they fail, and recorded so that every attempt can be inspected later.

## Two processes, one codebase

Hookline is a modular monolith. It runs as two processes that share one codebase and one PostgreSQL database.

```
 Producer app -- POST /api/v1/events (X-API-Key) --> +--------------+
 Admin/member -- /api/v1/* (JWT) ------------------> | hookline API | --> PostgreSQL <--+
                                                     |  (uvicorn)   |                   |
                                                     +--------------+                   |
                                                     +--------------+  claim (SKIP LOCKED)
                                                     |   hookline   | ------------------+
                                                     |    worker    | --> HTTPS POST, signed --> Subscriber endpoint
                                                     +--------------+
```

- The API never sends webhooks. It stores events and creates delivery rows in the same transaction.
- The worker never accepts HTTP requests. It claims due deliveries, sends them and records each attempt.
- Several workers can run at the same time, because each delivery is claimed with `FOR UPDATE SKIP LOCKED`.

Keeping the two jobs in separate processes means a slow or unreachable subscriber never blocks the API, and the number of workers can be changed without touching the API.

## Package layout

The code lives in `src/hookline/`. Each feature has its own folder.

| Module | Responsibility |
|---|---|
| `main.py` | Application factory `create_app()` and logging setup |
| `config.py` | `Settings` read from `HOOKLINE_` environment variables |
| `health/router.py` | Health endpoints |

Feature folders follow the same shape as they are added: SQLAlchemy models, Pydantic schemas, a service module with plain functions that take a database connection object, and a FastAPI router. Routers translate HTTP requests into service calls and contain no queries. There is no separate repository layer.

## Current state

Only the application factory, configuration and the liveness endpoint `GET /health/live` exist so far. The database, the worker and the API under `/api/v1` are added in later stages.
