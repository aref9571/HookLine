# Development

This guide explains how to run Hookline and its tests on a development machine.

## Requirements

- Python 3.12 or newer
- Docker with Docker Compose v2, for the local PostgreSQL and for the integration tests

## Setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## Configuration and `.env`

Hookline reads its configuration from environment variables that start with `HOOKLINE_`. The application does not read `.env` files itself. The `.env` file is used by Docker Compose for the database credentials and can be loaded into your shell for the application.

```bash
cp .env.example .env
```

Change `POSTGRES_PASSWORD` in `.env` and use the same password in `HOOKLINE_DATABASE_URL`. `.env` is listed in `.gitignore` and must never be committed.

Load the variables into the current shell:

```bash
set -a
. ./.env
set +a
```

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `HOOKLINE_DATABASE_URL` | yes | none | SQLAlchemy URL, for example `postgresql+psycopg://hookline:change-me@127.0.0.1:5432/hookline` |
| `HOOKLINE_JWT_SECRET` | yes | none | Secret for signing access tokens, at least 32 characters |
| `HOOKLINE_ACCESS_TOKEN_MINUTES` | no | `15` | Lifetime of an access token in minutes |
| `HOOKLINE_REFRESH_TOKEN_DAYS` | no | `7` | Lifetime of a refresh token in days |
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
| `HOOKLINE_RATE_LIMIT_PER_MINUTE` | no | `120` | Event intake requests allowed per API key and minute; more get `429` |
| `HOOKLINE_APP_NAME` | no | `Hookline` | Title shown in the API docs |
| `HOOKLINE_LOG_LEVEL` | no | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | for Compose | none | Credentials of the local PostgreSQL container |

The application refuses to start if `HOOKLINE_DATABASE_URL` or `HOOKLINE_JWT_SECRET` is not set, or if the JWT secret is shorter than 32 characters. Alembic and the command-line tool read the same settings, so they need both variables too. Create a JWT secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

The tests set their own placeholder values and do not need these variables.

## Starting PostgreSQL

```bash
docker compose up -d --wait postgres
```

This starts PostgreSQL 17, reachable only from the local machine on `127.0.0.1:5432`. The data is kept in the named volume `postgres-data`. Stop it with `docker compose down`; add `-v` to delete the data as well.

## Running migrations

Alembic reads the database URL from `HOOKLINE_DATABASE_URL`, not from `alembic.ini`.

```bash
alembic upgrade head
alembic downgrade base
alembic check
```

New migrations use readable, numbered revision IDs:

```bash
alembic revision --autogenerate --rev-id 0002 -m "short description"
ruff format migrations
```

Autogenerate puts two comment lines around the generated operations. Delete them before committing, because the project keeps no comments in code.

## Creating the first admin

```bash
python -m hookline.cli create-admin --email admin@example.com
```

The command asks for the password twice without showing it. To run it without a prompt, set `HOOKLINE_ADMIN_PASSWORD` for that one command. The password must be 12 to 128 characters and at most 72 bytes in UTF-8. The command fails if a user with that email already exists.

## Running the API

```bash
uvicorn hookline.main:app --reload
curl localhost:8000/health/live
curl localhost:8000/health/ready
```

`/health/ready` returns `503` if the database cannot be reached. The API docs are at http://localhost:8000/docs.

## Running the worker

```bash
python -m hookline.worker
```

The worker sends pending deliveries and retries failed ones. It needs the same environment variables as the API. Stop it with Ctrl+C or `SIGTERM`; it finishes the delivery it is sending first. Several workers can run at the same time. For a local test against a receiver on your own machine, set `HOOKLINE_ALLOW_PRIVATE_TARGETS=true` and `HOOKLINE_REQUIRE_HTTPS_TARGETS=false` for both the API and the worker.

## Running the checks and tests

```bash
ruff format --check .
ruff check .
mypy src
pytest --cov --cov-report=term-missing
```

Integration tests are marked with `integration`. They start their own PostgreSQL 17 container with Testcontainers, run the migrations and empty the tables after each test, so they do not touch the Compose database. To run only one group:

```bash
pytest -m "not integration"
pytest -m integration
```

## Troubleshooting Docker

- `Cannot connect to the Docker daemon` or similar connection errors in the integration tests mean Docker is not running. Start Docker and run the tests again. The unit tests do not need Docker.
- `port is already allocated` when starting Compose means another PostgreSQL is using port 5432. Stop it, or change the host port in `docker-compose.yml` and in `HOOKLINE_DATABASE_URL`.
- `set POSTGRES_PASSWORD in .env` means the `.env` file is missing or incomplete. Copy `.env.example` to `.env`.
- If the first test run is slow, Docker is downloading the `postgres:17` image. Later runs reuse it.
