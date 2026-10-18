# Hookline

Hookline is a webhook delivery service. Applications send events to its REST API, and Hookline delivers each event to every subscriber endpoint that wants it, with signed payloads, automatic retries with backoff, a dead-letter state, manual replay and a full delivery history.

Status: in development

## Why

Many products, such as Stripe, GitHub and Shopify, notify other systems by sending HTTP requests called webhooks. Doing this well is harder than it looks: receivers go down, requests time out, the same event must not be delivered twice by two workers, receivers must be able to check that a request really came from the sender, and developers need to see what happened to each delivery. Hookline handles these problems in one small, tested service.

## Planned features

- User accounts with `admin` and `member` roles
- Login with a short-lived JWT access token and a rotating, revocable refresh token
- API keys for producer applications
- Subscriber endpoints with event types and a signing secret
- Event intake with idempotency keys
- One delivery per matching endpoint for each event
- A worker process that claims deliveries from a PostgreSQL queue and retries failures with exponential backoff and jitter
- HMAC-SHA256 signatures on every delivery
- A dead-letter state after the maximum number of attempts, and manual retry
- Delivery history with every attempt
- Delivery statistics
- Per-API-key rate limiting on event intake
- Protection against server-side request forgery on subscriber URLs
- Health endpoints, Docker packaging and CI

## What exists now

- The `hookline` Python package with configuration loading from `HOOKLINE_` environment variables
- A FastAPI application with OpenAPI docs at `/docs`
- `GET /health/live`, which returns `{"status": "ok"}`
- `GET /health/ready`, which checks the database and returns `503` when it cannot be reached
- A PostgreSQL connection through SQLAlchemy, with Alembic migrations
- The database schema for users, refresh tokens, API keys, endpoints, events, deliveries and delivery attempts, with its constraints and indexes (described in [docs/database.md](docs/database.md))
- Login with a JWT access token and a rotating refresh token: `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh` and `POST /api/v1/auth/logout`, with reuse detection for refresh tokens
- `GET /api/v1/users/me`, which returns the logged-in user
- `admin` and `member` roles; admins create, list, promote, demote, deactivate and reactivate users with `POST /api/v1/users`, `GET /api/v1/users` and `PATCH /api/v1/users/{id}`
- API keys for producer applications: `POST /api/v1/api-keys` (the key is shown once), `GET /api/v1/api-keys` and `DELETE /api/v1/api-keys/{id}`, and a dependency that authenticates producer requests with the `X-API-Key` header
- Subscriber endpoints: `POST /api/v1/endpoints` (the signing secret is shown once), `GET /api/v1/endpoints`, `GET`, `PATCH` and `DELETE /api/v1/endpoints/{id}`, and `POST /api/v1/endpoints/{id}/rotate-secret`
- Checks on endpoint URLs against server-side request forgery: `https` only by default, no credentials or fragments, and no host that resolves to a private, loopback, link-local, multicast, reserved or unspecified address (described in [docs/security.md](docs/security.md))
- Event intake for producers: `POST /api/v1/events` with an API key stores the event and creates one pending delivery for each matching active endpoint in the same transaction; an optional `Idempotency-Key` header makes retries safe (`200` with `Idempotent-Replayed: true` for the same body, `409` for a different body)
- `GET /api/v1/events` (with `event_type`, `created_after` and `created_before` filters) and `GET /api/v1/events/{id}` with the event's payload and a summary of its deliveries
- A request body size limit (`413` for bodies over `HOOKLINE_MAX_BODY_BYTES`) and an event payload size limit (`HOOKLINE_MAX_PAYLOAD_BYTES`)
- Pagination with `limit` and `offset` on list routes
- HMAC-SHA256 signing of delivery bodies and a sender that signs and sends one delivery and classifies the result (success only for `2xx`, redirects not followed, timeouts and connection errors recorded as failures, the target URL checked again before sending)
- A delivery worker, `python -m hookline.worker`, that claims due deliveries from PostgreSQL with `FOR UPDATE SKIP LOCKED` and a lease, sends them, records every attempt, retries failures with exponential backoff and jitter, and marks a delivery `dead` after `HOOKLINE_MAX_ATTEMPTS` attempts; several workers can run at once, and the worker stops cleanly on Ctrl+C or `SIGTERM` (described in [docs/architecture.md](docs/architecture.md#delivery-worker))
- Delivery history and manual retry: `GET /api/v1/deliveries` (with `status`, `endpoint_id`, `event_id`, `created_after` and `created_before` filters), `GET /api/v1/deliveries/{id}` with every attempt, and `POST /api/v1/deliveries/{id}/retry`, which requeues a `failed` or `dead` delivery for a fresh run of attempts while keeping the old attempts as history
- A command to create the first admin user: `python -m hookline.cli create-admin --email ...`
- Error responses in RFC 9457 problem details format (`application/problem+json`), with validation errors returned as `400`
- A Docker Compose file that starts PostgreSQL 17 for local development
- Unit tests, integration tests against a real PostgreSQL started by Testcontainers (including tests for every check constraint, unique constraint and delete rule of the schema), and a CI workflow for formatting, linting, type checking and tests

## Tech stack

- Python 3.12
- FastAPI, Pydantic v2 and pydantic-settings
- bcrypt for passwords and PyJWT for access tokens
- httpx2 for outgoing HTTP requests
- uvicorn
- PostgreSQL 17, SQLAlchemy 2 with psycopg 3, Alembic
- pytest, pytest-cov, httpx2 `MockTransport` and Testcontainers for tests
- ruff and mypy for code quality
- Docker Compose for the local database
- GitHub Actions for CI

## Getting started

Requirements: Python 3.12 or newer, and Docker with Docker Compose v2.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
set -a
. ./.env
set +a
```

Replace `change-me` for `HOOKLINE_JWT_SECRET` in `.env` with a random value, for example the output of `python -c "import secrets; print(secrets.token_urlsafe(32))"`. The application does not start with a secret shorter than 32 characters.

Hookline reads its configuration from environment variables. The application does not read `.env` itself, so the commands above load it into the shell. Docker Compose reads `.env` on its own.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `HOOKLINE_DATABASE_URL` | yes | none | `postgresql+psycopg://...` URL of the database |
| `HOOKLINE_JWT_SECRET` | yes | none | Secret for signing access tokens, at least 32 characters |
| `HOOKLINE_ACCESS_TOKEN_MINUTES` | no | `15` | Lifetime of an access token |
| `HOOKLINE_REFRESH_TOKEN_DAYS` | no | `7` | Lifetime of a refresh token |
| `HOOKLINE_REQUIRE_HTTPS_TARGETS` | no | `true` | Endpoint URLs must use `https`; `false` also allows `http` |
| `HOOKLINE_ALLOW_PRIVATE_TARGETS` | no | `false` | `true` skips the private address checks on endpoint URLs; only for tests and local demos |
| `HOOKLINE_MAX_BODY_BYTES` | no | `262144` | Largest accepted request body in bytes; larger bodies get `413` |
| `HOOKLINE_MAX_PAYLOAD_BYTES` | no | `65536` | Largest accepted event payload in bytes, as compact JSON; larger payloads get `413` |
| `HOOKLINE_DELIVERY_TIMEOUT_SECONDS` | no | `10` | Timeout in seconds for each delivery request |
| `HOOKLINE_MAX_ATTEMPTS` | no | `8` | Attempts before a delivery becomes `dead` |
| `HOOKLINE_BACKOFF_BASE_SECONDS` | no | `10` | Delay before the second attempt, doubled for each later attempt (before jitter) |
| `HOOKLINE_BACKOFF_MAX_SECONDS` | no | `3600` | Longest delay between two attempts (before jitter) |
| `HOOKLINE_WORKER_BATCH_SIZE` | no | `10` | Deliveries a worker claims at once |
| `HOOKLINE_WORKER_POLL_SECONDS` | no | `2` | Seconds a worker waits when nothing is due |
| `HOOKLINE_WORKER_LEASE_SECONDS` | no | `60` | How long a claimed delivery stays reserved for one worker |
| `HOOKLINE_APP_NAME` | no | `Hookline` | Title shown in the API docs |
| `HOOKLINE_LOG_LEVEL` | no | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR` |

Start PostgreSQL, run the migrations, create the first admin and start the API:

```bash
docker compose up -d --wait postgres
alembic upgrade head
python -m hookline.cli create-admin --email admin@example.com
uvicorn hookline.main:app --reload
curl localhost:8000/health/ready
```

In a second shell with the same environment variables, start the worker that sends the deliveries:

```bash
python -m hookline.worker
```

`create-admin` asks for the password, or reads it from `HOOKLINE_ADMIN_PASSWORD`. Then log in and call an authenticated route:

```bash
curl -X POST localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email": "admin@example.com", "password": "your-password"}'
curl localhost:8000/api/v1/users/me -H 'Authorization: Bearer <access_token>'
curl -X POST localhost:8000/api/v1/api-keys \
  -H 'Authorization: Bearer <access_token>' \
  -H 'Content-Type: application/json' \
  -d '{"name": "local test"}'
curl -X POST localhost:8000/api/v1/events \
  -H 'X-API-Key: <api key>' \
  -H 'Idempotency-Key: order-42' \
  -H 'Content-Type: application/json' \
  -d '{"event_type": "order.created", "payload": {"order_id": 42}}'
```

All routes are described in [docs/api.md](docs/api.md).

The interactive API docs are at http://localhost:8000/docs.

## Verifying webhook signatures

Every delivery carries a `Hookline-Signature: t=<timestamp>,v1=<signature>` header. The signature is the hex HMAC-SHA256 of the timestamp, a dot and the raw request body, with the endpoint's signing secret as the key. A receiver checks it against the raw body bytes, before parsing the JSON, and rejects timestamps more than five minutes old:

```python
import hashlib
import hmac
import time


def verify_hookline_signature(secret: str, header: str, body: bytes, tolerance: int = 300) -> bool:
    values = {}
    for part in header.split(","):
        name, _, value = part.strip().partition("=")
        values[name] = value
    timestamp = values.get("t", "")
    signature = values.get("v1", "")
    if not timestamp.isdecimal() or not signature:
        return False
    if abs(time.time() - int(timestamp)) > tolerance:
        return False
    message = f"{timestamp}.".encode() + body
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), signature.encode())
```

Call it with the endpoint's secret, the `Hookline-Signature` header and the raw request body, and answer `401` when it returns `False`. Hookline delivers at least once, so the same event can arrive more than once; use the `Hookline-Event-Id` header to ignore events you have already processed. The full description is in [docs/security.md](docs/security.md#verifying-signatures) and [decision 0004](docs/decisions/0004-payload-signing.md).

## Running the checks

```bash
ruff format --check .
ruff check .
mypy src
pytest --cov --cov-report=term-missing
```

The integration tests start their own PostgreSQL container, so Docker must be running. See [docs/development.md](docs/development.md) for details and troubleshooting.

## Documentation

- [API](docs/api.md)
- [Architecture](docs/architecture.md)
- [Database](docs/database.md)
- [Development](docs/development.md)
- [Security](docs/security.md)
- [Decision records](docs/decisions/)

## License

MIT, see [LICENSE](LICENSE).
