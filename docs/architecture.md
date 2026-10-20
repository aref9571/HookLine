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
| `main.py` | Application factory `create_app()` |
| `config.py` | `Settings` read from `HOOKLINE_` environment variables, the `AppSettings` dependency and the logging setup |
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
| `deliveries/` | Delivery and delivery attempt models, payload signing (`signing.py`), the sender that sends one delivery and classifies the result (`sender.py`) and the retry delay (`backoff.py`) |
| `worker/` | The delivery worker: claiming due deliveries (`claims.py`), the claim, send and record loop (`runner.py`) and the `python -m hookline.worker` entry point (`__main__.py`) |
| `body_limit.py` | ASGI middleware that rejects request bodies over `HOOKLINE_MAX_BODY_BYTES` with `413` |
| `security_headers.py` | ASGI middleware that adds `X-Content-Type-Options: nosniff` to every response and `Cache-Control: no-store` to `/api/v1/auth/*` responses |
| `request_logging.py` | ASGI middleware that logs one line per request with the method, path, status and duration |
| `errors.py` | Application exceptions and the problem details error handlers |
| `health/router.py` | Liveness and readiness endpoints |

Database migrations live in `migrations/` and are run with Alembic. The schema is described in [database.md](database.md).

Feature folders follow the same shape as they are added: SQLAlchemy models, Pydantic schemas, a service module with plain functions that take a database connection object, and a FastAPI router. Routers translate HTTP requests into service calls and contain no queries. There is no separate repository layer.

## Current state

The application factory, configuration, the database connection, Alembic migrations, problem details error handling and the health endpoints `GET /health/live` and `GET /health/ready` exist so far, together with the database schema and its SQLAlchemy models. Under `/api/v1`, login, refresh, logout, `GET /api/v1/users/me`, admin user management, API key management, endpoint management, event intake, reading events, the delivery history, manual retry and delivery statistics exist; they are listed in [api.md](api.md), and how passwords, tokens, roles, API keys, endpoint secrets and endpoint URLs are handled is described in [security.md](security.md). Event intake stores each event and its pending deliveries in one transaction, as described in [decision 0003](decisions/0003-event-intake-and-idempotency.md). The sender in `deliveries/sender.py` signs and sends a single delivery and returns the result without touching the database; signing is described in [decision 0004](decisions/0004-payload-signing.md). The delivery worker described below sends pending deliveries and retries failed ones. `GET /api/v1/stats` (`stats/service.py`) counts deliveries and events with `GROUP BY` and aggregate queries, and event intake is rate limited per API key with a fixed one-minute window stored in `rate_limit_windows`, as described in [decision 0006](decisions/0006-rate-limiting.md). Every request passes through three small ASGI middlewares: request logging (outermost, so it also sees requests that the inner middlewares reject), the security headers and the body size limit.

## Delivery worker

The worker is started with `python -m hookline.worker`. It reads the same settings as the API, opens one database engine and one HTTP client, and repeats a claim, send and record cycle until it is stopped:

1. **Claim.** In one short transaction, `claim_due_deliveries` in `worker/claims.py` selects up to `HOOKLINE_WORKER_BATCH_SIZE` due deliveries with `FOR UPDATE SKIP LOCKED`, sets them to `in_progress` with a lease until `now + HOOKLINE_WORKER_LEASE_SECONDS`, and commits. A delivery is due when it is `pending` or `failed` and `next_attempt_at` has passed, or when it is `in_progress` and its lease has run out because a worker crashed. Deliveries whose endpoint has been deactivated are set to `dead` with the error `endpoint disabled` instead. The claim returns plain data: the URL, the secret, the event and the attempt number to use (the highest recorded attempt number plus one).
2. **Send.** For each claimed delivery, `process_claimed` in `worker/runner.py` calls the sender. No database transaction is open while the HTTP request runs.
3. **Record.** In a new short transaction it updates the delivery and inserts a `delivery_attempts` row: `succeeded` on a `2xx` answer; `failed` with `next_attempt_at = now + backoff` while attempts are left; `dead` once `attempt_count` reaches `HOOKLINE_MAX_ATTEMPTS`. `attempt_count` goes up by one each time and the lease is cleared. The update only applies if the delivery is still `in_progress` with the lease this worker set; otherwise the result is discarded and a warning is logged, so a worker whose lease expired cannot overwrite a newer result.

At the start of a cycle, and at most once a minute, the worker also deletes rate limit windows older than one hour with one `DELETE` (`clean_up_if_due` in `worker/runner.py`).

When a claim finds nothing, the worker waits `HOOKLINE_WORKER_POLL_SECONDS` seconds before the next one. If the database cannot be reached during a cycle (SQLAlchemy raises `OperationalError`), the worker logs a warning without the error text, waits the same poll interval and tries again, so a short database outage does not stop it. A delivery whose result could not be recorded stays `in_progress` until its lease runs out and is then sent again, which the at-least-once guarantee already allows. `SIGTERM` and `SIGINT` (Ctrl+C) set a stop flag: the worker finishes the delivery it is sending and exits; the rest of its batch stays leased and is picked up by another worker when the lease runs out.

The retry delay comes from `next_delay_seconds` in `deliveries/backoff.py`: `min(HOOKLINE_BACKOFF_MAX_SECONDS, HOOKLINE_BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))`, multiplied by a random factor between 0.5 and 1.0 so that many failed deliveries do not all come back at the same moment. With the defaults the full delays are 10, 20, 40, 80, 160, 320 and 640 seconds before the eighth and last attempt. `attempt` here is the number of attempts in the current run, `attempt_count + 1`.

A user can requeue a `failed` or `dead` delivery with `POST /api/v1/deliveries/{id}/retry` (`deliveries/service.py`). It resets the delivery to `pending` with `attempt_count = 0`, so the worker gives it a fresh run of up to `HOOKLINE_MAX_ATTEMPTS` attempts with the backoff starting again from the base delay. The old attempt rows stay, and the attempt number keeps counting up from the highest recorded one, so the history is never overwritten and the unique `(delivery_id, attempt_number)` constraint is never hit. `attempt_count` decides when the delivery is `dead`; the attempt number only names the attempt.

Each attempt is logged in one line with the delivery ID, the attempt number, the outcome, the status code and the duration. Payloads, secrets and URLs are not logged. Why the queue is in PostgreSQL, how leases work and why delivery is at least once is explained in [decision 0005](decisions/0005-postgres-job-queue.md).

## Errors

Every error response uses RFC 9457 problem details with the media type `application/problem+json`:

```json
{"type": "about:blank", "title": "Invalid request", "status": 400, "detail": "One or more fields are invalid.", "errors": [{"field": "limit", "message": "Input should be a valid integer"}]}
```

`errors` is only present for validation failures. Unexpected exceptions are logged with their stack trace and returned as a generic `500`; their message never reaches the client.
