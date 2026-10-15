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
- The database schema for users, refresh tokens, API keys, endpoints, events, deliveries and delivery attempts, with its constraints and indexes (described in [docs/database.md](docs/database.md)); users, refresh tokens and API keys are used by the API so far
- Login with a JWT access token and a rotating refresh token: `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh` and `POST /api/v1/auth/logout`, with reuse detection for refresh tokens
- `GET /api/v1/users/me`, which returns the logged-in user
- `admin` and `member` roles; admins create, list, promote, demote, deactivate and reactivate users with `POST /api/v1/users`, `GET /api/v1/users` and `PATCH /api/v1/users/{id}`
- API keys for producer applications: `POST /api/v1/api-keys` (the key is shown once), `GET /api/v1/api-keys` and `DELETE /api/v1/api-keys/{id}`, and a dependency that authenticates requests with the `X-API-Key` header (used by event intake later)
- Pagination with `limit` and `offset` on list routes
- A command to create the first admin user: `python -m hookline.cli create-admin --email ...`
- Error responses in RFC 9457 problem details format (`application/problem+json`), with validation errors returned as `400`
- A Docker Compose file that starts PostgreSQL 17 for local development
- Unit tests, integration tests against a real PostgreSQL started by Testcontainers (including tests for every check constraint, unique constraint and delete rule of the schema), and a CI workflow for formatting, linting, type checking and tests

## Tech stack

- Python 3.12
- FastAPI, Pydantic v2 and pydantic-settings
- bcrypt for passwords and PyJWT for access tokens
- uvicorn
- PostgreSQL 17, SQLAlchemy 2 with psycopg 3, Alembic
- pytest, pytest-cov, httpx2 and Testcontainers for tests
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
```

All routes are described in [docs/api.md](docs/api.md).

The interactive API docs are at http://localhost:8000/docs.

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
