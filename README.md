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
- A PostgreSQL connection through SQLAlchemy, with Alembic migrations (the first one enables the `pgcrypto` extension; there are no application tables yet)
- Error responses in RFC 9457 problem details format (`application/problem+json`), with validation errors returned as `400`
- A Docker Compose file that starts PostgreSQL 17 for local development
- Unit tests, integration tests against a real PostgreSQL started by Testcontainers, and a CI workflow for formatting, linting, type checking and tests

## Tech stack

- Python 3.12
- FastAPI, Pydantic v2 and pydantic-settings
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

Hookline reads its configuration from environment variables. The application does not read `.env` itself, so the commands above load it into the shell. Docker Compose reads `.env` on its own.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `HOOKLINE_DATABASE_URL` | yes | none | `postgresql+psycopg://...` URL of the database |
| `HOOKLINE_APP_NAME` | no | `Hookline` | Title shown in the API docs |
| `HOOKLINE_LOG_LEVEL` | no | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR` |

Start PostgreSQL, run the migrations and start the API:

```bash
docker compose up -d --wait postgres
alembic upgrade head
uvicorn hookline.main:app --reload
curl localhost:8000/health/ready
```

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

- [Architecture](docs/architecture.md)
- [Development](docs/development.md)
- [Decision records](docs/decisions/)

## License

MIT, see [LICENSE](LICENSE).
