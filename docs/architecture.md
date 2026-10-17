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
| `config.py` | `Settings` read from `HOOKLINE_` environment variables, and the `AppSettings` dependency |
| `clock.py` | The `get_now` dependency that gives the current time and can be replaced in tests |
| `cli.py` | Command-line tool with the `create-admin` command |
| `database.py` | Declarative `Base`, engine creation and the `get_session` dependency |
| `models.py` | Imports every model, so Alembic and the tests see all tables |
| `pagination.py` | The `PageParams` dependency for `limit` and `offset`, and the `Page[T]` response model |
| `auth/` | Password hashing, JWT access tokens, refresh tokens, login, refresh and logout, and the `get_current_user`, `require_admin` and `get_current_api_key` dependencies |
| `users/` | User and refresh token models, `GET /api/v1/users/me` and the admin user management routes |
| `api_keys/` | API key model, creating, listing and revoking keys, and checking a key sent by a producer |
| `endpoints/` | Endpoint model, creating, listing, updating and deleting endpoints, rotating signing secrets, and the URL safety checks in `url_safety.py` |
| `events/` | Event model, event intake with idempotency keys and delivery creation, and listing and reading events |
| `deliveries/` | Delivery and delivery attempt models, payload signing (`signing.py`) and the sender that sends one delivery and classifies the result (`sender.py`) |
| `body_limit.py` | ASGI middleware that rejects request bodies over `HOOKLINE_MAX_BODY_BYTES` with `413` |
| `errors.py` | Application exceptions and the problem details error handlers |
| `health/router.py` | Liveness and readiness endpoints |

Database migrations live in `migrations/` and are run with Alembic. The schema is described in [database.md](database.md).

Feature folders follow the same shape as they are added: SQLAlchemy models, Pydantic schemas, a service module with plain functions that take a database connection object, and a FastAPI router. Routers translate HTTP requests into service calls and contain no queries. There is no separate repository layer.

## Current state

The application factory, configuration, the database connection, Alembic migrations, problem details error handling and the health endpoints `GET /health/live` and `GET /health/ready` exist so far, together with the database schema and its SQLAlchemy models. Under `/api/v1`, login, refresh, logout, `GET /api/v1/users/me`, admin user management, API key management, endpoint management, event intake and reading events exist; they are listed in [api.md](api.md), and how passwords, tokens, roles, API keys, endpoint secrets and endpoint URLs are handled is described in [security.md](security.md). Event intake stores each event and its pending deliveries in one transaction, as described in [decision 0003](decisions/0003-event-intake-and-idempotency.md). The sender in `deliveries/sender.py` signs and sends a single delivery and returns the result without touching the database; signing is described in [decision 0004](decisions/0004-payload-signing.md). The worker that uses the sender and the other routes are added in later stages.

## Errors

Every error response uses RFC 9457 problem details with the media type `application/problem+json`:

```json
{"type": "about:blank", "title": "Invalid request", "status": 400, "detail": "One or more fields are invalid.", "errors": [{"field": "limit", "message": "Input should be a valid integer"}]}
```

`errors` is only present for validation failures. Unexpected exceptions are logged with their stack trace and returned as a generic `500`; their message never reaches the client.
