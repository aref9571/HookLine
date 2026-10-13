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
- Unit tests and a CI workflow for formatting, linting, type checking and tests

## Tech stack

- Python 3.12
- FastAPI, Pydantic v2 and pydantic-settings
- uvicorn
- pytest, pytest-cov and httpx for tests
- ruff and mypy for code quality
- GitHub Actions for CI

PostgreSQL, SQLAlchemy, Alembic and Docker are part of the planned stack and are added in later stages.

## Getting started

Requirements: Python 3.12 or newer.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

Copy `.env.example` to `.env` if you want to change the defaults, or set the variables in your shell.

| Variable | Default | Purpose |
|---|---|---|
| `HOOKLINE_APP_NAME` | `Hookline` | Title shown in the API docs |
| `HOOKLINE_LOG_LEVEL` | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR` |

Run the API:

```bash
uvicorn hookline.main:app --reload
curl localhost:8000/health/live
```

The interactive API docs are at http://localhost:8000/docs.

## Running the checks

```bash
ruff format --check .
ruff check .
mypy src
pytest --cov --cov-report=term-missing
```

## Documentation

- [Architecture](docs/architecture.md)
- [Decision records](docs/decisions/)

## License

MIT, see [LICENSE](LICENSE).
